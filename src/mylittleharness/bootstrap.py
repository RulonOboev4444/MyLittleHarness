from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import venv
from pathlib import Path

from .inventory import Inventory
from .models import Finding


def bootstrap_sections(inventory: Inventory) -> list[tuple[str, list[Finding]]]:
    return [
        ("Summary", _summary_findings(inventory)),
        ("Package Smoke", _package_smoke_findings(inventory)),
        ("Bootstrap Apply", _bootstrap_apply_findings()),
        ("Switch-Over", _switch_over_findings()),
        ("Publishing", _publishing_findings()),
        ("Workstation Adoption", _workstation_adoption_findings()),
        ("Boundary", _boundary_findings()),
    ]


def package_smoke_sections(inventory: Inventory) -> list[tuple[str, list[Finding]]]:
    root_findings = _package_root_findings(inventory)
    if any(finding.severity == "error" for finding in root_findings):
        return [
            ("Summary", _package_smoke_summary_findings(inventory, "error")),
            ("Package Root", root_findings),
            ("Temp Boundary", _package_smoke_not_started_findings()),
            ("Install", _package_smoke_not_started_findings()),
            ("Import", _package_smoke_not_started_findings()),
            ("Console Script", _package_smoke_not_started_findings()),
            ("Boundary", _package_smoke_boundary_findings()),
        ]
    return _run_package_smoke(inventory, root_findings)


def _summary_findings(inventory: Inventory) -> list[Finding]:
    return [
        Finding("info", "bootstrap-summary", "bootstrap readiness report for package, setup, switch-over, publishing, and workstation adoption lanes"),
        Finding("info", "bootstrap-root-kind", f"root kind: {inventory.root_kind}"),
        Finding("info", "bootstrap-python", f"current interpreter: {sys.executable}; version={sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"),
        Finding("info", "bootstrap-report", "bootstrap --inspect is terminal-only and read-only"),
    ]


def _package_smoke_findings(inventory: Inventory) -> list[Finding]:
    findings = [
        Finding(
            "info",
            "bootstrap-package-smoke",
            "local wheel/install smoke remains temporary verification for package metadata, importability, and the console script only",
        ),
        Finding(
            "info",
            "bootstrap-package-artifacts",
            "build directories, wheels, dist output, and egg-info must stay outside the product source root and never become authority",
        ),
    ]
    if inventory.root_kind == "product_source_fixture":
        project = _read_project_metadata(inventory.root / "pyproject.toml")
        if project is None:
            findings.append(Finding("warn", "bootstrap-package-metadata", "package metadata could not be read from pyproject.toml"))
        else:
            scripts = project.get("scripts") if isinstance(project.get("scripts"), dict) else {}
            script = scripts.get("mylittleharness") if isinstance(scripts, dict) else None
            findings.extend(
                [
                    Finding(
                        "info",
                        "bootstrap-package-metadata",
                        f"name={project.get('name', 'unknown')}; version={project.get('version', 'unknown')}",
                    ),
                    Finding("info", "bootstrap-console-script", f"console script declaration: mylittleharness = {script or 'missing'}"),
                ]
            )
    else:
        findings.append(
            Finding(
                "info",
                "bootstrap-package-metadata-skipped",
                "package metadata is checked only for the product source checkout; live operating roots use package smoke evidence from the product root",
            )
        )
    return findings


