#!/usr/bin/env python3
"""
Check that frontend/src/roster/unit_matrix.json is up to date.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from check_roster_static_labels import collect_violations
from unit_matrix_generate import generate_matrix


def main() -> int:
    """Return 0 when matrix file is up to date, 1 otherwise."""
    project_root = Path(__file__).resolve().parent.parent

    # Guard against reintroduction of deprecated static AI classification labels.
    roster_violations = collect_violations(project_root)
    if roster_violations:
        print("❌ Deprecated static roster labels detected:")
        for violation in sorted(roster_violations):
            print(f"  - {violation}")
        return 1

    matrix_path = project_root / "frontend" / "src" / "roster" / "unit_matrix.json"

    if not matrix_path.exists():
        print(
            "❌ Missing unit agent matrix file: "
            f"{matrix_path}\n"
            "Run: python scripts/unit_matrix_generate.py"
        )
        return 1

    current_payload = json.loads(matrix_path.read_text(encoding="utf-8"))
    expected_payload = generate_matrix(project_root)

    # generated_at is runtime-specific, so it is excluded from drift checks.
    current_payload["generated_at"] = "<ignored>"
    expected_payload["generated_at"] = "<ignored>"

    if current_payload != expected_payload:
        print(
            "❌ unit_matrix.json is out of date.\n"
            "Run: python scripts/generate_unit_agent_matrix.py"
        )
        return 1

    print("✅ unit_matrix.json is up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
