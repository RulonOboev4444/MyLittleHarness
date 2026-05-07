from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .inventory import Inventory, RootLoadError, load_inventory
from .models import Finding


@dataclass(frozen=True)
class MirrorRequest:
    target_root: str
    paths: tuple[str, ...]
    allow_product_target: bool = False


@dataclass(frozen=True)
class MirrorRootPosture:
    root: Path
    root_kind: str
    root_role: str
    product_source_root: Path | None
    product_source_root_text: str
    load_errors: tuple[str, ...] = ()

    @property
    def is_product_source_root(self) -> bool:
        if self.root_kind == "product_source_fixture":
            return True
        return bool(self.product_source_root and _same_resolved_path(self.root, self.product_source_root))


@dataclass(frozen=True)
class MirrorFilePlan:
    rel_path: str
    source_path: Path
    target_path: Path
    source_sha256: str
    target_sha256: str | None
    action: str


@dataclass(frozen=True)
class MirrorDependencyClosure:
    rel_paths: frozenset[str]
    importers: dict[str, frozenset[str]]
    findings: tuple[Finding, ...]


def make_mirror_request(target_root: str, paths: list[str], allow_product_target: bool = False) -> MirrorRequest:
    return MirrorRequest(target_root=target_root, paths=tuple(paths), allow_product_target=allow_product_target)


def mirror_dry_run_findings(inventory, request: MirrorRequest) -> list[Finding]:
    findings, plan = _mirror_plan(inventory, request)
    findings.insert(0, Finding("info", "mirror-dry-run", "mirror proposal only; no files were written"))
    findings.append(
        Finding(
            "info",
            "mirror-boundary",
            "mirror previews declared root-relative product-to-demo file copies only; it cannot approve closeout, archive, roadmap promotion, staging, commit, rollback, or lifecycle decisions",
        )
    )
    findings.extend(_mirror_summary_findings(plan, copied=False))
    return findings


def mirror_apply_findings(inventory, request: MirrorRequest) -> list[Finding]:
    findings, plan = _mirror_plan(inventory, request)
    findings.insert(0, Finding("info", "mirror-apply", "mirror apply started"))
    if any(finding.severity == "error" for finding in findings):
        findings.append(Finding("info", "mirror-apply-refused", "mirror apply refused before writing target files"))
        return findings

    copied = 0
    for file_plan in plan:
        if file_plan.action == "equal":
            continue
        try:
            _write_bytes_atomic(file_plan.source_path.read_bytes(), file_plan.target_path)
        except OSError as exc:
            findings.append(Finding("error", "mirror-copy-failed", f"copy failed: {exc}", file_plan.rel_path))
            break
        copied += 1
        findings.append(Finding("info", "mirror-file-copied", f"copied declared file to target: {file_plan.rel_path}", file_plan.rel_path))
        target_sha256 = _sha256(file_plan.target_path)
        if target_sha256 != file_plan.source_sha256:
            findings.append(
                Finding(
                    "error",
                    "mirror-verify-failed",
                    f"post-copy hash mismatch: source_sha256={file_plan.source_sha256}; target_sha256={target_sha256}",
                    file_plan.rel_path,
                )
            )
            break
        findings.append(Finding("info", "mirror-verified", f"hash parity verified: sha256={target_sha256}", file_plan.rel_path))

    findings.append(Finding("info", "mirror-no-vcs", "mirror apply does not stage, commit, push, or mutate Git state"))
    findings.append(
        Finding(
            "info",
            "mirror-boundary",
            "mirror apply writes only declared target files after dry-run-compatible validation; it cannot approve closeout, archive, roadmap promotion, rollback, or lifecycle decisions",
        )
    )
    findings.extend(_mirror_summary_findings(plan, copied=not any(finding.severity == "error" for finding in findings), copied_count=copied))
    return findings


