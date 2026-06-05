from __future__ import annotations

import hashlib
import re
import shutil
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .atomic_files import AtomicFileWrite, FileTransactionError, apply_file_transaction
from .inventory import Inventory
from .models import Finding
from .reporting import RouteWriteEvidence, route_write_findings
from .root_boundary import root_relative_path_conflict


ATTACHMENTS_DIR_REL = "project/attachments"
ATTACHMENT_IMPORT_SOURCE = "attachment-import cli"
ATTACHMENT_STATUS = "imported"
ATTACHMENT_AUTHORITY_NOTE = "binary is source evidence; this md card is metadata authority"
ATTACHMENT_NON_AUTHORITY_NOTE = (
    "attachment import records source evidence and sidecar metadata only; it cannot approve purchase, commit, "
    "roadmap status, plans, archive, staging, or lifecycle decisions."
)
SUPPORTED_ATTACHMENT_MIMES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".zip": "application/zip",
}
REQUIRED_ATTACHMENT_FIELDS = (
    "type",
    "kind",
    "status",
    "title",
    "source_file",
    "mime_type",
    "sha256",
    "size_bytes",
    "received_at",
    "source",
    "authority",
)
DOCS_DECISIONS = {"updated", "not-needed", "uncertain"}


@dataclass(frozen=True)
class AttachmentImportRequest:
    file: str
    kind: str
    topic: str
    title: str
    received_at: str = ""
    source_label: str = ""
    related_research: tuple[str, ...] = ()


@dataclass(frozen=True)
class AttachmentImportTarget:
    source_path: Path
    source_ext: str
    kind: str
    topic: str
    title: str
    received_at: str
    source_label: str
    mime_type: str
    sha256: str
    size_bytes: int
    target_dir_rel: str
    target_dir: Path
    source_file_name: str
    binary_rel_path: str
    binary_path: Path
    card_rel_path: str
    card_path: Path
    related_research: tuple[str, ...]


def make_attachment_import_request(
    file: str,
    *,
    kind: str,
    topic: str,
    title: str,
    received_at: str | None = None,
    source_label: str | None = None,
    related_research: tuple[str, ...] | None = None,
) -> AttachmentImportRequest:
    return AttachmentImportRequest(
        file=str(file or "").strip(),
        kind=str(kind or "").strip(),
        topic=str(topic or "").strip(),
        title=str(title or "").strip(),
        received_at=str(received_at or "").strip(),
        source_label=str(source_label or "").strip(),
        related_research=tuple(_normalize_rel(ref) for ref in (related_research or ()) if _normalize_rel(ref)),
    )


def attachment_import_dry_run_findings(inventory: Inventory, request: AttachmentImportRequest) -> list[Finding]:
    target = _attachment_import_target(inventory, request)
    errors = _attachment_import_preflight_errors(inventory, request, target)
    findings: list[Finding] = [
        Finding("info", "attachment-import-dry-run", "dry-run only; no binary or metadata card was written", ATTACHMENTS_DIR_REL),
    ]
    if target:
        rendered = _render_attachment_card(inventory.root, target)
        findings.extend(_target_findings(target, apply=False))
        findings.extend(route_write_findings("attachment-import-route-write", (_route_write(inventory.root, target.card_rel_path, rendered),), apply=False))
        findings.extend(_handoff_findings(inventory.root, target))
    findings.extend(errors)
    findings.append(_boundary_finding())
    return _dedupe_findings(findings)


