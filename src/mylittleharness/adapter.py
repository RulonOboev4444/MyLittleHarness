from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from . import __version__
from .inventory import Inventory, RootLoadError, load_inventory
from .models import Finding
from .projection import Projection, build_projection
from .projection_artifacts import inspect_projection_artifacts
from .projection_index import inspect_projection_index


MCP_READ_PROJECTION_TARGET = "mcp-read-projection"
MCP_PROTOCOL_VERSION = "2025-11-25"
MCP_READ_PROJECTION_TOOL = "mylittleharness.read_projection"
MCP_READ_PROJECTION_SERVER_NAME = "mylittleharness"
InventoryLoader = Callable[[Path | str], Inventory]


def mcp_read_projection_sections(inventory: Inventory) -> list[tuple[str, list[Finding]]]:
    projection = build_projection(inventory)
    return [
        ("Adapter", _adapter_findings(inventory)),
        ("Projection", _projection_findings(projection)),
        ("Sources", _source_findings(projection)),
        ("Generated Inputs", _generated_input_findings(inventory, projection)),
        ("Boundary", _boundary_findings()),
    ]


def mcp_read_projection_payload(
    inventory: Inventory,
    *,
    default_root: Path | None = None,
    requested_root: str | None = None,
) -> dict[str, object]:
    root_selection = _root_selection_payload(inventory, default_root or inventory.root, requested_root)
    sections = mcp_read_projection_sections(inventory)
    findings = [finding for _, section_findings in sections for finding in section_findings]
    return {
        "adapter": {
            "id": MCP_READ_PROJECTION_TARGET,
            "tool": MCP_READ_PROJECTION_TOOL,
            "group": "MCP",
            "role": "read/projection helper",
            "owner": "MyLittleHarness adapter boundary",
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "transport": "stdio",
        },
        "activation": mcp_read_projection_client_config(inventory),
        "root": {
            "path": str(inventory.root),
            "kind": inventory.root_kind,
        },
        "rootSelection": root_selection,
        "status": _result_for(findings),
        "sources": inventory.sources_for_report(),
        "sections": [
            {
                "name": section_name,
                "findings": [_finding_payload(finding) for finding in section_findings],
            }
            for section_name, section_findings in sections
        ],
        "boundary": {
            "readOnly": True,
            "sourceBodiesIncluded": False,
            "writesFiles": False,
            "createsAdapterState": False,
            "authorizesLifecycle": False,
            "serveCommand": mcp_read_projection_serve_command(inventory),
            "refreshPolicy": (
                "tool calls reload the selected root inventory in memory; generated projection artifacts and SQLite indexes "
                "remain optional inputs and are never refreshed by the adapter"
            ),
            "fallback": "generic CLI and repo-visible files remain sufficient without MCP tooling",
            "rootSelection": root_selection,
        },
    }


def mcp_read_projection_serve_command(inventory: Inventory) -> list[str]:
    return [
        "mylittleharness",
        "--root",
        str(inventory.root),
        "adapter",
        "--serve",
        "--target",
        MCP_READ_PROJECTION_TARGET,
        "--transport",
        "stdio",
    ]


def mcp_read_projection_client_config(inventory: Inventory) -> dict[str, object]:
    command = mcp_read_projection_serve_command(inventory)
    server = {
        "name": MCP_READ_PROJECTION_SERVER_NAME,
        "command": command[0],
        "args": command[1:],
        "transport": "stdio",
    }
    return {
        "status": "available",
        "defaultActive": True,
        "serverName": MCP_READ_PROJECTION_SERVER_NAME,
        "tool": MCP_READ_PROJECTION_TOOL,
        "recommendedUse": (
            "call before or alongside CLI/file reads when route discovery, projection context, "
            "relationship lookup, impact checks, or root selection would reduce navigation"
        ),
        "toolInputSchema": _tool_input_schema(),
        "rootSelection": {
            "defaultRoot": str(inventory.root),
            "toolArgument": "root",
            "supportsPerCallRoot": True,
            "refreshesInventoryPerCall": True,
            "boundary": (
                "per-call root selection reads another MLH-serviced root without installing scaffold, lifecycle debris, "
                "generated cache authority, or another runtime layer"
            ),
        },
        "codex": {
            "configPath": "%USERPROFILE%\\.codex\\config.toml",
            "server": server,
            "toml": _codex_mcp_toml(command),
        },
        "generic": {
            "server": server,
            "json": {"mcpServers": {MCP_READ_PROJECTION_SERVER_NAME: {"command": command[0], "args": command[1:]}}},
        },
        "boundary": {
            "writesUserConfig": False,
            "writesRepoFiles": False,
            "authorizesLifecycle": False,
            "fallback": "repo-visible files and generic CLI remain authoritative when no MCP client is active",
        },
    }


