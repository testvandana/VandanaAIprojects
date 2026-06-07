# Test-Case Explorer — Local MCP Server

A local [MCP](https://modelcontextprotocol.io) server built with **FastMCP** that
lets any MCP-capable LLM (Claude Desktop, Cursor, Claude Code, etc.) connect and
search the test cases in `testcases_vwo_100.csv` by priority, severity, module,
labels (metadata), owner, sprint, status, test type, or free text.

It supports **two transports**:

- **stdio** (default) — the client launches the script as a subprocess. Best for
  local desktop clients (Claude Desktop, Cursor, Claude Code).
- **http** — the script runs as a standalone server on a URL. Best for remote /
  networked clients or quick browser-based testing.

## Files

| File | Purpose |
|------|---------|
| `tc_mcp.py` | The FastMCP server (supports `--transport stdio|http`) |
| `testcases_vwo_100.csv` | The test-case data |
| `claude_desktop_config.json` | Ready-to-use stdio config snippet for Claude Desktop |

## Tools exposed to the LLM

| Tool | What it does |
|------|--------------|
| `search_test_cases` | Filter by `priority`, `severity`, `module`, `test_type`, `status`, `owner`, `sprint`, `label`, and/or free-text `query`. All optional, combined with AND. |
| `get_test_case` | Fetch one full test case by id, e.g. `TC-00005`. |
| `list_filter_values` | Discover all distinct values available for each filter (priorities, modules, labels…). |
| `get_stats` | Summary counts grouped by priority / severity / module / test type. |

## Requirements

```bash
pip install fastmcp
```

## Run it

```bash
# stdio transport (default — what local MCP clients launch as a subprocess)
python tc_mcp.py

# or via the FastMCP CLI
fastmcp run tc_mcp.py

# HTTP transport for remote clients or browser-based testing
# serves at http://127.0.0.1:8000/mcp
python tc_mcp.py --transport http --host 127.0.0.1 --port 8000
```

CLI flags (HTTP mode only): `--host` (default `127.0.0.1`) and `--port`
(default `8000`).

> When running in HTTP mode, keep the terminal open — the server stays up only
> as long as the process runs.

## Verify with the MCP Inspector

The [MCP Inspector](https://github.com/modelcontextprotocol/inspector) is a
browser UI for testing a server's tools interactively. Launch it with:

```bash
fastmcp dev tc_mcp.py
```

This installs (first run) and starts the Inspector, printing a URL with an auth
token, e.g.:

```
🚀 MCP Inspector is up and running at:
   http://localhost:6274/?MCP_PROXY_AUTH_TOKEN=<token>
```

Open that URL (the token is required), then:

1. Click **Connect**.
2. Open the **Tools** tab → **List Tools** — you should see all four:
   `search_test_cases`, `get_test_case`, `list_filter_values`, `get_stats`.
3. Run `get_stats` (no args) to see priority/severity/module counts, or
   `search_test_cases` with `priority = P0` to see filtered results.

> Requires Node.js / `npx` (the Inspector is a Node package).

## Connect a client

### Option A — stdio (local, client spawns the process)

#### Claude Desktop
Copy the contents of `claude_desktop_config.json` into your Claude Desktop config
file and restart Claude Desktop:

- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

(Adjust the python path / script path if they differ on your machine.)

#### Claude Code
```bash
claude mcp add test-case-explorer -- python "d:\AI Testing Course\AITestBlueprint\MCP-Creation\tc_mcp.py"
```

#### Cursor / other clients
Use the same `command` + `args` shape as `claude_desktop_config.json` in that
client's MCP settings.

### Option B — HTTP (remote / URL-based clients)

First start the server in HTTP mode:

```bash
python tc_mcp.py --transport http --host 127.0.0.1 --port 8000
```

Then point the client at the URL (no `command`/`args` needed):

```json
{
  "mcpServers": {
    "test-case-explorer": {
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

Some clients also expect a `"type": "http"` (or `"transport": "streamable-http"`)
field alongside the URL — check your client's format.

> **Testing the HTTP endpoint manually:** MCP is not a webpage, so opening the URL
> in a browser will fail. Requests must be **POST** with the header
> `Accept: application/json, text/event-stream` and a JSON-RPC body. Responses come
> back as Server-Sent Events (`content-type: text/event-stream`).
>
> `127.0.0.1` is reachable only from this machine. To connect a client on another
> device, bind `--host 0.0.0.0` and expose it via a tunnel (e.g. ngrok) with
> authentication.

## Example prompts once connected

- "Show me all P0 test cases."
- "Find AB Testing test cases tagged with the `security` label."
- "Get the full details for TC-00005."
- "How many test cases are there per priority?"
- "Search for test cases about cookie targeting."

## Data note

Despite the `_100` in the filename, `testcases_vwo_100.csv` currently holds **480
test cases**. The server loads and serves all rows in the file, whatever the
count. The CSV columns are: `id`, `jira_id`, `summary`, `module`, `priority`,
`severity`, `labels`, `preconditions`, `steps`, `expected_result`, `test_type`,
`owner`, `sprint`, `status`. The `labels` column is pipe-separated (`a|b|c`) and is
parsed into a list for metadata filtering.
