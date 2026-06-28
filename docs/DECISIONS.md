# Architectural Decisions

## ADR-0002: Defer PyYAML Until Config Needs Broader YAML Compatibility

Date: 2026-06-28

### Context

The MVP uses a small internal parser for `.ai-orch/config.yaml`. It supports the current starter config shape and avoids adding a production dependency.

### Decision

Keep the minimal parser for now. Do not add PyYAML until the config format needs broader YAML features such as anchors, nested arbitrary maps, multiline scalars, or third-party generated YAML compatibility.

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

## ADR-0001: MVP строится как supervisor над CLI-агентами

Дата: 2026-06-25

### Контекст

Есть задача создать оркестратор для локальных ИИ-систем и CLI-агентов.

### Решение

Core-path MVP строится как control plane над CLI/headless-интерфейсами, а не как GUI-макрос поверх окон.

### Последствия

Плюсы:

- выше надёжность;
- проще логировать;
- проще тестировать;
- проще возобновлять задачи;
- меньше зависимости от UI.

Минусы:

- для некоторых агентов придётся писать adapter;
- GUI automation останется только fallback.

### Альтернативы

- RPA-first подход поверх окон;
- полноценная интеграция с OpenHands;
- LangGraph/MAF как runtime с первого дня.
