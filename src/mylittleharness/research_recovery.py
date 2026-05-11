from __future__ import annotations

import re
from pathlib import Path

from .inventory import Inventory
from .models import Finding


DEEP_RESEARCH_RUBRIC_LIVE_ROUTE = "project/research/harness-deep-research-comparison-rubric.md"
DEEP_RESEARCH_RUBRIC_ARCHIVE_ROUTE = "project/archive/reference/research"
DEEP_RESEARCH_RUBRIC_ARCHIVE_ROUTE_HINT = (
    "project/archive/reference/research/**/harness-deep-research-comparison-rubric.md"
)
DEEP_RESEARCH_RUBRIC_RECOVERY_ROUTES = (
    "project/research",
    DEEP_RESEARCH_RUBRIC_ARCHIVE_ROUTE,
)

_RUBRIC_SIGNAL_MARKERS = (
    "deep research quality rubric",
    "deep-research-quality-rubric",
    "deep-research-rubric-recovery-route-gap",
    "harness-deep-research-comparison-rubric",
)
_RUBRIC_ARTIFACT_MARKERS = (
    "harness-deep-research-comparison-rubric",
    "deep research quality rubric",
    "quality gate for a useful answer",
    "standard output schema for deep research answers",
    "minimal matrix row",
    "prompt spine",
)
_RUBRIC_SCAN_RELS = (
    "project/roadmap.md",
)
_RUBRIC_SCAN_DIRS = (
    "project/plan-incubation",
    "project/archive/reference/incubation",
    "project/research",
)


def deep_research_rubric_recovery_findings(
    inventory: Inventory,
    *,
    force_signal: bool = False,
    include_present: bool = False,
) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []
    if not force_signal and not _has_deep_research_rubric_signal(inventory):
        return []

    present_routes = _present_deep_research_rubric_routes(inventory.root)
    source = _rubric_signal_source(inventory) or DEEP_RESEARCH_RUBRIC_LIVE_ROUTE
    if present_routes:
        if not include_present:
            return []
        return [
            Finding(
                "info",
                "deep-research-rubric-recovery-current",
                (
                    "Deep Research rubric artifact is recoverable from current research/reference route(s): "
                    f"{', '.join(present_routes[:3])}; use research-distill --dry-run only when a reviewed "
                    "non-authority synthesis is still needed"
                ),
                present_routes[0],
            )
        ]

    return [
        Finding(
            "warn",
            "deep-research-rubric-recovery-route-gap",
            (
                "Deep Research rubric cues are present, but no durable comparison-rubric artifact was found "
                f"at {DEEP_RESEARCH_RUBRIC_LIVE_ROUTE} or under {DEEP_RESEARCH_RUBRIC_ARCHIVE_ROUTE}/**. "
                "Bounded recovery: review the legacy or external rubric text, then preview "
                f"`mylittleharness --root <root> research-import --dry-run --title \"Deep Research Comparison Rubric\" "
                f"--text-file <reviewed-rubric.md> --target {DEEP_RESEARCH_RUBRIC_LIVE_ROUTE}` followed by "
                f"`mylittleharness --root <root> research-distill --dry-run --source {DEEP_RESEARCH_RUBRIC_LIVE_ROUTE}`; "
                "otherwise keep the result as a human-review blocker. These diagnostics are read-only and cannot "
                "import research, promote authority, move lifecycle, archive, stage, commit, or open a plan"
            ),
            source,
        ),
        Finding(
            "info",
            "deep-research-rubric-recovery-boundary",
            (
                "rubric recovery diagnostics are read-only and cannot import research, promote authority, move lifecycle, "
                "archive, stage, commit, or open a plan"
            ),
            source,
        ),
    ]


def deep_research_rubric_recovery_target_label(inventory: Inventory) -> str:
    present_routes = _present_deep_research_rubric_routes(inventory.root)
    if present_routes:
        return ", ".join(present_routes[:3])
    if inventory.root_kind == "live_operating_root" and _has_deep_research_rubric_signal(inventory):
        return f"{DEEP_RESEARCH_RUBRIC_LIVE_ROUTE} missing; {DEEP_RESEARCH_RUBRIC_ARCHIVE_ROUTE_HINT} missing"
    return ""


