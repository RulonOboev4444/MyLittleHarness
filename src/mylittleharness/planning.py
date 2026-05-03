from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .atomic_files import AtomicFileWrite, FileTransactionError, apply_file_transaction
from .inventory import Inventory
from .lifecycle_focus import sync_current_focus_block
from .models import Finding
from .roadmap import (
    RoadmapPlan,
    RoadmapSliceContract,
    RoadmapSynthesisReport,
    make_roadmap_request,
    roadmap_item_fields,
    roadmap_plans_for_requests,
    roadmap_slice_contract_for_item,
    roadmap_synthesis_report_for_item,
)
from .writeback import state_compaction_apply_findings, state_compaction_dry_run_findings


DEFAULT_PLAN_REL = "project/implementation-plan.md"
DEFAULT_ACTIVE_PHASE = "phase-1-implementation"
DEFAULT_PHASE_STATUS = "pending"
DEFAULT_DOCS_DECISION = "uncertain"
DEFAULT_EXECUTION_POLICY = "current-phase-only"
DEFAULT_CLOSEOUT_BOUNDARY = "explicit-closeout-required"
DEFAULT_AUTO_CONTINUE = False
DEFAULT_STOP_CONDITIONS = (
    "auto_continue is absent, false, malformed, or not attached to the current active phase/plan contract",
    "expected verification failed, was skipped without rationale, or lacks a deterministic success signal",
    "docs, API, lifecycle authority, root classification, or write-scope impact is uncertain",
    "the next phase would edit outside the current write scope or cross into a different execution slice",
    "source reality invalidates a future phase contract, discovers a new dependency/schema shape, or needs destructive/sensitive action",
    "the last implementation phase is complete; the next state is explicit closeout preparation, not archive or next-slice opening",
)


@dataclass(frozen=True)
class PlanRequest:
    title: str
    objective: str
    task: str
    update_active: bool = False
    roadmap_item: str = ""
    only_requested_item: bool = False


def make_plan_request(
    title: str | None,
    objective: str | None,
    task: str | None,
    update_active: bool = False,
    roadmap_item: str | None = None,
    only_requested_item: bool = False,
) -> PlanRequest:
    return PlanRequest(
        title=_normalized_text(title),
        objective=_normalized_note(objective),
        task=_normalized_note(task),
        update_active=update_active,
        roadmap_item=_normalized_item_id(roadmap_item),
        only_requested_item=only_requested_item,
    )


