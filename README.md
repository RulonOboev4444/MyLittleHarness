# MyLittleHarness

MyLittleHarness helps AI-assisted projects keep their truth in the repository, so agents can move with clearer rails and humans stay in control without babysitting every step.

AI coding tools are good at producing code. The harder problem is the work around the code: state hides in chat, generated reports start looking official, a cache becomes a source of truth, and the next agent cannot tell what is accepted work and what is only a suggestion.

MyLittleHarness is the small repo-native layer for that moment. It moves process state out of the prompt and into visible files: current focus, active plans, repair boundaries, docs decisions, verification, and closeout evidence. The repo keeps the truth; tools get better rails; people keep the final say.

It is deliberately not an agent framework, workflow runner, dashboard, scheduler, CI replacement, or control plane. Workflow tools decide what to do next. MyLittleHarness decides what the repository is allowed to treat as true.

## Why It Exists

Use MyLittleHarness when an AI-assisted repository needs answers like:

- What is the current project state?
- Which plan, if any, is active?
- Which files are authority, and which files are generated cache?
- Can a new agent recover context from the repo alone?
- What repair is safe to apply, and what is only a warning?
- How do we close out work without pretending a report or throwaway run is durable evidence?

The product formula is intentionally plain:

> Files hold authority. Metadata routes. Git records durable history. Generated projections accelerate. Diagnostics warn. Adapters assist. Mutation stays explicit and fail-closed.

## Why Agents Get More Efficient

MLH does not make the model magically smarter. It makes the workspace easier for the model to operate.

The efficiency gain comes from moving process state out of the prompt and into the repo. Project state, roadmap, active plans, checks, closeout evidence, and archives tell the agent what is active, what is allowed, what is blocked, what counts as done, where evidence goes, and how to resume.

That means less context reconstruction, less task-selection ambiguity, less scope creep, fewer unsafe actions, faster verification, better resumability, and optional process feedback when explicitly enabled.

The result: less prompt entropy, fewer wrong turns, tighter scopes, and more reliable autonomous loops.

## Who It Is For

MyLittleHarness is for developers, teams, and tool builders who are already using AI coding assistants and want a stronger repository boundary around them.

It is especially useful when:

- more than one agent or developer touches the same repository
- work spans multiple sessions and chat memory is not enough
- generated indexes, diagnostics, or adapter output are useful but must stay disposable
- repair needs a dry-run/apply boundary instead of a vague "fix everything" button
- closeout facts, docs decisions, verification, and carry-forward notes need to be recoverable later

It complements orchestrators. It does not compete with them. An orchestrator can plan, code, validate, and open PRs; MyLittleHarness keeps repo-visible state, active plan pointers, generated caches, repair boundaries, docs decisions, and closeout evidence explicit across those steps.

## What You Get

- A small visible CLI: `init`, `check`, `repair`, and `detach`.
- Repo-visible operating memory under the target repository.
- Read-only diagnostics that explain state, validation, drift, links, lifecycle routes, and generated projection posture.
- Bounded apply modes that name the target root and write boundary before touching files.
- Disposable navigation/search projections under `.mylittleharness/generated/projection/`.
- Compatibility rails for advanced lifecycle work such as explicit `writeback`, `transition`, `incubate`, `plan`, `memory-hygiene`, and `roadmap`.

Generated state is build-to-delete. Reports are diagnostics, not decisions. Snapshots are safety evidence, not authority.

## First-Run Operator Path

The first-run path is short on purpose. From a MyLittleHarness source checkout:

```bash
export PYTHONPATH=src
ProductRoot="$(pwd)"
TargetRoot="/path/to/target"

# Optional local package evidence from temporary locations outside this checkout.
python -m mylittleharness --root $ProductRoot bootstrap --package-smoke

# Attach and inspect an explicit target repository.
python -m mylittleharness --root $TargetRoot init --dry-run
python -m mylittleharness --root $TargetRoot init --apply --project "My Project"
python -m mylittleharness --root $TargetRoot check
python -m mylittleharness --root $TargetRoot repair --dry-run
python -m mylittleharness --root $TargetRoot detach --dry-run
```

