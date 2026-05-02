from __future__ import annotations

import re
from datetime import date
from dataclasses import dataclass
from pathlib import Path

from .inventory import Inventory, Surface
from .lifecycle_focus import sync_current_focus_block
from .models import Finding


WRITEBACK_BEGIN = "<!-- BEGIN mylittleharness-closeout-writeback v1 -->"
WRITEBACK_END = "<!-- END mylittleharness-closeout-writeback v1 -->"
STATE_COMPACTION_LINE_THRESHOLD = 250

CLOSEOUT_WRITEBACK_FIELDS = (
    "worktree_start_state",
    "task_scope",
    "docs_decision",
    "state_writeback",
    "verification",
    "commit_decision",
    "residual_risk",
    "carry_forward",
)
LIFECYCLE_WRITEBACK_FIELDS = ("active_phase", "phase_status", "last_archived_plan")
DOCS_DECISION_VALUES = {"updated", "not-needed", "uncertain"}
PHASE_STATUS_VALUES = {"pending", "active", "in_progress", "blocked", "complete", "skipped", "paused"}
PHASE_BODY_COMPLETE_STATUS = "done"
PHASE_BODY_STATUS_VALUES = {*PHASE_STATUS_VALUES, PHASE_BODY_COMPLETE_STATUS}
COMPLETED_CLOSEOUT_REQUIRED_FIELDS = ("docs_decision", "state_writeback", "verification", "commit_decision")
INCOMPLETE_CLOSEOUT_VALUES = {"", "pending", "uncertain", "unknown", "tbd", "todo"}
DEFAULT_PLAN_REL = "project/implementation-plan.md"
DEFAULT_ARCHIVE_DIR_REL = "project/archive/plans"
DEFAULT_STATE_REL = "project/project-state.md"
DEFAULT_STATE_HISTORY_DIR_REL = "project/archive/reference"

_FIELD_LABELS = {
    "worktree_start_state": ("worktree_start_state", "worktree start state"),
    "task_scope": ("task_scope", "task scope"),
    "docs_decision": ("docs_decision", "docs decision"),
    "state_writeback": ("state_writeback", "state writeback"),
    "verification": ("verification", "validation"),
    "commit_decision": ("commit_decision", "commit decision"),
    "residual_risk": ("residual_risk", "residual risk", "residual risks"),
    "carry_forward": ("carry_forward", "carry-forward", "carry forward"),
}


@dataclass(frozen=True)
class WritebackFact:
    field: str
    value: str
    source: str
    line: int


@dataclass(frozen=True)
class WritebackRequest:
    closeout: dict[str, str]
    lifecycle: dict[str, str]
    archive_active_plan: bool = False


@dataclass(frozen=True)
class PhaseBlockSpan:
    active_phase: str
    start_index: int
    end_index: int


def make_writeback_request(archive_active_plan: bool = False, **values: str | None) -> WritebackRequest:
    closeout = {
        field: _normalized_value(values.get(field))
        for field in CLOSEOUT_WRITEBACK_FIELDS
        if _normalized_value(values.get(field))
    }
    lifecycle = {
        field: _normalized_value(values.get(field))
        for field in LIFECYCLE_WRITEBACK_FIELDS
        if _normalized_value(values.get(field))
    }
    return WritebackRequest(closeout=closeout, lifecycle=lifecycle, archive_active_plan=archive_active_plan)


def canonical_phase_body_status(phase_status: str) -> str:
    return PHASE_BODY_COMPLETE_STATUS if phase_status == "complete" else phase_status


def closeout_values_are_complete(values: dict[str, str]) -> bool:
    docs_decision = values.get("docs_decision", "")
    if docs_decision not in {"updated", "not-needed"}:
        return False
    for field in COMPLETED_CLOSEOUT_REQUIRED_FIELDS:
        if not _closeout_value_is_complete(values.get(field, "")):
            return False
    return True


def state_writeback_facts(state: Surface | None) -> dict[str, WritebackFact]:
    if state is None or not state.exists:
        return {}
    lines = state.content.splitlines()
    ranges: list[tuple[int, int]] = []
    begin: int | None = None
    for index, line in enumerate(lines, start=1):
        if line.strip() == WRITEBACK_BEGIN:
            begin = index
            continue
        if line.strip() == WRITEBACK_END and begin is not None:
            ranges.append((begin, index))
            begin = None
    if not ranges:
        return {}

    start, end = ranges[-1]
    facts: dict[str, WritebackFact] = {}
    for line_number in range(start + 1, end):
        field, value = _field_line_value(lines[line_number - 1])
        if field and field in CLOSEOUT_WRITEBACK_FIELDS and value:
            facts[field] = WritebackFact(field=field, value=value, source=state.rel_path, line=line_number)
    return facts


def active_plan_body_facts(plan: Surface | None) -> dict[str, WritebackFact]:
    if plan is None or not plan.exists:
        return {}
    facts: dict[str, WritebackFact] = {}
    for line_number, line in enumerate(plan.content.splitlines(), start=1):
        field, value = _field_line_value(line)
        if field and field in CLOSEOUT_WRITEBACK_FIELDS and value:
            facts.setdefault(field, WritebackFact(field=field, value=value, source=plan.rel_path, line=line_number))
    return facts


def active_plan_phase_body_status_fact(plan: Surface | None, active_phase: str) -> WritebackFact | None:
    if plan is None or not plan.exists or not active_phase:
        return None
    block = _find_phase_block(plan.content, active_phase)
    if block is None:
        return None
    lines = plan.content.splitlines(keepends=True)
    status_index = _phase_status_line_index(lines, block)
    if status_index is None:
        return None
    status = _phase_status_line_value(lines[status_index])
    if not status:
        return None
    return WritebackFact(field="phase_status", value=status, source=plan.rel_path, line=status_index + 1)


