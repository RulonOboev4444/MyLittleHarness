# Metadata Routing And Evidence Spec

## Purpose

This spec defines how MyLittleHarness uses metadata, routing surfaces, Git-native evidence, and doc-gardening checks without making them stronger than file-visible authority.

Metadata should help agents and tools find the right files, understand lifecycle, and preserve provenance. It must not become the only meaning of a document.

## Authority

Human-readable repo files remain the recovery baseline. Stable product contracts live under `docs/...` in the product root. Active operating-project focus, plan status, and research intake live in the operating root for the repository MyLittleHarness is servicing.

Metadata may route to authority, classify lifecycle, point at source sets, name provenance, and support validation. The surrounding Markdown content must remain meaningful when metadata is missing, stale, or partially invalid.

Evidence has authority only when it points back to inspectable files, commands, observations, accepted docs, or commit metadata. Evidence paperwork alone is not completion.

## Non-Authority

The following are advisory or generated support, not authority:

- YAML frontmatter by itself
- docmaps and routing maps
- persistent generated evidence manifests
- repair snapshot manifests
- backlink or link reports
- stale-pointer reports
- quality-gate summaries
- search results and metadata indexes
- adapter memory from skills, MCP, browser, IDE, GitHub, CI, hooks, or task runners

Metadata cannot authorize mutation, closeout, repair, or archiving without the matching repo-visible plan and validation evidence. Repair snapshot metadata is included in this rule even when it records copied file hashes and rollback instructions.

## Current Contract

Metadata and routing are allowed when they reduce context load and improve recovery. They must stay lightweight, repo-visible when durable, and subordinate to the files they describe.

Target repository work keeps active memory and new research in that target repository. The product repository receives reusable product specs only. Legacy reference material is not part of default routing.

Routing surfaces should behave like tables of contents or impact maps, not hidden policy engines. Weak semantic matches, stale docmaps, and incomplete metadata may guide reading, but they must not authorize writes.

Evidence should be captured when provenance value exceeds ceremony cost, especially for verification, closeout, repair, or product-root hygiene. Small ad hoc work may rely on a concise chat summary and project-state writeback when required.

For Git repositories, durable closeout history should prefer commit metadata such as Git trailers. Suggested trailer fields may be assembled from repo-visible closeout facts, but MyLittleHarness helpers must not stage files, create commits, amend commits, push, mutate Git config, or decide lifecycle state. For non-git roots, the durable fallback is repo-visible Markdown closeout fields and operator summaries. Persistent generated evidence manifests are rejected as the default fallback.

Docs decisions are portable closeout facts. Use `docs_decision = updated` when the relevant docs were changed, `docs_decision = not-needed` when routed docs were checked and already match the work, and `docs_decision = uncertain` when the operator lacks enough evidence to state either result. `uncertain` blocks confident closeout language until the uncertainty is resolved or explicitly carried forward. The current MLH-owned closeout authority is the marked closeout writeback block in `project/project-state.md`; `active_phase`, `phase_status`, and `last_archived_plan` remain lifecycle frontmatter authority in `project/project-state.md`. The active-plan frontmatter, exact active-plan closeout bullets, and active-phase body status line are derived diagnostic copies; the marked Current Focus summary is derived from the same lifecycle frontmatter. When an active implementation plan carries `docs_decision` in frontmatter, `validate` reports unsupported values and reports `uncertain` as stale closeout posture when `project/project-state.md` says `phase_status = complete`. When project-state says `phase_status = complete` but an active-plan frontmatter `status` copy still says `active`, or when the matching active phase body still says `pending` or `in_progress`, `check`/`validate` report lifecycle drift instead of forcing agents to infer the split from prose history. If completed closeout facts are already present while the default active plan remains active, `check`/`validate` report complete-but-not-archived lifecycle drift.

A docs decision is required when behavior, CLI usage, configuration, setup, contract meaning, permissions, output shape, UX/copy, terminology, rollout, migration, or other user-facing meaning changes. Portable inputs are the actual file diff or task evidence, `.agents/docmap.yaml` when present, `audit-links`, `check`, relevant product specs, and explicit closeout fields. A Codex skill, generated docs-impact report, IDE rule, MCP client, hook, or CI result may help route attention, but it cannot be required for the decision and cannot store the only copy of the decision.

