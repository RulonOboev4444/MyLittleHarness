from __future__ import annotations

import difflib
import glob
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from importlib import resources
from pathlib import Path

from . import __version__
from .atomic_files import AtomicFileWrite, FileTransactionError, apply_file_transaction
from .inventory import (
    EXPECTED_SPEC_NAMES,
    Inventory,
    LinkRef,
    Surface,
    load_inventory,
)
from .lifecycle_focus import CURRENT_FOCUS_BEGIN, CURRENT_FOCUS_END, MEMORY_ROADMAP_BEGIN, MEMORY_ROADMAP_END
from .models import Finding
from .memory_hygiene import relationship_hygiene_scan_findings
from .projection import Projection, ProjectionLinkRecord, build_projection, product_target_artifact_reason
from .projection_artifacts import (
    ARTIFACT_DIR_REL,
    build_projection_artifacts,
    inspect_projection_artifacts,
    projection_artifact_path_query_findings,
    rebuild_projection_artifacts,
)
from .projection_index import INDEX_REL_PATH, build_projection_index, full_text_search_findings, inspect_projection_index, rebuild_projection_index
from .routes import (
    INTAKE_ROUTE_ALLOWED_TARGETS,
    INTAKE_ROUTE_DEFAULT_STATUS,
    IntakeRouteAdvice,
    ROUTE_BY_ID,
    classify_intake_text,
    classify_memory_route,
    intake_target_matches_route,
    lifecycle_route_rows,
)
from .writeback import (
    active_plan_body_facts,
    active_plan_completed_phase_handoff_findings,
    active_plan_phase_body_status_fact,
    active_plan_preceding_phase_body_status_facts,
    canonical_phase_body_status,
    closeout_values_are_complete,
    state_writeback_facts,
)


LARGE_FILE_LINES = 500
VERY_LARGE_FILE_LINES = 1500
LARGE_FILE_CHARS = 25_000
VERY_LARGE_FILE_CHARS = 75_000
LARGE_AGGREGATE_LINES = 2500
LARGE_AGGREGATE_CHARS = 125_000
SEARCH_RESULT_LIMIT = 20
FAN_IN_RESULT_LIMIT = 20
CURRENT_PHASE_ONLY_POLICY = "current-phase-only"
AUTO_CONTINUE_STOP_COVERAGE = (
    ("verification", ("verification", "deterministic success", "success signal")),
    ("authority", ("docs", "api", "lifecycle authority", "root classification")),
    ("write_scope", ("write scope", "write-scope", "execution slice")),
    ("source_reality", ("source reality", "future phase", "dependency", "schema")),
    ("sensitive_action", ("destructive", "sensitive")),
    ("closeout_boundary", ("closeout", "archive", "next-slice", "next slice")),
)

PRODUCT_HYGIENE_OPERATIONAL_PREFIXES = {
    "project/implementation-plan.md": "active implementation plans live in the operating root",
    "project/roadmap.md": "roadmaps live in the operating root",
    "project/adrs": "ADR records live in the operating root",
    "project/decisions": "decision and do-not-revisit records live in the operating root",
    "project/archive": "archives and historical memory live in the operating root",
    "project/incubator": "legacy incubator notes must use canonical project/plan-incubation in the operating root",
    "project/plan-incubation": "incubation notes live in the operating root",
    "project/problem-reports": "problem reports and new intake live in the operating root",
    "project/raw-intake": "raw intake lives in the operating root",
    "project/research": "research and raw intake live in the operating root",
    "project/reports": "reports live in the operating root",
    "project/verification": "verification artifacts live in the operating root",
}
PRODUCT_HYGIENE_PACKAGE_PREFIXES = {
    "codex-home": "skill projections are not part of the clean product source tree",
    "research": "root research mirrors are excluded from the product source tree",
    "specs": "root package-source mirrors are excluded from the product source tree",
    "templates": "templates are package-source material, not product source",
}
PRODUCT_HYGIENE_DEBRIS_DIR_NAMES = {
    ".cache",
    ".eggs",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "artifacts",
    "build",
    "cache",
    "dist",
    "generated-validation",
    "htmlcov",
    "logs",
    "reports",
    "tmp",
    "validation-artifacts",
}
PRODUCT_HYGIENE_DEBRIS_FILE_SUFFIXES = {
    ".bak",
    ".db",
    ".egg",
    ".log",
    ".pyc",
    ".pyo",
    ".swo",
    ".swp",
    ".temp",
    ".sqlite",
    ".sqlite3",
    ".tmp",
    ".whl",
    ".zip",
}
PRODUCT_HYGIENE_DEBRIS_FILE_NAMES = {
    ".coverage",
    "coverage.xml",
    "validation-report.md",
}
PRODUCT_HYGIENE_ARCHIVE_SUFFIXES = (
    ".tar",
    ".tar.bz2",
    ".tar.gz",
    ".tar.xz",
    ".tgz",
)
EXPECTED_PRODUCT_NAME = "MyLittleHarness"
EXPECTED_PRODUCT_ROOT_ROLE = "product-source"
EXPECTED_PRODUCT_FIXTURE_STATUS = "product-compatibility-fixture"
ROOT_RELATIVE_LINK_PREFIXES = (
    ".mylittleharness/",
    ".agents/",
    ".codex/",
    "docs/",
    "project/",
    "specs/",
    "src/",
    "tests/",
)
ROOT_RELATIVE_LINK_NAMES = {"README.md", "AGENTS.md", "pyproject.toml"}
SNAPSHOT_REPAIR_ROOT_REL = ".mylittleharness/snapshots/repair"
SNAPSHOT_SCHEMA_VERSION = 1
SNAPSHOT_DRY_RUN_TIMESTAMP = "00000000T000000Z"
DOCMAP_REPAIR_CLASS = "docmap-route-repair"
DOCMAP_CREATE_CLASS = "docmap-create"
DOCMAP_REPAIR_TARGET_REL = ".agents/docmap.yaml"
DOCMAP_REPAIR_TARGET_SLUG = "agents-docmap-yaml"
DOCMAP_REPAIR_COPY_REL = "files/.agents/docmap.yaml"
STABLE_SPEC_CREATE_CLASS = "stable-spec-create"
STABLE_SPEC_ROOT_REL = "project/specs/workflow"
STABLE_SPEC_TEMPLATE_PACKAGE = "mylittleharness"
STABLE_SPEC_TEMPLATE_REL = ("templates", "workflow")
AGENTS_CONTRACT_CREATE_CLASS = "agents-contract-create"
AGENTS_CONTRACT_TARGET_REL = "AGENTS.md"
AGENTS_CONTRACT_TEMPLATE_REL = ("templates", "operating-root", "AGENTS.md")
STATE_FRONTMATTER_REPAIR_CLASS = "state-frontmatter-repair"
STATE_FRONTMATTER_TARGET_REL = "project/project-state.md"
STATE_FRONTMATTER_TARGET_SLUG = "project-project-state-md"
STATE_FRONTMATTER_COPY_REL = "files/project/project-state.md"
STATE_FRONTMATTER_OPTIONAL_KEYS = (
    "active_phase",
    "phase_status",
    "last_archived_plan",
    "operating_root",
    "canonical_source_evidence_root",
    "product_source_root",
    "projection_root",
    "projection_status",
    "historical_fallback_root",
)
SNAPSHOT_METADATA_FIELDS = (
    "schema_version",
    "created_at_utc",
    "tool_name",
    "tool_version",
    "command",
    "root_kind",
    "repair_class",
    "target_root",
    "snapshot_root",
    "target_paths",
    "copied_files",
    "pre_repair_hashes",
    "planned_post_repair_paths",
    "source_diagnostics",
    "planned_route_entries",
    "retention",
    "rollback_instructions",
    "authority_note",
)
CHECK_DRIFT_CODES = {
    "candidate-docmap-gap",
    "stale-fallback-root-reference",
    "stale-product-root-role",
    "stale-operating-root-role",
}
RULE_CONTEXT_PRIMARY_SURFACES = (
    "AGENTS.md",
    "README.md",
    ".agents/docmap.yaml",
    ".codex/project-workflow.toml",
    "project/project-state.md",
)
REMAINDER_DRIFT_SURFACE_ROLES = {
    "active-plan",
    "incubation",
    "project-state",
    "research",
}
DELIVERED_CONTEXT_MARKERS = (
    "completed",
    "current implementation",
    "delivered",
    "implemented",
    "now accepts",
    "now creates",
    "now reports",
    "shipped",
    "substantially narrowed",
)
REMAINDER_CONTEXT_MARKERS = (
    "backlog",
    "candidate",
    "deferred",
    "future",
    "not yet implemented",
    "open",
    "planned",
    "remainder",
    "remaining",
    "still open",
    "todo",
)
HISTORICAL_CONTEXT_MARKERS = (
    "archive",
    "archived",
    "changelog",
    "historical",
    "history",
    "old lane",
    "past release",
    "prior release",
    "release history",
    "superseded",
)
PHASE_STATUS_VALUES = {
    "pending",
    "active",
    "in_progress",
    "blocked",
    "complete",
    "skipped",
    "paused",
}
PHASE_BODY_TERMINAL_STATUS_VALUES = {"complete", "done", "skipped"}
DOCS_DECISION_VALUES = {"updated", "not-needed", "uncertain"}
ROUTE_METADATA_VALIDATED_ROUTES = {"adrs", "decisions", "incubation", "research", "roadmap", "stable-specs", "verification"}
ROUTE_METADATA_STATUS_VALUES = {
    "accepted",
    "active",
    "archived",
    "blocked",
    "complete",
    "deferred",
    "distilled",
    "done",
    "draft",
    "failed",
    "implemented",
    "imported",
    "incubating",
    "in_progress",
    "in-progress",
    "partial",
    "passed",
    "paused",
    "pending",
    "proposed",
    "promoted",
    "rejected",
    "research-ready",
    "skipped",
    "superseded",
}
ROUTE_METADATA_SCALAR_PATH_FIELDS = {"archived_to", "promoted_to"}
ROUTE_METADATA_FLEXIBLE_PATH_FIELDS = {
    "related_adr",
    "related_adrs",
    "related_decision",
    "related_decisions",
    "related_doc",
    "related_docs",
    "related_incubation",
    "related_plan",
    "related_roadmap",
    "related_research",
    "related_spec",
    "related_specs",
    "related_verification",
    "archived_plan",
    "source_incubation",
    "source_roadmap",
    "source_research",
    "implemented_by",
    "merged_from",
    "merged_into",
    "rejected_by",
    "split_from",
    "split_to",
    "superseded_by",
    "supersedes",
}
ROUTE_METADATA_PROMOTION_TARGET_ROUTES = {
    "active-plan",
    "adrs",
    "decisions",
    "operating-guardrails",
    "product-docs",
    "roadmap",
    "stable-specs",
    "state",
    "verification",
}
LIFECYCLE_ROUTE_ROWS = lifecycle_route_rows()


@dataclass(frozen=True)
class IntakeRequest:
    text: str
    text_source: str
    title: str
    target: str


def make_intake_request(text: str | None, text_source: str, title: str | None, target: str | None) -> IntakeRequest:
    return IntakeRequest(
        text=str(text or ""),
        text_source=str(text_source or "").strip() or "intake input",
        title=str(title or "").strip(),
        target=_normalized_intake_target(target),
    )


def intake_dry_run_findings(inventory: Inventory, request: IntakeRequest) -> list[Finding]:
    findings = [
        Finding("info", "intake-dry-run", "intake route proposal only; no files were written"),
        Finding("info", "intake-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    errors = _intake_request_errors(inventory, request, apply=False)
    if errors:
        findings.extend(_with_severity(errors, "warn"))
        findings.append(Finding("info", "intake-validation-posture", "dry-run refused before apply; classify the input and rerun dry-run before writing intake"))
        return findings

    advice = classify_intake_text(request.text)
    findings.extend(_intake_advice_findings(advice, request, prefix="would "))
    if request.target:
        findings.extend(_intake_target_preview_findings(request, advice))
    findings.extend(_intake_boundary_findings())
    findings.append(
        Finding(
            "info",
            "intake-validation-posture",
            "apply would write one explicit new Markdown target in a compatible route; dry-run writes no files",
            request.target or None,
        )
    )
    return findings


def intake_apply_findings(inventory: Inventory, request: IntakeRequest) -> list[Finding]:
    advice = classify_intake_text(request.text)
    errors = _intake_request_errors(inventory, request, apply=True)
    if errors:
        return errors

    target_path = inventory.root / request.target
    document = _intake_document_text(request, advice)
    operation = AtomicFileWrite(
        target_path=target_path,
        tmp_path=target_path.with_name(f".{target_path.name}.intake.tmp"),
        text=document,
        backup_path=target_path.with_name(f".{target_path.name}.intake.backup"),
    )
    try:
        cleanup_warnings = apply_file_transaction([operation])
    except FileTransactionError as exc:
        return [Finding("error", "intake-refused", f"intake apply failed before the target write completed: {exc}", request.target)]

    findings = [
        Finding("info", "intake-apply", "intake apply started"),
        Finding("info", "intake-root-posture", f"root kind: {inventory.root_kind}"),
        Finding("info", "intake-written", f"wrote routed intake note to {request.target}", request.target),
    ]
    findings.extend(_intake_advice_findings(advice, request, prefix=""))
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "intake-backup-cleanup", warning, request.target))
    findings.extend(_intake_boundary_findings())
    findings.append(
        Finding(
            "info",
            "intake-validation-posture",
            "run check after apply to verify the live operating root remains healthy; intake output is not lifecycle approval",
            request.target,
        )
    )
    return findings


def status_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    state = inventory.state
    data = state.frontmatter.data if state else {}
    findings.append(Finding("info", "root-kind", f"root kind: {inventory.root_kind}"))
    findings.extend(_product_posture_status_findings(inventory))
    findings.extend(lifecycle_route_findings(inventory))
    findings.extend(lifecycle_summary_findings(inventory))
    for key in (
        "project",
        "root_role",
        "fixture_status",
        "operating_mode",
        "plan_status",
        "active_plan",
        "active_phase",
        "phase_status",
        "operating_root",
        "product_source_root",
        "projection_status",
    ):
        value = data.get(key)
        if value not in (None, ""):
            findings.append(Finding("info", "state-field", f"{key}: {value}", state.rel_path if state else None))

    if inventory.active_plan_surface and inventory.active_plan_surface.exists:
        findings.append(
            Finding(
                "info",
                "active-plan",
                f"active plan present: {inventory.active_plan_surface.rel_path}",
                inventory.active_plan_surface.rel_path,
            )
        )
    else:
        findings.append(Finding("info", "active-plan", "no active plan file is required by current state"))

    required_total = len([surface for surface in inventory.surfaces if surface.required])
    required_present = len([surface for surface in inventory.surfaces if surface.required and surface.exists])
    optional_present = len([surface for surface in inventory.surfaces if not surface.required and surface.exists])
    findings.append(
        Finding(
            "info",
            "surface-inventory",
            f"required surfaces present: {required_present}/{required_total}; optional surfaces present: {optional_present}",
        )
    )

    source_root = data.get("operating_root") or data.get("canonical_source_evidence_root")
    product_root = data.get("product_source_root") or data.get("projection_root")
    if source_root:
        findings.append(Finding("info", "operating-root", f"operating root: {source_root}", state.rel_path if state else None))
    if product_root:
        findings.append(Finding("info", "product-root", f"product source root: {product_root}", state.rel_path if state else None))
    marker = inventory.surface_by_rel.get(DETACH_MARKER_REL_PATH)
    if marker and marker.exists:
        findings.extend(_detach_marker_status_findings(inventory, marker))
    return findings


def lifecycle_summary_findings(inventory: Inventory) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []
    state = inventory.state
    data = state.frontmatter.data if state and state.exists else {}
    plan_status = str(data.get("plan_status") or "")
    active_phase = str(data.get("active_phase") or "")
    phase_status = str(data.get("phase_status") or "")
    active_plan = str(data.get("active_plan") or "project/implementation-plan.md")
    source = state.rel_path if state else None
    if plan_status == "active":
        phase_label = f"; active_phase: {active_phase}" if active_phase else ""
        if phase_status == "complete":
            return [
                Finding(
                    "info",
                    "lifecycle-summary",
                    (
                        f"active plan phase is complete{phase_label}; implementation work is not pending and the active plan is ready for explicit closeout/writeback; "
                        "phase completion alone does not approve auto-continue, archive, roadmap done-status, next-slice opening, or commit"
                    ),
                    source,
                )
            ]
        if phase_status in {"active", "in_progress"}:
            return [
                Finding(
                    "info",
                    "lifecycle-summary",
                    (
                        f"active plan is in progress{phase_label}; current-phase-only default continues from "
                        "project-state active_phase and stops after repo-visible state/evidence unless explicit auto_continue is safe"
                    ),
                    source,
                )
            ]
        if phase_status in {"blocked", "paused"}:
            return [
                Finding(
                    "warn",
                    "lifecycle-summary",
                    f"active plan is {phase_status}{phase_label}; resolve the blocker or update lifecycle state before continuing",
                    source,
                )
            ]
        if phase_status == "skipped":
            return [
                Finding(
                    "info",
                    "lifecycle-summary",
                    f"active plan phase is skipped{phase_label}; next action is explicit lifecycle writeback or archive decision",
                    source,
                )
            ]
        return [
            Finding(
                "info",
                "lifecycle-summary",
                (
                    f"active plan is open at {active_plan}; phase_status is {phase_status or 'not recorded'}; "
                    "current-phase-only default requires an explicit lifecycle decision before any next phase"
                ),
                source,
            )
        ]
    if plan_status in {"", "none"}:
        return [Finding("info", "lifecycle-summary", "no active implementation plan is open", source)]
    return [
        Finding(
            "warn",
            "lifecycle-summary",
            f"plan_status is {plan_status!r}; expected active or none for normal continuation",
            source,
        )
    ]


def lifecycle_route_findings(inventory: Inventory) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []
    findings = [
        Finding(
            "info",
            "lifecycle-route-table",
            (
                "canonical lifecycle route table for live operating roots; "
                "advisory only and cannot approve mutation, repair, closeout, archive, commit, or lifecycle decisions"
            ),
        )
    ]
    findings.extend(
        Finding("info", "lifecycle-route", f"{name}: {target}; {purpose}")
        for name, target, purpose in LIFECYCLE_ROUTE_ROWS
    )
    return findings


def memory_route_inventory_findings(inventory: Inventory) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []

    surfaces = [surface for surface in inventory.present_surfaces if surface.memory_route]
    if not surfaces:
        return [Finding("info", "memory-route-inventory", "no present repo-visible surfaces were classified")]

    route_counts: dict[str, list[Surface]] = {}
    for surface in surfaces:
        route_counts.setdefault(surface.memory_route, []).append(surface)

    findings = [
        Finding(
            "info",
            "memory-route-inventory",
            f"classified {len(surfaces)} present repo-visible surface(s) into {len(route_counts)} memory route(s)",
        )
    ]
    for route_id in _ordered_route_ids(route_counts):
        route = ROUTE_BY_ID.get(route_id)
        route_surfaces = sorted(route_counts[route_id], key=lambda item: item.rel_path)
        examples = ", ".join(surface.rel_path for surface in route_surfaces[:3])
        if len(route_surfaces) > 3:
            examples += f", +{len(route_surfaces) - 3} more"
        target = route.target if route else "<unknown>"
        findings.append(
            Finding(
                "info",
                "memory-route",
                f"{route_id}: {len(route_surfaces)} surface(s); target: {target}; examples: {examples}",
            )
        )

    for surface in sorted(surfaces, key=lambda item: item.rel_path):
        route = ROUTE_BY_ID.get(surface.memory_route)
        purpose = route.purpose if route else "unknown route"
        findings.append(
            Finding(
                "info",
                "memory-route-surface",
                f"{surface.rel_path} -> {surface.memory_route}; {purpose}",
                surface.rel_path,
            )
        )
    return findings


def _ordered_route_ids(route_counts: dict[str, list[Surface]]) -> list[str]:
    registry_order = {route_id: index for index, route_id in enumerate(ROUTE_BY_ID)}
    return sorted(route_counts, key=lambda route_id: (registry_order.get(route_id, len(registry_order)), route_id))


def validation_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(_required_surface_findings(inventory))
    findings.extend(_manifest_findings(inventory))
    findings.extend(_state_findings(inventory))
    findings.extend(_incubation_contract_findings(inventory))
    findings.extend(_product_posture_findings(inventory))
    findings.extend(_active_plan_findings(inventory))
    findings.extend(_spec_findings(inventory))
    findings.extend(_frontmatter_findings(inventory))
    findings.extend(_route_metadata_findings(inventory))
    findings.extend(_docmap_findings(inventory))
    findings.extend(_mirror_findings(inventory))
    return findings


def _incubation_contract_findings(inventory: Inventory) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []
    findings: list[Finding] = []
    legacy_path = inventory.root / "project/incubator"
    if legacy_path.exists():
        findings.append(
            Finding(
                "warn",
                "incubation-legacy-path",
                "project/incubator is a legacy or ambiguous idea surface; use canonical project/plan-incubation/*.md for incubation notes",
                "project/incubator",
            )
        )
    agents = inventory.surface_by_rel.get("AGENTS.md")
    if agents and agents.exists and "project/plan-incubation" not in agents.content:
        findings.append(
            Finding(
                "warn",
                "agents-incubation-contract-missing",
                "AGENTS.md does not name the canonical incubation surface; idea-incubation requests should create or update project/plan-incubation/*.md instead of project-state carry-forward bullets",
                "AGENTS.md",
            )
        )
    return findings


def check_drift_findings(inventory: Inventory) -> list[Finding]:
    findings = [finding for finding in audit_link_findings(inventory) if finding.code in CHECK_DRIFT_CODES]
    findings.extend(rule_context_findings(inventory, include_ok=False))
    findings.extend(remainder_drift_findings(inventory, include_ok=False))
    if findings:
        return findings
    return [Finding("info", "check-drift-ok", "no check-level docmap, root-pointer, rule/context, or remainder drift was found")]


def projection_cache_status_findings(inventory: Inventory) -> list[Finding]:
    projection = build_projection(inventory)
    artifact_findings = inspect_projection_artifacts(inventory, projection)
    index_findings = inspect_projection_index(inventory, projection)
    artifact_status, artifact_reason = _projection_cache_status(
        artifact_findings,
        current_code="projection-artifact-current",
        missing_code="projection-artifact-missing",
    )
    index_status, index_reason = _projection_cache_status(
        index_findings,
        current_code="projection-index-current",
        missing_code="projection-index-missing",
    )
    reason = _projection_cache_reason_label(artifact_reason, index_reason)
    return [
        Finding(
            "info",
            "projection-cache-status",
            (
                f"generated projection cache: artifacts={artifact_status}; sqlite_index={index_status}; "
                f"detail={reason}; source files and the in-memory projection remain authoritative"
            ),
            ARTIFACT_DIR_REL,
        ),
        Finding(
            "info",
            "projection-cache-read-only",
            (
                "check inspects projection freshness without refreshing generated artifacts or SQLite indexes; "
                "intelligence path/full-text navigation may refresh the disposable cache when a query needs it"
            ),
            ARTIFACT_DIR_REL,
        ),
    ]


def _projection_cache_status(findings: list[Finding], current_code: str, missing_code: str) -> tuple[str, str]:
    codes = [finding.code for finding in findings]
    if any(code.endswith("fts5-unavailable") for code in codes):
        return "unavailable", _projection_cache_sample(codes)
    if missing_code in codes:
        return "missing", missing_code
    if current_code in codes:
        return "current", current_code
    if any(
        code.endswith(suffix)
        for code in codes
        for suffix in ("stale", "hash", "count", "schema", "root-mismatch")
    ):
        return "stale", _projection_cache_sample(codes)
    if any(finding.severity in {"warn", "error"} for finding in findings):
        return "degraded", _projection_cache_sample(codes)
    return "current", _projection_cache_sample(codes)


def _projection_cache_sample(codes: list[str]) -> str:
    selected = [code for code in codes if not code.endswith("boundary")]
    return ",".join(selected[:3]) if selected else "no-detail"


def _projection_cache_reason_label(artifact_reason: str, index_reason: str) -> str:
    if artifact_reason == index_reason:
        return artifact_reason
    return f"artifacts:{artifact_reason}; index:{index_reason}"


def diagnostic_drift_findings(inventory: Inventory) -> list[Finding]:
    findings = audit_link_findings(inventory)
    findings.extend(rule_context_findings(inventory, include_ok=False))
    findings.extend(remainder_drift_findings(inventory, include_ok=False))
    return findings


def rule_context_findings(inventory: Inventory, include_ok: bool = True) -> list[Finding]:
    findings: list[Finding] = []
    rel_paths = list(RULE_CONTEXT_PRIMARY_SURFACES)
    if inventory.active_plan_surface and inventory.active_plan_surface.rel_path not in rel_paths:
        rel_paths.append(inventory.active_plan_surface.rel_path)

    for rel_path in rel_paths:
        surface = inventory.surface_by_rel.get(rel_path)
        if not surface or not surface.exists:
            continue
        label = _budget_label(surface.line_count, surface.char_count)
        if label not in {"large", "very-large"}:
            continue
        findings.append(
            Finding(
                "warn",
                "rule-context-surface-large",
                _large_rule_context_message(inventory, surface, label),
                surface.rel_path,
            )
        )

    if findings or not include_ok:
        return findings
    return [Finding("info", "rule-context-ok", "primary instruction surfaces are within check-level size thresholds")]


def _large_rule_context_message(inventory: Inventory, surface: Surface, label: str) -> str:
    message = (
        f"{surface.rel_path}: primary instruction surface is {surface.line_count} lines, "
        f"{surface.char_count} chars, label={label}; use context-budget for section detail"
    )
    if inventory.root_kind == "live_operating_root" and surface.rel_path == "project/project-state.md":
        message += "; preview whole-state history compaction with writeback --dry-run --compact-only"
    return message


def remainder_drift_findings(inventory: Inventory, include_ok: bool = True) -> list[Finding]:
    delivered: dict[str, tuple[Surface, int]] = {}
    remainder: list[tuple[str, Surface, int]] = []
    findings: list[Finding] = []

    for surface in inventory.present_surfaces:
        if surface.role not in REMAINDER_DRIFT_SURFACE_ROLES or surface.role == "package-mirror":
            continue
        lines = surface.content.splitlines()
        for line_number, line in enumerate(lines, start=1):
            context = _remainder_drift_context(surface, line_number, line)
            if context == "historical":
                continue
            tokens = _explicit_remainder_tokens(line)
            if not tokens:
                continue
            if context == "delivered":
                for token in tokens:
                    delivered.setdefault(token, (surface, line_number))
            elif context == "remainder":
                for token in tokens:
                    remainder.append((token, surface, line_number))

    seen: set[tuple[str, str, int]] = set()
    for token, surface, line_number in remainder:
        if token not in delivered:
            continue
        key = (token, surface.rel_path, line_number)
        if key in seen:
            continue
        seen.add(key)
        delivered_surface, delivered_line = delivered[token]
        findings.append(
            Finding(
                "warn",
                "remainder-drift",
                (
                    f"`{token}` is described as delivered/current at "
                    f"{delivered_surface.rel_path}:{delivered_line} but still appears in future/backlog wording"
                ),
                surface.rel_path,
                line_number,
            )
        )

    if findings or not include_ok:
        return findings
    return [Finding("info", "remainder-drift-ok", "no explicit delivered-vs-remainder token contradictions were found")]


