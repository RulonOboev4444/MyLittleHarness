from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

from .atomic_files import AtomicFileWrite, FileTransactionError, apply_file_transaction
from .inventory import Inventory
from .memory_hygiene import RelationshipUpdatePlan, relationship_update_plan
from .models import Finding


ROADMAP_REL = "project/roadmap.md"
DEFAULT_PLAN_REL = "project/implementation-plan.md"
ROADMAP_STATUS_VALUES = {"proposed", "accepted", "active", "blocked", "done", "deferred", "rejected", "superseded"}
DOCS_DECISION_VALUES = {"updated", "not-needed", "uncertain"}
TERMINAL_QUEUE_STATUSES = {"done", "rejected", "superseded"}
FUTURE_QUEUE_FIELD = "future_execution_slice_queue"
FUTURE_QUEUE_TITLE = "Future Execution Slice Queue"
ARCHIVED_HISTORY_FIELD = "archived_completed_history"
ARCHIVED_HISTORY_TITLE = "Archived Completed History"
DETAILED_DONE_TAIL_LIMIT = 4
ACCEPTED_ITEM_ORDER_FIELD = "accepted_item_order"
ITEM_ID_LIST_FIELDS = ("dependencies", "slice_members", "slice_dependencies", "supersedes", "superseded_by")
PATH_LIST_FIELDS = ("related_specs",)
ARTIFACT_LIST_FIELDS = ("target_artifacts",)
LIST_FIELDS = (*ITEM_ID_LIST_FIELDS, *PATH_LIST_FIELDS, *ARTIFACT_LIST_FIELDS)
STANDARD_FIELDS = (
    "id",
    "status",
    "order",
    "execution_slice",
    "slice_goal",
    "slice_members",
    "slice_dependencies",
    "slice_closeout_boundary",
    "dependencies",
    "source_incubation",
    "source_research",
    "related_specs",
    "related_plan",
    "archived_plan",
    "target_artifacts",
    "verification_summary",
    "docs_decision",
    "carry_forward",
    "supersedes",
    "superseded_by",
)
PATH_FIELDS = {"source_incubation", "source_research", "related_plan", "archived_plan"}


@dataclass(frozen=True)
class RoadmapRequest:
    action: str
    item_id: str
    title: str
    status: str
    order: int | None
    execution_slice: str
    slice_goal: str
    slice_closeout_boundary: str
    source_incubation: str
    source_research: str
    related_plan: str
    archived_plan: str
    verification_summary: str
    docs_decision: str
    carry_forward: str
    dependencies: tuple[str, ...]
    slice_members: tuple[str, ...]
    slice_dependencies: tuple[str, ...]
    related_specs: tuple[str, ...]
    target_artifacts: tuple[str, ...]
    supersedes: tuple[str, ...]
    superseded_by: tuple[str, ...]


@dataclass(frozen=True)
class RoadmapItem:
    title: str
    fields: dict[str, object]
    start: int
    end: int
    style: str = "canonical"


@dataclass(frozen=True)
class RoadmapPlan:
    action: str
    item_id: str
    target_rel: str
    target_path: Path
    changed_fields: tuple[str, ...]
    reordered_item_ids: tuple[str, ...]
    compacted_item_ids: tuple[str, ...]
    current_text: str
    updated_text: str
    relationship_plan: RelationshipUpdatePlan | None = None


@dataclass(frozen=True)
class RoadmapSliceContract:
    primary_roadmap_item: str
    execution_slice: str
    slice_goal: str
    covered_roadmap_items: tuple[str, ...]
    domain_context: str
    target_artifacts: tuple[str, ...]
    execution_policy: str
    closeout_boundary: str
    source_incubation: str
    source_research: str
    related_specs: tuple[str, ...]


@dataclass(frozen=True)
class RoadmapSynthesisReport:
    primary_roadmap_item: str
    execution_slice: str
    covered_roadmap_items: tuple[str, ...]
    domain_contexts: tuple[str, ...]
    target_artifacts: tuple[str, ...]
    related_specs: tuple[str, ...]
    source_inputs: tuple[str, ...]
    bundle_signals: tuple[str, ...]
    split_signals: tuple[str, ...]
    in_slice_dependencies: tuple[str, ...]
    verification_summary_count: int
    target_artifact_pressure: str
    phase_pressure: str


def make_roadmap_request(
    action: str | None,
    item_id: str | None,
    title: str | None = None,
    status: str | None = None,
    order: int | None = None,
    execution_slice: str | None = None,
    slice_goal: str | None = None,
    slice_closeout_boundary: str | None = None,
    source_incubation: str | None = None,
    source_research: str | None = None,
    related_plan: str | None = None,
    archived_plan: str | None = None,
    verification_summary: str | None = None,
    docs_decision: str | None = None,
    carry_forward: str | None = None,
    dependencies: list[str] | None = None,
    slice_members: list[str] | None = None,
    slice_dependencies: list[str] | None = None,
    related_specs: list[str] | None = None,
    target_artifacts: list[str] | None = None,
    supersedes: list[str] | None = None,
    superseded_by: list[str] | None = None,
) -> RoadmapRequest:
    return RoadmapRequest(
        action=str(action or "").strip().casefold().replace("_", "-"),
        item_id=_normalized_item_id(item_id),
        title=_normalized_text(title),
        status=_normalized_status(status),
        order=order,
        execution_slice=_normalized_item_id(execution_slice),
        slice_goal=_normalized_scalar(slice_goal),
        slice_closeout_boundary=_normalized_scalar(slice_closeout_boundary),
        source_incubation=_normalize_rel(source_incubation),
        source_research=_normalize_rel(source_research),
        related_plan=_normalize_rel(related_plan),
        archived_plan=_normalize_rel(archived_plan),
        verification_summary=_normalized_scalar(verification_summary),
        docs_decision=_normalized_status(docs_decision),
        carry_forward=_normalized_scalar(carry_forward),
        dependencies=tuple(_normalized_item_id(value) for value in dependencies or ()),
        slice_members=tuple(_normalized_item_id(value) for value in slice_members or ()),
        slice_dependencies=tuple(_normalized_item_id(value) for value in slice_dependencies or ()),
        related_specs=tuple(_normalize_rel(value) for value in related_specs or ()),
        target_artifacts=tuple(_normalize_rel(value) for value in target_artifacts or ()),
        supersedes=tuple(_normalized_item_id(value) for value in supersedes or ()),
        superseded_by=tuple(_normalized_item_id(value) for value in superseded_by or ()),
    )


def roadmap_plan_for_request(
    inventory: Inventory,
    request: RoadmapRequest,
    *,
    allowed_missing_paths: set[str] | None = None,
) -> tuple[RoadmapPlan | None, list[Finding]]:
    return _roadmap_plan(inventory, request, allowed_missing_paths=allowed_missing_paths)


def roadmap_plans_for_requests(
    inventory: Inventory,
    requests: tuple[RoadmapRequest, ...],
    *,
    allowed_missing_paths: set[str] | None = None,
) -> tuple[tuple[RoadmapPlan, ...], list[Finding]]:
    if not requests:
        return (), []

    errors: list[Finding] = []
    for request in requests:
        errors.extend(_request_errors(inventory, request))
    target_path = inventory.root / ROADMAP_REL
    errors.extend(_roadmap_target_errors(inventory, target_path))
    if errors:
        return (), errors

    try:
        text = target_path.read_text(encoding="utf-8")
    except OSError as exc:
        return (), [Finding("error", "roadmap-refused", f"roadmap could not be read: {exc}", ROADMAP_REL)]

    plans: list[RoadmapPlan] = []
    current_text = text
    for request in requests:
        plan, request_errors = _roadmap_plan_from_text(
            inventory,
            request,
            target_path,
            current_text,
            allowed_missing_paths=allowed_missing_paths or set(),
        )
        if request_errors:
            return (), request_errors
        assert plan is not None
        plans.append(plan)
        current_text = plan.updated_text
    return tuple(plans), []


