from __future__ import annotations

from .inventory import Inventory
from .models import Finding
from .projection import Projection, build_projection
from .projection_artifacts import ARTIFACT_DIR_REL, inspect_projection_artifacts
from .projection_index import INDEX_REL_PATH, full_text_search_findings, inspect_projection_index


SEMANTIC_OUTPUT_REL = ".mylittleharness/generated/semantic"
EVALUATION_RESULT_LIMIT = 3
EVALUATION_CASES = (
    ("semantic retrieval", "semantic-retrieval", False),
    ("source verification", "source-verification", False),
    ("stale index", "stale-index", False),
    ("offline degraded mode", "offline-degraded-mode", False),
    ("repair closeout archive commit", "lifecycle-risk", False),
    ("DefinitelyMissingSemanticNeedle", "negative-probe", True),
)


def semantic_inspect_sections(inventory: Inventory) -> list[tuple[str, list[Finding]]]:
    projection = build_projection(inventory)
    artifact_findings = inspect_projection_artifacts(inventory, projection)
    index_findings = inspect_projection_index(inventory, projection)
    search_base = _search_base_findings(projection, artifact_findings, index_findings)
    runtime = _runtime_findings(inventory)
    evaluation = _evaluation_findings()
    return [
        ("Summary", _summary_findings(inventory, projection, search_base + runtime)),
        ("Search Base", search_base),
        ("Runtime", runtime),
        ("Evaluation", evaluation),
        ("Boundary", _boundary_findings()),
    ]


def semantic_evaluate_sections(inventory: Inventory) -> list[tuple[str, list[Finding]]]:
    projection = build_projection(inventory)
    index_findings = inspect_projection_index(inventory, projection)
    blocking = _semantic_index_blocking_findings(index_findings)
    query_findings, false_positive_findings, source_findings = _evaluation_query_findings(inventory, projection, blocking)
    return [
        ("Summary", _evaluation_summary_findings(inventory, projection, blocking)),
        ("Corpus", _evaluation_corpus_findings(inventory, projection, index_findings, blocking)),
        ("Evaluation Queries", query_findings),
        ("False-Positive Review", false_positive_findings),
        ("Source Verification", source_findings),
        ("Degraded Modes", _evaluation_degraded_mode_findings(blocking)),
        ("Boundary", _evaluation_boundary_findings()),
    ]


def _summary_findings(inventory: Inventory, projection: Projection, findings: list[Finding]) -> list[Finding]:
    warnings = sum(1 for finding in findings if finding.severity == "warn")
    errors = sum(1 for finding in findings if finding.severity == "error")
    readiness = "degraded" if errors or warnings else "inspectable"
    return [
        Finding(
            "info",
            "semantic-boundary",
            "terminal-only semantic readiness inspection; no embeddings, models, provider config, generated semantic indexes, reports, caches, databases, or mutations are written",
        ),
        Finding("info", "semantic-root-kind", f"root kind: {inventory.root_kind}"),
        Finding(
            "info",
            "semantic-readiness",
            (
                f"advisory readiness: {readiness}; sources={projection.summary.source_count}; "
                f"readable={projection.summary.readable_source_count}; warnings={warnings}; errors={errors}; "
                "semantic retrieval runtime remains deferred"
            ),
        ),
    ]


def _evaluation_summary_findings(inventory: Inventory, projection: Projection, blocking: list[Finding]) -> list[Finding]:
    posture = "degraded" if blocking else "source-verified-index-current"
    return [
        Finding(
            "info",
            "semantic-evaluation-boundary",
            "terminal-only semantic evaluation; no embeddings, models, provider config, generated semantic indexes, reports, caches, databases, or mutations are written",
        ),
        Finding("info", "semantic-evaluation-root-kind", f"root kind: {inventory.root_kind}"),
        Finding(
            "info",
            "semantic-evaluation-summary",
            (
                f"bounded evaluation posture: {posture}; fixed_queries={len(EVALUATION_CASES)}; "
                f"sources={projection.summary.source_count}; readable={projection.summary.readable_source_count}; "
                "runtime=none; generated_semantic_output=deferred"
            ),
        ),
    ]


def _search_base_findings(
    projection: Projection,
    artifact_findings: list[Finding],
    index_findings: list[Finding],
) -> list[Finding]:
    summary = projection.summary
    return [
        Finding(
            "info",
            "semantic-in-memory-projection",
            (
                "in-memory projection rebuilt from current inventory; storage_boundary=none; "
                f"sources={summary.source_count}; present={summary.present_source_count}; "
                f"readable={summary.readable_source_count}; hashed={summary.hashed_source_count}; "
                f"links={summary.link_record_count}; fan_in={summary.fan_in_record_count}"
            ),
        ),
        Finding(
            "info",
            "semantic-exact-path-base",
            "exact text search stays source-backed; path/reference parity may use current projection artifacts only when they inspect as current",
        ),
        _projection_posture("artifacts", artifact_findings),
        _projection_posture("index", index_findings),
    ]