def context_budget_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    start_surfaces = _start_path_surfaces(inventory)
    total_lines = 0
    total_chars = 0
    warning_lines = 0
    warning_chars = 0

    for surface in start_surfaces:
        if not surface.exists:
            continue
        lines = surface.line_count
        chars = surface.char_count
        total_lines += lines
        total_chars += chars
        if _context_budget_surface_can_warn(surface):
            warning_lines += lines
            warning_chars += chars
        token_estimate = max(1, chars // 4) if chars else 0
        label = _budget_label(lines, chars)
        severity = "warn" if label in {"large", "very-large"} and _context_budget_surface_can_warn(surface) else "info"
        findings.append(
            Finding(
                severity,
                "file-budget",
                f"{surface.rel_path}: {lines} lines, {chars} chars, {surface.byte_count} bytes, ~{token_estimate} tokens, label={label}",
                surface.rel_path,
            )
        )
        for heading in surface.largest_sections(limit=3):
            findings.append(
                Finding(
                    "info",
                    "section-budget",
                    f"{surface.rel_path}:{heading.line} section '{heading.title}' spans {heading.length} lines",
                    surface.rel_path,
                    heading.line,
                )
            )

    aggregate_label = "large" if total_lines > LARGE_AGGREGATE_LINES or total_chars > LARGE_AGGREGATE_CHARS else "normal"
    warning_aggregate_label = (
        "large" if warning_lines > LARGE_AGGREGATE_LINES or warning_chars > LARGE_AGGREGATE_CHARS else "normal"
    )
    severity = "warn" if warning_aggregate_label == "large" else "info"
    findings.insert(
        0,
        Finding(
            severity,
            "start-set-budget",
            f"start-path aggregate: {total_lines} lines, {total_chars} chars, ~{max(1, total_chars // 4) if total_chars else 0} tokens, label={aggregate_label}",
        ),
    )
    return findings


def _context_budget_surface_can_warn(surface: Surface) -> bool:
    return surface.role not in {"product-doc", "stable-spec", "package-mirror"}


def audit_link_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    skipped_external = 0
    skipped_mirrors = 0
    seen: set[tuple[str, str, int]] = set()
    for surface in inventory.present_surfaces:
        if surface.role == "package-mirror":
            skipped_mirrors += 1
            continue
        for link in surface.links:
            key = (surface.rel_path, link.target, link.line)
            if key in seen:
                continue
            seen.add(key)
            resolution = resolve_link(inventory.root, link.target, surface.rel_path)
            if resolution.kind == "external":
                skipped_external += 1
                continue
            if resolution.kind == "anchor":
                continue
            if resolution.kind == "unresolved":
                findings.append(
                    Finding("warn", "unresolved-link", f"{link.target} could not be resolved as a local path", surface.rel_path, link.line)
                )
                continue
            if resolution.kind == "pattern":
                if not resolution.exists:
                    product_target_reason = product_target_artifact_reason(inventory, surface, link.target, link.line)
                    if product_target_reason:
                        findings.append(
                            Finding(
                                "info",
                                "product-target-artifact",
                                f"{link.target} is not present in the operating root; {product_target_reason}",
                                surface.rel_path,
                                link.line,
                            )
                        )
                        continue
                    findings.append(
                        Finding(
                            "info",
                            "optional-pattern-missing",
                            f"{link.target} did not match an existing local path; treating as optional pattern",
                            surface.rel_path,
                            link.line,
                        )
                    )
                continue
            if not resolution.exists:
                product_target_reason = product_target_artifact_reason(inventory, surface, link.target, link.line)
                if product_target_reason:
                    findings.append(
                        Finding(
                            "info",
                            "product-target-artifact",
                            f"{link.target} is not present in the operating root; {product_target_reason}",
                            surface.rel_path,
                            link.line,
                        )
                    )
                    continue
                optional_reason = _optional_missing_link_reason(inventory, link.target)
                if optional_reason:
                    findings.append(
                        Finding(
                            "info",
                            "optional-link-missing",
                            f"{link.target} is not present; {optional_reason}",
                            surface.rel_path,
                            link.line,
                        )
                    )
                    continue
                findings.append(
                    Finding(
                        "warn",
                        "missing-link",
                        f"{link.target} does not resolve to an existing local path",
                        surface.rel_path,
                        link.line,
                    )
                )
    if skipped_external:
        findings.append(Finding("info", "external-links-skipped", f"skipped {skipped_external} external URL links"))
    if skipped_mirrors:
        findings.append(Finding("info", "package-mirrors-skipped", f"skipped duplicate link audit for {skipped_mirrors} package-source mirror files"))
    findings.extend(_docmap_gap_findings(inventory))
    findings.extend(_stale_root_pointer_findings(inventory))
    if not findings:
        findings.append(Finding("info", "links-ok", "no missing local links were found"))
    return findings


def intelligence_sections(
    inventory: Inventory,
    search_text: str | None = None,
    path_text: str | None = None,
    full_text: str | None = None,
    limit: int = 10,
    query_text: str | None = None,
) -> list[tuple[str, list[Finding]]]:
    search_text, path_text, full_text, query_expansion = _expanded_intelligence_queries(
        search_text,
        path_text,
        full_text,
        query_text,
    )
    projection = build_projection(inventory)
    sections = [
        ("Boundary", _intelligence_boundary_findings(inventory, search_text, path_text, full_text)),
        ("Drift", diagnostic_drift_findings(inventory)),
        ("Repo Map", _repo_map_findings(projection)),
        ("Backlinks", _backlink_findings(projection.links)),
        ("Search", _search_findings(inventory, projection, search_text, path_text, full_text, limit, query_expansion)),
        ("Fan-In", _fan_in_findings(inventory, projection)),
        ("Projection", _projection_findings(inventory, projection)),
    ]
    normalized_sections = [
        (section_name, [_normalize_intelligence_finding(inventory, finding) for finding in findings])
        for section_name, findings in sections
    ]
    return [("Summary", _intelligence_summary_findings(inventory, normalized_sections, search_text, path_text, full_text))] + normalized_sections


def intelligence_route_sections(inventory: Inventory) -> list[tuple[str, list[Finding]]]:
    boundary = [
        Finding("info", "intelligence-routes-read-only", "intelligence --focus routes reports lifecycle routing without writing files"),
        Finding(
            "info",
            "intelligence-routes-boundary",
            (
                "route output is advisory and cannot approve mutation, repair, closeout, archive, commit, "
                "or lifecycle decisions"
            ),
        ),
        Finding("info", "intelligence-routes-root-kind", f"root kind: {inventory.root_kind}"),
    ]
    if inventory.root_kind != "live_operating_root":
        boundary.append(
            Finding(
                "info",
                "route-table-scope",
                "lifecycle route table is reported only for live operating roots; product-source fixtures remain product/fixture context",
            )
        )
    sections = [("Boundary", boundary), ("Lifecycle Routes", lifecycle_route_findings(inventory))]
    discovered = memory_route_inventory_findings(inventory)
    if discovered:
        sections.append(("Discovered Routes", discovered))
    return sections


def flatten_sections(sections: list[tuple[str, list[Finding]]]) -> list[Finding]:
    return [finding for _, findings in sections for finding in findings]


def _expanded_intelligence_queries(
    search_text: str | None,
    path_text: str | None,
    full_text: str | None,
    query_text: str | None,
) -> tuple[str | None, str | None, str | None, Finding | None]:
    if query_text in (None, ""):
        return search_text, path_text, full_text, None

    filled: list[str] = []
    if search_text is None:
        search_text = query_text
        filled.append("exact text")
    if path_text is None:
        path_text = query_text
        filled.append("path")
    if full_text is None:
        full_text = query_text
        filled.append("full text")

    filled_label = ", ".join(filled) if filled else "none"
    return (
        search_text,
        path_text,
        full_text,
        Finding(
            "info",
            "intelligence-query-expansion",
            f"unified query expanded into omitted modes: {filled_label}; explicit mode flags keep their own values",
        ),
    )


def _intelligence_boundary_findings(
    inventory: Inventory,
    search_text: str | None,
    path_text: str | None,
    full_text: str | None,
) -> list[Finding]:
    present_count = len(inventory.present_surfaces)
    cache_posture = (
        f"path/full-text navigation may refresh disposable generated projection cache inside {ARTIFACT_DIR_REL}"
        if path_text not in (None, "") or full_text not in (None, "")
        else "no generated projection cache refresh is needed for this invocation"
    )
    return [
        Finding("info", "intelligence-boundary", f"terminal-only report; {cache_posture}; lifecycle authority files, hooks, adapters, snapshots, repairs, archives, and commits are not written"),
        Finding("info", "intelligence-root-kind", f"root kind: {inventory.root_kind}"),
        Finding("info", "intelligence-corpus", f"inventory corpus: {present_count}/{len(inventory.surfaces)} discovered surfaces present"),
        Finding("info", "intelligence-search-mode", f"case-sensitive exact/path matching plus optional source-verified full-text; active queries: {_intelligence_query_label(search_text, path_text, full_text)}"),
    ]


def _intelligence_summary_findings(
    inventory: Inventory,
    sections: list[tuple[str, list[Finding]]],
    search_text: str | None,
    path_text: str | None,
    full_text: str | None,
) -> list[Finding]:
    findings = flatten_sections(sections)
    errors = [finding for finding in findings if finding.severity == "error"]
    warnings = [finding for finding in findings if finding.severity == "warn"]
    result = "error" if errors else "warn" if warnings else "ok"
    present_count = len(inventory.present_surfaces)
    summary = [
        Finding(
            "info",
            "intelligence-summary",
            (
                f"root kind: {inventory.root_kind}; status: {result}; corpus: {present_count}/{len(inventory.surfaces)}; "
                f"actionable warnings: {len(warnings)}; errors: {len(errors)}; active queries: {_intelligence_query_label(search_text, path_text, full_text)}"
            ),
        )
    ]
    state = inventory.state
    state_data = state.frontmatter.data if state and state.exists else {}
    for key in ("operating_mode", "plan_status", "active_plan", "active_phase", "phase_status"):
        value = state_data.get(key)
        if value not in (None, ""):
            summary.append(Finding("info", "intelligence-state", f"{key}: {value}", state.rel_path if state else None))
    summary.append(Finding("info", "intelligence-recovery-targets", f"top recovery targets: {_intelligence_recovery_targets(inventory)}"))
    return summary


def _intelligence_query_label(search_text: str | None, path_text: str | None, full_text: str | None = None) -> str:
    query_parts = []
    if search_text not in (None, ""):
        query_parts.append("exact text")
    if path_text not in (None, ""):
        query_parts.append("path")
    if full_text not in (None, ""):
        query_parts.append("full text")
    return ", ".join(query_parts) if query_parts else "none"


def _intelligence_recovery_targets(inventory: Inventory) -> str:
    targets: list[str] = []
    for rel_path in (
        inventory.state.rel_path if inventory.state else "",
        inventory.active_plan_surface.rel_path if inventory.active_plan_surface else "",
        "README.md",
        "docs/README.md",
        "docs/specs/attach-repair-status-cli.md",
        "docs/specs/generated-state-and-projections.md",
    ):
        if rel_path and rel_path in inventory.surface_by_rel and inventory.surface_by_rel[rel_path].exists and rel_path not in targets:
            targets.append(rel_path)
    return ", ".join(targets[:5]) if targets else "none"


def _remainder_drift_context(surface: Surface, line_number: int, line: str) -> str:
    heading = _heading_for_line(surface, line_number)
    heading_text = heading.casefold()
    line_text = line.casefold()
    line_start = re.sub(r"^[\s>*#\-0-9.)]+", "", line_text).strip()
    text = f"{heading_text} {line_text}"
    if any(marker in text for marker in HISTORICAL_CONTEXT_MARKERS):
        return "historical"
    if (
        any(marker in heading_text for marker in REMAINDER_CONTEXT_MARKERS)
        or any(line_start.startswith(marker) for marker in REMAINDER_CONTEXT_MARKERS)
        or "listed as future" in line_text
        or "still listed" in line_text
        or "still lists" in line_text
        or "remains open" in line_text
    ):
        return "remainder"
    if any(marker in heading_text for marker in DELIVERED_CONTEXT_MARKERS) or any(
        line_start.startswith(marker) for marker in DELIVERED_CONTEXT_MARKERS
    ):
        return "delivered"
    return "neutral"


def _heading_for_line(surface: Surface, line_number: int) -> str:
    current = ""
    for heading in surface.headings:
        if heading.line > line_number:
            break
        current = heading.title
    return current


def _explicit_remainder_tokens(line: str) -> set[str]:
    tokens: set[str] = set()
    for match in re.finditer(r"`([^`\n]{2,100})`", line):
        token = _normalize_remainder_token(match.group(1))
        if _is_remainder_capability_token(token):
            tokens.add(token)
    for match in re.finditer(r'"([^"\n]{2,100})"', line):
        token = _normalize_remainder_token(match.group(1))
        if _is_remainder_capability_token(token):
            tokens.add(token)
    return tokens


def _normalize_remainder_token(token: str) -> str:
    normalized = token.strip().strip(".,;:()[]{}").replace("\\", "/").casefold()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _is_remainder_capability_token(token: str) -> bool:
    if not token or len(token) > 80:
        return False
    if "/" in token or token.endswith((".md", ".toml", ".yaml", ".json", ".py")):
        return False
    if not re.search(r"[a-z]", token):
        return False
    return (
        "--" in token
        or token
        in {
            "adapter",
            "adapters",
            "attach",
            "audit-links",
            "bootstrap",
            "check",
            "closeout",
            "context-budget",
            "detach",
            "doctor",
            "evidence",
            "init",
            "intelligence",
            "preflight",
            "projection",
            "repair",
            "semantic",
            "snapshot",
            "status",
            "tasks",
            "validate",
        }
    )


def _normalize_intelligence_finding(inventory: Inventory, finding: Finding) -> Finding:
    if finding.severity != "warn" or not _intelligence_warning_is_informational(inventory, finding):
        return finding
    return Finding(
        "info",
        finding.code,
        f"{finding.message}; informational in intelligence recovery view",
        finding.source,
        finding.line,
    )


def _intelligence_warning_is_informational(inventory: Inventory, finding: Finding) -> bool:
    text = f"{finding.message} {finding.source or ''}".replace("\\", "/")
    text_lower = text.lower()
    if "%userprofile%" in text_lower or ".codex/config.toml" in text_lower:
        return True
    if "__pycache__" in text_lower or "validation-report" in text_lower:
        return True
    if inventory.root_kind != "live_operating_root":
        return False
    target = _target_from_finding(finding)
    if target.startswith(("src/", "tests/", "research/", "specs/", "templates/", "codex-home/")):
        return True
    if re.search(r"project/(research|archive|verification)/.*\d{4}-\d{2}-\d{2}", target):
        return True
    return False


def _target_from_finding(finding: Finding) -> str:
    message = finding.message.replace("\\", "/")
    if finding.code in {"missing-link", "unresolved-link"}:
        return message.split(" ", 1)[0]
    if finding.code == "backlink-reference" and " -> " in message:
        return message.split(" -> ", 1)[1].split(";", 1)[0]
    if finding.code == "fan-in-target":
        return message.split(":", 1)[0]
    return message


def _repo_map_findings(projection: Projection) -> list[Finding]:
    findings: list[Finding] = []
    for source in projection.sources:
        presence = "present" if source.present else "missing"
        requirement = "required" if source.required else "optional"
        message = (
            f"{source.path}: role={source.role}; {requirement}; {presence}; "
            f"lines={source.line_count}; bytes={source.byte_count}; headings={source.heading_count}; "
            f"links={source.link_count}; hash={_display_hash(source.content_hash)}"
        )
        severity = "warn" if source.required and not source.present else "info"
        findings.append(Finding(severity, "repo-map-surface", message, source.path))
        if source.read_error:
            findings.append(Finding("warn", "repo-map-read-error", f"{source.path}: {source.read_error}", source.path))
    return findings


def _backlink_findings(records: tuple[ProjectionLinkRecord, ...]) -> list[Finding]:
    if not records:
        return [Finding("info", "backlink-empty", "no repo-local path references were found")]
    findings: list[Finding] = []
    for record in records:
        severity = "warn" if record.status in {"missing", "unresolved"} else "info"
        findings.append(
            Finding(
                severity,
                "backlink-reference",
                f"{record.source}:{record.line} -> {record.target}; status={record.status}",
                record.source,
                record.line,
            )
        )
    return findings


def _search_findings(
    inventory: Inventory,
    projection: Projection,
    search_text: str | None,
    path_text: str | None,
    full_text: str | None,
    limit: int,
    query_expansion: Finding | None = None,
) -> list[Finding]:
    if search_text == "":
        search_text = None
    if path_text == "":
        path_text = None
    if full_text == "":
        full_text = None
    if search_text is None and path_text is None and full_text is None:
        return [Finding("info", "search-ready", "no query provided; use --query TEXT, --search TEXT, --path TEXT, and/or --full-text TEXT for inventory search")]

    notes: list[Finding] = []
    if query_expansion is not None:
        notes.append(query_expansion)
    if search_text:
        notes.append(
            Finding(
                "info",
                "projection-exact-search-source-only",
                "exact text search reads direct source content through the in-memory projection; projection artifacts do not store source bodies",
            )
        )
    notes.extend(_navigation_cache_maintenance_findings(inventory, projection, path_text, full_text))
    notes.extend(projection_artifact_path_query_findings(inventory, projection, path_text))
    notes.extend(full_text_search_findings(inventory, projection, full_text, limit))

    findings: list[Finding] = []
    truncated = False

    def add(finding: Finding) -> None:
        nonlocal truncated
        if len(findings) >= SEARCH_RESULT_LIMIT:
            truncated = True
            return
        findings.append(finding)

    if path_text:
        for source in projection.sources:
            if path_text in source.path:
                add(
                    Finding(
                        "info",
                        "search-path-match",
                        f"path match for {path_text!r}: projection source {source.path}",
                        source.path,
                    )
                )
        for record in projection.links:
            if path_text in record.target:
                add(
                    Finding(
                        "info",
                        "search-path-reference",
                        f"path reference match for {path_text!r}: {record.target}; status={record.status}",
                        record.source,
                        record.line,
                    )
                )

    if search_text:
        for source in projection.sources:
            if not source.present:
                continue
            for line_number, line in enumerate(source.content.splitlines(), start=1):
                if search_text in line:
                    add(
                        Finding(
                            "info",
                            "search-match",
                            f"text match for {search_text!r}: {_trim_line(line)}",
                            source.path,
                            line_number,
                        )
                    )

    if not findings:
        if search_text is None and path_text is None:
            return notes
        return notes + [Finding("info", "search-no-matches", "no case-sensitive inventory matches found")]
    if truncated:
        findings.append(Finding("info", "search-truncated", f"showing first {SEARCH_RESULT_LIMIT} deterministic matches"))
    return notes + findings


def _navigation_cache_maintenance_findings(
    inventory: Inventory,
    projection: Projection,
    path_text: str | None,
    full_text: str | None,
) -> list[Finding]:
    findings: list[Finding] = []
    if path_text not in (None, ""):
        findings.extend(_ensure_projection_artifacts_for_navigation(inventory, projection))
    if full_text not in (None, ""):
        findings.extend(_ensure_projection_index_for_navigation(inventory, projection))
    return findings


def _ensure_projection_artifacts_for_navigation(inventory: Inventory, projection: Projection) -> list[Finding]:
    inspect_findings = inspect_projection_artifacts(inventory, projection)
    blocking = _projection_cache_blocking_findings(inspect_findings, {"projection-artifact-missing"})
    if not blocking:
        return [
            Finding(
                "info",
                "navigation-cache-artifacts-current",
                "projection artifacts are current for path/reference navigation",
                ARTIFACT_DIR_REL,
            )
        ]
    reason = blocking[0]
    refresh = rebuild_projection_artifacts(inventory)
    findings = [
        Finding(
            "info",
            "navigation-cache-artifacts-refresh",
            f"refreshed disposable projection artifacts for path/reference navigation because {reason.code}",
            reason.source or ARTIFACT_DIR_REL,
            reason.line,
        )
    ]
    findings.extend(refresh)
    if any(finding.severity in {"warn", "error"} for finding in refresh):
        findings.append(
            Finding(
                "info",
                "navigation-cache-artifacts-degraded",
                "projection artifact refresh degraded; direct in-memory path search remains authoritative",
                ARTIFACT_DIR_REL,
            )
        )
    return findings


def _ensure_projection_index_for_navigation(inventory: Inventory, projection: Projection) -> list[Finding]:
    inspect_findings = inspect_projection_index(inventory, projection)
    blocking = _projection_cache_blocking_findings(inspect_findings, {"projection-index-missing"})
    if not blocking:
        return [
            Finding(
                "info",
                "navigation-cache-index-current",
                "SQLite FTS/BM25 projection index is current for full-text navigation",
                INDEX_REL_PATH,
            )
        ]
    reason = blocking[0]
    refresh = rebuild_projection_index(inventory)
    findings = [
        Finding(
            "info",
            "navigation-cache-index-refresh",
            f"refreshed disposable SQLite FTS/BM25 projection index for full-text navigation because {reason.code}",
            reason.source or INDEX_REL_PATH,
            reason.line,
        )
    ]
    findings.extend(refresh)
    if any(finding.severity in {"warn", "error"} for finding in refresh):
        findings.append(
            Finding(
                "info",
                "navigation-cache-index-degraded",
                "SQLite projection index refresh degraded; direct exact/path search remains authoritative",
                INDEX_REL_PATH,
            )
        )
    return findings


def _projection_cache_blocking_findings(findings: list[Finding], missing_codes: set[str]) -> list[Finding]:
    return [
        finding
        for finding in findings
        if finding.severity in {"warn", "error"} or finding.code in missing_codes
    ]


def _fan_in_findings(inventory: Inventory, projection: Projection) -> list[Finding]:
    if not projection.links:
        return [Finding("info", "fan-in-empty", "no repo-local references are available for fan-in analysis")]

    findings: list[Finding] = []
    rows = projection.fan_in[:FAN_IN_RESULT_LIMIT]
    for row in rows:
        severity = "warn" if row.status == "missing" else "info"
        sources = ", ".join(row.sources[:5])
        findings.append(
            Finding(
                severity,
                "fan-in-target",
                f"{row.target}: inbound={row.inbound_count}; status={row.status}; sources={sources}",
                row.source,
            )
        )
    if len(projection.fan_in) > FAN_IN_RESULT_LIMIT:
        findings.append(Finding("info", "fan-in-truncated", f"showing top {FAN_IN_RESULT_LIMIT} referenced paths by inbound count"))

    budget_warnings = [finding for finding in context_budget_findings(inventory) if finding.severity == "warn"]
    if budget_warnings:
        findings.append(Finding("info", "fan-in-context-pressure", f"context-budget warning count: {len(budget_warnings)}"))
    else:
        findings.append(Finding("info", "fan-in-context-pressure", "context-budget has no warning-level pressure signals"))
    return findings


def _projection_findings(inventory: Inventory, projection: Projection) -> list[Finding]:
    summary = projection.summary
    findings = [
        Finding(
            "info",
            "projection-rebuild",
            f"{summary.rebuild_status}; in-memory storage boundary={summary.storage_boundary}; artifact boundary={ARTIFACT_DIR_REL}",
        ),
        Finding(
            "info",
            "projection-authority",
            "repo-visible files remain authoritative; generated artifacts are disposable and never approve repairs, closeout, commits, or lifecycle decisions",
        ),
        Finding(
            "info",
            "projection-source-coverage",
            (
                f"sources={summary.present_source_count}/{summary.source_count} present; "
                f"hashed={summary.hashed_source_count}/{summary.readable_source_count} readable; "
                f"missing_required={summary.missing_required_count}"
            ),
        ),
        Finding(
            "info",
            "projection-record-counts",
            (
                f"source_records={summary.source_count}; link_records={summary.link_record_count}; "
                f"fan_in_records={summary.fan_in_record_count}; relationship_nodes={summary.relationship_node_count}; "
                f"relationship_edges={summary.relationship_edge_count}"
            ),
        ),
    ]
    provenance = _projection_provenance(projection)
    if provenance:
        findings.append(Finding("info", "projection-provenance", f"source hashes: {provenance}"))
    findings.extend(inspect_projection_artifacts(inventory, projection))
    findings.extend(inspect_projection_index(inventory, projection))
    for source in projection.sources:
        if source.required and not source.present:
            findings.append(Finding("warn", "projection-source-missing", f"missing required projection source: {source.path}", source.path))
        if source.read_error:
            findings.append(Finding("warn", "projection-source-read-error", f"{source.path}: {source.read_error}", source.path))
    return findings


def _projection_provenance(projection: Projection, limit: int = 5) -> str:
    rows = [
        f"{source.path}@{_display_hash(source.content_hash)}"
        for source in projection.sources
        if source.content_hash is not None
    ]
    return ", ".join(rows[:limit])


def _display_hash(value: str | None) -> str:
    return value[:12] if value else "none"


def _trim_line(line: str, limit: int = 140) -> str:
    compact = re.sub(r"\s+", " ", line.strip())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _unique_sorted(values) -> list[str]:
    return sorted(set(values))


def doctor_findings(root: Path, inventory: Inventory) -> list[Finding]:
    hygiene = product_hygiene_findings(inventory)
    hygiene_warnings = [finding for finding in hygiene if finding.severity in {"warn", "error"}]
    relationship_hygiene = relationship_hygiene_scan_findings(inventory)
    relationship_warnings = [finding for finding in relationship_hygiene if finding.severity in {"warn", "error"}]
    findings: list[Finding] = [
        Finding("info", "python", f"python: {sys.version.split()[0]}"),
        Finding("info", "root", f"root exists: {root}"),
    ]
    findings.extend(_git_findings(root))
    findings.extend(hygiene)
    findings.extend(relationship_hygiene)
    validation = validation_findings(inventory)
    link_warnings = [finding for finding in audit_link_findings(inventory) if finding.severity in {"warn", "error"}]
    context_warnings = [finding for finding in context_budget_findings(inventory) if finding.severity in {"warn", "error"}]
    error_count = len([finding for finding in validation if finding.severity == "error"])
    warning_count = len([finding for finding in validation if finding.severity == "warn"])
    findings.append(
        Finding(
            "error" if error_count else "warn" if warning_count else "info",
            "validate-summary",
            f"validate findings: {error_count} errors, {warning_count} warnings",
        )
    )
    findings.append(
        Finding(
            "warn" if hygiene_warnings else "info",
            "product-hygiene-summary",
            f"product hygiene warnings/errors: {len(hygiene_warnings)}",
        )
    )
    findings.append(
        Finding(
            "warn" if relationship_warnings else "info",
            "relationship-hygiene-summary",
            f"relationship hygiene warnings/errors: {len(relationship_warnings)}",
        )
    )
    findings.append(
        Finding(
            "warn" if link_warnings else "info",
            "audit-links-summary",
            f"audit-links warnings/errors: {len(link_warnings)}",
        )
    )
    findings.append(
        Finding(
            "warn" if context_warnings else "info",
            "context-budget-summary",
            f"context-budget warnings/errors: {len(context_warnings)}",
        )
    )
    return findings


WORKFLOW_ATTACH_DIRECTORIES = (
    ".agents",
    ".codex",
    "project/specs/workflow",
    "project/research",
    "project/plan-incubation",
    "project/archive/plans",
    "project/archive/reference",
)

DETACH_PRESERVED_AUTHORITY_PATHS = (
    ".codex/project-workflow.toml",
    "project/project-state.md",
    ".agents/docmap.yaml",
    "project/specs/workflow/",
    "project/archive/",
    "project/research/",
    ".mylittleharness/snapshots/repair/",
)
DETACH_MARKER_DIR_REL = ".mylittleharness/detach"
DETACH_MARKER_REL_PATH = f"{DETACH_MARKER_DIR_REL}/disabled.json"
DETACH_MARKER_SCHEMA_VERSION = 1
DETACH_MARKER_MANUAL_RECOVERY = f"manual recovery only: remove {DETACH_MARKER_REL_PATH} to clear the marker; preserved repo-visible authority files remain the source of truth"
DETACH_MARKER_NON_AUTHORITY = "detach marker is informational evidence only and cannot approve cleanup, repair, closeout, archive, commit, rollback, lifecycle decisions, or future mutations"


def detach_dry_run_sections(inventory: Inventory) -> list[tuple[str, list[Finding]]]:
    return [
        ("Root Posture", _detach_root_posture_findings(inventory)),
        ("Preservation", _detach_preservation_findings(inventory)),
        ("Marker", _detach_marker_preview_findings(inventory)),
        ("Generated Projection", _detach_generated_projection_findings(inventory)),
        ("Manual Recovery", _detach_recovery_findings()),
        ("Boundary", _detach_boundary_findings(inventory)),
    ]


def detach_apply_sections(inventory: Inventory) -> list[tuple[str, list[Finding]]]:
    return [
        ("Root Posture", _detach_apply_root_findings(inventory)),
        ("Preservation", _detach_preservation_findings(inventory)),
        ("Marker", _detach_marker_apply_findings(inventory)),
        ("Generated Projection", _detach_generated_projection_findings(inventory)),
        ("Manual Recovery", _detach_apply_recovery_findings()),
        ("Boundary", _detach_apply_boundary_findings(inventory)),
    ]


def _detach_root_posture_findings(inventory: Inventory) -> list[Finding]:
    findings = [
        Finding("info", "detach-dry-run", "detach preview only; no files, reports, caches, generated outputs, snapshots, Git state, config, hooks, or package artifacts are written"),
        Finding("info", "detach-root-kind", f"root kind: {inventory.root_kind}"),
    ]
    if _is_product_source_inventory(inventory):
        findings.append(
            Finding(
                "info",
                "detach-root-posture",
                "product-source compatibility fixture: detach reports fixture preservation only; future detach apply would be refused",
                inventory.state.rel_path if inventory.state else None,
            )
        )
    elif _is_fallback_or_archive_inventory(inventory):
        findings.append(
            Finding(
                "warn",
                "detach-refused",
                "target is fallback/archive or generated-output evidence; future detach apply would be refused before mutation",
                inventory.state.rel_path if inventory.state else None,
            )
        )
    elif inventory.root_kind == "live_operating_root":
        findings.append(Finding("info", "detach-root-posture", "live operating root: detach dry-run reports preservation and future-apply refusal posture only"))
    else:
        findings.append(Finding("warn", "detach-refused", "target role is ambiguous; future detach apply would be refused before mutation"))

    manifest = inventory.manifest_surface
    if manifest is None or not manifest.exists:
        findings.append(Finding("warn", "detach-refused", "workflow manifest is missing; future detach apply would be refused", ".codex/project-workflow.toml"))
    elif manifest.read_error:
        findings.append(Finding("warn", "detach-refused", f"workflow manifest is unreadable: {manifest.read_error}", manifest.rel_path))
    for error in inventory.manifest_errors:
        findings.append(Finding("warn", "detach-refused", f"workflow manifest is malformed: {error}", manifest.rel_path if manifest else ".codex/project-workflow.toml"))

    state = inventory.state
    if state is None or not state.exists:
        findings.append(Finding("warn", "detach-refused", "project state is missing; future detach apply would be refused", "project/project-state.md"))
    elif state.read_error:
        findings.append(Finding("warn", "detach-refused", f"project state is unreadable: {state.read_error}", state.rel_path))

    memory = inventory.manifest.get("memory", {}) if inventory.manifest else {}
    state_file = str(memory.get("state_file", "project/project-state.md")).replace("\\", "/")
    plan_file = str(memory.get("plan_file", "project/implementation-plan.md")).replace("\\", "/")
    if state_file != "project/project-state.md":
        findings.append(Finding("warn", "detach-refused", f"non-default state_file is preserved and future detach apply is refused: {state_file}", manifest.rel_path if manifest else None))
    if plan_file != "project/implementation-plan.md":
        findings.append(Finding("warn", "detach-refused", f"non-default plan_file is preserved and future detach apply is refused: {plan_file}", manifest.rel_path if manifest else None))
    return findings


def _detach_apply_root_findings(inventory: Inventory) -> list[Finding]:
    findings = [
        Finding("info", "detach-apply", "detach apply is marker-only; it never deletes, rewrites, archives, repairs, cleans, commits, or mutates Git/config/hooks/CI/package/workstation state"),
        Finding("info", "detach-root-kind", f"root kind: {inventory.root_kind}"),
    ]
    findings.extend(_detach_apply_refusal_findings(inventory))
    return findings


def _detach_preservation_findings(inventory: Inventory) -> list[Finding]:
    findings = [
        Finding("info", "detach-preservation-policy", "preservation beats cleanup; repo-visible authority remains inspectable"),
        Finding("info", "detach-disable-candidate", "no disable marker, metadata toggle, rewritten file, removed path, archive move, or cleanup candidate is selected in this dry-run"),
    ]
    for rel_path in DETACH_PRESERVED_AUTHORITY_PATHS:
        path = inventory.root / rel_path.rstrip("/")
        status = "present" if path.exists() else "absent"
        findings.append(Finding("info", "detach-preserve", f"preserve {status} path: {rel_path}", rel_path.rstrip("/")))
    return findings


def _detach_marker_preview_findings(inventory: Inventory) -> list[Finding]:
    findings = [
        Finding("info", "detach-marker-target", f"marker-only apply target: {DETACH_MARKER_REL_PATH}", DETACH_MARKER_REL_PATH),
        Finding("info", "detach-marker-preview", "detach --dry-run creates no marker; detach --apply may create this file only in an eligible live operating root", DETACH_MARKER_REL_PATH),
        Finding("info", "detach-marker-authority", DETACH_MARKER_NON_AUTHORITY, DETACH_MARKER_REL_PATH),
    ]
    marker = inventory.surface_by_rel.get(DETACH_MARKER_REL_PATH)
    if marker and marker.exists:
        findings.extend(_detach_marker_status_findings(inventory, marker))
    return findings


def _detach_marker_apply_findings(inventory: Inventory) -> list[Finding]:
    findings = [Finding("info", "detach-marker-target", f"marker-only apply target: {DETACH_MARKER_REL_PATH}", DETACH_MARKER_REL_PATH)]
    preflight_errors = _detach_apply_refusal_findings(inventory) + _detach_apply_path_conflict_findings(inventory)
    if preflight_errors:
        findings.extend(preflight_errors)
        return findings

    target = inventory.root / DETACH_MARKER_REL_PATH
    if target.exists():
        marker_error = _detach_marker_validation_error(inventory, target)
        if marker_error:
            findings.append(marker_error)
        else:
            findings.append(Finding("info", "detach-marker-unchanged", f"valid detach marker already exists and was left unchanged: {DETACH_MARKER_REL_PATH}", DETACH_MARKER_REL_PATH))
            findings.append(Finding("info", "detach-marker-authority", DETACH_MARKER_NON_AUTHORITY, DETACH_MARKER_REL_PATH))
        return findings

    payload = _detach_marker_payload(inventory, _current_marker_timestamp())
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        findings.append(Finding("error", "detach-marker-refused", f"failed to create detach marker before apply completed: {exc}", DETACH_MARKER_REL_PATH))
        return findings

    findings.extend(
        [
            Finding("info", "detach-marker-created", f"created marker-only detach evidence: {DETACH_MARKER_REL_PATH}", DETACH_MARKER_REL_PATH),
            Finding("info", "detach-marker-status", "status: disabled", DETACH_MARKER_REL_PATH),
            Finding("info", "detach-marker-recovery", DETACH_MARKER_MANUAL_RECOVERY, DETACH_MARKER_REL_PATH),
            Finding("info", "detach-marker-authority", DETACH_MARKER_NON_AUTHORITY, DETACH_MARKER_REL_PATH),
        ]
    )
    return findings


def _detach_generated_projection_findings(inventory: Inventory) -> list[Finding]:
    projection_path = inventory.root / ARTIFACT_DIR_REL
    if projection_path.exists() and (projection_path.is_symlink() or not projection_path.is_dir()):
        return [
            Finding("warn", "detach-boundary-conflict", f"generated projection boundary is not a directory: {ARTIFACT_DIR_REL}", ARTIFACT_DIR_REL),
            Finding("info", "detach-generated-projection", "generated projection cleanup is not proposed by detach dry-run"),
        ]
    if projection_path.exists():
        return [
            Finding("info", "detach-generated-projection", f"disposable generated projection boundary is present and preserved: {ARTIFACT_DIR_REL}", ARTIFACT_DIR_REL),
            Finding("info", "detach-generated-projection-authority", "generated projections remain build-to-delete speedups and cannot approve detach, repair, closeout, archive, commit, lifecycle decisions"),
        ]
    return [
        Finding("info", "detach-generated-projection", f"disposable generated projection boundary is absent and no cleanup is proposed: {ARTIFACT_DIR_REL}", ARTIFACT_DIR_REL),
        Finding("info", "detach-generated-projection-authority", "generated projections remain build-to-delete speedups and are preserved when present"),
    ]


def _detach_recovery_findings() -> list[Finding]:
    return [
        Finding("info", "detach-recovery", "no detach mutation occurred; recovery starts from preserved repo-visible files and normal source control or operator backups"),
        Finding("info", "detach-apply-marker-only", "detach --apply creates or reuses only the marker file in eligible live operating roots; preserved authority files remain the source of truth"),
        Finding("info", "detach-disable-terminology", "disable is explanatory terminology for a possible future effect, not a CLI command or alias in this slice"),
    ]


def _detach_apply_recovery_findings() -> list[Finding]:
    return [
        Finding("info", "detach-recovery", DETACH_MARKER_MANUAL_RECOVERY, DETACH_MARKER_REL_PATH),
        Finding("info", "detach-apply-marker-only", "detach --apply creates or reuses only the marker file; preserved authority files, generated projections, archives, research, and repair snapshots are not changed"),
        Finding("info", "detach-disable-terminology", "disable is explanatory terminology for the marker effect, not a CLI command or alias"),
    ]


def _detach_boundary_findings(inventory: Inventory) -> list[Finding]:
    findings = [
        Finding("info", "detach-read-only", "detach --dry-run writes no files, reports, caches, generated outputs, snapshots, Git state, config, hooks, CI files, package artifacts, or workstation state"),
        Finding("info", "detach-no-authority", "detach dry-run output cannot approve cleanup, repair, closeout, archive, commit, lifecycle decisions, or future mutations"),
    ]
    findings.extend(_detach_path_conflict_findings(inventory))
    return findings


def _detach_apply_boundary_findings(inventory: Inventory) -> list[Finding]:
    findings = [
        Finding("info", "detach-apply-boundary", f"detach --apply may create only {DETACH_MARKER_REL_PATH}", DETACH_MARKER_REL_PATH),
        Finding("info", "detach-no-authority", DETACH_MARKER_NON_AUTHORITY, DETACH_MARKER_REL_PATH),
    ]
    findings.extend(_detach_apply_path_conflict_findings(inventory))
    return findings


def _detach_path_conflict_findings(inventory: Inventory, severity: str = "warn") -> list[Finding]:
    checks = {
        ".codex": "dir",
        ".codex/project-workflow.toml": "file",
        "project": "dir",
        "project/project-state.md": "file",
        ".agents": "dir",
        ".agents/docmap.yaml": "file",
        "project/specs/workflow": "dir",
        "project/archive": "dir",
        "project/research": "dir",
        ".mylittleharness": "dir",
        ".mylittleharness/generated": "dir",
        ARTIFACT_DIR_REL: "dir",
        ".mylittleharness/snapshots/repair": "dir",
    }
    findings: list[Finding] = []
    for rel_path, expected_kind in checks.items():
        path = inventory.root / rel_path
        if path.is_symlink():
            findings.append(Finding(severity, "detach-boundary-conflict", f"path contains a symlink and is preserved without mutation: {rel_path}", rel_path))
            continue
        if not path.exists():
            continue
        if expected_kind == "dir" and not path.is_dir():
            findings.append(Finding(severity, "detach-boundary-conflict", f"expected directory path is not a directory and is preserved without mutation: {rel_path}", rel_path))
        if expected_kind == "file" and not path.is_file():
            findings.append(Finding(severity, "detach-boundary-conflict", f"expected file path is not a file and is preserved without mutation: {rel_path}", rel_path))
    return findings


def _detach_apply_path_conflict_findings(inventory: Inventory) -> list[Finding]:
    findings = _detach_path_conflict_findings(inventory, severity="error")
    marker_conflict = _detach_marker_target_conflict(inventory.root)
    if marker_conflict:
        findings.append(marker_conflict)
    return findings


def _detach_apply_refusal_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    if _is_product_source_inventory(inventory):
        findings.append(Finding("error", "detach-refused", "target is a product-source compatibility fixture; detach --apply is refused before mutation", inventory.state.rel_path if inventory.state else None))
    elif _is_fallback_or_archive_inventory(inventory):
        findings.append(Finding("error", "detach-refused", "target is fallback/archive or generated-output evidence; detach --apply is refused before mutation", inventory.state.rel_path if inventory.state else None))
    elif inventory.root_kind != "live_operating_root":
        findings.append(Finding("error", "detach-refused", f"target root kind is {inventory.root_kind}; detach --apply requires an explicit live operating root"))

    manifest = inventory.manifest_surface
    if manifest is None or not manifest.exists:
        findings.append(Finding("error", "detach-refused", "workflow manifest is missing; detach --apply is refused", ".codex/project-workflow.toml"))
    elif manifest.read_error:
        findings.append(Finding("error", "detach-refused", f"workflow manifest is unreadable: {manifest.read_error}", manifest.rel_path))
    for error in inventory.manifest_errors:
        findings.append(Finding("error", "detach-refused", f"workflow manifest is malformed: {error}", manifest.rel_path if manifest else ".codex/project-workflow.toml"))
    if inventory.manifest and inventory.manifest.get("workflow") != "workflow-core":
        findings.append(Finding("error", "detach-refused", "detach --apply requires manifest workflow = workflow-core", manifest.rel_path if manifest else ".codex/project-workflow.toml"))

    state = inventory.state
    if state is None or not state.exists:
        findings.append(Finding("error", "detach-refused", "project state is missing; detach --apply is refused", "project/project-state.md"))
    elif state.read_error:
        findings.append(Finding("error", "detach-refused", f"project state is unreadable: {state.read_error}", state.rel_path))

    memory = inventory.manifest.get("memory", {}) if inventory.manifest else {}
    state_file = str(memory.get("state_file", "project/project-state.md")).replace("\\", "/")
    plan_file = str(memory.get("plan_file", "project/implementation-plan.md")).replace("\\", "/")
    if state_file != "project/project-state.md":
        findings.append(Finding("error", "detach-refused", f"non-default state_file is preserved and detach --apply is refused: {state_file}", manifest.rel_path if manifest else None))
    if plan_file != "project/implementation-plan.md":
        findings.append(Finding("error", "detach-refused", f"non-default plan_file is preserved and detach --apply is refused: {plan_file}", manifest.rel_path if manifest else None))
    return findings


def _detach_marker_target_conflict(root: Path) -> Finding | None:
    target = root / DETACH_MARKER_REL_PATH
    for candidate in _root_relative_path_chain(root, DETACH_MARKER_REL_PATH):
        candidate_rel = candidate.relative_to(root).as_posix()
        if candidate.is_symlink():
            return Finding("error", "detach-marker-refused", f"marker path contains a symlink segment: {candidate_rel}", candidate_rel)
        if candidate != target and candidate.exists() and not candidate.is_dir():
            return Finding("error", "detach-marker-refused", f"marker path contains a non-directory segment: {candidate_rel}", candidate_rel)
    if target.exists() and not target.is_file():
        return Finding("error", "detach-marker-refused", f"marker path is not a regular file: {DETACH_MARKER_REL_PATH}", DETACH_MARKER_REL_PATH)
    if not _path_stays_within_root(root, target):
        return Finding("error", "detach-marker-refused", f"marker path would escape the target root: {DETACH_MARKER_REL_PATH}", DETACH_MARKER_REL_PATH)
    return None


def _detach_marker_status_findings(inventory: Inventory, marker: Surface) -> list[Finding]:
    if marker.read_error:
        return [Finding("warn", "detach-marker-invalid", f"detach marker could not be read: {marker.read_error}", marker.rel_path)]
    marker_error = _detach_marker_validation_error(inventory, marker.path)
    if marker_error:
        return [Finding("warn", "detach-marker-invalid", marker_error.message, marker.rel_path)]
    return [
        Finding("info", "detach-marker-present", f"detach marker present: {DETACH_MARKER_REL_PATH}", DETACH_MARKER_REL_PATH),
        Finding("info", "detach-marker-status", "status: disabled", DETACH_MARKER_REL_PATH),
        Finding("info", "detach-marker-authority", DETACH_MARKER_NON_AUTHORITY, DETACH_MARKER_REL_PATH),
    ]


def _detach_marker_validation_error(inventory: Inventory, path: Path) -> Finding | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return Finding("error", "detach-marker-refused", f"existing detach marker is unreadable or invalid JSON: {exc}", DETACH_MARKER_REL_PATH)
    if not isinstance(payload, dict):
        return Finding("error", "detach-marker-refused", "existing detach marker payload must be a JSON object", DETACH_MARKER_REL_PATH)
    expected_values = {
        "schema_version": DETACH_MARKER_SCHEMA_VERSION,
        "status": "disabled",
        "command": "detach --apply",
        "marker_path": DETACH_MARKER_REL_PATH,
        "manual_recovery": DETACH_MARKER_MANUAL_RECOVERY,
        "non_authority": DETACH_MARKER_NON_AUTHORITY,
    }
    for key, expected in expected_values.items():
        if payload.get(key) != expected:
            return Finding("error", "detach-marker-refused", f"existing detach marker has unexpected {key}: {payload.get(key)!r}", DETACH_MARKER_REL_PATH)
    if not isinstance(payload.get("created_at_utc"), str) or not payload.get("created_at_utc"):
        return Finding("error", "detach-marker-refused", "existing detach marker is missing created_at_utc", DETACH_MARKER_REL_PATH)
    if not _same_path_value(payload.get("root"), inventory.root):
        return Finding("error", "detach-marker-refused", f"existing detach marker root does not match target root: {payload.get('root')!r}", DETACH_MARKER_REL_PATH)
    if payload.get("preserved_authority_paths") != list(DETACH_PRESERVED_AUTHORITY_PATHS):
        return Finding("error", "detach-marker-refused", "existing detach marker preserved_authority_paths do not match the current contract", DETACH_MARKER_REL_PATH)
    return None


def _detach_marker_payload(inventory: Inventory, timestamp: str) -> dict[str, object]:
    return {
        "schema_version": DETACH_MARKER_SCHEMA_VERSION,
        "status": "disabled",
        "command": "detach --apply",
        "root": str(inventory.root),
        "marker_path": DETACH_MARKER_REL_PATH,
        "created_at_utc": timestamp,
        "preserved_authority_paths": list(DETACH_PRESERVED_AUTHORITY_PATHS),
        "manual_recovery": DETACH_MARKER_MANUAL_RECOVERY,
        "non_authority": DETACH_MARKER_NON_AUTHORITY,
    }


def _current_marker_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def attach_dry_run_findings(inventory: Inventory, project_name: str | None = None) -> list[Finding]:
    findings: list[Finding] = [
        Finding("info", "dry-run", "attach proposal only; no files or directories were written"),
        Finding("info", "mutation-guard", "use attach --apply for explicit create-only scaffold writes"),
    ]
    if _is_product_source_inventory(inventory):
        findings.append(
            Finding(
                "info",
                "attach-scope",
                "target is a product-source compatibility fixture; operating-root scaffold expansion is intentionally not proposed",
                inventory.state.rel_path if inventory.state else None,
            )
        )
        findings.append(
            Finding(
                "info",
                "attach-proposal",
                "no-op: keep product source clean and attach live operating roots from an explicit operating root",
            )
        )
        return findings

    if _is_fallback_or_archive_inventory(inventory):
        findings.append(
            Finding(
                "warn",
                "attach-refused",
                "target is fallback/archive or generated-output evidence; attach --apply would be refused before mutation",
                inventory.state.rel_path if inventory.state else None,
            )
        )
        return findings

    normalized_project = _normalize_project_name(project_name)
    if _is_attach_already_attached_live_root(inventory, normalized_project):
        findings.extend(_attach_already_attached_dry_run_findings())
        return findings

    state_path = inventory.root / ATTACH_STATE_REL_PATH
    if not state_path.exists() and normalized_project is None:
        findings.append(
            Finding(
                "warn",
                "attach-project-required",
                "--project <name> would be required because project/project-state.md would be created",
                ATTACH_STATE_REL_PATH,
            )
        )

    preflight_errors = _attach_apply_preflight_errors(inventory, normalized_project)
    if preflight_errors:
        findings.extend(
            Finding(
                "warn",
                error.code,
                f"attach --apply would be refused before mutation: {error.message}",
                error.source,
                error.line,
            )
            for error in preflight_errors
        )
        return findings

    missing_dirs = [rel_path for rel_path in WORKFLOW_ATTACH_DIRECTORIES if not (inventory.root / rel_path).exists()]
    if missing_dirs:
        for rel_path in missing_dirs:
            findings.append(Finding("warn", "attach-proposal", f"would create scaffold directory: {rel_path}", rel_path))
    else:
        findings.append(Finding("info", "attach-proposal", "all eager scaffold directories are already present"))

    for surface in inventory.surfaces:
        if surface.required and not surface.exists:
            findings.append(Finding("warn", "attach-proposal", f"would require file content for missing surface: {surface.rel_path}", surface.rel_path))

    if not any(finding.code == "attach-proposal" and finding.severity == "warn" for finding in findings):
        findings.append(Finding("info", "attach-proposal", "no missing required surfaces were found"))
    return findings


ATTACH_MANIFEST_REL_PATH = ".codex/project-workflow.toml"
ATTACH_STATE_REL_PATH = "project/project-state.md"


def attach_apply_findings(inventory: Inventory, project_name: str | None) -> list[Finding]:
    if _is_product_source_inventory(inventory):
        return [
            Finding(
                "error",
                "attach-refused",
                "target is a product-source compatibility fixture; attach --apply is refused",
                inventory.state.rel_path if inventory.state else ATTACH_STATE_REL_PATH,
            )
        ]
    if _is_fallback_or_archive_inventory(inventory):
        return [
            Finding(
                "error",
                "attach-refused",
                "target is fallback/archive or generated-output evidence; attach --apply is refused",
                inventory.state.rel_path if inventory.state else ATTACH_STATE_REL_PATH,
            )
        ]

    normalized_project = _normalize_project_name(project_name)
    if _is_attach_already_attached_live_root(inventory, normalized_project):
        return _attach_already_attached_apply_findings()

    state_path = inventory.root / ATTACH_STATE_REL_PATH
    if not state_path.exists() and normalized_project is None:
        return [
            Finding(
                "error",
                "attach-project-required",
                "--project <name> is required because project/project-state.md would be created",
                ATTACH_STATE_REL_PATH,
            )
        ]

    errors = _attach_apply_preflight_errors(inventory, normalized_project)
    errors.extend(_attach_generated_projection_preflight_errors(inventory))
    if errors:
        return errors

    findings: list[Finding] = [Finding("info", "attach-apply", "create-only attach apply started")]
    created_paths: list[str] = []
    existing_paths: list[str] = []

    for rel_path in WORKFLOW_ATTACH_DIRECTORIES:
        path = inventory.root / rel_path
        if path.exists():
            existing_paths.append(rel_path)
            continue
        path.mkdir(parents=True, exist_ok=False)
        created_paths.append(rel_path)

    templates = _attach_apply_templates(normalized_project, inventory)
    for rel_path, content in templates.items():
        path = inventory.root / rel_path
        if path.exists():
            existing_paths.append(rel_path)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        created_paths.append(rel_path)

    for rel_path in created_paths:
        findings.append(Finding("info", "attach-created", f"created create-only attach path: {rel_path}", rel_path))
    for rel_path in existing_paths:
        findings.append(Finding("info", "attach-existing", f"preserved existing attach path without changes: {rel_path}", rel_path))
    if not created_paths:
        findings.append(Finding("info", "attach-unchanged", "no file or directory changes were needed"))
    findings.append(
        Finding(
            "info",
            "attach-apply-boundary",
            "attach --apply wrote eager scaffold directories, absent manifest/state templates, and attach-time disposable generated projection output",
        )
    )
    refreshed_inventory = load_inventory(inventory.root)
    findings.extend(_attach_generated_projection_findings(refreshed_inventory))
    return findings


def _attach_generated_projection_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = [
        Finding(
            "info",
            "attach-generated-projection-boundary",
            f"attach-time generated projection boundary: {ARTIFACT_DIR_REL}",
            ARTIFACT_DIR_REL,
        )
    ]
    artifact_findings = build_projection_artifacts(inventory)
    index_findings = build_projection_index(inventory)
    build_findings = artifact_findings + index_findings
    if any(finding.severity == "error" for finding in build_findings):
        findings.append(
            Finding(
                "error",
                "attach-generated-projection-refused",
                "attach-time generated projection setup was refused by the owned boundary preflight",
                ARTIFACT_DIR_REL,
            )
        )
    elif any(finding.code in {"projection-index-fts5-unavailable", "projection-index-build-failed"} for finding in index_findings):
        findings.append(
            Finding(
                "warn",
                "attach-generated-projection-unavailable",
                f"SQLite FTS/BM25 index was unavailable; JSON projection artifacts were built and no current index is required: {INDEX_REL_PATH}",
                INDEX_REL_PATH,
            )
        )
    elif any(finding.code == "projection-index-build" for finding in index_findings):
        findings.append(
            Finding(
                "info",
                "attach-generated-projection-build",
                f"built schema v2 JSON projection artifacts and SQLite FTS/BM25 index: {INDEX_REL_PATH}",
                INDEX_REL_PATH,
            )
        )
    else:
        findings.append(
            Finding(
                "info",
                "attach-generated-projection-skipped",
                "attach-time generated projection setup completed without a SQLite build finding",
                ARTIFACT_DIR_REL,
            )
        )
    findings.extend(build_findings)
    return findings


def _attach_generated_projection_preflight_errors(inventory: Inventory) -> list[Finding]:
    errors: list[Finding] = []
    root_resolved = inventory.root.resolve()
    current = inventory.root
    for part in ARTIFACT_DIR_REL.split("/"):
        current = current / part
        rel_path = current.relative_to(inventory.root).as_posix()
        if current.is_symlink():
            errors.append(
                Finding(
                    "error",
                    "attach-generated-projection-refused",
                    f"cannot create attach-time generated projection because a symlink segment exists: {rel_path}",
                    rel_path,
                )
            )
            return errors
        if current.exists() and not current.is_dir():
            errors.append(
                Finding(
                    "error",
                    "attach-generated-projection-refused",
                    f"cannot create attach-time generated projection because a non-directory segment exists: {rel_path}",
                    rel_path,
                )
            )
            return errors

    projection_dir = inventory.root / ARTIFACT_DIR_REL
    if projection_dir.exists():
        try:
            projection_dir.resolve().relative_to(root_resolved)
        except ValueError:
            errors.append(
                Finding(
                    "error",
                    "attach-generated-projection-refused",
                    f"attach-time generated projection boundary escapes target root: {ARTIFACT_DIR_REL}",
                    ARTIFACT_DIR_REL,
                )
            )
    return errors


def _attach_already_attached_dry_run_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "attach-already-attached",
            "already-attached live operating root: default workflow manifest and project-state authority are readable; no create-only attach changes are proposed",
            ATTACH_STATE_REL_PATH,
        ),
        Finding("info", "attach-existing", f"existing workflow manifest authority: {ATTACH_MANIFEST_REL_PATH}", ATTACH_MANIFEST_REL_PATH),
        Finding("info", "attach-existing", f"existing project-state authority: {ATTACH_STATE_REL_PATH}", ATTACH_STATE_REL_PATH),
        Finding("info", "attach-proposal", "no-op: root is already attached; first-run template conflict checks and generated projection setup are skipped"),
    ]


