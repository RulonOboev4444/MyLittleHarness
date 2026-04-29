from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mylittleharness.checks import (
    check_drift_findings,
    audit_link_findings,
    product_hygiene_findings,
    rule_context_findings,
    status_findings,
    validation_findings,
)
from mylittleharness.inventory import EXPECTED_SPEC_NAMES, load_inventory


class InventoryTests(unittest.TestCase):
    def test_missing_optional_surfaces_do_not_create_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            inventory = load_inventory(root)
            errors = [finding for finding in validation_findings(inventory) if finding.severity == "error"]
            self.assertEqual(errors, [])

    def test_status_reports_product_root_posture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            inventory = load_inventory(root)
            codes = [finding.code for finding in status_findings(inventory)]
            for expected in (
                "product-name",
                "target-root-role",
                "fixture-status",
                "operating-root",
                "product-root",
                "fallback-root",
                "no-switch-over",
            ):
                self.assertIn(expected, codes)

    def test_product_posture_reports_wrong_product_name_and_root_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            state = root / "project/project-state.md"
            state.write_text(
                f'---\nproject: "workflow-core"\nroot_role: "operating-root"\nfixture_status: "live-workflow"\nworkflow: "workflow-core"\noperating_mode: "ad_hoc"\nplan_status: "none"\nactive_plan: ""\noperating_root: "{root}"\nproduct_source_root: "{root.parent / "Elsewhere"}"\nhistorical_fallback_root: "{root}"\n---\n# State\n',
                encoding="utf-8",
            )
            inventory = load_inventory(root)
            errors = [finding.code for finding in validation_findings(inventory) if finding.severity == "error"]
            self.assertIn("product-posture-product-name", errors)
            self.assertIn("product-posture-root-role", errors)
            self.assertIn("product-posture-fixture-status", errors)
            self.assertIn("product-posture-product-root", errors)
            self.assertIn("product-posture-operating-root", errors)
            self.assertIn("product-posture-fallback-root", errors)

    def test_product_posture_rejects_active_plan_in_product_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=True, docmap=True)
            inventory = load_inventory(root)
            errors = [finding.code for finding in validation_findings(inventory) if finding.severity == "error"]
            self.assertIn("product-posture-active-plan", errors)

    def test_active_plan_is_required_when_state_is_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=True, docmap=True)
            (root / "project/implementation-plan.md").unlink()
            inventory = load_inventory(root)
            errors = [finding.code for finding in validation_findings(inventory) if finding.severity == "error"]
            self.assertIn("active-plan-missing", errors)

    def test_mirror_drift_is_reported_as_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True, mirrors=True)
            (root / "specs/workflow" / EXPECTED_SPEC_NAMES[0]).write_text("# drift\n", encoding="utf-8")
            inventory = load_inventory(root)
            errors = [finding.code for finding in validation_findings(inventory) if finding.severity == "error"]
            self.assertIn("mirror-drift", errors)

    def test_inactive_plan_route_is_not_required_in_docmap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            inventory = load_inventory(root)
            warnings = [finding.code for finding in audit_link_findings(inventory) if finding.severity == "warn"]
            self.assertNotIn("candidate-docmap-gap", warnings)

    def test_active_plan_route_is_required_in_docmap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=True, docmap=True)
            inventory = load_inventory(root)
            warnings = [finding.code for finding in audit_link_findings(inventory) if finding.severity == "warn"]
            self.assertIn("candidate-docmap-gap", warnings)

    def test_product_doc_links_resolve_relative_to_source_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            (root / "docs/architecture").mkdir(parents=True)
            (root / "docs/README.md").write_text("Read `architecture/target-architecture.md`.\n", encoding="utf-8")
            (root / "docs/architecture/target-architecture.md").write_text("# Target\n", encoding="utf-8")
            inventory = load_inventory(root)
            warnings = [
                finding
                for finding in audit_link_findings(inventory)
                if finding.severity == "warn" and finding.code in {"missing-link", "unresolved-link"}
            ]
            self.assertEqual(warnings, [])

    def test_audit_links_reports_product_docmap_gaps_and_stale_root_wording(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            (root / "docs").mkdir(parents=True)
            archive_root = root.parent / "legacy-root"
            (root / "docs/README.md").write_text(
                f"{archive_root} is current source.\n{root} is the operating root.\n",
                encoding="utf-8",
            )
            (root / "pyproject.toml").write_text("[project]\nname = \"mylittleharness\"\n", encoding="utf-8")
            (root / "src/mylittleharness").mkdir(parents=True)
            (root / "tests").mkdir()
            inventory = load_inventory(root)
            warnings = [finding.code for finding in audit_link_findings(inventory) if finding.severity == "warn"]
            self.assertIn("candidate-docmap-gap", warnings)
            self.assertIn("stale-fallback-root-reference", warnings)
            self.assertIn("stale-product-root-role", warnings)

    def test_check_drift_reports_only_docmap_and_root_pointer_risk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            (root / "docs").mkdir(parents=True)
            archive_root = root.parent / "legacy-root"
            (root / "docs/README.md").write_text(
                f"{archive_root} is current source.\n"
                f"{root} is the operating root.\n"
                "`missing-local.md` is missing.\n",
                encoding="utf-8",
            )
            (root / "pyproject.toml").write_text("[project]\nname = \"mylittleharness\"\n", encoding="utf-8")
            (root / "src/mylittleharness").mkdir(parents=True)
            (root / "tests").mkdir()
            inventory = load_inventory(root)
            codes = [finding.code for finding in check_drift_findings(inventory)]
            self.assertIn("candidate-docmap-gap", codes)
            self.assertIn("stale-fallback-root-reference", codes)
            self.assertIn("stale-product-root-role", codes)
            self.assertNotIn("missing-link", codes)

    def test_check_drift_reports_remainder_contradiction_for_explicit_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            state = root / "project/project-state.md"
            state.write_text(
                state.read_text(encoding="utf-8")
                + "\n## Delivered\n\n- Completed `detach --apply` as marker-only disable.\n"
                + "\n## Future Backlog\n\n- Future contract still lists `detach --apply` as unimplemented.\n",
                encoding="utf-8",
            )
            inventory = load_inventory(root)
            findings = check_drift_findings(inventory)
            warnings = [finding for finding in findings if finding.severity == "warn"]
            self.assertEqual(["remainder-drift"], [finding.code for finding in warnings])
            self.assertIn("project/project-state.md", warnings[0].source or "")

    def test_check_drift_allows_clean_remainder_with_distinct_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            state = root / "project/project-state.md"
            state.write_text(
                state.read_text(encoding="utf-8")
                + "\n## Delivered\n\n- Completed `detach --apply` as marker-only disable.\n"
                + "\n## Future Backlog\n\n- Future contract still lists `semantic --inspect` policy work.\n",
                encoding="utf-8",
            )
            inventory = load_inventory(root)
            codes = [finding.code for finding in check_drift_findings(inventory)]
            self.assertIn("check-drift-ok", codes)
            self.assertNotIn("remainder-drift", codes)

    def test_check_drift_ignores_historical_release_remainder_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            state = root / "project/project-state.md"
            state.write_text(
                state.read_text(encoding="utf-8")
                + "\n## Delivered\n\n- Completed `closeout` Git evidence suggestions.\n"
                + "\n## Historical Release Notes\n\n- Future backlog in a prior release mentioned `closeout`.\n",
                encoding="utf-8",
            )
            inventory = load_inventory(root)
            codes = [finding.code for finding in check_drift_findings(inventory)]
            self.assertIn("check-drift-ok", codes)
            self.assertNotIn("remainder-drift", codes)

    def test_check_drift_does_not_guess_ambiguous_prose_remainder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            state = root / "project/project-state.md"
            state.write_text(
                state.read_text(encoding="utf-8")
                + "\n## Delivered\n\n- Completed semantic provider policy design research.\n"
                + "\n## Future Backlog\n\n- Future semantic provider policy implementation remains open.\n",
                encoding="utf-8",
            )
            inventory = load_inventory(root)
            codes = [finding.code for finding in check_drift_findings(inventory)]
            self.assertIn("check-drift-ok", codes)
            self.assertNotIn("remainder-drift", codes)

    def test_rule_context_reports_large_primary_instruction_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            (root / "AGENTS.md").write_text("# AGENTS\n" + ("Instruction line.\n" * 501), encoding="utf-8")
            inventory = load_inventory(root)
            findings = rule_context_findings(inventory)
            warnings = [finding for finding in findings if finding.severity == "warn"]
            self.assertEqual(["rule-context-surface-large"], [finding.code for finding in warnings])
            self.assertEqual("AGENTS.md", warnings[0].source)

    def test_check_drift_excludes_large_product_docs_and_stable_specs_from_rule_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            (root / "docs").mkdir()
            (root / "docs/large.md").write_text("# Large Doc\n" + ("Details.\n" * 501), encoding="utf-8")
            (root / "project/specs/workflow" / EXPECTED_SPEC_NAMES[0]).write_text(
                "# Large Stable Spec\n" + ("Details.\n" * 501),
                encoding="utf-8",
            )
            inventory = load_inventory(root)
            codes = [finding.code for finding in check_drift_findings(inventory)]
            self.assertIn("check-drift-ok", codes)
            self.assertNotIn("rule-context-surface-large", codes)

    def test_product_hygiene_allows_clean_product_fixture_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            inventory = load_inventory(root)
            findings = product_hygiene_findings(inventory)
            warning_codes = [finding.code for finding in findings if finding.severity == "warn"]
            self.assertEqual(warning_codes, [])
            self.assertIn("product-hygiene-ok", [finding.code for finding in findings])

    def test_product_hygiene_reports_operational_surfaces_and_debris(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_minimal_root(Path(tmp), active=False, docmap=True)
            (root / "project/research").mkdir()
            (root / "project/research/raw.md").write_text("# Raw\n", encoding="utf-8")
            (root / "project/archive/plans").mkdir(parents=True)
            (root / "project/archive/plans/old.md").write_text("# Old\n", encoding="utf-8")
            (root / "__pycache__").mkdir()
            (root / "debug.log").write_text("debug\n", encoding="utf-8")
            (root / "local.sqlite").write_text("", encoding="utf-8")
            (root / "dist").mkdir()
            (root / "reports").mkdir()
            (root / "validation-artifacts").mkdir()
            (root / "generated-validation").mkdir()
            (root / "validation-report-2026-04-25.md").write_text("# Generated\n", encoding="utf-8")
            (root / "scratch.pyc").write_text("", encoding="utf-8")

            inventory = load_inventory(root)
            findings = [finding for finding in product_hygiene_findings(inventory) if finding.severity == "warn"]
            codes = [finding.code for finding in findings]
            sources = {finding.source for finding in findings}

            self.assertIn("forbidden-product-surface", codes)
            self.assertIn("product-debris", codes)
            self.assertIn("project/research", sources)
            self.assertIn("project/archive", sources)
            self.assertIn("__pycache__", sources)
            self.assertIn("debug.log", sources)
            self.assertIn("local.sqlite", sources)
            self.assertIn("dist", sources)
            self.assertIn("reports", sources)
            self.assertIn("validation-artifacts", sources)
            self.assertIn("generated-validation", sources)
            self.assertIn("validation-report-2026-04-25.md", sources)
            self.assertIn("scratch.pyc", sources)


def make_minimal_root(root: Path, active: bool, docmap: bool, mirrors: bool = False) -> Path:
    (root / ".codex").mkdir(parents=True)
    (root / "project/specs/workflow").mkdir(parents=True)
    (root / ".codex/project-workflow.toml").write_text(
        'workflow = "workflow-core"\n\n[memory]\nstate_file = "project/project-state.md"\nplan_file = "project/implementation-plan.md"\n',
        encoding="utf-8",
    )
    plan_status = "active" if active else "none"
    active_plan = "project/implementation-plan.md" if active else ""
    (root / "project/project-state.md").write_text(
        f'---\nproject: "MyLittleHarness"\nroot_role: "product-source"\nfixture_status: "product-compatibility-fixture"\nworkflow: "workflow-core"\noperating_mode: "plan"\nplan_status: "{plan_status}"\nactive_plan: "{active_plan}"\noperating_root: "{root.parent / "operator-root"}"\nproduct_source_root: "{root}"\nhistorical_fallback_root: "{root.parent / "legacy-root"}"\n---\n# State\n\nNo active implementation plan is open in this product tree.\nThis product tree stores fixture metadata only.\n',
        encoding="utf-8",
    )
    (root / "README.md").write_text("# README\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    if docmap:
        (root / ".agents").mkdir(parents=True)
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


if __name__ == "__main__":
    unittest.main()

