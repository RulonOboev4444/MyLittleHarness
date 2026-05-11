from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass

from .inventory import Surface
from .models import Finding


MAX_CANDIDATES_PER_GROUP = 5
CLOSEOUT_FIELD_NAMES = ("docs_decision", "state_writeback", "verification", "commit_decision")

_PROSPECTIVE_CONTEXT_PATTERNS = (
    r"\bif implemented\b",
    r"\blater scoped plan\b",
    r"\bfuture\b",
    r"\bdeferred\b",
    r"\bremains deferred\b",
)


@dataclass(frozen=True)
class EvidenceCue:
    kind: str
    label: str
    source: str
    line: int
    preview: str
    strength: str = "candidate"

    @property
    def identity(self) -> str:
        seed = f"{self.kind}|{self.source}|{self.line}|{self.preview}"
        return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


def find_cues(surface: Surface, kind: str, label: str, patterns: Iterable[str], strength: str = "candidate") -> list[EvidenceCue]:
    regexes = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    cues: list[EvidenceCue] = []
    for line_number, line in enumerate(surface.content.splitlines(), start=1):
        if any(regex.search(line) for regex in regexes):
            cues.append(
                EvidenceCue(
                    kind=kind,
                    label=label,
                    source=surface.rel_path,
                    line=line_number,
                    preview=normalized_preview(line),
                    strength=strength,
                )
            )
    return cues


def closeout_field_cues(surface: Surface, field: str) -> tuple[list[EvidenceCue], list[EvidenceCue]]:
    label = f"{field} candidate"
    concrete = _concrete_closeout_field_cues(surface, field, label)
    broad: list[EvidenceCue] = []
    if not concrete:
        broad = find_cues(surface, field, label, _closeout_field_broad_patterns(field), strength="context")
    return concrete, broad


def cue_findings(code: str, label: str, cues: list[EvidenceCue], limit: int = MAX_CANDIDATES_PER_GROUP) -> list[Finding]:
    findings = [
        Finding(
            "info",
            code,
            (
                f"candidate evidence cue only: {label}: {cue.preview}; "
                f"identity={cue.identity}; kind={cue.kind}; source={cue.source}:{cue.line}"
            ),
            cue.source,
            cue.line,
        )
        for cue in cues[:limit]
    ]
    if len(cues) > limit:
        findings.append(Finding("info", code, f"candidate evidence cue only: {label} truncated at {limit} deterministic matches", cues[0].source))
    return findings


def normalized_preview(line: str, limit: int = 160) -> str:
    compact = re.sub(r"\s+", " ", line.strip())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3]}..."


def _concrete_closeout_field_cues(surface: Surface, field: str, label: str) -> list[EvidenceCue]:
    cues: list[EvidenceCue] = []
    for line_number, line in enumerate(surface.content.splitlines(), start=1):
        if _is_concrete_closeout_field_line(field, line):
            cues.append(
                EvidenceCue(
                    kind=field,
                    label=label,
                    source=surface.rel_path,
                    line=line_number,
                    preview=normalized_preview(line),
                    strength="concrete",
                )
            )
    return cues


def _is_concrete_closeout_field_line(field: str, line: str) -> bool:
    explicit_patterns = _closeout_field_explicit_patterns(field)
    if any(re.search(pattern, line, re.IGNORECASE) for pattern in explicit_patterns):
        return True
    if _is_prospective_context(line):
        return False
    return any(re.search(pattern, line, re.IGNORECASE) for pattern in _closeout_field_result_patterns(field))


def _is_prospective_context(line: str) -> bool:
    return any(re.search(pattern, line, re.IGNORECASE) for pattern in _PROSPECTIVE_CONTEXT_PATTERNS)


def _closeout_field_explicit_patterns(field: str) -> tuple[str, ...]:
    if field == "verification":
        return (
            r"^[-*]\s*`?verification`?\s*:",
            r"^[-*]\s*`?validation`?\s*:",
            r"^#{1,6}\s*(verification|validation)\s*:?\s*$",
        )
    words = field.replace("_", " ")
    return (
        rf"^[-*]\s*`?{re.escape(field)}`?\s*:",
        rf"^[-*]\s*{re.escape(words)}\s*:",
        rf"^#{{1,6}}\s*{re.escape(field)}\s*:?\s*$",
        rf"^#{{1,6}}\s*{re.escape(words)}\s*:?\s*$",
    )


def _closeout_field_result_patterns(field: str) -> tuple[str, ...]:
    if field == "verification":
        return (
            r"^[-*]\s*verification (records?|passed|complete|completeness|methods?|results?|skipped)\b",
            r"^[-*]\s*validation (passed|methods?|results?|smokes?|suite|records?)\b",
            r"^\s*verification (records?|passed|complete|completeness|methods?|results?|skipped)\b",
            r"^\s*validation (passed|methods?|results?|smokes?|suite|records?)\b",
        )
    words = field.replace("_", " ")
    return (
        rf"\b{re.escape(words)} (is|was|=)",
    )


def _closeout_field_broad_patterns(field: str) -> tuple[str, ...]:
    if field == "verification":
        return (r"`verification`", r"`validation`", r"\bverification\b", r"\bvalidation\b")
    words = field.replace("_", " ")
    return (rf"`{re.escape(field)}`", rf"\b{re.escape(field)}\b", rf"\b{re.escape(words)}\b")
