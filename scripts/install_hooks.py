#!/usr/bin/env python
"""Install the local pre-commit guard (sensitive-info scan)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

HOOK = """#!/bin/sh
# wenshu-sensitive-guard
if [ -x ".venv/Scripts/python.exe" ]; then
  PY=".venv/Scripts/python.exe"
elif [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  PY="python3"
fi
"$PY" scripts/check_sensitive.py --staged || {
  echo "commit blocked: potential secret found. Fix it or run --all to audit."
  exit 1
}
"""


def repo_root() -> Path:
    out = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
    return Path(out)


def main() -> int:
    root = repo_root()
    hook = root / ".git" / "hooks" / "pre-commit"
    if hook.exists():
        existing = hook.read_text(encoding="utf-8", errors="ignore")
        if "wenshu-sensitive-guard" not in existing:
            print(f"{hook} already exists and is not ours; leaving it untouched.")
            print("Add this line to your hook if you want the scan:")
            print('  uv run --quiet python scripts/check_sensitive.py --staged || exit 1')
            return 1
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(HOOK, encoding="utf-8", newline="\n")
    try:
        os.chmod(hook, 0o755)
    except OSError:
        pass
    print(f"installed {hook}")
    print("try: git add <file> && git commit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
