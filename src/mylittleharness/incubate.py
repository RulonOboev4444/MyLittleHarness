from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .inventory import Inventory
from .models import Finding


INCUBATION_DIR_REL = "project/plan-incubation"
INCUBATION_SOURCE = "incubate cli"
NON_AUTHORITY_NOTE = (
    "incubation is temporary synthesis; promoted research/spec/plan/state remains authority when accepted."
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


@dataclass(frozen=True)
class IncubationTarget:
    topic: str
    note: str
    slug: str
    rel_path: str
    path: Path


def make_incubate_request(topic: str | None, note: str | None) -> IncubateRequest:
    return IncubateRequest(topic=_normalized_text(topic), note=_normalized_note(note))


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
    try:
        target.path.parent.mkdir(parents=True, exist_ok=True)
        if existed:
            with target.path.open("a", encoding="utf-8") as handle:
                handle.write(_append_entry(target.note))
        else:
            target.path.write_text(_new_note_text(target), encoding="utf-8")
    except OSError as exc:
        return [Finding("error", "incubate-refused", f"incubate apply failed before all target writes completed: {exc}", target.rel_path)]

    findings = [
        Finding("info", "incubate-apply", "incubation note apply started"),
        _root_posture_finding(inventory),
        *_target_findings(target, apply=True),
        _note_posture_finding(target, apply=True, existed=existed),
        *_boundary_findings(),
        Finding(
            "info",
            "incubate-validation-posture",
            "run check after apply to verify the live operating root remains healthy; incubation notes are non-authority until promoted",
            target.rel_path,
        ),
    ]
    return findings


def _incubation_target(inventory: Inventory, request: IncubateRequest) -> IncubationTarget | None:
    slug = _safe_slug(request.topic)
    if not slug:
        return None
    rel_path = f"{INCUBATION_DIR_REL}/{slug}.md"
    return IncubationTarget(topic=request.topic, note=request.note, slug=slug, rel_path=rel_path, path=inventory.root / rel_path)


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


def _new_note_text(target: IncubationTarget) -> str:
    today = date.today().isoformat()
    return (
        "---\n"
        f'topic: "{_yaml_double_quoted_value(target.topic)}"\n'
        'status: "incubating"\n'
        f'created: "{today}"\n'
        f'updated: "{today}"\n'
        f'source: "{INCUBATION_SOURCE}"\n'
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
