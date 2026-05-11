from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path


GIT_TIMEOUT_SECONDS = 5
CHANGED_SAMPLE_LIMIT = 10
TRAILER_SAMPLE_LIMIT = 10


@dataclass(frozen=True)
class VcsChangedPath:
    status: str
    path: str


@dataclass(frozen=True)
class VcsPosture:
    root: Path
    git_available: bool
    is_worktree: bool
    state: str
    top_level: str | None = None
    changed_count: int = 0
    changed_samples: tuple[VcsChangedPath, ...] = ()
    detail: str | None = None


@dataclass(frozen=True)
class VcsTrailer:
    key: str
    value: str


@dataclass(frozen=True)
class VcsTrailerParseResult:
    root: Path
    git_available: bool
    parsed: bool
    trailers: tuple[VcsTrailer, ...] = ()
    detail: str | None = None


GitRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def probe_vcs(root: Path, runner: GitRunner | None = None) -> VcsPosture:
    root = root.expanduser().resolve()
    rev_parse = _run_git(root, ("rev-parse", "--is-inside-work-tree"), runner)
    if isinstance(rev_parse, str):
        return VcsPosture(root=root, git_available=False, is_worktree=False, state="unknown", detail=rev_parse)
    if rev_parse.returncode != 0:
        return VcsPosture(
            root=root,
            git_available=True,
            is_worktree=False,
            state="non-git",
            detail=_first_output_line(rev_parse) or f"git exited {rev_parse.returncode}",
        )
    if rev_parse.stdout.strip().casefold() != "true":
        return VcsPosture(root=root, git_available=True, is_worktree=False, state="non-git", detail="not inside a Git worktree")

    top_level = _git_top_level(root, runner)
    status = _run_git(root, ("status", "--porcelain=v1"), runner)
    if isinstance(status, str):
        return VcsPosture(root=root, git_available=False, is_worktree=True, state="unknown", top_level=top_level, detail=status)
    if status.returncode != 0:
        return VcsPosture(
            root=root,
            git_available=True,
            is_worktree=True,
            state="unknown",
            top_level=top_level,
            detail=_first_output_line(status) or f"git status exited {status.returncode}",
        )

    entries = _parse_porcelain(status.stdout)
    state = "dirty" if entries else "clean"
    return VcsPosture(
        root=root,
        git_available=True,
        is_worktree=True,
        state=state,
        top_level=top_level,
        changed_count=len(entries),
        changed_samples=tuple(entries[:CHANGED_SAMPLE_LIMIT]),
    )


def parse_head_commit_trailers(root: Path) -> VcsTrailerParseResult:
    root = root.expanduser().resolve()
    message = _run_git(root, ("log", "-1", "--format=%B"), runner=None)
    if isinstance(message, str):
        return VcsTrailerParseResult(root=root, git_available=False, parsed=False, detail=message)
    if message.returncode != 0:
        return VcsTrailerParseResult(
            root=root,
            git_available=True,
            parsed=False,
            detail=_first_output_line(message) or f"git log exited {message.returncode}",
        )

    parsed = _run_git_with_input(root, ("interpret-trailers", "--parse"), message.stdout)
    if isinstance(parsed, str):
        return VcsTrailerParseResult(root=root, git_available=False, parsed=False, detail=parsed)
    if parsed.returncode != 0:
        return VcsTrailerParseResult(
            root=root,
            git_available=True,
            parsed=False,
            detail=_first_output_line(parsed) or f"git interpret-trailers exited {parsed.returncode}",
        )
    return VcsTrailerParseResult(
        root=root,
        git_available=True,
        parsed=True,
        trailers=tuple(_parse_trailer_lines(parsed.stdout)[:TRAILER_SAMPLE_LIMIT]),
    )


def _git_top_level(root: Path, runner: GitRunner | None) -> str | None:
    result = _run_git(root, ("rev-parse", "--show-toplevel"), runner)
    if isinstance(result, str) or result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _run_git(root: Path, args: Sequence[str], runner: GitRunner | None) -> subprocess.CompletedProcess[str] | str:
    command = ("git", "-C", str(root), *args)
    try:
        if runner:
            return runner(command)
        return subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        return f"git executable unavailable: {exc}"
    except subprocess.TimeoutExpired:
        return f"git command timed out after {GIT_TIMEOUT_SECONDS}s"
    except OSError as exc:
        return f"git command failed: {exc}"


def _run_git_with_input(root: Path, args: Sequence[str], stdin: str) -> subprocess.CompletedProcess[str] | str:
    command = ("git", "-C", str(root), *args)
    try:
        return subprocess.run(
            list(command),
            input=stdin,
            check=False,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        return f"git executable unavailable: {exc}"
    except subprocess.TimeoutExpired:
        return f"git command timed out after {GIT_TIMEOUT_SECONDS}s"
    except OSError as exc:
        return f"git command failed: {exc}"


def _first_output_line(result: subprocess.CompletedProcess[str]) -> str:
    output = (result.stderr or result.stdout or "").strip()
    return output.splitlines()[0] if output else ""


def _parse_porcelain(text: str) -> list[VcsChangedPath]:
    entries: list[VcsChangedPath] = []
    for raw_line in text.splitlines():
        if not raw_line:
            continue
        status = raw_line[:2].strip() or "??"
        path = raw_line[3:].strip() if len(raw_line) > 3 else raw_line.strip()
        entries.append(VcsChangedPath(status=status, path=path))
    return entries


def _parse_trailer_lines(text: str) -> list[VcsTrailer]:
    trailers: list[VcsTrailer] = []
    for raw_line in text.splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        key = key.strip()
        value = " ".join(value.split())
        if key and value:
            trailers.append(VcsTrailer(key=key, value=value))
    return trailers
