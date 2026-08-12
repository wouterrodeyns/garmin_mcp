# Garmin MCP for AI Coaching

A purpose-built Garmin MCP for AI coaching and workout creation, with
in-place workout updates. This project
is a fork of [Taxuspt's Garmin MCP](https://github.com/Taxuspt/garmin_mcp), keeps
its maintained Garmin backend intentionally upstream-compatible, and is
installed from
[wouterrodeyns/garmin_mcp](https://github.com/wouterrodeyns/garmin_mcp).

It uses the unofficial
[python-garminconnect](https://github.com/cyberjunky/python-garminconnect)
client. Garmin data and metric availability vary by account, device,
subscription, and sync state.

## Designed AI-coach workflow

The recommended experience centers on three high-level coaching roles:

| Tool | Role |
|---|---|
| [`get_training_context(days=14)`](docs/ai-training.md) | Context eyes: a compact, read-only factual snapshot before making a recommendation. |
| [`analyze_activity(activity_id)`](docs/ai-activity.md) | Completed-session feedback read: bounded facts for the AI to interpret. |
| [`create_workout(...)`](docs/ai-workouts.md) and [`update_workout(...)`](docs/ai-workouts.md) | Workout hands: create a readable workout or apply a friendly in-place update while preserving its ID and schedules. |

```text
User: Review my last 30 days and recommend today's run.
AI:   get_training_context(days=30) -> factual context -> conservative advice.

User: Put that workout on Garmin for tomorrow.
AI:   explain the proposed workout, request confirmation, then
      create_workout(..., schedule_date="YYYY-MM-DD") -> upload + schedule.

User: Change that workout to five five-minute intervals.
AI:   confirm the patch, then update_workout(workout_id=..., name="Threshold 5x5", steps=[...])
      -> in-place update; the workout ID and existing schedules are preserved.
```

A `null` recovery or fitness metric means it was not available in this snapshot.
It does not prove that the account or device cannot support it. Use structured
warnings and actual metric dates, and do not treat stale or unsynced Garmin data
as current.

Before any write, the AI should explain the proposed session and obtain the
user's confirmation. Activity data and training context remain read-only.

## Claude Desktop quick start

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/).

2. Authenticate interactively in a terminal:

   ```bash
   uvx --python 3.12 --from git+https://github.com/wouterrodeyns/garmin_mcp garmin-mcp-auth
   ```

3. Add the server to Claude Desktop:

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

4. Restart Claude Desktop, then ask it to review your Garmin context before it
   recommends training.

Do not put Garmin email addresses, passwords, MFA codes, or tokens in Claude Desktop configuration.
`garmin-mcp-auth` stores local tokens for the MCP server to reuse.

For config-file locations, Codex, opencode, local checkouts, Docker, transports,
Garmin Connect China, and token recovery, see the
[setup reference](docs/setup.md).

## AI-coach tool profile

Set `GARMIN_TOOL_PROFILE=ai-coach` to expose this deliberate 13-tool surface:

```text
`get_training_context`
`analyze_activity`
`create_workout`
`update_workout`
`get_activities`
`get_activities_by_date`
`get_activity`
`get_workouts`
`get_workout_by_id`
`get_scheduled_workouts`
`schedule_workout`
`unschedule_workout`
`delete_workout`
```

This profile narrows registration for the AI-facing surface; no existing
upstream tool is removed, and broad upstream-compatible registration remains
available when no profile is selected.

The activity and coaching-context operations are reads. Workout creation and
in-place update, scheduling, unscheduling, and deletion are deliberate writes.
An update uses the numeric `workout_id` template ID; `scheduled_workout_id` is
the calendar-entry ID used only for unscheduling. Updates preserve the
underlying ID and existing schedules and make no calendar call. If an update
reports `update_may_have_applied` or `partial_success`, read it with
`get_workout_by_id` before retrying.
The safe instruction is to read the workout before retrying.

Tool filtering follows this precedence:

1. A non-empty `GARMIN_ENABLED_TOOLS` explicit allowlist takes precedence; the
   denylist is ignored while the explicit allowlist is active.
2. Without an explicit allowlist, `GARMIN_DISABLED_TOOLS` subtracts tools from
   the selected profile or broad default.
3. Otherwise, the selected profile controls registration.

When the explicit allowlist is absent and the profile is unset, broad upstream-compatible registration remains available.
This preserves the full upstream tool registration for advanced users who
intentionally want all tools; the `ai-coach` profile remains the recommended
AI-facing default.

## Documentation and development

- [Training context](docs/ai-training.md) documents aggregation windows,
  normalized fields, optional metrics, and structured warning/status behavior.
- [Activity analysis](docs/ai-activity.md) documents the completed-session
  feedback read, sport-gated detail, stable envelope, and v1 boundaries.
- [AI-friendly workouts](docs/ai-workouts.md) documents the readable workout
  schema, compiler, supported sports, targets, and scheduling result.
- [Setup and operations](docs/setup.md) covers clients, authentication, local
  development, transports, Docker, China, testing, and troubleshooting.

The project supports Python 3.12+. For local development:

```bash
git clone https://github.com/wouterrodeyns/garmin_mcp.git
cd garmin_mcp
uv sync
uv run pytest -m "not e2e"
```

The normal suite is offline and does not require a Garmin account. Live E2E
tests use a real account and are run separately as described in the setup
reference.

### Product boundaries

- Garmin activity and health data are read-only.
- The curated profile does not expose unrelated Garmin mutations.
- Credentials remain local and are never AI-callable tools.
- The AI generates a human-readable workout schema, not raw Garmin DTO JSON.
- Compiled workouts still pass through Taxuspt's normalization and validation
  before upload.
- Garmin Coach/adaptive UUID workouts and unsupported-sport updates remain
  outside v1; moving a workout remains deferred.

## Compatibility, contributing, and license

Fork-specific AI abstractions live in separate `ai_training`, `ai_workouts`, and
`ai_activity` packages. The ai_training, ai_workouts, and ai_activity packages
wrap Taxuspt's backend instead of replacing authentication,
Garmin API handling, or workout normalization, keeping future upstream sync
practical.

Report fork-specific issues in the
[wouterrodeyns issue tracker](https://github.com/wouterrodeyns/garmin_mcp/issues).
Use the upstream project only for upstream context and credit.

A fork-specific Desktop Extension is not published yet; use the token-based
`uvx` quick start above.

Contributions are welcome. Keep new AI-facing tools narrow, intention-oriented,
and built on the maintained backend rather than duplicating Garmin integration.

This project is distributed under the [MIT License](LICENSE).
