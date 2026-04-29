# MyLittleHarness Product Source Operator Contract

## Repo-Local Posture

- Treat this directory as a reusable MyLittleHarness product source checkout and implementation target.
- Do not use this directory as an operating workflow root.
- Recover active operating context from the operator-provided operating project root before non-trivial product work.
- In reusable product behavior, the operator-provided operating root means the user's target repository after MyLittleHarness is attached. The product chain is `MyLittleHarness -> target repository`.
- Treat any historical archive or evidence root as opt-in context for named blockers only.
- Treat `workflow-core` as a compatibility label in fixture manifests and operator wording only. It is not the architectural baseline for MyLittleHarness.
- Keep `.codex/project-workflow.toml`, `.agents/docmap.yaml`, `project/project-state.md`, and `project/specs/workflow/**` as product compatibility fixtures only while the CLI/tests need a workflow-shaped target root.
- Do not change PATH, user config, installed skills, package archives, attach/install distribution, MCP, hooks, runtime helpers, or workstation state from this product tree.
- Do not create or import active implementation plans, archived plans, research/history/raw intake, archive-under-study material, candidate source packs, old migration evidence, package zips, broad research corpus, runtime/demo debris, reports, logs, caches, generated validation artifacts, local databases, or pycache into this product tree.

## Start Pass

For non-trivial product work in this directory:

1. Recover operating context from the operator-provided root for the current task. For shipped product behavior this is the user's target repository.
2. Read this `README.md` and `AGENTS.md`.
3. Read the relevant `src/`, `tests/`, and product docs for the product change.
4. Read `.agents/docmap.yaml`, `.codex/project-workflow.toml`, `project/project-state.md`, or `project/specs/workflow/*.md` only when changing CLI validation behavior or compatibility fixtures.

There should be no `project/implementation-plan.md` in this product source tree.

## Fixture Boundary

- `project/project-state.md` is a product compatibility fixture, not writable operating memory.
- Keep `.agents/docmap.yaml` conservative and limited to product entrypoints plus compatibility fixtures.
- Keep stable workflow fixture rules under `project/specs/workflow/**` only while the CLI/tests need them.
- Do not write working memory, plans, research, or archive history into this product checkout.

<!-- BEGIN workflow-core v1 -->
## Workflow Core Compatibility

- This compatibility block is a fixture contract for CLI/tests, not permission to operate workflow memory here.
- First recover operating context from the task's explicit operating root or target root; read `project/project-state.md` here only as fixture data.
- Keep the start pass cheap: read the implementation plan file only when `plan_status = "active"` or when the user explicitly asks about plan, phase, or closeout.
- Do not create `project/implementation-plan.md` here. Current product-development plans live outside this checkout; shipped MyLittleHarness attaches directly to a target repository.
- Keep `project/project-state.md` as fixture metadata only.
- Keep stable fixture docs under `project/specs/workflow/**`.
- Run docs routing only for mutating tasks with docs, contract, setup, rollout, terminology, or other user-visible impact.
- Do not perform operational switch-over from this product tree without a separate explicit decision or plan.
- On closeout, use manual commit policy and record skipped commit decisions when this directory is not a git worktree.
- If the compatibility fixture contract is missing or broken, report that it needs repair from the operating project root instead of silently installing or adopting workstation tooling.
<!-- END workflow-core v1 -->