def writeback_dry_run_findings(inventory: Inventory, request: WritebackRequest) -> list[Finding]:
    findings = [
        Finding("info", "writeback-dry-run", "writeback proposal only; no files were written"),
        Finding(
            "info",
            "writeback-boundary",
            "writeback --apply is the explicit MLH-owned closeout/state writeback path; read-only reports remain no-write",
        ),
    ]
    errors = _writeback_preflight_errors(inventory, request)
    if errors:
        findings.extend(_with_severity(errors, "warn"))
        findings.append(
            Finding(
                "info",
                "writeback-validation-posture",
                "dry-run refused before apply; fix refusal reasons, then rerun dry-run and check before relying on lifecycle close",
            )
        )
        return findings

    planned = _planned_writeback_values(inventory, request)
    findings.append(_planned_closeout_finding(planned))
    archive_plan = _archive_plan(inventory, request)
    planned_lifecycle = _planned_lifecycle_values(request, archive_plan.archive_rel_path if archive_plan else None)
    if archive_plan and not request.archive_active_plan:
        findings.append(_auto_archive_finding(inventory, apply=False))
    if archive_plan:
        findings.extend(_archive_plan_findings(inventory, archive_plan, apply=False))
    if planned_lifecycle:
        findings.append(
            Finding(
                "info",
                "writeback-lifecycle-plan",
                f"would update project-state lifecycle frontmatter: {', '.join(planned_lifecycle)}",
                inventory.state.rel_path if inventory.state else None,
            )
        )
    if inventory.state:
        projected_state_text = _state_text_with_writeback(inventory.state.content, planned, planned_lifecycle)
        findings.extend(_state_compaction_findings(_state_compaction_plan(inventory, projected_state_text), apply=False))
    findings.extend(_active_plan_sync_plan_findings(inventory, planned, planned_lifecycle, apply=False))
    findings.append(
        Finding(
            "info",
            "writeback-validation-posture",
            "after apply, run check to verify lifecycle state and stale-plan-file posture; dry-run writes no files",
        )
    )
    return findings


def writeback_apply_findings(inventory: Inventory, request: WritebackRequest) -> list[Finding]:
    errors = _writeback_preflight_errors(inventory, request)
    if errors:
        return errors

    if _should_archive_active_plan(inventory, request):
        return _writeback_archive_apply_findings(inventory, request)

    state = inventory.state
    assert state is not None
    planned = _planned_writeback_values(inventory, request)
    state_text = _state_text_with_writeback(state.content, planned, request.lifecycle)
    plan_changes: tuple[Surface, str, list[Finding]] | None = None
    if inventory.active_plan_surface and inventory.active_plan_surface.exists:
        plan = inventory.active_plan_surface
        plan_text, sync_findings = _active_plan_text_with_synced_values(
            plan,
            planned,
            request.lifecycle,
            _requested_or_current_active_phase(inventory, request.lifecycle),
        )
        plan_changes = (plan, plan_text, sync_findings)
    else:
        sync_findings = [
            Finding("info", "writeback-active-plan-skipped", "no readable active plan exists; only project-state writeback is planned")
        ]

    findings: list[Finding] = [
        Finding("info", "writeback-apply", "closeout/state writeback apply started"),
        _planned_closeout_finding(planned),
    ]
    if request.lifecycle:
        findings.append(
            Finding(
                "info",
                "writeback-lifecycle-updated",
                f"updated project-state lifecycle frontmatter: {', '.join(request.lifecycle)}",
                state.rel_path,
            )
        )

    try:
        state.path.write_text(state_text, encoding="utf-8")
        if plan_changes and plan_changes[1] != plan_changes[0].content:
            plan_changes[0].path.write_text(plan_changes[1], encoding="utf-8")
    except OSError as exc:
        return [Finding("error", "writeback-refused", f"writeback failed before all target files were written: {exc}")]

    if planned:
        findings.append(
            Finding(
                "info",
                "writeback-state-updated",
                "wrote MLH-owned closeout writeback block in project/project-state.md",
                state.rel_path,
            )
        )
    elif request.lifecycle:
        findings.append(
            Finding(
                "info",
                "writeback-state-updated",
                "updated project-state lifecycle frontmatter and Current Focus managed block without adding a closeout writeback block",
                state.rel_path,
            )
        )
    if plan_changes:
        findings.extend(plan_changes[2])
    else:
        findings.extend(sync_findings)
    findings.append(
        Finding(
            "info",
            "writeback-authority",
            "project-state frontmatter remains lifecycle authority; the MLH closeout writeback block is current closeout fact authority; active-plan frontmatter/body copies are synchronized derived metadata when present",
            state.rel_path,
        )
    )
    compaction_plan = _state_compaction_plan(inventory, state.path.read_text(encoding="utf-8"))
    findings.extend(_apply_state_compaction(inventory, compaction_plan))
    return findings


def _writeback_preflight_errors(inventory: Inventory, request: WritebackRequest) -> list[Finding]:
    errors: list[Finding] = []
    if not request.closeout and not request.lifecycle and not request.archive_active_plan:
        errors.append(Finding("error", "writeback-refused", "writeback requires at least one closeout or lifecycle field"))
    if request.archive_active_plan and any(field in request.lifecycle for field in ("active_phase", "phase_status", "last_archived_plan")):
        errors.append(
            Finding(
                "error",
                "writeback-refused",
                "--archive-active-plan owns plan_status, active_plan, and last_archived_plan lifecycle updates; do not combine it with explicit lifecycle fields",
            )
        )
    docs_decision = request.closeout.get("docs_decision")
    if docs_decision and docs_decision not in DOCS_DECISION_VALUES:
        errors.append(
            Finding(
                "error",
                "writeback-refused",
                f"docs_decision is {docs_decision!r}; expected one of: not-needed, uncertain, updated",
            )
        )
    phase_status = request.lifecycle.get("phase_status")
    if phase_status and phase_status not in PHASE_STATUS_VALUES:
        errors.append(
            Finding(
                "error",
                "writeback-refused",
                f"phase_status is {phase_status!r}; expected one of: active, blocked, complete, in_progress, paused, pending, skipped",
            )
        )
    if inventory.root_kind == "product_source_fixture":
        errors.append(
            Finding(
                "error",
                "writeback-refused",
                "target is a product-source compatibility fixture; writeback --apply is refused",
                inventory.state.rel_path if inventory.state else "project/project-state.md",
            )
        )
    elif inventory.root_kind == "fallback_or_archive":
        errors.append(
            Finding(
                "error",
                "writeback-refused",
                "target is fallback/archive or generated-output evidence; writeback --apply is refused",
                inventory.state.rel_path if inventory.state else "project/project-state.md",
            )
        )
    elif inventory.root_kind != "live_operating_root":
        errors.append(Finding("error", "writeback-refused", f"target root kind is {inventory.root_kind}; writeback requires a live operating root"))

    state = inventory.state
    if state is None or not state.exists:
        errors.append(Finding("error", "writeback-refused", "project-state.md is missing", "project/project-state.md"))
    elif not state.frontmatter.has_frontmatter:
        errors.append(
            Finding(
                "error",
                "writeback-refused",
                "project-state.md must have frontmatter before closeout/state writeback; run the bounded state-frontmatter repair first",
                state.rel_path,
            )
        )
    elif state.frontmatter.errors:
        errors.append(Finding("error", "writeback-refused", "project-state.md frontmatter is malformed", state.rel_path))
    elif not state.path.is_file():
        errors.append(Finding("error", "writeback-refused", "project-state.md is not a regular file", state.rel_path))

    plan = inventory.active_plan_surface
    if plan and plan.exists:
        if not plan.path.is_file():
            errors.append(Finding("error", "writeback-refused", "active plan is not a regular file", plan.rel_path))
        elif plan.path.is_symlink():
            errors.append(Finding("error", "writeback-refused", "active plan is a symlink; archive apply is refused", plan.rel_path))
        elif plan.frontmatter.has_frontmatter and plan.frontmatter.errors:
            errors.append(Finding("error", "writeback-refused", "active plan frontmatter is malformed", plan.rel_path))
    if request.archive_active_plan:
        errors.extend(_archive_preflight_errors(inventory))
    elif _auto_archive_active_plan(inventory, request):
        errors.extend(_archive_preflight_errors(inventory))
    return errors


