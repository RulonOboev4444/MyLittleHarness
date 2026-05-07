from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from hashlib import sha256

from .atomic_files import AtomicFileWrite, FileTransactionError, apply_file_transaction
from .incubate import INCUBATION_DIR_REL, incubate_apply_findings, incubate_dry_run_findings, make_incubate_request
from .inventory import Inventory, load_inventory
from .models import Finding
from .reporting import RouteWriteEvidence, route_write_findings
from .roadmap import make_roadmap_request, roadmap_apply_findings, roadmap_item_fields, roadmap_plan_for_request


ROADMAP_STATUS = "accepted"
DEFAULT_DOCS_DECISION = "uncertain"
DEFAULT_ORDER = 900
RELEASE_BOUNDARY = "no automatic release removal, lifecycle movement, closeout, archive, staging, commit, or next-plan opening"
CENTRAL_META_FEEDBACK_PROJECT = "MyLittleHarness-dev"
META_FEEDBACK_ROOT_ENV_VAR = "MYLITTLEHARNESS_META_FEEDBACK_ROOT"
TERMINAL_DUPLICATE_STATUSES = {"done", "rejected", "superseded"}
AGENT_OPERABILITY_SIGNAL_TYPES = {"agent-operability", "agent-operability-micro-friction"}
AGENT_OPERABILITY_OWNER_COMMANDS = "meta-feedback, check, writeback, and the mlh-meta-feedback skill"
AGENT_OPERABILITY_FRICTION_SCOPE = (
    "command ergonomics, route discovery, dry-run/apply wording, docs_decision pressure, and state-transfer hesitation"
)
CLUSTER_BEGIN = "<!-- BEGIN mylittleharness-meta-feedback-cluster v1 -->"
CLUSTER_END = "<!-- END mylittleharness-meta-feedback-cluster v1 -->"
UNSPECIFIED_ROUTE = "unspecified"
KNOWN_OWNER_COMMANDS = (
    "check",
    "incubate",
    "memory-hygiene",
    "meta-feedback",
    "repair",
    "roadmap",
    "transition",
    "writeback",
)
STOP_WORDS = {
    "about",
    "after",
    "again",
    "agent",
    "apply",
    "between",
    "candidate",
    "command",
    "could",
    "during",
    "feedback",
    "future",
    "manual",
    "meta",
    "needs",
    "operator",
    "report",
    "roadmap",
    "route",
    "should",
    "state",
    "through",
    "without",
    "would",
}


@dataclass(frozen=True)
class MetaFeedbackRequest:
    topic: str
    note: str
    note_source: str
    from_root: str
    signal_type: str
    severity: str
    roadmap_item: str
    order: int | None
    dedupe_to: str


@dataclass(frozen=True)
class ClusterRecord:
    canonical_id: str
    source_rel: str
    friction_signature: str
    signal_type: str
    expected_owner_command: str
    affected_routes: tuple[str, ...]
    problem_tokens: tuple[str, ...]


@dataclass(frozen=True)
class ClusterObservation:
    canonical_id: str
    source_rel: str
    friction_signature: str
    latest_observation_hash: str
    signal_type: str
    expected_owner_command: str
    affected_routes: tuple[str, ...]
    problem_tokens: tuple[str, ...]
    representative_example: str
    observed_roots: tuple[str, ...]
    duplicate_topics: tuple[str, ...]
    occurrence_count: int
    recurrence_score: int
    first_seen: str
    exact_matches: tuple[ClusterRecord, ...]
    candidate_matches: tuple[ClusterRecord, ...]
    matched_by: str


def make_meta_feedback_request(
    topic: str | None,
    note: str | None,
    note_source: str = "--note",
    from_root: str | None = None,
    signal_type: str | None = None,
    severity: str | None = None,
    roadmap_item: str | None = None,
    order: int | None = None,
    dedupe_to: str | None = None,
) -> MetaFeedbackRequest:
    normalized_topic = _normalized_text(topic)
    item_id = _normalized_item_id(roadmap_item) or _safe_slug(normalized_topic)
    return MetaFeedbackRequest(
        topic=normalized_topic,
        note=str(note or "").strip(),
        note_source=note_source,
        from_root=_normalized_pathish(from_root),
        signal_type=_normalized_text(signal_type) or "meta-feedback",
        severity=_normalized_text(severity) or "medium",
        roadmap_item=item_id,
        order=order,
        dedupe_to=_normalized_item_id(dedupe_to),
    )