def render_implementation_plan(
    request: PlanRequest,
    *,
    today: date | None = None,
    source_incubation: str = "",
    slice_contract: RoadmapSliceContract | None = None,
    synthesis_report: RoadmapSynthesisReport | None = None,
) -> str:
    current_date = (today or date.today()).isoformat()
    title = request.title or "Implementation Plan"
    objective = request.objective or "Define and verify the requested implementation work."
    plan_id = f"{current_date}-{_safe_slug(title) or 'implementation-plan'}"
    relationship_frontmatter = _slice_frontmatter(request, slice_contract, source_incubation)
    task_section = ""
    if request.task:
        task_section = f"\n## Explicit Task Input\n\n{request.task.rstrip()}\n"
    slice_section = _slice_contract_section(slice_contract)
    synthesis_section = _plan_synthesis_section(synthesis_report)
    roadmap_authority_input = "- `project/roadmap.md`\n" if request.roadmap_item else ""

    return (
        "---\n"
        f'plan_id: "{_yaml_double_quoted_value(plan_id)}"\n'
        f'title: "{_yaml_double_quoted_value(title)}"\n'
        'status: "pending"\n'
        f'active_phase: "{DEFAULT_ACTIVE_PHASE}"\n'
        f'phase_status: "{DEFAULT_PHASE_STATUS}"\n'
        f'docs_decision: "{DEFAULT_DOCS_DECISION}"\n'
        f"{_execution_policy_frontmatter(slice_contract)}"
        f"{relationship_frontmatter}"
        f'created: "{current_date}"\n'
        f'updated: "{current_date}"\n'
        "---\n"
        f"# {title}\n\n"
        "## Objective\n\n"
        f"{objective.rstrip()}\n"
        f"{task_section}"
        f"{slice_section}"
        f"{synthesis_section}"
        "\n## Authority Inputs\n\n"
        "- `AGENTS.md`\n"
        "- `.codex/project-workflow.toml`\n"
        "- `project/project-state.md`\n"
        f"{roadmap_authority_input}"
        "- `project/specs/workflow/workflow-plan-synthesis-spec.md`\n"
        "- `project/specs/workflow/workflow-rollout-slices-spec.md`\n"
        "- `project/specs/workflow/workflow-verification-and-closeout-spec.md`\n"
        "- Explicit task input supplied to `mylittleharness plan`\n"
        "\n## Non-goals\n\n"
        "- No hidden memory, background planner, external service, model call, or dependency install.\n"
        "- No autonomous repair, archive, closeout, commit, rollback, or lifecycle approval.\n"
        "- No broad refactor outside the accepted write scope for this plan.\n"
        "\n## Invariants\n\n"
        "- Repo-visible files remain authority; command output is advisory until written.\n"
        "- Recovery stays non-destructive and reviewable.\n"
        "- Product-source fixtures and archive roots are not live operating memory.\n"
        "- Docs decision must be recorded as `updated`, `not-needed`, or `uncertain` before confident closeout.\n"
        "\n## Execution Policy\n\n"
        f"- execution_policy: `{slice_contract.execution_policy if slice_contract and slice_contract.execution_policy else DEFAULT_EXECUTION_POLICY}`\n"
        f"- auto_continue: `{str(DEFAULT_AUTO_CONTINUE).lower()}`\n"
        f"- default continuation: execute only `{DEFAULT_ACTIVE_PHASE}`, record repo-visible evidence/state, then stop.\n"
        f"{_stop_conditions_body()}"
        "\n## File Ownership\n\n"
        "- Write scope: declare exact files before editing them.\n"
        "- Read context: inspect adjacent source, tests, docs, and workflow authority before widening scope.\n"
        "- Off-limits: generated caches, workstation state, package artifacts, and unrelated user changes.\n"
        "\n## Phases\n\n"
        f"### {DEFAULT_ACTIVE_PHASE}\n\n"
        f"- status: `{DEFAULT_PHASE_STATUS}`\n"
        "- objective: implement the requested change inside the declared write scope.\n"
        "- preconditions: operating-root `check` is clean enough for the work; existing dirty files are preserved.\n"
        "- write scope: update this section with exact target files before mutation.\n"
        "- read context: use repo-visible authority and relevant local tests/docs.\n"
        "- invariants: keep MLH target-repository boundaries and explicit apply/dry-run semantics intact.\n"
        "- implementation contract: deliver the requested behavior without adding hidden runtime state.\n"
        "- verification gates: run targeted tests first, then broader checks appropriate to the changed surface.\n"
        "- docs decision: keep `docs_decision` as `uncertain` until docs impact is proven.\n"
        "- state transfer: record changed contracts, verification evidence, residual risk, and carry-forward.\n"
        "- refusal or escalation: stop before unsafe roots, destructive recovery, hidden infrastructure, or unclear ownership.\n"
        "\n## Verification Strategy\n\n"
        "- Run the narrowest deterministic tests that cover changed behavior.\n"
        "- Run `mylittleharness --root <this-repo> check` before confident closeout.\n"
        "- Treat failed verification as a blocker or residual risk, not as permission to widen scope silently.\n"
        "\n## Docs Decision\n\n"
        f"- docs_decision: {DEFAULT_DOCS_DECISION}\n"
        "- Record `updated`, `not-needed`, or `uncertain` with evidence before closeout.\n"
        "\n## State Transfer\n\n"
        "- Update `project/project-state.md` lifecycle fields through an explicit writeback path or equivalent scoped mutation.\n"
        "- Keep active-plan copies as derived execution metadata; project-state remains lifecycle authority.\n"
        "\n## Refusal Conditions\n\n"
        "- Refuse unsafe roots, malformed authority files, active-plan conflicts, path escapes, symlink targets, or ambiguous lifecycle state.\n"
        "- Refuse task input that asks for destructive VCS recovery, broad restoration, or cleanup outside the declared scope.\n"
        "\n## Closeout Checklist\n\n"
        "- worktree_start_state: record clean/dirty starting posture and preserve unrelated changes.\n"
        "- task_scope: summarize the completed product or workflow behavior.\n"
        "- docs_decision: record `updated`, `not-needed`, or `uncertain`.\n"
        "- state_writeback: describe lifecycle/state updates performed.\n"
        "- verification: list commands run and observed outcomes.\n"
        "- commit_decision: follow the repository policy.\n"
        "- residual_risk: record known gaps.\n"
        "- carry_forward: record bounded follow-up items.\n"
        "\n## Decision Log\n\n"
        f"- {current_date}: Created deterministic implementation-plan scaffold with `mylittleharness plan`.\n"
    )


