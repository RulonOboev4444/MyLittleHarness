from __future__ import annotations

import sys
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "build_backend"))

from mylittleharness import __version__
import mylittleharness_build


class PackageMetadataTests(unittest.TestCase):
    def test_package_metadata_matches_runtime_contract(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = pyproject["project"]

        self.assertEqual("mylittleharness", project["name"])
        self.assertEqual(__version__, project["version"])
        self.assertEqual("1.0.0", __version__)
        self.assertEqual([], project["dependencies"])
        self.assertEqual({"mylittleharness": "mylittleharness.cli:main"}, project["scripts"])

    def test_stdlib_build_backend_stays_self_contained(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual([], pyproject["build-system"]["requires"])
        self.assertEqual("mylittleharness_build", pyproject["build-system"]["build-backend"])
        self.assertEqual(["build_backend"], pyproject["build-system"]["backend-path"])
        self.assertTrue((ROOT / "build_backend/mylittleharness_build.py").is_file())

    def test_wheel_includes_stable_spec_templates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wheel_name = mylittleharness_build.build_wheel(tmp)
            with zipfile.ZipFile(Path(tmp) / wheel_name) as wheel:
                names = set(wheel.namelist())

        self.assertIn("mylittleharness/templates/operating-root/AGENTS.md", names)
        self.assertIn("mylittleharness/templates/workflow/workflow-artifact-model-spec.md", names)
        self.assertIn("mylittleharness/templates/workflow/workflow-plan-synthesis-spec.md", names)

    def test_wheel_metadata_keeps_local_install_entrypoint_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wheel_name = mylittleharness_build.build_wheel(tmp)
            self.assertEqual("mylittleharness-1.0.0-py3-none-any.whl", wheel_name)
            with zipfile.ZipFile(Path(tmp) / wheel_name) as wheel:
                metadata = wheel.read("mylittleharness-1.0.0.dist-info/METADATA").decode("utf-8")
                entry_points = wheel.read("mylittleharness-1.0.0.dist-info/entry_points.txt").decode("utf-8")

        self.assertIn("Name: mylittleharness\n", metadata)
        self.assertIn("Version: 1.0.0\n", metadata)
        self.assertIn("[console_scripts]\n", entry_points)
        self.assertIn("mylittleharness = mylittleharness.cli:main\n", entry_points)

    def test_release_readiness_docs_keep_publication_optional(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        docs_readme = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        boundary = (ROOT / "docs/specs/product-boundary.md").read_text(encoding="utf-8")

        self.assertIn("The local release checklist is:", readme)
        for expected in (
            "package metadata and runtime version agree on `1.0.0`",
            "`bootstrap --package-smoke` passes from temporary source/build/install locations outside the product source checkout",
            "Wheel, build, and install artifacts are verification outputs only",
            "rejects standalone `bootstrap --apply`",
            "standalone switch-over automation is rejected",
        ):
            self.assertIn(expected, readme)
        for expected in (
            "documentation-and-verification based",
            "Package-index publication, signed artifact release, global installation",
            "standalone switch-over automation",
        ):
            self.assertIn(expected, docs_readme)
        for expected in (
            "not by publication",
            "ephemeral verification artifacts",
            "not required for release-candidate correctness",
            "standalone switch-over automation is rejected",
        ):
            self.assertIn(expected, boundary)

    def test_first_run_docs_keep_small_operator_path_primary(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        docs_readme = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        architecture = (ROOT / "docs/architecture/target-architecture.md").read_text(encoding="utf-8")
        cli_spec = (ROOT / "docs/specs/attach-repair-status-cli.md").read_text(encoding="utf-8")

        for expected in (
            "## First-Run Operator Path",
            "python -m mylittleharness --root $ProductRoot bootstrap --package-smoke",
            "python -m mylittleharness --root $TargetRoot init --dry-run",
            "python -m mylittleharness --root $TargetRoot check",
            "python -m mylittleharness --root $TargetRoot repair --dry-run",
            "python -m mylittleharness --root $TargetRoot detach --dry-run",
            "Apply modes stay explicit and target-bound",
            "they are not required first-contact steps",
        ):
            self.assertIn(expected, readme)
        for forbidden in (
            "python -m mylittleharness --root $ProductRoot init --dry-run",
            "python -m mylittleharness --root $ProductRoot repair --dry-run",
            "python -m mylittleharness --root $ProductRoot detach --dry-run",
        ):
            self.assertNotIn(forbidden, readme)
        for expected in (
            "The first-run operator path is deliberately shorter than the full diagnostic surface",
            "then point `--root` at the target repository",
            "not prerequisites for first-run correctness",
        ):
            self.assertIn(expected, docs_readme)
        for expected in (
            "The first-run path is source checkout first",
            "target-repository `init` / `check` / `repair` / `detach`",
            "not prerequisites for first-contact correctness",
        ):
            self.assertIn(expected, architecture)
        for expected in (
            "The first-run operator path starts from source-checkout usage",
            "then points `--root` at the target repository",
            "`init --dry-run`, `check`, `repair --dry-run`, and `detach --dry-run`",
        ):
            self.assertIn(expected, cli_spec)

    def test_portable_start_pass_contract_has_no_skill_dependency(self) -> None:
        template = (ROOT / "src/mylittleharness/templates/operating-root/AGENTS.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        docs_readme = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        architecture = (ROOT / "docs/architecture/target-architecture.md").read_text(encoding="utf-8")
        cli_spec = (ROOT / "docs/specs/attach-repair-status-cli.md").read_text(encoding="utf-8")

        for expected in (
            "Any file-reading, shell-capable agent can operate",
            "installed skills, IDE rules, MCP clients, hooks, and CI are optional convenience layers only",
            "Start by reading this `AGENTS.md`, `.codex/project-workflow.toml`, and `project/project-state.md`",
            'Read `project/implementation-plan.md` only when `project/project-state.md` or the manifest says `plan_status = "active"`',
            "Use the optional docs routing file when present as a routing aid",
            "Run `mylittleharness --root <this-repo> check` before mutating repair work",
        ):
            self.assertIn(expected, template)
        for expected in (
            "Any file-reading, shell-capable agent can use MyLittleHarness from repo-visible files plus CLI reports",
            "`project/implementation-plan.md` only when `plan_status = \"active\"`",
            "Codex skills, IDE-native rules, MCP clients, shell aliases, preflight wrappers, hooks, and CI may wrap this flow",
        ):
            self.assertIn(expected, readme)
        for expected in (
            "The operating-root start pass is portable across agents that can read files and run shell commands",
            "do not require Codex skills, IDE-native skills, MCP clients, hooks, CI, or workstation adoption",
        ):
            self.assertIn(expected, docs_readme)
        self.assertIn("No skill, IDE rule, MCP client, hook, CI job, or workstation adoption step is part of the correctness path", architecture)
        self.assertIn("The no-skill start pass is part of the CLI contract", cli_spec)
        self.assertIn("no `docs-impact`, `guide`, or `orient` command is required for v1", cli_spec)

    def test_docs_decision_contract_is_portable(self) -> None:
        template = (ROOT / "src/mylittleharness/templates/operating-root/AGENTS.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        docs_readme = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        architecture = (ROOT / "docs/architecture/target-architecture.md").read_text(encoding="utf-8")
        metadata = (ROOT / "docs/specs/metadata-routing-and-evidence.md").read_text(encoding="utf-8")
        cli_spec = (ROOT / "docs/specs/attach-repair-status-cli.md").read_text(encoding="utf-8")

        for doc in (template, readme, docs_readme, architecture, metadata, cli_spec):
            self.assertIn("updated", doc)
            self.assertIn("not-needed", doc)
            self.assertIn("uncertain", doc)
        for doc in (readme, docs_readme, metadata, cli_spec):
            self.assertIn(
                "behavior, CLI usage, configuration, setup, contract meaning, permissions, output shape, UX/copy, terminology, rollout, migration",
                doc,
            )
            self.assertIn("`audit-links`", doc)
            self.assertIn("`check`", doc)
        self.assertIn("no Codex skill or generated docs-impact report is required for v1", readme)
        self.assertIn("A Codex skill, generated docs-impact report, IDE rule, MCP client, hook, or CI result may help route attention", metadata)
        self.assertIn("it cannot be required for the decision and cannot store the only copy of the decision", metadata)

    def test_optional_adapter_docs_reject_skill_owned_memory(self) -> None:
        adapter = (ROOT / "docs/specs/adapter-boundary.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        for expected in (
            "Optional wrappers such as Codex skills, IDE rules, shell aliases, preflight wrappers, MCP clients, hooks, CI jobs, and future adapter packs",
            "must not become the first-run path, docs-decision path, repair path, verification path, closeout path",
            "skill-only correctness and skill-owned memory are rejected",
        ):
            self.assertIn(expected, adapter)
        self.assertIn("must not store the only copy of accepted decisions, current focus, docs decisions, repair approval, verification, or closeout evidence", readme)

    def test_rule_context_drift_docs_keep_check_compact(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        docs_readme = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        cli_spec = (ROOT / "docs/specs/attach-repair-status-cli.md").read_text(encoding="utf-8")

        for expected in (
            "primary instruction-surface size warnings",
            "Deeper section-size detail remains in advanced `context-budget` and `doctor` diagnostics",
            "link/docmap/stale-root/rule-context/remainder drift",
        ):
            self.assertIn(expected, readme)
        self.assertIn("deeper section-size details remain advanced diagnostics", docs_readme)
        for expected in (
            "primary instruction-surface size warnings",
            "product docs and stable specs remain covered by advanced `context-budget` detail",
            "`doctor` stays summary-oriented",
        ):
            self.assertIn(expected, cli_spec)


if __name__ == "__main__":
    unittest.main()

