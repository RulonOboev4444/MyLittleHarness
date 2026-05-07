from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from .atomic_files import AtomicFileWrite, FileTransactionError, apply_file_transaction
from .inventory import Inventory
from .lifecycle_focus import sync_current_focus_block
from .memory_hygiene import (
    ROADMAP_CURRENT_POSTURE_FIELD,
    RelationshipUpdatePlan,
    relationship_update_plan,
    sync_roadmap_current_posture_section,
)
from .models import Finding
from .roadmap import (
    ROADMAP_REL,
    RELATED_INCUBATION_FIELD,
    TERMINAL_RELATED_PLAN_RETARGET_FIELD,
    RoadmapPlan,
    RoadmapSliceContract,
    RoadmapSynthesisReport,
    make_roadmap_request,
    roadmap_item_fields,
    roadmap_item_title,
    roadmap_plans_for_requests,
    roadmap_slice_contract_for_item,
    roadmap_synthesis_report_for_item,
    roadmap_text_with_terminal_related_plan_retargets,
)
from .reporting import RouteWriteEvidence, route_write_findings
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
DOCS_WRITE_SCOPE_PLACEHOLDER = "declare exact docs/spec/package metadata files before docs_decision=updated mutation"


@dataclass(frozen=True)
class PlanRequest:
    title: str
    objective: str
    task: str
    update_active: bool = False
    roadmap_item: str = ""
    only_requested_item: bool = False


@dataclass(frozen=True)
class PlanInputResolution:
    request: PlanRequest
    derived_fields: tuple[str, ...] = ()
    candidate_title: str = ""
    candidate_objective: str = ""
    candidate_task: str = ""
    source_excerpt: str = ""


@dataclass(frozen=True)
class GeneratedPlanPhase:
    phase_id: str
    status: str
    objective: str
    dependencies: tuple[str, ...]
    write_scope: tuple[str, ...]
    read_context: tuple[str, ...]
    invariants: str
    implementation_contract: str
    verification_gates: str
    docs_decision_rule: str
    state_transfer: str
    refusal_or_escalation: str


@dataclass(frozen=True)
class VerificationGateProfile:
    status: str
    command: str
    source: str
    reason: str


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


def resolve_plan_request_from_roadmap(inventory: Inventory, request: PlanRequest) -> PlanInputResolution:
    if not request.roadmap_item:
        return PlanInputResolution(request)
    fields = roadmap_item_fields(inventory, request.roadmap_item)
    if not fields:
        return PlanInputResolution(request)

    source_excerpt = _roadmap_source_excerpt(inventory, fields)
    candidate_title = _roadmap_candidate_title(inventory, request.roadmap_item)
    candidate_objective = _roadmap_candidate_objective(request.roadmap_item, fields, source_excerpt)
    candidate_task = _roadmap_candidate_task(request.roadmap_item, fields, source_excerpt)
    derived_fields: list[str] = []
    resolved = request
    if not resolved.title and candidate_title:
        resolved = replace(resolved, title=candidate_title)
        derived_fields.append("title")
    if not resolved.objective and candidate_objective:
        resolved = replace(resolved, objective=candidate_objective)
        derived_fields.append("objective")
    if not resolved.task and candidate_task:
        resolved = replace(resolved, task=candidate_task)
        derived_fields.append("task")
    return PlanInputResolution(
        resolved,
        tuple(derived_fields),
        candidate_title=candidate_title,
        candidate_objective=candidate_objective,
        candidate_task=candidate_task,
        source_excerpt=source_excerpt,
    )