def roadmap_item_fields(inventory: Inventory, item_id: str) -> dict[str, object]:
    target_path = inventory.root / ROADMAP_REL
    if not target_path.is_file():
        return {}
    try:
        text = target_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    parse_result = _parse_roadmap_items_for_sync(text)
    if parse_result[1]:
        return {}
    _items_start, _items_end, items = parse_result[0]
    item = items.get(_normalized_item_id(item_id))
    return dict(item.fields) if item else {}


def roadmap_slice_contract_for_item(inventory: Inventory, item_id: str) -> RoadmapSliceContract | None:
    target_path = inventory.root / ROADMAP_REL
    if not target_path.is_file():
        return None
    try:
        text = target_path.read_text(encoding="utf-8")
    except OSError:
        return None
    parse_result = _parse_roadmap_items_for_sync(text)
    if parse_result[1]:
        return None
    _items_start, _items_end, items = parse_result[0]
    normalized_item_id = _normalized_item_id(item_id)
    primary = items.get(normalized_item_id)
    if primary is None:
        return None

    primary_fields = primary.fields
    execution_slice = _normalized_item_id(primary_fields.get("execution_slice"))
    covered = _covered_item_ids(items, normalized_item_id, primary)
    covered_items = [items[item] for item in covered if item in items]
    slice_goal = _field_scalar(primary_fields, "slice_goal")
    closeout_boundary = _field_scalar(primary_fields, "slice_closeout_boundary") or "explicit-closeout-required"
    domain_context = slice_goal or execution_slice or primary.title or normalized_item_id
    return RoadmapSliceContract(
        primary_roadmap_item=normalized_item_id,
        execution_slice=execution_slice,
        slice_goal=slice_goal,
        covered_roadmap_items=covered,
        domain_context=domain_context,
        target_artifacts=tuple(_dedupe_nonempty(_values_from_items(covered_items, "target_artifacts"))),
        execution_policy="current-phase-only",
        closeout_boundary=closeout_boundary,
        source_incubation=_first_value_from_items([primary], "source_incubation"),
        source_research=_first_value_from_items(covered_items or [primary], "source_research"),
        related_specs=tuple(_dedupe_nonempty(_values_from_items(covered_items or [primary], "related_specs"))),
    )


def roadmap_synthesis_report_for_item(inventory: Inventory, item_id: str) -> RoadmapSynthesisReport | None:
    target_path = inventory.root / ROADMAP_REL
    if not target_path.is_file():
        return None
    try:
        text = target_path.read_text(encoding="utf-8")
    except OSError:
        return None
    parse_result = _parse_roadmap_items_for_sync(text)
    if parse_result[1]:
        return None
    _items_start, _items_end, items = parse_result[0]
    normalized_item_id = _normalized_item_id(item_id)
    primary = items.get(normalized_item_id)
    if primary is None:
        return None

    covered = _covered_item_ids(items, normalized_item_id, primary)
    covered_items = [(roadmap_item_id, items[roadmap_item_id]) for roadmap_item_id in covered if roadmap_item_id in items]
    execution_slice = _normalized_item_id(primary.fields.get("execution_slice"))
    target_artifacts = tuple(_dedupe_nonempty(_values_from_items([item for _, item in covered_items], "target_artifacts")))
    related_specs = tuple(_dedupe_nonempty(_values_from_items([item for _, item in covered_items], "related_specs")))
    source_inputs = tuple(
        _dedupe_nonempty(
            [
                *_values_from_items([item for _, item in covered_items], "source_incubation"),
                *_values_from_items([item for _, item in covered_items], "source_research"),
            ]
        )
    )
    domain_contexts = tuple(_dedupe_nonempty(_domain_context_for_item(roadmap_item_id, item) for roadmap_item_id, item in covered_items))
    shared_specs = _shared_values([item for _, item in covered_items], "related_specs")
    shared_targets = _shared_values([item for _, item in covered_items], "target_artifacts")
    shared_research = _shared_values([item for _, item in covered_items], "source_research")
    shared_incubation = _shared_values([item for _, item in covered_items], "source_incubation")
    shared_sources = shared_research + tuple(value for value in shared_incubation if value not in shared_research)
    in_slice_dependencies = _in_slice_dependencies(covered_items, set(covered))
    external_dependencies = _external_dependencies(covered_items, set(covered))

    bundle_signals: list[str] = []
    if execution_slice and len(covered) > 1:
        bundle_signals.append(f"shared execution_slice {execution_slice!r} covers {len(covered)} roadmap items")
    if shared_specs:
        bundle_signals.append(f"shared related_specs: {_summarize_values(shared_specs)}")
    if shared_targets:
        bundle_signals.append(f"shared target_artifacts: {len(shared_targets)} shared")
    if shared_sources:
        bundle_signals.append(f"shared source inputs: {_summarize_values(shared_sources)}")
    if in_slice_dependencies:
        bundle_signals.append(f"in-slice dependencies: {_summarize_values(in_slice_dependencies)}")
    if not bundle_signals:
        bundle_signals.append("no shared slice signals beyond the requested roadmap item")

    split_signals: list[str] = []
    if execution_slice:
        split_signals.append(f"items outside execution_slice {execution_slice!r} are excluded from this plan")
    else:
        split_signals.append("no execution_slice is recorded; synthesis is scoped to the requested roadmap item")
    if external_dependencies:
        split_signals.append(f"external dependencies remain outside the slice: {_summarize_values(external_dependencies)}")
    split_signals.append("bundle/split output is advisory and cannot approve lifecycle movement")

    verification_summary_count = sum(1 for _, item in covered_items if _field_scalar(item.fields, "verification_summary"))
    recommended_phase_count = _recommended_phase_count(
        covered_count=len(covered),
        target_count=len(target_artifacts),
        related_spec_count=len(related_specs),
        verification_summary_count=verification_summary_count,
    )
    return RoadmapSynthesisReport(
        primary_roadmap_item=normalized_item_id,
        execution_slice=execution_slice,
        covered_roadmap_items=covered,
        domain_contexts=domain_contexts,
        target_artifacts=target_artifacts,
        related_specs=related_specs,
        source_inputs=source_inputs,
        bundle_signals=tuple(bundle_signals),
        split_signals=tuple(split_signals),
        in_slice_dependencies=tuple(in_slice_dependencies),
        verification_summary_count=verification_summary_count,
        target_artifact_pressure=(
            f"{len(target_artifacts)} target artifacts across {len(covered)} roadmap items; "
            "report-only sizing signal, not a hard gate"
        ),
        phase_pressure=(
            f"{len(domain_contexts)} {_plural('domain context', len(domain_contexts))} and "
            f"{verification_summary_count} {_plural('verification summary', verification_summary_count)}; "
            f"candidate plan outline: {recommended_phase_count} {_plural('phase', recommended_phase_count)} or explicit one-shot rationale"
        ),
    )


def roadmap_dry_run_findings(inventory: Inventory, request: RoadmapRequest) -> list[Finding]:
    findings = [
        Finding("info", "roadmap-dry-run", "roadmap proposal only; no files were written"),
        _root_posture_finding(inventory),
    ]
    plan, errors = _roadmap_plan(inventory, request)
    findings.append(Finding("info", "roadmap-target", f"would target roadmap: {ROADMAP_REL}", ROADMAP_REL))
    findings.append(Finding("info", "roadmap-action", f"requested action: {request.action or '<empty>'}; item_id: {request.item_id or '<empty>'}", ROADMAP_REL))
    if plan:
        findings.extend(_plan_findings(plan, apply=False))
    if errors:
        findings.extend(_with_severity(errors, "warn"))
        findings.append(
            Finding(
                "info",
                "roadmap-validation-posture",
                "dry-run refused before apply; fix refusal reasons, then rerun dry-run before writing roadmap changes",
                ROADMAP_REL,
            )
        )
        return findings
    findings.extend(_boundary_findings())
    findings.append(
        Finding(
            "info",
            "roadmap-validation-posture",
            "apply would write only project/roadmap.md in an eligible live operating root; dry-run writes no files",
            ROADMAP_REL,
        )
    )
    return findings


