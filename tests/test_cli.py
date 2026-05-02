from __future__ import annotations

import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mylittleharness.cli import main
from mylittleharness.inventory import EXPECTED_SPEC_NAMES
from mylittleharness.projection_artifacts import ARTIFACT_DIR_REL
from mylittleharness.projection_index import INDEX_REL_PATH
from mylittleharness.vcs import VcsChangedPath, VcsPosture


class CliTests(unittest.TestCase):
    def test_status_report_sections_and_zero_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=True, mirrors=True)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "status"])
            self.assertEqual(code, 0)
            rendered = output.getvalue()
            for heading in ("Root", "Result", "Sources", "Findings", "Suggestions"):
                self.assertIn(heading, rendered)
            self.assertIn("MyLittleHarness status", rendered)
            self.assertNotIn("lifecycle-route-table", rendered)

    def test_check_composes_status_and_validate_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=True)
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "check"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("MyLittleHarness check", rendered)
            for heading in ("Status", "Validation", "Drift", "Boundary"):
                self.assertIn(heading, rendered)
            self.assertIn("check-read-only", rendered)
            self.assertIn("check-drift-ok", rendered)
            self.assertIn("fixture-status", rendered)
            self.assertIn("state-field", rendered)
            self.assertNotIn("lifecycle-route-table", rendered)

    def test_live_status_and_check_report_full_route_table_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            before = snapshot_tree(root)
            reports = []
            for command in (["status"], ["check"]):
                output = io.StringIO()
                with redirect_stdout(output):
                    code = main(["--root", str(root), *command])
                self.assertEqual(code, 0)
                self.assertEqual(before, snapshot_tree(root))
                reports.append(output.getvalue())

            for rendered in reports:
                self.assertIn("lifecycle-route-table", rendered)
                self.assertIn("advisory only and cannot approve mutation, repair, closeout, archive, commit, or lifecycle decisions", rendered)
                for expected in (
                    "state: project/project-state.md",
                    "active-plan: project/implementation-plan.md",
                    "incubation: project/plan-incubation/*.md",
                    "research: project/research/*.md",
                    "stable-specs: project/specs/**/*.md",
                    "decisions: project/decisions/*.md",
                    "verification: active-plan verification block",
                    "closeout-writeback: project/project-state.md MLH closeout writeback block",
                    "archive: project/archive/plans/*.md; project/archive/reference/**",
                    "docs-routing: .agents/docmap.yaml",
                    "future-optional: project/verification/*.md; project/adrs/*.md; reusable procedural surfaces",
                ):
                    self.assertIn(expected, rendered)

    def test_check_and_validate_report_route_metadata_warnings_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            (root / "project/research").mkdir()
            (root / "project/research/bad.md").write_text(
                "---\n"
                'status: "teleported"\n'
                'archived_to: "project/archive/reference/research/missing.md"\n'
                "---\n"
                "# Bad\n",
                encoding="utf-8",
            )
            before = snapshot_tree(root)
            for command in (["validate"], ["check"], ["check", "--focus", "validation"]):
                with self.subTest(command=command):
                    output = io.StringIO()
                    with redirect_stdout(output):
                        code = main(["--root", str(root), *command])
                    rendered = output.getvalue()
                    self.assertEqual(code, 0)
                    self.assertEqual(before, snapshot_tree(root))
                    self.assertIn("route-metadata-status", rendered)
                    self.assertIn("route-metadata-missing-target", rendered)
                    self.assertIn("route-metadata-authority", rendered)

    def test_completed_active_phase_reports_next_lifecycle_action_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_active_live_root(Path(tmp), phase_status="complete")
            (root / "project/implementation-plan.md").write_text(
                "---\n"
                'title: "Plan"\n'
                'status: "active"\n'
                "---\n"
                "# Plan\n",
                encoding="utf-8",
            )
            before = snapshot_tree(root)
            reports = []
            for command in (["status"], ["check"]):
                output = io.StringIO()
                with redirect_stdout(output):
                    code = main(["--root", str(root), *command])
                self.assertEqual(code, 0)
                self.assertEqual(before, snapshot_tree(root))
                reports.append(output.getvalue())

            for rendered in reports:
                self.assertIn("lifecycle-summary", rendered)
                self.assertIn("implementation work is not pending", rendered)
                self.assertIn("next action is explicit closeout/writeback, archive, or manual commit per policy", rendered)
            self.assertIn("active-plan-lifecycle-drift", reports[1])
            self.assertIn("phase_status is complete but active-plan frontmatter status is active", reports[1])

    def test_product_fixture_status_and_check_do_not_emit_live_route_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=True)
            for command in (["status"], ["check"]):
                with self.subTest(command=command):
                    output = io.StringIO()
                    with redirect_stdout(output):
                        code = main(["--root", str(root), *command])
                    rendered = output.getvalue()
                    self.assertEqual(code, 0)
                    self.assertIn("product-source", rendered)
                    self.assertNotIn("lifecycle-route-table", rendered)
                    self.assertNotIn("[INFO] lifecycle-route", rendered)

    def test_check_reports_docmap_and_root_pointer_drift_without_failing_or_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            (root / "docs").mkdir()
            archive_root = root.parent / "legacy-root"
            (root / "docs/README.md").write_text(
                f"{archive_root} is current source.\n{root} is the operating root.\n",
                encoding="utf-8",
            )
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "check"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("Drift", rendered)
            self.assertIn("candidate-docmap-gap", rendered)
            self.assertIn("stale-fallback-root-reference", rendered)
            self.assertIn("stale-product-root-role", rendered)

    def test_check_reports_rule_context_warning_without_failing_or_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=True)
            (root / "AGENTS.md").write_text("# AGENTS\n" + ("Instruction line.\n" * 501), encoding="utf-8")
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "check"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("Drift", rendered)
            self.assertIn("rule-context-surface-large", rendered)
            self.assertIn("use context-budget for section detail", rendered)

    def test_check_returns_one_on_validation_errors_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=True, mirrors=True)
            (root / "project/specs/workflow" / EXPECTED_SPEC_NAMES[0]).unlink()
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "check"])
            rendered = output.getvalue()
            self.assertEqual(code, 1)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("status: error", rendered)
            self.assertIn("missing-stable-spec", rendered)
            self.assertIn("check found validation errors", rendered)

    def test_check_deep_includes_links_context_and_hygiene_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "check", "--deep"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("MyLittleHarness check --deep", rendered)
            for heading in ("Status", "Validation", "Drift", "Links", "Context", "Hygiene", "Boundary"):
                self.assertIn(heading, rendered)
            self.assertIn("check-deep-read-only", rendered)
            self.assertIn("check --deep completed as a read-only status, validation, drift, links, context, and hygiene report", rendered)

    def test_check_deep_returns_one_on_included_validation_errors_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=True, mirrors=True)
            (root / "project/specs/workflow" / EXPECTED_SPEC_NAMES[0]).unlink()
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "check", "--deep"])
            rendered = output.getvalue()
            self.assertEqual(code, 1)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("MyLittleHarness check --deep", rendered)
            self.assertIn("missing-stable-spec", rendered)

    def test_check_focus_modes_run_one_diagnostic_without_writes(self) -> None:
        cases = (
            ("validation", "Validation", "missing-stable-spec"),
            ("links", "Links", "missing-link"),
            ("context", "Context", "file-budget"),
            ("hygiene", "Hygiene", "product-hygiene"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=True, mirrors=True)
            (root / "README.md").write_text("See `missing/path.md`.\n", encoding="utf-8")
            (root / "project/specs/workflow" / EXPECTED_SPEC_NAMES[0]).unlink()
            (root / "project/research").mkdir(parents=True)
            (root / "project/research/debris.md").write_text("debris\n", encoding="utf-8")
            before = snapshot_tree(root)
            for focus, heading, expected in cases:
                with self.subTest(focus=focus):
                    output = io.StringIO()
                    with redirect_stdout(output):
                        code = main(["--root", str(root), "check", "--focus", focus])
                    rendered = output.getvalue()
                    self.assertEqual(before, snapshot_tree(root))
                    self.assertIn(f"MyLittleHarness check --focus {focus}", rendered)
                    self.assertIn(heading, rendered)
                    self.assertIn("Boundary", rendered)
                    self.assertIn("check-focus-read-only", rendered)
                    self.assertIn(expected, rendered)
                    if focus == "context":
                        self.assertIn("check --focus context runs one compatibility diagnostic without writing files", rendered)
                    if focus in {"validation", "hygiene"}:
                        self.assertEqual(code, 1)
                    else:
                        self.assertEqual(code, 0)

    def test_check_rejects_combined_or_unknown_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=True)
            for command in (
                ["check", "--deep", "--focus", "validation"],
                ["check", "--focus", "unknown"],
            ):
                with self.subTest(command=command):
                    output = io.StringIO()
                    with redirect_stderr(output), self.assertRaises(SystemExit) as raised:
                        main(["--root", str(root), *command])
                    self.assertEqual(raised.exception.code, 2)

    def test_init_dry_run_routes_to_attach_behavior_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "init", "--dry-run"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("MyLittleHarness init --dry-run", rendered)
            self.assertIn("product-source compatibility fixture", rendered)
            self.assertIn("no-op", rendered)

    def test_init_apply_refuses_product_fixture_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "init", "--apply", "--project", "Smoke"])
            rendered = output.getvalue()
            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("MyLittleHarness init --apply", rendered)
            self.assertIn("attach-refused", rendered)
            self.assertFalse((root / INDEX_REL_PATH).exists())

    def test_init_apply_builds_generated_projection_and_index_for_new_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "init", "--apply", "--project", "Demo"])
            rendered = output.getvalue()

            self.assertEqual(code, 0)
            self.assertTrue((root / ARTIFACT_DIR_REL / "manifest.json").is_file())
            self.assertTrue((root / INDEX_REL_PATH).is_file())
            self.assertIn("attach-generated-projection-build", rendered)
            self.assertIn("projection-artifact-build", rendered)
            self.assertIn("projection-index-build", rendered)

            intelligence_output = io.StringIO()
            with redirect_stdout(intelligence_output):
                intelligence_code = main(["--root", str(root), "intelligence", "--focus", "search", "--query", "Demo"])
            self.assertEqual(intelligence_code, 0)
            self.assertIn("projection-index-query-current", intelligence_output.getvalue())

    def test_intelligence_focus_routes_reports_route_table_only_for_live_roots_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "intelligence", "--focus", "routes"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("Boundary", rendered)
            self.assertIn("Lifecycle Routes", rendered)
            self.assertIn("Discovered Routes", rendered)
            self.assertIn("intelligence-routes-read-only", rendered)
            self.assertIn("lifecycle-route-table", rendered)
            self.assertIn("memory-route-inventory", rendered)
            self.assertIn("project/project-state.md -> state", rendered)
            self.assertIn(".codex/project-workflow.toml -> operating-guardrails", rendered)
            self.assertIn("decisions: project/decisions/*.md", rendered)
            self.assertIn("future-optional: project/verification/*.md; project/adrs/*.md; reusable procedural surfaces", rendered)
            self.assertNotIn("Repo Map", rendered)
            self.assertNotIn("Search", rendered)

    def test_intelligence_focus_routes_keeps_product_fixtures_out_of_live_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=True)
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "intelligence", "--focus", "routes"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("route-table-scope", rendered)
            self.assertIn("product-source fixtures remain product/fixture context", rendered)
            self.assertNotIn("lifecycle-route-table", rendered)
            self.assertNotIn("[INFO] lifecycle-route", rendered)
            self.assertNotIn("Discovered Routes", rendered)
            self.assertNotIn("memory-route-surface", rendered)

    def test_detach_dry_run_product_fixture_reports_preservation_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "detach", "--dry-run"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertFalse((root / ".mylittleharness").exists())
            self.assertIn("MyLittleHarness detach --dry-run", rendered)
            for heading in ("Root Posture", "Preservation", "Generated Projection", "Manual Recovery", "Boundary"):
                self.assertIn(heading, rendered)
            self.assertIn("Marker", rendered)
            for code_name in (
                "detach-dry-run",
                "detach-root-kind",
                "detach-root-posture",
                "detach-preserve",
                "detach-marker-target",
                "detach-generated-projection",
                "detach-apply-marker-only",
                "detach-disable-terminology",
                "detach-read-only",
                "detach-no-authority",
            ):
                self.assertIn(code_name, rendered)
            self.assertIn("product-source compatibility fixture", rendered)
            self.assertIn("disable is explanatory terminology", rendered)

    def test_detach_dry_run_live_root_preserves_generated_projection_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            projection_dir = root / ".mylittleharness/generated/projection"
            projection_dir.mkdir(parents=True)
            (projection_dir / "manifest.json").write_text("{}", encoding="utf-8")
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "detach", "--dry-run"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("root kind: live_operating_root", rendered)
            self.assertIn("present and preserved", rendered)
            self.assertIn(".mylittleharness/generated/projection", rendered)

    def test_detach_apply_creates_marker_for_live_root_without_authority_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            (root / ".agents").mkdir()
            (root / ".agents/docmap.yaml").write_text("version: 2\n", encoding="utf-8")
            (root / "project/archive/plans").mkdir(parents=True)
            (root / "project/archive/plans/old.md").write_text("# Old\n", encoding="utf-8")
            (root / "project/research").mkdir()
            (root / "project/research/note.md").write_text("# Research\n", encoding="utf-8")
            projection_dir = root / ".mylittleharness/generated/projection"
            projection_dir.mkdir(parents=True)
            (projection_dir / "manifest.json").write_text("{}", encoding="utf-8")
            snapshot_dir = root / ".mylittleharness/snapshots/repair/old"
            snapshot_dir.mkdir(parents=True)
            (snapshot_dir / "snapshot.json").write_text("{}", encoding="utf-8")
            preserved_paths = (
                ".codex/project-workflow.toml",
                "project/project-state.md",
                ".agents/docmap.yaml",
                "project/archive/plans/old.md",
                "project/research/note.md",
                ".mylittleharness/generated/projection/manifest.json",
                ".mylittleharness/snapshots/repair/old/snapshot.json",
            )
            before = {rel_path: (root / rel_path).read_bytes() for rel_path in preserved_paths}
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "detach", "--apply"])
            rendered = output.getvalue()
            marker_path = root / ".mylittleharness/detach/disabled.json"
            payload = json.loads(marker_path.read_text(encoding="utf-8"))
            self.assertEqual(code, 0)
            self.assertTrue(marker_path.is_file())
            self.assertEqual(before, {rel_path: (root / rel_path).read_bytes() for rel_path in preserved_paths})
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["status"], "disabled")
            self.assertEqual(payload["command"], "detach --apply")
            self.assertEqual(payload["root"], str(root.resolve()))
            self.assertEqual(payload["marker_path"], ".mylittleharness/detach/disabled.json")
            self.assertIn("project/project-state.md", payload["preserved_authority_paths"])
            self.assertIn("detach-marker-created", rendered)
            self.assertIn("detach-marker-authority", rendered)
            self.assertIn("status: disabled", rendered)

    def test_detach_apply_is_idempotent_for_valid_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            first_output = io.StringIO()
            with redirect_stdout(first_output):
                first_code = main(["--root", str(root), "detach", "--apply"])
            marker_path = root / ".mylittleharness/detach/disabled.json"
            first_marker = marker_path.read_text(encoding="utf-8")
            second_output = io.StringIO()
            with redirect_stdout(second_output):
                second_code = main(["--root", str(root), "detach", "--apply"])
            self.assertEqual(first_code, 0)
            self.assertEqual(second_code, 0)
            self.assertEqual(first_marker, marker_path.read_text(encoding="utf-8"))
            self.assertIn("detach-marker-unchanged", second_output.getvalue())

    def test_status_and_check_report_existing_detach_marker_without_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            with redirect_stdout(io.StringIO()):
                apply_code = main(["--root", str(root), "detach", "--apply"])
            self.assertEqual(apply_code, 0)
            for command in ("status", "check"):
                with self.subTest(command=command):
                    output = io.StringIO()
                    with redirect_stdout(output):
                        code = main(["--root", str(root), command])
                    rendered = output.getvalue()
                    self.assertEqual(code, 0)
                    self.assertIn(".mylittleharness/detach/disabled.json [detach-marker; optional; present]", rendered)
                    self.assertIn("detach-marker-present", rendered)
                    self.assertIn("detach-marker-authority", rendered)

    def test_detach_apply_refuses_non_live_roots_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cases = (
                make_root(base / "product", active=False, mirrors=False),
                make_fallback_root(base / "fallback"),
                make_generated_output_root(base / "generated"),
                base / "ambiguous",
            )
            cases[-1].mkdir()
            for root in cases:
                with self.subTest(root=root.name):
                    before = snapshot_tree(root)
                    output = io.StringIO()
                    with redirect_stdout(output):
                        code = main(["--root", str(root), "detach", "--apply"])
                    self.assertEqual(code, 2)
                    self.assertEqual(before, snapshot_tree(root))
                    self.assertFalse((root / ".mylittleharness/detach/disabled.json").exists())
                    self.assertIn("detach-refused", output.getvalue())

    def test_detach_apply_refuses_marker_path_conflict_without_partial_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            (root / ".mylittleharness").write_text("not a directory", encoding="utf-8")
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "detach", "--apply"])
            rendered = output.getvalue()
            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("detach-marker-refused", rendered)
            self.assertIn("non-directory segment", rendered)

    def test_detach_apply_refuses_invalid_existing_marker_without_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            marker_path = root / ".mylittleharness/detach/disabled.json"
            marker_path.parent.mkdir(parents=True)
            marker_path.write_text('{"schema_version": 999}\n', encoding="utf-8")
            before = marker_path.read_text(encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "detach", "--apply"])
            rendered = output.getvalue()
            self.assertEqual(code, 2)
            self.assertEqual(before, marker_path.read_text(encoding="utf-8"))
            self.assertIn("detach-marker-refused", rendered)

    def test_detach_dry_run_reports_refusal_posture_for_non_live_roots_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cases = (
                make_fallback_root(base / "fallback"),
                make_generated_output_root(base / "generated"),
                base / "ambiguous",
            )
            cases[-1].mkdir()
            for root in cases:
                with self.subTest(root=root.name):
                    before = snapshot_tree(root)
                    output = io.StringIO()
                    with redirect_stdout(output):
                        code = main(["--root", str(root), "detach", "--dry-run"])
                    rendered = output.getvalue()
                    self.assertEqual(code, 0)
                    self.assertEqual(before, snapshot_tree(root))
                    self.assertIn("detach-refused", rendered)

    def test_detach_rejects_missing_apply_combined_and_unknown_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            cases = (
                ["detach"],
                ["detach", "--dry-run", "--apply"],
                ["detach", "--unknown"],
                ["disable"],
            )
            for command in cases:
                with self.subTest(command=command):
                    output = io.StringIO()
                    with redirect_stderr(output), self.assertRaises(SystemExit) as raised:
                        main(["--root", str(root), *command])
                    self.assertEqual(raised.exception.code, 2)

    def test_tasks_inspect_product_fixture_task_groups_and_no_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "tasks", "--inspect"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertFalse((root / ".mylittleharness").exists())
            self.assertIn("MyLittleHarness tasks --inspect", rendered)
            for heading in ("Summary", "Operator Tasks", "Compatibility", "Boundary", "Future Power-Ups"):
                self.assertIn(heading, rendered)
            for code_name in (
                "tasks-summary",
                "tasks-orient",
                "tasks-verify",
                "tasks-search-inspect",
                "tasks-evidence-closeout",
                "tasks-generated-projection",
                "tasks-bootstrap-readiness",
                "tasks-attach-repair",
                "tasks-package-smoke",
                "tasks-read-only",
                "tasks-no-authority",
            ):
                self.assertIn(code_name, rendered)

    def test_tasks_inspect_live_root_reports_posture_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "tasks", "--inspect"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertFalse((root / ".mylittleharness").exists())
            self.assertIn("root kind: live_operating_root", rendered)
            self.assertIn("tasks --inspect is terminal-only and read-only", rendered)
            self.assertIn("preflight --template git-pre-commit", rendered)
            self.assertIn("bootstrap --inspect", rendered)
            self.assertIn("bootstrap --package-smoke", rendered)

    def test_tasks_requires_explicit_inspect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            output = io.StringIO()
            with redirect_stderr(output), self.assertRaises(SystemExit) as raised:
                main(["--root", str(root), "tasks"])
            self.assertEqual(raised.exception.code, 2)

    def test_tasks_rejects_unknown_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            output = io.StringIO()
            with redirect_stderr(output), self.assertRaises(SystemExit) as raised:
                main(["--root", str(root), "tasks", "--apply"])
            self.assertEqual(raised.exception.code, 2)

    def test_top_level_help_foregrounds_primary_commands_and_keeps_compatibility(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        rendered = output.getvalue()
        self.assertIn("Primary commands: init, check, repair,", rendered)
        self.assertIn("detach.", rendered)
        self.assertIn("init", rendered)
        self.assertIn("check", rendered)
        self.assertIn("repair", rendered)
        self.assertIn("detach", rendered)
        self.assertIn("Attach MyLittleHarness", rendered)
        self.assertIn("Run read-only status", rendered)
        self.assertIn("Preview harness detach", rendered)
        self.assertIn("Compatibility and advanced diagnostics", rendered)
        self.assertIn("{init,check,repair,detach,...}", rendered)
        self.assertNotIn("tasks", rendered)
        self.assertNotIn("bootstrap", rendered)
        self.assertNotIn("adapter", rendered)
        self.assertNotIn("semantic", rendered)
        self.assertNotIn("intelligence", rendered)
        self.assertNotIn("projection", rendered)
        self.assertNotIn("snapshot", rendered)
        self.assertNotIn("writeback", rendered)
        self.assertNotIn("incubate", rendered)
        self.assertNotIn("plan", rendered)
        self.assertNotIn("memory-hygiene", rendered)
        self.assertNotIn("preflight", rendered)
        self.assertNotIn("attach", rendered)
        self.assertNotIn("Inspect operator task groups", rendered)
        self.assertNotIn("Inspect bootstrap", rendered)

    def test_hidden_advanced_commands_keep_command_specific_help(self) -> None:
        cases = (
            (["tasks", "--help"], "Advanced compatibility diagnostic: inspect operator task groups"),
            (["bootstrap", "--help"], "Advanced compatibility diagnostic: inspect bootstrap"),
            (["preflight", "--help"], "Advanced diagnostic: run optional preflight warnings"),
            (["semantic", "--help"], "Advanced diagnostic: inspect or evaluate semantic retrieval"),
            (["intelligence", "--help"], "Advanced diagnostic: report read-only repo intelligence"),
            (["projection", "--help"], "Advanced diagnostic: build, inspect, delete"),
            (["snapshot", "--help"], "Advanced diagnostic: inspect repair snapshots"),
            (["writeback", "--help"], "Advanced mutating command: apply explicit closeout/state writeback"),
            (["incubate", "--help"], "Advanced mutating command: create or append explicit future-idea incubation"),
            (["plan", "--help"], "Advanced mutating command: create or replace a deterministic active"),
            (["memory-hygiene", "--help"], "Advanced mutating command: apply explicit research/incubation lifecycle"),
            (["adapter", "--help"], "Advanced diagnostic: inspect or serve optional adapter"),
            (["attach", "--help"], "Compatibility command: preview or apply workflow scaffold attachment"),
        )
        for command, expected in cases:
            with self.subTest(command=command):
                output = io.StringIO()
                with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
                    main(command)
                self.assertEqual(raised.exception.code, 0)
                self.assertIn(expected, output.getvalue())

    def test_check_help_documents_deep_and_focus_modes(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["check", "--help"])
        self.assertEqual(raised.exception.code, 0)
        rendered = output.getvalue()
        self.assertIn("--deep", rendered)
        self.assertIn("--focus", rendered)
        self.assertIn("validation,links,context,hygiene", rendered)

    def test_representative_existing_commands_still_parse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            cases = (
                (["init", "--dry-run"], 0),
                (["check"], 0),
                (["detach", "--dry-run"], 0),
                (["status"], 0),
                (["validate"], 0),
                (["context-budget"], 0),
                (["bootstrap", "--inspect"], 0),
                (["semantic", "--inspect"], 0),
                (["semantic", "--evaluate"], 0),
                (["attach", "--dry-run"], 0),
                (["repair", "--dry-run"], 0),
                (["incubate", "--dry-run", "--topic", "Future CLI rail", "--note", "Capture explicit future ideas."], 0),
                (["plan", "--dry-run", "--title", "Generated Plan", "--objective", "Create a deterministic active plan."], 0),
            )
            for command, expected_code in cases:
                with self.subTest(command=command):
                    output = io.StringIO()
                    with redirect_stdout(output):
                        code = main(["--root", str(root), *command])
                    self.assertEqual(code, expected_code)

    def test_bootstrap_inspect_product_fixture_readiness_and_no_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_package_source_root(Path(tmp))
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "bootstrap", "--inspect"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertFalse((root / ".mylittleharness").exists())
            self.assertFalse((root / "dist").exists())
            self.assertIn("MyLittleHarness bootstrap --inspect", rendered)
            self.assertIn("status: warn", rendered)
            for heading in (
                "Summary",
                "Package Smoke",
                "Bootstrap Apply",
                "Publishing",
                "Workstation Adoption",
                "Boundary",
            ):
                self.assertIn(heading, rendered)
            for code_name in (
                "bootstrap-summary",
                "bootstrap-python",
                "bootstrap-package-smoke",
                "bootstrap-package-metadata",
                "bootstrap-apply-rejected",
                "bootstrap-apply-gate",
                "bootstrap-publishing-out-of-scope",
                "bootstrap-workstation-readiness",
                "bootstrap-path-discovery",
                "bootstrap-workstation-out-of-scope",
                "bootstrap-read-only",
                "bootstrap-no-authority",
            ):
                self.assertIn(code_name, rendered)
            self.assertIn("name=mylittleharness; version=1.0.0", rendered)
            self.assertIn("console script declaration: mylittleharness = mylittleharness.cli:main", rendered)
            self.assertIn("fate=ship now as no-write readiness evidence only", rendered)
            self.assertIn("fate=rejected as standalone product surface; bootstrap apply is not implemented", rendered)
            self.assertIn("later scoped contract with its own command ownership", rendered)
            self.assertIn("exact target root, exact write set, dry-run shape, refusal cases, validation gate", rendered)
            self.assertIn("starts no background runtime", rendered)

    def test_bootstrap_inspect_live_root_readiness_and_no_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "bootstrap", "--inspect"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertFalse((root / ".mylittleharness").exists())
            self.assertFalse((root / ".git" / "hooks").exists())
            self.assertFalse((root / ".github" / "workflows").exists())
            self.assertIn("root kind: live_operating_root", rendered)
            self.assertIn("bootstrap --inspect is terminal-only and read-only", rendered)
            self.assertIn("bootstrap-package-metadata-skipped", rendered)
            self.assertIn("bootstrap-path-discovery", rendered)
            self.assertIn("PATH changes, shell profiles, user config, global tools", rendered)
            self.assertIn("standalone bootstrap apply is rejected", rendered)

    def test_bootstrap_package_smoke_product_fixture_passes_without_product_root_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_package_source_root(Path(tmp))
            before = snapshot_tree(root)
            calls: list[list[str]] = []

            def fake_run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
                calls.append(command)
                if command[1:3] == ["-m", "pip"]:
                    return subprocess.CompletedProcess(command, 0, stdout="installed\n", stderr="")
                if "-c" in command:
                    return subprocess.CompletedProcess(command, 0, stdout="1.0.0\n", stderr="")
                return subprocess.CompletedProcess(command, 0, stdout="usage: mylittleharness\nMyLittleHarness repo safety utility\ninit\n", stderr="")

            output = io.StringIO()
            with patch("mylittleharness.bootstrap._create_venv"), patch("mylittleharness.bootstrap._run_command", side_effect=fake_run):
                with redirect_stdout(output):
                    code = main(["--root", str(root), "bootstrap", "--package-smoke"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertEqual(len(calls), 3)
            self.assertFalse((root / ".mylittleharness").exists())
            self.assertFalse((root / "build").exists())
            self.assertFalse((root / "dist").exists())
            self.assertFalse(any(root.glob("*.egg-info")))
            self.assertIn("MyLittleHarness bootstrap --package-smoke", rendered)
            for heading in ("Summary", "Package Root", "Temp Boundary", "Install", "Import", "Console Script", "Boundary"):
                self.assertIn(heading, rendered)
            self.assertIn("package-smoke-install-ok", rendered)
            self.assertIn("package-smoke-import-ok", rendered)
            self.assertIn("package-smoke-console-ok", rendered)
            self.assertIn("temporary workspace outside product root: True", rendered)
            self.assertIn("does not publish packages, change PATH, write user config, install hooks, add CI/GitHub workflows", rendered)

    def test_bootstrap_package_smoke_refuses_non_product_root_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "bootstrap", "--package-smoke"])
            rendered = output.getvalue()
            self.assertEqual(code, 1)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("package-smoke-root-refused", rendered)
            self.assertIn("package-smoke-not-started", rendered)

    def test_bootstrap_package_smoke_reports_install_failure_without_later_checks_or_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_package_source_root(Path(tmp))
            before = snapshot_tree(root)

            def fake_run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess(command, 3, stdout="", stderr="missing build backend")

            output = io.StringIO()
            with patch("mylittleharness.bootstrap._create_venv"), patch("mylittleharness.bootstrap._run_command", side_effect=fake_run):
                with redirect_stdout(output):
                    code = main(["--root", str(root), "bootstrap", "--package-smoke"])
            rendered = output.getvalue()
            self.assertEqual(code, 1)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("package-smoke-install-failed", rendered)
            self.assertIn("package-smoke-import-skipped", rendered)
            self.assertIn("package-smoke-console-skipped", rendered)
            self.assertIn("package smoke failed before creating product-root package artifacts or workstation changes", rendered)

    def test_bootstrap_requires_explicit_inspect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            output = io.StringIO()
            with redirect_stderr(output), self.assertRaises(SystemExit) as raised:
                main(["--root", str(root), "bootstrap"])
            self.assertEqual(raised.exception.code, 2)

    def test_bootstrap_rejects_unknown_and_apply_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            for flag in ("--unknown", "--apply", "--dry-run"):
                with self.subTest(flag=flag):
                    output = io.StringIO()
                    with redirect_stderr(output), self.assertRaises(SystemExit) as raised:
                        main(["--root", str(root), "bootstrap", flag])
                    self.assertEqual(raised.exception.code, 2)

    def test_intelligence_report_sections_and_no_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=True, mirrors=True)
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "intelligence"])
            after = snapshot_tree(root)
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, after)
            self.assertIn("MyLittleHarness intelligence", rendered)
            for heading in ("Summary", "Boundary", "Drift", "Repo Map", "Backlinks", "Search", "Fan-In", "Projection"):
                self.assertIn(heading, rendered)
            self.assertIn("intelligence-summary", rendered)
            self.assertIn("intelligence-boundary", rendered)
            self.assertIn("repo-map-surface", rendered)
            self.assertIn("search-ready", rendered)
            self.assertIn("projection-rebuild", rendered)
            self.assertIn("storage boundary=none", rendered)

    def test_evidence_product_fixture_no_active_plan_no_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "evidence"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertFalse((root / ".mylittleharness").exists())
            self.assertIn("MyLittleHarness evidence", rendered)
            self.assertIn("evidence-boundary", rendered)
            self.assertIn("evidence-root-kind", rendered)
            self.assertIn("product source checkout contains compatibility fixtures only", rendered)
            self.assertIn("no active plan is required by current state", rendered)
            self.assertNotIn("[WARN]", rendered)

    def test_evidence_quality_cues_can_use_state_writeback_without_active_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            state = root / "project/project-state.md"
            state.write_text(
                state.read_text(encoding="utf-8")
                + "\n## MLH Closeout Writeback\n\n"
                "<!-- BEGIN mylittleharness-closeout-writeback v1 -->\n"
                "- docs_decision: not-needed\n"
                "- state_writeback: complete\n"
                "- verification: validation passed\n"
                "- commit_decision: skipped because no commit requested\n"
                "<!-- END mylittleharness-closeout-writeback v1 -->\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "evidence"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("candidate: docs_decision candidate: - docs_decision: not-needed", rendered)
            self.assertIn("report-only closeout readiness cue: concrete closeout field evidence is present", rendered)
            self.assertNotIn("AttributeError", rendered)

    def test_evidence_active_plan_reports_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=True, mirrors=True)
            (root / "project/implementation-plan.md").write_text(
                "# Plan\n\n"
                "## Source Set\n\n"
                "- Source set includes `README.md` and `project/project-state.md`.\n\n"
                "## Verification Blocks\n\n"
                "- Plan anchor after contract review.\n"
                "- Integration anchor after implementation verification.\n"
                "- Closeout anchor before archive or carry-forward.\n\n"
                "## Closeout Summary\n\n"
                "- docs_decision: updated\n"
                "- state_writeback: complete\n"
                "- verification: unit suite passed\n"
                "- commit_decision: skipped because policy is manual\n"
                "- residual risk: evidence manifest remains deferred\n"
                "- explicit skip rationale: non-git repo\n"
                "- carry-forward: later-extension evidence manifest remains deferred\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "evidence"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("evidence-source-set", rendered)
            self.assertIn("evidence-anchor-candidate", rendered)
            self.assertIn("evidence-closeout-candidate", rendered)
            self.assertIn("evidence-residual-risk", rendered)
            self.assertIn("evidence-skip-rationale", rendered)
            self.assertIn("evidence-carry-forward", rendered)
            self.assertIn("evidence-operator-required", rendered)
            self.assertNotIn("[WARN]", rendered)

    def test_evidence_treats_validation_section_as_verification_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=True, mirrors=True)
            (root / "project/implementation-plan.md").write_text(
                "# Plan\n\n"
                "## Source Set\n\n"
                "- Source set includes `README.md`.\n\n"
                "## Verification Blocks\n\n"
                "- Plan anchor after contract review.\n"
                "- Integration anchor after implementation verification.\n"
                "- Closeout anchor before archive.\n\n"
                "## Closeout Summary\n\n"
                "- docs_decision: updated\n"
                "- state_writeback: complete\n"
                "- commit_decision: skipped because policy is manual\n"
                "- residual risk: none known\n"
                "- explicit skip rationale: non-git repo\n"
                "- carry-forward: no later-extension needed\n\n"
                "## Validation\n\n"
                "- Unit suite passed.\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "evidence"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("verification candidate: ## Validation", rendered)
            self.assertNotIn("missing: closeout field candidate not found: verification", rendered)

    def test_future_manifest_language_does_not_satisfy_concrete_closeout_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=True, mirrors=True)
            (root / "project/implementation-plan.md").write_text(
                "# Plan\n\n"
                "## Source Set\n\n"
                "- Source set includes `README.md`.\n\n"
                "## Verification Blocks\n\n"
                "- Plan anchor after contract review.\n"
                "- Integration anchor after implementation verification.\n"
                "- Closeout anchor before archive.\n\n"
                "## Future Evidence Manifest\n\n"
                "- If implemented, the manifest shape names source pointers, command observations, verification anchors, skip rationale, residual risk, carry-forward destination, rebuild behavior, and non-authority wording.\n"
                "- A later scoped plan may define docs decision, state writeback, validation evidence, and commit decision fields.\n"
                "- Future generated evidence stores remain deferred.\n",
                encoding="utf-8",
            )

            evidence_output = io.StringIO()
            with redirect_stdout(evidence_output):
                self.assertEqual(main(["--root", str(root), "evidence"]), 0)
            evidence_rendered = evidence_output.getvalue()
            self.assertIn("missing: concrete closeout field candidate not found: docs_decision", evidence_rendered)
            self.assertIn("missing: concrete closeout field candidate not found: state_writeback", evidence_rendered)
            self.assertIn("missing: concrete closeout field candidate not found: verification", evidence_rendered)
            self.assertIn("missing: concrete closeout field candidate not found: commit_decision", evidence_rendered)
            self.assertNotIn("verification candidate: - If implemented", evidence_rendered)
            self.assertNotIn("verification candidate: - A later scoped plan", evidence_rendered)

            closeout_output = io.StringIO()
            with redirect_stdout(closeout_output):
                self.assertEqual(main(["--root", str(root), "closeout"]), 0)
            closeout_rendered = closeout_output.getvalue()
            self.assertIn("missing: concrete closeout field candidate not found: verification", closeout_rendered)
            self.assertNotIn("closeout-verification: candidate", closeout_rendered)

    def test_evidence_reports_stable_identity_and_plural_anchors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=True, mirrors=True)
            (root / "project/implementation-plan.md").write_text(
                "# Plan\n\n"
                "## Source Set\n\n"
                "- Source set includes `README.md`.\n\n"
                "## Verification Blocks\n\n"
                "- Plan anchors after contract review.\n"
                "- Integration anchors after implementation verification.\n"
                "- Closeout anchors before archive.\n\n"
                "## Closeout Summary\n\n"
                "- docs_decision: updated\n"
                "- state_writeback: complete\n"
                "- verification: unit suite passed\n"
                "- commit_decision: skipped because policy is manual\n"
                "- residual risk: none known\n"
                "- explicit skip rationale: non-git repo\n"
                "- carry-forward: no later-extension needed\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "evidence"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("evidence-identity", rendered)
            self.assertIn("identity=", rendered)
            self.assertIn("kind=integration-anchor", rendered)
            self.assertNotIn("missing: integration anchor candidate", rendered)
            self.assertNotIn("[WARN]", rendered)

    def test_evidence_active_plan_with_gaps_reports_warnings_without_failing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=True, mirrors=True)
            (root / "project/implementation-plan.md").write_text("# Plan\n\nNarrative only.\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "evidence"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("[WARN] evidence-source-set", rendered)
            self.assertIn("[WARN] evidence-anchor-missing", rendered)
            self.assertIn("[WARN] evidence-closeout-missing", rendered)
            self.assertIn("[WARN] evidence-residual-risk", rendered)
            self.assertIn("closeout assembly prompts", rendered)

    def test_evidence_live_prose_state_reports_operator_required_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "evidence"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("root kind: live_operating_root", rendered)
            self.assertIn("evidence-active-plan", rendered)
            self.assertIn("evidence-operator-required", rendered)
            self.assertIn("evidence does not run Git or VCS commands", rendered)

    def test_evidence_rejects_unknown_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            output = io.StringIO()
            with redirect_stderr(output), self.assertRaises(SystemExit) as raised:
                main(["--root", str(root), "evidence", "--focus"])
            self.assertEqual(raised.exception.code, 2)

    def test_closeout_product_fixture_no_active_plan_no_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "closeout"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertFalse((root / ".mylittleharness").exists())
            self.assertIn("MyLittleHarness closeout", rendered)
            for heading in ("Summary", "Worktree", "Closeout Fields", "Git Evidence", "Evidence Cues", "Quality Gates", "Projection", "Boundary"):
                self.assertIn(heading, rendered)
            self.assertIn("closeout-boundary", rendered)
            self.assertIn("closeout-worktree-start-state", rendered)
            self.assertIn("closeout-task-scope", rendered)
            self.assertIn("closeout-commit-input", rendered)
            self.assertIn("product source checkout contains compatibility fixtures only", rendered)
            self.assertIn("closeout-git-evidence-fallback", rendered)
            self.assertNotIn("suggestion: MLH-Worktree-Start-State", rendered)

    def test_closeout_active_plan_reports_assembly_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=True, mirrors=True)
            (root / "project/implementation-plan.md").write_text(
                "# Plan\n\n"
                "## Source Set\n\n"
                "- Source set includes `README.md`.\n\n"
                "## Closeout Summary\n\n"
                "- docs_decision: updated\n"
                "- state_writeback: complete\n"
                "- verification: unit suite passed\n"
                "- commit_decision: skipped because policy is manual\n"
                "- residual risk: none known\n"
                "- explicit skip rationale: non-git repo\n"
                "- carry-forward: no later-extension needed\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "closeout"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("closeout-active-plan", rendered)
            self.assertIn("closeout-docs-decision", rendered)
            self.assertIn("closeout-state-writeback", rendered)
            self.assertIn("closeout-verification", rendered)
            self.assertIn("closeout-commit-decision", rendered)
            self.assertIn("closeout-residual-risk", rendered)
            self.assertIn("closeout-skip-rationale", rendered)
            self.assertIn("closeout-carry-forward", rendered)
            self.assertNotIn("missing: closeout field candidate", rendered)

    def test_closeout_clean_git_worktree_suggests_ordered_trailers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=True, mirrors=True)
            (root / "project/implementation-plan.md").write_text(
                "# Plan\n\n"
                "## Closeout Summary\n\n"
                "- worktree_start_state: Git worktree clean\n"
                "- task_scope: task_only\n"
                "- docs_decision: updated\n"
                "- state_writeback: complete\n"
                "- verification: unit suite passed\n"
                "- commit_decision: skipped because policy is manual\n"
                "- residual risk: none known\n"
                "- carry-forward: detach/disable design\n",
                encoding="utf-8",
            )
            posture = VcsPosture(root=root, git_available=True, is_worktree=True, state="clean", top_level=str(root))
            output = io.StringIO()
            with patch("mylittleharness.closeout.probe_vcs", return_value=posture), redirect_stdout(output):
                code = main(["--root", str(root), "closeout"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("Git Evidence", rendered)
            ordered = (
                "suggestion: MLH-Worktree-Start-State: Git worktree clean",
                "suggestion: MLH-Task-Scope: task_only",
                "suggestion: MLH-Docs-Decision: updated",
                "suggestion: MLH-State-Writeback: complete",
                "suggestion: MLH-Verification: unit suite passed",
                "suggestion: MLH-Commit-Decision: skipped because policy is manual",
                "suggestion: MLH-Residual-Risk: none known",
                "suggestion: MLH-Carry-Forward: detach/disable design",
            )
            positions = [rendered.index(item) for item in ordered]
            self.assertEqual(positions, sorted(positions))
            self.assertIn("closeout-git-evidence-boundary", rendered)
            self.assertIn("clean worktree; suggestions remain advisory", rendered)

    def test_closeout_dirty_git_worktree_keeps_trailers_advisory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=True, mirrors=True)
            (root / "project/implementation-plan.md").write_text(
                "# Plan\n\n"
                "## Closeout Summary\n\n"
                "- worktree_start_state: Git worktree dirty\n"
                "- task_scope: mixed\n"
                "- docs_decision: updated\n"
                "- state_writeback: complete\n"
                "- verification: smoke passed\n"
                "- commit_decision: skipped because dirty-start mixed scope\n",
                encoding="utf-8",
            )
            posture = VcsPosture(
                root=root,
                git_available=True,
                is_worktree=True,
                state="dirty",
                top_level=str(root),
                changed_count=1,
                changed_samples=(VcsChangedPath("M", "README.md"),),
            )
            output = io.StringIO()
            with patch("mylittleharness.closeout.probe_vcs", return_value=posture), redirect_stdout(output):
                code = main(["--root", str(root), "closeout"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("candidate: Git worktree dirty", rendered)
            self.assertIn("closeout-task-scope", rendered)
            self.assertIn("dirty worktree; suggestions remain advisory and require explicit task_scope", rendered)
            self.assertIn("suggestion: MLH-Task-Scope: mixed", rendered)

    def test_closeout_non_git_reports_markdown_fallback_without_trailers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=True, mirrors=True)
            (root / "project/implementation-plan.md").write_text(
                "# Plan\n\n"
                "## Closeout Summary\n\n"
                "- worktree_start_state: non-git root\n"
                "- task_scope: task_only\n"
                "- docs_decision: not-needed\n"
                "- state_writeback: complete\n"
                "- verification: validate passed\n"
                "- commit_decision: skipped because non-git repo\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "closeout"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("closeout-git-evidence-fallback", rendered)
            self.assertIn("Markdown closeout fields or an operator summary fallback", rendered)
            self.assertNotIn("suggestion: MLH-Worktree-Start-State", rendered)

    def test_closeout_git_evidence_reports_missing_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=True, mirrors=True)
            (root / "project/implementation-plan.md").write_text(
                "# Plan\n\n"
                "## Closeout Summary\n\n"
                "- worktree_start_state: Git worktree clean\n"
                "- docs_decision: updated\n"
                "- verification: unit suite passed\n",
                encoding="utf-8",
            )
            posture = VcsPosture(root=root, git_available=True, is_worktree=True, state="clean", top_level=str(root))
            output = io.StringIO()
            with patch("mylittleharness.closeout.probe_vcs", return_value=posture), redirect_stdout(output):
                code = main(["--root", str(root), "closeout"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("closeout-git-evidence-missing", rendered)
            self.assertIn("task_scope", rendered)
            self.assertIn("state_writeback", rendered)
            self.assertIn("commit_decision", rendered)
            self.assertNotIn("suggestion: MLH-Docs-Decision", rendered)

    def test_closeout_git_evidence_ignores_prospective_future_wording(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=True, mirrors=True)
            (root / "project/implementation-plan.md").write_text(
                "# Plan\n\n"
                "A future plan may record task_scope, docs_decision, state_writeback, verification, and commit_decision.\n\n"
                "## Closeout Summary\n\n"
                "- worktree_start_state: Git worktree clean\n",
                encoding="utf-8",
            )
            posture = VcsPosture(root=root, git_available=True, is_worktree=True, state="clean", top_level=str(root))
            output = io.StringIO()
            with patch("mylittleharness.closeout.probe_vcs", return_value=posture), redirect_stdout(output):
                code = main(["--root", str(root), "closeout"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("closeout-git-evidence-missing", rendered)
            self.assertIn("docs_decision", rendered)
            self.assertIn("verification", rendered)
            self.assertNotIn("suggestion: MLH-Verification", rendered)

    def test_closeout_prefers_concrete_fields_over_broad_future_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=True, mirrors=True)
            (root / "project/implementation-plan.md").write_text(
                "# Plan\n\n"
                "Closeout helpers better assemble `state_writeback`, `verification`, and `commit_decision` without approving lifecycle decisions.\n\n"
                "## Closeout Summary\n\n"
                "- docs_decision: updated\n"
                "- state_writeback: complete\n"
                "- verification: unit suite passed\n"
                "- commit_decision: skipped because policy is manual\n"
                "- residual risk: none known\n"
                "- explicit skip rationale: non-git repo\n"
                "- carry-forward: no later-extension needed\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "closeout"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("Quality Gates", rendered)
            self.assertIn("closeout-quality-gate", rendered)
            self.assertIn("state_writeback candidate: - state_writeback: complete", rendered)
            self.assertIn("identity=", rendered)
            self.assertNotIn("state_writeback context", rendered)
            self.assertNotIn("Closeout helpers better assemble", rendered)

    def test_closeout_rejects_unknown_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            output = io.StringIO()
            with redirect_stderr(output), self.assertRaises(SystemExit) as raised:
                main(["--root", str(root), "closeout", "--apply"])
            self.assertEqual(raised.exception.code, 2)

    def test_writeback_apply_synchronizes_docs_decision_split_brain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_active_live_root(Path(tmp), phase_status="complete")
            (root / "project/implementation-plan.md").write_text(
                "---\n"
                'title: "Plan"\n'
                'docs_decision: "uncertain"\n'
                'state_writeback: "pending"\n'
                'verification: "pending"\n'
                'commit_decision: "pending"\n'
                'residual_risk: "unknown"\n'
                'carry_forward: "unknown"\n'
                "---\n"
                "# Plan\n\n"
                "## Closeout Summary\n\n"
                "- docs_decision: uncertain\n"
                "- state_writeback: pending\n"
                "- verification: pending\n"
                "- commit_decision: pending\n"
                "- residual risk: unknown\n"
                "- carry-forward: unknown\n",
                encoding="utf-8",
            )

            check_before = io.StringIO()
            with redirect_stdout(check_before):
                self.assertEqual(main(["--root", str(root), "check"]), 0)
            self.assertIn("active-plan-docs-decision-uncertain", check_before.getvalue())

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "writeback",
                        "--apply",
                        "--docs-decision",
                        "updated",
                        "--state-writeback",
                        "complete",
                        "--verification",
                        "unit suite passed",
                        "--commit-decision",
                        "skipped because policy is manual",
                        "--residual-risk",
                        "none known",
                        "--carry-forward",
                        "no follow-up",
                        "--phase-status",
                        "complete",
                    ]
                )
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("writeback-auto-archive-active-plan", rendered)
            self.assertIn("writeback-active-plan-archived", rendered)
            self.assertIn("writeback-state-updated", rendered)
            self.assertIn("writeback-active-plan-frontmatter-updated", rendered)
            self.assertIn("writeback-active-plan-body-updated", rendered)

            state_text = (root / "project/project-state.md").read_text(encoding="utf-8")
            self.assertIn("<!-- BEGIN mylittleharness-closeout-writeback v1 -->", state_text)
            self.assertIn("- docs_decision: updated", state_text)
            self.assertIn('phase_status: "complete"', state_text)
            self.assertIn('plan_status: "none"', state_text)
            self.assertIn('active_plan: ""', state_text)

            self.assertFalse((root / "project/implementation-plan.md").exists())
            archived_paths = list((root / "project/archive/plans").glob("*-plan.md"))
            self.assertEqual(1, len(archived_paths))
            archived_rel = archived_paths[0].relative_to(root).as_posix()
            self.assertIn(f'last_archived_plan: "{archived_rel}"', state_text)
            plan_text = archived_paths[0].read_text(encoding="utf-8")
            self.assertIn('docs_decision: "updated"', plan_text)
            self.assertIn('state_writeback: "complete"', plan_text)
            self.assertIn('verification: "unit suite passed"', plan_text)
            self.assertIn('commit_decision: "skipped because policy is manual"', plan_text)
            self.assertIn("- docs_decision: updated", plan_text)
            self.assertIn("- state_writeback: complete", plan_text)
            self.assertIn("- verification: unit suite passed", plan_text)
            self.assertIn("- commit_decision: skipped because policy is manual", plan_text)
            self.assertIn("- residual risk: none known", plan_text)
            self.assertIn("- carry-forward: no follow-up", plan_text)

            check_after = io.StringIO()
            with redirect_stdout(check_after):
                self.assertEqual(main(["--root", str(root), "check"]), 0)
            rendered_after = check_after.getvalue()
            self.assertIn("no active implementation plan is open", rendered_after)
            self.assertNotIn("active-plan-docs-decision-uncertain", rendered_after)
            self.assertNotIn("active-plan-writeback-drift", rendered_after)

    def test_writeback_phase_status_synchronizes_active_plan_status_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_active_live_root(Path(tmp), phase_status="complete")
            (root / "project/implementation-plan.md").write_text(
                "---\n"
                'title: "Plan"\n'
                'status: "active"\n'
                "---\n"
                "# Plan\n",
                encoding="utf-8",
            )

            check_before = io.StringIO()
            with redirect_stdout(check_before):
                self.assertEqual(main(["--root", str(root), "check"]), 0)
            self.assertIn("active-plan-lifecycle-drift", check_before.getvalue())

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "writeback", "--apply", "--phase-status", "complete"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("writeback-active-plan-frontmatter-updated", rendered)

            plan_text = (root / "project/implementation-plan.md").read_text(encoding="utf-8")
            self.assertIn('status: "complete"', plan_text)

            check_after = io.StringIO()
            with redirect_stdout(check_after):
                self.assertEqual(main(["--root", str(root), "check"]), 0)
            self.assertNotIn("active-plan-lifecycle-drift", check_after.getvalue())

    def test_writeback_phase_status_synchronizes_only_active_phase_body_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_active_live_root(Path(tmp), phase_status="in_progress")
            state = root / "project/project-state.md"
            state.write_text(
                state.read_text(encoding="utf-8").replace(
                    'active_phase: "Phase 4 - Validation And Closeout"',
                    'active_phase: "phase-2-verify"',
                ),
                encoding="utf-8",
            )
            plan_path = root / "project/implementation-plan.md"
            plan_path.write_text(
                "---\n"
                'title: "Plan"\n'
                'status: "active"\n'
                'active_phase: "phase-2-verify"\n'
                'phase_status: "in_progress"\n'
                "---\n"
                "# Plan\n\n"
                "## Phases\n\n"
                "### Phase 1: Setup\n\n"
                "- id: `phase-1-setup`\n"
                "- status: `pending`\n\n"
                "### Phase 2: Verify\n\n"
                "- id: `phase-2-verify`\n"
                "- status: `in_progress`\n\n"
                "### Phase 3: Followup\n\n"
                "- id: `phase-3-followup`\n"
                "- status: `pending`\n",
                encoding="utf-8",
            )

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "writeback", "--apply", "--phase-status", "complete"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("writeback-active-plan-phase-block-updated", rendered)
            self.assertNotIn("writeback-active-plan-archived", rendered)

            plan_text = plan_path.read_text(encoding="utf-8")
            self.assertIn("- id: `phase-1-setup`\n- status: `pending`", plan_text)
            self.assertIn("- id: `phase-2-verify`\n- status: `done`", plan_text)
            self.assertIn("- id: `phase-3-followup`\n- status: `pending`", plan_text)
            self.assertIn('status: "complete"', plan_text)
            self.assertIn('phase_status: "complete"', plan_text)

    def test_writeback_active_phase_transition_synchronizes_current_focus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_active_live_root(Path(tmp), phase_status="in_progress")
            state = root / "project/project-state.md"
            state.write_text(
                state.read_text(encoding="utf-8").replace(
                    'active_phase: "Phase 4 - Validation And Closeout"',
                    'active_phase: "phase-2-verify"',
                ),
                encoding="utf-8",
            )
            plan_path = root / "project/implementation-plan.md"
            plan_path.write_text(
                "---\n"
                'title: "Plan"\n'
                'status: "in_progress"\n'
                'active_phase: "phase-2-verify"\n'
                'phase_status: "in_progress"\n'
                "---\n"
                "# Plan\n\n"
                "## Phases\n\n"
                "### Phase 2: Verify\n\n"
                "- id: `phase-2-verify`\n"
                "- status: `done`\n\n"
                "### Phase 3: Followup\n\n"
                "- id: `phase-3-followup`\n"
                "- status: `pending`\n",
                encoding="utf-8",
            )

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "writeback",
                        "--apply",
                        "--active-phase",
                        "phase-3-followup",
                        "--phase-status",
                        "active",
                    ]
                )
            self.assertEqual(code, 0)
            rendered = output.getvalue()
            self.assertIn("writeback-active-plan-phase-block-updated", rendered)

            state_text = state.read_text(encoding="utf-8")
            self.assertIn('active_phase: "phase-3-followup"', state_text)
            self.assertIn('phase_status: "active"', state_text)
            self.assertIn("<!-- BEGIN mylittleharness-current-focus v1 -->", state_text)
            self.assertIn("Continue from active_phase `phase-3-followup` with phase_status `active`.", state_text)
            self.assertNotIn("Continue from active_phase `phase-2-verify` with phase_status `in_progress`.", state_text)

            plan_text = plan_path.read_text(encoding="utf-8")
            self.assertIn('active_phase: "phase-3-followup"', plan_text)
            self.assertIn('phase_status: "active"', plan_text)
            self.assertIn("- id: `phase-3-followup`\n- status: `active`", plan_text)

    def test_writeback_dry_run_reports_phase_block_sync_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_active_live_root(Path(tmp), phase_status="in_progress")
            state = root / "project/project-state.md"
            state.write_text(
                state.read_text(encoding="utf-8").replace(
                    'active_phase: "Phase 4 - Validation And Closeout"',
                    'active_phase: "phase-2-verify"',
                ),
                encoding="utf-8",
            )
            (root / "project/implementation-plan.md").write_text(
                "---\n"
                'title: "Plan"\n'
                'status: "active"\n'
                "---\n"
                "# Plan\n\n"
                "## Phases\n\n"
                "### Phase 1: Setup\n\n"
                "- id: `phase-1-setup`\n"
                "- status: `pending`\n\n"
                "### Phase 2: Verify\n\n"
                "- id: `phase-2-verify`\n"
                "- status: `in_progress`\n",
                encoding="utf-8",
            )
            before = snapshot_tree(root)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "writeback", "--dry-run", "--phase-status", "complete"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("writeback-active-plan-phase-block-plan", rendered)
            self.assertIn("would update active-plan phase block 'phase-2-verify' status body copy to 'done'", rendered)

    def test_writeback_dry_run_and_read_only_commands_do_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_active_live_root(Path(tmp), phase_status="complete")
            (root / "project/implementation-plan.md").write_text(
                "---\n"
                'title: "Plan"\n'
                'docs_decision: "uncertain"\n'
                "---\n"
                "# Plan\n\n"
                "- docs_decision: updated\n",
                encoding="utf-8",
            )
            before = snapshot_tree(root)
            commands = (
                ["check"],
                ["validate"],
                ["status"],
                ["intelligence"],
                ["evidence"],
                ["closeout"],
                ["audit-links"],
                ["doctor"],
                ["writeback", "--dry-run", "--docs-decision", "updated", "--phase-status", "complete"],
            )
            for command in commands:
                with self.subTest(command=command):
                    output = io.StringIO()
                    with redirect_stdout(output):
                        code = main(["--root", str(root), *command])
                    self.assertEqual(code, 0)
                    self.assertEqual(before, snapshot_tree(root))

    def test_incubate_dry_run_reports_create_posture_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "incubate",
                        "--dry-run",
                        "--topic",
                        "Future Ideas Rail",
                        "--note",
                        "Capture explicitly formulated future ideas.",
                    ]
                )
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertFalse((root / "project/plan-incubation/future-ideas-rail.md").exists())
            for expected in (
                "incubate-dry-run",
                "incubate-root-posture",
                "root kind: live_operating_root",
                "incubate-target-note",
                "project/plan-incubation/future-ideas-rail.md",
                "would create same-topic incubation note",
                "normalized topic: Future Ideas Rail; slug: future-ideas-rail",
                "incubate-validation-posture",
            ):
                self.assertIn(expected, rendered)

    def test_incubate_apply_creates_note_in_live_operating_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "incubate",
                        "--apply",
                        "--topic",
                        "Future Ideas Rail",
                        "--note",
                        "Capture explicitly formulated future ideas.",
                    ]
                )
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("created same-topic incubation note", rendered)
            note_path = root / "project/plan-incubation/future-ideas-rail.md"
            note_text = note_path.read_text(encoding="utf-8")
            self.assertIn('topic: "Future Ideas Rail"', note_text)
            self.assertIn('status: "incubating"', note_text)
            self.assertIn('source: "incubate cli"', note_text)
            self.assertIn("Non-authority note: incubation is temporary synthesis", note_text)
            self.assertIn("Capture explicitly formulated future ideas.", note_text)

    def test_incubate_apply_appends_same_topic_note_preserving_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            note_path = root / "project/plan-incubation/future-ideas-rail.md"
            note_path.parent.mkdir(parents=True)
            original = "# Existing Idea\n\nOriginal content stays.\n"
            note_path.write_text(original, encoding="utf-8")

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "incubate",
                        "--apply",
                        "--topic",
                        "Future Ideas Rail",
                        "--note",
                        "Second explicit entry.",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("appended to existing same-topic incubation note", output.getvalue())
            note_text = note_path.read_text(encoding="utf-8")
            self.assertTrue(note_text.startswith(original))
            self.assertIn("Second explicit entry.", note_text)

    def test_incubate_apply_refuses_product_fixture_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "incubate",
                        "--apply",
                        "--topic",
                        "Future Ideas Rail",
                        "--note",
                        "Do not write into product fixture.",
                    ]
                )
            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("product-source compatibility fixture", output.getvalue())

    def test_incubate_refuses_unsafe_topic_and_path_conflict_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            before = snapshot_tree(root)
            unsafe_output = io.StringIO()
            with redirect_stdout(unsafe_output):
                unsafe_code = main(
                    [
                        "--root",
                        str(root),
                        "incubate",
                        "--apply",
                        "--topic",
                        "../future.md",
                        "--note",
                        "No path topics.",
                    ]
                )
            self.assertEqual(unsafe_code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("topic looks like a path", unsafe_output.getvalue())

        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            note_path = root / "project/plan-incubation/future-ideas-rail.md"
            note_path.unlink() if note_path.exists() else None
            note_path.mkdir(parents=True)
            before = snapshot_tree(root)
            conflict_output = io.StringIO()
            with redirect_stdout(conflict_output):
                conflict_code = main(
                    [
                        "--root",
                        str(root),
                        "incubate",
                        "--apply",
                        "--topic",
                        "Future Ideas Rail",
                        "--note",
                        "No directory overwrite.",
                    ]
                )
            self.assertEqual(conflict_code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("target note path exists but is not a regular file", conflict_output.getvalue())

    def test_incubate_apply_refuses_state_without_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "incubate",
                        "--apply",
                        "--topic",
                        "Future Ideas Rail",
                        "--note",
                        "State frontmatter is required.",
                    ]
                )
            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("project-state.md frontmatter is required", output.getvalue())

    def test_plan_dry_run_reports_lifecycle_posture_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "plan",
                        "--dry-run",
                        "--title",
                        "Plan Synthesis Rail",
                        "--objective",
                        "Create deterministic implementation plans.",
                    ]
                )
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertFalse((root / "project/implementation-plan.md").exists())
            for expected in (
                "plan-dry-run",
                "plan-root-posture",
                "root kind: live_operating_root",
                "would write active plan: project/implementation-plan.md",
                "would update project-state lifecycle frontmatter",
                "plan-boundary",
                "docs_decision='uncertain'",
            ):
                self.assertIn(expected, rendered)

    def test_plan_apply_creates_active_plan_in_live_operating_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "plan",
                        "--apply",
                        "--title",
                        "Plan Synthesis Rail",
                        "--objective",
                        "Create deterministic implementation plans.",
                        "--task",
                        "Use explicit task input only.",
                    ]
                )
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("plan-written", rendered)
            self.assertIn("created active plan", rendered)

            plan_text = (root / "project/implementation-plan.md").read_text(encoding="utf-8")
            self.assertIn('title: "Plan Synthesis Rail"', plan_text)
            self.assertIn('docs_decision: "uncertain"', plan_text)
            self.assertIn("Use explicit task input only.", plan_text)
            self.assertIn("## Refusal Conditions", plan_text)

            state_text = (root / "project/project-state.md").read_text(encoding="utf-8")
            self.assertIn('operating_mode: "plan"', state_text)
            self.assertIn('plan_status: "active"', state_text)
            self.assertIn('active_plan: "project/implementation-plan.md"', state_text)
            self.assertIn('active_phase: "phase-1-implementation"', state_text)
            self.assertIn('phase_status: "pending"', state_text)
            self.assertIn("<!-- BEGIN mylittleharness-current-focus v1 -->", state_text)
            self.assertIn("Current focus: active implementation plan is open at `project/implementation-plan.md`.", state_text)
            self.assertIn("Continue from active_phase `phase-1-implementation` with phase_status `pending`.", state_text)

            check_output = io.StringIO()
            with redirect_stdout(check_output):
                check_code = main(["--root", str(root), "check"])
            self.assertEqual(check_code, 0)
            self.assertIn("active plan present: project/implementation-plan.md", check_output.getvalue())
            self.assertNotIn("[ERROR]", check_output.getvalue())

    def test_plan_apply_refuses_product_fixture_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "plan",
                        "--apply",
                        "--title",
                        "Fixture Plan",
                        "--objective",
                        "Do not write into product fixtures.",
                    ]
                )
            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("product-source compatibility fixture", output.getvalue())

    def test_plan_apply_refuses_existing_active_plan_without_update_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_active_live_root(Path(tmp))
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "plan",
                        "--apply",
                        "--title",
                        "Replacement Plan",
                        "--objective",
                        "Replace the active scaffold only when requested.",
                    ]
                )
            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("pass --update-active", output.getvalue())

    def test_plan_apply_update_active_replaces_generated_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_active_live_root(Path(tmp))
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "plan",
                        "--apply",
                        "--update-active",
                        "--title",
                        "Updated Active Plan",
                        "--objective",
                        "Refresh the deterministic scaffold.",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("updated existing active plan", output.getvalue())
            plan_text = (root / "project/implementation-plan.md").read_text(encoding="utf-8")
            self.assertIn("# Updated Active Plan", plan_text)
            self.assertIn("Refresh the deterministic scaffold.", plan_text)
            state_text = (root / "project/project-state.md").read_text(encoding="utf-8")
            self.assertIn('active_phase: "phase-1-implementation"', state_text)
            self.assertIn('phase_status: "pending"', state_text)
            self.assertIn("Continue from active_phase `phase-1-implementation` with phase_status `pending`.", state_text)

    def test_plan_apply_refuses_dangerous_task_input_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "plan",
                        "--apply",
                        "--title",
                        "Unsafe Plan",
                        "--objective",
                        "Run git reset --hard before implementation.",
                    ]
                )
            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("destructive VCS recovery", output.getvalue())

    def test_writeback_archive_active_plan_dry_run_reports_plan_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_active_live_root(Path(tmp), phase_status="complete")
            (root / "project/implementation-plan.md").write_text(
                "---\n"
                'title: "Lifecycle Close"\n'
                "---\n"
                "# Lifecycle Close\n",
                encoding="utf-8",
            )
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "writeback",
                        "--dry-run",
                        "--archive-active-plan",
                        "--docs-decision",
                        "updated",
                    ]
                )
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("writeback-archive-active-plan", rendered)
            self.assertIn("active plan: project/implementation-plan.md", rendered)
            self.assertIn("writeback-archive-target", rendered)
            self.assertIn("project/archive/plans/", rendered)
            self.assertIn("lifecycle-close.md", rendered)
            self.assertIn("would update project-state lifecycle frontmatter: plan_status, active_plan, last_archived_plan", rendered)
            self.assertIn("writeback-validation-posture", rendered)

    def test_writeback_archive_active_plan_dry_run_reports_auto_compaction_posture_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_active_live_root(Path(tmp), phase_status="complete")
            (root / "project/project-state.md").write_text(large_active_state_text(), encoding="utf-8")
            (root / "project/implementation-plan.md").write_text(
                "---\n"
                'title: "Lifecycle Close"\n'
                "---\n"
                "# Lifecycle Close\n",
                encoding="utf-8",
            )
            before = snapshot_tree(root)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "writeback",
                        "--dry-run",
                        "--archive-active-plan",
                        "--docs-decision",
                        "updated",
                    ]
                )
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("state-auto-compaction-posture", rendered)
            self.assertIn("auto-compaction would run", rendered)
            self.assertIn("target archive path: project/archive/reference/project-state-history-", rendered)
            self.assertIn("sections that would stay:", rendered)
            self.assertIn("Current Focus, Repository Role Map, Notes", rendered)
            self.assertIn("Ad Hoc Update - 2026-04-30 - Automatic Operating Memory Compaction", rendered)
            self.assertIn("MLH Closeout Writeback", rendered)
            self.assertIn("sections that would be archived:", rendered)
            self.assertIn("Ad Hoc Update - 2026-04-01 - Old Work 1", rendered)
            self.assertIn("state-auto-compaction-validation-posture", rendered)

    def test_writeback_dry_run_reports_auto_compaction_for_closeout_only_writeback_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            (root / "project/project-state.md").write_text(large_inactive_state_text(), encoding="utf-8")
            before = snapshot_tree(root)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "writeback",
                        "--dry-run",
                        "--docs-decision",
                        "updated",
                        "--state-writeback",
                        "recorded closeout facts",
                    ]
                )
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("state-auto-compaction-posture", rendered)
            self.assertIn("auto-compaction would run", rendered)
            self.assertIn("target archive path: project/archive/reference/project-state-history-", rendered)

    def test_writeback_apply_compacts_large_state_after_closeout_only_writeback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            state_path = root / "project/project-state.md"
            state_path.write_text(large_inactive_state_text(), encoding="utf-8")

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "writeback",
                        "--apply",
                        "--docs-decision",
                        "updated",
                        "--state-writeback",
                        "recorded closeout facts and compacted operating memory",
                    ]
                )
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("writeback-state-updated", rendered)
            self.assertIn("auto-compaction ran", rendered)

            state_text = state_path.read_text(encoding="utf-8")
            self.assertLess(len(state_text.splitlines()), 250)
            self.assertIn("- docs_decision: updated", state_text)
            self.assertIn("- state_writeback: recorded closeout facts and compacted operating memory", state_text)
            self.assertIn("## Archived State History", state_text)
            self.assertNotIn("## Ad Hoc Update - 2026-04-01 - Old Work 1", state_text)
            history_paths = list((root / "project/archive/reference").glob(f"project-state-history-{date.today().isoformat()}*.md"))
            self.assertEqual(1, len(history_paths))
            self.assertIn("## Ad Hoc Update - 2026-04-01 - Old Work 1", history_paths[0].read_text(encoding="utf-8"))

    def test_writeback_archive_active_plan_apply_moves_plan_and_closes_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_active_live_root(Path(tmp), phase_status="complete")
            plan_path = root / "project/implementation-plan.md"
            plan_path.write_text(
                "---\n"
                'title: "Lifecycle Close"\n'
                "---\n"
                "# Lifecycle Close\n\n"
                "## Closeout Summary\n\n"
                "- docs_decision: uncertain\n",
                encoding="utf-8",
            )

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "writeback",
                        "--apply",
                        "--archive-active-plan",
                        "--docs-decision",
                        "updated",
                        "--state-writeback",
                        "archived active plan",
                    ]
                )
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("writeback-active-plan-archived", rendered)
            self.assertFalse(plan_path.exists())

            archived_paths = list((root / "project/archive/plans").glob("*-lifecycle-close.md"))
            self.assertEqual(1, len(archived_paths))
            self.assertIn("# Lifecycle Close", archived_paths[0].read_text(encoding="utf-8"))

            state_text = (root / "project/project-state.md").read_text(encoding="utf-8")
            archived_rel = archived_paths[0].relative_to(root).as_posix()
            self.assertIn('plan_status: "none"', state_text)
            self.assertIn('active_plan: ""', state_text)
            self.assertIn(f'last_archived_plan: "{archived_rel}"', state_text)
            self.assertIn("Current focus: no active implementation plan is open.", state_text)
            self.assertIn(f"Last archived plan: `{archived_rel}`.", state_text)
            self.assertIn("- docs_decision: updated", state_text)
            self.assertIn("- state_writeback: archived active plan", state_text)

            check_output = io.StringIO()
            with redirect_stdout(check_output):
                self.assertEqual(main(["--root", str(root), "check"]), 0)
            check_rendered = check_output.getvalue()
            self.assertIn("no active implementation plan is open", check_rendered)
            self.assertNotIn("stale-plan-file", check_rendered)

            before_rerun = snapshot_tree(root)
            rerun_output = io.StringIO()
            with redirect_stdout(rerun_output):
                rerun_code = main(["--root", str(root), "writeback", "--apply", "--archive-active-plan"])
            self.assertEqual(rerun_code, 2)
            self.assertEqual(before_rerun, snapshot_tree(root))
            self.assertIn("archive-active-plan requires plan_status active", rerun_output.getvalue())

    def test_writeback_archive_active_plan_apply_compacts_large_state_after_lifecycle_close(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_active_live_root(Path(tmp), phase_status="complete")
            plan_path = root / "project/implementation-plan.md"
            plan_path.write_text(
                "---\n"
                'title: "Lifecycle Close"\n'
                "---\n"
                "# Lifecycle Close\n",
                encoding="utf-8",
            )
            (root / "project/project-state.md").write_text(large_active_state_text(), encoding="utf-8")
            reference_dir = root / "project/archive/reference"
            reference_dir.mkdir(parents=True, exist_ok=True)
            base_history = reference_dir / f"project-state-history-{date.today().isoformat()}.md"
            base_history.write_text("# Existing history\n", encoding="utf-8")

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "writeback",
                        "--apply",
                        "--archive-active-plan",
                        "--docs-decision",
                        "updated",
                        "--state-writeback",
                        "archived active plan and compacted operating memory",
                    ]
                )
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("writeback-active-plan-archived", rendered)
            self.assertIn("auto-compaction ran", rendered)

            state_text = (root / "project/project-state.md").read_text(encoding="utf-8")
            self.assertLess(len(state_text.splitlines()), 250)
            self.assertIn('plan_status: "none"', state_text)
            self.assertIn('active_plan: ""', state_text)
            self.assertIn("## Current Focus", state_text)
            self.assertIn("## Repository Role Map", state_text)
            self.assertIn("## Notes", state_text)
            self.assertIn("## Ad Hoc Update - 2026-04-30 - Automatic Operating Memory Compaction", state_text)
            self.assertIn("## MLH Closeout Writeback", state_text)
            self.assertIn("- docs_decision: updated", state_text)
            self.assertIn("- state_writeback: archived active plan and compacted operating memory", state_text)
            self.assertIn("## Archived State History", state_text)
            self.assertIn("project/archive/reference/project-state-history-", state_text)
            self.assertNotIn("## Ad Hoc Update - 2026-04-01 - Old Work 1", state_text)

            history_paths = sorted(reference_dir.glob(f"project-state-history-{date.today().isoformat()}*.md"))
            self.assertEqual(2, len(history_paths))
            self.assertEqual("# Existing history\n", base_history.read_text(encoding="utf-8"))
            new_history = [path for path in history_paths if path != base_history][0]
            history_text = new_history.read_text(encoding="utf-8")
            self.assertIn("- Source state path: `project/project-state.md`", history_text)
            self.assertIn(f"- Archive path: `{new_history.relative_to(root).as_posix()}`", history_text)
            self.assertIn(f"- Reason: exceeded 250 line default", history_text)
            self.assertIn("archived history is reference", history_text)
            self.assertIn("## Ad Hoc Update - 2026-04-01 - Old Work 1", history_text)

            check_output = io.StringIO()
            with redirect_stdout(check_output):
                self.assertEqual(main(["--root", str(root), "check"]), 0)
            self.assertNotIn("rule-context-surface-large", check_output.getvalue())

    def test_writeback_archive_active_plan_apply_reports_compaction_refusal_without_undoing_lifecycle_close(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_active_live_root(Path(tmp), phase_status="complete")
            plan_path = root / "project/implementation-plan.md"
            plan_path.write_text(
                "---\n"
                'title: "Lifecycle Close"\n'
                "---\n"
                "# Lifecycle Close\n",
                encoding="utf-8",
            )
            (root / "project/project-state.md").write_text(large_active_state_text(loose_title_text=True), encoding="utf-8")

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "writeback", "--apply", "--archive-active-plan"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("writeback-active-plan-archived", rendered)
            self.assertIn("auto-compaction refused", rendered)
            self.assertIn("loose title text before the first section", rendered)
            self.assertFalse(plan_path.exists())
            self.assertFalse(list((root / "project/archive/reference").glob("project-state-history-*.md")))

            state_text = (root / "project/project-state.md").read_text(encoding="utf-8")
            self.assertIn('plan_status: "none"', state_text)
            self.assertIn('active_plan: ""', state_text)
            self.assertIn("Loose title paragraph makes section boundaries unclear.", state_text)
            self.assertIn("## Ad Hoc Update - 2026-04-01 - Old Work 1", state_text)

    def test_writeback_archive_active_plan_refuses_conflict_and_product_fixture_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_active_live_root(Path(tmp), phase_status="complete")
            (root / "project/implementation-plan.md").write_text(
                "---\n"
                'title: "Lifecycle Close"\n'
                "---\n"
                "# Lifecycle Close\n",
                encoding="utf-8",
            )
            archive_dir = root / "project/archive/plans"
            archive_dir.mkdir(parents=True, exist_ok=True)
            (archive_dir / f"{date.today().isoformat()}-lifecycle-close.md").write_text(
                "# Existing\n",
                encoding="utf-8",
            )
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "writeback", "--apply", "--archive-active-plan"])
            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("archive target already exists", output.getvalue())

        with tempfile.TemporaryDirectory() as tmp:
            product_root = make_root(Path(tmp), active=True, mirrors=False)
            before_product = snapshot_tree(product_root)
            product_output = io.StringIO()
            with redirect_stdout(product_output):
                product_code = main(["--root", str(product_root), "writeback", "--apply", "--archive-active-plan"])
            self.assertEqual(product_code, 2)
            self.assertEqual(before_product, snapshot_tree(product_root))
            self.assertIn("product-source compatibility fixture", product_output.getvalue())

        with tempfile.TemporaryDirectory() as tmp:
            root = make_active_live_root(Path(tmp), phase_status="in_progress")
            (root / "project/implementation-plan.md").write_text(
                "---\n"
                'title: "Lifecycle Close"\n'
                "---\n"
                "# Lifecycle Close\n",
                encoding="utf-8",
            )
            archive_dir = root / "project/archive/plans"
            archive_dir.mkdir(parents=True, exist_ok=True)
            (archive_dir / f"{date.today().isoformat()}-lifecycle-close.md").write_text(
                "# Existing\n",
                encoding="utf-8",
            )
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "writeback",
                        "--apply",
                        "--docs-decision",
                        "updated",
                        "--state-writeback",
                        "recorded completed lifecycle facts",
                        "--verification",
                        "targeted suite passed",
                        "--commit-decision",
                        "manual policy",
                        "--phase-status",
                        "complete",
                    ]
                )
            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("archive target already exists", output.getvalue())

    def test_closeout_git_trailers_prefer_state_writeback_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_active_live_root(Path(tmp), phase_status="complete")
            state = root / "project/project-state.md"
            state.write_text(
                state.read_text(encoding="utf-8")
                + "\n## MLH Closeout Writeback\n\n"
                "<!-- BEGIN mylittleharness-closeout-writeback v1 -->\n"
                "- worktree_start_state: Git worktree clean\n"
                "- task_scope: task_only\n"
                "- docs_decision: updated\n"
                "- state_writeback: complete\n"
                "- verification: current validation passed\n"
                "- commit_decision: skipped because policy is manual\n"
                "- residual_risk: none known\n"
                "- carry_forward: no follow-up\n"
                "<!-- END mylittleharness-closeout-writeback v1 -->\n",
                encoding="utf-8",
            )
            (root / "project/implementation-plan.md").write_text(
                "# Plan\n\n"
                "## Closeout Summary\n\n"
                "- worktree_start_state: stale dirty state\n"
                "- task_scope: stale mixed\n"
                "- docs_decision: uncertain\n"
                "- state_writeback: stale\n"
                "- verification: stale validation\n"
                "- commit_decision: stale commit decision\n"
                "- residual risk: stale risk\n"
                "- carry-forward: stale follow-up\n",
                encoding="utf-8",
            )
            posture = VcsPosture(root=root, git_available=True, is_worktree=True, state="clean", top_level=str(root))
            output = io.StringIO()
            with patch("mylittleharness.closeout.probe_vcs", return_value=posture), redirect_stdout(output):
                code = main(["--root", str(root), "closeout"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("suggestion: MLH-Docs-Decision: updated", rendered)
            self.assertIn("suggestion: MLH-Verification: current validation passed", rendered)
            self.assertIn("suggestion: MLH-Commit-Decision: skipped because policy is manual", rendered)
            self.assertIn("suggestion: MLH-Carry-Forward: no follow-up", rendered)
            self.assertNotIn("suggestion: MLH-Docs-Decision: uncertain", rendered)

            check_output = io.StringIO()
            with redirect_stdout(check_output):
                self.assertEqual(main(["--root", str(root), "check"]), 0)
            self.assertIn("active-plan-writeback-drift", check_output.getvalue())

    def test_closeout_git_trailers_can_use_state_writeback_without_active_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            state = root / "project/project-state.md"
            state.write_text(
                state.read_text(encoding="utf-8")
                + "\n## MLH Closeout Writeback\n\n"
                "<!-- BEGIN mylittleharness-closeout-writeback v1 -->\n"
                "- worktree_start_state: Git worktree clean\n"
                "- task_scope: task_only\n"
                "- docs_decision: not-needed\n"
                "- state_writeback: complete\n"
                "- verification: validation passed\n"
                "- commit_decision: skipped because no commit requested\n"
                "- residual_risk: none known\n"
                "- carry_forward: no follow-up\n"
                "<!-- END mylittleharness-closeout-writeback v1 -->\n",
                encoding="utf-8",
            )
            posture = VcsPosture(root=root, git_available=True, is_worktree=True, state="clean", top_level=str(root))
            output = io.StringIO()
            with patch("mylittleharness.closeout.probe_vcs", return_value=posture), redirect_stdout(output):
                code = main(["--root", str(root), "closeout"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("suggestion: MLH-Docs-Decision: not-needed", rendered)
            self.assertIn("suggestion: MLH-State-Writeback: complete", rendered)
            self.assertIn("suggestion: MLH-Verification: validation passed", rendered)
            self.assertNotIn("closeout-git-evidence-skipped", rendered)

    def test_writeback_apply_refuses_product_fixture_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=True, mirrors=False)
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "writeback", "--apply", "--docs-decision", "updated"])
            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("writeback-refused", output.getvalue())

    def test_preflight_product_fixture_no_active_plan_no_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "preflight"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertFalse((root / ".mylittleharness").exists())
            self.assertIn("MyLittleHarness preflight", rendered)
            for heading in ("Summary", "Checks", "Closeout Readiness", "Boundary"):
                self.assertIn(heading, rendered)
            self.assertIn("preflight-boundary", rendered)
            self.assertIn("preflight-validate", rendered)
            self.assertIn("preflight-audit-links", rendered)
            self.assertIn("preflight-context-budget", rendered)
            self.assertIn("preflight-product-hygiene", rendered)
            self.assertIn("preflight-closeout-source", rendered)
            self.assertIn("preflight-no-hooks", rendered)
            self.assertIn("does not install hooks, add CI/GitHub workflows", rendered)

    def test_preflight_live_root_reports_closeout_warnings_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "preflight"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertFalse((root / ".mylittleharness").exists())
            self.assertIn("root kind: live_operating_root", rendered)
            self.assertIn("[WARN] preflight-closeout", rendered)
            self.assertIn("preflight-closeout-cue", rendered)
            self.assertIn("closeout-quality-gate", rendered)
            self.assertIn("source files, observed verification, and operator decisions remain authority", rendered)

    def test_preflight_git_pre_commit_template_product_fixture_no_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "preflight", "--template", "git-pre-commit"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertFalse((root / ".git" / "hooks").exists())
            self.assertFalse((root / ".github" / "workflows").exists())
            self.assertFalse((root / ".mylittleharness").exists())
            self.assertTrue(rendered.startswith("#!/bin/sh\n"))
            self.assertIn(f"MLH_ROOT={shlex.quote(str(root.resolve()))}", rendered)
            self.assertIn('mylittleharness --root "$MLH_ROOT" preflight', rendered)
            self.assertIn("warning: mylittleharness is not available", rendered)
            self.assertIn("warning: mylittleharness preflight did not complete", rendered)
            self.assertIn("never blocks commits", rendered)
            self.assertTrue(rendered.rstrip().endswith("exit 0"))
            self.assertNotIn("MyLittleHarness preflight", rendered)

    def test_preflight_git_pre_commit_template_live_root_no_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "preflight", "--template", "git-pre-commit"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertFalse((root / ".git" / "hooks").exists())
            self.assertFalse((root / ".github" / "workflows").exists())
            self.assertFalse((root / ".mylittleharness").exists())
            self.assertIn(f"MLH_ROOT={shlex.quote(str(root.resolve()))}", rendered)
            self.assertIn('mylittleharness --root "$MLH_ROOT" preflight', rendered)
            self.assertTrue(rendered.rstrip().endswith("exit 0"))

    def test_preflight_git_pre_commit_template_quotes_root_with_spaces(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mlh root with spaces ") as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "preflight", "--template", "git-pre-commit"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn(f"MLH_ROOT={shlex.quote(str(root.resolve()))}", rendered)

    def test_preflight_reports_validation_errors_without_repair_or_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            (root / "project/specs/workflow" / EXPECTED_SPEC_NAMES[0]).unlink()
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "preflight"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("status: error", rendered)
            self.assertIn("[ERROR] preflight-validate", rendered)
            self.assertIn("missing-stable-spec", rendered)
            self.assertIn("preflight-no-mutation", rendered)

    def test_preflight_rejects_unknown_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            output = io.StringIO()
            with redirect_stderr(output), self.assertRaises(SystemExit) as raised:
                main(["--root", str(root), "preflight", "--strict"])
            self.assertEqual(raised.exception.code, 2)

    def test_semantic_inspect_product_fixture_no_active_plan_no_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            before = snapshot_tree_bytes(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "semantic", "--inspect"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree_bytes(root))
            self.assertFalse((root / ".mylittleharness").exists())
            self.assertIn("MyLittleHarness semantic --inspect", rendered)
            for heading in ("Summary", "Search Base", "Runtime", "Evaluation", "Boundary"):
                self.assertIn(heading, rendered)
            self.assertIn("semantic-runtime-deferred", rendered)
            self.assertIn("semantic-artifacts-missing", rendered)
            self.assertIn("semantic-index-missing", rendered)
            self.assertIn("semantic-evaluation-source-verification", rendered)
            self.assertIn("semantic-no-runtime", rendered)

    def test_semantic_inspect_live_root_reports_readiness_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            before = snapshot_tree_bytes(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "semantic", "--inspect"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree_bytes(root))
            self.assertFalse((root / ".mylittleharness").exists())
            self.assertIn("root kind: live_operating_root", rendered)
            self.assertIn("semantic-readiness", rendered)
            self.assertIn("semantic-exact-path-base", rendered)
            self.assertIn("repo files, in-memory projection", rendered)

    def test_semantic_reports_stale_generated_projection_as_degraded_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "projection", "--build", "--target", "all"]), 0)
            (root / "README.md").write_text("# Readme\nChanged semantic readiness source.\n", encoding="utf-8")
            before = snapshot_tree_bytes(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "semantic", "--inspect"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree_bytes(root))
            self.assertIn("semantic-artifacts-degraded", rendered)
            self.assertIn("semantic-index-degraded", rendered)
            self.assertFalse((root / ".mylittleharness/generated/semantic").exists())

    def test_semantic_reports_current_full_text_index_when_current(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "projection", "--build", "--target", "all"]), 0)
            before = snapshot_tree_bytes(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "semantic", "--inspect"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree_bytes(root))
            self.assertIn("semantic-artifacts-current", rendered)
            self.assertIn("semantic-index-current", rendered)
            self.assertNotIn("semantic-generated-output-present", rendered)

    def test_semantic_evaluate_missing_index_degrades_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            before = snapshot_tree_bytes(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "semantic", "--evaluate"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree_bytes(root))
            self.assertFalse((root / ".mylittleharness/generated/semantic").exists())
            self.assertIn("MyLittleHarness semantic --evaluate", rendered)
            for heading in ("Summary", "Corpus", "Evaluation Queries", "False-Positive Review", "Source Verification", "Degraded Modes", "Boundary"):
                self.assertIn(heading, rendered)
            self.assertIn("semantic-evaluation-index-degraded", rendered)
            self.assertIn("semantic-evaluation-query-degraded", rendered)
            self.assertIn("exact/path/full-text recovery stays source-backed", rendered)

    def test_semantic_evaluate_degrades_for_stale_corrupt_or_unavailable_index(self) -> None:
        scenarios = ("stale", "corrupt", "unavailable")
        for scenario in scenarios:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as tmp:
                root = make_root(Path(tmp), active=False, mirrors=False)
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(main(["--root", str(root), "projection", "--build", "--target", "index"]), 0)
                if scenario == "stale":
                    (root / "README.md").write_text("# Readme\nChanged semantic evaluation source.\n", encoding="utf-8")
                    context = nullcontext()
                elif scenario == "corrupt":
                    (root / ".mylittleharness/generated/projection/search-index.sqlite3").write_text("not sqlite\n", encoding="utf-8")
                    context = nullcontext()
                else:
                    context = patch("mylittleharness.projection_index._fts5_is_available", return_value=False)

                before = snapshot_tree_bytes(root)
                output = io.StringIO()
                with context, redirect_stdout(output):
                    code = main(["--root", str(root), "semantic", "--evaluate"])
                rendered = output.getvalue()
                self.assertEqual(code, 0)
                self.assertEqual(before, snapshot_tree_bytes(root))
                self.assertIn("semantic-evaluation-index-degraded", rendered)
                self.assertIn("semantic-evaluation-query-degraded", rendered)
                self.assertIn("semantic-evaluation-degraded-input", rendered)
                self.assertFalse((root / ".mylittleharness/generated/semantic").exists())

    def test_semantic_evaluate_current_index_reports_source_verified_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            (root / "README.md").write_text(
                "# Readme\n"
                "semantic retrieval depends on source verification and stale index review.\n"
                "offline degraded mode keeps repair closeout archive commit terms advisory.\n",
                encoding="utf-8",
            )
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(root), "projection", "--build", "--target", "index"]), 0)
            before = snapshot_tree_bytes(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "semantic", "--evaluate"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree_bytes(root))
            self.assertIn("semantic-evaluation-index-current", rendered)
            self.assertIn("semantic-evaluation-query-current", rendered)
            self.assertIn("semantic-evaluation-query-match", rendered)
            self.assertIn("semantic-evaluation-source-match", rendered)
            self.assertIn("semantic-evaluation-negative-no-match", rendered)
            self.assertIn("semantic-evaluation-lifecycle-risk", rendered)
            self.assertIn("verification=source-verified", rendered)
            self.assertIn("source_hash=", rendered)
            self.assertFalse((root / ".mylittleharness/generated/semantic").exists())

    def test_semantic_rejects_unknown_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            output = io.StringIO()
            with redirect_stderr(output), self.assertRaises(SystemExit) as raised:
                main(["--root", str(root), "semantic", "--search", "workflow"])
            self.assertEqual(raised.exception.code, 2)

    def test_semantic_requires_inspect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            output = io.StringIO()
            with redirect_stderr(output), self.assertRaises(SystemExit) as raised:
                main(["--root", str(root), "semantic"])
            self.assertEqual(raised.exception.code, 2)

    def test_semantic_rejects_combined_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            output = io.StringIO()
            with redirect_stderr(output), self.assertRaises(SystemExit) as raised:
                main(["--root", str(root), "semantic", "--inspect", "--evaluate"])
            self.assertEqual(raised.exception.code, 2)

    def test_adapter_product_fixture_no_active_plan_no_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "adapter", "--inspect", "--target", "mcp-read-projection"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertFalse((root / ".mylittleharness").exists())
            self.assertIn("MyLittleHarness adapter --inspect --target mcp-read-projection", rendered)
            for heading in ("Adapter", "Projection", "Sources", "Generated Inputs", "Boundary"):
                self.assertIn(heading, rendered)
            self.assertIn("adapter-target", rendered)
            self.assertIn("adapter-source-record", rendered)
            self.assertIn("adapter-generated-artifacts", rendered)
            self.assertIn("adapter-no-authority", rendered)
            self.assertIn("no MCP SDK", rendered)
            self.assertNotIn("[ERROR]", rendered)

    def test_adapter_live_root_reports_missing_optional_surfaces_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "adapter", "--inspect", "--target", "mcp-read-projection"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertFalse((root / ".mylittleharness").exists())
            self.assertIn("root kind: live_operating_root", rendered)
            self.assertIn("README.md; role=orientation; required=False; posture=missing", rendered)
            self.assertIn("adapter-generated-index", rendered)
            self.assertIn("generic CLI and repo files remain usable when MCP tooling is absent", rendered)

    def test_adapter_reports_stale_generated_projection_as_optional_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            with redirect_stdout(io.StringIO()):
                build_code = main(["--root", str(root), "projection", "--build", "--target", "artifacts"])
            self.assertEqual(build_code, 0)
            (root / "README.md").write_text("# Changed Readme\nSee `.agents/docmap.yaml`.\n", encoding="utf-8")
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "adapter", "--inspect", "--target", "mcp-read-projection"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("[WARN] adapter-generated-artifacts", rendered)
            self.assertIn("projection-artifact-stale", rendered)
            self.assertIn("adapter fails open to repo files and in-memory projection", rendered)

    def test_adapter_rejects_unknown_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            output = io.StringIO()
            with redirect_stderr(output), self.assertRaises(SystemExit) as raised:
                main(["--root", str(root), "adapter", "--inspect", "--target", "browser"])
            self.assertEqual(raised.exception.code, 2)

    def test_adapter_serve_requires_stdio_transport(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            output = io.StringIO()
            with redirect_stderr(output), self.assertRaises(SystemExit) as raised:
                main(["--root", str(root), "adapter", "--serve", "--target", "mcp-read-projection"])
            self.assertEqual(raised.exception.code, 2)
            self.assertIn("adapter --serve requires --transport stdio", output.getvalue())

    def test_adapter_inspect_rejects_transport_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            output = io.StringIO()
            with redirect_stderr(output), self.assertRaises(SystemExit) as raised:
                main(["--root", str(root), "adapter", "--inspect", "--target", "mcp-read-projection", "--transport", "stdio"])
            self.assertEqual(raised.exception.code, 2)
            self.assertIn("--transport is only valid with adapter --serve", output.getvalue())

    def test_adapter_serve_mcp_stdio_lifecycle_tool_call_and_no_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            before = snapshot_tree(root)
            messages = [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "test-client", "version": "1.0.0"},
                    },
                },
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "ping"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "mylittleharness.read_projection", "arguments": {}},
                },
            ]
            input_stream = io.StringIO("\n".join(json.dumps(message) for message in messages) + "\n")
            output = io.StringIO()
            with patch("sys.stdin", input_stream), redirect_stdout(output):
                code = main(["--root", str(root), "adapter", "--serve", "--target", "mcp-read-projection", "--transport", "stdio"])

            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertFalse((root / ".mylittleharness").exists())
            responses = jsonrpc_lines(output.getvalue())
            self.assertEqual([1, 2, 3, 4], [response["id"] for response in responses])
            self.assertEqual("2025-11-25", responses[0]["result"]["protocolVersion"])
            self.assertEqual({"tools": {"listChanged": False}}, responses[0]["result"]["capabilities"])
            self.assertEqual({}, responses[1]["result"])
            tool = responses[2]["result"]["tools"][0]
            self.assertEqual("mylittleharness.read_projection", tool["name"])
            self.assertEqual({"type": "object", "additionalProperties": False}, tool["inputSchema"])
            result = responses[3]["result"]
            self.assertFalse(result["isError"])
            structured = result["structuredContent"]
            self.assertEqual("mcp-read-projection", structured["adapter"]["id"])
            self.assertEqual(str(root), structured["root"]["path"])
            self.assertEqual("ok", structured["status"])
            section_names = [section["name"] for section in structured["sections"]]
            self.assertEqual(["Adapter", "Projection", "Sources", "Generated Inputs", "Boundary"], section_names)
            finding_codes = [finding["code"] for section in structured["sections"] for finding in section["findings"]]
            self.assertIn("adapter-source-record", finding_codes)
            self.assertIn("adapter-generated-index", finding_codes)
            self.assertIn("adapter-no-authority", finding_codes)
            self.assertFalse(structured["boundary"]["sourceBodiesIncluded"])
            self.assertIn('"adapter"', result["content"][0]["text"])
            self.assertNotIn("See `.agents/docmap.yaml`.", output.getvalue())

    def test_adapter_serve_mcp_stdio_protocol_and_tool_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            messages = [
                "{not json}",
                json.dumps({"jsonrpc": "2.0", "id": 10, "method": "unknown/method"}),
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 11,
                        "method": "tools/call",
                        "params": {"name": "unknown.tool", "arguments": {}},
                    }
                ),
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 12,
                        "method": "tools/call",
                        "params": {"name": "mylittleharness.read_projection", "arguments": {"extra": True}},
                    }
                ),
            ]
            input_stream = io.StringIO("\n".join(messages) + "\n")
            output = io.StringIO()
            with patch("sys.stdin", input_stream), redirect_stdout(output):
                code = main(["--root", str(root), "adapter", "--serve", "--target", "mcp-read-projection", "--transport", "stdio"])

            self.assertEqual(code, 0)
            responses = jsonrpc_lines(output.getvalue())
            self.assertEqual(-32700, responses[0]["error"]["code"])
            self.assertEqual(-32601, responses[1]["error"]["code"])
            self.assertEqual(-32602, responses[2]["error"]["code"])
            self.assertTrue(responses[3]["result"]["isError"])
            self.assertIn("accepts only an empty object", responses[3]["result"]["content"][0]["text"])

    def test_adapter_serve_mcp_stdio_eof_exits_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            output = io.StringIO()
            with patch("sys.stdin", io.StringIO("")), redirect_stdout(output):
                code = main(["--root", str(root), "adapter", "--serve", "--target", "mcp-read-projection", "--transport", "stdio"])
            self.assertEqual(code, 0)
            self.assertEqual("", output.getvalue())

    def test_intelligence_exact_search_is_case_sensitive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            exact_output = io.StringIO()
            with redirect_stdout(exact_output):
                exact_code = main(["--root", str(root), "intelligence", "--search", "MyLittleHarness"])
            lower_output = io.StringIO()
            with redirect_stdout(lower_output):
                lower_code = main(["--root", str(root), "intelligence", "--search", "mylittleharness"])
            self.assertEqual(exact_code, 0)
            self.assertEqual(lower_code, 0)
            self.assertIn("search-match", exact_output.getvalue())
            self.assertIn("search-no-matches", lower_output.getvalue())

    def test_intelligence_path_search_reports_inventory_and_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "intelligence", "--path", ".agents/docmap.yaml"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("search-path-match", rendered)
            self.assertIn("search-path-reference", rendered)
            self.assertIn("fan-in-target", rendered)
            self.assertIn("inbound=2", rendered)

    def test_intelligence_unified_query_expands_to_exact_path_and_full_text_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "intelligence", "--focus", "search", "--query", ".agents/docmap.yaml"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertFalse((root / ".mylittleharness").exists())
            self.assertIn("intelligence-query-expansion", rendered)
            self.assertIn("omitted modes: exact text, path, full text", rendered)
            self.assertIn("search-match", rendered)
            self.assertIn("search-path-match", rendered)
            self.assertIn("search-path-reference", rendered)
            self.assertIn("projection-index-query-skipped", rendered)

    def test_intelligence_unified_query_preserves_explicit_mode_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            (root / "README.md").write_text("# Readme\nExplicitSearch lives here.\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--root",
                        str(root),
                        "intelligence",
                        "--focus",
                        "search",
                        "--query",
                        "QueryTerm",
                        "--search",
                        "ExplicitSearch",
                        "--path",
                        ".agents/docmap.yaml",
                        "--full-text",
                        "ExplicitFull",
                    ]
                )
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("intelligence-query-expansion", rendered)
            self.assertIn("omitted modes: none", rendered)
            self.assertIn("text match for 'ExplicitSearch'", rendered)
            self.assertIn("path match for '.agents/docmap.yaml'", rendered)
            self.assertIn("full-text search skipped for 'ExplicitFull'", rendered)
            self.assertNotIn("text match for 'QueryTerm'", rendered)

    def test_intelligence_reports_no_matches_for_missing_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "intelligence", "--search", "DefinitelyMissingNeedle"])
            self.assertEqual(code, 0)
            self.assertIn("search-no-matches", output.getvalue())

    def test_intelligence_focus_search_omits_full_sections_and_keeps_path_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "intelligence", "--focus", "search", "--path", ".agents/docmap.yaml"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("Summary", rendered)
            self.assertIn("Search", rendered)
            self.assertIn("search-path-match", rendered)
            self.assertIn("search-path-reference", rendered)
            self.assertIn("inventory sources discovered", rendered)
            self.assertNotIn("\nRepo Map\n", rendered)
            self.assertNotIn("repo-map-surface", rendered)
            self.assertNotIn("fan-in-target", rendered)
            self.assertNotIn(".codex/project-workflow.toml [manifest", rendered)

    def test_intelligence_focus_search_reports_no_matches_compactly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "intelligence", "--focus", "search", "--search", "DefinitelyMissingNeedle"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("search-no-matches", rendered)
            self.assertNotIn("repo-map-surface", rendered)
            self.assertNotIn("backlink-reference", rendered)

    def test_intelligence_focus_projection_reports_in_memory_projection_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=True, mirrors=True)
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "intelligence", "--focus", "projection"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("Summary", rendered)
            self.assertIn("Boundary", rendered)
            self.assertIn("Projection", rendered)
            self.assertIn("projection-rebuild", rendered)
            self.assertIn("projection-source-coverage", rendered)
            self.assertIn("projection-record-counts", rendered)
            self.assertIn("source hashes:", rendered)
            self.assertIn("inventory sources discovered", rendered)
            self.assertNotIn("\nRepo Map\n", rendered)
            self.assertNotIn("\nBacklinks\n", rendered)
            self.assertNotIn("\nSearch\n", rendered)
            self.assertNotIn("\nFan-In\n", rendered)

    def test_intelligence_focus_warnings_demotes_recovery_noise_only_inside_intelligence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            agents = root / "AGENTS.md"
            agents.write_text(
                agents.read_text(encoding="utf-8")
                + "Optional user global: `%USERPROFILE%\\\\.codex\\\\config.toml`.\n"
                + "Product source reference: `src/mylittleharness`.\n"
                + "Actionable missing reference: `project/missing.md`.\n",
                encoding="utf-8",
            )
            state = root / "project/project-state.md"
            state.write_text(
                state.read_text(encoding="utf-8") + "Verification mentioned `src/mylittleharness/__pycache__` as absent.\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "intelligence", "--focus", "warnings"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("Actionable Warnings", rendered)
            self.assertIn("[WARN] missing-link: project/missing.md", rendered)
            self.assertNotIn("%USERPROFILE%", rendered)
            self.assertNotIn("src/mylittleharness/__pycache__", rendered)
            self.assertNotIn("src/mylittleharness does not resolve", rendered)

    def test_intelligence_handles_operating_root_lazy_docmap_and_stale_wording(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            (root / "project/research/stale.md").write_text(
                f"{root.parent / 'legacy-root'} is the current source.\n",
                encoding="utf-8",
            )
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "intelligence", "--path", "project/implementation-plan.md"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("root kind: live_operating_root", rendered)
            self.assertIn("stale-fallback-root-reference", rendered)
            self.assertNotIn("[ERROR]", rendered)
            self.assertIn("search-path-match", rendered)

    def test_intelligence_warnings_include_rule_context_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            (root / "AGENTS.md").write_text("# AGENTS\n" + ("Instruction line.\n" * 501), encoding="utf-8")
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "intelligence", "--focus", "warnings"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("Actionable Warnings", rendered)
            self.assertIn("rule-context-surface-large", rendered)

    def test_validate_is_strict_but_status_is_advisory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=True, mirrors=True)
            (root / "project/specs/workflow" / EXPECTED_SPEC_NAMES[0]).unlink()
            validate_output = io.StringIO()
            with redirect_stdout(validate_output):
                validate_code = main(["--root", str(root), "validate"])
            status_output = io.StringIO()
            with redirect_stdout(status_output):
                status_code = main(["--root", str(root), "status"])
            self.assertEqual(validate_code, 1)
            self.assertEqual(status_code, 0)
            self.assertIn("missing expected workflow spec", validate_output.getvalue())

    def test_audit_links_reports_missing_path_but_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            (root / "README.md").write_text("See `project/missing.md`.\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "audit-links"])
            self.assertEqual(code, 0)
            self.assertIn("missing-link", output.getvalue())

    def test_audit_links_keeps_user_global_missing_reference_as_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            agents = root / "AGENTS.md"
            agents.write_text(
                agents.read_text(encoding="utf-8") + "Optional user global: `%USERPROFILE%\\\\.codex\\\\config.toml`.\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "audit-links"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("[WARN] missing-link", rendered)
            self.assertIn("%USERPROFILE%", rendered)

    def test_audit_links_treats_inactive_plan_as_lazy_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            (root / "README.md").write_text("See `project/implementation-plan.md` only when active.\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "audit-links"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("optional-link-missing", rendered)
            self.assertNotIn("[WARN] missing-link", rendered)

    def test_audit_links_treats_absolute_in_root_inactive_plan_as_lazy_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            plan_path = (root / "project/implementation-plan.md").as_posix()
            (root / "README.md").write_text(f"See `{plan_path}` only when active.\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "audit-links"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("optional-link-missing", rendered)
            self.assertNotIn("[WARN] missing-link", rendered)

    def test_audit_links_treats_source_research_as_fixture_optional(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            (root / "README.md").write_text("See `project/research/deeper-context.md` in the operating root.\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "audit-links"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("optional-link-missing", rendered)
            self.assertNotIn("[WARN] missing-link", rendered)

    def test_audit_links_treats_snapshot_copied_file_path_as_snapshot_internal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            (root / "README.md").write_text(
                "Snapshot copied bytes live at `files/.agents/docmap.yaml` and "
                "`files/project/project-state.md` inside a repair snapshot.\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "audit-links"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("optional-link-missing", rendered)
            self.assertIn("snapshot copied-file paths are relative to a repair snapshot directory", rendered)
            self.assertNotIn("[WARN] missing-link", rendered)

    def test_doctor_reports_product_hygiene_warnings_without_failing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            (root / "debug.log").write_text("debug\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "doctor"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("product-debris", rendered)
            self.assertIn("product-hygiene-summary", rendered)

    def test_missing_root_returns_usage_failure_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"
            output = io.StringIO()
            with redirect_stderr(output):
                code = main(["--root", str(missing), "status"])
            self.assertEqual(code, 2)
            self.assertIn("target root does not exist", output.getvalue())

    def test_missing_command_exits_with_argparse_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            output = io.StringIO()
            with redirect_stderr(output), self.assertRaises(SystemExit) as raised:
                main(["--root", str(root)])
            self.assertEqual(raised.exception.code, 2)

    def test_attach_dry_run_reports_product_fixture_noop_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "attach", "--dry-run"])
            after = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, after)
            self.assertIn("attach --dry-run", rendered)
            self.assertIn("product-source compatibility fixture", rendered)
            self.assertIn("no-op", rendered)

    def test_init_attach_dry_run_reports_fallback_generated_refusal_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            roots = (make_fallback_root(base / "fallback"), make_generated_output_root(base / "generated"))
            for root in roots:
                for command in ("init", "attach"):
                    with self.subTest(command=command, root=root.name):
                        before = snapshot_tree(root)
                        output = io.StringIO()
                        with redirect_stdout(output):
                            code = main(["--root", str(root), command, "--dry-run", "--project", "Demo"])
                        rendered = output.getvalue()
                        self.assertEqual(code, 0)
                        self.assertEqual(before, snapshot_tree(root))
                        self.assertIn("attach-refused", rendered)
                        self.assertIn("fallback/archive or generated-output evidence", rendered)

    def test_repair_dry_run_reports_proposal_without_restoring_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=True, mirrors=True)
            missing = root / "project/specs/workflow" / EXPECTED_SPEC_NAMES[0]
            missing.unlink()
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--dry-run"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertFalse(missing.exists())
            self.assertIn("repair --dry-run", rendered)
            self.assertIn("repair-proposal", rendered)
            self.assertIn("missing-stable-spec", rendered)

    def test_attach_requires_explicit_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            output = io.StringIO()
            with redirect_stderr(output), self.assertRaises(SystemExit) as raised:
                main(["--root", str(root), "attach"])
            self.assertEqual(raised.exception.code, 2)

    def test_attach_rejects_dry_run_and_apply_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            output = io.StringIO()
            with redirect_stderr(output), self.assertRaises(SystemExit) as raised:
                main(["--root", str(root), "attach", "--dry-run", "--apply"])
            self.assertEqual(raised.exception.code, 2)

    def test_attach_apply_refuses_product_fixture_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "attach", "--apply", "--project", "Demo"])
            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("attach-refused", output.getvalue())
            self.assertIn("product-source compatibility fixture", output.getvalue())

    def test_init_attach_apply_refuses_fallback_generated_roots_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            roots = (make_fallback_root(base / "fallback"), make_generated_output_root(base / "generated"))
            for root in roots:
                for command in ("init", "attach"):
                    with self.subTest(command=command, root=root.name):
                        before = snapshot_tree(root)
                        output = io.StringIO()
                        with redirect_stdout(output):
                            code = main(["--root", str(root), command, "--apply", "--project", "Demo"])
                        rendered = output.getvalue()
                        self.assertEqual(code, 2)
                        self.assertEqual(before, snapshot_tree(root))
                        self.assertIn("attach-refused", rendered)
                        self.assertIn("fallback/archive or generated-output evidence", rendered)

    def test_attach_apply_requires_project_when_state_would_be_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "attach", "--apply"])
            self.assertEqual(code, 2)
            self.assertFalse((root / ".codex").exists())
            self.assertFalse((root / "project").exists())
            self.assertIn("attach-project-required", output.getvalue())

    def test_attach_apply_creates_only_allowed_scaffold_and_templates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "attach", "--apply", "--project", "Demo"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            for rel_path in (
                ".agents",
                ".codex",
                "project/specs/workflow",
                "project/research",
                "project/plan-incubation",
                "project/archive/plans",
                "project/archive/reference",
            ):
                self.assertTrue((root / rel_path).is_dir(), rel_path)
                self.assertIn(rel_path, rendered)
            self.assertTrue((root / ".codex/project-workflow.toml").is_file())
            self.assertTrue((root / "project/project-state.md").is_file())
            self.assertIn('project: "Demo"', (root / "project/project-state.md").read_text(encoding="utf-8"))
            self.assertFalse((root / ".agents/docmap.yaml").exists())
            self.assertFalse((root / "project/implementation-plan.md").exists())
            self.assertEqual([], list((root / "project/specs/workflow").glob("*.md")))
            self.assertTrue((root / ARTIFACT_DIR_REL / "manifest.json").is_file())
            self.assertTrue((root / INDEX_REL_PATH).is_file())
            self.assertIn("attach-generated-projection-build", rendered)

    def test_attach_apply_is_idempotent_and_preserves_contents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with redirect_stdout(io.StringIO()):
                first_code = main(["--root", str(root), "attach", "--apply", "--project", "Demo"])
            preserved_paths = (
                ".codex/project-workflow.toml",
                "project/project-state.md",
            )
            before = {rel_path: (root / rel_path).read_text(encoding="utf-8") for rel_path in preserved_paths}
            output = io.StringIO()
            with redirect_stdout(output):
                second_code = main(["--root", str(root), "attach", "--apply", "--project", "Demo"])
            self.assertEqual(first_code, 0)
            self.assertEqual(second_code, 0)
            self.assertEqual(before, {rel_path: (root / rel_path).read_text(encoding="utf-8") for rel_path in preserved_paths})
            self.assertTrue((root / ARTIFACT_DIR_REL / "manifest.json").is_file())
            self.assertTrue((root / INDEX_REL_PATH).is_file())
            self.assertIn("attach-unchanged", output.getvalue())
            self.assertIn("attach-generated-projection-build", output.getvalue())

    def test_attach_apply_refuses_path_conflict_without_partial_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".codex").write_text("not a directory\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "attach", "--apply", "--project", "Demo"])
            self.assertEqual(code, 2)
            self.assertTrue((root / ".codex").is_file())
            self.assertFalse((root / "project").exists())
            self.assertIn("attach-target-conflict", output.getvalue())

    def test_attach_apply_refuses_generated_projection_boundary_conflict_without_partial_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".mylittleharness").write_text("not a directory\n", encoding="utf-8")
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "attach", "--apply", "--project", "Demo"])
            rendered = output.getvalue()
            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertFalse((root / ".codex").exists())
            self.assertFalse((root / "project").exists())
            self.assertIn("attach-generated-projection-refused", rendered)
            self.assertIn("non-directory segment", rendered)

    def test_attach_apply_degrades_when_fts5_is_unavailable_without_index_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = io.StringIO()
            with patch("mylittleharness.projection_index._fts5_is_available", return_value=False), redirect_stdout(output):
                code = main(["--root", str(root), "attach", "--apply", "--project", "Demo"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertTrue((root / ARTIFACT_DIR_REL / "manifest.json").is_file())
            self.assertFalse((root / INDEX_REL_PATH).exists())
            self.assertIn("attach-generated-projection-unavailable", rendered)
            self.assertIn("projection-index-fts5-unavailable", rendered)

    def test_check_and_intelligence_do_not_create_missing_projection_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            before = snapshot_tree_bytes(root)
            check_output = io.StringIO()
            with redirect_stdout(check_output):
                check_code = main(["--root", str(root), "check"])
            intelligence_output = io.StringIO()
            with redirect_stdout(intelligence_output):
                intelligence_code = main(["--root", str(root), "intelligence", "--focus", "search", "--query", "MyLittleHarness"])
            self.assertEqual(check_code, 0)
            self.assertEqual(intelligence_code, 0)
            self.assertEqual(before, snapshot_tree_bytes(root))
            self.assertFalse((root / INDEX_REL_PATH).exists())
            self.assertIn("projection-index-query-skipped", intelligence_output.getvalue())

    def test_init_attach_refuses_symlink_scaffold_conflict_without_partial_writes(self) -> None:
        for command in ("init", "attach"):
            with self.subTest(command=command):
                with tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp)
                    root = base / "root"
                    root.mkdir()
                    outside = base / "outside"
                    outside.mkdir()
                    try:
                        os.symlink(outside, root / ".codex", target_is_directory=True)
                    except (OSError, NotImplementedError) as exc:
                        self.skipTest(f"directory symlink unavailable: {exc}")

                    before = snapshot_tree(root)
                    dry_run_output = io.StringIO()
                    with redirect_stdout(dry_run_output):
                        dry_run_code = main(["--root", str(root), command, "--dry-run", "--project", "Demo"])
                    self.assertEqual(dry_run_code, 0)
                    self.assertEqual(before, snapshot_tree(root))
                    self.assertIn("attach-target-conflict", dry_run_output.getvalue())
                    self.assertIn("symlink segment", dry_run_output.getvalue())

                    apply_output = io.StringIO()
                    with redirect_stdout(apply_output):
                        apply_code = main(["--root", str(root), command, "--apply", "--project", "Demo"])
                    self.assertEqual(apply_code, 2)
                    self.assertEqual(before, snapshot_tree(root))
                    self.assertFalse((root / "project").exists())
                    self.assertIn("attach-target-conflict", apply_output.getvalue())
                    self.assertIn("symlink segment", apply_output.getvalue())

    def test_repair_requires_explicit_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            output = io.StringIO()
            with redirect_stderr(output), self.assertRaises(SystemExit) as raised:
                main(["--root", str(root), "repair"])
            self.assertEqual(raised.exception.code, 2)

    def test_snapshot_inspect_requires_explicit_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            output = io.StringIO()
            with redirect_stderr(output), self.assertRaises(SystemExit) as raised:
                main(["--root", str(root), "snapshot"])
            self.assertEqual(raised.exception.code, 2)

    def test_snapshot_inspect_empty_live_root_no_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "snapshot", "--inspect"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertFalse((root / ".mylittleharness").exists())
            self.assertIn("MyLittleHarness snapshot --inspect", rendered)
            for heading in ("Root", "Result", "Sources", "Findings", "Suggestions"):
                self.assertIn(heading, rendered)
            self.assertIn("snapshot-inspect-boundary", rendered)
            self.assertIn("snapshot-inspect-empty", rendered)
            self.assertIn("no repair snapshot directory found", rendered)

    def test_snapshot_inspect_valid_repair_snapshot_no_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            add_complete_scaffold(root)
            (root / ".agents/docmap.yaml").write_text(
                "version: 2\nrepo_summary:\n  product_docs_entrypoints:\n    - \"README.md\"\n",
                encoding="utf-8",
            )
            with redirect_stdout(io.StringIO()):
                apply_code = main(["--root", str(root), "repair", "--apply"])
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                inspect_code = main(["--root", str(root), "snapshot", "--inspect"])
            rendered = output.getvalue()
            self.assertEqual(apply_code, 0)
            self.assertEqual(inspect_code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("snapshot-found", rendered)
            self.assertIn("snapshot-metadata-read", rendered)
            self.assertIn("snapshot-repair-class", rendered)
            self.assertIn("snapshot-copied-file-hash", rendered)
            self.assertIn("snapshot-copied-file-size", rendered)
            self.assertIn("current target differs from copied pre-repair bytes", rendered)
            self.assertIn("manual rollback only", rendered)
            self.assertIn("metadata authority note preserves snapshot non-authority", rendered)
            self.assertNotIn("[WARN]", rendered)

    def test_snapshot_inspect_reports_malformed_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            snapshot_dir = root / ".mylittleharness/snapshots/repair/bad-snapshot"
            snapshot_dir.mkdir(parents=True)
            (snapshot_dir / "snapshot.json").write_text("{not-json\n", encoding="utf-8")
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "snapshot", "--inspect"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("snapshot-metadata-malformed", rendered)

    def test_snapshot_inspect_reports_missing_copied_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            add_complete_scaffold(root)
            (root / ".agents/docmap.yaml").write_text(
                "version: 2\nrepo_summary:\n  product_docs_entrypoints:\n    - \"README.md\"\n",
                encoding="utf-8",
            )
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "repair", "--apply"])
            copied_file = next((root / ".mylittleharness/snapshots/repair").iterdir()) / "files/.agents/docmap.yaml"
            copied_file.unlink()
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "snapshot", "--inspect"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("snapshot-copied-file-missing", rendered)
            self.assertIn("copied file is missing", rendered)

    def test_snapshot_inspect_reports_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            add_complete_scaffold(root)
            (root / ".agents/docmap.yaml").write_text(
                "version: 2\nrepo_summary:\n  product_docs_entrypoints:\n    - \"README.md\"\n",
                encoding="utf-8",
            )
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "repair", "--apply"])
            metadata_path = next((root / ".mylittleharness/snapshots/repair").iterdir()) / "snapshot.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["copied_files"][0]["sha256"] = "0" * 64
            metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "snapshot", "--inspect"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("snapshot-copied-file-hash", rendered)
            self.assertIn("copied file sha256 mismatch", rendered)

    def test_snapshot_inspect_reports_missing_current_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            add_complete_scaffold(root)
            (root / ".agents/docmap.yaml").write_text(
                "version: 2\nrepo_summary:\n  product_docs_entrypoints:\n    - \"README.md\"\n",
                encoding="utf-8",
            )
            with redirect_stdout(io.StringIO()):
                main(["--root", str(root), "repair", "--apply"])
            (root / ".agents/docmap.yaml").unlink()
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "snapshot", "--inspect"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("snapshot-target-missing", rendered)
            self.assertIn("current target is missing: .agents/docmap.yaml", rendered)

    def test_snapshot_inspect_reports_product_fixture_snapshot_debris(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            snapshot_dir = root / ".mylittleharness/snapshots/repair/product-debris"
            snapshot_dir.mkdir(parents=True)
            (snapshot_dir / "snapshot.json").write_text("{}", encoding="utf-8")
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "snapshot", "--inspect"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("snapshot-inspect-product-debris", rendered)
            self.assertIn("product-source compatibility fixture contains repair snapshot debris", rendered)

    def test_snapshot_inspect_reports_fallback_generated_and_ambiguous_posture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            fallback = make_fallback_root(base / "fallback")
            generated = make_generated_output_root(base / "generated")
            ambiguous = base / "ambiguous"
            ambiguous.mkdir()
            cases = (
                (fallback, "fallback/archive or generated-output evidence"),
                (generated, "fallback/archive or generated-output evidence"),
                (ambiguous, "target root kind is ambiguous"),
            )
            for root, expected in cases:
                output = io.StringIO()
                with redirect_stdout(output):
                    code = main(["--root", str(root), "snapshot", "--inspect"])
                self.assertEqual(code, 0)
                self.assertIn("snapshot-inspect-root-posture", output.getvalue())
                self.assertIn(expected, output.getvalue())

    def test_snapshot_inspect_reports_non_directory_boundary_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            (root / ".mylittleharness").mkdir()
            (root / ".mylittleharness/snapshots").write_text("not a directory\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "snapshot", "--inspect"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("snapshot-inspect-boundary-conflict", rendered)
            self.assertIn("snapshot boundary contains a non-directory segment: .mylittleharness/snapshots", rendered)

    def test_snapshot_inspect_reports_symlink_boundary_conflict_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp) / "root")
            outside = Path(tmp) / "outside"
            outside.mkdir()
            (root / ".mylittleharness").mkdir()
            try:
                os.symlink(outside, root / ".mylittleharness/snapshots", target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"directory symlink unavailable: {exc}")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "snapshot", "--inspect"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("snapshot-inspect-boundary-conflict", rendered)
            self.assertIn("snapshot boundary contains a symlink segment: .mylittleharness/snapshots", rendered)

    def test_repair_rejects_dry_run_and_apply_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            output = io.StringIO()
            with redirect_stderr(output), self.assertRaises(SystemExit) as raised:
                main(["--root", str(root), "repair", "--dry-run", "--apply"])
            self.assertEqual(raised.exception.code, 2)

    def test_repair_apply_refuses_product_fixture_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--apply"])
            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("repair-refused", output.getvalue())
            self.assertIn("product-source compatibility fixture", output.getvalue())

    def test_repair_apply_refuses_ambiguous_root_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--apply"])
            self.assertEqual(code, 2)
            self.assertFalse((root / ".agents").exists())
            self.assertFalse((root / "project").exists())
            self.assertIn("repair --apply requires an existing readable workflow-core manifest", output.getvalue())

    def test_repair_apply_refuses_fallback_generated_roots_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cases = (make_fallback_root(base / "fallback"), make_generated_output_root(base / "generated"))
            for root in cases:
                with self.subTest(root=root.name):
                    before = snapshot_tree(root)
                    output = io.StringIO()
                    with redirect_stdout(output):
                        code = main(["--root", str(root), "repair", "--apply"])
                    self.assertEqual(code, 2)
                    self.assertEqual(before, snapshot_tree(root))
                    self.assertIn("repair-refused", output.getvalue())
                    self.assertIn("fallback/archive", output.getvalue())

    def test_repair_dry_run_reports_missing_scaffold_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--dry-run"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("would create missing scaffold directory: .agents", rendered)
            self.assertIn("would create missing scaffold directory: project/research", rendered)
            self.assertIn("would create missing scaffold directory: project/plan-incubation", rendered)

    def test_repair_dry_run_reports_state_frontmatter_plan_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--dry-run"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("state-frontmatter-plan", rendered)
            self.assertIn("selected repair class: state-frontmatter-repair; target file: project/project-state.md", rendered)
            self.assertIn(
                ".mylittleharness/snapshots/repair/00000000T000000Z-state-frontmatter-repair-project-project-state-md-",
                rendered,
            )
            self.assertIn("files/project/project-state.md", rendered)
            self.assertIn("planned frontmatter keys: project, workflow, operating_mode, plan_status, active_plan", rendered)
            self.assertIn("manual rollback only", rendered)
            self.assertFalse((root / ".mylittleharness").exists())

    def test_repair_dry_run_reports_docmap_snapshot_plan_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            add_complete_scaffold(root)
            (root / ".agents/docmap.yaml").write_text(
                "version: 2\nrepo_summary:\n  product_docs_entrypoints:\n    - \"README.md\"\n",
                encoding="utf-8",
            )
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--dry-run"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("snapshot-plan", rendered)
            self.assertIn("selected repair class: docmap-route-repair; target file: .agents/docmap.yaml", rendered)
            self.assertIn(
                ".mylittleharness/snapshots/repair/00000000T000000Z-docmap-route-repair-agents-docmap-yaml-",
                rendered,
            )
            self.assertIn("snapshot.json", rendered)
            self.assertIn("files/.agents/docmap.yaml", rendered)
            self.assertIn("metadata fields: schema_version", rendered)
            self.assertIn("planned route entries: AGENTS.md", rendered)
            self.assertIn("manual rollback only", rendered)
            self.assertIn("python -m mylittleharness --root <target-root> validate", rendered)
            self.assertFalse((root / ".mylittleharness").exists())

    def test_repair_dry_run_reports_clean_docmap_snapshot_plan_not_needed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            add_complete_scaffold(root)
            write_complete_docmap(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--dry-run"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("no .agents/docmap.yaml route diagnostics require a snapshot plan", rendered)
            self.assertNotIn("planned snapshot directory:", rendered)

    def test_repair_dry_run_refuses_snapshot_plan_for_product_fixture_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp), active=False, mirrors=False)
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--dry-run"])
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("snapshot-plan-refused", output.getvalue())
            self.assertIn("product-source compatibility fixture", output.getvalue())

    def test_repair_dry_run_refuses_snapshot_plan_for_fallback_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_fallback_root(Path(tmp))
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--dry-run"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("snapshot-plan-refused", rendered)
            self.assertIn("fallback/archive or generated-output evidence", rendered)

    def test_repair_dry_run_refuses_snapshot_plan_for_ambiguous_root_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--dry-run"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("snapshot-plan-refused", rendered)
            self.assertIn("target root kind is ambiguous", rendered)

    def test_repair_dry_run_skips_snapshot_plan_when_docmap_missing_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--dry-run"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("snapshot-plan-skipped", rendered)
            self.assertIn("target file is absent: .agents/docmap.yaml", rendered)

    def test_repair_dry_run_reports_docmap_create_plan_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            add_complete_scaffold(root)
            require_docmap(root)
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--dry-run"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("docmap-create-plan", rendered)
            self.assertIn("selected repair class: docmap-create; target file: .agents/docmap.yaml", rendered)
            self.assertIn("planned route entries: README.md, AGENTS.md, .codex/project-workflow.toml", rendered)
            self.assertIn("manual rollback only: remove .agents/docmap.yaml", rendered)
            self.assertIn("python -m mylittleharness --root <target-root> validate", rendered)
            self.assertFalse((root / ".agents/docmap.yaml").exists())
            self.assertFalse((root / ".mylittleharness").exists())

    def test_repair_dry_run_skips_docmap_create_when_docmap_is_lazy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            add_complete_scaffold(root)
            enable_lazy_docmap(root)
            require_docmap(root)
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--dry-run"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("docmap-create-skipped", rendered)
            self.assertIn("lazy or not-required docmaps remain absent", rendered)
            self.assertNotIn("docmap-create-plan", rendered)

    def test_repair_dry_run_refuses_snapshot_plan_for_docmap_path_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            (root / ".agents").write_text("not a directory\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--dry-run"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("snapshot-plan-refused", rendered)
            self.assertIn("target path contains a non-directory segment: .agents", rendered)

    def test_repair_dry_run_refuses_snapshot_plan_for_snapshot_boundary_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            add_complete_scaffold(root)
            (root / ".agents/docmap.yaml").write_text("version: 2\n", encoding="utf-8")
            (root / ".mylittleharness").mkdir()
            (root / ".mylittleharness/snapshots").write_text("not a directory\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--dry-run"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("snapshot-plan-refused", rendered)
            self.assertIn("snapshot boundary contains a non-directory segment: .mylittleharness/snapshots", rendered)

    def test_repair_dry_run_refuses_docmap_create_for_docmap_path_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            require_docmap(root)
            (root / ".agents").mkdir()
            (root / ".agents/docmap.yaml").mkdir()
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--dry-run"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("docmap-create-refused", rendered)
            self.assertIn("target path is not a regular file: .agents/docmap.yaml", rendered)

    def test_repair_apply_snapshots_then_updates_docmap_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            add_complete_scaffold(root)
            original_docmap = "version: 2\nrepo_summary:\n  product_docs_entrypoints:\n    - \"README.md\"\n"
            (root / ".agents/docmap.yaml").write_text(original_docmap, encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--apply"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("snapshot-created", rendered)
            self.assertIn("snapshot-copied-file", rendered)
            self.assertIn("snapshot-metadata-written", rendered)
            self.assertIn("repair-docmap-updated", rendered)
            self.assertIn("manual rollback only", rendered)
            self.assertIn("post-repair validation findings: 0 errors", rendered)
            self.assertIn("post-repair audit-link findings: 0 warnings", rendered)

            repaired_docmap = (root / ".agents/docmap.yaml").read_text(encoding="utf-8")
            for rel_path in ("AGENTS.md", ".codex/project-workflow.toml", "project/project-state.md", "project/specs/workflow/"):
                self.assertIn(rel_path, repaired_docmap)

            snapshot_dirs = list((root / ".mylittleharness/snapshots/repair").iterdir())
            self.assertEqual(1, len(snapshot_dirs))
            snapshot_dir = snapshot_dirs[0]
            self.assertRegex(snapshot_dir.name, r"^\d{8}T\d{6}Z-docmap-route-repair-agents-docmap-yaml-[0-9a-f]{12}$")
            copied_docmap = snapshot_dir / "files/.agents/docmap.yaml"
            self.assertEqual(original_docmap, copied_docmap.read_text(encoding="utf-8"))
            metadata = json.loads((snapshot_dir / "snapshot.json").read_text(encoding="utf-8"))
            self.assertEqual(1, metadata["schema_version"])
            self.assertEqual("repair --apply", metadata["command"])
            self.assertEqual("docmap-route-repair", metadata["repair_class"])
            self.assertEqual([".agents/docmap.yaml"], metadata["target_paths"])
            self.assertEqual(str(root.resolve()), metadata["target_root"])
            self.assertEqual(copied_docmap.relative_to(root).as_posix(), metadata["copied_files"][0]["snapshot_path"])
            self.assertIn("AGENTS.md", metadata["planned_route_entries"])
            self.assertIn("safety evidence only", metadata["authority_note"])

    def test_repair_apply_docmap_route_repair_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            add_complete_scaffold(root)
            (root / ".agents/docmap.yaml").write_text(
                "version: 2\nrepo_summary:\n  product_docs_entrypoints:\n    - \"README.md\"\n",
                encoding="utf-8",
            )
            with redirect_stdout(io.StringIO()):
                first_code = main(["--root", str(root), "repair", "--apply"])
            before_second = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                second_code = main(["--root", str(root), "repair", "--apply"])
            self.assertEqual(first_code, 0)
            self.assertEqual(second_code, 0)
            self.assertEqual(before_second, snapshot_tree(root))
            self.assertEqual(1, len(list((root / ".mylittleharness/snapshots/repair").iterdir())))
            rendered = output.getvalue()
            self.assertIn("snapshot-apply-skipped", rendered)
            self.assertIn("repair-unchanged", rendered)

    def test_repair_apply_creates_required_docmap_without_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            add_complete_scaffold(root)
            require_docmap(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--apply"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("docmap-create-created", rendered)
            self.assertIn("docmap-create-rollback", rendered)
            self.assertIn("post-repair validation findings: 0 errors", rendered)
            self.assertIn("post-repair audit-link findings: 0 warnings", rendered)
            docmap = (root / ".agents/docmap.yaml").read_text(encoding="utf-8")
            self.assertEqual(expected_docmap_text(), docmap)
            self.assertFalse((root / ".mylittleharness").exists())

    def test_repair_apply_docmap_create_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            add_complete_scaffold(root)
            require_docmap(root)
            with redirect_stdout(io.StringIO()):
                first_code = main(["--root", str(root), "repair", "--apply"])
            before_second = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                second_code = main(["--root", str(root), "repair", "--apply"])
            self.assertEqual(first_code, 0)
            self.assertEqual(second_code, 0)
            self.assertEqual(before_second, snapshot_tree(root))
            rendered = output.getvalue()
            self.assertIn("docmap-create-skipped", rendered)
            self.assertIn("repair-unchanged", rendered)

    def test_repair_apply_skips_docmap_create_when_docmap_is_lazy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            add_complete_scaffold(root)
            enable_lazy_docmap(root)
            require_docmap(root)
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--apply"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("docmap-create-skipped", rendered)
            self.assertIn("lazy or not-required docmaps remain absent", rendered)
            self.assertFalse((root / ".agents/docmap.yaml").exists())

    def test_repair_apply_never_rewrites_existing_docmap_for_create_class(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            add_complete_scaffold(root)
            require_docmap(root)
            write_complete_docmap(root)
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--apply"])
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("docmap-create-skipped", output.getvalue())
            self.assertFalse((root / ".mylittleharness").exists())

    def test_repair_apply_refuses_docmap_create_path_conflict_without_partial_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            require_docmap(root)
            (root / ".agents").mkdir()
            (root / ".agents/docmap.yaml").mkdir()
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--apply"])
            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("docmap-create-refused", output.getvalue())
            self.assertIn("target path is not a regular file: .agents/docmap.yaml", output.getvalue())

    def test_repair_dry_run_reports_stable_spec_create_plan_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            add_complete_scaffold(root)
            missing = [EXPECTED_SPEC_NAMES[0], EXPECTED_SPEC_NAMES[1]]
            for name in missing:
                (root / "project/specs/workflow" / name).unlink()
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--dry-run"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("stable-spec-create-scope", rendered)
            self.assertIn("selected repair class: stable-spec-create; target directory: project/specs/workflow/", rendered)
            self.assertIn("stable-spec-create-plan", rendered)
            self.assertIn(f"project/specs/workflow/{missing[0]}", rendered)
            self.assertIn(f"project/specs/workflow/{missing[1]}", rendered)
            self.assertIn("manual rollback only", rendered)
            self.assertFalse((root / ".mylittleharness").exists())

    def test_repair_apply_creates_missing_stable_specs_without_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            add_complete_scaffold(root)
            missing_name = EXPECTED_SPEC_NAMES[0]
            target = root / "project/specs/workflow" / missing_name
            target.unlink()
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--apply"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("stable-spec-create-created", rendered)
            self.assertIn("stable-spec-create-rollback", rendered)
            self.assertIn("post-repair validation findings: 0 errors", rendered)
            self.assertIn("post-repair audit-link findings: 0 warnings", rendered)
            self.assertTrue(target.is_file())
            self.assertIn("# Workflow Artifact Model Spec", target.read_text(encoding="utf-8"))
            self.assertFalse((root / ".mylittleharness").exists())

    def test_repair_apply_stable_spec_create_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            add_complete_scaffold(root)
            target = root / "project/specs/workflow" / EXPECTED_SPEC_NAMES[0]
            target.unlink()
            with redirect_stdout(io.StringIO()):
                first_code = main(["--root", str(root), "repair", "--apply"])
            before_second = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                second_code = main(["--root", str(root), "repair", "--apply"])
            self.assertEqual(first_code, 0)
            self.assertEqual(second_code, 0)
            self.assertEqual(before_second, snapshot_tree(root))
            rendered = output.getvalue()
            self.assertIn("stable-spec-create-skipped", rendered)
            self.assertIn("repair-unchanged", rendered)

    def test_repair_apply_never_rewrites_existing_stable_specs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            add_complete_scaffold(root)
            target = root / "project/specs/workflow" / EXPECTED_SPEC_NAMES[0]
            target.write_text("# Custom local spec\n", encoding="utf-8")
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--apply"])
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("stable-spec-create-skipped", output.getvalue())

    def test_repair_dry_run_reports_agents_contract_create_plan_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            add_complete_scaffold(root)
            target = root / "AGENTS.md"
            target.unlink()
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--dry-run"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("agents-contract-create-scope", rendered)
            self.assertIn("selected repair class: agents-contract-create; target file: AGENTS.md", rendered)
            self.assertIn("agents-contract-create-plan", rendered)
            self.assertIn("missing required surface: AGENTS.md", rendered)
            self.assertIn("manual rollback only", rendered)
            self.assertFalse((root / ".mylittleharness").exists())

    def test_repair_apply_creates_missing_agents_contract_without_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            add_complete_scaffold(root)
            target = root / "AGENTS.md"
            target.unlink()
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--apply"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("agents-contract-create-created", rendered)
            self.assertIn("agents-contract-create-rollback", rendered)
            self.assertIn("post-repair validation findings: 0 errors", rendered)
            self.assertIn("post-repair audit-link findings: 0 warnings", rendered)
            self.assertTrue(target.is_file())
            self.assertIn("# MyLittleHarness Operator Contract", target.read_text(encoding="utf-8"))
            self.assertFalse((root / ".mylittleharness").exists())

    def test_repair_apply_agents_contract_create_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            add_complete_scaffold(root)
            target = root / "AGENTS.md"
            target.unlink()
            with redirect_stdout(io.StringIO()):
                first_code = main(["--root", str(root), "repair", "--apply"])
            before_second = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                second_code = main(["--root", str(root), "repair", "--apply"])
            self.assertEqual(first_code, 0)
            self.assertEqual(second_code, 0)
            self.assertEqual(before_second, snapshot_tree(root))
            rendered = output.getvalue()
            self.assertIn("agents-contract-create-skipped", rendered)
            self.assertIn("repair-unchanged", rendered)

    def test_repair_apply_never_rewrites_existing_agents_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            add_complete_scaffold(root)
            target = root / "AGENTS.md"
            target.write_text("# Custom agents\n", encoding="utf-8")
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--apply"])
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("agents-contract-create-skipped", output.getvalue())

    def test_repair_dry_run_refuses_agents_contract_create_for_unsafe_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cases = (
                make_root(base / "product", active=False, mirrors=False),
                make_fallback_root(base / "fallback"),
                base / "ambiguous",
            )
            cases[2].mkdir()
            for root in cases:
                target = root / "AGENTS.md"
                if target.exists():
                    target.unlink()
                with self.subTest(root=root.name):
                    before = snapshot_tree(root)
                    output = io.StringIO()
                    with redirect_stdout(output):
                        code = main(["--root", str(root), "repair", "--dry-run"])
                    self.assertEqual(code, 0)
                    self.assertEqual(before, snapshot_tree(root))
                    self.assertIn("agents-contract-create-refused", output.getvalue())

    def test_repair_apply_refuses_agents_contract_path_conflict_without_partial_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            (root / "AGENTS.md").unlink()
            (root / "AGENTS.md").mkdir()
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--apply"])
            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("agents-contract-create-refused", output.getvalue())
            self.assertIn("target path is not a regular file: AGENTS.md", output.getvalue())

    def test_repair_apply_keeps_active_plan_missing_as_manual_lifecycle_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            (root / "AGENTS.md").unlink()
            state_path = root / "project/project-state.md"
            state_path.write_text(
                state_path.read_text(encoding="utf-8").replace(
                    'operating_mode: "ad_hoc"\nplan_status: "none"\nactive_plan: ""',
                    'operating_mode: "plan"\nplan_status: "active"\nactive_plan: "project/implementation-plan.md"',
                ),
                encoding="utf-8",
            )
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--apply"])
            rendered = output.getvalue()
            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("state-frontmatter-refused", rendered)
            self.assertIn("active-plan-missing", rendered)
            self.assertFalse((root / "AGENTS.md").exists())

    def test_repair_dry_run_refuses_stable_spec_create_for_unsafe_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cases = (
                make_root(base / "product", active=False, mirrors=False),
                make_fallback_root(base / "fallback"),
                base / "ambiguous",
            )
            cases[2].mkdir()
            for root in cases:
                spec = root / "project/specs/workflow" / EXPECTED_SPEC_NAMES[0]
                if spec.exists():
                    spec.unlink()
                with self.subTest(root=root.name):
                    before = snapshot_tree(root)
                    output = io.StringIO()
                    with redirect_stdout(output):
                        code = main(["--root", str(root), "repair", "--dry-run"])
                    self.assertEqual(code, 0)
                    self.assertEqual(before, snapshot_tree(root))
                    self.assertIn("stable-spec-create-refused", output.getvalue())

    def test_repair_dry_run_refuses_stable_spec_create_path_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            spec_root = root / "project/specs/workflow"
            for child in spec_root.iterdir():
                child.unlink()
            spec_root.rmdir()
            spec_root.write_text("not a directory\n", encoding="utf-8")
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--dry-run"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("stable-spec-create-refused", rendered)
            self.assertIn("target path contains a non-directory segment: project/specs/workflow", rendered)

    def test_repair_apply_refuses_snapshot_boundary_conflict_without_partial_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            (root / ".agents").mkdir()
            original_docmap = "version: 2\nrepo_summary:\n  product_docs_entrypoints:\n    - \"README.md\"\n"
            (root / ".agents/docmap.yaml").write_text(original_docmap, encoding="utf-8")
            (root / ".mylittleharness").mkdir()
            (root / ".mylittleharness/snapshots").write_text("not a directory\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--apply"])
            rendered = output.getvalue()
            self.assertEqual(code, 2)
            self.assertIn("snapshot-apply-refused", rendered)
            self.assertIn("snapshot boundary contains a non-directory segment: .mylittleharness/snapshots", rendered)
            self.assertEqual(original_docmap, (root / ".agents/docmap.yaml").read_text(encoding="utf-8"))
            self.assertFalse((root / "project/research").exists())
            self.assertFalse((root / "project/plan-incubation").exists())

    def test_repair_apply_creates_missing_scaffold_directories_and_validates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--apply"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            for rel_path in (
                ".agents",
                "project/research",
                "project/plan-incubation",
                "project/archive/plans",
                "project/archive/reference",
            ):
                self.assertTrue((root / rel_path).is_dir(), rel_path)
                self.assertIn(rel_path, rendered)
            self.assertIn("repair-created", rendered)
            self.assertIn("post-repair validation findings: 0 errors", rendered)
            self.assertFalse((root / ".agents/docmap.yaml").exists())
            self.assertFalse((root / "project/implementation-plan.md").exists())

    def test_repair_apply_is_idempotent_and_preserves_contents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            with redirect_stdout(io.StringIO()):
                first_code = main(["--root", str(root), "repair", "--apply"])
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                second_code = main(["--root", str(root), "repair", "--apply"])
            self.assertEqual(first_code, 0)
            self.assertEqual(second_code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("repair-unchanged", output.getvalue())

    def test_repair_apply_refuses_path_conflict_without_partial_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            (root / "project/research").write_text("not a directory\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--apply"])
            self.assertEqual(code, 2)
            self.assertFalse((root / ".agents").exists())
            self.assertTrue((root / "project/research").is_file())
            self.assertIn("repair-target-conflict", output.getvalue())

    def test_validate_accepts_portable_operating_root_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "validate"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("state-prose-fallback", rendered)
            self.assertNotIn("missing-required-surface", rendered)
            self.assertNotIn("state-frontmatter", rendered)
            self.assertNotIn("stale-plan-file", rendered)

    def test_validate_warns_when_incubation_route_is_hidden_or_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            (root / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
            (root / "project/incubator").mkdir(parents=True)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "validate"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("agents-incubation-contract-missing", rendered)
            self.assertIn("incubation-legacy-path", rendered)
            self.assertIn("project/plan-incubation/*.md", rendered)

    def test_status_reports_operating_root_active_plan_from_prose_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "status"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("root kind: live_operating_root", rendered)
        self.assertIn("plan_status: active", rendered)
        self.assertIn("active_phase: Phase 1", rendered)
        self.assertIn("phase_status: in_progress", rendered)
        self.assertIn("active plan present: project/implementation-plan.md", rendered)
        self.assertIn("lifecycle-route-table", rendered)
        self.assertIn("incubation: project/plan-incubation/*.md", rendered)
        self.assertIn("decisions: project/decisions/*.md", rendered)
        self.assertIn("future-optional", rendered)

    def test_repair_apply_snapshots_then_prepends_state_frontmatter_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            original_state = (root / "project/project-state.md").read_text(encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--apply"])
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("state-frontmatter-updated", rendered)
            self.assertIn("state-frontmatter-rerun", rendered)
            self.assertIn("post-repair validation findings: 0 errors", rendered)
            self.assertIn("post-repair audit-link findings: 0 warnings", rendered)
            self.assertNotIn("repair-existing", rendered)

            repaired_state = (root / "project/project-state.md").read_text(encoding="utf-8")
            self.assertTrue(repaired_state.startswith("---\n"))
            self.assertIn('project: "Operating"', repaired_state)
            self.assertIn('workflow: "workflow-core"', repaired_state)
            self.assertIn('operating_mode: "plan"', repaired_state)
            self.assertIn('plan_status: "active"', repaired_state)
            self.assertIn('active_plan: "project/implementation-plan.md"', repaired_state)
            self.assertIn('active_phase: "Phase 1"', repaired_state)
            self.assertIn('phase_status: "in_progress"', repaired_state)
            self.assertIn("historical_fallback_root:", repaired_state)
            self.assertTrue(repaired_state.endswith(original_state))

            snapshot_dirs = list((root / ".mylittleharness/snapshots/repair").iterdir())
            self.assertEqual(1, len(snapshot_dirs))
            snapshot_dir = snapshot_dirs[0]
            self.assertRegex(snapshot_dir.name, r"^\d{8}T\d{6}Z-state-frontmatter-repair-project-project-state-md-[0-9a-f]{12}$")
            copied_state = snapshot_dir / "files/project/project-state.md"
            self.assertEqual(original_state, copied_state.read_text(encoding="utf-8"))
            metadata = json.loads((snapshot_dir / "snapshot.json").read_text(encoding="utf-8"))
            self.assertEqual("state-frontmatter-repair", metadata["repair_class"])
            self.assertEqual(["project/project-state.md"], metadata["target_paths"])
            self.assertEqual(copied_state.relative_to(root).as_posix(), metadata["copied_files"][0]["snapshot_path"])
            self.assertIn("plan_status", metadata["planned_frontmatter_keys"])
            self.assertEqual([], metadata["planned_route_entries"])
            self.assertIn("state-prose-fallback", metadata["source_diagnostics"][0]["code"])
            self.assertIn("safety evidence only", metadata["authority_note"])

    def test_repair_apply_state_frontmatter_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            with redirect_stdout(io.StringIO()):
                first_code = main(["--root", str(root), "repair", "--apply"])
            before_second = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                second_code = main(["--root", str(root), "repair", "--apply"])
            self.assertEqual(first_code, 0)
            self.assertEqual(second_code, 0)
            self.assertEqual(before_second, snapshot_tree(root))
            self.assertEqual(1, len(list((root / ".mylittleharness/snapshots/repair").iterdir())))
            rendered = output.getvalue()
            self.assertNotIn("state-frontmatter-updated", rendered)
            self.assertIn("repair-unchanged", rendered)

    def test_snapshot_inspect_valid_state_frontmatter_snapshot_no_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            with redirect_stdout(io.StringIO()):
                apply_code = main(["--root", str(root), "repair", "--apply"])
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                inspect_code = main(["--root", str(root), "snapshot", "--inspect"])
            rendered = output.getvalue()
            self.assertEqual(apply_code, 0)
            self.assertEqual(inspect_code, 0)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("snapshot-repair-class", rendered)
            self.assertIn("repair class: state-frontmatter-repair", rendered)
            self.assertIn("snapshot-planned-frontmatter", rendered)
            self.assertIn("project/project-state.md", rendered)
            self.assertNotIn("[WARN]", rendered)

    def test_repair_apply_refuses_state_frontmatter_non_default_state_path_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            custom = root / "project/custom-state.md"
            custom.write_text((root / "project/project-state.md").read_text(encoding="utf-8"), encoding="utf-8")
            manifest_path = root / ".codex/project-workflow.toml"
            manifest_path.write_text(
                manifest_path.read_text(encoding="utf-8").replace(
                    'state_file = "project/project-state.md"',
                    'state_file = "project/custom-state.md"',
                ),
                encoding="utf-8",
            )
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--apply"])
            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("state-frontmatter-refused", output.getvalue())
            self.assertIn("manifest state_file is project/custom-state.md", output.getvalue())

    def test_repair_apply_refuses_state_frontmatter_active_plan_mismatch_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            state_path = root / "project/project-state.md"
            state_path.write_text(
                state_path.read_text(encoding="utf-8").replace(
                    'active_plan = "project/implementation-plan.md"',
                    'active_plan = "project/other-plan.md"',
                ),
                encoding="utf-8",
            )
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--apply"])
            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("state-frontmatter-refused", output.getvalue())
            self.assertIn("active_plan mismatch", output.getvalue())

    def test_repair_apply_refuses_state_frontmatter_snapshot_boundary_conflict_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_operating_root(Path(tmp))
            (root / ".mylittleharness").mkdir()
            (root / ".mylittleharness/snapshots").write_text("not a directory\n", encoding="utf-8")
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--apply"])
            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("state-frontmatter-refused", output.getvalue())
            self.assertIn("snapshot boundary contains a non-directory segment: .mylittleharness/snapshots", output.getvalue())

    def test_repair_apply_refuses_malformed_state_frontmatter_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_live_root(Path(tmp))
            state_path = root / "project/project-state.md"
            state_path.write_text('---\nproject: "Demo"\nworkflow: "workflow-core"\n# no closing marker\n', encoding="utf-8")
            before = snapshot_tree(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--root", str(root), "repair", "--apply"])
            self.assertEqual(code, 2)
            self.assertEqual(before, snapshot_tree(root))
            self.assertIn("state-frontmatter-refused", output.getvalue())


def make_root(root: Path, active: bool, mirrors: bool) -> Path:
    (root / ".codex").mkdir(parents=True)
    (root / ".agents").mkdir(parents=True)
    (root / "project/specs/workflow").mkdir(parents=True)
    (root / ".codex/project-workflow.toml").write_text(
        'workflow = "workflow-core"\nversion = 1\n\n[memory]\nstate_file = "project/project-state.md"\nplan_file = "project/implementation-plan.md"\n',
        encoding="utf-8",
    )
    plan_status = "active" if active else "none"
    active_plan = "project/implementation-plan.md" if active else ""
    phase_fields = 'active_phase: "Phase 1"\nphase_status: "in_progress"\n' if active else ""
    (root / "project/project-state.md").write_text(
        f'---\nproject: "MyLittleHarness"\nroot_role: "product-source"\nfixture_status: "product-compatibility-fixture"\nworkflow: "workflow-core"\noperating_mode: "plan"\nplan_status: "{plan_status}"\nactive_plan: "{active_plan}"\n{phase_fields}operating_root: "{root.parent / "operator-root"}"\nproduct_source_root: "{root}"\nhistorical_fallback_root: "{root.parent / "legacy-root"}"\n---\n# State\n\nNo active implementation plan is open in this product tree.\nThis product tree stores fixture metadata only.\n',
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Readme\nSee `.agents/docmap.yaml`.\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("# Agents\nUse `.agents/docmap.yaml`.\n", encoding="utf-8")
    (root / ".agents/docmap.yaml").write_text(
        'version: 2\nrepo_summary:\n  product_docs_entrypoints:\n    - "README.md"\n    - "AGENTS.md"\n    - ".codex/project-workflow.toml"\n    - "project/project-state.md"\n    - "project/specs/workflow/"\n',
        encoding="utf-8",
    )
    if active:
        (root / "project/implementation-plan.md").write_text("# Plan\n", encoding="utf-8")
    for name in EXPECTED_SPEC_NAMES:
        content = f"# {name}\n"
        (root / "project/specs/workflow" / name).write_text(content, encoding="utf-8")
        if mirrors:
            (root / "specs/workflow").mkdir(parents=True, exist_ok=True)
            (root / "specs/workflow" / name).write_text(content, encoding="utf-8")
    return root


def make_package_source_root(root: Path) -> Path:
    make_root(root, active=False, mirrors=False)
    (root / "src/mylittleharness").mkdir(parents=True)
    (root / "src/mylittleharness/__init__.py").write_text('__version__ = "1.0.0"\n', encoding="utf-8")
    (root / "src/mylittleharness/cli.py").write_text(
        "def main():\n"
        "    print('MyLittleHarness repo safety utility')\n"
        "    return 0\n",
        encoding="utf-8",
    )
    (root / "build_backend").mkdir()
    (root / "build_backend/mylittleharness_build.py").write_text("# test build backend placeholder\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[build-system]\n"
        "requires = []\n"
        'build-backend = "mylittleharness_build"\n'
        'backend-path = ["build_backend"]\n'
        "\n"
        "[project]\n"
        'name = "mylittleharness"\n'
        'version = "1.0.0"\n'
        'dependencies = []\n'
        "\n"
        "[project.scripts]\n"
        'mylittleharness = "mylittleharness.cli:main"\n',
        encoding="utf-8",
    )
    return root


def make_live_root(root: Path) -> Path:
    (root / ".codex").mkdir(parents=True)
    (root / "project/specs/workflow").mkdir(parents=True)
    (root / ".codex/project-workflow.toml").write_text(
        'workflow = "workflow-core"\nversion = 1\n\n[memory]\nstate_file = "project/project-state.md"\nplan_file = "project/implementation-plan.md"\n',
        encoding="utf-8",
    )
    (root / "project/project-state.md").write_text(
        '---\nproject: "Demo"\nworkflow: "workflow-core"\noperating_mode: "ad_hoc"\nplan_status: "none"\nactive_plan: ""\n---\n# Demo Project State\n\nNo active implementation plan.\n',
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("# Agents\nUse `project/plan-incubation/*.md` for incubation notes.\n", encoding="utf-8")
    for name in EXPECTED_SPEC_NAMES:
        (root / "project/specs/workflow" / name).write_text(f"# {name}\n", encoding="utf-8")
    return root


def make_active_live_root(root: Path, phase_status: str = "in_progress") -> Path:
    make_live_root(root)
    state_path = root / "project/project-state.md"
    state_path.write_text(
        state_path.read_text(encoding="utf-8").replace(
            'operating_mode: "ad_hoc"\nplan_status: "none"\nactive_plan: ""',
            (
                'operating_mode: "plan"\n'
                'plan_status: "active"\n'
                'active_plan: "project/implementation-plan.md"\n'
                'active_phase: "Phase 4 - Validation And Closeout"\n'
                f'phase_status: "{phase_status}"'
            ),
        ),
        encoding="utf-8",
    )
    (root / "project/implementation-plan.md").write_text("# Plan\n", encoding="utf-8")
    return root


def make_fallback_root(root: Path) -> Path:
    (root / ".codex").mkdir(parents=True)
    (root / ".agents").mkdir(parents=True)
    (root / "project/specs/workflow").mkdir(parents=True)
    (root / ".codex/project-workflow.toml").write_text(
        'workflow = "workflow-core"\nversion = 1\n\n[memory]\nstate_file = "project/project-state.md"\nplan_file = "project/implementation-plan.md"\n',
        encoding="utf-8",
    )
    (root / "project/project-state.md").write_text(
        '---\nproject: "Archive"\nroot_role: "archive"\nworkflow: "workflow-core"\noperating_mode: "ad_hoc"\nplan_status: "none"\nactive_plan: ""\n---\n# Archive State\n',
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Archive\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
    (root / ".agents/docmap.yaml").write_text("version: 2\n", encoding="utf-8")
    for name in EXPECTED_SPEC_NAMES:
        (root / "project/specs/workflow" / name).write_text(f"# {name}\n", encoding="utf-8")
    return root


def make_generated_output_root(root: Path) -> Path:
    (root / ".codex").mkdir(parents=True)
    (root / "project").mkdir(parents=True)
    (root / ".codex/project-workflow.toml").write_text(
        'workflow = "workflow-core"\nversion = 1\n\n[memory]\nstate_file = "project/project-state.md"\n',
        encoding="utf-8",
    )
    (root / "project/project-state.md").write_text(
        '---\nproject: "Generated"\nroot_role: "generated-output"\nworkflow: "workflow-core"\noperating_mode: "ad_hoc"\nplan_status: "none"\nactive_plan: ""\n---\n# Generated Output State\n',
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Generated\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
    return root


def make_operating_root(root: Path) -> Path:
    (root / ".codex").mkdir(parents=True)
    (root / ".agents").mkdir(parents=True)
    (root / "project/specs/workflow").mkdir(parents=True)
    (root / "project/research").mkdir(parents=True)
    (root / "project/plan-incubation").mkdir(parents=True)
    (root / "project/archive/plans").mkdir(parents=True)
    (root / "project/archive/reference").mkdir(parents=True)
    (root / ".codex/project-workflow.toml").write_text(
        'workflow = "workflow-core"\n'
        "version = 1\n"
        "\n"
        "[memory]\n"
        'state_file = "project/project-state.md"\n'
        'plan_file = "project/implementation-plan.md"\n'
        'archive_dir = "project/archive/plans"\n'
        "\n"
        "[policy]\n"
        'docmap_mode = "lazy"\n'
        'closeout_commit = "manual"\n',
        encoding="utf-8",
    )
    (root / "AGENTS.md").write_text(
        "# Operating Project Agents\n\n"
        "Read `project/project-state.md` first. `.agents/docmap.yaml` is lazy.\n"
        "Use `project/plan-incubation/*.md` for incubation notes.\n",
        encoding="utf-8",
    )
    (root / "project/project-state.md").write_text(
        "# Operating Project State\n\n"
        "## Plan Status\n\n"
        'plan_status = "active"\n\n'
        'operating_mode = "plan"\n\n'
        'active_plan = "project/implementation-plan.md"\n\n'
        'active_phase = "Phase 1"\n\n'
        'phase_status = "in_progress"\n\n'
        f'historical_fallback_root = "{root.parent / "legacy-root"}"\n\n'
        "## Current Focus\n\n"
        "This root remains the operating project root.\n",
        encoding="utf-8",
    )
    (root / "project/implementation-plan.md").write_text("# Active Plan\n", encoding="utf-8")
    (root / "project/research/README.md").write_text("# Research\n", encoding="utf-8")
    for name in EXPECTED_SPEC_NAMES:
        (root / "project/specs/workflow" / name).write_text(f"# {name}\n", encoding="utf-8")
    return root


def add_complete_scaffold(root: Path) -> None:
    for rel_path in (
        ".agents",
        "project/research",
        "project/plan-incubation",
        "project/archive/plans",
        "project/archive/reference",
    ):
        (root / rel_path).mkdir(parents=True, exist_ok=True)


def write_complete_docmap(root: Path) -> None:
    (root / ".agents").mkdir(parents=True, exist_ok=True)
    (root / ".agents/docmap.yaml").write_text(expected_docmap_text(), encoding="utf-8")


def expected_docmap_text() -> str:
    return (
        "version: 2\n"
        "repo_summary:\n"
        "  product_docs_entrypoints:\n"
        "    - \"README.md\"\n"
        "    - \"AGENTS.md\"\n"
        "    - \".codex/project-workflow.toml\"\n"
        "    - \"project/project-state.md\"\n"
        "    - \"project/specs/workflow/\"\n"
    )


def require_docmap(root: Path) -> None:
    (root / "AGENTS.md").write_text("# Agents\nUse `.agents/docmap.yaml`.\n", encoding="utf-8")


def enable_lazy_docmap(root: Path) -> None:
    manifest_path = root / ".codex/project-workflow.toml"
    manifest = manifest_path.read_text(encoding="utf-8")
    if "[policy]" not in manifest:
        manifest += "\n[policy]\n"
    manifest += 'docmap_mode = "lazy"\n'
    manifest_path.write_text(manifest, encoding="utf-8")


def large_active_state_text(loose_title_text: bool = False) -> str:
    title_intro = "Loose title paragraph makes section boundaries unclear.\n\n" if loose_title_text else ""
    old_sections = []
    for section_number in range(1, 8):
        lines = "\n".join(f"- Old detail {section_number}.{line_number}: historical context." for line_number in range(1, 38))
        old_sections.append(f"## Ad Hoc Update - 2026-04-0{section_number} - Old Work {section_number}\n\n{lines}\n")
    return (
        "---\n"
        'project: "Demo"\n'
        'workflow: "workflow-core"\n'
        'operating_mode: "plan"\n'
        'plan_status: "active"\n'
        'active_plan: "project/implementation-plan.md"\n'
        'active_phase: "Phase 4 - Validation And Closeout"\n'
        'phase_status: "complete"\n'
        "---\n"
        "# Demo Project State\n\n"
        f"{title_intro}"
        "## Current Focus\n\n"
        "Finish the current lifecycle close.\n\n"
        "## Repository Role Map\n\n"
        "- Operating root: this temporary test root.\n"
        "- Product source: not used by this fixture.\n\n"
        "## Notes\n\n"
        "Short note stays in operating memory.\n\n"
        f"{''.join(old_sections)}\n"
        "## Ad Hoc Update - 2026-04-30 - Automatic Operating Memory Compaction\n\n"
        "- Product target: clean product source.\n"
        "- Result: compaction should keep this latest relevant update.\n\n"
        "## MLH Closeout Writeback\n\n"
        "<!-- BEGIN mylittleharness-closeout-writeback v1 -->\n"
        "- docs_decision: uncertain\n"
        "- state_writeback: pending\n"
        "<!-- END mylittleharness-closeout-writeback v1 -->\n"
    )


def large_inactive_state_text() -> str:
    return (
        large_active_state_text()
        .replace('operating_mode: "plan"\n', 'operating_mode: "ad_hoc"\n')
        .replace('plan_status: "active"\n', 'plan_status: "none"\n')
        .replace('active_plan: "project/implementation-plan.md"\n', 'active_plan: ""\n')
    )


def snapshot_tree(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel_path = path.relative_to(root).as_posix()
        snapshot[rel_path] = "<dir>" if path.is_dir() else path.read_text(encoding="utf-8")
    return snapshot


def snapshot_tree_bytes(root: Path) -> dict[str, bytes]:
    snapshot: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        rel_path = path.relative_to(root).as_posix()
        snapshot[rel_path] = b"<dir>" if path.is_dir() else path.read_bytes()
    return snapshot


def jsonrpc_lines(value: str) -> list[dict[str, object]]:
    lines = [line for line in value.splitlines() if line]
    return [json.loads(line) for line in lines]


if __name__ == "__main__":
    unittest.main()
