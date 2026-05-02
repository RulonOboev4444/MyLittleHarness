# MyLittleHarness

MyLittleHarness is a portable, file-first harness for adding lightweight workflow memory, validation, repair, and read-only diagnostics to a target repository.

This repository is the reusable MyLittleHarness product source. It contains the Python package, tests, product docs, and the minimal compatibility fixtures used to validate the CLI against workflow-shaped roots.

## What This Contains

- `pyproject.toml`, `build_backend/`, `src/mylittleharness/`, and `tests/` for the stdlib-first Python package.
- `README.md` and `AGENTS.md` as the product entrypoint and operator contract.
- `docs/` as the reusable product architecture and specification home.
- `.codex/project-workflow.toml`, `.agents/docmap.yaml`, `project/project-state.md`, and `project/specs/workflow/*.md` as compatibility fixtures for CLI/tests.

The compatibility fixtures are not live working memory. They must not be used to open plans, preserve research, archive history, or operate the workflow from this product tree.

## Analyzer CLI

The visible CLI is deliberately small: `init`, `check`, `repair`, and `detach`.

- `init --dry-run` previews attach/create work for a target repository.
- `check` reports status, validation, and compact drift signals without writing files.
- `repair --dry-run` previews bounded repair classes before any apply mode.
- `detach --dry-run` previews marker-only detach behavior for eligible live operating roots.

Advanced and compatibility commands remain available for recovery and deeper review, including `status`, `validate`, `doctor`, `audit-links`, `context-budget`, `tasks --inspect`, `bootstrap --inspect`, `bootstrap --package-smoke`, `intelligence`, `projection`, `semantic`, `adapter`, `snapshot`, `preflight`, `evidence`, `closeout`, explicit `writeback`, explicit `incubate`, explicit `plan`, and explicit `memory-hygiene`; they are not required first-contact steps.

`check` includes compact link/docmap/stale-root/rule-context/remainder drift reporting. `check --deep` adds links, context, and hygiene diagnostics, while `check --focus validation|links|context|hygiene` runs one focused read-only diagnostic through the same front door. The primary instruction-surface size warnings cover start-pass files such as `README.md`, `AGENTS.md`, `.agents/docmap.yaml`, `.codex/project-workflow.toml`, `project/project-state.md`, and any active plan. Deeper section-size detail remains in advanced `context-budget` and `doctor` diagnostics.

## First-Run Operator Path

Any file-reading, shell-capable agent can use MyLittleHarness from repo-visible files plus CLI reports. The portable start pass reads `AGENTS.md`, `.codex/project-workflow.toml`, `project/project-state.md`, and `project/implementation-plan.md` only when `plan_status = "active"` or the user asks about plan, phase, or closeout. Active plans can record `active_phase` and `phase_status` in `project/project-state.md` so continuation does not depend on prose inference; MLH write rails refresh a marked Current Focus block from those lifecycle fields. Live-root `status`/`check` summarize whether implementation work is pending or the next action is explicit closeout/writeback, archive, or manual commit. `status`/`check` report a compact lifecycle route table for live roots, covering state, active plans, incubation, research, stable specs, decision/do-not-revisit records, verification, closeout/writeback, archive, docs routing, and future optional lanes. `intelligence --focus routes` prints the same read-only route table without the broader intelligence report. Route output is advisory only; it cannot approve mutation, repair, closeout, archive, commit, or lifecycle decisions. `.agents/docmap.yaml` can route docs reading when present, but routing metadata is not authority by itself.

The shortest safe first run is:

1. Use this product source checkout with `PYTHONPATH` pointing at `src`.
2. Optionally verify local package behavior with `bootstrap --package-smoke`.
3. Point `--root` at the target repository and use `init`, `check`, `repair`, and `detach`.

For PowerShell:

```powershell
$ProductRoot = (Resolve-Path .).Path
$TargetRoot = $env:MLH_TARGET_ROOT
$env:PYTHONPATH = Join-Path $ProductRoot "src"
python -m mylittleharness --root $ProductRoot bootstrap --package-smoke
python -m mylittleharness --root $TargetRoot init --dry-run
python -m mylittleharness --root $TargetRoot check
python -m mylittleharness --root $TargetRoot repair --dry-run
python -m mylittleharness --root $TargetRoot detach --dry-run
```

