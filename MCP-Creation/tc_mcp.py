"""
Local Test-Case MCP server (FastMCP).

Exposes the 100 VWO test cases in `testcases_vwo_100.csv` to any MCP-capable LLM
client. The LLM can search/filter the test cases by priority, severity, module,
labels (metadata), owner, sprint, status, test type, or free text — and fetch a
single test case in full by id.

Run locally:
    python tc_mcp.py            # stdio transport (default, for Claude Desktop / Cursor etc.)
    fastmcp run tc_mcp.py       # alternative launcher
"""

import csv
import argparse
from pathlib import Path
from typing import Optional

from fastmcp import FastMCP

CSV_PATH = Path(__file__).parent / "testcases_vwo_100.csv"

# Columns whose value is a "metadata" pipe-separated list rather than a scalar.
LIST_FIELDS = {"labels"}

mcp = FastMCP("test-case-explorer")


def _load_test_cases() -> list[dict]:
    """Read the CSV once into a list of dict rows, splitting list-style fields."""
    rows: list[dict] = []
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            # Normalise pipe-separated metadata into real lists for easy matching.
            for field in LIST_FIELDS:
                raw = (row.get(field) or "").strip()
                row[field] = [v.strip() for v in raw.split("|") if v.strip()] if raw else []
            rows.append(row)
    return rows


# Loaded once at import; the CSV is static so there's no need to re-read per call.
TEST_CASES: list[dict] = _load_test_cases()


def _matches(tc: dict, field: str, wanted: Optional[str]) -> bool:
    """Case-insensitive equality match for a scalar field (None = no filter)."""
    if not wanted:
        return True
    return str(tc.get(field, "")).strip().lower() == wanted.strip().lower()


@mcp.tool
def search_test_cases(
    priority: Optional[str] = None,
    severity: Optional[str] = None,
    module: Optional[str] = None,
    test_type: Optional[str] = None,
    status: Optional[str] = None,
    owner: Optional[str] = None,
    sprint: Optional[str] = None,
    label: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 50,
) -> dict:
    """Search and filter the test cases.

    All filters are optional and combined with AND. Omit a filter to ignore it.

    Args:
        priority: Exact priority, e.g. "P0", "P1", "P2", "P3".
        severity: Exact severity, e.g. "Blocker", "Critical", "Major", "Minor", "Trivial".
        module: Exact module/feature area, e.g. "Reports", "AB Testing", "Admin".
        test_type: Exact type, e.g. "Functional", "UI", "Negative", "Boundary".
        status: Exact status, e.g. "Active".
        owner: Exact owner username, e.g. "riya.sharma".
        sprint: Exact sprint id, e.g. "VWO-25.S38".
        label: A single metadata label/tag the test case must carry, e.g.
            "regression", "smoke", "mobile", "security", "accessibility".
        query: Free-text substring matched against id, jira_id, summary,
            steps, preconditions and expected_result (case-insensitive).
        limit: Maximum number of results to return (default 50).

    Returns:
        A dict with `count` (number of matches returned), `total_matched`
        (matches before the limit) and `results` (list of test cases).
    """
    q = query.strip().lower() if query else None
    lbl = label.strip().lower() if label else None

    matched: list[dict] = []
    for tc in TEST_CASES:
        if not (
            _matches(tc, "priority", priority)
            and _matches(tc, "severity", severity)
            and _matches(tc, "module", module)
            and _matches(tc, "test_type", test_type)
            and _matches(tc, "status", status)
            and _matches(tc, "owner", owner)
            and _matches(tc, "sprint", sprint)
        ):
            continue

        if lbl and lbl not in [l.lower() for l in tc.get("labels", [])]:
            continue

        if q:
            haystack = " ".join(
                str(tc.get(k, ""))
                for k in ("id", "jira_id", "summary", "steps", "preconditions", "expected_result")
            ).lower()
            if q not in haystack:
                continue

        matched.append(tc)

    return {
        "count": len(matched[:limit]),
        "total_matched": len(matched),
        "results": matched[:limit],
    }


@mcp.tool
def get_test_case(test_id: str) -> dict:
    """Fetch a single test case in full by its id (e.g. "TC-00001").

    Returns the test case dict, or an `error` key if no match is found.
    """
    tid = test_id.strip().lower()
    for tc in TEST_CASES:
        if str(tc.get("id", "")).strip().lower() == tid:
            return tc
    return {"error": f"No test case found with id '{test_id}'."}


@mcp.tool
def list_filter_values() -> dict:
    """List the distinct values available for each filterable field.

    Useful for an LLM to discover what it can filter by (which priorities,
    modules, labels, owners, sprints, etc. actually exist in the data).
    """
    scalar_fields = ["priority", "severity", "module", "test_type", "status", "owner", "sprint"]
    facets: dict = {f: set() for f in scalar_fields}
    labels: set = set()

    for tc in TEST_CASES:
        for f in scalar_fields:
            val = str(tc.get(f, "")).strip()
            if val:
                facets[f].add(val)
        labels.update(tc.get("labels", []))

    result = {f: sorted(v) for f, v in facets.items()}
    result["labels"] = sorted(labels)
    result["total_test_cases"] = len(TEST_CASES)
    return result


@mcp.tool
def get_stats() -> dict:
    """Return summary counts of test cases grouped by priority, severity and module."""
    def tally(field: str) -> dict:
        counts: dict = {}
        for tc in TEST_CASES:
            key = str(tc.get(field, "")).strip() or "(none)"
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))

    return {
        "total": len(TEST_CASES),
        "by_priority": tally("priority"),
        "by_severity": tally("severity"),
        "by_module": tally("module"),
        "by_test_type": tally("test_type"),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Test Case Explorer MCP server.")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio",
        help="Transport to use. Use stdio for local clients, http for remote MCP clients.")
    parser.add_argument("--host", default="127.0.0.1",
        help="Host to bind when using HTTP transport.")
    parser.add_argument("--port", type=int, default=8000,
        help="Port to bind when using HTTP transport.")
    args = parser.parse_args()

    if args.transport == "http":
        # HTTP transport so remote/networked LLM clients can connect over a URL.
        # Endpoint: http://%s:%s/mcp
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        # stdio transport for local MCP clients that spawn the process directly.
        mcp.run(transport="stdio")
