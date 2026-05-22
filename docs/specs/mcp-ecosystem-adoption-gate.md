---
spec_status: "accepted"
implementation_posture: "target-only"
---
# MCP Ecosystem Adoption Gate Spec

## Purpose

This spec defines how MyLittleHarness evaluates MCP ecosystem servers before any
server becomes a recommended rail around MLH work.

The gate exists because MLH's product value is not generic tool exposure. MLH
protects repo-visible authority: lifecycle state, dry-run/apply review, route
ownership, evidence, roadmap sequencing, root boundaries, archive posture, and
closeout language.

## Source Set

- Roadmap item id: `mcp-ecosystem-adoption-gate-for-mlh`
- Imported research: MCP ecosystem adoption research reviewed on 2026-05-21
- Research source snapshot: official MCP Registry, official MCP reference
  servers repository, GitHub MCP server, Docker MCP Toolkit, ToolHive, and MCP
  security best practices

The research artifact is provenance and synthesis input. This spec is the
product-facing decision surface. Neither artifact installs a server, approves a
client config, starts a runtime, replaces lifecycle routes, or grants an MCP
server authority over MLH state.

## Decision

MLH keeps an MLH-owned MCP facade for MLH lifecycle and source-bound navigation.
Generic filesystem, Git, memory, registry, browser, or SaaS MCPs must not
replace MLH-owned route semantics.

MLH may adopt external MCP servers only for surfaces where the external owner is
the natural authority and the server passes this adoption gate. Examples include
GitHub-owned repository collaboration, browser verification, SaaS APIs, registry
discovery, and sandbox/runtime tooling.

## Authority Boundaries

An adopted MCP server can help an agent inspect or operate an external surface,
but it cannot approve:

- lifecycle movement
- repair, closeout, archive, or roadmap status
- staging, commit, push, rollback, release, or package publication
- product-source mutation outside an active write scope
- generated-cache truth, daemon state, dispatcher decisions, or provider routing
- replacement of MLH dry-run/apply rails

When MCP output conflicts with repo-visible MLH route files, explicit MLH route
files and reviewed dry-run/apply commands remain authority.

## Gate Criteria

Every candidate MCP server must be reviewed against these criteria before
recommendation:

| Criterion | Required evidence |
| --- | --- |
| Ownership | Official/vendor-maintained, or a named accountable maintainer and release channel. |
| Scope control | Toolsets or allowlisted tools can be enabled one by one; broad writes are disabled by default. |
| Security posture | Explicit auth model, least-privilege setup, read-only mode where applicable, no token echo, and clear network/OAuth/SSRF boundaries. |
| MLH authority fit | Server output cannot bypass MLH lifecycle, roadmap, archive, closeout, Git, release, daemon, or cache boundaries. |
| Auditability | Deterministic tool names, stable reports, visible errors, and enough provenance to review what was read or changed. |
| Windows/operator fit | Works on the local workstation without fragile shell assumptions or hidden background mutation. |
| Failure shape | Refusals, partial execution, and degraded operation name the safe next action instead of leaving ambiguous state. |
| Prompt/tool injection | Tool descriptions, resource metadata, and remote content are treated as untrusted until allowlisted. |

## Review Report Shape

A future review artifact for any MCP candidate must include:

- candidate name, upstream owner, source URL, version or commit, and package or
  distribution channel
- intended MLH use case and explicit non-goals
- requested tools/resources/prompts, default enabled toolsets, and disabled tools
- credential, network, filesystem, and write-surface boundaries
- read-only/degraded mode behavior
- prompt-injection and remote-content handling
- Windows setup notes and uninstall/disable path
- dry-run/apply or config-review rail that would own adoption
- verification commands and observed failure behavior
- disposition: `adopt`, `wrap`, `keep-custom`, `reject`, or `research-only`

The review artifact is evidence only. Adoption still requires a later scoped
plan or explicit client-config rail.

## Candidate Matrix

