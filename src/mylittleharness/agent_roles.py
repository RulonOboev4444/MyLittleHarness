from __future__ import annotations

from dataclasses import dataclass

from .routes import ROUTE_BY_ID, route_protocol_for_id


@dataclass(frozen=True)
class RolePermission:
    route_id: str
    read: bool = False
    propose: bool = False
    apply: bool = False
    requires_human_gate: bool = False

    def to_manifest(self) -> dict[str, object]:
        protocol = route_protocol_for_id(self.route_id)
        route_gate = dict(protocol["human_gate"])
        requires_gate = self.requires_human_gate or bool((self.propose or self.apply) and route_gate["required"])
        human_gate = {
            **route_gate,
            "required": requires_gate,
        }
        return {
            "route_id": str(protocol["route_id"]),
            "read": self.read,
            "propose": self.propose,
            "apply": self.apply,
            "requires_human_gate": requires_gate,
            "route_requires_human_gate": bool(route_gate["required"]),
            "gate_class": str(protocol["gate_class"]),
            "mutability": str(protocol["mutability"]),
            "allowed_decisions": list(protocol["allowed_decisions"]),
            "human_gate": human_gate,
            "advisory": True,
        }


@dataclass(frozen=True)
class RoleProfile:
    role_id: str
    title: str
    purpose: str
    default_inputs: tuple[str, ...]
    context_packet_requirements: tuple[str, ...]
    required_outputs: tuple[str, ...]
    output_packet_requirements: tuple[str, ...]
    permissions: tuple[RolePermission, ...]
    forbidden_actions: tuple[str, ...]
    stop_conditions: tuple[str, ...]

    def to_manifest(self) -> dict[str, object]:
        permission_rows = tuple(permission.to_manifest() for permission in self.permissions)
        human_gates = tuple(
            {
                "route_id": permission["route_id"],
                "gate_class": permission["gate_class"],
                "reason": permission["human_gate"]["reason"],
                "allowed_decisions": permission["human_gate"]["allowed_decisions"],
            }
            for permission in permission_rows
            if permission["human_gate"]["required"]
        )
        return {
            "role_id": self.role_id,
            "title": self.title,
            "purpose": self.purpose,
            "default_inputs": list(self.default_inputs),
            "context_packet_requirements": list(self.context_packet_requirements),
            "required_outputs": list(self.required_outputs),
            "output_packet_requirements": list(self.output_packet_requirements),
            "permissions": list(permission_rows),
            "human_gates": list(human_gates),
            "forbidden_actions": list(self.forbidden_actions),
            "stop_conditions": list(self.stop_conditions),
            "apply_authority": any(permission.apply for permission in self.permissions),
            "advisory": True,
        }


COMMON_CONTEXT_PACKET = (
    "role_id",
    "task",
    "input_refs",
    "allowed_routes",
    "stop_conditions",
)
COMMON_OUTPUT_PACKET = (
    "status",
    "output_refs",
    "evidence",
    "residual_risk",
)
COMMON_FORBIDDEN_ACTIONS = (
    "approve lifecycle transitions",
    "archive plans",
    "stage, commit, push, or release",
    "bypass explicit dry-run/apply rails",
    "store hidden memory as authority",
)
COMMON_STOP_CONDITIONS = (
    "route authority is ambiguous",
    "requested write is outside the assigned scope",
    "verification is missing or failed",
    "human gate is required but no reviewed decision is present",
)


def _permissions(*rows: tuple[str, ...]) -> tuple[RolePermission, ...]:
    permissions: list[RolePermission] = []
    for row in rows:
        if not row or row[0] not in ROUTE_BY_ID:
            raise ValueError(f"unknown role permission route: {row[0] if row else '<missing>'}")
        actions = set(row[1:])
        permissions.append(
            RolePermission(
                row[0],
                read="read" in actions,
                propose="propose" in actions,
                apply="apply" in actions,
                requires_human_gate="gate" in actions,
            )
        )
    return tuple(permissions)


