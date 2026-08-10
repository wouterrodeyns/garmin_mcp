# AI-Coach README Redesign

## Objective

Redesign the repository README as a concise, accurate landing page for Garmin
AI-coaching users. The landing page must make the intended product clear:

```text
get_training_context   # factual coaching context (eyes)
create_workout         # intentional Garmin workout creation (hands)
```

The fork keeps Taxuspt's maintained Garmin integration and broad
upstream-compatible surface, but its primary documented experience is a narrow,
safe AI-coach workflow. The README must direct end users to this fork, use
token-based authentication, recommend `GARMIN_TOOL_PROFILE=ai-coach`, and avoid
teaching an LLM to generate raw Garmin workout DTOs.

This is a documentation-only change. It must not alter the MCP runtime,
authentication implementation, DXT artifact, tool registration, Docker files,
or Garmin API behavior.

## Scope and Files

Implementation changes these documentation/test files:

- `README.md` — replace the current upstream-centric, long-form landing page
  with the concise AI-coach landing page specified below.
- `docs/setup.md` — add the detailed setup and deployment reference migrated
  from README, with this fork's URLs and the same security policy.
- `.gitignore` — explicitly allow the new tracked `docs/setup.md`; the repository
  otherwise ignores new files directly under `docs/`.
- `tests/unit/test_readme_docs.py` — add focused, text-level documentation
  regression tests for README and setup guidance.

Existing README assertions in `tests/unit/test_ai_workouts_docs.py` may be
updated only when the redesign makes their old landing-page wording obsolete.
Their dedicated `docs/ai-workouts.md` contract coverage must remain unchanged.

Existing detailed product references remain authoritative and are linked rather
than duplicated:

- `docs/ai-training.md` for normalized training-context fields, bounded reads,
  optional metrics, and warning/status semantics.
- `docs/ai-workouts.md` for the human-readable workout schema, compiler
  behavior, supported sports/actions/targets, and create result semantics.

`dxt/manifest.json` is deliberately untouched in this PR. It currently points
at upstream and advertises a credential prompt, so README must not promote DXT
installation until a separate fork-specific release and manifest decision.

## README Structure

The finished README should be approximately 150–220 lines of useful content,
not an exhaustive endpoint catalog. It uses the following ordered sections.

### 1. Title, purpose, and upstream attribution

Title the page **Garmin MCP for AI Coaching**. Lead with a short statement that
this is a purpose-built Garmin MCP for AI coaching and workout creation. State
that it is a fork of, and remains intentionally compatible with, Taxuspt's
maintained Garmin MCP backend. Link to:

- `https://github.com/wouterrodeyns/garmin_mcp` as the project/install source;
- `https://github.com/Taxuspt/garmin_mcp` as the upstream project; and
- `https://github.com/cyberjunky/python-garminconnect` as the Garmin client
  dependency.

State concisely that Garmin Connect is accessed through an unofficial client and
that Garmin data/metric availability varies by account, device, subscriptions,
and sync state. Do not retain Taxuspt's third-party security-assessment badge:
it evaluates a different repository.

### 2. Designed AI-coach workflow

Present the two flagship tools in a small table or short list:

- `get_training_context(days=14)`: a compact, read-only snapshot used before
  coaching decisions; link to `docs/ai-training.md`.
- `create_workout(...)`: validates a readable workout schema, uploads it, and
  optionally schedules it in one high-level write; link to
  `docs/ai-workouts.md`.

Include a short workflow:

```text
User: Review my last 30 days and recommend today's run.
AI:   get_training_context(days=30) -> factual context -> conservative advice.

User: Put that workout on Garmin for tomorrow.
AI:   create_workout(..., schedule_date="YYYY-MM-DD") -> upload + schedule.
```

The copy must explain that a `null` current recovery/fitness metric means it was
not available in this snapshot; it does **not** establish that the account or
device cannot support it. It should tell the AI to use structured warnings and
actual metric dates, and to avoid treating stale or unsynced data as current.
The write flow must explicitly recommend explaining the proposed workout and
getting user confirmation before `create_workout` schedules it.

### 3. Claude Desktop quick start

Provide the primary end-user setup path in four short steps:

1. Install `uv` with a link to its official installation page.
2. Authenticate interactively outside the MCP client:

   ```bash
   uvx --python 3.12 --from git+https://github.com/wouterrodeyns/garmin_mcp garmin-mcp-auth
   ```