def serve_mcp_read_projection(
    inventory: Inventory,
    stdin: TextIO,
    stdout: TextIO,
    inventory_loader: InventoryLoader = load_inventory,
) -> int:
    for line in stdin:
        raw = line.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as exc:
            _write_message(stdout, _error_response(None, -32700, "Parse error", {"detail": str(exc)}))
            continue
        response = _handle_jsonrpc_message(inventory, message, inventory_loader)
        if response is not None:
            _write_message(stdout, response)
    return 0


def _adapter_findings(inventory: Inventory) -> list[Finding]:
    return [
        Finding(
            "info",
            "adapter-boundary",
            "terminal-only read-only adapter inspection; no files, generated reports, caches, databases, hooks, adapter state, or mutations are written",
        ),
        Finding(
            "info",
            "adapter-target",
            "adapter_id=mcp-read-projection; group=MCP; role=read/projection helper; owner=MyLittleHarness adapter boundary",
        ),
        Finding("info", "adapter-root", f"input root: {inventory.root}; root kind: {inventory.root_kind}"),
        Finding(
            "info",
            "adapter-output-shape",
            "sectioned terminal report and MCP stdio tool payload for adapter metadata, projection summary, source records, generated-input posture, and boundary notes",
        ),
        Finding(
            "info",
            "adapter-runtime",
            "dependency-free MCP stdio serving is explicit and foreground-only; no MCP SDK, HTTP server, network dependency, hook, IDE, browser, GitHub, CI, or task-runner runtime is required",
        ),
        Finding(
            "info",
            "adapter-mcp-helper",
            (
                "read-only MCP helper can be served with `mylittleharness --root <root> adapter --serve --target "
                "mcp-read-projection --transport stdio`; each tool call reloads the selected root inventory while generated inputs remain optional"
            ),
        ),
        Finding(
            "info",
            "adapter-default-agent-tooling",
            (
                "default agent tooling config is available for MCP server `mylittleharness` and tool "
                "`mylittleharness.read_projection`; MyLittleHarness reports the config but does not write user config"
            ),
        ),
        Finding(
            "info",
            "adapter-agent-use",
            (
                "agents should call `mylittleharness.read_projection` with optional root selection before or alongside CLI/file reads "
                "when projection context helps navigation, relationship lookup, route discovery, or impact checks"
            ),
        ),
        Finding(
            "info",
            "adapter-root-selection",
            (
                "mylittleharness.read_projection accepts optional `root` per call and reloads that MLH-serviced root read-only; "
                "omitting `root` reloads the adapter startup root"
            ),
        ),
    ]


def _projection_findings(projection: Projection) -> list[Finding]:
    summary = projection.summary
    return [
        Finding(
            "info",
            "adapter-projection-rebuild",
            (
                "in-memory projection rebuilt from inventory; storage_boundary=none; "
                f"source_set_hash={_source_set_hash(projection)}; record_set_hash={_record_set_hash(projection)}"
            ),
        ),
        Finding(
            "info",
            "adapter-projection-summary",
            (
                f"sources={summary.source_count}; present={summary.present_source_count}; "
                f"readable={summary.readable_source_count}; hashed={summary.hashed_source_count}; "
                f"missing_required={summary.missing_required_count}"
            ),
        ),
        Finding(
            "info",
            "adapter-record-counts",
            f"links={summary.link_record_count}; fan_in={summary.fan_in_record_count}",
        ),
    ]


def _source_findings(projection: Projection) -> list[Finding]:
    findings: list[Finding] = []
    for source in projection.sources:
        if source.readable:
            posture = "readable"
        elif not source.present:
            posture = "missing"
        else:
            posture = f"unreadable: {source.read_error or 'unknown read error'}"
        findings.append(
            Finding(
                "info",
                "adapter-source-record",
                (
                    f"{source.path}; role={source.role}; required={source.required}; posture={posture}; "
                    f"lines={source.line_count}; bytes={source.byte_count}; headings={source.heading_count}; "
                    f"links={source.link_count}; hash={_hash_prefix(source.content_hash)}"
                ),
                source.path,
            )
        )
    return findings


