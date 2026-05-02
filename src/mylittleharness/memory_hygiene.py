from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .inventory import Inventory
from .models import Finding


RESEARCH_DIR_REL = "project/research"
INCUBATION_DIR_REL = "project/plan-incubation"
ARCHIVE_RESEARCH_DIR_REL = "project/archive/reference/research"
ARCHIVE_INCUBATION_DIR_REL = "project/archive/reference/incubation"
ALLOWED_STATUS_VALUES = {"archived", "distilled", "implemented", "rejected"}


@dataclass(frozen=True)
class MemoryHygieneRequest:
    source: str
    promoted_to: str
    status: str
    archive_to: str
    repair_links: bool = False


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


def make_memory_hygiene_request(
    source: str | None,
    promoted_to: str | None,
    status: str | None,
    archive_to: str | None,
    repair_links: bool = False,
) -> MemoryHygieneRequest:
    promoted = _normalize_rel(promoted_to)
    archive = _normalize_rel(archive_to)
    normalized_status = _normalized_status(status, promoted, archive)
    return MemoryHygieneRequest(
        source=_normalize_rel(source),
        promoted_to=promoted,
        status=normalized_status,
        archive_to=archive,
        repair_links=repair_links,
    )


def memory_hygiene_dry_run_findings(inventory: Inventory, request: MemoryHygieneRequest) -> list[Finding]:
    findings = [
        Finding("info", "memory-hygiene-dry-run", "memory hygiene proposal only; no files were written"),
        _root_posture_finding(inventory),
    ]
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
    plan, errors = _memory_hygiene_plan(inventory, request)
    if errors:
        return errors
    assert plan is not None

    tmp_paths: list[Path] = []
    try:
        if plan.archive_path:
            plan.archive_path.parent.mkdir(parents=True, exist_ok=True)
            archive_tmp = plan.archive_path.with_name(f".{plan.archive_path.name}.memory-hygiene.tmp")
            archive_tmp.write_text(plan.updated_source_text, encoding="utf-8")
            tmp_paths.append(archive_tmp)
        else:
            source_tmp = plan.source_path.with_name(f".{plan.source_path.name}.memory-hygiene.tmp")
            source_tmp.write_text(plan.updated_source_text, encoding="utf-8")
            tmp_paths.append(source_tmp)

        link_tmp_paths: list[tuple[Path, Path]] = []
        for _, path, text in plan.link_repairs:
            link_tmp = path.with_name(f".{path.name}.memory-hygiene.tmp")
            link_tmp.write_text(text, encoding="utf-8")
            tmp_paths.append(link_tmp)
            link_tmp_paths.append((link_tmp, path))

        for link_tmp, path in link_tmp_paths:
            link_tmp.replace(path)
            tmp_paths.remove(link_tmp)

        if plan.archive_path:
            archive_tmp.replace(plan.archive_path)
            tmp_paths.remove(archive_tmp)
            plan.source_path.unlink()
        else:
            source_tmp.replace(plan.source_path)
            tmp_paths.remove(source_tmp)
    except OSError as exc:
        for tmp in tmp_paths:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
        return [Finding("error", "memory-hygiene-refused", f"memory hygiene apply failed before all target writes completed: {exc}", plan.source_rel)]

    findings = [
        Finding("info", "memory-hygiene-apply", "memory hygiene apply started"),
        _root_posture_finding(inventory),
        Finding("info", "memory-hygiene-frontmatter-updated", "updated lifecycle frontmatter", plan.archive_rel or plan.source_rel),
    ]
    if plan.archive_rel:
        findings.append(Finding("info", "memory-hygiene-archived", f"archived source to {plan.archive_rel}", plan.archive_rel))
    for rel_path, _, _ in plan.link_repairs:
        findings.append(Finding("info", "memory-hygiene-link-repaired", f"repaired exact source-path references in {rel_path}", rel_path))
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

    if not request.source:
        errors.append(Finding("error", "memory-hygiene-refused", "--source is required and cannot be empty"))
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


def _iter_lifecycle_markdown_files(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for rel in ("project/project-state.md", "project/implementation-plan.md"):
        path = root / rel
        if path.is_file() and not path.is_symlink():
            candidates.append(path)
    for base_rel in ("project/plan-incubation", "project/research", "project/specs"):
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


def _root_posture_finding(inventory: Inventory) -> Finding:
    return Finding("info", "memory-hygiene-root-posture", f"root kind: {inventory.root_kind}")


def _normalized_status(status: str | None, promoted_to: str, archive_to: str) -> str:
    normalized = str(status or "").strip().casefold().replace("_", "-")
    if normalized:
        return normalized
    if promoted_to:
        return "distilled"
    if archive_to:
        return "archived"
    return ""


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


def _with_severity(findings: list[Finding], severity: str) -> list[Finding]:
    return [Finding(severity, finding.code, finding.message, finding.source, finding.line) for finding in findings]
