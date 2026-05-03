from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .atomic_files import AtomicFileDelete, AtomicFileWrite, FileTransactionError, apply_file_transaction
from .inventory import Inventory
from .models import Finding
from .parsing import parse_frontmatter


RESEARCH_DIR_REL = "project/research"
INCUBATION_DIR_REL = "project/plan-incubation"
ARCHIVE_RESEARCH_DIR_REL = "project/archive/reference/research"
ARCHIVE_INCUBATION_DIR_REL = "project/archive/reference/incubation"
ROADMAP_REL = "project/roadmap.md"
ALLOWED_STATUS_VALUES = {"archived", "distilled", "implemented", "rejected"}
RELATIONSHIP_STATUS_FIELDS = {
    "archived_plan",
    "archived_to",
    "docs_decision",
    "implemented_by",
    "promoted_to",
    "related_plan",
    "related_roadmap",
    "related_roadmap_item",
    "verification_summary",
}
OPEN_THREAD_FRONTMATTER_FIELDS = {
    "contains",
    "open_questions",
    "open_threads",
    "remaining_threads",
    "todo",
    "todos",
}
OPEN_THREAD_HEADING_MARKERS = (
    "open question",
    "open questions",
    "future",
    "follow-up",
    "follow up",
    "followups",
    "remainder",
    "remaining",
    "deferred",
    "todo",
)
ENTRY_COVERAGE_HEADING = "entry coverage"
ENTRY_COVERAGE_TERMINAL_STATUSES = {"implemented", "rejected", "superseded", "merged", "split", "archived"}
ENTRY_COVERAGE_OPEN_STATUSES = {"accepted", "active", "blocked", "deferred", "incubating", "open", "pending", "todo"}


@dataclass(frozen=True)
class IncubationEntry:
    entry_id: str
    heading: str
    line: int


@dataclass(frozen=True)
class EntryCoverage:
    entry_id: str
    status: str
    detail: str
    line: int


@dataclass(frozen=True)
class EntryCoverageReport:
    entries: tuple[IncubationEntry, ...]
    coverage: tuple[EntryCoverage, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True)
class MemoryHygieneRequest:
    source: str
    promoted_to: str
    status: str
    archive_to: str
    repair_links: bool = False
    scan: bool = False
    archive_covered: bool = False
    entry_coverage: tuple[str, ...] = ()


@dataclass(frozen=True)
class MemoryHygienePlan:
    source_rel: str
    source_path: Path
    promoted_to_rel: str
    promoted_to_path: Path | None
    status: str
    archive_rel: str
    archive_path: Path | None
    updated_source_text: str
    link_repairs: tuple[tuple[str, Path, str], ...]
    entry_coverage_updates: tuple[EntryCoverage, ...] = ()
    archive_covered: bool = False


@dataclass(frozen=True)
class RelationshipUpdatePlan:
    source_rel: str
    source_path: Path
    target_rel: str
    target_path: Path
    current_text: str
    updated_text: str
    changed_fields: tuple[str, ...]
    archive_rel: str = ""
    archive_path: Path | None = None
    archive_blockers: tuple[str, ...] = ()
    link_repairs: tuple[tuple[str, Path, str], ...] = ()


def make_memory_hygiene_request(
    source: str | None,
    promoted_to: str | None,
    status: str | None,
    archive_to: str | None,
    repair_links: bool = False,
    scan: bool = False,
    archive_covered: bool = False,
    entry_coverage: tuple[str, ...] | list[str] = (),
) -> MemoryHygieneRequest:
    source_rel = _normalize_rel(source)
    promoted = _normalize_rel(promoted_to)
    archive = _normalize_rel(archive_to)
    if archive_covered and not archive and source_rel.startswith(f"{INCUBATION_DIR_REL}/"):
        archive = _default_incubation_archive_rel(source_rel)
    normalized_status = _normalized_status(status, promoted, archive)
    return MemoryHygieneRequest(
        source=source_rel,
        promoted_to=promoted,
        status=normalized_status,
        archive_to=archive,
        repair_links=repair_links,
        scan=scan,
        archive_covered=archive_covered,
        entry_coverage=tuple(str(item or "").strip() for item in entry_coverage if str(item or "").strip()),
    )


def memory_hygiene_dry_run_findings(inventory: Inventory, request: MemoryHygieneRequest) -> list[Finding]:
    findings = [
        Finding("info", "memory-hygiene-dry-run", "memory hygiene proposal only; no files were written"),
        _root_posture_finding(inventory),
    ]
    if request.scan:
        findings.append(
            Finding(
                "info",
                "memory-hygiene-scan",
                "relationship hygiene scan is read-only and reports stale links, missing reciprocal links, orphan notes, text-input audit posture, entry coverage, split suggestions, and safe cleanup candidates",
            )
        )
        errors = _request_errors(inventory, request)
        if errors:
            findings.extend(_with_severity(errors, "warn"))
            return findings
        findings.extend(cli_text_audit_findings())
        findings.extend(relationship_hygiene_scan_findings(inventory))
        findings.extend(_relationship_scan_boundary_findings())
        return findings

    plan, errors = _memory_hygiene_plan(inventory, request)
    if plan:
        findings.extend(_plan_findings(plan, apply=False, repair_links=request.repair_links))
    if errors:
        findings.extend(_with_severity(errors, "warn"))
        findings.append(
            Finding(
                "info",
                "memory-hygiene-validation-posture",
                "dry-run refused before apply; fix refusal reasons, then rerun dry-run before writing lifecycle hygiene changes",
            )
        )
        return findings
    assert plan is not None
    findings.extend(_boundary_findings())
    findings.append(
        Finding(
            "info",
            "memory-hygiene-validation-posture",
            "apply would write only the declared source/archive/link targets in an eligible live operating root; dry-run writes no files",
            plan.source_rel,
        )
    )
    return findings


