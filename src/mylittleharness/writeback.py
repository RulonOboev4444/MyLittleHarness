from __future__ import annotations

import re
from datetime import date
from dataclasses import dataclass, replace
from pathlib import Path

from .atomic_files import AtomicFileDelete, AtomicFileWrite, FileTransactionError, apply_file_transaction
from .inventory import Inventory, Surface
from .lifecycle_focus import sync_current_focus_block
from .memory_hygiene import RelationshipUpdatePlan, incubation_closeout_plan
from .models import Finding
from .roadmap import ROADMAP_STATUS_VALUES, RoadmapPlan, make_roadmap_request, roadmap_item_fields, roadmap_plans_for_requests


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
CLOSEOUT_IDENTITY_FIELDS = ("plan_id", "active_plan", "archived_plan")
LIFECYCLE_WRITEBACK_FIELDS = ("active_phase", "phase_status", "last_archived_plan", "product_source_root")
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
_CLOSEOUT_BODY_SECTION_TITLES = frozenset(
    {
        "closeout",
        "closeout fields",
        "closeout facts",
        "closeout summary",
        "closeout writeback",
        "mlh closeout",
        "mlh closeout fields",
        "mlh closeout facts",
        "mlh closeout summary",
        "mlh closeout writeback",
    }
)

_FIELD_LABELS = {
    "plan_id": ("plan_id", "plan id"),
    "active_plan": ("active_plan", "active plan"),
    "archived_plan": ("archived_plan", "archived plan"),
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
class CloseoutIdentity:
    plan_id: str = ""
    active_plan: str = ""
    archived_plan: str = ""


@dataclass(frozen=True)
class CloseoutWritebackPlan:
    values: dict[str, str]
    identity: CloseoutIdentity
    decision: str
    message: str
    errors: tuple[Finding, ...] = ()


@dataclass(frozen=True)
class WritebackRequest:
    closeout: dict[str, str]
    lifecycle: dict[str, str]
    archive_active_plan: bool = False
    compact_only: bool = False
    from_active_plan: bool = False
    roadmap_item: str = ""
    roadmap_status: str = ""
    input_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class RoadmapWritebackPlan:
    target_rel: str
    target_path: Path
    item_plans: tuple[RoadmapPlan, ...]

    @property
    def current_text(self) -> str:
        return self.item_plans[0].current_text if self.item_plans else ""

    @property
    def updated_text(self) -> str:
        return self.item_plans[-1].updated_text if self.item_plans else ""

    @property
    def item_ids(self) -> tuple[str, ...]:
        return tuple(plan.item_id for plan in self.item_plans)


@dataclass(frozen=True)
class RouteRetargetPlan:
    source_rel: str
    target_path: Path
    current_text: str
    updated_text: str
    changed_fields: tuple[str, ...]


@dataclass(frozen=True)
class PhaseBlockSpan:
    active_phase: str
    start_index: int
    end_index: int


@dataclass(frozen=True)
class BodySectionSpan:
    start_index: int
    end_index: int


def make_writeback_request(
    archive_active_plan: bool = False,
    compact_only: bool = False,
    from_active_plan: bool = False,
    roadmap_item: str | None = None,
    roadmap_status: str | None = None,
    **values: str | None,
) -> WritebackRequest:
    input_errors = tuple(_text_field_input_errors(values))
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
    return WritebackRequest(
        closeout=closeout,
        lifecycle=lifecycle,
        archive_active_plan=archive_active_plan,
        compact_only=compact_only,
        from_active_plan=from_active_plan,
        roadmap_item=_normalized_item_id(roadmap_item),
        roadmap_status=_normalized_status(roadmap_status),
        input_errors=input_errors,
    )


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
    return _state_writeback_block_facts(state, CLOSEOUT_WRITEBACK_FIELDS)


def state_writeback_identity_facts(state: Surface | None) -> dict[str, WritebackFact]:
    return _state_writeback_block_facts(state, CLOSEOUT_IDENTITY_FIELDS)


def _state_writeback_block_facts(state: Surface | None, allowed_fields: tuple[str, ...]) -> dict[str, WritebackFact]:
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
    allowed = set(allowed_fields)
    facts: dict[str, WritebackFact] = {}
    for line_number in range(start + 1, end):
        field, value = _field_line_value(lines[line_number - 1])
        if field and field in allowed and value:
            facts[field] = WritebackFact(field=field, value=value, source=state.rel_path, line=line_number)
    return facts


def active_plan_body_facts(plan: Surface | None) -> dict[str, WritebackFact]:
    if plan is None or not plan.exists:
        return {}
    lines = plan.content.splitlines()
    facts: dict[str, WritebackFact] = {}
    for index in _closeout_body_field_line_indexes(plan.content):
        line_number = index + 1
        line = lines[index]
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
    request, harvest_findings, harvest_errors = _writeback_request_with_active_plan_facts(inventory, request, apply=False)
    findings.extend(harvest_findings)
    errors = _writeback_preflight_errors(inventory, request)
    errors.extend(harvest_errors)
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

    if request.compact_only:
        findings.append(
            Finding(
                "info",
                "writeback-compact-only",
                "compact-only proposal checks safe project-state history archival without changing closeout fields, lifecycle frontmatter, or active-plan copies",
                DEFAULT_STATE_REL,
            )
        )
        findings.extend(state_compaction_dry_run_findings(inventory))
        findings.append(
            Finding(
                "info",
                "writeback-validation-posture",
                "dry-run writes no files; after compact-only apply, run check to verify compact operating memory and archive/reference pointer posture",
            )
        )
        return findings

    archive_plan = _archive_plan(inventory, request)
    closeout_plan = _closeout_writeback_plan(inventory, request, archive_plan.archive_rel_path if archive_plan else None)
    planned = closeout_plan.values
    findings.append(_planned_closeout_finding(planned))
    findings.extend(_closeout_writeback_plan_findings(closeout_plan, apply=False))
    planned_lifecycle = _planned_lifecycle_values(request, archive_plan.archive_rel_path if archive_plan else None)
    active_plan_lifecycle = _active_plan_lifecycle_values(inventory, request, planned_lifecycle)
    roadmap_plan, roadmap_errors = _writeback_roadmap_plan(inventory, request, archive_plan.archive_rel_path if archive_plan else None)
    if roadmap_errors:
        findings.extend(_with_severity(roadmap_errors, "warn"))
        findings.append(
            Finding(
                "info",
                "writeback-validation-posture",
                "dry-run refused before apply; fix refusal reasons, then rerun dry-run and check before relying on lifecycle close",
            )
        )
        return findings
    incubation_plan, incubation_errors = _writeback_incubation_plan(inventory, request, archive_plan.archive_rel_path if archive_plan else None)
    if incubation_errors:
        findings.extend(_with_severity(incubation_errors, "warn"))
        findings.append(
            Finding(
                "info",
                "writeback-validation-posture",
                "dry-run refused before apply; fix relationship writeback refusal reasons, then rerun dry-run and check before relying on lifecycle close",
            )
        )
        return findings
    route_retarget_plans = _archive_route_retarget_plans(
        inventory,
        archive_plan.archive_rel_path if archive_plan else "",
        skip_rels=_incubation_plan_source_rels(incubation_plan),
    )
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
        findings.append(_phase_execution_boundary_finding(planned_lifecycle, inventory.state.rel_path if inventory.state else None, apply=False))
        ready_finding = _ready_for_closeout_boundary_finding(planned_lifecycle, inventory.state.rel_path if inventory.state else None, apply=False)
        if ready_finding:
            findings.append(ready_finding)
    if inventory.state:
        projected_state_text = _state_text_with_writeback(inventory.state.content, planned, planned_lifecycle, closeout_plan.identity)
        findings.extend(_state_compaction_findings(_state_compaction_plan(inventory, projected_state_text), apply=False))
    findings.extend(_active_plan_sync_plan_findings(inventory, planned, active_plan_lifecycle, apply=False))
    if roadmap_plan:
        findings.extend(_writeback_roadmap_findings(roadmap_plan, apply=False))
    if incubation_plan:
        findings.extend(_writeback_incubation_findings(incubation_plan, apply=False))
    if route_retarget_plans:
        findings.extend(_archive_route_retarget_findings(route_retarget_plans, apply=False))
    findings.append(
        Finding(
            "info",
            "writeback-validation-posture",
            "after apply, run check to verify lifecycle state and stale-plan-file posture; dry-run writes no files",
        )
    )
    return findings


def writeback_apply_findings(inventory: Inventory, request: WritebackRequest) -> list[Finding]:
    request, harvest_findings, harvest_errors = _writeback_request_with_active_plan_facts(inventory, request, apply=True)
    if harvest_errors:
        return harvest_errors
    errors = _writeback_preflight_errors(inventory, request)
    if errors:
        return errors

    if request.compact_only:
        findings = [
            Finding("info", "writeback-apply", "compact-only writeback apply started"),
            Finding(
                "info",
                "writeback-compact-only",
                "compact-only apply may write only project/project-state.md and a project/archive/reference state-history archive",
                DEFAULT_STATE_REL,
            ),
        ]
        findings.extend(state_compaction_apply_findings(inventory))
        return findings

    if _should_archive_active_plan(inventory, request):
        archive_findings = _writeback_archive_apply_findings(inventory, request)
        if harvest_findings and not any(finding.severity == "error" for finding in archive_findings):
            return [*harvest_findings, *archive_findings]
        return archive_findings

    state = inventory.state
    assert state is not None
    closeout_plan = _closeout_writeback_plan(inventory, request, None)
    planned = closeout_plan.values
    roadmap_plan, roadmap_errors = _writeback_roadmap_plan(inventory, request, None)
    if roadmap_errors:
        return roadmap_errors
    state_text = _state_text_with_writeback(state.content, planned, request.lifecycle, closeout_plan.identity)
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
    state_tmp = state.path.with_name(f".{state.path.name}.writeback.tmp")
    state_backup = state.path.with_name(f".{state.path.name}.writeback.backup")
    plan_tmp = (
        plan_changes[0].path.with_name(f".{plan_changes[0].path.name}.writeback.tmp")
        if plan_changes and plan_changes[1] != plan_changes[0].content
        else None
    )
    plan_backup = (
        plan_changes[0].path.with_name(f".{plan_changes[0].path.name}.writeback.backup")
        if plan_tmp and plan_changes
        else None
    )
    roadmap_tmp = _roadmap_writeback_tmp(roadmap_plan)
    roadmap_backup = _roadmap_writeback_backup(roadmap_plan) if roadmap_tmp else None
    for candidate, label in (
        (state_tmp, "temporary state write path"),
        (state_backup, "temporary state backup path"),
        (plan_tmp, "temporary active-plan write path"),
        (plan_backup, "temporary active-plan backup path"),
        (roadmap_tmp, "temporary roadmap write path"),
        (roadmap_backup, "temporary roadmap backup path"),
    ):
        if candidate and candidate.exists():
            return [Finding("error", "writeback-refused", f"{label} already exists: {candidate.relative_to(inventory.root).as_posix()}")]

    findings: list[Finding] = [
        Finding("info", "writeback-apply", "closeout/state writeback apply started"),
        _planned_closeout_finding(planned),
    ]
    findings.extend(harvest_findings)
    findings.extend(_closeout_writeback_plan_findings(closeout_plan, apply=True))
    if request.lifecycle:
        findings.append(
            Finding(
                "info",
                "writeback-lifecycle-updated",
                f"updated project-state lifecycle frontmatter: {', '.join(request.lifecycle)}",
                state.rel_path,
            )
        )
        findings.append(_phase_execution_boundary_finding(request.lifecycle, state.rel_path, apply=True))
        ready_finding = _ready_for_closeout_boundary_finding(request.lifecycle, state.rel_path, apply=True)
        if ready_finding:
            findings.append(ready_finding)

    operations: list[AtomicFileWrite] = [AtomicFileWrite(state.path, state_tmp, state_text, state_backup)]
    if plan_tmp and plan_backup and plan_changes:
        operations.append(AtomicFileWrite(plan_changes[0].path, plan_tmp, plan_changes[1], plan_backup))
    if roadmap_tmp and roadmap_backup and roadmap_plan:
        operations.append(AtomicFileWrite(roadmap_plan.target_path, roadmap_tmp, roadmap_plan.updated_text, roadmap_backup))
    try:
        cleanup_warnings = apply_file_transaction(operations)
    except FileTransactionError as exc:
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
    if roadmap_plan:
        findings.extend(_writeback_roadmap_findings(roadmap_plan, apply=True))
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "writeback-backup-cleanup", warning, state.rel_path))
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
    for error in request.input_errors:
        errors.append(Finding("error", "writeback-refused", error))
    if request.from_active_plan and request.compact_only:
        errors.append(Finding("error", "writeback-refused", "--from-active-plan cannot be combined with --compact-only"))
    if request.compact_only and (request.closeout or request.lifecycle or request.archive_active_plan or request.roadmap_item or request.roadmap_status):
        errors.append(Finding("error", "writeback-refused", "--compact-only cannot be combined with closeout fields, lifecycle fields, --archive-active-plan, or roadmap sync fields"))
    if not request.closeout and not request.lifecycle and not request.archive_active_plan and not request.compact_only:
        errors.append(Finding("error", "writeback-refused", "writeback requires at least one closeout or lifecycle field"))
    if request.roadmap_status and not request.roadmap_item:
        errors.append(Finding("error", "writeback-refused", "--roadmap-status requires --roadmap-item"))
    if request.roadmap_status and request.roadmap_status not in ROADMAP_STATUS_VALUES:
        errors.append(Finding("error", "writeback-refused", f"--roadmap-status must be one of: {', '.join(sorted(ROADMAP_STATUS_VALUES))}"))
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
    product_source_root = request.lifecycle.get("product_source_root")
    if product_source_root:
        errors.extend(_product_source_root_errors(inventory, product_source_root))
    errors.extend(_writeback_root_state_preflight_errors(inventory))
    if request.compact_only:
        return errors
    errors.extend(_closeout_writeback_plan(inventory, request, None).errors)

    plan = inventory.active_plan_surface
    if plan and plan.exists:
        if not plan.path.is_file():
            errors.append(Finding("error", "writeback-refused", "active plan is not a regular file", plan.rel_path))
        elif plan.path.is_symlink():
            errors.append(Finding("error", "writeback-refused", "active plan is a symlink; archive apply is refused", plan.rel_path))
        elif plan.frontmatter.has_frontmatter and plan.frontmatter.errors:
            errors.append(Finding("error", "writeback-refused", "active plan frontmatter is malformed", plan.rel_path))
    if request.archive_active_plan:
        errors.extend(_archive_preflight_errors(inventory, request))
    return errors