def _writeback_archive_apply_findings(inventory: Inventory, request: WritebackRequest) -> list[Finding]:
    state = inventory.state
    assert state is not None
    archive_plan = _archive_plan(inventory, request)
    if archive_plan is None:
        return [Finding("error", "writeback-refused", "archive-active-plan could not determine a safe archive target")]

    planned = _planned_writeback_values(inventory, request)
    lifecycle_values = _planned_lifecycle_values(request, archive_plan.archive_rel_path)
    state_text = _state_text_with_writeback(state.content, planned, lifecycle_values)
    plan_text, sync_findings = _active_plan_text_with_synced_values(
        archive_plan.plan,
        planned,
        lifecycle_values,
        _requested_or_current_active_phase(inventory, lifecycle_values),
    )
    findings: list[Finding] = [
        Finding("info", "writeback-apply", "closeout/state writeback apply started"),
        _planned_closeout_finding(planned),
    ]
    if not request.archive_active_plan:
        findings.append(_auto_archive_finding(inventory, apply=True))
    findings.extend(_archive_plan_findings(inventory, archive_plan, apply=True))
    findings.append(
        Finding(
            "info",
            "writeback-lifecycle-updated",
            f"updated project-state lifecycle frontmatter: {', '.join(lifecycle_values)}",
            state.rel_path,
        )
    )

    state_tmp = state.path.with_name(f".{state.path.name}.writeback.tmp")
    archive_tmp = archive_plan.archive_path.with_name(f".{archive_plan.archive_path.name}.writeback.tmp")
    plan_backup = archive_plan.plan.path.with_name(f".{archive_plan.plan.path.name}.writeback.backup")
    for tmp_path, label in ((state_tmp, "temporary state write path"), (archive_tmp, "temporary archive write path"), (plan_backup, "temporary active-plan backup path")):
        if tmp_path.exists():
            return [Finding("error", "writeback-refused", f"{label} already exists: {tmp_path.relative_to(inventory.root).as_posix()}")]
    archive_created = False
    try:
        archive_plan.archive_path.parent.mkdir(parents=True, exist_ok=True)
        state_tmp.write_text(state_text, encoding="utf-8")
        archive_tmp.write_text(plan_text, encoding="utf-8")
        archive_plan.plan.path.rename(plan_backup)
        archive_tmp.replace(archive_plan.archive_path)
        archive_created = True
        try:
            state_tmp.replace(state.path)
        except OSError:
            if archive_plan.archive_path.exists():
                archive_plan.archive_path.unlink()
            if plan_backup.exists():
                plan_backup.rename(archive_plan.plan.path)
            raise
    except OSError as exc:
        for tmp_path in (state_tmp, archive_tmp):
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
        if archive_created:
            try:
                if archive_plan.archive_path.exists():
                    archive_plan.archive_path.unlink()
            except OSError:
                pass
        try:
            if plan_backup.exists() and not archive_plan.plan.path.exists():
                plan_backup.rename(archive_plan.plan.path)
        except OSError:
            pass
        return [Finding("error", "writeback-refused", f"archive-active-plan failed before all target files were written: {exc}")]

    try:
        if plan_backup.exists():
            plan_backup.unlink()
    except OSError as exc:
        findings.append(Finding("warn", "writeback-archive-backup-cleanup", f"archived active plan but could not remove temporary backup: {exc}", archive_plan.plan.rel_path))

    if planned:
        findings.append(
            Finding(
                "info",
                "writeback-state-updated",
                "wrote MLH-owned closeout writeback block in project/project-state.md",
                state.rel_path,
            )
        )
    else:
        findings.append(
            Finding(
                "info",
                "writeback-state-updated",
                "updated project-state lifecycle frontmatter and Current Focus managed block without adding a closeout writeback block",
                state.rel_path,
            )
        )
    findings.extend(sync_findings)
    findings.extend(
        [
            Finding("info", "writeback-active-plan-archived", f"moved active plan to {archive_plan.archive_rel_path}", archive_plan.archive_rel_path),
            Finding(
                "info",
                "writeback-validation-posture",
                "run check after archive apply to verify inactive lifecycle state and absence of stale-plan-file drift",
            ),
            Finding(
                "info",
                "writeback-authority",
                "project-state frontmatter remains lifecycle authority; the MLH closeout writeback block is current closeout fact authority; archived plans are historical evidence",
                state.rel_path,
            ),
        ]
    )
    compaction_plan = _state_compaction_plan(inventory, state.path.read_text(encoding="utf-8"))
    findings.extend(_apply_state_compaction(inventory, compaction_plan))
    return findings


def _planned_writeback_values(inventory: Inventory, request: WritebackRequest) -> dict[str, str]:
    current = {field: fact.value for field, fact in state_writeback_facts(inventory.state).items()}
    current.update(request.closeout)
    return {field: current[field] for field in CLOSEOUT_WRITEBACK_FIELDS if field in current}


