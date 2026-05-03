from __future__ import annotations

from collections.abc import Iterable

from .inventory import Inventory, Surface
from .models import Finding
from .evidence_cues import CLOSEOUT_FIELD_NAMES, closeout_field_cues, cue_findings, find_cues
from .writeback import WritebackFact, state_writeback_facts


ANCHOR_PATTERNS = (
    ("plan", (r"\bplan anchors?\b", r"\bplan\b.*\banchors?\b")),
    ("integration", (r"\bintegration anchors?\b", r"\bintegration\b.*\banchors?\b")),
    ("closeout", (r"\bcloseout anchors?\b", r"\bcloseout\b.*\banchors?\b")),
)

CARRY_FORWARD_PATTERNS = (
    r"carry-forward",
    r"deferred",
    r"unresolved",
    r"optional-next",
    r"later-extension",
    r"needs-more-research",
    r"\bopen questions?\b",
)
SKIP_RATIONALE_PATTERNS = (
    r"skip rationale",
    r"explicit skip",
    r"verified skip",
    r"explicitly skipped",
    r"skipped because",
)
DURABLE_PROOF_RECORD_PREFIX = "project/verification/"
DURABLE_PROOF_RECORD_LIMIT = 5


def evidence_findings(inventory: Inventory) -> list[Finding]:
    state = inventory.state
    state_data = state.frontmatter.data if state and state.exists else {}
    active_plan = inventory.active_plan_surface if inventory.active_plan_surface and inventory.active_plan_surface.exists else None
    findings: list[Finding] = [
        Finding(
            "info",
            "evidence-boundary",
            "terminal-only read-only report; persistent evidence manifest remains deferred and no files, caches, databases, generated artifacts, VCS probes, hooks, adapters, or mutations are written",
        ),
        Finding("info", "evidence-root-kind", f"root kind: {inventory.root_kind}"),
    ]

    if inventory.root_kind == "product_source_fixture":
        findings.append(
            Finding(
                "info",
                "evidence-non-authority",
                "product source checkout contains compatibility fixtures only; evidence findings do not make it an operating project root",
                state.rel_path if state else None,
            )
        )

    findings.extend(_active_plan_findings(inventory, active_plan, state_data))
    findings.extend(durable_proof_record_findings(inventory, "evidence"))
    findings.extend(_source_set_findings(active_plan, inventory))
    findings.extend(_anchor_findings(active_plan, inventory))
    findings.extend(_identity_findings(active_plan))
    findings.extend(_closeout_findings(active_plan, inventory))
    findings.extend(_quality_cue_findings(active_plan, inventory))
    findings.extend(_operator_required_findings(inventory))
    findings.extend(_line_group_findings(active_plan, "evidence-residual-risk", "residual risk", (r"residual risk", r"residual risks"), inventory))
    findings.extend(_line_group_findings(active_plan, "evidence-skip-rationale", "skip rationale", SKIP_RATIONALE_PATTERNS, inventory))
    findings.extend(_line_group_findings(active_plan, "evidence-carry-forward", "carry-forward", CARRY_FORWARD_PATTERNS, inventory))
    findings.append(
        Finding(
            "info",
            "evidence-non-authority",
            "candidate evidence can guide closeout assembly, but source files, observed verification, and operator decisions remain authority",
        )
    )
    return findings


def durable_proof_record_findings(inventory: Inventory, code_prefix: str) -> list[Finding]:
    code = f"{code_prefix}-proof-record"
    if inventory.root_kind != "live_operating_root":
        return [
            Finding(
                "info",
                code,
                "durable proof/evidence record scan is live-root only; product fixtures and archive roots remain non-authority context",
                inventory.state.rel_path if inventory.state and inventory.state.exists else None,
            )
        ]

    records = _durable_proof_record_surfaces(inventory)
    if not records:
        return [
            Finding(
                "info",
                code,
                (
                    "no durable proof/evidence records found at project/verification/*.md; "
                    "the active-plan verification block remains the default evidence surface and absence does not block closeout"
                ),
            )
        ]

    findings: list[Finding] = []
    for record in records[:DURABLE_PROOF_RECORD_LIMIT]:
        status = _record_status(record)
        title = _record_title(record)
        findings.append(
            Finding(
                "info",
                code,
                (
                    f"candidate: durable proof/evidence record: {record.rel_path}; "
                    f"status={status}; title={title}; read-only closeout assembly input only"
                ),
                record.rel_path,
            )
        )
        if record.frontmatter.errors or status == "unrecorded" or title == "untitled":
            findings.append(
                Finding(
                    "warn",
                    f"{code}-ambiguous",
                    (
                        f"ambiguous durable proof/evidence record metadata: {record.rel_path}; "
                        "record status and heading should be explicit before relying on it for closeout assembly"
                    ),
                    record.rel_path,
                )
            )
    if len(records) > DURABLE_PROOF_RECORD_LIMIT:
        findings.append(
            Finding(
                "info",
                code,
                f"durable proof/evidence record scan truncated at {DURABLE_PROOF_RECORD_LIMIT} of {len(records)} records",
            )
        )
    findings.append(
        Finding(
            "info",
            f"{code}-non-authority",
            "durable proof/evidence records are report inputs only; they do not satisfy closeout fields, approve lifecycle changes, or write evidence manifests",
        )
    )
    return findings


