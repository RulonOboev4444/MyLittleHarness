# Workflow Capability Roadmap Spec

> Product fixture note: In a product source checkout, this spec is retained as a product compatibility fixture for CLI/tests. Operational workflow authority, plans, research, and memory remain in the operating project root; historical archive/evidence material is opt-in only.

## Purpose

This spec records the full useful capability roadmap for the workflow-level upgrade so that important future improvements do not remain trapped in chat history, research notes, or the implementation plan of one nearby slice.
The roadmap is for a repo-native workflow contract where the canonical behavior should remain inspectable and portable with the repository.

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
- operational switch-over, package/archive regeneration, skills/MCP/hooks redesign, candidate tooling, evidence IDs, quality gates, task execution, backlog, bootstrap/cache/generated-state, and adapters are not Core v0; they remain deferred lanes unless a later plan promotes them

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

No later plan should treat skills, MCP, hooks, adapters, evidence IDs, quality gates, package/archive regeneration, or operational switch-over as already promoted by Core v0.

## Guardrail

No future implementation pass should claim roadmap coverage by landing only helper automation while leaving the underlying canonical rules implicit. The contract must stay readable from the stable specs even if no helper ever lands.


