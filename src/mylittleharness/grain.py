from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from .inventory import Inventory, Surface
from .models import Finding
from .parsing import Heading, extract_headings, parse_frontmatter


REQUIRED_PLAN_FRONTMATTER = (
    "plan_id",
    "status",
    "active_phase",
    "phase_status",
    "docs_decision",
    "execution_policy",
    "auto_continue",
    "stop_conditions",
    "closeout_boundary",
)
PHASE_REVIEW_THRESHOLD = 4
COVERED_ITEM_REVIEW_THRESHOLD = 4
TARGET_ARTIFACT_REVIEW_THRESHOLD = 8
PLAN_LINE_REVIEW_THRESHOLD = 500
VERIFICATION_SUMMARY_REVIEW_CHARS = 240
CALIBRATION_SAMPLE_LIMIT = 8


@dataclass(frozen=True)
class PlanGrainStats:
    rel_path: str
    line_count: int
    char_count: int
    frontmatter: dict[str, object]
    phase_count: int
    covered_roadmap_items: tuple[str, ...]
    target_artifacts: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    auto_continue: bool
    execution_policy: str
    docs_decision: str
    write_scope_lines: tuple[str, ...]
    verification_lines: tuple[str, ...]
    state_transfer_present: bool
    closeout_fact_count: int
    raw_log_markers: int


@dataclass(frozen=True)
class RoadmapGrainItem:
    item_id: str
    title: str
    fields: dict[str, object]
    line: int


def grain_findings(inventory: Inventory) -> list[Finding]:
    findings = [
        Finding(
            "info",
            "grain-read-only",
            "grain diagnostics are report-only sizing and hygiene signals; they write no files and approve no lifecycle movement",
        )
    ]
    if inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                "info",
                "grain-scope",
                f"grain diagnostics are live-operating-root scoped; root kind is {inventory.root_kind}",
            )
        )
        return findings

    active_plan = inventory.active_plan_surface
    if active_plan and active_plan.exists:
        active_stats = _plan_stats(active_plan.rel_path, active_plan.content)
        findings.extend(_active_plan_grain_findings(active_stats))
    else:
        active_stats = None
        findings.append(Finding("info", "grain-active-plan", "no active plan is present; plan-grain diagnostics skipped"))

    findings.extend(_roadmap_grain_findings(inventory, active_stats))
    findings.extend(_calibration_findings(inventory))
    findings.append(
        Finding(
            "info",
            "grain-boundary",
            "grain output may guide plan sizing, roadmap hygiene, and future threshold tuning, but remains advisory until promoted into specs or explicit write rails",
        )
    )
    return findings


