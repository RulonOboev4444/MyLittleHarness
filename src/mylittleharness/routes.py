from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryRoute:
    route_id: str
    target: str
    purpose: str
    start_path: str
    authority: str


@dataclass(frozen=True)
class IntakeRouteAdvice:
    route_id: str
    target: str
    confidence: str
    reason: str
    next_action: str
    apply_allowed: bool


LIVE_LIFECYCLE_ROUTES: tuple[MemoryRoute, ...] = (
    MemoryRoute(
        "state",
        "project/project-state.md",
        "durable project memory, current focus, lifecycle pointers, and closeout writeback authority",
        "always",
        "authority",
    ),
    MemoryRoute(
        "active-plan",
        "project/implementation-plan.md",
        "bounded execution plan when plan_status is active",
        "when active",
        "authority",
    ),
    MemoryRoute(
        "roadmap",
        "project/roadmap.md",
        "optional sequencing surface for accepted work between incubation and one active implementation plan",
        "when planning/sequencing",
        "sequencing advisory",
    ),
    MemoryRoute(
        "incubation",
        "project/plan-incubation/*.md",
        "temporary same-topic synthesis before research, spec, or plan promotion",
        "by task",
        "non-authority until promoted",
    ),
    MemoryRoute(
        "research",
        "project/research/*.md",
        "durable research findings and distilled external evidence",
        "by task",
        "non-authority until promoted",
    ),
    MemoryRoute(
        "stable-specs",
        "project/specs/**/*.md",
        "stable workflow contracts and routing rules",
        "by route",
        "authority",
    ),
    MemoryRoute(
        "decisions",
        "project/decisions/*.md",
        "accepted rationale and do-not-revisit records",
        "by task",
        "authority when accepted",
    ),
    MemoryRoute(
        "adrs",
        "project/adrs/*.md",
        "material architecture decision records",
        "explicit need",
        "authority when accepted",
    ),
    MemoryRoute(
        "verification",
        "active-plan verification block; project/verification/*.md",
        "default verification evidence surface plus optional durable proof/evidence records",
        "at verification or closeout",
        "evidence",
    ),
    MemoryRoute(
        "agent-runs",
        "project/verification/agent-runs/*.md",
        "source-bound durable agent run evidence records",
        "at explicit run evidence record",
        "evidence",
    ),
    MemoryRoute(
        "closeout-writeback",
        "project/project-state.md MLH closeout writeback block",
        "current closeout fact authority; explicit closeout active-plan copies are derived metadata",
        "at closeout",
        "authority",
    ),
    MemoryRoute(
        "archive",
        "project/archive/plans/*.md; project/archive/reference/**",
        "historical plans and reference material, not default execution authority",
        "explicit need",
        "reference",
    ),
    MemoryRoute(
        "docs-routing",
        ".agents/docmap.yaml",
        "optional docs routing aid for product docs and impact checks; not authority by itself",
        "by task",
        "advisory",
    ),
)

SUPPORT_ROUTES: tuple[MemoryRoute, ...] = (
    MemoryRoute(
        "operating-guardrails",
        "AGENTS.md; .codex/project-workflow.toml",
        "operator contract and workflow manifest",
        "always",
        "authority",
    ),
    MemoryRoute(
        "orientation",
        "README.md",
        "human orientation surface",
        "by task",
        "advisory",
    ),
    MemoryRoute(
        "product-docs",
        "docs/**/*.md",
        "reusable product documentation and product contracts",
        "by task",
        "authority for product behavior",
    ),
    MemoryRoute(
        "generated-cache",
        ".mylittleharness/generated/**",
        "rebuildable navigation and search cache",
        "never authority",
        "generated advisory",
    ),
    MemoryRoute(
        "package-mirror",
        "specs/workflow/*.md",
        "package-source mirror material",
        "by task",
        "derived",
    ),
    MemoryRoute(
        "unclassified",
        "<unknown>",
        "repo-visible surface without a known memory route",
        "explicit inspection",
        "unknown",
    ),
)

ROUTE_REGISTRY: tuple[MemoryRoute, ...] = LIVE_LIFECYCLE_ROUTES + SUPPORT_ROUTES
ROUTE_BY_ID = {route.route_id: route for route in ROUTE_REGISTRY}

