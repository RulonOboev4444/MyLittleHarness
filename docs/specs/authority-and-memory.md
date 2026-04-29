# Authority And Memory Spec

## Purpose

This spec defines how MyLittleHarness separates product authority, operating memory, compatibility fixtures, and future generated views.

## Authority Model

MyLittleHarness authority is file-first. Accepted decisions, current focus, plan status, stable rules, and carry-forward fates must be recoverable from repo-visible artifacts.

Product docs under `docs/...` describe reusable architecture and product contracts. They do not operate the current workflow by themselves.

The operating project root owns active focus, current plan status, research intake, and closeout evidence for the repository MyLittleHarness is servicing. The product source checkout owns reusable source, tests, and product documentation. Archive/evidence roots are opt-in historical lookup targets only.

## Memory Rule

An operating root has one mutable project memory surface for active focus and canonical pointers.

The product tree must not introduce a second mutable memory tree. The fixture `project/project-state.md` inside a product source checkout is compatibility data for CLI/tests, not operating memory.

The final product model is MyLittleHarness attached to a target repository, with accepted project truth recoverable from that repository's visible files.

Read-only tools may recover lifecycle pointers from a prose-style operating-root `project/project-state.md` when it contains explicit assignment lines such as `plan_status = "active"` and `active_plan = "project/implementation-plan.md"`. This fallback is an analyzer recovery aid. The only mutating bridge from that posture is the bounded `state-frontmatter-repair` class, which snapshots default-path state bytes and prepends deterministic frontmatter before any other repair class can run.

Read-only drift tools may also compare explicit delivered/current capability tokens against future/backlog/remainder wording in operating-memory and research surfaces. That remainder-drift signal is advisory memory hygiene only: it can point to stale backlog wording, but it cannot approve plan edits, closeout, archive, commit, repair, cleanup, switch-over, or any lifecycle mutation.

## Allowed Product Surfaces

The product source tree may contain:

- `README.md` and `AGENTS.md` orientation surfaces
- product docs under `docs/...`
- product source under `src/mylittleharness/...`
- tests under `tests/...`
- `pyproject.toml` and package metadata
- minimal compatibility fixtures under `.codex/`, `.agents/`, and `project/` while the CLI/tests need them

## Forbidden Product Memory

The product source tree must not contain:

- active implementation plans
- project-state used as operating memory
- research/history/raw intake
- archived plans
- archive-under-study material
- workflow execution state
- runtime/demo debris
- reports, logs, caches, local databases, generated validation artifacts, package archives, build directories, wheels, egg-info, or pycache
- hidden queues, schedulers, dashboards, or control-plane state

## Compatibility Fixtures

Files under `.codex`, `.agents`, and `project` in the product source checkout are compatibility fixtures unless a later explicit switch-over plan changes their role. They support validation and tests; they do not outrank product docs or operating-root workflow authority.

Clean product specs belong under `docs/specs/...`.

## Mutation Authority

An apply flag does not create authority by itself. Mutating CLI behavior may write only repo-visible files inside an explicitly targeted live operating root, and only when the target root, target path, and operation have product-contract authority.

`init --apply` is the primary implemented write gate for attach behavior, with `attach --apply` preserved as the compatibility spelling. Its first allowed scope is create-only scaffold setup plus absent `.codex/project-workflow.toml` and `project/project-state.md` from explicit product templates. Creating `project/project-state.md` requires an operator-provided project name; the CLI must not infer authoritative project identity from a folder name. Attach apply refuses product-source compatibility fixtures, fallback/archive or generated-output roots, symlink path segments, non-directory scaffold conflicts, non-file template conflicts, and template content mismatches before writing.

`repair --apply` is the implemented limited repair write gate. Its allowed scope is snapshot-protected `project/project-state.md` frontmatter prepending for default-path prose operating state, absent eager scaffold directory creation, create-only `AGENTS.md` creation when validation reports a missing required operator contract, create-only `.agents/docmap.yaml` creation when validation reports a missing required docmap, create-only `project/specs/workflow/*.md` restoration when validation reports missing stable spec fixtures, and snapshot-protected `.agents/docmap.yaml` route repair in a live operating root that already has readable workflow-core manifest and strict workflow-core project-state frontmatter authority. It does not create or rewrite manifest, active plans, existing AGENTS contracts, existing stable specs, archives, research files, generated reports, caches, local databases, broad docmap structure beyond the deterministic create template, malformed or partial state frontmatter, or switch-over surfaces.

`detach --apply` is the implemented marker-only detach write gate. Its allowed scope is create-only `.mylittleharness/detach/disabled.json` in an eligible live operating root with readable default manifest and state authority. The marker is informational evidence only; it does not rewrite authority files, close active plans, delete generated projections, clean snapshots, archive research, mutate Git/config/hooks/CI/package/workstation state, or approve lifecycle decisions.

Product-source compatibility fixtures are never live operating memory. Apply modes must refuse product-source roots and fixtures with exit code `2`; dry-run modes may continue to report no-op or review-only proposals.

Rollback is not implied by the memory model. Any overwrite, delete, rename, normalization, resync, archive, active-plan mutation, or switch-over operation requires an explicit rollback or snapshot contract before implementation.

Repair snapshots are safety evidence, not operating memory. The repair snapshot boundary is `.mylittleharness/snapshots/repair/` inside an explicitly targeted live operating root, and it may contain only pre-repair file copies plus inspectable metadata for a named repair class. `snapshot --inspect` is a read-only report over that boundary; it can report metadata readability, copied-file/hash/path consistency, target-root confinement, current-target posture, retention, manual rollback instructions, and non-authority wording, but it cannot authorize repair, rollback, cleanup, closeout, archive, commit, switch-over, lifecycle changes, or future mutations. `repair --dry-run` may report a no-write `state-frontmatter-repair` snapshot plan for default-path prose `project/project-state.md`, create-only plans for a missing required `AGENTS.md`, missing required `.agents/docmap.yaml`, or missing stable workflow spec fixtures, and a no-write `.agents/docmap.yaml` route-repair snapshot plan with deterministic preview paths, metadata fields, copied-file paths, refusal or skip posture, manual rollback posture, and validation commands. Snapshot metadata cannot authorize repair, closeout, archive, commit, switch-over, plan lifecycle changes, or future mutations.

Snapshot retention is manual-first. MyLittleHarness must not silently delete or rotate repair snapshots; a later cleanup command would need its own dry-run, refusal rules, and product contract. Product-source compatibility fixtures must refuse snapshot creation, and any snapshot directory inside a product source checkout is product debris rather than compatibility data.

## Future Promotion Gates

Before product code or CLI behavior can rely on this authority model, a later scoped plan must define:

- command or module interface
- read-only versus mutating behavior
- fixture handling
- snapshot/rollback handling for any existing-content mutation
- validation output
- failure behavior
- tests
- docs cascade and closeout evidence

