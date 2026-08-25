# Garmin MCP setup reference

This reference covers [Garmin MCP for AI Coaching](../README.md) installation,
client configuration, deployment, authentication, and troubleshooting. Start
with the README for product orientation.

## Authentication first

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then
authenticate in a terminal before launching an MCP client:

```bash
uvx --python 3.12 --from git+https://github.com/wouterrodeyns/garmin_mcp garmin-mcp-auth
```

The interactive command stores local Garmin tokens, normally under
`~/.garminconnect`. Garmin email addresses, passwords, MFA codes, and tokens do
not belong in MCP client configuration.

## Claude Desktop

Claude Desktop reads its MCP configuration from:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

After authenticating, add this credential-free server entry:

```json
{
  "mcpServers": {
    "garmin": {
      "command": "uvx",
      "args": [
        "--python", "3.12",
        "--from", "git+https://github.com/wouterrodeyns/garmin_mcp",
        "garmin-mcp"
      ],
      "env": {
        "GARMIN_TOOL_PROFILE": "ai-coach"
      }
    }
  }
}
```

For a local checkout, replace the command and arguments with
`uv --directory /absolute/path/to/garmin_mcp run garmin-mcp`. Restart Claude
Desktop after changing its configuration.

## Codex

After token pre-authentication, add this credential-free entry to
`~/.codex/config.toml`:

```toml
[mcp_servers.garmin]
command = "uvx"
args = ["--python", "3.12", "--from", "git+https://github.com/wouterrodeyns/garmin_mcp", "garmin-mcp"]

[mcp_servers.garmin.env]
GARMIN_TOOL_PROFILE = "ai-coach"
```

From a local checkout, Codex can instead launch `uv run garmin-mcp` with that
checkout as its working directory.

## opencode

The tracked [`opencode.json`](../opencode.json) runs the MCP from the working
tree when opencode starts in a clone. For a global installation, authenticate
first and use this credential-free configuration:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "garmin": {
      "type": "local",
      "command": [
        "uvx", "--python", "3.12",
        "--from", "git+https://github.com/wouterrodeyns/garmin_mcp",
        "garmin-mcp"
      ],
      "environment": {
        "GARMIN_TOOL_PROFILE": "ai-coach"
      },
      "enabled": true,
      "timeout": 30000
    }
  }
}
```

Restart opencode after saving its configuration. The first `uvx` invocation
may take longer while it downloads and caches dependencies.

## Local development

The project supports Python 3.12+. Hosted examples use that lower bound for a
predictable environment.

```bash
git clone https://github.com/wouterrodeyns/garmin_mcp.git
cd garmin_mcp
uv sync
uv run garmin-mcp-auth
uv run garmin-mcp
```

To inspect the local MCP server interactively:

```bash
npx @modelcontextprotocol/inspector uv run garmin-mcp
```

## Runtime configuration and tool filtering

ai-coach is the default profile when `GARMIN_TOOL_PROFILE` is unset or
empty. Set `GARMIN_TOOL_PROFILE=ai-coach` explicitly in a client configuration
when documenting that intent. Filtering follows this precedence:

1. A non-empty `GARMIN_ENABLED_TOOLS` explicit allowlist wins; the selected
   profile and denylist are both ignored while the explicit allowlist is active.
2. Without an explicit allowlist, `GARMIN_DISABLED_TOOLS` subtracts tools from
   the selected or default profile.
3. Otherwise, `GARMIN_TOOL_PROFILE` selects a named profile. Full upstream tool
   registration is an explicit choice: full Taxuspt-compatible registration
   requires explicitly setting `GARMIN_TOOL_PROFILE=upstream-full`. That
   profile enables all tools exposed by the upstream-compatible server.
4. When `GARMIN_TOOL_PROFILE` is unset or empty, `ai-coach` applies by default.

For the high-level coaching tools, see [training context](ai-training.md),
[target-event evidence](ai-target-events.md),
[sleep trend evidence](ai-sleep-trend.md),
[activity analysis](ai-activity.md), [activity time-series
evidence](ai-activity-timeseries.md), [AI-friendly workouts](ai-workouts.md),
and [wellness heart-rate evidence](ai-wellness-heart-rate.md).

Training context is the coach's eyes/current context. `get_target_events` is a
separate deliberate target-event read for event-aware questions.
`analyze_activity` is the completed-session feedback overview, and
`get_activity_timeseries` is its narrow follow-up for concrete short-interval
evidence. Workout creation and in-place update (`create_workout` and
`update_workout`) are the coach's hands/write operations. `get_sleep_trend` and
`get_wellness_heart_rate` are deliberate evidence reads for those roles.
Activity analysis and time-series evidence are read-only and do not replace the
low-level `get_activity` compatibility/targeted read.

The `ai-coach` profile exposes exactly 17 tools:

`get_training_context`, `get_target_events`, `get_sleep_trend`, `get_wellness_heart_rate`, `analyze_activity`, `get_activity_timeseries`,
`create_workout`, `update_workout`, `get_activities`, `get_activities_by_date`,
`get_activity`, `get_workouts`, `get_workout_by_id`, `get_scheduled_workouts`,
`schedule_workout`, `unschedule_workout`, and `delete_workout`.

Other runtime variables include:

- `GARMIN_IS_CN`: use Garmin Connect China when set to `true`.
- `GARMIN_FIT_DOWNLOAD_DIR`: default activity-file download directory.
- `GARMIN_FIT_CONFIG`: persisted download configuration path; defaults to
  `~/.garminconnect_fit_config.json`.

For the advanced, opt-in scalar course read, see [course details](course-details.md).
It is outside `ai-coach`; enable it with `GARMIN_TOOL_PROFILE=upstream-full` or
the explicit `GARMIN_ENABLED_TOOLS=get_course_details` allowlist. It ignores
course geometry and does not change upload, list, or delete behavior.

## Transport

The default transport is `stdio`, suitable for Claude Desktop, Codex, opencode,
and MCP Inspector. HTTP deployments use:

- `GARMIN_MCP_TRANSPORT`: `stdio`, `streamable-http`, or `sse`.
- `GARMIN_MCP_HOST`: bind address, default `127.0.0.1`.
- `GARMIN_MCP_PORT`: bind port, default `8000`.

```bash
GARMIN_MCP_TRANSPORT=streamable-http garmin-mcp
```

Streamable-http clients connect to `/mcp`; SSE clients connect to `/sse`. The
SSE message endpoint is protocol-managed at `/messages/`. `GET /healthz`
provides liveness/readiness.
Loopback hosts are allowed for `streamable-http` and `sse`; by default, the
server refuses non-loopback binds. The MCP server does not authenticate its HTTP
endpoint. `GARMIN_MCP_ALLOW_UNAUTHENTICATED_REMOTE=true` is a dangerous
acknowledgement only: it does not add auth and should be used only behind an
authenticating reverse proxy. Never expose the endpoint without that
protection; `0.0.0.0` requires the same explicit override and proxy protection.

## Docker and non-interactive deployments

Docker credentials and file secrets are for non-interactive deployments and
require appropriate secret management; they are not Claude Desktop configuration.
Prefer persisted tokens created through interactive authentication when
practical.

The Docker commands below are local/container stdio examples; they do not
expose a reachable network service. The image defaults to stdio and these
examples publish no HTTP port. Credentials and tokens must be provisioned before
container start using a persisted token volume or managed secrets.

An HTTP container deployment requires explicit transport/host acknowledgement
and must run behind an authenticating reverse proxy. Set the transport and host
explicitly for that deployment and apply the remote acknowledgement only with
that proxy protection.

Start the included Compose deployment and inspect its logs with:

```bash
docker compose up -d
docker compose logs -f garmin-mcp
```

Or build and run directly, mounting a persistent token volume:

```bash
docker build -t garmin-mcp .
docker run -it -v garmin-tokens:/root/.garminconnect garmin-mcp
```

For a managed non-interactive deployment, configure file-backed secrets rather
than placing values in source-controlled files:

```yaml
services:
  garmin-mcp:
    environment:
      - GARMIN_EMAIL_FILE=/run/secrets/garmin_email
      - GARMIN_PASSWORD_FILE=/run/secrets/garmin_password
    secrets:
      - garmin_email
      - garmin_password