def _active_plan_grain_findings(stats: PlanGrainStats) -> list[Finding]:
    findings: list[Finding] = []
    missing = [key for key in REQUIRED_PLAN_FRONTMATTER if not _has_value(stats.frontmatter.get(key))]
    if missing:
        findings.append(
            Finding(
                "warn",
                "grain-plan-frontmatter",
                f"active plan is missing grain-relevant frontmatter fields: {', '.join(missing)}",
                stats.rel_path,
            )
        )

    if stats.frontmatter.get("related_roadmap_item") and not stats.covered_roadmap_items:
        findings.append(
            Finding(
                "warn",
                "grain-plan-mapping",
                "active plan has a roadmap relationship but no covered_roadmap_items for slice-size review",
                stats.rel_path,
            )
        )

    if not stats.target_artifacts:
        findings.append(
            Finding(
                "info",
                "grain-plan-target-artifacts",
                "active plan target_artifacts is empty; treat this as a sizing signal, not a refusal gate",
                stats.rel_path,
            )
        )

    if _write_scope_is_vague(stats.write_scope_lines):
        findings.append(
            Finding(
                "warn",
                "grain-plan-write-scope",
                "active plan write scope is missing or still placeholder/vague; exact file ownership is needed before confident execution",
                stats.rel_path,
            )
        )

    if _verification_is_vague(stats.verification_lines):
        findings.append(
            Finding(
                "warn",
                "grain-plan-verification",
                "active plan verification gates are missing or generic; deterministic success signals should be named",
                stats.rel_path,
            )
        )

    if stats.auto_continue and len(stats.stop_conditions) < 3:
        findings.append(
            Finding(
                "warn",
                "grain-plan-auto-continue",
                "auto_continue is true without enough repo-visible stop_conditions for safe continuation",
                stats.rel_path,
            )
        )

    pressure = _pressure_signals(stats)
    if pressure:
        findings.append(
            Finding(
                "warn",
                "grain-plan-giant",
                "active plan may be too broad: " + "; ".join(pressure),
                stats.rel_path,
            )
        )
    elif len(stats.covered_roadmap_items) <= 1 and stats.phase_count <= 1 and len(stats.target_artifacts) <= 1:
        findings.append(
            Finding(
                "info",
                "grain-plan-atomic",
                "active plan is a possible over-atomic slice: <=1 roadmap item, <=1 phase, and <=1 target artifact",
                stats.rel_path,
            )
        )

    if stats.raw_log_markers:
        findings.append(
            Finding(
                "warn",
                "grain-plan-raw-log",
                f"active plan contains {stats.raw_log_markers} raw command-log marker(s); hot plans should keep compact evidence, not transcript dumps",
                stats.rel_path,
            )
        )
    return findings


def _roadmap_grain_findings(inventory: Inventory, active_stats: PlanGrainStats | None) -> list[Finding]:
    roadmap = inventory.surface_by_rel.get("project/roadmap.md")
    if not roadmap or not roadmap.exists:
        return [Finding("info", "grain-roadmap", "no project/roadmap.md present; roadmap grain diagnostics skipped")]

    items, errors = _roadmap_items(roadmap)
    if errors:
        return errors

    findings: list[Finding] = []
    by_id = {item.item_id: item for item in items}
    if active_stats:
        missing_covered = [item_id for item_id in active_stats.covered_roadmap_items if item_id not in by_id]
        if missing_covered:
            findings.append(
                Finding(
                    "warn",
                    "grain-roadmap-covered-missing",
                    f"active plan covered_roadmap_items are missing from project/roadmap.md: {', '.join(missing_covered)}",
                    roadmap.rel_path,
                )
            )

    detailed_done = [item for item in items if _field_scalar(item.fields, "status") == "done"]
    if len(detailed_done) > 4:
        findings.append(
            Finding(
                "warn",
                "grain-roadmap-done-tail",
                f"roadmap keeps {len(detailed_done)} detailed done item blocks; consider live-tail compaction only after durable closeout evidence",
                roadmap.rel_path,
            )
        )

    targetless_review_items = []
    for item in items:
        status = _field_scalar(item.fields, "status")
        verification_summary = _field_scalar(item.fields, "verification_summary")
        archived_plan = _field_scalar(item.fields, "archived_plan")
        related_plan = _field_scalar(item.fields, "related_plan")
        if status == "done" and not archived_plan:
            findings.append(
                Finding(
                    "warn",
                    "grain-roadmap-done-missing-archive",
                    f"done roadmap item {item.item_id!r} lacks archived_plan",
                    roadmap.rel_path,
                    item.line,
                )
            )
        if status == "done" and not verification_summary:
            findings.append(
                Finding(
                    "warn",
                    "grain-roadmap-done-missing-evidence",
                    f"done roadmap item {item.item_id!r} lacks verification_summary",
                    roadmap.rel_path,
                    item.line,
                )
            )
        if status == "done" and related_plan == "project/implementation-plan.md":
            findings.append(
                Finding(
                    "warn",
                    "grain-roadmap-stale-active-plan",
                    f"done roadmap item {item.item_id!r} still points related_plan at active implementation-plan.md",
                    roadmap.rel_path,
                    item.line,
                )
            )
        if len(verification_summary) > VERIFICATION_SUMMARY_REVIEW_CHARS:
            findings.append(
                Finding(
                    "info",
                    "grain-roadmap-long-verification",
                    f"roadmap item {item.item_id!r} verification_summary is {len(verification_summary)} chars; keep roadmap evidence compact",
                    roadmap.rel_path,
                    item.line,
                )
            )
        if status in {"accepted", "active", "proposed"} and not _field_list(item.fields, "target_artifacts"):
            targetless_review_items.append(item.item_id)

    if targetless_review_items:
        sample = ", ".join(targetless_review_items[:5])
        suffix = f", +{len(targetless_review_items) - 5} more" if len(targetless_review_items) > 5 else ""
        findings.append(
            Finding(
                "info",
                "grain-roadmap-target-artifacts",
                f"{len(targetless_review_items)} non-closed roadmap item(s) lack target_artifacts: {sample}{suffix}; report-only sizing signal",
                roadmap.rel_path,
            )
        )

    if not findings:
        findings.append(Finding("info", "grain-roadmap-ok", "roadmap grain diagnostics found no review pressure", roadmap.rel_path))
    return findings