def _slice_frontmatter(
    request: PlanRequest,
    slice_contract: RoadmapSliceContract | None,
    source_incubation: str,
) -> str:
    lines: list[str] = []
    if slice_contract:
        if slice_contract.execution_slice:
            lines.append(f'execution_slice: "{_yaml_double_quoted_value(slice_contract.execution_slice)}"\n')
        lines.append(f'primary_roadmap_item: "{_yaml_double_quoted_value(slice_contract.primary_roadmap_item)}"\n')
        lines.append(_yaml_frontmatter_list("covered_roadmap_items", slice_contract.covered_roadmap_items))
        lines.append(f'domain_context: "{_yaml_double_quoted_value(slice_contract.domain_context)}"\n')
        lines.append(_yaml_frontmatter_list("target_artifacts", slice_contract.target_artifacts))
        lines.append(f'related_roadmap_item: "{_yaml_double_quoted_value(slice_contract.primary_roadmap_item)}"\n')
        if slice_contract.source_incubation:
            lines.append(f'source_incubation: "{_yaml_double_quoted_value(slice_contract.source_incubation)}"\n')
        if slice_contract.source_research:
            lines.append(f'source_research: "{_yaml_double_quoted_value(slice_contract.source_research)}"\n')
        if slice_contract.related_specs:
            lines.append(_yaml_frontmatter_list("related_specs", slice_contract.related_specs))
    else:
        if request.roadmap_item:
            lines.append(f'related_roadmap_item: "{_yaml_double_quoted_value(request.roadmap_item)}"\n')
        if source_incubation:
            lines.append(f'source_incubation: "{_yaml_double_quoted_value(source_incubation)}"\n')
    return "".join(lines)


def _execution_policy_frontmatter(slice_contract: RoadmapSliceContract | None) -> str:
    policy = slice_contract.execution_policy if slice_contract and slice_contract.execution_policy else DEFAULT_EXECUTION_POLICY
    closeout_boundary = slice_contract.closeout_boundary if slice_contract and slice_contract.closeout_boundary else DEFAULT_CLOSEOUT_BOUNDARY
    return (
        f'execution_policy: "{_yaml_double_quoted_value(policy)}"\n'
        f"auto_continue: {str(DEFAULT_AUTO_CONTINUE).lower()}\n"
        f"{_yaml_frontmatter_list('stop_conditions', DEFAULT_STOP_CONDITIONS)}"
        f'closeout_boundary: "{_yaml_double_quoted_value(closeout_boundary)}"\n'
    )


def _stop_conditions_body() -> str:
    return "".join(f"- stop_condition: {condition}.\n" for condition in DEFAULT_STOP_CONDITIONS)


def _slice_contract_section(slice_contract: RoadmapSliceContract | None) -> str:
    if slice_contract is None:
        return ""
    covered = ", ".join(f"`{item}`" for item in slice_contract.covered_roadmap_items) or "`<none>`"
    artifacts = ", ".join(f"`{item}`" for item in slice_contract.target_artifacts) or "`[]`"
    return (
        "\n## Slice Contract\n\n"
        f"- primary_roadmap_item: `{slice_contract.primary_roadmap_item}`\n"
        f"- covered_roadmap_items: {covered}\n"
        f"- execution_slice: `{slice_contract.execution_slice or '<none>'}`\n"
        f"- domain_context: `{slice_contract.domain_context}`\n"
        f"- target_artifacts: {artifacts}\n"
        f"- execution_policy: `{slice_contract.execution_policy}`\n"
        f"- closeout_boundary: `{slice_contract.closeout_boundary}`\n"
    )


def _plan_synthesis_section(report: RoadmapSynthesisReport | None) -> str:
    if report is None:
        return ""
    covered = ", ".join(f"`{item}`" for item in report.covered_roadmap_items) or "`<none>`"
    bundle = "\n".join(f"- {signal}" for signal in report.bundle_signals)
    split = "\n".join(f"- {signal}" for signal in report.split_signals)
    return (
        "\n## Plan Synthesis Notes\n\n"
        f"- covered_roadmap_items: {covered}\n"
        f"- target_artifact_pressure: {report.target_artifact_pressure}\n"
        f"- phase_pressure: {report.phase_pressure}\n"
        "\n### Bundle Rationale\n\n"
        f"{bundle}\n"
        "\n### Split Boundary\n\n"
        f"{split}\n"
        "\nPlan synthesis notes are advisory sizing evidence only; they cannot approve repair, closeout, archive, commit, rollback, lifecycle decisions, or next-slice movement.\n"
    )


