from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mylittleharness.lifecycle_focus import sync_current_focus_block


class LifecycleFocusTests(unittest.TestCase):
    def test_sync_inserts_active_focus_and_removes_legacy_leading_summary(self) -> None:
        state = (
            "---\n"
            'project: "Demo"\n'
            'plan_status: "active"\n'
            'active_plan: "project/implementation-plan.md"\n'
            'active_phase: "phase-2-build"\n'
            'phase_status: "in_progress"\n'
            "---\n"
            "# Demo Project State\n\n"
            "## Current Focus\n\n"
            "Current focus: stale old phase text.\n\n"
            "Durable note stays here.\n\n"
            "## Notes\n\n"
            "Keep me.\n"
        )

        synced = sync_current_focus_block(state)

        self.assertIn("<!-- BEGIN mylittleharness-current-focus v1 -->", synced)
        self.assertIn("Continue from active_phase `phase-2-build` with phase_status `in_progress`.", synced)
        self.assertNotIn("Current focus: stale old phase text.", synced)
        self.assertIn("Durable note stays here.", synced)
        self.assertIn("## Notes\n\nKeep me.", synced)

    def test_sync_replaces_existing_focus_block(self) -> None:
        state = (
            "---\n"
            'project: "Demo"\n'
            'plan_status: "none"\n'
            'active_plan: ""\n'
            'last_archived_plan: "project/archive/plans/closed.md"\n'
            "---\n"
            "# Demo Project State\n\n"
            "## Current Focus\n\n"
            "<!-- BEGIN mylittleharness-current-focus v1 -->\n"
            "Current focus: active implementation plan is open at `project/implementation-plan.md`.\n"
            "<!-- END mylittleharness-current-focus v1 -->\n\n"
            "Human note stays.\n"
        )

        synced = sync_current_focus_block(state)

        self.assertEqual(1, synced.count("<!-- BEGIN mylittleharness-current-focus v1 -->"))
        self.assertIn("Current focus: no active implementation plan is open.", synced)
        self.assertIn("Last archived plan: `project/archive/plans/closed.md`.", synced)
        self.assertIn("Human note stays.", synced)


if __name__ == "__main__":
    unittest.main()
