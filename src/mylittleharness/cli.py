from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .adapter import MCP_READ_PROJECTION_TARGET, mcp_read_projection_sections, serve_mcp_read_projection
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
    load_for_root,
    detach_apply_sections,
    repair_apply_findings,
    repair_dry_run_findings,
    snapshot_inspect_findings,
    status_findings,
    detach_dry_run_sections,
    validation_findings,
)
from .closeout import closeout_sections
from .evidence import evidence_findings
from .inventory import RootLoadError
from .models import Finding
from .projection_artifacts import (
    build_projection_artifacts,
    delete_projection_artifacts,
    inspect_projection_artifacts,
    rebuild_projection_artifacts,
)
from .projection_index import (
    build_projection_index,
    delete_projection_index,
    inspect_projection_index,
    rebuild_projection_index,
)
from .preflight import preflight_sections, render_git_pre_commit_template
from .reporting import render_intelligence_report, render_report, render_sectioned_report
from .semantic import semantic_evaluate_sections, semantic_inspect_sections
from .tasks import tasks_sections


COMMANDS = (
    "init",
    "check",
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
    "projection",
    "snapshot",
    "attach",
    "adapter",
)


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
    subparsers.add_parser("check", help="Run read-only status and validation checks without writing files.")
    repair = subparsers.add_parser("repair", help="Preview or apply deterministic workflow contract repair.")
    repair_mode = repair.add_mutually_exclusive_group(required=True)
    repair_mode.add_argument("--dry-run", action="store_true", help="Report the repair proposal without writing files.")
    repair_mode.add_argument("--apply", action="store_true", help="Create only allowed missing repair paths.")
    detach = subparsers.add_parser("detach", help="Preview harness detach posture without writing files.")
    detach_mode = detach.add_mutually_exclusive_group(required=True)
    detach_mode.add_argument("--dry-run", action="store_true", help="Report detach preservation and refusal posture without writing files.")
    detach_mode.add_argument("--apply", action="store_true", help="Create the marker-only detach evidence file in an eligible live operating root.")
    for command in ("status", "validate", "context-budget", "audit-links", "doctor", "evidence", "closeout"):
        subparsers.add_parser(command)
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
        description="Advanced compatibility diagnostic: inspect bootstrap, switch-over, publishing, package, and workstation readiness without writing files.",
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
        description="Advanced diagnostic: report read-only repo intelligence over inventory-discovered surfaces.",
    )
    intelligence.add_argument("--query", help="Unified recovery query expanded into omitted exact, path, and full-text search modes.")
    intelligence.add_argument("--search", help="Case-sensitive literal text to search in inventory-discovered surface contents.")
    intelligence.add_argument("--path", help="Case-sensitive path fragment to search in inventory-discovered paths and references.")
    intelligence.add_argument("--full-text", help="Optional SQLite FTS/BM25 query over a current source-verified projection index.")
    intelligence.add_argument("--limit", type=_positive_int, default=10, help="Maximum full-text results to show. Defaults to 10.")
    intelligence.add_argument("--focus", choices=("search", "warnings", "projection"), help="Render a focused intelligence report while keeping the command read-only.")
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
    adapter.add_argument("--target", choices=(MCP_READ_PROJECTION_TARGET,), required=True, help="Adapter projection target to inspect.")
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
        if args.inspect and args.transport is not None:
            parser.error("--transport is only valid with adapter --serve")
        if args.serve and args.transport != "stdio":
            parser.error("adapter --serve requires --transport stdio")
    root = Path(args.root).expanduser()
    try:
        inventory = load_for_root(root)
    except RootLoadError as exc:
        print(f"mylittleharness: {exc}", file=sys.stderr)
        return 2

    command = args.command
    if command == "check":
        status_section = status_findings(inventory)
        validation_section = validation_findings(inventory)
        drift_section = check_drift_findings(inventory)
        boundary_section = [
            Finding("info", "check-read-only", "check composes status, validate, and check-level drift signals without writing files"),
            Finding("info", "check-no-deep-diagnostics", "advanced diagnostics remain available through compatibility commands"),
        ]
        sections = [
            ("Status", status_section),
            ("Validation", validation_section),
            ("Drift", drift_section),
            ("Boundary", boundary_section),
        ]
        findings = flatten_sections(sections)
        result = _result_for(findings)
        print(render_sectioned_report("check", inventory.root, result, inventory.sources_for_report(), sections, _suggestions(command, findings)))
        return 1 if any(finding.severity == "error" for finding in validation_section) else 0
    if command == "detach":
        report_name = "detach --dry-run"
        if args.apply:
            sections = detach_apply_sections(inventory)
            report_name = "detach --apply"
        else:
            sections = detach_dry_run_sections(inventory)
        findings = flatten_sections(sections)
        result = _result_for(findings)
        print(render_sectioned_report(report_name, inventory.root, result, inventory.sources_for_report(), sections, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "status":
        findings = status_findings(inventory)
        result = _result_for(findings)
        print(render_report("status", inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 0
    if command == "validate":
        findings = validation_findings(inventory)
        result = _result_for(findings)
        print(render_report("validate", inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 1 if any(finding.severity == "error" for finding in findings) else 0
    if command == "context-budget":
        findings = context_budget_findings(inventory)
        result = _result_for(findings)
        print(render_report("context-budget", inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 0
    if command == "audit-links":
        findings = audit_link_findings(inventory)
        result = _result_for(findings)
        print(render_report("audit-links", inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 0
    if command == "doctor":
        findings = doctor_findings(inventory.root, inventory)
        result = _result_for(findings)
        print(render_report("doctor", inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 0
    if command == "preflight":
        if args.template == "git-pre-commit":
            print(render_git_pre_commit_template(inventory.root))
            return 0
        sections = preflight_sections(inventory)
        findings = flatten_sections(sections)
        result = _result_for(findings)
        print(render_sectioned_report("preflight", inventory.root, result, inventory.sources_for_report(), sections, _suggestions(command, findings)))
        return 0
    if command == "tasks":
        sections = tasks_sections(inventory)
        findings = flatten_sections(sections)
        result = _result_for(findings)
        print(render_sectioned_report("tasks --inspect", inventory.root, result, inventory.sources_for_report(), sections, _suggestions(command, findings)))
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
        print(render_sectioned_report(report_name, inventory.root, result, inventory.sources_for_report(), sections, _suggestions(command, findings)))
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
        print(render_sectioned_report(report_name, inventory.root, result, inventory.sources_for_report(), sections, _suggestions(command, findings)))
        return 0
    if command == "intelligence":
        sections = intelligence_sections(inventory, args.search, args.path, args.full_text, args.limit, args.query)
        findings = flatten_sections(sections)
        result = _result_for(findings)
        display_sections = _focused_intelligence_sections(sections, args.focus)
        print(
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
        findings = evidence_findings(inventory)
        result = _result_for(findings)
        print(render_report("evidence", inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 0
    if command == "closeout":
        sections = closeout_sections(inventory)
        findings = flatten_sections(sections)
        result = _result_for(findings)
        print(render_sectioned_report("closeout", inventory.root, result, inventory.sources_for_report(), sections, _suggestions(command, findings)))
        return 0
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
        print(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if any(finding.severity == "error" for finding in findings) else 0
    if command == "snapshot":
        findings = snapshot_inspect_findings(inventory)
        result = _result_for(findings)
        print(render_report("snapshot --inspect", inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 0
    if command == "adapter":
        if args.serve:
            return serve_mcp_read_projection(inventory, sys.stdin, sys.stdout)
        sections = mcp_read_projection_sections(inventory)
        findings = flatten_sections(sections)
        result = _result_for(findings)
        print(render_sectioned_report(f"adapter --inspect --target {args.target}", inventory.root, result, inventory.sources_for_report(), sections, _suggestions(command, findings)))
        return 0
    if command in {"init", "attach"}:
        report_name = f"{command} --dry-run"
        if args.apply:
            findings = attach_apply_findings(inventory, args.project)
            report_name = f"{command} --apply"
        else:
            findings = attach_dry_run_findings(inventory, args.project)
        result = _result_for(findings)
        print(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        return 2 if args.apply and result == "error" else 0
    if command == "repair":
        report_name = "repair --dry-run"
        if args.apply:
            findings = repair_apply_findings(inventory)
            report_name = "repair --apply"
        else:
            findings = repair_dry_run_findings(inventory)
        result = _result_for(findings)
        print(render_report(report_name, inventory.root, result, inventory.sources_for_report(), findings, _suggestions(command, findings)))
        if args.apply:
            return _repair_apply_exit_code(findings)
        return 0
    parser.error(f"unknown command: {command}")
    return 2


def _result_for(findings) -> str:
    if any(finding.severity == "error" for finding in findings):
        return "error"
    if any(finding.severity == "warn" for finding in findings):
        return "warn"
    return "ok"


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--limit must be an integer >= 1") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("--limit must be >= 1")
    return parsed


def _projection_target_findings(target: str, artifacts_fn, index_fn, inventory: object) -> list[Finding]:
    if target == "artifacts":
        return artifacts_fn(inventory)
    if target == "index":
        return index_fn(inventory)
    return artifacts_fn(inventory) + index_fn(inventory)


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
        if warnings:
            return ["check completed as a read-only report with advisory findings; use advanced diagnostics only when needed."]
        return ["check completed as a read-only status plus validation report."]
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
        return ["intelligence completed as a terminal-only read-only report; repo files remain the authority."]
    if command == "projection":
        if any(finding.severity == "error" for finding in findings):
            return ["projection artifact command was refused before writing or deleting outside the owned boundary."]
        if any(finding.severity == "warn" for finding in findings):
            return ["Generated projection artifacts are advisory; rebuild them if useful, or inspect repo files directly."]
        return ["projection artifacts are disposable generated output; deleting them does not change repo authority."]
    if command == "snapshot":
        if any(finding.severity == "warn" for finding in findings):
            return ["Use snapshot inspection as safety-evidence review only; manual rollback and source files remain operator decisions."]
        return ["snapshot inspection completed as a terminal-only read-only report; it did not approve repair, rollback, cleanup, closeout, archive, commit, or switch-over."]
    if command == "evidence":
        if any(finding.severity == "warn" for finding in findings):
            return ["Use evidence findings as closeout assembly prompts; source files and observed verification remain authority."]
        return ["evidence completed as a terminal-only read-only report; it did not approve lifecycle, archive, commit, or repair actions."]
    if command == "closeout":
        if any(finding.severity == "warn" for finding in findings):
            return ["Use closeout findings as assembly inputs; operator decisions, source files, manifest policy, and observed verification remain authority."]
        return ["closeout completed as a terminal-only read-only report; it did not approve archive, commit, repair, or lifecycle actions."]
    if command == "adapter":
        if any(finding.severity == "warn" for finding in findings):
            return ["Use adapter findings as optional read/projection input; repo files and the generic CLI remain authoritative."]
        return ["adapter inspection completed as a terminal-only read-only report; it did not install MCP tooling, write adapter state, or approve lifecycle actions."]
    if command == "preflight":
        if any(finding.severity in {"warn", "error"} for finding in findings):
            return ["Use preflight findings as optional warning inputs; source files, observed verification, and operator decisions remain authority."]
        return ["preflight completed as a terminal-only optional report; it did not install hooks, add CI, write reports, or approve lifecycle actions."]
    if command == "tasks":
        return ["tasks inspection completed as a terminal-only read-only task map; existing commands and repo files remain authoritative."]
    if command == "bootstrap":
        if any(finding.code == "package-smoke-install-ok" for finding in findings):
            return ["package smoke passed in temporary locations; product-root files and workstation state were not changed."]
        if any(finding.code.startswith("package-smoke-") and finding.severity == "error" for finding in findings):
            return ["package smoke failed before creating product-root package artifacts or workstation changes."]
        if any(finding.severity in {"warn", "error"} for finding in findings):
            return ["Use bootstrap readiness findings as planning inputs; no-write workstation readiness is advisory, package smoke remains explicit verification, standalone bootstrap apply is rejected, and publishing or switch-over require separate scoped contracts."]
        return ["bootstrap inspection completed as terminal-only read-only output; it did not install, publish, switch roots, write artifacts, or mutate workstation state."]
    if command == "semantic":
        if any(finding.severity in {"warn", "error"} for finding in findings):
            return ["Use semantic warnings as planning inputs; exact/path/full-text source-backed search and repo files remain authority."]
        return ["semantic report completed as terminal-only read-only output; it did not install runtimes, write indexes, or approve lifecycle actions."]
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