def _package_root_findings(inventory: Inventory) -> list[Finding]:
    findings = [
        Finding("info", "package-smoke-root-kind", f"root kind: {inventory.root_kind}"),
        Finding("info", "package-smoke-root", f"package source root: {inventory.root}"),
    ]
    if inventory.root_kind != "product_source_fixture":
        findings.append(
            Finding(
                "error",
                "package-smoke-root-refused",
                "package smoke requires the MyLittleHarness product source checkout and refuses operating, fallback, archive, generated, or ambiguous roots",
            )
        )
    pyproject_path = inventory.root / "pyproject.toml"
    package_dir = inventory.root / "src/mylittleharness"
    if not pyproject_path.is_file():
        findings.append(Finding("error", "package-smoke-pyproject-missing", "pyproject.toml is required in the package source root"))
    if not package_dir.is_dir():
        findings.append(Finding("error", "package-smoke-src-missing", "src/mylittleharness is required in the package source root"))
    pyproject = _read_pyproject(pyproject_path)
    raw_project = pyproject.get("project") if pyproject else None
    project = raw_project if isinstance(raw_project, dict) else None
    if project is None:
        findings.append(Finding("error", "package-smoke-pyproject-invalid", "pyproject.toml could not be parsed for package metadata"))
    else:
        findings.append(
            Finding(
                "info",
                "package-smoke-metadata",
                f"name={project.get('name', 'unknown')}; version={project.get('version', 'unknown')}; scripts={sorted((project.get('scripts') or {}).keys())}",
            )
        )
        if project.get("name") != "mylittleharness":
            findings.append(Finding("error", "package-smoke-name-invalid", "package name must be mylittleharness"))
        if (project.get("scripts") or {}).get("mylittleharness") != "mylittleharness.cli:main":
            findings.append(Finding("error", "package-smoke-script-invalid", "console script must be mylittleharness = mylittleharness.cli:main"))
    build_system = pyproject.get("build-system") if pyproject else None
    if isinstance(build_system, dict):
        if build_system.get("requires") != []:
            findings.append(Finding("error", "package-smoke-build-requires-invalid", "build-system.requires must stay empty for no-network package smoke"))
        if build_system.get("build-backend") != "mylittleharness_build":
            findings.append(Finding("error", "package-smoke-build-backend-invalid", "build backend must be mylittleharness_build"))
        backend_paths = build_system.get("backend-path")
        if backend_paths != ["build_backend"] or not (inventory.root / "build_backend/mylittleharness_build.py").is_file():
            findings.append(Finding("error", "package-smoke-build-backend-missing", "build_backend/mylittleharness_build.py is required for no-network package smoke"))
    else:
        findings.append(Finding("error", "package-smoke-build-system-invalid", "pyproject.toml [build-system] table is required"))
    return findings


def _run_package_smoke(inventory: Inventory, root_findings: list[Finding]) -> list[tuple[str, list[Finding]]]:
    with tempfile.TemporaryDirectory(prefix="mylittleharness-package-smoke-") as tmp:
        temp_root = Path(tmp).resolve()
        source_copy = temp_root / "source"
        venv_dir = temp_root / "venv"
        temp_findings = _temp_boundary_findings(inventory.root, temp_root, source_copy, venv_dir)
        install_findings: list[Finding] = []
        import_findings: list[Finding] = []
        console_findings: list[Finding] = []
        try:
            shutil.copytree(inventory.root, source_copy, ignore=_package_copy_ignore)
            _create_venv(venv_dir)
            python_exe = _venv_python(venv_dir)
            install_findings = _install_findings(python_exe, source_copy)
            if not any(finding.severity == "error" for finding in install_findings):
                import_findings = _import_findings(python_exe, source_copy)
            else:
                import_findings = [_skip_after_failure("package-smoke-import-skipped", "import check skipped because package install failed")]
            if not any(finding.severity == "error" for finding in install_findings + import_findings):
                console_findings = _console_findings(python_exe, source_copy)
            else:
                console_findings = [_skip_after_failure("package-smoke-console-skipped", "console script check skipped because install or import failed")]
        except Exception as exc:  # pragma: no cover - defensive subprocess/venv boundary
            if not install_findings:
                install_findings = [Finding("error", "package-smoke-exception", f"package smoke failed before install completed: {type(exc).__name__}: {exc}")]
            elif not import_findings:
                import_findings = [Finding("error", "package-smoke-exception", f"package smoke failed before import completed: {type(exc).__name__}: {exc}")]
            else:
                console_findings = [Finding("error", "package-smoke-exception", f"package smoke failed before console check completed: {type(exc).__name__}: {exc}")]
        all_findings = root_findings + temp_findings + install_findings + import_findings + console_findings
        result = "error" if any(finding.severity == "error" for finding in all_findings) else "ok"
        temp_findings.append(Finding("info", "package-smoke-temp-cleanup", f"temporary workspace is scheduled for removal: {temp_root}"))
        return [
            ("Summary", _package_smoke_summary_findings(inventory, result)),
            ("Package Root", root_findings),
            ("Temp Boundary", temp_findings),
            ("Install", install_findings),
            ("Import", import_findings),
            ("Console Script", console_findings),
            ("Boundary", _package_smoke_boundary_findings()),
        ]


def _read_project_metadata(pyproject_path: Path) -> dict[str, object] | None:
    data = _read_pyproject(pyproject_path)
    project = data.get("project") if data else None
    return project if isinstance(project, dict) else None