def memory_hygiene_apply_findings(inventory: Inventory, request: MemoryHygieneRequest) -> list[Finding]:
    if request.scan:
        return [Finding("error", "memory-hygiene-refused", "--scan is read-only and can be used only with --dry-run")]

    plan, errors = _memory_hygiene_plan(inventory, request)
    if errors:
        return errors
    assert plan is not None

    operations: list[AtomicFileWrite | AtomicFileDelete] = []
    archive_rel = plan.archive_rel or plan.source_rel
    if plan.archive_path:
        archive_tmp = plan.archive_path.with_name(f".{plan.archive_path.name}.memory-hygiene.tmp")
        archive_backup = plan.archive_path.with_name(f".{plan.archive_path.name}.memory-hygiene.backup")
        source_backup = plan.source_path.with_name(f".{plan.source_path.name}.memory-hygiene.backup")
        operations.append(AtomicFileWrite(plan.archive_path, archive_tmp, plan.updated_source_text, archive_backup))
        operations.append(AtomicFileDelete(plan.source_path, source_backup))
    else:
        source_tmp = plan.source_path.with_name(f".{plan.source_path.name}.memory-hygiene.tmp")
        source_backup = plan.source_path.with_name(f".{plan.source_path.name}.memory-hygiene.backup")
        operations.append(AtomicFileWrite(plan.source_path, source_tmp, plan.updated_source_text, source_backup))

    for _, path, text in plan.link_repairs:
        link_tmp = path.with_name(f".{path.name}.memory-hygiene.tmp")
        link_backup = path.with_name(f".{path.name}.memory-hygiene.backup")
        operations.append(AtomicFileWrite(path, link_tmp, text, link_backup))

    try:
        cleanup_warnings = apply_file_transaction(operations)
    except FileTransactionError as exc:
        return [Finding("error", "memory-hygiene-refused", f"memory hygiene apply failed before all target writes completed: {exc}", plan.source_rel)]

    findings = [
        Finding("info", "memory-hygiene-apply", "memory hygiene apply started"),
        _root_posture_finding(inventory),
        Finding("info", "memory-hygiene-frontmatter-updated", "updated lifecycle frontmatter", archive_rel),
    ]
    if plan.archive_rel:
        findings.append(Finding("info", "memory-hygiene-archived", f"archived source to {plan.archive_rel}", plan.archive_rel))
    for rel_path, _, _ in plan.link_repairs:
        findings.append(Finding("info", "memory-hygiene-link-repaired", f"repaired exact source-path references in {rel_path}", rel_path))
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "memory-hygiene-backup-cleanup", warning, archive_rel))
    findings.extend(_boundary_findings())
    findings.append(
        Finding(
            "info",
            "memory-hygiene-validation-posture",
            "run check after apply to verify the live operating root remains healthy; hygiene output is not lifecycle approval",
            plan.archive_rel or plan.source_rel,
        )
    )
    return findings


def _memory_hygiene_plan(inventory: Inventory, request: MemoryHygieneRequest) -> tuple[MemoryHygienePlan | None, list[Finding]]:
    errors: list[Finding] = []
    errors.extend(_request_errors(inventory, request))

    source_path = inventory.root / request.source if request.source else inventory.root
    promoted_to_path = inventory.root / request.promoted_to if request.promoted_to else None
    archive_path = inventory.root / request.archive_to if request.archive_to else None

    errors.extend(_source_errors(inventory, request.source, source_path))
    errors.extend(_promoted_to_errors(inventory, request.promoted_to, promoted_to_path))
    errors.extend(_archive_errors(inventory, request.archive_to, archive_path))

    if errors:
        return None, errors

    try:
        source_text = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [Finding("error", "memory-hygiene-refused", f"source could not be read: {exc}", request.source)]

    coverage_updates: tuple[EntryCoverage, ...] = ()
    if request.entry_coverage:
        source_text, coverage_updates, coverage_error = _source_text_with_entry_coverage(source_text, request.entry_coverage)
        if coverage_error:
            return None, [Finding("error", "memory-hygiene-refused", coverage_error, request.source)]

    if request.archive_covered:
        blockers = incubation_archive_blockers(source_text)
        if blockers:
            return None, [
                Finding(
                    "error",
                    "memory-hygiene-refused",
                    f"--archive-covered requires terminal Entry Coverage and no archive blockers: {', '.join(blockers)}",
                    request.source,
                )
            ]

    updated_text, frontmatter_error = _source_text_with_lifecycle_frontmatter(source_text, request)
    if frontmatter_error:
        return None, [Finding("error", "memory-hygiene-refused", frontmatter_error, request.source)]

    link_repairs: tuple[tuple[str, Path, str], ...] = ()
    if request.repair_links and request.archive_to:
        link_repairs = tuple(_planned_link_repairs(inventory, request.source, request.archive_to))

    return (
        MemoryHygienePlan(
            source_rel=request.source,
            source_path=source_path,
            promoted_to_rel=request.promoted_to,
            promoted_to_path=promoted_to_path,
            status=request.status,
            archive_rel=request.archive_to,
            archive_path=archive_path,
            updated_source_text=updated_text,
            link_repairs=link_repairs,
            entry_coverage_updates=coverage_updates,
            archive_covered=request.archive_covered,
        ),
        [],
    )


