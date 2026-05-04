from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path

from .atomic_files import AtomicFileWrite, FileTransactionError, apply_file_transaction
from .inventory import Inventory
from .models import Finding
from .parsing import parse_frontmatter


INCUBATION_DIR_REL = "project/plan-incubation"
INCUBATION_SOURCE = "incubate cli"
DEFAULT_PLAN_REL = "project/implementation-plan.md"
ROADMAP_REL = "project/roadmap.md"
NON_AUTHORITY_NOTE = (
    "incubation is temporary synthesis; promoted research/spec/plan/state remains authority when accepted."
)
RELATIONSHIP_FIELDS = (
    "related_plan",
    "related_roadmap",
    "related_roadmap_item",
    "source_incubation",
    "source_research",
    "promoted_to",
    "archived_to",
    "implemented_by",
    "archived_plan",
    "supersedes",
    "superseded_by",
    "merged_into",
    "merged_from",
    "split_from",
    "split_to",
    "rejected_by",
)
_RESERVED_SLUGS = {
    "aux",
    "con",
    "incubation",
    "nul",
    "plan-incubation",
    "prn",
    "project",
    *{f"com{index}" for index in range(1, 10)},
    *{f"lpt{index}" for index in range(1, 10)},
}


@dataclass(frozen=True)
class IncubateRequest:
    topic: str
    note: str
    note_source: str = "--note"
    fix_candidate: bool = False


@dataclass(frozen=True)
class IncubationTarget:
    topic: str
    note: str
    note_source: str
    fix_candidate: bool
    slug: str
    rel_path: str
    path: Path


@dataclass(frozen=True)
class IncubationWritePlan:
    text: str
    relationship_fields: tuple[str, ...] = ()
    relationship_skip: str = ""


def make_incubate_request(topic: str | None, note: str | None, note_source: str = "--note", fix_candidate: bool = False) -> IncubateRequest:
    normalized_note = _normalized_note(note)
    if fix_candidate:
        normalized_note = _fix_candidate_note(normalized_note)
    return IncubateRequest(
        topic=_normalized_text(topic),
        note=normalized_note,
        note_source=note_source,
        fix_candidate=fix_candidate,
    )


def incubate_dry_run_findings(inventory: Inventory, request: IncubateRequest) -> list[Finding]:
    findings = [
        Finding("info", "incubate-dry-run", "incubate proposal only; no files were written"),
        _root_posture_finding(inventory),
    ]
    target = _incubation_target(inventory, request)
    errors = _incubate_preflight_errors(inventory, request, target)
    if target:
        findings.extend(_target_findings(target, apply=False))
    if errors:
        findings.extend(_with_severity(errors, "warn"))
        findings.append(
            Finding(
                "info",
                "incubate-validation-posture",
                "dry-run refused before apply; fix refusal reasons, then rerun dry-run before writing incubation notes",
            )
        )
        return findings
    assert target is not None
    write_plan = _incubation_write_plan(inventory, target, existed=target.path.exists())
    findings.append(_note_body_finding(target))
    if request.fix_candidate:
        findings.append(Finding("info", "incubate-fix-candidate", "would record note with [MLH-Fix-Candidate] tag", target.rel_path))
    findings.extend(_relationship_findings(target, write_plan, apply=False))
    findings.append(_note_posture_finding(target, apply=False))
    findings.extend(_boundary_findings())
    findings.append(
        Finding(
            "info",
            "incubate-validation-posture",
            "apply would write only the target incubation note in a live operating root; dry-run writes no files",
            target.rel_path,
        )
    )
    return findings


def incubate_apply_findings(inventory: Inventory, request: IncubateRequest) -> list[Finding]:
    target = _incubation_target(inventory, request)
    errors = _incubate_preflight_errors(inventory, request, target)
    if errors:
        return errors
    assert target is not None

    existed = target.path.exists()
    write_plan = _incubation_write_plan(inventory, target, existed=existed)
    tmp_path = target.path.with_name(f".{target.path.name}.incubate.tmp")
    backup_path = target.path.with_name(f".{target.path.name}.incubate.backup")
    try:
        cleanup_warnings = apply_file_transaction(
            (AtomicFileWrite(target.path, tmp_path, write_plan.text, backup_path),)
        )
    except OSError as exc:
        return [Finding("error", "incubate-refused", f"incubate apply failed before all target writes completed: {exc}", target.rel_path)]

    findings = [
        Finding("info", "incubate-apply", "incubation note apply started"),
        _root_posture_finding(inventory),
        *_target_findings(target, apply=True),
        _note_body_finding(target),
        *([Finding("info", "incubate-fix-candidate", "recorded note with [MLH-Fix-Candidate] tag", target.rel_path)] if request.fix_candidate else []),
        *_relationship_findings(target, write_plan, apply=True),
        _note_posture_finding(target, apply=True, existed=existed),
        *_boundary_findings(),
        Finding(
            "info",
            "incubate-validation-posture",
            "run check after apply to verify the live operating root remains healthy; incubation notes are non-authority until promoted",
            target.rel_path,
        ),
    ]
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "incubate-backup-cleanup", warning, target.rel_path))
    return findings