def meta_feedback_dry_run_findings(inventory: Inventory, request: MetaFeedbackRequest) -> list[Finding]:
    findings = [
        Finding("info", "meta-feedback-dry-run", "meta-feedback proposal only; no files were written"),
        _destination_root_finding(inventory),
        _root_posture_finding(inventory),
        _source_root_finding(request),
    ]
    errors = _request_errors(inventory, request)
    if errors:
        findings.extend(_with_severity(errors, "warn"))
        findings.append(
            Finding(
                "info",
                "meta-feedback-validation-posture",
                "dry-run refused before apply; fix refusal reasons, then rerun dry-run before collecting meta-feedback",
            )
        )
        return findings

    observation = _cluster_observation(inventory, request)
    source_rel = observation.source_rel
    incubate_request = make_incubate_request(_canonical_topic(request, observation), _note_body(request, observation), request.note_source, fix_candidate=True)
    findings.extend(incubate_dry_run_findings(inventory, incubate_request))
    findings.extend(_cluster_findings(observation, apply=False))
    findings.extend(_cluster_route_write_findings(inventory, observation, apply=False))
    roadmap_request = _roadmap_request(inventory, request, observation)
    roadmap_plan, roadmap_errors = roadmap_plan_for_request(inventory, roadmap_request, allowed_missing_paths={source_rel})
    findings.append(_dedupe_finding(inventory, observation, apply=False))
    findings.extend(_agent_operability_findings(request, apply=False))
    findings.append(Finding("info", "meta-feedback-roadmap-target", f"would place roadmap item: {observation.canonical_id}", "project/roadmap.md"))
    findings.append(Finding("info", "meta-feedback-roadmap-status", f"roadmap placement status: {ROADMAP_STATUS}; next-plan opening remains explicit", "project/roadmap.md"))
    findings.append(Finding("info", "meta-feedback-release-boundary", RELEASE_BOUNDARY, "project/roadmap.md"))
    if roadmap_plan:
        findings.append(Finding("info", "meta-feedback-roadmap-action", f"would {roadmap_plan.action} roadmap item {roadmap_plan.item_id!r}", "project/roadmap.md"))
        if roadmap_plan.changed_fields:
            findings.append(Finding("info", "meta-feedback-roadmap-fields", f"would change fields: {', '.join(roadmap_plan.changed_fields)}", "project/roadmap.md"))
    if roadmap_errors:
        findings.extend(_with_severity(roadmap_errors, "warn"))
    findings.extend(_boundary_findings(apply=False))
    findings.append(
        Finding(
            "info",
            "meta-feedback-validation-posture",
            "apply would write one incubation note and one accepted roadmap item/update in an eligible live operating root",
        )
    )
    return findings


def meta_feedback_apply_findings(inventory: Inventory, request: MetaFeedbackRequest) -> list[Finding]:
    errors = _request_errors(inventory, request)
    if errors:
        return errors

    observation = _cluster_observation(inventory, request)
    source_rel = observation.source_rel
    incubate_request = make_incubate_request(_canonical_topic(request, observation), _note_body(request, observation), request.note_source, fix_candidate=True)
    findings = [
        Finding("info", "meta-feedback-apply", "meta-feedback apply started"),
        _destination_root_finding(inventory),
        _root_posture_finding(inventory),
        _source_root_finding(request),
    ]
    incubate_findings = incubate_apply_findings(inventory, incubate_request)
    findings.extend(incubate_findings)
    if any(finding.severity == "error" for finding in incubate_findings):
        findings.append(Finding("info", "meta-feedback-validation-posture", "roadmap placement skipped because incubation write was refused"))
        return findings

    refreshed = load_inventory(inventory.root)
    cluster_findings = _cluster_apply_findings(refreshed, observation)
    findings.extend(_cluster_findings(observation, apply=True))
    findings.extend(cluster_findings)
    if any(finding.severity == "error" for finding in cluster_findings):
        findings.append(Finding("info", "meta-feedback-validation-posture", "roadmap placement skipped because cluster metadata write was refused"))
        return findings

    refreshed = load_inventory(inventory.root)
    roadmap_request = _roadmap_request(refreshed, request, observation)
    roadmap_findings = roadmap_apply_findings(refreshed, roadmap_request)
    findings.append(_dedupe_finding(refreshed, observation, apply=True))
    findings.extend(_agent_operability_findings(request, apply=True))
    findings.append(Finding("info", "meta-feedback-roadmap-status", f"roadmap placement status: {ROADMAP_STATUS}; next-plan opening remains explicit", "project/roadmap.md"))
    findings.append(Finding("info", "meta-feedback-release-boundary", RELEASE_BOUNDARY, "project/roadmap.md"))
    findings.extend(roadmap_findings)
    findings.extend(_boundary_findings(apply=True))
    findings.append(
        Finding(
            "info",
            "meta-feedback-validation-posture",
            "run check after apply; collected meta-feedback is operating memory and accepted roadmap sequencing, not lifecycle approval",
        )
    )
    return findings


def is_central_meta_feedback_inventory(inventory: Inventory) -> bool:
    data = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    return inventory.root_kind == "live_operating_root" and data.get("project") == CENTRAL_META_FEEDBACK_PROJECT


