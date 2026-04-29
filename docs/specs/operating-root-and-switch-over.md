# Operating Root And Switch-Over Spec

## Purpose

This spec defines how MyLittleHarness separates logical operating roots from local filesystem paths, and why standalone operating-root switch-over automation is rejected as a product surface.

The product must support clean operating work without turning one developer machine layout into reusable product law.

Reusable product behavior is MyLittleHarness serving an explicitly targeted repository directly.

## Authority

Accepted operating focus, active plan status, research intake, and operating evidence belong in the operating project root. Reusable product contracts belong under `docs/...` in the product source checkout.

Reusable product vocabulary:

- `operating_root`: the user's explicitly targeted repository after MyLittleHarness is attached.
- `product_root`: the root that owns reusable source, tests, and docs.
- `archive_root` or `evidence_root`: opt-in historical material.
- `generated_output_root`: disposable generated artifacts, caches, indexes, or reports.
- `repair_snapshot_root`: target-bound safety evidence under `.mylittleharness/snapshots/repair/` in an explicit live operating root.
- `explicit_target_root`: the operator-supplied command target.
- `ambiguous_target`: a target whose role cannot be proven.

Absolute local paths are operator/bootstrap evidence, not portable authority.

## Non-Authority

The following must not become authority for root identity or switch-over status:

- hardcoded host paths in reusable product docs
- generated root maps
- repair snapshot metadata by itself
- shell history, IDE state, browser state, MCP state, or plugin state
- compatibility fixtures in the product root
- stale docs that describe an old operating root as current
- old research, archives, raw intake, or workflow execution state
- any extra state root as a required future runtime or intermediary

Deleting a generated root map or losing an adapter session must not change which files are authoritative.

## Current Contract

Any root map used by future tools must distinguish at least:

- the target repository operating root that owns active memory and plans for that repository
- the product root that owns reusable source, tests, and docs
- legacy reference material opened only for a named blocker
- generated-output locations that are disposable and subordinate
- repair snapshot locations that are target-bound safety evidence only

Read-only root discovery may fail open to explicit file paths and operator-provided context. Mutating paths must fail safe when the target root is missing, ambiguous, outside an allowed root, or classified as legacy reference material.

Product docs alone do not switch operation. Standalone switch-over automation is rejected; any future migration or adoption checklist requires an explicit plan with validation evidence and rollback posture.

Switch-over must preserve the direct relationship between MyLittleHarness and the target repository. If the product source folder is renamed or packaged, MyLittleHarness must still attach to and service the target repository directly.

Local package install or wheel smoke checks prove only package metadata, importability, and console script entrypoint behavior. They do not switch operating roots, publish packages, create bootstrap authority, mutate workstation state, or permit build artifacts inside the product source checkout. `bootstrap --inspect` is a read-only hidden-help readiness report for package smoke, rejected standalone bootstrap apply, switch-over, publishing, package artifact, and workstation adoption lanes; it reports interpreter context, product package metadata when available, console-script declaration, PATH discovery, and explicit fate/gate decisions without executing discovered tools. Workstation adoption is accepted only as no-write readiness evidence. Standalone `bootstrap --apply` is rejected as a product surface; future adoption, publication, or switch-over apply behavior requires a later scoped contract with its own command ownership, exact target root, exact write set, dry-run shape, refusal cases, validation gate, rollback posture, cleanup or non-adoption story, closeout evidence, and non-authority wording. `bootstrap --inspect` does not install, publish, switch roots, write artifacts, mutate user config or PATH, or authorize bootstrap apply. `bootstrap --package-smoke` is explicit package verification for the product source checkout only: it uses temporary source and virtual-environment locations outside the product root, verifies local install/import/console-script behavior, and still cannot publish, switch roots, mutate workstation state, or create product-root package authority.

For read-only validation, live operating roots may use lighter orientation surfaces than product-source fixtures. A root `README.md` is not required for an operating root, `.agents/docmap.yaml` may remain lazy when the manifest says so, and explicit assignment lines in `project/project-state.md` may expose lifecycle pointers without requiring YAML frontmatter. This tolerance is read-only except for the bounded `state-frontmatter-repair` class, which snapshots default-path state bytes and prepends deterministic frontmatter before any other repair class can run.

## Root Classification For Mutation

Every mutating command must classify the target root before applying changes:

- `live_operating_root`: an explicit target repository that owns operating memory and is not the MyLittleHarness product source, a compatibility fixture, legacy reference material, generated output, adapter state, cache, or archive-only material.
- `product_source_fixture`: a product root or compatibility fixture, including targets that mark `root_role = "product-source"`, `fixture_status = "product-compatibility-fixture"`, or `product_source_root` equal to the target path. Apply modes refuse this class with exit code `2`.
- `fallback_or_archive`: historical roots, archive roots, old context trees, and opt-in evidence mines. Apply modes refuse this class with exit code `2`.
- `generated_or_adapter_surface`: generated projections, caches, logs, local databases, reports, package artifacts, hooks, user/workstation config, PATH, IDE/browser/MCP/GitHub/CI state, and other adapter-owned surfaces. Apply modes refuse this class with exit code `2`.

