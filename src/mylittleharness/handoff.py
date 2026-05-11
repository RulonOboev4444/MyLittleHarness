from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .atomic_files import AtomicFileWrite, FileTransactionError, apply_file_transaction
from .approval_packets import APPROVAL_PACKET_SCHEMA, APPROVAL_PACKETS_DIR_REL
from .claims import WORK_CLAIM_SCHEMA, WORK_CLAIMS_DIR_REL
from .inventory import Inventory
from .models import Finding


HANDOFF_PACKET_SCHEMA = "mylittleharness.handoff-packet.v1"
HANDOFF_PACKETS_DIR_REL = "project/verification/handoffs"
ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
HANDOFF_PACKET_REQUIRED_SCALARS = ("handoff_id", "worker_id", "role_id", "execution_slice")
HANDOFF_PACKET_REQUIRED_LISTS = ("allowed_routes", "write_scope", "stop_conditions", "required_outputs")
HANDOFF_PACKET_REF_LISTS = ("evidence_refs", "approval_packet_refs", "claim_refs")


@dataclass(frozen=True)
class HandoffPacketRequest:
    handoff_id: str
    worker_id: str
    role_id: str
    execution_slice: str
    worktree_id: str
    branch: str
    base_revision: str
    head_revision: str
    allowed_routes: tuple[str, ...]
    write_scope: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    context_budget: str
    required_outputs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    approval_packet_refs: tuple[str, ...]
    claim_refs: tuple[str, ...]


def make_handoff_packet_request(args: object) -> HandoffPacketRequest:
    return HandoffPacketRequest(
        handoff_id=str(getattr(args, "handoff_id", "") or "").strip(),
        worker_id=str(getattr(args, "worker_id", "") or "").strip(),
        role_id=str(getattr(args, "role_id", "") or "").strip(),
        execution_slice=str(getattr(args, "execution_slice", "") or "").strip(),
        worktree_id=str(getattr(args, "worktree_id", "") or "").strip(),
        branch=str(getattr(args, "branch", "") or "").strip(),
        base_revision=str(getattr(args, "base_revision", "") or "").strip(),
        head_revision=str(getattr(args, "head_revision", "") or "").strip(),
        allowed_routes=_tuple_values(getattr(args, "allowed_routes", ()), path_like=False),
        write_scope=_tuple_values(getattr(args, "write_scope", ())),
        stop_conditions=_tuple_values(getattr(args, "stop_conditions", ()), path_like=False),
        context_budget=str(getattr(args, "context_budget", "") or "").strip() or "compact packet; target about 400 tokens; no hidden context",
        required_outputs=_tuple_values(getattr(args, "required_outputs", ()), path_like=False),
        evidence_refs=_tuple_values(getattr(args, "evidence_refs", ())),
        approval_packet_refs=_tuple_values(getattr(args, "approval_packet_refs", ())),
        claim_refs=_tuple_values(getattr(args, "claim_refs", ())),
    )


