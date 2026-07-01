from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: smoke_agent.py REPO PROMPT", file=sys.stderr)
        return 2

    repo = Path(argv[1])
    prompt = argv[2]
    output = repo / "SMOKE_RESULT.md"
    output.write_text(
        "\n".join(
            [
                "# Real Agent Smoke Result",
                "",
                "status: done",
                f"updated_at: {datetime.now(UTC).isoformat()}",
                "",
                "prompt_excerpt:",
                prompt[:500],
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