def _evaluation_corpus_findings(
    inventory: Inventory,
    projection: Projection,
    index_findings: list[Finding],
    blocking: list[Finding],
) -> list[Finding]:
    summary = projection.summary
    findings = [
        Finding(
            "info",
            "semantic-evaluation-corpus",
            (
                "evaluation corpus is the current inventory-backed in-memory projection; "
                f"sources={summary.source_count}; present={summary.present_source_count}; "
                f"readable={summary.readable_source_count}; hashed={summary.hashed_source_count}; "
                f"links={summary.link_record_count}; fan_in={summary.fan_in_record_count}"
            ),
        ),
        Finding(
            "info",
            "semantic-evaluation-query-set",
            "fixed built-in evaluation queries only; arbitrary semantic query input remains unsupported",
        ),
    ]
    if blocking:
        sample = "; ".join(f"{finding.code}: {_trim(finding.message)}" for finding in blocking[:3])
        findings.append(
            Finding(
                "warn",
                "semantic-evaluation-index-degraded",
                f"SQLite FTS/BM25 evaluation input is degraded: {sample}; exact/path/full-text recovery stays source-backed",
                blocking[0].source or INDEX_REL_PATH,
                blocking[0].line,
            )
        )
    elif any(finding.code == "projection-index-current" for finding in index_findings):
        findings.append(
            Finding(
                "info",
                "semantic-evaluation-index-current",
                "SQLite FTS/BM25 index is current enough for source-verified evaluation and remains disposable generated output",
                INDEX_REL_PATH,
            )
        )
    else:
        findings.append(
            Finding(
                "info",
                "semantic-evaluation-index-inspectable",
                "SQLite FTS/BM25 index inspect completed without blocking findings; generated output remains advisory",
                INDEX_REL_PATH,
            )
        )
    semantic_path = inventory.root / SEMANTIC_OUTPUT_REL
    if semantic_path.exists() or semantic_path.is_symlink():
        findings.append(
            Finding(
                "warn",
                "semantic-evaluation-generated-output-present",
                f"deferred semantic generated-output path already exists and is not used as authority: {SEMANTIC_OUTPUT_REL}",
                SEMANTIC_OUTPUT_REL,
            )
        )
    else:
        findings.append(
            Finding(
                "info",
                "semantic-evaluation-generated-output-absent",
                f"no generated semantic output is required or created: {SEMANTIC_OUTPUT_REL}",
                SEMANTIC_OUTPUT_REL,
            )
        )
    return findings


def _runtime_findings(inventory: Inventory) -> list[Finding]:
    semantic_path = inventory.root / SEMANTIC_OUTPUT_REL
    findings = [
        Finding(
            "info",
            "semantic-runtime-deferred",
            "embedding runtime is intentionally deferred; no local model, provider API, network access, dependency, environment variable, or workstation tool is required",
        ),
        Finding(
            "info",
            "semantic-generated-output-deferred",
            f"future semantic output remains deferred; this command does not create, inspect as authority, or require {SEMANTIC_OUTPUT_REL}",
            SEMANTIC_OUTPUT_REL,
        ),
    ]
    if semantic_path.exists() or semantic_path.is_symlink():
        findings.append(
            Finding(
                "warn",
                "semantic-generated-output-present",
                f"deferred semantic generated-output path already exists and is not used as authority: {SEMANTIC_OUTPUT_REL}",
                SEMANTIC_OUTPUT_REL,
            )
        )
    return findings


def _evaluation_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "semantic-evaluation-false-positives",
            "future semantic retrieval needs an evaluation set for false positives and weak matches before results can be trusted as recovery hints",
        ),
        Finding(
            "info",
            "semantic-evaluation-stale-index",
            "future semantic indexes must report stale, missing, root-mismatched, and corrupted posture as degraded input",
        ),
        Finding(
            "info",
            "semantic-evaluation-missing-runtime",
            "missing model/runtime/provider availability must degrade to exact, path, and full-text source-backed search",
        ),
        Finding(
            "info",
            "semantic-evaluation-offline",
            "offline work must remain valid without network access, model downloads, API credentials, hooks, CI, or adapters",
        ),
        Finding(
            "info",
            "semantic-evaluation-source-verification",
            "semantic matches must point back to inspectable source paths and require source verification before influencing any write decision",
        ),
    ]