def plan_dry_run_findings(inventory: Inventory, request: PlanRequest) -> list[Finding]:
    findings = [
        Finding("info", "plan-dry-run", "plan proposal only; no files were written"),
        _root_posture_finding(inventory),
    ]
    errors = _plan_preflight_errors(inventory, request)
    roadmap_plans, roadmap_errors = _plan_roadmap_plans(inventory, request)
    errors.extend(roadmap_errors)
    findings.append(Finding("info", "plan-target", f"would write active plan: {DEFAULT_PLAN_REL}", DEFAULT_PLAN_REL))
    findings.append(
        Finding(
            "info",
            "plan-lifecycle",
            "would update project-state lifecycle frontmatter and Current Focus managed block: operating_mode, plan_status, active_plan, active_phase, phase_status",
            inventory.state.rel_path if inventory.state else "project/project-state.md",
        )
    )
    if roadmap_plans:
        findings.extend(_plan_roadmap_findings(roadmap_plans, apply=False))
        slice_contract = _plan_slice_contract(inventory, request)
        if slice_contract:
            findings.extend(_plan_slice_contract_findings(slice_contract, apply=False))
        if request.only_requested_item:
            findings.append(_plan_only_requested_item_finding(request, apply=False))
        synthesis_report = _plan_synthesis_report(inventory, request, slice_contract)
        if synthesis_report:
            findings.extend(_plan_synthesis_findings(synthesis_report, apply=False))
    if errors:
        findings.extend(_with_severity(errors, "warn"))
        findings.append(Finding("info", "plan-validation-posture", "dry-run refused before apply; fix refusal reasons, then rerun dry-run before writing a plan"))
        return findings
    findings.extend(_boundary_findings())
    findings.append(Finding("info", "plan-docs-decision", f"generated plan frontmatter starts with docs_decision={DEFAULT_DOCS_DECISION!r}", DEFAULT_PLAN_REL))
    findings.append(
        Finding(
            "info",
            "plan-execution-policy",
            "generated plan defaults to current-phase-only execution with auto_continue=false and repo-visible stop_conditions",
            DEFAULT_PLAN_REL,
        )
    )
    if inventory.state:
        lifecycle = {
            "operating_mode": "plan",
            "plan_status": "active",
            "active_plan": DEFAULT_PLAN_REL,
            "active_phase": DEFAULT_ACTIVE_PHASE,
            "phase_status": DEFAULT_PHASE_STATUS,
        }
        projected_state_text = sync_current_focus_block(_update_frontmatter_scalars(inventory.state.content, lifecycle))
        findings.extend(state_compaction_dry_run_findings(inventory, projected_state_text))
    findings.append(Finding("info", "plan-validation-posture", "apply would write only the active plan, project-state lifecycle frontmatter, and safe state-history compaction in an eligible live operating root"))
    return findings


def plan_apply_findings(inventory: Inventory, request: PlanRequest) -> list[Finding]:
    errors = _plan_preflight_errors(inventory, request)
    roadmap_plans, roadmap_errors = _plan_roadmap_plans(inventory, request)
    errors.extend(roadmap_errors)
    if errors:
        return errors

    state = inventory.state
    assert state is not None
    plan_path = inventory.root / DEFAULT_PLAN_REL
    source_incubation = _roadmap_source_incubation(inventory, request.roadmap_item)
    slice_contract = _plan_slice_contract(inventory, request)
    synthesis_report = _plan_synthesis_report(inventory, request, slice_contract)
    plan_text = render_implementation_plan(
        request,
        source_incubation=source_incubation,
        slice_contract=slice_contract,
        synthesis_report=synthesis_report,
    )
    lifecycle = {
        "operating_mode": "plan",
        "plan_status": "active",
        "active_plan": DEFAULT_PLAN_REL,
        "active_phase": DEFAULT_ACTIVE_PHASE,
        "phase_status": DEFAULT_PHASE_STATUS,
    }
    state_text = sync_current_focus_block(_update_frontmatter_scalars(state.content, lifecycle))
    plan_tmp = plan_path.with_name(f".{plan_path.name}.plan.tmp")
    state_tmp = state.path.with_name(f".{state.path.name}.plan.tmp")
    plan_backup = plan_path.with_name(f".{plan_path.name}.plan.backup")
    state_backup = state.path.with_name(f".{state.path.name}.plan.backup")
    roadmap_target_path = roadmap_plans[-1].target_path if roadmap_plans else None
    roadmap_tmp = (
        roadmap_target_path.with_name(f".{roadmap_target_path.name}.plan.tmp")
        if roadmap_target_path and _plan_roadmap_has_changes(roadmap_plans)
        else None
    )
    roadmap_backup = roadmap_target_path.with_name(f".{roadmap_target_path.name}.plan.backup") if roadmap_target_path else None
    for candidate, label in (
        (plan_tmp, "temporary plan write path"),
        (state_tmp, "temporary state write path"),
        (plan_backup, "temporary plan backup path"),
        (state_backup, "temporary state backup path"),
        (roadmap_tmp, "temporary roadmap write path"),
        (roadmap_backup if roadmap_tmp else None, "temporary roadmap backup path"),
    ):
        if candidate and candidate.exists():
            return [Finding("error", "plan-refused", f"{label} already exists: {candidate.relative_to(inventory.root).as_posix()}")]

    existed = plan_path.exists()
    operations: list[AtomicFileWrite] = [
        AtomicFileWrite(plan_path, plan_tmp, plan_text, plan_backup),
        AtomicFileWrite(state.path, state_tmp, state_text, state_backup),
    ]
    if roadmap_tmp and roadmap_target_path and roadmap_backup and roadmap_plans:
        operations.append(AtomicFileWrite(roadmap_target_path, roadmap_tmp, roadmap_plans[-1].updated_text, roadmap_backup))
    try:
        cleanup_warnings = apply_file_transaction(operations)
    except FileTransactionError as exc:
        return [Finding("error", "plan-refused", f"plan apply failed before all target writes completed: {exc}", DEFAULT_PLAN_REL)]

    action = "updated existing active plan" if existed else "created active plan"
    findings = [
        Finding("info", "plan-apply", "plan apply started"),
        _root_posture_finding(inventory),
        Finding("info", "plan-written", action, DEFAULT_PLAN_REL),
        Finding("info", "plan-lifecycle-updated", "updated project-state lifecycle frontmatter: operating_mode, plan_status, active_plan, active_phase, phase_status", state.rel_path),
        Finding("info", "plan-current-focus-updated", "updated project-state Current Focus managed block from lifecycle frontmatter", state.rel_path),
        Finding("info", "plan-docs-decision", f"generated plan frontmatter starts with docs_decision={DEFAULT_DOCS_DECISION!r}", DEFAULT_PLAN_REL),
        Finding(
            "info",
            "plan-execution-policy",
            "generated plan defaults to current-phase-only execution with auto_continue=false and repo-visible stop_conditions",
            DEFAULT_PLAN_REL,
        ),
        *_boundary_findings(),
        Finding("info", "plan-validation-posture", "run check after apply to verify lifecycle state, active-plan validation, and compact operating memory posture"),
    ]
    if roadmap_plans:
        findings.extend(_plan_roadmap_findings(roadmap_plans, apply=True))
    if slice_contract:
        findings.extend(_plan_slice_contract_findings(slice_contract, apply=True))
    if request.only_requested_item:
        findings.append(_plan_only_requested_item_finding(request, apply=True))
    if synthesis_report:
        findings.extend(_plan_synthesis_findings(synthesis_report, apply=True))
    if request.roadmap_item:
        findings.append(
            Finding(
                "info",
                "plan-relationship-frontmatter",
                "active plan frontmatter records related_roadmap_item, source_incubation, and slice metadata when the roadmap item provides it",
                DEFAULT_PLAN_REL,
            )
        )
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "plan-backup-cleanup", warning, DEFAULT_PLAN_REL))
    findings.extend(state_compaction_apply_findings(inventory, state.path.read_text(encoding="utf-8")))
    return findings


