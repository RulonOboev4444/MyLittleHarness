from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mylittleharness.planning import make_plan_request, render_implementation_plan


class PlanningTests(unittest.TestCase):
    def test_renderer_emits_required_frontmatter_and_sections(self) -> None:
        request = make_plan_request(
            "Plan Synthesis Rail",
            "Create deterministic implementation plans for live roots.",
            "Preserve explicit task input.",
        )
        rendered = render_implementation_plan(request, today=date(2026, 5, 1))

        for expected in (
            'plan_id: "2026-05-01-plan-synthesis-rail"',
            'title: "Plan Synthesis Rail"',
            'status: "pending"',
            'active_phase: "phase-1-implementation"',
            'phase_status: "pending"',
            'docs_decision: "uncertain"',
            "# Plan Synthesis Rail",
            "## Objective",
            "## Explicit Task Input",
            "## Authority Inputs",
            "## Non-goals",
            "## Invariants",
            "## File Ownership",
            "## Phases",
            "## Verification Strategy",
            "## Docs Decision",
            "## State Transfer",
            "## Refusal Conditions",
            "## Closeout Checklist",
            "## Decision Log",
        ):
            self.assertIn(expected, rendered)

    def test_renderer_defaults_docs_decision_to_uncertain(self) -> None:
        rendered = render_implementation_plan(
            make_plan_request("Docs Decision", "Track docs posture.", None),
            today=date(2026, 5, 1),
        )

        self.assertIn('docs_decision: "uncertain"', rendered)
        self.assertIn("- docs_decision: uncertain", rendered)

    def test_renderer_defaults_do_not_contain_destructive_rollback_commands(self) -> None:
        rendered = render_implementation_plan(
            make_plan_request("Safe Recovery", "Keep recovery bounded.", None),
            today=date(2026, 5, 1),
        ).casefold()

        for forbidden in (
            "git reset --hard",
            "git checkout --",
            "git restore .",
            "git clean -fd",
            "rm -rf",
            "remove-item -recurse",
        ):
            self.assertNotIn(forbidden, rendered)


if __name__ == "__main__":
    unittest.main()
