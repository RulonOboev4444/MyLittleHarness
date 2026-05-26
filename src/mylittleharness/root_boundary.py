from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


LIVE_OPERATING_ROOT = "live_operating_root"
PRODUCT_SOURCE_FIXTURE = "product_source_fixture"
FALLBACK_OR_ARCHIVE = "fallback_or_archive"
AMBIGUOUS_ROOT = "ambiguous"


@dataclass(frozen=True)
class BoundaryViolation:
    code: str
    message: str
    path: Path
    rel_path: str


def absolute_path(path: Path | str, *, base: Path | str | None = None) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    root = Path(base).expanduser() if base is not None else Path.cwd()
    return root / candidate


def first_symlink_prefix(root: Path | str, path: Path | str) -> Path | None:
    root_path = absolute_path(root)
    candidate = absolute_path(path, base=root_path)
    try:
        relative = candidate.relative_to(root_path)
    except ValueError:
        return None
    current = root_path
    for part in relative.parts:
        current = current / part
        try:
            if current.is_symlink():
                return current
        except OSError:
            return current
    return None


def path_resolves_within_root(root: Path | str, path: Path | str) -> bool:
    root_path = absolute_path(root)
    candidate = absolute_path(path, base=root_path)
    try:
        candidate.resolve(strict=False).relative_to(root_path.resolve(strict=False))
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def same_resolved_path(first: Path | str, second: Path | str) -> bool:
    try:
        return str(absolute_path(first).resolve()).casefold() == str(absolute_path(second).resolve()).casefold()
    except (OSError, RuntimeError):
        first_text = str(first).replace("/", "\\").rstrip("\\").casefold()
        second_text = str(second).replace("/", "\\").rstrip("\\").casefold()
        return first_text == second_text


def source_path_boundary_violation(root: Path | str, path: Path | str, *, label: str = "source path") -> BoundaryViolation | None:
    root_path = absolute_path(root)
    candidate = absolute_path(path, base=root_path)
    if root_path.is_symlink():
        return BoundaryViolation(
            code="root-symlink",
            message=f"{label} root is a symlink: {root_path}",
            path=candidate,
            rel_path=root_path.as_posix(),
        )
    symlink_prefix = first_symlink_prefix(root_path, candidate)
    if symlink_prefix is not None:
        rel_path = root_relative_display(root_path, symlink_prefix)
        return BoundaryViolation(
            code="symlink",
            message=f"{label} crosses symlink inside root: {rel_path}",
            path=candidate,
            rel_path=rel_path,
        )
    if not path_resolves_within_root(root_path, candidate):
        rel_path = root_relative_display(root_path, candidate)
        return BoundaryViolation(
            code="outside-root",
            message=f"{label} resolves outside root: {rel_path}",
            path=candidate,
            rel_path=rel_path,
        )
    return None


def root_relative_display(root: Path | str, path: Path | str) -> str:
    root_path = absolute_path(root)
    candidate = absolute_path(path, base=root_path)
    try:
        return candidate.relative_to(root_path).as_posix()
    except ValueError:
        return str(candidate)