def handoff_packet_dry_run_findings(inventory: Inventory, request: HandoffPacketRequest) -> list[Finding]:
    findings = [
        Finding("info", "handoff-packet-dry-run", "handoff packet proposal only; no files were written"),
        Finding("info", "handoff-packet-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    request_findings = _request_findings(inventory, request, apply=False)
    findings.extend(request_findings)
    if any(finding.severity in {"warn", "error"} for finding in request_findings):
        findings.append(Finding("info", "handoff-packet-validation-posture", "dry-run refused before apply; fix explicit handoff fields before writing packet evidence"))
        findings.extend(_boundary_findings())
        return findings

    text = _packet_json(_packet_data(request))
    rel_path = _packet_rel_path(request.handoff_id)
    findings.append(Finding("info", "handoff-packet-target", f"would write handoff packet: {rel_path}", rel_path))
    findings.append(
        Finding(
            "info",
            "handoff-packet-route-write",
            (
                f"would create route {rel_path}; before_hash=missing; after_hash={_short_hash(text)}; "
                f"before_bytes=missing; after_bytes={len(text.encode('utf-8'))}; "
                "source-bound write evidence is independent of Git tracking"
            ),
            rel_path,
        )
    )
    findings.extend(_packet_shape_findings(request))
    findings.extend(_boundary_findings())
    return findings


def handoff_packet_apply_findings(inventory: Inventory, request: HandoffPacketRequest) -> list[Finding]:
    findings = [
        Finding("info", "handoff-packet-apply", "handoff packet apply started"),
        Finding("info", "handoff-packet-root-posture", f"root kind: {inventory.root_kind}"),
    ]
    request_findings = _request_findings(inventory, request, apply=True)
    findings.extend(request_findings)
    if any(finding.severity == "error" for finding in request_findings):
        findings.append(Finding("info", "handoff-packet-apply-refused", "handoff packet apply refused before writing packet evidence"))
        findings.extend(_boundary_findings())
        return findings

    rel_path = _packet_rel_path(request.handoff_id)
    target = inventory.root / rel_path
    text = _packet_json(_packet_data(request))
    try:
        cleanup_warnings = apply_file_transaction(
            (
                AtomicFileWrite(
                    target_path=target,
                    tmp_path=target.with_name(f".{target.name}.tmp"),
                    text=text,
                    backup_path=target.with_name(f".{target.name}.bak"),
                ),
            )
        )
    except FileTransactionError as exc:
        findings.append(Finding("error", "handoff-packet-refused", f"failed to write handoff packet before apply completed: {exc}", rel_path))
        findings.extend(_boundary_findings())
        return findings

    findings.append(Finding("info", "handoff-packet-written", f"created handoff packet: {rel_path}", rel_path))
    findings.append(
        Finding(
            "info",
            "handoff-packet-route-write",
            (
                f"created route {rel_path}; before_hash=missing; after_hash={_short_hash(text)}; "
                f"before_bytes=missing; after_bytes={len(text.encode('utf-8'))}; "
                "source-bound write evidence is independent of Git tracking"
            ),
            rel_path,
        )
    )
    for warning in cleanup_warnings:
        findings.append(Finding("warn", "handoff-packet-backup-cleanup", warning, rel_path))
    findings.extend(_packet_shape_findings(request))
    findings.extend(_boundary_findings())
    return findings


def handoff_packet_status_findings(inventory: Inventory, code_prefix: str = "handoff-packet-status") -> list[Finding]:
    findings: list[Finding] = []
    if inventory.root_kind != "live_operating_root":
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-non-authority",
                f"handoff packet diagnostics are live-root only; root kind is {inventory.root_kind}",
                HANDOFF_PACKETS_DIR_REL,
            )
        )
        findings.extend(_boundary_findings(code_prefix))
        return findings

    directory = inventory.root / HANDOFF_PACKETS_DIR_REL
    if not directory.exists() or not directory.is_dir():
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-records",
                f"no handoff packet records found at {HANDOFF_PACKETS_DIR_REL}/*.json",
                HANDOFF_PACKETS_DIR_REL,
            )
        )
        findings.extend(_boundary_findings(code_prefix))
        return findings

    for path in sorted(directory.glob("*.json")):
        rel_path = _to_rel_path(inventory.root, path)
        if path.is_symlink() or not path.is_file():
            findings.append(Finding("warn", f"{code_prefix}-malformed", "handoff packet record path is not a regular file", rel_path))
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            findings.append(Finding("warn", f"{code_prefix}-malformed", f"handoff packet record could not be read: {exc}", rel_path))
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            findings.append(Finding("warn", f"{code_prefix}-malformed", f"handoff packet record could not be read as JSON: {exc}", rel_path))
            continue
        if not isinstance(data, dict):
            findings.append(Finding("warn", f"{code_prefix}-malformed", "handoff packet JSON root must be an object", rel_path))
            continue
        findings.extend(_handoff_packet_metadata_findings(data, rel_path, code_prefix))
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-packet",
                (
                    f"handoff_id={str(data.get('handoff_id') or Path(rel_path).stem)}; "
                    f"worker_id={str(data.get('worker_id') or '<missing>')}; "
                    f"evidence_refs={len(_json_list(data.get('evidence_refs')))}; "
                    f"approval_packet_refs={len(_json_list(data.get('approval_packet_refs')))}; "
                    f"claim_refs={len(_json_list(data.get('claim_refs')))}; "
                    f"fingerprint={_file_fingerprint(path)}; read-only handoff posture"
                ),
                rel_path,
            )
        )
        findings.extend(_handoff_packet_ref_findings(inventory.root, data, rel_path, code_prefix))

    if not any(finding.severity == "warn" for finding in findings):
        findings.append(
            Finding(
                "info",
                f"{code_prefix}-clean",
                "no malformed handoff packets or degraded handoff refs were found",
                HANDOFF_PACKETS_DIR_REL,
            )
        )
    findings.extend(_boundary_findings(code_prefix))
    return findings


