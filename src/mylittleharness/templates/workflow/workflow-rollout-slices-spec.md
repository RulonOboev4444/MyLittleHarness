# Workflow Rollout Slices Spec

This stable workflow spec fixture anchors the expected rollout slices surface for a MyLittleHarness operating root.

Repo-visible project files remain authoritative. This fixture is repair-created only when absent, and it cannot approve repair, closeout, archive, commit, rollback, lifecycle decisions, or future mutations.

Roadmap execution-slice metadata such as `execution_slice`, `slice_members`, and `slice_closeout_boundary` is advisory sequencing evidence. Accepted or active item boundary wording that still reflects an earlier no-plan/no-archive research posture should be carried into the active plan only as a normalized non-authority safety note. The active implementation plan carries the executable slice copy, including current-phase-only execution metadata. A completed phase can become ready for explicit closeout/writeback without archive, roadmap done-status, or next-slice movement. Roadmap grouping cannot approve lifecycle movement or next-slice closeout.

Bundle/split rationale and target-artifact pressure reports are review aids for bounded plan synthesis, not hard gates or lifecycle authority.

Generated plans default to `execution_policy = current-phase-only`, `auto_continue = false`, and repo-visible `stop_conditions`; verification success alone does not authorize the next phase.

Read-only grain diagnostics may compare active and archived plans for roadmap item count, phase count, target artifact count, write-scope specificity, verification specificity, stop points, closeout evidence, and roadmap live-tail hygiene. They should flag under-decomposed plans when a single phase carries multiple target artifacts with generic write scope or verification gates. Their output is empirical tuning evidence only, not an automatic split, compaction, closeout, or lifecycle decision.