def _read_pyproject(pyproject_path: Path) -> dict[str, object] | None:
    try:
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return data


def _package_smoke_summary_findings(inventory: Inventory, status: str) -> list[Finding]:
    severity = "error" if status == "error" else "info"
    return [
        Finding(
            severity,
            "package-smoke-result",
            f"package smoke status={status}; verifies local install, import, and console script from a temporary environment",
        ),
        Finding("info", "package-smoke-root-kind", f"root kind: {inventory.root_kind}"),
        Finding(
            "info",
            "package-smoke-no-authority",
            "package smoke is verification evidence only and cannot publish, switch roots, approve lifecycle actions, or create package authority",
        ),
    ]


def _package_smoke_not_started_findings() -> list[Finding]:
    return [Finding("info", "package-smoke-not-started", "package smoke did not start because package root validation failed")]


def _temp_boundary_findings(product_root: Path, temp_root: Path, source_copy: Path, venv_dir: Path) -> list[Finding]:
    outside = not _is_relative_to(temp_root, product_root)
    severity = "info" if outside else "error"
    return [
        Finding(severity, "package-smoke-temp-boundary", f"temporary workspace outside product root: {outside}; path={temp_root}"),
        Finding("info", "package-smoke-source-copy", f"temporary source copy: {source_copy}"),
        Finding("info", "package-smoke-venv", f"temporary virtual environment: {venv_dir}"),
    ]


def _install_findings(python_exe: Path, source_copy: Path) -> list[Finding]:
    command = [
        str(python_exe),
        "-m",
        "pip",
        "install",
        "--no-index",
        "--no-build-isolation",
        "--no-deps",
        str(source_copy),
    ]
    result = _run_command(command, cwd=source_copy)
    if result.returncode != 0:
        return [
            Finding(
                "error",
                "package-smoke-install-failed",
                f"local no-network install failed with exit {result.returncode}: {_command_output(result)}",
            )
        ]
    return [
        Finding(
            "info",
            "package-smoke-install-ok",
            "local no-network install completed in the temporary virtual environment with --no-index --no-build-isolation --no-deps",
        )
    ]


def _import_findings(python_exe: Path, source_copy: Path) -> list[Finding]:
    expected_version = _read_project_metadata(source_copy / "pyproject.toml")["version"]  # type: ignore[index]
    code = "import mylittleharness; print(mylittleharness.__version__)"
    result = _run_command([str(python_exe), "-c", code], cwd=source_copy.parent)
    observed = result.stdout.strip()
    if result.returncode != 0:
        return [Finding("error", "package-smoke-import-failed", f"import check failed with exit {result.returncode}: {_command_output(result)}")]
    if observed != expected_version:
        return [
            Finding(
                "error",
                "package-smoke-version-mismatch",
                f"imported mylittleharness version {observed!r} did not match pyproject version {expected_version!r}",
            )
        ]
    return [Finding("info", "package-smoke-import-ok", f"imported mylittleharness version {observed}")]


def _console_findings(python_exe: Path, source_copy: Path) -> list[Finding]:
    script = _venv_script(python_exe.parent.parent, "mylittleharness")
    command = [str(script), "--help"] if script.exists() else [str(python_exe), "-m", "mylittleharness.cli", "--help"]
    result = _run_command(command, cwd=source_copy.parent)
    if result.returncode != 0:
        return [Finding("error", "package-smoke-console-failed", f"console script help failed with exit {result.returncode}: {_command_output(result)}")]
    if "MyLittleHarness repo safety utility" not in result.stdout or "init" not in result.stdout:
        return [Finding("error", "package-smoke-console-invalid", f"console script help output did not match CLI contract: {_trim(result.stdout)}")]
    return [Finding("info", "package-smoke-console-ok", "mylittleharness console script returned help output from the temporary environment")]


def _package_smoke_boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "package-smoke-no-product-artifacts",
            "package smoke uses only temporary source, build, install, and venv locations outside the product source root",
        ),
        Finding(
            "info",
            "package-smoke-no-workstation-mutation",
            "package smoke does not publish packages, change PATH, write user config, install hooks, add CI/GitHub workflows, or adopt workstation state",
        ),
        Finding(
            "info",
            "package-smoke-no-lifecycle-authority",
            "package smoke output cannot approve bootstrap apply, switch-over, closeout, archive, commit, repair, rollback, or lifecycle decisions",
        ),
    ]


def _skip_after_failure(code: str, message: str) -> Finding:
    return Finding("warn", code, message)