def _request_errors(inventory: Inventory, request: MetaFeedbackRequest) -> list[Finding]:
    errors: list[Finding] = []
    if not is_central_meta_feedback_inventory(inventory):
        errors.append(
            Finding(
                "error",
                "meta-feedback-central-root-refused",
                (
                    f"destination must be the central {CENTRAL_META_FEEDBACK_PROJECT} live operating root; "
                    f"use --to-root <{CENTRAL_META_FEEDBACK_PROJECT}> or {META_FEEDBACK_ROOT_ENV_VAR}; "
                    "the observed source root is provenance only and must not receive canonical MLH product debt"
                ),
            )
        )
    if inventory.root_kind == "product_source_fixture":
        errors.append(Finding("error", "meta-feedback-refused", "target is a product-source compatibility fixture; meta-feedback apply is refused"))
    elif inventory.root_kind == "fallback_or_archive":
        errors.append(Finding("error", "meta-feedback-refused", "target is fallback/archive or generated-output evidence; meta-feedback apply is refused"))
    elif inventory.root_kind != "live_operating_root":
        errors.append(Finding("error", "meta-feedback-refused", f"target root kind is {inventory.root_kind}; meta-feedback requires a live operating root"))
    if not request.topic:
        errors.append(Finding("error", "meta-feedback-refused", "--topic is required and cannot be empty"))
    if not request.note:
        errors.append(Finding("error", "meta-feedback-refused", "--note is required and cannot be empty"))
    if not request.from_root:
        errors.append(Finding("error", "meta-feedback-refused", "--from-root is required and cannot be empty"))
    elif _rel_has_parent_parts(request.from_root):
        errors.append(Finding("error", "meta-feedback-refused", "--from-root must not contain parent path segments"))
    if not request.roadmap_item or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", request.roadmap_item):
        errors.append(Finding("error", "meta-feedback-refused", "--roadmap-item/topic must produce a lowercase ASCII id using letters, numbers, and hyphens"))
    if request.dedupe_to:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", request.dedupe_to):
            errors.append(Finding("error", "meta-feedback-refused", "--dedupe-to must be a lowercase ASCII id using letters, numbers, and hyphens"))
        elif not _canonical_target_exists(inventory, request.dedupe_to):
            errors.append(
                Finding(
                    "error",
                    "meta-feedback-refused",
                    "--dedupe-to must name an existing canonical incubation note or roadmap item",
                    f"{INCUBATION_DIR_REL}/{request.dedupe_to}.md",
                )
            )
    if request.order is not None and request.order < 0:
        errors.append(Finding("error", "meta-feedback-refused", "--order must be a non-negative integer"))
    return errors


def _roadmap_request(inventory: Inventory, request: MetaFeedbackRequest, observation: ClusterObservation):
    existing = roadmap_item_fields(inventory, observation.canonical_id)
    action = "update" if existing else "add"
    existing_status = str(existing.get("status") or "").strip().casefold().replace("_", "-") if existing else ""
    status = existing_status if existing_status in TERMINAL_DUPLICATE_STATUSES else ROADMAP_STATUS
    return make_roadmap_request(
        action=action,
        item_id=observation.canonical_id,
        title=_title_from_topic(observation.canonical_id),
        status=status,
        order=request.order if request.order is not None else (_next_roadmap_order(inventory, status=ROADMAP_STATUS) if not existing else None),
        execution_slice=observation.canonical_id,
        slice_goal=_roadmap_goal(observation),
        slice_closeout_boundary=f"accepted sequencing only; {RELEASE_BOUNDARY}",
        source_incubation=observation.source_rel,
        verification_summary=(
            "Future implementation should prove meta-feedback collection preserves provenance, dedupes safely, "
            "clusters recurring pain transparently, and cannot approve lifecycle, release removal, staging, commit, or next-plan opening"
        ),
        docs_decision=DEFAULT_DOCS_DECISION,
        carry_forward=(
            f"Meta-feedback candidate observed from {request.from_root}; signal_type={request.signal_type}; "
            f"severity={request.severity}; canonical_id={observation.canonical_id}; "
            f"occurrence_count={observation.occurrence_count}; recurrence_score={observation.recurrence_score}; "
            f"friction_signature={observation.friction_signature}; {RELEASE_BOUNDARY}."
        ),
        slice_members=[observation.canonical_id],
    )


