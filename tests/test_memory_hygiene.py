from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mylittleharness.cli import main


class MemoryHygieneTests(unittest.TestCase):
    def test_dry_run_reports_exact_lifecycle_plan_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            make_research_source(root)
            (root / "project/plan-incubation/lane.md").write_text(
                "See `project/research/raw-import.md` and [raw](../research/raw-import.md).\n",
                encoding="utf-8",
            )
            before = snapshot_tree(root)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "memory-hygiene",
                        "--dry-run",
                        "--source",
                        "project/research/raw-import.md",
                        "--promoted-to",
                        "project/specs/workflow/workflow-memory-routing-spec.md",
                        "--archive-to",
                        "project/archive/reference/research/2026-05-01-raw-import/raw-import.md",
                        "--repair-links",
                    ]
                )

            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("MyLittleHarness memory-hygiene --dry-run", rendered)
            self.assertIn("memory-hygiene-dry-run", rendered)
            self.assertIn("would update lifecycle frontmatter", rendered)
            self.assertIn("would archive source", rendered)
            self.assertIn("would repair exact links", rendered)
            self.assertIn("cannot approve closeout, archive, commit, rollback, or lifecycle decisions", rendered)

    def test_apply_updates_frontmatter_archives_source_and_repairs_exact_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source = make_research_source(root)
            lane = root / "project/plan-incubation/lane.md"
            lane.write_text(
                "Promoted from `project/research/raw-import.md`.\n"
                "Relative link stays untouched: [raw](../research/raw-import.md).\n",
                encoding="utf-8",
            )
            archive_rel = "project/archive/reference/research/2026-05-01-raw-import/raw-import.md"
            output = io.StringIO()

            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "memory-hygiene",
                        "--apply",
                        "--source",
                        "project/research/raw-import.md",
                        "--promoted-to",
                        "project/specs/workflow/workflow-memory-routing-spec.md",
                        "--archive-to",
                        archive_rel,
                        "--repair-links",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertFalse(source.exists())
            archived = root / archive_rel
            self.assertTrue(archived.is_file())
            archived_text = archived.read_text(encoding="utf-8")
            self.assertIn('status: "distilled"', archived_text)
            self.assertIn('promoted_to: "project/specs/workflow/workflow-memory-routing-spec.md"', archived_text)
            self.assertIn(f'archived_to: "{archive_rel}"', archived_text)
            self.assertIn("# Raw Import", archived_text)
            self.assertIn(f"`{archive_rel}`", lane.read_text(encoding="utf-8"))
            self.assertIn("../research/raw-import.md", lane.read_text(encoding="utf-8"))
            self.assertIn("memory-hygiene-archived", output.getvalue())
            self.assertIn("memory-hygiene-link-repaired", output.getvalue())

    def test_apply_refuses_product_fixture_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_product_fixture_root(Path(tmp))
            make_research_source(root)
            before = snapshot_tree(root)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "memory-hygiene",
                        "--apply",
                        "--source",
                        "project/research/raw-import.md",
                        "--promoted-to",
                        "project/specs/workflow/workflow-memory-routing-spec.md",
                    ]
                )

            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("memory-hygiene-refused", output.getvalue())
            self.assertIn("product-source compatibility fixture", output.getvalue())

    def test_apply_refuses_archive_conflict_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            source = make_research_source(root)
            archive_rel = "project/archive/reference/research/2026-05-01-raw-import/raw-import.md"
            archive = root / archive_rel
            archive.parent.mkdir(parents=True)
            archive.write_text("existing archive\n", encoding="utf-8")
            before = snapshot_tree(root)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "memory-hygiene",
                        "--apply",
                        "--source",
                        "project/research/raw-import.md",
                        "--promoted-to",
                        "project/specs/workflow/workflow-memory-routing-spec.md",
                        "--archive-to",
                        archive_rel,
                    ]
                )

            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertTrue(source.is_file())
            self.assertIn("archive target already exists", output.getvalue())


def make_live_root(root: Path) -> Path:
    (root / ".codex").mkdir(parents=True)
    (root / "project/specs/workflow").mkdir(parents=True)
    (root / "project/plan-incubation").mkdir(parents=True)
    (root / "project/research").mkdir(parents=True)
    (root / ".codex/project-workflow.toml").write_text(
        'workflow = "workflow-core"\nversion = 1\n\n[memory]\nstate_file = "project/project-state.md"\nplan_file = "project/implementation-plan.md"\n',
        encoding="utf-8",
    )
    (root / "project/project-state.md").write_text(
        '---\nproject: "Demo"\nworkflow: "workflow-core"\noperating_mode: "ad_hoc"\nplan_status: "none"\nactive_plan: ""\n---\n# Demo Project State\n',
        encoding="utf-8",
    )
    (root / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")
    (root / "project/specs/workflow/workflow-memory-routing-spec.md").write_text("# Routing Spec\n", encoding="utf-8")
    return root


def make_product_fixture_root(root: Path) -> Path:
    make_live_root(root)
    state = root / "project/project-state.md"
    state.write_text(
        state.read_text(encoding="utf-8").replace(
            'workflow: "workflow-core"\n',
            'root_role: "product-source"\nfixture_status: "product-compatibility-fixture"\nworkflow: "workflow-core"\n',
        ),
        encoding="utf-8",
    )
    return root


def make_research_source(root: Path) -> Path:
    path = root / "project/research/raw-import.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        'status: "imported"\n'
        'topic: "raw import"\n'
        'created: "2026-05-01"\n'
        "---\n"
        "# Raw Import\n\n"
        "Raw imported notes.\n",
        encoding="utf-8",
    )
    return path


def snapshot_tree(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel_path = path.relative_to(root).as_posix()
        snapshot[rel_path] = "<dir>" if path.is_dir() else path.read_text(encoding="utf-8")
    return snapshot


if __name__ == "__main__":
    unittest.main()