def _generated_input_findings(inventory: Inventory, projection: Projection) -> list[Finding]:
    return [
        Finding(
            "info",
            "adapter-generated-input-boundary",
            "generated projection artifacts and SQLite indexes are optional adapter inputs; direct repo files and the current in-memory projection remain authoritative",
        ),
        _generated_posture("artifacts", inspect_projection_artifacts(inventory, projection)),
        _generated_posture("index", inspect_projection_index(inventory, projection)),
    ]


def _generated_posture(kind: str, findings: list[Finding]) -> Finding:
    degraded = [
        finding
        for finding in findings
        if finding.severity in {"warn", "error"} or finding.code in {"projection-artifact-missing", "projection-index-missing"}
    ]
    if not degraded:
        return Finding(
            "info",
            f"adapter-generated-{kind}",
            f"generated {kind} posture is current; adapter output still treats generated data as advisory",
        )
    severity = "warn" if any(finding.severity in {"warn", "error"} for finding in degraded) else "info"
    sample = "; ".join(f"{finding.code}: {_trim(finding.message)}" for finding in degraded[:3])
    return Finding(
        severity,
        f"adapter-generated-{kind}",
        f"generated {kind} posture is degraded but optional: {sample}; adapter fails open to repo files and in-memory projection",
    )


def _boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "adapter-no-authority",
            "adapter output is helper evidence only and cannot authorize accepted decisions, repair, closeout, archive, commit, lifecycle changes",
        ),
        Finding(
            "info",
            "adapter-no-source-bodies",
            "adapter source records expose paths, roles, counts, and hashes only; source file bodies remain in repo-visible files",
        ),
        Finding(
            "info",
            "adapter-no-mutation",
            "adapter inspection does not create MCP state, generated reports, projection artifacts, snapshots, hooks, config, commits, or filesystem mutations",
        ),
        Finding(
            "info",
            "adapter-recovery",
            "generic CLI and repo files remain usable when MCP tooling is absent, stale, disabled, or never installed",
        ),
    ]


def _source_set_hash(projection: Projection) -> str:
    rows = [(source.path, source.content_hash) for source in projection.sources if source.content_hash is not None]
    return _payload_hash(rows)[:12]


def _record_set_hash(projection: Projection) -> str:
    rows = [
        ("link", record.source, record.line, record.target, record.status, record.resolution_kind)
        for record in projection.links
    ] + [
        ("fan_in", record.target, record.inbound_count, record.status, record.sources)
        for record in projection.fan_in
    ]
    return _payload_hash(rows)[:12]


def _payload_hash(payload: object) -> str:
    rendered = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _hash_prefix(value: str | None) -> str:
    return value[:12] if value else "none"


def _trim(value: str, limit: int = 140) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _codex_mcp_toml(command: list[str]) -> str:
    rendered_args = ", ".join(json.dumps(arg, ensure_ascii=True) for arg in command[1:])
    return "\n".join(
        [
            f"[mcp_servers.{MCP_READ_PROJECTION_SERVER_NAME}]",
            f"command = {json.dumps(command[0], ensure_ascii=True)}",
            f"args = [{rendered_args}]",
        ]
    )


def _root_selection_payload(inventory: Inventory, default_root: Path, requested_root: str | None) -> dict[str, object]:
    return {
        "defaultRoot": str(default_root),
        "selectedRoot": str(inventory.root),
        "requestedRoot": requested_root or "",
        "toolArgument": "root",
        "inventoryReloadedPerCall": True,
        "writesFiles": False,
        "authorizesLifecycle": False,
    }


def _handle_jsonrpc_message(inventory: Inventory, message: object, inventory_loader: InventoryLoader) -> dict[str, object] | None:
    if not isinstance(message, dict):
        return _error_response(None, -32600, "Invalid Request")
    request_id = message.get("id")
    method = message.get("method")
    is_request = "id" in message
    if message.get("jsonrpc") != "2.0" or not isinstance(method, str):
        return _error_response(request_id if is_request else None, -32600, "Invalid Request") if is_request else None
    if method == "notifications/initialized":
        return None
    if not is_request:
        return None
    if method == "initialize":
        return _result_response(request_id, _initialize_result())
    if method == "ping":
        return _result_response(request_id, {})
    if method == "tools/list":
        return _result_response(request_id, {"tools": [_tool_definition()]})
    if method == "tools/call":
        return _tools_call_response(inventory, request_id, message.get("params"), inventory_loader)
    return _error_response(request_id, -32601, f"Method not found: {method}")