def _note_body(request: MetaFeedbackRequest, observation: ClusterObservation) -> str:
    agent_operability_fields = ""
    if _is_agent_operability_signal(request):
        agent_operability_fields = (
            f"- agent_friction: {AGENT_OPERABILITY_FRICTION_SCOPE} are valid capture subjects\n"
        )
    return (
        f"{request.note}\n\n"
        "Meta-feedback intake fields:\n"
        f"- signal_type: {request.signal_type}\n"
        f"- severity: {request.severity}\n"
        f"- observed_root: {request.from_root}\n"
        f"- dedupe_key: {observation.canonical_id}\n"
        f"- canonical_id: {observation.canonical_id}\n"
        f"- duplicate_topic: {request.topic}\n"
        f"- friction_signature: {observation.friction_signature}\n"
        f"- occurrence_count: {observation.occurrence_count}\n"
        f"- recurrence_score: {observation.recurrence_score}\n"
        f"- affected_routes: {_json_list(observation.affected_routes)}\n"
        f"- latest_observation_hash: {observation.latest_observation_hash}\n"
        f"- expected_owner_command: {_expected_owner_command(request)}\n"
        f"{agent_operability_fields}"
        "- authority_boundary: operating-memory capture and accepted roadmap placement only; "
        f"{RELEASE_BOUNDARY}.\n"
    )


def _source_incubation_rel(canonical_id: str) -> str:
    return f"{INCUBATION_DIR_REL}/{canonical_id}.md"


def _next_roadmap_order(inventory: Inventory, *, status: str) -> int:
    path = inventory.root / "project/roadmap.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_ORDER
    orders = [
        order
        for item_status, order in _roadmap_status_order_rows(text)
        if item_status == status
    ]
    return (max(orders) + 1) if orders else DEFAULT_ORDER


def _root_posture_finding(inventory: Inventory) -> Finding:
    return Finding("info", "meta-feedback-root-posture", f"destination root kind: {inventory.root_kind}")


def _destination_root_finding(inventory: Inventory) -> Finding:
    return Finding("info", "meta-feedback-destination-root", f"destination root: {inventory.root}")


def _source_root_finding(request: MetaFeedbackRequest) -> Finding:
    return Finding("info", "meta-feedback-source-root", f"observed source root: {request.from_root}")


def _boundary_findings(*, apply: bool) -> list[Finding]:
    verb = "writes" if apply else "would write"
    return [
        Finding(
            "info",
            "meta-feedback-boundary",
            f"meta-feedback {verb} only the destination root's project/plan-incubation/<safe-topic>.md and accepted project/roadmap.md item/update in eligible live operating roots",
        ),
        Finding(
            "info",
            "meta-feedback-authority",
            "meta-feedback output cannot approve repair, closeout, archive, lifecycle movement, next-plan opening, release removal, staging, commit, or push",
        ),
    ]


def _agent_operability_findings(request: MetaFeedbackRequest, *, apply: bool) -> list[Finding]:
    if not _is_agent_operability_signal(request):
        return []
    prefix = "" if apply else "would "
    return [
        Finding(
            "info",
            "meta-feedback-agent-operability-signal",
            (
                f"{prefix}treat agent-operability micro-friction as a first-class MLH feedback signal; "
                f"owner commands: {AGENT_OPERABILITY_OWNER_COMMANDS}"
            ),
        ),
        Finding(
            "info",
            "meta-feedback-agent-operability-boundary",
            (
                f"{prefix}capture {AGENT_OPERABILITY_FRICTION_SCOPE} as operating memory only; "
                f"{RELEASE_BOUNDARY}"
            ),
        ),
    ]


def _dedupe_finding(inventory: Inventory, observation: ClusterObservation, *, apply: bool) -> Finding:
    existing = roadmap_item_fields(inventory, observation.canonical_id)
    prefix = "" if apply else "would "
    if existing:
        status = str(existing.get("status") or "<unset>")
        if status.strip().casefold().replace("_", "-") in TERMINAL_DUPLICATE_STATUSES:
            return Finding(
                "info",
                "meta-feedback-dedupe",
                f"{prefix}reuse existing terminal roadmap item {observation.canonical_id!r} with status {status!r}; duplicate item creation is skipped",
                "project/roadmap.md",
            )
        return Finding(
            "info",
            "meta-feedback-dedupe",
            f"{prefix}update existing roadmap item {observation.canonical_id!r}; duplicate item creation is skipped",
            "project/roadmap.md",
        )
    return Finding("info", "meta-feedback-dedupe", f"{prefix}create new roadmap item {observation.canonical_id!r}; no exact duplicate id was found", "project/roadmap.md")


