from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mylittleharness.inventory import load_inventory
from mylittleharness.research_compare import (
    compare_research_texts,
    make_research_compare_request,
    research_compare_apply_findings,
    research_compare_dry_run_findings,
)


IMPORTED_RESEARCH = """---
status: "imported"
title: "Deep Research Import"
derived_from: "manual export"
related_artifacts:
  - "project/research/prompt-packet.md"
---
# Deep Research Import

## Candidate MLH Improvements

- Add exact provenance checks to `project/plan-incubation/provenance-gap.md`.
- Candidate route: `src/mylittleharness/checks.py`

## Open Questions

- Risk: source confidence is still unknown.
"""


DISTILLED_RESEARCH = """---
status: "distilled"
title: "Deep Research Distillate"
derived_from: "project/research/deep-research-import.md"
---
# Deep Research Distillate

## Accepted Candidates

- Add exact provenance checks to `project/plan-incubation/provenance-gap.md`.

## Unresolved Gaps

- Tension: `project/plan-incubation/provenance-gap.md` still needs human review before roadmap promotion.
- How should `project/roadmap.md` preserve confidence gaps?
"""


class ResearchCompareTests(unittest.TestCase):
    def test_compare_extracts_shared_candidates_conflicts_gaps_and_routes(self) -> None:
        extraction = compare_research_texts(
            (
                ("project/research/import.md", IMPORTED_RESEARCH),
                ("project/research/distillate.md", DISTILLED_RESEARCH),
            )
        )

        self.assertTrue(any("provenance-gap.md" in item for item in extraction.shared_candidates))
        self.assertTrue(any("unresolved/gap-linked" in item for item in extraction.conflicts))
        self.assertTrue(any("source confidence is still unknown" in item for item in extraction.unresolved_gaps))
        self.assertIn("project/research/import.md", extraction.source_links)
        self.assertIn("project/research/prompt-packet.md", extraction.source_links)
        self.assertIn("project/plan-incubation/provenance-gap.md", extraction.route_proposals)
        self.assertIn("src/mylittleharness/checks.py", extraction.route_proposals)
        self.assertIn("project/roadmap.md", extraction.route_proposals)

    def test_dry_run_reports_comparison_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            import_source, distill_source = write_sources(root)
            before = snapshot_tree(root)
            request = make_research_compare_request(
                (
                    str(import_source.relative_to(root)).replace("\\", "/"),
                    str(distill_source.relative_to(root)).replace("\\", "/"),
                )
            )

            findings = research_compare_dry_run_findings(load_inventory(root), request)

            self.assertEqual(before, snapshot_tree(root))
            rendered = "\n".join(finding.render() for finding in findings)
            self.assertIn("research-compare-dry-run", rendered)
            self.assertIn("research-compare-source-hash", rendered)
            self.assertIn("research-compare-extraction", rendered)
            self.assertIn("conflicts=", rendered)
            self.assertIn("route_proposals=", rendered)
            self.assertFalse((root / "project/research/deep-research-import-comparison.md").exists())

    def test_apply_writes_one_compared_research_artifact_with_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            import_source, distill_source = write_sources(root)
            before = snapshot_tree(root)
            request = make_research_compare_request(
                (
                    str(import_source.relative_to(root)).replace("\\", "/"),
                    str(distill_source.relative_to(root)).replace("\\", "/"),
                ),
                target="project/research/deep-research-comparison.md",
                topic="Deep Research",
            )

            findings = research_compare_apply_findings(load_inventory(root), request)

            rendered = "\n".join(finding.render() for finding in findings)
            self.assertIn("research-compare-written", rendered)
            self.assertIn("research-compare-route-write", rendered)
            after = snapshot_tree(root)
            changed = [rel for rel in after if before.get(rel) != after.get(rel)]
            self.assertEqual(["project/research/deep-research-comparison.md"], changed)

            text = (root / "project/research/deep-research-comparison.md").read_text(encoding="utf-8")
            self.assertIn('status: "compared"', text)
            self.assertIn("compared_sources:", text)
            self.assertIn("## Shared Candidates", text)
            self.assertIn("provenance-gap.md", text)
            self.assertIn("## Conflicts And Tensions", text)
            self.assertIn("unresolved/gap-linked", text)
            self.assertIn("## Route Proposals", text)
            self.assertIn("It does not decide which source is true", text)

    def test_archive_sources_dry_run_reports_distill_archive_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            import_source, distill_source = write_sources(root)
            lane = root / "project/plan-incubation/lane.md"
            lane.parent.mkdir(parents=True, exist_ok=True)
            lane.write_text(
                "Compare from `project/research/import.md` and `project/research/distillate.md`.\n"
                "Relative source link remains untouched: [import](../research/import.md).\n",
                encoding="utf-8",
            )
            before = snapshot_tree(root)

            findings = research_compare_dry_run_findings(
                load_inventory(root),
                make_research_compare_request(
                    (
                        str(import_source.relative_to(root)).replace("\\", "/"),
                        str(distill_source.relative_to(root)).replace("\\", "/"),
                    ),
                    target="project/research/deep-research-comparison.md",
                    archive_sources=True,
                    repair_links=True,
                ),
            )

            self.assertEqual(before, snapshot_tree(root))
            rendered = "\n".join(finding.render() for finding in findings)
            self.assertIn("research-compare-archive-before-removal", rendered)
            self.assertIn("research-compare-source-metadata-plan", rendered)
            self.assertIn("research-compare-link-repair-plan", rendered)
            self.assertIn("research-compare-unresolved-followups-preserved", rendered)
            self.assertIn("would create route project/archive/reference/research", rendered)
            self.assertIn("would delete route project/research/import.md", rendered)

    def test_apply_archives_sources_updates_metadata_preserves_gaps_and_repairs_exact_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            import_source, distill_source = write_sources(root)
            lane = root / "project/plan-incubation/lane.md"
            lane.parent.mkdir(parents=True, exist_ok=True)
            lane.write_text(
                "Compare from `project/research/import.md` and `project/research/distillate.md`.\n"
                "Relative source link remains untouched: [import](../research/import.md).\n",
                encoding="utf-8",
            )

            findings = research_compare_apply_findings(
                load_inventory(root),
                make_research_compare_request(
                    (
                        str(import_source.relative_to(root)).replace("\\", "/"),
                        str(distill_source.relative_to(root)).replace("\\", "/"),
                    ),
                    target="project/research/deep-research-comparison.md",
                    archive_sources=True,
                    repair_links=True,
                ),
            )

            rendered = "\n".join(finding.render() for finding in findings)
            self.assertIn("research-compare-written", rendered)
            self.assertIn("research-compare-source-archived", rendered)
            self.assertIn("research-compare-link-repaired", rendered)
            self.assertFalse(import_source.exists())
            self.assertFalse(distill_source.exists())

            import_archive = f"project/archive/reference/research/{date.today().isoformat()}-import/import.md"
            distill_archive = f"project/archive/reference/research/{date.today().isoformat()}-distillate/distillate.md"
            self.assertTrue((root / import_archive).is_file())
            self.assertTrue((root / distill_archive).is_file())
            import_archive_text = (root / import_archive).read_text(encoding="utf-8")
            self.assertIn('status: "distilled"', import_archive_text)
            self.assertIn('promoted_to: "project/research/deep-research-comparison.md"', import_archive_text)
            self.assertIn(f'archived_to: "{import_archive}"', import_archive_text)

            comparison_text = (root / "project/research/deep-research-comparison.md").read_text(encoding="utf-8")
            self.assertIn(import_archive, comparison_text)
            self.assertIn(distill_archive, comparison_text)
            self.assertIn("source confidence is still unknown", comparison_text)
            self.assertIn("still needs human review", comparison_text)
            self.assertIn("archived from `project/research/import.md`", comparison_text)

            lane_text = lane.read_text(encoding="utf-8")
            self.assertIn(f"`{import_archive}`", lane_text)
            self.assertIn(f"`{distill_archive}`", lane_text)
            self.assertIn("../research/import.md", lane_text)

    def test_apply_refuses_product_fixture_unsafe_source_and_existing_target_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            product_root = make_product_root(Path(tmp) / "product")
            import_source, distill_source = write_sources(product_root)
            before = snapshot_tree(product_root)
            findings = research_compare_apply_findings(
                load_inventory(product_root),
                make_research_compare_request(
                    (
                        str(import_source.relative_to(product_root)).replace("\\", "/"),
                        str(distill_source.relative_to(product_root)).replace("\\", "/"),
                    )
                ),
            )
            rendered = "\n".join(finding.render() for finding in findings)
            self.assertEqual(before, snapshot_tree(product_root))
            self.assertIn("product-source compatibility fixture", rendered)

        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            write_sources(root)
            before = snapshot_tree(root)
            findings = research_compare_apply_findings(
                load_inventory(root),
                make_research_compare_request(("project/research/import.md", "project/plan-incubation/source.md")),
            )
            rendered = "\n".join(finding.render() for finding in findings)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("source must be under project/research/*.md", rendered)

        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            import_source, distill_source = write_sources(root)
            existing = root / "project/research/out.md"
            existing.write_text("existing\n", encoding="utf-8")
            before = snapshot_tree(root)
            findings = research_compare_apply_findings(
                load_inventory(root),
                make_research_compare_request(
                    (
                        str(import_source.relative_to(root)).replace("\\", "/"),
                        str(distill_source.relative_to(root)).replace("\\", "/"),
                    ),
                    target="project/research/out.md",
                ),
            )
            rendered = "\n".join(finding.render() for finding in findings)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("target research artifact already exists", rendered)