def deep_research_rubric_context_items(root: Path, *, max_items: int = 16) -> tuple[str, ...]:
    routes = _present_deep_research_rubric_routes(root)
    if not routes:
        return ()

    route = routes[0]
    path = root / route
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return (f"source-bound rubric artifact: {route}",)

    items = [f"{_rubric_context_label(route)}: {route}"]
    normalized = re.sub(r"\s+", " ", text.casefold())
    for framework in ("TAG/XML", "CAD", "CoVe", "Chutye/Reflex", "PICCO", "Quality Gate"):
        if framework.casefold() in normalized:
            items.append(f"required framework section: {framework}")

    for bullet in _section_bullets(text, "Deep Research Quality Rubric"):
        items.append(f"quality rubric: {bullet}")
    for bullet in _section_bullets(text, "Chutye/Reflex Fields")[:3]:
        items.append(f"chutye/reflex gate: {bullet}")
    for bullet in _section_bullets(text, "Boundaries")[:3]:
        items.append(f"boundary: {bullet}")

    return _unique_items(items)[:max_items]


def _has_deep_research_rubric_signal(inventory: Inventory) -> bool:
    for rel_path in _RUBRIC_SCAN_RELS:
        surface = inventory.surface_by_rel.get(rel_path)
        if surface and surface.exists and _contains_rubric_signal(surface.content):
            return True
    for base_rel in _RUBRIC_SCAN_DIRS:
        base = inventory.root / base_rel
        if not base.is_dir() or base.is_symlink():
            continue
        for path in sorted(base.rglob("*.md")):
            if path.is_symlink() or not path.is_file():
                continue
            if _path_contains_any(path, _RUBRIC_SIGNAL_MARKERS):
                return True
    return False


def _rubric_signal_source(inventory: Inventory) -> str:
    for rel_path in _RUBRIC_SCAN_RELS:
        surface = inventory.surface_by_rel.get(rel_path)
        if surface and surface.exists and _contains_rubric_signal(surface.content):
            return rel_path
    for base_rel in _RUBRIC_SCAN_DIRS:
        base = inventory.root / base_rel
        if not base.is_dir() or base.is_symlink():
            continue
        for path in sorted(base.rglob("*.md")):
            if path.is_symlink() or not path.is_file():
                continue
            if _path_contains_any(path, _RUBRIC_SIGNAL_MARKERS):
                return path.relative_to(inventory.root).as_posix()
    return ""


def _present_deep_research_rubric_routes(root: Path) -> list[str]:
    candidates = []
    live_path = root / DEEP_RESEARCH_RUBRIC_LIVE_ROUTE
    if _rubric_artifact_matches(live_path):
        candidates.append(DEEP_RESEARCH_RUBRIC_LIVE_ROUTE)

    archive_root = root / DEEP_RESEARCH_RUBRIC_ARCHIVE_ROUTE
    if archive_root.is_dir() and not archive_root.is_symlink():
        for path in sorted(archive_root.rglob("*.md")):
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if rel in candidates:
                continue
            if _rubric_artifact_matches(path):
                candidates.append(rel)
    return candidates


def _rubric_context_label(route: str) -> str:
    return "source-bound rubric artifact"


def _rubric_artifact_matches(path: Path) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    name = path.name.casefold()
    if "deep-research" in name and "rubric" in name:
        return True
    return _path_contains_any(path, _RUBRIC_ARTIFACT_MARKERS)


def _path_contains_any(path: Path, markers: tuple[str, ...]) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return _contains_any(text, markers)


def _contains_rubric_signal(text: str) -> bool:
    return _contains_any(text, _RUBRIC_SIGNAL_MARKERS)


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    normalized = re.sub(r"\s+", " ", text.casefold())
    return any(marker.casefold() in normalized for marker in markers)


def _section_bullets(text: str, heading: str) -> tuple[str, ...]:
    lines = text.splitlines()
    bullets: list[str] = []
    in_section = False
    heading_pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.IGNORECASE)
    for line in lines:
        stripped = line.strip()
        if in_section and stripped.startswith("## "):
            break
        if heading_pattern.match(stripped):
            in_section = True
            continue
        if not in_section or not stripped.startswith("- "):
            continue
        bullet = stripped[2:].strip().rstrip(".;")
        if bullet:
            bullets.append(bullet)
    return tuple(bullets)


def _unique_items(items: list[str]) -> tuple[str, ...]:
    seen = set()
    unique: list[str] = []
    for item in items:
        normalized = item.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(item)
    return tuple(unique)


__all__ = [
    "DEEP_RESEARCH_RUBRIC_ARCHIVE_ROUTE",
    "DEEP_RESEARCH_RUBRIC_ARCHIVE_ROUTE_HINT",
    "DEEP_RESEARCH_RUBRIC_LIVE_ROUTE",
    "DEEP_RESEARCH_RUBRIC_RECOVERY_ROUTES",
    "deep_research_rubric_context_items",
    "deep_research_rubric_recovery_findings",
    "deep_research_rubric_recovery_target_label",
]