def _cluster_observation(inventory: Inventory, request: MetaFeedbackRequest) -> ClusterObservation:
    signal_type = request.signal_type.casefold().replace("_", "-")
    expected_owner_command = _expected_owner_command(request)
    affected_routes = _affected_routes(request)
    problem_tokens = _problem_tokens(request.note)
    friction_signature = _friction_signature(inventory, signal_type, expected_owner_command, affected_routes, problem_tokens)
    latest_hash = sha256(_normalized_observation_text(request).encode("utf-8")).hexdigest()[:16]
    records = _cluster_records(inventory)
    exact_matches = tuple(record for record in records if record.friction_signature == friction_signature)
    candidate_matches = tuple(
        record
        for record in records
        if record.friction_signature != friction_signature and _cluster_record_looks_related(record, signal_type, expected_owner_command, affected_routes, problem_tokens)
    )
    if request.dedupe_to:
        canonical_id = request.dedupe_to
        matched_by = "explicit --dedupe-to"
    elif exact_matches:
        canonical_id = exact_matches[0].canonical_id
        matched_by = "exact friction_signature"
    else:
        canonical_id = request.roadmap_item
        matched_by = "new canonical candidate"
    source_rel = _source_incubation_rel(canonical_id)
    metadata = _existing_cluster_metadata(inventory.root / source_rel)
    today = date.today().isoformat()
    occurrence_count = _existing_occurrence_count(metadata, inventory.root / source_rel) + 1
    observed_roots = tuple(_dedupe_nonempty((*_metadata_list(metadata, "observed_roots"), request.from_root)))
    duplicate_topics = tuple(_dedupe_nonempty((*_metadata_list(metadata, "duplicate_topics"), request.topic)))
    first_seen = _metadata_scalar(metadata, "first_seen") or today
    recurrence_score = _recurrence_score(
        occurrence_count=occurrence_count,
        severity=request.severity,
        observed_roots=observed_roots,
        affected_routes=affected_routes,
        agent_operability=_is_agent_operability_signal(request),
    )
    return ClusterObservation(
        canonical_id=canonical_id,
        source_rel=source_rel,
        friction_signature=friction_signature,
        latest_observation_hash=latest_hash,
        signal_type=signal_type,
        expected_owner_command=expected_owner_command,
        affected_routes=affected_routes,
        problem_tokens=problem_tokens,
        representative_example=_single_line_goal(request.topic, request.note),
        observed_roots=observed_roots,
        duplicate_topics=duplicate_topics,
        occurrence_count=occurrence_count,
        recurrence_score=recurrence_score,
        first_seen=first_seen,
        exact_matches=exact_matches,
        candidate_matches=candidate_matches,
        matched_by=matched_by,
    )


def _cluster_findings(observation: ClusterObservation, *, apply: bool) -> list[Finding]:
    prefix = "" if apply else "would "
    findings = [
        Finding(
            "info",
            "meta-feedback-cluster-signature",
            (
                f"{prefix}record friction_signature={observation.friction_signature}; "
                f"canonical_id={observation.canonical_id}; affected_routes={_json_list(observation.affected_routes)}"
            ),
            observation.source_rel,
        ),
        Finding(
            "info",
            "meta-feedback-cluster-table",
            (
                f"{prefix}cluster action: matched_by={observation.matched_by}; "
                f"occurrence_count={observation.occurrence_count}; recurrence_score={observation.recurrence_score}; "
                f"source={observation.source_rel}"
            ),
            observation.source_rel,
        ),
    ]
    if observation.exact_matches:
        findings.append(
            Finding(
                "info",
                "meta-feedback-cluster-exact-match",
                f"{prefix}append to canonical cluster(s) from exact signature: {_record_ids(observation.exact_matches)}",
                observation.source_rel,
            )
        )
    if observation.matched_by == "explicit --dedupe-to":
        findings.append(
            Finding(
                "info",
                "meta-feedback-cluster-explicit-dedupe",
                f"{prefix}append observation to requested canonical cluster {observation.canonical_id!r}",
                observation.source_rel,
            )
        )
    if observation.candidate_matches:
        findings.append(
            Finding(
                "info",
                "meta-feedback-cluster-candidate-match",
                (
                    f"{prefix}report related cluster candidate(s): {_record_ids(observation.candidate_matches)}; "
                    "use --dedupe-to <canonical_id> to intentionally append near-duplicates to an existing canonical note"
                ),
                observation.source_rel,
            )
        )
    findings.append(
        Finding(
            "info",
            "meta-feedback-cluster-boundary",
            f"{prefix}update only canonical incubation cluster metadata plus the bounded roadmap item/update; {RELEASE_BOUNDARY}",
            observation.source_rel,
        )
    )
    return findings