The first implemented evidence helper is the read-only `evidence` CLI report. It collects candidate verification anchors, closeout fields, validation sections as verification closeout candidates, residual risks, skip rationale, and carry-forward cues from inventory-discovered source files and currently readable workflow surfaces. Candidate cue identity is report-only and derived from cue kind, source path, line number, normalized preview text, and a deterministic hash. Concrete closeout fields are limited to explicit field bullets, exact field headings, or observed result lines; manifest language and future-contract wording remain context rather than completed evidence. It is terminal-only, creates no persistent evidence manifest, report file, generated output, database, cache, adapter state, quality-gate state, or quality-gate record, and cannot authorize mutation, closeout, archive, commit, plan lifecycle changes.

The first closeout assembly helper is the read-only `closeout` CLI report. It combines source-bound evidence cues, manifest policy, read-only Git evidence suggestions, report-only quality/readiness cues, projection posture, and a fail-open VCS probe into operator-facing closeout prompts. The VCS probe may run only target-bound read-only Git discovery and porcelain status commands; non-git roots, missing Git, subprocess failure, clean status, and dirty status all remain report findings rather than authority. Concrete closeout field lines are explicit field bullets, exact field headings, observed result lines, or fields in the MLH closeout writeback block. Broad future-contract mentions remain context when concrete field evidence is absent. For Git worktrees, the report may suggest trailers for `worktree_start_state`, `task_scope`, `docs_decision`, `state_writeback`, `verification`, `commit_decision`, residual risk, and carry-forward from explicit repo-visible closeout lines, preferring the current state writeback block over stale derived plan copies. For non-git or unknown Git posture, it reports the Markdown/operator-summary fallback and emits no trailer suggestions. It cannot decide task scope, approve completion, archive plans, stage files, commit, repair, write persistent evidence manifests, write quality-gate state, or write lifecycle state.

The implemented mutating closeout/state path is hidden `writeback --dry-run|--apply`. Dry-run is no-write. Apply is allowed only for a live operating root with readable frontmatter state, refuses product-source fixtures, fallback/archive roots, ambiguous roots, malformed frontmatter, and unsafe active-plan targets, and writes only the MLH closeout writeback block in `project/project-state.md`, requested lifecycle frontmatter fields in `project/project-state.md`, the marked Current Focus block derived from lifecycle frontmatter, matching derived active-plan frontmatter/body fields when those copies already exist, the canonical active-plan archive move, and post-writeback operating-memory compaction when safe. It synchronizes `worktree_start_state`, `task_scope`, `docs_decision`, `state_writeback`, `verification`, `commit_decision`, `residual_risk`, and `carry_forward`; it also writes requested `active_phase`, `phase_status`, and `last_archived_plan` lifecycle fields. When `phase_status` is requested, an existing active-plan frontmatter `status` copy is synchronized to the same value as derived metadata, and the phase block selected by the requested or current `active_phase` gets its body `- status:` line updated. The body status for lifecycle `phase_status = complete` is `done`; other lifecycle status values are copied as-is. `writeback --dry-run --archive-active-plan` and `writeback --apply --archive-active-plan` are the explicit completed-plan close rail for live operating roots using the default active plan and `project/archive/plans/` archive directory: dry-run reports active plan, archive target, lifecycle updates, closeout facts, auto-compaction posture, and validation posture; apply moves the plan, sets `plan_status` to `none`, clears `active_plan`, records `last_archived_plan`, refreshes Current Focus, and preserves or updates supplied closeout facts. The same archive rail is selected automatically when `writeback --apply --phase-status complete` has completed closeout posture: `docs_decision` is `updated` or `not-needed`, and `state_writeback`, `verification`, and `commit_decision` are non-placeholder facts. If the auto-archive target is unsafe or conflicting, writeback is refused before state or plan writes. If any resulting live `project/project-state.md` after writeback exceeds the default 250-line threshold and section boundaries are clear, auto-compaction archives older history into `project/archive/reference/project-state-history-YYYY-MM-DD.md` or a conflict-free same-day variant and leaves compact operating memory plus an archive pointer. Refused or skipped compaction does not invalidate the state writeback. It does not stage, commit, clean archives, repair unrelated files, create generated evidence stores, create repair snapshots, change docmaps, or make read-only warnings into approval.