def _writeback_request_with_active_plan_facts(
    inventory: Inventory,
    request: WritebackRequest,
    apply: bool,
) -> tuple[WritebackRequest, list[Finding], list[Finding]]:
    if not request.from_active_plan:
        return request, [], []
    plan = inventory.active_plan_surface
    source = plan.rel_path if plan else DEFAULT_PLAN_REL
    if plan is None or not plan.exists:
        return request, [], [
            Finding("error", "writeback-refused", "--from-active-plan requires a readable active plan", DEFAULT_PLAN_REL)
        ]
    facts = active_plan_body_facts(plan)
    state_fallback = False
    finding_source = source
    if facts:
        harvested = {field: fact.value for field, fact in facts.items()}
    else:
        harvested, fallback_errors = _state_closeout_authority_facts(inventory)
        if fallback_errors:
            return request, [], fallback_errors
        state_fallback = True
        finding_source = inventory.state.rel_path if inventory.state else DEFAULT_STATE_REL
    merged = dict(harvested)
    merged.update(request.closeout)
    fields = ", ".join(field for field in CLOSEOUT_WRITEBACK_FIELDS if field in harvested)
    override_fields = ", ".join(field for field in CLOSEOUT_WRITEBACK_FIELDS if field in request.closeout and field in harvested)
    verb = "harvested" if apply else "would harvest"
    origin = "project-state closeout authority" if state_fallback else "active plan"
    message = f"{verb} closeout facts from {origin}: {fields}"
    if override_fields:
        message += f"; same-request fields override harvested values: {override_fields}"
    return (
        replace(request, closeout=_ordered_closeout_values(merged)),
        [Finding("info", "writeback-from-active-plan", message, finding_source)],
        [],
    )