def _cluster_apply_findings(inventory: Inventory, observation: ClusterObservation) -> list[Finding]:
    path = inventory.root / observation.source_rel
    if not path.is_file() or path.is_symlink():
        return [Finding("error", "meta-feedback-cluster-refused", "canonical incubation note is missing or unsafe after incubation apply", observation.source_rel)]
    try:
        current_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [Finding("error", "meta-feedback-cluster-refused", f"canonical incubation note could not be read: {exc}", observation.source_rel)]
    updated_text = _text_with_cluster_metadata(current_text, observation)
    write_findings = _cluster_route_write_findings_from_text(observation.source_rel, current_text, updated_text, apply=True)
    if current_text == updated_text:
        return [
            Finding("info", "meta-feedback-cluster-noop", "canonical cluster metadata already matches the observation", observation.source_rel),
            *write_findings,
        ]
    tmp_path = path.with_name(f".{path.name}.meta-feedback-cluster.tmp")
    backup_path = path.with_name(f".{path.name}.meta-feedback-cluster.backup")
    if tmp_path.exists() or backup_path.exists():
        return [Finding("error", "meta-feedback-cluster-refused", "temporary cluster write or backup path already exists", observation.source_rel)]
    try:
        cleanup_warnings = apply_file_transaction((AtomicFileWrite(path, tmp_path, updated_text, backup_path),))
    except FileTransactionError as exc:
        return [Finding("error", "meta-feedback-cluster-refused", f"cluster metadata write failed before all writes completed: {exc}", observation.source_rel)]
    findings = [
        Finding("info", "meta-feedback-cluster-written", "updated canonical meta-feedback cluster metadata", observation.source_rel),
        *write_findings,
    ]
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "meta-feedback-cluster-backup-cleanup", warning, observation.source_rel))
    return findings


def _cluster_route_write_findings(inventory: Inventory, observation: ClusterObservation, *, apply: bool) -> list[Finding]:
    path = inventory.root / observation.source_rel
    try:
        current_text = path.read_text(encoding="utf-8")
    except OSError:
        current_text = ""
    updated_text = _text_with_cluster_metadata(current_text or _new_cluster_placeholder_text(observation), observation)
    return _cluster_route_write_findings_from_text(observation.source_rel, current_text, updated_text, apply=apply)


def _cluster_route_write_findings_from_text(source_rel: str, current_text: str, updated_text: str, *, apply: bool) -> list[Finding]:
    return route_write_findings("meta-feedback-cluster-route-write", (RouteWriteEvidence(source_rel, current_text, updated_text),), apply=apply)


def _text_with_cluster_metadata(text: str, observation: ClusterObservation) -> str:
    block = _cluster_section(observation)
    if CLUSTER_BEGIN in text and CLUSTER_END in text:
        start = text.index(CLUSTER_BEGIN)
        end = text.index(CLUSTER_END, start) + len(CLUSTER_END)
        return text[:start] + _cluster_block(observation) + text[end:]
    marker = "\n## Entries\n"
    if marker in text:
        return text.replace(marker, "\n" + block + marker, 1)
    return text.rstrip() + "\n\n" + block


def _cluster_section(observation: ClusterObservation) -> str:
    return "## Meta-feedback Cluster\n\n" + _cluster_block(observation) + "\n\n"


def _cluster_block(observation: ClusterObservation) -> str:
    today = date.today().isoformat()
    return (
        f"{CLUSTER_BEGIN}\n"
        f"- `canonical_id`: `{_safe_backtick_value(observation.canonical_id)}`\n"
        f"- `friction_signature`: `{observation.friction_signature}`\n"
        f"- `signal_type`: `{_safe_backtick_value(observation.signal_type)}`\n"
        f"- `expected_owner_command`: `{_safe_backtick_value(observation.expected_owner_command)}`\n"
        f"- `occurrence_count`: `{observation.occurrence_count}`\n"
        f"- `first_seen`: `{observation.first_seen}`\n"
        f"- `last_seen`: `{today}`\n"
        f"- `observed_roots`: `{_json_list(observation.observed_roots)}`\n"
        f"- `affected_routes`: `{_json_list(observation.affected_routes)}`\n"
        f"- `duplicate_topics`: `{_json_list(observation.duplicate_topics)}`\n"
        f"- `recurrence_score`: `{observation.recurrence_score}`\n"
        f"- `representative_examples`: `{_json_list((observation.representative_example,))}`\n"
        f"- `latest_observation_hash`: `{observation.latest_observation_hash}`\n"
        f"{CLUSTER_END}"
    )


