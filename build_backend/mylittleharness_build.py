from __future__ import annotations

import base64
import csv
import hashlib
import io
import tomllib
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def get_requires_for_build_wheel(config_settings: object | None = None) -> list[str]:
    return []


def prepare_metadata_for_build_wheel(metadata_directory: str, config_settings: object | None = None) -> str:
    dist_info = _dist_info_name()
    target = Path(metadata_directory) / dist_info
    target.mkdir(parents=True, exist_ok=True)
    _write_metadata_files(target)
    return dist_info


def build_wheel(
    wheel_directory: str,
    config_settings: object | None = None,
    metadata_directory: str | None = None,
) -> str:
    project = _project_metadata()
    name = _normalized_name(project["name"])
    version = str(project["version"])
    wheel_name = f"{name}-{version}-py3-none-any.whl"
    wheel_path = Path(wheel_directory) / wheel_name
    dist_info = _dist_info_name()
    records: list[tuple[str, bytes]] = []

    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as wheel:
        for path in sorted((ROOT / "src/mylittleharness").rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            rel_path = path.relative_to(ROOT / "src").as_posix()
            data = path.read_bytes()
            wheel.writestr(rel_path, data)
            records.append((rel_path, data))
        for rel_path, data in _metadata_file_payloads(dist_info):
            wheel.writestr(rel_path, data)
            records.append((rel_path, data))
        record_path = f"{dist_info}/RECORD"
        wheel.writestr(record_path, _record_payload(records, record_path))
    return wheel_name


def _project_metadata() -> dict[str, object]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    if not isinstance(project, dict):
        raise ValueError("pyproject.toml [project] table is required")
    return project


def _dist_info_name() -> str:
    project = _project_metadata()
    return f"{_normalized_name(project['name'])}-{project['version']}.dist-info"


def _write_metadata_files(target: Path) -> None:
    for rel_path, data in _metadata_file_payloads(target.name):
        (target.parent / rel_path).write_bytes(data)


def _metadata_file_payloads(dist_info: str) -> list[tuple[str, bytes]]:
    project = _project_metadata()
    metadata = "\n".join(
        [
            "Metadata-Version: 2.1",
            f"Name: {project['name']}",
            f"Version: {project['version']}",
            f"Summary: {project.get('description', '')}",
            f"Requires-Python: {project.get('requires-python', '>=3.11')}",
            "",
        ]
    ).encode("utf-8")
    wheel = "\n".join(
        [
            "Wheel-Version: 1.0",
            "Generator: mylittleharness-build",
            "Root-Is-Purelib: true",
            "Tag: py3-none-any",
            "",
        ]
    ).encode("utf-8")
    entry_points = "\n".join(
        [
            "[console_scripts]",
            "mylittleharness = mylittleharness.cli:main",
            "",
        ]
    ).encode("utf-8")
    top_level = b"mylittleharness\n"
    return [
        (f"{dist_info}/METADATA", metadata),
        (f"{dist_info}/WHEEL", wheel),
        (f"{dist_info}/entry_points.txt", entry_points),
        (f"{dist_info}/top_level.txt", top_level),
    ]


def _record_payload(records: list[tuple[str, bytes]], record_path: str) -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    for rel_path, data in records:
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")
        writer.writerow([rel_path, f"sha256={digest}", str(len(data))])
    writer.writerow([record_path, "", ""])
    return output.getvalue()


def _normalized_name(name: object) -> str:
    return str(name).replace("-", "_")
