# 03 - Agent Secrets Management (P2)

## Finding

Agent credentials are expected to come from each CLI's native auth flow or process environment,
but stored agent and verification outputs could previously contain secret-like tokens.

## Status

Partially addressed.

## Resolution

- Added redaction for common secret-like token formats before storing agent output.
- Added redaction for verification stdout, stderr, and error fields.
- Added report-time redaction for markdown excerpts.
- Documented secret storage and PolicyEngine scope in `docs/SECURITY.md`.

## Residual Risk

Redaction only covers common token patterns. Secrets should still not be placed in prompts,
config, logs, command output, or reports. Future work may add explicit environment allowlists
for subprocess execution.
