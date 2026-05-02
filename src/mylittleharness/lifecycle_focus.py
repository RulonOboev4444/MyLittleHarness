from __future__ import annotations

import re


CURRENT_FOCUS_BEGIN = "<!-- BEGIN mylittleharness-current-focus v1 -->"
CURRENT_FOCUS_END = "<!-- END mylittleharness-current-focus v1 -->"
DEFAULT_ACTIVE_PLAN_REL = "project/implementation-plan.md"


def sync_current_focus_block(text: str) -> str:
    block = _render_current_focus_block(_frontmatter_scalars(text))
    replaced = _replace_existing_focus_block(text, block)
    if replaced is not None:
        return replaced
    return _insert_focus_block(text, block)


def _render_current_focus_block(fields: dict[str, str]) -> str:
    plan_status = fields.get("plan_status", "")
    active_plan = fields.get("active_plan", "") or DEFAULT_ACTIVE_PLAN_REL
    active_phase = fields.get("active_phase", "")
    phase_status = fields.get("phase_status", "")
    last_archived_plan = fields.get("last_archived_plan", "")
    lines = [CURRENT_FOCUS_BEGIN]
    if plan_status == "active":
        lines.append(f"Current focus: active implementation plan is open at `{active_plan}`.")
        if active_phase or phase_status:
            lines.append(
                "Continue from "
                f"active_phase `{active_phase or '<not recorded>'}` "
                f"with phase_status `{phase_status or '<not recorded>'}`."
            )
        else:
            lines.append("Continue from project-state lifecycle fields before inferring prose.")
    else:
        lines.append("Current focus: no active implementation plan is open.")
        if last_archived_plan:
            lines.append(f"Last archived plan: `{last_archived_plan}`.")
    lines.append("Project-state lifecycle frontmatter remains the continuation authority.")
    lines.append(CURRENT_FOCUS_END)
    return "\n".join(lines) + "\n"


def _replace_existing_focus_block(text: str, block: str) -> str | None:
    begin_index = text.rfind(CURRENT_FOCUS_BEGIN)
    end_index = text.rfind(CURRENT_FOCUS_END)
    if begin_index == -1 or end_index == -1 or end_index <= begin_index:
        return None
    end_after = end_index + len(CURRENT_FOCUS_END)
    if end_after < len(text) and text[end_after : end_after + 2] == "\r\n":
        end_after += 2
    elif end_after < len(text) and text[end_after : end_after + 1] == "\n":
        end_after += 1
    return text[:begin_index] + block + text[end_after:]


def _insert_focus_block(text: str, block: str) -> str:
    lines = text.splitlines(keepends=True)
    heading_index = _heading_index(lines, "Current Focus", level=2)
    if heading_index is not None:
        insert_index = heading_index + 1
        while insert_index < len(lines) and not lines[insert_index].strip():
            insert_index += 1
        section_end = _section_end_index(lines, heading_index, level=2)
        insert_index = _skip_legacy_focus_prelude(lines, insert_index, section_end)
        return "".join(lines[: heading_index + 1] + ["\n", block, "\n"] + lines[insert_index:])

    h1_index = _first_heading_index(lines, level=1)
    if h1_index is not None:
        insert_index = h1_index + 1
        while insert_index < len(lines) and not lines[insert_index].strip():
            insert_index += 1
        section = "## Current Focus\n\n" + block + "\n"
        return "".join(lines[: h1_index + 1] + ["\n", section] + lines[insert_index:])

    separator = "" if text.endswith(("\n", "\r")) else "\n"
    return text + separator + "\n## Current Focus\n\n" + block


def _heading_index(lines: list[str], title: str, level: int) -> int | None:
    marker = "#" * level
    for index, line in enumerate(lines):
        match = re.match(rf"^{re.escape(marker)}\s+(.+?)\s*$", line)
        if match and match.group(1).strip() == title:
            return index
    return None


def _first_heading_index(lines: list[str], level: int) -> int | None:
    marker = "#" * level
    for index, line in enumerate(lines):
        if re.match(rf"^{re.escape(marker)}\s+.+?\s*$", line):
            return index
    return None


def _section_end_index(lines: list[str], heading_index: int, level: int) -> int:
    for index in range(heading_index + 1, len(lines)):
        match = re.match(r"^(#{1,6})\s+.+?\s*$", lines[index])
        if match and len(match.group(1)) <= level:
            return index
    return len(lines)


def _skip_legacy_focus_prelude(lines: list[str], start_index: int, end_index: int) -> int:
    if start_index >= end_index:
        return start_index
    if not lines[start_index].lstrip().casefold().startswith("current focus:"):
        return start_index
    index = start_index
    while index < end_index and lines[index].strip():
        index += 1
    while index < end_index and not lines[index].strip():
        index += 1
    return index


def _frontmatter_scalars(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*?)\s*$", line)
        if match:
            fields[match.group(1)] = _strip_quotes(match.group(2))
    return fields


def _strip_quotes(value: str) -> str:
    raw = value.strip()
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    return raw