def _state_closeout_authority_facts(inventory: Inventory) -> tuple[dict[str, str], list[Finding]]:
    facts = state_writeback_facts(inventory.state)
    harvested = {field: fact.value for field, fact in facts.items()}
    source = inventory.state.rel_path if inventory.state else DEFAULT_STATE_REL
    if not harvested:
        return {}, [
            Finding(
                "error",
                "writeback-refused",
                "--from-active-plan found no closeout facts in an explicit Closeout Summary/Facts/Fields section or the project-state closeout authority block",
                source,
            )
        ]
    if not closeout_values_are_complete(harvested):
        return {}, [
            Finding(
                "error",
                "writeback-refused",
                "--from-active-plan fallback found incomplete project-state closeout facts; supply complete closeout facts explicitly",
                source,
            )
        ]

    existing_identity = _identity_from_facts(state_writeback_identity_facts(inventory.state))
    current_identity = _current_closeout_identity(inventory, None)
    if not _closeout_identity_matches(existing_identity, current_identity):
        return {}, [
            Finding(
                "error",
                "writeback-refused",
                "--from-active-plan fallback refused project-state closeout facts because recorded identity "
                f"{_closeout_identity_summary(existing_identity)} does not match current identity {_closeout_identity_summary(current_identity)}",
                source,
            )
        ]
    return harvested, []


def _writeback_root_state_preflight_errors(inventory: Inventory) -> list[Finding]:
    errors: list[Finding] = []
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
    return errors


def _product_source_root_errors(inventory: Inventory, value: str) -> list[Finding]:
    errors: list[Finding] = []
    if "\n" in value or "\r" in value:
        errors.append(Finding("error", "writeback-refused", "--product-source-root must be a one-line path value"))
        return errors
    try:
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = inventory.root / candidate
        resolved = candidate.resolve()
    except (OSError, RuntimeError) as exc:
        errors.append(Finding("error", "writeback-refused", f"--product-source-root could not be resolved: {exc}"))
        return errors
    if not resolved.exists():
        errors.append(Finding("error", "writeback-refused", f"--product-source-root does not exist: {value}"))
    elif not resolved.is_dir():
        errors.append(Finding("error", "writeback-refused", f"--product-source-root is not a directory: {value}"))
    elif str(resolved).casefold() == str(inventory.root.resolve()).casefold():
        errors.append(Finding("error", "writeback-refused", "--product-source-root must not point at the operating root"))
    return errors