def _calibration_findings(inventory: Inventory) -> list[Finding]:
    archive_dir = inventory.root / "project/archive/plans"
    if not archive_dir.is_dir():
        return [
            Finding(
                "info",
                "grain-calibration-skip",
                "no project/archive/plans directory is available for empirical slice calibration",
                "project/archive/plans",
            )
        ]

    paths = sorted(path for path in archive_dir.glob("*.md") if path.is_file())[-CALIBRATION_SAMPLE_LIMIT:]
    if not paths:
        return [
            Finding(
                "info",
                "grain-calibration-skip",
                "no archived plan samples are available for empirical slice calibration",
                "project/archive/plans",
            )
        ]

    findings: list[Finding] = []
    samples: list[PlanGrainStats] = []
    for path in paths:
        rel_path = _rel_path(inventory.root, path)
        try:
            stats = _plan_stats(rel_path, path.read_text(encoding="utf-8"))
        except OSError as exc:
            findings.append(Finding("warn", "grain-calibration-sample", f"could not read archived plan sample: {exc}", rel_path))
            continue
        samples.append(stats)
        findings.append(
            Finding(
                "info",
                "grain-calibration-sample",
                (
                    f"{rel_path}: {len(stats.covered_roadmap_items)} roadmap item(s), "
                    f"{stats.phase_count} phase(s), {len(stats.target_artifacts)} target artifact(s), "
                    f"docs_decision={stats.docs_decision or '<missing>'}, closeout_facts={stats.closeout_fact_count}"
                ),
                rel_path,
            )
        )

    if samples:
        item_counts = [len(sample.covered_roadmap_items) for sample in samples]
        phase_counts = [sample.phase_count for sample in samples]
        target_counts = [len(sample.target_artifacts) for sample in samples]
        findings.append(
            Finding(
                "info",
                "grain-calibration-summary",
                (
                    f"sampled {len(samples)} archived plan(s); observed roadmap item range {_value_range(item_counts)}, "
                    f"phase range {_value_range(phase_counts)}, target artifact range {_value_range(target_counts)}"
                ),
                "project/archive/plans",
            )
        )
        findings.append(
            Finding(
                "info",
                "grain-calibration-thresholds",
                (
                    "candidate review thresholds remain advisory: "
                    f"covered_roadmap_items>{max(COVERED_ITEM_REVIEW_THRESHOLD, max(item_counts) + 1)}, "
                    f"phases>{max(PHASE_REVIEW_THRESHOLD, max(phase_counts) + 1)}, "
                    f"target_artifacts>{max(TARGET_ARTIFACT_REVIEW_THRESHOLD, max(target_counts) + 1)}"
                ),
                "project/archive/plans",
            )
        )
    return findings


