# Authority And Memory Spec

## Purpose

This spec defines how MyLittleHarness separates product authority, operating memory, compatibility fixtures, and future generated views.

## Authority Model

MyLittleHarness authority is file-first. Accepted decisions, current focus, plan status, stable rules, and carry-forward fates must be recoverable from repo-visible artifacts.

Product docs under `docs/...` describe reusable architecture and product contracts. They do not operate the current workflow by themselves.

The target repository owns active focus, current plan status, research intake, and closeout evidence for the repository MyLittleHarness is servicing. The product repository owns reusable source, tests, and product documentation. Legacy reference material is opened only for a named blocker.

Live-root route discovery is reportable helper context, not a new authority layer. `status`, `check`, and `intelligence --focus routes` may print a compact lifecycle route table for live operating roots so agents can place state, active plans, optional roadmap sequencing, incubation, research, specs, decision/do-not-revisit records, ADR records, verification through the active-plan block and optional `project/verification/*.md` proof/evidence records, closeout/writeback, archives, and docs routing without growing `AGENTS.md` into a dense manual. `intelligence --focus routes` also reports deterministic present-surface classification from the product route registry, mapping discovered repo-visible files to routes such as state, active-plan, roadmap, incubation, research, stable-specs, docs-routing, product-docs, archive, decisions, ADRs, verification, generated-cache, or operating-guardrails. `project/roadmap.md` may sequence accepted work between incubation and one active implementation plan, but it is not part of the mandatory start path and cannot approve repair, closeout, archive, commit, rollback, or lifecycle decisions. `status` and `check` also summarize first-class lifecycle pointers so `phase_status = complete` is visible as "implementation work is not pending" and ready for explicit closeout/writeback without approving archive, roadmap done-status, next-slice movement, or manual commit. Product-source fixtures must not present that table as live memory, must not present discovered surface inventory as live memory, and must not present the continuation summary as live memory; route output cannot approve mutation, repair, closeout, archive, commit, or lifecycle decisions.

Read-only route metadata validation is also live-root-only. `validate`, `check`, and `check --focus validation` may warn about malformed lifecycle frontmatter relationship fields on routed roadmap, research, incubation, stable-spec, decision, ADR, and verification artifacts, including unsafe root-relative paths, missing archive targets, stale active relationship references, and destination-route mismatches. Strict fields such as `promoted_to` and `archived_to` remain path-only; flexible relationship fields may carry prose labels, but only path-like values are validated as local targets. Roadmap relationship fields such as `related_roadmap`, `source_roadmap`, and `archived_plan` are path-checked when present; the separate hidden `roadmap --dry-run|--apply` rail is the only implemented roadmap write path. These `route-metadata-*` findings are advisory diagnostics; they do not create a repair class, approve archive movement, or authorize closeout, commit, rollback, or lifecycle decisions.

## Memory Rule

An operating root has one mutable project memory surface for active focus and canonical pointers.

The product tree must not introduce a second mutable memory tree. The fixture `project/project-state.md` inside a product source checkout is compatibility data for CLI/tests, not operating memory.

The final product model is MyLittleHarness attached to a target repository, with accepted project truth recoverable from that repository's visible files.

Read-only tools may recover lifecycle pointers from a prose-style operating-root `project/project-state.md` when it contains explicit assignment lines such as `plan_status = "active"`, `active_plan = "project/implementation-plan.md"`, `active_phase = "Phase 2"`, and `phase_status = "in_progress"`. This fallback is an analyzer recovery aid. The only mutating bridge from that posture is the bounded `state-frontmatter-repair` class, which snapshots default-path state bytes and prepends deterministic frontmatter before any other repair class can run.

Read-only drift tools may also compare explicit delivered/current capability tokens against future/backlog/remainder wording in operating-memory and research surfaces. That remainder-drift signal is advisory memory hygiene only: it can point to stale backlog wording, but it cannot approve plan edits, closeout, archive, commit, repair, cleanup, or any lifecycle mutation.

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
- roadmaps under `project/roadmap.md`
- project-state used as operating memory
- decision/do-not-revisit records under `project/decisions`
- ADR records under `project/adrs`
- research/history/raw intake
- archived plans
- archive-under-study material
- workflow execution state
- runtime/demo debris
- reports, logs, caches, local databases, generated validation artifacts, package archives, build directories, wheels, egg-info, or pycache
- hidden queues, schedulers, dashboards, or control-plane state

## Compatibility Fixtures

