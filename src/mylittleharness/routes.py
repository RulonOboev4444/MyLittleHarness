from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryRoute:
    route_id: str
    target: str
    purpose: str
    start_path: str
    authority: str


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


def lifecycle_route_rows() -> tuple[tuple[str, str, str], ...]:
    return tuple((route.route_id, route.target, route.purpose) for route in LIVE_LIFECYCLE_ROUTES)


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
        ("project/specs/", "stable-specs"),
        ("project/verification/", "verification"),
        ("specs/workflow/", "package-mirror"),
        (".mylittleharness/generated/", "generated-cache"),
    )
    for prefix, prefix_route_id in prefixes:
        if lowered.startswith(prefix):
            return ROUTE_BY_ID[prefix_route_id]
    return ROUTE_BY_ID["unclassified"]