def _request_errors(inventory: Inventory, request: MemoryHygieneRequest) -> list[Finding]:
    errors: list[Finding] = []
    if inventory.root_kind == "product_source_fixture":
        errors.append(Finding("error", "memory-hygiene-refused", "target is a product-source compatibility fixture; memory-hygiene --apply is refused", request.source or None))
    elif inventory.root_kind == "fallback_or_archive":
        errors.append(Finding("error", "memory-hygiene-refused", "target is fallback/archive or generated-output evidence; memory-hygiene --apply is refused", request.source or None))
    elif inventory.root_kind != "live_operating_root":
        errors.append(Finding("error", "memory-hygiene-refused", f"target root kind is {inventory.root_kind}; memory-hygiene requires a live operating root"))

    if request.scan:
        if request.source or request.promoted_to or request.archive_to or request.status or request.repair_links or request.archive_covered or request.entry_coverage:
            errors.append(Finding("error", "memory-hygiene-refused", "--scan cannot be combined with source, promotion, archive, status, link-repair, archive-covered, or entry-coverage fields"))
        return errors

    if not request.source:
        errors.append(Finding("error", "memory-hygiene-refused", "--source is required and cannot be empty"))
    if request.archive_covered and not request.source.startswith(f"{INCUBATION_DIR_REL}/"):
        errors.append(Finding("error", "memory-hygiene-refused", "--archive-covered requires an incubation source under project/plan-incubation/", request.source or None))
    if request.archive_covered and request.promoted_to:
        errors.append(Finding("error", "memory-hygiene-refused", "--archive-covered cannot be combined with --promoted-to", request.source or None))
    if not request.promoted_to and not request.archive_to:
        errors.append(Finding("error", "memory-hygiene-refused", "at least one of --promoted-to or --archive-to is required"))
    if request.status not in ALLOWED_STATUS_VALUES:
        errors.append(Finding("error", "memory-hygiene-refused", f"--status must be one of: {', '.join(sorted(ALLOWED_STATUS_VALUES))}"))
    if request.repair_links and not request.archive_to:
        errors.append(Finding("error", "memory-hygiene-refused", "--repair-links requires --archive-to"))
    return errors


def _source_errors(inventory: Inventory, source_rel: str, source_path: Path) -> list[Finding]:
    if not source_rel:
        return []
    errors: list[Finding] = []
    if _rel_has_absolute_or_parent_parts(source_rel):
        errors.append(Finding("error", "memory-hygiene-refused", "--source must be a root-relative path without parent segments", source_rel))
        return errors
    if not _source_route_allowed(source_rel):
        errors.append(Finding("error", "memory-hygiene-refused", "source must be under project/research/ or project/plan-incubation/", source_rel))
    if not source_rel.endswith(".md"):
        errors.append(Finding("error", "memory-hygiene-refused", "source must be a Markdown file", source_rel))
    if _path_escapes_root(inventory.root, source_path):
        errors.append(Finding("error", "memory-hygiene-refused", "source path escapes the target root", source_rel))
    elif not source_path.exists():
        errors.append(Finding("error", "memory-hygiene-refused", "source does not exist", source_rel))
    elif source_path.is_symlink():
        errors.append(Finding("error", "memory-hygiene-refused", "source is a symlink", source_rel))
    elif not source_path.is_file():
        errors.append(Finding("error", "memory-hygiene-refused", "source is not a regular file", source_rel))
    return errors


def _promoted_to_errors(inventory: Inventory, promoted_rel: str, promoted_path: Path | None) -> list[Finding]:
    if not promoted_rel or promoted_path is None:
        return []
    errors: list[Finding] = []
    if _rel_has_absolute_or_parent_parts(promoted_rel):
        errors.append(Finding("error", "memory-hygiene-refused", "--promoted-to must be a root-relative path without parent segments", promoted_rel))
        return errors
    if _path_escapes_root(inventory.root, promoted_path):
        errors.append(Finding("error", "memory-hygiene-refused", "promoted target path escapes the target root", promoted_rel))
    elif not promoted_path.exists():
        errors.append(Finding("error", "memory-hygiene-refused", "promoted target does not exist", promoted_rel))
    elif promoted_path.is_symlink():
        errors.append(Finding("error", "memory-hygiene-refused", "promoted target is a symlink", promoted_rel))
    elif not promoted_path.is_file():
        errors.append(Finding("error", "memory-hygiene-refused", "promoted target is not a regular file", promoted_rel))
    return errors


def _archive_errors(inventory: Inventory, archive_rel: str, archive_path: Path | None) -> list[Finding]:
    if not archive_rel or archive_path is None:
        return []
    errors: list[Finding] = []
    if _rel_has_absolute_or_parent_parts(archive_rel):
        errors.append(Finding("error", "memory-hygiene-refused", "--archive-to must be a root-relative path without parent segments", archive_rel))
        return errors
    if not _archive_route_allowed(archive_rel):
        errors.append(Finding("error", "memory-hygiene-refused", "--archive-to must be under project/archive/reference/research/ or project/archive/reference/incubation/", archive_rel))
    if not archive_rel.endswith(".md"):
        errors.append(Finding("error", "memory-hygiene-refused", "archive target must be a Markdown file", archive_rel))
    if _path_escapes_root(inventory.root, archive_path):
        errors.append(Finding("error", "memory-hygiene-refused", "archive target path escapes the target root", archive_rel))
        return errors
    for parent in _parents_between(inventory.root, archive_path.parent):
        rel = parent.relative_to(inventory.root).as_posix()
        if parent.exists() and parent.is_symlink():
            errors.append(Finding("error", "memory-hygiene-refused", f"archive target directory contains a symlink segment: {rel}", rel))
        elif parent.exists() and not parent.is_dir():
            errors.append(Finding("error", "memory-hygiene-refused", f"archive target directory contains a non-directory segment: {rel}", rel))
    if archive_path.exists():
        errors.append(Finding("error", "memory-hygiene-refused", "archive target already exists", archive_rel))
    return errors


def _source_text_with_lifecycle_frontmatter(text: str, request: MemoryHygieneRequest) -> tuple[str, str | None]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text, "source frontmatter is required for lifecycle hygiene"
    closing_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        return text, "source frontmatter is malformed"

    updates = {
        "status": request.status,
        "updated": date.today().isoformat(),
    }
    if request.promoted_to:
        updates["promoted_to"] = request.promoted_to
    if request.archive_to:
        updates["archived_to"] = request.archive_to

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
        lines[closing_index:closing_index] = [f'{key}: "{_yaml_double_quoted_value(updates[key])}"\n' for key in missing]
    return "".join(lines), None