| Surface | Candidate | Disposition | Rationale | Boundary |
| --- | --- | --- | --- | --- |
| MLH lifecycle state, plans, archive, roadmap, closeout | MLH-owned MCP facade | keep-custom | This is the product authority model; generic servers do not know MLH lifecycle invariants. | Keep source-bound reads and route-safe operations in MLH. |
| Repo lifecycle file reads | Generic filesystem MCP | wrap or reject for lifecycle routes | Filesystem access is useful, but lifecycle files need MLH route policy, source bounds, and authority wording. | Do not allow direct lifecycle mutation or unbounded lifecycle reads as a trusted substitute. |
| GitHub issues, PRs, files, and repo collaboration | Official GitHub MCP server | adopt when needed | GitHub owns the API surface and can provide scoped toolsets and read-only modes. | GitHub MCP cannot approve MLH lifecycle, local Git, release, or roadmap decisions. |
| Browser/UI verification | Browser or Playwright MCP rails | adopt existing rail | Browser automation is naturally external to MLH state and useful for deterministic UI checks. | UI verification evidence does not approve lifecycle closeout by itself. |
| Registry/catalog discovery | Official MCP Registry and catalogs | research-only | Registry metadata can seed candidate discovery but is not a safety decision. | Registry presence is never adoption approval. |
| MCP runtime/gateway/sandbox | Docker MCP Toolkit, ToolHive | research-only then wrap if proven | Potential value for isolation, secrets, OAuth, audit, and gateway policy. | No daemon, listener, credential store, or runtime authority without a later plan. |
| Memory/vector knowledge servers | Memory MCPs | reject for authority | Opaque memory cannot outrank repo-visible MLH state. | May be used only as non-authority notes after a separate spec. |
| Generic Git or filesystem mutation servers | Generic Git/filesystem MCPs | reject for lifecycle routes | Direct mutation bypasses route-specific dry-run/apply and evidence handling. | Local Git and lifecycle mutation stay behind MLH or explicit human rails. |

## Adoption Flow

1. Record a candidate review artifact with the report shape above.
2. Classify the candidate as `adopt`, `wrap`, `keep-custom`, `reject`, or
   `research-only`.
3. For `adopt` or `wrap`, open a later scoped implementation plan naming the
   exact client config, toolset, credential boundary, tests, and rollback path.
4. Verify degraded/offline behavior and hook/report output before enabling it as
   a recommended operator rail.
5. Keep docs and roadmap closeout explicit; this gate never auto-installs or
   blesses a server.

## Rejection Rules

Reject or keep a candidate in research-only posture when it:

- requires broad filesystem, Git, network, or shell writes by default
- stores secrets or echoes tokens in reports
- treats registry presence, popularity, or reference status as production safety
- cannot expose an allowlisted toolset
- makes partial execution ambiguous
- claims authority over MLH lifecycle, roadmap, archive, closeout, Git, release,
  daemon, cache, or provider decisions

## Residual Risk

This gate is a product contract, not an adoption result. It does not prove any
candidate server is currently installed, current, secure, or suitable for the
local workstation. Candidate details can change upstream, so every later
adoption slice must re-check upstream ownership, tool surface, security posture,
and failure behavior before enabling a server.

The highest-risk failure mode is authority blur: a useful external MCP server
could make an operation feel official while bypassing MLH route ownership. The
mitigation is to keep adopted servers as helpers around explicit MLH rails and
to record every adoption through a bounded review artifact.

## Follow-up Slice Candidates

- Review the official GitHub MCP server for scoped issue, PR, and repository
  collaboration workflows.
- Review Browser or Playwright MCP rails for UI verification evidence that stays
  separate from lifecycle closeout.
- Research Docker MCP Toolkit and ToolHive as sandbox or gateway options before
  any runtime adoption.
- Keep the MLH-owned lifecycle MCP facade thin, source-bound, and read-first;
  do not expand it into generic filesystem, Git, or memory authority.

## Carry Forward

Future MCP adoption work should reduce MLH-owned generic integration surface
where the ecosystem is clearly better, while keeping MLH semantics inside MLH.
The product model remains `MyLittleHarness -> target repository`; no extra MCP
runtime, gateway, daemon, or memory service becomes authority without its own
reviewed plan.