If the console script is installed, the same target-root command can be shorter:

```bash
mylittleharness --root /path/to/target check
```

Apply modes stay explicit and target-bound. Use `repair --apply`, `detach --apply`, or advanced apply rails only after the matching dry-run names the expected target repository and write boundary. Advanced diagnostics exist, but they are not required first-contact steps. `meta-feedback` is opt-in and is not part of the default start pass.

## Command Shape

- `init` attaches MyLittleHarness scaffold to an explicit target repository.
- `check` runs read-only orientation, validation, drift, and boundary reporting.
- `repair` previews or applies one bounded repair class at a time.
- `detach` creates a marker-only detach posture without deleting authority files.

`check` includes compact link/docmap/stale-root/rule-context/remainder drift reporting, live `product_source_root` validation, installed-console command-surface lag warnings for advanced lifecycle sentinels, Deep Research rubric recovery hints, and primary instruction-surface size warnings. `check --deep` adds links, context, hygiene, and report-only grain diagnostics. Grain diagnostics inspect active-plan slice size, roadmap mapping/hygiene, and archived-plan calibration samples as advisory signals only. `check --focus archive-context` audits archived-plan context coverage, missing archive targets, reconstructed source evidence, stale source references, and suspect incomplete-context archives without writing files. `check --focus route-references` inventories missing route references and reports per-class bounded recovery actions with next safe commands, while keeping repair, archive recreation, metadata retargeting, lifecycle movement, and generated-cache rebuilding explicit. `check --focus agents` runs the report-only reconcile/drift view for route, source, evidence, claim, approval, and worker-space residue posture. Deeper section-size detail remains in advanced `context-budget` and `doctor` diagnostics. `check --focus validation|links|context|hygiene|grain|archive-context|route-references|agents` runs one focused read-only diagnostic.

Advanced and compatibility commands remain available for recovery and deeper review: `status`, `validate`, `audit-links`, `context-budget`, `doctor`, `preflight`, `suggest --intent`, `intelligence`, `projection`, `snapshot`, `adapter`, `semantic`, bare `evidence`, `evidence --record`, `reconcile`, `closeout`, `bootstrap --inspect`, `bootstrap --package-smoke`, explicit `research-import`, explicit `research-distill`, explicit `research-compare`, explicit `writeback`, explicit `transition`, explicit `incubate`, opt-in `meta-feedback`, explicit `plan`, explicit `memory-hygiene`, and explicit `roadmap`.

Focused write rails include `incubate --fix-candidate` for standard MLH debt capture, opt-in `meta-feedback --to-root <mlh-dev-root>` for routing observed-root feedback into a central incubation note plus managed cluster metadata, `meta-feedback --dedupe-to <canonical-id>` for appending related observations to a canonical friction cluster, `evidence --record --dry-run|--apply` for one source-bound agent run record in a live operating root, explicit `roadmap --dry-run|--apply` for reviewed promotion of mature clusters into accepted work, `research-distill` quality gates for provisional-vs-planning-ready distillates, `research-compare --archive-sources --repair-links` for reviewed multi-source comparison plus archive-before-removal source cleanup, local Python dependency-closure gap or ok reports, `roadmap normalize --dry-run|--apply` for canonical roadmap item-block housekeeping, `memory-hygiene --archive-covered` with explicit Entry Coverage for terminal incubation cleanup, `writeback --from-active-plan` with project-state closeout authority fallback, and `writeback --product-source-root <path>` for validated clean product source metadata. `memory-hygiene --dry-run --scan` emits reviewable cleanup proposal details for covered incubation candidates, including candidate ids, archive targets, exact link-repair files, a proposal token, and per-candidate dry-run/apply command shapes; the scan itself still has no matching apply mode. `suggest --intent "phase closeout handoff"` and matching writeback refusals surface the reviewed two-step sequence for phase evidence handoff followed by archive closeout replacement, without passing explicit `--active-phase` to the archive command.