Apply modes stay explicit and target-bound: use `init --apply --project <name>`, selected `repair --apply` classes, explicit `plan --apply`, explicit `writeback --apply`, explicit `incubate --apply`, explicit `memory-hygiene --apply`, or `detach --apply` only after dry-run output names the expected target repository and write boundary. Hidden `incubate --dry-run|--apply --topic <topic> --note <note>` creates or appends the same-topic canonical `project/plan-incubation/<safe-topic-slug>.md` note in eligible live operating roots only; it accepts explicit fields, does not infer idea quality or meaning, and refuses product fixtures, unsafe roots, path-looking topics, path conflicts, and malformed state frontmatter before writing. Hidden `plan --dry-run --title <title> --objective <objective>` and `plan --apply --title <title> --objective <objective> [--task <text>] [--update-active]` create or replace the default active `project/implementation-plan.md` scaffold in eligible live operating roots only; they use explicit task input, set lifecycle frontmatter and the marked Current Focus block in `project/project-state.md`, start `docs_decision` as `uncertain`, refuse active-plan conflicts unless `--update-active` is supplied, and do not infer architecture or call an LLM. Hidden `memory-hygiene --dry-run|--apply --source <rel> [--promoted-to <rel>] [--archive-to <rel>] [--repair-links]` updates only MLH-owned research/incubation lifecycle metadata, explicit reference archive targets, and exact source-path link repairs in eligible live operating roots; it refuses product fixtures, unsafe roots, path escapes, symlinks, destination conflicts, and fuzzy or semantic link rewriting before writing. Hidden `writeback --dry-run --archive-active-plan` and `writeback --apply --archive-active-plan` provide the bounded live-root plan archive rail: they move the default active plan to `project/archive/plans/`, set `plan_status` to `none`, clear `active_plan`, update `last_archived_plan`, and refresh the marked Current Focus block without staging, committing, cleaning archives, or repairing unrelated files. A normal `writeback --apply --phase-status complete` also uses that archive rail automatically when the planned closeout facts include final `docs_decision`, `state_writeback`, `verification`, and `commit_decision` values; if the archive path is unsafe or conflicting, apply is refused before writes. Whenever `writeback --dry-run|--apply` would leave live `project/project-state.md` above the default 250-line operating-memory threshold, MLH treats compaction as post-writeback hygiene for live operating roots only: dry-run reports whether compaction would run, skip, or refuse plus the reference archive target and section plan; apply archives old state history to `project/archive/reference/project-state-history-YYYY-MM-DD*.md` after the state writeback succeeds. A successful `init --apply` also builds disposable generated projection artifacts and the SQLite FTS/BM25 index under `.mylittleharness/generated/projection/` so read-only `intelligence --query` can use full-text search immediately when SQLite FTS5 is available.

Codex skills, IDE-native rules, MCP clients, shell aliases, preflight wrappers, hooks, and CI may wrap this flow, but they are optional helpers. They must not store the only copy of accepted decisions, current focus, docs decisions, repair approval, verification, or closeout evidence.

## Install And Verification

The supported local paths are:

- Source checkout usage: set `PYTHONPATH` to `src` and run `python -m mylittleharness`.
- Package smoke: run `python -m mylittleharness --root <product-checkout> bootstrap --package-smoke`.
- Readiness inspection: use `bootstrap --inspect` for no-write evidence about interpreter context, package metadata, and console-script discovery.

`bootstrap --package-smoke` uses temporary source, build, install, and virtual-environment locations outside the product root. It verifies package metadata, import/version behavior, and the `mylittleharness` console script. It does not publish packages, change PATH, write user config, install hooks, add CI, mutate workstation state, change target roots, or make generated package output authoritative.

Package-index publication, signed artifacts, global installation, PATH/profile edits, user-config mutation, and mutating workstation adoption remain separate future decisions. Standalone `bootstrap --apply` is not a product surface.

## Product Readiness