def _initialize_result() -> dict[str, object]:
    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {
            "name": "mylittleharness",
            "title": "MyLittleHarness Read Projection",
            "version": __version__,
            "description": "Dependency-free read-only MCP stdio adapter for MyLittleHarness projection posture.",
        },
        "instructions": (
            "Use the mylittleharness.read_projection tool as optional root-aware read/projection helper evidence only; "
            "repo-visible files and the generic CLI remain authoritative."
        ),
    }


def _tool_input_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "root": {
                "type": "string",
                "description": (
                    "Optional filesystem path to an MLH-serviced root to read for this call. "
                    "Omit to reload the adapter startup root."
                ),
            }
        },
        "additionalProperties": False,
    }


def _tool_definition() -> dict[str, object]:
    return {
        "name": MCP_READ_PROJECTION_TOOL,
        "title": "MyLittleHarness Read Projection",
        "description": (
            "Return a source-bound, read-only projection summary for a selected MyLittleHarness root without copying source "
            "bodies or approving lifecycle decisions."
        ),
        "inputSchema": _tool_input_schema(),
        "outputSchema": {
            "type": "object",
            "properties": {
                "adapter": {"type": "object"},
                "activation": {"type": "object"},
                "root": {"type": "object"},
                "rootSelection": {"type": "object"},
                "status": {"type": "string"},
                "sources": {"type": "array"},
                "sections": {"type": "array"},
                "boundary": {"type": "object"},
            },
            "required": ["adapter", "activation", "root", "status", "sources", "sections", "boundary"],
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        "execution": {"taskSupport": "forbidden"},
    }


def _tools_call_response(
    inventory: Inventory,
    request_id: object,
    params: object,
    inventory_loader: InventoryLoader,
) -> dict[str, object]:
    if not isinstance(params, dict):
        return _error_response(request_id, -32602, "Invalid params: tools/call params must be an object")
    name = params.get("name")
    if name != MCP_READ_PROJECTION_TOOL:
        return _error_response(request_id, -32602, f"Unknown tool: {name}")
    arguments = params.get("arguments", {})
    if arguments is None:
        arguments = {}
    target_root, requested_root, error = _selected_root_argument(inventory, arguments)
    if error:
        return _tool_error_response(request_id, error)
    try:
        selected_inventory = inventory_loader(target_root)
    except RootLoadError as exc:
        return _tool_error_response(request_id, f"Invalid root: {exc}")

    structured = mcp_read_projection_payload(
        selected_inventory,
        default_root=inventory.root,
        requested_root=requested_root,
    )
    return _result_response(
        request_id,
        {
            "content": [{"type": "text", "text": json.dumps(structured, sort_keys=True, indent=2, ensure_ascii=True)}],
            "structuredContent": structured,
            "isError": False,
        },
    )


def _selected_root_argument(inventory: Inventory, arguments: object) -> tuple[Path | str, str | None, str | None]:
    if not isinstance(arguments, dict):
        return inventory.root, None, "Invalid arguments: mylittleharness.read_projection accepts an optional root string."
    unknown = sorted(set(arguments) - {"root"})
    if unknown:
        return inventory.root, None, f"Invalid arguments: unknown field(s): {', '.join(unknown)}."
    requested_root = arguments.get("root")
    if requested_root in (None, ""):
        return inventory.root, None, None
    if not isinstance(requested_root, str):
        return inventory.root, None, "Invalid arguments: root must be a string path when supplied."
    return requested_root, requested_root, None


def _tool_error_response(request_id: object, text: str) -> dict[str, object]:
    return _result_response(
        request_id,
        {
            "content": [{"type": "text", "text": text}],
            "isError": True,
        },
    )


def _finding_payload(finding: Finding) -> dict[str, object]:
    payload: dict[str, object] = {
        "severity": finding.severity,
        "code": finding.code,
        "message": finding.message,
    }
    if finding.source is not None:
        payload["source"] = finding.source
    if finding.line is not None:
        payload["line"] = finding.line
    return payload


def _result_for(findings: list[Finding]) -> str:
    if any(finding.severity == "error" for finding in findings):
        return "error"
    if any(finding.severity == "warn" for finding in findings):
        return "warn"
    return "ok"


def _result_response(request_id: object, result: dict[str, object]) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error_response(request_id: object, code: int, message: str, data: object | None = None) -> dict[str, object]:
    error: dict[str, object] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _write_message(stdout: TextIO, message: dict[str, object]) -> None:
    stdout.write(json.dumps(message, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
    stdout.flush()