## Safety Model

Any file-reading, shell-capable agent can use MyLittleHarness from repo-visible files plus CLI reports. A portable start pass reads `AGENTS.md`, `.codex/project-workflow.toml`, and `project/project-state.md`; it reads `project/implementation-plan.md` only when `plan_status = "active"` or the operator asks about plan, phase, or closeout. When present, `active_phase` and `phase_status` are first-class continuation pointers.

`status`/`check` report a compact lifecycle route table for live roots, including state, active-plan, optional `project/roadmap.md` sequencing route, incubation, research, stable specs, decision/do-not-revisit records, ADR records, optional `project/verification/*.md` proof/evidence records, closeout/writeback, archive, and docs routing. `intelligence --focus routes` prints the same read-only route table.

Route output is advisory only; it cannot approve mutation, repair, closeout, archive, commit, rollback, or lifecycle decisions. `current-phase-only`, `auto_continue`, `stop_conditions`, `active-plan-auto-continue`, and writeback-phase-execution-boundary diagnostics make sure verification success alone does not silently authorize the next phase, archive, commit, or next slice. For an explicit same-plan phase advance, `writeback --apply --active-phase <next-phase> --phase-status pending` can complete the previously active phase body and move Current Focus to the next pending phase in one lifecycle writeback; that report still cannot approve closeout, archive, roadmap done-status, next-plan opening, staging, or commit.

Codex skills, IDE-native rules, MCP clients, shell aliases, preflight wrappers, hooks, and CI may wrap this flow. They must not store the only copy of accepted decisions, current focus, docs decisions, repair approval, verification, or closeout evidence.

## Product And Target Roots

MyLittleHarness keeps a strict product/target split:

- the product repository owns reusable MLH source, tests, product docs, package metadata, and compatibility fixtures
- the target repository owns its own operating memory, state, plans, research, closeout evidence, and generated projection boundary
- product-source compatibility fixtures are not live operating memory

For live operating roots, product-source target artifact references can be classified as product-target navigation metadata instead of missing operating-root files. That lets `target_artifacts` point at clean product source while the serviced operating root keeps only operating memory and generated output.

## Generated Projections

The owned generated boundary is:

```text
.mylittleharness/generated/projection/
```

It may contain rebuildable JSON artifacts such as `manifest.json`, `sources.json`, `links.json`, `backlinks.json`, `fan-in.json`, `relationships.json`, `summary.json`, source hashes, and the optional SQLite FTS/BM25 search index at `search-index.sqlite3`.

These projections are source-bound, stale-checked, disposable, and subordinate to repo-visible files. They can accelerate route discovery, backlinks, relationship graph inspection, path search, and source-verified full-text search. They must not hold accepted decisions, current focus, `plan_status`, active plan identity, durable closeout evidence, repair approval, archive actions, commit actions, or lifecycle authority.

Deleting generated projection output must not change what the repository is allowed to treat as true.

## Development And Verification

This repository is the reusable MyLittleHarness product source. It contains `pyproject.toml`, the stdlib build backend under `build_backend/`, source under `src/mylittleharness/`, tests under `tests/`, product docs under `docs/`, and minimal compatibility fixtures under `.codex/`, `.agents/`, and `project/`.

The package baseline is stdlib-first:

- Python `>=3.11`
- no runtime dependencies in `pyproject.toml`
- empty build-system requirements
- console script declaration: `mylittleharness = mylittleharness.cli:main`

Useful local verification commands:

```bash
python -m unittest discover -s tests
python -m mylittleharness --root . check
python -m mylittleharness --root . bootstrap --package-smoke
```

`bootstrap --package-smoke` uses temporary source, build, install, and virtual-environment locations outside the product root. It verifies package metadata, import/version behavior, and the `mylittleharness` console script. It does not publish packages, change PATH, write user config, install hooks, add CI, mutate workstation state, change target roots, or make generated package output authoritative.