def _mirror_plan(inventory: Inventory, request: MirrorRequest) -> tuple[list[Finding], list[MirrorFilePlan]]:
    source_root = inventory.root
    findings: list[Finding] = [
        Finding("info", "mirror-source-root", f"source root: {source_root}"),
        Finding("info", "mirror-target-root", f"target root: {Path(request.target_root).expanduser()}"),
    ]
    plan: list[MirrorFilePlan] = []
    target_root = Path(request.target_root).expanduser()
    source_root = source_root.resolve()
    target_root_resolved = target_root.resolve(strict=False)
    source_posture = _root_posture_from_inventory(inventory)
    target_posture = _target_root_posture(target_root_resolved)
    findings.extend(_root_posture_findings("source", source_posture))
    findings.extend(_root_posture_findings("target", target_posture))
    findings.append(
        Finding(
            "info",
            "mirror-direction-boundary",
            "mirror direction boundary: source must be the product_source_root and target must not be a product_source_root unless explicitly reviewed",
        )
    )
    findings.extend(_mirror_direction_guard_findings(source_posture, target_posture, request))

    if not target_root.exists() or not target_root.is_dir():
        findings.append(Finding("error", "mirror-refused", f"--target-root must be an existing directory: {target_root}"))
        return findings, plan
    if source_root == target_root_resolved:
        findings.append(Finding("error", "mirror-refused", "--target-root must be different from --root"))
        return findings, plan

    seen: set[str] = set()
    for raw_path in request.paths:
        rel_result = _normalize_rel_path(raw_path)
        if isinstance(rel_result, Finding):
            findings.append(rel_result)
            continue
        rel_path = rel_result.as_posix()
        if rel_path in seen:
            findings.append(Finding("error", "mirror-refused", f"duplicate declared mirror path: {rel_path}", rel_path))
            continue
        seen.add(rel_path)

        source_path = source_root.joinpath(*rel_result.parts)
        target_path = target_root_resolved.joinpath(*rel_result.parts)
        path_errors = _path_validation_errors(source_root, target_root_resolved, rel_path, source_path, target_path)
        if path_errors:
            findings.extend(path_errors)
            continue

        source_sha256 = _sha256(source_path)
        target_sha256 = _sha256(target_path) if target_path.exists() else None
        if target_sha256 is None:
            findings.append(Finding("warn", "mirror-target-missing", f"would copy missing target file; source_sha256={source_sha256}", rel_path))
            action = "copy"
        elif target_sha256 != source_sha256:
            findings.append(
                Finding(
                    "warn",
                    "mirror-drift",
                    f"would replace target file; source_sha256={source_sha256}; target_sha256={target_sha256}",
                    rel_path,
                )
            )
            action = "copy"
        else:
            findings.append(Finding("info", "mirror-parity-ok", f"target hash already matches source: sha256={source_sha256}", rel_path))
            action = "equal"
        plan.append(MirrorFilePlan(rel_path, source_path, target_path, source_sha256, target_sha256, action))

    if not request.paths:
        findings.append(Finding("error", "mirror-refused", "at least one --path is required"))
    findings.extend(_mirror_dependency_closure_findings(source_root, target_root_resolved, plan))
    return findings, plan


def _root_posture_from_inventory(inventory: Inventory) -> MirrorRootPosture:
    data = inventory.state.frontmatter.data if inventory.state and inventory.state.exists else {}
    product_source_root_text = str(data.get("product_source_root") or data.get("projection_root") or "")
    return MirrorRootPosture(
        root=inventory.root.resolve(),
        root_kind=inventory.root_kind,
        root_role=str(data.get("root_role") or ""),
        product_source_root=_resolve_frontmatter_path(product_source_root_text, inventory.root),
        product_source_root_text=product_source_root_text,
        load_errors=tuple(inventory.manifest_errors),
    )


def _target_root_posture(target_root: Path) -> MirrorRootPosture:
    try:
        return _root_posture_from_inventory(load_inventory(target_root))
    except RootLoadError as exc:
        return MirrorRootPosture(
            root=target_root.resolve(strict=False),
            root_kind="unreadable",
            root_role="",
            product_source_root=None,
            product_source_root_text="",
            load_errors=(str(exc),),
        )


def _root_posture_findings(label: str, posture: MirrorRootPosture) -> list[Finding]:
    findings = [
        Finding(
            "info",
            f"mirror-{label}-role",
            (
                f"{label} root kind: {posture.root_kind}; root_role={posture.root_role or '<none>'}; "
                f"product_source_root={_format_optional_path(posture.product_source_root)}; "
                f"is_product_source_root={posture.is_product_source_root}"
            ),
        )
    ]
    findings.extend(Finding("warn", f"mirror-{label}-role-load-warning", error) for error in posture.load_errors)
    return findings