def attachment_import_apply_findings(inventory: Inventory, request: AttachmentImportRequest) -> list[Finding]:
    target = _attachment_import_target(inventory, request)
    errors = _attachment_import_preflight_errors(inventory, request, target)
    if errors:
        findings = [
            Finding("error", "attachment-import-refused", "attachment-import --apply refused before any binary or metadata card was written", ATTACHMENTS_DIR_REL),
            *errors,
            _boundary_finding(),
        ]
        return _dedupe_findings(findings)
    assert target is not None

    rendered = _render_attachment_card(inventory.root, target)
    binary_cleanup_warnings: list[str] = []
    card_cleanup_warnings: tuple[str, ...] = ()
    tmp_binary_path = target.binary_path.with_name(f"{target.binary_path.name}.attachment-import.tmp")
    backup_path = target.card_path.with_name("artifact.md.attachment-import.bak")
    tmp_card_path = target.card_path.with_name("artifact.md.attachment-import.tmp")
    write_evidence = _route_write(inventory.root, target.card_rel_path, rendered)
    try:
        target.target_dir.mkdir(parents=True, exist_ok=True)
        with target.source_path.open("rb") as source, tmp_binary_path.open("wb") as tmp:
            shutil.copyfileobj(source, tmp)
        tmp_binary_path.replace(target.binary_path)
        card_cleanup_warnings = apply_file_transaction(
            (AtomicFileWrite(target.card_path, tmp_card_path, rendered, backup_path),),
            root=inventory.root,
        )
    except (OSError, FileTransactionError) as exc:
        _remove_if_exists(tmp_binary_path, binary_cleanup_warnings)
        _remove_if_exists(target.binary_path, binary_cleanup_warnings)
        message = f"attachment import apply failed: {exc}"
        if binary_cleanup_warnings:
            message = f"{message}; cleanup warnings: {'; '.join(binary_cleanup_warnings)}"
        return [
            Finding("error", "attachment-import-failed", message, target.card_rel_path),
            _boundary_finding(),
        ]

    findings = [
        Finding("info", "attachment-import-applied", f"copied binary and wrote metadata card: {target.card_rel_path}", target.card_rel_path),
        *_target_findings(target, apply=True),
        *route_write_findings("attachment-import-route-write", (write_evidence,), apply=True),
        *_handoff_findings(inventory.root, target),
        Finding("info", "attachment-import-validation-posture", "run check after apply to verify the attachment card hash, size, MIME metadata, and route references", target.card_rel_path),
        _boundary_finding(),
    ]
    for warning in card_cleanup_warnings:
        findings.append(Finding("warn", "attachment-import-backup-cleanup", warning, target.card_rel_path))
    return _dedupe_findings(findings)


def attachment_validation_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    for surface in inventory.present_surfaces:
        if surface.memory_route != "attachments" or Path(surface.rel_path).name != "artifact.md":
            continue
        findings.extend(_attachment_card_findings(surface.rel_path, surface.path, surface.frontmatter.data, surface.frontmatter.errors))
    if not findings:
        return []
    return _dedupe_findings(findings)


def _attachment_import_target(inventory: Inventory, request: AttachmentImportRequest) -> AttachmentImportTarget | None:
    source_path = Path(request.file).expanduser()
    try:
        source_path = source_path.resolve()
    except OSError:
        source_path = source_path.absolute()
    source_ext = source_path.suffix.casefold()
    kind_slug = _safe_slug(request.kind)
    topic_slug = _safe_slug(request.topic)
    title = _normalized_title(request.title)
    received_at = request.received_at or date.today().isoformat()
    if not source_ext or source_ext not in SUPPORTED_ATTACHMENT_MIMES or not kind_slug or not topic_slug or not title:
        return None
    source_file_name = f"original{source_ext}"
    kind_dir = _plural_kind_dir(kind_slug)
    target_dir_rel = f"{ATTACHMENTS_DIR_REL}/{kind_dir}/{received_at}-{topic_slug}"
    binary_rel_path = f"{target_dir_rel}/{source_file_name}"
    card_rel_path = f"{target_dir_rel}/artifact.md"
    return AttachmentImportTarget(
        source_path=source_path,
        source_ext=source_ext,
        kind=kind_slug,
        topic=topic_slug,
        title=title,
        received_at=received_at,
        source_label=request.source_label or ATTACHMENT_IMPORT_SOURCE,
        mime_type=SUPPORTED_ATTACHMENT_MIMES[source_ext],
        sha256=_sha256_file(source_path) if source_path.is_file() and not source_path.is_symlink() else "",
        size_bytes=source_path.stat().st_size if source_path.is_file() and not source_path.is_symlink() else -1,
        target_dir_rel=target_dir_rel,
        target_dir=inventory.root / target_dir_rel,
        source_file_name=source_file_name,
        binary_rel_path=binary_rel_path,
        binary_path=inventory.root / binary_rel_path,
        card_rel_path=card_rel_path,
        card_path=inventory.root / card_rel_path,
        related_research=request.related_research,
    )