3. Add a Claude Desktop configuration that launches this fork and includes:

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

4. Restart Claude Desktop and use the example prompt/workflow.

The quick-start prose must say plainly: do not put Garmin email addresses,
passwords, MFA codes, or tokens in the Claude Desktop MCP configuration. The
interactive `garmin-mcp-auth` flow stores local tokens and is the recommended
authentication method. The exact Claude config file locations and alternative
client/install variants belong in `docs/setup.md`.

### 4. AI-coach tool profile and safety

Document that `GARMIN_TOOL_PROFILE=ai-coach` exposes exactly these 11 tools:

```text
get_training_context
create_workout
get_activities
get_activities_by_date
get_activity
get_workouts
get_workout_by_id
get_scheduled_workouts
schedule_workout
unschedule_workout
delete_workout
```

Describe this as the recommended profile for AI coaching. Explain that activity
and coaching-context reads are read-only while workout operations are deliberate
writes. State that `GARMIN_ENABLED_TOOLS` has precedence and
`GARMIN_DISABLED_TOOLS` subtracts from the selected profile.

Keep a short advanced-use note: when no profile or explicit allowlist is set,
the server retains its broad upstream-compatible tool registration. Do not give
an exact tool count, a percentage of upstream coverage, endpoint-category
counts, or marketing claims that drift with upstream changes.

### 5. Further documentation and development

Link to:

- `docs/ai-training.md` — training context contract;
- `docs/ai-workouts.md` — workout schema and compiler contract; and
- `docs/setup.md` — detailed client setup, local development, transports,
  Docker, Garmin China, MFA/token recovery, and troubleshooting.

Provide concise developer setup:

```bash
git clone https://github.com/wouterrodeyns/garmin_mcp.git
cd garmin_mcp
uv sync
uv run pytest -m "not e2e"
```

State the supported baseline accurately as Python 3.10+ (the quick-start
examples may choose Python 3.12). Do not claim a fixed passing-test count or
percentage. Mention that live E2E tests require a real Garmin account and are
run separately, with commands in `docs/setup.md`.

### 6. Compatibility, contribution, and license

Close with a compact statement of intentional divergence: fork-specific AI
abstractions live in separate packages and wrap Taxuspt's backend so future
upstream sync remains practical. Keep contributor/issue and license links,
using the wouterrodeyns repository for fork issues and Taxuspt only for upstream
credit/context.

## Content Migration Map

The implementation moves, compresses, or removes existing README material as
follows.

| Current README material | Destination/action |
|---|---|
| Feature catalog, tool coverage totals, endpoint categories | Remove from the landing page. Replace with the broad upstream-compatible surface note. |
| Activity-file download, skipped-endpoint explanations | Move only useful operational detail to `docs/setup.md` or omit from v1 README; do not retain an endpoint catalog. |
| Tool filtering | Condense the precedence/profile behavior in README; retain detailed examples in `docs/setup.md`. |
| AI training context and AI-friendly workout sections | Replace legacy/builders material with the flagship-tool section and links to their dedicated docs. |
| Legacy workout builder walkthroughs and raw `upload_workout` DTO/end-condition/target tutorials | Remove from README. They conflict with the friendly-schema-first AI-coach experience; advanced raw API material is not promoted here. |
| One-click DXT install/build instructions | Remove from README. Do not change DXT files in this PR. |
| Claude Desktop setup, Codex setup, opencode setup | Keep one secure Claude quick start in README; move all detailed/alternate client instructions to `docs/setup.md`. |
| Development setup, runtime configuration, transports, MCP Inspector | Move detailed reference to `docs/setup.md`; keep only concise developer setup in README. |
| Garmin China, Docker, file-based secrets, MFA, token recovery | Move to `docs/setup.md`; retain the README's token-first security summary. |
| Usage examples | Replace with the AI-coach workflow and confirmation-before-write example. |
| Troubleshooting and client log paths | Move to `docs/setup.md`. |
| Test count/percentage and detailed test structure | Remove volatile claims; preserve stable test commands only. |
| Local Windows personal reinstall path | Remove. |

`docs/setup.md` is a reference document, not a second marketing landing page.
It must preserve useful technical detail while applying the install URL and
security rules below. It should use clear headings for Claude Desktop, Codex,
opencode, local development, runtime configuration/tool filtering, transport,
Docker, Garmin China, MFA/token recovery, tests, and troubleshooting. It may
link back to README for product orientation.