Files under `.codex`, `.agents`, and `project` in the product source checkout are compatibility fixtures unless a later explicit product plan changes their role. They support validation and tests; they do not outrank product docs or operating-root workflow authority.

Clean product specs belong under `docs/specs/...`.

## Mutation Authority

An apply flag does not create authority by itself. Mutating CLI behavior may write only repo-visible files inside an explicitly targeted live operating root, and only when the target root, target path, and operation have product-contract authority.

Multi-target apply rails must prepare all replacement bytes before changing live files, then apply bounded file transactions with temporary backups. If a late target replacement fails, completed target writes are rolled back when possible; if rollback cleanup itself fails, the command must report explicitly recoverable residue instead of treating partial mutation as lifecycle approval.

`init --apply` is the primary implemented write gate for attach behavior, with `attach --apply` preserved as the compatibility spelling. Its allowed scope is create-only scaffold setup plus absent `.codex/project-workflow.toml` and `project/project-state.md` from explicit product templates, followed by attach-time disposable generated projection setup under `.mylittleharness/generated/projection/`. Creating `project/project-state.md` requires an operator-provided project name; the CLI must not infer authoritative project identity from a folder name. Attach apply refuses product-source compatibility fixtures, fallback/archive or generated-output roots, symlink path segments, non-directory scaffold conflicts, non-file template conflicts, template content mismatches, and generated-projection boundary conflicts before writing. SQLite FTS5 or index-build unavailability is degraded generated-output posture, not attach failure.

`repair --apply` is the implemented limited repair write gate. Its allowed scope is snapshot-protected `project/project-state.md` frontmatter prepending for default-path prose operating state, absent eager scaffold directory creation, create-only `AGENTS.md` creation when validation reports a missing required operator contract, create-only `.agents/docmap.yaml` creation when validation reports a missing required docmap, create-only `project/specs/workflow/*.md` restoration when validation reports missing stable spec fixtures, and snapshot-protected `.agents/docmap.yaml` route repair in a live operating root that already has readable workflow-core manifest and strict workflow-core project-state frontmatter authority. It does not create or rewrite manifest, active plans, existing AGENTS contracts, existing stable specs, archives, research files, generated reports, caches, local databases, broad docmap structure beyond the deterministic create template, malformed or partial state frontmatter, or workflow execution surfaces.

`detach --apply` is the implemented marker-only detach write gate. Its allowed scope is create-only `.mylittleharness/detach/disabled.json` in an eligible live operating root with readable default manifest and state authority. The marker is informational evidence only; it does not rewrite authority files, close active plans, delete generated projections, clean snapshots, archive research, mutate Git/config/hooks/CI/package/workstation state, or approve lifecycle decisions.

`writeback --apply` is the implemented closeout and lifecycle write gate for live operating roots. Its allowed scope is the MLH closeout writeback block in `project/project-state.md`, selected lifecycle frontmatter, the marked Current Focus block derived from lifecycle frontmatter, matching active-plan derived copies in explicit closeout summary/facts/fields sections, optional same-request roadmap item sync, the default active-plan archive move under `project/archive/plans/`, and operating-memory compaction when the live state file exceeds the default 250-line threshold. Closeout blocks record plan identity with `plan_id`, `active_plan`, and `archived_plan` when those values are available; partial closeout writeback may carry existing facts only when that recorded identity matches the current active or archived plan, otherwise it refuses unless complete replacement facts are supplied in the same request. Lifecycle-only phase-pointer writeback does not copy prior closeout facts into a new active plan, and optional roadmap sync uses only same-request closeout facts plus the active or archived plan path. `plan --apply` may run the same compaction after its own lifecycle state write, and `writeback --apply --compact-only` exposes only that compaction rail without editing closeout facts, lifecycle frontmatter, active-plan copies, or roadmap fields. Compaction may move older state history into `project/archive/reference/project-state-history-YYYY-MM-DD*.md`, but the archive is reference material only; current `project/project-state.md` remains operating memory authority. Read-only context warnings cannot trigger this write path by themselves.