def _writeback_archive_apply_findings(inventory: Inventory, request: WritebackRequest) -> list[Finding]:
    state = inventory.state
    assert state is not None
    archive_plan = _archive_plan(inventory, request)
    if archive_plan is None:
        return [Finding("error", "writeback-refused", "archive-active-plan could not determine a safe archive target")]

    closeout_plan = _closeout_writeback_plan(inventory, request, archive_plan.archive_rel_path)
    planned = closeout_plan.values
    lifecycle_values = _planned_lifecycle_values(request, archive_plan.archive_rel_path)
    roadmap_plan, roadmap_errors = _writeback_roadmap_plan(inventory, request, archive_plan.archive_rel_path)
    if roadmap_errors:
        return roadmap_errors
    incubation_plan, incubation_errors = _writeback_incubation_plan(inventory, request, archive_plan.archive_rel_path)
    if incubation_errors:
        return incubation_errors
    route_retarget_plans = _archive_route_retarget_plans(
        inventory,
        archive_plan.archive_rel_path,
        skip_rels=_incubation_plan_source_rels(incubation_plan),
    )
    state_text = _state_text_with_writeback(state.content, planned, lifecycle_values, closeout_plan.identity)
    active_plan_lifecycle = _active_plan_lifecycle_values(inventory, request, lifecycle_values)
    plan_text, sync_findings = _active_plan_text_with_synced_values(
        archive_plan.plan,
        planned,
        active_plan_lifecycle,
        _requested_or_current_active_phase(inventory, active_plan_lifecycle),
    )
    findings: list[Finding] = [
        Finding("info", "writeback-apply", "closeout/state writeback apply started"),
        _planned_closeout_finding(planned),
    ]
    findings.extend(_closeout_writeback_plan_findings(closeout_plan, apply=True))
    findings.extend(_archive_plan_findings(inventory, archive_plan, apply=True))
    findings.append(
        Finding(
            "info",
            "writeback-lifecycle-updated",
            f"updated project-state lifecycle frontmatter: {', '.join(lifecycle_values)}",
            state.rel_path,
        )
    )
    findings.append(_phase_execution_boundary_finding(lifecycle_values, state.rel_path, apply=True))

    state_tmp = state.path.with_name(f".{state.path.name}.writeback.tmp")
    state_backup = state.path.with_name(f".{state.path.name}.writeback.backup")
    archive_tmp = archive_plan.archive_path.with_name(f".{archive_plan.archive_path.name}.writeback.tmp")
    archive_backup = archive_plan.archive_path.with_name(f".{archive_plan.archive_path.name}.writeback.backup")
    plan_backup = archive_plan.plan.path.with_name(f".{archive_plan.plan.path.name}.writeback.backup")
    roadmap_tmp = _roadmap_writeback_tmp(roadmap_plan)
    incubation_tmp = _incubation_writeback_tmp(incubation_plan)
    incubation_backup = _incubation_source_backup(incubation_plan)
    if incubation_plan and incubation_plan.archive_rel:
        state_text = state_text.replace(incubation_plan.source_rel, incubation_plan.archive_rel)
        plan_text = plan_text.replace(incubation_plan.source_rel, incubation_plan.archive_rel)
        if roadmap_plan:
            roadmap_plan = _roadmap_writeback_plan_with_updated_text(
                roadmap_plan,
                roadmap_plan.updated_text.replace(incubation_plan.source_rel, incubation_plan.archive_rel),
            )
            roadmap_tmp = _roadmap_writeback_tmp(roadmap_plan)
        route_retarget_plans = tuple(
            _route_retarget_plan_with_updated_text(plan, plan.updated_text.replace(incubation_plan.source_rel, incubation_plan.archive_rel))
            for plan in route_retarget_plans
        )
    roadmap_backup = _roadmap_writeback_backup(roadmap_plan) if roadmap_tmp else None
    incubation_write_backup = _incubation_writeback_backup(incubation_plan) if incubation_tmp else None
    link_repair_skip_targets = {state.path, archive_plan.plan.path}
    if roadmap_plan:
        link_repair_skip_targets.add(roadmap_plan.target_path)
    link_repair_skip_targets.update(plan.target_path for plan in route_retarget_plans)
    incubation_link_tmps = [
        (tmp_path, backup_path, target_path, text)
        for tmp_path, backup_path, target_path, text in _incubation_link_tmp_paths(incubation_plan)
        if target_path not in link_repair_skip_targets
    ]
    route_retarget_tmps = [
        (
            plan.target_path.with_name(f".{plan.target_path.name}.writeback-retarget.tmp"),
            plan.target_path.with_name(f".{plan.target_path.name}.writeback-retarget.backup"),
            plan,
        )
        for plan in route_retarget_plans
        if plan.current_text != plan.updated_text
    ]
    tmp_checks = [
        (state_tmp, "temporary state write path"),
        (state_backup, "temporary state backup path"),
        (archive_tmp, "temporary archive write path"),
        (archive_backup, "temporary archive backup path"),
        (plan_backup, "temporary active-plan backup path"),
    ]
    if roadmap_tmp:
        tmp_checks.append((roadmap_tmp, "temporary roadmap write path"))
    if roadmap_backup:
        tmp_checks.append((roadmap_backup, "temporary roadmap backup path"))
    if incubation_tmp:
        tmp_checks.append((incubation_tmp, "temporary incubation relationship write path"))
    if incubation_write_backup:
        tmp_checks.append((incubation_write_backup, "temporary incubation relationship backup path"))
    if incubation_backup:
        tmp_checks.append((incubation_backup, "temporary incubation source backup path"))
    tmp_checks.extend((tmp_path, "temporary route-retarget write path") for tmp_path, _backup_path, _plan in route_retarget_tmps)
    tmp_checks.extend((backup_path, "temporary route-retarget backup path") for _tmp_path, backup_path, _plan in route_retarget_tmps)
    tmp_checks.extend((tmp_path, "temporary incubation link-repair write path") for tmp_path, _backup_path, _target, _text in incubation_link_tmps)
    tmp_checks.extend((backup_path, "temporary incubation link-repair backup path") for _tmp_path, backup_path, _target, _text in incubation_link_tmps)
    for tmp_path, label in tmp_checks:
        if tmp_path.exists():
            return [Finding("error", "writeback-refused", f"{label} already exists: {tmp_path.relative_to(inventory.root).as_posix()}")]

    operations: list[AtomicFileWrite | AtomicFileDelete] = [
        AtomicFileWrite(state.path, state_tmp, state_text, state_backup),
        AtomicFileWrite(archive_plan.archive_path, archive_tmp, plan_text, archive_backup),
        AtomicFileDelete(archive_plan.plan.path, plan_backup),
    ]
    if roadmap_tmp and roadmap_backup and roadmap_plan:
        operations.append(AtomicFileWrite(roadmap_plan.target_path, roadmap_tmp, roadmap_plan.updated_text, roadmap_backup))
    if incubation_tmp and incubation_write_backup and incubation_plan:
        operations.append(AtomicFileWrite(incubation_plan.target_path, incubation_tmp, incubation_plan.updated_text, incubation_write_backup))
        if incubation_plan.archive_rel and incubation_backup:
            operations.append(AtomicFileDelete(incubation_plan.source_path, incubation_backup))
    for tmp_path, backup_path, retarget_plan in route_retarget_tmps:
        operations.append(AtomicFileWrite(retarget_plan.target_path, tmp_path, retarget_plan.updated_text, backup_path))
    for tmp_path, backup_path, target_path, text in incubation_link_tmps:
        operations.append(AtomicFileWrite(target_path, tmp_path, text, backup_path))

    try:
        cleanup_warnings = apply_file_transaction(operations)
    except FileTransactionError as exc:
        return [Finding("error", "writeback-refused", f"archive-active-plan failed before all target files were written: {exc}")]

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
    if roadmap_plan:
        findings.extend(_writeback_roadmap_findings(roadmap_plan, apply=True))
    if incubation_plan:
        findings.extend(_writeback_incubation_findings(incubation_plan, apply=True))
    if route_retarget_plans:
        findings.extend(_archive_route_retarget_findings(route_retarget_plans, apply=True))
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "writeback-archive-backup-cleanup", warning, archive_plan.archive_rel_path))
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


def _should_carry_current_closeout_values(request: WritebackRequest) -> bool:
    if request.roadmap_item:
        return False
    return bool(request.closeout)


