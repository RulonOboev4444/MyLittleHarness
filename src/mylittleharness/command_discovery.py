from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .models import Finding


@dataclass(frozen=True)
class CommandIntent:
    intent_id: str
    summary: str
    aliases: tuple[str, ...]
    first_safe_command: str
    follow_up_commands: tuple[str, ...]
    root_posture: str
    boundary: str


COMMAND_INTENTS: tuple[CommandIntent, ...] = (
    CommandIntent(
        "start-pass",
        "Inspect current root posture before choosing a mutating rail.",
        ("start", "status", "check", "validate", "what next", "current posture", "root posture"),
        "mylittleharness --root <root> check",
        ("mylittleharness --root <root> check --deep", "mylittleharness --root <root> check --focus validation"),
        "any readable MLH root",
        "read-only report only; does not repair, write files, close out, archive, stage, commit, or change lifecycle state",
    ),
    CommandIntent(
        "repair-preview",
        "Preview deterministic workflow contract repair before any apply.",
        ("repair", "fix missing scaffold", "contract repair", "repair before apply", "validation error"),
        "mylittleharness --root <root> repair --dry-run",
        ("mylittleharness --root <root> repair --apply",),
        "live operating root after check reports a repairable validation issue",
        "dry-run is advisory; apply remains explicit and bounded to deterministic repair classes",
    ),
    CommandIntent(
        "open-active-plan",
        "Open a deterministic active implementation plan from explicit or roadmap-derived title/objective/task input.",
        ("open plan", "create plan", "next plan", "implementation plan", "roadmap item", "plan apply"),
        "mylittleharness --root <root> plan --dry-run --roadmap-item <id> [--title <title>] [--objective <objective>]",
        ("mylittleharness --root <root> plan --apply --roadmap-item <id> [--title <title>] [--objective <objective>]",),
        "live operating root with no conflicting active plan unless --update-active is explicit",
        "plan output creates execution scaffolding only; it cannot approve closeout, archive, commit, rollback, or future mutations",
    ),
    CommandIntent(
        "advance-active-phase",
        "Advance an already open plan to the next explicit phase.",
        ("advance phase", "next phase", "phase pending", "phase complete", "active phase"),
        "mylittleharness --root <root> writeback --dry-run --active-phase <next-phase> --phase-status pending",
        ("mylittleharness --root <root> writeback --apply --active-phase <next-phase> --phase-status pending",),
        "live operating root with an active plan and explicit operator decision to continue",
        "phase advancement does not approve archive, roadmap done-status, next-plan opening, staging, commit, or push",
    ),
    CommandIntent(
        "closeout-fields",
        "Assemble closeout evidence and record explicit closeout facts.",
        ("closeout", "record closeout", "docs decision", "state transfer", "work result", "commit decision"),
        "mylittleharness --root <root> closeout",
        (
            "mylittleharness --root <root> writeback --dry-run --docs-decision <updated|not-needed|uncertain> --state-writeback <text> --verification <text> --commit-decision <text>",
            "mylittleharness --root <root> writeback --apply --docs-decision <updated|not-needed|uncertain> --state-writeback <text> --verification <text> --commit-decision <text>",
        ),
        "live operating root; product/source verification remains separate evidence",
        "closeout and writeback facts are lifecycle authority only after explicit apply; reports do not stage, commit, archive, or open next work",
    ),
    CommandIntent(
        "archive-active-plan",
        "Archive a completed active plan through the bounded lifecycle write rail.",
        ("archive", "archive plan", "archive active plan", "completed plan", "mark roadmap done", "roadmap done"),
        "mylittleharness --root <root> writeback --dry-run --archive-active-plan --phase-status complete --from-active-plan --roadmap-item <id> --roadmap-status done",
        ("mylittleharness --root <root> writeback --apply --archive-active-plan --phase-status complete --from-active-plan --roadmap-item <id> --roadmap-status done",),
        "live operating root whose project-state phase_status is complete, or whose same reviewed writeback request supplies --phase-status complete",
        "archive-active-plan refuses uncompleted lifecycle state unless the same writeback request explicitly supplies --phase-status complete; it does not stage, commit, push, repair, or open the next plan",
    ),
    CommandIntent(
        "reviewed-transition",
        "Review a composed phase-completion/archive/next-plan transition with a token.",
        ("transition", "close archive next", "review token", "archive and open next", "complete current phase"),
        "mylittleharness --root <root> transition --dry-run --complete-current-phase --archive-active-plan --current-roadmap-item <id> --current-roadmap-status done [--next-roadmap-item <id>]",
        ("mylittleharness --root <root> transition --apply --review-token <token> <same reviewed flags>",),
        "live operating root with an explicit lifecycle transition request",
        "transition apply requires the matching dry-run token and delegates only to bounded writeback/plan rails",
    ),
    CommandIntent(
        "compact-project-state",
        "Compact oversized project-state history through the whole-state compaction rail.",
        ("compact", "compact state", "state too large", "project state oversized", "compact-only"),
        "mylittleharness --root <root> writeback --dry-run --compact-only",
        ("mylittleharness --root <root> writeback --apply --compact-only",),
        "live operating root after check reports oversized project/project-state.md",
        "compact-only scans the whole state and cannot approve repair, closeout, archive, roadmap changes, staging, commit, or push",
    ),
    CommandIntent(
        "capture-meta-feedback",
        "Capture an MLH rough edge as a source-bound fix candidate.",
        ("meta feedback", "fix candidate", "rough edge", "agent friction", "route discovery", "mlh debt"),
        "mylittleharness --root <mlh-dev-root> meta-feedback --dry-run --from-root <observed-root> --topic <topic> --note <note>",
        ("mylittleharness --root <mlh-dev-root> meta-feedback --apply --from-root <observed-root> --topic <topic> --note <note>",),
        "central MLH operating root for product debt; observed root is provenance only",
        "meta-feedback records operating memory and accepted placement only; it cannot approve release removal, lifecycle movement, archive, staging, commit, or next-plan opening",
    ),
    CommandIntent(
        "route-incoming-information",
        "Classify incoming text before writing operating memory.",
        ("intake", "route text", "incoming information", "docs impact", "research import", "decision record"),
        "mylittleharness --root <root> intake --dry-run --text <text>",
        ("mylittleharness --root <root> intake --apply --text <text> --target <route/file.md>",),
        "live operating root with explicit target for apply",
        "intake classification is advisory; apply writes one explicit route target and cannot promote roadmap, closeout, archive, commit, or repair",
    ),
    CommandIntent(
        "incubate-future-idea",
        "Create or append a same-topic future-idea note.",
        ("incubate", "future idea", "follow-up note", "plan incubation", "note-file"),
        "mylittleharness --root <root> incubate --dry-run --topic <topic> --note <note>",
        ("mylittleharness --root <root> incubate --apply --topic <topic> --note <note>",),
        "live operating root",
        "incubation is operating memory only; it cannot approve roadmap promotion, plan opening, closeout, archive, staging, commit, or push",
    ),
    CommandIntent(
        "update-roadmap-item",
        "Add or update one accepted-work roadmap item.",
        ("roadmap", "accepted work", "queue item", "roadmap update", "roadmap add"),
        "mylittleharness --root <root> roadmap --dry-run --action update --item-id <id> [fields]",
        ("mylittleharness --root <root> roadmap --apply --action update --item-id <id> [fields]",),
        "live operating root with readable project/roadmap.md",
        "roadmap output is sequencing evidence only; it cannot approve closeout, archive, commit, rollback, repair, or lifecycle decisions",
    ),
    CommandIntent(
        "mirror-product-files",
        "Preview and apply declared product-to-demo file parity with source-root guidance and local Python dependency-closure diagnostics.",
        ("mirror", "copy to demo", "product to demo", "hash parity", "dependency closure", "mirror apply", "source root"),
        "mylittleharness --root <product-source-root> mirror --dry-run --target-root <demo-root> --path <rel-path> [--allow-product-target]",
        ("mylittleharness --root <product-source-root> mirror --apply --target-root <demo-root> --path <rel-path> [--allow-product-target]",),
        "declared product_source_root as --root plus explicit mirror target",
        "mirror copies only declared files, reports undeclared local dependency gaps, and cannot approve lifecycle, closeout, archive, staging, commit, push, or unrelated cleanup",
    ),
    CommandIntent(
        "record-agent-evidence",
        "Record one source-bound agent run evidence file after explicit review.",
        ("agent evidence", "record evidence", "agent run", "verification record", "proof record"),
        "mylittleharness --root <root> evidence --record --dry-run --record-id <id> --role <role> --actor <actor> --task <task> --status <status> --stop-reason <reason> --attempt-budget <budget> --input-ref <rel> --output-ref <rel> --claimed-path <rel> --command <command>",
        ("mylittleharness --root <root> evidence --record --apply <same reviewed fields>",),
        "live operating root with explicit source-bound refs",
        "agent run evidence is proof input only; it cannot approve lifecycle transitions, archive, roadmap status, staging, commit, rollback, or next-plan opening",
    ),
    CommandIntent(
        "command-discovery",
        "Inspect this deterministic command intent registry.",
        ("suggest", "intent", "command discovery", "which command", "safe command", "command index"),
        "mylittleharness --root <root> suggest --intent <operator-action>",
        ("mylittleharness --root <root> suggest --list", "mylittleharness --root <root> suggest --intent <operator-action> --json"),
        "any readable MLH root",
        "suggest is read-only and never executes the commands it reports",
    ),
)