## Status

The current productization posture is a local 1.0.0 release candidate. The package version is `1.0.0`, and the reusable docs, stdlib package posture, compatibility fixtures, and verification matrix describe the direct `MyLittleHarness -> target repository` product model.

This is a local release-candidate posture, not a claim of package-index publication, global installation, production adoption, or workstation mutation.

The local release checklist is:

- package metadata and runtime version agree on `1.0.0`
- the stdlib build backend remains self-contained and requires no build-time dependency download
- top-level help foregrounds only `init`, `check`, `repair`, and `detach`
- bytecode-disabled unit tests pass
- `validate`, `check`, `audit-links`, and `doctor` complete with only expected advisory findings
- `bootstrap --package-smoke` passes from temporary source/build/install locations outside the product source checkout
- product hygiene finds no active plans, research intake, archived plans, package debris, generated validation artifacts, logs, caches, local databases, pycache, repair snapshots, or build output in this product tree
- product-boundary wording keeps the shipped runtime model direct, rejects standalone `bootstrap --apply`, and keeps publication, signing, global install, PATH/profile/user-config mutation, and workstation adoption outside normal correctness

Wheel, build, and install artifacts are verification outputs only unless a later publication plan accepts a durable artifact retention and signing policy.

## Non-Goals

- no hidden control plane
- no daemon, scheduler, queue, dashboard, or swarm as a correctness dependency
- no autonomous broad repair loop
- no generated truth
- no generated evidence database as durable authority
- no mandatory MCP, hooks, CI, IDE, browser, or adapter dependency
- no broad rollback automation or cleanup by implication
- no package publishing, global install, PATH/profile edits, user-config mutation, or workstation mutation as part of the current product surface
- no product-root storage of operating memory, plans, research, archives, generated validation reports, local databases, package artifacts, pycache, or runtime residue

## Docs Map

Start at `docs/README.md` for the deeper documentation spine.

- `docs/architecture/product-architecture.md` explains the architecture thesis and product gates.
- `docs/architecture/layer-model.md` explains the authority, lifecycle, projection, adapter, substrate, and product layers.
- `docs/specs/authority-and-memory.md` explains authority and memory placement.
- `docs/specs/product-boundary.md` explains the product repository and target repository boundary.
- `docs/specs/attach-repair-status-cli.md` carries the detailed CLI, repair, detach, and diagnostic contracts.
- `docs/specs/generated-state-and-projections.md` explains generated projection boundaries.
- `docs/specs/context-and-ceremony-budget.md` explains the start-pass and ceremony budget.
- `docs/specs/metadata-routing-and-evidence.md` explains docs decisions, routing, and evidence rules.
- `docs/specs/generated-state-search-and-sqlite.md` explains search and SQLite projection details.
- `docs/specs/adapter-boundary.md` explains optional integration boundaries.

## Docs Decisions

Docs decision values are `updated`, `not-needed`, and `uncertain`. A docs decision is required when behavior, CLI usage, configuration, setup, contract meaning, permissions, output shape, UX/copy, terminology, rollout, migration, or other user-facing meaning changes. Closeout facts live in the marked `project/project-state.md` writeback block; active-plan closeout bullets are derived copies, and `writeback --from-active-plan` may fall back to complete matching project-state closeout authority when the active plan has no explicit closeout section. Read-only `closeout` reports ignore project-state closeout blocks whose `plan_id`, `active_plan`, or `archived_plan` identity does not match the current lifecycle target, then prefer active-plan fields instead of emitting stale trailer suggestions. For phase-only ready-for-closeout handoff, `docs_decision = uncertain` with `phase_status = complete` may replace mismatched stale closeout facts with current plan identity while keeping closeout language provisional.

Use `.agents/docmap.yaml`, `audit-links`, `check`, relevant specs, and observed diff evidence as portable inputs. no Codex skill or generated docs-impact report is required for v1.