def _evaluation_query_findings(
    inventory: Inventory,
    projection: Projection,
    blocking: list[Finding],
) -> tuple[list[Finding], list[Finding], list[Finding]]:
    query_findings: list[Finding] = []
    false_positive_findings: list[Finding] = [
        Finding(
            "info",
            "semantic-evaluation-false-positive-review",
            "fixed probes include broad semantic terms, stale/degraded wording, lifecycle-risk terms, and a negative no-match query",
        )
    ]
    source_findings: list[Finding] = [
        Finding(
            "info",
            "semantic-evaluation-source-verification",
            "accepted evaluation matches must be reported only after current source-file verification by path, line, source hash, and indexed text",
        )
    ]
    if blocking:
        blocker = blocking[0]
        for query, role, _negative in EVALUATION_CASES:
            query_findings.append(
                Finding(
                    "warn",
                    "semantic-evaluation-query-degraded",
                    (
                        f"evaluation query {query!r} ({role}) skipped: {blocker.code}; "
                        "exact/path/full-text recovery stays source-backed and direct repo files remain authoritative"
                    ),
                    blocker.source or INDEX_REL_PATH,
                    blocker.line,
                )
            )
        false_positive_findings.append(
            Finding(
                "info",
                "semantic-evaluation-false-positive-deferred",
                "false-positive review is advisory and limited while the SQLite FTS/BM25 index is missing, stale, corrupt, or unavailable",
            )
        )
        source_findings.append(
            Finding(
                "info",
                "semantic-evaluation-source-verification-degraded",
                "source verification is not attempted for skipped evaluation queries; source files remain directly inspectable",
            )
        )
        return query_findings, false_positive_findings, source_findings

    for query, role, negative in EVALUATION_CASES:
        raw_findings = full_text_search_findings(inventory, projection, query, EVALUATION_RESULT_LIMIT)
        matches = [finding for finding in raw_findings if finding.code == "full-text-match"]
        no_matches = [finding for finding in raw_findings if finding.code == "full-text-no-matches"]
        skipped = [finding for finding in raw_findings if finding.code == "projection-index-query-skipped"]
        if skipped:
            skipped_finding = skipped[0]
            query_findings.append(
                Finding(
                    "warn",
                    "semantic-evaluation-query-degraded",
                    f"evaluation query {query!r} ({role}) skipped after index inspection: {_trim(skipped_finding.message)}",
                    skipped_finding.source,
                    skipped_finding.line,
                )
            )
            continue
        query_findings.append(
            Finding(
                "info",
                "semantic-evaluation-query-current",
                f"evaluation query {query!r} ({role}) used the current source-verified SQLite FTS/BM25 index",
                INDEX_REL_PATH,
            )
        )
        if no_matches:
            severity = "info" if negative else "warn"
            code = "semantic-evaluation-negative-no-match" if negative else "semantic-evaluation-query-no-match"
            query_findings.append(
                Finding(
                    severity,
                    code,
                    f"evaluation query {query!r} ({role}) produced no source-verified matches",
                    INDEX_REL_PATH,
                )
            )
            if negative:
                false_positive_findings.append(
                    Finding(
                        "info",
                        "semantic-evaluation-negative-no-match",
                        f"negative probe {query!r} produced no source-verified matches",
                        INDEX_REL_PATH,
                    )
                )
            continue
        for match in matches:
            if negative:
                false_positive_findings.append(
                    Finding(
                        "warn",
                        "semantic-evaluation-negative-hit",
                        f"negative probe {query!r} unexpectedly matched source text; manual false-positive review required: {_trim(match.message, 260)}",
                        match.source,
                        match.line,
                    )
                )
                continue
            query_findings.append(
                Finding(
                    "info",
                    "semantic-evaluation-query-match",
                    f"evaluation query {query!r} ({role}) source-verified match: {_trim(match.message, 260)}",
                    match.source,
                    match.line,
                )
            )
            source_findings.append(
                Finding(
                    "info",
                    "semantic-evaluation-source-match",
                    f"source-verified evaluation match for {query!r}: {_trim(match.message, 260)}",
                    match.source,
                    match.line,
                )
            )
        if role == "lifecycle-risk":
            false_positive_findings.append(
                Finding(
                    "info",
                    "semantic-evaluation-lifecycle-risk",
                    (
                        "lifecycle-risk query contains repair/closeout/archive/commit terms; matches are recovery hints only "
                        "and cannot approve repair, closeout, archive, commit, switch-over, or lifecycle decisions"
                    ),
                )
            )
    return query_findings, false_positive_findings, source_findings