def _closeout_writeback_plan(inventory: Inventory, request: WritebackRequest, archive_rel_path: str | None) -> CloseoutWritebackPlan:
    identity = _current_closeout_identity(inventory, archive_rel_path)
    if not request.closeout:
        return CloseoutWritebackPlan({}, identity, "skipped", "no closeout facts were requested")
    if not _should_carry_current_closeout_values(request):
        values = _ordered_closeout_values(request.closeout)
        return CloseoutWritebackPlan(
            values,
            identity,
            "replace",
            "use same-request closeout facts only; existing project-state closeout facts are not carried",
        )

    current = {field: fact.value for field, fact in state_writeback_facts(inventory.state).items()}
    if not current:
        return CloseoutWritebackPlan(
            _ordered_closeout_values(request.closeout),
            identity,
            "replace",
            "start the current closeout block with same-request facts because no existing closeout facts were present",
        )

    existing_identity = _identity_from_facts(state_writeback_identity_facts(inventory.state))
    if not _identity_has_plan_anchor(identity):
        values = dict(current)
        values.update(request.closeout)
        return CloseoutWritebackPlan(
            _ordered_closeout_values(values),
            identity,
            "carry",
            "carry existing closeout facts because no active or archived plan identity is available for this closeout",
        )
    if _closeout_identity_matches(existing_identity, identity):
        values = dict(current)
        values.update(request.closeout)
        return CloseoutWritebackPlan(
            _ordered_closeout_values(values),
            identity,
            "carry",
            "carry existing closeout facts because recorded identity matches the current plan identity",
        )
    if closeout_values_are_complete(request.closeout):
        return CloseoutWritebackPlan(
            _ordered_closeout_values(request.closeout),
            identity,
            "replace",
            f"replace existing closeout facts because recorded identity {_closeout_identity_summary(existing_identity)} does not match current identity {_closeout_identity_summary(identity)}",
        )

    source = inventory.state.rel_path if inventory.state else DEFAULT_STATE_REL
    error = Finding(
        "error",
        "writeback-closeout-identity-refused",
        "partial closeout writeback would carry existing facts without a matching plan identity; "
        f"recorded identity {_closeout_identity_summary(existing_identity)}; current identity {_closeout_identity_summary(identity)}; "
        "supply complete closeout facts with docs_decision updated/not-needed plus state_writeback, verification, and commit_decision to replace them",
        source,
    )
    return CloseoutWritebackPlan(_ordered_closeout_values(request.closeout), identity, "refuse", error.message, (error,))


def _current_closeout_identity(inventory: Inventory, archive_rel_path: str | None) -> CloseoutIdentity:
    state_data = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    active_plan = _normalize_rel(str(state_data.get("active_plan") or ""))
    archived_plan = _normalize_rel(str(archive_rel_path or ""))
    if not archived_plan and not active_plan:
        archived_plan = _normalize_rel(str(state_data.get("last_archived_plan") or ""))
    plan_id = ""
    plan = inventory.active_plan_surface
    if plan and plan.exists and plan.frontmatter.has_frontmatter and not plan.frontmatter.errors:
        plan_id = _normalized_value(plan.frontmatter.data.get("plan_id") or "")
    return CloseoutIdentity(plan_id=plan_id, active_plan=active_plan, archived_plan=archived_plan)


def _identity_from_facts(facts: dict[str, WritebackFact]) -> CloseoutIdentity:
    return CloseoutIdentity(
        plan_id=facts["plan_id"].value if "plan_id" in facts else "",
        active_plan=_normalize_rel(facts["active_plan"].value) if "active_plan" in facts else "",
        archived_plan=_normalize_rel(facts["archived_plan"].value) if "archived_plan" in facts else "",
    )


def _identity_has_plan_anchor(identity: CloseoutIdentity) -> bool:
    return bool(identity.plan_id or identity.active_plan or identity.archived_plan)


def _closeout_identity_matches(existing: CloseoutIdentity, current: CloseoutIdentity) -> bool:
    if not _identity_has_plan_anchor(current):
        return True
    if not _identity_has_plan_anchor(existing):
        return False
    if current.plan_id and existing.plan_id != current.plan_id:
        return False
    active_match = bool(current.active_plan and existing.active_plan == current.active_plan)
    archived_match = bool(current.archived_plan and existing.archived_plan == current.archived_plan)
    if active_match or archived_match:
        return True
    return bool(current.plan_id and existing.plan_id == current.plan_id and not (current.active_plan or current.archived_plan))


def _ordered_closeout_values(values: dict[str, str]) -> dict[str, str]:
    return {field: values[field] for field in CLOSEOUT_WRITEBACK_FIELDS if field in values}


def _closeout_writeback_plan_findings(plan: CloseoutWritebackPlan, apply: bool) -> list[Finding]:
    if plan.decision == "skipped":
        return []
    prefix = "" if apply else "would "
    code = {
        "carry": "writeback-closeout-carry",
        "replace": "writeback-closeout-replace",
        "refuse": "writeback-closeout-identity-refused",
    }.get(plan.decision, "writeback-closeout-identity")
    return [
        Finding(
            "info",
            "writeback-closeout-identity",
            f"{prefix}record closeout identity: {_closeout_identity_summary(plan.identity)}",
            DEFAULT_STATE_REL,
        ),
        Finding("info", code, f"{prefix}{plan.message}", DEFAULT_STATE_REL),
    ]


def _closeout_identity_summary(identity: CloseoutIdentity) -> str:
    parts = [
        f"plan_id={identity.plan_id!r}",
        f"active_plan={identity.active_plan!r}",
        f"archived_plan={identity.archived_plan!r}",
    ]
    return ", ".join(parts)


def _planned_lifecycle_values(request: WritebackRequest, archive_rel_path: str | None) -> dict[str, str]:
    values = dict(request.lifecycle)
    if archive_rel_path:
        values.update({"plan_status": "none", "active_plan": "", "last_archived_plan": archive_rel_path})
    return values


def _phase_execution_boundary_finding(lifecycle_values: dict[str, str], source: str | None, apply: bool) -> Finding:
    verb = "updated" if apply else "would update"
    fields = ", ".join(lifecycle_values) or "lifecycle fields"
    return Finding(
        "info",
        "writeback-phase-execution-boundary",
        f"{verb} {fields} only; lifecycle writeback does not authorize auto_continue, closeout, archive, commit, or next-slice movement",
        source,
    )


def _ready_for_closeout_boundary_finding(lifecycle_values: dict[str, str], source: str | None, apply: bool) -> Finding | None:
    if lifecycle_values.get("phase_status") != "complete":
        return None
    verb = "updated" if apply else "would update"
    return Finding(
        "info",
        "writeback-ready-for-closeout-boundary",
        (
            f"{verb} phase_status complete as a ready-for-closeout state only; "
            "explicit --archive-active-plan is required to archive the plan, default roadmap items to done, "
            "or move the lifecycle past the active plan"
        ),
        source,
    )