def _durable_proof_record_surfaces(inventory: Inventory) -> list[Surface]:
    return sorted(
        (
            surface
            for surface in inventory.present_surfaces
            if surface.memory_route == "verification"
            and surface.rel_path.startswith(DURABLE_PROOF_RECORD_PREFIX)
            and surface.path.suffix.lower() == ".md"
        ),
        key=lambda surface: surface.rel_path,
    )


def _record_status(surface: Surface) -> str:
    status = surface.frontmatter.data.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip()
    return "unrecorded"


def _record_title(surface: Surface) -> str:
    if surface.headings:
        return surface.headings[0].title
    return "untitled"


def _active_plan_findings(inventory: Inventory, active_plan: Surface | None, state_data: dict[str, object]) -> list[Finding]:
    state = inventory.state
    plan_status = str(state_data.get("plan_status") or "")
    configured_plan = str(state_data.get("active_plan") or inventory.manifest.get("memory", {}).get("plan_file", "project/implementation-plan.md"))
    if active_plan:
        return [
            Finding(
                "info",
                "evidence-active-plan",
                f"candidate: active plan present: {active_plan.rel_path}",
                active_plan.rel_path,
            )
        ]
    if plan_status == "active":
        return [
            Finding(
                "warn",
                "evidence-active-plan",
                f"missing: plan_status is active but active plan is not readable: {configured_plan}",
                state.rel_path if state else configured_plan,
            )
        ]
    return [
        Finding(
            "info",
            "evidence-active-plan",
            "no active plan is required by current state",
            state.rel_path if state else None,
        )
    ]


def _source_set_findings(active_plan: Surface | None, inventory: Inventory) -> list[Finding]:
    if not active_plan:
        return [
            Finding(
                "info",
                "evidence-source-set",
                "source-set scan skipped because no active plan is present",
            )
        ]
    cues = find_cues(active_plan, "source-set", "source-set candidate", (r"\bsource set\b", r"\bsource_set\b"))
    if not cues:
        return [
            Finding(
                "warn",
                "evidence-source-set",
                "missing: active plan has no source-set candidate",
                active_plan.rel_path,
            )
        ]
    return cue_findings("evidence-source-set", "source-set candidate", cues)


def _anchor_findings(active_plan: Surface | None, inventory: Inventory) -> list[Finding]:
    if not active_plan:
        return [
            Finding(
                "info",
                "evidence-anchor-missing",
                "anchor scan skipped because no active plan is present",
            )
        ]
    findings: list[Finding] = []
    for anchor_name, patterns in ANCHOR_PATTERNS:
        cues = find_cues(active_plan, f"{anchor_name}-anchor", f"{anchor_name} anchor candidate", patterns)
        if cues:
            findings.extend(cue_findings("evidence-anchor-candidate", f"{anchor_name} anchor candidate", cues, limit=2))
        else:
            findings.append(
                Finding(
                    "warn",
                    "evidence-anchor-missing",
                    f"missing: {anchor_name} anchor candidate not found in active plan",
                    active_plan.rel_path,
                )
            )
    return findings


def _identity_findings(active_plan: Surface | None) -> list[Finding]:
    if not active_plan:
        return [
            Finding(
                "info",
                "evidence-identity",
                "cue identity scan skipped because no active plan is present; persistent evidence manifest remains deferred and no evidence manifest was written",
            )
        ]
    return [
        Finding(
            "info",
            "evidence-identity",
            "report-only cue identity uses kind, source path, line number, normalized preview, and a deterministic hash; persistent evidence manifest remains deferred and no generated report is written",
            active_plan.rel_path,
        )
    ]