def _plan_preflight_errors(inventory: Inventory, request: PlanRequest) -> list[Finding]:
    errors: list[Finding] = []
    if not request.title:
        errors.append(Finding("error", "plan-refused", "--title is required and cannot be empty or whitespace-only"))
    if not request.objective:
        errors.append(Finding("error", "plan-refused", "--objective is required and cannot be empty or whitespace-only"))
    dangerous = _dangerous_input_reason(" ".join(part for part in (request.title, request.objective, request.task) if part))
    if dangerous:
        errors.append(Finding("error", "plan-refused", dangerous))
    if request.only_requested_item and not request.roadmap_item:
        errors.append(Finding("error", "plan-refused", "--only-requested-item requires --roadmap-item"))

    if inventory.root_kind == "product_source_fixture":
        errors.append(Finding("error", "plan-refused", "target is a product-source compatibility fixture; plan --apply is refused", DEFAULT_PLAN_REL))
    elif inventory.root_kind == "fallback_or_archive":
        errors.append(Finding("error", "plan-refused", "target is fallback/archive or generated-output evidence; plan --apply is refused", DEFAULT_PLAN_REL))
    elif inventory.root_kind != "live_operating_root":
        errors.append(Finding("error", "plan-refused", f"target root kind is {inventory.root_kind}; plan requires a live operating root"))

    manifest_plan = str(inventory.manifest.get("memory", {}).get("plan_file", DEFAULT_PLAN_REL)) if isinstance(inventory.manifest, dict) else DEFAULT_PLAN_REL
    if _normalize_rel(manifest_plan) != DEFAULT_PLAN_REL:
        errors.append(Finding("error", "plan-refused", f"non-default manifest plan_file is refused for plan apply: {manifest_plan}", inventory.manifest_surface.rel_path if inventory.manifest_surface else None))

    state = inventory.state
    if state is None or not state.exists:
        errors.append(Finding("error", "plan-refused", "project-state.md is missing", "project/project-state.md"))
    elif not state.frontmatter.has_frontmatter:
        errors.append(Finding("error", "plan-refused", "project-state.md frontmatter is required for plan apply", state.rel_path))
    elif state.frontmatter.errors:
        errors.append(Finding("error", "plan-refused", "project-state.md frontmatter is malformed", state.rel_path))
    elif not state.path.is_file():
        errors.append(Finding("error", "plan-refused", "project-state.md is not a regular file", state.rel_path))
    elif state.path.is_symlink():
        errors.append(Finding("error", "plan-refused", "project-state.md is a symlink", state.rel_path))

    plan_path = inventory.root / DEFAULT_PLAN_REL
    if _path_escapes_root(inventory.root, plan_path):
        errors.append(Finding("error", "plan-refused", "active plan path escapes the target root", DEFAULT_PLAN_REL))
    for parent in _parents_between(inventory.root, plan_path.parent):
        rel = parent.relative_to(inventory.root).as_posix()
        if parent.exists() and parent.is_symlink():
            errors.append(Finding("error", "plan-refused", f"active plan directory contains a symlink segment: {rel}", rel))
        elif parent.exists() and not parent.is_dir():
            errors.append(Finding("error", "plan-refused", f"active plan directory contains a non-directory segment: {rel}", rel))
    if plan_path.exists():
        if plan_path.is_symlink():
            errors.append(Finding("error", "plan-refused", "active plan target is a symlink", DEFAULT_PLAN_REL))
        elif not plan_path.is_file():
            errors.append(Finding("error", "plan-refused", "active plan target exists but is not a regular file", DEFAULT_PLAN_REL))

    if state and state.exists and state.frontmatter.has_frontmatter:
        data = state.frontmatter.data
        plan_status = str(data.get("plan_status") or "")
        active_plan = str(data.get("active_plan") or "")
        if plan_status == "active":
            if _normalize_rel(active_plan) != DEFAULT_PLAN_REL:
                errors.append(Finding("error", "plan-refused", f"active_plan must be {DEFAULT_PLAN_REL} for plan update; got {active_plan or '<empty>'}", state.rel_path))
            if not request.update_active:
                errors.append(Finding("error", "plan-refused", "an active implementation plan already exists; pass --update-active to replace the active plan scaffold", state.rel_path))
            elif not plan_path.exists():
                errors.append(Finding("error", "plan-refused", "active plan update requested but the active plan file is missing", DEFAULT_PLAN_REL))
        elif plan_status not in {"", "none"}:
            errors.append(Finding("error", "plan-refused", f"plan_status is {plan_status!r}; expected active or none before plan apply", state.rel_path))
        elif active_plan:
            errors.append(Finding("error", "plan-refused", "active_plan is set while plan_status is not active", state.rel_path))
        elif plan_path.exists():
            errors.append(Finding("error", "plan-refused", "stale implementation plan exists while plan_status is not active", DEFAULT_PLAN_REL))
        elif request.update_active:
            errors.append(Finding("error", "plan-refused", "--update-active requires plan_status active and an existing active plan", state.rel_path))
    return errors


