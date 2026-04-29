# Product And Operating Boundary Spec

## Purpose

This spec defines how the MyLittleHarness product repository stays separate from the repositories it inspects or attaches to.

The shipped product serves one explicit target repository at a time.

## Portable Root Roles

- Product repository: reusable product source, tests, product README/operator orientation, product docs under `docs/...`, and minimal compatibility fixtures for CLI/tests.
- Target repository: the explicitly targeted repository MyLittleHarness inspects or attaches to; it owns its own plans, project state, research, navigation/routing surfaces, closeout evidence, and other task memory.
- Legacy reference material: old context opened only for a named blocker with a narrow lookup.
- Generated-output boundary: rebuildable artifacts, reports, caches, or indexes that remain disposable and subordinate to source files.
- Repair snapshot boundary: target-bound safety evidence under `.mylittleharness/snapshots/repair/` inside an explicit live operating root.
- Explicit target root: the root supplied by the operator to a CLI command.
- Ambiguous target: a target whose role cannot be proven from metadata, path, and product contract.

## Product Repository Responsibilities

The product source checkout holds:

- reusable product source
- tests
- stdlib package build backend
- product README and operator orientation
- product docs under `docs/...`
- minimal compatibility fixtures for CLI/tests when needed
- package metadata for the reusable stdlib package and console script

The product repository is for MyLittleHarness source, docs, tests, fixtures, and package metadata.

## Forbidden Product-Root Content

The product source checkout must not hold:

- active working memory
- implementation plans
- research/history/raw intake
- archived plans
- workflow execution state
- runtime/demo debris
- generated validation artifacts
- repair snapshots
- logs, caches, local databases, package archives, pycache, or temporary outputs
- build directories, wheels, or egg-info from local package smoke checks
- hidden workflow schedulers, queues, dashboards, or control planes

## Fixture Boundary

The product tree may retain workflow-shaped fixtures under:

- `.codex/...`
- `.agents/...`
- `project/project-state.md`
- `project/specs/workflow/...`

These files are product compatibility fixtures for CLI/tests. They are not the home for new product architecture docs and are not operating memory.

Clean reusable architecture and specs belong under `docs/...`.

## Apply Boundary

The product source checkout is never the target for live workflow mutation. `init --apply`, compatibility `attach --apply`, `repair --apply`, and `detach --apply` must refuse product-source compatibility fixtures with exit code `2`; `init --dry-run`, `detach --dry-run`, compatibility `attach --dry-run`, and `repair --dry-run` remain report-only for product-source fixtures.

A live operating root may be attached only when the operator supplies it explicitly and it is not classified as product source, legacy reference material, generated output, adapter state, cache, log, local database, package archive, user config, PATH, hook, MCP, browser, IDE, GitHub, CI, or switch-over surface.

The first attach apply scope is create-only. It may create eager scaffold directories and absent `.codex/project-workflow.toml` plus `project/project-state.md` from explicit templates, with `--project <name>` required for state creation. It must not create active implementation plans, archives, research intake, generated validation artifacts, logs, caches, local databases, or workflow execution residue in the product source tree.

Repair apply must stay narrower than validation: only deterministic proposals with allowed paths and post-repair validation can mutate files. The implemented repair apply scope can snapshot-protect and prepend missing `project/project-state.md` frontmatter for default-path prose operating state, creates missing scaffold directories, creates an absent required `.agents/docmap.yaml` through the create-only `docmap-create` class, creates absent required stable workflow spec fixtures through the create-only `stable-spec-create` class, and performs only the snapshot-protected `.agents/docmap.yaml` route repair for existing docmaps. Existing-content repair requires the repair snapshot contract under `.mylittleharness/snapshots/repair/`, a no-write dry-run snapshot plan, target-bound path checks, manual retention, and manual rollback instructions before any overwrite or normalization can be implemented. `snapshot --inspect` is report-only and may surface product-source snapshot debris, malformed metadata, missing copied bytes, hash/path drift, current-target posture, planned state frontmatter keys, and manual rollback text; it does not make snapshots acceptable product-root content and does not authorize rollback, cleanup, repair, closeout, archive, commit, or switch-over. The implemented snapshot-plan classes are state frontmatter repair and `.agents/docmap.yaml` route repair, which report target files, preview snapshot paths, metadata fields, refusal or skip posture, manual rollback posture, and validation commands; apply creates the real snapshot before prepending state frontmatter or adding missing docmap route entries. Stable spec repair is create-only and uses packaged templates, so it creates no repair snapshot and never rewrites existing spec files.

