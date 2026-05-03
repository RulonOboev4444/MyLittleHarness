# Workflow Plan Synthesis Spec

This stable workflow spec fixture anchors the expected plan synthesis surface for a MyLittleHarness operating root.

Repo-visible project files remain authoritative. This fixture is repair-created only when absent, and it cannot approve repair, closeout, archive, commit, rollback, lifecycle decisions, or future mutations.

Roadmap-backed plans should keep the executable one-slice contract in active-plan frontmatter: `primary_roadmap_item`, `covered_roadmap_items`, `domain_context`, `target_artifacts`, `execution_policy`, `auto_continue`, `stop_conditions`, and `closeout_boundary`. The default generated policy is current-phase-only with `auto_continue = false`; verification success does not authorize a later phase by itself. `project/project-state.md` remains lifecycle pointer authority rather than slice-membership storage.

Roadmap-backed plan synthesis may report bundle rationale, split boundary, `target_artifact_pressure`, and `phase_pressure` in dry-run/apply output and generated `Plan Synthesis Notes`. These are advisory sizing signals only; they cannot approve repair, closeout, archive, commit, rollback, lifecycle decisions, or future mutations.

Read-only grain diagnostics may inspect active plans for missing slice metadata, target-artifact gaps, vague write scope, generic verification, over-atomic slices, giant brittle slices, and unsafe auto-continuation posture. They are calibration inputs only and do not rewrite plans or promote numeric thresholds into hard gates.