def _request_findings(inventory: Inventory, request: HandoffPacketRequest, *, apply: bool) -> list[Finding]:
    severity = "error" if apply else "warn"
    findings: list[Finding] = []
    if inventory.root_kind != "live_operating_root":
        findings.append(Finding(severity, "handoff-packet-refused", f"target root kind is {inventory.root_kind}; handoff packet writes require a live operating root"))
    for field, value in (
        ("--handoff-id", request.handoff_id),
        ("--worker-id", request.worker_id),
        ("--role-id", request.role_id),
        ("--execution-slice", request.execution_slice),
    ):
        if not value:
            findings.append(Finding("error", "handoff-packet-refused", f"{field} is required"))
    if request.handoff_id and not ID_RE.match(request.handoff_id):
        findings.append(Finding("error", "handoff-packet-refused", "--handoff-id may contain only letters, digits, dot, underscore, or dash"))
    if not request.allowed_routes:
        findings.append(Finding("error", "handoff-packet-refused", "--allowed-route must be supplied at least once"))
    if not request.write_scope:
        findings.append(Finding("error", "handoff-packet-refused", "--write-scope must be supplied at least once"))
    if not request.stop_conditions:
        findings.append(Finding("error", "handoff-packet-refused", "--stop-condition must be supplied at least once"))
    if not request.required_outputs:
        findings.append(Finding("error", "handoff-packet-refused", "--required-output must be supplied at least once"))
    for flag, values in (
        ("--write-scope", request.write_scope),
        ("--evidence-ref", request.evidence_refs),
        ("--approval-packet-ref", request.approval_packet_refs),
        ("--claim-ref", request.claim_refs),
    ):
        for rel_path in values:
            conflict = _root_relative_path_conflict(rel_path)
            if conflict:
                findings.append(Finding("error", "handoff-packet-refused", f"{flag} {conflict}", rel_path))
    if request.handoff_id:
        rel_path = _packet_rel_path(request.handoff_id)
        target = inventory.root / rel_path
        conflict = _root_relative_path_conflict(rel_path)
        if conflict:
            findings.append(Finding("error", "handoff-packet-refused", f"handoff target {conflict}", rel_path))
        if target.exists():
            findings.append(Finding(severity, "handoff-packet-refused", "handoff packet already exists; choose a new --handoff-id", rel_path))
    return findings


def _handoff_packet_metadata_findings(data: dict[str, object], rel_path: str, code_prefix: str) -> list[Finding]:
    findings: list[Finding] = []
    if data.get("schema") != HANDOFF_PACKET_SCHEMA:
        findings.append(Finding("warn", f"{code_prefix}-malformed", f"handoff packet schema should be {HANDOFF_PACKET_SCHEMA}", rel_path))
    if data.get("record_type") != "handoff-packet":
        findings.append(Finding("warn", f"{code_prefix}-malformed", "handoff packet record_type should be handoff-packet", rel_path))
    for field in HANDOFF_PACKET_REQUIRED_SCALARS:
        if not str(data.get(field) or "").strip():
            findings.append(Finding("warn", f"{code_prefix}-malformed", f"handoff packet {field} is required", rel_path))
    handoff_id = str(data.get("handoff_id") or "").strip()
    if handoff_id and not ID_RE.match(handoff_id):
        findings.append(Finding("warn", f"{code_prefix}-malformed", "handoff packet handoff_id may contain only letters, digits, dot, underscore, or dash", rel_path))
    for field in (*HANDOFF_PACKET_REQUIRED_LISTS, *HANDOFF_PACKET_REF_LISTS):
        value = data.get(field)
        if value not in (None, "") and not isinstance(value, list):
            findings.append(Finding("warn", f"{code_prefix}-malformed", f"handoff packet {field} must be a list of strings", rel_path))
            continue
        if field in HANDOFF_PACKET_REQUIRED_LISTS and not _json_list(value):
            findings.append(Finding("warn", f"{code_prefix}-malformed", f"handoff packet {field} must contain at least one value", rel_path))
    for rel in _json_list(data.get("write_scope")):
        conflict = _root_relative_path_conflict(rel)
        if conflict:
            findings.append(Finding("warn", f"{code_prefix}-malformed", f"handoff packet write_scope {conflict}", rel_path))
    return findings


