# Adapter Boundary Spec

## Purpose

This spec defines how MyLittleHarness treats optional integrations such as skills, plugins, MCP, browser tools, IDEs, Git/GitHub/CI, hooks, issue trackers, and task runners.

Adapters can help.
Adapters cannot own correctness.

## Adapter Rules

All adapters must:

- fail open to repo files
- keep accepted decisions in file-visible authority surfaces
- avoid adapter-only memory
- avoid hidden mutation
- expose failures clearly
- remain optional for recovery
- preserve the product/operating root boundary

No adapter may become the only way to recover current focus, plan status, accepted decisions, stable rules, or closeout evidence.

Optional wrappers such as Codex skills, IDE rules, shell aliases, preflight wrappers, MCP clients, hooks, CI jobs, and future adapter packs may derive prompts or ergonomics from the repo-visible contract. They must not become the first-run path, docs-decision path, repair path, verification path, closeout path, or the only location for accepted decisions.

## Adapter Groups

| Adapter group | Product role | Boundary |
| --- | --- | --- |
| Skills and plugins | Behavior projection and reusable procedures | Repo-native rules remain stronger than agent-specific skill state; skill-only correctness and skill-owned memory are rejected |
| MCP | Read/projection adapter | No mandatory correctness or unique memory; the implemented stdio slice is explicit, foreground-only, dependency-free, and read-only |
| Browser | Verification or inspection helper | Browser state is not authority |
| IDE | Convenience projection | IDE state is not recovery state |
| Git, GitHub, CI, issues | Collaboration, distribution, and evidence helpers | Core recovery remains non-git-safe and file-first; read-only VCS posture probes are advisory inputs only |
| Hooks | Advisory reminders or visible preflight checks | No hidden repair, auto-commit, auto-archive, or correctness dependency |
| Task runners | Reproducible command ergonomics | Not required for workflow recovery |
| Agent-specific projections | Final-stage convenience adapters | Generic repo and CLI contract must remain stable without them |

## Hook Subdoctrine

Hooks are the strictest adapter lane.
They may remind, warn, or run visible preflight checks.
They must not silently mutate files, repair workflow state, commit changes, archive plans, or become a hidden condition for correctness.

The implemented `preflight` command is a terminal-only warning feed that wrapper scripts may consume explicitly. `preflight --template git-pre-commit` prints a local Git pre-commit wrapper template to stdout, but it does not install that wrapper. Neither mode blocks by itself, writes reports, or becomes correctness authority.

## Product Gates

An adapter requires a later scoped plan before implementation.
That plan must define:

- adapter purpose and owner
- input/output shape
- fail-open behavior
- no-authority guarantee
- mutation boundary
- validation method
- docs impact
- tests or equivalent evidence

## Implemented MCP Read Projection Slice

`adapter --inspect --target mcp-read-projection` is the first implemented adapter report.
`adapter --serve --target mcp-read-projection --transport stdio` is the first real adapter integration.
It is an explicit foreground MCP stdio JSON-RPC tools server over the same read projection, not an installed service, SDK-backed runtime, HTTP server, network integration, or background daemon.

The inspect report and stdio tool payload expose:

- adapter id, purpose, owner, input root, output shape, and no-runtime posture
- in-memory projection summary, source-set hash, record-set hash, link counts, and fan-in counts
- source paths, roles, required/present/readable posture, counts, and hash prefixes without copying source bodies
- optional generated artifact and SQLite index posture as degraded input when missing, stale, corrupt, or unavailable
- no-authority and no-mutation reminders

The stdio server supports only `initialize`, `notifications/initialized`, `ping`, `tools/list`, and `tools/call`.
It exposes one tool, `mylittleharness.read_projection`, which accepts only an empty object and returns `structuredContent` plus a text JSON copy.
It reads newline-delimited JSON-RPC from stdin, writes only JSON-RPC messages to stdout, exits cleanly on EOF, and keeps generated projection files and SQLite indexes optional degraded inputs.

Both modes fail open to repo files and the current in-memory projection when generated projection files are missing or stale.
They return `0` for readable roots with info or warning findings; root-load failures remain exit `2`; missing required adapter modes, missing `--transport stdio` for serving, or unknown targets remain argparse usage failures.

They must not install an MCP SDK, create an HTTP or network server, create adapter state, write generated reports, mutate files, approve repair, approve closeout, archive, commit, switch roots, store accepted decisions, or become the only recovery path.

## Implemented Preflight Warning Slice

`preflight` is the first optional warning/preflight slice.
It is a terminal-only read-only report plus a stdout-only local hook template, not an installed hook, CI job, or GitHub integration.

It reports:

- advisory summary and root kind
- validation, link audit, context budget, and product-hygiene counts plus warning/error samples
- closeout readiness cues assembled from the existing read-only closeout report, including VCS posture cues when available
- no-authority, no-hook-installation, and no-mutation reminders

`preflight --template git-pre-commit` prints a deterministic POSIX wrapper that sets `MLH_ROOT` to the resolved target root with shell-safe quoting, checks for `mylittleharness`, runs `mylittleharness --root "$MLH_ROOT" preflight`, warns when tooling is unavailable or preflight does not complete, and exits `0`.

The command returns `0` after a successful report even when findings include warnings or errors.
Root-load failures and parser usage failures remain exit `2`.

It must not install hooks, create CI/GitHub workflows, use network calls, write generated preflight reports, block by itself, repair files, archive, commit, switch roots, create lifecycle state, or store accepted decisions.

## Explicit Rejects

- Mandatory adapter correctness.
- Issue-board authority.
- CI-only completion truth.
- VCS status as archive, commit, repair, switch-over, or lifecycle authority.
- Hidden hook repair.
- Preflight-only correctness or hidden blocking policy.
- Browser, IDE, MCP, GitHub, or plugin state as accepted decision storage.
- Adapter-specific source of truth that cannot be recovered from files.