INTAKE_ROUTE_ALLOWED_TARGETS = {
    "adrs",
    "archive",
    "decisions",
    "incubation",
    "product-docs",
    "research",
    "verification",
}
INTAKE_ROUTE_DEFAULT_STATUS = {
    "adrs": "draft",
    "archive": "archived",
    "decisions": "draft",
    "incubation": "incubating",
    "product-docs": "draft",
    "research": "imported",
    "verification": "passed",
}
INTAKE_ROUTE_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("adrs", ("adr:", "adr ", "architecture decision record", "architecture decision")),
    ("decisions", ("decision:", "decided:", "do-not-revisit", "do not revisit", "we decided", "accepted decision")),
    ("verification", ("verification:", "verified:", "pytest", "tests passed", "smoke passed", "validation passed", "evidence:")),
    ("product-docs", ("docs impact:", "doc impact:", "documentation:", "readme", "docs update", "documentation update")),
    ("archive", ("archive reference:", "archived reference", "historical reference", "legacy reference", "for reference only")),
    ("research", ("research import:", "research:", "distillate:", "source notes", "imported research", "raw import")),
    ("incubation", ("future idea:", "idea:", "follow-up:", "follow up:", "later:", "todo:", "proposal:", "candidate:")),
)
AMBIGUOUS_INTAKE = IntakeRouteAdvice(
    route_id="ambiguous",
    target="<manual-route-required>",
    confidence="none",
    reason="no single route cue dominated the input",
    next_action="classify the input explicitly before writing operating memory",
    apply_allowed=False,
)

ROLE_TO_ROUTE_ID = {
    "active-plan": "active-plan",
    "adr": "adrs",
    "decision": "decisions",
    "docmap": "docs-routing",
    "incubation": "incubation",
    "manifest": "operating-guardrails",
    "operator-contract": "operating-guardrails",
    "orientation": "orientation",
    "package-mirror": "package-mirror",
    "product-doc": "product-docs",
    "project-state": "state",
    "roadmap": "roadmap",
    "research": "research",
    "stable-spec": "stable-specs",
    "verification": "verification",
}

_ROUTE_MUTABILITY = {
    "active-plan": "lifecycle-apply-rail",
    "adrs": "human-reviewed-authority",
    "archive": "archive-apply-rail",
    "agent-runs": "evidence-record-apply-rail",
    "closeout-writeback": "lifecycle-apply-rail",
    "decisions": "human-reviewed-authority",
    "docs-routing": "advisory-file",
    "generated-cache": "generated-rebuildable",
    "incubation": "intake-or-incubate-apply-rail",
    "operating-guardrails": "human-reviewed-authority",
    "product-docs": "human-reviewed-product-contract",
    "research": "research-or-hygiene-apply-rail",
    "roadmap": "roadmap-apply-rail",
    "stable-specs": "human-reviewed-authority",
    "state": "lifecycle-apply-rail",
    "verification": "evidence-route",
}

_ROUTE_GATE_CLASS = {
    "active-plan": "lifecycle",
    "adrs": "authority",
    "archive": "archive",
    "agent-runs": "evidence",
    "closeout-writeback": "lifecycle",
    "decisions": "authority",
    "operating-guardrails": "authority",
    "product-docs": "product-contract",
    "roadmap": "planning",
    "stable-specs": "authority",
    "state": "lifecycle",
}

_ROUTE_ALLOWED_DECISIONS = {
    "active-plan": ("plan", "writeback", "transition"),
    "adrs": ("accept", "supersede", "archive"),
    "archive": ("archive", "restore-reference"),
    "agent-runs": ("record", "inspect"),
    "closeout-writeback": ("writeback", "transition"),
    "decisions": ("accept", "supersede", "archive"),
    "operating-guardrails": ("repair", "manual-review"),
    "product-docs": ("update", "not-needed", "uncertain"),
    "roadmap": ("add", "update", "mark-active", "mark-done"),
    "stable-specs": ("update", "supersede", "reject"),
    "state": ("writeback", "compact", "transition"),
}


def lifecycle_route_rows() -> tuple[tuple[str, str, str], ...]:
    return tuple((route.route_id, route.target, route.purpose) for route in LIVE_LIFECYCLE_ROUTES)


def route_protocol_for_id(route_id: str | None) -> dict[str, object]:
    normalized = route_id if route_id in ROUTE_BY_ID else "unclassified"
    gate_class = _ROUTE_GATE_CLASS.get(normalized, "none" if normalized != "unclassified" else "unknown")
    allowed_decisions = _ROUTE_ALLOWED_DECISIONS.get(normalized, ())
    requires_gate = bool(allowed_decisions)
    reason = (
        f"route {normalized} changes require an explicit reviewed decision or apply rail"
        if requires_gate
        else "route is read-only, advisory, generated, or does not carry authority by itself"
    )
    return {
        "route_id": normalized,
        "mutability": _ROUTE_MUTABILITY.get(normalized, "unknown"),
        "human_gate": {
            "required": requires_gate,
            "gate_class": gate_class,
            "reason": reason,
            "allowed_decisions": list(allowed_decisions),
        },
        "gate_class": gate_class,
        "human_gate_reason": reason,
        "allowed_decisions": list(allowed_decisions),
        "advisory": normalized not in {"state", "active-plan", "stable-specs", "closeout-writeback"},
    }