def _attach_already_attached_apply_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "attach-already-attached",
            "already-attached live operating root; attach --apply left repo-visible authority and generated projection output unchanged",
            ATTACH_STATE_REL_PATH,
        ),
        Finding("info", "attach-existing", f"preserved workflow manifest authority: {ATTACH_MANIFEST_REL_PATH}", ATTACH_MANIFEST_REL_PATH),
        Finding("info", "attach-existing", f"preserved project-state authority: {ATTACH_STATE_REL_PATH}", ATTACH_STATE_REL_PATH),
        Finding("info", "attach-unchanged", "no file, directory, or generated projection changes were needed"),
        Finding("info", "attach-apply-boundary", "already-attached apply is a true no-op; create-only template and attach-time generated projection writes were skipped"),
    ]


def _is_attach_already_attached_live_root(inventory: Inventory, project_name: str | None) -> bool:
    if not _has_default_attach_authority(inventory):
        return False
    if _attach_apply_preflight_errors(inventory, project_name, allow_existing_template_content=True):
        return False
    if _attach_generated_projection_preflight_errors(inventory):
        return False
    return True


def _has_default_attach_authority(inventory: Inventory) -> bool:
    if inventory.root_kind != "live_operating_root":
        return False

    manifest = inventory.manifest_surface
    if manifest is None or not manifest.exists or manifest.read_error or inventory.manifest_errors:
        return False
    if inventory.manifest.get("workflow") != "workflow-core":
        return False

    memory = inventory.manifest.get("memory", {}) if isinstance(inventory.manifest, dict) else {}
    state_file = str(memory.get("state_file", ATTACH_STATE_REL_PATH)).replace("\\", "/")
    plan_file = str(memory.get("plan_file", "project/implementation-plan.md")).replace("\\", "/")
    if state_file != ATTACH_STATE_REL_PATH or plan_file != "project/implementation-plan.md":
        return False

    state = inventory.surface_by_rel.get(ATTACH_STATE_REL_PATH)
    if state is None or not state.exists or state.read_error or state.frontmatter.errors:
        return False
    if state.frontmatter.has_frontmatter:
        data = state.frontmatter.data
        required = ("project", "workflow", "operating_mode", "plan_status")
        return all(data.get(key) for key in required) and data.get("workflow") == "workflow-core"
    return _has_read_only_state_assignments(state)


def _attach_existing_authority_preflight_errors(inventory: Inventory) -> list[Finding]:
    errors: list[Finding] = []
    manifest = inventory.manifest_surface
    if manifest and manifest.exists:
        if manifest.read_error:
            errors.append(Finding("error", "attach-refused", f"workflow manifest is unreadable: {manifest.read_error}", manifest.rel_path))
        for error in inventory.manifest_errors:
            errors.append(Finding("error", "attach-refused", f"workflow manifest is malformed: {error}", manifest.rel_path))
        if inventory.manifest and inventory.manifest.get("workflow") != "workflow-core":
            errors.append(Finding("error", "attach-refused", "attach requires manifest workflow = workflow-core when a workflow manifest already exists", manifest.rel_path))
        memory = inventory.manifest.get("memory", {}) if inventory.manifest else {}
        state_file = str(memory.get("state_file", ATTACH_STATE_REL_PATH)).replace("\\", "/")
        plan_file = str(memory.get("plan_file", "project/implementation-plan.md")).replace("\\", "/")
        if state_file != ATTACH_STATE_REL_PATH:
            errors.append(Finding("error", "attach-refused", f"non-default state_file is preserved and attach is refused: {state_file}", manifest.rel_path))
        if plan_file != "project/implementation-plan.md":
            errors.append(Finding("error", "attach-refused", f"non-default plan_file is preserved and attach is refused: {plan_file}", manifest.rel_path))

    state = inventory.state
    if state and state.exists:
        if state.read_error:
            errors.append(Finding("error", "attach-refused", f"project state is unreadable: {state.read_error}", state.rel_path))
        for error in state.frontmatter.errors:
            errors.append(Finding("error", "attach-refused", f"project state frontmatter is malformed: {error}", state.rel_path))
    return errors


def _attach_detach_marker_preflight_errors(inventory: Inventory) -> list[Finding]:
    marker = inventory.surface_by_rel.get(DETACH_MARKER_REL_PATH)
    if marker and marker.exists:
        return [
            Finding(
                "error",
                "attach-refused",
                f"target has a detach disabled marker; remove {DETACH_MARKER_REL_PATH} manually before init/attach mutation",
                DETACH_MARKER_REL_PATH,
            )
        ]
    return []


def _attach_apply_preflight_errors(inventory: Inventory, project_name: str | None, *, allow_existing_template_content: bool = False) -> list[Finding]:
    errors: list[Finding] = []
    errors.extend(_attach_existing_authority_preflight_errors(inventory))
    errors.extend(_attach_detach_marker_preflight_errors(inventory))
    seen_directory_segments: set[str] = set()
    for rel_path in WORKFLOW_ATTACH_DIRECTORIES:
        for candidate in _root_relative_path_chain(inventory.root, rel_path):
            candidate_rel = candidate.relative_to(inventory.root).as_posix()
            if candidate_rel in seen_directory_segments:
                continue
            seen_directory_segments.add(candidate_rel)
            if candidate.is_symlink():
                errors.append(
                    Finding(
                        "error",
                        "attach-target-conflict",
                        f"cannot create scaffold directory because a symlink segment exists: {candidate_rel}",
                        candidate_rel,
                    )
                )
            elif candidate.exists() and not candidate.is_dir():
                errors.append(
                    Finding(
                        "error",
                        "attach-target-conflict",
                        f"cannot create scaffold directory because a non-directory already exists: {candidate_rel}",
                        candidate_rel,
                    )
                )

    templates = _attach_apply_templates(project_name, inventory)
    for rel_path, content in templates.items():
        chain = _root_relative_path_chain(inventory.root, rel_path)
        for candidate in chain[:-1]:
            candidate_rel = candidate.relative_to(inventory.root).as_posix()
            if candidate_rel in seen_directory_segments:
                continue
            seen_directory_segments.add(candidate_rel)
            if candidate.is_symlink():
                errors.append(
                    Finding(
                        "error",
                        "attach-target-conflict",
                        f"cannot create template file because a symlink segment exists: {candidate_rel}",
                        candidate_rel,
                    )
                )
            elif candidate.exists() and not candidate.is_dir():
                errors.append(
                    Finding(
                        "error",
                        "attach-target-conflict",
                        f"cannot create template file because a parent path is not a directory: {candidate_rel}",
                        candidate_rel,
                    )
                )
        path = inventory.root / rel_path
        if path.is_symlink():
            errors.append(
                Finding(
                    "error",
                    "attach-target-conflict",
                    f"cannot create template file because a symlink exists: {rel_path}",
                    rel_path,
                )
            )
            continue
        if path.exists() and not path.is_file():
            errors.append(
                Finding(
                    "error",
                    "attach-target-conflict",
                    f"cannot create template file because a non-file already exists: {rel_path}",
                    rel_path,
                )
            )
            continue
        if path.exists() and allow_existing_template_content:
            continue
        if path.exists():
            try:
                existing_content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                errors.append(
                    Finding(
                        "error",
                        "attach-target-conflict",
                        f"cannot compare existing template file before attach: {rel_path}: {exc}",
                        rel_path,
                    )
                )
                continue
            if existing_content == content:
                continue
            errors.append(
                Finding(
                    "error",
                    "attach-target-conflict",
                    f"existing file differs from the create-only attach template; refusing to overwrite: {rel_path}",
                    rel_path,
                )
            )
    return errors


def _attach_apply_templates(project_name: str | None, inventory: Inventory) -> dict[str, str]:
    project = project_name
    state = inventory.state
    if project is None and state and state.exists:
        existing_project = state.frontmatter.data.get("project")
        if isinstance(existing_project, str) and existing_project.strip():
            project = existing_project.strip()
    templates = {ATTACH_MANIFEST_REL_PATH: _workflow_manifest_template()}
    if project is not None:
        templates[ATTACH_STATE_REL_PATH] = _project_state_template(project)
    return templates


def _workflow_manifest_template() -> str:
    return (
        'workflow = "workflow-core"\n'
        "version = 1\n"
        "\n"
        "[memory]\n"
        'state_file = "project/project-state.md"\n'
        'plan_file = "project/implementation-plan.md"\n'
        'archive_dir = "project/archive/plans"\n'
        "\n"
        "[policy]\n"
        'closeout_commit = "manual"\n'
    )


def _project_state_template(project_name: str) -> str:
    quoted_project = _frontmatter_quote(project_name)
    heading = project_name.replace("\r", " ").replace("\n", " ").strip()
    return (
        "---\n"
        f"project: {quoted_project}\n"
        'workflow: "workflow-core"\n'
        'operating_mode: "ad_hoc"\n'
        'plan_status: "none"\n'
        'active_plan: ""\n'
        'last_archived_plan: ""\n'
        "---\n"
        f"# {heading} Project State\n"
        "\n"
        "## Current Focus\n"
        "\n"
        "No active implementation plan.\n"
        "\n"
        "## Notes\n"
        "\n"
        "Attached by MyLittleHarness. Add durable project memory here as work proceeds.\n"
    )


def _normalize_project_name(project_name: str | None) -> str | None:
    if project_name is None:
        return None
    normalized = project_name.strip()
    if not normalized or "\r" in normalized or "\n" in normalized:
        return None
    return normalized


def _frontmatter_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def repair_dry_run_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = [
        Finding("info", "dry-run", "repair proposal only; no files or directories were written"),
        Finding(
            "info",
            "mutation-guard",
            "use repair --apply only for deterministic scaffold, create-only AGENTS.md, create-only docmap, create-only stable spec restoration, snapshot-protected docmap route repairs, or snapshot-protected state frontmatter repair",
        ),
    ]
    validation = validation_findings(inventory)
    actionable = [
        finding
        for finding in validation
        if finding.severity in {"error", "warn"} and not _is_route_metadata_advisory(finding)
    ]
    findings.extend(_state_frontmatter_plan_findings(inventory, validation))
    findings.extend(_agents_contract_create_plan_findings(inventory, validation))
    findings.extend(_docmap_snapshot_plan_findings(inventory, validation))
    findings.extend(_docmap_create_plan_findings(inventory, validation))
    findings.extend(_stable_spec_create_plan_findings(inventory, validation))

    if _is_product_source_inventory(inventory):
        findings.append(
            Finding(
                "info",
                "repair-scope",
                "target is a product-source compatibility fixture; repair proposals are constrained to report-only review",
                inventory.state.rel_path if inventory.state else None,
            )
        )

    if not _is_product_source_inventory(inventory) and _has_repair_apply_authority(inventory):
        missing_dirs = _repair_missing_scaffold_directories(inventory)
        for rel_path in missing_dirs:
            findings.append(Finding("warn", "repair-proposal", f"would create missing scaffold directory: {rel_path}", rel_path))
        if not missing_dirs:
            findings.append(Finding("info", "repair-proposal", "no missing scaffold directories were found"))
    elif not _is_product_source_inventory(inventory):
        findings.append(
            Finding(
                "info",
                "repair-scope",
                "repair apply would require an existing readable workflow-core manifest and project state",
            )
        )

    if not actionable:
        if not any(finding.code == "repair-proposal" for finding in findings):
            findings.append(Finding("info", "repair-proposal", "no validation errors or warnings require a repair proposal"))
        return findings

    for finding in actionable:
        findings.append(_repair_proposal_for(finding))
    return findings


