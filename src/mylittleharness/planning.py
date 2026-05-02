from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .inventory import Inventory
from .lifecycle_focus import sync_current_focus_block
from .models import Finding


DEFAULT_PLAN_REL = "project/implementation-plan.md"
DEFAULT_ACTIVE_PHASE = "phase-1-implementation"
DEFAULT_PHASE_STATUS = "pending"
DEFAULT_DOCS_DECISION = "uncertain"


@dataclass(frozen=True)
class PlanRequest:
    title: str
    objective: str
    task: str
    update_active: bool = False


def make_plan_request(title: str | None, objective: str | None, task: str | None, update_active: bool = False) -> PlanRequest:
    return PlanRequest(
        title=_normalized_text(title),
        objective=_normalized_note(objective),
        task=_normalized_note(task),
        update_active=update_active,
    )


def render_implementation_plan(request: PlanRequest, *, today: date | None = None) -> str:
    current_date = (today or date.today()).isoformat()
    title = request.title or "Implementation Plan"
    objective = request.objective or "Define and verify the requested implementation work."
    plan_id = f"{current_date}-{_safe_slug(title) or 'implementation-plan'}"
    task_section = ""
    if request.task:
        task_section = f"\n## Explicit Task Input\n\n{request.task.rstrip()}\n"

    return (
        "---\n"
        f'plan_id: "{_yaml_double_quoted_value(plan_id)}"\n'
        f'title: "{_yaml_double_quoted_value(title)}"\n'
        'status: "pending"\n'
        f'active_phase: "{DEFAULT_ACTIVE_PHASE}"\n'
        f'phase_status: "{DEFAULT_PHASE_STATUS}"\n'
        f'docs_decision: "{DEFAULT_DOCS_DECISION}"\n'
        f'created: "{current_date}"\n'
        f'updated: "{current_date}"\n'
        "---\n"
        f"# {title}\n\n"
        "## Objective\n\n"
        f"{objective.rstrip()}\n"
        f"{task_section}"
        "\n## Authority Inputs\n\n"
        "- `AGENTS.md`\n"
        "- `.codex/project-workflow.toml`\n"
        "- `project/project-state.md`\n"
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


def plan_dry_run_findings(inventory: Inventory, request: PlanRequest) -> list[Finding]:
    findings = [
        Finding("info", "plan-dry-run", "plan proposal only; no files were written"),
        _root_posture_finding(inventory),
    ]
    errors = _plan_preflight_errors(inventory, request)
    findings.append(Finding("info", "plan-target", f"would write active plan: {DEFAULT_PLAN_REL}", DEFAULT_PLAN_REL))
    findings.append(
        Finding(
            "info",
            "plan-lifecycle",
            "would update project-state lifecycle frontmatter and Current Focus managed block: operating_mode, plan_status, active_plan, active_phase, phase_status",
            inventory.state.rel_path if inventory.state else "project/project-state.md",
        )
    )
    if errors:
        findings.extend(_with_severity(errors, "warn"))
        findings.append(Finding("info", "plan-validation-posture", "dry-run refused before apply; fix refusal reasons, then rerun dry-run before writing a plan"))
        return findings
    findings.extend(_boundary_findings())
    findings.append(Finding("info", "plan-docs-decision", f"generated plan frontmatter starts with docs_decision={DEFAULT_DOCS_DECISION!r}", DEFAULT_PLAN_REL))
    findings.append(Finding("info", "plan-validation-posture", "apply would write only the active plan and project-state lifecycle frontmatter in an eligible live operating root"))
    return findings


def plan_apply_findings(inventory: Inventory, request: PlanRequest) -> list[Finding]:
    errors = _plan_preflight_errors(inventory, request)
    if errors:
        return errors

    state = inventory.state
    assert state is not None
    plan_path = inventory.root / DEFAULT_PLAN_REL
    plan_text = render_implementation_plan(request)
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
    if plan_tmp.exists():
        return [Finding("error", "plan-refused", f"temporary plan write path already exists: {plan_tmp.relative_to(inventory.root).as_posix()}")]
    if state_tmp.exists():
        return [Finding("error", "plan-refused", f"temporary state write path already exists: {state_tmp.relative_to(inventory.root).as_posix()}")]

    existed = plan_path.exists()
    try:
        plan_tmp.write_text(plan_text, encoding="utf-8")
        state_tmp.write_text(state_text, encoding="utf-8")
        plan_tmp.replace(plan_path)
        state_tmp.replace(state.path)
    except OSError as exc:
        for tmp in (plan_tmp, state_tmp):
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
        return [Finding("error", "plan-refused", f"plan apply failed before all target writes completed: {exc}", DEFAULT_PLAN_REL)]

    action = "updated existing active plan" if existed else "created active plan"
    findings = [
        Finding("info", "plan-apply", "plan apply started"),
        _root_posture_finding(inventory),
        Finding("info", "plan-written", action, DEFAULT_PLAN_REL),
        Finding("info", "plan-lifecycle-updated", "updated project-state lifecycle frontmatter: operating_mode, plan_status, active_plan, active_phase, phase_status", state.rel_path),
        Finding("info", "plan-current-focus-updated", "updated project-state Current Focus managed block from lifecycle frontmatter", state.rel_path),
        Finding("info", "plan-docs-decision", f"generated plan frontmatter starts with docs_decision={DEFAULT_DOCS_DECISION!r}", DEFAULT_PLAN_REL),
        *_boundary_findings(),
        Finding("info", "plan-validation-posture", "run check after apply to verify lifecycle state and active-plan validation"),
    ]
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


def _yaml_double_quoted_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _with_severity(findings: list[Finding], severity: str) -> list[Finding]:
    return [Finding(severity, finding.code, finding.message, finding.source, finding.line) for finding in findings]