def _planned_lifecycle_values(request: WritebackRequest, archive_rel_path: str | None) -> dict[str, str]:
    values = dict(request.lifecycle)
    if archive_rel_path:
        values.update({"plan_status": "none", "active_plan": "", "last_archived_plan": archive_rel_path})
    return values


def _planned_closeout_finding(values: dict[str, str]) -> Finding:
    summary = ", ".join(f"{field}={values[field]!r}" for field in CLOSEOUT_WRITEBACK_FIELDS if field in values)
    return Finding("info", "writeback-closeout-fields", f"closeout writeback fields: {summary or 'none'}", "project/project-state.md")


def _state_compaction_plan(inventory: Inventory, state_text: str) -> StateCompactionPlan:
    state = inventory.state
    line_count = len(state_text.splitlines())
    if line_count <= STATE_COMPACTION_LINE_THRESHOLD:
        return StateCompactionPlan(
            posture="skipped",
            reason=f"project/project-state.md is {line_count} lines; default trigger is > {STATE_COMPACTION_LINE_THRESHOLD} lines",
        )
    if inventory.root_kind != "live_operating_root":
        return StateCompactionPlan("refused", f"target root kind is {inventory.root_kind}; auto-compaction requires a live operating root")
    if state is None or not state.exists:
        return StateCompactionPlan("refused", "project/project-state.md is missing")
    if state.rel_path != DEFAULT_STATE_REL:
        return StateCompactionPlan("refused", f"unsafe state path for auto-compaction: {state.rel_path}")
    if _path_escapes_root(inventory.root, state.path):
        return StateCompactionPlan("refused", "project-state path escapes the target root")
    if not state.path.is_file():
        return StateCompactionPlan("refused", "project-state.md is not a regular file")
    if state.path.is_symlink():
        return StateCompactionPlan("refused", "project-state.md is a symlink")
    if not state.frontmatter.has_frontmatter or state.frontmatter.errors:
        return StateCompactionPlan("refused", "project-state.md frontmatter is missing or malformed")

    archive_target = _state_history_archive_target(inventory)
    if isinstance(archive_target, str):
        return StateCompactionPlan("refused", archive_target)
    archive_rel_path, archive_path = archive_target
    parsed = _parse_state_compaction_sections(state_text)
    if isinstance(parsed, str):
        return StateCompactionPlan("refused", parsed, archive_rel_path=archive_rel_path, archive_path=archive_path)
    prefix, sections = parsed
    partition = _partition_state_sections(sections)
    if isinstance(partition, str):
        return StateCompactionPlan("refused", partition, archive_rel_path=archive_rel_path, archive_path=archive_path)
    kept_sections, archived_sections, prior_history_paths = partition
    if not archived_sections:
        return StateCompactionPlan("refused", "project-state.md has no clearly archivable history sections")

    compacted_state_text = _render_compacted_state(prefix, kept_sections, [*prior_history_paths, archive_rel_path])
    archive_text = _render_state_history_archive(DEFAULT_STATE_REL, archive_rel_path, archived_sections)
    return StateCompactionPlan(
        posture="would run",
        reason=f"project/project-state.md is {line_count} lines; exceeded {STATE_COMPACTION_LINE_THRESHOLD} line default",
        archive_rel_path=archive_rel_path,
        archive_path=archive_path,
        compacted_state_text=compacted_state_text,
        archive_text=archive_text,
        kept_sections=tuple(section.title for section in kept_sections),
        archived_sections=tuple(section.title for section in archived_sections),
    )


def _state_compaction_findings(plan: StateCompactionPlan, apply: bool) -> list[Finding]:
    if apply and plan.posture == "would run":
        posture = "ran"
    else:
        posture = plan.posture
    findings = [
        Finding("info" if posture in {"would run", "ran", "skipped"} else "warn", "state-auto-compaction-posture", f"auto-compaction {posture}: {plan.reason}", DEFAULT_STATE_REL)
    ]
    if plan.archive_rel_path:
        findings.append(Finding("info", "state-auto-compaction-target", f"target archive path: {plan.archive_rel_path}", plan.archive_rel_path))
    if plan.kept_sections:
        findings.append(Finding("info", "state-auto-compaction-kept-sections", f"sections that would stay: {', '.join(plan.kept_sections)}", DEFAULT_STATE_REL))
    if plan.archived_sections:
        findings.append(
            Finding("info", "state-auto-compaction-archived-sections", f"sections that would be archived: {', '.join(plan.archived_sections)}", plan.archive_rel_path or DEFAULT_STATE_REL)
        )
    validation = (
        "after apply, run check to verify compact operating memory and archive/reference pointer posture"
        if posture in {"would run", "ran"}
        else "auto-compaction did not write; state writeback posture remains separately verifiable with check"
    )
    findings.append(Finding("info", "state-auto-compaction-validation-posture", validation, DEFAULT_STATE_REL))
    return findings


def _apply_state_compaction(inventory: Inventory, plan: StateCompactionPlan) -> list[Finding]:
    if plan.posture != "would run":
        return _state_compaction_findings(plan, apply=True)
    state = inventory.state
    assert state is not None
    assert plan.archive_path is not None
    assert plan.archive_text is not None
    assert plan.compacted_state_text is not None

    state_tmp = state.path.with_name(f".{state.path.name}.compact.tmp")
    try:
        if state_tmp.exists():
            refused = StateCompactionPlan("refused", f"temporary state compaction path already exists: {state_tmp.relative_to(inventory.root).as_posix()}", plan.archive_rel_path, plan.archive_path)
            return _state_compaction_findings(refused, apply=True)
        plan.archive_path.parent.mkdir(parents=True, exist_ok=True)
        state_tmp.write_text(plan.compacted_state_text, encoding="utf-8")
        with plan.archive_path.open("x", encoding="utf-8") as archive_file:
            archive_file.write(plan.archive_text)
        state_tmp.replace(state.path)
    except OSError as exc:
        try:
            if state_tmp.exists():
                state_tmp.unlink()
        except OSError:
            pass
        refused = StateCompactionPlan("refused", f"auto-compaction failed after state writeback: {exc}", plan.archive_rel_path, plan.archive_path)
        return _state_compaction_findings(refused, apply=True)
    return _state_compaction_findings(plan, apply=True)