def _source_text_with_entry_coverage(text: str, raw_records: tuple[str, ...]) -> tuple[str, tuple[EntryCoverage, ...], str | None]:
    parsed_records: list[EntryCoverage] = []
    for raw in raw_records:
        parsed = _parse_entry_coverage_line(f"- {raw.strip()}", 0)
        if parsed is None:
            return text, (), "entry coverage value must be `<entry-id>: <status> <destination>`"
        parsed_records.append(parsed)
    if not parsed_records:
        return text, (), None
    report = incubation_entry_coverage_report(text)
    entry_ids = {entry.entry_id for entry in report.entries}
    for record in parsed_records:
        if record.entry_id not in entry_ids:
            return text, (), f"entry coverage references unknown entry {record.entry_id!r}"
        blockers = _entry_coverage_record_blockers(record)
        if blockers:
            return text, (), "; ".join(blockers)

    lines = text.splitlines(keepends=True)
    section = _entry_coverage_section(text)
    record_text = "".join(f"- `{record.entry_id}`: `{record.status}` {record.detail}\n" for record in parsed_records)
    if section is None:
        separator = "" if text.endswith(("\n", "\r")) else "\n"
        return text + separator + "\n## Entry Coverage\n\n" + record_text, tuple(parsed_records), None

    start, end = section
    coverage_by_id = {record.entry_id: record for record in report.coverage}
    for record in parsed_records:
        coverage_by_id[record.entry_id] = record
    ordered_ids = [entry.entry_id for entry in report.entries if entry.entry_id in coverage_by_id]
    rendered = [f"- `{entry_id}`: `{coverage_by_id[entry_id].status}` {coverage_by_id[entry_id].detail}\n" for entry_id in ordered_ids]
    return "".join(lines[:start] + rendered + lines[end:]), tuple(parsed_records), None


def relationship_update_plan(
    inventory: Inventory,
    source_rel: str,
    updates: dict[str, str],
    *,
    archive_to: str = "",
    repair_links: bool = False,
    archive_blockers: tuple[str, ...] = (),
) -> tuple[RelationshipUpdatePlan | None, list[Finding]]:
    source_rel = _normalize_rel(source_rel)
    archive_rel = _normalize_rel(archive_to)
    source_path = inventory.root / source_rel if source_rel else inventory.root
    archive_path = inventory.root / archive_rel if archive_rel else None
    errors = _incubation_source_errors(inventory, source_rel, source_path)
    if archive_rel:
        errors.extend(_archive_errors(inventory, archive_rel, archive_path))
    if repair_links and not archive_rel:
        errors.append(Finding("error", "relationship-writeback-refused", "--repair-links requires an archive target", source_rel or None))
    if errors:
        return None, errors

    try:
        source_text = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [Finding("error", "relationship-writeback-refused", f"source could not be read: {exc}", source_rel)]

    update_values = {key: value for key, value in updates.items() if value not in (None, "")}
    if archive_rel:
        update_values["archived_to"] = archive_rel
    update_values["updated"] = date.today().isoformat()
    updated_text, frontmatter_error = _text_with_frontmatter_scalars(source_text, update_values)
    if frontmatter_error:
        return None, [Finding("error", "relationship-writeback-refused", frontmatter_error, source_rel)]

    changed_fields = tuple(key for key in update_values if _frontmatter_value(source_text, key) != update_values[key])
    link_repairs: tuple[tuple[str, Path, str], ...] = ()
    if repair_links and archive_rel:
        link_repairs = tuple(_planned_link_repairs(inventory, source_rel, archive_rel))

    return (
        RelationshipUpdatePlan(
            source_rel=source_rel,
            source_path=source_path,
            target_rel=archive_rel or source_rel,
            target_path=archive_path or source_path,
            current_text=source_text,
            updated_text=updated_text,
            changed_fields=changed_fields,
            archive_rel=archive_rel,
            archive_path=archive_path,
            archive_blockers=archive_blockers,
            link_repairs=link_repairs,
        ),
        [],
    )


def incubation_closeout_plan(
    inventory: Inventory,
    source_rel: str,
    *,
    roadmap_item: str,
    archived_plan: str,
    verification_summary: str,
    docs_decision: str,
) -> tuple[RelationshipUpdatePlan | None, list[Finding]]:
    source_rel = _normalize_rel(source_rel)
    source_path = inventory.root / source_rel if source_rel else inventory.root
    errors = _incubation_source_errors(inventory, source_rel, source_path)
    if errors:
        return None, errors
    try:
        source_text = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [Finding("error", "relationship-writeback-refused", f"source could not be read: {exc}", source_rel)]

    blockers = incubation_archive_blockers(source_text)
    if not archived_plan:
        blockers = (*blockers, "missing archived plan")
    if not verification_summary:
        blockers = (*blockers, "missing verification summary")
    if docs_decision not in {"updated", "not-needed"}:
        blockers = (*blockers, "docs_decision is not updated or not-needed")

    updates = {
        "related_roadmap": ROADMAP_REL,
        "related_roadmap_item": roadmap_item,
        "related_plan": archived_plan,
        "archived_plan": archived_plan,
        "implemented_by": archived_plan,
        "verification_summary": verification_summary,
        "docs_decision": docs_decision,
    }
    archive_rel = ""
    if not blockers:
        updates["status"] = "implemented"
        archive_rel = _default_incubation_archive_rel(source_rel)
    return relationship_update_plan(
        inventory,
        source_rel,
        updates,
        archive_to=archive_rel,
        repair_links=bool(archive_rel),
        archive_blockers=blockers,
    )


def incubation_archive_blockers(text: str) -> tuple[str, ...]:
    blockers: list[str] = []
    frontmatter = parse_frontmatter(text)
    for key in OPEN_THREAD_FRONTMATTER_FIELDS:
        value = frontmatter.data.get(key)
        if _frontmatter_value_is_nonempty(value):
            blockers.append(f"frontmatter {key} is present")
    body = text
    if frontmatter.has_frontmatter:
        body = "\n".join(text.splitlines()[max(frontmatter.body_start_line - 1, 0) :])
    coverage_report = incubation_entry_coverage_report(text)
    if len(coverage_report.entries) > 1:
        blockers.extend(_entry_coverage_archive_blockers(coverage_report))
    else:
        blockers.extend(_explicit_open_entry_coverage_blockers(coverage_report))
    for heading in re.findall(r"(?m)^#{2,6}\s+(.+?)\s*$", body):
        normalized = re.sub(r"\s+", " ", heading.casefold()).strip()
        if any(marker in normalized for marker in OPEN_THREAD_HEADING_MARKERS):
            blockers.append(f"open-thread heading: {heading.strip()}")
    if re.search(r"(?m)^\s*[-*]\s+\[\s\]\s+", body):
        blockers.append("unchecked task list item")
    return tuple(dict.fromkeys(blockers))