def repair_apply_findings(inventory: Inventory) -> list[Finding]:
    validation = validation_findings(inventory)
    non_default_state_refusal = _non_default_state_path_apply_refusal(inventory)
    if non_default_state_refusal:
        return [non_default_state_refusal]
    if _state_prose_fallback_diagnostic(validation) is not None:
        errors = _state_frontmatter_apply_preflight_errors(inventory, validation)
        if errors:
            return errors
        findings, changed = _state_frontmatter_apply_findings(inventory, validation)
        if any(finding.severity == "error" for finding in findings):
            return findings
        findings.extend(_post_repair_validation_findings(inventory))
        if changed:
            findings.append(
                Finding(
                    "info",
                    "state-frontmatter-rerun",
                    "state frontmatter repair completed first; review validation and rerun repair --apply for any remaining scaffold or docmap repair classes",
                    STATE_FRONTMATTER_TARGET_REL,
                )
            )
        return findings

    errors = _repair_apply_authority_errors(inventory)
    if not errors:
        errors.extend(_repair_apply_lifecycle_preflight_errors(validation))
    if not errors:
        errors.extend(_repair_apply_preflight_errors(inventory))
    if not errors:
        errors.extend(_agents_contract_create_apply_preflight_errors(inventory, validation))
    if not errors:
        errors.extend(_docmap_create_apply_preflight_errors(inventory, validation))
    if not errors:
        errors.extend(_docmap_snapshot_apply_preflight_errors(inventory, validation))
    if not errors:
        errors.extend(_stable_spec_create_apply_preflight_errors(inventory, validation))
    if errors:
        return errors

    findings: list[Finding] = [Finding("info", "repair-apply", "bounded repair apply started")]
    created_paths: list[str] = []
    existing_paths: list[str] = []
    docmap_route_changed = False
    docmap_created = False
    stable_specs_created = False
    agents_contract_created = False

    agents_contract_findings, agents_contract_created = _agents_contract_create_apply_findings(inventory, validation)
    findings.extend(agents_contract_findings)
    if any(finding.severity == "error" for finding in agents_contract_findings):
        return findings
    docmap_findings, docmap_route_changed = _docmap_snapshot_apply_findings(inventory, validation)
    findings.extend(docmap_findings)
    if any(finding.severity == "error" for finding in docmap_findings):
        return findings
    docmap_create_findings, docmap_created = _docmap_create_apply_findings(inventory, validation)
    findings.extend(docmap_create_findings)
    if any(finding.severity == "error" for finding in docmap_create_findings):
        return findings
    stable_spec_findings, stable_specs_created = _stable_spec_create_apply_findings(inventory, validation)
    findings.extend(stable_spec_findings)
    if any(finding.severity == "error" for finding in stable_spec_findings):
        return findings

    for rel_path in WORKFLOW_ATTACH_DIRECTORIES:
        path = inventory.root / rel_path
        if path.exists():
            existing_paths.append(rel_path)
            continue
        path.mkdir(parents=True, exist_ok=False)
        created_paths.append(rel_path)

    for rel_path in created_paths:
        findings.append(Finding("info", "repair-created", f"created create-only repair path: {rel_path}", rel_path))
    for rel_path in existing_paths:
        findings.append(Finding("info", "repair-existing", f"preserved existing repair path without changes: {rel_path}", rel_path))
    if not created_paths and not docmap_route_changed and not docmap_created and not stable_specs_created and not agents_contract_created:
        findings.append(Finding("info", "repair-unchanged", "no file or directory changes were needed"))
    findings.append(
        Finding(
            "info",
            "repair-apply-boundary",
            "repair --apply wrote only absent eager scaffold directories, selected create-only AGENTS.md creation, selected create-only docmap creation, selected create-only stable spec restoration, and selected snapshot-protected docmap route repair classes",
        )
    )

    findings.extend(_post_repair_validation_findings(inventory))
    return findings


def _post_repair_validation_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    refreshed = load_inventory(inventory.root)
    validation = validation_findings(refreshed)
    audit = audit_link_findings(refreshed)
    validation_errors = [finding for finding in validation if finding.severity == "error"]
    validation_warnings = [finding for finding in validation if finding.severity == "warn"]
    audit_warnings = [finding for finding in audit if finding.severity == "warn"]
    findings.append(
        Finding(
            "info",
            "repair-validation",
            f"post-repair validation findings: {len(validation_errors)} errors, {len(validation_warnings)} warnings",
        )
    )
    for finding in validation_errors:
        findings.append(
            Finding(
                "error",
                "repair-validation-error",
                f"post-repair validation still reports {finding.code}: {finding.message}",
                finding.source,
                finding.line,
            )
        )
    for finding in validation_warnings:
        findings.append(
            Finding(
                "warn",
                "repair-validation-warning",
                f"post-repair validation still reports {finding.code}: {finding.message}",
                finding.source,
                finding.line,
            )
        )
    findings.append(
        Finding(
            "info",
            "repair-audit-links",
            f"post-repair audit-link findings: {len(audit_warnings)} warnings",
        )
    )
    for finding in audit_warnings:
        findings.append(
            Finding(
                "warn",
                "repair-audit-link-warning",
                f"post-repair audit-links still reports {finding.code}: {finding.message}",
                finding.source,
                finding.line,
            )
        )
    return findings


def snapshot_inspect_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = [
        Finding(
            "info",
            "snapshot-inspect-boundary",
            (
                f"inspecting repair snapshots under {SNAPSHOT_REPAIR_ROOT_REL}/; terminal-only read-only report; "
                "no rollback, cleanup, repair, archive, commit, or lifecycle mutation is implied"
            ),
        ),
        Finding(
            "info",
            "snapshot-authority",
            "repair snapshots are safety evidence only and cannot approve repair, closeout, archive, commit, lifecycle decisions, or future repairs",
        ),
    ]
    findings.extend(_snapshot_inspect_root_posture_findings(inventory))

    boundary_conflict = _snapshot_inspect_boundary_conflict(inventory.root)
    if boundary_conflict:
        findings.append(boundary_conflict)
        return findings

    snapshot_root = inventory.root / SNAPSHOT_REPAIR_ROOT_REL
    if not snapshot_root.exists():
        findings.append(
            Finding(
                "info",
                "snapshot-inspect-empty",
                f"no repair snapshot directory found: {SNAPSHOT_REPAIR_ROOT_REL}/",
                SNAPSHOT_REPAIR_ROOT_REL,
            )
        )
        return findings

    snapshot_dirs: list[Path] = []
    for child in sorted(snapshot_root.iterdir(), key=lambda item: item.name):
        rel_path = child.relative_to(inventory.root).as_posix()
        if child.is_symlink():
            findings.append(Finding("warn", "snapshot-inspect-boundary-conflict", f"snapshot entry is a symlink: {rel_path}", rel_path))
            continue
        if not child.is_dir():
            findings.append(Finding("warn", "snapshot-inspect-malformed", f"snapshot entry is not a directory: {rel_path}", rel_path))
            continue
        snapshot_dirs.append(child)

    if not snapshot_dirs:
        findings.append(
            Finding(
                "info",
                "snapshot-inspect-empty",
                f"repair snapshot directory contains no snapshot directories: {SNAPSHOT_REPAIR_ROOT_REL}/",
                SNAPSHOT_REPAIR_ROOT_REL,
            )
        )
        return findings

    for snapshot_dir in snapshot_dirs:
        findings.extend(_inspect_repair_snapshot(inventory, snapshot_dir))
    return findings


def _repair_apply_authority_errors(inventory: Inventory) -> list[Finding]:
    if _is_product_source_inventory(inventory):
        return [
            Finding(
                "error",
                "repair-refused",
                "target is a product-source compatibility fixture; repair --apply is refused",
                inventory.state.rel_path if inventory.state else ATTACH_STATE_REL_PATH,
            )
        ]
    if _is_fallback_or_archive_inventory(inventory):
        return [
            Finding(
                "error",
                "repair-refused",
                "target is fallback/archive evidence; repair --apply is refused",
                inventory.state.rel_path if inventory.state else None,
            )
        ]
    state = inventory.state
    if state and state.frontmatter.has_frontmatter and state.frontmatter.errors:
        return [
            Finding(
                "error",
                "state-frontmatter-refused",
                "project-state.md frontmatter is malformed; repair --apply refuses lifecycle mutation until state frontmatter is fixed manually",
                state.rel_path,
            )
        ]
    if not _has_repair_apply_authority(inventory):
        return [
            Finding(
                "error",
                "repair-refused",
                "repair --apply requires an existing readable workflow-core manifest and project state",
                inventory.manifest_surface.rel_path if inventory.manifest_surface else ATTACH_MANIFEST_REL_PATH,
            )
        ]
    return []


def _non_default_state_path_apply_refusal(inventory: Inventory) -> Finding | None:
    if not inventory.manifest:
        return None
    manifest_state = str(inventory.manifest.get("memory", {}).get("state_file", STATE_FRONTMATTER_TARGET_REL)).replace("\\", "/")
    if manifest_state == STATE_FRONTMATTER_TARGET_REL:
        return None
    return Finding(
        "error",
        "state-frontmatter-refused",
        f"repair --apply is limited to {STATE_FRONTMATTER_TARGET_REL} state authority; manifest state_file is {manifest_state}",
        inventory.manifest_surface.rel_path if inventory.manifest_surface else ATTACH_MANIFEST_REL_PATH,
    )


def _has_repair_apply_authority(inventory: Inventory) -> bool:
    manifest = inventory.manifest_surface
    state = inventory.state
    if not manifest or not manifest.exists or inventory.manifest_errors:
        return False
    if not state or not state.exists or not state.frontmatter.has_frontmatter:
        return False
    if inventory.manifest.get("workflow") != "workflow-core":
        return False
    if state.frontmatter.data.get("workflow") != "workflow-core":
        return False
    return True


def _repair_apply_lifecycle_preflight_errors(validation: list[Finding]) -> list[Finding]:
    refused_codes = {
        "state-frontmatter",
        "state-frontmatter-field",
        "active-plan-field",
        "active-plan-missing",
        "active-plan-manifest",
        "frontmatter-parse",
    }
    for finding in validation:
        if finding.code in refused_codes:
            return [
                Finding(
                    "error",
                    "state-frontmatter-refused",
                    f"repair --apply refuses lifecycle-sensitive state diagnostic {finding.code}: {finding.message}",
                    finding.source,
                    finding.line,
                )
            ]
    return []


def _repair_apply_preflight_errors(inventory: Inventory) -> list[Finding]:
    errors: list[Finding] = []
    seen: set[str] = set()
    for rel_path in WORKFLOW_ATTACH_DIRECTORIES:
        for candidate in _root_relative_path_chain(inventory.root, rel_path):
            candidate_rel = candidate.relative_to(inventory.root).as_posix()
            if candidate_rel in seen:
                continue
            seen.add(candidate_rel)
            if not candidate.exists():
                continue
            if candidate.is_symlink() or not candidate.is_dir():
                errors.append(
                    Finding(
                        "error",
                        "repair-target-conflict",
                        f"cannot create scaffold directory because a non-directory or symlink exists: {candidate_rel}",
                        candidate_rel,
                    )
                )
    return errors


def _root_relative_path_chain(root: Path, rel_path: str) -> list[Path]:
    current = root
    paths: list[Path] = []
    for part in Path(rel_path).parts:
        current = current / part
        paths.append(current)
    return paths


def _repair_missing_scaffold_directories(inventory: Inventory) -> list[str]:
    return [rel_path for rel_path in WORKFLOW_ATTACH_DIRECTORIES if not (inventory.root / rel_path).exists()]


def _repair_proposal_for(finding: Finding) -> Finding:
    action_by_code = {
        "missing-required-surface": "restore or create the required repo-native surface after confirming root authority",
        "manifest-parse": "fix manifest TOML syntax before relying on manifest-resolved memory paths",
        "manifest-workflow": "review manifest workflow value and align it with workflow-core compatibility if intended",
        "manifest-state-file": "review non-default state_file before repair; do not move memory implicitly",
        "manifest-plan-file": "review non-default plan_file before repair; do not move active plans implicitly",
        "state-frontmatter": "restore project-state.md frontmatter with canonical project, workflow, operating_mode, and plan_status fields",
        "state-frontmatter-field": "add the missing project-state.md frontmatter field after confirming current operating state",
        "active-plan-field": "set active_plan to the manifest plan path when plan_status remains active",
        "active-plan-missing": "restore the active implementation plan or mark plan_status inactive from the operating root",
        "active-plan-manifest": "align active_plan with manifest memory.plan_file after confirming the active plan location",
        "stale-plan-file": "archive, remove, or reactivate the stale plan only through the operating root closeout path",
        "missing-stable-spec": "restore the expected workflow spec fixture from product docs or the operating source of truth",
        "frontmatter-parse": "fix malformed markdown frontmatter without changing body authority",
        "research-frontmatter": "add lightweight routing frontmatter only if the research artifact remains durable",
        "docmap-routing": "update docmap routes after confirming the target files are canonical entrypoints",
        "mirror-drift": "resync mirrors only if package-source mirror parity is still intended",
    }
    action = action_by_code.get(finding.code, "review this diagnostic manually before any repair mutation")
    return Finding(
        "warn",
        "repair-proposal",
        f"{action}; source diagnostic: {finding.code} - {finding.message}",
        finding.source,
        finding.line,
    )


def _is_route_metadata_advisory(finding: Finding) -> bool:
    return finding.code.startswith("route-metadata-")


def _state_frontmatter_plan_findings(inventory: Inventory, validation: list[Finding]) -> list[Finding]:
    findings: list[Finding] = [
        Finding(
            "info",
            "state-frontmatter-scope",
            f"selected repair class: {STATE_FRONTMATTER_REPAIR_CLASS}; target file: {STATE_FRONTMATTER_TARGET_REL}",
            STATE_FRONTMATTER_TARGET_REL,
        )
    ]

    diagnostic = _state_prose_fallback_diagnostic(validation)
    if diagnostic is None:
        findings.append(
            Finding(
                "info",
                "state-frontmatter-skipped",
                f"no state-prose-fallback diagnostic was found; {STATE_FRONTMATTER_TARGET_REL} frontmatter repair is not needed",
                STATE_FRONTMATTER_TARGET_REL,
            )
        )
        return findings

    refusal = _state_frontmatter_refusal_finding(inventory, validation, severity="warn")
    if refusal:
        findings.append(refusal)
        return findings

    state = inventory.state
    assert state is not None
    target_conflict = _snapshot_target_conflict(inventory.root, STATE_FRONTMATTER_TARGET_REL)
    if target_conflict:
        findings.append(_state_frontmatter_refusal_from(target_conflict, "warn"))
        return findings

    fields = _state_frontmatter_fields(inventory)
    frontmatter_text = _state_frontmatter_text(fields)
    snapshot_dir = _state_frontmatter_snapshot_dir(state.path, frontmatter_text, SNAPSHOT_DRY_RUN_TIMESTAMP)
    boundary_conflict = _snapshot_boundary_conflict(inventory.root, snapshot_dir)
    if boundary_conflict:
        findings.append(_state_frontmatter_refusal_from(boundary_conflict, "warn"))
        return findings

    planned_keys = list(fields)
    metadata_fields = ", ".join([*SNAPSHOT_METADATA_FIELDS, "planned_frontmatter_keys"])
    findings.extend(
        [
            Finding(
                "warn",
                "state-frontmatter-plan",
                f"would prepend deterministic project-state frontmatter because validation reports {diagnostic.code}: {diagnostic.message}",
                STATE_FRONTMATTER_TARGET_REL,
            ),
            Finding(
                "info",
                "state-frontmatter-keys",
                f"planned frontmatter keys: {', '.join(planned_keys)}",
                STATE_FRONTMATTER_TARGET_REL,
            ),
            Finding(
                "info",
                "state-frontmatter-snapshot-path",
                f"planned snapshot directory: {snapshot_dir}/; metadata: {snapshot_dir}/snapshot.json; copied file: {snapshot_dir}/{STATE_FRONTMATTER_COPY_REL}",
                STATE_FRONTMATTER_TARGET_REL,
            ),
            Finding(
                "info",
                "state-frontmatter-metadata",
                f"metadata fields: {metadata_fields}",
                STATE_FRONTMATTER_TARGET_REL,
            ),
            Finding(
                "info",
                "state-frontmatter-rollback",
                f"manual rollback only: copy {snapshot_dir}/{STATE_FRONTMATTER_COPY_REL} back to {STATE_FRONTMATTER_TARGET_REL}; no rollback command, cleanup, archive, commit, or lifecycle mutation is implied",
                STATE_FRONTMATTER_TARGET_REL,
            ),
            Finding(
                "info",
                "state-frontmatter-validation",
                "validation method after apply: python -m mylittleharness --root <target-root> validate; python -m mylittleharness --root <target-root> audit-links",
                STATE_FRONTMATTER_TARGET_REL,
            ),
            Finding(
                "info",
                "state-frontmatter-authority",
                "state frontmatter repair cannot approve closeout, archive, commit, lifecycle decisions, or future repairs",
                STATE_FRONTMATTER_TARGET_REL,
            ),
        ]
    )
    return findings


def _docmap_snapshot_plan_findings(inventory: Inventory, validation: list[Finding]) -> list[Finding]:
    findings: list[Finding] = [
        Finding(
            "info",
            "snapshot-plan-scope",
            f"selected repair class: {DOCMAP_REPAIR_CLASS}; target file: {DOCMAP_REPAIR_TARGET_REL}",
            DOCMAP_REPAIR_TARGET_REL,
        )
    ]

    if _is_product_source_inventory(inventory):
        findings.append(
            Finding(
                "warn",
                "snapshot-plan-refused",
                "target is a product-source compatibility fixture; repair snapshot planning is report-only and snapshot creation is refused",
                inventory.state.rel_path if inventory.state else ATTACH_STATE_REL_PATH,
            )
        )
        return findings
    if _is_fallback_or_archive_inventory(inventory):
        findings.append(
            Finding(
                "warn",
                "snapshot-plan-refused",
                "target is fallback/archive or generated-output evidence; repair snapshot planning is refused",
                inventory.state.rel_path if inventory.state else None,
            )
        )
        return findings
    if inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                "warn",
                "snapshot-plan-refused",
                f"target root kind is {inventory.root_kind}; docmap snapshot planning requires an explicit live operating root",
            )
        )
        return findings
    if not _has_repair_apply_authority(inventory):
        findings.append(
            Finding(
                "warn",
                "snapshot-plan-refused",
                "snapshot-protected repair would require an existing readable workflow-core manifest and strict project-state frontmatter authority",
                inventory.manifest_surface.rel_path if inventory.manifest_surface else ATTACH_MANIFEST_REL_PATH,
            )
        )
        return findings

    path_conflict = _snapshot_target_conflict(inventory.root, DOCMAP_REPAIR_TARGET_REL)
    if path_conflict:
        findings.append(path_conflict)
        return findings
    target = inventory.root / DOCMAP_REPAIR_TARGET_REL
    if not target.exists():
        findings.append(
            Finding(
                "info",
                "snapshot-plan-skipped",
                f"target file is absent: {DOCMAP_REPAIR_TARGET_REL}; absent docmap remains a create-only/bootstrap question",
                DOCMAP_REPAIR_TARGET_REL,
            )
        )
        return findings

    route_diagnostics = _docmap_route_diagnostics(inventory, validation)
    if not route_diagnostics:
        findings.append(
            Finding(
                "info",
                "snapshot-plan",
                f"no {DOCMAP_REPAIR_TARGET_REL} route diagnostics require a snapshot plan",
                DOCMAP_REPAIR_TARGET_REL,
            )
        )
        return findings

    route_entries = _docmap_route_entries_from_diagnostics(route_diagnostics)
    snapshot_dir = _docmap_snapshot_preview_dir(target, route_entries)
    boundary_conflict = _snapshot_boundary_conflict(inventory.root, snapshot_dir)
    if boundary_conflict:
        findings.append(boundary_conflict)
        return findings

    diagnostic_codes = ", ".join(sorted({finding.code for finding in route_diagnostics}))
    route_summary = ", ".join(route_entries) if route_entries else "route entries from listed docmap diagnostics"
    metadata_fields = ", ".join(SNAPSHOT_METADATA_FIELDS)
    findings.extend(
        [
            Finding(
                "warn",
                "snapshot-plan",
                f"would plan snapshot before docmap route repair; target files: {DOCMAP_REPAIR_TARGET_REL}; source diagnostics: {diagnostic_codes}",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "snapshot-path",
                f"planned snapshot directory: {snapshot_dir}/; metadata: {snapshot_dir}/snapshot.json; copied file: {snapshot_dir}/{DOCMAP_REPAIR_COPY_REL}",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "snapshot-metadata",
                f"metadata fields: {metadata_fields}",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "snapshot-route-change",
                f"planned route entries: {route_summary}",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "snapshot-rollback",
                f"manual rollback only: copy {snapshot_dir}/{DOCMAP_REPAIR_COPY_REL} back to {DOCMAP_REPAIR_TARGET_REL}; no rollback command, cleanup, archive, commit, or lifecycle mutation is implied",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "snapshot-validation",
                "validation method after a future apply: python -m mylittleharness --root <target-root> validate; python -m mylittleharness --root <target-root> audit-links",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "snapshot-authority",
                "snapshot metadata is safety evidence only and cannot approve repair, closeout, archive, commit, lifecycle decisions, or future repairs",
                DOCMAP_REPAIR_TARGET_REL,
            ),
        ]
    )
    return findings


def _docmap_create_plan_findings(inventory: Inventory, validation: list[Finding]) -> list[Finding]:
    findings: list[Finding] = [
        Finding(
            "info",
            "docmap-create-scope",
            f"selected repair class: {DOCMAP_CREATE_CLASS}; target file: {DOCMAP_REPAIR_TARGET_REL}",
            DOCMAP_REPAIR_TARGET_REL,
        )
    ]

    if _is_product_source_inventory(inventory):
        findings.append(
            Finding(
                "warn",
                "docmap-create-refused",
                "target is a product-source compatibility fixture; docmap creation is report-only and repair --apply is refused",
                inventory.state.rel_path if inventory.state else ATTACH_STATE_REL_PATH,
            )
        )
        return findings
    if _is_fallback_or_archive_inventory(inventory):
        findings.append(
            Finding(
                "warn",
                "docmap-create-refused",
                "target is fallback/archive or generated-output evidence; docmap creation is refused",
                inventory.state.rel_path if inventory.state else None,
            )
        )
        return findings
    if inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                "warn",
                "docmap-create-refused",
                f"target root kind is {inventory.root_kind}; docmap creation requires an explicit live operating root",
            )
        )
        return findings
    if not _has_repair_apply_authority(inventory):
        findings.append(
            Finding(
                "warn",
                "docmap-create-refused",
                "docmap creation would require an existing readable workflow-core manifest and strict project-state frontmatter authority",
                inventory.manifest_surface.rel_path if inventory.manifest_surface else ATTACH_MANIFEST_REL_PATH,
            )
        )
        return findings

    conflict = _docmap_create_target_conflict(inventory.root)
    if conflict:
        findings.append(conflict)
        return findings

    target = inventory.root / DOCMAP_REPAIR_TARGET_REL
    if target.exists():
        findings.append(
            Finding(
                "info",
                "docmap-create-skipped",
                f"target file already exists: {DOCMAP_REPAIR_TARGET_REL}; docmap creation never rewrites existing content",
                DOCMAP_REPAIR_TARGET_REL,
            )
        )
        return findings

    diagnostic = _docmap_missing_required_diagnostic(validation)
    if diagnostic is None:
        findings.append(
            Finding(
                "info",
                "docmap-create-skipped",
                f"no missing required {DOCMAP_REPAIR_TARGET_REL} diagnostic was found; lazy or not-required docmaps remain absent",
                DOCMAP_REPAIR_TARGET_REL,
            )
        )
        return findings

    route_entries = _docmap_create_route_entries(inventory)
    findings.extend(
        [
            Finding(
                "warn",
                "docmap-create-plan",
                f"would create {DOCMAP_REPAIR_TARGET_REL} because validation reports {diagnostic.code}: {diagnostic.message}",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "docmap-create-routes",
                f"planned route entries: {', '.join(route_entries)}",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "docmap-create-rollback",
                f"manual rollback only: remove {DOCMAP_REPAIR_TARGET_REL}; remove .agents/ only if it is empty and was created by this repair",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "docmap-create-validation",
                "validation method after apply: python -m mylittleharness --root <target-root> validate; python -m mylittleharness --root <target-root> audit-links",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "docmap-create-authority",
                "docmap routing is advisory and cannot approve repair, closeout, archive, commit, lifecycle decisions, or future repairs",
                DOCMAP_REPAIR_TARGET_REL,
            ),
        ]
    )
    return findings


def _agents_contract_create_plan_findings(inventory: Inventory, validation: list[Finding]) -> list[Finding]:
    findings: list[Finding] = [
        Finding(
            "info",
            "agents-contract-create-scope",
            f"selected repair class: {AGENTS_CONTRACT_CREATE_CLASS}; target file: {AGENTS_CONTRACT_TARGET_REL}",
            AGENTS_CONTRACT_TARGET_REL,
        )
    ]

    if _is_product_source_inventory(inventory):
        findings.append(
            Finding(
                "warn",
                "agents-contract-create-refused",
                "target is a product-source compatibility fixture; AGENTS.md creation is report-only and repair --apply is refused",
                inventory.state.rel_path if inventory.state else ATTACH_STATE_REL_PATH,
            )
        )
        return findings
    if _is_fallback_or_archive_inventory(inventory):
        findings.append(
            Finding(
                "warn",
                "agents-contract-create-refused",
                "target is fallback/archive or generated-output evidence; AGENTS.md creation is refused",
                inventory.state.rel_path if inventory.state else None,
            )
        )
        return findings
    if inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                "warn",
                "agents-contract-create-refused",
                f"target root kind is {inventory.root_kind}; AGENTS.md creation requires an explicit live operating root",
            )
        )
        return findings
    if not _has_repair_apply_authority(inventory):
        findings.append(
            Finding(
                "warn",
                "agents-contract-create-refused",
                "AGENTS.md creation would require an existing readable workflow-core manifest and strict project-state frontmatter authority",
                inventory.manifest_surface.rel_path if inventory.manifest_surface else ATTACH_MANIFEST_REL_PATH,
            )
        )
        return findings

    conflict = _agents_contract_create_target_conflict(inventory.root)
    if conflict:
        findings.append(conflict)
        return findings

    target = inventory.root / AGENTS_CONTRACT_TARGET_REL
    if target.exists():
        findings.append(
            Finding(
                "info",
                "agents-contract-create-skipped",
                f"target file already exists: {AGENTS_CONTRACT_TARGET_REL}; AGENTS.md creation never rewrites existing content",
                AGENTS_CONTRACT_TARGET_REL,
            )
        )
        return findings

    diagnostic = _agents_contract_missing_required_diagnostic(validation)
    if diagnostic is None:
        findings.append(
            Finding(
                "info",
                "agents-contract-create-skipped",
                f"no missing required {AGENTS_CONTRACT_TARGET_REL} diagnostic was found",
                AGENTS_CONTRACT_TARGET_REL,
            )
        )
        return findings

    _, template_error = _agents_contract_template()
    if template_error:
        findings.append(template_error)
        return findings

    findings.extend(
        [
            Finding(
                "warn",
                "agents-contract-create-plan",
                f"would create {AGENTS_CONTRACT_TARGET_REL} because validation reports {diagnostic.code}: {diagnostic.message}",
                AGENTS_CONTRACT_TARGET_REL,
            ),
            Finding(
                "info",
                "agents-contract-create-rollback",
                f"manual rollback only: remove {AGENTS_CONTRACT_TARGET_REL}; no rollback command, cleanup, archive, commit, or lifecycle mutation is implied",
                AGENTS_CONTRACT_TARGET_REL,
            ),
            Finding(
                "info",
                "agents-contract-create-validation",
                "validation method after apply: python -m mylittleharness --root <target-root> validate; python -m mylittleharness --root <target-root> audit-links",
                AGENTS_CONTRACT_TARGET_REL,
            ),
            Finding(
                "info",
                "agents-contract-create-authority",
                "AGENTS.md is an operator contract surface and cannot approve repair, closeout, archive, commit, lifecycle decisions, or future repairs",
                AGENTS_CONTRACT_TARGET_REL,
            ),
        ]
    )
    return findings


def _agents_contract_create_apply_preflight_errors(inventory: Inventory, validation: list[Finding]) -> list[Finding]:
    target = inventory.root / AGENTS_CONTRACT_TARGET_REL
    conflict = _agents_contract_create_target_conflict(inventory.root)
    if conflict and (target.exists() or _agents_contract_missing_required_diagnostic(validation) is not None):
        return [Finding("error", conflict.code, conflict.message, conflict.source, conflict.line)]
    if target.exists() or _agents_contract_missing_required_diagnostic(validation) is None:
        return []
    _, template_error = _agents_contract_template()
    if template_error:
        return [Finding("error", template_error.code, template_error.message, template_error.source, template_error.line)]
    return []


def _agents_contract_create_apply_findings(inventory: Inventory, validation: list[Finding]) -> tuple[list[Finding], bool]:
    findings: list[Finding] = [
        Finding(
            "info",
            "agents-contract-create-scope",
            f"selected repair class: {AGENTS_CONTRACT_CREATE_CLASS}; target file: {AGENTS_CONTRACT_TARGET_REL}",
            AGENTS_CONTRACT_TARGET_REL,
        )
    ]
    target = inventory.root / AGENTS_CONTRACT_TARGET_REL
    if target.exists():
        findings.append(
            Finding(
                "info",
                "agents-contract-create-skipped",
                f"target file already exists: {AGENTS_CONTRACT_TARGET_REL}; AGENTS.md creation never rewrites existing content",
                AGENTS_CONTRACT_TARGET_REL,
            )
        )
        return findings, False

    diagnostic = _agents_contract_missing_required_diagnostic(validation)
    if diagnostic is None:
        findings.append(
            Finding(
                "info",
                "agents-contract-create-skipped",
                f"no missing required {AGENTS_CONTRACT_TARGET_REL} diagnostic was found",
                AGENTS_CONTRACT_TARGET_REL,
            )
        )
        return findings, False

    template, template_error = _agents_contract_template()
    if template_error:
        return [Finding("error", template_error.code, template_error.message, template_error.source, template_error.line)], False

    try:
        target.write_text(template, encoding="utf-8")
    except OSError as exc:
        return [
            Finding(
                "error",
                "agents-contract-create-refused",
                f"create-only AGENTS.md repair failed before target file was completed: {exc}",
                AGENTS_CONTRACT_TARGET_REL,
            )
        ], False

    findings.extend(
        [
            Finding("info", "agents-contract-create-created", f"created create-only repair file: {AGENTS_CONTRACT_TARGET_REL}", AGENTS_CONTRACT_TARGET_REL),
            Finding(
                "info",
                "agents-contract-create-rollback",
                f"manual rollback only: remove {AGENTS_CONTRACT_TARGET_REL}; no rollback command, cleanup, archive, commit, or lifecycle mutation is implied",
                AGENTS_CONTRACT_TARGET_REL,
            ),
            Finding(
                "info",
                "agents-contract-create-authority",
                "AGENTS.md is an operator contract surface and cannot approve repair, closeout, archive, commit, lifecycle decisions, or future repairs",
                AGENTS_CONTRACT_TARGET_REL,
            ),
        ]
    )
    return findings, True


