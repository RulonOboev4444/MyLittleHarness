from __future__ import annotations

from typing import Any


TERMINAL_HISTORY_STUB_MARKERS = (
    "terminal relationship stub",
    "historical relationship recovery only",
    "original archived plan body was not recoverable",
    "original archive body was not recoverable",
    "without recreating missing archive content",
    "no archive recreation",
    "preserve the historical dependency edge",
    "preserve historical dependency edge",
)


def roadmap_item_is_terminal_history_stub(item: Any) -> bool:
    fields = getattr(item, "fields", None)
    title = str(getattr(item, "title", ""))
    if fields is None and isinstance(item, dict):
        fields = item
    if not isinstance(fields, dict):
        return False
    if _field_scalar(fields.get("archived_plan")):
        return False
    text = _item_text(title, fields)
    return any(marker in text for marker in TERMINAL_HISTORY_STUB_MARKERS)


def _item_text(title: str, fields: dict[str, object]) -> str:
    text_parts = [title]
    for value in fields.values():
        if isinstance(value, list):
            text_parts.extend(str(part) for part in value)
        else:
            text_parts.append(str(value))
    return "\n".join(text_parts).casefold()


def _field_scalar(value: object) -> str:
    if value in (None, "", [], ()):
        return ""
    if isinstance(value, list):
        return str(value[0]).strip() if value else ""
    return str(value).strip()