def _incubation_target(inventory: Inventory, request: IncubateRequest) -> IncubationTarget | None:
    slug = _safe_slug(request.topic)
    if not slug:
        return None
    rel_path = f"{INCUBATION_DIR_REL}/{slug}.md"
    return IncubationTarget(
        topic=request.topic,
        note=request.note,
        note_source=request.note_source,
        fix_candidate=request.fix_candidate,
        slug=slug,
        rel_path=rel_path,
        path=inventory.root / rel_path,
    )


def _incubate_preflight_errors(
    inventory: Inventory,
    request: IncubateRequest,
    target: IncubationTarget | None,
) -> list[Finding]:
    errors: list[Finding] = []
    if not request.topic:
        errors.append(Finding("error", "incubate-refused", "--topic is required and cannot be empty or whitespace-only"))
    if not request.note:
        errors.append(Finding("error", "incubate-refused", "--note is required and cannot be empty or whitespace-only"))
    if request.topic and _topic_looks_like_path(request.topic):
        errors.append(Finding("error", "incubate-refused", "topic looks like a path or reserved filename; provide a plain future-idea topic"))
    if request.topic and target is None:
        errors.append(Finding("error", "incubate-refused", "topic does not produce a safe non-empty ASCII slug"))
    elif target and target.slug in _RESERVED_SLUGS:
        errors.append(Finding("error", "incubate-refused", f"topic slug is reserved or ambiguous: {target.slug!r}"))

    if inventory.root_kind == "product_source_fixture":
        errors.append(
            Finding(
                "error",
                "incubate-refused",
                "target is a product-source compatibility fixture; incubate --apply is refused",
                target.rel_path if target else INCUBATION_DIR_REL,
            )
        )
    elif inventory.root_kind == "fallback_or_archive":
        errors.append(
            Finding(
                "error",
                "incubate-refused",
                "target is fallback/archive or generated-output evidence; incubate --apply is refused",
                target.rel_path if target else INCUBATION_DIR_REL,
            )
        )
    elif inventory.root_kind != "live_operating_root":
        errors.append(Finding("error", "incubate-refused", f"target root kind is {inventory.root_kind}; incubate requires a live operating root"))

    state = inventory.state
    if state is None or not state.exists:
        errors.append(Finding("error", "incubate-refused", "project-state.md is missing", "project/project-state.md"))
    elif not state.frontmatter.has_frontmatter:
        errors.append(Finding("error", "incubate-refused", "project-state.md frontmatter is required for incubate apply", state.rel_path))
    elif state.frontmatter.errors:
        errors.append(Finding("error", "incubate-refused", "project-state.md frontmatter is malformed", state.rel_path))
    elif not state.path.is_file():
        errors.append(Finding("error", "incubate-refused", "project-state.md is not a regular file", state.rel_path))
    elif state.path.is_symlink():
        errors.append(Finding("error", "incubate-refused", "project-state.md is a symlink", state.rel_path))

    incubation_dir = inventory.root / INCUBATION_DIR_REL
    if _path_escapes_root(inventory.root, incubation_dir):
        errors.append(Finding("error", "incubate-refused", "incubation directory path escapes the target root", INCUBATION_DIR_REL))
    for parent in _parents_between(inventory.root, incubation_dir):
        rel = parent.relative_to(inventory.root).as_posix()
        if parent.exists() and parent.is_symlink():
            errors.append(Finding("error", "incubate-refused", f"incubation directory contains a symlink segment: {rel}", rel))
        elif parent.exists() and not parent.is_dir():
            errors.append(Finding("error", "incubate-refused", f"incubation directory contains a non-directory segment: {rel}", rel))

    if target:
        if _path_escapes_root(inventory.root, target.path):
            errors.append(Finding("error", "incubate-refused", "target note path escapes the target root", target.rel_path))
        elif target.path.exists():
            if target.path.is_symlink():
                errors.append(Finding("error", "incubate-refused", "target note is a symlink; append is refused", target.rel_path))
            elif not target.path.is_file():
                errors.append(Finding("error", "incubate-refused", "target note path exists but is not a regular file", target.rel_path))
    return errors