def _attachment_import_preflight_errors(
    inventory: Inventory,
    request: AttachmentImportRequest,
    target: AttachmentImportTarget | None,
) -> list[Finding]:
    errors: list[Finding] = []
    if not request.file:
        errors.append(Finding("error", "attachment-import-refused", "--file is required and cannot be empty", ATTACHMENTS_DIR_REL))
    if not request.kind or not _safe_slug(request.kind):
        errors.append(Finding("error", "attachment-import-refused", "--kind is required and must produce a safe ASCII slug", ATTACHMENTS_DIR_REL))
    if not request.topic or not _safe_slug(request.topic):
        errors.append(Finding("error", "attachment-import-refused", "--topic is required and must produce a safe ASCII slug", ATTACHMENTS_DIR_REL))
    if not request.title or not _normalized_title(request.title):
        errors.append(Finding("error", "attachment-import-refused", "--title is required and cannot be empty", ATTACHMENTS_DIR_REL))
    if request.received_at:
        try:
            date.fromisoformat(request.received_at)
        except ValueError:
            errors.append(Finding("error", "attachment-import-refused", "--received-at must be an ISO date like 2026-06-02", ATTACHMENTS_DIR_REL))
    for ref in request.related_research:
        conflict = root_relative_path_conflict(ref)
        if conflict:
            errors.append(Finding("error", "attachment-import-refused", f"related research {conflict}", ref))
        elif not ref.startswith("project/research/") or not ref.endswith(".md"):
            errors.append(Finding("error", "attachment-import-refused", "related research must point to project/research/*.md", ref))

    if target is None:
        errors.append(Finding("error", "attachment-import-refused", "source extension or target slug is unsupported; supported extensions: .pdf, .docx, .xlsx, .png, .jpg, .jpeg, .zip", ATTACHMENTS_DIR_REL))
        return _dedupe_findings(errors)

    if not target.source_path.exists():
        errors.append(Finding("error", "attachment-import-refused", "source attachment file does not exist", str(target.source_path)))
    elif target.source_path.is_symlink():
        errors.append(Finding("error", "attachment-import-refused", "source attachment file is a symlink; import is refused", str(target.source_path)))
    elif not target.source_path.is_file():
        errors.append(Finding("error", "attachment-import-refused", "source attachment path is not a regular file", str(target.source_path)))
    if target.source_ext not in SUPPORTED_ATTACHMENT_MIMES:
        errors.append(Finding("error", "attachment-import-refused", f"unsupported attachment extension: {target.source_ext}", str(target.source_path)))
    if target.source_path == target.binary_path.resolve():
        errors.append(Finding("error", "attachment-import-refused", "source and target binary paths are identical", target.binary_rel_path))
    if _path_escapes_root(inventory.root, target.target_dir) or _path_escapes_root(inventory.root, target.binary_path) or _path_escapes_root(inventory.root, target.card_path):
        errors.append(Finding("error", "attachment-import-refused", "target attachment path escapes the target root", target.card_rel_path))

    if inventory.root_kind == "product_source_fixture":
        errors.append(Finding("error", "attachment-import-refused", "target is a product-source compatibility fixture; attachment-import --apply is refused", target.card_rel_path))
    elif inventory.root_kind == "fallback_or_archive":
        errors.append(Finding("error", "attachment-import-refused", "target is fallback/archive or generated-output evidence; attachment-import --apply is refused", target.card_rel_path))
    elif inventory.root_kind != "live_operating_root":
        errors.append(Finding("error", "attachment-import-refused", f"target root kind is {inventory.root_kind}; attachment import requires a live operating root", target.card_rel_path))

    state = inventory.state
    if state is None or not state.exists:
        errors.append(Finding("error", "attachment-import-refused", "project-state.md is missing", "project/project-state.md"))
    elif not state.frontmatter.has_frontmatter:
        errors.append(Finding("error", "attachment-import-refused", "project-state.md frontmatter is required for attachment import apply", state.rel_path))
    elif state.frontmatter.errors:
        errors.append(Finding("error", "attachment-import-refused", "project-state.md frontmatter is malformed", state.rel_path))
    elif not state.path.is_file():
        errors.append(Finding("error", "attachment-import-refused", "project-state.md is not a regular file", state.rel_path))
    elif state.path.is_symlink():
        errors.append(Finding("error", "attachment-import-refused", "project-state.md is a symlink", state.rel_path))

    for parent in _parents_between(inventory.root, target.target_dir):
        rel = parent.relative_to(inventory.root).as_posix()
        if parent.exists() and parent.is_symlink():
            errors.append(Finding("error", "attachment-import-refused", f"attachment target contains a symlink segment: {rel}", rel))
        elif parent.exists() and not parent.is_dir():
            errors.append(Finding("error", "attachment-import-refused", f"attachment target contains a non-directory segment: {rel}", rel))
    for rel_path, path, label in (
        (target.binary_rel_path, target.binary_path, "target binary"),
        (target.card_rel_path, target.card_path, "target metadata card"),
    ):
        if path.exists():
            if path.is_symlink():
                errors.append(Finding("error", "attachment-import-refused", f"{label} is a symlink; overwrite is refused", rel_path))
            elif not path.is_file():
                errors.append(Finding("error", "attachment-import-refused", f"{label} path exists but is not a regular file", rel_path))
            else:
                errors.append(Finding("error", "attachment-import-refused", f"{label} already exists; choose a different --topic or --received-at", rel_path))
    return _dedupe_findings(errors)