`plan --apply` is the implemented deterministic active-plan scaffold write gate for live operating roots. Its allowed scope is the default `project/implementation-plan.md` plus selected lifecycle frontmatter in `project/project-state.md`: `operating_mode`, `plan_status`, `active_plan`, `active_phase`, and `phase_status`, along with the marked Current Focus block derived from those values. With `--roadmap-item`, it may also update the requested roadmap item plus roadmap-slice `covered_roadmap_items` to record the active plan relationship. It accepts explicit title/objective/task input, starts generated plans with `docs_decision = "uncertain"`, and records current-phase-only execution metadata: `execution_policy`, `auto_continue`, `stop_conditions`, and `closeout_boundary`. The default is `execution_policy = current-phase-only` and `auto_continue = false`, so the operator executes only the current active phase and stops after repo-visible evidence/state unless a later explicit contract opts into auto-continuation with stop-condition coverage. It refuses product-source fixtures, fallback/archive roots, ambiguous roots, malformed state frontmatter, non-default plan paths, stale inactive plan files, unsafe path targets, active-plan conflicts unless `--update-active` is supplied, invalid requested roadmap links, and destructive recovery instructions before writing. Generated plans are execution scaffolds, not LLM planning, hidden memory, repair approval, closeout approval, archive approval, commit approval, or rollback authority.

When `--roadmap-item` finds advisory slice metadata, plan output may also include bounded synthesis evidence: bundle rationale, split boundary, target-artifact pressure, and phase pressure. That evidence can help an operator see why a plan covers multiple roadmap items, but it does not change the write boundary or promote roadmap output into lifecycle authority.

`roadmap --apply` is the implemented accepted-work roadmap item write gate for live operating roots. Its allowed scope is one managed `###` item block inside an existing `project/roadmap.md` with a `## Items` section. It accepts explicit add/update fields, known roadmap statuses, docs decision values, relationship paths, dependencies, supersession links, verification summary, and carry-forward text; dry-run names the target file, action, item id, and changed fields. `plan --roadmap-item` and `writeback --roadmap-item` reuse that boundary to update explicit item relationships or same-request closeout summaries without broad roadmap rewriting; plan opening can batch the requested item plus roadmap-slice `covered_roadmap_items`, and archive closeout can batch the requested item plus active-plan `covered_roadmap_items` through one transaction. Apply refuses product-source fixtures, fallback/archive roots, ambiguous roots, malformed state frontmatter, missing or malformed roadmap files, duplicate ids, invalid statuses, invalid docs decisions, unsafe path targets, symlink or parent path conflicts, incompatible relationship destinations, missing related item ids, and self-relations before writing. Roadmap output is sequencing evidence only, not repair approval, closeout approval, archive approval, commit approval, rollback authority, or lifecycle approval.

`memory-hygiene --dry-run --scan` is the implemented read-only relationship hygiene and text-input audit report for live operating roots. It can report stale links, missing reciprocal relationships, orphan incubation notes, CLI text-field posture, `## Entry Coverage` completeness for mixed incubation notes, heuristic split suggestions, and coverage-aware archive candidates. The report writes no files and cannot make semantic guesses authoritative. `writeback --apply` may archive a source incubation note only when closeout/archive was explicitly requested and structural coverage is complete: single-entry notes can be covered by the closeout chain, while mixed notes need terminal Entry Coverage bullets for every dated entry and still fail closed on open questions, unchecked tasks, malformed coverage, unsafe paths, or archive conflicts. Writeback closeout fields are one-line summaries; multiline detail belongs in the active plan or `project/verification/*.md` and is refused on those flags before writes.

Product-source compatibility fixtures are never live operating memory. Apply modes must refuse product-source roots and fixtures with exit code `2`; dry-run modes may continue to report no-op or review-only proposals.

Rollback is not implied by the memory model. Any overwrite, delete, rename, normalization, resync, archive, active-plan mutation, or lifecycle decision operation requires an explicit rollback or snapshot contract before implementation.

Repair snapshots are safety evidence, not operating memory. The repair snapshot boundary is `.mylittleharness/snapshots/repair/` inside an explicitly targeted live operating root, and it may contain only pre-repair file copies plus inspectable metadata for a named repair class. `snapshot --inspect` is a read-only report over that boundary; it can report metadata readability, copied-file/hash/path consistency, target-root confinement, current-target posture, retention, manual rollback instructions, and non-authority wording, but it cannot authorize repair, rollback, cleanup, closeout, archive, commit, lifecycle changes, or future mutations. `repair --dry-run` may report a no-write `state-frontmatter-repair` snapshot plan for default-path prose `project/project-state.md`, create-only plans for a missing required `AGENTS.md`, missing required `.agents/docmap.yaml`, or missing stable workflow spec fixtures, and a no-write `.agents/docmap.yaml` route-repair snapshot plan with deterministic preview paths, metadata fields, copied-file paths, refusal or skip posture, manual rollback posture, and validation commands. Snapshot metadata cannot authorize repair, closeout, archive, commit, plan lifecycle changes, or future mutations.

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