def _mirror_direction_guard_findings(
    source_posture: MirrorRootPosture,
    target_posture: MirrorRootPosture,
    request: MirrorRequest,
) -> list[Finding]:
    findings: list[Finding] = []
    target_is_configured_product = bool(
        source_posture.product_source_root and _same_resolved_path(target_posture.root, source_posture.product_source_root)
    )
    target_is_product_source_root = target_posture.is_product_source_root or target_is_configured_product
    if not source_posture.is_product_source_root:
        findings.append(
            Finding(
                "error",
                "mirror-direction-refused",
                f"source root kind is {source_posture.root_kind}; mirror source must be the product_source_root",
            )
        )
        if source_posture.product_source_root:
            findings.append(_source_root_selection_suggestion(source_posture, target_posture, request, target_is_product_source_root))

    if target_is_product_source_root and not request.allow_product_target:
        findings.append(
            Finding(
                "error",
                "mirror-direction-refused",
                "--target-root resolves to a product_source_root; reverse demo-to-product or product-target mirrors are refused by default",
            )
        )
    elif target_is_product_source_root:
        findings.append(
            Finding(
                "warn",
                "mirror-product-target-override",
                "--allow-product-target is set; product_source_root target protection was explicitly bypassed after external review",
            )
        )
    return findings


def _source_root_selection_suggestion(
    source_posture: MirrorRootPosture,
    target_posture: MirrorRootPosture,
    request: MirrorRequest,
    target_is_product_source_root: bool,
) -> Finding:
    product_root = source_posture.product_source_root
    assert product_root is not None
    allow_product_target = request.allow_product_target or target_is_product_source_root
    dry_run_command = _format_mirror_command(product_root, target_posture.root, request.paths, "--dry-run", allow_product_target)
    apply_command = _format_mirror_command(product_root, target_posture.root, request.paths, "--apply", allow_product_target)
    return Finding(
        "info",
        "mirror-source-root-selection-suggestion",
        (
            "rerun mirror from configured product_source_root instead of the operating root: "
            f"dry_run_command={dry_run_command}; apply_command={apply_command}"
        ),
    )


def _format_mirror_command(product_root: Path, target_root: Path, paths: tuple[str, ...], mode: str, allow_product_target: bool) -> str:
    args = ["mylittleharness", "--root", str(product_root), "mirror", mode, "--target-root", str(target_root)]
    for rel_path in paths:
        args.extend(("--path", rel_path))
    if allow_product_target:
        args.append("--allow-product-target")
    return " ".join(_quote_cli_arg(arg) for arg in args)


def _quote_cli_arg(value: str) -> str:
    text = str(value)
    if not text:
        return '""'
    if re.search(r"\s", text):
        return f'"{text.replace(chr(34), chr(92) + chr(34))}"'
    return text


def _resolve_frontmatter_path(value: str, base_root: Path) -> Path | None:
    if not value:
        return None
    normalized = value.replace("\\\\", "\\").strip()
    if not normalized:
        return None
    try:
        candidate = Path(normalized).expanduser()
        if not candidate.is_absolute():
            candidate = base_root / candidate
        return candidate.resolve(strict=False)
    except (OSError, RuntimeError):
        return None


def _same_resolved_path(left: Path, right: Path) -> bool:
    try:
        left_resolved = left.expanduser().resolve(strict=False)
        right_resolved = right.expanduser().resolve(strict=False)
        return str(left_resolved).casefold() == str(right_resolved).casefold()
    except (OSError, RuntimeError):
        return str(left).replace("/", "\\").rstrip("\\").casefold() == str(right).replace("/", "\\").rstrip("\\").casefold()


def _format_optional_path(path: Path | None) -> str:
    return str(path) if path else "<none>"