def _planned_closeout_finding(values: dict[str, str]) -> Finding:
    summary = ", ".join(f"{field}={values[field]!r}" for field in CLOSEOUT_WRITEBACK_FIELDS if field in values)
    return Finding("info", "writeback-closeout-fields", f"closeout writeback fields: {summary or 'none'}", "project/project-state.md")


def _writeback_roadmap_plan(inventory: Inventory, request: WritebackRequest, archive_rel_path: str | None) -> tuple[RoadmapWritebackPlan | None, list[Finding]]:
    if not request.roadmap_item:
        return None, []
    if not inventory.active_plan_surface or not inventory.active_plan_surface.exists:
        return None, [
            Finding(
                "error",
                "writeback-refused",
                "--roadmap-item requires a readable active plan so roadmap closeout sync is target-bound",
                DEFAULT_PLAN_REL,
            )
        ]
    roadmap_status = request.roadmap_status or ("done" if archive_rel_path else "")
    related_plan = archive_rel_path or DEFAULT_PLAN_REL
    roadmap_requests = tuple(
        make_roadmap_request(
            "update",
            item_id,
            status=roadmap_status,
            related_plan=related_plan,
            archived_plan=archive_rel_path or "",
            verification_summary=request.closeout.get("verification", ""),
            docs_decision=request.closeout.get("docs_decision", ""),
            carry_forward=_roadmap_carry_forward_value(request.closeout),
        )
        for item_id in _writeback_roadmap_item_ids(inventory, request)
    )
    allowed_missing_paths = {related_plan}
    if archive_rel_path:
        allowed_missing_paths.add(archive_rel_path)
    plans, errors = roadmap_plans_for_requests(inventory, roadmap_requests, allowed_missing_paths=allowed_missing_paths)
    if errors:
        return None, errors
    if not plans:
        return None, []
    return RoadmapWritebackPlan(target_rel=plans[-1].target_rel, target_path=plans[-1].target_path, item_plans=plans), []


def _writeback_roadmap_item_ids(inventory: Inventory, request: WritebackRequest) -> tuple[str, ...]:
    requested = _normalized_item_id(request.roadmap_item)
    if not requested:
        return ()
    plan = inventory.active_plan_surface
    if not plan or not plan.exists or not plan.frontmatter.has_frontmatter:
        return (requested,)
    data = plan.frontmatter.data
    primary = _normalized_item_id(data.get("primary_roadmap_item") or data.get("related_roadmap_item"))
    covered = tuple(_dedupe_nonempty(_frontmatter_item_list(data.get("covered_roadmap_items"))))
    if covered and requested in {*covered, primary}:
        return tuple(_dedupe_nonempty((requested, *covered)))
    return (requested,)


def _roadmap_writeback_tmp(plan: RoadmapWritebackPlan | None) -> Path | None:
    if plan is None or plan.current_text == plan.updated_text:
        return None
    return plan.target_path.with_name(f".{plan.target_path.name}.writeback.tmp")


def _roadmap_writeback_backup(plan: RoadmapWritebackPlan | None) -> Path | None:
    if plan is None or plan.current_text == plan.updated_text:
        return None
    return plan.target_path.with_name(f".{plan.target_path.name}.writeback.backup")


def _roadmap_writeback_plan_with_updated_text(plan: RoadmapWritebackPlan, updated_text: str) -> RoadmapWritebackPlan:
    if not plan.item_plans:
        return plan
    item_plans = (*plan.item_plans[:-1], replace(plan.item_plans[-1], updated_text=updated_text))
    return replace(plan, item_plans=item_plans)


def _roadmap_carry_forward_value(closeout: dict[str, str]) -> str:
    parts: list[str] = []
    if closeout.get("residual_risk"):
        parts.append(f"Residual risk: {closeout['residual_risk']}")
    if closeout.get("carry_forward"):
        parts.append(f"Carry-forward: {closeout['carry_forward']}")
    return "; ".join(parts)


def _frontmatter_item_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [_normalized_item_id(item) for item in value]
    normalized = _normalized_item_id(value)
    return [normalized] if normalized else []


def _dedupe_nonempty(values) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        if value and value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped


def _writeback_roadmap_findings(plan: RoadmapWritebackPlan, apply: bool) -> list[Finding]:
    prefix = "" if apply else "would "
    changed_plans = tuple(item_plan for item_plan in plan.item_plans if item_plan.changed_fields)
    action = "updated" if apply and changed_plans else "checked" if apply else "would update"
    findings = [
        Finding("info", "writeback-roadmap-sync", f"{action} roadmap item(s) {list(plan.item_ids)!r} with selected writeback facts", plan.target_rel),
        Finding("info", "writeback-roadmap-target", f"{prefix}write roadmap sync target: {plan.target_rel}", plan.target_rel),
    ]
    if changed_plans:
        for item_plan in plan.item_plans:
            findings.extend(
                Finding(
                    "info",
                    "writeback-roadmap-changed-field",
                    f"{prefix}change roadmap item {item_plan.item_id!r} field: {field}",
                    plan.target_rel,
                )
                for field in item_plan.changed_fields
            )
    else:
        findings.append(Finding("info", "writeback-roadmap-noop", "roadmap item(s) already match selected writeback facts", plan.target_rel))
    findings.append(
        Finding(
            "info",
            "writeback-roadmap-boundary",
            "roadmap sync is separate from lifecycle and archive writes and bounded to the requested item plus covered_roadmap_items from the active plan; roadmap output cannot approve closeout, archive, commit, rollback, repair, or lifecycle decisions",
            plan.target_rel,
        )
    )
    return findings


def _writeback_incubation_plan(
    inventory: Inventory,
    request: WritebackRequest,
    archive_rel_path: str | None,
) -> tuple[RelationshipUpdatePlan | None, list[Finding]]:
    if not request.roadmap_item or not archive_rel_path:
        return None, []
    fields = roadmap_item_fields(inventory, request.roadmap_item)
    source_incubation = _normalize_rel(str(fields.get("source_incubation") or ""))
    if not source_incubation:
        return None, []
    return incubation_closeout_plan(
        inventory,
        source_incubation,
        roadmap_item=request.roadmap_item,
        archived_plan=archive_rel_path,
        verification_summary=request.closeout.get("verification", ""),
        docs_decision=request.closeout.get("docs_decision", ""),
    )