The current productization posture is a local **1.0.0 release candidate**. The package version is `1.0.0`, and the reusable docs, stdlib package posture, compatibility fixtures, and verification matrix describe the direct `MyLittleHarness -> target repository` product model.

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

Optional power-ups such as semantic retrieval, generated evidence manifests, quality gates, adapter packs, hook/CI integration, package publishing, mutating workstation adoption, operating-root mutation, additional repair classes, rollback automation, and snapshot cleanup require later scoped contracts, tests, docs, degraded/offline behavior, and explicit non-authority wording before they can ship.

## Docs Map

Start at `docs/README.md` for the product documentation spine.

- `docs/architecture/product-architecture.md` explains the architecture thesis and product gates.
- `docs/architecture/layer-model.md` explains the authority, lifecycle, projection, adapter, substrate, and product layers.
- `docs/specs/operating-root.md` explains the operating-root and fallback-root boundary.
- `docs/specs/authority-and-memory.md` explains authority and memory placement.
- `docs/specs/product-boundary.md` explains the reusable product-source boundary.
- `docs/specs/attach-repair-status-cli.md` carries the detailed CLI, repair, detach, and diagnostic contracts.
- `docs/specs/metadata-routing-and-evidence.md` carries docs routing, docs decisions, and evidence rules.
- `docs/specs/generated-state-and-projections.md` and `docs/specs/generated-state-search-and-sqlite.md` explain generated projection boundaries.
- `docs/specs/adapter-boundary.md` explains optional integration boundaries.

## Docs Decisions

Docs decision values are `updated`, `not-needed`, and `uncertain`. A docs decision is required when behavior, CLI usage, configuration, setup, contract meaning, permissions, output shape, UX/copy, terminology, rollout, migration, or other user-facing meaning changes. The current MLH-owned closeout authority is the marked closeout writeback block in `project/project-state.md`; active-plan frontmatter and exact active-plan closeout field bullets are synchronized derived copies when they exist. `writeback --apply` updates those derived copies in the same apply, including `docs_decision`, `state_writeback`, `verification`, `commit_decision`, residual risk, carry-forward, and lifecycle frontmatter such as `active_phase` and `phase_status`; when `phase_status` is written, an existing active-plan frontmatter `status` copy is synchronized to the same value, the matching active-phase body `- status:` line is synchronized too, and the marked Current Focus block in `project/project-state.md` is refreshed from lifecycle frontmatter. The body value for lifecycle `phase_status = complete` is canonicalized as `done` so generated and hand-maintained phase blocks share the same completed marker. `writeback --apply --archive-active-plan` preserves or updates supplied closeout writeback facts while closing the active lifecycle pointer and archiving the default active plan; the same archive close happens automatically for `--phase-status complete` when final closeout facts are present, then may compact oversized live operating memory by preserving frontmatter, current focus, repository roles, short notes, the latest relevant update, the current closeout writeback block, and an archive pointer. Read-only `check`/`validate` warnings can report stale or unsupported derived copies, complete-but-unarchived active plans, and phase body split-brain, but warnings are not repair, closeout, archive, commit, or lifecycle approval.

Use `.agents/docmap.yaml`, `audit-links`, `check`, relevant specs, and observed diff evidence as portable inputs. no Codex skill or generated docs-impact report is required for v1.

## Authority

Inside this product tree, `src/mylittleharness/`, `tests/`, `pyproject.toml`, and this README are product source surfaces. The workflow-shaped files under `.codex/`, `.agents/`, and `project/` are product compatibility fixtures for CLI/tests, not operational authority.

Generated projection artifacts and indexes under `.mylittleharness/generated/projection/` are disposable local output. Detach markers and repair snapshots do not belong in the product source tree.

Keep this repository focused on product source, tests, docs, and compatibility fixtures. Do not copy legacy context, runtime logs, research dumps, generated validation artifacts, active task plans, or closeout debris into it.

## Fresh Agent Start

1. Recover workflow context from the repository named by the current task.
2. Use this directory only as product source / target root.
3. Read `README.md`, `AGENTS.md`, and the relevant source/tests for local implementation work.
4. Read fixture workflow files only when changing CLI validation behavior or product compatibility fixtures.