def _handoff_packet_ref_findings(root: Path, data: dict[str, object], rel_path: str, code_prefix: str) -> list[Finding]:
    findings: list[Finding] = []
    for ref in _json_list(data.get("evidence_refs")):
        findings.extend(_generic_ref_findings(root, ref, rel_path, code_prefix, "evidence"))
    for ref in _json_list(data.get("approval_packet_refs")):
        findings.extend(
            _typed_json_ref_findings(
                root,
                ref,
                rel_path,
                code_prefix,
                label="approval-packet",
                directory_rel=APPROVAL_PACKETS_DIR_REL,
                schema=APPROVAL_PACKET_SCHEMA,
                record_type="approval-packet",
            )
        )
    for ref in _json_list(data.get("claim_refs")):
        findings.extend(
            _typed_json_ref_findings(
                root,
                ref,
                rel_path,
                code_prefix,
                label="work-claim",
                directory_rel=WORK_CLAIMS_DIR_REL,
                schema=WORK_CLAIM_SCHEMA,
                record_type="work-claim",
            )
        )
    return findings


def _generic_ref_findings(root: Path, ref: str, rel_path: str, code_prefix: str, label: str) -> list[Finding]:
    target, degraded = _ref_target(root, ref, rel_path, code_prefix, label)
    if degraded:
        return degraded
    try:
        target.read_bytes()
    except OSError as exc:
        return [Finding("warn", f"{code_prefix}-{label}-ref-unreadable", f"handoff packet {label} ref could not be read: {exc}", ref)]
    return [
        Finding(
            "info",
            f"{code_prefix}-{label}-ref",
            f"handoff packet {label} ref is readable: {ref}; fingerprint={_file_fingerprint(target)}",
            ref,
        )
    ]


def _typed_json_ref_findings(
    root: Path,
    ref: str,
    rel_path: str,
    code_prefix: str,
    *,
    label: str,
    directory_rel: str,
    schema: str,
    record_type: str,
) -> list[Finding]:
    findings: list[Finding] = []
    normalized = _normalize_ref(ref)
    if not normalized.startswith(f"{directory_rel}/") or not normalized.endswith(".json"):
        findings.append(
            Finding(
                "warn",
                f"{code_prefix}-{label}-ref-invalid",
                f"handoff packet {label} ref should point under {directory_rel}/*.json",
                rel_path,
            )
        )
    target, degraded = _ref_target(root, normalized, rel_path, code_prefix, label)
    if degraded:
        return [*findings, *degraded]
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        return [*findings, Finding("warn", f"{code_prefix}-{label}-ref-unreadable", f"handoff packet {label} ref could not be read: {exc}", normalized)]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return [*findings, Finding("warn", f"{code_prefix}-{label}-ref-malformed", f"handoff packet {label} ref is not valid JSON: {exc}", normalized)]
    if not isinstance(data, dict):
        return [*findings, Finding("warn", f"{code_prefix}-{label}-ref-malformed", f"handoff packet {label} ref JSON root must be an object", normalized)]
    if data.get("schema") != schema or data.get("record_type") != record_type:
        findings.append(
            Finding(
                "warn",
                f"{code_prefix}-{label}-ref-malformed",
                f"handoff packet {label} ref must be a {schema} {record_type} record",
                normalized,
            )
        )
    findings.append(
        Finding(
            "info",
            f"{code_prefix}-{label}-ref",
            f"handoff packet {label} ref is readable: {normalized}; fingerprint={_file_fingerprint(target)}",
            normalized,
        )
    )
    return findings