def _target_findings(target: IncubationTarget, apply: bool) -> list[Finding]:
    verb = "target note path" if apply else "would target note path"
    return [
        Finding("info", "incubate-topic", f"normalized topic: {target.topic}; slug: {target.slug}", target.rel_path),
        Finding("info", "incubate-target-note", f"{verb}: {target.rel_path}", target.rel_path),
    ]


def _note_posture_finding(target: IncubationTarget, apply: bool, existed: bool | None = None) -> Finding:
    exists = target.path.exists() if existed is None else existed
    if apply:
        action = "appended to existing same-topic incubation note" if exists else "created same-topic incubation note"
    else:
        action = "would append to existing same-topic incubation note" if exists else "would create same-topic incubation note"
    return Finding("info", "incubate-note-posture", action, target.rel_path)


def _note_body_finding(target: IncubationTarget) -> Finding:
    digest = sha256(target.note.encode("utf-8")).hexdigest()[:16]
    line_count = len(target.note.splitlines()) or 1
    return Finding(
        "info",
        "incubate-note-body",
        f"note input: {target.note_source}; lines={line_count}; chars={len(target.note)}; sha256={digest}",
        target.rel_path,
    )


def _root_posture_finding(inventory: Inventory) -> Finding:
    return Finding("info", "incubate-root-posture", f"root kind: {inventory.root_kind}")


def _boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "incubate-boundary",
            "incubate writes only project/plan-incubation/<safe-topic-slug>.md in eligible live operating roots; it does not repair, archive, stage, commit, or mutate product-source fixtures",
        ),
        Finding(
            "info",
            "incubate-authority",
            "incubation notes are temporary non-authority synthesis until promoted into accepted research, specs, plans, or state",
        ),
    ]


def _incubation_write_plan(inventory: Inventory, target: IncubationTarget, *, existed: bool) -> IncubationWritePlan:
    relationships = _known_active_relationships(inventory, target)
    if not existed:
        return IncubationWritePlan(
            text=_new_note_text(target, relationships),
            relationship_fields=tuple(relationships),
            relationship_skip="" if relationships else "no active plan relationship facts were structurally known",
        )

    current_text = target.path.read_text(encoding="utf-8")
    updated_text = current_text
    relationship_fields: tuple[str, ...] = ()
    relationship_skip = ""
    if relationships:
        updated_text, relationship_fields, relationship_skip = _text_with_relationships_if_unclaimed(current_text, relationships)
    else:
        relationship_skip = "no active plan relationship facts were structurally known"
    return IncubationWritePlan(
        text=updated_text + _append_entry(target.note),
        relationship_fields=relationship_fields,
        relationship_skip=relationship_skip,
    )


def _known_active_relationships(inventory: Inventory, target: IncubationTarget) -> dict[str, str]:
    state = inventory.state
    if state is None or not state.exists or not state.frontmatter.has_frontmatter or state.frontmatter.errors:
        return {}
    state_data = state.frontmatter.data
    if str(state_data.get("plan_status") or "").strip() != "active":
        return {}
    active_plan = _normalize_rel(state_data.get("active_plan"))
    if active_plan != DEFAULT_PLAN_REL:
        return {}
    plan = inventory.active_plan_surface
    if plan is None or not plan.exists or plan.path.is_symlink() or not plan.path.is_file():
        return {}

    relationships = {"related_plan": DEFAULT_PLAN_REL}
    if not plan.frontmatter.has_frontmatter or plan.frontmatter.errors:
        return {} if target.fix_candidate else relationships

    plan_data = plan.frontmatter.data
    roadmap_item = _normalized_item_id(plan_data.get("primary_roadmap_item") or plan_data.get("related_roadmap_item"))
    if target.fix_candidate and not _target_matches_active_plan(target, plan_data, roadmap_item):
        return {}
    if roadmap_item:
        relationships["related_roadmap_item"] = roadmap_item
        roadmap = inventory.root / ROADMAP_REL
        if roadmap.is_file() and not roadmap.is_symlink():
            relationships["related_roadmap"] = ROADMAP_REL
    return relationships


def _target_matches_active_plan(target: IncubationTarget, plan_data: dict[str, object], roadmap_item: str) -> bool:
    target_keys = {_normalized_item_id(target.topic), _normalized_item_id(target.slug)}
    candidate_keys = {
        roadmap_item,
        _normalized_item_id(plan_data.get("related_roadmap_item")),
        _normalized_item_id(plan_data.get("primary_roadmap_item")),
        _normalized_item_id(plan_data.get("execution_slice")),
        _normalized_item_id(plan_data.get("plan_id")),
        _normalized_item_id(plan_data.get("title")),
    }
    for item in _frontmatter_list_values(plan_data.get("covered_roadmap_items")):
        candidate_keys.add(_normalized_item_id(item))
    return bool(target_keys & {key for key in candidate_keys if key})