def _root_posture_finding(inventory: Inventory) -> Finding:
    return Finding("info", "plan-root-posture", f"root kind: {inventory.root_kind}")


def _boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "plan-boundary",
            "plan apply writes only project/implementation-plan.md plus selected project-state lifecycle frontmatter and the Current Focus managed block in eligible live operating roots",
        ),
        Finding(
            "info",
            "plan-authority",
            "generated plans are repo-visible execution scaffolds; they cannot approve repair, archive, closeout, commit, rollback, or future mutations",
        ),
    ]


def _plan_roadmap_plans(inventory: Inventory, request: PlanRequest) -> tuple[tuple[RoadmapPlan, ...], list[Finding]]:
    if not request.roadmap_item:
        return (), []
    roadmap_requests = tuple(
        make_roadmap_request("update", item_id, related_plan=DEFAULT_PLAN_REL)
        for item_id in _plan_roadmap_item_ids(inventory, request)
    )
    return roadmap_plans_for_requests(inventory, roadmap_requests, allowed_missing_paths={DEFAULT_PLAN_REL})


def _plan_roadmap_item_ids(inventory: Inventory, request: PlanRequest) -> tuple[str, ...]:
    requested = _normalized_item_id(request.roadmap_item)
    if not requested:
        return ()
    if request.only_requested_item:
        return (requested,)
    slice_contract = roadmap_slice_contract_for_item(inventory, requested)
    if slice_contract and requested in {slice_contract.primary_roadmap_item, *slice_contract.covered_roadmap_items}:
        return tuple(_dedupe_nonempty((requested, *slice_contract.covered_roadmap_items)))
    return (requested,)


def _plan_slice_contract(inventory: Inventory, request: PlanRequest) -> RoadmapSliceContract | None:
    if not request.roadmap_item:
        return None
    contract = roadmap_slice_contract_for_item(inventory, request.roadmap_item)
    if contract is None or not request.only_requested_item:
        return contract
    fields = roadmap_item_fields(inventory, request.roadmap_item)
    return RoadmapSliceContract(
        primary_roadmap_item=contract.primary_roadmap_item,
        execution_slice=contract.execution_slice,
        slice_goal=contract.slice_goal,
        covered_roadmap_items=(request.roadmap_item,),
        domain_context=contract.domain_context,
        target_artifacts=tuple(_dedupe_nonempty(_field_list(fields.get("target_artifacts")))),
        execution_policy=contract.execution_policy,
        closeout_boundary=contract.closeout_boundary,
        source_incubation=_normalize_rel(str(fields.get("source_incubation") or "")),
        source_research=_normalize_rel(str(fields.get("source_research") or "")),
        related_specs=tuple(_dedupe_nonempty(_field_list(fields.get("related_specs")))),
    )