def roadmap_apply_findings(inventory: Inventory, request: RoadmapRequest) -> list[Finding]:
    plan, errors = _roadmap_plan(inventory, request)
    if errors:
        return errors
    assert plan is not None

    if not _plan_has_changes(plan):
        return [
            Finding("info", "roadmap-apply", "roadmap apply started"),
            _root_posture_finding(inventory),
            Finding("info", "roadmap-noop", "roadmap item already matches requested fields; no file was rewritten", plan.target_rel),
            *_plan_findings(plan, apply=True),
            *_boundary_findings(),
        ]

    tmp_path = plan.target_path.with_name(f".{plan.target_path.name}.roadmap.tmp") if plan.current_text != plan.updated_text else None
    backup_path = plan.target_path.with_name(f".{plan.target_path.name}.roadmap.backup") if tmp_path else None
    relationship_tmp = _relationship_tmp_path(plan.relationship_plan)
    relationship_backup = _relationship_backup_path(plan.relationship_plan) if relationship_tmp else None
    for candidate, label in (
        (tmp_path, "temporary roadmap write path"),
        (backup_path, "temporary roadmap backup path"),
        (relationship_tmp, "temporary relationship write path"),
        (relationship_backup, "temporary relationship backup path"),
    ):
        if candidate and candidate.exists():
            return [Finding("error", "roadmap-refused", f"{label} already exists: {candidate.relative_to(inventory.root).as_posix()}")]

    operations: list[AtomicFileWrite] = []
    if tmp_path and backup_path:
        operations.append(AtomicFileWrite(plan.target_path, tmp_path, plan.updated_text, backup_path))
    if relationship_tmp and relationship_backup and plan.relationship_plan:
        operations.append(AtomicFileWrite(plan.relationship_plan.target_path, relationship_tmp, plan.relationship_plan.updated_text, relationship_backup))
    try:
        cleanup_warnings = apply_file_transaction(operations)
    except FileTransactionError as exc:
        return [Finding("error", "roadmap-refused", f"roadmap apply failed before all target writes completed: {exc}", plan.target_rel)]

    findings = [
        Finding("info", "roadmap-apply", "roadmap apply started"),
        _root_posture_finding(inventory),
        Finding("info", "roadmap-written", f"updated roadmap item {plan.item_id!r} with action {plan.action!r}", plan.target_rel),
        *_plan_findings(plan, apply=True),
        *_boundary_findings(),
        Finding("info", "roadmap-validation-posture", "run check after apply to verify the live operating root remains healthy; roadmap output is not lifecycle approval", plan.target_rel),
    ]
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "roadmap-backup-cleanup", warning, plan.target_rel))
    return findings


def _roadmap_plan(
    inventory: Inventory,
    request: RoadmapRequest,
    *,
    allowed_missing_paths: set[str] | None = None,
) -> tuple[RoadmapPlan | None, list[Finding]]:
    errors: list[Finding] = []
    errors.extend(_request_errors(inventory, request))
    target_path = inventory.root / ROADMAP_REL
    errors.extend(_roadmap_target_errors(inventory, target_path))
    if errors:
        return None, errors

    try:
        text = target_path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [Finding("error", "roadmap-refused", f"roadmap could not be read: {exc}", ROADMAP_REL)]

    return _roadmap_plan_from_text(
        inventory,
        request,
        target_path,
        text,
        allowed_missing_paths=allowed_missing_paths or set(),
    )


def _roadmap_plan_from_text(
    inventory: Inventory,
    request: RoadmapRequest,
    target_path: Path,
    text: str,
    *,
    allowed_missing_paths: set[str],
) -> tuple[RoadmapPlan | None, list[Finding]]:
    parse_result = _parse_roadmap_items_for_sync(text)
    if parse_result[1]:
        return None, parse_result[1]
    items_start, items_end, items = parse_result[0]
    existing = items.get(request.item_id)
    if request.action == "add" and existing:
        return None, [Finding("error", "roadmap-refused", f"roadmap item id already exists: {request.item_id}", ROADMAP_REL)]
    if request.action == "update" and not existing:
        return None, [Finding("error", "roadmap-refused", f"roadmap item id does not exist: {request.item_id}", ROADMAP_REL)]

    errors: list[Finding] = []
    errors.extend(_relationship_errors(inventory, request, set(items), allowed_missing_paths or set()))
    if errors:
        return None, errors
    relationship_plan = None
    if request.source_incubation:
        relationship_plan, relationship_errors = relationship_update_plan(
            inventory,
            request.source_incubation,
            {
                "related_roadmap": ROADMAP_REL,
                "related_roadmap_item": request.item_id,
                "promoted_to": ROADMAP_REL,
            },
        )
        if relationship_errors:
            return None, relationship_errors
        relationship_plan = _relationship_plan_without_queued_active_plan_leak(inventory, request, relationship_plan)

    lines = text.splitlines(keepends=True)
    if request.action == "add":
        if items_start < 0:
            return None, [
                Finding(
                    "error",
                    "roadmap-refused",
                    "legacy top-level roadmap sections support update only; add requires a canonical ## Items section",
                    ROADMAP_REL,
                )
            ]
        fields = _new_item_fields(request)
        block = _render_item_block(request.title, fields)
        insert_at = items_end
        if insert_at > 0 and lines[insert_at - 1].strip():
            block = "\n" + block
        updated_lines = [*lines[:insert_at], block, *lines[insert_at:]]
        changed_fields = tuple(field for field in STANDARD_FIELDS if field in fields)
        updated_text = "".join(updated_lines)
    else:
        assert existing is not None
        fields = _updated_item_fields(existing.fields, request)
        changed_fields = tuple(field for field in STANDARD_FIELDS if existing.fields.get(field, _empty_field_value(field)) != fields.get(field, _empty_field_value(field)))
        if changed_fields:
            block = (
                _render_updated_legacy_item_block(lines[existing.start : existing.end], changed_fields, fields)
                if existing.style == "legacy"
                else _render_item_block(existing.title, fields)
            )
            updated_text = "".join([*lines[: existing.start], block, *lines[existing.end :]])
        else:
            updated_text = text

    updated_text, reordered_item_ids = _order_accepted_item_blocks(updated_text)
    if reordered_item_ids:
        changed_fields = (*changed_fields, ACCEPTED_ITEM_ORDER_FIELD)

    refreshed_text = _refresh_future_execution_slice_queue(updated_text)
    if refreshed_text != updated_text:
        changed_fields = (*changed_fields, FUTURE_QUEUE_FIELD)
        updated_text = refreshed_text

    refreshed_text, compacted_item_ids = _refresh_archived_completed_history(updated_text)
    if refreshed_text != updated_text:
        changed_fields = (*changed_fields, ARCHIVED_HISTORY_FIELD)
        updated_text = refreshed_text

    return (
        RoadmapPlan(
            action=request.action,
            item_id=request.item_id,
            target_rel=ROADMAP_REL,
            target_path=target_path,
            changed_fields=changed_fields,
            reordered_item_ids=reordered_item_ids,
            compacted_item_ids=compacted_item_ids,
            current_text=text,
            updated_text=updated_text,
            relationship_plan=relationship_plan,
        ),
        [],
    )