def _render_attachment_card(root: Path, target: AttachmentImportTarget) -> str:
    related_research = list(target.related_research)
    frontmatter = [
        "---",
        'type: "attachment"',
        f'kind: "{_yaml_double_quoted_value(target.kind)}"',
        f'status: "{ATTACHMENT_STATUS}"',
        f'title: "{_yaml_double_quoted_value(target.title)}"',
        f'source_file: "{_yaml_double_quoted_value(target.source_file_name)}"',
        f'mime_type: "{_yaml_double_quoted_value(target.mime_type)}"',
        f'sha256: "{target.sha256}"',
        f"size_bytes: {target.size_bytes}",
        f'received_at: "{_yaml_double_quoted_value(target.received_at)}"',
        f'source: "{_yaml_double_quoted_value(target.source_label)}"',
        *_yaml_list_lines("related_research", tuple(related_research), empty_as_inline=True),
        'docs_decision: "not-needed"',
        f'authority: "{_yaml_double_quoted_value(ATTACHMENT_AUTHORITY_NOTE)}"',
        "---",
    ]
    research_command = _research_handoff_command(root, target)
    lines = [
        *frontmatter,
        f"# {target.title}",
        "",
        ATTACHMENT_NON_AUTHORITY_NOTE,
        "",
        "## Evidence",
        "",
        f"- Binary source file: `{target.source_file_name}`",
        f"- MIME type: `{target.mime_type}`",
        f"- Size bytes: `{target.size_bytes}`",
        f"- SHA256: `{target.sha256}`",
        f"- Received at: `{target.received_at}`",
        f"- Source: `{target.source_label}`",
        "",
        "## Research Handoff",
        "",
        f"- Next safe command: `{research_command}`",
        "",
        "## Boundaries",
        "",
        "- The binary file is source evidence; this Markdown sidecar is metadata authority.",
        "- Text extraction, preview rendering, and later summaries are advisory only unless promoted by an explicit route.",
        "- Importing or referencing this attachment cannot approve purchase, commit, roadmap status, plans, archive, staging, or lifecycle decisions.",
        "",
    ]
    return "\n".join(lines)


