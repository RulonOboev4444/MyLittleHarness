from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class AtomicFileWrite:
    target_path: Path
    tmp_path: Path
    text: str
    backup_path: Path


@dataclass(frozen=True)
class AtomicFileDelete:
    target_path: Path
    backup_path: Path


@dataclass(frozen=True)
class _AppliedOperation:
    operation: AtomicFileWrite | AtomicFileDelete
    had_original: bool


class FileTransactionError(OSError):
    pass


def apply_file_transaction(operations: Iterable[AtomicFileWrite | AtomicFileDelete]) -> tuple[str, ...]:
    planned = tuple(operations)
    if not planned:
        return ()

    _validate_transaction_paths(planned)

    created_dirs: list[Path] = []
    written_tmps: list[Path] = []
    applied: list[_AppliedOperation] = []
    try:
        for operation in planned:
            if not isinstance(operation, AtomicFileWrite):
                continue
            created_dirs.extend(_missing_parent_dirs(operation.tmp_path))
            operation.tmp_path.parent.mkdir(parents=True, exist_ok=True)
            _write_text_exact(operation.tmp_path, operation.text)
            written_tmps.append(operation.tmp_path)

        for operation in planned:
            had_original = operation.target_path.exists()
            if had_original:
                _replace_path(operation.target_path, operation.backup_path)
            applied.append(_AppliedOperation(operation, had_original))
            if isinstance(operation, AtomicFileWrite):
                _replace_path(operation.tmp_path, operation.target_path)
                _remove_known_path(written_tmps, operation.tmp_path)
    except OSError as exc:
        rollback_errors = _rollback_applied_operations(applied)
        cleanup_errors = _cleanup_temporary_writes(written_tmps)
        cleanup_errors.extend(_cleanup_created_dirs(created_dirs))
        raise FileTransactionError(_transaction_failure_message(exc, rollback_errors + cleanup_errors)) from exc

    return tuple(_cleanup_success_backups(applied))


def _validate_transaction_paths(operations: tuple[AtomicFileWrite | AtomicFileDelete, ...]) -> None:
    targets = [operation.target_path for operation in operations]
    if len(set(targets)) != len(targets):
        raise FileTransactionError("file transaction target paths must be unique")
    backups = [operation.backup_path for operation in operations]
    if len(set(backups)) != len(backups):
        raise FileTransactionError("file transaction backup paths must be unique")
    tmps = [operation.tmp_path for operation in operations if isinstance(operation, AtomicFileWrite)]
    if len(set(tmps)) != len(tmps):
        raise FileTransactionError("file transaction temporary paths must be unique")

    protected = set(targets)
    protected.update(operation.backup_path for operation in operations)
    for operation in operations:
        if operation.backup_path in targets:
            raise FileTransactionError(f"backup path would overwrite another transaction target: {operation.backup_path}")
        if operation.backup_path.exists():
            raise FileTransactionError(f"transaction backup path already exists: {operation.backup_path}")
        if isinstance(operation, AtomicFileWrite):
            if operation.tmp_path in protected:
                raise FileTransactionError(f"temporary write path overlaps transaction target or backup: {operation.tmp_path}")
            if operation.tmp_path.exists():
                raise FileTransactionError(f"temporary write path already exists: {operation.tmp_path}")


def _rollback_applied_operations(applied: list[_AppliedOperation]) -> list[str]:
    errors: list[str] = []
    for applied_operation in reversed(applied):
        operation = applied_operation.operation
        try:
            if isinstance(operation, AtomicFileWrite) and operation.target_path.exists():
                _unlink_path(operation.target_path)
            if applied_operation.had_original and operation.backup_path.exists():
                _replace_path(operation.backup_path, operation.target_path)
        except OSError as rollback_exc:
            errors.append(f"{operation.target_path}: {rollback_exc}")
    return errors


def _cleanup_temporary_writes(paths: list[Path]) -> list[str]:
    errors: list[str] = []
    for path in tuple(paths):
        try:
            if path.exists():
                _unlink_path(path)
        except OSError as cleanup_exc:
            errors.append(f"{path}: {cleanup_exc}")
    paths.clear()
    return errors


def _cleanup_created_dirs(paths: list[Path]) -> list[str]:
    errors: list[str] = []
    for path in sorted(set(paths), key=lambda item: len(item.parts), reverse=True):
        try:
            path.rmdir()
        except FileNotFoundError:
            pass
        except OSError as cleanup_exc:
            errors.append(f"{path}: {cleanup_exc}")
    paths.clear()
    return errors


def _cleanup_success_backups(applied: list[_AppliedOperation]) -> list[str]:
    warnings: list[str] = []
    for applied_operation in applied:
        backup = applied_operation.operation.backup_path
        if not backup.exists():
            continue
        try:
            _unlink_path(backup)
        except OSError as cleanup_exc:
            warnings.append(f"temporary backup remains at {backup}: {cleanup_exc}")
    return warnings


def _transaction_failure_message(exc: OSError, recovery_errors: list[str]) -> str:
    if recovery_errors:
        details = "; ".join(recovery_errors)
        return f"{exc}; attempted rollback but manual recovery may be needed: {details}"
    return f"{exc}; rolled back completed target writes"


def _remove_known_path(paths: list[Path], path: Path) -> None:
    try:
        paths.remove(path)
    except ValueError:
        pass


def _missing_parent_dirs(path: Path) -> list[Path]:
    missing: list[Path] = []
    parent = path.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    return missing


def _replace_path(source: Path, target: Path) -> None:
    source.replace(target)


def _unlink_path(path: Path) -> None:
    path.unlink()


def _write_text_exact(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))