def _request_errors(inventory: Inventory, request: RoadmapRequest) -> list[Finding]:
    errors: list[Finding] = []
    if inventory.root_kind == "product_source_fixture":
        errors.append(Finding("error", "roadmap-refused", "target is a product-source compatibility fixture; roadmap --apply is refused", ROADMAP_REL))
    elif inventory.root_kind == "fallback_or_archive":
        errors.append(Finding("error", "roadmap-refused", "target is fallback/archive or generated-output evidence; roadmap --apply is refused", ROADMAP_REL))
    elif inventory.root_kind != "live_operating_root":
        errors.append(Finding("error", "roadmap-refused", f"target root kind is {inventory.root_kind}; roadmap requires a live operating root", ROADMAP_REL))

    if request.action not in {"add", "update"}:
        errors.append(Finding("error", "roadmap-refused", "--action must be one of: add, update"))
    if not request.item_id or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", request.item_id):
        errors.append(Finding("error", "roadmap-refused", "--item-id must be a lowercase ASCII id using letters, numbers, and hyphens only"))
    if request.action == "add":
        if not request.title:
            errors.append(Finding("error", "roadmap-refused", "--title is required for --action add"))
        if not request.status:
            errors.append(Finding("error", "roadmap-refused", "--status is required for --action add"))
        if request.order is None:
            errors.append(Finding("error", "roadmap-refused", "--order is required for --action add"))
    if request.status and request.status not in ROADMAP_STATUS_VALUES:
        errors.append(Finding("error", "roadmap-refused", f"--status must be one of: {', '.join(sorted(ROADMAP_STATUS_VALUES))}"))
    if request.docs_decision and request.docs_decision not in DOCS_DECISION_VALUES:
        errors.append(Finding("error", "roadmap-refused", f"--docs-decision must be one of: {', '.join(sorted(DOCS_DECISION_VALUES))}"))
    if request.order is not None and request.order < 0:
        errors.append(Finding("error", "roadmap-refused", "--order must be a non-negative integer"))
    if request.execution_slice and not re.fullmatch(r"[a-z0-9][a-z0-9-]*", request.execution_slice):
        errors.append(Finding("error", "roadmap-refused", "--execution-slice must be a lowercase ASCII id using letters, numbers, and hyphens only"))
    for field, value in _scalar_request_fields(request).items():
        if "\n" in value or "\r" in value or "`" in value:
            errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} must be a single line without backticks", ROADMAP_REL))
    for field, values in _item_id_list_request_fields(request).items():
        if len(values) != len(set(values)):
            errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} contains duplicate item ids", ROADMAP_REL))
        for value in values:
            if not value or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", value):
                errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} values must be lowercase ASCII item ids", ROADMAP_REL))
            if value == request.item_id and field != "slice_members":
                errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} cannot point at the target item itself: {value}", ROADMAP_REL))
    for field, values in _path_list_request_fields(request).items():
        if len(values) != len(set(values)):
            errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} contains duplicate paths", ROADMAP_REL))
        for value in values:
            if "\n" in value or "\r" in value or "`" in value:
                errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} values must be single-line paths without backticks", ROADMAP_REL))
    for field, values in _artifact_list_request_fields(request).items():
        if len(values) != len(set(values)):
            errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} contains duplicate paths", ROADMAP_REL))
        for value in values:
            if "\n" in value or "\r" in value or "`" in value:
                errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} values must be single-line paths without backticks", ROADMAP_REL))
            if _rel_has_absolute_or_parent_parts(value):
                errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} values must be root-relative paths without parent segments", ROADMAP_REL))

    state = inventory.state
    if state is None or not state.exists:
        errors.append(Finding("error", "roadmap-refused", "project-state.md is missing", "project/project-state.md"))
    elif not state.frontmatter.has_frontmatter:
        errors.append(Finding("error", "roadmap-refused", "project-state.md frontmatter is required for roadmap apply", state.rel_path))
    elif state.frontmatter.errors:
        errors.append(Finding("error", "roadmap-refused", "project-state.md frontmatter is malformed", state.rel_path))
    elif not state.path.is_file():
        errors.append(Finding("error", "roadmap-refused", "project-state.md is not a regular file", state.rel_path))
    elif state.path.is_symlink():
        errors.append(Finding("error", "roadmap-refused", "project-state.md is a symlink", state.rel_path))
    return errors


def _roadmap_target_errors(inventory: Inventory, target_path: Path) -> list[Finding]:
    errors: list[Finding] = []
    if _path_escapes_root(inventory.root, target_path):
        errors.append(Finding("error", "roadmap-refused", "roadmap path escapes the target root", ROADMAP_REL))
        return errors
    for parent in _parents_between(inventory.root, target_path.parent):
        rel = parent.relative_to(inventory.root).as_posix()
        if parent.exists() and parent.is_symlink():
            errors.append(Finding("error", "roadmap-refused", f"roadmap path contains a symlink segment: {rel}", rel))
        elif parent.exists() and not parent.is_dir():
            errors.append(Finding("error", "roadmap-refused", f"roadmap path contains a non-directory segment: {rel}", rel))
    if not target_path.exists():
        errors.append(Finding("error", "roadmap-refused", "project/roadmap.md is missing", ROADMAP_REL))
    elif target_path.is_symlink():
        errors.append(Finding("error", "roadmap-refused", "project/roadmap.md is a symlink", ROADMAP_REL))
    elif not target_path.is_file():
        errors.append(Finding("error", "roadmap-refused", "project/roadmap.md is not a regular file", ROADMAP_REL))
    return errors


def _parse_roadmap_items(text: str) -> tuple[tuple[int, int, dict[str, RoadmapItem]], list[Finding]]:
    lines = text.splitlines(keepends=True)
    if lines and lines[0].strip() == "---":
        closing_index = None
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                closing_index = index
                break
        if closing_index is None:
            return (0, 0, {}), [Finding("error", "roadmap-refused", "project/roadmap.md frontmatter is malformed", ROADMAP_REL)]

    items_heading = None
    for index, line in enumerate(lines):
        if re.match(r"^##\s+Items\s*$", line.strip()):
            items_heading = index
            break
    if items_heading is None:
        return (0, 0, {}), [Finding("error", "roadmap-refused", "project/roadmap.md must contain a ## Items section", ROADMAP_REL)]

    items_end = len(lines)
    for index in range(items_heading + 1, len(lines)):
        if re.match(r"^##\s+\S", lines[index].strip()):
            items_end = index
            break

    block_starts = [index for index in range(items_heading + 1, items_end) if re.match(r"^###\s+.+\s*$", lines[index].strip())]
    if not block_starts:
        return (0, 0, {}), [Finding("error", "roadmap-refused", "project/roadmap.md ## Items section has no managed item blocks", ROADMAP_REL)]

    items: dict[str, RoadmapItem] = {}
    errors: list[Finding] = []
    for position, start in enumerate(block_starts):
        end = block_starts[position + 1] if position + 1 < len(block_starts) else items_end
        title = re.sub(r"^###\s+", "", lines[start].strip()).strip()
        fields = _parse_item_fields(lines[start:end])
        item_id = fields.get("id")
        if not isinstance(item_id, str) or not item_id:
            errors.append(Finding("error", "roadmap-refused", f"roadmap item block lacks an id field: {title}", ROADMAP_REL, start + 1))
            continue
        if item_id in items:
            errors.append(Finding("error", "roadmap-refused", f"duplicate roadmap item id: {item_id}", ROADMAP_REL, start + 1))
            continue
        items[item_id] = RoadmapItem(title=title, fields=fields, start=start, end=end)
    if errors:
        return (0, 0, {}), errors
    return (items_heading + 1, items_end, items), []


def _parse_roadmap_items_for_sync(text: str) -> tuple[tuple[int, int, dict[str, RoadmapItem]], list[Finding]]:
    parse_result = _parse_roadmap_items(text)
    if not parse_result[1]:
        return parse_result
    findings = parse_result[1]
    if len(findings) != 1 or "must contain a ## Items section" not in findings[0].message:
        return parse_result

    legacy_result = _parse_legacy_roadmap_items(text)
    if legacy_result[1] or not legacy_result[0][2]:
        return parse_result
    return legacy_result