def relationship_hygiene_scan_findings(inventory: Inventory) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return [Finding("info", "relationship-scan-skipped", "relationship hygiene scan runs only for live operating roots")]

    roadmap_items = _roadmap_items(inventory)
    findings: list[Finding] = []
    findings.extend(_roadmap_relationship_findings(inventory, roadmap_items))
    findings.extend(_incubation_relationship_findings(inventory, roadmap_items))
    if not findings:
        findings.append(Finding("info", "relationship-scan-ok", "no relationship hygiene findings were found"))
    return findings


def cli_text_audit_findings() -> list[Finding]:
    audited = (
        ("incubate --note", "preserves the parsed argv string; use --note-file for shell-safe multi-paragraph text"),
        ("incubate --note-file", "preserves UTF-8 file or stdin text and reports line, character, and hash identity"),
        ("plan --objective/--task", "preserves explicit task/objective text inside the generated plan body"),
        ("roadmap text fields", "single-line by contract and refused when newline or backtick input is supplied"),
        ("writeback closeout fields", "single-line by contract and refused when multiline input is supplied"),
        ("evidence/closeout reports", "read-only proposal surfaces; no operator text is persisted"),
    )
    findings = [
        Finding(
            "info",
            "cli-text-audit-summary",
            f"audited {len(audited)} text-bearing CLI paths; multiline persistence is explicit through file/stdin or plan body paths, while one-line summary fields fail closed instead of silently changing paragraph structure",
        )
    ]
    findings.extend(Finding("info", "cli-text-audit-path", f"{path}: {posture}") for path, posture in audited)
    return findings


def _planned_link_repairs(inventory: Inventory, source_rel: str, archive_rel: str) -> list[tuple[str, Path, str]]:
    repairs: list[tuple[str, Path, str]] = []
    for path in _iter_lifecycle_markdown_files(inventory.root):
        rel_path = path.relative_to(inventory.root).as_posix()
        if rel_path == source_rel or rel_path.startswith("project/archive/"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if source_rel not in text:
            continue
        repairs.append((rel_path, path, text.replace(source_rel, archive_rel)))
    return repairs


def _incubation_source_errors(inventory: Inventory, source_rel: str, source_path: Path) -> list[Finding]:
    errors: list[Finding] = []
    if not source_rel:
        return [Finding("error", "relationship-writeback-refused", "source incubation path is required")]
    if _rel_has_absolute_or_parent_parts(source_rel):
        return [Finding("error", "relationship-writeback-refused", "source incubation path must be root-relative without parent segments", source_rel)]
    if not (
        source_rel.startswith(f"{INCUBATION_DIR_REL}/")
        or source_rel.startswith(f"{ARCHIVE_INCUBATION_DIR_REL}/")
    ):
        errors.append(Finding("error", "relationship-writeback-refused", "source incubation must be under project/plan-incubation/ or project/archive/reference/incubation/", source_rel))
    if not source_rel.endswith(".md"):
        errors.append(Finding("error", "relationship-writeback-refused", "source incubation must be a Markdown file", source_rel))
    if _path_escapes_root(inventory.root, source_path):
        errors.append(Finding("error", "relationship-writeback-refused", "source incubation path escapes the target root", source_rel))
    elif not source_path.exists():
        errors.append(Finding("error", "relationship-writeback-refused", "source incubation target is missing", source_rel))
    elif source_path.is_symlink():
        errors.append(Finding("error", "relationship-writeback-refused", "source incubation is a symlink", source_rel))
    elif not source_path.is_file():
        errors.append(Finding("error", "relationship-writeback-refused", "source incubation is not a regular file", source_rel))
    return errors


def _iter_lifecycle_markdown_files(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for rel in ("project/project-state.md", "project/implementation-plan.md", "project/roadmap.md"):
        path = root / rel
        if path.is_file() and not path.is_symlink():
            candidates.append(path)
    for base_rel in ("project/plan-incubation", "project/research", "project/specs", "project/adrs", "project/decisions", "project/verification"):
        base = root / base_rel
        if not base.is_dir() or base.is_symlink():
            continue
        candidates.extend(path for path in base.rglob("*.md") if path.is_file() and not path.is_symlink())
    return sorted(dict.fromkeys(candidates))


def _plan_findings(plan: MemoryHygienePlan, apply: bool, repair_links: bool) -> list[Finding]:
    prefix = "" if apply else "would "
    findings = [
        Finding("info", "memory-hygiene-source", f"{prefix}target source: {plan.source_rel}", plan.source_rel),
        Finding("info", "memory-hygiene-frontmatter-plan", f"{prefix}update lifecycle frontmatter with status={plan.status!r}", plan.source_rel),
    ]
    if plan.promoted_to_rel:
        findings.append(Finding("info", "memory-hygiene-promoted-to", f"{prefix}record promoted_to: {plan.promoted_to_rel}", plan.source_rel))
    if plan.archive_rel:
        findings.append(Finding("info", "memory-hygiene-archive-plan", f"{prefix}archive source to {plan.archive_rel}", plan.archive_rel))
    if plan.entry_coverage_updates:
        findings.append(
            Finding(
                "info",
                "memory-hygiene-entry-coverage-plan",
                f"{prefix}write terminal Entry Coverage for {len(plan.entry_coverage_updates)} entr{'y' if len(plan.entry_coverage_updates) == 1 else 'ies'}",
                plan.source_rel,
            )
        )
    if plan.archive_covered:
        findings.append(Finding("info", "memory-hygiene-archive-covered", f"{prefix}archive source only after terminal Entry Coverage validation", plan.archive_rel or plan.source_rel))
    if repair_links:
        count = len(plan.link_repairs)
        findings.append(Finding("info", "memory-hygiene-link-plan", f"{prefix}repair exact links in {count} file(s)", plan.archive_rel or plan.source_rel))
    return findings


def _boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "memory-hygiene-boundary",
            "memory-hygiene writes only declared MLH-owned research/incubation source, explicit archive target, and exact source-path link repairs in eligible live operating roots",
        ),
        Finding(
            "info",
            "memory-hygiene-authority",
            "memory hygiene output is bounded mutation evidence only; it cannot approve closeout, archive, commit, rollback, or lifecycle decisions",
        ),
    ]