def _cluster_records(inventory: Inventory) -> tuple[ClusterRecord, ...]:
    root = inventory.root / INCUBATION_DIR_REL
    if not root.is_dir():
        return ()
    records: list[ClusterRecord] = []
    for path in sorted(root.glob("*.md")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        metadata = _cluster_metadata_from_text(text)
        canonical_id = _metadata_scalar(metadata, "canonical_id") or path.stem
        signature = _metadata_scalar(metadata, "friction_signature") or _line_field(text, "friction_signature")
        if not signature:
            continue
        signal_type = _metadata_scalar(metadata, "signal_type") or _line_field(text, "signal_type")
        owner = _metadata_scalar(metadata, "expected_owner_command") or _line_field(text, "expected_owner_command")
        affected_routes = tuple(_metadata_list(metadata, "affected_routes")) or tuple(_list_line_field(text, "affected_routes")) or (UNSPECIFIED_ROUTE,)
        duplicate_topics = tuple(_metadata_list(metadata, "duplicate_topics"))
        problem_tokens = _problem_tokens(" ".join((*duplicate_topics, _representative_text(metadata), text[:1200])))
        records.append(
            ClusterRecord(
                canonical_id=_normalized_item_id(canonical_id),
                source_rel=f"{INCUBATION_DIR_REL}/{path.name}",
                friction_signature=signature,
                signal_type=signal_type.casefold().replace("_", "-"),
                expected_owner_command=owner,
                affected_routes=affected_routes,
                problem_tokens=problem_tokens,
            )
        )
    return tuple(records)


def _existing_cluster_metadata(path) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        return _cluster_metadata_from_text(path.read_text(encoding="utf-8"))
    except OSError:
        return {}


def _cluster_metadata_from_text(text: str) -> dict[str, object]:
    if CLUSTER_BEGIN not in text or CLUSTER_END not in text:
        return {}
    start = text.index(CLUSTER_BEGIN) + len(CLUSTER_BEGIN)
    end = text.index(CLUSTER_END, start)
    metadata: dict[str, object] = {}
    for line in text[start:end].splitlines():
        match = re.match(r"^\s*-\s+`([^`]+)`:\s+`(.*?)`\s*$", line)
        if not match:
            continue
        key, raw = match.group(1), match.group(2)
        if raw.startswith("[") and raw.endswith("]"):
            metadata[key] = _parse_json_list(raw)
        else:
            metadata[key] = raw
    return metadata


def _existing_occurrence_count(metadata: dict[str, object], path) -> int:
    value = _metadata_scalar(metadata, "occurrence_count")
    if value:
        try:
            return max(int(value), 0)
        except ValueError:
            return 0
    if not path.is_file() or path.is_symlink():
        return 0
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0
    return text.count("Meta-feedback intake fields:")


def _canonical_target_exists(inventory: Inventory, canonical_id: str) -> bool:
    if (inventory.root / _source_incubation_rel(canonical_id)).is_file():
        return True
    return bool(roadmap_item_fields(inventory, canonical_id))


def _canonical_topic(request: MetaFeedbackRequest, observation: ClusterObservation) -> str:
    if observation.canonical_id == request.roadmap_item and not request.dedupe_to:
        return request.topic
    return _title_from_topic(observation.canonical_id)


def _affected_routes(request: MetaFeedbackRequest) -> tuple[str, ...]:
    haystack = f"{request.topic}\n{request.note}"
    routes: list[str] = []
    for match in re.finditer(r"(?<![A-Za-z0-9_.-])((?:project|docs|src|tests|\.codex|\.agents)/[A-Za-z0-9_./-]+)", haystack):
        routes.append(match.group(1).strip("./"))
    lowered = haystack.casefold()
    for command in KNOWN_OWNER_COMMANDS:
        if re.search(rf"\b{re.escape(command)}\b", lowered):
            routes.append(command)
    deduped = tuple(_dedupe_nonempty(routes))
    return deduped or (UNSPECIFIED_ROUTE,)


def _problem_tokens(text: str) -> tuple[str, ...]:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").casefold()
    words = re.findall(r"[a-z0-9]{4,}", ascii_text)
    tokens = [word for word in words if word not in STOP_WORDS]
    return tuple(sorted(set(tokens))[:16])


def _friction_signature(
    inventory: Inventory,
    signal_type: str,
    expected_owner_command: str,
    affected_routes: tuple[str, ...],
    problem_tokens: tuple[str, ...],
) -> str:
    material = "|".join(
        (
            inventory.root_kind,
            signal_type,
            expected_owner_command,
            ",".join(sorted(affected_routes)),
            ",".join(problem_tokens[:12]),
        )
    )
    return sha256(material.encode("utf-8")).hexdigest()[:16]


def _normalized_observation_text(request: MetaFeedbackRequest) -> str:
    return "|".join((request.topic, request.note, request.from_root, request.signal_type, request.severity))


def _cluster_record_looks_related(
    record: ClusterRecord,
    signal_type: str,
    expected_owner_command: str,
    affected_routes: tuple[str, ...],
    problem_tokens: tuple[str, ...],
) -> bool:
    if record.signal_type != signal_type or record.expected_owner_command != expected_owner_command:
        return False
    route_overlap = set(record.affected_routes) & set(affected_routes) - {UNSPECIFIED_ROUTE}
    token_overlap = set(record.problem_tokens) & set(problem_tokens)
    return bool(route_overlap) or len(token_overlap) >= 2


def _recurrence_score(
    *,
    occurrence_count: int,
    severity: str,
    observed_roots: tuple[str, ...],
    affected_routes: tuple[str, ...],
    agent_operability: bool,
) -> int:
    severity_score = {"low": 1, "medium": 2, "high": 3, "critical": 4}.get(severity.casefold(), 2)
    route_count = len([route for route in affected_routes if route != UNSPECIFIED_ROUTE])
    score = occurrence_count * 2 + severity_score + min(len(observed_roots), 3) + min(route_count, 3)
    if agent_operability:
        score += 2
    return score


def _roadmap_status_order_rows(text: str) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []
    for block in re.split(r"(?m)^###\s+", text):
        status_match = re.search(r"- `status`:\s*`([^`]+)`", block)
        order_match = re.search(r"- `order`:\s*`([0-9]+)`", block)
        if not status_match or not order_match:
            continue
        rows.append((status_match.group(1).strip().casefold().replace("_", "-"), int(order_match.group(1))))
    return rows


def _new_cluster_placeholder_text(observation: ClusterObservation) -> str:
    return f"# {_title_from_topic(observation.canonical_id)}\n\n## Entries\n"


def _metadata_scalar(metadata: dict[str, object], key: str) -> str:
    value = metadata.get(key)
    if value in (None, "", [], ()):
        return ""
    if isinstance(value, (list, tuple)):
        return str(value[0]) if value else ""
    return str(value).strip()


def _metadata_list(metadata: dict[str, object], key: str) -> tuple[str, ...]:
    value = metadata.get(key)
    if value in (None, "", [], ()):
        return ()
    if isinstance(value, str):
        return tuple(_parse_json_list(value) if value.startswith("[") else [value])
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if str(item).strip())
    return (str(value),)


