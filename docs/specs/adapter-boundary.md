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

When an MCP client exposes `mylittleharness.read_projection`, `mylittleharness.search`, `mylittleharness.read_source`, or `mylittleharness.related_or_bundle`, agents may use those tools as the projection leg of the agent-navigation reflex before or alongside CLI/file reads for route discovery, relationship lookup, source snippets, and impact checks. That use is optional and read-only. It cannot replace direct source verification, refresh generated caches from the adapter, create adapter-owned memory, or decide the lifecycle rail.

## V2 External Orchestrator Boundary

The v2 architecture treats external orchestrators, model providers, MCP servers, generated indexes, and notification relays as embassies around MLH's deterministic State. They may inspect route law, receive role packets, produce patches, record run evidence, transport approval packets, or help humans review work. They must not become lifecycle authority.

The first v2-compatible adapter contract is read/projection and report legibility:

- external clients can ask for route, role, gate, evidence, and generated-map posture;
- `manifest --inspect --json` exposes `route_manifest` and advisory `role_manifest` data for orchestrator packet setup;
- route entries expose advisory orchestration fields such as `parallelism_class`, `authority_lane`, `claim_scope`, `merge_policy`, `fan_in_gate`, and `max_parallelism_hint`, with lifecycle routes remaining `sequential_only` and coordinator-owned;
- role entries expose advisory coordination fields such as `orchestration_role`, `may_spawn_workers`, `worker_space_boundary`, `isolation_contract`, `fan_in_output_required`, and `coordination_budget`, with worker spawning false by default;
- route/role manifests are advisory until an MLH apply rail writes repo-visible authority;
- provider/model/tool routing is policy metadata before it is runtime ownership;
- optional relay adapters may transport approval packets only after core packets and review tokens exist;
- relay, provider, model, MCP, or generated-index state cannot approve closeout, archive, repair, roadmap movement, commit, push, release, or lifecycle transitions.

Do not add a hidden swarm runtime, background daemon, provider credential store, webhook tunnel, workstation install, or autonomous worker supervisor as part of v2 foundation. Future orchestration remains an external client of MLH until route manifests, role profiles, run evidence, claims, review tokens, and reconcile diagnostics are reliable.

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
`suggest --intent "inspect projection adapter runtime"` routes operators to the read-only inspect rail before projection-cache rebuild advice, so runtime/source/root provenance questions do not depend on remembering the exact adapter target id.

The inspect report and stdio tool payloads expose:

- adapter id, purpose, owner, input root, output shape, and no-runtime posture
- adapter runtime provenance: package version, adapter module path, MCP server startup root, selected root, requested root, and the serve command that can be used to restart/reconfigure the helper
- in-memory projection summary, source-set hash, record-set hash, link counts, and fan-in counts
- source paths, roles, required/present/readable posture, counts, and hash prefixes without copying source bodies
- bounded source line slices only when `mylittleharness.read_source` is explicitly called with a root-relative source path, 1-based start line, and line limit
- source-verified search rows from direct exact text search, projection path/reference search, and a current SQLite FTS/BM25 index when available
- nearby route/source bundles for a root-relative projection source, including outbound links, inbound links, fan-in rows, relationship graph rows, and adjacent source records without source bodies
- optional generated artifact and SQLite index posture as degraded input when missing, stale, corrupt, or unavailable
- no-authority and no-mutation reminders

The stdio server supports only `initialize`, `notifications/initialized`, `ping`, `tools/list`, and `tools/call`.
It exposes four read-only tools: `mylittleharness.read_projection`, `mylittleharness.read_source`, `mylittleharness.search`, and `mylittleharness.related_or_bundle`.
Each tool accepts optional per-call `root` selection and reloads that root inventory for the call.
`read_projection` returns summary posture without source bodies.
`read_source` returns only the requested bounded source slice and never stores it.
`search` accepts `query`, optional `mode` (`all`, `exact`, `path`, or `full-text`), and `limit`; it never refreshes generated caches from inside the adapter.
`related_or_bundle` accepts a root-relative projection source path and returns graph/link/source metadata only.
It reads newline-delimited JSON-RPC from stdin, writes only JSON-RPC messages to stdout, exits cleanly on EOF, and keeps generated projection files and SQLite indexes optional degraded inputs.

Both modes fail open to repo files and the current in-memory projection when generated projection files are missing or stale.
Generated-input warnings must point operators at `projection --inspect`/`projection --rebuild` for the selected root, and when MCP output disagrees with current CLI posture they must route operators to restart/reconfigure the MCP server or fall back to direct CLI/source reads rather than treating the long-lived MCP process as authority.
They return `0` for readable roots with info or warning findings; root-load failures remain exit `2`; missing required adapter modes, missing `--transport stdio` for serving, or unknown targets remain argparse usage failures.

They must not install an MCP SDK, create an HTTP or network server, create adapter state, write generated reports, refresh generated caches, mutate files, approve repair, approve closeout, archive, commit, change target roots outside explicit per-call selection, store accepted decisions, or become the only recovery path.

## Implemented Approval Relay Adapter Slice

`adapter --inspect --target approval-relay --approval-packet-ref <project/verification/approval-packets/id.json>` is the first approval relay adapter report.
It compiles a serializable relay preview from repo-visible approval packet JSON records, optional relay channel labels, and optional recipient labels.
The command is a terminal-only inspection rail: it does not deliver messages, open webhooks, read credentials, store secrets, create adapter state, install daemons, or write files.

The approval relay report exposes:

- adapter id, purpose, owner, input root, and no-runtime posture
- each approval packet ref, approval id, status, gate class, and packet hash
- a serializable relay payload hash with `delivery_attempted=false`
- boundary findings that approved packet status and relay delivery cannot authorize lifecycle, archive, repair, roadmap movement, staging, commit, push, release, or next-plan opening

`adapter --client-config --target approval-relay` prints a no-write command template and boundary payload for external clients that want to invoke the same terminal report.
`adapter --serve` remains supported only for `mcp-read-projection`; approval relay deliberately has no foreground server mode.

The relay slice fails open to the repo-visible approval packets. Missing, malformed, absolute, traversal, or non-approval-packet refs are warnings in the adapter report, not hidden recovery state or lifecycle blockers.

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

It must not install hooks, create CI/GitHub workflows, use network calls, write generated preflight reports, block by itself, repair files, archive, commit, change target roots, create lifecycle state, or store accepted decisions.

## Explicit Rejects

- Mandatory adapter correctness.
- Issue-board authority.
- CI-only completion truth.
- VCS status as archive, commit, repair, lifecycle authority.
- Hidden hook repair.
- Preflight-only correctness or hidden blocking policy.
- Browser, IDE, MCP, GitHub, or plugin state as accepted decision storage.
- Adapter-specific source of truth that cannot be recovered from files.