def _relationship_scan_boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "relationship-scan-read-only",
            "relationship hygiene scan writes no files and cannot approve repair, closeout, archive, commit, rollback, or lifecycle decisions",
        ),
        Finding(
            "info",
            "relationship-scan-archive-route",
            "safe incubation auto-archive candidates use project/archive/reference/incubation/** unless a later route policy changes that lane",
        ),
    ]


def _root_posture_finding(inventory: Inventory) -> Finding:
    return Finding("info", "memory-hygiene-root-posture", f"root kind: {inventory.root_kind}")


def _roadmap_items(inventory: Inventory) -> dict[str, dict[str, object]]:
    roadmap = inventory.surface_by_rel.get(ROADMAP_REL)
    if not roadmap or not roadmap.exists:
        return {}
    items: dict[str, dict[str, object]] = {}
    current: dict[str, object] | None = None
    for line in roadmap.content.splitlines():
        if re.match(r"^###\s+\S", line.strip()):
            if current and isinstance(current.get("id"), str):
                items[str(current["id"])] = current
            current = {}
            continue
        if current is None:
            continue
        match = re.match(r"^-\s+`([A-Za-z0-9_-]+)`:\s*(.*?)\s*$", line.strip())
        if not match:
            continue
        key = match.group(1)
        raw = match.group(2).strip()
        if raw.startswith("`") and raw.endswith("`"):
            raw = raw[1:-1]
        if raw.startswith("[") and raw.endswith("]"):
            try:
                parsed = ast.literal_eval(raw)
            except (SyntaxError, ValueError):
                parsed = []
            current[key] = parsed if isinstance(parsed, list) else []
        else:
            current[key] = raw
    if current and isinstance(current.get("id"), str):
        items[str(current["id"])] = current
    return items


def _roadmap_relationship_findings(inventory: Inventory, roadmap_items: dict[str, dict[str, object]]) -> list[Finding]:
    findings: list[Finding] = []
    for item_id, fields in sorted(roadmap_items.items()):
        status = str(fields.get("status") or "")
        source_incubation = _normalize_rel(fields.get("source_incubation"))
        archived_plan = _normalize_rel(fields.get("archived_plan"))
        related_plan = _normalize_rel(fields.get("related_plan"))
        verification_summary = str(fields.get("verification_summary") or "").strip()
        docs_decision = str(fields.get("docs_decision") or "").strip()
        if source_incubation:
            source_path = inventory.root / source_incubation
            if not source_path.is_file():
                findings.append(Finding("warn", "relationship-stale-path", f"roadmap item {item_id!r} source_incubation target is missing: {source_incubation}", ROADMAP_REL))
            else:
                source_surface = inventory.surface_by_rel.get(source_incubation)
                data = source_surface.frontmatter.data if source_surface else parse_frontmatter(source_path.read_text(encoding="utf-8", errors="replace")).data
                reciprocal_item = str(data.get("related_roadmap_item") or "")
                promoted_to = _normalize_rel(data.get("promoted_to"))
                related_roadmap = _normalize_rel(data.get("related_roadmap"))
                if reciprocal_item != item_id and promoted_to != ROADMAP_REL and related_roadmap != ROADMAP_REL:
                    findings.append(
                        Finding(
                            "warn",
                            "relationship-missing-reciprocal",
                            f"roadmap item {item_id!r} points to {source_incubation}, but the incubation note does not point back to the roadmap item",
                            source_incubation,
                        )
                    )
        if status == "done":
            if not archived_plan:
                findings.append(Finding("warn", "relationship-roadmap-done-missing-archive", f"done roadmap item {item_id!r} has no archived_plan", ROADMAP_REL))
            if not verification_summary:
                findings.append(Finding("warn", "relationship-roadmap-done-missing-verification", f"done roadmap item {item_id!r} has no verification_summary", ROADMAP_REL))
            if docs_decision not in {"updated", "not-needed"}:
                findings.append(Finding("warn", "relationship-roadmap-done-missing-docs", f"done roadmap item {item_id!r} lacks a final docs_decision", ROADMAP_REL))
            if archived_plan and related_plan == "project/implementation-plan.md":
                findings.append(Finding("warn", "relationship-stale-active-plan-link", f"done roadmap item {item_id!r} still has related_plan pointing at the active plan", ROADMAP_REL))
    return findings