def _line_field(text: str, key: str) -> str:
    match = re.search(rf"(?m)^\s*-\s*{re.escape(key)}:\s*(.+?)\s*$", text)
    return match.group(1).strip() if match else ""


def _list_line_field(text: str, key: str) -> tuple[str, ...]:
    raw = _line_field(text, key)
    if not raw:
        return ()
    if raw.startswith("[") and raw.endswith("]"):
        return tuple(_parse_json_list(raw))
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _parse_json_list(raw: str) -> list[str]:
    try:
        parsed = json.loads(raw)
    except ValueError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _representative_text(metadata: dict[str, object]) -> str:
    values = _metadata_list(metadata, "representative_examples")
    return " ".join(values)


def _record_ids(records: tuple[ClusterRecord, ...]) -> str:
    return ", ".join(_dedupe_nonempty(record.canonical_id for record in records))


def _json_list(values: tuple[str, ...] | list[str]) -> str:
    return json.dumps(list(values), ensure_ascii=True)


def _safe_backtick_value(value: str) -> str:
    return str(value).replace("`", "'")


def _title_from_topic(topic: str) -> str:
    words = re.split(r"[\s_-]+", topic.strip())
    return " ".join(word[:1].upper() + word[1:] for word in words if word) or "Meta Feedback Candidate"


def _single_line_goal(topic: str, note: str) -> str:
    paragraph: list[str] = []
    for raw_line in note.splitlines():
        line = raw_line.strip()
        if not line:
            if paragraph:
                break
            continue
        paragraph.append(line)
    goal = " ".join(paragraph) or topic
    return _roadmap_scalar_text(goal).rstrip(".")


def _roadmap_goal(observation: ClusterObservation) -> str:
    goal = observation.representative_example
    lower_goal = goal.casefold()
    hints: list[str] = []
    if observation.affected_routes and "affected_route" not in lower_goal:
        hints.append(f"affected_routes: {_json_list(observation.affected_routes)}")
    if observation.expected_owner_command and "expected_owner_command" not in lower_goal:
        hints.append(f"expected_owner_command: {observation.expected_owner_command}")
    if hints:
        goal = f"{goal}. {'; '.join(hints)}"
    return _roadmap_scalar_text(goal).rstrip(".")


def _roadmap_scalar_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("`", "'").strip())


def _normalized_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).rstrip(".")


def _normalized_pathish(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/")


def _normalized_item_id(value: object) -> str:
    return str(value or "").strip().casefold().replace("_", "-")


def _is_agent_operability_signal(request: MetaFeedbackRequest) -> bool:
    return request.signal_type.casefold().replace("_", "-") in AGENT_OPERABILITY_SIGNAL_TYPES


def _expected_owner_command(request: MetaFeedbackRequest) -> str:
    if _is_agent_operability_signal(request):
        return AGENT_OPERABILITY_OWNER_COMMANDS
    return "meta-feedback"


def _safe_slug(topic: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", topic).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


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


def _rel_has_parent_parts(value: str) -> bool:
    parts = [part for part in value.replace("\\", "/").split("/") if part]
    return any(part == ".." for part in parts)


def _with_severity(findings: list[Finding], severity: str) -> list[Finding]:
    return [Finding(severity, finding.code, finding.message, finding.source, finding.line) for finding in findings]