The implemented mutating active-plan scaffold path is hidden `plan --dry-run|--apply`. Dry-run is no-write. Apply is allowed only for a live operating root with readable frontmatter state and the default manifest plan path, refuses product-source fixtures, fallback/archive roots, ambiguous roots, malformed frontmatter, stale inactive plan files, unsafe plan targets, active-plan conflicts without `--update-active`, and destructive task input, and writes only `project/implementation-plan.md` plus selected project-state lifecycle frontmatter. The generated plan records `docs_decision = "uncertain"` as derived diagnostic metadata until closeout evidence proves `updated` or `not-needed`; it cannot approve repair, closeout, archive, commit, rollback, or future mutation by itself.

The implemented mutating memory lifecycle hygiene path is hidden `memory-hygiene --dry-run|--apply`. Dry-run is no-write. Apply is allowed only for a live operating root with an explicit source under `project/research/` or `project/plan-incubation/`, optional existing `--promoted-to` destination, optional explicit `--archive-to` destination under `project/archive/reference/research/` or `project/archive/reference/incubation/`, and optional exact `--repair-links`. It writes only requested source frontmatter fields such as `status`, `updated`, `promoted_to`, and `archived_to`, the explicit archive target, and exact root-relative source-path link replacements in MLH-owned lifecycle surfaces. It refuses product-source fixtures, fallback/archive roots, ambiguous roots, missing or malformed source frontmatter, invalid routes, path escapes, symlinks, target conflicts, and `--repair-links` without `--archive-to`; it cannot infer promotion meaning, perform fuzzy link repair, approve archive decisions, closeout, commit, rollback, or broader lifecycle changes.

The implemented read-only route metadata diagnostic path is part of `validate`, `check`, and `check --focus validation` for live operating roots. It inspects routed research, incubation, stable-spec, decision, ADR, and verification Markdown frontmatter for known lifecycle statuses, malformed relationship values, root-relative path safety, missing targets, archive-destination shape, promotion destinations, route-specific `related_*` fields, `source_research`, `source_incubation`, `supersedes`, and `superseded_by`. It reports warning-level `route-metadata-*` findings plus an authority reminder when problems are found. It does not run for product-source fixtures, does not repair metadata, does not move archives, and does not approve closeout, commit, rollback, or lifecycle decisions.

Doc-gardening checks should report stale pointers, missing required sections, invalid links, path drift, lifecycle conflicts, and forbidden residue before any repair flow mutates files.

Repair snapshot metadata is provenance for one repair attempt. It may record schema version, tool/version, command, root kind, repair class, target paths, copied files, pre-repair hashes, source diagnostics, planned route entries, planned frontmatter keys, retention posture, rollback instructions, and an authority note. It must point back to repo-visible target files and copied bytes, and it must not become a durable evidence database, quality gate, routing authority, closeout approval, archive approval, commit decision, or future repair authorization.

