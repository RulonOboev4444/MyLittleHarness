from __future__ import annotations

import shlex
from pathlib import Path

from .checks import (
    audit_link_findings,
    context_budget_findings,
    flatten_sections,
    product_hygiene_findings,
    validation_findings,
)
from .closeout import closeout_sections
from .inventory import Inventory
from .models import Finding


def render_git_pre_commit_template(root: Path) -> str:
    root_literal = shlex.quote(str(root.resolve()))
    return "\n".join(
        [
            "#!/bin/sh",
            "# MyLittleHarness advisory preflight hook template.",
            "# Install manually only when an operator wants local warning output.",
            "# This wrapper never blocks commits and never mutates files, Git config, or workflow state.",
            f"MLH_ROOT={root_literal}",
            "",
            "if ! command -v mylittleharness >/dev/null 2>&1; then",
            "    printf '%s\\n' 'warning: mylittleharness is not available; skipping advisory preflight.' >&2",
            "    exit 0",
            "fi",
            "",
            'if ! mylittleharness --root "$MLH_ROOT" preflight; then',
            "    printf '%s\\n' 'warning: mylittleharness preflight did not complete; this hook remains warning-only.' >&2",
            "fi",
            "",
            "exit 0",
        ]
    )


def preflight_sections(inventory: Inventory) -> list[tuple[str, list[Finding]]]:
    checks = _check_findings(inventory)
    closeout = _closeout_readiness_findings(inventory)
    return [
        ("Summary", _summary_findings(inventory, checks + closeout)),
        ("Checks", checks),
        ("Closeout Readiness", closeout),
        ("Boundary", _boundary_findings()),
    ]


def _summary_findings(inventory: Inventory, findings: list[Finding]) -> list[Finding]:
    errors = sum(1 for finding in findings if finding.severity == "error")
    warnings = sum(1 for finding in findings if finding.severity == "warn")
    status = "error" if errors else "warn" if warnings else "ok"
    return [
        Finding(
            "info",
            "preflight-boundary",
            "terminal-only optional preflight report; no files, hooks, CI config, GitHub state, generated reports, caches, repairs, commits, archives, or lifecycle state are written",
        ),
        Finding("info", "preflight-root-kind", f"root kind: {inventory.root_kind}"),
        Finding(
            "info",
            "preflight-result",
            f"advisory result: status={status}; errors={errors}; warnings={warnings}; local closeout remains valid without hooks, CI, GitHub, network, or adapter state",
        ),
    ]


def _check_findings(inventory: Inventory) -> list[Finding]:
    groups = [
        ("validate", validation_findings(inventory)),
        ("audit-links", audit_link_findings(inventory)),
        ("context-budget", context_budget_findings(inventory)),
        ("product-hygiene", product_hygiene_findings(inventory)),
    ]
    findings: list[Finding] = []
    for label, group_findings in groups:
        findings.append(_group_summary(label, group_findings))
        findings.extend(_group_samples(label, group_findings))
    return findings


def _closeout_readiness_findings(inventory: Inventory) -> list[Finding]:
    sections = closeout_sections(inventory)
    closeout_findings = flatten_sections(sections)
    findings = [
        _group_summary("closeout", closeout_findings),
        Finding(
            "info",
            "preflight-closeout-source",
            "closeout readiness is assembled from the read-only closeout report, including target-bound VCS posture cues when Git is available",
        ),
    ]
    for finding in closeout_findings:
        if finding.code in {
            "closeout-worktree-start-state",
            "closeout-task-scope",
            "closeout-commit-input",
            "closeout-quality-gate",
        }:
            findings.append(
                Finding(
                    finding.severity,
                    "preflight-closeout-cue",
                    f"{finding.code}: {finding.message}",
                    finding.source,
                    finding.line,
                )
            )
    return findings


def _group_summary(label: str, findings: list[Finding]) -> Finding:
    errors = sum(1 for finding in findings if finding.severity == "error")
    warnings = sum(1 for finding in findings if finding.severity == "warn")
    severity = "error" if errors else "warn" if warnings else "info"
    return Finding(severity, f"preflight-{label}", f"{label} findings: {errors} errors, {warnings} warnings")


def _group_samples(label: str, findings: list[Finding], limit: int = 3) -> list[Finding]:
    samples = [finding for finding in findings if finding.severity in {"error", "warn"}][:limit]
    return [
        Finding(
            finding.severity,
            "preflight-check-sample",
            f"{label} {finding.severity} {finding.code}: {finding.message}",
            finding.source,
            finding.line,
        )
        for finding in samples
    ]


def _boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "preflight-no-authority",
            "preflight output is advisory evidence only and cannot approve correctness, repair, closeout, archive, commit, lifecycle decisions",
        ),
        Finding(
            "info",
            "preflight-no-hooks",
            "preflight is suitable for manual or future hook/CI consumption, but this command does not install hooks, add CI/GitHub workflows, block by itself, or require network access",
        ),
        Finding(
            "info",
            "preflight-no-mutation",
            "preflight does not format, repair, write reports, create generated artifacts, stage files, commit, archive, change target roots, or mutate workflow state",
        ),
    ]