def _boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "semantic-no-authority",
            "semantic readiness output is advisory evidence only and cannot authorize accepted decisions, repair, closeout, archive, commit, switch-over, or lifecycle changes",
        ),
        Finding(
            "info",
            "semantic-no-runtime",
            "semantic inspection does not install embedding runtimes, download models, call providers, create vector stores, or require network access",
        ),
        Finding(
            "info",
            "semantic-no-mutation",
            "semantic inspection does not write reports, generated semantic output, projection artifacts, search indexes, caches, hooks, config, commits, archives, repairs, or workflow state",
        ),
        Finding(
            "info",
            "semantic-recovery",
            "repo files, in-memory projection, exact/path search, and source-verified SQLite FTS/BM25 remain the recovery base before semantic retrieval is implemented",
        ),
    ]


def _evaluation_degraded_mode_findings(blocking: list[Finding]) -> list[Finding]:
    findings = [
        Finding(
            "info",
            "semantic-evaluation-no-runtime",
            "evaluation requires no embedding runtime, model download, provider API, network access, dependency, environment variable, or workstation tool",
        ),
        Finding(
            "info",
            "semantic-evaluation-no-rebuild",
            "semantic --evaluate does not build, rebuild, delete, repair, or write projection or semantic generated output",
        ),
        Finding(
            "info",
            "semantic-evaluation-offline",
            "offline degraded mode falls back to repo files, in-memory projection, exact/path search, and source-backed full-text posture",
        ),
    ]
    for finding in blocking[:3]:
        findings.append(
            Finding(
                "warn",
                "semantic-evaluation-degraded-input",
                f"degraded evaluation input: {finding.code}; {_trim(finding.message)}",
                finding.source,
                finding.line,
            )
        )
    if not blocking:
        findings.append(
            Finding(
                "info",
                "semantic-evaluation-degraded-inputs-clear",
                "no blocking SQLite FTS/BM25 degraded-input findings were observed for this evaluation run",
                INDEX_REL_PATH,
            )
        )
    return findings


def _evaluation_boundary_findings() -> list[Finding]:
    return [
        Finding(
            "info",
            "semantic-evaluation-no-authority",
            "semantic evaluation output is advisory evidence only and cannot authorize accepted decisions, repair, closeout, archive, commit, switch-over, or lifecycle changes",
        ),
        Finding(
            "info",
            "semantic-evaluation-no-semantic-runtime",
            "semantic evaluation does not install embedding runtimes, download models, call providers, create vector stores, or require network access",
        ),
        Finding(
            "info",
            "semantic-evaluation-no-mutation",
            "semantic evaluation does not write reports, generated semantic output, projection artifacts, search indexes, caches, hooks, config, commits, archives, repairs, or workflow state",
        ),
        Finding(
            "info",
            "semantic-evaluation-recovery",
            "repo files, in-memory projection, exact/path search, and source-verified SQLite FTS/BM25 remain the recovery base before real semantic retrieval is implemented",
        ),
    ]


def _projection_posture(kind: str, findings: list[Finding]) -> Finding:
    missing_codes = {
        "artifacts": "projection-artifact-missing",
        "index": "projection-index-missing",
    }
    current_codes = {
        "artifacts": "projection-artifact-current",
        "index": "projection-index-current",
    }
    sources = {
        "artifacts": ARTIFACT_DIR_REL,
        "index": INDEX_REL_PATH,
    }
    degraded = [finding for finding in findings if finding.severity in {"warn", "error"}]
    if degraded:
        sample = "; ".join(f"{finding.code}: {_trim(finding.message)}" for finding in degraded[:3])
        return Finding(
            "warn",
            f"semantic-{kind}-degraded",
            f"generated projection {kind} posture is degraded but optional for semantic readiness: {sample}; direct source files remain authoritative",
            sources[kind],
        )
    if any(finding.code == current_codes[kind] for finding in findings):
        return Finding(
            "info",
            f"semantic-{kind}-current",
            f"generated projection {kind} are current enough for readiness inspection; they remain advisory generated output",
            sources[kind],
        )
    if any(finding.code == missing_codes[kind] for finding in findings):
        return Finding(
            "info",
            f"semantic-{kind}-missing",
            f"generated projection {kind} are missing; semantic readiness falls back to current repo files and in-memory projection",
            sources[kind],
        )
    return Finding(
        "info",
        f"semantic-{kind}-inspectable",
        f"generated projection {kind} inspect completed without warning posture; generated output remains advisory",
        sources[kind],
    )


def _trim(value: str, limit: int = 140) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _semantic_index_blocking_findings(findings: list[Finding]) -> list[Finding]:
    return [
        finding
        for finding in findings
        if finding.severity in {"warn", "error"} or finding.code == "projection-index-missing"
    ]