ROLE_PROFILES: tuple[RoleProfile, ...] = (
    RoleProfile(
        role_id="intake-clerk",
        title="Intake Clerk",
        purpose="Classify incoming information before it becomes operating-memory clutter.",
        default_inputs=("user_text", "route_manifest", "project_state"),
        context_packet_requirements=COMMON_CONTEXT_PACKET,
        required_outputs=("route_advice", "target_route_or_refusal", "source_text_summary"),
        output_packet_requirements=COMMON_OUTPUT_PACKET + ("target_route",),
        permissions=_permissions(
            ("state", "read"),
            ("roadmap", "read"),
            ("incubation", "read", "propose"),
            ("research", "read", "propose"),
            ("verification", "read"),
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS
        + (
            "accept specs",
            "open implementation plans",
            "mark roadmap items done",
        ),
        stop_conditions=COMMON_STOP_CONDITIONS + ("input matches multiple destination routes",),
    ),
    RoleProfile(
        role_id="researcher",
        title="Researcher",
        purpose="Gather and compress source-bound knowledge without making findings authoritative.",
        default_inputs=("intake_refs", "archive_refs", "source_refs"),
        context_packet_requirements=COMMON_CONTEXT_PACKET + ("source_policy",),
        required_outputs=("research_distillate", "source_refs", "limits_and_uncertainties"),
        output_packet_requirements=COMMON_OUTPUT_PACKET + ("citations",),
        permissions=_permissions(
            ("archive", "read"),
            ("incubation", "read"),
            ("research", "read", "propose"),
            ("product-docs", "read"),
            ("stable-specs", "read"),
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS + ("make research findings authoritative",),
        stop_conditions=COMMON_STOP_CONDITIONS + ("source provenance cannot be preserved",),
    ),
    RoleProfile(
        role_id="specifier",
        title="Specifier",
        purpose="Turn accepted evidence into candidate contracts and amendments.",
        default_inputs=("research_refs", "incubation_refs", "existing_specs", "decisions"),
        context_packet_requirements=COMMON_CONTEXT_PACKET + ("contract_status",),
        required_outputs=("draft_spec_delta", "affected_contracts", "open_questions"),
        output_packet_requirements=COMMON_OUTPUT_PACKET + ("contract_refs",),
        permissions=_permissions(
            ("research", "read"),
            ("incubation", "read"),
            ("stable-specs", "read", "propose"),
            ("decisions", "read", "propose"),
            ("adrs", "read", "propose"),
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS + ("silently change accepted contracts",),
        stop_conditions=COMMON_STOP_CONDITIONS + ("accepted contract status is unclear",),
    ),
    RoleProfile(
        role_id="planner",
        title="Planner",
        purpose="Convert accepted intent into a bounded implementation-plan scaffold.",
        default_inputs=("roadmap_item", "project_state", "related_specs", "product_target_context"),
        context_packet_requirements=COMMON_CONTEXT_PACKET + ("execution_slice",),
        required_outputs=("plan_scaffold", "write_scope", "verification_gates", "stop_conditions"),
        output_packet_requirements=COMMON_OUTPUT_PACKET + ("active_plan_ref",),
        permissions=_permissions(
            ("state", "read"),
            ("roadmap", "read", "propose"),
            ("active-plan", "read", "propose"),
            ("stable-specs", "read"),
            ("product-docs", "read"),
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS
        + (
            "edit product code",
            "approve closeout",
        ),
        stop_conditions=COMMON_STOP_CONDITIONS + ("requested slice cannot be bounded",),
    ),
    RoleProfile(
        role_id="coder",
        title="Coder",
        purpose="Implement bounded source changes inside the declared write scope.",
        default_inputs=("active_plan", "target_artifacts", "adjacent_tests", "related_specs"),
        context_packet_requirements=COMMON_CONTEXT_PACKET + ("write_scope",),
        required_outputs=("patch_summary", "changed_paths", "test_plan", "residual_risk"),
        output_packet_requirements=COMMON_OUTPUT_PACKET + ("changed_paths",),
        permissions=_permissions(
            ("active-plan", "read"),
            ("stable-specs", "read"),
            ("product-docs", "read", "propose"),
            ("unclassified", "read", "propose"),
            ("verification", "read", "propose"),
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS
        + (
            "change lifecycle state",
            "spawn workers without an explicit handoff contract",
            "rewrite accepted specs as part of implementation",
        ),
        stop_conditions=COMMON_STOP_CONDITIONS + ("source reality invalidates the active write scope",),
    ),
    RoleProfile(
        role_id="reviewer",
        title="Reviewer",
        purpose="Identify defects, scope drift, and missing proof without approving release alone.",
        default_inputs=("patch", "active_plan", "spec_refs", "test_results"),
        context_packet_requirements=COMMON_CONTEXT_PACKET + ("review_scope",),
        required_outputs=("findings", "severity", "requested_changes", "test_gaps"),
        output_packet_requirements=COMMON_OUTPUT_PACKET + ("review_findings",),
        permissions=_permissions(
            ("active-plan", "read"),
            ("stable-specs", "read"),
            ("product-docs", "read"),
            ("verification", "read", "propose"),
            ("unclassified", "read"),
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS + ("approve release alone",),
        stop_conditions=COMMON_STOP_CONDITIONS + ("patch scope cannot be matched to the plan",),
    ),
    RoleProfile(
        role_id="verifier",
        title="Verifier",
        purpose="Prove behavior with deterministic commands and source-bound evidence.",
        default_inputs=("active_plan", "commands", "changed_paths"),
        context_packet_requirements=COMMON_CONTEXT_PACKET + ("verification_gate",),
        required_outputs=("command_results", "verdict", "skips", "evidence_refs"),
        output_packet_requirements=COMMON_OUTPUT_PACKET + ("commands", "verdict"),
        permissions=_permissions(
            ("active-plan", "read"),
            ("stable-specs", "read"),
            ("verification", "read", "propose"),
            ("unclassified", "read"),
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS + ("change scope or product promises",),
        stop_conditions=COMMON_STOP_CONDITIONS + ("deterministic success signal is missing",),
    ),
    RoleProfile(
        role_id="devops-sandbox-operator",
        title="DevOps/Sandbox Operator",
        purpose="Run approved commands and isolate tools while preserving host and secret boundaries.",
        default_inputs=("active_plan", "command_policy", "environment_contract"),
        context_packet_requirements=COMMON_CONTEXT_PACKET + ("command_allowlist",),
        required_outputs=("command_results", "artifacts", "environment_notes"),
        output_packet_requirements=COMMON_OUTPUT_PACKET + ("commands", "artifacts"),
        permissions=_permissions(
            ("active-plan", "read"),
            ("operating-guardrails", "read"),
            ("verification", "read", "propose"),
            ("generated-cache", "read", "propose"),
            ("unclassified", "read"),
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS
        + (
            "expose secrets",
            "mutate workstation state without an adoption contract",
            "decide architecture",
        ),
        stop_conditions=COMMON_STOP_CONDITIONS + ("command requires destructive or sensitive host access",),
    ),
    RoleProfile(
        role_id="reconciler",
        title="Reconciler",
        purpose="Compare intended contracts with observed code and evidence, then propose drift handling.",
        default_inputs=("spec_refs", "code_refs", "evidence_refs", "diff"),
        context_packet_requirements=COMMON_CONTEXT_PACKET + ("drift_basis",),
        required_outputs=("drift_record", "classification", "proposal", "affected_authority"),
        output_packet_requirements=COMMON_OUTPUT_PACKET + ("drift_refs",),
        permissions=_permissions(
            ("stable-specs", "read", "propose"),
            ("decisions", "read", "propose"),
            ("incubation", "read", "propose"),
            ("verification", "read"),
            ("unclassified", "read"),
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS + ("silently normalize authority to implementation",),
        stop_conditions=COMMON_STOP_CONDITIONS + ("contract and implementation cannot be compared from source refs",),
    ),
    RoleProfile(
        role_id="archivist",
        title="Archivist",
        purpose="Move cold memory out of active lanes while keeping provenance recoverable.",
        default_inputs=("terminal_artifacts", "source_links", "coverage_evidence"),
        context_packet_requirements=COMMON_CONTEXT_PACKET + ("archive_boundary",),
        required_outputs=("archive_plan", "link_repairs", "provenance_summary"),
        output_packet_requirements=COMMON_OUTPUT_PACKET + ("archive_refs",),
        permissions=_permissions(
            ("state", "read"),
            ("active-plan", "read"),
            ("archive", "read", "propose"),
            ("incubation", "read", "propose"),
            ("research", "read", "propose"),
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS + ("delete unresolved provenance",),
        stop_conditions=COMMON_STOP_CONDITIONS + ("entry coverage is incomplete",),
    ),
    RoleProfile(
        role_id="governor",
        title="Governor",
        purpose="Represent deterministic MLH state-machine law and bounded apply rails.",
        default_inputs=("reviewed_request", "repo_visible_state", "route_protocol", "review_token"),
        context_packet_requirements=COMMON_CONTEXT_PACKET + ("review_token", "source_hashes"),
        required_outputs=("dry_run_report", "apply_report_or_refusal", "route_write_evidence"),
        output_packet_requirements=COMMON_OUTPUT_PACKET + ("review_token_status",),
        permissions=_permissions(
            ("state", "read", "propose"),
            ("active-plan", "read", "propose"),
            ("roadmap", "read", "propose"),
            ("closeout-writeback", "read", "propose"),
            ("archive", "read", "propose"),
            ("stable-specs", "read"),
        ),
        forbidden_actions=COMMON_FORBIDDEN_ACTIONS
        + (
            "hallucinate route writes",
            "bypass review tokens",
            "depend on hidden memory",
        ),
        stop_conditions=COMMON_STOP_CONDITIONS + ("review token or source hash has drifted",),
    ),
)
ROLE_PROFILE_BY_ID = {profile.role_id: profile for profile in ROLE_PROFILES}


def role_manifest() -> tuple[dict[str, object], ...]:
    return tuple(profile.to_manifest() for profile in ROLE_PROFILES)


def role_profile_for_id(role_id: str) -> RoleProfile | None:
    return ROLE_PROFILE_BY_ID.get(role_id)


def roles_with_apply_authority() -> tuple[str, ...]:
    return tuple(profile.role_id for profile in ROLE_PROFILES if any(permission.apply for permission in profile.permissions))
