# MyLittleHarness Operator Contract

## Operating Root

- Treat this repository as the target operating root that MyLittleHarness services.
- Repo-visible files remain authoritative; command output is advisory until changes are written here.
- Any file-reading, shell-capable agent can operate from this contract, repo-visible files, and MyLittleHarness CLI reports; installed skills, IDE rules, MCP clients, hooks, and CI are optional convenience layers only.
- Start by reading this `AGENTS.md`, `.codex/project-workflow.toml`, and `project/project-state.md`.
- Read `project/implementation-plan.md` only when `project/project-state.md` or the manifest says `plan_status = "active"` or the user explicitly asks about the plan, phase, or closeout.
- Use the optional docs routing file when present as a routing aid for product docs and impact checks; it is not authority by itself.
- Run `mylittleharness --root <this-repo> check` before mutating repair work.
- Run `mylittleharness --root <this-repo> repair --dry-run` before `repair --apply`.
- For user-facing changes, record a `docs_decision` of `updated`, `not-needed`, or `uncertain` before confident closeout; `uncertain` means closeout language must stay provisional.
- Do not treat repair output as approval for closeout, archive, commit, switch-over, rollback, or lifecycle decisions.
- The product model is `MyLittleHarness -> target repository`; do not add another runtime layer.