def _text_with_relationships_if_unclaimed(text: str, relationships: dict[str, str]) -> tuple[str, tuple[str, ...], str]:
    frontmatter = parse_frontmatter(text)
    if not frontmatter.has_frontmatter:
        return text, (), "existing note has no frontmatter; relationship metadata was left unchanged"
    if frontmatter.errors:
        return text, (), "existing note frontmatter is malformed; relationship metadata was left unchanged"
    if any(_frontmatter_value_is_nonempty(frontmatter.data.get(field)) for field in RELATIONSHIP_FIELDS):
        return text, (), "existing note already has relationship metadata; relationship metadata was left unchanged"

    updates = dict(relationships)
    updates["updated"] = date.today().isoformat()
    return _text_with_frontmatter_scalars(text, updates), tuple(relationships), ""


def _relationship_findings(target: IncubationTarget, plan: IncubationWritePlan, apply: bool) -> list[Finding]:
    if plan.relationship_fields:
        prefix = "" if apply else "would "
        return [
            Finding(
                "info",
                "incubate-relationship-sync",
                f"{prefix}record known active-plan relationship metadata: {', '.join(plan.relationship_fields)}",
                target.rel_path,
            )
        ]
    if plan.relationship_skip and apply:
        return [Finding("info", "incubate-relationship-skipped", plan.relationship_skip, target.rel_path)]
    return []


def _new_note_text(target: IncubationTarget, relationships: dict[str, str] | None = None) -> str:
    today = date.today().isoformat()
    relationship_lines = _relationship_frontmatter_lines(relationships or {})
    return (
        "---\n"
        f'topic: "{_yaml_double_quoted_value(target.topic)}"\n'
        'status: "incubating"\n'
        f'created: "{today}"\n'
        f'updated: "{today}"\n'
        f'source: "{INCUBATION_SOURCE}"\n'
        f"{relationship_lines}"
        "---\n"
        f"# {target.topic}\n\n"
        "## Provenance\n\n"
        f"- Source: {INCUBATION_SOURCE}\n"
        f"- Non-authority note: {NON_AUTHORITY_NOTE}\n\n"
        "## Entries\n"
        f"{_entry_text(target.note)}"
    )


def _append_entry(note: str) -> str:
    return "\n" + _entry_text(note)


def _entry_text(note: str) -> str:
    return f"\n### {date.today().isoformat()}\n\n{note.rstrip()}\n"


def _safe_slug(topic: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", topic).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def _topic_looks_like_path(topic: str) -> bool:
    stripped = topic.strip()
    lowered = stripped.lower()
    if stripped in {".", ".."} or stripped.startswith("."):
        return True
    if any(separator in stripped for separator in ("/", "\\", ":")):
        return True
    if ".." in stripped or lowered.endswith((".md", ".txt", ".yaml", ".yml", ".toml")):
        return True
    if re.match(r"^[A-Za-z]:", stripped):
        return True
    return False


def _normalized_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).rstrip(".")


def _normalized_note(value: object) -> str:
    return str(value or "").strip()


def _normalized_item_id(value: object) -> str:
    return str(value or "").strip().casefold().replace("_", "-")


def _fix_candidate_note(note: str) -> str:
    if note.lstrip().startswith("[MLH-Fix-Candidate]"):
        return note
    return f"[MLH-Fix-Candidate] {note}".strip()


def _relationship_frontmatter_lines(relationships: dict[str, str]) -> str:
    return "".join(f'{key}: "{_yaml_double_quoted_value(value)}"\n' for key, value in relationships.items() if value)


def _text_with_frontmatter_scalars(text: str, updates: dict[str, str]) -> str:
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

    missing = [key for key in updates if key not in seen]
    if missing:
        lines[closing_index:closing_index] = [f'{key}: "{_yaml_double_quoted_value(updates[key])}"\n' for key in missing]
    return "".join(lines)


def _frontmatter_value_is_nonempty(value: object) -> bool:
    if value in (None, "", [], ()):
        return False
    if isinstance(value, (list, tuple, set)):
        return any(_frontmatter_value_is_nonempty(item) for item in value)
    return bool(str(value).strip())


def _frontmatter_list_values(value: object) -> tuple[str, ...]:
    if value in (None, "", [], ()):
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if str(item).strip())
    return (str(value),)


def _normalize_rel(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/")


def _yaml_double_quoted_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


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