def render_implementation_plan(
    request: PlanRequest,
    *,
    today: date | None = None,
    source_incubation: str = "",
    slice_contract: RoadmapSliceContract | None = None,
    synthesis_report: RoadmapSynthesisReport | None = None,
    verification_profile: VerificationGateProfile | None = None,
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
        f"{_phase_sections(slice_contract, synthesis_report, verification_profile)}"
        "\n## Verification Strategy\n\n"
        "- Run the narrowest deterministic tests that cover changed behavior.\n"
        "- Run `mylittleharness --root <this-repo> check` before confident closeout.\n"
        "- Treat failed verification as a blocker or residual risk, not as permission to widen scope silently.\n"
        "\n## Docs Decision\n\n"
        f"- docs_decision: {DEFAULT_DOCS_DECISION}\n"
        "- Record `updated`, `not-needed`, or `uncertain` with evidence before closeout.\n"
        "\n## State Transfer\n\n"
        "- Update `project/project-state.md` lifecycle fields through an explicit writeback path or equivalent scoped mutation.\n"
        "- Record a concise plain-language work result capsule for meaningful mutating or lifecycle work.\n"
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
        "- work_result: record what changed, what became better, how it was checked, and what remains in plain language.\n"
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
        if slice_contract.related_incubation:
            lines.append(f'related_incubation: "{_yaml_double_quoted_value(slice_contract.related_incubation)}"\n')
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
    phase_note = _phase_outline_note(report)
    return (
        "\n## Plan Synthesis Notes\n\n"
        f"- covered_roadmap_items: {covered}\n"
        f"- target_artifact_pressure: {report.target_artifact_pressure}\n"
        f"- phase_pressure: {report.phase_pressure}\n"
        "\n### Bundle Rationale\n\n"
        f"{bundle}\n"
        "\n### Split Boundary\n\n"
        f"{split}\n"
        f"{phase_note}"
        "\nPlan synthesis notes are advisory sizing evidence only; they cannot approve repair, closeout, archive, commit, rollback, lifecycle decisions, or next-slice movement.\n"
    )


def _phase_outline_note(report: RoadmapSynthesisReport) -> str:
    if _recommended_phase_count_for_report(report) <= 1:
        return (
            "\n### One-Shot Rationale\n\n"
            "- Generated as one explicit current phase because the roadmap slice has low artifact and verification pressure.\n"
            "- If implementation discovers extra write scope, docs/API uncertainty, or missing deterministic verification, stop and update the plan before widening.\n"
        )
    phases = _generated_phases(None, report)
    lines = ["\n### Phase Outline\n\n"]
    for phase in phases:
        lines.append(f"- `{phase.phase_id}`: {phase.objective}\n")
    return "".join(lines)


def _phase_sections(
    slice_contract: RoadmapSliceContract | None,
    report: RoadmapSynthesisReport | None,
    verification_profile: VerificationGateProfile | None = None,
) -> str:
    return "\n".join(_render_phase_section(phase) for phase in _generated_phases(slice_contract, report, verification_profile))


def _generated_phases(
    slice_contract: RoadmapSliceContract | None,
    report: RoadmapSynthesisReport | None,
    verification_profile: VerificationGateProfile | None = None,
) -> tuple[GeneratedPlanPhase, ...]:
    if report is None:
        return (_default_generated_phase(),)

    targets = tuple(report.target_artifacts)
    groups = _artifact_groups(targets)
    read_context = tuple(
        _dedupe_nonempty(
            (
                "AGENTS.md",
                ".codex/project-workflow.toml",
                "project/project-state.md",
                "project/roadmap.md",
                *report.related_specs,
                *report.source_inputs,
            )
        )
    )
    boundary = slice_contract.closeout_boundary if slice_contract else "explicit-closeout-required"
    source_scope = groups["source"] or groups["other"] or targets
    test_scope = groups["tests"]
    docs_scope = _docs_impact_scope(report, groups)
    if getattr(report, "docs_update_count", 0) > 0 and docs_scope:
        docs_scope_set = set(docs_scope)
        source_scope = tuple(target for target in source_scope if target not in docs_scope_set)
    all_scope = targets or ("project/implementation-plan.md",)
    phase_1_scope = tuple(_dedupe_nonempty((*source_scope, *test_scope))) if test_scope else source_scope

    phase_1 = GeneratedPlanPhase(
        phase_id=DEFAULT_ACTIVE_PHASE,
        status=DEFAULT_PHASE_STATUS,
        objective="Implement the roadmap-backed behavior inside the declared product/source contract.",
        dependencies=(),
        write_scope=phase_1_scope,
        read_context=read_context,
        invariants=(
            "keep MLH target-repository boundaries, explicit dry-run/apply semantics, and "
            "current-phase-only execution intact"
        ),
        implementation_contract=(
            f"deliver the behavior for `{report.primary_roadmap_item}` without hidden runtime state; "
            "roadmap synthesis remains advisory and cannot approve lifecycle movement"
        ),
        verification_gates=_focused_verification_gate(test_scope, verification_profile),
        docs_decision_rule="keep `docs_decision` as `uncertain` until docs/spec/package impact is proven.",
        state_transfer="record changed contracts, source assumptions, verification evidence, residual risk, carry-forward, and a plain-language work result capsule.",
        refusal_or_escalation="stop before unsafe roots, destructive recovery, hidden infrastructure, unclear ownership, or edits outside this phase write_scope.",
    )

    if _recommended_phase_count_for_report(report) <= 1:
        return (phase_1,)

    phase_2_scope = tuple(_dedupe_nonempty((*test_scope, *docs_scope))) or all_scope
    phase_2 = GeneratedPlanPhase(
        phase_id="phase-2-verification-and-docs",
        status="pending",
        objective="Prove the behavior with focused tests and update user-facing workflow specs/templates when impact is present.",
        dependencies=(DEFAULT_ACTIVE_PHASE,),
        write_scope=phase_2_scope,
        read_context=read_context,
        invariants="do not weaken phase-1 verification, roadmap advisory boundaries, or current-phase-only stop conditions.",
        implementation_contract=(
            "focused tests and docs/spec fixtures describe the generated phase outline or one-shot rationale consistently"
        ),
        verification_gates=_focused_verification_gate(test_scope, verification_profile),
        docs_decision_rule="record `updated` when specs/templates/docs change; otherwise record `not-needed` with evidence.",
        state_transfer="record exact commands, expected success signals, docs decision evidence, any remaining generic gates, and a plain-language work result capsule.",
        refusal_or_escalation="stop if docs/API/lifecycle authority is uncertain or verification cannot provide a deterministic success signal.",
    )

    if _recommended_phase_count_for_report(report) <= 2:
        return (phase_1, phase_2)

    phase_3 = GeneratedPlanPhase(
        phase_id="phase-3-integration-and-state-transfer",
        status="pending",
        objective="Run broader integration checks, mirror/cross-root verification when required, and prepare explicit closeout evidence.",
        dependencies=("phase-2-verification-and-docs",),
        write_scope=("project/implementation-plan.md", "project/project-state.md"),
        read_context=tuple(_dedupe_nonempty((*read_context, *all_scope))),
        invariants=(
            f"closeout boundary remains `{boundary}`; completing implementation does not archive, commit, "
            "mark roadmap done, or open the next slice"
        ),
        implementation_contract="repo-visible state transfer is compact, deterministic, and enough for explicit closeout preparation.",
        verification_gates=(
            "`mylittleharness --root <operating-root> check` exits 0; run broader product/demo tests when product source or mirrors changed"
        ),
        docs_decision_rule="final docs_decision must be `updated`, `not-needed`, or `uncertain`; uncertain keeps closeout language provisional.",
        state_transfer="record final verification summary, residual risk, carry-forward, work result capsule, and commit decision without staging or archive authority.",
        refusal_or_escalation="stop before closeout/archive/roadmap done-status/commit unless the user explicitly requests that lifecycle action.",
    )
    return (phase_1, phase_2, phase_3)


def _default_generated_phase() -> GeneratedPlanPhase:
    return GeneratedPlanPhase(
        phase_id=DEFAULT_ACTIVE_PHASE,
        status=DEFAULT_PHASE_STATUS,
        objective="Implement the requested change inside the declared write scope.",
        dependencies=(),
        write_scope=("update this section with exact target files before mutation",),
        read_context=("repo-visible authority and relevant local tests/docs",),
        invariants="keep MLH target-repository boundaries and explicit apply/dry-run semantics intact.",
        implementation_contract="deliver the requested behavior without adding hidden runtime state.",
        verification_gates="run targeted tests first, then broader checks appropriate to the changed surface.",
        docs_decision_rule="keep `docs_decision` as `uncertain` until docs impact is proven.",
        state_transfer="record changed contracts, verification evidence, residual risk, carry-forward, and a plain-language work result capsule.",
        refusal_or_escalation="stop before unsafe roots, destructive recovery, hidden infrastructure, or unclear ownership.",
    )


def _render_phase_section(phase: GeneratedPlanPhase) -> str:
    dependencies = _backticked_values(phase.dependencies, "`<none>`")
    return (
        f"### {phase.phase_id}\n\n"
        f"- id: `{phase.phase_id}`\n"
        f"- status: `{phase.status}`\n"
        f"- objective: {phase.objective}\n"
        f"- dependencies: {dependencies}\n"
        f"- write_scope: {_backticked_values(phase.write_scope, '`<none>`')}\n"
        f"- read_context: {_backticked_values(phase.read_context, '`<none>`')}\n"
        f"- invariants: {phase.invariants}\n"
        f"- implementation_contract: {phase.implementation_contract}\n"
        f"- verification_gates: {phase.verification_gates}\n"
        f"- docs_decision_rule: {phase.docs_decision_rule}\n"
        f"- state_transfer: {phase.state_transfer}\n"
        f"- refusal_or_escalation: {phase.refusal_or_escalation}\n"
    )


def _artifact_groups(targets: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    source: list[str] = []
    tests: list[str] = []
    docs: list[str] = []
    other: list[str] = []
    for target in targets:
        normalized = _normalize_rel(target)
        if normalized.startswith("tests/"):
            tests.append(normalized)
        elif (
            normalized.startswith("docs/")
            or normalized.startswith("project/specs/")
            or normalized.startswith("src/mylittleharness/templates/")
            or normalized.endswith(".md")
        ):
            docs.append(normalized)
        elif normalized.startswith("src/"):
            source.append(normalized)
        else:
            other.append(normalized)
    return {
        "source": tuple(source),
        "tests": tuple(tests),
        "docs": tuple(docs),
        "other": tuple(other),
    }


def _docs_impact_scope(report: RoadmapSynthesisReport, groups: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    docs_scope = list(groups["docs"])
    if getattr(report, "docs_update_count", 0) <= 0:
        return tuple(docs_scope)
    docs_scope.extend(report.related_specs)
    docs_scope.extend(target for target in groups["other"] if _is_package_metadata_target(target))
    if not docs_scope:
        docs_scope.append(DOCS_WRITE_SCOPE_PLACEHOLDER)
    return tuple(_dedupe_nonempty(docs_scope))


def _is_package_metadata_target(target: str) -> bool:
    normalized = _normalize_rel(target).casefold()
    return normalized in {"pyproject.toml", "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock"}


def _focused_verification_gate(
    test_scope: tuple[str, ...],
    verification_profile: VerificationGateProfile | None = None,
) -> str:
    if test_scope:
        return (
            "`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src uv run --no-project --with pytest pytest -q "
            f"{' '.join(test_scope)}` exits 0"
        )
    if verification_profile and verification_profile.status == "candidate" and verification_profile.command:
        return (
            f"`{verification_profile.command}` exits 0 "
            f"(repo-visible candidate from {verification_profile.source}; {verification_profile.reason})"
        )
    if verification_profile and verification_profile.status == "unresolved":
        return (
            "UNRESOLVED: no repo-visible verification command was discovered from target artifacts, package scripts, "
            "Makefile/just/task files, CI workflows, docs, prior evidence, or roadmap verification_summary; "
            "agent must record a concrete gate before confident closeout."
        )
    return "`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src uv run --no-project --with pytest pytest -q` exits 0 or a narrower deterministic command is recorded before completion"


def _repo_verification_gate_profile(
    inventory: Inventory,
    request: PlanRequest,
    report: RoadmapSynthesisReport | None,
    slice_contract: RoadmapSliceContract | None,
) -> VerificationGateProfile | None:
    if report is None and slice_contract is None:
        return None
    target_artifacts = tuple(report.target_artifacts if report else slice_contract.target_artifacts if slice_contract else ())
    verification_summary = ""
    if request.roadmap_item:
        verification_summary = _normalized_note(roadmap_item_fields(inventory, request.roadmap_item).get("verification_summary"))
    target_root = _verification_target_root(inventory)
    if command := _command_from_package_scripts(target_root, target_artifacts):
        return VerificationGateProfile(
            status="candidate",
            command=command,
            source=f"{_display_repo_source(target_root, inventory)} package scripts",
            reason="agent may add adjacent scripts when the change requires them",
        )
    if command := _command_from_task_files(target_root):
        return VerificationGateProfile(
            status="candidate",
            command=command,
            source=f"{_display_repo_source(target_root, inventory)} task file",
            reason="agent should confirm the task covers the changed surface",
        )
    if command := _command_from_ci_workflow(target_root):
        return VerificationGateProfile(
            status="candidate",
            command=command,
            source=f"{_display_repo_source(target_root, inventory)} CI workflow",
            reason="local reproduction may need adjustment if the CI command depends on setup steps",
        )
    if command := _command_from_text(verification_summary):
        return VerificationGateProfile(
            status="candidate",
            command=command,
            source="roadmap verification_summary",
            reason="verify that this remains task-specific before closeout",
        )
    if command := _command_from_docs(target_root):
        return VerificationGateProfile(
            status="candidate",
            command=command,
            source=_display_repo_source(target_root, inventory),
            reason="verify that this repo-documented command covers the changed surface",
        )
    if command := _python_test_command(target_root, target_artifacts):
        return VerificationGateProfile(
            status="candidate",
            command=command,
            source=f"{_display_repo_source(target_root, inventory)} Python test layout",
            reason="agent may narrow with specific test paths when available",
        )
    return VerificationGateProfile(
        status="unresolved",
        command="",
        source=_display_repo_source(target_root, inventory),
        reason=(
            "no concrete command was visible; generated plan must stay unresolved until an agent records "
            "an evidence-backed gate"
        ),
    )


def _plan_verification_gate_findings(
    report: RoadmapSynthesisReport | None,
    profile: VerificationGateProfile | None,
    apply: bool,
) -> list[Finding]:
    if report is None:
        return []
    prefix = "" if apply else "would "
    groups = _artifact_groups(tuple(report.target_artifacts))
    test_scope = groups["tests"]
    source_scope = groups["source"] or groups["other"]
    findings: list[Finding] = []
    if test_scope:
        findings.append(
            Finding(
                "info",
                "plan-verification-gate-target-tests",
                f"{prefix}render verification gate from target test artifact(s): {', '.join(test_scope)}",
                DEFAULT_PLAN_REL,
            )
        )
        if source_scope:
            findings.append(
                Finding(
                    "info",
                    "plan-adjacent-verification-ownership",
                    f"{prefix}include adjacent regression-test ownership in phase write_scope: {', '.join(test_scope)}",
                    DEFAULT_PLAN_REL,
                )
            )
        return findings
    if profile is None:
        return []
    if profile.status == "candidate":
        findings.append(
            Finding(
                "info",
                "plan-verification-gate-discovery",
                f"{prefix}render repo-visible verification candidate `{profile.command}` from {profile.source}",
                DEFAULT_PLAN_REL,
            )
        )
        if _profile_needs_adjacent_regression_scope(profile, tuple(report.target_artifacts)):
            findings.append(
                Finding(
                    "warn",
                    "plan-adjacent-verification-ownership",
                    f"{prefix}surface unresolved adjacent regression-test ownership because `{profile.command}` is broader than declared target_artifacts",
                    DEFAULT_PLAN_REL,
                )
            )
        return findings
    findings.append(
        Finding(
            "warn",
            "plan-verification-gate-unresolved",
            f"{prefix}render unresolved verification gate because {profile.reason}",
            DEFAULT_PLAN_REL,
        )
    )
    return findings


def _profile_needs_adjacent_regression_scope(
    profile: VerificationGateProfile,
    target_artifacts: tuple[str, ...],
) -> bool:
    command = profile.command.casefold()
    if "pytest" not in command:
        return False
    if any(_normalize_rel(target).casefold().startswith("tests/") for target in target_artifacts):
        return False
    return any(_normalize_rel(target).casefold().startswith("src/") or _normalize_rel(target).casefold().endswith(".py") for target in target_artifacts)


def _verification_target_root(inventory: Inventory) -> Path:
    state_data = inventory.state.frontmatter.data if inventory.state and inventory.state.frontmatter.has_frontmatter else {}
    for key in ("product_source_root", "projection_root", "operating_root", "canonical_source_evidence_root"):
        raw = str(state_data.get(key) or "").strip()
        if not raw:
            continue
        candidate = Path(raw.replace("\\\\", "\\"))
        if not candidate.is_absolute():
            candidate = inventory.root / candidate
        if candidate.is_dir():
            return candidate
    return inventory.root


def _display_repo_source(target_root: Path, inventory: Inventory) -> str:
    try:
        if target_root.resolve() == inventory.root.resolve():
            return "target root"
    except OSError:
        pass
    return "product_source_root"


def _command_from_text(text: str) -> str:
    for candidate in re.findall(r"`([^`]+)`", text or ""):
        command = _clean_command_candidate(candidate)
        if command:
            return command
    return ""


def _command_from_docs(target_root: Path) -> str:
    for rel_path in ("README.md", "CONTRIBUTING.md", "docs/README.md", "docs/development.md", "docs/testing.md"):
        path = target_root / rel_path
        if not path.is_file():
            continue
        try:
            if command := _command_from_text(path.read_text(encoding="utf-8")):
                return command
        except OSError:
            continue
    return ""


def _command_from_package_scripts(target_root: Path, target_artifacts: tuple[str, ...]) -> str:
    package_json = target_root / "package.json"
    if not package_json.is_file():
        return ""
    try:
        package = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    scripts = package.get("scripts")
    if not isinstance(scripts, dict):
        return ""
    preferred = ("test", "typecheck", "lint", "build", "check")
    if _target_artifacts_look_js(target_artifacts):
        preferred = ("test", "typecheck", "lint", "build", "check")
    for script_name in preferred:
        if isinstance(scripts.get(script_name), str) and scripts[script_name].strip():
            return _package_manager_command(target_root, script_name)
    return ""


def _package_manager_command(target_root: Path, script_name: str) -> str:
    if (target_root / "pnpm-lock.yaml").is_file():
        return f"pnpm run {script_name}"
    if (target_root / "yarn.lock").is_file():
        return f"yarn {script_name}"
    if (target_root / "bun.lockb").is_file() or (target_root / "bun.lock").is_file():
        return f"bun run {script_name}"
    return f"npm run {script_name}"


def _command_from_task_files(target_root: Path) -> str:
    for filename, command_prefix in (
        ("Makefile", "make"),
        ("makefile", "make"),
        ("justfile", "just"),
        ("Justfile", "just"),
        ("Taskfile.yml", "task"),
        ("Taskfile.yaml", "task"),
    ):
        path = target_root / filename
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for target in ("test", "typecheck", "lint", "build", "check"):
            if re.search(rf"(?m)^{re.escape(target)}\s*:", text):
                return f"{command_prefix} {target}"
    return ""


def _command_from_ci_workflow(target_root: Path) -> str:
    workflow_dir = target_root / ".github" / "workflows"
    if not workflow_dir.is_dir():
        return ""
    for path in sorted(tuple(workflow_dir.glob("*.yml")) + tuple(workflow_dir.glob("*.yaml"))):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            match = re.search(r"\brun:\s*(.+?)\s*$", line)
            if not match:
                continue
            command = _clean_command_candidate(match.group(1).strip().strip("'\""))
            if command:
                return command
    return ""


def _python_test_command(target_root: Path, target_artifacts: tuple[str, ...]) -> str:
    has_python_layout = (target_root / "pyproject.toml").is_file() and (target_root / "tests").is_dir()
    if not has_python_layout:
        return ""
    if (target_root / "package.json").is_file() and _target_artifacts_look_js(target_artifacts):
        return ""
    return "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src uv run --no-project --with pytest pytest -q"


def _clean_command_candidate(candidate: str) -> str:
    command = re.sub(r"\s+", " ", str(candidate or "").strip())
    if not command or "\n" in command:
        return ""
    lowered = command.casefold()
    command_markers = (
        "pytest",
        "npm ",
        "pnpm ",
        "yarn ",
        "bun ",
        "make ",
        "just ",
        "task ",
        "tox",
        "nox",
        "ruff",
        "mypy",
    )
    intent_markers = ("test", "typecheck", "lint", "build", "check")
    if any(marker in lowered for marker in command_markers) and any(marker in lowered for marker in intent_markers):
        return command
    return ""


def _target_artifacts_look_js(target_artifacts: tuple[str, ...]) -> bool:
    js_suffixes = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
    js_names = ("package.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb", "bun.lock")
    js_prefixes = ("apps/", "packages/", "web/", "frontend/")
    for target in target_artifacts:
        normalized = _normalize_rel(target).casefold()
        if normalized.endswith(js_suffixes) or normalized in js_names or normalized.startswith(js_prefixes):
            return True
    return False


def _recommended_phase_count_for_report(report: RoadmapSynthesisReport) -> int:
    return _recommended_phase_count_for_values(
        covered_count=len(report.covered_roadmap_items),
        target_count=len(report.target_artifacts),
        related_spec_count=len(report.related_specs),
        verification_summary_count=report.verification_summary_count,
        docs_update_count=getattr(report, "docs_update_count", 0),
    )


def _recommended_phase_count_for_values(
    *,
    covered_count: int,
    target_count: int,
    related_spec_count: int,
    verification_summary_count: int,
    docs_update_count: int = 0,
) -> int:
    pressure = 0
    if covered_count > 1:
        pressure += 1
    if target_count >= 4:
        pressure += 2
    elif target_count > 1:
        pressure += 1
    if related_spec_count > 1:
        pressure += 1
    if verification_summary_count > 0:
        pressure += 1
    if docs_update_count > 0:
        pressure += 2
    if pressure <= 1:
        return 1
    if pressure <= 2:
        return 2
    return 3


def _backticked_values(values: tuple[str, ...], fallback: str) -> str:
    rendered = ", ".join(f"`{value}`" for value in values if value)
    return rendered or fallback


def _plan_input_resolution_findings(resolution: PlanInputResolution, apply: bool) -> list[Finding]:
    if not resolution.candidate_title and not resolution.candidate_objective and not resolution.candidate_task:
        return []
    prefix = "" if apply else "would "
    findings: list[Finding] = []
    item_id = resolution.request.roadmap_item
    if resolution.derived_fields:
        findings.append(
            Finding(
                "info",
                "plan-roadmap-derived-input",
                f"{prefix}derive missing plan input field(s) from roadmap item {item_id!r}: {', '.join(resolution.derived_fields)}",
                DEFAULT_PLAN_REL,
            )
        )
    else:
        findings.append(
            Finding(
                "info",
                "plan-roadmap-candidate-input",
                f"{prefix}report roadmap-derived plan input candidates for roadmap item {item_id!r}; explicit CLI input remains authoritative",
                DEFAULT_PLAN_REL,
            )
        )
    if resolution.candidate_objective:
        findings.append(
            Finding(
                "info",
                "plan-roadmap-candidate-objective",
                f"candidate objective: {_truncate_text(resolution.candidate_objective, 260)}",
                DEFAULT_PLAN_REL,
            )
        )
    if resolution.candidate_task:
        findings.append(
            Finding(
                "info",
                "plan-roadmap-candidate-task",
                f"candidate task: {_truncate_text(resolution.candidate_task, 360)}",
                DEFAULT_PLAN_REL,
            )
        )
    return findings


def plan_dry_run_findings(inventory: Inventory, request: PlanRequest) -> list[Finding]:
    resolution = resolve_plan_request_from_roadmap(inventory, request)
    request = resolution.request
    findings = [
        Finding("info", "plan-dry-run", "plan proposal only; no files were written"),
        _root_posture_finding(inventory),
    ]
    errors = _plan_preflight_errors(inventory, request)
    roadmap_plans, roadmap_errors = _plan_roadmap_plans(inventory, request)
    errors.extend(roadmap_errors)
    source_plans, source_errors = _plan_source_incubation_plans(inventory, request)
    errors.extend(source_errors)
    findings.append(Finding("info", "plan-target", f"would write active plan: {DEFAULT_PLAN_REL}", DEFAULT_PLAN_REL))
    findings.append(
        Finding(
            "info",
            "plan-lifecycle",
            "would update project-state lifecycle frontmatter and Current Focus managed block: operating_mode, plan_status, active_plan, active_phase, phase_status",
            inventory.state.rel_path if inventory.state else "project/project-state.md",
        )
    )
    findings.extend(_plan_input_resolution_findings(resolution, apply=False))
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
            verification_profile = _repo_verification_gate_profile(inventory, request, synthesis_report, slice_contract)
            findings.extend(_plan_verification_gate_findings(synthesis_report, verification_profile, apply=False))
    if source_plans:
        findings.extend(_plan_source_incubation_findings(source_plans, apply=False))
    if errors:
        findings.extend(_with_severity(errors, "warn"))
        findings.append(Finding("info", "plan-validation-posture", "dry-run refused before apply; fix refusal reasons, then rerun dry-run before writing a plan"))
        return findings
    projected_state_text = ""
    if inventory.state:
        plan_text = _render_plan_text_for_request(inventory, request)
        lifecycle = _plan_lifecycle_values()
        projected_state_text = sync_current_focus_block(_update_frontmatter_scalars(inventory.state.content, lifecycle))
        findings.extend(_plan_route_write_findings(inventory, plan_text, projected_state_text, roadmap_plans, source_plans, apply=False))
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
        findings.extend(state_compaction_dry_run_findings(inventory, projected_state_text))
    findings.append(Finding("info", "plan-validation-posture", "apply would write only the active plan, project-state lifecycle frontmatter, and safe state-history compaction in an eligible live operating root"))
    return findings


def plan_apply_findings(inventory: Inventory, request: PlanRequest) -> list[Finding]:
    resolution = resolve_plan_request_from_roadmap(inventory, request)
    request = resolution.request
    errors = _plan_preflight_errors(inventory, request)
    roadmap_plans, roadmap_errors = _plan_roadmap_plans(inventory, request)
    errors.extend(roadmap_errors)
    source_plans, source_errors = _plan_source_incubation_plans(inventory, request)
    errors.extend(source_errors)
    if errors:
        return errors

    state = inventory.state
    assert state is not None
    plan_path = inventory.root / DEFAULT_PLAN_REL
    source_incubation = _roadmap_source_incubation(inventory, request.roadmap_item)
    slice_contract = _plan_slice_contract(inventory, request)
    synthesis_report = _plan_synthesis_report(inventory, request, slice_contract)
    verification_profile = _repo_verification_gate_profile(inventory, request, synthesis_report, slice_contract)
    plan_text = render_implementation_plan(
        request,
        source_incubation=source_incubation,
        slice_contract=slice_contract,
        synthesis_report=synthesis_report,
        verification_profile=verification_profile,
    )
    lifecycle = _plan_lifecycle_values()
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
    source_plan_tmps = tuple(
        (_plan_source_incubation_tmp(plan), _plan_source_incubation_backup(plan), plan)
        for plan in source_plans
        if plan.current_text != plan.updated_text
    )
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
    for source_tmp, source_backup, _plan in source_plan_tmps:
        for candidate, label in (
            (source_tmp, "temporary source-incubation relationship write path"),
            (source_backup, "temporary source-incubation relationship backup path"),
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
    for source_tmp, source_backup, source_plan in source_plan_tmps:
        operations.append(AtomicFileWrite(source_plan.target_path, source_tmp, source_plan.updated_text, source_backup))
    route_write_evidence = _plan_route_write_findings(
        inventory,
        plan_text,
        state_text,
        roadmap_plans,
        source_plans,
        apply=True,
    )
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
        *route_write_evidence,
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
    findings.extend(_plan_input_resolution_findings(resolution, apply=True))
    if roadmap_plans:
        findings.extend(_plan_roadmap_findings(roadmap_plans, apply=True))
    if source_plans:
        findings.extend(_plan_source_incubation_findings(source_plans, apply=True))
    if slice_contract:
        findings.extend(_plan_slice_contract_findings(slice_contract, apply=True))
    if request.only_requested_item:
        findings.append(_plan_only_requested_item_finding(request, apply=True))
    if synthesis_report:
        findings.extend(_plan_synthesis_findings(synthesis_report, apply=True))
        findings.extend(_plan_verification_gate_findings(synthesis_report, verification_profile, apply=True))
    if request.roadmap_item:
        findings.append(
            Finding(
                "info",
                "plan-relationship-frontmatter",
                "active plan frontmatter records related_roadmap_item, source_incubation or related_incubation provenance, and slice metadata when the roadmap item provides it",
                DEFAULT_PLAN_REL,
            )
        )
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "plan-backup-cleanup", warning, DEFAULT_PLAN_REL))
    findings.extend(state_compaction_apply_findings(inventory, state.path.read_text(encoding="utf-8")))
    return findings


def _render_plan_text_for_request(inventory: Inventory, request: PlanRequest) -> str:
    source_incubation = _roadmap_source_incubation(inventory, request.roadmap_item)
    slice_contract = _plan_slice_contract(inventory, request)
    synthesis_report = _plan_synthesis_report(inventory, request, slice_contract)
    verification_profile = _repo_verification_gate_profile(inventory, request, synthesis_report, slice_contract)
    return render_implementation_plan(
        request,
        source_incubation=source_incubation,
        slice_contract=slice_contract,
        synthesis_report=synthesis_report,
        verification_profile=verification_profile,
    )


def _plan_lifecycle_values() -> dict[str, str]:
    return {
        "operating_mode": "plan",
        "plan_status": "active",
        "active_plan": DEFAULT_PLAN_REL,
        "active_phase": DEFAULT_ACTIVE_PHASE,
        "phase_status": DEFAULT_PHASE_STATUS,
    }


def _plan_route_write_findings(
    inventory: Inventory,
    plan_text: str,
    state_text: str,
    roadmap_plans: tuple[RoadmapPlan, ...],
    source_plans: tuple[RelationshipUpdatePlan, ...],
    *,
    apply: bool,
) -> list[Finding]:
    writes = [
        RouteWriteEvidence(DEFAULT_PLAN_REL, _existing_plan_text(inventory), plan_text),
    ]
    if inventory.state:
        writes.append(RouteWriteEvidence(inventory.state.rel_path, inventory.state.content, state_text))
    if roadmap_plans:
        writes.append(RouteWriteEvidence(roadmap_plans[-1].target_rel, roadmap_plans[0].current_text, roadmap_plans[-1].updated_text))
    writes.extend(
        RouteWriteEvidence(plan.target_rel, plan.current_text, plan.updated_text)
        for plan in source_plans
    )
    return route_write_findings("plan-route-write", tuple(writes), apply=apply)


def _existing_plan_text(inventory: Inventory) -> str | None:
    plan = inventory.active_plan_surface
    if plan and plan.exists:
        return plan.content
    path = inventory.root / DEFAULT_PLAN_REL
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _plan_preflight_errors(inventory: Inventory, request: PlanRequest) -> list[Finding]:
    errors: list[Finding] = []
    if not request.title:
        errors.append(Finding("error", "plan-refused", "--title is required when it cannot be derived from --roadmap-item"))
    if not request.objective:
        errors.append(Finding("error", "plan-refused", "--objective is required when it cannot be derived from --roadmap-item"))
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
    plans, errors = roadmap_plans_for_requests(inventory, roadmap_requests, allowed_missing_paths={DEFAULT_PLAN_REL})
    if errors:
        return plans, errors
    return _plan_roadmap_plans_with_current_posture(plans), []


def _plan_roadmap_plans_with_current_posture(plans: tuple[RoadmapPlan, ...]) -> tuple[RoadmapPlan, ...]:
    if not plans:
        return plans
    last = plans[-1]
    active_item_ids = tuple(_dedupe_nonempty(plan.item_id for plan in plans))
    updated_text, retargeted_item_ids = roadmap_text_with_terminal_related_plan_retargets(
        last.updated_text,
        active_item_ids=active_item_ids,
    )
    changed_fields = last.changed_fields
    if updated_text != last.updated_text:
        changed_fields = tuple(_dedupe_nonempty((*changed_fields, TERMINAL_RELATED_PLAN_RETARGET_FIELD)))

    refreshed_text = sync_roadmap_current_posture_section(updated_text)
    if refreshed_text != updated_text:
        changed_fields = tuple(_dedupe_nonempty((*changed_fields, ROADMAP_CURRENT_POSTURE_FIELD)))
        updated_text = refreshed_text

    if updated_text == last.updated_text and not retargeted_item_ids:
        return plans
    return (
        *plans[:-1],
        replace(
            last,
            updated_text=updated_text,
            changed_fields=changed_fields,
            retargeted_terminal_item_ids=tuple(_dedupe_nonempty((*last.retargeted_terminal_item_ids, *retargeted_item_ids))),
        ),
    )


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


def _plan_source_incubation_plans(inventory: Inventory, request: PlanRequest) -> tuple[tuple[RelationshipUpdatePlan, ...], list[Finding]]:
    if not request.roadmap_item:
        return (), []
    plans: list[RelationshipUpdatePlan] = []
    errors: list[Finding] = []
    seen_sources: set[str] = set()
    for item_id in _plan_roadmap_item_ids(inventory, request):
        fields = roadmap_item_fields(inventory, item_id)
        source_incubation = _normalize_rel(str(fields.get("source_incubation") or ""))
        if not source_incubation or source_incubation in seen_sources:
            continue
        seen_sources.add(source_incubation)
        plan, plan_errors = relationship_update_plan(
            inventory,
            source_incubation,
            {
                "related_roadmap": ROADMAP_REL,
                "related_roadmap_item": item_id,
                "related_plan": DEFAULT_PLAN_REL,
                "promoted_to": ROADMAP_REL,
            },
        )
        errors.extend(plan_errors)
        if plan is not None:
            plans.append(plan)
    return tuple(plans), errors


def _plan_source_incubation_tmp(plan: RelationshipUpdatePlan) -> Path:
    return plan.target_path.with_name(f".{plan.target_path.name}.plan-source-incubation.tmp")


def _plan_source_incubation_backup(plan: RelationshipUpdatePlan) -> Path:
    return plan.target_path.with_name(f".{plan.target_path.name}.plan-source-incubation.backup")


def _plan_source_incubation_findings(plans: tuple[RelationshipUpdatePlan, ...], apply: bool) -> list[Finding]:
    prefix = "" if apply else "would "
    changed_plans = tuple(plan for plan in plans if plan.changed_fields)
    action = "updated" if apply and changed_plans else "checked" if apply else "would update"
    findings = [
        Finding(
            "info",
            "plan-source-incubation-sync",
            f"{action} source incubation relationship metadata for {len(plans)} roadmap source file(s)",
        )
    ]
    for plan in changed_plans:
        findings.extend(
            Finding(
                "info",
                "plan-source-incubation-changed-field",
                f"{prefix}change source incubation {plan.source_rel} field: {field}",
                plan.source_rel,
            )
            for field in plan.changed_fields
        )
    if not changed_plans:
        findings.append(Finding("info", "plan-source-incubation-noop", "source incubation relationship metadata already matches the new active plan", plans[0].source_rel if plans else None))
    findings.append(
        Finding(
            "info",
            "plan-source-incubation-boundary",
            "plan source-incubation sync records same-request active-plan ownership only; it cannot approve archive, closeout, roadmap done-status, commit, or future lifecycle movement",
            DEFAULT_PLAN_REL,
        )
    )
    return findings


def _plan_slice_contract(inventory: Inventory, request: PlanRequest) -> RoadmapSliceContract | None:
    if not request.roadmap_item:
        return None
    contract = roadmap_slice_contract_for_item(inventory, request.roadmap_item)
    fields = roadmap_item_fields(inventory, request.roadmap_item)
    source_excerpt = _roadmap_source_excerpt(inventory, fields)
    domain_context = _roadmap_domain_context(contract.domain_context, source_excerpt) if contract else ""
    if contract is None:
        return None
    if not request.only_requested_item:
        return replace(contract, domain_context=domain_context)
    return RoadmapSliceContract(
        primary_roadmap_item=contract.primary_roadmap_item,
        execution_slice=contract.execution_slice,
        slice_goal=contract.slice_goal,
        covered_roadmap_items=(request.roadmap_item,),
        domain_context=domain_context,
        target_artifacts=tuple(_dedupe_nonempty(_field_list(fields.get("target_artifacts")))),
        execution_policy=contract.execution_policy,
        closeout_boundary=contract.closeout_boundary,
        source_incubation=_normalize_rel(str(fields.get("source_incubation") or "")),
        source_research=_normalize_rel(str(fields.get("source_research") or "")),
        related_specs=tuple(_dedupe_nonempty(_field_list(fields.get("related_specs")))),
        related_incubation=_normalize_rel(str(fields.get(RELATED_INCUBATION_FIELD) or "")),
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
    source_inputs = tuple(_dedupe_nonempty((contract.source_incubation, contract.related_incubation, contract.source_research)))
    item_fields = roadmap_item_fields(inventory, request.roadmap_item)
    verification_summary = _normalized_note(item_fields.get("verification_summary"))
    docs_update_count = 1 if str(item_fields.get("docs_decision") or "").strip().casefold() == "updated" else 0
    verification_summary_count = 1 if verification_summary else 0
    recommended_phase_count = _recommended_phase_count_for_values(
        covered_count=1,
        target_count=len(contract.target_artifacts),
        related_spec_count=len(contract.related_specs),
        verification_summary_count=verification_summary_count,
        docs_update_count=docs_update_count,
    )
    docs_pressure = (
        f" and {docs_update_count} docs update {_plural('decision', docs_update_count)}"
        if docs_update_count
        else ""
    )
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
            f"1 domain context and {verification_summary_count} {_plural('verification summary', verification_summary_count)}"
            f"{docs_pressure}; "
            f"candidate plan outline: {recommended_phase_count} {_plural('phase', recommended_phase_count)} or explicit one-shot rationale"
        ),
        docs_update_count=docs_update_count,
    )


def _roadmap_source_incubation(inventory: Inventory, roadmap_item: str) -> str:
    if not roadmap_item:
        return ""
    fields = roadmap_item_fields(inventory, roadmap_item)
    return _normalize_rel(str(fields.get("source_incubation") or ""))


def _roadmap_incubation_provenance(fields: dict[str, object]) -> str:
    source = _normalize_rel(str(fields.get("source_incubation") or ""))
    if source:
        return source
    return _normalize_rel(str(fields.get(RELATED_INCUBATION_FIELD) or ""))


def _roadmap_candidate_title(inventory: Inventory, roadmap_item: str) -> str:
    return roadmap_item_title(inventory, roadmap_item) or _title_from_item_id(roadmap_item)


def _roadmap_candidate_objective(item_id: str, fields: dict[str, object], source_excerpt: str) -> str:
    source_first = source_excerpt if _source_excerpt_has_route_hints(source_excerpt) else ""
    for value in (
        source_first,
        fields.get("slice_goal"),
        source_excerpt,
        fields.get("verification_summary"),
        fields.get("carry_forward"),
        fields.get("execution_slice"),
    ):
        text = _clean_candidate_text(value)
        if text:
            return text
    normalized_item = _normalized_item_id(item_id)
    if normalized_item:
        return f"Implement roadmap item {normalized_item}."
    return ""


def _roadmap_candidate_task(item_id: str, fields: dict[str, object], source_excerpt: str) -> str:
    item = _normalized_item_id(item_id)
    parts: list[str] = []
    if item:
        parts.append(f"Implement roadmap item {item}.")
    source = _normalize_rel(str(fields.get("source_incubation") or ""))
    if source:
        parts.append(f"Source incubation: {source}.")
    else:
        related_source = _normalize_rel(str(fields.get(RELATED_INCUBATION_FIELD) or ""))
        if related_source:
            parts.append(f"Related incubation: {related_source}.")
    context = _clean_candidate_text(source_excerpt or fields.get("slice_goal"))
    if context:
        parts.append(f"Context: {context}")
    verification = _clean_candidate_text(fields.get("verification_summary"))
    if verification:
        parts.append(f"Verification context: {verification}")
    docs_decision = _clean_candidate_text(fields.get("docs_decision"))
    if docs_decision:
        parts.append(f"Roadmap docs_decision: {docs_decision}.")
    boundary = _clean_candidate_text(fields.get("slice_closeout_boundary"))
    if boundary:
        parts.append(f"Boundary: {boundary}.")
    return " ".join(parts)


def _roadmap_source_excerpt(inventory: Inventory, fields: dict[str, object]) -> str:
    source_rel = _roadmap_incubation_provenance(fields)
    if not source_rel:
        return ""
    source_path = inventory.root / source_rel
    if _path_escapes_root(inventory.root, source_path) or not source_path.is_file():
        return ""
    try:
        text = source_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""
    body = _body_without_frontmatter(text)
    paragraphs = _candidate_paragraphs(body)
    tagged = next((paragraph for paragraph in paragraphs if paragraph.lstrip().startswith("[MLH-Fix-Candidate]")), "")
    if not tagged:
        tagged = next((paragraph for paragraph in paragraphs if "[MLH-Fix-Candidate]" in paragraph), "")
    excerpt = _clean_candidate_text(tagged or (paragraphs[0] if paragraphs else ""))
    if tagged:
        excerpt = _source_excerpt_with_hints(excerpt, text)
    return excerpt


def _roadmap_domain_context(roadmap_context: str, source_excerpt: str) -> str:
    if _source_excerpt_has_route_hints(source_excerpt):
        return source_excerpt
    return roadmap_context


def _body_without_frontmatter(text: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[index + 1 :])
    return text


def _candidate_paragraphs(text: str) -> tuple[str, ...]:
    paragraphs: list[str] = []
    current: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        current.append(line)
    if current:
        paragraphs.append(" ".join(current))
    return tuple(paragraph for paragraph in (re.sub(r"\s+", " ", item).strip() for item in paragraphs) if paragraph)


def _source_excerpt_with_hints(excerpt: str, source_text: str) -> str:
    hints: list[str] = []
    lower_excerpt = excerpt.casefold()
    for key in ("affected_routes", "expected_owner_command"):
        value = _source_hint_field(source_text, key)
        if value and key not in lower_excerpt:
            hints.append(f"{key}: {value}")
    if not hints:
        return excerpt
    return f"{excerpt} {'; '.join(hints)}"


def _source_hint_field(text: str, key: str) -> str:
    match = re.search(rf"(?m)^\s*-\s*`?{re.escape(key)}`?:\s*(.+?)\s*$", text)
    if not match:
        return ""
    return match.group(1).strip().strip("`").strip()


def _source_excerpt_has_route_hints(value: str) -> bool:
    text = value.casefold()
    return "affected_routes:" in text or "expected_owner_command:" in text


def _clean_candidate_text(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip()).replace("[MLH-Fix-Candidate]", "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _title_from_item_id(value: str) -> str:
    words = [word for word in re.split(r"[^A-Za-z0-9]+", str(value or "")) if word]
    return " ".join(word[:1].upper() + word[1:] for word in words)


def _truncate_text(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


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
    retargeted = tuple(_dedupe_nonempty(item_id for plan in plans for item_id in plan.retargeted_terminal_item_ids))
    if retargeted:
        findings.append(
            Finding(
                "info",
                "plan-roadmap-terminal-retarget",
                f"{prefix}retarget terminal roadmap related_plan link(s): {', '.join(retargeted)}",
                target_rel,
            )
        )
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
    findings = [
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
    if contract.related_incubation and not contract.source_incubation:
        findings.append(
            Finding(
                "info",
                "plan-related-incubation-provenance",
                (
                    f"{prefix}record non-owning related_incubation provenance "
                    f"{contract.related_incubation!r} in active-plan metadata without source-note relationship writes"
                ),
                DEFAULT_PLAN_REL,
            )
        )
    return findings


def _plan_synthesis_findings(report: RoadmapSynthesisReport, apply: bool) -> list[Finding]:
    prefix = "" if apply else "would "
    findings = [
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
    docs_update_count = getattr(report, "docs_update_count", 0)
    if docs_update_count > 0:
        docs_scope = _docs_impact_scope(report, _artifact_groups(tuple(report.target_artifacts)))
        missing_exact_scope = DOCS_WRITE_SCOPE_PLACEHOLDER in docs_scope
        findings.append(
            Finding(
                "warn" if missing_exact_scope else "info",
                "plan-docs-write-scope-impact",
                (
                    f"{prefix}surface docs/spec write-scope impact for {docs_update_count} "
                    f"roadmap docs_decision=updated {_plural('item', docs_update_count)}: "
                    f"{', '.join(docs_scope)}"
                ),
                DEFAULT_PLAN_REL,
            )
        )
    return findings


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
