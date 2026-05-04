from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO

from .models import Finding


def emit_text(text: str, stream: TextIO | None = None) -> None:
    target = sys.stdout if stream is None else stream
    payload = f"{text}\n"
    try:
        target.write(payload)
        target.flush()
    except UnicodeEncodeError:
        encoding = getattr(target, "encoding", None) or "ascii"
        fallback, fallback_encoding = _encoding_safe_payload(payload, encoding)
        buffer = getattr(target, "buffer", None)
        if buffer is not None:
            buffer.write(fallback)
            buffer.flush()
            return
        target.write(fallback.decode(fallback_encoding))
        target.flush()


def _encoding_safe_payload(text: str, encoding: str) -> tuple[bytes, str]:
    try:
        return text.encode(encoding, errors="backslashreplace"), encoding
    except LookupError:
        return text.encode("ascii", errors="backslashreplace"), "ascii"


def render_report(command: str, root: Path, result: str, sources: list[str], findings: list[Finding], suggestions: list[str]) -> str:
    lines: list[str] = [f"MyLittleHarness {command}", ""]
    lines.extend(["Root", f"- {root}", ""])
    lines.extend(["Result", f"- status: {result}", ""])
    lines.append("Sources")
    if sources:
        lines.extend(f"- {source}" for source in sources)
    else:
        lines.append("- none")
    lines.append("")
    lines.append("Findings")
    if findings:
        lines.extend(f"- {finding.render()}" for finding in findings)
    else:
        lines.append("- [INFO] none: no findings")
    lines.append("")
    lines.append("Suggestions")
    if suggestions:
        lines.extend(f"- {suggestion}" for suggestion in suggestions)
    else:
        lines.append("- No suggestions.")
    return "\n".join(lines)


def render_intelligence_report(
    root: Path,
    result: str,
    sources: list[str],
    sections: list[tuple[str, list[Finding]]],
    suggestions: list[str],
    compact_sources: bool = False,
) -> str:
    lines: list[str] = ["MyLittleHarness intelligence", ""]
    lines.extend(["Root", f"- {root}", ""])
    lines.extend(["Result", f"- status: {result}", ""])
    lines.append("Sources")
    if compact_sources and sources:
        lines.append(f"- {len(sources)} inventory sources discovered; rerun without --focus for the full source list")
    elif sources:
        lines.extend(f"- {source}" for source in sources)
    else:
        lines.append("- none")
    lines.append("")
    for section_name, findings in sections:
        lines.append(section_name)
        if findings:
            lines.extend(f"- {finding.render()}" for finding in findings)
        else:
            lines.append("- [INFO] none: no findings")
        lines.append("")
    lines.append("Suggestions")
    if suggestions:
        lines.extend(f"- {suggestion}" for suggestion in suggestions)
    else:
        lines.append("- No suggestions.")
    return "\n".join(lines)


def render_sectioned_report(
    command: str,
    root: Path,
    result: str,
    sources: list[str],
    sections: list[tuple[str, list[Finding]]],
    suggestions: list[str],
) -> str:
    lines: list[str] = [f"MyLittleHarness {command}", ""]
    lines.extend(["Root", f"- {root}", ""])
    lines.extend(["Result", f"- status: {result}", ""])
    lines.append("Sources")
    if sources:
        lines.extend(f"- {source}" for source in sources)
    else:
        lines.append("- none")
    lines.append("")
    for section_name, findings in sections:
        lines.append(section_name)
        if findings:
            lines.extend(f"- {finding.render()}" for finding in findings)
        else:
            lines.append("- [INFO] none: no findings")
        lines.append("")
    lines.append("Suggestions")
    if suggestions:
        lines.extend(f"- {suggestion}" for suggestion in suggestions)
    else:
        lines.append("- No suggestions.")
    return "\n".join(lines)