def _ref_target(root: Path, ref: str, rel_path: str, code_prefix: str, label: str) -> tuple[Path, list[Finding]]:
    normalized = _normalize_ref(ref)
    conflict = _root_relative_path_conflict(normalized)
    if conflict:
        return root / normalized, [Finding("warn", f"{code_prefix}-{label}-ref-invalid", f"handoff packet {label} ref {conflict}", rel_path)]
    target = root / normalized
    if not target.exists():
        return target, [Finding("warn", f"{code_prefix}-{label}-ref-missing", f"handoff packet {label} ref is missing: {normalized}", normalized)]
    if target.is_symlink() or not target.is_file():
        return target, [Finding("warn", f"{code_prefix}-{label}-ref-invalid", f"handoff packet {label} ref is not a regular file: {normalized}", normalized)]
    return target, []


def _packet_data(request: HandoffPacketRequest) -> dict[str, object]:
    return {
        "schema": HANDOFF_PACKET_SCHEMA,
        "record_type": "handoff-packet",
        "handoff_id": request.handoff_id,
        "worker_id": request.worker_id,
        "role_id": request.role_id,
        "execution_slice": request.execution_slice,
        "worktree_id": request.worktree_id,
        "branch": request.branch,
        "base_revision": request.base_revision,
        "head_revision": request.head_revision,
        "allowed_routes": list(request.allowed_routes),
        "write_scope": list(request.write_scope),
        "stop_conditions": list(request.stop_conditions),
        "context_budget": request.context_budget,
        "required_outputs": list(request.required_outputs),
        "evidence_refs": list(request.evidence_refs),
        "approval_packet_refs": list(request.approval_packet_refs),
        "claim_refs": list(request.claim_refs),
        "created_at_utc": _utc_timestamp(),
        "authority_boundary": "handoff packets are context and coordination evidence only; they do not grant lifecycle, archive, Git, or release authority",
    }


def _packet_shape_findings(request: HandoffPacketRequest) -> list[Finding]:
    return [
        Finding(
            "info",
            "handoff-packet-shape",
            (
                f"allowed_routes={len(request.allowed_routes)}; write_scope={len(request.write_scope)}; "
                f"stop_conditions={len(request.stop_conditions)}; required_outputs={len(request.required_outputs)}; "
                f"claim_refs={len(request.claim_refs)}; approval_packet_refs={len(request.approval_packet_refs)}"
            ),
            _packet_rel_path(request.handoff_id),
        )
    ]


def _boundary_findings(code_prefix: str = "handoff-packet") -> list[Finding]:
    return [
        Finding(
            "info",
            f"{code_prefix}-boundary",
            "handoff packets carry allowed routes, write scope, stop conditions, context budget, required outputs, evidence refs, approval-packet refs, and claim refs without granting worker lifecycle authority",
            HANDOFF_PACKETS_DIR_REL,
        ),
        Finding(
            "info",
            f"{code_prefix}-route",
            f"handoff packets live under {HANDOFF_PACKETS_DIR_REL}/*.json as repo-visible evidence; no hidden runtime, queue, database, adapter state, or worker spawn is created",
            HANDOFF_PACKETS_DIR_REL,
        ),
    ]


def _packet_rel_path(handoff_id: str) -> str:
    return f"{HANDOFF_PACKETS_DIR_REL}/{handoff_id}.json"


def _packet_json(data: dict[str, object]) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _tuple_values(values: object, *, path_like: bool = True) -> tuple[str, ...]:
    if not values:
        return ()
    if isinstance(values, str):
        values = (values,)
    cleaned: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        cleaned.append(_normalize_ref(text) if path_like else text)
    return tuple(dict.fromkeys(cleaned))


def _json_list(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    return ()


def _root_relative_path_conflict(rel_path: str) -> str:
    normalized = _normalize_ref(rel_path)
    if not normalized:
        return "must be a non-empty root-relative path"
    if re.match(r"^[A-Za-z]:[\\/]", normalized) or normalized.startswith("/"):
        return "must be root-relative, not absolute"
    if any(part in {"..", ".", ""} for part in normalized.split("/")):
        return "must not contain parent traversal, current-directory, or empty path segments"
    return ""


def _normalize_ref(value: str) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/")


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _file_fingerprint(path: Path) -> str:
    if not path.exists():
        return "missing"
    if path.is_symlink() or not path.is_file():
        return "invalid-path"
    try:
        return f"sha256={_sha256_file(path)[:12]}"
    except OSError:
        return "unreadable"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _to_rel_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
