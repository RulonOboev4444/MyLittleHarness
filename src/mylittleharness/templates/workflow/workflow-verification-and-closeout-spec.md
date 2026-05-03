# Workflow Verification And Closeout Spec

This stable workflow spec fixture anchors the expected verification and closeout surface for a MyLittleHarness operating root.

Repo-visible project files remain authoritative. This fixture is repair-created only when absent, and it cannot approve repair, closeout, archive, commit, rollback, lifecycle decisions, or future mutations.

Verified phase work stops at repo-visible state/evidence unless the active plan explicitly opts into `auto_continue` and records stop-condition coverage. Closeout preparation remains an explicit boundary, not an automatic side effect of passing checks. `writeback --phase-status complete` is a ready-for-closeout boundary only; archive, roadmap done-status, source-incubation archive, and next-slice opening require separate explicit requests.

Read-only grain diagnostics may flag generic verification gates, raw-log-heavy plans, done roadmap items without archived evidence, and weak archived-plan closeout samples. These findings are closeout prompts and calibration evidence only; they cannot mark work verified, write closeout state, archive a plan, or change roadmap status.