def _plan_synthesis_report(
    inventory: Inventory,
    request: PlanRequest,
    slice_contract: RoadmapSliceContract | None,
) -> RoadmapSynthesisReport | None:
    if not request.roadmap_item:
        return None
    if not request.only_requested_item:
        return roadmap_synthesis_report_for_item(inventory, request.roadmap_item)
    contract = slice_contract or _plan_slice_contract(inventory, request)
    if contract is None:
        return None
    source_inputs = tuple(_dedupe_nonempty((contract.source_incubation, contract.source_research)))
    verification_summary = _normalized_note(roadmap_item_fields(inventory, request.roadmap_item).get("verification_summary"))
    verification_summary_count = 1 if verification_summary else 0
    return RoadmapSynthesisReport(
        primary_roadmap_item=request.roadmap_item,
        execution_slice=contract.execution_slice,
        covered_roadmap_items=(request.roadmap_item,),
        domain_contexts=(contract.domain_context,),
        target_artifacts=contract.target_artifacts,
        related_specs=contract.related_specs,
        source_inputs=source_inputs,
        bundle_signals=("only requested roadmap item was selected; roadmap slice siblings are not batched",),
        split_signals=(
            f"only requested roadmap item {request.roadmap_item!r} is included; roadmap slice siblings are excluded from this plan",
            "bundle/split output is advisory and cannot approve lifecycle movement",
        ),
        in_slice_dependencies=(),
        verification_summary_count=verification_summary_count,
        target_artifact_pressure=(
            f"{len(contract.target_artifacts)} target artifacts across 1 roadmap item; "
            "report-only sizing signal, not a hard gate"
        ),
        phase_pressure=(
            f"1 domain context and {verification_summary_count} {_plural('verification summary', verification_summary_count)}; "
            "generated plans still start with one explicit current phase"
        ),
    )


def _roadmap_source_incubation(inventory: Inventory, roadmap_item: str) -> str:
    if not roadmap_item:
        return ""
    fields = roadmap_item_fields(inventory, roadmap_item)
    return _normalize_rel(str(fields.get("source_incubation") or ""))


def _plan_roadmap_has_changes(plans: tuple[RoadmapPlan, ...]) -> bool:
    return bool(plans) and plans[0].current_text != plans[-1].updated_text


def _plan_roadmap_findings(plans: tuple[RoadmapPlan, ...], apply: bool) -> list[Finding]:
    prefix = "" if apply else "would "
    changed_plans = tuple(plan for plan in plans if plan.changed_fields)
    item_ids = tuple(plan.item_id for plan in plans)
    target_rel = plans[-1].target_rel
    action = "updated" if apply and changed_plans else "checked" if apply else "would update"
    findings = [
        Finding("info", "plan-roadmap-sync", f"{action} roadmap item(s) {list(item_ids)!r} with active plan relationship", target_rel),
        Finding("info", "plan-roadmap-target", f"{prefix}write roadmap sync target: {target_rel}", target_rel),
    ]
    if changed_plans:
        for item_plan in plans:
            findings.extend(
                Finding(
                    "info",
                    "plan-roadmap-changed-field",
                    f"{prefix}change roadmap item {item_plan.item_id!r} field: {field}",
                    target_rel,
                )
                for field in item_plan.changed_fields
            )
    else:
        findings.append(Finding("info", "plan-roadmap-noop", "roadmap item(s) already record the requested active plan relationship", target_rel))
    findings.append(
        Finding(
            "info",
            "plan-roadmap-boundary",
            "plan roadmap sync is an optional project/roadmap.md relationship update bounded to the requested item plus covered_roadmap_items from the roadmap slice contract; roadmap output cannot approve closeout, archive, commit, rollback, repair, or lifecycle decisions",
            target_rel,
        )
    )
    return findings


def _plan_only_requested_item_finding(request: PlanRequest, apply: bool) -> Finding:
    prefix = "" if apply else "would "
    return Finding(
        "info",
        "plan-only-requested-item",
        f"{prefix}limit roadmap relationship and active-plan slice frontmatter to requested item {request.roadmap_item!r}",
        DEFAULT_PLAN_REL,
    )


def _plan_slice_contract_findings(contract: RoadmapSliceContract, apply: bool) -> list[Finding]:
    prefix = "" if apply else "would "
    return [
        Finding(
            "info",
            "plan-slice-frontmatter",
            (
                f"{prefix}record executable slice frontmatter: primary_roadmap_item={contract.primary_roadmap_item!r}; "
                f"covered_roadmap_items={list(contract.covered_roadmap_items)!r}; execution_policy={contract.execution_policy!r}"
            ),
            DEFAULT_PLAN_REL,
        ),
        Finding(
            "info",
            "plan-slice-boundary",
            "plan slice metadata is derived from repo-visible roadmap fields and cannot approve auto-continue, closeout, archive, commit, rollback, repair, or lifecycle decisions",
            DEFAULT_PLAN_REL,
        ),
    ]


