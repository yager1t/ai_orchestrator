# 02 - Minimal YAML Parser (P2)

## Finding

The project still uses a minimal internal parser for `.ai-orch/config.yaml`. It intentionally
supports only the starter schema subset and does not support full YAML features such as anchors,
inline collections, multiline scalars, or all comment forms.

## Status

Deferred by ADR-0002.

## Resolution

The project keeps the minimal parser for now to avoid adding a production dependency before the
configuration format needs broader YAML compatibility.

See `docs/DECISIONS.md`:

- `ADR-0002: Defer PyYAML Until Config Needs Broader YAML Compatibility`

## Revisit When

- users need standard YAML features not supported by the minimal parser;
- config ownership moves beyond the starter schema;
- schema validation is introduced alongside a full YAML parser.