def _agents_contract_missing_required_diagnostic(validation: list[Finding]) -> Finding | None:
    for finding in validation:
        if (
            finding.severity == "error"
            and finding.code == "missing-required-surface"
            and finding.source == AGENTS_CONTRACT_TARGET_REL
        ):
            return finding
    return None


def _agents_contract_create_target_conflict(root: Path) -> Finding | None:
    target_path = root / AGENTS_CONTRACT_TARGET_REL
    if target_path.is_symlink():
        return Finding("warn", "agents-contract-create-refused", f"target path contains a symlink segment: {AGENTS_CONTRACT_TARGET_REL}", AGENTS_CONTRACT_TARGET_REL)
    if target_path.exists() and not target_path.is_file():
        return Finding("warn", "agents-contract-create-refused", f"target path is not a regular file: {AGENTS_CONTRACT_TARGET_REL}", AGENTS_CONTRACT_TARGET_REL)
    try:
        target_path.resolve().relative_to(root.resolve())
    except ValueError:
        return Finding("warn", "agents-contract-create-refused", f"target path would escape the target root: {AGENTS_CONTRACT_TARGET_REL}", AGENTS_CONTRACT_TARGET_REL)
    return None


def _agents_contract_template() -> tuple[str | None, Finding | None]:
    try:
        content = resources.files(STABLE_SPEC_TEMPLATE_PACKAGE).joinpath(*AGENTS_CONTRACT_TEMPLATE_REL).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, UnicodeDecodeError) as exc:
        return None, Finding(
            "warn",
            "agents-contract-create-refused",
            f"packaged AGENTS.md template is missing or unreadable: {exc}",
            "/".join(AGENTS_CONTRACT_TEMPLATE_REL),
        )
    return content if content.endswith("\n") else content + "\n", None


def _docmap_create_apply_preflight_errors(inventory: Inventory, validation: list[Finding]) -> list[Finding]:
    target = inventory.root / DOCMAP_REPAIR_TARGET_REL
    conflict = _docmap_create_target_conflict(inventory.root)
    if conflict and (target.exists() or _docmap_missing_required_diagnostic(validation) is not None):
        return [Finding("error", conflict.code, conflict.message, conflict.source, conflict.line)]
    if target.exists() or _docmap_missing_required_diagnostic(validation) is None:
        return []
    return []


def _docmap_create_apply_findings(inventory: Inventory, validation: list[Finding]) -> tuple[list[Finding], bool]:
    findings: list[Finding] = [
        Finding(
            "info",
            "docmap-create-scope",
            f"selected repair class: {DOCMAP_CREATE_CLASS}; target file: {DOCMAP_REPAIR_TARGET_REL}",
            DOCMAP_REPAIR_TARGET_REL,
        )
    ]

    target = inventory.root / DOCMAP_REPAIR_TARGET_REL
    if target.exists():
        findings.append(
            Finding(
                "info",
                "docmap-create-skipped",
                f"target file already exists: {DOCMAP_REPAIR_TARGET_REL}; docmap creation never rewrites existing content",
                DOCMAP_REPAIR_TARGET_REL,
            )
        )
        return findings, False

    diagnostic = _docmap_missing_required_diagnostic(validation)
    if diagnostic is None:
        findings.append(
            Finding(
                "info",
                "docmap-create-skipped",
                f"no missing required {DOCMAP_REPAIR_TARGET_REL} diagnostic was found; lazy or not-required docmaps remain absent",
                DOCMAP_REPAIR_TARGET_REL,
            )
        )
        return findings, False

    parent_created = not target.parent.exists()
    route_entries = _docmap_create_route_entries(inventory)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_docmap_create_content(route_entries), encoding="utf-8")
    except OSError as exc:
        return [
            Finding(
                "error",
                "docmap-create-refused",
                f"create-only docmap repair failed before target file was completed: {exc}",
                DOCMAP_REPAIR_TARGET_REL,
            )
        ], False

    if parent_created:
        findings.append(Finding("info", "docmap-create-parent-created", "created parent directory: .agents", ".agents"))
    findings.extend(
        [
            Finding("info", "docmap-create-created", f"created create-only repair file: {DOCMAP_REPAIR_TARGET_REL}", DOCMAP_REPAIR_TARGET_REL),
            Finding("info", "docmap-create-routes", f"created route entries: {', '.join(route_entries)}", DOCMAP_REPAIR_TARGET_REL),
            Finding(
                "info",
                "docmap-create-rollback",
                f"manual rollback only: remove {DOCMAP_REPAIR_TARGET_REL}; remove .agents/ only if it is empty and was created by this repair",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "docmap-create-authority",
                "docmap routing is advisory and cannot approve repair, closeout, archive, commit, lifecycle decisions, or future repairs",
                DOCMAP_REPAIR_TARGET_REL,
            ),
        ]
    )
    return findings, True


def _docmap_missing_required_diagnostic(validation: list[Finding]) -> Finding | None:
    for finding in validation:
        if (
            finding.severity == "error"
            and finding.code == "missing-required-surface"
            and finding.source == DOCMAP_REPAIR_TARGET_REL
        ):
            return finding
    return None


def _stable_spec_create_plan_findings(inventory: Inventory, validation: list[Finding]) -> list[Finding]:
    findings: list[Finding] = [
        Finding(
            "info",
            "stable-spec-create-scope",
            f"selected repair class: {STABLE_SPEC_CREATE_CLASS}; target directory: {STABLE_SPEC_ROOT_REL}/",
            STABLE_SPEC_ROOT_REL,
        )
    ]

    if _is_product_source_inventory(inventory):
        findings.append(
            Finding(
                "warn",
                "stable-spec-create-refused",
                "target is a product-source compatibility fixture; stable spec creation is report-only and repair --apply is refused",
                inventory.state.rel_path if inventory.state else ATTACH_STATE_REL_PATH,
            )
        )
        return findings
    if _is_fallback_or_archive_inventory(inventory):
        findings.append(
            Finding(
                "warn",
                "stable-spec-create-refused",
                "target is fallback/archive or generated-output evidence; stable spec creation is refused",
                inventory.state.rel_path if inventory.state else None,
            )
        )
        return findings
    if inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                "warn",
                "stable-spec-create-refused",
                f"target root kind is {inventory.root_kind}; stable spec creation requires an explicit live operating root",
            )
        )
        return findings
    if not _has_repair_apply_authority(inventory):
        findings.append(
            Finding(
                "warn",
                "stable-spec-create-refused",
                "stable spec creation would require an existing readable workflow-core manifest and strict project-state frontmatter authority",
                inventory.manifest_surface.rel_path if inventory.manifest_surface else ATTACH_MANIFEST_REL_PATH,
            )
        )
        return findings

    missing_names = _missing_stable_spec_names(inventory, validation)
    if not missing_names:
        findings.append(
            Finding(
                "info",
                "stable-spec-create-skipped",
                f"no missing required stable workflow spec diagnostic was found under {STABLE_SPEC_ROOT_REL}/",
                STABLE_SPEC_ROOT_REL,
            )
        )
        return findings

    conflict = _stable_spec_create_target_conflict(inventory.root, missing_names)
    if conflict:
        findings.append(conflict)
        return findings
    _, template_errors = _stable_spec_templates_for(missing_names)
    if template_errors:
        findings.extend(template_errors)
        return findings

    rel_paths = _stable_spec_rel_paths(missing_names)
    findings.extend(
        [
            Finding(
                "warn",
                "stable-spec-create-plan",
                f"would create missing stable workflow specs because validation reports missing-stable-spec: {', '.join(rel_paths)}",
                STABLE_SPEC_ROOT_REL,
            ),
            Finding("info", "stable-spec-create-files", f"planned stable spec files: {', '.join(rel_paths)}", STABLE_SPEC_ROOT_REL),
            Finding(
                "info",
                "stable-spec-create-rollback",
                f"manual rollback only: remove created stable spec files: {', '.join(rel_paths)}; remove {STABLE_SPEC_ROOT_REL}/ only if it is empty and was created by this repair",
                STABLE_SPEC_ROOT_REL,
            ),
            Finding(
                "info",
                "stable-spec-create-validation",
                "validation method after apply: python -m mylittleharness --root <target-root> validate; python -m mylittleharness --root <target-root> audit-links",
                STABLE_SPEC_ROOT_REL,
            ),
            Finding(
                "info",
                "stable-spec-create-authority",
                "stable spec fixtures are repo-visible compatibility surfaces and cannot approve repair, closeout, archive, commit, lifecycle decisions, or future repairs",
                STABLE_SPEC_ROOT_REL,
            ),
        ]
    )
    return findings


def _stable_spec_create_apply_preflight_errors(inventory: Inventory, validation: list[Finding]) -> list[Finding]:
    missing_names = _missing_stable_spec_names(inventory, validation)
    if not missing_names:
        return []
    conflict = _stable_spec_create_target_conflict(inventory.root, missing_names)
    if conflict:
        return [Finding("error", conflict.code, conflict.message, conflict.source, conflict.line)]
    _, template_errors = _stable_spec_templates_for(missing_names)
    return [Finding("error", finding.code, finding.message, finding.source, finding.line) for finding in template_errors]


def _stable_spec_create_apply_findings(inventory: Inventory, validation: list[Finding]) -> tuple[list[Finding], bool]:
    findings: list[Finding] = [
        Finding(
            "info",
            "stable-spec-create-scope",
            f"selected repair class: {STABLE_SPEC_CREATE_CLASS}; target directory: {STABLE_SPEC_ROOT_REL}/",
            STABLE_SPEC_ROOT_REL,
        )
    ]
    missing_names = _missing_stable_spec_names(inventory, validation)
    if not missing_names:
        findings.append(
            Finding(
                "info",
                "stable-spec-create-skipped",
                f"no missing required stable workflow spec diagnostic was found under {STABLE_SPEC_ROOT_REL}/",
                STABLE_SPEC_ROOT_REL,
            )
        )
        return findings, False

    templates, template_errors = _stable_spec_templates_for(missing_names)
    if template_errors:
        return [Finding("error", finding.code, finding.message, finding.source, finding.line) for finding in template_errors], False

    root = inventory.root
    spec_root = root / STABLE_SPEC_ROOT_REL
    parent_created = not spec_root.exists()
    created_rel_paths: list[str] = []
    try:
        spec_root.mkdir(parents=True, exist_ok=True)
        for name in missing_names:
            target = root / STABLE_SPEC_ROOT_REL / name
            if target.exists():
                continue
            target.write_text(templates[name], encoding="utf-8")
            created_rel_paths.append(f"{STABLE_SPEC_ROOT_REL}/{name}")
    except OSError as exc:
        return [
            Finding(
                "error",
                "stable-spec-create-refused",
                f"create-only stable spec repair failed before target files were completed: {exc}",
                STABLE_SPEC_ROOT_REL,
            )
        ], False

    if not created_rel_paths:
        findings.append(
            Finding(
                "info",
                "stable-spec-create-skipped",
                f"stable workflow spec files already existed under {STABLE_SPEC_ROOT_REL}/; stable spec creation never rewrites existing content",
                STABLE_SPEC_ROOT_REL,
            )
        )
        return findings, False

    if parent_created:
        findings.append(Finding("info", "stable-spec-create-created", f"created parent directory: {STABLE_SPEC_ROOT_REL}", STABLE_SPEC_ROOT_REL))
    for rel_path in created_rel_paths:
        findings.append(Finding("info", "stable-spec-create-created", f"created create-only repair file: {rel_path}", rel_path))
    findings.extend(
        [
            Finding("info", "stable-spec-create-files", f"created stable spec files: {', '.join(created_rel_paths)}", STABLE_SPEC_ROOT_REL),
            Finding(
                "info",
                "stable-spec-create-rollback",
                f"manual rollback only: remove created stable spec files: {', '.join(created_rel_paths)}; remove {STABLE_SPEC_ROOT_REL}/ only if it is empty and was created by this repair",
                STABLE_SPEC_ROOT_REL,
            ),
            Finding(
                "info",
                "stable-spec-create-authority",
                "stable spec fixtures are repo-visible compatibility surfaces and cannot approve repair, closeout, archive, commit, lifecycle decisions, or future repairs",
                STABLE_SPEC_ROOT_REL,
            ),
        ]
    )
    return findings, True


def _missing_stable_spec_names(inventory: Inventory, validation: list[Finding]) -> list[str]:
    expected = set(EXPECTED_SPEC_NAMES)
    names: list[str] = []
    prefix = f"missing expected workflow spec: {STABLE_SPEC_ROOT_REL}/"
    for finding in validation:
        if finding.severity != "error" or finding.code != "missing-stable-spec":
            continue
        if not finding.message.startswith(prefix):
            continue
        name = finding.message[len(prefix) :].strip()
        if name in expected and not (inventory.root / STABLE_SPEC_ROOT_REL / name).exists() and name not in names:
            names.append(name)
    return names


def _stable_spec_rel_paths(names: list[str]) -> list[str]:
    return [f"{STABLE_SPEC_ROOT_REL}/{name}" for name in names]


def _stable_spec_create_target_conflict(root: Path, names: list[str]) -> Finding | None:
    for name in names:
        rel_path = f"{STABLE_SPEC_ROOT_REL}/{name}"
        target_path = root / rel_path
        for candidate in _root_relative_path_chain(root, rel_path):
            candidate_rel = candidate.relative_to(root).as_posix()
            if candidate.is_symlink():
                return Finding("warn", "stable-spec-create-refused", f"target path contains a symlink segment: {candidate_rel}", candidate_rel)
            if candidate.exists() and candidate != target_path and not candidate.is_dir():
                return Finding("warn", "stable-spec-create-refused", f"target path contains a non-directory segment: {candidate_rel}", candidate_rel)
        if target_path.exists() and not target_path.is_file():
            return Finding("warn", "stable-spec-create-refused", f"target path is not a regular file: {rel_path}", rel_path)
        try:
            target_path.resolve().relative_to(root.resolve())
        except ValueError:
            return Finding("warn", "stable-spec-create-refused", f"target path would escape the target root: {rel_path}", rel_path)
    return None


def _stable_spec_templates_for(names: list[str]) -> tuple[dict[str, str], list[Finding]]:
    templates: dict[str, str] = {}
    errors: list[Finding] = []
    base = resources.files(STABLE_SPEC_TEMPLATE_PACKAGE).joinpath(*STABLE_SPEC_TEMPLATE_REL)
    for name in names:
        try:
            content = base.joinpath(name).read_text(encoding="utf-8")
        except (FileNotFoundError, OSError, UnicodeDecodeError) as exc:
            errors.append(
                Finding(
                    "warn",
                    "stable-spec-create-refused",
                    f"packaged stable spec template is missing or unreadable: {name}: {exc}",
                    f"{'/'.join(STABLE_SPEC_TEMPLATE_REL)}/{name}",
                )
            )
            continue
        templates[name] = content if content.endswith("\n") else content + "\n"
    return templates, errors


def _state_prose_fallback_diagnostic(validation: list[Finding]) -> Finding | None:
    for finding in validation:
        if finding.code == "state-prose-fallback" and finding.source == STATE_FRONTMATTER_TARGET_REL:
            return finding
    return None


def _state_frontmatter_refusal_finding(inventory: Inventory, validation: list[Finding], severity: str) -> Finding | None:
    if _is_product_source_inventory(inventory):
        return Finding(
            severity,
            "state-frontmatter-refused",
            "target is a product-source compatibility fixture; state frontmatter repair is report-only and repair --apply is refused",
            inventory.state.rel_path if inventory.state else ATTACH_STATE_REL_PATH,
        )
    if _is_fallback_or_archive_inventory(inventory):
        return Finding(
            severity,
            "state-frontmatter-refused",
            "target is fallback/archive or generated-output evidence; state frontmatter repair is refused",
            inventory.state.rel_path if inventory.state else None,
        )
    if inventory.root_kind != "live_operating_root":
        return Finding(
            severity,
            "state-frontmatter-refused",
            f"target root kind is {inventory.root_kind}; state frontmatter repair requires an explicit live operating root",
        )

    manifest = inventory.manifest_surface
    if not manifest or not manifest.exists or inventory.manifest_errors:
        return Finding(
            severity,
            "state-frontmatter-refused",
            "state frontmatter repair requires an existing readable workflow-core manifest",
            manifest.rel_path if manifest else ATTACH_MANIFEST_REL_PATH,
        )
    if inventory.manifest.get("workflow") != "workflow-core":
        return Finding(
            severity,
            "state-frontmatter-refused",
            "state frontmatter repair requires manifest workflow = workflow-core",
            manifest.rel_path,
        )
    manifest_state = str(inventory.manifest.get("memory", {}).get("state_file", STATE_FRONTMATTER_TARGET_REL)).replace("\\", "/")
    if manifest_state != STATE_FRONTMATTER_TARGET_REL:
        return Finding(
            severity,
            "state-frontmatter-refused",
            f"state frontmatter repair is limited to {STATE_FRONTMATTER_TARGET_REL}; manifest state_file is {manifest_state}",
            manifest.rel_path,
        )

    state = inventory.state
    if not state or not state.exists:
        return Finding(
            severity,
            "state-frontmatter-refused",
            f"state frontmatter repair requires an existing {STATE_FRONTMATTER_TARGET_REL}",
            STATE_FRONTMATTER_TARGET_REL,
        )
    if state.read_error:
        return Finding(
            severity,
            "state-frontmatter-refused",
            f"state file could not be read as clean UTF-8 before state frontmatter repair: {state.read_error}",
            STATE_FRONTMATTER_TARGET_REL,
        )
    if state.frontmatter.has_frontmatter:
        return Finding(
            severity,
            "state-frontmatter-refused",
            "project-state.md already has frontmatter or malformed frontmatter; this class only prepends missing frontmatter to prose state",
            STATE_FRONTMATTER_TARGET_REL,
        )

    data = state.frontmatter.data
    missing = [key for key in ("operating_mode", "plan_status") if not data.get(key)]
    if missing:
        return Finding(
            severity,
            "state-frontmatter-refused",
            f"state frontmatter repair requires prose assignments for: {', '.join(missing)}",
            STATE_FRONTMATTER_TARGET_REL,
        )

    plan_status = str(data.get("plan_status") or "")
    manifest_plan = str(inventory.manifest.get("memory", {}).get("plan_file", "project/implementation-plan.md")).replace("\\", "/")
    active_plan = str(data.get("active_plan") or "").replace("\\", "/")
    if plan_status == "active":
        if not active_plan:
            return Finding(
                severity,
                "state-frontmatter-refused",
                "state frontmatter repair refuses active plan_status when active_plan is missing",
                STATE_FRONTMATTER_TARGET_REL,
            )
        if active_plan != manifest_plan:
            return Finding(
                severity,
                "state-frontmatter-refused",
                f"state frontmatter repair refuses active_plan mismatch: {active_plan} != {manifest_plan}",
                STATE_FRONTMATTER_TARGET_REL,
            )
        if not inventory.active_plan_surface or not inventory.active_plan_surface.exists:
            return Finding(
                severity,
                "state-frontmatter-refused",
                f"state frontmatter repair refuses missing active plan: {active_plan}",
                active_plan,
            )

    disallowed_codes = {"manifest-parse", "manifest-workflow", "manifest-state-file", "active-plan-field", "active-plan-missing", "active-plan-manifest"}
    for finding in validation:
        if finding.code in disallowed_codes:
            return Finding(
                severity,
                "state-frontmatter-refused",
                f"state frontmatter repair refuses unresolved diagnostic {finding.code}: {finding.message}",
                finding.source,
                finding.line,
            )
    return None


def _state_frontmatter_refusal_from(finding: Finding, severity: str = "error") -> Finding:
    return Finding(severity, "state-frontmatter-refused", finding.message, finding.source, finding.line)


def _state_frontmatter_apply_preflight_errors(inventory: Inventory, validation: list[Finding]) -> list[Finding]:
    refusal = _state_frontmatter_refusal_finding(inventory, validation, severity="error")
    if refusal:
        return [refusal]
    target_conflict = _snapshot_target_conflict(inventory.root, STATE_FRONTMATTER_TARGET_REL)
    if target_conflict:
        return [_state_frontmatter_refusal_from(target_conflict)]

    state = inventory.state
    assert state is not None
    fields = _state_frontmatter_fields(inventory)
    snapshot_dir = _state_frontmatter_snapshot_dir(state.path, _state_frontmatter_text(fields), _current_snapshot_timestamp())
    boundary_conflict = _snapshot_boundary_conflict(inventory.root, snapshot_dir)
    if boundary_conflict:
        return [_state_frontmatter_refusal_from(boundary_conflict)]
    return []


def _state_frontmatter_apply_findings(inventory: Inventory, validation: list[Finding]) -> tuple[list[Finding], bool]:
    findings: list[Finding] = [
        Finding(
            "info",
            "state-frontmatter-apply-scope",
            f"selected repair class: {STATE_FRONTMATTER_REPAIR_CLASS}; target file: {STATE_FRONTMATTER_TARGET_REL}",
            STATE_FRONTMATTER_TARGET_REL,
        )
    ]
    diagnostic = _state_prose_fallback_diagnostic(validation)
    if diagnostic is None:
        findings.append(
            Finding(
                "info",
                "state-frontmatter-apply-skipped",
                "no state-prose-fallback diagnostic required state frontmatter repair",
                STATE_FRONTMATTER_TARGET_REL,
            )
        )
        return findings, False

    state = inventory.state
    assert state is not None
    target = state.path
    fields = _state_frontmatter_fields(inventory)
    frontmatter_text = _state_frontmatter_text(fields)
    timestamp = _current_snapshot_timestamp()
    snapshot_dir_rel = _state_frontmatter_snapshot_dir(target, frontmatter_text, timestamp)
    snapshot_dir = inventory.root / snapshot_dir_rel
    copy_rel = f"{snapshot_dir_rel}/{STATE_FRONTMATTER_COPY_REL}"
    copy_path = inventory.root / copy_rel
    metadata_rel = f"{snapshot_dir_rel}/snapshot.json"
    metadata_path = inventory.root / metadata_rel
    boundary_conflict = _snapshot_boundary_conflict(inventory.root, snapshot_dir_rel)
    if boundary_conflict:
        return [_state_frontmatter_refusal_from(boundary_conflict)], False

    try:
        pre_repair_bytes = target.read_bytes()
        pre_repair_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [
            Finding(
                "error",
                "state-frontmatter-refused",
                f"state file could not be decoded as UTF-8 before state frontmatter repair: {exc}",
                STATE_FRONTMATTER_TARGET_REL,
            )
        ], False
    except OSError as exc:
        return [
            Finding(
                "error",
                "state-frontmatter-refused",
                f"state file could not be read before state frontmatter repair: {exc}",
                STATE_FRONTMATTER_TARGET_REL,
            )
        ], False

    repaired_bytes = frontmatter_text.encode("utf-8") + pre_repair_bytes
    metadata = _state_frontmatter_snapshot_metadata(
        inventory,
        timestamp,
        snapshot_dir_rel,
        copy_rel,
        list(fields),
        diagnostic,
        pre_repair_bytes,
    )
    try:
        snapshot_dir.mkdir(parents=True, exist_ok=False)
        copy_path.parent.mkdir(parents=True, exist_ok=True)
        copy_path.write_bytes(pre_repair_bytes)
        metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        target.write_bytes(repaired_bytes)
    except OSError as exc:
        return [
            Finding(
                "error",
                "state-frontmatter-refused",
                f"state frontmatter repair failed before target mutation completed: {exc}",
                STATE_FRONTMATTER_TARGET_REL,
            )
        ], False

    findings.extend(
        [
            Finding("info", "snapshot-created", f"created repair snapshot before state frontmatter mutation: {snapshot_dir_rel}/", STATE_FRONTMATTER_TARGET_REL),
            Finding("info", "snapshot-copied-file", f"copied pre-repair bytes to {copy_rel}", STATE_FRONTMATTER_TARGET_REL),
            Finding("info", "snapshot-metadata-written", f"wrote snapshot metadata: {metadata_rel}", STATE_FRONTMATTER_TARGET_REL),
            Finding("info", "state-frontmatter-updated", f"prepended deterministic frontmatter keys: {', '.join(fields)}", STATE_FRONTMATTER_TARGET_REL),
            Finding(
                "info",
                "state-frontmatter-rollback",
                f"manual rollback only: copy {copy_rel} back to {STATE_FRONTMATTER_TARGET_REL}; then run validate and audit-links",
                STATE_FRONTMATTER_TARGET_REL,
            ),
            Finding(
                "info",
                "state-frontmatter-authority",
                "snapshot metadata is safety evidence only and cannot approve repair, closeout, archive, commit, lifecycle decisions, or future repairs",
                STATE_FRONTMATTER_TARGET_REL,
            ),
        ]
    )
    return findings, True


def _docmap_create_target_conflict(root: Path) -> Finding | None:
    target_path = root / DOCMAP_REPAIR_TARGET_REL
    for candidate in _root_relative_path_chain(root, DOCMAP_REPAIR_TARGET_REL):
        candidate_rel = candidate.relative_to(root).as_posix()
        if candidate.is_symlink():
            return Finding("warn", "docmap-create-refused", f"target path contains a symlink segment: {candidate_rel}", candidate_rel)
        if candidate.exists() and candidate != target_path and not candidate.is_dir():
            return Finding("warn", "docmap-create-refused", f"target path contains a non-directory segment: {candidate_rel}", candidate_rel)
    if target_path.exists() and not target_path.is_file():
        return Finding("warn", "docmap-create-refused", f"target path is not a regular file: {DOCMAP_REPAIR_TARGET_REL}", DOCMAP_REPAIR_TARGET_REL)
    try:
        target_path.resolve().relative_to(root.resolve())
    except ValueError:
        return Finding("warn", "docmap-create-refused", f"target path would escape the target root: {DOCMAP_REPAIR_TARGET_REL}", DOCMAP_REPAIR_TARGET_REL)
    return None


def _docmap_create_route_entries(inventory: Inventory) -> list[str]:
    expected = [
        "README.md",
        "AGENTS.md",
        ".codex/project-workflow.toml",
        "project/project-state.md",
        "project/specs/workflow/",
    ]
    for rel in ("docs/README.md", "docs/architecture/", "docs/specs/", "pyproject.toml", "src/mylittleharness/", "tests/"):
        if (inventory.root / rel).exists():
            expected.append(rel)
    state = inventory.state
    plan_status = state.frontmatter.data.get("plan_status") if state and state.exists else None
    active_plan = inventory.active_plan_surface
    if plan_status == "active" or (active_plan and active_plan.exists):
        expected.append("project/implementation-plan.md")
    return expected


def _docmap_create_content(route_entries: list[str]) -> str:
    return (
        "version: 2\n"
        "repo_summary:\n"
        "  product_docs_entrypoints:\n"
        + "".join(f'    - "{_yaml_double_quoted_value(entry)}"\n' for entry in route_entries)
    )


def _docmap_route_diagnostics(inventory: Inventory, validation: list[Finding]) -> list[Finding]:
    audit = audit_link_findings(inventory)
    candidates = validation + audit
    return [
        finding
        for finding in candidates
        if finding.code in {"docmap-routing", "candidate-docmap-gap"} and finding.source == DOCMAP_REPAIR_TARGET_REL
    ]


def _docmap_route_entries_from_diagnostics(findings: list[Finding]) -> list[str]:
    entries: list[str] = []
    prefixes = ("docmap does not mention ", "candidate route missing from docmap: ")
    for finding in findings:
        for prefix in prefixes:
            if finding.message.startswith(prefix):
                entry = finding.message[len(prefix) :].strip()
                if entry and entry not in entries:
                    entries.append(entry)
                break
    return entries


def _docmap_snapshot_preview_dir(target: Path, route_entries: list[str]) -> str:
    return _docmap_snapshot_dir(target, route_entries, SNAPSHOT_DRY_RUN_TIMESTAMP)


def _docmap_snapshot_dir(target: Path, route_entries: list[str], timestamp: str) -> str:
    content = target.read_text(encoding="utf-8", errors="replace") if target.exists() and target.is_file() else ""
    payload = "\n".join([DOCMAP_REPAIR_CLASS, DOCMAP_REPAIR_TARGET_REL, content, *route_entries])
    hash_prefix = hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"{SNAPSHOT_REPAIR_ROOT_REL}/{timestamp}-{DOCMAP_REPAIR_CLASS}-{DOCMAP_REPAIR_TARGET_SLUG}-{hash_prefix}"


def _docmap_snapshot_apply_preflight_errors(inventory: Inventory, validation: list[Finding]) -> list[Finding]:
    target_conflict = _snapshot_target_conflict(inventory.root, DOCMAP_REPAIR_TARGET_REL)
    if target_conflict:
        return [_error_from_snapshot_refusal(target_conflict)]

    target = inventory.root / DOCMAP_REPAIR_TARGET_REL
    if not target.exists():
        return []

    docmap = inventory.surface_by_rel.get(DOCMAP_REPAIR_TARGET_REL)
    if docmap and docmap.read_error:
        return [
            Finding(
                "error",
                "snapshot-apply-refused",
                f"target file could not be read as clean UTF-8 before snapshot-protected repair: {docmap.read_error}",
                DOCMAP_REPAIR_TARGET_REL,
            )
        ]

    route_diagnostics = _docmap_route_diagnostics(inventory, validation)
    if not route_diagnostics:
        return []
    route_entries = _docmap_route_entries_from_diagnostics(route_diagnostics)
    if not route_entries:
        return [
            Finding(
                "error",
                "snapshot-apply-refused",
                "docmap route diagnostics did not produce deterministic route entries",
                DOCMAP_REPAIR_TARGET_REL,
            )
        ]
    snapshot_dir = _docmap_snapshot_dir(target, route_entries, _current_snapshot_timestamp())
    boundary_conflict = _snapshot_boundary_conflict(inventory.root, snapshot_dir)
    if boundary_conflict:
        return [_error_from_snapshot_refusal(boundary_conflict)]
    return []