def _writeback_incubation_findings(plan: RelationshipUpdatePlan, apply: bool) -> list[Finding]:
    prefix = "" if apply else "would "
    findings = [
        Finding("info", "writeback-incubation-sync", f"{prefix}sync source incubation relationship metadata", plan.source_rel),
        Finding("info", "writeback-incubation-target", f"{prefix}write source incubation target: {plan.target_rel}", plan.target_rel),
    ]
    if plan.changed_fields:
        findings.extend(
            Finding("info", "writeback-incubation-changed-field", f"{prefix}change source incubation field: {field}", plan.source_rel)
            for field in plan.changed_fields
        )
    else:
        findings.append(Finding("info", "writeback-incubation-noop", "source incubation relationship metadata already matches same-request closeout facts", plan.source_rel))
    if plan.archive_blockers:
        findings.append(
            Finding(
                "warn",
                "writeback-incubation-archive-blocked",
                f"source incubation was not auto-archived because: {', '.join(plan.archive_blockers)}",
                plan.source_rel,
            )
        )
    elif plan.archive_rel:
        findings.append(Finding("info", "writeback-incubation-auto-archive", f"{prefix}archive fully covered source incubation to {plan.archive_rel}", plan.archive_rel))
    if plan.link_repairs:
        findings.append(Finding("info", "writeback-incubation-link-repair", f"{prefix}repair exact source-incubation links in {len(plan.link_repairs)} file(s)", plan.archive_rel or plan.source_rel))
    findings.append(
        Finding(
            "info",
            "writeback-incubation-boundary",
            "incubation relationship writeback uses only the roadmap item's explicit source_incubation and same-request closeout facts; mixed notes stay active",
            plan.source_rel,
        )
    )
    return findings


def _incubation_writeback_tmp(plan: RelationshipUpdatePlan | None) -> Path | None:
    if plan is None or plan.current_text == plan.updated_text:
        return None
    return plan.target_path.with_name(f".{plan.target_path.name}.writeback-incubation.tmp")


def _incubation_writeback_backup(plan: RelationshipUpdatePlan | None) -> Path | None:
    if plan is None or plan.current_text == plan.updated_text:
        return None
    return plan.target_path.with_name(f".{plan.target_path.name}.writeback-incubation.backup")


def _incubation_source_backup(plan: RelationshipUpdatePlan | None) -> Path | None:
    if plan is None or not plan.archive_rel:
        return None
    return plan.source_path.with_name(f".{plan.source_path.name}.writeback-incubation.backup")


def _incubation_link_tmp_paths(plan: RelationshipUpdatePlan | None) -> list[tuple[Path, Path, Path, str]]:
    if plan is None:
        return []
    return [
        (
            path.with_name(f".{path.name}.writeback-incubation.tmp"),
            path.with_name(f".{path.name}.writeback-incubation.backup"),
            path,
            text,
        )
        for _rel, path, text in plan.link_repairs
    ]


def _incubation_plan_source_rels(plan: RelationshipUpdatePlan | None) -> tuple[str, ...]:
    if plan is None:
        return ()
    return (plan.source_rel,)


def _archive_route_retarget_plans(
    inventory: Inventory,
    archive_rel_path: str,
    *,
    skip_rels: tuple[str, ...] = (),
) -> tuple[RouteRetargetPlan, ...]:
    archive_rel_path = _normalize_rel(archive_rel_path)
    if not archive_rel_path:
        return ()
    skip = {DEFAULT_STATE_REL, DEFAULT_PLAN_REL, "project/roadmap.md", *skip_rels}
    plans: list[RouteRetargetPlan] = []
    for surface in inventory.present_surfaces:
        if surface.rel_path in skip or surface.rel_path.startswith("project/archive/"):
            continue
        if surface.memory_route not in {"research", "incubation", "verification", "decisions", "adrs"}:
            continue
        if surface.path.suffix.lower() != ".md" or not surface.frontmatter.has_frontmatter or surface.frontmatter.errors:
            continue
        updates = _archive_route_retarget_updates(surface, archive_rel_path)
        if not updates:
            continue
        updated_text = _update_frontmatter_scalars(surface.content, updates, only_existing=False)
        changed_fields = tuple(
            field
            for field, value in updates.items()
            if _frontmatter_value(surface.content, field) != value and _frontmatter_value(updated_text, field) == value
        )
        if changed_fields:
            plans.append(
                RouteRetargetPlan(
                    source_rel=surface.rel_path,
                    target_path=surface.path,
                    current_text=surface.content,
                    updated_text=updated_text,
                    changed_fields=changed_fields,
                )
            )
    return tuple(plans)


def _archive_route_retarget_updates(surface: Surface, archive_rel_path: str) -> dict[str, str]:
    data = surface.frontmatter.data
    updates: dict[str, str] = {}
    related_plan = _normalize_rel(str(data.get("related_plan") or ""))
    if related_plan == DEFAULT_PLAN_REL:
        updates["related_plan"] = archive_rel_path
        for field in ("archived_plan", "implemented_by"):
            value = _normalize_rel(str(data.get(field) or ""))
            if value in {"", DEFAULT_PLAN_REL}:
                updates[field] = archive_rel_path
        return updates
    for field in ("archived_plan", "implemented_by"):
        if _normalize_rel(str(data.get(field) or "")) == DEFAULT_PLAN_REL:
            updates[field] = archive_rel_path
    return updates


def _route_retarget_plan_with_updated_text(plan: RouteRetargetPlan, updated_text: str) -> RouteRetargetPlan:
    return replace(plan, updated_text=updated_text)


def _archive_route_retarget_findings(plans: tuple[RouteRetargetPlan, ...], apply: bool) -> list[Finding]:
    if not plans:
        return []
    prefix = "" if apply else "would "
    findings = [
        Finding(
            "info",
            "writeback-route-retarget",
            f"{prefix}retarget archive relationship metadata in {len(plans)} route file(s)",
        )
    ]
    for plan in plans:
        for field in plan.changed_fields:
            findings.append(
                Finding(
                    "info",
                    "writeback-route-retarget-field",
                    f"{prefix}change {plan.source_rel} frontmatter field: {field}",
                    plan.source_rel,
                )
            )
    findings.append(
        Finding(
            "info",
            "writeback-route-retarget-boundary",
            "archive relationship retargeting updates only MLH route frontmatter that pointed at the active plan; it does not rewrite historical archives or approve lifecycle decisions",
        )
    )
    return findings


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


def state_compaction_dry_run_findings(inventory: Inventory, state_text: str | None = None) -> list[Finding]:
    if state_text is None and inventory.state is not None:
        state_text = inventory.state.content
    if state_text is None:
        return _state_compaction_findings(StateCompactionPlan("refused", "project/project-state.md is missing"), apply=False)
    return _state_compaction_findings(_state_compaction_plan(inventory, state_text), apply=False)


def state_compaction_apply_findings(inventory: Inventory, state_text: str | None = None) -> list[Finding]:
    if state_text is None and inventory.state is not None:
        state_text = inventory.state.path.read_text(encoding="utf-8")
    if state_text is None:
        return _state_compaction_findings(StateCompactionPlan("refused", "project/project-state.md is missing"), apply=True)
    return _apply_state_compaction(inventory, _state_compaction_plan(inventory, state_text))


