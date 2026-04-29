# MyLittleHarness Product Documentation

This directory is the reusable product documentation spine for MyLittleHarness.
It explains the target architecture and product-facing boundaries without treating any operating root as product authority.

Reusable product docs describe MyLittleHarness serving an explicitly targeted repository directly. The intended chain is `MyLittleHarness -> target repository`.

## Reading Order

1. `architecture/target-architecture.md` - the product architecture thesis, design axioms, and future capability gates.
2. `architecture/layer-model.md` - the layer model that separates authority, lifecycle, projections, adapters, substrate, and product modules.
3. `specs/operating-root-and-switch-over.md` - the operating-root, fallback-root, and switch-over boundary.
4. `specs/authority-and-memory.md` - the authority and memory contract.
5. `specs/product-boundary.md` - the boundary between reusable product source and the operating root.
6. `architecture/clean-room-carry-forward.md` - the portable clean-room field manual for an operating project root.
7. `specs/context-and-ceremony-budget.md` - the context-loading and solo-first ceremony contract.
8. `specs/metadata-routing-and-evidence.md` - the metadata, routing, evidence, and doc-gardening contract.
9. `specs/generated-state-and-projections.md` - the generated-state, cache, index, and SQLite projection contract.
10. `specs/generated-state-search-and-sqlite.md` - the search, backlink, repo-map, telemetry, and SQLite projection contract.
11. `specs/attach-repair-status-cli.md` - the small visible CLI target, compatibility command surface, advanced diagnostics, and attach/repair mutation boundary.
12. `specs/adapter-boundary.md` - the adapter and optional integration boundary.

## Authority

These docs describe the reusable MyLittleHarness product architecture.
They do not create an operating workflow root inside a product source checkout.

In shipped product behavior, the operating root is the user's target repository after MyLittleHarness is attached.

Historical archive/evidence roots are opt-in lookup targets only. They are not default sources for fresh product-doc work.

This product tree may contain source, tests, the stdlib build backend, product docs, and minimal compatibility fixtures for CLI/tests.
It must not contain active plans, project memory, research/history/raw intake, archived plans, logs, caches, local databases, generated validation artifacts, or demo-workflow residue.

## Fixture Boundary

The workflow-shaped files under `.codex/`, `.agents/`, and `project/` in this product tree are compatibility fixtures for CLI reports and tests.
They are not the product architecture destination and are not operating memory.

Clean product architecture and specs belong under `docs/...`.

## Current Product Posture

MyLittleHarness is a solo-first, repo-native safety layer for AI-assisted development.
The product architecture keeps human-readable files as authority, uses metadata for routing, treats generated views as rebuildable projections, keeps analyzer reports separate from explicit apply mutation, defines repair snapshots as target-bound safety evidence for existing-content repair, and treats adapters as optional helpers that fail open to repo files.

The current productization posture is a local 1.0.0 release candidate at package version `1.0.0`. It is a verified product boundary for the direct `MyLittleHarness -> target repository` model, not a published package-index release, global installation flow, mutating workstation adoption step, or switch-over automation.

The target visible CLI is `init`, `check`, `repair`, and `detach`. The 1.0.0 implementation provides primary `init`, `check`, no-write `detach --dry-run`, marker-only `detach --apply`, and bounded `repair` classes for state frontmatter, docmap metadata, docmap routes, and create-only stable workflow spec fixtures. `check` includes compact check-level drift for docmap gaps, stale root-role wording, primary instruction-surface size warnings, and explicit delivered-vs-remainder token contradictions, while deeper section-size details remain advanced diagnostics. It also keeps explicit `bootstrap --package-smoke` package verification, unified read-only `intelligence --query` recovery search, optional read-only MCP projection access through `adapter`, read-only Git trailer suggestions to `closeout`, compatibility names such as `attach`, `status`, and `validate`, and advanced diagnostics including `doctor`, `preflight`, `context-budget`, `audit-links`, `intelligence`, `projection`, `semantic`, `evidence`, `closeout`, `snapshot`, `adapter`, `bootstrap`, and `tasks`. Those diagnostics remain read-only or explicitly bounded where implemented, but they are progressive-disclosure surfaces rather than the product front door. Top-level help foregrounds only `init`, `check`, `repair`, and `detach`; advanced/compatibility command-specific help and normal report stdout stay available and compatible.

The first-run operator path is deliberately shorter than the full diagnostic surface: run from the product source checkout with `PYTHONPATH=src`, optionally run `bootstrap --package-smoke` against the product checkout, then point `--root` at the target repository and start with `init --dry-run`, `check`, `repair --dry-run`, and `detach --dry-run`. Apply modes stay explicit and target-bound after dry-run review. `bootstrap --inspect`, `tasks --inspect`, switch-over, publication, global installation, PATH/profile edits, user-config mutation, hooks, CI, MCP clients, semantic providers, and workstation adoption are not prerequisites for first-run correctness.

The operating-root start pass is portable across agents that can read files and run shell commands. It starts from `AGENTS.md`, `.codex/project-workflow.toml`, `project/project-state.md`, and the active plan only when `plan_status = "active"` or the user asks about plan/phase/closeout. `check`, `status`, `validate`, `audit-links`, `evidence`, and `closeout` are CLI reports over those files; they do not require Codex skills, IDE-native skills, MCP clients, hooks, CI, or workstation adoption.

