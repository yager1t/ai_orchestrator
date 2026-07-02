from __future__ import annotations

from pathlib import Path


def main() -> int:
    result_path = Path("SMOKE_RESULT.md")
    if not result_path.exists():
        print("SMOKE_RESULT.md was not created")
        return 1

    content = result_path.read_text(encoding="utf-8")
    required = ["# Real Agent Smoke Result", "status: done", "prompt_excerpt:"]
    missing = [item for item in required if item not in content]
    if missing:
        print(f"SMOKE_RESULT.md is missing required markers: {missing}")
        return 1

    print("smoke result verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