def _apply_state_compaction(inventory: Inventory, plan: StateCompactionPlan) -> list[Finding]:
    if plan.posture != "would run":
        return _state_compaction_findings(plan, apply=True)
    state = inventory.state
    assert state is not None
    assert plan.archive_path is not None
    assert plan.archive_text is not None
    assert plan.compacted_state_text is not None

    state_tmp = state.path.with_name(f".{state.path.name}.compact.tmp")
    state_backup = state.path.with_name(f".{state.path.name}.compact.backup")
    archive_tmp = plan.archive_path.with_name(f".{plan.archive_path.name}.compact.tmp")
    archive_backup = plan.archive_path.with_name(f".{plan.archive_path.name}.compact.backup")
    try:
        for candidate, label in (
            (state_tmp, "temporary state compaction path"),
            (state_backup, "temporary state compaction backup path"),
            (archive_tmp, "temporary state-history archive path"),
            (archive_backup, "temporary state-history archive backup path"),
        ):
            if candidate.exists():
                refused = StateCompactionPlan("refused", f"{label} already exists: {candidate.relative_to(inventory.root).as_posix()}", plan.archive_rel_path, plan.archive_path)
                return _state_compaction_findings(refused, apply=True)
        if plan.archive_path.exists():
            refused = StateCompactionPlan("refused", f"state-history archive target already exists: {plan.archive_rel_path}", plan.archive_rel_path, plan.archive_path)
            return _state_compaction_findings(refused, apply=True)
        apply_file_transaction(
            (
                AtomicFileWrite(plan.archive_path, archive_tmp, plan.archive_text, archive_backup),
                AtomicFileWrite(state.path, state_tmp, plan.compacted_state_text, state_backup),
            )
        )
    except (FileTransactionError, OSError) as exc:
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
    keep_titles = {"Current Focus", "Memory Routing Roadmap", "Repository Role Map"}
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


def _should_archive_active_plan(_inventory: Inventory, request: WritebackRequest) -> bool:
    return request.archive_active_plan


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


def _archive_preflight_errors(inventory: Inventory, request: WritebackRequest) -> list[Finding]:
    errors: list[Finding] = []
    state = inventory.state
    data = state.frontmatter.data if state and state.exists else {}
    plan_status = str(data.get("plan_status") or "")
    active_plan_value = str(data.get("active_plan") or "")
    phase_status = _archive_phase_status(inventory, request)
    manifest_plan = _manifest_memory_value(inventory, "plan_file", DEFAULT_PLAN_REL)
    archive_dir = _manifest_memory_value(inventory, "archive_dir", DEFAULT_ARCHIVE_DIR_REL)

    if plan_status != "active":
        errors.append(Finding("error", "writeback-refused", f"archive-active-plan requires plan_status active; current plan_status is {plan_status or '<empty>'!r}", state.rel_path if state else None))
    if phase_status != "complete":
        errors.append(
            Finding(
                "error",
                "writeback-refused",
                (
                    "archive-active-plan requires phase_status complete before lifecycle close; "
                    f"current/requested phase_status is {phase_status or '<empty>'!r}"
                ),
                state.rel_path if state else None,
            )
        )
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


def _archive_phase_status(inventory: Inventory, request: WritebackRequest) -> str:
    requested = str(request.lifecycle.get("phase_status") or "")
    if requested:
        return requested
    state = inventory.state
    data = state.frontmatter.data if state and state.exists else {}
    return str(data.get("phase_status") or "")


def _active_plan_lifecycle_values(
    inventory: Inventory,
    request: WritebackRequest,
    lifecycle_values: dict[str, str],
) -> dict[str, str]:
    if not _should_archive_active_plan(inventory, request):
        return lifecycle_values
    phase_status = _archive_phase_status(inventory, request)
    if phase_status != "complete":
        return lifecycle_values
    values = dict(lifecycle_values)
    values.setdefault("phase_status", phase_status)
    return values


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


def _state_text_with_writeback(
    text: str,
    closeout_values: dict[str, str],
    lifecycle_values: dict[str, str],
    identity: CloseoutIdentity | None = None,
) -> str:
    updated = _update_frontmatter_scalars(text, lifecycle_values, only_existing=False) if lifecycle_values else text
    if closeout_values:
        updated = _replace_or_append_writeback_block(updated, closeout_values, identity or CloseoutIdentity())
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


def _replace_or_append_writeback_block(text: str, closeout_values: dict[str, str], identity: CloseoutIdentity | None = None) -> str:
    block = _render_writeback_block(closeout_values, identity or CloseoutIdentity())
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


def _render_writeback_block(closeout_values: dict[str, str], identity: CloseoutIdentity | None = None) -> str:
    lines = [WRITEBACK_BEGIN]
    current_identity = identity or CloseoutIdentity()
    for field in CLOSEOUT_IDENTITY_FIELDS:
        value = getattr(current_identity, field)
        if value:
            lines.append(f"- {field}: {value}")
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
    for index in _closeout_body_field_line_indexes(text):
        line = lines[index]
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


def _closeout_body_field_line_indexes(text: str) -> list[int]:
    lines = text.splitlines(keepends=True)
    indexes: list[int] = []
    for span in _closeout_body_sections(lines):
        for index in range(span.start_index, span.end_index):
            field, value = _field_line_value(lines[index])
            if field and value:
                indexes.append(index)
    return indexes


def _closeout_body_sections(lines: list[str]) -> list[BodySectionSpan]:
    headings: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*(?:\r?\n)?$", line)
        if match:
            headings.append((index, len(match.group(1)), _normalized_heading_title(match.group(2))))

    sections: list[BodySectionSpan] = []
    for heading_index, (start, level, title) in enumerate(headings):
        if title not in _CLOSEOUT_BODY_SECTION_TITLES:
            continue
        end = len(lines)
        for next_start, next_level, _next_title in headings[heading_index + 1 :]:
            if next_level <= level:
                end = next_start
                break
        sections.append(BodySectionSpan(start_index=start + 1, end_index=end))
    return sections


def _normalized_heading_title(title: str) -> str:
    return re.sub(r"\s+", " ", _strip_inline_code(title).casefold()).strip(" :")


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


def _text_field_input_errors(values: dict[str, object]) -> list[str]:
    errors: list[str] = []
    for field in CLOSEOUT_WRITEBACK_FIELDS:
        value = values.get(field)
        if value is None:
            continue
        text = str(value)
        if "\n" in text or "\r" in text:
            errors.append(
                f"--{field.replace('_', '-')} is a one-line closeout field; put multi-paragraph evidence in the active plan or project/verification and pass a concise summary"
            )
    return errors


def _normalized_value(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).rstrip(".")


def _normalized_status(value: object) -> str:
    return str(value or "").strip().casefold().replace("_", "-")


def _normalized_item_id(value: object) -> str:
    return str(value or "").strip().casefold().replace("_", "-")


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
