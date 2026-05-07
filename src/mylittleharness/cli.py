from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path

from .adapter import (
    MCP_READ_PROJECTION_TARGET,
    mcp_read_projection_client_config,
    mcp_read_projection_sections,
    serve_mcp_read_projection,
)
from .agent_roles import role_manifest
from .bootstrap import bootstrap_sections, package_smoke_sections
from .checks import (
    attach_apply_findings,
    attach_dry_run_findings,
    audit_link_findings,
    check_drift_findings,
    context_budget_findings,
    doctor_findings,
    flatten_sections,
    intelligence_sections,
    intelligence_route_sections,
    intake_apply_findings,
    intake_dry_run_findings,
    load_for_root,
    make_intake_request,
    projection_cache_status_findings,
    detach_apply_sections,
    repair_apply_findings,
    repair_dry_run_findings,
    snapshot_inspect_findings,
    status_findings,
    detach_dry_run_sections,
    validation_findings,
)
from .closeout import closeout_sections
from .command_discovery import (
    command_intent_registry,
    command_suggestion_boundary_findings,
    command_suggestion_findings,
    command_suggestions_for_intent,
    command_suggestions_to_dict,
)
from .evidence import (
    agent_run_record_apply_findings,
    agent_run_record_dry_run_findings,
    agent_run_record_findings,
    evidence_findings,
    make_agent_run_record_request,
)
from .incubate import incubate_apply_findings, incubate_dry_run_findings, make_incubate_request
from .grain import grain_findings
from .inventory import RootLoadError
from .meta_feedback import (
    META_FEEDBACK_ROOT_ENV_VAR,
    make_meta_feedback_request,
    meta_feedback_apply_findings,
    meta_feedback_dry_run_findings,
)
from .memory_hygiene import (
    make_memory_hygiene_request,
    memory_hygiene_apply_findings,
    memory_hygiene_dry_run_findings,
)
from .mirror import make_mirror_request, mirror_apply_findings, mirror_dry_run_findings
from .models import Finding
from .parsing import extract_headings, extract_path_refs, parse_frontmatter
from .planning import make_plan_request, plan_apply_findings, plan_dry_run_findings, resolve_plan_request_from_roadmap
from .projection_artifacts import (
    build_projection_artifacts,
    delete_projection_artifacts,
    inspect_projection_artifacts,
    mark_projection_cache_dirty,
    rebuild_projection_artifacts,
)
from .projection_index import (
    build_projection_index,
    delete_projection_index,
    inspect_projection_index,
    rebuild_projection_index,
)
from .preflight import preflight_sections, render_git_pre_commit_template
from .reporting import emit_text, render_intelligence_report, render_json_report, render_report, render_sectioned_report
from .routes import route_manifest
from .roadmap import make_roadmap_request, roadmap_apply_findings, roadmap_dry_run_findings, roadmap_item_fields
from .semantic import semantic_evaluate_sections, semantic_inspect_sections
from .tasks import tasks_sections
from .writeback import make_writeback_request, writeback_apply_findings, writeback_dry_run_findings


COMMANDS = (
    "init",
    "check",
    "suggest",
    "manifest",
    "repair",
    "detach",
    "status",
    "validate",
    "context-budget",
    "audit-links",
    "doctor",
    "preflight",
    "tasks",
    "bootstrap",
    "semantic",
    "intelligence",
    "evidence",
    "closeout",
    "intake",
    "incubate",
    "plan",
    "writeback",
    "transition",
    "memory-hygiene",
    "roadmap",
    "meta-feedback",
    "mirror",
    "projection",
    "snapshot",
    "attach",
    "adapter",
)
CACHE_DIRTY_APPLY_COMMANDS = {
    "evidence",
    "incubate",
    "intake",
    "memory-hygiene",
    "meta-feedback",
    "plan",
    "repair",
    "roadmap",
    "transition",
    "writeback",
}