secrets:
  garmin_email:
    file: ./secrets/garmin_email.txt
  garmin_password:
    file: ./secrets/garmin_password.txt
```

The documented `secrets/garmin_email.txt` and `secrets/garmin_password.txt`
paths are ignored by Git and excluded from the Docker build context. Still
protect both files with strict filesystem permissions.

Do not set both `GARMIN_EMAIL` and `GARMIN_EMAIL_FILE`, or both
`GARMIN_PASSWORD` and `GARMIN_PASSWORD_FILE`. Protect secret files with strict
filesystem permissions. The `garmin-tokens` volume preserves authentication
across container restarts.

## Garmin Connect China

Authenticate against Garmin Connect China with either form:

```bash
GARMIN_IS_CN=true garmin-mcp-auth
garmin-mcp-auth --is-cn
```

Then add `"GARMIN_IS_CN": "true"` beside `GARMIN_TOOL_PROFILE` in a
credential-free client configuration. Docker deployments can set the same
variable in their deployment environment.

## MFA and token recovery

Desktop MCP servers are non-interactive. Complete MFA, verification, or token
recovery in a terminal, then restart the MCP client:

```bash
garmin-mcp-auth
garmin-mcp-auth --verify
garmin-mcp-auth --force-reauth
garmin-mcp-auth --token-path ~/.garmin_tokens
```

Never store a literal MFA code in configuration. If tokens have expired, run
the force-reauthentication command and complete the interactive prompts.

## Tests

Run the normal offline suite without a Garmin account:

```bash
uv run pytest -m "not e2e"
```

Live end-to-end tests require a real Garmin account and are deliberately
separate:

```bash
uv run pytest -m e2e
```

## Troubleshooting

- **Client cannot find `uvx`:** run `which uvx` (or the Windows equivalent)
  and use that full executable path in the client configuration.
- **First start is slow:** allow `uvx` time to download and cache dependencies.
- **Authentication expired:** run `garmin-mcp-auth --force-reauth`, verify, and
  restart the MCP client.
- **Claude Desktop cannot start the server:** check
  `~/Library/Logs/Claude/mcp-server-garmin.log` on macOS or
  `%APPDATA%\Claude\logs\mcp-server-garmin.log` on Windows.
- **Changes do not appear:** fully restart the MCP client after editing its
  configuration or refreshing Garmin tokens.

Keep credentials out of client configuration; return to `garmin-mcp-auth` for
login and recovery.