The implemented repair candidates are snapshot-protected state frontmatter repair, create-only `AGENTS.md` creation, create-only `.agents/docmap.yaml` creation, create-only stable workflow spec fixture restoration, and snapshot-protected `.agents/docmap.yaml` route repair. `state-frontmatter-repair` is allowed only when validation reports `state-prose-fallback` for the default manifest state path, required lifecycle assignments are present, and active-plan pointers match the manifest; malformed or partial frontmatter remains manual. `agents-contract-create` is allowed only when validation reports a missing required `AGENTS.md`; existing AGENTS files are preserved, and no snapshot is created because no existing bytes are changed. `docmap-create` is allowed only when validation reports a missing required docmap; lazy or not-required docmaps remain absent, and no snapshot is created because no existing bytes are changed. `stable-spec-create` is allowed only when validation reports missing required `project/specs/workflow/*.md` fixtures; existing stable specs are preserved, and no snapshot is created because no existing bytes are changed. `snapshot --inspect` reads repair snapshot metadata and copied bytes as safety evidence, reporting schema, repair class, command, target-root and snapshot-root posture, copied-file presence, hash and byte-count consistency, current-target posture, planned frontmatter keys when present, retention, manual rollback instructions, and non-authority wording without approving repair or rollback. `repair --dry-run` reports target files, deterministic preview snapshot paths where a snapshot class applies, copied-file paths, source diagnostics, planned frontmatter keys, route entries, AGENTS contracts, or stable spec files, metadata fields, manual rollback posture, and `validate`/`audit-links` validation methods. `repair --apply` writes timestamped snapshot metadata and copied pre-repair bytes before prepending state frontmatter or adding missing route entries to an existing docmap, and uses packaged templates for create-only AGENTS and stable spec restoration. Snapshot metadata may help an operator inspect a bounded rewrite, but it cannot make operator-contract text, docmap routing, state metadata, or stable spec fixtures authoritative, and it cannot promote manifest/archive/active-plan repair.

## Future Product Gates

Before metadata, routing, Git-evidence helpers, quality gates, or stronger evidence helpers are implemented, a later scoped plan must define:

- minimal metadata fields and tolerant defaults
- required versus optional lifecycle fields
- severity levels for missing, stale, or contradictory metadata
- routing-map ownership and update rules
- stronger Git-evidence behavior beyond the current read-only trailer suggestions, including any field-shape changes, generated output, enforcement, or non-git fallback changes
- persistent generated evidence manifest shape, identity, and provenance fields only if a later plan explicitly re-accepts generated manifests after Git-native evidence proves insufficient
- repair snapshot metadata, retention, and cleanup rules when existing-content repair is in scope
- quality-gate names, skip rules, and closeout linkage when enforcement or durable gate state is in scope
- stale-link and stale-pointer report format
- migration behavior for existing docs
- tests for metadata absence, partial validity, stale routing, and conflicting lifecycle status

Strict validators must not block recovery when a human-readable file still contains enough authority for read-only work.

## Validation Expectations

A valid implementation should prove that:

- documents remain understandable without metadata
- metadata routes to existing files
- stale metadata is reported rather than silently trusted
- evidence points to inspectable artifacts or explicit skip rationale
- terminal evidence reports remain useful without storing generated truth
- report-only evidence cue identity remains source-bound and deterministic without becoming a manifest
- manifest or prospective closeout wording remains context rather than concrete closeout completion evidence
- closeout assembly reports preserve Git/VCS facts and any suggested trailers as advisory evidence rather than required authority
- report-only quality gates improve closeout readiness without enforcement state
- generated reports can be deleted and rebuilt when a later generated-report feature exists
- routing never authorizes mutation by itself
- repair snapshot metadata and `snapshot --inspect` remain evidence for copied bytes, not authority for repair, rollback, cleanup, or closeout
- writeback apply synchronizes closeout/state authority, the marked Current Focus block, and derived active-plan copies in the same mutation, while read-only commands keep reporting stale derived copies without writing
- archive-active-plan writeback dry-run/apply closes the default completed-plan lifecycle without turning repair, check, evidence, or closeout reports into archive approval
- post-writeback auto-compaction keeps oversized live operating memory compact without giving read-only context warnings permission to write files
- live-root status/check summarize completed active phases as explicit closeout/archive/manual-commit next action rather than leaving agents to reconstruct that state from prose history
- legacy reference material is opened only for a named blocker

Validation should prefer report-first checks. Mutating doc repair requires a separate explicit plan.

## Explicit Non-Goals

- No metadata schema implementation in this phase.
- No evidence database, hidden registry, default persistent evidence manifest, or generated truth.
- No Git staging, commits, amendments, pushes, hook installation, or Git config mutation by evidence helpers.
- No required docmap for a first operating-root phase.
- No auto-gardening or silent doc repair.
- No metadata-only authority.
- No quality-gate ceremony for every small ad hoc task.
- No import of old research or archives as routing defaults.