def _docmap_snapshot_apply_findings(inventory: Inventory, validation: list[Finding]) -> tuple[list[Finding], bool]:
    findings: list[Finding] = [
        Finding(
            "info",
            "snapshot-apply-scope",
            f"selected repair class: {DOCMAP_REPAIR_CLASS}; target file: {DOCMAP_REPAIR_TARGET_REL}",
            DOCMAP_REPAIR_TARGET_REL,
        )
    ]
    target = inventory.root / DOCMAP_REPAIR_TARGET_REL
    if not target.exists():
        findings.append(
            Finding(
                "info",
                "snapshot-apply-skipped",
                f"target file is absent: {DOCMAP_REPAIR_TARGET_REL}; absent docmap remains a create-only/bootstrap question",
                DOCMAP_REPAIR_TARGET_REL,
            )
        )
        return findings, False

    route_diagnostics = _docmap_route_diagnostics(inventory, validation)
    if not route_diagnostics:
        findings.append(
            Finding(
                "info",
                "snapshot-apply-skipped",
                f"no {DOCMAP_REPAIR_TARGET_REL} route diagnostics require snapshot-protected repair",
                DOCMAP_REPAIR_TARGET_REL,
            )
        )
        return findings, False

    route_entries = _docmap_route_entries_from_diagnostics(route_diagnostics)
    timestamp = _current_snapshot_timestamp()
    snapshot_dir_rel = _docmap_snapshot_dir(target, route_entries, timestamp)
    snapshot_dir = inventory.root / snapshot_dir_rel
    copy_rel = f"{snapshot_dir_rel}/{DOCMAP_REPAIR_COPY_REL}"
    copy_path = inventory.root / copy_rel
    metadata_rel = f"{snapshot_dir_rel}/snapshot.json"
    metadata_path = inventory.root / metadata_rel

    try:
        pre_repair_bytes = target.read_bytes()
        pre_repair_text = pre_repair_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [
            Finding(
                "error",
                "snapshot-apply-refused",
                f"target file could not be decoded as UTF-8 before snapshot-protected repair: {exc}",
                DOCMAP_REPAIR_TARGET_REL,
            )
        ], False
    except OSError as exc:
        return [
            Finding(
                "error",
                "snapshot-apply-refused",
                f"target file could not be read before snapshot-protected repair: {exc}",
                DOCMAP_REPAIR_TARGET_REL,
            )
        ], False

    repaired_text = _docmap_text_with_route_entries(pre_repair_text, route_entries)
    if repaired_text == pre_repair_text:
        findings.append(
            Finding(
                "info",
                "snapshot-apply-skipped",
                "planned docmap route entries were already present; no snapshot or docmap rewrite was needed",
                DOCMAP_REPAIR_TARGET_REL,
            )
        )
        return findings, False

    metadata = _docmap_snapshot_metadata(
        inventory,
        timestamp,
        snapshot_dir_rel,
        copy_rel,
        route_entries,
        route_diagnostics,
        pre_repair_bytes,
    )

    try:
        snapshot_dir.mkdir(parents=True, exist_ok=False)
        copy_path.parent.mkdir(parents=True, exist_ok=True)
        copy_path.write_bytes(pre_repair_bytes)
        metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        target.write_bytes(repaired_text.encode("utf-8"))
    except OSError as exc:
        return [
            Finding(
                "error",
                "snapshot-apply-refused",
                f"snapshot-protected docmap repair failed before target mutation completed: {exc}",
                DOCMAP_REPAIR_TARGET_REL,
            )
        ], False

    route_summary = ", ".join(route_entries)
    findings.extend(
        [
            Finding(
                "info",
                "snapshot-created",
                f"created repair snapshot before docmap mutation: {snapshot_dir_rel}/",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "snapshot-copied-file",
                f"copied pre-repair bytes to {copy_rel}",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "snapshot-metadata-written",
                f"wrote snapshot metadata: {metadata_rel}",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "repair-docmap-updated",
                f"updated docmap route entries: {route_summary}",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "snapshot-rollback",
                f"manual rollback only: copy {copy_rel} back to {DOCMAP_REPAIR_TARGET_REL}; then run validate and audit-links",
                DOCMAP_REPAIR_TARGET_REL,
            ),
            Finding(
                "info",
                "snapshot-authority",
                "snapshot metadata is safety evidence only and cannot approve repair, closeout, archive, commit, lifecycle decisions, or future repairs",
                DOCMAP_REPAIR_TARGET_REL,
            ),
        ]
    )
    return findings, True


def _current_snapshot_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _error_from_snapshot_refusal(finding: Finding) -> Finding:
    return Finding("error", "snapshot-apply-refused", finding.message, finding.source, finding.line)


def _docmap_text_with_route_entries(text: str, route_entries: list[str]) -> str:
    missing_entries = [entry for entry in route_entries if entry not in text]
    if not missing_entries:
        return text

    lines = text.splitlines(keepends=True)
    if not lines:
        return _docmap_route_block(missing_entries)

    entry_lines = [f'    - "{_yaml_double_quoted_value(entry)}"\n' for entry in missing_entries]
    product_entry_index = _find_line_index(lines, r"^\s{2}product_docs_entrypoints:\s*$")
    if product_entry_index is not None:
        insert_at = product_entry_index + 1
        while insert_at < len(lines):
            line = lines[insert_at]
            if line.strip() and not line.startswith("    "):
                break
            insert_at += 1
        return "".join(lines[:insert_at] + entry_lines + lines[insert_at:])

    repo_summary_index = _find_line_index(lines, r"^repo_summary:\s*$")
    if repo_summary_index is not None:
        insert_at = repo_summary_index + 1
        block = ["  product_docs_entrypoints:\n"] + entry_lines
        return "".join(lines[:insert_at] + block + lines[insert_at:])

    separator = "" if text.endswith(("\n", "\r")) else "\n"
    return text + separator + "\n" + _docmap_route_block(missing_entries)


def _find_line_index(lines: list[str], pattern: str) -> int | None:
    compiled = re.compile(pattern)
    for index, line in enumerate(lines):
        if compiled.match(line.rstrip("\r\n")):
            return index
    return None


def _docmap_route_block(route_entries: list[str]) -> str:
    entries = "".join(f'    - "{_yaml_double_quoted_value(entry)}"\n' for entry in route_entries)
    return "repo_summary:\n  product_docs_entrypoints:\n" + entries


def _yaml_double_quoted_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _state_frontmatter_fields(inventory: Inventory) -> dict[str, str]:
    state = inventory.state
    data = state.frontmatter.data if state else {}
    plan_status = str(data.get("plan_status") or "")
    manifest_plan = str(inventory.manifest.get("memory", {}).get("plan_file", "project/implementation-plan.md")).replace("\\", "/")
    fields = {
        "project": _state_frontmatter_project_name(inventory),
        "workflow": "workflow-core",
        "operating_mode": str(data.get("operating_mode") or ""),
        "plan_status": plan_status,
        "active_plan": str(data.get("active_plan") or (manifest_plan if plan_status == "active" else "")),
    }
    for key in STATE_FRONTMATTER_OPTIONAL_KEYS:
        value = data.get(key)
        if value not in (None, ""):
            fields[key] = str(value)
    return fields


def _state_frontmatter_project_name(inventory: Inventory) -> str:
    state = inventory.state
    data = state.frontmatter.data if state else {}
    if data.get("project"):
        return str(data["project"])
    if state:
        for heading in state.headings:
            if heading.level != 1:
                continue
            title = heading.title.strip()
            for suffix in (" Project State", " State"):
                if title.endswith(suffix) and len(title) > len(suffix):
                    return title[: -len(suffix)]
            if title:
                return title
    return inventory.root.name


def _state_frontmatter_text(fields: dict[str, str]) -> str:
    body = "".join(f'{key}: "{_yaml_double_quoted_value(value)}"\n' for key, value in fields.items())
    return f"---\n{body}---\n"


def _state_frontmatter_snapshot_dir(target: Path, frontmatter_text: str, timestamp: str) -> str:
    content = target.read_bytes() if target.exists() and target.is_file() else b""
    payload = b"\n".join(
        [
            STATE_FRONTMATTER_REPAIR_CLASS.encode("utf-8"),
            STATE_FRONTMATTER_TARGET_REL.encode("utf-8"),
            frontmatter_text.encode("utf-8"),
            content,
        ]
    )
    hash_prefix = hashlib.sha256(payload).hexdigest()[:12]
    return f"{SNAPSHOT_REPAIR_ROOT_REL}/{timestamp}-{STATE_FRONTMATTER_REPAIR_CLASS}-{STATE_FRONTMATTER_TARGET_SLUG}-{hash_prefix}"


def _state_frontmatter_snapshot_metadata(
    inventory: Inventory,
    timestamp: str,
    snapshot_dir_rel: str,
    copy_rel: str,
    planned_keys: list[str],
    diagnostic: Finding,
    pre_repair_bytes: bytes,
) -> dict[str, object]:
    digest = hashlib.sha256(pre_repair_bytes).hexdigest()
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "created_at_utc": timestamp,
        "tool_name": "mylittleharness",
        "tool_version": __version__,
        "command": "repair --apply",
        "root_kind": inventory.root_kind,
        "repair_class": STATE_FRONTMATTER_REPAIR_CLASS,
        "target_root": str(inventory.root),
        "snapshot_root": snapshot_dir_rel,
        "target_paths": [STATE_FRONTMATTER_TARGET_REL],
        "copied_files": [
            {
                "target_path": STATE_FRONTMATTER_TARGET_REL,
                "snapshot_path": copy_rel,
                "sha256": digest,
                "byte_count": len(pre_repair_bytes),
            }
        ],
        "pre_repair_hashes": {STATE_FRONTMATTER_TARGET_REL: digest},
        "planned_post_repair_paths": [STATE_FRONTMATTER_TARGET_REL],
        "source_diagnostics": [
            {
                "code": diagnostic.code,
                "message": diagnostic.message,
                "source": diagnostic.source,
                "line": diagnostic.line,
            }
        ],
        "planned_route_entries": [],
        "planned_frontmatter_keys": planned_keys,
        "retention": "manual; MyLittleHarness does not silently delete, rotate, compress, move, or hide repair snapshots",
        "rollback_instructions": (
            f"Copy {copy_rel} back to {STATE_FRONTMATTER_TARGET_REL}, then run "
            "python -m mylittleharness --root <target-root> validate and "
            "python -m mylittleharness --root <target-root> audit-links."
        ),
        "authority_note": (
            "snapshot metadata is safety evidence only and cannot approve repair, closeout, archive, commit, "
            "lifecycle decisions, or future repairs"
        ),
    }


def _docmap_snapshot_metadata(
    inventory: Inventory,
    timestamp: str,
    snapshot_dir_rel: str,
    copy_rel: str,
    route_entries: list[str],
    route_diagnostics: list[Finding],
    pre_repair_bytes: bytes,
) -> dict[str, object]:
    digest = hashlib.sha256(pre_repair_bytes).hexdigest()
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "created_at_utc": timestamp,
        "tool_name": "mylittleharness",
        "tool_version": __version__,
        "command": "repair --apply",
        "root_kind": inventory.root_kind,
        "repair_class": DOCMAP_REPAIR_CLASS,
        "target_root": str(inventory.root),
        "snapshot_root": snapshot_dir_rel,
        "target_paths": [DOCMAP_REPAIR_TARGET_REL],
        "copied_files": [
            {
                "target_path": DOCMAP_REPAIR_TARGET_REL,
                "snapshot_path": copy_rel,
                "sha256": digest,
                "byte_count": len(pre_repair_bytes),
            }
        ],
        "pre_repair_hashes": {DOCMAP_REPAIR_TARGET_REL: digest},
        "planned_post_repair_paths": [DOCMAP_REPAIR_TARGET_REL],
        "source_diagnostics": [
            {
                "code": finding.code,
                "message": finding.message,
                "source": finding.source,
                "line": finding.line,
            }
            for finding in route_diagnostics
        ],
        "planned_route_entries": route_entries,
        "retention": "manual; MyLittleHarness does not silently delete, rotate, compress, move, or hide repair snapshots",
        "rollback_instructions": (
            f"Copy {copy_rel} back to {DOCMAP_REPAIR_TARGET_REL}, then run "
            "python -m mylittleharness --root <target-root> validate and "
            "python -m mylittleharness --root <target-root> audit-links."
        ),
        "authority_note": (
            "snapshot metadata is safety evidence only and cannot approve repair, closeout, archive, commit, "
            "lifecycle decisions, or future repairs"
        ),
    }


def _snapshot_inspect_root_posture_findings(inventory: Inventory) -> list[Finding]:
    snapshot_root = inventory.root / SNAPSHOT_REPAIR_ROOT_REL
    if _is_product_source_inventory(inventory):
        if snapshot_root.exists():
            return [
                Finding(
                    "warn",
                    "snapshot-inspect-product-debris",
                    "product-source compatibility fixture contains repair snapshot debris; snapshots belong only in explicit live operating roots",
                    SNAPSHOT_REPAIR_ROOT_REL,
                )
            ]
        return [
            Finding(
                "info",
                "snapshot-inspect-root-posture",
                "product-source compatibility fixture has no repair snapshot debris",
                inventory.state.rel_path if inventory.state else ATTACH_STATE_REL_PATH,
            )
        ]
    if _is_fallback_or_archive_inventory(inventory):
        return [
            Finding(
                "warn",
                "snapshot-inspect-root-posture",
                "target is fallback/archive or generated-output evidence; any snapshots here are historical evidence only, not live repair authority",
                inventory.state.rel_path if inventory.state else None,
            )
        ]
    if inventory.root_kind != "live_operating_root":
        return [
            Finding(
                "warn",
                "snapshot-inspect-root-posture",
                f"target root kind is {inventory.root_kind}; inspection is report-only and cannot establish live repair eligibility",
            )
        ]
    return [
        Finding(
            "info",
            "snapshot-inspect-root-posture",
            "target is a live operating root; inspection remains read-only and does not authorize repair or rollback",
            inventory.state.rel_path if inventory.state else ATTACH_STATE_REL_PATH,
        )
    ]


def _snapshot_inspect_boundary_conflict(root: Path) -> Finding | None:
    for candidate in _root_relative_path_chain(root, SNAPSHOT_REPAIR_ROOT_REL):
        candidate_rel = candidate.relative_to(root).as_posix()
        if candidate.is_symlink():
            return Finding(
                "warn",
                "snapshot-inspect-boundary-conflict",
                f"snapshot boundary contains a symlink segment: {candidate_rel}",
                candidate_rel,
            )
        if candidate.exists() and not candidate.is_dir():
            return Finding(
                "warn",
                "snapshot-inspect-boundary-conflict",
                f"snapshot boundary contains a non-directory segment: {candidate_rel}",
                candidate_rel,
            )
    target = root / SNAPSHOT_REPAIR_ROOT_REL
    if not _path_stays_within_root(root, target):
        return Finding(
            "warn",
            "snapshot-inspect-boundary-conflict",
            f"snapshot boundary would escape the target root: {SNAPSHOT_REPAIR_ROOT_REL}",
            SNAPSHOT_REPAIR_ROOT_REL,
        )
    return None


