#!/usr/bin/env python
"""Scan staged changes or tracked files for credentials before they go public.

Usage:
    python scripts/check_sensitive.py --staged   # pre-commit
    python scripts/check_sensitive.py --all      # CI / manual audit

Exit code 1 when something looks like a real secret. Placeholders such as
``sk-test``, ``your-api-key``, ``change-me`` are ignored on purpose.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

SKIP_PATHS = (
    "docs/",
    "skills/",
    "README.md",
    "NOTICE.md",
    "CHANGELOG.md",
    "uv.lock",
    "src/wenshu/static/csl/",
    "src/wenshu/static/vendor/",
)
SKIP_SUFFIXES = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".docx",
    ".zip",
    ".gz",
    ".woff",
    ".woff2",
    ".ttf",
    ".pyc",
)
PLACEHOLDER = re.compile(
    r"(?i)(test|demo|fake|dummy|example|placeholder|your[-_]?|xxxx|123456|"
    r"change[-_]?me|replace[-_]?me|redacted|not[-_]?a[-_]?real)"
)

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("OpenAI/DeepSeek-style key", re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{18,}")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("Hugging Face token", re.compile(r"\bhf_[A-Za-z0-9]{20,}")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    (
        "secret assignment",
        re.compile(
            r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|"
            r"auth[_-]?token|client[_-]?secret)\b\s*[:=]\s*[\"']([^\"']{8,})[\"']"
        ),
    ),
]


def _skip(path: str) -> bool:
    if any(path.startswith(prefix) for prefix in SKIP_PATHS):
        return True
    return path.lower().endswith(SKIP_SUFFIXES)


def scan_line(path: str, line_no: int, line: str) -> list[str]:
    findings: list[str] = []
    for name, pattern in PATTERNS:
        for match in pattern.finditer(line):
            value = match.group(1) if match.lastindex else match.group(0)
            if PLACEHOLDER.search(value):
                continue
            findings.append(f"{path}:{line_no}: {name}")
            break
    return findings


def scan_staged() -> list[str]:
    try:
        diff = subprocess.check_output(
            ["git", "diff", "--cached", "--unified=0"], text=True, stderr=subprocess.PIPE
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"cannot read staged diff: {exc}", file=sys.stderr)
        return []
    findings: list[str] = []
    path = ""
    line_no = 0
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
            continue
        if line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            line_no = int(match.group(1)) if match else 0
            continue
        if line.startswith("+") and not line.startswith("+++"):
            if path and not _skip(path):
                findings.extend(scan_line(path, line_no, line[1:]))
            line_no += 1
    return findings


def scan_all() -> list[str]:
    try:
        raw = subprocess.check_output(["git", "ls-files", "-z"], stderr=subprocess.PIPE)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"cannot list tracked files: {exc}", file=sys.stderr)
        return []
    findings: list[str] = []
    for item in raw.split(b"\0"):
        if not item:
            continue
        path = item.decode("utf-8", "replace")
        if _skip(path):
            continue
        file_path = Path(path)
        if not file_path.is_file() or file_path.stat().st_size > 2_000_000:
            continue
        data = file_path.read_bytes()
        if b"\0" in data:
            continue
        text = data.decode("utf-8", "ignore")
        for line_no, line in enumerate(text.splitlines(), start=1):
            findings.extend(scan_line(path, line_no, line))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--staged", action="store_true", help="scan staged additions")
    group.add_argument("--all", action="store_true", help="scan every tracked text file")
    args = parser.parse_args()
    findings = scan_staged() if args.staged else scan_all()
    if findings:
        print("potential secrets found:")
        for item in findings:
            print("  " + item)
        print(
            "\nRemove the value, rotate the credential, then stage the change again. "
            "If it is a deliberate placeholder, make it obvious (test/example/change-me)."
        )
        return 1
    print("sensitive-info scan ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