The current install and distribution story is local and bounded. Operators can run from a source checkout with `PYTHONPATH=src`, or verify the package path with `bootstrap --package-smoke`, which performs a temporary no-network install outside the product root and proves metadata, import/version, and the `mylittleharness` console script. `bootstrap --inspect` provides no-write adoption readiness evidence, including interpreter context, package metadata when run on the product checkout, and PATH discovery for the console script. Package-index publication, signed artifacts, global installation, PATH or profile edits, and user-config mutation remain separate future decisions, not prerequisites for normal correctness. Standalone `bootstrap --apply` and standalone switch-over automation are rejected as product surfaces.

Durable evidence direction is Git-native: Git trailers or commit metadata for Git repositories, and repo-visible Markdown closeout fields plus operator summaries for non-git roots. Read-only `closeout` reports may suggest paste-ready Git trailers from explicit closeout fields, and `evidence` reports may assemble source-bound candidates, but neither stages, commits, archives, repairs, approves lifecycle actions, or creates persistent generated evidence stores.

Docs decisions are explicit closeout facts, not skill-owned side effects. The accepted values are `updated`, `not-needed`, and `uncertain`; `uncertain` keeps closeout language provisional. A docs decision is required when behavior, CLI usage, configuration, setup, contract meaning, permissions, output shape, UX/copy, terminology, rollout, migration, or other user-facing meaning changes. `.agents/docmap.yaml`, `audit-links`, `check`, relevant specs, and observed diff evidence are the portable inputs.

The first owned generated-output boundary is `.mylittleharness/generated/projection/`. It may contain rebuildable JSON projection artifacts and the disposable SQLite FTS/BM25 index, including relaxed plain-text recovery search over source-verified rows; deleting it must not change accepted project truth. Semantic readiness/evaluation, adapter inspection/stdio serving, optional preflight templates, snapshot inspection, and bootstrap/package readiness remain advanced helper surfaces with explicit non-authority wording. `bootstrap --inspect` is the no-write workstation adoption readiness surface; it can report context but cannot adopt, install, or mutate workstation state. `bootstrap --package-smoke` verifies local install/import/console-script behavior only from temporary locations outside the product source root. Future semantic retrieval runtime, generated semantic output boundaries, generated evidence manifests, additional adapter families, publishing automation, mutation-capable VCS/GitHub behavior, additional hook/CI integrations, and switch-over procedures require later scoped plans before implementation. Future adoption, publication, or switch-over apply behavior must use a scoped contract under its own command ownership, not a generic bootstrap apply lane.

`detach --dry-run` reports root posture, preserved authority files, marker target, generated projection posture, manual recovery notes, and boundary reminders without writing files. `detach --apply` creates only `.mylittleharness/detach/disabled.json` in eligible live operating roots, leaves valid existing markers unchanged, treats generated projection artifacts as disposable but preserved, and reports product-source fixtures, fallback/archive or generated-output roots, ambiguous roots, non-default authority paths, unreadable manifest/state surfaces, path conflicts, and invalid marker payloads as fail-closed apply inputs. `disable` is explanatory terminology only, not a command spelling.

The repair snapshot boundary is `.mylittleharness/snapshots/repair/` inside an explicit live operating root. Snapshots preserve pre-repair bytes and metadata for inspection only; they cannot approve repair, closeout, archive, commit, switch-over, or lifecycle decisions. `snapshot --inspect` is the terminal-only no-write inspection surface for snapshot presence, metadata readability, copied-file/hash/path posture, current-target posture, retention, manual rollback instructions, and non-authority wording. `repair --dry-run` reports a no-write `state-frontmatter-repair` snapshot plan only for default-path prose `project/project-state.md`, reports no-write create-only plans for a missing required `AGENTS.md`, missing required `.agents/docmap.yaml`, or missing `project/specs/workflow/*.md` stable spec fixtures, and reports the no-write `.agents/docmap.yaml` route-repair snapshot plan when existing docmap route diagnostics exist. `repair --apply` can snapshot and prepend deterministic state frontmatter before stopping, creates absent required AGENTS contracts, docmaps, and stable spec fixtures without snapshots, and creates a timestamped snapshot before adding missing route entries to an existing docmap. Product-source fixtures and historical archive/evidence roots remain outside state, AGENTS, docmap, stable-spec, and snapshot creation.

Product readiness means the reusable source tree, docs, tests, package metadata, stdlib build backend, and compatibility fixtures are coherent while operating memory and closeout evidence stay in an explicit operating root. The 1.0.0 baseline is the small visible CLI, stdlib package posture, local package-smoke verification, explicit repair/detach mutation boundaries, read-only intelligence/evidence helpers, optional read-only MCP projection access, disposable generated projections, and gated optional power-ups. The current release checklist is documentation-and-verification based: package metadata/runtime version agreement, bytecode-disabled tests, read-only health gates, package smoke from temporary locations outside the product root, product hygiene, and product-boundary wording. Optional power-ups become release candidates only after their contracts name source-of-truth placement, generated or adapter boundaries, dependency policy, degraded/offline behavior, verification, closeout evidence, and non-authority rules. The stdlib core remains the default dependency posture; semantic runtimes, provider adapters, package extras, publishing helpers, mutating workstation adoption helpers, and other external runtimes require later scoped policy before they become product surfaces. Package-index publication, signed artifact release, global installation, PATH/profile/user-config mutation, and workstation adoption are not part of local release-candidate correctness; standalone `bootstrap --apply` and standalone switch-over automation are rejected.

For a clean operating-project pilot, `architecture/clean-room-carry-forward.md` carries the reusable invariants and risk register without importing unrelated historical context.