def _attachment_card_findings(rel_path: str, path: Path, data: dict[str, object], frontmatter_errors: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    if frontmatter_errors:
        findings.append(Finding("error", "attachment-card-frontmatter", "attachment card frontmatter is malformed", rel_path))
        return findings
    for field in REQUIRED_ATTACHMENT_FIELDS:
        if data.get(field) in (None, "", []):
            findings.append(Finding("error", "attachment-card-field", f"missing required attachment field: {field}", rel_path))
    if data.get("type") != "attachment":
        findings.append(Finding("error", "attachment-card-field", 'type must be "attachment"', rel_path))
    if data.get("status") != ATTACHMENT_STATUS:
        findings.append(Finding("error", "attachment-card-field", f'status must be "{ATTACHMENT_STATUS}"', rel_path))
    docs_decision = str(data.get("docs_decision") or "")
    if docs_decision and docs_decision not in DOCS_DECISIONS:
        findings.append(Finding("warn", "attachment-card-docs-decision", "docs_decision should be updated, not-needed, or uncertain", rel_path))
    source_file = str(data.get("source_file") or "")
    source_conflict = root_relative_path_conflict(source_file, allow_current_dir=True) if source_file else "must be non-empty"
    if source_conflict:
        findings.append(Finding("error", "attachment-source-file", f"source_file {source_conflict}", rel_path))
        return findings
    binary_path = path.parent / source_file
    if _path_escapes_root(path.parent, binary_path):
        findings.append(Finding("error", "attachment-source-file", "source_file escapes the attachment directory", rel_path))
        return findings
    if not binary_path.exists():
        findings.append(Finding("error", "attachment-source-missing", f"attachment source file is missing: {source_file}", rel_path))
        return findings
    if binary_path.is_symlink():
        findings.append(Finding("error", "attachment-source-symlink", f"attachment source file is a symlink: {source_file}", rel_path))
        return findings
    if not binary_path.is_file():
        findings.append(Finding("error", "attachment-source-file", f"attachment source path is not a regular file: {source_file}", rel_path))
        return findings
    actual_sha = _sha256_file(binary_path)
    actual_size = binary_path.stat().st_size
    expected_sha = str(data.get("sha256") or "")
    if expected_sha and expected_sha != actual_sha:
        findings.append(Finding("error", "attachment-source-hash", f"sha256 mismatch for {source_file}", rel_path))
    expected_size = _int_value(data.get("size_bytes"))
    if expected_size is None:
        findings.append(Finding("error", "attachment-source-size", "size_bytes must be an integer", rel_path))
    elif expected_size != actual_size:
        findings.append(Finding("error", "attachment-source-size", f"size_bytes mismatch for {source_file}", rel_path))
    actual_mime = SUPPORTED_ATTACHMENT_MIMES.get(binary_path.suffix.casefold(), "")
    expected_mime = str(data.get("mime_type") or "")
    if actual_mime and expected_mime and expected_mime != actual_mime:
        findings.append(Finding("error", "attachment-source-mime", f"mime_type mismatch for {source_file}", rel_path))
    if not findings:
        findings.append(Finding("info", "attachment-card-ok", f"attachment metadata matches binary source file: {source_file}", rel_path))
    authority = str(data.get("authority") or "").casefold()
    if "binary is source evidence" not in authority or "metadata authority" not in authority:
        findings.append(Finding("warn", "attachment-card-authority", "authority should state that the binary is source evidence and the md card is metadata authority", rel_path))
    return findings


def _target_findings(target: AttachmentImportTarget, apply: bool) -> list[Finding]:
    verb = "copied binary" if apply else "would copy binary"
    return [
        Finding("info", "attachment-import-target", f"{verb}: {target.binary_rel_path}", target.binary_rel_path),
        Finding("info", "attachment-import-card", f"metadata card: {target.card_rel_path}", target.card_rel_path),
        Finding("info", "attachment-import-source-hash", f"sha256={target.sha256}; size_bytes={target.size_bytes}; mime_type={target.mime_type}", target.binary_rel_path),
    ]


def _handoff_findings(root: Path, target: AttachmentImportTarget) -> list[Finding]:
    return [
        Finding("info", "attachment-import-research-handoff", _research_handoff_command(root, target), target.card_rel_path),
    ]


def _boundary_finding() -> Finding:
    return Finding("info", "attachment-import-boundary", ATTACHMENT_NON_AUTHORITY_NOTE, ATTACHMENTS_DIR_REL)


def _research_handoff_command(root: Path, target: AttachmentImportTarget) -> str:
    root_text = root.as_posix()
    title = _yaml_double_quoted_value(target.title)
    return f'mylittleharness --root "{root_text}" research-import --dry-run --from-attachment "{target.card_rel_path}" --title "{title}"'


def _route_write(root: Path, rel_path: str, after_text: str) -> RouteWriteEvidence:
    target = root / rel_path
    before_text = target.read_text(encoding="utf-8") if target.is_file() else None
    return RouteWriteEvidence(rel_path, before_text, after_text)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_rel(value: object) -> str:
    return str(value or "").strip().replace("\\", "/")


def _normalized_title(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _safe_slug(value: object) -> str:
    ascii_text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def _plural_kind_dir(kind_slug: str) -> str:
    if kind_slug.endswith("s"):
        return kind_slug
    if kind_slug.endswith("y") and len(kind_slug) > 1:
        return f"{kind_slug[:-1]}ies"
    return f"{kind_slug}s"


def _yaml_double_quoted_value(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _yaml_list_lines(key: str, values: tuple[str, ...], *, empty_as_inline: bool = False) -> list[str]:
    if not values:
        return [f"{key}: []"] if empty_as_inline else [f"{key}:", '  - "none"']
    return [f"{key}:", *(f'  - "{_yaml_double_quoted_value(value)}"' for value in values)]


def _path_escapes_root(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return True
    return False


def _parents_between(root: Path, path: Path) -> tuple[Path, ...]:
    try:
        root = root.resolve()
        path = path.resolve()
    except OSError:
        return ()
    parents: list[Path] = []
    current = path.parent
    while current != root and current != current.parent:
        parents.append(current)
        current = current.parent
    parents.reverse()
    return tuple(parent for parent in parents if _path_within(root, parent))


def _path_within(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _remove_if_exists(path: Path, warnings: list[str]) -> None:
    try:
        if path.exists() and path.is_file() and not path.is_symlink():
            path.unlink()
    except OSError as exc:
        warnings.append(f"could not remove {path}: {exc}")


def _int_value(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _dedupe_findings(findings: list[Finding]) -> list[Finding]:
    result: list[Finding] = []
    seen: set[tuple[str, str, str, str | None]] = set()
    for finding in findings:
        key = (finding.severity, finding.code, str(finding.message), finding.source)
        if key in seen:
            continue
        seen.add(key)
        result.append(finding)
    return result


__all__ = [
    "ATTACHMENT_AUTHORITY_NOTE",
    "ATTACHMENTS_DIR_REL",
    "AttachmentImportRequest",
    "AttachmentImportTarget",
    "attachment_import_apply_findings",
    "attachment_import_dry_run_findings",
    "attachment_validation_findings",
    "make_attachment_import_request",
]