def _parse_state_compaction_sections(text: str) -> tuple[str, list[StateSection]] | str:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return "project-state.md frontmatter is missing or malformed"
    frontmatter_end = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            frontmatter_end = index
            break
    if frontmatter_end is None:
        return "project-state.md frontmatter is missing or malformed"

    h1_indexes = [index for index, line in enumerate(lines) if re.match(r"^#\s+.+?\s*$", line)]
    if len(h1_indexes) != 1:
        return "unclear section boundaries: project-state.md must have exactly one top-level title"
    h1_index = h1_indexes[0]
    if h1_index <= frontmatter_end:
        return "unclear section boundaries: project-state.md title must follow frontmatter"

    h2_indexes = [index for index, line in enumerate(lines) if re.match(r"^##\s+.+?\s*$", line)]
    if not h2_indexes:
        return "unclear section boundaries: no second-level sections were found"
    if any(line.strip() for line in lines[h1_index + 1 : h2_indexes[0]]):
        return "unclear section boundaries: loose title text before the first section"

    sections: list[StateSection] = []
    for offset, start in enumerate(h2_indexes):
        end = h2_indexes[offset + 1] if offset + 1 < len(h2_indexes) else len(lines)
        title_match = re.match(r"^##\s+(.+?)\s*$", lines[start])
        if not title_match:
            return "unclear section boundaries: section heading could not be parsed"
        title = title_match.group(1).strip()
        sections.append(StateSection(title=title, start=start + 1, end=end, text="".join(lines[start:end])))
    return "".join(lines[: h2_indexes[0]]), sections


def _partition_state_sections(sections: list[StateSection]) -> tuple[list[StateSection], list[StateSection], list[str]] | str:
    keep_titles = {"Current Focus", "Repository Role Map"}
    latest_update = _latest_relevant_update_section(sections)
    kept: list[StateSection] = []
    archived: list[StateSection] = []
    prior_history_paths: list[str] = []
    for section in sections:
        if section.title == "Archived State History":
            prior_history_paths.extend(_state_history_paths(section.text))
            continue
        if section.title in keep_titles:
            kept.append(section)
            continue
        if section.title == "Notes" and len(section.text.splitlines()) <= 12:
            kept.append(section)
            continue
        if latest_update and section is latest_update:
            kept.append(section)
            continue
        if section.title == "MLH Closeout Writeback" and WRITEBACK_BEGIN in section.text and WRITEBACK_END in section.text:
            kept.append(section)
            continue
        archived.append(section)
    if "Current Focus" not in {section.title for section in kept} or "Repository Role Map" not in {section.title for section in kept}:
        return "unclear section boundaries: required Current Focus and Repository Role Map sections were not found"
    return kept, archived, prior_history_paths


def _latest_relevant_update_section(sections: list[StateSection]) -> StateSection | None:
    candidates = [
        section
        for section in sections
        if section.title.startswith(("Ad Hoc Update", "Active Plan Implementation Update", "Active Plan Validation Refresh", "Research Update"))
    ]
    return candidates[-1] if candidates else None


def _state_history_paths(text: str) -> list[str]:
    paths: list[str] = []
    for match in re.finditer(r"project/archive/reference/project-state-history-[A-Za-z0-9_.-]+\.md", text):
        path = match.group(0)
        if path not in paths:
            paths.append(path)
    return paths


def _render_compacted_state(prefix: str, kept_sections: list[StateSection], archive_paths: list[str]) -> str:
    parts = [prefix.rstrip(), ""]
    for section in kept_sections:
        parts.append(section.text.rstrip())
        parts.append("")
    parts.append("## Archived State History")
    parts.append("")
    parts.append("Archived history is reference material; current `project/project-state.md` remains operating memory authority.")
    parts.append("")
    for path in dict.fromkeys(archive_paths):
        parts.append(f"- `{path}`")
    return "\n".join(parts).rstrip() + "\n"


def _render_state_history_archive(source_rel_path: str, archive_rel_path: str, archived_sections: list[StateSection]) -> str:
    section_titles = "\n".join(f"- {section.title}" for section in archived_sections)
    archived_text = "\n\n".join(section.text.rstrip() for section in archived_sections)
    return (
        f"# Project State History - {date.today().isoformat()}\n\n"
        "## Provenance\n\n"
        f"- Source state path: `{source_rel_path}`\n"
        f"- Archive path: `{archive_rel_path}`\n"
        f"- Compaction date: {date.today().isoformat()}\n"
        f"- Reason: exceeded {STATE_COMPACTION_LINE_THRESHOLD} line default\n"
        "- Non-authority note: archived history is reference; current `project/project-state.md` remains operating memory authority.\n\n"
        "## Archived Sections\n\n"
        f"{section_titles}\n\n"
        "## Archived Content\n\n"
        f"{archived_text}\n"
    )


def _state_history_archive_target(inventory: Inventory) -> tuple[str, Path] | str:
    archive_dir_path = inventory.root / DEFAULT_STATE_HISTORY_DIR_REL
    if _path_escapes_root(inventory.root, archive_dir_path):
        return "state history archive path escapes the target root"
    for parent in _parents_between(inventory.root, archive_dir_path):
        if parent.exists() and parent.is_symlink():
            return f"state history archive directory contains a symlink segment: {parent.relative_to(inventory.root).as_posix()}"
        if parent.exists() and not parent.is_dir():
            return f"state history archive directory contains a non-directory segment: {parent.relative_to(inventory.root).as_posix()}"
    today = date.today().isoformat()
    for suffix in ("", *[f"-{index}" for index in range(2, 100)]):
        rel_path = f"{DEFAULT_STATE_HISTORY_DIR_REL}/project-state-history-{today}{suffix}.md"
        path = inventory.root / rel_path
        if _path_escapes_root(inventory.root, path):
            return "state history archive target escapes the target root"
        if not path.exists():
            return rel_path, path
    return f"state history archive target conflict: no conflict-free same-day path available under {DEFAULT_STATE_HISTORY_DIR_REL}"


@dataclass(frozen=True)
class ArchivePlan:
    plan: Surface
    archive_rel_path: str
    archive_path: Path


@dataclass(frozen=True)
class StateSection:
    title: str
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class StateCompactionPlan:
    posture: str
    reason: str
    archive_rel_path: str | None = None
    archive_path: Path | None = None
    compacted_state_text: str | None = None
    archive_text: str | None = None
    kept_sections: tuple[str, ...] = ()
    archived_sections: tuple[str, ...] = ()