def _create_venv(venv_dir: Path) -> None:
    venv.EnvBuilder(with_pip=True, system_site_packages=True, clear=True).create(venv_dir)


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts/python.exe"
    return venv_dir / "bin/python"


def _venv_script(venv_dir: Path, name: str) -> Path:
    if os.name == "nt":
        return venv_dir / f"Scripts/{name}.exe"
    return venv_dir / f"bin/{name}"


def _run_command(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    return subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, timeout=120)


def _package_copy_ignore(directory: str, names: list[str]) -> set[str]:
    ignored = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "build", "dist"}
    ignored.update(name for name in names if name.endswith(".egg-info") or name.endswith(".pyc") or name.endswith(".pyo"))
    return ignored.intersection(names)


def _command_output(result: subprocess.CompletedProcess[str]) -> str:
    output = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
    return _trim(output or "no command output")


def _trim(value: str, limit: int = 240) -> str:
    rendered = " ".join(value.split())
    if len(rendered) <= limit:
        return rendered
    return rendered[: limit - 3] + "..."


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _bootstrap_apply_findings() -> list[Finding]:
    return [
        Finding(
            "warn",
            "bootstrap-apply-rejected",
            "fate=rejected as standalone product surface; bootstrap apply is not implemented and normal correctness does not depend on it",
        ),
        Finding(
            "info",
            "bootstrap-apply-gate",
            "future adoption, publication, or switch-over apply behavior must use a later scoped contract with its own command ownership, exact target root, exact write set, dry-run shape, refusal cases, validation gate, rollback posture, cleanup/non-adoption story, and non-authority wording",
        ),
    ]


def _switch_over_findings() -> list[Finding]:
    return [
        Finding(
            "warn",
            "bootstrap-switch-over-rejected",
            "fate=rejected as standalone product surface; operating-root switch-over automation is not implemented and normal correctness does not depend on it",
        ),
        Finding(
            "info",
            "bootstrap-switch-over-gate",
            "any future migration or adoption checklist must use a separate scoped contract that defines source and destination roots, exact write set, start-pass recovery, validation evidence, rollback posture, closeout evidence, refusal cases, and non-authority wording before implementation",
        ),
        Finding(
            "info",
            "bootstrap-switch-over-non-authority",
            "package smoke, docs, generated projections, adapter output, hooks, and CLI reports cannot declare switch-over status",
        ),
    ]


def _publishing_findings() -> list[Finding]:
    return [
        Finding("warn", "bootstrap-publishing-out-of-scope", "fate=out of scope for this plan; package-index upload, credentials, signing, global install, and persistent package artifact policy are not implemented"),
        Finding(
            "info",
            "bootstrap-publishing-boundary",
            "bootstrap --inspect uses no publishing credentials, no network access, no package upload, and no product-root package artifact storage",
        ),
    ]


def _workstation_adoption_findings() -> list[Finding]:
    discovered = shutil.which("mylittleharness")
    discovery_message = f"PATH discovery for mylittleharness console script: {discovered}" if discovered else "PATH discovery for mylittleharness console script: not found"
    return [
        Finding(
            "info",
            "bootstrap-workstation-readiness",
            "fate=ship now as no-write readiness evidence only; workstation adoption helpers report context but do not adopt or mutate workstation state",
        ),
        Finding(
            "info",
            "bootstrap-path-discovery",
            discovery_message,
        ),
        Finding(
            "info",
            "bootstrap-workstation-out-of-scope",
            "PATH changes, shell profiles, user config, global tools, hooks, CI, IDE/browser/MCP state, package indexes, and credentials remain outside this helper",
        ),
        Finding(
            "info",
            "bootstrap-workstation-boundary",
            "this report does not install tools, mutate user configuration, write hook or CI files, or adopt workstation state",
        ),
    ]


def _boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "bootstrap-read-only",
            "bootstrap --inspect writes no files, reports, package artifacts, generated output, snapshots, hooks, CI config, user config, VCS state, or credentials",
        ),
        Finding(
            "info",
            "bootstrap-no-authority",
            "bootstrap readiness output cannot approve correctness, repair, closeout, archive, commit, publishing, switch-over, lifecycle decisions, or mutation",
        ),
        Finding(
            "info",
            "bootstrap-no-runtime",
            "bootstrap --inspect starts no background runtime, installs no dependencies, publishes no packages, and performs no bootstrap apply",
        ),
    ]