def _inspect_repair_snapshot(inventory: Inventory, snapshot_dir: Path) -> list[Finding]:
    snapshot_rel = snapshot_dir.relative_to(inventory.root).as_posix()
    findings: list[Finding] = [Finding("info", "snapshot-found", f"repair snapshot found: {snapshot_rel}/", snapshot_rel)]
    metadata_path = snapshot_dir / "snapshot.json"
    metadata_rel = metadata_path.relative_to(inventory.root).as_posix()
    if metadata_path.is_symlink():
        findings.append(Finding("warn", "snapshot-metadata-malformed", f"snapshot metadata is a symlink: {metadata_rel}", metadata_rel))
        return findings
    if not metadata_path.exists():
        findings.append(Finding("warn", "snapshot-metadata-missing", f"snapshot metadata is missing: {metadata_rel}", metadata_rel))
        return findings
    if not metadata_path.is_file():
        findings.append(Finding("warn", "snapshot-metadata-malformed", f"snapshot metadata is not a regular file: {metadata_rel}", metadata_rel))
        return findings

    try:
        metadata_text = metadata_path.read_text(encoding="utf-8")
        metadata = json.loads(metadata_text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        findings.append(Finding("warn", "snapshot-metadata-malformed", f"snapshot metadata could not be read as JSON: {exc}", metadata_rel))
        return findings

    if not isinstance(metadata, dict):
        findings.append(Finding("warn", "snapshot-metadata-malformed", "snapshot metadata must be a JSON object", metadata_rel))
        return findings

    findings.append(Finding("info", "snapshot-metadata-read", f"snapshot metadata read: {metadata_rel}", metadata_rel))
    findings.extend(_snapshot_metadata_contract_findings(inventory, snapshot_dir, metadata))
    return findings


def _snapshot_metadata_contract_findings(inventory: Inventory, snapshot_dir: Path, metadata: dict[str, object]) -> list[Finding]:
    snapshot_rel = snapshot_dir.relative_to(inventory.root).as_posix()
    findings: list[Finding] = []
    missing_fields = [field for field in SNAPSHOT_METADATA_FIELDS if field not in metadata]
    if missing_fields:
        findings.append(
            Finding(
                "warn",
                "snapshot-metadata-missing-field",
                f"snapshot metadata missing fields: {', '.join(missing_fields)}",
                f"{snapshot_rel}/snapshot.json",
            )
        )

    schema_version = metadata.get("schema_version")
    if schema_version == SNAPSHOT_SCHEMA_VERSION:
        findings.append(Finding("info", "snapshot-schema", f"snapshot schema_version: {SNAPSHOT_SCHEMA_VERSION}", f"{snapshot_rel}/snapshot.json"))
    else:
        findings.append(
            Finding(
                "warn",
                "snapshot-schema",
                f"expected schema_version {SNAPSHOT_SCHEMA_VERSION}, found {schema_version!r}",
                f"{snapshot_rel}/snapshot.json",
            )
        )

    repair_class = metadata.get("repair_class")
    if repair_class in {DOCMAP_REPAIR_CLASS, STATE_FRONTMATTER_REPAIR_CLASS}:
        findings.append(Finding("info", "snapshot-repair-class", f"repair class: {repair_class}", f"{snapshot_rel}/snapshot.json"))
    else:
        findings.append(Finding("warn", "snapshot-repair-class", f"unexpected or missing repair class: {repair_class!r}", f"{snapshot_rel}/snapshot.json"))

    command = metadata.get("command")
    if command == "repair --apply":
        findings.append(Finding("info", "snapshot-command", "snapshot was created by repair --apply", f"{snapshot_rel}/snapshot.json"))
    else:
        findings.append(Finding("warn", "snapshot-command", f"unexpected or missing snapshot command: {command!r}", f"{snapshot_rel}/snapshot.json"))

    target_root = metadata.get("target_root")
    if isinstance(target_root, str) and _same_path_value(target_root, inventory.root):
        findings.append(Finding("info", "snapshot-target-root", f"metadata target_root matches inspected root: {target_root}", f"{snapshot_rel}/snapshot.json"))
    else:
        findings.append(
            Finding(
                "warn",
                "snapshot-target-root",
                f"metadata target_root does not match inspected root: {target_root!r}",
                f"{snapshot_rel}/snapshot.json",
            )
        )

    snapshot_root = metadata.get("snapshot_root")
    if snapshot_root == snapshot_rel:
        findings.append(Finding("info", "snapshot-root", f"metadata snapshot_root matches snapshot directory: {snapshot_rel}", f"{snapshot_rel}/snapshot.json"))
    else:
        findings.append(Finding("warn", "snapshot-root", f"metadata snapshot_root does not match snapshot directory: {snapshot_root!r}", f"{snapshot_rel}/snapshot.json"))

    copied_files = metadata.get("copied_files")
    if not isinstance(copied_files, list) or not copied_files:
        findings.append(Finding("warn", "snapshot-copied-file-missing", "snapshot metadata has no copied_files records", f"{snapshot_rel}/snapshot.json"))
    else:
        for index, record in enumerate(copied_files):
            findings.extend(_snapshot_copied_file_findings(inventory, snapshot_dir, metadata, record, index))

    planned_frontmatter_keys = metadata.get("planned_frontmatter_keys")
    if repair_class == STATE_FRONTMATTER_REPAIR_CLASS:
        if isinstance(planned_frontmatter_keys, list) and all(isinstance(key, str) for key in planned_frontmatter_keys):
            findings.append(
                Finding(
                    "info",
                    "snapshot-planned-frontmatter",
                    f"planned frontmatter keys: {', '.join(planned_frontmatter_keys)}",
                    f"{snapshot_rel}/snapshot.json",
                )
            )
        else:
            findings.append(
                Finding(
                    "warn",
                    "snapshot-planned-frontmatter",
                    f"state frontmatter snapshot has malformed planned_frontmatter_keys: {planned_frontmatter_keys!r}",
                    f"{snapshot_rel}/snapshot.json",
                )
            )

    retention = metadata.get("retention")
    if isinstance(retention, str) and "manual" in retention.casefold():
        findings.append(Finding("info", "snapshot-retention", f"retention posture: {retention}", f"{snapshot_rel}/snapshot.json"))
    else:
        findings.append(Finding("warn", "snapshot-retention", f"manual retention posture missing or unclear: {retention!r}", f"{snapshot_rel}/snapshot.json"))

    authority_note = metadata.get("authority_note")
    if isinstance(authority_note, str) and "cannot approve" in authority_note.casefold():
        findings.append(Finding("info", "snapshot-authority", "metadata authority note preserves snapshot non-authority", f"{snapshot_rel}/snapshot.json"))
    else:
        findings.append(Finding("warn", "snapshot-authority", "metadata authority note is missing or does not preserve snapshot non-authority", f"{snapshot_rel}/snapshot.json"))

    rollback_instructions = metadata.get("rollback_instructions")
    if isinstance(rollback_instructions, str) and rollback_instructions.strip():
        findings.append(Finding("info", "snapshot-rollback", f"metadata rollback instructions: {rollback_instructions}", f"{snapshot_rel}/snapshot.json"))
    else:
        findings.append(Finding("warn", "snapshot-rollback", "metadata rollback instructions are missing", f"{snapshot_rel}/snapshot.json"))
    return findings


def _snapshot_copied_file_findings(
    inventory: Inventory,
    snapshot_dir: Path,
    metadata: dict[str, object],
    record: object,
    index: int,
) -> list[Finding]:
    snapshot_rel = snapshot_dir.relative_to(inventory.root).as_posix()
    source = f"{snapshot_rel}/snapshot.json"
    if not isinstance(record, dict):
        return [Finding("warn", "snapshot-copied-file-malformed", f"copied_files[{index}] must be an object", source)]

    target_rel, target_path_finding = _snapshot_metadata_rel_path(inventory.root, record.get("target_path"), "target_path", source)
    snapshot_path_rel, snapshot_path_finding = _snapshot_metadata_rel_path(inventory.root, record.get("snapshot_path"), "snapshot_path", source)
    findings = [finding for finding in (target_path_finding, snapshot_path_finding) if finding]
    if target_rel is None or snapshot_path_rel is None:
        return findings

    copy_path = inventory.root / snapshot_path_rel
    target_path = inventory.root / target_rel
    if not _path_stays_within_root(snapshot_dir, copy_path):
        findings.append(
            Finding(
                "warn",
                "snapshot-path-conflict",
                f"copied file path is not inside this snapshot directory: {snapshot_path_rel}",
                source,
            )
        )
        return findings

    copied_conflict = _snapshot_existing_file_conflict(inventory.root, snapshot_path_rel, "copied file")
    if copied_conflict:
        findings.append(copied_conflict)
        return findings
    target_conflict = _snapshot_existing_file_conflict(inventory.root, target_rel, "target file")
    target_safe = target_conflict is None
    if target_conflict:
        findings.append(target_conflict)

    if not copy_path.exists():
        findings.append(Finding("warn", "snapshot-copied-file-missing", f"copied file is missing: {snapshot_path_rel}", snapshot_path_rel))
        return findings
    if not copy_path.is_file():
        findings.append(Finding("warn", "snapshot-copied-file-malformed", f"copied file is not a regular file: {snapshot_path_rel}", snapshot_path_rel))
        return findings

    try:
        copied_bytes = copy_path.read_bytes()
    except OSError as exc:
        findings.append(Finding("warn", "snapshot-copied-file-malformed", f"copied file could not be read: {exc}", snapshot_path_rel))
        return findings

    digest = hashlib.sha256(copied_bytes).hexdigest()
    expected_sha = record.get("sha256")
    if isinstance(expected_sha, str) and expected_sha == digest:
        findings.append(Finding("info", "snapshot-copied-file-hash", f"copied file sha256 matches metadata: {snapshot_path_rel}", snapshot_path_rel))
    else:
        findings.append(
            Finding(
                "warn",
                "snapshot-copied-file-hash",
                f"copied file sha256 mismatch for {snapshot_path_rel}: metadata={expected_sha!r}, actual={digest}",
                snapshot_path_rel,
            )
        )

    expected_size = record.get("byte_count")
    if isinstance(expected_size, int) and expected_size == len(copied_bytes):
        findings.append(Finding("info", "snapshot-copied-file-size", f"copied file byte_count matches metadata: {len(copied_bytes)}", snapshot_path_rel))
    else:
        findings.append(
            Finding(
                "warn",
                "snapshot-copied-file-size",
                f"copied file byte_count mismatch for {snapshot_path_rel}: metadata={expected_size!r}, actual={len(copied_bytes)}",
                snapshot_path_rel,
            )
        )

    pre_hashes = metadata.get("pre_repair_hashes")
    if isinstance(pre_hashes, dict) and pre_hashes.get(target_rel) not in (None, digest):
        findings.append(
            Finding(
                "warn",
                "snapshot-pre-repair-hash",
                f"pre_repair_hashes[{target_rel}] does not match copied bytes: {pre_hashes.get(target_rel)!r}",
                source,
            )
        )
    elif isinstance(pre_hashes, dict) and pre_hashes.get(target_rel) == digest:
        findings.append(Finding("info", "snapshot-pre-repair-hash", f"pre-repair hash matches copied bytes for {target_rel}", source))

    if target_safe:
        findings.extend(_snapshot_current_target_findings(target_path, target_rel, digest))
    findings.append(
        Finding(
            "info",
            "snapshot-rollback",
            f"manual rollback only: copy {snapshot_path_rel} back to {target_rel}; then run validate and audit-links",
            snapshot_path_rel,
        )
    )
    return findings


def _snapshot_metadata_rel_path(root: Path, value: object, field_name: str, source: str) -> tuple[str | None, Finding | None]:
    if not isinstance(value, str) or not value.strip():
        return None, Finding("warn", "snapshot-path-conflict", f"{field_name} is missing or not a string: {value!r}", source)
    normalized = value.strip().replace("\\", "/")
    if _is_absolute_path(normalized):
        return None, Finding("warn", "snapshot-path-conflict", f"{field_name} must be target-root relative, not absolute: {normalized}", source)
    if any(part == ".." for part in Path(normalized).parts):
        return None, Finding("warn", "snapshot-path-conflict", f"{field_name} must not contain parent traversal: {normalized}", source)
    if not _path_stays_within_root(root, root / normalized):
        return None, Finding("warn", "snapshot-path-conflict", f"{field_name} would escape the target root: {normalized}", source)
    return normalized, None


def _snapshot_existing_file_conflict(root: Path, rel_path: str, label: str) -> Finding | None:
    target = root / rel_path
    for candidate in _root_relative_path_chain(root, rel_path):
        candidate_rel = candidate.relative_to(root).as_posix()
        if candidate.is_symlink():
            return Finding("warn", "snapshot-path-conflict", f"{label} path contains a symlink segment: {candidate_rel}", candidate_rel)
        if candidate.exists() and candidate != target and not candidate.is_dir():
            return Finding("warn", "snapshot-path-conflict", f"{label} path contains a non-directory segment: {candidate_rel}", candidate_rel)
    if target.exists() and not target.is_file():
        return Finding("warn", "snapshot-path-conflict", f"{label} path is not a regular file: {rel_path}", rel_path)
    return None


def _snapshot_current_target_findings(target_path: Path, target_rel: str, copied_digest: str) -> list[Finding]:
    if not target_path.exists():
        return [Finding("warn", "snapshot-target-missing", f"current target is missing: {target_rel}", target_rel)]
    if not target_path.is_file():
        return [Finding("warn", "snapshot-target-conflict", f"current target is not a regular file: {target_rel}", target_rel)]
    try:
        target_digest = hashlib.sha256(target_path.read_bytes()).hexdigest()
    except OSError as exc:
        return [Finding("warn", "snapshot-target-conflict", f"current target could not be read: {exc}", target_rel)]
    if target_digest == copied_digest:
        return [
            Finding(
                "info",
                "snapshot-target-current",
                f"current target still matches copied pre-repair bytes: {target_rel}",
                target_rel,
            )
        ]
    return [
        Finding(
            "info",
            "snapshot-target-current",
            f"current target differs from copied pre-repair bytes: {target_rel}; snapshot remains rollback evidence only",
            target_rel,
        )
    ]


def _snapshot_target_conflict(root: Path, rel_path: str) -> Finding | None:
    for candidate in _root_relative_path_chain(root, rel_path):
        candidate_rel = candidate.relative_to(root).as_posix()
        if candidate.is_symlink():
            return Finding("warn", "snapshot-plan-refused", f"target path contains a symlink segment: {candidate_rel}", candidate_rel)
        if candidate.exists() and candidate != root / rel_path and not candidate.is_dir():
            return Finding("warn", "snapshot-plan-refused", f"target path contains a non-directory segment: {candidate_rel}", candidate_rel)
    target = root / rel_path
    if target.exists() and not target.is_file():
        return Finding("warn", "snapshot-plan-refused", f"target path is not a regular file: {rel_path}", rel_path)
    if not _path_stays_within_root(root, target):
        return Finding("warn", "snapshot-plan-refused", f"target path would escape the target root: {rel_path}", rel_path)
    return None


def _snapshot_boundary_conflict(root: Path, snapshot_dir_rel: str) -> Finding | None:
    for rel_path in (SNAPSHOT_REPAIR_ROOT_REL, snapshot_dir_rel):
        for candidate in _root_relative_path_chain(root, rel_path):
            candidate_rel = candidate.relative_to(root).as_posix()
            if candidate.is_symlink():
                return Finding("warn", "snapshot-plan-refused", f"snapshot boundary contains a symlink segment: {candidate_rel}", candidate_rel)
            if candidate.exists() and not candidate.is_dir():
                return Finding("warn", "snapshot-plan-refused", f"snapshot boundary contains a non-directory segment: {candidate_rel}", candidate_rel)
    target = root / snapshot_dir_rel
    if target.exists():
        return Finding("warn", "snapshot-plan-refused", f"planned snapshot directory already exists: {snapshot_dir_rel}", snapshot_dir_rel)
    if not _path_stays_within_root(root, target):
        return Finding("warn", "snapshot-plan-refused", f"snapshot path would escape the target root: {snapshot_dir_rel}", snapshot_dir_rel)
    return None


def _path_stays_within_root(root: Path, target: Path) -> bool:
    try:
        target.resolve(strict=False).relative_to(root.resolve())
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def product_hygiene_findings(inventory: Inventory) -> list[Finding]:
    if not _is_product_source_inventory(inventory):
        return [Finding("info", "product-hygiene-scope", "product hygiene check skipped because root is not marked as product source")]

    findings: list[Finding] = []
    for path, rel_path in _iter_hygiene_paths(inventory.root):
        classification = _classify_product_hygiene_path(path, rel_path)
        if classification is None:
            continue
        code, reason = classification
        if code == "forbidden-product-surface":
            message = f"operational surface must not live in product root: {rel_path}; {reason}"
        else:
            message = f"unexpected product-root debris: {rel_path}; {reason}; report only, no deletion performed"
        findings.append(Finding("warn", code, message, rel_path))

    if not findings:
        findings.append(Finding("info", "product-hygiene-ok", "no product-root debris found"))
    return findings


class LinkResolution:
    def __init__(self, kind: str, exists: bool = False) -> None:
        self.kind = kind
        self.exists = exists


def resolve_link(root: Path, target: str, source_rel: str | None = None) -> LinkResolution:
    clean = target.strip().strip("<>").strip()
    if not clean:
        return LinkResolution("unresolved", False)
    if clean.startswith("#"):
        return LinkResolution("anchor", True)
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", clean) or clean.startswith("mailto:"):
        return LinkResolution("external", True)
    path_part = clean.split("#", 1)[0]
    if not path_part:
        return LinkResolution("anchor", True)
    base = _link_base(root, path_part, source_rel)
    if any(char in path_part for char in "*?[]{}"):
        patterns = _expand_brace_pattern(path_part)
        exists = False
        for pattern in patterns:
            resolved_pattern = pattern if _is_absolute_path(pattern) else str(base / pattern)
            if glob.glob(resolved_pattern):
                exists = True
                break
            if "{" in pattern or "}" in pattern:
                continue
            if Path(resolved_pattern).exists():
                exists = True
                break
        return LinkResolution("pattern", exists)
    if _is_absolute_path(path_part):
        candidate = Path(path_part)
    else:
        candidate = base / path_part
    return LinkResolution("local", candidate.exists())


def _required_surface_findings(inventory: Inventory) -> list[Finding]:
    findings = []
    for surface in inventory.surfaces:
        if surface.required and not surface.exists:
            findings.append(Finding("error", "missing-required-surface", f"missing required surface: {surface.rel_path}", surface.rel_path))
    return findings


def _manifest_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    manifest = inventory.manifest_surface
    if not manifest or not manifest.exists:
        return findings
    for error in inventory.manifest_errors:
        findings.append(Finding("error", "manifest-parse", error, manifest.rel_path))
    workflow = inventory.manifest.get("workflow") if isinstance(inventory.manifest, dict) else None
    if workflow != "workflow-core":
        findings.append(Finding("warn", "manifest-workflow", "manifest workflow is not workflow-core", manifest.rel_path))
    memory = inventory.manifest.get("memory", {}) if isinstance(inventory.manifest, dict) else {}
    if memory.get("state_file", "project/project-state.md") != "project/project-state.md":
        findings.append(Finding("warn", "manifest-state-file", "manifest state_file differs from project/project-state.md", manifest.rel_path))
    if memory.get("plan_file", "project/implementation-plan.md") != "project/implementation-plan.md":
        findings.append(Finding("warn", "manifest-plan-file", "manifest plan_file differs from project/implementation-plan.md", manifest.rel_path))
    return findings


def _state_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    state = inventory.state
    if not state or not state.exists:
        return findings
    if not state.frontmatter.has_frontmatter:
        if inventory.root_kind == "live_operating_root" and _has_read_only_state_assignments(state):
            findings.append(
                Finding(
                    "info",
                    "state-prose-fallback",
                    "project-state.md has no frontmatter; read-only assignment fallback is used for status and validation only",
                    state.rel_path,
                )
            )
            return findings
        findings.append(Finding("error", "state-frontmatter", "project-state.md is missing frontmatter", state.rel_path))
        return findings
    for key in ("project", "workflow", "operating_mode", "plan_status"):
        if not state.frontmatter.data.get(key):
            findings.append(Finding("error", "state-frontmatter-field", f"project-state.md missing frontmatter key: {key}", state.rel_path))
    if inventory.root_kind == "live_operating_root":
        findings.extend(_live_product_source_root_findings(inventory, state))
        findings.extend(_state_lifecycle_prose_drift_findings(state))
    return findings


def _state_lifecycle_prose_drift_findings(state: Surface) -> list[Finding]:
    plan_status = str(state.frontmatter.data.get("plan_status") or "")
    if plan_status not in {"active", "none", ""}:
        return []

    findings: list[Finding] = []
    for line_number, line in _current_state_authority_lines(state.content):
        normalized = line.casefold()
        if plan_status == "none" and _line_says_active_plan_is_open(normalized):
            findings.append(
                Finding(
                    "warn",
                    "state-lifecycle-prose-drift",
                    (
                        "project-state frontmatter records plan_status='none' but current prose says an active plan is open; "
                        "rewrite the prose as historical context or preview whole-state history compaction with writeback --dry-run --compact-only"
                    ),
                    state.rel_path,
                    line_number,
                )
            )
        elif plan_status == "active" and _line_says_no_active_plan_is_open(normalized):
            findings.append(
                Finding(
                    "warn",
                    "state-lifecycle-prose-drift",
                    (
                        "project-state frontmatter records plan_status='active' but current prose says no active plan is open; "
                        "rewrite the prose as historical context or refresh managed focus with writeback/plan apply"
                    ),
                    state.rel_path,
                    line_number,
                )
            )
    return findings


def _current_state_authority_lines(text: str) -> list[tuple[int, str]]:
    excluded_spans = _managed_state_spans(text)
    lines = text.splitlines()
    current_section = ""
    results: list[tuple[int, str]] = []
    for index, line in enumerate(lines, start=1):
        if any(start <= index <= end for start, end in excluded_spans):
            continue
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            current_section = heading.group(1).strip()
            continue
        if _state_section_is_historical(current_section):
            continue
        if line.strip():
            results.append((index, line))
    return results


def _managed_state_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for begin, end in (
        (CURRENT_FOCUS_BEGIN, CURRENT_FOCUS_END),
        (MEMORY_ROADMAP_BEGIN, MEMORY_ROADMAP_END),
        ("<!-- BEGIN mylittleharness-closeout-writeback v1 -->", "<!-- END mylittleharness-closeout-writeback v1 -->"),
    ):
        spans.extend(_marker_spans(text, begin, end))
    return spans


def _marker_spans(text: str, begin: str, end: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start: int | None = None
    for index, line in enumerate(text.splitlines(), start=1):
        if line.strip() == begin:
            start = index
            continue
        if line.strip() == end and start is not None:
            spans.append((start, index))
            start = None
    return spans


def _state_section_is_historical(title: str) -> bool:
    normalized = title.casefold()
    return normalized.startswith(
        (
            "ad hoc update",
            "active plan implementation update",
            "active plan validation refresh",
            "archived state history",
            "research update",
            "mlh closeout writeback",
        )
    )


def _line_says_active_plan_is_open(normalized_line: str) -> bool:
    return (
        "active implementation plan is open" in normalized_line
        or "active plan is open" in normalized_line
        or "current active-plan pointer" in normalized_line
    )


def _line_says_no_active_plan_is_open(normalized_line: str) -> bool:
    return (
        "no active implementation plan is open" in normalized_line
        or "no active plan is open" in normalized_line
        or "no active-plan pointer" in normalized_line
    )


def _live_product_source_root_findings(inventory: Inventory, state: Surface) -> list[Finding]:
    value = state.frontmatter.data.get("product_source_root")
    if not value:
        return []
    text = _display_path_value(str(value)).strip()
    try:
        candidate = Path(text).expanduser()
        if not candidate.is_absolute():
            candidate = inventory.root / candidate
        resolved = candidate.resolve()
    except (OSError, RuntimeError) as exc:
        return [Finding("warn", "product-source-root-invalid", f"product_source_root could not be resolved: {exc}", state.rel_path)]
    try:
        root_resolved = inventory.root.resolve()
    except (OSError, RuntimeError):
        root_resolved = inventory.root
    if not resolved.exists():
        return [Finding("warn", "product-source-root-missing", f"product_source_root does not exist: {text}", state.rel_path)]
    if not resolved.is_dir():
        return [Finding("warn", "product-source-root-invalid", f"product_source_root is not a directory: {text}", state.rel_path)]
    if str(resolved).casefold() == str(root_resolved).casefold():
        return [Finding("warn", "product-source-root-invalid", "product_source_root points at the operating root", state.rel_path)]
    return [Finding("info", "product-source-root-ok", f"product_source_root exists: {resolved}", state.rel_path)]


def _has_read_only_state_assignments(state: Surface) -> bool:
    data = state.frontmatter.data
    return bool(data.get("operating_mode") and data.get("plan_status"))


def _product_posture_status_findings(inventory: Inventory) -> list[Finding]:
    state = inventory.state
    if not state or not state.exists:
        return []
    data = state.frontmatter.data
    findings: list[Finding] = []
    product_name = data.get("project")
    root_role = data.get("root_role")
    fixture_status = data.get("fixture_status")
    operating_root = data.get("operating_root") or data.get("canonical_source_evidence_root")
    product_root = data.get("product_source_root") or data.get("projection_root")
    fallback_root = data.get("historical_fallback_root")

    if product_name:
        findings.append(Finding("info", "product-name", f"product name: {product_name}", state.rel_path))
    if root_role:
        findings.append(Finding("info", "target-root-role", f"target root role: {root_role}", state.rel_path))
    if fixture_status:
        findings.append(Finding("info", "fixture-status", f"fixture status: {fixture_status}", state.rel_path))
    if operating_root:
        findings.append(Finding("info", "operating-root", f"operating root: {operating_root}", state.rel_path))
    if product_root:
        findings.append(Finding("info", "product-root", f"product root: {product_root}", state.rel_path))
    if fallback_root:
        findings.append(Finding("info", "fallback-root", f"fallback root: {fallback_root}", state.rel_path))
    return findings


def _product_posture_findings(inventory: Inventory) -> list[Finding]:
    if not _is_mylittleharness_product_context(inventory):
        return []
    state = inventory.state
    if not state or not state.exists:
        return []
    data = state.frontmatter.data
    findings: list[Finding] = []

    required = (
        "project",
        "root_role",
        "fixture_status",
        "operating_root",
        "product_source_root",
        "historical_fallback_root",
    )
    for key in required:
        if data.get(key) in (None, ""):
            findings.append(Finding("error", "product-posture-field", f"product-root posture missing field: {key}", state.rel_path))

    if data.get("project") not in (None, "", EXPECTED_PRODUCT_NAME):
        findings.append(
            Finding(
                "error",
                "product-posture-product-name",
                f"product-root posture names {data.get('project')!r}; expected {EXPECTED_PRODUCT_NAME}",
                state.rel_path,
            )
        )
    if data.get("root_role") not in (None, "", EXPECTED_PRODUCT_ROOT_ROLE):
        findings.append(
            Finding(
                "error",
                "product-posture-root-role",
                f"product-root posture has root_role={data.get('root_role')!r}; expected {EXPECTED_PRODUCT_ROOT_ROLE}",
                state.rel_path,
            )
        )
    if data.get("fixture_status") not in (None, "", EXPECTED_PRODUCT_FIXTURE_STATUS):
        findings.append(
            Finding(
                "error",
                "product-posture-fixture-status",
                f"product-root posture has fixture_status={data.get('fixture_status')!r}; expected {EXPECTED_PRODUCT_FIXTURE_STATUS}",
                state.rel_path,
            )
        )

    operating_root = data.get("operating_root")
    product_root = data.get("product_source_root")
    fallback_root = data.get("historical_fallback_root")
    if product_root and not _same_path_value(product_root, inventory.root):
        findings.append(
            Finding(
                "error",
                "product-posture-product-root",
                f"product_source_root does not match target root: {product_root}",
                state.rel_path,
            )
        )
    if operating_root and _same_path_value(operating_root, inventory.root):
        findings.append(
            Finding(
                "error",
                "product-posture-operating-root",
                "operating_root points at the product source root; operating memory must stay outside the product tree",
                state.rel_path,
            )
        )
    if fallback_root and _same_path_value(fallback_root, inventory.root):
        findings.append(
            Finding(
                "error",
                "product-posture-fallback-root",
                "historical_fallback_root points at the product source root",
                state.rel_path,
            )
        )
    if data.get("plan_status") == "active" or data.get("active_plan") not in (None, "") or (
        inventory.active_plan_surface and inventory.active_plan_surface.exists
    ):
        findings.append(
            Finding(
                "error",
                "product-posture-active-plan",
                "product source root must not contain or own an active implementation plan; use the operating root",
                state.rel_path,
            )
        )
    return findings


def _active_plan_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    state = inventory.state
    data = state.frontmatter.data if state else {}
    status = data.get("plan_status")
    active_plan = data.get("active_plan") or "project/implementation-plan.md"
    plan = inventory.active_plan_surface
    if status == "active":
        if not data.get("active_plan"):
            findings.append(Finding("error", "active-plan-field", "plan_status is active but active_plan is empty", state.rel_path if state else None))
        if not plan or not plan.exists:
            findings.append(Finding("error", "active-plan-missing", f"plan_status is active but {active_plan} is missing", active_plan))
        if not data.get("active_phase"):
            findings.append(
                Finding(
                    "warn",
                    "active-phase-field",
                    "plan_status is active but active_phase is empty; record the current plan phase explicitly",
                    state.rel_path if state else None,
                )
            )
        phase_status = str(data.get("phase_status") or "")
        if not phase_status:
            findings.append(
                Finding(
                    "warn",
                    "phase-status-field",
                    "plan_status is active but phase_status is empty; record one of: active, blocked, complete, in_progress, paused, pending, skipped",
                    state.rel_path if state else None,
                )
            )
        elif phase_status not in PHASE_STATUS_VALUES:
            findings.append(
                Finding(
                    "warn",
                    "phase-status-value",
                    f"phase_status is {phase_status!r}; expected one of: active, blocked, complete, in_progress, paused, pending, skipped",
                    state.rel_path if state else None,
                )
            )
        if plan and plan.exists:
            findings.extend(_active_plan_generated_shape_findings(plan))
            findings.extend(_active_plan_execution_policy_findings(plan, data))
            findings.extend(_active_plan_docs_decision_findings(plan, data))
            findings.extend(_active_plan_writeback_drift_findings(inventory, plan, data))
            findings.extend(_active_plan_lifecycle_drift_findings(inventory, plan, data))
            findings.extend(_active_plan_source_incubation_relationship_findings(inventory, plan))
    elif plan and plan.exists:
        findings.append(Finding("warn", "stale-plan-file", "implementation plan exists while plan_status is not active", plan.rel_path))
    manifest_plan = inventory.manifest.get("memory", {}).get("plan_file") if inventory.manifest else None
    if status == "active" and manifest_plan and str(active_plan).replace("\\", "/") != str(manifest_plan).replace("\\", "/"):
        findings.append(Finding("error", "active-plan-manifest", "active_plan differs from manifest memory.plan_file", state.rel_path if state else None))
    return findings


def _active_plan_source_incubation_relationship_findings(inventory: Inventory, plan: Surface) -> list[Finding]:
    if not plan.frontmatter.has_frontmatter:
        return []
    source_incubation = _normalize_route_metadata_path(str(plan.frontmatter.data.get("source_incubation") or ""))
    if not source_incubation:
        return []
    source_surface = inventory.surface_by_rel.get(source_incubation)
    if not source_surface or not source_surface.exists or not source_surface.frontmatter.has_frontmatter:
        return []
    related_plan = _normalize_route_metadata_path(str(source_surface.frontmatter.data.get("related_plan") or ""))
    if related_plan == "project/implementation-plan.md":
        return []
    display = related_plan or "<empty>"
    return [
        Finding(
            "warn",
            "active-plan-source-incubation-related-plan-drift",
            (
                f"active plan source_incubation {source_incubation} has related_plan {display!r}; "
                "plan --apply --roadmap-item should sync the source incubation back to project/implementation-plan.md "
                "when opening this active plan"
            ),
            source_incubation,
        )
    ]


def _active_plan_generated_shape_findings(plan: Surface) -> list[Finding]:
    if not plan.frontmatter.has_frontmatter or not plan.frontmatter.data.get("plan_id"):
        return []
    heading_titles = {heading.title for heading in plan.headings}
    required = {
        "Objective",
        "Authority Inputs",
        "Non-goals",
        "Invariants",
        "File Ownership",
        "Phases",
        "Verification Strategy",
        "Docs Decision",
        "State Transfer",
        "Refusal Conditions",
        "Closeout Checklist",
        "Decision Log",
    }
    missing = sorted(required - heading_titles)
    if not missing:
        return []
    return [
        Finding(
            "warn",
            "active-plan-generated-shape",
            f"generated active plan is missing expected sections: {', '.join(missing)}",
            plan.rel_path,
        )
    ]


def _active_plan_execution_policy_findings(plan: Surface, state_data: dict[str, object]) -> list[Finding]:
    active_phase = str(state_data.get("active_phase") or "")
    phase_metadata = _active_phase_contract_metadata(plan, active_phase)
    plan_data = plan.frontmatter.data if plan.frontmatter.has_frontmatter else {}
    policy_raw, policy_line = _contract_entry("execution_policy", phase_metadata, plan_data)
    auto_raw, auto_line = _contract_entry("auto_continue", phase_metadata, plan_data)
    stop_raw, stop_line = _contract_entry("stop_conditions", phase_metadata, plan_data)
    findings: list[Finding] = []

    policy = _contract_text(policy_raw).casefold()
    if not policy:
        findings.append(
            Finding(
                "info",
                "active-plan-execution-policy",
                f"active plan has no execution_policy metadata; {CURRENT_PHASE_ONLY_POLICY} default applies to active_phase {active_phase or '<unset>'}",
                plan.rel_path,
            )
        )
    elif policy == CURRENT_PHASE_ONLY_POLICY:
        findings.append(
            Finding(
                "info",
                "active-plan-execution-policy",
                f"active plan execution_policy is {CURRENT_PHASE_ONLY_POLICY}; continue only active_phase {active_phase or '<unset>'} until explicit lifecycle writeback",
                plan.rel_path,
                policy_line,
            )
        )
    else:
        findings.append(
            Finding(
                "warn",
                "active-plan-execution-policy-value",
                f"active plan execution_policy is {policy_raw!r}; expected {CURRENT_PHASE_ONLY_POLICY!r}; current-phase-only fallback applies",
                plan.rel_path,
                policy_line,
            )
        )

    auto_continue = _contract_bool(auto_raw)
    if auto_raw is None:
        findings.append(
            Finding(
                "info",
                "active-plan-auto-continue-stop",
                "auto_continue metadata is absent; current-phase-only stop applies and no future phase is authorized",
                plan.rel_path,
            )
        )
    elif auto_continue is False:
        findings.append(
            Finding(
                "info",
                "active-plan-auto-continue-stop",
                "auto_continue is false; current-phase-only stop applies and no future phase is authorized by verification success alone",
                plan.rel_path,
                auto_line,
            )
        )
    elif auto_continue is None:
        findings.append(
            Finding(
                "warn",
                "active-plan-auto-continue-value",
                f"auto_continue is {auto_raw!r}; expected true or false, so current-phase-only stop applies",
                plan.rel_path,
                auto_line,
            )
        )
    else:
        stop_conditions = _contract_list(stop_raw)
        if not stop_conditions:
            findings.append(
                Finding(
                    "warn",
                    "active-plan-auto-continue-stop-conditions",
                    "auto_continue is true but no stop_conditions metadata was found; automatic continuation is unsafe",
                    plan.rel_path,
                    stop_line or auto_line,
                )
            )
        else:
            missing = _missing_stop_condition_coverage(stop_conditions)
            if missing:
                findings.append(
                    Finding(
                        "warn",
                        "active-plan-auto-continue-stop-conditions",
                        f"auto_continue is true but stop_conditions miss coverage for: {', '.join(missing)}",
                        plan.rel_path,
                        stop_line or auto_line,
                    )
                )
            else:
                findings.append(
                    Finding(
                        "info",
                        "active-plan-auto-continue-candidate",
                        "auto_continue is explicit and stop_conditions cover verification, authority, write-scope, source-reality, sensitive-action, and closeout boundaries",
                        plan.rel_path,
                        auto_line,
                    )
                )

    if stop_raw in (None, ""):
        findings.append(
            Finding(
                "info",
                "active-plan-stop-conditions",
                "stop_conditions metadata is absent; current-phase-only remains the safe default stop",
                plan.rel_path,
            )
        )
    return findings


def _contract_entry(
    key: str,
    phase_metadata: dict[str, tuple[object, int]],
    plan_data: dict[str, object],
) -> tuple[object | None, int | None]:
    if key in phase_metadata:
        value, line = phase_metadata[key]
        return value, line
    if key in plan_data:
        return plan_data[key], None
    return None, None


def _active_phase_contract_metadata(plan: Surface, active_phase: str) -> dict[str, tuple[object, int]]:
    block = _active_phase_block(plan.content, active_phase)
    if block is None:
        return {}
    lines = plan.content.splitlines(keepends=True)
    metadata: dict[str, tuple[object, int]] = {}
    for index in range(block[0] + 1, block[1]):
        match = re.match(
            r"^\s*[-*]\s*(execution_policy|auto_continue|stop_conditions)\s*:\s*(.*?)\s*(?:\r?\n)?$",
            lines[index],
            re.IGNORECASE,
        )
        if not match:
            continue
        key = match.group(1).casefold()
        raw_value = match.group(2).strip()
        if key == "stop_conditions" and raw_value == "":
            metadata[key] = (_phase_list_values(lines, index + 1, block[1]), index + 1)
        else:
            metadata[key] = (_contract_parse_scalar(raw_value), index + 1)
    return metadata


def _active_phase_block(text: str, active_phase: str) -> tuple[int, int] | None:
    target = active_phase.strip()
    if not target:
        return None
    lines = text.splitlines(keepends=True)
    headings: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^(#{2,6})\s+(.+?)\s*#*\s*(?:\r?\n)?$", line)
        if match:
            headings.append((index, len(match.group(1)), match.group(2).strip()))
    candidates: list[tuple[int, int]] = []
    for heading_index, (start, level, title) in enumerate(headings):
        end = len(lines)
        for next_start, next_level, _next_title in headings[heading_index + 1 :]:
            if next_level <= level:
                end = next_start
                break
        if _contract_heading_matches(title, target) or _phase_block_has_contract_id(lines, start, end, target):
            candidates.append((start, end))
    if not candidates:
        return None
    return min(candidates, key=lambda item: (item[1] - item[0], item[0]))


def _contract_heading_matches(title: str, active_phase: str) -> bool:
    normalized_title = _contract_text(title).casefold()
    normalized_phase = active_phase.casefold()
    return normalized_title == normalized_phase or normalized_phase in normalized_title


def _phase_block_has_contract_id(lines: list[str], start: int, end: int, active_phase: str) -> bool:
    for line in lines[start + 1 : end]:
        match = re.match(r"^\s*[-*]\s*id\s*:\s*(.+?)\s*(?:\r?\n)?$", line, re.IGNORECASE)
        if match and _contract_text(match.group(1)) == active_phase:
            return True
    return False


def _phase_list_values(lines: list[str], start: int, end: int) -> list[str]:
    values: list[str] = []
    for index in range(start, end):
        match = re.match(r"^\s+[-*]\s+(.+?)\s*(?:\r?\n)?$", lines[index])
        if not match:
            break
        values.append(_contract_text(match.group(1)))
    return values


def _contract_parse_scalar(raw_value: str) -> object:
    value = _contract_text(raw_value)
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_contract_parse_scalar(part.strip()) for part in inner.split(",")]
    normalized = value.casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return value


def _contract_text(value: object) -> str:
    text = str(value or "").strip()
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        text = text[1:-1].strip()
    if text.startswith("`") and text.endswith("`") and len(text) >= 2:
        text = text[1:-1].strip()
    return text


def _contract_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    normalized = _contract_text(value).casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return None


def _contract_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_contract_text(item) for item in value if _contract_text(item)]
    text = _contract_text(value)
    if not text:
        return []
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_contract_text(part) for part in inner.split(",") if _contract_text(part)]
    return [text]


def _missing_stop_condition_coverage(stop_conditions: list[str]) -> list[str]:
    normalized = "\n".join(stop_conditions).casefold()
    missing: list[str] = []
    for label, markers in AUTO_CONTINUE_STOP_COVERAGE:
        if not any(marker in normalized for marker in markers):
            missing.append(label)
    return missing


def _active_plan_lifecycle_drift_findings(inventory: Inventory, plan: Surface, state_data: dict[str, object]) -> list[Finding]:
    findings: list[Finding] = []
    phase_status = str(state_data.get("phase_status") or "")
    if not phase_status or phase_status not in PHASE_STATUS_VALUES:
        return findings

    if plan.frontmatter.has_frontmatter:
        plan_status = str(plan.frontmatter.data.get("status") or "")
        if plan_status and plan_status != phase_status and phase_status == "complete" and plan_status == "active":
            findings.append(
                Finding(
                    "warn",
                    "active-plan-lifecycle-drift",
                    (
                        "project-state phase_status is complete but active-plan frontmatter status is active; "
                        "writeback --apply --phase-status complete synchronizes the derived active-plan status copy"
                    ),
                    plan.rel_path,
                )
            )

    active_phase = str(state_data.get("active_phase") or "")
    body_fact = active_plan_phase_body_status_fact(plan, active_phase)
    handoff_body_drift = bool(
        body_fact and phase_status == "pending" and body_fact.value in PHASE_BODY_TERMINAL_STATUS_VALUES
    )
    findings.extend(active_plan_completed_phase_handoff_findings(inventory))
    if body_fact:
        expected_body_status = canonical_phase_body_status(phase_status)
        if body_fact.value != expected_body_status and not handoff_body_drift:
            findings.append(
                Finding(
                    "warn",
                    "active-plan-phase-body-drift",
                    (
                        f"project-state phase_status is {phase_status!r} but active-plan phase block {active_phase!r} "
                        f"body status is {body_fact.value!r}; writeback --apply --phase-status {phase_status} "
                        f"synchronizes that phase block to {expected_body_status!r}"
                    ),
                    body_fact.source,
                    body_fact.line,
                )
            )
    if active_phase and phase_status == "pending":
        active_body_status_line = body_fact.line if body_fact else None
        for prior_fact in active_plan_preceding_phase_body_status_facts(plan, active_phase):
            if _phase_label_matches_active_phase(prior_fact.phase, active_phase):
                continue
            if active_body_status_line is not None and prior_fact.line == active_body_status_line:
                continue
            if prior_fact.value in PHASE_BODY_TERMINAL_STATUS_VALUES:
                continue
            findings.append(
                Finding(
                    "warn",
                    "active-plan-prior-phase-open",
                    (
                        f"project-state active_phase is {active_phase!r} with phase_status 'pending', but earlier active-plan "
                        f"phase block {prior_fact.phase!r} has body status {prior_fact.value!r}; "
                        f"writeback --apply --active-phase {active_phase} --phase-status pending completes the prior current phase "
                        "and advances the next pending phase in one lifecycle writeback"
                    ),
                    prior_fact.source,
                    prior_fact.line,
                )
            )

    closeout_values = {field: fact.value for field, fact in state_writeback_facts(inventory.state).items()}
    if (
        state_data.get("plan_status") == "active"
        and phase_status == "complete"
        and closeout_values_are_complete(closeout_values)
    ):
        findings.append(
            Finding(
                "info",
                "active-plan-ready-for-closeout",
                (
                    "project-state phase_status is complete and closeout facts are complete while the active plan is still open; "
                    "this is a ready-for-closeout boundary, and writeback --apply --archive-active-plan is the explicit archive path"
                ),
                plan.rel_path,
            )
        )
    return findings


def _phase_label_matches_active_phase(phase: str, active_phase: str) -> bool:
    return _contract_text(phase).casefold() == _contract_text(active_phase).casefold()


def _active_plan_docs_decision_findings(plan: Surface, state_data: dict[str, object]) -> list[Finding]:
    if not plan.frontmatter.has_frontmatter or "docs_decision" not in plan.frontmatter.data:
        return []
    value = str(plan.frontmatter.data.get("docs_decision") or "")
    if value not in DOCS_DECISION_VALUES:
        return [
            Finding(
                "warn",
                "active-plan-docs-decision-value",
                f"active plan docs_decision is {value!r}; expected one of: not-needed, uncertain, updated",
                plan.rel_path,
            )
        ]
    if value == "uncertain" and str(state_data.get("phase_status") or "") == "complete":
        return [
            Finding(
                "warn",
                "active-plan-docs-decision-uncertain",
                "active plan frontmatter docs_decision is uncertain while phase_status is complete; record updated/not-needed or keep closeout language provisional",
                plan.rel_path,
            )
        ]
    return []


def _active_plan_writeback_drift_findings(inventory: Inventory, plan: Surface, state_data: dict[str, object]) -> list[Finding]:
    if str(state_data.get("phase_status") or "") != "complete":
        return []
    facts = state_writeback_facts(inventory.state)
    if not facts:
        return []
    findings: list[Finding] = []
    if plan.frontmatter.has_frontmatter:
        for field, fact in facts.items():
            plan_value = plan.frontmatter.data.get(field)
            if plan_value in (None, ""):
                continue
            if str(plan_value) != fact.value:
                findings.append(
                    Finding(
                        "warn",
                        "active-plan-writeback-drift",
                        (
                            f"active plan frontmatter {field} is {plan_value!r} but project-state MLH closeout "
                            f"writeback records {fact.value!r}; writeback --apply synchronizes derived active-plan copies"
                        ),
                        plan.rel_path,
                    )
                )
    body_facts = active_plan_body_facts(plan)
    for field, fact in facts.items():
        body_fact = body_facts.get(field)
        if body_fact and body_fact.value != fact.value:
            findings.append(
                Finding(
                    "warn",
                    "active-plan-writeback-drift",
                    (
                        f"active plan body {field} is {body_fact.value!r} but project-state MLH closeout "
                        f"writeback records {fact.value!r}; writeback --apply synchronizes derived active-plan copies"
                    ),
                    body_fact.source,
                    body_fact.line,
                )
            )
    return findings


def _spec_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    existing = {surface.path.name for surface in inventory.surfaces if surface.role == "stable-spec" and surface.exists}
    for name in EXPECTED_SPEC_NAMES:
        if name not in existing:
            findings.append(Finding("error", "missing-stable-spec", f"missing expected workflow spec: project/specs/workflow/{name}"))
    return findings


def _frontmatter_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    for surface in inventory.present_surfaces:
        for error in surface.frontmatter.errors:
            severity = "error" if surface.rel_path == "project/project-state.md" else "warn"
            findings.append(Finding(severity, "frontmatter-parse", error, surface.rel_path))
        if surface.role == "research" and surface.path.name.lower() != "readme.md" and not surface.frontmatter.has_frontmatter:
            findings.append(Finding("warn", "research-frontmatter", "research artifact has no frontmatter", surface.rel_path))
    return findings


def _route_metadata_findings(inventory: Inventory) -> list[Finding]:
    if inventory.root_kind != "live_operating_root":
        return []

    findings: list[Finding] = []
    for surface in inventory.present_surfaces:
        if surface.memory_route not in ROUTE_METADATA_VALIDATED_ROUTES or surface.path.suffix.lower() != ".md":
            continue
        if surface.frontmatter.errors:
            for error in surface.frontmatter.errors:
                findings.append(
                    Finding(
                        "warn",
                        "route-metadata-frontmatter",
                        f"route metadata frontmatter is malformed: {error}",
                        surface.rel_path,
                    )
                )
            continue
        if not surface.frontmatter.has_frontmatter:
            continue

        findings.extend(_route_metadata_status_findings(surface))
        for key, value in surface.frontmatter.data.items():
            if not _is_route_metadata_path_field(key):
                continue
            values, field_findings = _route_metadata_path_values(surface, key, value)
            findings.extend(field_findings)
            for rel_path in values:
                findings.extend(_route_metadata_path_findings(inventory, surface, key, rel_path))

    if findings:
        findings.append(
            Finding(
                "info",
                "route-metadata-authority",
                "route metadata diagnostics are advisory only and cannot approve mutation, repair, archive, closeout, commit, rollback, or lifecycle decisions",
            )
        )
    return findings


def _route_metadata_status_findings(surface: Surface) -> list[Finding]:
    if "status" not in surface.frontmatter.data:
        return []
    value = surface.frontmatter.data.get("status")
    if not isinstance(value, str) or not value.strip():
        return [
            Finding(
                "warn",
                "route-metadata-field",
                f"{surface.rel_path} status must be a non-empty scalar string",
                surface.rel_path,
                _frontmatter_key_line(surface, "status"),
            )
        ]
    normalized = value.strip().casefold()
    if normalized not in ROUTE_METADATA_STATUS_VALUES:
        return [
            Finding(
                "warn",
                "route-metadata-status",
                f"{surface.rel_path} status is {value!r}; expected a known lifecycle status",
                surface.rel_path,
                _frontmatter_key_line(surface, "status"),
            )
        ]
    return []


def _is_route_metadata_path_field(key: str) -> bool:
    return key in ROUTE_METADATA_SCALAR_PATH_FIELDS or key in ROUTE_METADATA_FLEXIBLE_PATH_FIELDS or key.startswith("related_")