def write_sources(root: Path) -> tuple[Path, Path]:
    research_dir = root / "project/research"
    research_dir.mkdir(parents=True, exist_ok=True)
    import_source = research_dir / "import.md"
    distill_source = research_dir / "distillate.md"
    import_source.write_text(IMPORTED_RESEARCH, encoding="utf-8")
    distill_source.write_text(DISTILLED_RESEARCH, encoding="utf-8")
    return import_source, distill_source


def make_live_root(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".codex").mkdir()
    (root / "project").mkdir()
    (root / "project/research").mkdir()
    (root / ".codex/project-workflow.toml").write_text(
        'workflow = "workflow-core"\n'
        "version = 1\n\n"
        "[memory]\n"
        'state_file = "project/project-state.md"\n'
        'plan_file = "project/implementation-plan.md"\n',
        encoding="utf-8",
    )
    (root / "project/project-state.md").write_text(
        "---\n"
        'project: "Sample"\n'
        'workflow: "workflow-core"\n'
        'operating_mode: "plan"\n'
        'plan_status: "none"\n'
        'active_plan: ""\n'
        "---\n"
        "# Sample\n",
        encoding="utf-8",
    )
    (root / "AGENTS.md").write_text("# Contract\n", encoding="utf-8")
    return root


def make_product_root(root: Path) -> Path:
    make_live_root(root)
    state = root / "project/project-state.md"
    state.write_text(state.read_text(encoding="utf-8").replace('workflow: "workflow-core"\n', 'workflow: "workflow-core"\nroot_role: "product-source"\n'), encoding="utf-8")
    return root


def snapshot_tree(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)).replace("\\", "/"): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


if __name__ == "__main__":
    unittest.main()
