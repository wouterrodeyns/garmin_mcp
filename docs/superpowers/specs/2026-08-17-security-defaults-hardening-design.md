# Security Defaults Hardening Design

Date: 2026-08-17

## Goal

Make the fork fail closed when an AI client omits security configuration, while
retaining an explicit upstream-compatible mode for maintainers and advanced
users. This PR addresses configuration and distribution risks found by the
2026-08-17 security audit. It does not redesign Garmin authentication, add MCP
OAuth, or change the behavior of individual Garmin tools.

## Scope

This PR will:

1. make `ai-coach` the default tool profile;
2. add an explicit `upstream-full` profile name for the complete Taxuspt tool
   surface;
3. configure the tracked OpenCode client to request `ai-coach` explicitly;
4. refuse unauthenticated non-loopback HTTP binds unless a deliberately named
   override is enabled;
5. ignore the documented local `secrets/` directory;
6. remove the stale upstream DXT manifest and tracked bundle;
7. update current user documentation and regression tests.

This PR will not:

- change Garmin token formats or authentication;
- add an authenticating HTTP proxy or MCP OAuth server;
- alter individual read/write tool implementations;
- add a confirmation protocol to `delete_workout`;
- remove upstream modules or tools from the codebase;
- modify historical design specifications or implementation plans.

Guarded workout deletion, public error-detail sanitization, legacy token-copy
cleanup, legacy FIT parser consolidation, and supply-chain hardening remain
separate follow-up work.

## Tool-profile behavior

The resolver will use the following precedence:

1. A non-empty `GARMIN_ENABLED_TOOLS` is an explicit allowlist and wins over
   every profile and denylist value, preserving current behavior.
2. Otherwise, `GARMIN_TOOL_PROFILE=upstream-full` exposes the complete registered
   upstream-compatible surface, minus `GARMIN_DISABLED_TOOLS`.
3. Otherwise, `GARMIN_TOOL_PROFILE=ai-coach` exposes the maintained `ai-coach`
   allowlist, minus `GARMIN_DISABLED_TOOLS`.
4. An unset, empty, or whitespace-only `GARMIN_TOOL_PROFILE` behaves exactly as
   `ai-coach`, minus `GARMIN_DISABLED_TOOLS`.
5. Every other non-empty profile value is rejected before Garmin authentication.

Profile names remain case-insensitive and surrounding whitespace is ignored.
`upstream-full` is a deliberate selector, not a set of duplicated tool names;
the existing register-all path remains the upstream-compatible implementation.

Startup output will make the selected policy visible. Default or explicit
`ai-coach` startup reports an active allowlist. Explicit `upstream-full` reports
that the full upstream-compatible surface is active. A zero-tool `ai-coach`
allowlist after denylist subtraction retains the current warning.

The tracked `opencode.json` will set `GARMIN_TOOL_PROFILE=ai-coach` even though it
is now the default. Explicit configuration documents intent and protects users
if defaults change in the future.

## HTTP transport guard

`stdio` remains the default and is unaffected by HTTP host validation.

For `streamable-http` and `sse`, these hosts are treated as local:

- IP literals for which Python's `ipaddress.ip_address(...).is_loopback` is true,
  including IPv4 and IPv6 loopback ranges;
- `localhost` and `localhost.` case-insensitively.

Any other host, including `0.0.0.0`, `::`, LAN addresses, public addresses, and
arbitrary DNS names, is rejected before Garmin authentication unless:

```text
GARMIN_MCP_ALLOW_UNAUTHENTICATED_REMOTE=true
```

The override accepts the project's established true values (`true`, `1`, and
`yes`, case-insensitively). Any absent or other value is false. The error is
fixed and contains no credentials or request data. It explains that this server
does not provide HTTP authentication and recommends an authenticating reverse
proxy. Supplying a non-loopback `GARMIN_MCP_HOST` with `stdio` does not fail,
because stdio opens no network listener.

This override is intentionally alarming. It acknowledges risk; it does not make
the HTTP endpoint secure.

## Credential-file protection

The repository `.gitignore` will contain `/secrets/`. Because `.dockerignore`
resolves to `.gitignore`, the same rule also excludes the directory from Docker
build context.

Documentation may continue to show Docker Compose secrets at:

```text
secrets/garmin_email.txt
secrets/garmin_password.txt
```

No real or example credentials will be committed. A regression test will use
Git's ignore behavior to prove both documented paths are ignored.

## DXT disposition

The tracked `garmin-mcp.dxt` bundle and `dxt/manifest.json` describe and install
the original Taxuspt repository with broad tools and credential fields. They do
not represent this fork and will be removed. Manifest/bundle consistency tests
that only validate those stale artifacts will be removed.

Current documentation will state that this fork does not distribute a DXT
package. A future DXT release must be designed independently around this fork,
token-based authentication, and the `ai-coach` profile.

## Documentation

README and setup documentation will state:

- `ai-coach` is the default;
- `upstream-full` is the explicit compatibility escape hatch;
- explicit allowlist and denylist precedence;
- non-loopback HTTP is refused unless the dangerous override is supplied;
- the override must only be used behind an authenticating reverse proxy;
- local credential files belong under ignored `/secrets/`;
- no fork-specific DXT is currently distributed.

Current documentation and tests will describe the actual sixteen-tool
`ai-coach` profile without changing that membership in this PR.

## Testing

Tests will be written before production/configuration changes and will cover:

1. unset, empty, and whitespace-only profiles select the exact `ai-coach` set;
2. explicit `ai-coach` remains identical;
3. `upstream-full` activates register-all behavior;
4. denylist subtraction works for default `ai-coach` and `upstream-full`;
5. explicit allowlist still overrides profiles and denylist;
6. unknown profiles still fail before Garmin initialization;
7. real FastMCP startup registers exactly sixteen tools by default;
8. OpenCode explicitly selects `ai-coach`;
9. stdio permits any unused host value;
10. HTTP accepts loopback IPv4, IPv6, and localhost names;
11. HTTP rejects wildcard, LAN, public, and arbitrary DNS hosts by default;
12. the explicit dangerous override permits a non-loopback HTTP host;
13. rejected HTTP configuration performs no Garmin authentication;
14. documented Docker credential paths are ignored by Git;
15. stale DXT artifacts are absent and docs do not advertise their installation;
16. existing zero-tool and unknown-filter diagnostics remain intact.

After focused red-green cycles, verification will run:

```bash
uv run pytest -m "not e2e" -q
git diff --check
```

No normal test requires Garmin credentials or network access.

## Compatibility and rollout

The default-profile change is intentionally backward-incompatible for callers
that relied on an unset profile to expose all upstream tools. Those callers must
set:

```text
GARMIN_TOOL_PROFILE=upstream-full
```

The server will continue to contain and register all upstream modules in that
mode, keeping future Taxuspt synchronization straightforward. The change affects
only which tools are visible when configuration is absent.

The completed work will be opened as a normal ready-for-review pull request
against `main`, not as a draft.