def _route_metadata_path_values(surface: Surface, key: str, value: object) -> tuple[list[str], list[Finding]]:
    line = _frontmatter_key_line(surface, key)
    if key in ROUTE_METADATA_SCALAR_PATH_FIELDS:
        if not isinstance(value, str) or not value.strip():
            return [], [
                Finding(
                    "warn",
                    "route-metadata-field",
                    f"{surface.rel_path} {key} must be a non-empty scalar root-relative path",
                    surface.rel_path,
                    line,
                )
            ]
        return [_normalize_route_metadata_path(value)], []

    if isinstance(value, str):
        if not value.strip():
            return [], [
                Finding(
                    "warn",
                    "route-metadata-field",
                    f"{surface.rel_path} {key} must not be empty",
                    surface.rel_path,
                    line,
                )
            ]
        normalized = _normalize_route_metadata_path(value)
        if not _route_metadata_value_is_path_like(normalized):
            return [], []
        return [normalized], []

    if isinstance(value, list) and value and all(isinstance(item, str) and item.strip() for item in value):
        return [
            normalized
            for item in value
            if _route_metadata_value_is_path_like(normalized := _normalize_route_metadata_path(item))
        ], []

    return [], [
        Finding(
            "warn",
            "route-metadata-field",
            f"{surface.rel_path} {key} must be a non-empty scalar path or non-empty list of scalar paths",
            surface.rel_path,
            line,
        )
    ]


def _route_metadata_path_findings(inventory: Inventory, surface: Surface, key: str, rel_path: str) -> list[Finding]:
    findings: list[Finding] = []
    line = _frontmatter_key_line(surface, key)
    if _route_metadata_path_is_unsafe(rel_path):
        return [
            Finding(
                "warn",
                "route-metadata-path",
                f"{surface.rel_path} {key} must be a root-relative path without absolute or parent-traversal segments: {rel_path}",
                surface.rel_path,
                line,
            )
        ]

    target = inventory.root / rel_path
    if _route_metadata_path_escapes_root(inventory.root, target):
        return [
            Finding(
                "warn",
                "route-metadata-path",
                f"{surface.rel_path} {key} path escapes the target root: {rel_path}",
                surface.rel_path,
                line,
            )
        ]

    path_conflict = _route_metadata_path_conflict(inventory.root, rel_path, target)
    if path_conflict:
        findings.append(Finding("warn", "route-metadata-path", f"{surface.rel_path} {key} {path_conflict}", surface.rel_path, line))
    elif not target.exists():
        findings.append(
            Finding(
                "warn",
                "route-metadata-missing-target",
                f"{surface.rel_path} {key} target is missing: {rel_path}",
                surface.rel_path,
                line,
            )
        )

    destination = _route_metadata_destination_finding(surface, key, rel_path, line)
    if destination:
        findings.append(destination)
    if target.exists() and not rel_path.startswith("project/archive/"):
        stale = _route_metadata_stale_reference_finding(inventory, surface, key, rel_path, line)
        if stale:
            findings.append(stale)
    return findings


def _route_metadata_destination_finding(surface: Surface, key: str, rel_path: str, line: int | None) -> Finding | None:
    if key == "archived_to":
        if not rel_path.startswith("project/archive/reference/") or not rel_path.endswith(".md"):
            return Finding(
                "warn",
                "route-metadata-destination",
                f"{surface.rel_path} archived_to must point under project/archive/reference/**/*.md: {rel_path}",
                surface.rel_path,
                line,
            )
        return None

    route_id = classify_memory_route(rel_path).route_id
    if key == "promoted_to":
        if rel_path.startswith("project/archive/") or route_id not in ROUTE_METADATA_PROMOTION_TARGET_ROUTES:
            return Finding(
                "warn",
                "route-metadata-destination",
                f"{surface.rel_path} promoted_to must point to an existing non-archive authority or product route: {rel_path}",
                surface.rel_path,
                line,
            )
        return None

    allowed = _route_metadata_allowed_targets(surface, key)
    if allowed is None:
        return None
    allowed_routes, allowed_archive_prefixes, label = allowed
    if route_id in allowed_routes or any(rel_path.startswith(prefix) for prefix in allowed_archive_prefixes):
        return None
    return Finding(
        "warn",
        "route-metadata-destination",
        f"{surface.rel_path} {key} must point to {label}: {rel_path}",
        surface.rel_path,
        line,
    )


def _route_metadata_allowed_targets(surface: Surface, key: str) -> tuple[set[str], tuple[str, ...], str] | None:
    if key in {"source_research", "related_research"}:
        return {"research"}, ("project/archive/reference/research/",), "a research route"
    if key in {"source_incubation", "related_incubation"}:
        return {"incubation"}, ("project/archive/reference/incubation/",), "an incubation route"
    if key == "related_plan":
        return {"active-plan"}, ("project/archive/plans/",), "an active or archived plan route"
    if key == "archived_plan":
        return {"active-plan"}, ("project/archive/plans/",), "an active or archived plan route"
    if key in {"related_roadmap", "source_roadmap"}:
        return {"roadmap"}, (), "a roadmap route"
    if key in {"related_decision", "related_decisions"}:
        return {"decisions"}, ("project/archive/reference/decisions/",), "a decision route"
    if key in {"related_adr", "related_adrs"}:
        return {"adrs"}, ("project/archive/reference/adrs/",), "an ADR route"
    if key == "related_verification":
        return {"verification"}, ("project/archive/reference/verification/",), "a verification route"
    if key in {"related_spec", "related_specs"}:
        return {"stable-specs"}, (), "a stable-spec route"
    if key in {"related_doc", "related_docs"}:
        return {"product-docs"}, (), "a product-docs route"
    if key in {"supersedes", "superseded_by"}:
        return {surface.memory_route}, (), f"the same {surface.memory_route} route"
    return None


def _route_metadata_stale_reference_finding(
    inventory: Inventory,
    surface: Surface,
    key: str,
    rel_path: str,
    line: int | None,
) -> Finding | None:
    if key.startswith("source_"):
        return None
    target_surface = inventory.surface_by_rel.get(rel_path)
    if not target_surface or not target_surface.frontmatter.has_frontmatter:
        return None
    if target_surface.frontmatter.data.get("archived_to") in (None, ""):
        return None
    return Finding(
        "warn",
        "route-metadata-stale-reference",
        f"{surface.rel_path} {key} points at active route {rel_path}, but that target already records archived_to",
        surface.rel_path,
        line,
    )


def _normalize_route_metadata_path(value: str) -> str:
    return re.sub(r"/+", "/", value.strip().strip("<>").strip().replace("\\", "/"))


def _route_metadata_value_is_path_like(value: str) -> bool:
    if not value or any(separator in value for separator in (";", "|")):
        return False
    return (
        "/" in value
        or "\\" in value
        or value.endswith((".md", ".toml", ".yaml", ".yml", ".json"))
        or value.startswith((".", "~"))
        or _is_absolute_path(value)
    )


def _route_metadata_path_is_unsafe(rel_path: str) -> bool:
    if not rel_path or rel_path.startswith("/") or _is_absolute_path(rel_path):
        return True
    return any(part in {".", ".."} for part in rel_path.split("/"))


def _route_metadata_path_conflict(root: Path, rel_path: str, target: Path) -> str | None:
    for candidate in _root_relative_path_chain(root, rel_path):
        candidate_rel = candidate.relative_to(root).as_posix()
        if not candidate.exists():
            continue
        if candidate.is_symlink():
            return f"path contains a symlink segment: {candidate_rel}"
        if candidate != target and not candidate.is_dir():
            return f"path contains a non-directory segment: {candidate_rel}"
    if target.exists() and not target.is_file():
        return f"target is not a regular file: {rel_path}"
    return None


def _route_metadata_path_escapes_root(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return False
    except ValueError:
        return True


def _frontmatter_key_line(surface: Surface, key: str) -> int | None:
    lines = surface.content.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for index, line in enumerate(lines[1:], start=2):
        if line.strip() == "---":
            return None
        if re.match(rf"^{re.escape(key)}\s*:", line):
            return index
    return None


def _docmap_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    docmap = inventory.surface_by_rel.get(".agents/docmap.yaml")
    if not docmap or not docmap.exists:
        return findings
    text = docmap.content
    for expected in ("README.md", "AGENTS.md", "project/project-state.md", "project/specs/workflow/"):
        if expected not in text:
            findings.append(Finding("warn", "docmap-routing", f"docmap does not mention {expected}", docmap.rel_path))
    return findings


def _mirror_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    for name in EXPECTED_SPEC_NAMES:
        live = inventory.surface_by_rel.get(f"project/specs/workflow/{name}")
        mirror = inventory.surface_by_rel.get(f"specs/workflow/{name}")
        if live and mirror and live.exists and mirror.exists and live.content != mirror.content:
            diff = "\n".join(
                difflib.unified_diff(
                    live.content.splitlines(),
                    mirror.content.splitlines(),
                    fromfile=live.rel_path,
                    tofile=mirror.rel_path,
                    lineterm="",
                    n=1,
                )
            )
            findings.append(Finding("error", "mirror-drift", f"package-source mirror differs from live spec:\n{diff}", mirror.rel_path))
    return findings


def _docmap_gap_findings(inventory: Inventory) -> list[Finding]:
    docmap = inventory.surface_by_rel.get(".agents/docmap.yaml")
    if not docmap or not docmap.exists:
        return []
    gaps = []
    expected = [
        "README.md",
        "AGENTS.md",
        ".codex/project-workflow.toml",
        "project/project-state.md",
        "project/specs/workflow/",
    ]
    product_doc_candidates = ("docs/README.md", "docs/architecture/", "docs/specs/")
    cli_candidates = ("pyproject.toml", "src/mylittleharness/", "tests/")
    for rel in product_doc_candidates + cli_candidates:
        if (inventory.root / rel).exists():
            expected.append(rel)
    state = inventory.state
    plan_status = state.frontmatter.data.get("plan_status") if state and state.exists else None
    if plan_status == "active" or (inventory.active_plan_surface and inventory.active_plan_surface.exists):
        expected.append("project/implementation-plan.md")
    for rel in expected:
        if rel not in docmap.content:
            gaps.append(Finding("warn", "candidate-docmap-gap", f"candidate route missing from docmap: {rel}", docmap.rel_path))
    return gaps


def _stale_root_pointer_findings(inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    configured_roots = _configured_root_references(inventory)
    for surface in inventory.present_surfaces:
        if surface.role == "package-mirror":
            continue
        lines = surface.content.splitlines()
        for index, line in enumerate(lines, start=1):
            normalized = _display_path_value(line)
            fallback_root = configured_roots.get("fallback")
            product_root = configured_roots.get("product")
            operating_root = configured_roots.get("operating")
            if fallback_root and _line_references_path(normalized, fallback_root) and not _nearby_text_contains(
                lines, index, {"fallback", "archive", "evidence", "historical", "old", "reopened only"}
            ):
                findings.append(
                    Finding(
                        "warn",
                        "stale-fallback-root-reference",
                        "configured fallback/archive root is referenced without fallback/archive context",
                        surface.rel_path,
                        index,
                    )
                )
            if product_root and _line_references_path(normalized, product_root) and _line_claims_operating_role(normalized):
                findings.append(
                    Finding(
                        "warn",
                        "stale-product-root-role",
                        "configured product source root is described with operating-root wording; product roots should remain source/target only",
                        surface.rel_path,
                        index,
                    )
                )
            if operating_root and _line_references_path(normalized, operating_root) and _line_claims_product_role(normalized):
                findings.append(
                    Finding(
                        "warn",
                        "stale-operating-root-role",
                        "configured operating root is described with product-root wording; operating roots should remain operating memory",
                        surface.rel_path,
                        index,
                    )
                )
    return findings


def _configured_root_references(inventory: Inventory) -> dict[str, str]:
    state = inventory.state
    data = state.frontmatter.data if state and state.exists else {}
    references = {
        "operating": data.get("operating_root") or data.get("canonical_source_evidence_root"),
        "product": data.get("product_source_root") or data.get("projection_root"),
        "fallback": data.get("historical_fallback_root"),
    }
    return {
        role: _root_reference_text(value, inventory.root)
        for role, value in references.items()
        if value not in (None, "")
    }


def _root_reference_text(value: object, root: Path) -> str:
    text = _display_path_value(str(value)).strip()
    try:
        candidate = Path(text).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        return str(candidate.resolve())
    except (OSError, RuntimeError):
        return text


def _line_references_path(line: str, reference: str) -> bool:
    if reference in {"", ".", str(Path("."))}:
        return False
    normalized_line = _display_path_value(line).replace("/", "\\").casefold()
    normalized_reference = _display_path_value(reference).replace("/", "\\").rstrip("\\").casefold()
    return normalized_reference in normalized_line


def _start_path_surfaces(inventory: Inventory) -> list[Surface]:
    preferred = [
        "project/project-state.md",
        "README.md",
        "AGENTS.md",
        ".agents/docmap.yaml",
        ".codex/project-workflow.toml",
        "docs/README.md",
        "docs/architecture/product-architecture.md",
        "docs/architecture/layer-model.md",
        "docs/architecture/clean-room-carry-forward.md",
        "project/implementation-plan.md",
    ]
    surfaces = [inventory.surface_by_rel[rel] for rel in preferred if rel in inventory.surface_by_rel]
    surfaces.extend(
        surface
        for surface in inventory.surfaces
        if surface.role == "product-doc" and surface.exists and surface not in surfaces
    )
    surfaces.extend(
        surface
        for surface in inventory.surfaces
        if surface.role == "stable-spec" and surface.exists and surface not in surfaces
    )
    return surfaces


def _budget_label(lines: int, chars: int) -> str:
    if lines > VERY_LARGE_FILE_LINES or chars > VERY_LARGE_FILE_CHARS:
        return "very-large"
    if lines > LARGE_FILE_LINES or chars > LARGE_FILE_CHARS:
        return "large"
    return "normal"


def _git_findings(root: Path) -> list[Finding]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [Finding("warn", "git-status", f"git status unavailable: {exc}")]
    if result.returncode == 0:
        state = "clean" if not result.stdout.strip() else "dirty"
        return [Finding("info", "git-status", f"git worktree detected: {state}")]
    message = (result.stderr or result.stdout).strip().splitlines()
    detail = message[0] if message else f"git exited {result.returncode}"
    return [Finding("info", "git-status", f"not a git worktree: {detail}")]


def _intake_request_errors(inventory: Inventory, request: IntakeRequest, apply: bool) -> list[Finding]:
    errors: list[Finding] = []
    if not request.text.strip():
        errors.append(Finding("error", "intake-refused", "intake text is required"))

    advice = classify_intake_text(request.text)
    if apply:
        if inventory.root_kind == "product_source_fixture":
            errors.append(Finding("error", "intake-refused", "target is a product-source compatibility fixture; intake --apply is refused", request.target or None))
        elif inventory.root_kind == "fallback_or_archive":
            errors.append(Finding("error", "intake-refused", "target is fallback/archive or generated-output evidence; intake --apply is refused", request.target or None))
        elif inventory.root_kind != "live_operating_root":
            errors.append(Finding("error", "intake-refused", f"target root kind is {inventory.root_kind}; intake --apply requires a live operating root", request.target or None))
        if not request.target:
            errors.append(Finding("error", "intake-refused", "--target is required with --apply"))
        if not advice.apply_allowed:
            errors.append(Finding("error", "intake-refused", f"input is ambiguous: {advice.reason}"))

    if request.target:
        errors.extend(_intake_target_errors(inventory, request.target, advice, apply))
    return errors


def _intake_target_errors(inventory: Inventory, target: str, advice: IntakeRouteAdvice, apply: bool) -> list[Finding]:
    errors: list[Finding] = []
    if _intake_rel_has_absolute_or_parent_parts(target):
        return [Finding("error", "intake-refused", "--target must be a root-relative path without parent segments", target)]
    if not target.endswith(".md"):
        errors.append(Finding("error", "intake-refused", "--target must be a Markdown file", target))
    route_id = classify_memory_route(target).route_id
    if route_id not in INTAKE_ROUTE_ALLOWED_TARGETS:
        errors.append(
            Finding(
                "error",
                "intake-refused",
                f"--target route {route_id!r} is not an intake destination; use one of {', '.join(sorted(INTAKE_ROUTE_ALLOWED_TARGETS))}",
                target,
            )
        )
    elif advice.apply_allowed and not intake_target_matches_route(advice.route_id, target):
        errors.append(
            Finding(
                "error",
                "intake-refused",
                f"--target route {route_id!r} does not match classified route {advice.route_id!r}",
                target,
            )
        )
    target_path = inventory.root / target
    if _intake_path_escapes_root(inventory.root, target_path):
        errors.append(Finding("error", "intake-refused", "target path escapes the target root", target))
        return errors
    for parent in _intake_parents_between(inventory.root, target_path.parent):
        rel = parent.relative_to(inventory.root).as_posix()
        if parent.exists() and parent.is_symlink():
            errors.append(Finding("error", "intake-refused", f"target directory contains a symlink segment: {rel}", rel))
        elif parent.exists() and not parent.is_dir():
            errors.append(Finding("error", "intake-refused", f"target directory contains a non-directory segment: {rel}", rel))
    if apply and target_path.exists():
        errors.append(Finding("error", "intake-refused", "target already exists; choose a new explicit intake file", target))
    return errors


def _intake_advice_findings(advice: IntakeRouteAdvice, request: IntakeRequest, prefix: str) -> list[Finding]:
    source = request.target or None
    return [
        Finding(
            "info",
            "intake-route-advisor",
            f"{prefix}classify input as {advice.route_id}; target route: {advice.target}; confidence: {advice.confidence}; {advice.reason}",
            source,
        ),
        Finding("info", "intake-route-next-action", f"{prefix}{advice.next_action}", source),
    ]


def _intake_target_preview_findings(request: IntakeRequest, advice: IntakeRouteAdvice) -> list[Finding]:
    route_id = classify_memory_route(request.target).route_id
    compatible = advice.apply_allowed and intake_target_matches_route(advice.route_id, request.target)
    posture = "compatible" if compatible else "not compatible"
    return [
        Finding(
            "info",
            "intake-target",
            f"would target {request.target}; route: {route_id}; classifier compatibility: {posture}",
            request.target,
        )
    ]


def _intake_boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "intake-boundary",
            "intake dry-run is advisory; intake apply writes only one explicit new Markdown target in an eligible live operating root",
        ),
        Finding(
            "info",
            "intake-authority",
            "intake classification cannot approve repair, closeout, archive, commit, rollback, lifecycle decisions, or roadmap promotion",
        ),
    ]


def _intake_document_text(request: IntakeRequest, advice: IntakeRouteAdvice) -> str:
    title = _intake_title(request)
    status = INTAKE_ROUTE_DEFAULT_STATUS.get(advice.route_id, "draft")
    body = request.text.strip()
    return (
        "---\n"
        f'title: "{_yaml_double_quoted_value(title)}"\n'
        f'status: "{_yaml_double_quoted_value(status)}"\n'
        f'route: "{_yaml_double_quoted_value(advice.route_id)}"\n'
        f'created: "{date.today().isoformat()}"\n'
        f'intake_source: "{_yaml_double_quoted_value(request.text_source)}"\n'
        "---\n"
        f"# {title}\n\n"
        f"{body}\n"
    )


def _intake_title(request: IntakeRequest) -> str:
    if request.title:
        return _clean_intake_title(request.title)
    for line in request.text.splitlines():
        cleaned = _clean_intake_title(re.sub(r"^[A-Za-z][A-Za-z -]{1,30}:\s*", "", line.strip()))
        if cleaned:
            return cleaned
    return "Incoming Information"


def _clean_intake_title(value: str) -> str:
    cleaned = re.sub(r"[`*_#\[\]<>]", "", value).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:80].strip(" .,:;-") or "Incoming Information"


def _normalized_intake_target(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/")


def _intake_rel_has_absolute_or_parent_parts(rel_path: str) -> bool:
    if not rel_path or rel_path.startswith("/") or re.match(r"^[A-Za-z]:", rel_path):
        return True
    parts = [part for part in rel_path.split("/") if part]
    return any(part in {".", ".."} for part in parts)


def _intake_path_escapes_root(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return False
    except ValueError:
        return True


def _intake_parents_between(root: Path, path: Path) -> list[Path]:
    parents: list[Path] = []
    current = path
    root_resolved = root.resolve()
    while True:
        try:
            current.resolve().relative_to(root_resolved)
        except ValueError:
            break
        if current.resolve() == root_resolved:
            break
        parents.append(current)
        current = current.parent
    return list(reversed(parents))


def _with_severity(findings: list[Finding], severity: str) -> list[Finding]:
    return [Finding(severity, finding.code, finding.message, finding.source, finding.line) for finding in findings]


def _is_product_source_inventory(inventory: Inventory) -> bool:
    return inventory.root_kind == "product_source_fixture"


def _is_fallback_or_archive_inventory(inventory: Inventory) -> bool:
    return inventory.root_kind == "fallback_or_archive"


def _is_mylittleharness_product_context(inventory: Inventory) -> bool:
    if inventory.root_kind == "live_operating_root":
        return False
    state = inventory.state
    data = state.frontmatter.data if state and state.exists else {}
    return (
        data.get("project") == EXPECTED_PRODUCT_NAME
        or data.get("root_role") == EXPECTED_PRODUCT_ROOT_ROLE
        or data.get("fixture_status") == EXPECTED_PRODUCT_FIXTURE_STATUS
        or bool(data.get("operating_root") or data.get("product_source_root") or data.get("historical_fallback_root"))
        or _same_path_value(data.get("product_source_root"), inventory.root)
        or _string_contains(inventory, "# MyLittleHarness")
    )


def _iter_hygiene_paths(root: Path) -> list[tuple[Path, str]]:
    paths: list[tuple[Path, str]] = []
    _collect_hygiene_paths(root, root, paths)
    return paths


def _collect_hygiene_paths(root: Path, current: Path, paths: list[tuple[Path, str]]) -> None:
    try:
        children = sorted(current.iterdir(), key=lambda item: item.name.lower())
    except OSError:
        return
    for child in children:
        rel_path = child.relative_to(root).as_posix()
        if rel_path == ".git" or rel_path.startswith(".git/"):
            continue
        paths.append((child, rel_path))
        if child.is_dir() and not child.is_symlink() and _should_descend_for_hygiene(child, rel_path):
            _collect_hygiene_paths(root, child, paths)


def _should_descend_for_hygiene(path: Path, rel_path: str) -> bool:
    return _classify_product_hygiene_path(path, rel_path) is None


def _classify_product_hygiene_path(path: Path, rel_path: str) -> tuple[str, str] | None:
    normalized = rel_path.replace("\\", "/").lower()
    if normalized in {".mylittleharness", ".mylittleharness/generated"} or normalized.startswith(".mylittleharness/generated/projection"):
        return None
    if normalized.startswith(".mylittleharness/"):
        return ("product-debris", "generated MyLittleHarness output is allowed only under .mylittleharness/generated/projection")
    for prefix, reason in PRODUCT_HYGIENE_OPERATIONAL_PREFIXES.items():
        prefix_lower = prefix.lower()
        if normalized == prefix_lower or normalized.startswith(prefix_lower.rstrip("/") + "/"):
            return ("forbidden-product-surface", reason)
    for prefix, reason in PRODUCT_HYGIENE_PACKAGE_PREFIXES.items():
        prefix_lower = prefix.lower()
        if normalized == prefix_lower or normalized.startswith(prefix_lower.rstrip("/") + "/"):
            return ("forbidden-product-surface", reason)

    name = path.name.lower()
    if path.is_dir() and (name in PRODUCT_HYGIENE_DEBRIS_DIR_NAMES or name.endswith(".egg-info")):
        return ("product-debris", "generated/cache/build/runtime directory is excluded from product source")
    if path.is_file():
        if name in PRODUCT_HYGIENE_DEBRIS_FILE_NAMES:
            return ("product-debris", "generated validation, coverage, or runtime file is excluded from product source")
        if name.startswith("validation-report") and name.endswith(".md"):
            return ("product-debris", "generated validation report is excluded from product source")
        if any(name.endswith(suffix) for suffix in PRODUCT_HYGIENE_DEBRIS_FILE_SUFFIXES):
            return ("product-debris", "log, local database, package archive, or temporary file is excluded from product source")
        if any(name.endswith(suffix) for suffix in PRODUCT_HYGIENE_ARCHIVE_SUFFIXES):
            return ("product-debris", "package archive is excluded from product source")
    return None


def _string_contains(inventory: Inventory, needle: str) -> bool:
    return any(surface.exists and needle in surface.content for surface in inventory.surfaces)


def _same_path_value(value: object, expected: Path) -> bool:
    if not value:
        return False
    normalized = _display_path_value(str(value))
    try:
        candidate = Path(normalized).expanduser()
        if not candidate.is_absolute():
            candidate = expected / candidate
        candidate = candidate.resolve()
        target = expected.expanduser().resolve()
        return str(candidate).casefold() == str(target).casefold()
    except (OSError, RuntimeError):
        return normalized.replace("/", "\\").rstrip("\\").casefold() == str(expected).replace("/", "\\").rstrip("\\").casefold()


def _display_path_value(value: str) -> str:
    return value.replace("\\\\", "\\")


def _is_absolute_path(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", value)) or Path(value).is_absolute()


def _link_base(root: Path, path_part: str, source_rel: str | None) -> Path:
    normalized = _normalized_link_path(path_part)
    if source_rel and source_rel.startswith("docs/") and normalized.startswith(("architecture/", "specs/")):
        return root / Path(source_rel).parent
    if not source_rel or _is_repo_root_relative_link(normalized):
        return root
    source_parent = Path(source_rel).parent
    if str(source_parent) in ("", "."):
        return root
    return root / source_parent


def _is_repo_root_relative_link(normalized: str) -> bool:
    if normalized in ROOT_RELATIVE_LINK_NAMES:
        return True
    return any(normalized.startswith(prefix) for prefix in ROOT_RELATIVE_LINK_PREFIXES)


def _expand_brace_pattern(value: str) -> list[str]:
    match = re.search(r"\{([^{}]+)\}", value)
    if not match:
        return [value]
    prefix = value[: match.start()]
    suffix = value[match.end() :]
    return [prefix + option + suffix for option in match.group(1).split(",")]


def _optional_missing_link_reason(inventory: Inventory, target: str) -> str | None:
    rel = _normalized_link_path(target)
    if not rel:
        return None
    root_rel = _root_relative_link_path(inventory, rel)
    if root_rel is not None:
        rel = root_rel

    if inventory.root_kind == "live_operating_root":
        if rel == ".agents/docmap.yaml" and inventory.manifest.get("policy", {}).get("docmap_mode") == "lazy":
            return "docmap is lazy for this live operating root"
        if rel == "README.md":
            return "root README.md is optional for live operating roots"
        if rel == "project/roadmap.md":
            return "project/roadmap.md is an optional live-root roadmap route"

    state = inventory.state
    state_data = state.frontmatter.data if state and state.exists else {}
    operating_root = _normalized_link_path(str(state_data.get("operating_root") or state_data.get("canonical_source_evidence_root") or ""))
    fallback_root = _normalized_link_path(str(state_data.get("historical_fallback_root") or ""))
    if operating_root and rel.lower() == operating_root.lower().rstrip("/"):
        return "configured operating root is external local evidence, not a required in-tree product surface"
    if fallback_root and rel.lower() == fallback_root.lower().rstrip("/"):
        return "configured fallback/archive root is opt-in local evidence, not a required product surface"
    if operating_root and rel.lower().startswith(operating_root.lower().rstrip("/") + "/"):
        rel = rel[len(operating_root.rstrip("/")) + 1 :]

    plan_status = state_data.get("plan_status")
    manifest_plan = "project/implementation-plan.md"
    if inventory.manifest:
        manifest_plan = inventory.manifest.get("memory", {}).get("plan_file", manifest_plan)
    if rel == str(manifest_plan).replace("\\", "/") and plan_status != "active":
        return "the implementation plan is a lazy surface when plan_status is not active"

    if rel == DETACH_MARKER_REL_PATH:
        return "detach marker is created only in eligible live operating roots and is absent from the product source fixture"
    if rel == ".mylittleharness/generated/projection" or rel.startswith(".mylittleharness/generated/projection/"):
        return "generated projection artifacts are disposable navigation output and may be rebuilt when needed"
    if rel == "project/plan-incubation" or rel.startswith("project/plan-incubation/"):
        return "plan incubation surfaces are optional and only exist when a lane is open"
    if rel in {DOCMAP_REPAIR_COPY_REL, STATE_FRONTMATTER_COPY_REL}:
        return "snapshot copied-file paths are relative to a repair snapshot directory, not the repo root"

    fixture_root = (
        state_data.get("projection_status") == "candidate-projection"
        or state_data.get("root_role") == "product-source"
        or state_data.get("fixture_status") == "product-compatibility-fixture"
    )
    if fixture_root:
        if rel == "project/roadmap.md":
            return "roadmap route examples belong in serviced live operating roots, not this product source fixture"
        if rel == "project/adrs" or rel.startswith("project/adrs/"):
            return "ADR route examples belong in serviced live operating roots, not this product source fixture"
        if rel == "project/decisions" or rel.startswith("project/decisions/"):
            return "decision route examples belong in serviced live operating roots, not this product source fixture"
        if rel == "project/verification" or rel.startswith("project/verification/"):
            return "verification route examples belong in serviced live operating roots, not this product source fixture"
        if (rel == "project/research" or rel.startswith("project/research/")) and rel != "project/research/README.md":
            return "source-root research artifacts are intentionally excluded from this product compatibility fixture"
        if rel == "research/README.md":
            return "the root package-source research mirror is intentionally excluded from this product compatibility fixture"
        if rel.startswith("project/archive/"):
            return "legacy archives are intentionally excluded from this product compatibility fixture"
        if rel == "specs/workflow" or rel.startswith("specs/workflow/"):
            return "root package-source spec mirrors are intentionally excluded from this product source tree"
    return None


def _normalized_link_path(target: str) -> str:
    clean = target.strip().strip("<>").strip()
    if not clean or clean.startswith("#"):
        return ""
    path_part = clean.split("#", 1)[0]
    return re.sub(r"/+", "/", path_part.replace("\\", "/"))


def _root_relative_link_path(inventory: Inventory, rel: str) -> str | None:
    if not _is_absolute_path(rel):
        return None
    root = _normalized_link_path(str(inventory.root)).rstrip("/")
    if rel.casefold() == root.casefold():
        return ""
    prefix = root + "/"
    if rel.casefold().startswith(prefix.casefold()):
        return rel[len(prefix) :]
    return None


def _nearby_text_contains(lines: list[str], line_number: int, needles: set[str]) -> bool:
    start = max(0, line_number - 3)
    end = min(len(lines), line_number + 1)
    window = " ".join(lines[start:end]).lower()
    return any(needle in window for needle in needles)


def _line_claims_operating_role(line: str) -> bool:
    lowered = line.lower()
    if any(
        marker in lowered
        for marker in (
            "not an operating",
            "not the operating",
            "not operating",
            "must not",
            "not hold",
            "product source",
            "source tree",
            "fixture metadata",
            "target root",
        )
    ):
        return False
    return any(marker in lowered for marker in ("operating root", "operating/research", "working plans", "active implementation plans", "workflow execution"))


def _line_claims_product_role(line: str) -> bool:
    lowered = line.lower()
    if any(marker in lowered for marker in ("operating root", "operating/research", "research pilot", "plans, state", "operating evidence")):
        return False
    return any(marker in lowered for marker in ("product source root", "product root", "product repository", "fixture metadata"))


def load_for_root(root: Path) -> Inventory:
    return load_inventory(root)