`detach --dry-run` reports product-source fixture preservation without proposing product-root operating mutation. It writes no marker, metadata toggle, cleanup report, generated output, snapshot, Git state, hook, CI file, package artifact, or workstation state. It treats `.mylittleharness/generated/projection/` as disposable but preserved and previews the live-root marker target. `detach --apply` is marker-only for eligible live operating roots and must not create `.mylittleharness/detach/disabled.json` in the product source checkout.

## Local Versus Reusable

Absolute local paths are operator evidence. They are not public product law and must not be hardcoded into shipped product behavior.

Reusable MyLittleHarness currently supports local-only `bootstrap --package-smoke` verification of the existing stdlib package and `mylittleharness` console script through the stdlib build backend under `build_backend/`, with build artifacts kept outside the product source checkout. It also supports `bootstrap --inspect` as a read-only hidden-help readiness report that separates package smoke, rejected standalone bootstrap apply, switch-over, publishing, package artifact policy, PATH/user-config mutation, and workstation adoption without performing them. `bootstrap --inspect` may report interpreter context, product package metadata when available, console-script declaration, and PATH discovery for `mylittleharness`, but it does not execute discovered tools or mutate workstation state. Configurable roots, publishing, mutating workstation adoption, root hygiene validation expansion, generated-output boundary expansion, and any future adoption or switch-over apply behavior require later scoped product plans with command ownership outside a generic bootstrap apply lane.

## Readiness Boundary

The product source checkout is release-ready only when reusable source, tests, package metadata, product docs, and compatibility fixtures are coherent and the checkout contains no operating memory or runtime debris. Operating evidence for a release candidate belongs in the operating root, including observed verification, docs decisions, state writeback, residual risk, carry-forward, and commit decisions.

The current local `1.0.0` release-candidate checklist is satisfied by repo-visible source and verification, not by publication. It requires coherent `README.md`, `AGENTS.md`, `docs/...`, `pyproject.toml`, `build_backend/`, `src/mylittleharness/`, `tests/`, compatibility fixtures, package/runtime version agreement, bytecode-disabled tests, read-only health gates, product hygiene, and `bootstrap --package-smoke` from temporary locations outside the product source checkout. Wheel, build, install, and virtual-environment outputs are ephemeral verification artifacts unless a later publication plan accepts a durable artifact and signing policy. Package-index upload, credentials, signing, global installation, PATH/profile/user-config mutation, and mutating workstation adoption are not required for release-candidate correctness. Standalone `bootstrap --apply` is rejected, and standalone switch-over automation is rejected as a product surface.

Optional power-ups must not blur the product/operating boundary. Semantic runtimes, evidence manifests, quality gates, adapters, hooks, CI, publishing helpers, mutating workstation adoption helpers, switch-over tools, repair expansion, rollback automation, and snapshot cleanup require scoped product contracts before implementation. Those contracts must keep files authoritative, define generated-output or helper-state boundaries, name dependency and degraded/offline behavior, and state that helper output cannot approve repair, closeout, archive, commit, rollback, switch-over, or lifecycle decisions.

## Switch-Over Boundary

Creating product docs does not switch operation into the product source checkout.

Switch-over must preserve the target shape: one product serving one explicit target repository.

Standalone switch-over automation is rejected as a product surface. Any future migration or adoption checklist requires a later explicit plan that proves:

- start-pass recovery
- product docs and compatibility fixture disposition
- state/memory placement
- validation and hygiene checks
- rollback or recovery posture
- closeout evidence

Until such a plan exists, recover active context from the operating project root and use the product source checkout only as product source/docs/tests/fixtures.