def route_manifest() -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for route in ROUTE_REGISTRY:
        protocol = route_protocol_for_id(route.route_id)
        rows.append(
            {
                "route_id": route.route_id,
                "target": route.target,
                "purpose": route.purpose,
                "start_path": route.start_path,
                "authority": route.authority,
                "mutability": protocol["mutability"],
                "human_gate": protocol["human_gate"],
                "gate_class": protocol["gate_class"],
                "human_gate_reason": protocol["human_gate_reason"],
                "allowed_decisions": protocol["allowed_decisions"],
                "advisory": protocol["advisory"],
            }
        )
    return tuple(rows)


def classify_intake_text(text: str) -> IntakeRouteAdvice:
    normalized = _normalized_intake_text(text)
    if not normalized:
        return AMBIGUOUS_INTAKE

    matches: list[tuple[int, int, str, tuple[str, ...]]] = []
    for index, (route_id, cues) in enumerate(INTAKE_ROUTE_CUES):
        matched = tuple(cue for cue in cues if cue in normalized)
        if matched:
            matches.append((len(matched), index, route_id, matched))

    if not matches:
        return AMBIGUOUS_INTAKE

    matches.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    top_count, _top_index, route_id, top_cues = matches[0]
    if len(matches) > 1 and matches[1][0] == top_count:
        return IntakeRouteAdvice(
            route_id="ambiguous",
            target="<manual-route-required>",
            confidence="none",
            reason=f"multiple route cues matched: {route_id}, {matches[1][2]}",
            next_action="choose the destination route explicitly before applying intake",
            apply_allowed=False,
        )

    route = ROUTE_BY_ID[route_id]
    confidence = "high" if top_count > 1 or any(cue.endswith(":") for cue in top_cues) else "medium"
    return IntakeRouteAdvice(
        route_id=route_id,
        target=route.target,
        confidence=confidence,
        reason=f"matched cue(s): {', '.join(top_cues)}",
        next_action=_intake_next_action(route_id),
        apply_allowed=True,
    )


def intake_target_matches_route(route_id: str, rel_path: str) -> bool:
    if route_id not in INTAKE_ROUTE_ALLOWED_TARGETS:
        return False
    return classify_memory_route(rel_path).route_id == route_id


def classify_memory_route(rel_path: str, role: str = "") -> MemoryRoute:
    normalized = rel_path.replace("\\", "/").strip("/")
    lowered = normalized.casefold()

    role_route_id = ROLE_TO_ROUTE_ID.get(role)
    if role_route_id:
        return ROUTE_BY_ID[role_route_id]

    exact = {
        ".agents/docmap.yaml": "docs-routing",
        ".codex/project-workflow.toml": "operating-guardrails",
        "agents.md": "operating-guardrails",
        "readme.md": "orientation",
        "project/implementation-plan.md": "active-plan",
        "project/project-state.md": "state",
        "project/roadmap.md": "roadmap",
    }
    route_id = exact.get(lowered)
    if route_id:
        return ROUTE_BY_ID[route_id]

    prefixes = (
        ("docs/", "product-docs"),
        ("project/adrs/", "adrs"),
        ("project/archive/", "archive"),
        ("project/decisions/", "decisions"),
        ("project/plan-incubation/", "incubation"),
        ("project/research/", "research"),
        ("project/verification/agent-runs/", "agent-runs"),
        ("project/specs/", "stable-specs"),
        ("project/verification/", "verification"),
        ("specs/workflow/", "package-mirror"),
        (".mylittleharness/generated/", "generated-cache"),
    )
    for prefix, prefix_route_id in prefixes:
        if lowered.startswith(prefix):
            return ROUTE_BY_ID[prefix_route_id]
    return ROUTE_BY_ID["unclassified"]


def _normalized_intake_text(text: str) -> str:
    lowered = str(text or "").casefold()
    lowered = lowered.replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", lowered).strip()


def _intake_next_action(route_id: str) -> str:
    actions = {
        "adrs": "write an ADR under project/adrs/ only when an architecture decision is accepted",
        "archive": "write under project/archive/reference/** only for explicit historical reference material",
        "decisions": "write a decision record under project/decisions/ when rationale should not be rediscovered",
        "incubation": "use project/plan-incubation/*.md for future ideas that are not yet accepted work",
        "product-docs": "route docs impact to the relevant docs/**/*.md product contract or README surface",
        "research": "write imported or distilled research under project/research/*.md before promotion",
        "verification": "write durable proof under project/verification/*.md only when reusable evidence is worth the ceremony",
    }
    return actions.get(route_id, AMBIGUOUS_INTAKE.next_action)
