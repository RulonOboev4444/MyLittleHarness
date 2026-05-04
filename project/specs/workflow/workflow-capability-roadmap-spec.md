# Workflow Capability Roadmap Spec

> Product fixture note: This spec is retained as a product compatibility fixture for CLI/tests. Live workflow authority, plans, research, and memory remain in the target repository; legacy reference material is opened only for a named blocker.

## Purpose

This spec records the full useful capability roadmap for the workflow-level upgrade so that important future improvements do not remain trapped in chat history, research notes, or the implementation plan of one nearby slice.
The roadmap is for a repo-native workflow contract where the canonical behavior should remain inspectable and portable with the repository.

For live operating roots, the first-class roadmap route is `project/roadmap.md`. That file is optional sequencing authority for accepted work between incubation and one active implementation plan; it is not part of the mandatory start path and cannot approve repair, closeout, archive, commit, rollback, or lifecycle decisions.

The hidden `roadmap --dry-run|--apply` command is the bounded mutation rail for that live-root route. It may add one explicit managed item block to a canonical `## Items` section, update one explicit managed canonical item block or compatibility top-level `## RM-...` section in an existing `project/roadmap.md`, compact completed bullets in the MLH-owned `Future Execution Slice Queue` when every listed item is terminal, compact older detailed `done` item blocks with archived-plan, verification, and final docs-decision evidence into `Archived Completed History`, and when an explicit `source_incubation` is supplied it may write reciprocal source-note relationship frontmatter in the same operation. `incubate --apply` may also record structurally known active-plan and active-plan roadmap relationship metadata in the target incubation note it creates, while preserving existing nonempty relationship metadata on append. Roadmap item blocks may carry advisory slice metadata: `execution_slice`, `slice_goal`, `slice_members`, `slice_dependencies`, `slice_closeout_boundary`, `source_research`, `related_specs`, and `target_artifacts`. Hidden `plan --roadmap-item` / `writeback --roadmap-item` may reuse that boundary to sync explicit plan relationships, active-plan relationship metadata, same-request closeout summaries, structurally known source-incubation closeout links, and roadmap-slice or active-plan `covered_roadmap_items`; for compatibility top-level RM sections, non-item `slice_members` labels are not expanded as covered roadmap item ids. Plan opening also refreshes each explicit source-incubation note back to the new active plan. `transition --archive-active-plan --next-roadmap-item` keeps the next item's source note out of archive retargeting before that next plan opens. `plan --roadmap-item` may derive executable plan frontmatter such as `primary_roadmap_item`, `covered_roadmap_items`, `domain_context`, `target_artifacts`, `execution_policy`, and `closeout_boundary` from repo-visible roadmap fields. These rails do not infer priority, approve lifecycle decisions, or make roadmap output closeout authority.

Bounded plan synthesis may also report advisory bundle/split rationale and pressure signals for roadmap-backed plans, including `target_artifact_pressure` and `phase_pressure`. The report makes execution grain visible but cannot calibrate a mandatory threshold, force a split, or authorize lifecycle, closeout, archive, repair, commit, rollback, or future mutation.

The accepted relationship vocabulary is path/id based and human-readable: `source_incubation`, `source_research`, `related_roadmap`, `related_roadmap_item`, `primary_roadmap_item`, `covered_roadmap_items`, `related_plan`, `archived_plan`, `implemented_by`, `related_spec`, `related_decision`, `related_adr`, `related_verification`, `target_artifacts`, `verification_summary`, `docs_decision`, `carry_forward`, `archived_to`, `promoted_to`, `supersedes`, `superseded_by`, `merged_into`, `merged_from`, `split_from`, `split_to`, `rejected_by`, and `rejection_reason`. These fields are direct relationship metadata only; they are not a separate lifecycle index and cannot make generated reports authoritative. A generated `relationships.json` graph may project those repo-visible fields for navigation and impact lookup, but deleting it must not change lifecycle truth.