def _mirror_dependency_closure_findings(source_root: Path, target_root: Path, plan: list[MirrorFilePlan]) -> list[Finding]:
    declared_paths = frozenset(file_plan.rel_path for file_plan in plan)
    seed_paths = tuple(rel_path for rel_path in declared_paths if _is_python_dependency_seed(rel_path))
    if not seed_paths:
        return []

    closure = _local_python_dependency_closure(source_root, seed_paths)
    dependency_paths = sorted(path for path in closure.rel_paths if path not in declared_paths)
    findings = list(closure.findings)
    missing_count = 0
    drift_count = 0
    equal_count = 0
    unusable_count = 0
    source_missing_count = 0
    gap_paths: list[str] = []

    for rel_path in dependency_paths:
        rel_posix = PurePosixPath(rel_path)
        source_path = source_root.joinpath(*rel_posix.parts)
        target_path = target_root.joinpath(*rel_posix.parts)
        required_by = _format_required_by(closure.importers.get(rel_path, frozenset()))
        if not source_path.exists() or not source_path.is_file() or source_path.is_symlink():
            source_missing_count += 1
            gap_paths.append(rel_path)
            findings.append(
                Finding(
                    "warn",
                    "mirror-dependency-source-missing",
                    f"local dependency could not be read from source; required_by={required_by}",
                    rel_path,
                )
            )
            continue
        source_sha256 = _sha256(source_path)
        if not target_path.exists():
            missing_count += 1
            gap_paths.append(rel_path)
            findings.append(
                Finding(
                    "warn",
                    "mirror-dependency-target-missing",
                    f"target is missing local dependency required by declared mirror paths; required_by={required_by}; source_sha256={source_sha256}",
                    rel_path,
                )
            )
            continue
        if not target_path.is_file() or target_path.is_symlink():
            unusable_count += 1
            gap_paths.append(rel_path)
            findings.append(
                Finding(
                    "warn",
                    "mirror-dependency-target-unusable",
                    f"target dependency is not a regular file; required_by={required_by}",
                    rel_path,
                )
            )
            continue
        target_sha256 = _sha256(target_path)
        if target_sha256 != source_sha256:
            drift_count += 1
            gap_paths.append(rel_path)
            findings.append(
                Finding(
                    "warn",
                    "mirror-dependency-drift",
                    f"target dependency differs from source; required_by={required_by}; source_sha256={source_sha256}; target_sha256={target_sha256}",
                    rel_path,
                )
            )
        else:
            equal_count += 1

    if missing_count or drift_count or unusable_count or source_missing_count:
        findings.append(
            Finding(
                "warn",
                "mirror-dependency-declare-suggestion",
                _dependency_declare_suggestion(gap_paths),
            )
        )
        findings.append(
            Finding(
                "warn",
                "mirror-dependency-closure-gap",
                "local dependency closure has target gaps; "
                f"dependencies={len(dependency_paths)} equal={equal_count} missing={missing_count} drift={drift_count} "
                f"unusable={unusable_count} source_missing={source_missing_count}; declare required dependencies with --path or sync the target before relying on mirrored tests",
            )
        )
    elif dependency_paths:
        findings.append(
            Finding(
                "info",
                "mirror-dependency-closure-ok",
                f"local dependency closure matches target for {equal_count} undeclared dependency files",
            )
        )
    return findings


def _dependency_declare_suggestion(rel_paths: list[str]) -> str:
    ordered = sorted(dict.fromkeys(rel_paths))
    rendered_paths = ordered[:12]
    rendered = " ".join(f"--path {path}" for path in rendered_paths)
    suffix = f"; +{len(ordered) - len(rendered_paths)} more" if len(ordered) > len(rendered_paths) else ""
    return f"declare or resync undeclared local dependencies explicitly: {rendered}{suffix}"


def _is_python_dependency_seed(rel_path: str) -> bool:
    return rel_path.endswith(".py") and (rel_path.startswith("tests/") or rel_path.startswith("src/mylittleharness/"))


