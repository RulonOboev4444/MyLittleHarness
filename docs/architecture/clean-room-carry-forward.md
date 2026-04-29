# Clean-Room Carry-Forward

## Purpose

This is a portable field manual for keeping MyLittleHarness work in the target repository while the reusable product source remains separate. It is not an implementation plan, not switch-over approval, and not permission to copy legacy material into the product repository.

The field guide carries forward reusable product invariants: file-first authority, one operating memory surface, generated-state subordination, and explicit boundaries between product source, target-repository memory, and legacy reference material.

Reusable MyLittleHarness behavior attaches to and services the target repository directly.

## Portable Root Roles

- Product source checkout: reusable source, tests, product docs, and minimal compatibility fixtures.
- Operating project root: active focus, current project memory, implementation plans, research intake, operating evidence, and closeout records.
- Legacy reference material: old context opened only for named blockers and narrow lookup.
- Generated-output boundary: rebuildable artifacts, caches, indexes, and reports that remain disposable and subordinate to source files.
- Explicit target root: the root supplied to a CLI command by the operator.
- Ambiguous target: any root whose role cannot be proven from metadata, target path, and product contracts.

## Accepted Invariants

- File-first authority: accepted decisions and recoverable workflow truth stay in repo-visible files.
- Product/operating boundary: reusable product source/docs/tests stay separate from operating memory and research.
- No product-root contamination: product source must not absorb active plans, research, archives, logs, caches, local databases, generated validation debris, or runtime residue.
- One mutable operating memory: an operating root has one explicit mutable memory surface for active focus and canonical pointers.
- No second mutable memory tree: clean operation must not create a hidden state system beside project-state.
- Generated state is subordinate/build-to-delete: reports, indexes, caches, and generated views are rebuildable, disposable, and unable to hold unique authority.
- SQLite is projection/cache/index only: SQLite may accelerate retrieval and analytics, but cannot become canonical memory.
- Adapters fail open: skills, MCP, browser, IDE, Git/GitHub/CI, hooks, and task runners must remain optional for recovery.
- Hooks are advisory only: hooks may warn or run visible preflight checks, but must not silently mutate, repair, commit, or decide correctness.
- No switch-over from docs alone: product docs can describe gates, but operation moves only through an explicit verified setup plan.

## Risk Register

| Risk | Known portable rule | Remains to design | Must not happen |
| --- | --- | --- | --- |
| Product/operating boundary | Product docs and source stay separate from operating memory unless an explicit switch-over plan changes that boundary. | Portable setup guidance for future operating-root changes. | Treating product docs or fixtures as live operating memory. |
| Product-root contamination | Product source excludes active plans, research/history/raw intake, archives, logs, caches, local databases, generated reports, and demo residue. | Hygiene checks for each operator setup. | Using product source as the place for operating research, reports, or runtime output. |
| Adapter fail-open | Adapters can help, but correctness remains recoverable from repo files. | Adapter-specific test contracts and failure messages. | Making a skill, MCP server, browser session, IDE, GitHub state, or CI result mandatory for recovery. |
| Generated state subordinate | Generated views are rebuildable, disposable, subordinate, inspectable, and fail open to files. | Storage paths, rebuild commands, and report retention boundaries. | Letting generated output become the only copy of decisions, focus, plan status, or carry-forward fate. |
| Configurable roots/bootstrap | Local paths are operator evidence, not public product law. | Portable root config, platform differences, setup validation, and generated-output boundaries. | Hardcoding one workstation layout as reusable product contract. |
| Operational switch-over | Any future root change requires an explicit plan proving start-pass recovery, memory placement, validation, hygiene, and rollback. | Exact switch-over criteria, operator checklist, failure handling, and rollback deadline. | Moving operation into a product checkout by implication or partial setup. |
| Repair behavior if mutating | Analyzer and repair flows report before mutation unless a scoped plan owns mutation. | Mutation prompts, diff evidence, backups, idempotency, and post-repair validation. | Auto-repairing state, plans, docs, fixtures, or archives without an explicit mutation boundary. |

## What We Are Intentionally Not Carrying Forward

- Old research piles.
- Archived implementation plans.
- Raw external intake.
- Old candidate studies.
- Old migration evidence.
- Demo residue.
- Broad historical rationale.
- Package/source mirror history.
- Local path assumptions except as operator evidence.
- Any active memory from legacy reference material.

## Rules For Reopening Historical Context

Legacy reference material may be reopened only when all of these are true:

- A clean-room decision hits a concrete blocker.
- The question is named before the lookup begins.
- The lookup is narrow.
- The result is extracted into a short note.
- The old artifact is not copied wholesale.
- The operating project root remains the current working surface.

## Validation Criteria

The operating project root remains current when validation shows:

- Clean start pass works from that root.
- Project-state stays compact.
- Active plan lifecycle works.
- New research intake and extraction do not create a context swamp.
- Doctor/validate pass succeeds.
- Product specs stay in the product source checkout.
- Legacy reference material remains narrow opt-in lookup context, not default context.