Coverage-aware incubation auto-archive is allowed only after a requested closeout/archive operation produces structural proof: the roadmap item has the source incubation link, the item is closed with an archived plan, verification, and final docs decision, and the source note has no open-thread or unchecked-task markers. Single-entry notes can be covered by that structural chain. Mixed notes require a reviewable `## Entry Coverage` section with terminal bullets for every dated entry: `implemented`, `rejected`, `superseded`, `merged`, `split`, or `archived`, each with destination detail. The current archive lane for implemented incubation notes is `project/archive/reference/incubation/**`. When an explicit source incubation already lives in that archive lane, closeout writeback may update relationship metadata in place but must not re-archive it into a new path. Mixed notes without complete terminal coverage stay active and receive blocker findings plus heuristic split suggestions.

It exists to:
- capture the whole useful direction, not only the next implementation move
- mark each capability as `canonical-now`, `required-next`, `optional-next`, `later-extension`, `incubation-only`, or `not-planned`
- keep the roadmap inspectable and repo-native

This spec is authoritative for capability horizon and implementation intent. It does not replace the more detailed contract specs.

## MyLittleHarness Core v0 Status

Core v0 has landed the file-first harness contract in stable specs. MyLittleHarness is the target system; `workflow` and `workflow-core` remain compatibility vocabulary where existing manifests, operator blocks, package mirrors, and projection surfaces still need it.

The current capability posture is:
- repo-native authority, one mutable project memory surface, artifact lifecycle, research-before-plan handoff, lazy one-plan execution, verification/closeout, docs routing, projection demotion, and non-git operation are `canonical-now`
- package-source mirror parity for changed live specs is `canonical-now`
- operational lifecycle decision, package/archive regeneration, skills/MCP/hooks redesign, candidate tooling, evidence IDs, quality gates, task execution, backlog, bootstrap/cache/generated-state, and adapters are not Core v0; they remain deferred lanes unless a later plan promotes them

## Status Vocabulary

- `canonical-now`
  The rule is already part of the workflow contract and should be treated as current canon.
- `required-next`
  The capability should be implemented in the next bounded workflow-upgrade plan.
- `optional-next`
  The capability is useful and expected, but may land after the required scaffold if the next pass needs to stay narrow.
- `later-extension`
  The capability is useful, but only as an explicit, bounded extension after the required path proves itself.
- `incubation-only`
  The idea is promising, but not mature enough for commitment.
- `not-planned`
  The idea is consciously out of scope unless evidence changes.

## Capability Groups

### Artifact Model and Lifecycle

- layered artifact model for `project-state`, stable specs, active plan, incubation, verification, and archive -> `canonical-now`
- `project-state` as index + canonical map + active commitments -> `canonical-now`
- `project/specs/**` as the default home for stable contract docs -> `canonical-now`
- stable specs as the winning contract layer -> `canonical-now`
- `project/research/*.md` as the default home for imported deep-research findings -> `canonical-now`
- research artifacts with explicit source linkage back to repo-native docs -> `canonical-now`
- explicit decision-doc lane for durable tradeoffs when needed -> `optional-next`
- staged lifecycle `incubation -> research -> bounded plan decision -> carry-forward/closeout` -> `canonical-now`
- incubation frontmatter and explicit lifecycle status vocabulary -> `canonical-now`
- lifecycle relationship vocabulary, read-only relationship hygiene scan, generated relationship graph projection, CLI text-input audit posture, Entry Coverage diagnostics, heuristic split suggestions, active-plan relationship metadata on incubation note creation, reciprocal roadmap/source-incubation writeback, and coverage-aware incubation auto-archive -> `canonical-now`
- one active incubation artifact per topic -> `canonical-now`
- topic identity and `merge-before-create` discipline for incubation notes -> `canonical-now`
- visible contradiction handling and explicit promotion target for incubation notes -> `canonical-now`
- signal-driven capture and explicit provisional-note fate -> `canonical-now`
- stale-marking suggestions for old temporary artifacts -> `optional-next`
- archive entries that point to the winner artifact -> `canonical-now`
- heavy incubator hardening pack -> `later-extension`
- dedicated horizon/carry-forward stable surface expansion -> `later-extension`
- silent cleanup or deletion of temporary markdown -> `not-planned`

### Plan Synthesis and Distillation