def _local_python_dependency_closure(source_root: Path, seed_paths: tuple[str, ...]) -> MirrorDependencyClosure:
    pending = list(seed_paths)
    scanned: set[str] = set()
    dependencies: set[str] = set()
    importers: dict[str, set[str]] = {}
    findings: list[Finding] = []

    while pending:
        rel_path = pending.pop()
        if rel_path in scanned:
            continue
        scanned.add(rel_path)
        source_path = source_root.joinpath(*PurePosixPath(rel_path).parts)
        imported_paths, parse_findings = _local_python_imports(source_root, rel_path, source_path)
        findings.extend(parse_findings)
        for imported_path in imported_paths:
            importers.setdefault(imported_path, set()).add(rel_path)
            if imported_path not in dependencies:
                dependencies.add(imported_path)
                pending.append(imported_path)

    frozen_importers = {rel_path: frozenset(values) for rel_path, values in importers.items()}
    return MirrorDependencyClosure(frozenset(dependencies), frozen_importers, tuple(findings))


def _local_python_imports(source_root: Path, rel_path: str, source_path: Path) -> tuple[set[str], list[Finding]]:
    if not source_path.exists() or not source_path.is_file() or source_path.is_symlink():
        return set(), []
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=rel_path)
    except (OSError, UnicodeError, SyntaxError) as exc:
        return set(), [Finding("warn", "mirror-dependency-parse-skipped", f"could not parse local imports: {exc}", rel_path)]

    module_name, is_package = _module_name_for_rel_path(rel_path)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                resolved = _module_source_rel_path(source_root, alias.name)
                if resolved:
                    imports.add(resolved)
        elif isinstance(node, ast.ImportFrom):
            module_name_candidates = _import_from_module_candidates(module_name, is_package, node)
            for candidate in module_name_candidates:
                resolved = _module_source_rel_path(source_root, candidate)
                if resolved:
                    imports.add(resolved)
    return imports, []


def _module_name_for_rel_path(rel_path: str) -> tuple[str | None, bool]:
    posix_path = PurePosixPath(rel_path)
    parts = posix_path.parts
    if len(parts) < 2 or parts[0] != "src" or parts[-1] == "":
        return None, False
    path_without_suffix = posix_path.with_suffix("")
    module_parts = path_without_suffix.parts[1:]
    is_package = module_parts[-1] == "__init__"
    if is_package:
        module_parts = module_parts[:-1]
    return ".".join(module_parts), is_package


def _import_from_module_candidates(current_module: str | None, current_is_package: bool, node: ast.ImportFrom) -> tuple[str, ...]:
    if node.module == "__future__":
        return ()
    base_module: str | None
    if node.level:
        base_module = _resolve_relative_module(current_module, current_is_package, node.module, node.level)
    else:
        base_module = node.module
    if not base_module:
        return ()

    candidates = [base_module]
    if node.names and not any(alias.name == "*" for alias in node.names):
        candidates.extend(f"{base_module}.{alias.name}" for alias in node.names)
    return tuple(candidates)


def _resolve_relative_module(current_module: str | None, current_is_package: bool, imported_module: str | None, level: int) -> str | None:
    if not current_module:
        return None
    current_parts = current_module.split(".")
    package_parts = current_parts if current_is_package else current_parts[:-1]
    if level > len(package_parts) + 1:
        return None
    base_parts = package_parts[: len(package_parts) - level + 1]
    if imported_module:
        base_parts.extend(imported_module.split("."))
    if not base_parts:
        return None
    return ".".join(base_parts)


def _module_source_rel_path(source_root: Path, module_name: str) -> str | None:
    if not module_name.startswith("mylittleharness"):
        return None
    module_parts = module_name.split(".")
    file_path = source_root.joinpath("src", *module_parts).with_suffix(".py")
    if file_path.exists() and file_path.is_file() and not file_path.is_symlink():
        return PurePosixPath("src", *module_parts).with_suffix(".py").as_posix()
    package_path = source_root.joinpath("src", *module_parts, "__init__.py")
    if package_path.exists() and package_path.is_file() and not package_path.is_symlink():
        return PurePosixPath("src", *module_parts, "__init__.py").as_posix()
    return None


def _format_required_by(importers: frozenset[str]) -> str:
    if not importers:
        return "unknown"
    ordered = sorted(importers)
    rendered = ", ".join(ordered[:3])
    if len(ordered) > 3:
        rendered = f"{rendered}, +{len(ordered) - 3} more"
    return rendered