def _parse_legacy_roadmap_items(text: str) -> tuple[tuple[int, int, dict[str, RoadmapItem]], list[Finding]]:
    lines = text.splitlines(keepends=True)
    content_start = 0
    if lines and lines[0].strip() == "---":
        closing_index = None
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                closing_index = index
                break
        if closing_index is None:
            return (0, 0, {}), [Finding("error", "roadmap-refused", "project/roadmap.md frontmatter is malformed", ROADMAP_REL)]
        content_start = closing_index + 1

    block_starts = [index for index in range(content_start, len(lines)) if _legacy_item_heading_match(lines[index])]
    if not block_starts:
        return (0, 0, {}), []

    items: dict[str, RoadmapItem] = {}
    errors: list[Finding] = []
    for position, start in enumerate(block_starts):
        end = block_starts[position + 1] if position + 1 < len(block_starts) else len(lines)
        heading_match = _legacy_item_heading_match(lines[start])
        assert heading_match is not None
        heading_id = _normalized_item_id(heading_match.group("id"))
        title = re.sub(r"^##\s+", "", lines[start].strip()).strip()
        fields = _parse_legacy_item_fields(lines[start:end])
        item_id = _normalized_item_id(fields.get("id") or heading_id)
        if not item_id:
            errors.append(Finding("error", "roadmap-refused", f"legacy roadmap section lacks an id field: {title}", ROADMAP_REL, start + 1))
            continue
        if item_id in items:
            errors.append(Finding("error", "roadmap-refused", f"duplicate roadmap item id: {item_id}", ROADMAP_REL, start + 1))
            continue
        fields["id"] = item_id
        items[item_id] = RoadmapItem(title=title, fields=fields, start=start, end=end, style="legacy")
    if errors:
        return (0, 0, {}), errors
    return (-1, len(lines), items), []


def _legacy_item_heading_match(line: str) -> re.Match[str] | None:
    return re.match(r"^##\s+(?P<id>RM-[0-9]+)\b.*$", line.strip(), re.IGNORECASE)


def _refresh_future_execution_slice_queue(text: str) -> str:
    lines = text.splitlines(keepends=True)
    bounds = _h2_section_bounds(lines, FUTURE_QUEUE_TITLE)
    if bounds is None:
        return text

    parse_result = _parse_roadmap_items(text)
    if parse_result[1]:
        return text
    _items_start, _items_end, items = parse_result[0]

    start, end = bounds
    body = lines[start + 1 : end]
    kept_body: list[str] = []
    removed_completed_bullets = 0
    remaining_queue_bullets = 0
    for line in body:
        item_ids = _future_queue_bullet_item_ids(line)
        if item_ids:
            known_statuses = [_normalized_status(items[item_id].fields.get("status")) for item_id in item_ids if item_id in items]
            if len(known_statuses) == len(item_ids) and all(status in TERMINAL_QUEUE_STATUSES for status in known_statuses):
                removed_completed_bullets += 1
                continue
            remaining_queue_bullets += 1
        kept_body.append(line)

    if not removed_completed_bullets:
        return text

    if remaining_queue_bullets:
        replacement = [lines[start], *kept_body]
    else:
        replacement = [
            lines[start],
            "\n",
            "No future execution slice is currently queued in this roadmap. Completed or retired slice history lives in archived plans and in terminal item metadata below.\n",
            "\n",
            "Open the next slice only through an explicit plan request or accepted roadmap update. Incubation notes remain possible inputs, not queued work by themselves.\n",
            "\n",
        ]
    return "".join([*lines[:start], *replacement, *lines[end:]])


def _refresh_archived_completed_history(text: str) -> tuple[str, tuple[str, ...]]:
    parse_result = _parse_roadmap_items(text)
    if parse_result[1]:
        return text, ()
    items_start, _items_end, items = parse_result[0]
    done_items = [
        (item_id, item)
        for item_id, item in sorted(items.items(), key=lambda row: (row[1].start, row[0]))
        if _normalized_status(item.fields.get("status")) == "done"
    ]
    excess = len(done_items) - DETAILED_DONE_TAIL_LIMIT
    if excess <= 0:
        return text, ()

    to_compact: list[tuple[str, RoadmapItem]] = []
    for item_id, item in done_items:
        if excess <= 0:
            break
        if not _roadmap_item_has_compaction_evidence(item):
            continue
        to_compact.append((item_id, item))
        excess -= 1
    if not to_compact:
        return text, ()

    lines = text.splitlines(keepends=True)
    compacted_ids = tuple(item_id for item_id, _item in to_compact)
    remove_ranges = tuple((item.start, item.end) for _item_id, item in to_compact)
    kept_lines = [line for index, line in enumerate(lines) if not any(start <= index < end for start, end in remove_ranges)]
    history_entries = _compacted_history_entries(lines, to_compact)
    if history_entries:
        kept_lines = _with_archived_history_entries(kept_lines, history_entries, fallback_insert_at=items_start)
    return "".join(kept_lines), compacted_ids


def _roadmap_item_has_compaction_evidence(item: RoadmapItem) -> bool:
    archived_plan = _field_scalar(item.fields, "archived_plan")
    docs_decision = _field_scalar(item.fields, "docs_decision")
    return (
        archived_plan.startswith("project/archive/plans/")
        and bool(_field_scalar(item.fields, "verification_summary"))
        and docs_decision in {"updated", "not-needed"}
    )


def _compacted_history_entries(lines: list[str], items: list[tuple[str, RoadmapItem]]) -> list[str]:
    bounds = _h2_section_bounds(lines, ARCHIVED_HISTORY_TITLE)
    existing_history = "".join(lines[bounds[0] + 1 : bounds[1]]) if bounds else ""
    entries: list[str] = []
    for item_id, item in items:
        if f"`{item_id}`" in existing_history:
            continue
        archived_plan = _field_scalar(item.fields, "archived_plan")
        entries.append(f"- Compacted done roadmap item `{item_id}`: archived plan `{archived_plan}`.\n")
    return entries


def _with_archived_history_entries(lines: list[str], entries: list[str], *, fallback_insert_at: int) -> list[str]:
    bounds = _h2_section_bounds(lines, ARCHIVED_HISTORY_TITLE)
    if bounds is None:
        section = [
            "## Archived Completed History\n",
            "\n",
            "Detailed done roadmap item blocks compacted out of the live tail remain available through archived plans.\n",
            "\n",
            *entries,
            "\n",
        ]
        insert_at = max(0, min(fallback_insert_at, len(lines)))
        if insert_at > 0 and lines[insert_at - 1].strip():
            section.insert(0, "\n")
        return [*lines[:insert_at], *section, *lines[insert_at:]]

    _start, end = bounds
    insertion = [*entries]
    if end > 0 and lines[end - 1].strip():
        insertion.insert(0, "\n")
    insertion.append("\n")
    return [*lines[:end], *insertion, *lines[end:]]


def _h2_section_bounds(lines: list[str], title: str) -> tuple[int, int] | None:
    start = None
    title_pattern = re.compile(rf"^##\s+{re.escape(title)}\s*$")
    for index, line in enumerate(lines):
        if title_pattern.match(line.strip()):
            start = index
            break
    if start is None:
        return None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if re.match(r"^##\s+\S", lines[index].strip()):
            end = index
            break
    return start, end


def _future_queue_bullet_item_ids(line: str) -> tuple[str, ...]:
    if not re.match(r"^\s*-\s+", line):
        return ()
    match = re.search(r"\bItems:\s*(.+)$", line)
    if not match:
        return ()
    return tuple(_dedupe_nonempty(_normalized_item_id(value) for value in re.findall(r"`([^`]+)`", match.group(1))))