def _incubation_relationship_findings(inventory: Inventory, roadmap_items: dict[str, dict[str, object]]) -> list[Finding]:
    findings: list[Finding] = []
    items_by_source: dict[str, tuple[str, dict[str, object]]] = {}
    for item_id, fields in roadmap_items.items():
        source = _normalize_rel(fields.get("source_incubation"))
        if source:
            items_by_source[source] = (item_id, fields)

    for surface in sorted(inventory.present_surfaces, key=lambda item: item.rel_path):
        if not surface.rel_path.startswith(f"{INCUBATION_DIR_REL}/") or surface.path.suffix.lower() != ".md":
            continue
        data = surface.frontmatter.data
        status = str(data.get("status") or "").strip().casefold()
        relation_values = [data.get(field) for field in RELATIONSHIP_STATUS_FIELDS]
        related_item = str(data.get("related_roadmap_item") or "")
        if status in {"implemented", "archived", "rejected", "superseded"}:
            findings.append(Finding("warn", "relationship-active-incubation-closed", f"closed incubation note is still in the active incubation lane with status {status!r}", surface.rel_path))
        if not any(_frontmatter_value_is_nonempty(value) for value in relation_values):
            findings.append(Finding("warn", "relationship-orphan-incubation", "incubation note has no roadmap, plan, archive, rejection, or supersession relationship metadata", surface.rel_path))
        findings.extend(_incubation_entry_coverage_findings(surface.rel_path, surface.content))
        findings.extend(_incubation_split_suggestion_findings(surface.rel_path, surface.content))
        source_item = items_by_source.get(surface.rel_path)
        item_id = related_item or (source_item[0] if source_item else "")
        item_fields = roadmap_items.get(item_id) if item_id else None
        if not item_fields or str(item_fields.get("status") or "") != "done":
            continue
        blockers = incubation_archive_blockers(surface.content)
        if blockers:
            findings.append(
                Finding(
                    "warn",
                    "relationship-mixed-incubation-blocker",
                    f"incubation note is linked to done roadmap item {item_id!r} but is not safe for whole-file archive: {', '.join(blockers)}",
                    surface.rel_path,
                )
            )
            continue
        archived_plan = _normalize_rel(item_fields.get("archived_plan"))
        verification = str(item_fields.get("verification_summary") or "").strip()
        docs_decision = str(item_fields.get("docs_decision") or "").strip()
        if archived_plan and verification and docs_decision in {"updated", "not-needed"}:
            archive_rel = _default_incubation_archive_rel(surface.rel_path)
            findings.append(
                Finding(
                    "info",
                    "relationship-auto-archive-candidate",
                    f"single-entry incubation note is structurally covered by roadmap item {item_id!r}; safe cleanup command: mylittleharness memory-hygiene --dry-run --source {surface.rel_path} --archive-to {archive_rel} --repair-links",
                    surface.rel_path,
                )
            )
    return findings


def incubation_entry_coverage_report(text: str) -> EntryCoverageReport:
    coverage, errors = _entry_coverage_records(text)
    return EntryCoverageReport(
        entries=tuple(_incubation_entries(text)),
        coverage=tuple(coverage),
        errors=tuple(errors),
    )


def _incubation_entries(text: str) -> list[IncubationEntry]:
    frontmatter = parse_frontmatter(text)
    lines = text.splitlines()
    start_index = max(frontmatter.body_start_line - 1, 0) if frontmatter.has_frontmatter else 0
    raw_entries: list[tuple[str, str, int]] = []
    for index in range(start_index, len(lines)):
        match = re.match(r"^###\s+(\d{4}-\d{2}-\d{2})(?:\s+[-:]\s+(.+?))?\s*$", lines[index].strip())
        if not match:
            continue
        raw_entries.append((match.group(1), lines[index].strip()[4:].strip(), index + 1))

    date_counts: dict[str, int] = {}
    for entry_date, _heading, _line in raw_entries:
        date_counts[entry_date] = date_counts.get(entry_date, 0) + 1

    seen: dict[str, int] = {}
    entries: list[IncubationEntry] = []
    for entry_date, heading, line in raw_entries:
        seen[entry_date] = seen.get(entry_date, 0) + 1
        entry_id = entry_date if date_counts[entry_date] == 1 else f"{entry_date}#{seen[entry_date]}"
        entries.append(IncubationEntry(entry_id=entry_id, heading=heading, line=line))
    return entries


def _entry_coverage_records(text: str) -> tuple[list[EntryCoverage], list[str]]:
    section = _entry_coverage_section(text)
    if section is None:
        return [], []
    start_index, end_index = section
    records: list[EntryCoverage] = []
    errors: list[str] = []
    seen: set[str] = set()
    lines = text.splitlines()
    for index in range(start_index, end_index):
        raw = lines[index]
        stripped = raw.strip()
        if not stripped:
            continue
        if not stripped.startswith(("- ", "* ")):
            continue
        parsed = _parse_entry_coverage_line(stripped, index + 1)
        if parsed is None:
            errors.append(f"line {index + 1}: entry coverage bullet must be `<entry-id>: <status> <destination>`")
            continue
        if parsed.entry_id in seen:
            errors.append(f"line {index + 1}: duplicate entry coverage id {parsed.entry_id!r}")
            continue
        seen.add(parsed.entry_id)
        records.append(parsed)
    return records, errors