def _plan_stats(rel_path: str, text: str) -> PlanGrainStats:
    lines = text.splitlines()
    frontmatter = parse_frontmatter(text).data
    return PlanGrainStats(
        rel_path=rel_path,
        line_count=len(lines),
        char_count=len(text),
        frontmatter=frontmatter,
        phase_count=_phase_heading_count(extract_headings(text)),
        covered_roadmap_items=_list_value(frontmatter.get("covered_roadmap_items")),
        target_artifacts=_list_value(frontmatter.get("target_artifacts")),
        stop_conditions=_list_value(frontmatter.get("stop_conditions")),
        auto_continue=frontmatter.get("auto_continue") is True,
        execution_policy=str(frontmatter.get("execution_policy") or ""),
        docs_decision=str(frontmatter.get("docs_decision") or ""),
        write_scope_lines=_matching_contract_lines(lines, "write scope", "write_scope"),
        verification_lines=_matching_contract_lines(lines, "verification gates", "verification gate", "verification"),
        state_transfer_present="state transfer" in text.casefold(),
        closeout_fact_count=sum(1 for key in _closeout_keys() if re.search(rf"(?m)^-\s+{re.escape(key)}\s*:", text)),
        raw_log_markers=sum(1 for line in lines if _looks_like_raw_log_line(line)),
    )


def _phase_heading_count(headings: list[Heading]) -> int:
    in_phases = False
    count = 0
    for heading in headings:
        if heading.level == 2:
            in_phases = heading.title.strip().casefold() == "phases"
            continue
        if in_phases and heading.level == 3:
            count += 1
    return count


def _matching_contract_lines(lines: list[str], *labels: str) -> tuple[str, ...]:
    normalized_labels = tuple(label.casefold() for label in labels)
    matches = []
    for line in lines:
        stripped = line.strip()
        match = re.match(r"^-\s+([^:]+):\s*(.*)$", stripped)
        if not match:
            continue
        label = match.group(1).strip(" `").casefold()
        if label in normalized_labels:
            matches.append(stripped)
    return tuple(matches)


def _write_scope_is_vague(lines: tuple[str, ...]) -> bool:
    if not lines:
        return True
    vague_markers = ("declare exact", "update this section", "relevant", "as needed", "tbd", "todo", "unknown")
    return not any(_contract_line_is_specific(line, vague_markers) for line in lines)


def _verification_is_vague(lines: tuple[str, ...]) -> bool:
    if not lines:
        return True
    vague_markers = ("targeted tests first", "broader checks", "appropriate", "as needed", "tbd", "todo")
    return not any(_contract_line_is_specific(line, vague_markers) for line in lines)


def _contract_line_is_specific(line: str, vague_markers: tuple[str, ...]) -> bool:
    lowered = line.casefold()
    if any(marker in lowered for marker in vague_markers):
        return False
    return bool(re.search(r"`[^`]+`|[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+|[A-Za-z0-9_.-]+\.(py|md|toml|yaml|yml|json)", line))


def _pressure_signals(stats: PlanGrainStats) -> list[str]:
    signals: list[str] = []
    if len(stats.covered_roadmap_items) > COVERED_ITEM_REVIEW_THRESHOLD:
        signals.append(f"{len(stats.covered_roadmap_items)} covered roadmap items")
    if stats.phase_count > PHASE_REVIEW_THRESHOLD:
        signals.append(f"{stats.phase_count} phase headings")
    if len(stats.target_artifacts) > TARGET_ARTIFACT_REVIEW_THRESHOLD:
        signals.append(f"{len(stats.target_artifacts)} target artifacts")
    if stats.line_count > PLAN_LINE_REVIEW_THRESHOLD:
        signals.append(f"{stats.line_count} plan lines")
    return signals


