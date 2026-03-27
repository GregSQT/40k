#!/usr/bin/env python3
"""
Fail if deprecated static AI classification labels reappear in roster TS files.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys

FORBIDDEN_PATTERNS = (
    r"\bstatic\s+MOVE_TYPE\b",
    r"\bstatic\s+TANKING_LEVEL\b",
    r"\bstatic\s+TARGET_TYPE\b",
    r"\bstatic\s+OFFENSE_TYPE\b",
    r"AI CLASSIFICATION",
)


def collect_violations(project_root: Path) -> list[str]:
    """Collect forbidden pattern matches from roster unit/class TypeScript files."""
    roster_root = project_root / "frontend" / "src" / "roster"
    files = list(roster_root.glob("**/units/*.ts")) + list(roster_root.glob("**/classes/*.ts"))
    violations: list[str] = []
    compiled = [re.compile(pattern) for pattern in FORBIDDEN_PATTERNS]

    for file_path in files:
        content = file_path.read_text(encoding="utf-8")
        for regex in compiled:
            for match in regex.finditer(content):
                violations.append(
                    f"{file_path.relative_to(project_root)}: forbidden '{regex.pattern}'"
                )
                break

    return violations


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    violations = collect_violations(project_root)
    if violations:
        print("❌ Deprecated static roster labels detected:")
        for line in sorted(violations):
            print(f"  - {line}")
        print(
            "\nRemove static AI classification labels from roster TS files "
            "(MOVE_TYPE/TANKING_LEVEL/TARGET_TYPE/OFFENSE_TYPE and related comments)."
        )
        return 1

    print("✅ Roster static-label guard passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