A live operating root is the only root class eligible for primary `init --apply`, compatibility `attach --apply`, `repair --apply`, or `detach --apply`. Eligibility does not authorize every file under that root; each planned write still needs an allowed path, a dry-run proposal, snapshot behavior when existing content changes, or a create-only marker/idempotency story. `detach --dry-run` may report any explicit readable root, but it treats product-source fixtures, fallback/archive or generated-output roots, ambiguous roots, unreadable authority surfaces, non-default authority paths, and path conflicts as fail-closed apply inputs. Create-only AGENTS repair is eligible only when validation reports `AGENTS.md` as a missing required surface; existing AGENTS files remain unchanged. Create-only docmap repair is eligible only when validation reports `.agents/docmap.yaml` as a missing required surface; lazy docmaps remain absent. Create-only stable spec repair is eligible only when validation reports missing required `project/specs/workflow/*.md` fixtures; existing stable spec files remain unchanged.

The product source root may contain compatibility fixtures for tests and reporting, but those fixtures never become live operating memory through apply. Attempts to apply into any product source checkout must fail safe rather than create active plans, research, archives, logs, caches, reports, generated validation artifacts, local databases, or workflow execution residue there.

Snapshot-protected repair may create safety artifacts only under `.mylittleharness/snapshots/repair/` in an eligible live operating root, and only for a named repair class. `snapshot --inspect` may read that boundary in any explicit target root and report root posture, metadata readability, copied-file/hash/path consistency, current-target posture, retention, manual rollback instructions, planned state frontmatter keys, and non-authority wording; it cannot prove switch-over status, authorize repair, perform rollback, clean up snapshots, or turn product-source/fallback/generated/ambiguous roots into write targets. `repair --dry-run` reports a no-write `state-frontmatter-repair` snapshot plan only for default-path prose state with deterministic lifecycle assignments, reports no-write create-only plans only for a missing required `AGENTS.md`, missing required `.agents/docmap.yaml`, or missing `project/specs/workflow/*.md` stable spec fixtures, and reports the no-write route-repair snapshot plan only for an eligible live operating root with strict workflow-core mutation authority, an existing regular `.agents/docmap.yaml`, target-bound paths, and a non-conflicting snapshot boundary. `repair --apply` creates a real UTC-timestamped snapshot before prepending state frontmatter, creates absent required AGENTS contracts, docmaps, and stable spec fixtures without snapshots, and creates a real UTC-timestamped snapshot before adding missing route entries to an existing docmap. Snapshot creation must refuse product-source fixtures, fallback/archive roots, ambiguous targets, generated-output roots, non-default state paths, malformed or partial state frontmatter, active-plan mismatches, symlink path segments, non-directory boundary conflicts, existing preview-directory conflicts, and any path that normalizes outside the explicit target root.

`detach --dry-run` does not create a marker, rewrite metadata, delete generated output, clean snapshots, mutate Git, install hooks, write reports, or switch roots. It preserves repo-visible authority surfaces, previews `.mylittleharness/detach/disabled.json`, and reports `.mylittleharness/generated/projection/` as disposable generated output that remains preserved when present. `detach --apply` creates only that marker in eligible live operating roots, leaves a valid existing marker unchanged, refuses unsafe roots or invalid marker/path posture with exit `2`, and cannot authorize cleanup, rollback, repair, closeout, archive, commit, switch-over, or lifecycle decisions.

## Future Product Gates

Before mutating product code or CLI behavior may manage roots, publishing, mutating workstation adoption, or any migration/adoption checklist, a later scoped plan must define:

- root configuration source and bootstrap order
- portable logical-root names and required fields
- allowed-root validation for read and write operations
- cross-platform path normalization
- fixture versus live operating-memory detection
- generated-output and cache boundaries
- repair snapshot boundaries, retention, and manual rollback posture for existing-content mutation
- diagnostics for missing, ambiguous, stale, or forbidden roots
- switch-over checklist, rollback criteria, and closeout evidence
- tests covering clean setup, stale-root wording, and forbidden product-root contamination

## Validation Expectations

A valid implementation should prove that:

- operating memory is found in the operating root, not the product root
- product docs and source remain in the product root
- historical context is not loaded by default
- absolute local paths are treated as operator evidence rather than reusable contract
- writes cannot escape allowed roots
- generated root maps are rebuildable and subordinate
- switch-over cannot be declared by docs alone

Validation may start as read-only reports and fixtures. Mutating repair or switch-over commands require their own later gate.

## Explicit Non-Goals

- No operational switch-over in this spec.
- No hidden root registry, daemon, scheduler, or control plane.
- No import of old research or archives.
- No product-root operating memory.
- No guarantee that current local absolute paths are portable defaults.
- No automatic migration from one root to another.
- No extra root as product runtime, supervisor, or mandatory evidence authority.