def _archive_plan(inventory: Inventory, request: WritebackRequest) -> ArchivePlan | None:
    if not _should_archive_active_plan(inventory, request):
        return None
    plan = inventory.active_plan_surface
    if plan is None or not plan.exists:
        return None
    rel_path = f"{DEFAULT_ARCHIVE_DIR_REL}/{date.today().isoformat()}-{_archive_slug(plan)}.md"
    return ArchivePlan(plan=plan, archive_rel_path=rel_path, archive_path=inventory.root / rel_path)


def _should_archive_active_plan(inventory: Inventory, request: WritebackRequest) -> bool:
    return request.archive_active_plan or _auto_archive_active_plan(inventory, request)


def _auto_archive_active_plan(inventory: Inventory, request: WritebackRequest) -> bool:
    if request.archive_active_plan:
        return False
    if request.lifecycle.get("phase_status") != "complete":
        return False
    return closeout_values_are_complete(_planned_writeback_values(inventory, request))


def _auto_archive_finding(inventory: Inventory, apply: bool) -> Finding:
    verb = "archiving" if apply else "would archive"
    return Finding(
        "info",
        "writeback-auto-archive-active-plan",
        f"phase_status complete plus completed closeout facts {verb} the active plan through the archive-active-plan safety path",
        inventory.active_plan_surface.rel_path if inventory.active_plan_surface else DEFAULT_PLAN_REL,
    )


def _archive_plan_findings(inventory: Inventory, archive_plan: ArchivePlan, apply: bool) -> list[Finding]:
    verb = "archived" if apply else "would archive"
    return [
        Finding("info", "writeback-archive-active-plan", f"active plan: {archive_plan.plan.rel_path}", archive_plan.plan.rel_path),
        Finding("info", "writeback-archive-target", f"{verb} active plan to {archive_plan.archive_rel_path}", archive_plan.archive_rel_path),
        Finding(
            "info",
            "writeback-archive-boundary",
            "archive-active-plan moves only the active plan and updates project-state lifecycle frontmatter plus the Current Focus managed block; it does not stage, commit, clean archives, repair files, or delete unrelated content",
            inventory.state.rel_path if inventory.state else None,
        ),
    ]


def _archive_preflight_errors(inventory: Inventory) -> list[Finding]:
    errors: list[Finding] = []
    state = inventory.state
    data = state.frontmatter.data if state and state.exists else {}
    plan_status = str(data.get("plan_status") or "")
    active_plan_value = str(data.get("active_plan") or "")
    manifest_plan = _manifest_memory_value(inventory, "plan_file", DEFAULT_PLAN_REL)
    archive_dir = _manifest_memory_value(inventory, "archive_dir", DEFAULT_ARCHIVE_DIR_REL)

    if plan_status != "active":
        errors.append(Finding("error", "writeback-refused", f"archive-active-plan requires plan_status active; current plan_status is {plan_status or '<empty>'!r}", state.rel_path if state else None))
    if not active_plan_value:
        errors.append(Finding("error", "writeback-refused", "archive-active-plan requires active_plan in project-state frontmatter", state.rel_path if state else None))
    if _normalize_rel(manifest_plan) != DEFAULT_PLAN_REL:
        errors.append(Finding("error", "writeback-refused", f"non-default manifest plan_file is refused for archive-active-plan: {manifest_plan}", inventory.manifest_surface.rel_path if inventory.manifest_surface else None))
    if _normalize_rel(active_plan_value) != DEFAULT_PLAN_REL:
        errors.append(Finding("error", "writeback-refused", f"active_plan must be {DEFAULT_PLAN_REL} for archive-active-plan; got {active_plan_value or '<empty>'}", state.rel_path if state else None))
    if _normalize_rel(archive_dir) != DEFAULT_ARCHIVE_DIR_REL:
        errors.append(Finding("error", "writeback-refused", f"non-default archive_dir is refused for archive-active-plan: {archive_dir}", inventory.manifest_surface.rel_path if inventory.manifest_surface else None))

    plan = inventory.active_plan_surface
    if plan is None or not plan.exists:
        errors.append(Finding("error", "writeback-refused", f"active plan file is missing: {active_plan_value or DEFAULT_PLAN_REL}", active_plan_value or DEFAULT_PLAN_REL))
    elif _path_escapes_root(inventory.root, plan.path):
        errors.append(Finding("error", "writeback-refused", "active plan path escapes the target root", plan.rel_path))

    archive_dir_path = inventory.root / DEFAULT_ARCHIVE_DIR_REL
    for parent in _parents_between(inventory.root, archive_dir_path):
        if parent.exists() and parent.is_symlink():
            errors.append(Finding("error", "writeback-refused", f"archive directory contains a symlink segment: {parent.relative_to(inventory.root).as_posix()}"))
        elif parent.exists() and not parent.is_dir():
            errors.append(Finding("error", "writeback-refused", f"archive directory contains a non-directory segment: {parent.relative_to(inventory.root).as_posix()}"))

    archive_plan = _archive_plan(inventory, WritebackRequest(closeout={}, lifecycle={}, archive_active_plan=True))
    if archive_plan:
        if _path_escapes_root(inventory.root, archive_plan.archive_path):
            errors.append(Finding("error", "writeback-refused", "archive target escapes the target root", archive_plan.archive_rel_path))
        elif archive_plan.archive_path.exists():
            errors.append(Finding("error", "writeback-refused", f"archive target already exists: {archive_plan.archive_rel_path}", archive_plan.archive_rel_path))
    return errors


def _archive_slug(plan: Surface) -> str:
    raw = str(plan.frontmatter.data.get("title") or _first_heading(plan.content) or "implementation-plan")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", raw.strip().lower()).strip("-")
    return slug or "implementation-plan"


def _first_heading(text: str) -> str | None:
    for line in text.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()
    return None


def _manifest_memory_value(inventory: Inventory, key: str, default: str) -> str:
    memory = inventory.manifest.get("memory", {}) if isinstance(inventory.manifest, dict) else {}
    return str(memory.get(key) or default)


def _normalize_rel(value: str) -> str:
    return value.replace("\\", "/").strip("/")


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
            current.relative_to(root_resolved)
        except ValueError:
            break
        if current == root_resolved:
            break
        parents.append(current)
        current = current.parent
    return list(reversed(parents))