def _normalize_rel_path(raw_path: str) -> PurePosixPath | Finding:
    normalized = raw_path.replace("\\", "/").strip()
    if not normalized:
        return Finding("error", "mirror-refused", "declared mirror path cannot be empty")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        return Finding("error", "mirror-refused", f"declared mirror path must be root-relative: {raw_path}")
    rel_path = PurePosixPath(normalized)
    if any(part in {"", ".", ".."} for part in rel_path.parts):
        return Finding("error", "mirror-refused", f"declared mirror path must not contain empty, '.', or '..' segments: {raw_path}")
    if rel_path.parts and rel_path.parts[0] == ".git":
        return Finding("error", "mirror-refused", f"declared mirror path must not target Git metadata: {raw_path}")
    return rel_path


def _path_validation_errors(source_root: Path, target_root: Path, rel_path: str, source_path: Path, target_path: Path) -> list[Finding]:
    errors: list[Finding] = []
    if not source_path.resolve(strict=False).is_relative_to(source_root):
        errors.append(Finding("error", "mirror-refused", "source path escapes the source root", rel_path))
    if not target_path.resolve(strict=False).is_relative_to(target_root):
        errors.append(Finding("error", "mirror-refused", "target path escapes the target root", rel_path))
    if not source_path.exists():
        errors.append(Finding("error", "mirror-source-missing", "declared source file is missing", rel_path))
    elif not source_path.is_file() or source_path.is_symlink():
        errors.append(Finding("error", "mirror-refused", "declared source must be a regular file, not a directory or symlink", rel_path))
    if target_path.exists() and (not target_path.is_file() or target_path.is_symlink()):
        errors.append(Finding("error", "mirror-refused", "target path must be absent or a regular file", rel_path))
    errors.extend(_parent_segment_errors(source_root, source_path, rel_path, "source"))
    errors.extend(_parent_segment_errors(target_root, target_path, rel_path, "target"))
    if target_path.with_name(f".{target_path.name}.mylittleharness-mirror.tmp").exists():
        errors.append(Finding("error", "mirror-refused", "temporary mirror path already exists", rel_path))
    if target_path.with_name(f".{target_path.name}.mylittleharness-mirror.backup").exists():
        errors.append(Finding("error", "mirror-refused", "temporary mirror backup path already exists", rel_path))
    return errors


def _parent_segment_errors(root: Path, path: Path, rel_path: str, label: str) -> list[Finding]:
    errors: list[Finding] = []
    current = root
    try:
        relative_parts = path.relative_to(root).parts[:-1]
    except ValueError:
        return errors
    for part in relative_parts:
        current = current / part
        if current.exists() and current.is_symlink():
            errors.append(Finding("error", "mirror-refused", f"{label} parent contains a symlink segment", rel_path))
            break
        if current.exists() and not current.is_dir():
            errors.append(Finding("error", "mirror-refused", f"{label} parent contains a non-directory segment", rel_path))
            break
    return errors


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_bytes_atomic(data: bytes, target_path: Path) -> None:
    tmp_path = target_path.with_name(f".{target_path.name}.mylittleharness-mirror.tmp")
    backup_path = target_path.with_name(f".{target_path.name}.mylittleharness-mirror.backup")
    had_original = target_path.exists()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        tmp_path.write_bytes(data)
        if had_original:
            target_path.replace(backup_path)
        tmp_path.replace(target_path)
    except OSError:
        if tmp_path.exists():
            tmp_path.unlink()
        if had_original and backup_path.exists() and not target_path.exists():
            backup_path.replace(target_path)
        raise
    finally:
        if backup_path.exists():
            backup_path.unlink()


def _mirror_summary_findings(plan: list[MirrorFilePlan], copied: bool, copied_count: int = 0) -> list[Finding]:
    equal_count = sum(1 for item in plan if item.action == "equal")
    copy_count = sum(1 for item in plan if item.action == "copy")
    if copied:
        message = f"declared_paths={len(plan)} copied={copied_count} unchanged={equal_count}"
    else:
        message = f"declared_paths={len(plan)} already_equal={equal_count} would_copy={copy_count}"
    return [Finding("info", "mirror-summary", message)]