def _closeout_findings(active_plan: Surface | None, inventory: Inventory) -> list[Finding]:
    findings: list[Finding] = []
    policy = inventory.manifest.get("policy", {}) if isinstance(inventory.manifest, dict) else {}
    closeout_commit = policy.get("closeout_commit")
    facts = state_writeback_facts(inventory.state)
    if closeout_commit:
        findings.append(
            Finding(
                "info",
                "evidence-closeout-candidate",
                f"candidate: manifest closeout_commit policy is {closeout_commit}",
                inventory.manifest_surface.rel_path if inventory.manifest_surface else None,
            )
        )

    if not active_plan and not facts:
        findings.append(
            Finding(
                "info",
                "evidence-closeout-missing",
                "closeout field scan skipped because no active plan is present",
            )
        )
        return findings

    for field in CLOSEOUT_FIELD_NAMES:
        fact = facts.get(field)
        if fact:
            findings.append(_writeback_fact_finding("evidence-closeout-candidate", f"{field} candidate", fact))
            continue
        if not active_plan:
            findings.append(
                Finding(
                    "warn",
                    "evidence-closeout-missing",
                    f"missing: concrete closeout field candidate not found: {field}",
                )
            )
            continue
        concrete, broad = closeout_field_cues(active_plan, field)
        if concrete:
            findings.extend(cue_findings("evidence-closeout-candidate", f"{field} candidate", concrete, limit=2))
        else:
            findings.append(
                Finding(
                    "warn",
                    "evidence-closeout-missing",
                    f"missing: concrete closeout field candidate not found: {field}",
                    active_plan.rel_path,
                )
            )
            if broad:
                findings.extend(cue_findings("evidence-closeout-context", f"{field} context", broad, limit=2))
    return findings


def _writeback_fact_finding(code: str, label: str, fact: WritebackFact) -> Finding:
    return Finding(
        "info",
        code,
        f"candidate: {label}: - {fact.field}: {fact.value}; source={fact.source}:{fact.line}",
        fact.source,
        fact.line,
    )


def _quality_cue_findings(active_plan: Surface | None, inventory: Inventory) -> list[Finding]:
    facts = state_writeback_facts(inventory.state)
    if not active_plan and not facts:
        return [
            Finding(
                "info",
                "evidence-quality-cue",
                "quality cue scan skipped because no active plan is present; no quality-gate state was written",
            )
        ]
    missing = [
        field
        for field in CLOSEOUT_FIELD_NAMES
        if field not in facts and (not active_plan or not closeout_field_cues(active_plan, field)[0])
    ]
    fact_source = active_plan.rel_path if active_plan else (inventory.state.rel_path if inventory.state and inventory.state.exists else None)
    if missing:
        return [
            Finding(
                "warn",
                "evidence-quality-cue",
                f"report-only closeout readiness cue: concrete field evidence missing for {', '.join(missing)}; this does not approve or block lifecycle decisions",
                fact_source,
            )
        ]
    return [
        Finding(
            "info",
            "evidence-quality-cue",
            "report-only closeout readiness cue: concrete closeout field evidence is present; operator decisions and observed verification remain required",
            fact_source,
        )
    ]


def _operator_required_findings(inventory: Inventory) -> list[Finding]:
    source = inventory.manifest_surface.rel_path if inventory.manifest_surface and inventory.manifest_surface.exists else None
    return [
        Finding(
            "info",
            "evidence-operator-required",
            "operator-required: collect worktree_start_state before closeout; evidence does not run Git or VCS commands",
            source,
        ),
        Finding(
            "info",
            "evidence-operator-required",
            "operator-required: classify task_scope before closeout from the actual work performed",
            source,
        ),
    ]


def _line_group_findings(
    active_plan: Surface | None,
    code: str,
    label: str,
    patterns: Iterable[str],
    inventory: Inventory,
) -> list[Finding]:
    fact_key = "residual_risk" if "residual" in label else "carry_forward" if "carry" in label else ""
    fact = state_writeback_facts(inventory.state).get(fact_key) if fact_key else None
    if fact:
        return [_writeback_fact_finding(code, f"{label} candidate", fact)]
    if not active_plan:
        return [Finding("info", code, f"{label} scan skipped because no active plan is present")]
    cues = find_cues(active_plan, label.replace(" ", "-"), f"{label} candidate", patterns)
    if not cues:
        return [Finding("warn", code, f"missing: {label} candidate not found in active plan", active_plan.rel_path)]
    return cue_findings(code, f"{label} candidate", cues)
