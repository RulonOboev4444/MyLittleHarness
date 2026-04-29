# Context And Ceremony Budget Spec

## Purpose

This spec defines how MyLittleHarness keeps context loading and workflow ceremony small enough for solo-first work while preserving authority, safety, and recovery.

The harness should help an agent start cheaply, load details just in time, and escalate only when risk justifies more structure.

## Authority

The operating root owns current focus, active plan status, research intake, and closeout evidence for the repository MyLittleHarness is servicing. Product docs define reusable rules and gates. Generated summaries, search results, metadata, adapters, and background task state are support surfaces only.

For the portable clean-room posture, an operating project root owns active memory and research, the product source checkout owns reusable docs/source, and archive/evidence roots are opt-in lookup targets only. MyLittleHarness must remain a direct product for an explicit target repository.

The canonical start pass should be driven by explicit repo-visible files, not broad historical context or adapter memory.

## Non-Authority

The following must not become authority for task scope or completion:

- raw context dumps
- old chat transcripts by themselves
- generated summaries without source pointers
- search rankings
- semantic retrieval guesses
- background-agent state
- browser, IDE, MCP, plugin, hook, GitHub, or CI state
- ceremony checklists without observed verification evidence

More context is not more authority. More process is not completion.

## Current Contract

Start passes should be cheap. Load the canonical project state first, then the active plan only when plan status or the user request makes it relevant. Load problem reports, product docs, specs, and source files just in time.

Before mutation, the agent needs one planning gate that names the intended edits, reason, validation, assumptions, and boundaries. Small ad hoc tasks may proceed directly when the scope is narrow, the blast radius is low, and no durable multi-session state is needed.

Escalate to a full implementation plan when work is multi-session, high-risk, cross-root, contract-changing, hard to validate, or likely to require closeout evidence.

Context budgets should favor:

- source-set discipline over broad archaeology
- repo impact maps over full repo scans
- compact summaries over pasted raw intake
- named exclusions for old fallback context
- short durable state writeback when focus or plan phase changes
- independent review only when risk justifies it

Sub-agents and background work are optional bounded helpers. They require explicit user authorization and must return compact results to the main context.

## Future Product Gates

Before implementing context or ceremony tooling, a later scoped plan must define:

- start-pass profiles for read-only, ad hoc, plan, and closeout work
- impact-map format and routing rules
- context budget warnings and thresholds
- ceremony escalation criteria
- summary shape for long sessions
- background task status and recovery boundaries
- verification anchors for plan, integration, and closeout blocks
- tests or smoke scenarios for small tasks, plan tasks, and closeout

Measured thresholds should come after qualitative guidance proves useful.

## Validation Expectations

A valid implementation should prove that:

- small ad hoc tasks avoid unnecessary planning ceremony
- mutating work still has a clear pre-write boundary
- active plans are loaded only when relevant
- unrelated historical context is excluded by default
- generated summaries point back to source files or explicit observations
- background work cannot become hidden authority
- closeout cannot be declared without observed verification or explicit verified skip

Validation may include smoke scenarios for read-only explanation, small mutation, multi-session planning, and closeout.

## Explicit Non-Goals

- No new always-on router, scheduler, daemon, dashboard, or control plane.
- No required background agents.
- No hard token thresholds in this phase.
- No broad import of old research or archives.
- No ceremony checklist that substitutes for verification.
- No automatic thread renaming or user-global configuration changes.
- No implementation of tooling from this spec without a later scoped plan.



