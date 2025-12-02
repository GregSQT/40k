"""
Repository rule checker for AI-related coding constraints.

Purpose:
- Enforce high-level coding rules (no implicit recovery on missing data, no inline
  magic values in core logic, etc.) by scanning the working tree.
- Provide clear, fail-fast feedback during development, pre-commit, or CI.

Usage:
    python scripts/check_ai_rules.py

Exit codes:
- 0: no violations detected
- 1: one or more violations detected
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable, List, Tuple


# Directories that are not scanned by this checker.
IGNORED_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".idea",
    ".vscode",
}

# File name patterns (suffixes) that are not scanned.
IGNORED_FILE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".pdf",
    ".ods",
    ".odp",
    ".log",
    ".stdout",
    ".stderr",
}


class RuleViolation:
    def __init__(self, path: Path, line_no: int, message: str, line_text: str) -> None:
        self.path = path
        self.line_no = line_no
        self.message = message
        self.line_text = line_text

    def format(self) -> str:
        return (
            f"{self.path}:{self.line_no}: {self.message}\n"
            f"    {self.line_text.rstrip()}"
        )


def iter_source_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue

        if any(part in IGNORED_DIR_NAMES for part in path.parts):
            continue

        if any(str(path).endswith(suffix) for suffix in IGNORED_FILE_SUFFIXES):
            continue

        yield path


def check_forbidden_terms(path: Path, text: str) -> List[RuleViolation]:
    """
    Detect textual patterns that are disallowed by the high-level rules.
    This is intentionally simple and conservative: it prefers false positives
    to missing an actual violation.
    """
    violations: List[RuleViolation] = []

    # Simple keyword blocks (case-insensitive) applied to code and comments.
    forbidden_patterns: List[Tuple[re.Pattern[str], str]] = [
        (
            re.compile(r"\bworkaround\b", re.IGNORECASE),
            "Use a proper, simple solution instead of a workaround.",
        ),
        (
            re.compile(r"\bfallback\b", re.IGNORECASE),
            "Do not rely on fallback behaviors; raise on missing data instead.",
        ),
        (
            re.compile(r"\bmagic number\b", re.IGNORECASE),
            "Replace magic numbers with named configuration values.",
        ),
    ]

    for idx, line in enumerate(text.splitlines(), start=1):
        for pattern, message in forbidden_patterns:
            if pattern.search(line):
                violations.append(RuleViolation(path, idx, message, line))

    return violations


def main(argv: List[str]) -> int:
    root = Path(__file__).resolve().parents[1]
    all_violations: List[RuleViolation] = []

    for file_path in iter_source_files(root):
        try:
            # Use UTF-8 with errors replaced to avoid hard failures on odd files.
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            # If a file cannot be read, report it explicitly as a violation.
            all_violations.append(
                RuleViolation(
                    file_path,
                    0,
                    "Unable to read file for rule checking.",
                    "",
                )
            )
            continue

        all_violations.extend(check_forbidden_terms(file_path, text))

    if not all_violations:
        print("check_ai_rules: no violations found.")
        return 0

    print("check_ai_rules: violations detected:\n")
    for violation in all_violations:
        print(violation.format())

    print(
        "\nFailing per repository AI coding rules. "
        "Please address the messages above before committing or merging."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))