def command_intent_registry() -> tuple[CommandIntent, ...]:
    return COMMAND_INTENTS


def command_suggestions_for_intent(intent: str, limit: int = 3) -> tuple[CommandIntent, ...]:
    normalized = _normalize(intent)
    if not normalized:
        return ()

    scored: list[tuple[int, int, CommandIntent]] = []
    query_tokens = set(normalized.split())
    for index, command_intent in enumerate(COMMAND_INTENTS):
        aliases = tuple(_normalize(alias) for alias in command_intent.aliases)
        searchable = " ".join((command_intent.intent_id.replace("-", " "), command_intent.summary, *aliases))
        searchable_normalized = _normalize(searchable)
        score = 0
        if normalized == _normalize(command_intent.intent_id):
            score += 100
        if normalized in aliases:
            score += 80
        score += sum(40 for alias in aliases if alias and alias in normalized)
        score += sum(25 for alias in aliases if alias and normalized in alias)
        score += len(query_tokens & set(searchable_normalized.split())) * 5
        if score:
            scored.append((score, -index, command_intent))

    scored.sort(reverse=True)
    return tuple(item[2] for item in scored[:limit])


def command_suggestion_findings(
    suggestions: tuple[CommandIntent, ...],
    *,
    intent: str | None,
    list_all: bool,
) -> list[Finding]:
    findings: list[Finding] = []
    if not suggestions:
        findings.append(
            Finding(
                "warn",
                "command-suggest-no-match",
                f"no deterministic command intent matched {intent!r}; use suggest --list or start with `mylittleharness --root <root> check`",
                route_id="unclassified",
            )
        )
    for suggestion in suggestions:
        code = "command-suggest-registry-entry" if list_all else "command-suggest-match"
        findings.append(
            Finding(
                "info",
                code,
                (
                    f"{suggestion.intent_id}: first_safe_command={suggestion.first_safe_command}; "
                    f"follow_up_commands={list(suggestion.follow_up_commands)}; "
                    f"root_posture={suggestion.root_posture}; boundary={suggestion.boundary}"
                ),
                route_id="unclassified",
            )
        )
    return findings


def command_suggestion_boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "command-suggest-read-only",
            "suggest reports deterministic command advice only; it does not execute suggested commands, write files, approve repair, approve lifecycle movement, archive, stage, commit, push, or mutate workstation state",
            route_id="unclassified",
        )
    ]


def command_suggestions_to_dict(suggestions: tuple[CommandIntent, ...]) -> list[dict[str, object]]:
    return [asdict(suggestion) for suggestion in suggestions]


def _normalize(value: str) -> str:
    lowered = str(value or "").casefold().replace("_", " ").replace("-", " ")
    return re.sub(r"[^a-z0-9]+", " ", lowered).strip()