- cheap start pass from `project-state` first -> `canonical-now`
- explicit source-set and distillation output for planning work -> `canonical-now`
- explicit source ranking with repo artifacts outranking chat residue -> `canonical-now`
- archive relevance opt-in instead of always-on archive ingestion -> `canonical-now`
- conflict surfacing when canon and draft direction disagree -> `canonical-now`
- same-topic stable spec and decision-doc pull-in -> `canonical-now`
- research-first handoff before bounded plan-open -> `canonical-now`
- deterministic routing boundary with weak-signal fallback and explicit stop conditions -> `canonical-now`
- explicit limited-confidence handoff for still-bounded execution -> `optional-next`
- repeated procedure routing into skills/checklists rather than plan or memory sprawl -> `optional-next`
- lightweight distillation helper invoked by the operator -> `optional-next`
- hidden planner memory or multi-layer nested planners -> `not-planned`

### Verification and Closeout

- block-level verification anchors instead of per-phase ritual checking -> `canonical-now`
- three-anchor default: `plan`, `integration`, `closeout` -> `canonical-now`
- explicit evidence gate before block completion -> `canonical-now`
- phantom-completion guard based on explicit evidence, not narration -> `canonical-now`
- stable-spec-ready synthesis as handoff evidence, not landed canon by itself -> `canonical-now`
- explicit carry-forward verification for deferred, open, and needs-more-research lanes -> `canonical-now`
- standalone verification verdicts for medium/high-risk or audit-heavy work -> `optional-next`
- docs decision, state writeback, verification, and commit decision in closeout summary -> `canonical-now`
- lightweight verification formatter helper -> `optional-next`
- hidden verification loops or automatic repair escalation -> `not-planned`

### Review, Isolation, and Risk Control

- optional fresh-context review recommendation for risky integration or closeout -> `optional-next`
- independent review mode as an explicit verification mode -> `canonical-now`
- worktree-backed isolated review only for risky integration or pre-merge review -> `later-extension`
- worktree-heavy default execution or review model -> `not-planned`
- automatic reviewer swarms -> `not-planned`

### Automation and Helper Surfaces

- project-wide harness-stack framing across workflow canon, skills, MCP/helper surfaces, and runtime wiring -> `canonical-now`
- harness-layer questions evaluated as workflow questions rather than isolated tooling side-quests -> `canonical-now`
- operator-invoked helper surfaces only -> `canonical-now`
- conservative docmap maintenance for workflow docs -> `canonical-now`
- bounded stale-marking suggestions -> `optional-next`
- operator-invoked helper for archive relevance / source distillation -> `optional-next`
- read-only artifact inventory, link-gap, and candidate-backlink helper aligned to the stable routing contract -> `optional-next`
- suggestion-only intake or sort surface that returns candidate lists or proposed diffs without silent mutation -> `optional-next`
- on-demand orphan or backlink audit pass -> `later-extension`
- dedicated reverse-engineering usefulness lane -> `not-planned`
- background daemons, schedulers, or always-on lifecycle managers -> `not-planned`
- required dashboards or status UIs -> `not-planned`

### Research-Derived Ideas That Stay Incubation-Only

- aggressive stale thresholds like fixed 48-hour retirement -> `incubation-only`
- automatic context compaction and re-injection hooks as a core dependency -> `incubation-only`
- automatic phantom-completion hook enforcement as a correctness dependency -> `incubation-only`
- LLM garbage-collector agents -> `incubation-only`
- complex multi-agent arbitration or voting frameworks -> `incubation-only`

## Implementation Intent

Future bounded workflow-upgrade implementation plans should start from the Core v0 canon and promote only the specific deferred lane they are scoped to handle.

The workflow should not treat `later-extension` items as hidden commitments. They are useful extensions, not part of the first required scaffold.

No later plan should treat skills, MCP, hooks, adapters, evidence IDs, quality gates, package/archive regeneration, or operational lifecycle decision as already promoted by Core v0.

## Guardrail

No future implementation pass should claim roadmap coverage by landing only helper automation while leaving the underlying canonical rules implicit. The contract must stay readable from the stable specs even if no helper ever lands.