def _order_accepted_item_blocks(text: str) -> tuple[str, tuple[str, ...]]:
    parse_result = _parse_roadmap_items(text)
    if parse_result[1]:
        return text, ()
    _items_start, _items_end, items = parse_result[0]
    item_entries = sorted(items.items(), key=lambda row: (row[1].start, row[0]))
    accepted_entries = [
        (item_id, item)
        for item_id, item in item_entries
        if _normalized_status(item.fields.get("status")) == "accepted"
    ]
    if len(accepted_entries) < 2:
        return text, ()

    ordered_entries = sorted(accepted_entries, key=lambda row: (_order_sort_key(row[1]), row[1].start, row[0]))
    original_ids = tuple(item_id for item_id, _item in accepted_entries)
    ordered_ids = tuple(item_id for item_id, _item in ordered_entries)
    if original_ids == ordered_ids:
        return text, ()

    lines = text.splitlines(keepends=True)
    rebuilt: list[str] = []
    cursor = 0
    ordered_index = 0
    for _item_id, item in item_entries:
        rebuilt.extend(lines[cursor : item.start])
        if _normalized_status(item.fields.get("status")) == "accepted":
            _ordered_item_id, ordered_item = ordered_entries[ordered_index]
            rebuilt.extend(lines[ordered_item.start : ordered_item.end])
            ordered_index += 1
        else:
            rebuilt.extend(lines[item.start : item.end])
        cursor = item.end
    rebuilt.extend(lines[cursor:])
    moved_ids = tuple(item_id for index, item_id in enumerate(ordered_ids) if original_ids[index] != item_id)
    return "".join(rebuilt), moved_ids


def _order_sort_key(item: RoadmapItem) -> tuple[int, int | str]:
    order = item.fields.get("order")
    if isinstance(order, int):
        return (0, order)
    try:
        return (0, int(str(order).strip()))
    except ValueError:
        return (1, str(order or ""))


def _covered_item_ids(items: dict[str, RoadmapItem], normalized_item_id: str, primary: RoadmapItem) -> tuple[str, ...]:
    primary_fields = primary.fields
    execution_slice = _normalized_item_id(primary_fields.get("execution_slice"))
    explicit_members = tuple(_normalized_item_id(value) for value in _field_list(primary_fields, "slice_members"))
    if explicit_members:
        members = tuple(member for member in explicit_members if member in items)
        if not members:
            members = (normalized_item_id,)
    elif execution_slice:
        members = tuple(
            roadmap_item_id
            for roadmap_item_id, roadmap_item in sorted(items.items(), key=lambda row: (row[1].start, row[0]))
            if _normalized_item_id(roadmap_item.fields.get("execution_slice")) == execution_slice
        )
    else:
        members = (normalized_item_id,)
    return tuple(_dedupe_nonempty((normalized_item_id, *members)))


def _parse_item_fields(lines: list[str]) -> dict[str, object]:
    fields: dict[str, object] = {}
    for line in lines:
        match = re.match(r"^-\s+`([A-Za-z0-9_-]+)`:\s*(.*?)\s*$", line.strip())
        if not match:
            continue
        key = match.group(1)
        raw = match.group(2).strip()
        if raw.startswith("`") and raw.endswith("`"):
            raw = raw[1:-1]
        if key in LIST_FIELDS:
            fields[key] = _parse_list_value(raw)
        elif key == "order":
            try:
                fields[key] = int(raw)
            except ValueError:
                fields[key] = raw
        else:
            fields[key] = raw
    for key in LIST_FIELDS:
        fields.setdefault(key, [])
    return fields


def _parse_legacy_item_fields(lines: list[str]) -> dict[str, object]:
    fields: dict[str, object] = {}
    for index, line in enumerate(lines):
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*?)\s*$", line.strip())
        if not match:
            continue
        key = match.group(1)
        raw = match.group(2).strip()
        if key in LIST_FIELDS:
            fields[key] = _parse_legacy_list_field(lines, index, raw)
        elif key == "order":
            try:
                fields[key] = int(_strip_quotes(raw))
            except ValueError:
                fields[key] = _strip_quotes(raw)
        else:
            fields[key] = _strip_quotes(raw)
    for key in LIST_FIELDS:
        fields.setdefault(key, [])
    return fields


def _parse_legacy_list_field(lines: list[str], index: int, raw: str) -> list[str]:
    if raw:
        parsed = _parse_list_value(raw)
        if parsed:
            return parsed
        scalar = _strip_quotes(raw)
        return [scalar] if scalar and scalar != "[]" else []
    values: list[str] = []
    for line in lines[index + 1 :]:
        match = re.match(r"^\s*-\s+(.+?)\s*$", line)
        if not match:
            break
        values.append(_strip_quotes(match.group(1).strip()))
    return values


def _parse_list_value(raw: str) -> list[str]:
    if not raw:
        return []
    try:
        value = ast.literal_eval(raw)
    except (SyntaxError, ValueError):
        return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _new_item_fields(request: RoadmapRequest) -> dict[str, object]:
    return {
        "id": request.item_id,
        "status": request.status,
        "order": request.order if request.order is not None else 0,
        "execution_slice": request.execution_slice,
        "slice_goal": request.slice_goal,
        "slice_members": list(request.slice_members),
        "slice_dependencies": list(request.slice_dependencies),
        "slice_closeout_boundary": request.slice_closeout_boundary,
        "dependencies": list(request.dependencies),
        "source_incubation": request.source_incubation,
        "source_research": request.source_research,
        "related_specs": list(request.related_specs),
        "related_plan": request.related_plan,
        "archived_plan": request.archived_plan,
        "target_artifacts": list(request.target_artifacts),
        "verification_summary": request.verification_summary,
        "docs_decision": request.docs_decision,
        "carry_forward": request.carry_forward,
        "supersedes": list(request.supersedes),
        "superseded_by": list(request.superseded_by),
    }


def _updated_item_fields(current: dict[str, object], request: RoadmapRequest) -> dict[str, object]:
    fields = dict(current)
    for key in STANDARD_FIELDS:
        fields.setdefault(key, _empty_field_value(key))
    fields["id"] = request.item_id
    if request.status:
        fields["status"] = request.status
    if request.order is not None:
        fields["order"] = request.order
    for key, value in _scalar_request_fields(request).items():
        if key in {"status", "order"} or not value:
            continue
        fields[key] = value
    if request.docs_decision:
        fields["docs_decision"] = request.docs_decision
    for key, values in _list_request_fields(request).items():
        if values:
            fields[key] = list(values)
    return fields


def _render_item_block(title: str, fields: dict[str, object]) -> str:
    lines = [f"### {title}\n", "\n"]
    for key in STANDARD_FIELDS:
        value = fields.get(key, _empty_field_value(key))
        if key in LIST_FIELDS:
            rendered = json.dumps(list(value) if isinstance(value, list) else [], ensure_ascii=True)
        elif key == "order":
            rendered = str(value if value not in (None, "") else 0)
        else:
            rendered = str(value or "")
        lines.append(f"- `{key}`: `{rendered}`\n")
    lines.append("\n")
    return "".join(lines)


def _render_updated_legacy_item_block(block_lines: list[str], changed_fields: tuple[str, ...], fields: dict[str, object]) -> str:
    updated_lines = list(block_lines)
    newline = "\r\n" if any(line.endswith("\r\n") for line in block_lines) else "\n"
    for field in changed_fields:
        replacement = _render_legacy_field(field, fields.get(field, _empty_field_value(field)), newline)
        spans = _legacy_field_spans(updated_lines)
        span = spans.get(field)
        if span:
            start, end = span
            updated_lines[start:end] = replacement
            continue
        insert_at = _legacy_field_insert_index(updated_lines)
        updated_lines[insert_at:insert_at] = replacement
    return "".join(updated_lines)


def _legacy_field_spans(lines: list[str]) -> dict[str, tuple[int, int]]:
    spans: dict[str, tuple[int, int]] = {}
    index = 0
    while index < len(lines):
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*?)\s*$", lines[index].strip())
        if not match:
            index += 1
            continue
        key = match.group(1)
        end = index + 1
        while end < len(lines) and re.match(r"^\s*-\s+.+\s*$", lines[end]):
            end += 1
        spans[key] = (index, end)
        index = end
    return spans