def _active_plan_sync_plan_findings(
    inventory: Inventory,
    closeout_values: dict[str, str],
    lifecycle_values: dict[str, str],
    apply: bool,
) -> list[Finding]:
    plan = inventory.active_plan_surface
    if not plan or not plan.exists:
        return [Finding("info", "writeback-active-plan-skipped", "no readable active plan exists")]
    _, findings = _active_plan_text_with_synced_values(
        plan,
        closeout_values,
        lifecycle_values,
        _requested_or_current_active_phase(inventory, lifecycle_values),
    )
    if apply:
        return findings
    return [
        Finding(finding.severity, finding.code.replace("updated", "plan"), finding.message.replace("updated", "would update"), finding.source, finding.line)
        for finding in findings
    ]


def _state_text_with_writeback(text: str, closeout_values: dict[str, str], lifecycle_values: dict[str, str]) -> str:
    updated = _update_frontmatter_scalars(text, lifecycle_values, only_existing=False) if lifecycle_values else text
    if closeout_values:
        updated = _replace_or_append_writeback_block(updated, closeout_values)
    return sync_current_focus_block(updated)


def _active_plan_text_with_synced_values(
    plan: Surface,
    closeout_values: dict[str, str],
    lifecycle_values: dict[str, str],
    active_phase: str,
) -> tuple[str, list[Finding]]:
    text = plan.content
    findings: list[Finding] = []
    frontmatter_updates = {**closeout_values, **lifecycle_values}
    if "phase_status" in lifecycle_values:
        frontmatter_updates["status"] = lifecycle_values["phase_status"]
    if plan.frontmatter.has_frontmatter:
        updated_text, updated_keys = _update_existing_frontmatter_scalars(text, frontmatter_updates)
        text = updated_text
        if updated_keys:
            findings.append(
                Finding(
                    "info",
                    "writeback-active-plan-frontmatter-updated",
                    f"updated active-plan frontmatter keys: {', '.join(updated_keys)}",
                    plan.rel_path,
                )
            )
        else:
            findings.append(
                Finding(
                    "info",
                    "writeback-active-plan-frontmatter-skipped",
                    "active-plan frontmatter had no matching closeout/lifecycle keys to synchronize",
                    plan.rel_path,
                )
            )
    else:
        findings.append(
            Finding(
                "info",
                "writeback-active-plan-frontmatter-skipped",
                "active plan has no frontmatter; no diagnostic frontmatter copy was synchronized",
                plan.rel_path,
            )
        )

    body_text, body_fields = _update_exact_body_fields(text, closeout_values)
    text = body_text
    if body_fields:
        findings.append(
            Finding(
                "info",
                "writeback-active-plan-body-updated",
                f"updated active-plan closeout body fields: {', '.join(body_fields)}",
                plan.rel_path,
            )
        )
    else:
        findings.append(
            Finding(
                "info",
                "writeback-active-plan-body-skipped",
                "active-plan body had no matching exact closeout field lines to synchronize",
                plan.rel_path,
            )
        )
    phase_text, phase_finding = _active_plan_text_with_phase_body_status(text, plan.rel_path, active_phase, lifecycle_values)
    text = phase_text
    if phase_finding:
        findings.append(phase_finding)
    return text, findings


def _active_plan_text_with_phase_body_status(
    text: str,
    rel_path: str,
    active_phase: str,
    lifecycle_values: dict[str, str],
) -> tuple[str, Finding | None]:
    phase_status = lifecycle_values.get("phase_status")
    if not phase_status:
        return text, None
    if not active_phase:
        return (
            text,
            Finding(
                "info",
                "writeback-active-plan-phase-block-skipped",
                "phase_status was written but no active_phase was available for active-plan phase body synchronization",
                rel_path,
            ),
        )
    block = _find_phase_block(text, active_phase)
    if block is None:
        return (
            text,
            Finding(
                "info",
                "writeback-active-plan-phase-block-skipped",
                f"active-plan phase block {active_phase!r} was not found; no phase status body copy was synchronized",
                rel_path,
            ),
        )
    lines = text.splitlines(keepends=True)
    status_index = _phase_status_line_index(lines, block)
    if status_index is None:
        return (
            text,
            Finding(
                "info",
                "writeback-active-plan-phase-block-skipped",
                f"active-plan phase block {active_phase!r} has no status line to synchronize",
                rel_path,
            ),
        )
    current = _phase_status_line_value(lines[status_index])
    desired = canonical_phase_body_status(phase_status)
    if current == desired:
        return (
            text,
            Finding(
                "info",
                "writeback-active-plan-phase-block-skipped",
                f"active-plan phase block {active_phase!r} status body copy already records {desired!r}",
                rel_path,
                status_index + 1,
            ),
        )
    lines[status_index] = _updated_phase_status_line(lines[status_index], desired)
    return (
        "".join(lines),
        Finding(
            "info",
            "writeback-active-plan-phase-block-updated",
            f"updated active-plan phase block {active_phase!r} status body copy to {desired!r}",
            rel_path,
            status_index + 1,
        ),
    )


def _requested_or_current_active_phase(inventory: Inventory, lifecycle_values: dict[str, str]) -> str:
    if lifecycle_values.get("active_phase"):
        return lifecycle_values["active_phase"]
    state = inventory.state
    if state and state.exists:
        value = state.frontmatter.data.get("active_phase")
        if value not in (None, ""):
            return str(value)
    plan = inventory.active_plan_surface
    if plan and plan.exists and plan.frontmatter.has_frontmatter:
        value = plan.frontmatter.data.get("active_phase")
        if value not in (None, ""):
            return str(value)
    return ""


