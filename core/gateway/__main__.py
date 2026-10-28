"""Run one gateway call from the shell and print the Completion as JSON.

    uv run --frozen python -m core.gateway classify "Locked out after MFA reset"

Exit code 0 when ok, 1 when the provider failed (the JSON still explains why), 2 on bad usage.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.gateway.base import TASKS, Task
from core.gateway.config import GatewayConfig
from core.gateway.gateway import Gateway
from core.paths import REPO_ROOT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m core.gateway", description="One model-gateway call (synthetic).")
    parser.add_argument("task", choices=TASKS)
    parser.add_argument("text")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repo root holding config/ and fixtures/")
    args = parser.parse_args(argv)
    task: Task = args.task
    completion = Gateway(GatewayConfig.load(args.root)).complete(task, args.text)
    print(completion.model_dump_json())
    return 0 if completion.ok else 1


if __name__ == "__main__":
    sys.exit(main())