def _legacy_field_insert_index(lines: list[str]) -> int:
    index = len(lines)
    while index > 0 and not lines[index - 1].strip():
        index -= 1
    return index


def _render_legacy_field(field: str, value: object, newline: str) -> list[str]:
    if field in LIST_FIELDS:
        values = _field_value_list(value)
        if not values:
            return [f"{field}: []{newline}"]
        return [f"{field}:{newline}", *(f'  - "{_legacy_quoted_value(item)}"{newline}' for item in values)]
    if field == "order":
        rendered = str(value if value not in (None, "") else 0)
        return [f"{field}: {rendered}{newline}"]
    return [f'{field}: "{_legacy_quoted_value(str(value or ""))}"{newline}']


def _field_value_list(value: object) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        parsed = _parse_list_value(value) if value.startswith("[") and value.endswith("]") else [value]
        return [str(item) for item in parsed if str(item).strip()]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _legacy_quoted_value(value: object) -> str:
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"')


def _relationship_errors(
    inventory: Inventory,
    request: RoadmapRequest,
    item_ids: set[str],
    allowed_missing_paths: set[str],
) -> list[Finding]:
    errors: list[Finding] = []
    for field, value in _scalar_request_fields(request).items():
        if field not in PATH_FIELDS or not value:
            continue
        errors.extend(_path_relationship_errors(inventory, field, value, allowed_missing_paths))
    for field, values in _path_list_request_fields(request).items():
        for value in values:
            errors.extend(_path_relationship_errors(inventory, field, value, allowed_missing_paths))
    for field, values in _item_id_list_request_fields(request).items():
        allowed_item_ids = set(item_ids)
        if field == "slice_members":
            allowed_item_ids.add(request.item_id)
        for value in values:
            if value not in allowed_item_ids:
                errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} target item id is missing: {value}", ROADMAP_REL))
    return errors


def _path_relationship_errors(
    inventory: Inventory,
    field: str,
    rel_path: str,
    allowed_missing_paths: set[str],
) -> list[Finding]:
    errors: list[Finding] = []
    if _rel_has_absolute_or_parent_parts(rel_path):
        return [Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} must be a root-relative path without parent segments", ROADMAP_REL)]
    if not rel_path.endswith(".md"):
        errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} must point to a Markdown route", rel_path))
    if not _route_destination_allowed(field, rel_path):
        errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} points at an incompatible route: {rel_path}", rel_path))
    path = inventory.root / rel_path
    if _path_escapes_root(inventory.root, path):
        errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} path escapes the target root", rel_path))
        return errors
    for parent in _parents_between(inventory.root, path.parent):
        parent_rel = parent.relative_to(inventory.root).as_posix()
        if parent.exists() and parent.is_symlink():
            errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} path contains a symlink segment: {parent_rel}", parent_rel))
        elif parent.exists() and not parent.is_dir():
            errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} path contains a non-directory segment: {parent_rel}", parent_rel))
    if not path.exists():
        if _normalize_rel(rel_path) not in allowed_missing_paths:
            errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} target is missing: {rel_path}", rel_path))
    elif path.is_symlink():
        errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} target is a symlink", rel_path))
    elif not path.is_file():
        errors.append(Finding("error", "roadmap-refused", f"--{field.replace('_', '-')} target is not a regular file", rel_path))
    return errors


def _route_destination_allowed(field: str, rel_path: str) -> bool:
    if field == "source_incubation":
        return rel_path.startswith("project/plan-incubation/") or rel_path.startswith("project/archive/reference/incubation/")
    if field == "source_research":
        return rel_path.startswith("project/research/") or rel_path.startswith("project/archive/reference/research/")
    if field == "related_specs":
        return rel_path.startswith("project/specs/") or rel_path.startswith("docs/specs/")
    if field in {"related_plan", "archived_plan"}:
        return rel_path == "project/implementation-plan.md" or rel_path.startswith("project/archive/plans/")
    return True


def _plan_findings(plan: RoadmapPlan, apply: bool) -> list[Finding]:
    prefix = "" if apply else "would "
    findings = [
        Finding("info", "roadmap-plan", f"{prefix}{plan.action} roadmap item: {plan.item_id}", plan.target_rel),
        Finding("info", "roadmap-target-file", f"{prefix}write boundary: {plan.target_rel}", plan.target_rel),
    ]
    if plan.changed_fields:
        findings.extend(
            Finding("info", "roadmap-changed-field", f"{prefix}change field: {field}", plan.target_rel)
            for field in plan.changed_fields
        )
    else:
        message = "no roadmap fields would change" if not apply else "no roadmap fields changed"
        findings.append(Finding("info", "roadmap-noop", message, plan.target_rel))
    if plan.compacted_item_ids:
        findings.append(
            Finding(
                "info",
                "roadmap-live-tail-compaction",
                f"{prefix}compact done roadmap item block(s): {', '.join(plan.compacted_item_ids)}",
                plan.target_rel,
            )
        )
    if plan.reordered_item_ids:
        findings.append(
            Finding(
                "info",
                "roadmap-order-aware-insertion",
                f"{prefix}order accepted roadmap item block(s): {', '.join(plan.reordered_item_ids)}",
                plan.target_rel,
            )
        )
    if plan.relationship_plan:
        findings.extend(_relationship_plan_findings(plan.relationship_plan, apply))
    return findings


def _relationship_plan_findings(plan: RelationshipUpdatePlan, apply: bool) -> list[Finding]:
    prefix = "" if apply else "would "
    findings = [
        Finding("info", "roadmap-relationship-sync", f"{prefix}sync source incubation relationship metadata", plan.source_rel),
        Finding("info", "roadmap-relationship-target", f"{prefix}write relationship target: {plan.target_rel}", plan.target_rel),
    ]
    if plan.changed_fields:
        findings.extend(
            Finding("info", "roadmap-relationship-changed-field", f"{prefix}change source incubation field: {field}", plan.source_rel)
            for field in plan.changed_fields
        )
    else:
        findings.append(Finding("info", "roadmap-relationship-noop", "source incubation relationship metadata already matches requested roadmap item", plan.source_rel))
    return findings


def _relationship_plan_without_queued_active_plan_leak(
    inventory: Inventory,
    request: RoadmapRequest,
    plan: RelationshipUpdatePlan | None,
) -> RelationshipUpdatePlan | None:
    if plan is None:
        return None
    if request.related_plan == DEFAULT_PLAN_REL or _roadmap_item_owned_by_active_plan(inventory, request.item_id):
        return plan
    if not _source_text_is_fix_candidate(plan.current_text):
        return plan
    if _frontmatter_scalar(plan.current_text, "related_plan") != DEFAULT_PLAN_REL:
        return plan

    updated_text, changed = _text_with_empty_frontmatter_scalar(plan.updated_text, "related_plan")
    if not changed:
        return plan
    changed_fields = tuple(_dedupe_nonempty((*plan.changed_fields, "related_plan")))
    return replace(plan, updated_text=updated_text, changed_fields=changed_fields)


def _roadmap_item_owned_by_active_plan(inventory: Inventory, item_id: str) -> bool:
    state = inventory.state
    if state is None or not state.exists or not state.frontmatter.has_frontmatter or state.frontmatter.errors:
        return False
    state_data = state.frontmatter.data
    if str(state_data.get("plan_status") or "").strip() != "active":
        return False
    if _normalize_rel(state_data.get("active_plan")) != DEFAULT_PLAN_REL:
        return False
    plan = inventory.active_plan_surface
    if plan is None or not plan.exists or plan.path.is_symlink() or not plan.path.is_file():
        return False
    if not plan.frontmatter.has_frontmatter or plan.frontmatter.errors:
        return False

    normalized_item_id = _normalized_item_id(item_id)
    plan_data = plan.frontmatter.data
    owned_items = {
        _normalized_item_id(plan_data.get("primary_roadmap_item")),
        _normalized_item_id(plan_data.get("related_roadmap_item")),
    }
    owned_items.update(_normalized_item_id(value) for value in _frontmatter_list_values(plan_data.get("covered_roadmap_items")))
    return normalized_item_id in owned_items