def _plan_synthesis_findings(report: RoadmapSynthesisReport, apply: bool) -> list[Finding]:
    prefix = "" if apply else "would "
    return [
        Finding(
            "info",
            "plan-synthesis-bundle-rationale",
            f"{prefix}report bundle signals for {len(report.covered_roadmap_items)} roadmap items: {'; '.join(report.bundle_signals)}",
            DEFAULT_PLAN_REL,
        ),
        Finding(
            "info",
            "plan-synthesis-split-boundary",
            f"{prefix}report split boundary: {'; '.join(report.split_signals)}",
            DEFAULT_PLAN_REL,
        ),
        Finding(
            "info",
            "plan-synthesis-target-artifact-pressure",
            f"{prefix}report target artifact pressure: {report.target_artifact_pressure}",
            DEFAULT_PLAN_REL,
        ),
        Finding(
            "info",
            "plan-synthesis-phase-pressure",
            f"{prefix}report phase pressure: {report.phase_pressure}",
            DEFAULT_PLAN_REL,
        ),
        Finding(
            "info",
            "plan-synthesis-boundary",
            "plan synthesis rationale is advisory evidence only and cannot approve lifecycle movement or closeout",
            DEFAULT_PLAN_REL,
        ),
    ]


def _dangerous_input_reason(value: str) -> str | None:
    normalized = re.sub(r"\s+", " ", value.casefold())
    dangerous_markers = (
        ("git reset --hard", "task input asks for destructive VCS recovery"),
        ("git checkout --", "task input asks for broad VCS restoration"),
        ("git restore .", "task input asks for broad VCS restoration"),
        ("git restore -- .", "task input asks for broad VCS restoration"),
        ("git clean -fd", "task input asks for destructive cleanup"),
        ("git clean -xdf", "task input asks for destructive cleanup"),
        ("rm -rf", "task input asks for destructive cleanup"),
        ("remove-item -recurse", "task input asks for destructive cleanup"),
        ("rmdir /s", "task input asks for destructive cleanup"),
        ("del /s", "task input asks for destructive cleanup"),
    )
    for marker, reason in dangerous_markers:
        if marker in normalized:
            return reason
    return None


def _update_frontmatter_scalars(text: str, updates: dict[str, str]) -> str:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text
    closing_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        return text

    seen: set[str] = set()
    for index in range(1, closing_index):
        match = re.match(r"^([A-Za-z0-9_-]+):(.*?)(\r?\n)?$", lines[index])
        if not match:
            continue
        key = match.group(1)
        if key not in updates:
            continue
        newline = match.group(3) or ("\n" if lines[index].endswith("\n") else "")
        lines[index] = f'{key}: "{_yaml_double_quoted_value(updates[key])}"{newline}'
        seen.add(key)

    missing = [key for key in updates if key not in seen]
    if missing:
        insert_lines = [f'{key}: "{_yaml_double_quoted_value(updates[key])}"\n' for key in missing]
        lines[closing_index:closing_index] = insert_lines
    return "".join(lines)


def _path_escapes_root(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return False
    except ValueError:
        return True


def _parents_between(root: Path, path: Path) -> list[Path]:
    parents: list[Path] = []
    current = path
    root_resolved = root.resolve()
    while True:
        try:
            current.resolve().relative_to(root_resolved)
        except ValueError:
            break
        if current.resolve() == root_resolved:
            break
        parents.append(current)
        current = current.parent
    return list(reversed(parents))


def _normalize_rel(value: str) -> str:
    return value.replace("\\", "/").strip("/")


def _safe_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _normalized_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).rstrip(".")


def _normalized_note(value: object) -> str:
    return str(value or "").strip()


def _normalized_item_id(value: object) -> str:
    return str(value or "").strip().casefold().replace("_", "-")


def _field_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    normalized = str(value or "").strip()
    return [normalized] if normalized else []


def _yaml_double_quoted_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _yaml_frontmatter_list(key: str, values: tuple[str, ...]) -> str:
    if not values:
        return f"{key}: []\n"
    rendered = [f"{key}:\n"]
    rendered.extend(f'  - "{_yaml_double_quoted_value(value)}"\n' for value in values)
    return "".join(rendered)


def _dedupe_nonempty(values) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        if value and value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped


def _plural(label: str, count: int) -> str:
    return label if count == 1 else f"{label}s"


def _with_severity(findings: list[Finding], severity: str) -> list[Finding]:
    return [Finding(severity, finding.code, finding.message, finding.source, finding.line) for finding in findings]
