# Workflow Rollout Slices Spec

> Product fixture note: This spec is retained as a product compatibility fixture for CLI/tests. Live workflow authority, plans, research, and memory remain in the target repository; legacy reference material is opened only for a named blocker.

## Purpose

This spec defines the recommended rollout slices for implementing the workflow improvements captured in the new canonical specs.
The rollout should stay markdown-first and repo-native even when helper skills or adjacent tooling are later added around it.

It exists to:
- separate the minimum useful scaffold from optional later hardening
- keep the rollout cheap-first and repo-native
- prevent the implementation phase from jumping straight into hooks, daemons, or heavy orchestration

This spec is a stable rollout contract, not the active implementation plan itself.

## MyLittleHarness Core v0 Rollout Boundary

MyLittleHarness Core v0 is a contract landing, not an operational lifecycle decision. It lands the repo-native rules that make the harness readable from stable specs, README, project state, the artifact map, docmap, and any active or archived plan.

The Core v0 rollout may update live workflow specs, package-source mirrors for changed specs, and navigation surfaces. It does not regenerate package archives, rebuild attach/install machinery, redesign skills, redesign MCP, introduce hooks, run candidate tooling, create evidence IDs, add quality gates, or switch the operational harness.

Root-boundary readiness is evidence only. Any future operating-root change belongs to a later scoped plan after compatibility labels, projections, and validation evidence are explicit.

## Authoritative Inputs

- `project/specs/workflow/workflow-artifact-model-spec.md`
- `project/specs/workflow/workflow-plan-synthesis-spec.md`
- `project/specs/workflow/workflow-verification-and-closeout-spec.md`
- `project/specs/workflow/workflow-capability-roadmap-spec.md`
- existing base workflow contract and `project-orchestrator` behavior

## Capability Inventory Contract

The rollout must cover the full useful capability roadmap, not only the nearest implementation slice.

That means:
- core architecture belongs in the canonical specs
- useful future implementation ideas belong in the roadmap spec with explicit status
- optional or risky ideas must be marked `optional-next`, `later-extension`, or `incubation-only` instead of being left implicit
- implementation slices may be narrow, but the spec surface should preserve the whole intended direction

## Rollout Principles

- Keep the workflow markdown-first and inspectable.
- Treat workflow canon, skills, MCP/helper surfaces, and runtime wiring as one inspectable harness stack while keeping canonical authority in repo-native docs.
- Prefer explicit repo artifacts over hidden runtime state.
- Tighten templates and rules before adding automation.
- Prefer operator-invoked helpers over always-on background behavior.
- Introduce automation only when it clearly reduces toil without weakening transparency.

## Roadmap Execution Slice Metadata

Roadmap-backed rollout may group accepted roadmap items into one advisory execution slice when the items share context, target artifacts, verification posture, and closeout boundary. Roadmap item blocks can expose `execution_slice`, `slice_goal`, `slice_members`, `slice_dependencies`, and `slice_closeout_boundary` as planning evidence only.

The active implementation plan remains the executable contract for one slice. When a plan opens from a roadmap item, plan frontmatter can carry `primary_roadmap_item`, `covered_roadmap_items`, `domain_context`, `target_artifacts`, `execution_policy`, `auto_continue`, `stop_conditions`, and `closeout_boundary`; `project/project-state.md` should keep only current lifecycle pointers. The default execution policy is current-phase-only: continue only the current active phase, record repo-visible evidence/state, and stop unless explicit auto-continuation metadata and stop-condition coverage are present. A completed phase can become ready for explicit closeout/writeback without archiving the active plan, marking roadmap items done, or opening the next execution slice. Neither roadmap grouping nor generated plan metadata approves repair, closeout, archive, commit, rollback, lifecycle decisions, or next-slice movement.

Bounded plan synthesis may explain why a roadmap-backed plan bundles or splits accepted items by reporting shared execution slice, shared specs, shared target artifacts, source inputs, dependencies, target-artifact pressure, and phase pressure. These reports are advisory review aids only; they do not calibrate slice size, require a split, or authorize a lifecycle transition.

Slice-grain diagnostics are allowed only as read-only reports. They may compare active and archived plans for covered roadmap item count, phase count, target artifact count, write-scope specificity, verification specificity, stop points, closeout evidence, and roadmap live-tail hygiene. The output is empirical tuning evidence, not an automatic slice split, roadmap compaction, closeout decision, or lifecycle approval.

## Slice 1: Canonical Doc and Template Contract

### Goal

Make the new artifact model and verification model the canonical written contract.

### Includes

- stable workflow specs
- explicit `project-state` role as index plus active commitments
- explicit plan requirement for source set, distilled inputs, and verification blocks when relevant
- explicit incubation frontmatter expectations for new or refreshed temporary notes

### Excludes

- runtime hooks
- helper scripts
- auto-cleanup

### Done when

- the canonical docs are landed
- `project-state` points future work toward the new canon
- future implementation work can start from specs instead of re-synthesizing the architecture

## Slice 2: Distillation and Planning Support

### Goal

Make artifact-aware planning operational without creating a new planning platform.

### Includes

- bounded planning checklist or helper behavior that follows the start pass
- explicit source-set and distillation output in planning work
- conflict surfacing between state, specs, plans, and incubation notes

### Excludes

- autonomous plan generation
- hidden planner memory
- multi-layer nested planners

### Done when

- planning stops broad markdown ingestion by default
- planning outputs show which artifacts were actually used
- planning conflicts are surfaced instead of silently reconciled

## Slice 3: Verification Block Support

### Goal

Replace phase-by-phase ritual checking with meaningful verification anchors.

### Includes

- explicit `plan`, `integration`, and `closeout` anchors
- evidence requirements for a verified block
- optional standalone verification verdicts only for higher-risk work

### Excludes

- always-on verification daemons
- broad hook chains that correctness depends on
- dashboards

### Done when

- medium-risk work uses block verification instead of per-phase habit
- closeout summaries consistently expose docs, state, verification, and commit decisions
- verified completion requires explicit evidence

## Slice 4: Conservative Automation

### Goal

Automate only the narrowest parts that clearly reduce workflow friction without creating hidden state.

### Includes

- optional operator-invoked helpers for distillation or verification formatting
- conservative docmap maintenance when routing knowledge changes
- optional stale-marking suggestions for temporary artifacts

### Excludes

- background cleanup
- silent promotion
- hidden archival moves
- scheduler or daemon behavior

### Done when

- helpers save time but remain optional
- a user can still understand the workflow fully from repo artifacts alone

## Deferred to Later Extensions

These are explicitly not part of the first implementation pass:

- always-on scheduler or daemon orchestration
- automatic worktree swarms
- default fresh-context reviewer worktrees for ordinary work
- hidden auto-promotion of notes into canonical memory
- aggressive markdown garbage collection
- dashboards or status UIs as required workflow surfaces
- correctness that depends on long hook chains

## First Recommended Implementation Pass

The first Core v0 implementation pass begins with:

1. tightening `project-state` and active-plan expectations
2. making source-set and distillation output explicit in planning work
3. making verification anchors explicit in active plans and closeout
4. keeping package-source mirrors subordinate and resynced only after live spec edits
5. recording readiness without executing lifecycle decision

It should not begin with:

1. hooks
2. worktrees
3. background automation
4. UI surfaces
5. skills/MCP redesign
6. package/archive regeneration

## Success Condition

The rollout succeeds when the workflow becomes more trustworthy and scalable without becoming heavier, more opaque, or more scheduler-like.