def _source_text_is_fix_candidate(text: str) -> bool:
    return "[MLH-Fix-Candidate]" in text


def _frontmatter_scalar(text: str, key: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for line in lines[1:]:
        if line.strip() == "---":
            return ""
        match = re.match(rf"^{re.escape(key)}:\s*(.*?)\s*$", line)
        if match:
            return _strip_quotes(match.group(1).strip())
    return ""


def _text_with_empty_frontmatter_scalar(text: str, key: str) -> tuple[str, bool]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text, False
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return text, False
        match = re.match(rf"^({re.escape(key)}):(.*?)(\r?\n)?$", line)
        if not match:
            continue
        newline = match.group(3) or ("\n" if line.endswith("\n") else "")
        lines[index] = f'{key}: ""{newline}'
        return "".join(lines), True
    return text, False


def _relationship_tmp_path(plan: RelationshipUpdatePlan | None) -> Path | None:
    if plan is None or plan.current_text == plan.updated_text:
        return None
    return plan.target_path.with_name(f".{plan.target_path.name}.roadmap-relationship.tmp")


def _relationship_backup_path(plan: RelationshipUpdatePlan | None) -> Path | None:
    if plan is None or plan.current_text == plan.updated_text:
        return None
    return plan.target_path.with_name(f".{plan.target_path.name}.roadmap-relationship.backup")


def _plan_has_changes(plan: RoadmapPlan) -> bool:
    return plan.current_text != plan.updated_text or (
        plan.relationship_plan is not None and plan.relationship_plan.current_text != plan.relationship_plan.updated_text
    )


def _boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "roadmap-boundary",
            "roadmap writes only project/roadmap.md in eligible live operating roots; it does not repair, archive, stage, commit, or mutate product-source fixtures",
        ),
        Finding(
            "info",
            "roadmap-authority",
            "roadmap output is sequencing evidence only; it cannot approve repair, closeout, archive, commit, rollback, lifecycle decisions, or future mutations",
        ),
    ]


def _root_posture_finding(inventory: Inventory) -> Finding:
    return Finding("info", "roadmap-root-posture", f"root kind: {inventory.root_kind}")


def _scalar_request_fields(request: RoadmapRequest) -> dict[str, str]:
    return {
        "status": request.status,
        "execution_slice": request.execution_slice,
        "slice_goal": request.slice_goal,
        "slice_closeout_boundary": request.slice_closeout_boundary,
        "source_incubation": request.source_incubation,
        "source_research": request.source_research,
        "related_plan": request.related_plan,
        "archived_plan": request.archived_plan,
        "verification_summary": request.verification_summary,
        "docs_decision": request.docs_decision,
        "carry_forward": request.carry_forward,
    }


def _list_request_fields(request: RoadmapRequest) -> dict[str, tuple[str, ...]]:
    fields: dict[str, tuple[str, ...]] = {}
    fields.update(_item_id_list_request_fields(request))
    fields.update(_path_list_request_fields(request))
    fields.update(_artifact_list_request_fields(request))
    return fields


def _item_id_list_request_fields(request: RoadmapRequest) -> dict[str, tuple[str, ...]]:
    return {
        "dependencies": request.dependencies,
        "slice_members": request.slice_members,
        "slice_dependencies": request.slice_dependencies,
        "supersedes": request.supersedes,
        "superseded_by": request.superseded_by,
    }


def _path_list_request_fields(request: RoadmapRequest) -> dict[str, tuple[str, ...]]:
    return {
        "related_specs": request.related_specs,
    }


def _artifact_list_request_fields(request: RoadmapRequest) -> dict[str, tuple[str, ...]]:
    return {
        "target_artifacts": request.target_artifacts,
    }


def _field_scalar(fields: dict[str, object], key: str) -> str:
    value = fields.get(key)
    if value in (None, "", [], ()):
        return ""
    if isinstance(value, (list, tuple)):
        for item in value:
            text = str(item).strip()
            if text:
                return text
        return ""
    return str(value).strip()


def _field_list(fields: dict[str, object], key: str) -> tuple[str, ...]:
    value = fields.get(key)
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        parsed = _parse_list_value(value) if value.startswith("[") and value.endswith("]") else [value]
        return tuple(str(item).strip() for item in parsed if str(item).strip())
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return (str(value).strip(),)


def _values_from_items(items: list[RoadmapItem], key: str) -> list[str]:
    values: list[str] = []
    for item in items:
        values.extend(_field_list(item.fields, key))
    return values


def _first_value_from_items(items: list[RoadmapItem], key: str) -> str:
    for item in items:
        value = _field_scalar(item.fields, key)
        if value:
            return value
    return ""


def _shared_values(items: list[RoadmapItem], key: str) -> tuple[str, ...]:
    if len(items) < 2:
        return ()
    value_sets = [set(_field_list(item.fields, key)) for item in items]
    if not value_sets:
        return ()
    shared = set.intersection(*value_sets)
    return tuple(value for value in _dedupe_nonempty(_values_from_items(items, key)) if value in shared)


def _in_slice_dependencies(items: list[tuple[str, RoadmapItem]], covered: set[str]) -> list[str]:
    edges: list[str] = []
    for roadmap_item_id, item in items:
        for dependency in _field_list(item.fields, "dependencies"):
            if dependency in covered:
                edges.append(f"{roadmap_item_id} -> {dependency}")
    return _dedupe_nonempty(edges)


def _external_dependencies(items: list[tuple[str, RoadmapItem]], covered: set[str]) -> list[str]:
    dependencies: list[str] = []
    for _roadmap_item_id, item in items:
        for dependency in _field_list(item.fields, "dependencies"):
            if dependency not in covered:
                dependencies.append(dependency)
    return _dedupe_nonempty(dependencies)


def _domain_context_for_item(item_id: str, item: RoadmapItem) -> str:
    return _field_scalar(item.fields, "slice_goal") or _normalized_item_id(item.fields.get("execution_slice")) or item.title or item_id


def _summarize_values(values: tuple[str, ...] | list[str], limit: int = 3) -> str:
    compact = [str(value) for value in values if str(value)]
    if len(compact) <= limit:
        return ", ".join(compact)
    return ", ".join(compact[:limit]) + f", +{len(compact) - limit} more"


def _plural(label: str, count: int) -> str:
    return label if count == 1 else f"{label}s"


def _recommended_phase_count(
    *,
    covered_count: int,
    target_count: int,
    related_spec_count: int,
    verification_summary_count: int,
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
    if pressure <= 1:
        return 1
    if pressure <= 2:
        return 2
    return 3


def _dedupe_nonempty(values) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _empty_field_value(field: str) -> object:
    if field in LIST_FIELDS:
        return []
    if field == "order":
        return 0
    return ""


def _normalized_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).rstrip(".")


def _normalized_status(value: object) -> str:
    return str(value or "").strip().casefold().replace("_", "-")


def _normalized_scalar(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _normalized_item_id(value: object) -> str:
    return str(value or "").strip().casefold().replace("_", "-")


def _normalize_rel(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/")


def _frontmatter_list_values(value: object) -> tuple[str, ...]:
    if value in (None, "", [], ()):
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if str(item).strip())
    return (str(value),)


def _strip_quotes(value: str) -> str:
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def _rel_has_absolute_or_parent_parts(rel_path: str) -> bool:
    if not rel_path or rel_path.startswith("/") or re.match(r"^[A-Za-z]:", rel_path):
        return True
    parts = [part for part in rel_path.split("/") if part]
    return any(part in {".", ".."} for part in parts)


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


def _with_severity(findings: list[Finding], severity: str) -> list[Finding]:
    return [Finding(severity, finding.code, finding.message, finding.source, finding.line) for finding in findings]
