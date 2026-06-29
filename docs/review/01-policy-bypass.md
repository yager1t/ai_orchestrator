# 01 - Policy Engine Wrapper Bypass (P1)

## Finding

Earlier token-aware matching checked the first command token. That improved on substring
matching, but allowed dangerous commands hidden behind transparent wrappers:

```bash
env rm -rf /
sudo rm -rf /
FOO=bar rm -rf /
xargs rm -rf /
nice -n 10 rm -rf /
```

Newline-separated commands also needed to be treated as separate command segments.

## Status

Addressed.

## Resolution

- Added transparent wrapper peeling for built-in policy matching.
- Added newline normalization before command splitting.
- Added regression tests for `env`, assignment prefixes, `sudo`, `nice`, `xargs`, and newline-separated commands.

## Residual Risk

PolicyEngine is still defense-in-depth over trusted configuration and agent commands. It is
not a sandbox and does not provide complete shell semantics.
