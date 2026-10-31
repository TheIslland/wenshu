#!/usr/bin/env python
"""Fail if commit author/committer emails look like credentials.

A public repository exposes commit metadata forever. The most common accident is
putting a password, username, or phone number into ``git config user.email``.
This check runs in CI and can be run locally before pushing.
"""

from __future__ import annotations

import re
import subprocess

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NOREPLY_RE = re.compile(r"^[^@\s]+@users\.noreply\.github\.com$")


def main() -> int:
    try:
        raw = subprocess.check_output(
            ["git", "log", "--all", "--format=%ae%n%ce"], text=True, stderr=subprocess.PIPE
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"cannot read git history: {exc}")
        return 1
    bad: list[str] = []
    for email in {line.strip() for line in raw.splitlines() if line.strip()}:
        if not (EMAIL_RE.match(email) or NOREPLY_RE.match(email)):
            bad.append(email)
    if bad:
        print("commit identity check failed. These emails do not look like emails:")
        for email in sorted(bad):
            print(f"  - {email!r}")
        print(
            "\nFix: git config user.email 'you@example.com' or "
            "'username@users.noreply.github.com', then rewrite the offending commits."
        )
        return 1
    print("commit identity ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