def _find_phase_block(text: str, active_phase: str) -> PhaseBlockSpan | None:
    target = active_phase.strip()
    if not target:
        return None
    lines = text.splitlines(keepends=True)
    headings: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^(#{2,6})\s+(.+?)\s*#*\s*(?:\r?\n)?$", line)
        if match:
            headings.append((index, len(match.group(1)), match.group(2).strip()))
    candidates: list[PhaseBlockSpan] = []
    for heading_index, (start, level, title) in enumerate(headings):
        end = len(lines)
        for next_start, next_level, _next_title in headings[heading_index + 1 :]:
            if next_level <= level:
                end = next_start
                break
        block = PhaseBlockSpan(active_phase=target, start_index=start, end_index=end)
        if _phase_heading_matches(title, target) or _phase_block_has_id(lines, block, target):
            candidates.append(block)
    if not candidates:
        return None
    return min(candidates, key=lambda block: (block.end_index - block.start_index, block.start_index))


def _phase_heading_matches(title: str, active_phase: str) -> bool:
    normalized_title = _strip_inline_code(title).casefold()
    normalized_phase = active_phase.casefold()
    return normalized_title == normalized_phase or normalized_phase in normalized_title


def _phase_block_has_id(lines: list[str], block: PhaseBlockSpan, active_phase: str) -> bool:
    for line in lines[block.start_index + 1 : block.end_index]:
        match = re.match(r"^\s*[-*]\s*id\s*:\s*(.+?)\s*(?:\r?\n)?$", line, re.IGNORECASE)
        if match and _strip_inline_code(match.group(1).strip()) == active_phase:
            return True
    return False


def _phase_status_line_index(lines: list[str], block: PhaseBlockSpan) -> int | None:
    for index in range(block.start_index + 1, block.end_index):
        if _phase_status_line_match(lines[index]):
            return index
    return None


def _phase_status_line_value(line: str) -> str | None:
    match = _phase_status_line_match(line)
    if not match:
        return None
    return _strip_inline_code(match.group("value").strip())


def _updated_phase_status_line(line: str, desired: str) -> str:
    match = _phase_status_line_match(line)
    if not match:
        return line
    newline = match.group("newline") or ""
    tick = "`" if match.group("open") or match.group("close") else ""
    return f"{match.group('prefix')}{tick}{desired}{tick}{match.group('suffix')}{newline}"


def _phase_status_line_match(line: str) -> re.Match[str] | None:
    return re.match(
        r"^(?P<prefix>\s*[-*]\s*status\s*:\s*)(?P<open>`?)(?P<value>[^`\r\n]+?)(?P<close>`?)(?P<suffix>\s*)(?P<newline>\r?\n)?$",
        line,
        re.IGNORECASE,
    )


def _strip_inline_code(value: str) -> str:
    stripped = _strip_quotes(value.strip())
    if stripped.startswith("`") and stripped.endswith("`") and len(stripped) >= 2:
        return stripped[1:-1].strip()
    return stripped.strip()


def _replace_or_append_writeback_block(text: str, closeout_values: dict[str, str]) -> str:
    block = _render_writeback_block(closeout_values)
    begin_index = text.rfind(WRITEBACK_BEGIN)
    end_index = text.rfind(WRITEBACK_END)
    if begin_index != -1 and end_index != -1 and end_index > begin_index:
        end_after = end_index + len(WRITEBACK_END)
        if end_after < len(text) and text[end_after : end_after + 2] == "\r\n":
            end_after += 2
        elif end_after < len(text) and text[end_after : end_after + 1] == "\n":
            end_after += 1
        return text[:begin_index] + block + text[end_after:]

    separator = "" if text.endswith(("\n", "\r")) else "\n"
    return text + separator + "\n## MLH Closeout Writeback\n\n" + block


def _render_writeback_block(closeout_values: dict[str, str]) -> str:
    lines = [WRITEBACK_BEGIN]
    for field in CLOSEOUT_WRITEBACK_FIELDS:
        value = closeout_values.get(field)
        if value:
            lines.append(f"- {field}: {value}")
    lines.append(WRITEBACK_END)
    return "\n".join(lines) + "\n"


def _update_existing_frontmatter_scalars(text: str, updates: dict[str, str]) -> tuple[str, list[str]]:
    if not updates:
        return text, []
    new_text = _update_frontmatter_scalars(text, updates, only_existing=True)
    changed = [
        key
        for key, value in updates.items()
        if _frontmatter_value(text, key) not in (None, value) and _frontmatter_value(new_text, key) == value
    ]
    return new_text, changed


def _update_frontmatter_scalars(text: str, updates: dict[str, str], only_existing: bool) -> str:
    if not updates:
        return text
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

    if not only_existing:
        missing = [key for key in updates if key not in seen]
        if missing:
            insert_lines = [f'{key}: "{_yaml_double_quoted_value(updates[key])}"\n' for key in missing]
            lines[closing_index:closing_index] = insert_lines
    return "".join(lines)


def _frontmatter_value(text: str, key: str) -> str | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        match = re.match(rf"^{re.escape(key)}:\s*(.*?)\s*$", line)
        if match:
            return _strip_quotes(match.group(1))
    return None


def _update_exact_body_fields(text: str, closeout_values: dict[str, str]) -> tuple[str, list[str]]:
    if not closeout_values:
        return text, []
    lines = text.splitlines(keepends=True)
    updated_fields: list[str] = []
    for index, line in enumerate(lines):
        field, _value = _field_line_value(line)
        if field not in closeout_values:
            continue
        prefix_match = _field_line_prefix(field, line)
        if not prefix_match:
            continue
        newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        lines[index] = f"{prefix_match}{closeout_values[field]}{newline}"
        if field not in updated_fields:
            updated_fields.append(field)
    return "".join(lines), updated_fields


def _field_line_value(line: str) -> tuple[str | None, str | None]:
    compact = line.strip()
    for field, labels in _FIELD_LABELS.items():
        for label in labels:
            match = re.match(rf"^[-*]\s*`?{re.escape(label)}`?\s*:\s*(.+?)\s*$", compact, re.IGNORECASE)
            if match:
                return field, _normalized_value(match.group(1))
    return None, None


def _field_line_prefix(field: str, line: str) -> str | None:
    for label in _FIELD_LABELS.get(field, (field,)):
        match = re.match(rf"^(\s*[-*]\s*`?{re.escape(label)}`?\s*:\s*).*$", line.rstrip("\r\n"), re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _with_severity(findings: list[Finding], severity: str) -> list[Finding]:
    return [Finding(severity, finding.code, finding.message, finding.source, finding.line) for finding in findings]


def _normalized_value(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).rstrip(".")


def _closeout_value_is_complete(value: object) -> bool:
    normalized = _normalized_value(value).casefold()
    return normalized not in INCOMPLETE_CLOSEOUT_VALUES


def _strip_quotes(value: str) -> str:
    raw = value.strip()
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    return raw


def _yaml_double_quoted_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