## Link and Branding Policy

All user-facing clone, `uvx --from`, package-source, issue, release, and
configuration examples must use this fork:

```text
https://github.com/wouterrodeyns/garmin_mcp
```

Taxuspt links are allowed only when explicitly labelled as upstream attribution,
compatibility context, or upstream source credit. `python-garminconnect` links
remain allowed as dependency documentation. README must not link to a Taxuspt
release, clone URL, or install source.

README must not advertise a DXT download, a DXT one-click installation flow, or
a release artifact. It may state that a fork-specific Desktop Extension is not
published yet and direct users to the token-based `uvx` quick start instead.

## Security Rules

The README and `docs/setup.md` must:

- recommend one-time interactive `garmin-mcp-auth` authentication before an MCP
  client starts;
- use local token storage as the normal path;
- never include `GARMIN_EMAIL`, `GARMIN_PASSWORD`, `GARMIN_PASSWORD_FILE`,
  literal credential placeholders, or MFA codes in an MCP client configuration
  block;
- never instruct users to save credentials in Claude Desktop configuration;
- state that workout writes are intentional and the AI should request
  confirmation before scheduling/creating a proposed workout; and
- avoid output examples containing access tokens, Garmin payload dumps, or
  sensitive health data.

Advanced credential/file-secret guidance may remain in `docs/setup.md` only for
non-interactive deployments such as Docker. It must be clearly separated from
Claude Desktop configuration, use non-real placeholders, state the associated
risk, and direct normal desktop users to token pre-authentication.

## Documentation Test Acceptance

Add `tests/unit/test_readme_docs.py` to pin the product and security contract.
The tests must be deterministic text-level assertions and must not require a
Garmin account, network request, DXT build, or MCP server start. They must cover
at least:

1. README identifies the fork as AI-coach focused, names both flagship tools,
   and links both dedicated guides.
2. README quick-start authentication and all README installation/configuration
   source URLs point to `wouterrodeyns/garmin_mcp`.
3. Taxuspt appears only in explicitly labelled upstream attribution text; no
   Taxuspt clone/install/release URL appears in README or `docs/setup.md`.
4. README contains an `ai-coach` configuration example and the exact 11-tool
   profile vocabulary.
5. README retains profile/allowlist/denylist precedence and explains the full
   upstream-compatible default without an exact broad-surface tool count.
6. README contains the snapshot-scoped missing-data wording, sync/staleness
   caution, and confirmation-before-write guidance.
7. README does not promote DXT installation or a DXT release artifact.
8. Claude Desktop, Codex, and opencode MCP configuration code blocks do not
   contain Garmin email/password/MFA/token environment variables or
   credential-looking placeholders. This does not prohibit the explicitly
   separated Docker/file-secret deployment guidance allowed by the security
   rules above.
9. README contains no raw workout DTO/`upload_workout` tutorial, stale legacy
   builder names, fixed coverage percentages, `110+`, `100%`, stale exact test
   counts, or the personal Windows reinstall path.
10. `docs/setup.md` exists, links to this fork for all end-user installs, and
    contains the migrated setup/deployment headings and stable offline/E2E test
    commands.

Update existing documentation tests only if a README assertion they own becomes
incorrect due to the concise redesign. Preserve their coverage of the dedicated
AI workout/training documents; do not weaken those contracts just to make the
new README pass.

## Non-goals

- No code, configuration, DXT manifest, Docker, release, authentication, or MCP
  profile behavior changes.
- No fork-specific DXT packaging or release publication.
- No expansion of the AI-coach tool set or Garmin write surface.
- No redesign of `get_training_context`, `create_workout`, their schemas, or
  their dedicated documentation.
- No raw Garmin DTO tutorial in the README.
- No claim that all Garmin health/recovery metrics are available for every
  account, device, or unsynced watch.

## Upstream Compatibility

This documentation change describes a fork-specific product focus while keeping
the underlying code deliberately easy to sync with Taxuspt. It must not rewrite
or conceal the broad upstream-compatible server. Instead, it explains the
recommended narrow profile first and makes the broader surface an explicit
advanced option. The README credits Taxuspt clearly, but every instruction a
user could copy to install or configure the product uses this fork.
