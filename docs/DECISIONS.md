# Architectural Decisions

## ADR-0002: Defer PyYAML Until Config Needs Broader YAML Compatibility

Date: 2026-06-28

### Context

The MVP uses a small internal parser for `.ai-orch/config.yaml`. It supports the
current starter config shape and avoids adding a production dependency.

### Decision

Keep the minimal parser for now. Do not add PyYAML until the config format needs
broader YAML features such as anchors, nested arbitrary maps, multiline scalars,
or third-party generated YAML compatibility.

### Consequences

Pros:

- no new production dependency;
- predictable supported config subset;
- smaller packaging surface for the MVP.

Cons:

- config syntax remains intentionally limited;
- future YAML compatibility work may require a parser migration.

### Revisit When

- users need standard YAML features not supported by the minimal parser;
- config ownership moves beyond the starter schema;
- schema validation is introduced alongside a full YAML parser.

## ADR-0001: MVP Is a Supervisor over CLI Agents

Date: 2026-06-25

### Context

The project needs a local orchestrator for CLI-capable AI systems and coding
agents.

### Decision

The MVP core path is a control plane over CLI/headless interfaces, not a GUI
macro layer over application windows.

### Consequences

Pros:

- higher reliability;
- simpler logging;
- easier testing;
- easier task resume behavior;
- fewer UI dependencies.

Cons:

- some agents may need dedicated adapters;
- GUI automation remains only a fallback outside the MVP core path.

### Alternatives

- RPA-first automation over windows;
- full OpenHands integration;
- LangGraph/MAF as the first-day runtime.