def _entry_coverage_section(text: str) -> tuple[int, int] | None:
    lines = text.splitlines()
    headings: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^(#{2,6})\s+(.+?)\s*$", line.strip())
        if match:
            headings.append((index, len(match.group(1)), _normalized_heading(match.group(2))))
    for position, (start, level, title) in enumerate(headings):
        if title != ENTRY_COVERAGE_HEADING:
            continue
        end = len(lines)
        for next_start, next_level, _next_title in headings[position + 1 :]:
            if next_level <= level:
                end = next_start
                break
        return start + 1, end
    return None


def _parse_entry_coverage_line(line: str, line_number: int) -> EntryCoverage | None:
    match = re.match(r"^[-*]\s+`?(?P<entry_id>[^`:]+?)`?\s*:\s*(?P<rest>.+?)\s*$", line)
    if not match:
        return None
    entry_id = _normalized_entry_id(match.group("entry_id"))
    rest = match.group("rest").strip()
    status_match = re.match(r"`?(?P<status>[A-Za-z][A-Za-z0-9_-]*)`?(?P<detail>.*)$", rest)
    if not entry_id or not status_match:
        return None
    status = _normalized_coverage_status(status_match.group("status"))
    detail = status_match.group("detail").strip()
    detail = re.sub(r"^\s*[-;,:]\s*", "", detail).strip()
    return EntryCoverage(entry_id=entry_id, status=status, detail=detail, line=line_number)


def _entry_coverage_archive_blockers(report: EntryCoverageReport) -> list[str]:
    blockers: list[str] = []
    entry_ids = {entry.entry_id for entry in report.entries}
    coverage_by_id = {record.entry_id: record for record in report.coverage}
    if report.errors:
        blockers.append("entry coverage metadata is malformed")
    if not report.coverage:
        blockers.append("multiple dated incubation entries without entry coverage")
        return blockers
    for entry in report.entries:
        record = coverage_by_id.get(entry.entry_id)
        if record is None:
            blockers.append(f"entry coverage missing {entry.entry_id}")
            continue
        blockers.extend(_entry_coverage_record_blockers(record))
    for record in report.coverage:
        if record.entry_id not in entry_ids:
            blockers.append(f"entry coverage references unknown entry {record.entry_id}")
    return blockers


def _explicit_open_entry_coverage_blockers(report: EntryCoverageReport) -> list[str]:
    blockers: list[str] = []
    if report.errors:
        blockers.append("entry coverage metadata is malformed")
    for record in report.coverage:
        blockers.extend(_entry_coverage_record_blockers(record))
    return blockers


def _entry_coverage_record_blockers(record: EntryCoverage) -> list[str]:
    if record.status in ENTRY_COVERAGE_OPEN_STATUSES:
        return [f"entry coverage {record.entry_id} is {record.status}"]
    if record.status not in ENTRY_COVERAGE_TERMINAL_STATUSES:
        return [f"entry coverage {record.entry_id} has unknown status {record.status!r}"]
    if not _entry_coverage_has_destination(record):
        return [f"entry coverage {record.entry_id} lacks destination detail"]
    return []


def _entry_coverage_has_destination(record: EntryCoverage) -> bool:
    if record.status == "rejected":
        return bool(record.detail)
    return bool(record.detail)


def _incubation_entry_coverage_findings(rel_path: str, text: str) -> list[Finding]:
    report = incubation_entry_coverage_report(text)
    if not report.entries:
        return []
    findings: list[Finding] = []
    for error in report.errors:
        findings.append(Finding("warn", "relationship-entry-coverage-malformed", error, rel_path))
    if len(report.entries) <= 1:
        for record in report.coverage:
            for blocker in _entry_coverage_record_blockers(record):
                findings.append(Finding("warn", "relationship-entry-coverage-open", blocker, rel_path, record.line))
        return findings

    blockers = _entry_coverage_archive_blockers(report)
    if blockers:
        findings.append(
            Finding(
                "warn",
                "relationship-entry-coverage-needed",
                f"mixed incubation note needs terminal Entry Coverage before whole-file archive: {', '.join(blockers)}",
                rel_path,
            )
        )
        return findings

    findings.append(
        Finding(
            "info",
            "relationship-entry-coverage-complete",
            f"all {len(report.entries)} dated incubation entries have terminal Entry Coverage metadata",
            rel_path,
        )
    )
    return findings


def _incubation_split_suggestion_findings(rel_path: str, text: str) -> list[Finding]:
    report = incubation_entry_coverage_report(text)
    if len(report.entries) <= 1:
        return []
    entry_ids = [entry.entry_id for entry in report.entries]
    if not report.coverage:
        return [
            Finding(
                "info",
                "relationship-semantic-split-suggestion",
                f"review split suggestion: dated entries {', '.join(entry_ids)} may be separate ideas; add Entry Coverage or split them into separate incubation notes before archiving",
                rel_path,
            )
        ]

    terminal_ids = {
        record.entry_id
        for record in report.coverage
        if record.status in ENTRY_COVERAGE_TERMINAL_STATUSES and _entry_coverage_has_destination(record)
    }
    open_ids = [entry.entry_id for entry in report.entries if entry.entry_id not in terminal_ids]
    if terminal_ids and open_ids:
        return [
            Finding(
                "info",
                "relationship-semantic-split-suggestion",
                f"review split suggestion: covered entries {', '.join(sorted(terminal_ids))} and open entries {', '.join(open_ids)} should be separated or explicitly covered before whole-file archive; this is a heuristic no-write suggestion",
                rel_path,
            )
        ]
    return []


def _text_with_frontmatter_scalars(text: str, updates: dict[str, str]) -> tuple[str, str | None]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text, "source frontmatter is required for relationship writeback"
    closing_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        return text, "source frontmatter is malformed"

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
        lines[closing_index:closing_index] = [f'{key}: "{_yaml_double_quoted_value(updates[key])}"\n' for key in missing]
    return "".join(lines), None


def _frontmatter_value(text: str, key: str) -> str | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        match = re.match(rf"^{re.escape(key)}:\s*(.*?)\s*$", line)
        if match:
            return _strip_quotes(match.group(1).strip())
    return None


def _frontmatter_value_is_nonempty(value: object) -> bool:
    if value in (None, "", [], ()):
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_frontmatter_value_is_nonempty(item) for item in value)
    return True


def _default_incubation_archive_rel(source_rel: str) -> str:
    source = Path(source_rel)
    return f"{ARCHIVE_INCUBATION_DIR_REL}/{date.today().isoformat()}-{source.stem}.md"


def _normalized_status(status: str | None, promoted_to: str, archive_to: str) -> str:
    normalized = str(status or "").strip().casefold().replace("_", "-")
    if normalized:
        return normalized
    if promoted_to:
        return "distilled"
    if archive_to:
        return "archived"
    return ""


def _normalized_heading(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold()).strip(" :")


def _normalized_entry_id(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().strip("`").casefold())


def _normalized_coverage_status(value: object) -> str:
    return str(value or "").strip().casefold().replace("_", "-")


def _normalize_rel(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/")


def _source_route_allowed(rel_path: str) -> bool:
    return rel_path.startswith(f"{RESEARCH_DIR_REL}/") or rel_path.startswith(f"{INCUBATION_DIR_REL}/")


def _archive_route_allowed(rel_path: str) -> bool:
    return rel_path.startswith(f"{ARCHIVE_RESEARCH_DIR_REL}/") or rel_path.startswith(f"{ARCHIVE_INCUBATION_DIR_REL}/")


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


def _yaml_double_quoted_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _strip_quotes(value: str) -> str:
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def _with_severity(findings: list[Finding], severity: str) -> list[Finding]:
    return [Finding(severity, finding.code, finding.message, finding.source, finding.line) for finding in findings]