def _roadmap_items(surface: Surface) -> tuple[list[RoadmapGrainItem], list[Finding]]:
    lines = surface.content.splitlines()
    items_heading = None
    for index, line in enumerate(lines):
        if re.match(r"^##\s+Items\s*$", line.strip()):
            items_heading = index
            break
    if items_heading is None:
        return [], [Finding("warn", "grain-roadmap-parse", "project/roadmap.md has no ## Items section", surface.rel_path)]

    items_end = len(lines)
    for index in range(items_heading + 1, len(lines)):
        if re.match(r"^##\s+\S", lines[index].strip()):
            items_end = index
            break

    starts = [index for index in range(items_heading + 1, items_end) if re.match(r"^###\s+.+\s*$", lines[index].strip())]
    if not starts:
        return [], [Finding("warn", "grain-roadmap-parse", "project/roadmap.md ## Items section has no item blocks", surface.rel_path)]

    items: list[RoadmapGrainItem] = []
    errors: list[Finding] = []
    seen: set[str] = set()
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else items_end
        title = re.sub(r"^###\s+", "", lines[start].strip()).strip()
        fields = _parse_item_fields(lines[start:end])
        item_id = _field_scalar(fields, "id")
        if not item_id:
            errors.append(Finding("warn", "grain-roadmap-parse", f"roadmap item block lacks an id field: {title}", surface.rel_path, start + 1))
            continue
        if item_id in seen:
            errors.append(Finding("warn", "grain-roadmap-parse", f"duplicate roadmap item id: {item_id}", surface.rel_path, start + 1))
            continue
        seen.add(item_id)
        items.append(RoadmapGrainItem(item_id=item_id, title=title, fields=fields, line=start + 1))
    return items, errors


def _parse_item_fields(lines: list[str]) -> dict[str, object]:
    fields: dict[str, object] = {}
    for line in lines:
        match = re.match(r"^-\s+`([A-Za-z0-9_-]+)`:\s*(.*?)\s*$", line.strip())
        if not match:
            continue
        key = match.group(1)
        raw = match.group(2).strip()
        if raw.startswith("`") and raw.endswith("`"):
            raw = raw[1:-1]
        if raw.startswith("[") and raw.endswith("]"):
            try:
                parsed = ast.literal_eval(raw)
            except (SyntaxError, ValueError):
                parsed = []
            fields[key] = [str(item) for item in parsed] if isinstance(parsed, list) else []
        else:
            fields[key] = raw
    return fields


def _field_scalar(fields: dict[str, object], key: str) -> str:
    value = fields.get(key)
    if value in (None, "", [], ()):
        return ""
    if isinstance(value, list):
        return str(value[0]).strip() if value else ""
    return str(value).strip()


def _field_list(fields: dict[str, object], key: str) -> tuple[str, ...]:
    return _list_value(fields.get(key))


def _list_value(value: object) -> tuple[str, ...]:
    if value in (None, "", [], ()):
        return ()
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, tuple):
        return tuple(str(item).strip() for item in value if str(item).strip())
    text = str(value).strip()
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            return ()
        if isinstance(parsed, list):
            return tuple(str(item).strip() for item in parsed if str(item).strip())
    return (text,) if text else ()


def _has_value(value: object) -> bool:
    if value is False:
        return True
    return value not in (None, "", [], ())


def _looks_like_raw_log_line(line: str) -> bool:
    stripped = line.strip()
    return bool(
        re.match(r"^(Exit code:|Wall time:|Traceback \(most recent call last\):|PS [A-Za-z]:\\)", stripped)
        or re.match(r"^-{4,}$", stripped)
    )


def _closeout_keys() -> tuple[str, ...]:
    return (
        "worktree_start_state",
        "task_scope",
        "docs_decision",
        "state_writeback",
        "verification",
        "commit_decision",
        "residual_risk",
        "carry_forward",
    )


def _value_range(values: list[int]) -> str:
    if not values:
        return "n/a"
    return f"{min(values)}-{max(values)}"


def _rel_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