@dataclass(frozen=True)
class LifecyclePosture:
    plan_status: str
    active_plan: str
    active_phase: str
    phase_status: str
    active_plan_exists: bool
    active_plan_hash: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mylittleharness",
        description="MyLittleHarness repo safety utility. Primary commands: init, check, repair, detach.",
        epilog="Compatibility and advanced diagnostics remain available for recovery and transition.",
    )
    parser.add_argument("--root", default=".", help="Target workflow root. Defaults to the current directory.")
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="{init,check,repair,detach,...}")
    init = subparsers.add_parser("init", help="Attach MyLittleHarness to a target repository.")
    init_mode = init.add_mutually_exclusive_group(required=True)
    init_mode.add_argument("--dry-run", action="store_true", help="Report the init proposal without writing files.")
    init_mode.add_argument("--apply", action="store_true", help="Create only allowed missing scaffold/template paths.")
    init.add_argument("--project", help="Project name to use when creating project/project-state.md.")
    check = subparsers.add_parser("check", help="Run read-only status and validation checks without writing files.")
    check_mode = check.add_mutually_exclusive_group()
    check_mode.add_argument("--deep", action="store_true", help="Include links, context, and hygiene diagnostics in the read-only check report.")
    check_mode.add_argument(
        "--focus",
        choices=("validation", "links", "context", "hygiene", "grain"),
        help="Run one focused read-only diagnostic through check.",
    )
    check.add_argument("--json", action="store_true", help="Emit a structured JSON report while preserving the default text report.")
    manifest = subparsers.add_parser(
        "manifest",
        help=argparse.SUPPRESS,
        description="Advanced diagnostic: inspect the structured route and role manifest for external agents and orchestrators.",
    )
    manifest.add_argument("--inspect", action="store_true", required=True, help="Inspect the route and role manifest without writing files.")
    manifest.add_argument("--json", action="store_true", help="Emit the route and role manifest as structured JSON.")
    suggest = subparsers.add_parser(
        "suggest",
        help=argparse.SUPPRESS,
        description="Advanced diagnostic: report deterministic command intent suggestions without running them.",
    )
    suggest_mode = suggest.add_mutually_exclusive_group(required=True)
    suggest_mode.add_argument("--intent", help="Operator action to match against the deterministic command intent registry.")
    suggest_mode.add_argument("--list", action="store_true", help="List the deterministic command intent registry.")
    suggest.add_argument("--limit", type=_positive_int, default=3, help="Maximum suggestions to return for --intent. Defaults to 3.")
    suggest.add_argument("--json", action="store_true", help="Emit machine-readable command suggestions.")
    repair = subparsers.add_parser("repair", help="Preview or apply deterministic workflow contract repair.")
    repair_mode = repair.add_mutually_exclusive_group(required=True)
    repair_mode.add_argument("--dry-run", action="store_true", help="Report the repair proposal without writing files.")
    repair_mode.add_argument("--apply", action="store_true", help="Create only allowed missing repair paths.")
    detach = subparsers.add_parser("detach", help="Preview harness detach posture without writing files.")
    detach_mode = detach.add_mutually_exclusive_group(required=True)
    detach_mode.add_argument("--dry-run", action="store_true", help="Report detach preservation and refusal posture without writing files.")
    detach_mode.add_argument("--apply", action="store_true", help="Create the marker-only detach evidence file in an eligible live operating root.")
    for command in ("status", "validate", "context-budget", "audit-links", "doctor", "closeout"):
        subparsers.add_parser(command)
    evidence = subparsers.add_parser(
        "evidence",
        help=argparse.SUPPRESS,
        description="Advanced evidence helper: report closeout evidence or explicitly record source-bound agent run evidence.",
    )
    evidence.add_argument("--record", action="store_true", help="Write or preview an explicit agent run evidence record.")
    evidence_mode = evidence.add_mutually_exclusive_group()
    evidence_mode.add_argument("--dry-run", action="store_true", help="Preview an agent run evidence record without writing files.")
    evidence_mode.add_argument("--apply", action="store_true", help="Write one explicit agent run evidence record in a live operating root.")
    evidence.add_argument("--record-id", dest="record_id", help="Stable record id used as the Markdown filename under project/verification/agent-runs/.")
    evidence.add_argument("--role", dest="agent_role", help="Agent role that produced the work, such as coder, reviewer, or verifier.")
    evidence.add_argument("--actor", help="Human, agent, or tool actor label.")
    evidence.add_argument("--task", help="One-line task summary for the run record.")
    evidence.add_argument("--status", choices=("succeeded", "failed", "blocked", "skipped", "needs-refinement", "needs-human-review"), help="Run outcome status.")
    evidence.add_argument("--stop-reason", dest="stop_reason", help="Why the run stopped.")
    evidence.add_argument("--attempt-budget", dest="attempt_budget", help="Attempt budget posture, such as 1/3 or exhausted.")
    evidence.add_argument("--input-ref", dest="input_refs", action="append", default=[], help="Root-relative input route or source path. May be repeated.")
    evidence.add_argument("--output-ref", dest="output_refs", action="append", default=[], help="Root-relative output evidence or source path. May be repeated.")
    evidence.add_argument("--claimed-path", dest="claimed_paths", action="append", default=[], help="Root-relative path claimed or changed by the run. May be repeated.")
    evidence.add_argument("--command", dest="commands", action="append", default=[], help="Command run or intentionally recorded by the agent. May be repeated.")
    evidence.add_argument("--repeated-failure-signature", dest="repeated_failure_signature", help="Optional repeated failure or no-progress loop signature.")
    evidence.add_argument("--provider", help="Optional model/provider provenance.")
    evidence.add_argument("--model-id", dest="model_id", help="Optional model identifier provenance.")
    evidence.add_argument("--tool", dest="tools", action="append", default=[], help="Optional tool metadata. May be repeated.")
    intake = subparsers.add_parser(
        "intake",
        help=argparse.SUPPRESS,
        description="Advanced mutating command: route incoming information before it becomes incubation clutter.",
    )
    intake_mode = intake.add_mutually_exclusive_group(required=True)
    intake_mode.add_argument("--dry-run", action="store_true", help="Classify the intake text without writing files.")
    intake_mode.add_argument("--apply", action="store_true", help="Write one explicit new Markdown intake target in a compatible route.")
    intake_text = intake.add_mutually_exclusive_group(required=True)
    intake_text.add_argument("--text", help="Incoming information to classify or write.")
    intake_text.add_argument("--text-file", dest="text_file", help="Read incoming information from a UTF-8 file; use - for stdin.")
    intake.add_argument("--title", help="Optional Markdown title for the applied intake note.")
    intake.add_argument("--target", help="Explicit root-relative Markdown target for --apply.")
    incubate = subparsers.add_parser(
        "incubate",
        help=argparse.SUPPRESS,
        description="Advanced mutating command: create or append explicit future-idea incubation notes.",
    )
    incubate_mode = incubate.add_mutually_exclusive_group(required=True)
    incubate_mode.add_argument("--dry-run", action="store_true", help="Preview the incubation note target without writing files.")
    incubate_mode.add_argument("--apply", action="store_true", help="Create or append the same-topic incubation note in an eligible live operating root.")
    incubate.add_argument("--topic", required=True, help="Plain future-idea topic used to derive the safe note slug.")
    incubate_note = incubate.add_mutually_exclusive_group(required=True)
    incubate_note.add_argument("--note", help="Explicit incubation note text to record.")
    incubate_note.add_argument("--note-file", dest="note_file", help="Read explicit incubation note text from a UTF-8 file; use - for stdin.")
    incubate.add_argument("--fix-candidate", action="store_true", help="Prefix the note with [MLH-Fix-Candidate] if it is not already tagged.")
    plan = subparsers.add_parser(
        "plan",
        help=argparse.SUPPRESS,
        description="Advanced mutating command: create or replace a deterministic active implementation-plan scaffold with current-phase-only execution metadata.",
    )
    plan_mode = plan.add_mutually_exclusive_group(required=True)
    plan_mode.add_argument("--dry-run", action="store_true", help="Preview deterministic implementation-plan synthesis without writing files.")
    plan_mode.add_argument("--apply", action="store_true", help="Write the active implementation plan and lifecycle frontmatter in an eligible live operating root.")
    plan.add_argument("--title", help="Implementation plan title to render into frontmatter and the first heading. Required unless --roadmap-item can derive it.")
    plan.add_argument("--objective", help="Concrete objective to render into the generated implementation plan. Required unless --roadmap-item can derive it.")
    plan.add_argument("--task", help="Optional explicit task input to preserve inside the generated plan.")
    plan.add_argument("--update-active", action="store_true", help="Replace the current default active plan when project-state already has plan_status active.")
    plan.add_argument("--roadmap-item", dest="roadmap_item", help="Optional existing roadmap item id to link to the active plan.")
    plan.add_argument("--only-requested-item", action="store_true", help="Limit roadmap sync and slice frontmatter to only --roadmap-item.")
    writeback = subparsers.add_parser(
        "writeback",
        help=argparse.SUPPRESS,
        description="Advanced mutating command: apply explicit closeout/state writeback and synchronize derived active-plan copies; lifecycle writes do not approve auto-continue.",
    )
    writeback_mode = writeback.add_mutually_exclusive_group(required=True)
    writeback_mode.add_argument("--dry-run", action="store_true", help="Preview closeout/state writeback without writing files.")
    writeback_mode.add_argument("--apply", action="store_true", help="Write the MLH-owned closeout/state writeback block and synchronized derived copies.")
    writeback.add_argument("--worktree-start-state", dest="worktree_start_state", help="Closeout worktree_start_state value to record.")
    writeback.add_argument("--task-scope", dest="task_scope", help="Closeout task_scope value to record.")
    writeback.add_argument("--docs-decision", dest="docs_decision", help="Closeout docs_decision value: updated, not-needed, or uncertain.")
    writeback.add_argument("--state-writeback", dest="state_writeback", help="Closeout state_writeback value to record.")
    writeback.add_argument("--verification", help="Closeout verification value to record.")
    writeback.add_argument("--commit-decision", dest="commit_decision", help="Closeout commit_decision value to record.")
    writeback.add_argument("--residual-risk", dest="residual_risk", help="Optional closeout residual_risk value to record.")
    writeback.add_argument("--carry-forward", dest="carry_forward", help="Optional closeout carry_forward value to record.")
    writeback.add_argument("--work-result", dest="work_result", help="Optional plain-language closeout work_result capsule to record.")
    writeback.add_argument("--active-phase", dest="active_phase", help="Lifecycle active_phase value to write to project-state frontmatter.")
    writeback.add_argument("--phase-status", dest="phase_status", help="Lifecycle phase_status value to write to project-state frontmatter.")
    writeback.add_argument("--last-archived-plan", dest="last_archived_plan", help="Lifecycle last_archived_plan value to write to project-state frontmatter.")
    writeback.add_argument("--product-source-root", dest="product_source_root", help="Structured product_source_root value to write to project-state frontmatter.")
    writeback.add_argument("--archive-active-plan", action="store_true", help="Move the active implementation plan to the canonical archive and close the active lifecycle pointer.")
    writeback.add_argument("--from-active-plan", action="store_true", help="Harvest closeout facts from the active plan Closeout Summary/Facts/Fields section.")
    writeback.add_argument("--compact-only", action="store_true", help="Only preview or apply safe project-state history compaction.")
    writeback.add_argument("--allow-auto-compaction", action="store_true", help="Allow explicit lifecycle writeback to run project-state auto-compaction when the dry-run reports it would cross the size threshold.")
    writeback.add_argument("--roadmap-item", dest="roadmap_item", help="Optional existing roadmap item id to receive selected plan/writeback relationship facts.")
    writeback.add_argument("--roadmap-status", dest="roadmap_status", help="Optional roadmap status to write with --roadmap-item.")
    writeback.add_argument("--archived-plan", dest="archived_plan", help="Archived implementation-plan route to refresh closeout, roadmap, and source-incubation facts after the active lifecycle has already closed.")
    transition = subparsers.add_parser(
        "transition",
        help=argparse.SUPPRESS,
        description="Advanced mutating command: explicitly review and apply a closeout/archive/next-plan transition composed from writeback and plan rails.",
    )
    transition_mode = transition.add_mutually_exclusive_group(required=True)
    transition_mode.add_argument("--dry-run", action="store_true", help="Preview the transition proposal and review token without writing files.")
    transition_mode.add_argument("--apply", action="store_true", help="Apply the reviewed transition only when --review-token matches current repo-visible inputs.")
    transition.add_argument("--review-token", help="Review token printed by the matching transition dry-run; required for --apply.")
    transition.add_argument("--complete-current-phase", action="store_true", help="First write phase_status complete through writeback.")
    transition.add_argument("--archive-active-plan", action="store_true", help="Archive the current active plan through writeback after any phase completion step.")
    transition.add_argument("--allow-auto-compaction", action="store_true", help="Allow writeback steps in this transition to run project-state auto-compaction when the dry-run reports it would cross the size threshold.")
    transition.add_argument("--from-active-plan", action="store_true", help="Harvest archive closeout facts from the active plan.")
    transition.add_argument("--current-roadmap-item", dest="current_roadmap_item", help="Explicit current roadmap item to mark done during archive closeout.")
    transition.add_argument(
        "--current-roadmap-status",
        dest="current_roadmap_status",
        choices=("done", "blocked", "superseded"),
        help="Explicit terminal status for --current-roadmap-item during archive closeout. Defaults to done.",
    )
    transition.add_argument("--next-roadmap-item", dest="next_roadmap_item", help="Explicit roadmap item for the next active implementation plan.")
    transition.add_argument("--next-title", dest="next_title", help="Title for the next active implementation plan. Derived from --next-roadmap-item when omitted and available.")
    transition.add_argument("--next-objective", dest="next_objective", help="Objective for the next active implementation plan. Derived from --next-roadmap-item when omitted and available.")
    transition.add_argument("--next-task", dest="next_task", help="Optional explicit task input for the next active implementation plan. Derived from --next-roadmap-item when omitted and available.")
    transition.add_argument("--only-requested-item", action="store_true", help="Limit next-plan roadmap sync and slice frontmatter to --next-roadmap-item.")
    transition.add_argument("--worktree-start-state", dest="worktree_start_state", help="Archive closeout worktree_start_state value to record.")
    transition.add_argument("--task-scope", dest="task_scope", help="Archive closeout task_scope value to record.")
    transition.add_argument("--docs-decision", dest="docs_decision", help="Archive closeout docs_decision value: updated, not-needed, or uncertain.")
    transition.add_argument("--state-writeback", dest="state_writeback", help="Archive closeout state_writeback value to record.")
    transition.add_argument("--verification", help="Archive closeout verification value to record.")
    transition.add_argument("--commit-decision", dest="commit_decision", help="Archive closeout commit_decision value to record.")
    transition.add_argument("--residual-risk", dest="residual_risk", help="Optional archive closeout residual_risk value to record.")
    transition.add_argument("--carry-forward", dest="carry_forward", help="Optional archive closeout carry_forward value to record.")
    transition.add_argument("--work-result", dest="work_result", help="Optional plain-language archive closeout work_result capsule to record.")
    memory_hygiene = subparsers.add_parser(
        "memory-hygiene",
        help=argparse.SUPPRESS,
        description="Advanced mutating command: apply explicit research/incubation lifecycle hygiene.",
    )
    memory_hygiene_mode = memory_hygiene.add_mutually_exclusive_group(required=True)
    memory_hygiene_mode.add_argument("--dry-run", action="store_true", help="Preview lifecycle hygiene without writing files.")
    memory_hygiene_mode.add_argument("--apply", action="store_true", help="Write bounded lifecycle metadata, archive movement, and exact link repairs in an eligible live operating root.")
    memory_hygiene.add_argument("--source", help="Root-relative MLH-owned research/incubation Markdown source to update.")
    memory_hygiene.add_argument("--promoted-to", dest="promoted_to", help="Root-relative accepted destination recorded as promoted_to.")
    memory_hygiene.add_argument("--status", help="Lifecycle status to write. Defaults to distilled when --promoted-to is supplied.")
    memory_hygiene.add_argument("--archive-to", dest="archive_to", help="Explicit root-relative archive target under project/archive/reference/research or incubation.")
    memory_hygiene.add_argument("--repair-links", action="store_true", help="Repair exact root-relative source path references to the archive path.")
    memory_hygiene.add_argument("--scan", action="store_true", help="Read-only relationship hygiene and incubation cleanup advisor scan; valid with --dry-run.")
    memory_hygiene.add_argument("--archive-covered", action="store_true", help="For incubation notes, derive an archive target and require terminal Entry Coverage before archive.")
    memory_hygiene.add_argument("--entry-coverage", dest="entry_coverage", action="append", default=[], help="Terminal Entry Coverage bullet value `<entry-id>: <status> <destination>`; may be repeated.")
    roadmap = subparsers.add_parser(
        "roadmap",
        help=argparse.SUPPRESS,
        description="Advanced mutating command: add or update explicit accepted-work roadmap items.",
    )
    roadmap_mode = roadmap.add_mutually_exclusive_group(required=True)
    roadmap_mode.add_argument("--dry-run", action="store_true", help="Preview roadmap item changes without writing files.")
    roadmap_mode.add_argument("--apply", action="store_true", help="Write one bounded roadmap item change in an eligible live operating root.")
    roadmap.add_argument("--action", choices=("add", "update"), required=True, help="Roadmap mutation action.")
    roadmap.add_argument("--item-id", required=True, help="Stable roadmap item id to add or update.")
    roadmap.add_argument("--title", help="Roadmap item heading. Required for --action add.")
    roadmap.add_argument("--status", help="Roadmap item status.")
    roadmap.add_argument("--order", type=int, help="Roadmap item ordering value.")
    roadmap.add_argument("--execution-slice", dest="execution_slice", help="Advisory execution slice id for this roadmap item.")
    roadmap.add_argument("--slice-goal", dest="slice_goal", help="One-line advisory goal for the roadmap execution slice.")
    roadmap.add_argument("--slice-member", dest="slice_members", action="append", default=[], help="Roadmap item id covered by the same advisory execution slice. May be repeated.")
    roadmap.add_argument("--slice-dependency", dest="slice_dependencies", action="append", default=[], help="Roadmap item id that the advisory execution slice depends on. May be repeated.")
    roadmap.add_argument("--slice-closeout-boundary", dest="slice_closeout_boundary", help="One-line advisory closeout boundary for the execution slice.")
    roadmap.add_argument("--source-incubation", dest="source_incubation", help="Root-relative source incubation route.")
    roadmap.add_argument("--source-research", dest="source_research", help="Root-relative source research route.")
    roadmap.add_argument("--related-spec", dest="related_specs", action="append", default=[], help="Root-relative related spec route. May be repeated.")
    roadmap.add_argument("--related-plan", dest="related_plan", help="Root-relative active or archived plan route.")
    roadmap.add_argument("--archived-plan", dest="archived_plan", help="Root-relative archived plan route.")
    roadmap.add_argument("--target-artifact", dest="target_artifacts", action="append", default=[], help="Root-relative expected implementation target artifact. May be repeated.")
    roadmap.add_argument("--verification-summary", dest="verification_summary", help="One-line verification summary.")
    roadmap.add_argument("--docs-decision", dest="docs_decision", help="Docs decision: updated, not-needed, or uncertain.")
    roadmap.add_argument("--carry-forward", dest="carry_forward", help="One-line carry-forward summary.")
    roadmap.add_argument("--dependency", dest="dependencies", action="append", default=[], help="Existing roadmap item id dependency. May be repeated.")
    roadmap.add_argument("--supersedes", dest="supersedes", action="append", default=[], help="Existing roadmap item id superseded by this item. May be repeated.")
    roadmap.add_argument("--superseded-by", dest="superseded_by", action="append", default=[], help="Existing roadmap item id that supersedes this item. May be repeated.")
    meta_feedback = subparsers.add_parser(
        "meta-feedback",
        help=argparse.SUPPRESS,
        description="Advanced mutating command: collect MLH-Fix-Candidate meta-feedback into incubation and accepted roadmap placement.",
    )
    meta_feedback_mode = meta_feedback.add_mutually_exclusive_group(required=True)
    meta_feedback_mode.add_argument("--dry-run", action="store_true", help="Preview meta-feedback intake without writing files.")
    meta_feedback_mode.add_argument("--apply", action="store_true", help="Write one fix-candidate incubation note and accepted roadmap placement.")
    meta_feedback.add_argument(
        "--to-root",
        dest="to_root",
        help=(
            "Destination central MyLittleHarness-dev live operating root for the canonical incubation note and "
            f"accepted roadmap placement. Defaults to ${META_FEEDBACK_ROOT_ENV_VAR} when set, otherwise --root."
        ),
    )
    meta_feedback.add_argument("--from-root", dest="from_root", help="Observed source root where the rough edge was noticed. Defaults to --root.")
    meta_feedback.add_argument("--topic", required=True, help="Plain topic used for the incubation note and dedupe key.")
    meta_feedback_note = meta_feedback.add_mutually_exclusive_group(required=True)
    meta_feedback_note.add_argument("--note", help="Explicit meta-feedback note text to record.")
    meta_feedback_note.add_argument("--note-file", dest="note_file", help="Read explicit meta-feedback note text from a UTF-8 file; use - for stdin.")
    meta_feedback.add_argument("--signal-type", dest="signal_type", help="Optional signal type, such as lifecycle-drift or reviewability-gap.")
    meta_feedback.add_argument("--severity", help="Optional severity label for placement context.")
    meta_feedback.add_argument("--roadmap-item", dest="roadmap_item", help="Optional explicit roadmap item id; defaults to the topic slug.")
    meta_feedback.add_argument("--dedupe-to", dest="dedupe_to", help="Append this observation to an existing canonical cluster id instead of the topic slug.")
    meta_feedback.add_argument("--order", type=int, help="Optional accepted roadmap order; defaults after the current largest roadmap order.")
    mirror = subparsers.add_parser(
        "mirror",
        help=argparse.SUPPRESS,
        description="Advanced mutating command: preview or apply declared scoped product-to-demo file mirrors.",
    )
    mirror_mode = mirror.add_mutually_exclusive_group(required=True)
    mirror_mode.add_argument("--dry-run", action="store_true", help="Preview declared root-relative file mirrors without writing files.")
    mirror_mode.add_argument("--apply", action="store_true", help="Copy only declared root-relative files into the explicit target root.")
    mirror.add_argument("--target-root", dest="target_root", required=True, help="Explicit demo/product mirror target root.")
    mirror.add_argument("--path", dest="paths", action="append", required=True, help="Root-relative file path to mirror. May be repeated.")
    mirror.add_argument(
        "--allow-product-target",
        action="store_true",
        help="Allow a target root that identifies as product_source_root after explicit external review.",
    )
    preflight = subparsers.add_parser(
        "preflight",
        help=argparse.SUPPRESS,
        description="Advanced diagnostic: run optional preflight warnings or print an opt-in warning hook template.",
    )
    preflight.add_argument(
        "--template",
        choices=("git-pre-commit",),
        help="Print a warning-only local Git pre-commit hook template to stdout without installing it.",
    )
    tasks = subparsers.add_parser(
        "tasks",
        help=argparse.SUPPRESS,
        description="Advanced compatibility diagnostic: inspect operator task groups without writing files.",
    )
    tasks_mode = tasks.add_mutually_exclusive_group(required=True)
    tasks_mode.add_argument("--inspect", action="store_true", help="Inspect read-only operator task groups, compatibility posture, boundaries, and gated future lanes.")
    bootstrap = subparsers.add_parser(
        "bootstrap",
        help=argparse.SUPPRESS,
        description="Advanced compatibility diagnostic: inspect bootstrap, publishing, package, and workstation readiness without writing files.",
    )
    bootstrap_mode = bootstrap.add_mutually_exclusive_group(required=True)
    bootstrap_mode.add_argument("--inspect", action="store_true", help="Inspect read-only bootstrap readiness lanes and deferred mutation boundaries.")
    bootstrap_mode.add_argument("--package-smoke", action="store_true", help="Run local package install/import/console-script smoke verification in temporary locations.")
    semantic = subparsers.add_parser(
        "semantic",
        help=argparse.SUPPRESS,
        description="Advanced diagnostic: inspect or evaluate semantic retrieval readiness without writing files.",
    )
    semantic_mode = semantic.add_mutually_exclusive_group(required=True)
    semantic_mode.add_argument("--inspect", action="store_true", help="Inspect semantic readiness, search base posture, runtime deferral, and boundaries.")
    semantic_mode.add_argument("--evaluate", action="store_true", help="Run a fixed read-only semantic evaluation over the source-verified SQLite FTS/BM25 index.")
    intelligence = subparsers.add_parser(
        "intelligence",
        help=argparse.SUPPRESS,
        description="Advanced diagnostic: report repo intelligence over inventory-discovered surfaces and refresh disposable navigation cache when path/full-text search needs it.",
    )
    intelligence.add_argument("--query", help="Unified recovery query expanded into omitted exact, path, and full-text search modes.")
    intelligence.add_argument("--search", help="Case-sensitive literal text to search in inventory-discovered surface contents.")
    intelligence.add_argument("--path", help="Case-sensitive path fragment to search in inventory-discovered paths and references.")
    intelligence.add_argument("--full-text", help="Optional SQLite FTS/BM25 query over a current source-verified projection index.")
    intelligence.add_argument("--limit", type=_positive_int, default=10, help="Maximum full-text results to show. Defaults to 10.")
    intelligence.add_argument("--focus", choices=("search", "warnings", "projection", "routes"), help="Render a focused intelligence report while keeping the command read-only.")
    projection = subparsers.add_parser(
        "projection",
        help=argparse.SUPPRESS,
        description="Advanced diagnostic: build, inspect, delete, or rebuild disposable projection artifacts.",
    )
    projection_mode = projection.add_mutually_exclusive_group(required=True)
    projection_mode.add_argument("--build", action="store_true", help="Write rebuildable projection JSON artifacts inside the owned boundary.")
    projection_mode.add_argument("--inspect", action="store_true", help="Inspect generated projection artifacts without writing files.")
    projection_mode.add_argument("--delete", action="store_true", help="Delete only generated projection artifacts inside the owned boundary.")
    projection_mode.add_argument("--rebuild", action="store_true", help="Delete and rebuild generated projection artifacts inside the owned boundary.")
    projection.add_argument("--target", choices=("artifacts", "index", "all"), default="artifacts", help="Generated projection target to manage. Defaults to artifacts.")
    snapshot = subparsers.add_parser(
        "snapshot",
        help=argparse.SUPPRESS,
        description="Advanced diagnostic: inspect repair snapshots without writing files.",
    )
    snapshot_mode = snapshot.add_mutually_exclusive_group(required=True)
    snapshot_mode.add_argument("--inspect", action="store_true", help="Inspect repair snapshot metadata, copied files, hashes, and rollback posture.")
    adapter = subparsers.add_parser(
        "adapter",
        help=argparse.SUPPRESS,
        description="Advanced diagnostic: inspect or serve optional adapter projections without writing files.",
    )
    adapter_mode = adapter.add_mutually_exclusive_group(required=True)
    adapter_mode.add_argument("--inspect", action="store_true", help="Inspect the selected adapter projection without installing or running an adapter.")
    adapter_mode.add_argument("--serve", action="store_true", help="Serve the selected adapter projection as a foreground MCP stdio JSON-RPC server.")
    adapter_mode.add_argument("--client-config", action="store_true", help="Print no-write MCP client configuration for the selected adapter projection.")
    adapter.add_argument(
        "--target",
        choices=(MCP_READ_PROJECTION_TARGET,),
        default=MCP_READ_PROJECTION_TARGET,
        help="Adapter projection target to inspect. Defaults to mcp-read-projection.",
    )
    adapter.add_argument("--transport", choices=("stdio",), help="Adapter serving transport. Required with --serve; only stdio is supported.")
    attach = subparsers.add_parser(
        "attach",
        help=argparse.SUPPRESS,
        description="Compatibility command: preview or apply workflow scaffold attachment.",
    )
    attach_mode = attach.add_mutually_exclusive_group(required=True)
    attach_mode.add_argument("--dry-run", action="store_true", help="Report the attach proposal without writing files.")
    attach_mode.add_argument("--apply", action="store_true", help="Create only allowed missing scaffold/template paths.")
    attach.add_argument("--project", help="Project name to use when creating project/project-state.md.")
    hidden_top_level = {
        "tasks",
        "bootstrap",
        "preflight",
        "semantic",
        "intelligence",
        "suggest",
        "manifest",
        "intake",
        "incubate",
        "plan",
        "writeback",
        "transition",
        "memory-hygiene",
        "roadmap",
        "meta-feedback",
        "mirror",
        "projection",
        "snapshot",
        "adapter",
        "attach",
    }
    subparsers._choices_actions = [action for action in subparsers._choices_actions if action.dest not in hidden_top_level]
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "adapter":
        if not args.serve and args.transport is not None:
            parser.error("--transport is only valid with adapter --serve")
        if args.serve and args.transport != "stdio":
            parser.error("adapter --serve requires --transport stdio")
    root = Path(args.root).expanduser()
    try:
        inventory = load_for_root(root)
    except RootLoadError as exc:
        emit_text(f"mylittleharness: {exc}", stream=sys.stderr)
        return 2

    command = args.command
    if command == "suggest":
        suggestions = command_intent_registry() if args.list else command_suggestions_for_intent(args.intent, args.limit)
        sections = [
            ("Command Suggestions", command_suggestion_findings(suggestions, intent=args.intent, list_all=args.list)),
            ("Boundary", command_suggestion_boundary_findings()),
        ]
        findings = flatten_sections(sections)
        result = _result_for(findings)
        report_name = "suggest --list" if args.list else "suggest --intent"
        report_suggestions = _suggestions(command, findings)
        if args.json:
            emit_text(
                _render_suggest_json_report(
                    report_name,
                    inventory.root,
                    result,
                    inventory.sources_for_report(),
                    findings,
                    report_suggestions,
                    sections,
                    suggestions,
                    args.intent,
                    args.list,
                )
            )
        else:
            emit_text(render_sectioned_report(report_name, inventory.root, result, inventory.sources_for_report(), sections, report_suggestions))
        return 0
    if command == "manifest":
        route_findings = _route_manifest_findings()
        role_findings = _agent_role_manifest_findings()
        findings = [*route_findings, *role_findings]
        result = _result_for(findings)
        report_name = "manifest --inspect"
        sections = [("Route Manifest", route_findings), ("Role Profiles", role_findings)]
        suggestions = _suggestions(command, findings)
        manifest_rows = route_manifest()
        role_rows = role_manifest()
        if args.json:
            emit_text(
                _render_manifest_json_report(
                    report_name,
                    inventory.root,
                    result,
                    inventory.sources_for_report(),
                    findings,
                    suggestions,
                    sections,
                    manifest_rows,
                    role_rows,
                )
            )
        else:
            emit_text(render_sectioned_report(report_name, inventory.root, result, inventory.sources_for_report(), sections, suggestions))
        return 0
    if command == "check":
        report_name, sections = _check_report(args, inventory)
        findings = flatten_sections(sections)
        result = _result_for(findings)
        suggestions = _suggestions(command, findings)
        if args.json:
            emit_text(render_json_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, suggestions, sections, route_manifest()))
        else:
            emit_text(render_sectioned_report(report_name, inventory.root, result, inventory.sources_for_report(), sections, suggestions))
        return 1 if any(finding.severity == "error" for finding in findings) else 0
    if command == "detach":
        report_name = "detach --dry-run"
        if args.apply:
            sections = detach_apply_sections(inventory)
            report_name = "detach --apply"
        else:
            sections = detach_dry_run_sections(inventory)
        findings = flatten_sections(sections)
        result = _result_for(findings)
        emit_text(render_sectioned_report(report_name, inventory.root, result, inventory.sources_for_report(), sections, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "status":
        findings = status_findings(inventory)
        result = _result_for(findings)
        emit_text(render_report("status", inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 0
    if command == "validate":
        findings = validation_findings(inventory)
        result = _result_for(findings)
        emit_text(render_report("validate", inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 1 if any(finding.severity == "error" for finding in findings) else 0
    if command == "context-budget":
        findings = context_budget_findings(inventory)
        result = _result_for(findings)
        emit_text(render_report("context-budget", inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 0
    if command == "audit-links":
        findings = audit_link_findings(inventory)
        result = _result_for(findings)
        emit_text(render_report("audit-links", inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 0
    if command == "doctor":
        findings = doctor_findings(inventory.root, inventory)
        result = _result_for(findings)
        emit_text(render_report("doctor", inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 0
    if command == "preflight":
        if args.template == "git-pre-commit":
            emit_text(render_git_pre_commit_template(inventory.root))
            return 0
        sections = preflight_sections(inventory)
        findings = flatten_sections(sections)
        result = _result_for(findings)
        emit_text(render_sectioned_report("preflight", inventory.root, result, inventory.sources_for_report(), sections, _suggestions(command, findings)))
        return 0
    if command == "tasks":
        sections = tasks_sections(inventory)
        findings = flatten_sections(sections)
        result = _result_for(findings)
        emit_text(render_sectioned_report("tasks --inspect", inventory.root, result, inventory.sources_for_report(), sections, _suggestions(command, findings)))
        return 0
    if command == "bootstrap":
        if args.package_smoke:
            sections = package_smoke_sections(inventory)
            report_name = "bootstrap --package-smoke"
        else:
            sections = bootstrap_sections(inventory)
            report_name = "bootstrap --inspect"
        findings = flatten_sections(sections)
        result = _result_for(findings)
        emit_text(render_sectioned_report(report_name, inventory.root, result, inventory.sources_for_report(), sections, _suggestions(command, findings)))
        return 1 if args.package_smoke and result == "error" else 0
    if command == "semantic":
        if args.evaluate:
            sections = semantic_evaluate_sections(inventory)
            report_name = "semantic --evaluate"
        else:
            sections = semantic_inspect_sections(inventory)
            report_name = "semantic --inspect"
        findings = flatten_sections(sections)
        result = _result_for(findings)
        emit_text(render_sectioned_report(report_name, inventory.root, result, inventory.sources_for_report(), sections, _suggestions(command, findings)))
        return 0
    if command == "intelligence":
        sections = (
            intelligence_route_sections(inventory)
            if args.focus == "routes"
            else intelligence_sections(inventory, args.search, args.path, args.full_text, args.limit, args.query)
        )
        findings = flatten_sections(sections)
        result = _result_for(findings)
        display_sections = _focused_intelligence_sections(sections, args.focus)
        emit_text(
            render_intelligence_report(
                inventory.root,
                result,
                inventory.sources_for_report(),
                display_sections,
                _suggestions(command, findings),
                compact_sources=args.focus is not None,
            )
        )
        return 0
    if command == "evidence":
        if args.record and not (args.dry_run or args.apply):
            parser.error("evidence --record requires --dry-run or --apply")
        if (args.dry_run or args.apply) and not args.record:
            parser.error("evidence --dry-run/--apply are only valid with --record")
        if args.record:
            request = make_agent_run_record_request(args)
            report_name = "evidence --record --apply" if args.apply else "evidence --record --dry-run"
            findings = agent_run_record_apply_findings(inventory, request) if args.apply else agent_run_record_dry_run_findings(inventory, request)
            findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
            result = _result_for(findings)
            emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
            return 2 if args.apply and result == "error" else 0
        findings = evidence_findings(inventory)
        result = _result_for(findings)
        emit_text(render_report("evidence", inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 0
    if command == "closeout":
        sections = closeout_sections(inventory)
        findings = flatten_sections(sections)
        result = _result_for(findings)
        emit_text(render_sectioned_report("closeout", inventory.root, result, inventory.sources_for_report(), sections, _suggestions(command, findings)))
        return 0
    if command == "intake":
        intake_text = args.text
        intake_source = "--text"
        if args.text_file is not None:
            text_result = _read_text_argument("--text-file", args.text_file)
            if text_result[1]:
                emit_text(f"mylittleharness: {text_result[1]}", stream=sys.stderr)
                return 2
            intake_text = text_result[0]
            intake_source = f"--text-file {args.text_file}"
        request = make_intake_request(intake_text, intake_source, args.title, args.target)
        report_name = "intake --apply" if args.apply else "intake --dry-run"
        findings = intake_apply_findings(inventory, request) if args.apply else intake_dry_run_findings(inventory, request)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "writeback":
        request = make_writeback_request(
            archive_active_plan=args.archive_active_plan,
            compact_only=args.compact_only,
            allow_auto_compaction=args.allow_auto_compaction,
            from_active_plan=args.from_active_plan,
            roadmap_item=args.roadmap_item,
            roadmap_status=args.roadmap_status,
            archived_plan=args.archived_plan,
            worktree_start_state=args.worktree_start_state,
            task_scope=args.task_scope,
            docs_decision=args.docs_decision,
            state_writeback=args.state_writeback,
            verification=args.verification,
            commit_decision=args.commit_decision,
            residual_risk=args.residual_risk,
            carry_forward=args.carry_forward,
            work_result=args.work_result,
            active_phase=args.active_phase,
            phase_status=args.phase_status,
            last_archived_plan=args.last_archived_plan,
            product_source_root=args.product_source_root,
        )
        report_name = "writeback --apply" if args.apply else "writeback --dry-run"
        if args.compact_only:
            report_name += " --compact-only"
        if args.allow_auto_compaction:
            report_name += " --allow-auto-compaction"
        findings = writeback_apply_findings(inventory, request) if args.apply else writeback_dry_run_findings(inventory, request)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "transition":
        report_name = "transition --apply" if args.apply else "transition --dry-run"
        if args.allow_auto_compaction:
            report_name += " --allow-auto-compaction"
        findings = _transition_apply_findings(inventory, args) if args.apply else _transition_dry_run_findings(inventory, args)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "plan":
        request = make_plan_request(args.title, args.objective, args.task, args.update_active, args.roadmap_item, args.only_requested_item)
        report_name = "plan --apply" if args.apply else "plan --dry-run"
        findings = plan_apply_findings(inventory, request) if args.apply else plan_dry_run_findings(inventory, request)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "memory-hygiene":
        request = make_memory_hygiene_request(
            args.source,
            args.promoted_to,
            args.status,
            args.archive_to,
            args.repair_links,
            args.scan,
            args.archive_covered,
            tuple(args.entry_coverage),
        )
        report_name = "memory-hygiene --apply" if args.apply else "memory-hygiene --dry-run"
        findings = memory_hygiene_apply_findings(inventory, request) if args.apply else memory_hygiene_dry_run_findings(inventory, request)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "roadmap":
        request = make_roadmap_request(
            action=args.action,
            item_id=args.item_id,
            title=args.title,
            status=args.status,
            order=args.order,
            execution_slice=args.execution_slice,
            slice_goal=args.slice_goal,
            slice_members=args.slice_members,
            slice_dependencies=args.slice_dependencies,
            slice_closeout_boundary=args.slice_closeout_boundary,
            source_incubation=args.source_incubation,
            source_research=args.source_research,
            related_specs=args.related_specs,
            related_plan=args.related_plan,
            archived_plan=args.archived_plan,
            target_artifacts=args.target_artifacts,
            verification_summary=args.verification_summary,
            docs_decision=args.docs_decision,
            carry_forward=args.carry_forward,
            dependencies=args.dependencies,
            supersedes=args.supersedes,
            superseded_by=args.superseded_by,
        )
        report_name = "roadmap --apply" if args.apply else "roadmap --dry-run"
        findings = roadmap_apply_findings(inventory, request) if args.apply else roadmap_dry_run_findings(inventory, request)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "meta-feedback":
        note_text = args.note
        note_source = "--note"
        if args.note_file is not None:
            note_result = _read_text_argument("--note-file", args.note_file)
            if note_result[1]:
                emit_text(f"mylittleharness: {note_result[1]}", stream=sys.stderr)
                return 2
            note_text = note_result[0]
            note_source = f"--note-file {args.note_file}"
        destination_inventory = inventory
        destination_root = args.to_root or os.environ.get(META_FEEDBACK_ROOT_ENV_VAR)
        if destination_root:
            try:
                destination_inventory = load_for_root(Path(destination_root).expanduser())
            except RootLoadError as exc:
                emit_text(f"mylittleharness: {exc}", stream=sys.stderr)
                return 2
        request = make_meta_feedback_request(
            topic=args.topic,
            note=note_text,
            note_source=note_source,
            from_root=args.from_root or str(inventory.root),
            signal_type=args.signal_type,
            severity=args.severity,
            roadmap_item=args.roadmap_item,
            order=args.order,
            dedupe_to=args.dedupe_to,
        )
        report_name = "meta-feedback --apply" if args.apply else "meta-feedback --dry-run"
        lifecycle_before = _lifecycle_posture(destination_inventory) if args.apply else None
        findings = (
            meta_feedback_apply_findings(destination_inventory, request)
            if args.apply
            else meta_feedback_dry_run_findings(destination_inventory, request)
        )
        findings = _with_projection_cache_dirty_findings(command, args, destination_inventory, findings)
        if lifecycle_before and not any(finding.severity == "error" for finding in findings):
            lifecycle_after = _lifecycle_posture(load_for_root(destination_inventory.root))
            findings.extend(_meta_feedback_lifecycle_posture_findings(lifecycle_before, lifecycle_after))
        result = _result_for(findings)
        emit_text(
            render_report(
                report_name,
                destination_inventory.root,
                result,
                destination_inventory.sources_for_report(),
                findings,
                _suggestions(command, findings),
            )
        )
        return 2 if args.apply and result == "error" else 0
    if command == "mirror":
        request = make_mirror_request(args.target_root, args.paths, allow_product_target=args.allow_product_target)
        report_name = "mirror --apply" if args.apply else "mirror --dry-run"
        findings = mirror_apply_findings(inventory, request) if args.apply else mirror_dry_run_findings(inventory, request)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "incubate":
        note_text = args.note
        note_source = "--note"
        if args.note_file is not None:
            note_result = _read_text_argument("--note-file", args.note_file)
            if note_result[1]:
                emit_text(f"mylittleharness: {note_result[1]}", stream=sys.stderr)
                return 2
            note_text = note_result[0]
            note_source = f"--note-file {args.note_file}"
        request = make_incubate_request(args.topic, note_text, note_source, fix_candidate=args.fix_candidate)
        report_name = "incubate --apply" if args.apply else "incubate --dry-run"
        findings = incubate_apply_findings(inventory, request) if args.apply else incubate_dry_run_findings(inventory, request)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "projection":
        report_name = f"projection --inspect --target {args.target}"
        if args.build:
            findings = _projection_target_findings(args.target, build_projection_artifacts, build_projection_index, inventory)
            report_name = f"projection --build --target {args.target}"
        elif args.delete:
            findings = _projection_target_findings(args.target, delete_projection_artifacts, delete_projection_index, inventory)
            report_name = f"projection --delete --target {args.target}"
        elif args.rebuild:
            findings = _projection_target_findings(args.target, rebuild_projection_artifacts, rebuild_projection_index, inventory)
            report_name = f"projection --rebuild --target {args.target}"
        else:
            findings = _projection_target_findings(args.target, inspect_projection_artifacts, inspect_projection_index, inventory)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if any(finding.severity == "error" for finding in findings) else 0
    if command == "snapshot":
        findings = snapshot_inspect_findings(inventory)
        result = _result_for(findings)
        emit_text(render_report("snapshot --inspect", inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 0
    if command == "adapter":
        if args.serve:
            return serve_mcp_read_projection(inventory, sys.stdin, sys.stdout)
        if args.client_config:
            emit_text(json.dumps(mcp_read_projection_client_config(inventory), sort_keys=True, indent=2, ensure_ascii=True))
            return 0
        sections = mcp_read_projection_sections(inventory)
        findings = flatten_sections(sections)
        result = _result_for(findings)
        emit_text(render_sectioned_report(f"adapter --inspect --target {args.target}", inventory.root, result, inventory.sources_for_report(), sections, _suggestions(command, findings)))
        return 0
    if command in {"init", "attach"}:
        report_name = f"{command} --dry-run"
        if args.apply:
            findings = attach_apply_findings(inventory, args.project)
            report_name = f"{command} --apply"
        else:
            findings = attach_dry_run_findings(inventory, args.project)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "repair":
        report_name = "repair --dry-run"
        if args.apply:
            findings = repair_apply_findings(inventory)
            report_name = "repair --apply"
        else:
            findings = repair_dry_run_findings(inventory)
        findings = _with_projection_cache_dirty_findings(command, args, inventory, findings)
        result = _result_for(findings)
        emit_text(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        if args.apply:
            return _repair_apply_exit_code(findings)
        return 0
    parser.error(f"unknown command: {command}")
    return 2


def _transition_dry_run_findings(inventory, args) -> list[Finding]:
    review_payload = _transition_review_payload(inventory, args)
    token = _transition_review_token_from_payload(review_payload)
    next_plan_resolution = _transition_next_plan_resolution(inventory, args)
    phase_completion_inventory = inventory
    phase_completion_preview_ok = True
    findings = [
        Finding("info", "transition-dry-run", "transition proposal only; no files were written"),
        Finding(
            "info",
            "transition-boundary",
            "transition composes explicit writeback and plan rails; dry-run output cannot approve closeout, archive, next-plan opening, stage, commit, rollback, or future mutations",
        ),
        Finding("info", "transition-review-token", f"review token: {token}"),
        Finding("info", "transition-targets", f"target files: {', '.join(_transition_target_rels(inventory, args)) or 'none'}"),
    ]
    findings.extend(_transition_review_token_input_findings(review_payload))
    errors = _transition_input_errors(inventory, args, next_plan_resolution.request, apply=False)
    if errors:
        findings.extend(_with_severity(errors, "warn"))
        findings.append(Finding("info", "transition-validation-posture", "dry-run refused before apply; fix refusal reasons and rerun transition --dry-run"))
        return findings
    if args.complete_current_phase:
        findings.append(Finding("info", "transition-step", "would complete current phase through writeback --phase-status complete", "project/project-state.md"))
        phase_findings = writeback_dry_run_findings(
            inventory,
            make_writeback_request(phase_status="complete", allow_auto_compaction=args.allow_auto_compaction),
        )
        findings.extend(phase_findings)
        phase_completion_preview_ok = not any(finding.severity in {"warn", "error"} for finding in phase_findings)
        if phase_completion_preview_ok:
            phase_completion_inventory = _transition_phase_complete_preview_inventory(inventory)
    if args.archive_active_plan:
        findings.append(
            Finding(
                "info",
                "transition-step",
                f"would archive active plan through writeback --archive-active-plan with current roadmap status {_transition_current_roadmap_status(args)!r}",
                "project/implementation-plan.md",
            )
        )
        if args.complete_current_phase and _state_phase_status(inventory) != "complete":
            if phase_completion_preview_ok:
                findings.append(
                    Finding(
                        "info",
                        "transition-sequenced-preview",
                        "archive preview uses the projected phase-complete state, then reports archive-active-plan route writes without writing files",
                        "project/project-state.md",
                    )
                )
                findings.extend(writeback_dry_run_findings(phase_completion_inventory, _transition_archive_request(phase_completion_inventory, args)))
            else:
                findings.append(
                    Finding(
                        "info",
                        "transition-sequenced-preview",
                        "archive preview is sequenced after phase completion; phase-completion preview has warnings or errors, so detailed archive route-write evidence is deferred",
                        "project/project-state.md",
                    )
                )
        else:
            findings.extend(writeback_dry_run_findings(inventory, _transition_archive_request(inventory, args)))
    if args.next_roadmap_item:
        findings.append(Finding("info", "transition-step", f"would open next active plan for roadmap item {args.next_roadmap_item!r}", "project/implementation-plan.md"))
        findings.extend(_transition_next_plan_input_findings(next_plan_resolution, apply=False))
        if args.archive_active_plan and _state_plan_status(inventory) == "active":
            findings.append(
                Finding(
                    "info",
                    "transition-sequenced-preview",
                    "next-plan preview is sequenced after archive-active-plan clears the active lifecycle pointer",
                    "project/implementation-plan.md",
                )
            )
        else:
            findings.extend(plan_dry_run_findings(inventory, _transition_next_plan_request(args)))
        findings.append(Finding("info", "transition-step", f"would mark next roadmap item {args.next_roadmap_item!r} active", "project/roadmap.md"))
        findings.extend(roadmap_dry_run_findings(inventory, _transition_next_roadmap_status_request(args)))
    findings.append(Finding("info", "transition-validation-posture", "apply requires the same flags plus --review-token; token mismatch refuses before writes"))
    return findings


def _transition_apply_findings(inventory, args) -> list[Finding]:
    review_payload = _transition_review_payload(inventory, args)
    token = _transition_review_token_from_payload(review_payload)
    next_plan_resolution = _transition_next_plan_resolution(inventory, args)
    errors = _transition_input_errors(inventory, args, next_plan_resolution.request, apply=True)
    if args.review_token and args.review_token != token:
        errors.append(
            Finding(
                "error",
                "transition-review-token-mismatch",
                (
                    "--review-token does not match current repo-visible inputs; "
                    f"expected {token}; current input digests: {_transition_review_input_digest_summary(review_payload)}"
                ),
            )
        )
        errors.extend(_transition_review_token_input_findings(review_payload, current=True))
    if errors:
        return errors

    findings = [
        Finding("info", "transition-apply", "transition apply started"),
        Finding("info", "transition-review-token", f"accepted review token: {token}"),
        Finding("info", "transition-targets", f"target files: {', '.join(_transition_target_rels(inventory, args)) or 'none'}"),
        Finding("info", "transition-no-vcs", "transition does not stage, commit, push, or mutate Git state"),
    ]
    current = inventory
    if args.complete_current_phase:
        findings.append(Finding("info", "transition-step", "completing current phase through writeback --phase-status complete", "project/project-state.md"))
        step_findings = writeback_apply_findings(current, make_writeback_request(phase_status="complete", allow_auto_compaction=args.allow_auto_compaction))
        findings.extend(step_findings)
        if any(finding.severity == "error" for finding in step_findings):
            return findings
        current, reload_findings = _reload_transition_inventory(current)
        findings.extend(reload_findings)
        if reload_findings:
            return findings
    if args.archive_active_plan:
        findings.append(
            Finding(
                "info",
                "transition-step",
                f"archiving active plan through writeback --archive-active-plan with current roadmap status {_transition_current_roadmap_status(args)!r}",
                "project/implementation-plan.md",
            )
        )
        step_findings = writeback_apply_findings(current, _transition_archive_request(current, args))
        findings.extend(step_findings)
        if any(finding.severity == "error" for finding in step_findings):
            return findings
        current, reload_findings = _reload_transition_inventory(current)
        findings.extend(reload_findings)
        if reload_findings:
            return findings
    if args.next_roadmap_item:
        findings.append(Finding("info", "transition-step", f"opening next active plan for roadmap item {args.next_roadmap_item!r}", "project/implementation-plan.md"))
        current_next_plan_resolution = _transition_next_plan_resolution(current, args)
        findings.extend(_transition_next_plan_input_findings(current_next_plan_resolution, apply=True))
        step_findings = plan_apply_findings(current, _transition_next_plan_request(args))
        findings.extend(step_findings)
        if any(finding.severity == "error" for finding in step_findings):
            return findings
        current, reload_findings = _reload_transition_inventory(current)
        findings.extend(reload_findings)
        if reload_findings:
            return findings
        findings.append(Finding("info", "transition-step", f"marking next roadmap item {args.next_roadmap_item!r} active", "project/roadmap.md"))
        step_findings = roadmap_apply_findings(current, _transition_next_roadmap_status_request(args))
        findings.extend(step_findings)
        if any(finding.severity == "error" for finding in step_findings):
            return findings
    findings.append(
        Finding(
            "info",
            "transition-authority",
            "repo-visible project-state, archived plan, active plan, and roadmap files remain the only transition authority",
            "project/project-state.md",
        )
    )
    return findings


def _transition_input_errors(inventory, args, next_plan_request, apply: bool) -> list[Finding]:
    errors: list[Finding] = []
    if not (args.complete_current_phase or args.archive_active_plan or args.next_roadmap_item):
        errors.append(Finding("error", "transition-refused", "transition requires at least one explicit action flag"))
    if apply and not args.review_token:
        errors.append(Finding("error", "transition-refused", "transition --apply requires --review-token from a matching dry-run"))
    if args.from_active_plan and not args.archive_active_plan:
        errors.append(Finding("error", "transition-refused", "--from-active-plan requires --archive-active-plan"))
    if args.current_roadmap_item and not args.archive_active_plan:
        errors.append(Finding("error", "transition-refused", "--current-roadmap-item requires --archive-active-plan"))
    current_roadmap_status = _transition_current_roadmap_status(args, default="")
    if current_roadmap_status and not args.archive_active_plan:
        errors.append(Finding("error", "transition-refused", "--current-roadmap-status requires --archive-active-plan"))
    if current_roadmap_status and not args.current_roadmap_item:
        errors.append(Finding("error", "transition-refused", "--current-roadmap-status requires --current-roadmap-item"))
    if current_roadmap_status in {"blocked", "superseded"} and args.complete_current_phase:
        errors.append(
            Finding(
                "error",
                "transition-refused",
                "--complete-current-phase cannot be combined with blocked or superseded current roadmap status",
            )
        )
    if args.only_requested_item and not args.next_roadmap_item:
        errors.append(Finding("error", "transition-refused", "--only-requested-item requires --next-roadmap-item"))
    if args.next_roadmap_item:
        if not next_plan_request.title:
            errors.append(Finding("error", "transition-refused", "--next-title is required when it cannot be derived from --next-roadmap-item"))
        if not next_plan_request.objective:
            errors.append(Finding("error", "transition-refused", "--next-objective is required when it cannot be derived from --next-roadmap-item"))
        if _state_plan_status(inventory) == "active" and not args.archive_active_plan:
            errors.append(Finding("error", "transition-refused", "--next-roadmap-item with an active plan requires --archive-active-plan"))
    return errors


def _transition_archive_request(inventory, args):
    return make_writeback_request(
        archive_active_plan=True,
        allow_auto_compaction=args.allow_auto_compaction,
        from_active_plan=args.from_active_plan,
        roadmap_item=args.current_roadmap_item,
        roadmap_status=_transition_current_roadmap_status(args, default=""),
        archive_retarget_skip_rels=_transition_next_source_incubation_rels(inventory, args),
        worktree_start_state=args.worktree_start_state,
        task_scope=args.task_scope,
        docs_decision=args.docs_decision,
        state_writeback=args.state_writeback,
        verification=args.verification,
        commit_decision=args.commit_decision,
        residual_risk=args.residual_risk,
        carry_forward=args.carry_forward,
    )


def _transition_current_roadmap_status(args, default: str = "done") -> str:
    return str(getattr(args, "current_roadmap_status", None) or default)


def _transition_next_source_incubation_rels(inventory, args) -> tuple[str, ...]:
    if not args.next_roadmap_item:
        return ()
    fields = roadmap_item_fields(inventory, args.next_roadmap_item)
    source = str(fields.get("source_incubation") or "").strip().replace("\\", "/")
    return (source,) if source else ()


def _transition_next_plan_resolution(inventory, args):
    return resolve_plan_request_from_roadmap(inventory, _transition_next_plan_request(args))


def _transition_next_plan_request(args):
    return make_plan_request(
        args.next_title,
        args.next_objective,
        args.next_task,
        False,
        args.next_roadmap_item,
        args.only_requested_item,
    )


def _transition_next_plan_input_findings(resolution, apply: bool) -> list[Finding]:
    if not resolution.derived_fields:
        return []
    prefix = "" if apply else "would "
    findings = [
        Finding(
            "info",
            "transition-next-plan-derived-input",
            f"{prefix}use roadmap-derived next-plan field(s): {', '.join(resolution.derived_fields)}",
            "project/implementation-plan.md",
        )
    ]
    if resolution.candidate_objective:
        findings.append(
            Finding(
                "info",
                "transition-next-plan-candidate-objective",
                f"candidate objective: {resolution.candidate_objective}",
                "project/implementation-plan.md",
            )
        )
    if resolution.candidate_task:
        findings.append(
            Finding(
                "info",
                "transition-next-plan-candidate-task",
                f"candidate task: {resolution.candidate_task}",
                "project/implementation-plan.md",
            )
        )
    return findings


def _transition_next_roadmap_status_request(args):
    return make_roadmap_request("update", args.next_roadmap_item, status="active")


def _transition_phase_complete_preview_inventory(inventory):
    state = inventory.state
    if state is None or not state.exists:
        return inventory
    state_text = _transition_frontmatter_text_with_scalars(state.content, {"phase_status": "complete"})
    if state_text == state.content:
        return inventory
    state_surface = _transition_surface_with_content(state, state_text)
    return _transition_inventory_with_surface(inventory, state_surface)


def _transition_surface_with_content(surface, content: str):
    if surface.path.suffix.lower() == ".md":
        frontmatter = parse_frontmatter(content)
        headings = extract_headings(content)
    else:
        frontmatter = surface.frontmatter
        headings = []
    return replace(
        surface,
        content=content,
        read_error=None,
        frontmatter=frontmatter,
        headings=headings,
        links=extract_path_refs(content),
    )


def _transition_inventory_with_surface(inventory, updated_surface):
    replaced = False
    surfaces = []
    for surface in inventory.surfaces:
        if surface.rel_path == updated_surface.rel_path:
            surfaces.append(updated_surface)
            replaced = True
        else:
            surfaces.append(surface)
    if not replaced:
        surfaces.append(updated_surface)
    surface_by_rel = dict(inventory.surface_by_rel)
    surface_by_rel[updated_surface.rel_path] = updated_surface
    state = updated_surface if inventory.state and inventory.state.rel_path == updated_surface.rel_path else inventory.state
    active_plan = (
        updated_surface
        if inventory.active_plan_surface and inventory.active_plan_surface.rel_path == updated_surface.rel_path
        else inventory.active_plan_surface
    )
    return replace(inventory, surfaces=surfaces, surface_by_rel=surface_by_rel, state=state, active_plan_surface=active_plan)


def _transition_frontmatter_text_with_scalars(text: str, updates: dict[str, str]) -> str:
    if not updates:
        return text
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text
    closing_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        return text
    for index in range(1, closing_index):
        match = re.match(r"^([A-Za-z0-9_-]+):(.*?)(\r?\n)?$", lines[index])
        if not match or match.group(1) not in updates:
            continue
        newline = match.group(3) or ("\n" if lines[index].endswith("\n") else "")
        lines[index] = f'{match.group(1)}: "{_transition_yaml_double_quoted_value(updates[match.group(1)])}"{newline}'
    return "".join(lines)


def _transition_yaml_double_quoted_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _reload_transition_inventory(inventory):
    try:
        return load_for_root(inventory.root), []
    except RootLoadError as exc:
        return inventory, [Finding("error", "transition-refused", f"could not reload root after transition step: {exc}")]


def _transition_review_token(inventory, args) -> str:
    return _transition_review_token_from_payload(_transition_review_payload(inventory, args))


def _transition_review_payload(inventory, args) -> dict[str, object]:
    next_plan_resolution = _transition_next_plan_resolution(inventory, args)
    next_plan_request = next_plan_resolution.request
    return {
        "actions": {
            "complete_current_phase": bool(args.complete_current_phase),
            "archive_active_plan": bool(args.archive_active_plan),
            "from_active_plan": bool(args.from_active_plan),
            "current_roadmap_item": args.current_roadmap_item or "",
            "current_roadmap_status": _transition_current_roadmap_status(args, default=""),
            "next_roadmap_item": args.next_roadmap_item or "",
            "next_title": next_plan_request.title if args.next_roadmap_item else args.next_title or "",
            "next_objective": next_plan_request.objective if args.next_roadmap_item else args.next_objective or "",
            "next_task": next_plan_request.task if args.next_roadmap_item else args.next_task or "",
            "next_derived_fields": list(next_plan_resolution.derived_fields),
            "only_requested_item": bool(args.only_requested_item),
            "allow_auto_compaction": bool(args.allow_auto_compaction),
        },
        "closeout": _transition_closeout_values(args),
        "files": _transition_file_digests(inventory),
    }


def _transition_review_token_from_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _transition_review_token_input_findings(payload: dict[str, object], current: bool = False) -> list[Finding]:
    prefix = "current " if current else ""
    compare_hint = "; compare with the reviewed dry-run before rerunning apply" if current else ""
    findings = [
        Finding(
            "info",
            "transition-review-token-inputs",
            f"{prefix}review token input digests: {_transition_review_input_digest_summary(payload)}{compare_hint}",
            "project/project-state.md",
        )
    ]
    file_digests = payload.get("files")
    if isinstance(file_digests, dict):
        findings.append(
            Finding(
                "info",
                "transition-review-token-file-inputs",
                f"{prefix}review token file inputs: {_transition_review_file_digest_summary(file_digests)}",
                "project/project-state.md",
            )
        )
    return findings


def _transition_review_input_digest_summary(payload: dict[str, object]) -> str:
    return "; ".join(f"{key}={_transition_payload_digest(payload.get(key, {}))}" for key in ("actions", "closeout", "files"))


def _transition_review_file_digest_summary(file_digests: dict[object, object]) -> str:
    return "; ".join(f"{key}={str(value)[:12]}" for key, value in sorted(file_digests.items()))


def _transition_payload_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:12]


def _transition_closeout_values(args) -> dict[str, str]:
    values: dict[str, str] = {}
    for field in (
        "worktree_start_state",
        "task_scope",
        "docs_decision",
        "state_writeback",
        "verification",
        "commit_decision",
        "residual_risk",
        "carry_forward",
        "work_result",
    ):
        value = getattr(args, field, None)
        if value:
            values[field] = str(value)
    return values


def _transition_file_digests(inventory) -> dict[str, str]:
    digests: dict[str, str] = {}
    for rel in ("project/project-state.md", "project/implementation-plan.md", "project/roadmap.md"):
        path = inventory.root / rel
        if not path.exists():
            digests[rel] = "<missing>"
        elif not path.is_file():
            digests[rel] = "<not-file>"
        else:
            digests[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def _transition_target_rels(inventory, args) -> list[str]:
    targets: list[str] = []
    if args.complete_current_phase or args.archive_active_plan or args.next_roadmap_item:
        targets.append("project/project-state.md")
        targets.append("project/implementation-plan.md")
    if args.archive_active_plan:
        archive_rel = _transition_archive_target_rel(inventory)
        if archive_rel:
            targets.append(archive_rel)
    if args.current_roadmap_item or args.next_roadmap_item:
        targets.append("project/roadmap.md")
    return sorted(dict.fromkeys(targets))


def _transition_archive_target_rel(inventory) -> str:
    plan = inventory.active_plan_surface
    if not plan or not plan.exists:
        return ""
    title = ""
    if plan.frontmatter.has_frontmatter and not plan.frontmatter.errors:
        title = str(plan.frontmatter.data.get("title") or "")
    if not title:
        title = _transition_first_heading(plan.content) or "implementation-plan"
    slug = re.sub(r"[^A-Za-z0-9]+", "-", title.strip().lower()).strip("-") or "implementation-plan"
    from datetime import date

    return f"project/archive/plans/{date.today().isoformat()}-{slug}.md"


def _transition_first_heading(text: str) -> str | None:
    for line in text.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()
    return None


def _state_phase_status(inventory) -> str:
    data = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    return str(data.get("phase_status") or "")


def _state_plan_status(inventory) -> str:
    data = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    return str(data.get("plan_status") or "")


def _with_severity(findings: list[Finding], severity: str) -> list[Finding]:
    return [Finding(severity, finding.code, finding.message, finding.source, finding.line) for finding in findings]


def _result_for(findings) -> str:
    if any(finding.severity == "error" for finding in findings):
        return "error"
    if any(finding.severity == "warn" for finding in findings):
        return "warn"
    return "ok"


def _render_manifest_json_report(
    report_name: str,
    root: Path,
    result: str,
    sources: list[str],
    findings: list[Finding],
    suggestions: list[str],
    sections: list[tuple[str, list[Finding]]],
    route_rows: tuple[dict[str, object], ...],
    role_rows: tuple[dict[str, object], ...],
) -> str:
    payload = json.loads(render_json_report(report_name, root, result, sources, findings, suggestions, sections, route_rows))
    payload["role_manifest"] = list(role_rows)
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)


def _render_suggest_json_report(
    report_name: str,
    root: Path,
    result: str,
    sources: list[str],
    findings: list[Finding],
    suggestions: list[str],
    sections: list[tuple[str, list[Finding]]],
    command_suggestions: tuple[object, ...],
    intent: str | None,
    list_all: bool,
) -> str:
    payload = json.loads(render_json_report(report_name, root, result, sources, findings, suggestions, sections))
    payload["intent_query"] = intent
    payload["list_all"] = list_all
    payload["command_suggestions"] = command_suggestions_to_dict(command_suggestions)
    payload["boundary"]["suggestions_execute_commands"] = False
    payload["boundary"]["suggestions_approve_lifecycle"] = False
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)


def _route_manifest_findings() -> list[Finding]:
    findings: list[Finding] = []
    for row in route_manifest():
        route_id = str(row["route_id"])
        target = str(row["target"])
        findings.append(
            Finding(
                "info",
                "route-manifest-entry",
                (
                    f"{route_id}: target={target}; authority={row['authority']}; "
                    f"mutability={row['mutability']}; gate_class={row['gate_class']}"
                ),
                target,
                route_id=route_id,
            )
        )
    findings.append(
        Finding(
            "info",
            "route-manifest-boundary",
            "route manifest is advisory protocol data; repo-visible files and explicit apply rails remain authority",
            route_id="unclassified",
        )
    )
    return findings


def _agent_role_manifest_findings() -> list[Finding]:
    findings: list[Finding] = []
    for row in role_manifest():
        role_id = str(row["role_id"])
        permissions = list(row["permissions"])
        gate_classes = sorted({str(permission["gate_class"]) for permission in permissions if permission["human_gate"]["required"]})
        findings.append(
            Finding(
                "info",
                "agent-role-profile-entry",
                (
                    f"{role_id}: permissions={len(permissions)}; "
                    f"required_outputs={len(row['required_outputs'])}; "
                    f"human_gate_classes={gate_classes or ['none']}; "
                    f"apply_authority={row['apply_authority']}"
                ),
                route_id="unclassified",
            )
        )
    findings.append(
        Finding(
            "info",
            "agent-role-manifest-boundary",
            "role profiles are advisory protocol data; they do not grant direct lifecycle apply authority or spawn workers",
            route_id="unclassified",
        )
    )
    return findings


def _check_report(args: argparse.Namespace, inventory: object) -> tuple[str, list[tuple[str, list[Finding]]]]:
    boundary_section = [
        Finding("info", "check-read-only", "check diagnostics write no files, reports, caches, generated outputs, snapshots, Git state, hooks, package artifacts, adapter state, or workstation state"),
    ]
    if args.focus:
        focus_sections = {
            "validation": ("Validation", validation_findings(inventory)),
            "links": ("Links", audit_link_findings(inventory)),
            "context": ("Context", context_budget_findings(inventory)),
            "hygiene": ("Hygiene", doctor_findings(inventory.root, inventory)),
            "grain": ("Grain", grain_findings(inventory)),
        }
        section = focus_sections[args.focus]
        boundary_section.append(Finding("info", "check-focus-read-only", f"check --focus {args.focus} runs one compatibility diagnostic without writing files"))
        return f"check --focus {args.focus}", [section, ("Boundary", boundary_section)]

    sections = [
        ("Status", status_findings(inventory)),
        ("Validation", validation_findings(inventory)),
        ("Agent Run Evidence", agent_run_record_findings(inventory, "check-agent-run")),
        ("Projection Cache", projection_cache_status_findings(inventory)),
        ("Drift", check_drift_findings(inventory)),
    ]
    if args.deep:
        sections.extend(
            [
                ("Links", audit_link_findings(inventory)),
                ("Context", context_budget_findings(inventory)),
                ("Hygiene", doctor_findings(inventory.root, inventory)),
                ("Grain", grain_findings(inventory)),
            ]
        )
        boundary_section.append(Finding("info", "check-deep-read-only", "check --deep composes links, context, hygiene, and grain diagnostics without writing files"))
        return "check --deep", [*sections, ("Boundary", boundary_section)]

    boundary_section.append(Finding("info", "check-compatibility-diagnostics", "use check --deep or check --focus for consolidated links, context, and hygiene diagnostics; compatibility commands remain available"))
    return "check", [*sections, ("Boundary", boundary_section)]


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--limit must be an integer >= 1") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("--limit must be >= 1")
    return parsed


def _read_text_argument(flag: str, value: str) -> tuple[str | None, str | None]:
    if value == "-":
        return sys.stdin.read(), None
    path = Path(value).expanduser()
    try:
        return path.read_text(encoding="utf-8"), None
    except (OSError, UnicodeError) as exc:
        return None, f"{flag} could not be read as UTF-8 text: {exc}"


def _projection_target_findings(target: str, artifacts_fn, index_fn, inventory: object) -> list[Finding]:
    if target == "artifacts":
        return artifacts_fn(inventory)
    if target == "index":
        return index_fn(inventory)
    return artifacts_fn(inventory) + index_fn(inventory)


def _with_projection_cache_dirty_findings(command: str, args: object, inventory: object, findings: list[Finding]) -> list[Finding]:
    if command not in CACHE_DIRTY_APPLY_COMMANDS or not bool(getattr(args, "apply", False)):
        return findings
    if any(finding.severity == "error" for finding in findings):
        return findings
    changed_paths = _projection_cache_changed_paths(findings)
    return findings + mark_projection_cache_dirty(inventory, changed_paths, f"{command} --apply")


def _projection_cache_changed_paths(findings: list[Finding]) -> tuple[str, ...]:
    paths: set[str] = set()
    for finding in findings:
        if finding.source:
            paths.add(finding.source)
    return tuple(sorted(paths))


def _lifecycle_posture(inventory: object) -> LifecyclePosture:
    state = getattr(inventory, "state", None)
    state_data = getattr(getattr(state, "frontmatter", None), "data", {}) if state else {}
    plan_surface = getattr(inventory, "active_plan_surface", None)
    plan_exists = bool(plan_surface and getattr(plan_surface, "exists", False))
    plan_content = str(getattr(plan_surface, "content", "") or "") if plan_exists else ""
    return LifecyclePosture(
        plan_status=str(state_data.get("plan_status") or ""),
        active_plan=str(state_data.get("active_plan") or ""),
        active_phase=str(state_data.get("active_phase") or ""),
        phase_status=str(state_data.get("phase_status") or ""),
        active_plan_exists=plan_exists,
        active_plan_hash=_short_text_hash(plan_content) if plan_exists else "missing",
    )


def _short_text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _meta_feedback_lifecycle_posture_findings(before: LifecyclePosture, after: LifecyclePosture) -> list[Finding]:
    if before == after:
        return [
            Finding(
                "info",
                "meta-feedback-lifecycle-posture",
                (
                    "lifecycle posture preserved after meta-feedback apply: "
                    f"plan_status={after.plan_status or '<empty>'!r}; "
                    f"active_plan={after.active_plan or '<empty>'!r}; "
                    f"active_phase={after.active_phase or '<empty>'!r}; "
                    f"phase_status={after.phase_status or '<empty>'!r}; "
                    f"active_plan_exists={after.active_plan_exists}; "
                    f"active_plan_hash={after.active_plan_hash}; "
                    "next-plan opening remains explicit"
                ),
                "project/project-state.md",
            )
        ]
    return [
        Finding(
            "warn",
            "meta-feedback-lifecycle-drift",
            (
                "lifecycle posture changed during meta-feedback apply; "
                f"before=({_format_lifecycle_posture(before)}); "
                f"after=({_format_lifecycle_posture(after)}); "
                "meta-feedback did not request or approve lifecycle movement; run check and inspect repo-visible routes "
                "before closeout, archive, commit, or next-plan decisions"
            ),
            "project/project-state.md",
        )
    ]


def _format_lifecycle_posture(posture: LifecyclePosture) -> str:
    return (
        f"plan_status={posture.plan_status or '<empty>'!r}, "
        f"active_plan={posture.active_plan or '<empty>'!r}, "
        f"active_phase={posture.active_phase or '<empty>'!r}, "
        f"phase_status={posture.phase_status or '<empty>'!r}, "
        f"active_plan_exists={posture.active_plan_exists}, "
        f"active_plan_hash={posture.active_plan_hash}"
    )


def _repair_apply_exit_code(findings) -> int:
    invalid_codes = {
        "repair-refused",
        "repair-target-conflict",
        "snapshot-apply-refused",
        "agents-contract-create-refused",
        "docmap-create-refused",
        "stable-spec-create-refused",
        "state-frontmatter-refused",
    }
    if any(finding.severity == "error" and finding.code in invalid_codes for finding in findings):
        return 2
    if any(finding.severity == "error" for finding in findings):
        return 1
    return 0


def _focused_intelligence_sections(sections: list[tuple[str, list[Finding]]], focus: str | None) -> list[tuple[str, list[Finding]]]:
    if focus is None:
        return sections
    summary = _section_named(sections, "Summary")
    if focus == "search":
        return [summary, _section_named(sections, "Search")]
    if focus == "projection":
        return [summary, _section_named(sections, "Boundary"), _section_named(sections, "Projection")]
    if focus == "warnings":
        findings = [finding for _, section_findings in sections for finding in section_findings if finding.severity in {"warn", "error"}]
        if not findings:
            findings = [Finding("info", "actionable-warnings-empty", "no actionable intelligence warnings were found")]
        return [summary, ("Actionable Warnings", findings)]
    return sections


def _section_named(sections: list[tuple[str, list[Finding]]], name: str) -> tuple[str, list[Finding]]:
    for section in sections:
        if section[0] == name:
            return section
    return (name, [])


def _suggestions(command: str, findings) -> list[str]:
    errors = [finding for finding in findings if finding.severity == "error"]
    warnings = [finding for finding in findings if finding.severity == "warn"]
    if command == "check":
        if errors:
            return ["check found validation errors; inspect the validation section before running repair."]
        if any(finding.code == "check-deep-read-only" for finding in findings):
            return ["check --deep completed as a read-only status, validation, drift, links, context, hygiene, and grain report."]
        focus_finding = next((finding for finding in findings if finding.code == "check-focus-read-only"), None)
        if focus_finding:
            return [f"{focus_finding.message}."]
        if any(finding.code == "state-compaction-section-boundary-missing" for finding in warnings):
            return [
                "check completed with compact-only hygiene warnings; restore missing project-state section boundaries, then preview/apply `mylittleharness writeback --dry-run --compact-only` and `writeback --apply --compact-only`; no manual trimming, lifecycle closeout, archive, staging, commit, or next-plan opening is approved."
            ]
        if any(finding.code == "rule-context-surface-large" and finding.source == "project/project-state.md" for finding in warnings):
            return ["check completed as a read-only report; preview whole-state history compaction with `mylittleharness writeback --dry-run --compact-only`."]
        if warnings:
            return ["check completed as a read-only report with advisory findings; use advanced diagnostics only when needed."]
        return ["check completed as a read-only status plus validation report."]
    if command == "suggest":
        if warnings:
            return ["suggest completed as a read-only command-intent report; no suggested command was executed."]
        return ["suggest matched deterministic command intent advice without writing files or executing suggested commands."]
    if command == "detach":
        if any(finding.code == "detach-marker-created" for finding in findings):
            return ["detach apply created the marker-only evidence file; preserved repo-visible files remain the authority."]
        if any(finding.code == "detach-marker-unchanged" for finding in findings):
            return ["detach apply found an existing valid marker and left it unchanged."]
        if any(finding.severity == "error" for finding in findings):
            return ["detach apply was refused before authority files were changed."]
        if any(finding.severity == "warn" for finding in findings):
            return ["detach dry-run completed without writes; warnings are fail-closed inputs for detach apply."]
        return ["detach dry-run completed without writes; repo-visible files remain the authority."]
    if command == "intelligence":
        if warnings:
            return ["Use the listed source paths and line numbers for direct inspection; intelligence reports are advisory and never apply fixes."]
        return ["intelligence completed as a terminal-only advisory report; disposable navigation cache may be refreshed, but repo files remain the authority."]
    if command == "projection":
        if any(finding.severity == "error" for finding in findings):
            return ["projection artifact command was refused before writing or deleting outside the owned boundary."]
        if any(finding.severity == "warn" for finding in findings):
            return ["Generated projection artifacts are advisory; rebuild them if useful, or inspect repo files directly."]
        return ["projection artifacts are disposable generated output; deleting them does not change repo authority."]
    if command == "snapshot":
        if any(finding.severity == "warn" for finding in findings):
            return ["Use snapshot inspection as safety-evidence review only; manual rollback and source files remain operator decisions."]
        return ["snapshot inspection completed as a terminal-only read-only report; it did not approve repair, rollback, cleanup, closeout, archive, commit, or lifecycle decision."]
    if command == "evidence":
        if any(finding.severity == "warn" for finding in findings):
            return ["Use evidence findings as closeout assembly prompts; source files and observed verification remain authority."]
        return ["evidence completed as a terminal-only read-only report; it did not approve lifecycle, archive, commit, or repair actions."]
    if command == "closeout":
        if any(finding.severity == "warn" for finding in findings):
            return ["Use closeout findings as assembly inputs; operator decisions, source files, manifest policy, and observed verification remain authority."]
        return ["closeout completed as a terminal-only read-only report; it did not approve archive, commit, repair, or lifecycle decisions."]
    if command == "writeback":
        if any(finding.severity == "error" for finding in findings):
            return ["writeback apply was refused before closeout/state writeback became authoritative."]
        if any(finding.code == "writeback-compact-only" for finding in findings):
            if any(finding.code == "writeback-dry-run" for finding in findings):
                return ["writeback compact-only dry-run reported whole-state compaction posture without writing files."]
            return ["writeback compact-only apply ran the bounded whole-state compaction rail; run check to verify the archive pointer posture."]
        if any(finding.code == "writeback-dry-run" for finding in findings):
            return ["writeback dry-run reported the planned closeout/state synchronization without writing files."]
        return ["writeback apply synchronized project-state closeout facts and matching active-plan derived copies."]
    if command == "incubate":
        if any(finding.severity == "error" for finding in findings):
            return ["incubate apply was refused before any incubation note was changed."]
        if any(finding.code == "incubate-dry-run" for finding in findings):
            return ["incubate dry-run reported the target note and create/append posture without writing files."]
        return ["incubate apply updated the same-topic incubation note; promote accepted facts through research, specs, plans, or state later."]
    if command == "meta-feedback":
        if any(finding.severity == "error" for finding in findings):
            return ["meta-feedback apply was refused before any candidate or roadmap placement was changed."]
        if any(finding.code == "meta-feedback-dry-run" for finding in findings):
            return ["meta-feedback dry-run reported the candidate note, dedupe decision, and accepted roadmap placement without writing files."]
        return ["meta-feedback apply collected the candidate and accepted roadmap placement; next-plan opening and release removal remain explicit."]
    if command == "intake":
        if any(finding.severity == "error" for finding in findings):
            return ["intake apply was refused before any routed note was written."]
        if any(finding.code == "intake-dry-run" for finding in findings):
            return ["intake dry-run classified the incoming text without writing files."]
        return ["intake apply wrote one explicit routed note; classification remains advisory and does not approve lifecycle movement."]
    if command == "plan":
        if any(finding.severity == "error" for finding in findings):
            return ["plan apply was refused before active-plan or lifecycle files were changed."]
        if any(finding.code == "plan-dry-run" for finding in findings):
            return ["plan dry-run reported deterministic plan synthesis and lifecycle update posture without writing files."]
        return ["plan apply wrote the active implementation plan scaffold and project-state lifecycle pointers."]
    if command == "transition":
        if any(finding.severity == "error" for finding in findings):
            return ["transition apply was refused or stopped before the next unreviewed step."]
        if any(finding.code == "transition-dry-run" for finding in findings):
            return ["transition dry-run reported the reviewed closeout/archive/next-plan proposal and token without writing files."]
        return ["transition apply completed the explicitly reviewed writeback/plan sequence without VCS side effects."]
    if command == "memory-hygiene":
        if any(finding.severity == "error" for finding in findings):
            return ["memory-hygiene apply was refused before lifecycle source, archive, or link targets were changed."]
        if any(finding.code == "memory-hygiene-dry-run" for finding in findings):
            return ["memory-hygiene dry-run reported bounded research/incubation lifecycle hygiene without writing files."]
        return ["memory-hygiene apply updated only declared lifecycle source, archive, and exact link targets."]
    if command == "mirror":
        source_root_suggestion = next(
            (finding.message for finding in findings if finding.code == "mirror-source-root-selection-suggestion"),
            None,
        )
        if source_root_suggestion:
            return [source_root_suggestion]
        if any(finding.severity == "error" for finding in findings):
            return ["mirror refused before declared target files were changed."]
        if any(finding.code == "mirror-dry-run" for finding in findings):
            return ["mirror dry-run reported declared file parity, dependency-closure, and copy posture without writing files."]
        return ["mirror apply copied only declared target files and verified hash parity after dependency-closure diagnostics."]
    if command == "adapter":
        if any(finding.severity == "warn" for finding in findings):
            return ["Use adapter findings as optional read/projection input; repo files and the generic CLI remain authoritative."]
        return ["adapter inspection completed as a terminal-only read-only report; it did not install MCP tooling, write adapter state, or approve lifecycle decisions."]
    if command == "preflight":
        if any(finding.severity in {"warn", "error"} for finding in findings):
            return ["Use preflight findings as optional warning inputs; source files, observed verification, and operator decisions remain authority."]
        return ["preflight completed as a terminal-only optional report; it did not install hooks, add CI, write reports, or approve lifecycle decisions."]
    if command == "tasks":
        return ["tasks inspection completed as a terminal-only read-only task map; existing commands and repo files remain authoritative."]
    if command == "bootstrap":
        if any(finding.code == "package-smoke-install-ok" for finding in findings):
            return ["package smoke passed in temporary locations; product-root files and workstation state were not changed."]
        if any(finding.code.startswith("package-smoke-") and finding.severity == "error" for finding in findings):
            return ["package smoke failed before creating product-root package artifacts or workstation changes."]
        if any(finding.severity in {"warn", "error"} for finding in findings):
            return ["Use bootstrap readiness findings as planning inputs; no-write workstation readiness is advisory, package smoke remains explicit verification, standalone bootstrap apply is rejected, and publishing requires a separate scoped contract."]
        return ["bootstrap inspection completed as terminal-only read-only output; it did not install, publish, change target roots, write artifacts, or mutate workstation state."]
    if command == "semantic":
        if any(finding.severity in {"warn", "error"} for finding in findings):
            return ["Use semantic warnings as planning inputs; exact/path/full-text source-backed search and repo files remain authority."]
        return ["semantic report completed as terminal-only read-only output; it did not install runtimes, write indexes, or approve lifecycle decisions."]
    if any(finding.code in {"attach-refused", "attach-project-required", "attach-target-conflict"} for finding in errors):
        return ["attach apply was refused before any files were written."]
    if any(
        finding.code
        in {
            "repair-refused",
            "repair-target-conflict",
            "snapshot-apply-refused",
            "agents-contract-create-refused",
            "docmap-create-refused",
            "stable-spec-create-refused",
            "state-frontmatter-refused",
        }
        for finding in errors
    ):
        return ["repair apply was refused before any files were written."]
    if any(finding.code == "repair-validation-error" for finding in errors):
        return ["repair apply completed its allowed create-only pass, but post-repair validation still has errors."]
    if any(finding.code == "attach-created" for finding in findings):
        return ["attach apply completed create-only writes; run validate to inspect any remaining required surfaces."]
    if any(finding.code == "attach-unchanged" for finding in findings):
        return ["attach apply completed without changes; existing scaffold/template paths were preserved."]
    if any(finding.code == "repair-docmap-updated" for finding in findings):
        return ["repair apply created a repair snapshot, updated the selected docmap routes, and ran post-repair validation."]
    if any(finding.code == "state-frontmatter-updated" for finding in findings):
        return ["repair apply created a repair snapshot, prepended project-state frontmatter, and stopped before other repair classes."]
    if any(finding.code == "agents-contract-create-created" for finding in findings):
        return ["repair apply created the selected AGENTS.md operator contract without creating a repair snapshot and ran post-repair validation."]
    if any(finding.code == "docmap-create-created" for finding in findings):
        return ["repair apply created the selected docmap file without creating a repair snapshot and ran post-repair validation."]
    if any(finding.code == "stable-spec-create-created" for finding in findings):
        return ["repair apply created the selected stable spec fixtures without creating a repair snapshot and ran post-repair validation."]
    if any(finding.code == "repair-created" for finding in findings):
        return ["repair apply completed allowed writes and ran post-repair validation."]
    if any(finding.code == "repair-unchanged" for finding in findings):
        return ["repair apply completed without changes and ran post-repair validation."]
    if any(
        finding.code
        in {
            "state-frontmatter-plan",
            "state-frontmatter-refused",
            "state-frontmatter-skipped",
            "snapshot-plan",
            "snapshot-plan-refused",
            "snapshot-plan-skipped",
            "agents-contract-create-plan",
            "agents-contract-create-refused",
            "agents-contract-create-skipped",
            "docmap-create-plan",
            "docmap-create-refused",
            "stable-spec-create-plan",
            "stable-spec-create-refused",
        }
        for finding in findings
    ):
        return ["repair dry-run reported repair planning posture only; no files or snapshots were written."]
    if any(finding.code in {"attach-proposal", "repair-proposal"} for finding in findings):
        return [f"{command} completed as a dry-run proposal; no files were written."]
    if not errors and not warnings:
        return [f"{command} completed without required follow-up."]
    suggestions: list[str] = []
    if any(finding.code == "missing-required-surface" for finding in errors):
        suggestions.append("Restore the missing required repo-native surface before relying on the workflow state.")
    if any(finding.code == "mirror-drift" for finding in errors):
        suggestions.append("Resync package-source mirrors from project/specs/workflow only after confirming mirror parity is still intended.")
    if any(finding.code in {"missing-link", "unresolved-link"} for finding in warnings):
        suggestions.append("Review missing local path references manually; the CLI reports candidate fixes but never rewrites files.")
    if any(finding.code in {"file-budget", "start-set-budget"} for finding in warnings):
        suggestions.append("Treat large context-budget findings as measurement signals; the CLI does not compact or impose binding budgets.")
    if any(finding.code in {"forbidden-product-surface", "product-debris"} for finding in warnings):
        suggestions.append("Review product hygiene findings manually; the CLI reports debris but never deletes files.")
    if not suggestions:
        suggestions.append("Review warnings manually; this report does not apply fixes automatically.")
    return suggestions


if __name__ == "__main__":
    raise SystemExit(main())
