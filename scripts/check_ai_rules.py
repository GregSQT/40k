#!/usr/bin/env python3
"""
AI rules checker for AI_TURN.md and coding_practices.mdc compliance.

Purpose:
- Detect cache recalculation violations (build_enemy_adjacent_hexes, build_position_cache)
- Verify coordinate normalization (no direct col/row comparisons; supports "col"/'col')
- Detect anti-error fallbacks (.get with None, 0, [], {}); standalone or followed by if)
  For voluntary .get on optional keys (config, feature flags), add "# get allowed" or "# fallback allowed" on the same line to avoid false positives.
- Check AI_TURN.md specific patterns (end_activation with constants, not strings)
- Detect forbidden terms (workaround, fallback, magic number); skip comment lines that document the prohibition

Lines containing \"\"\" are ignored for col/row checks (to avoid flagging example code in docstrings); violations inside docstrings/strings are false negatives (accepted trade-off).

Usage:
    python scripts/check_ai_rules.py [--path PATH]

Exit codes:
- 0: no violations detected
- 1: one or more violations detected
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable, List, Optional

# Directories that are not scanned by this checker.
IGNORED_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".idea",
    ".vscode",
    "check",
    "scripts",
}

# File name patterns (suffixes) that are not scanned.
IGNORED_FILE_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".pdf", ".ods", ".odp",
    ".log", ".stdout", ".stderr",
    ".zip", ".pyc",
}

# Files to scan (only engine and ai directories)
SCAN_PATTERNS = [
    "engine/**/*.py",
    "ai/**/*.py",
]


class RuleViolation:
    def __init__(self, path: Path, line_no: int, message: str, line_text: str, rule_type: str = "general") -> None:
        self.path = path
        self.line_no = line_no
        self.message = message
        self.line_text = line_text
        self.rule_type = rule_type

    def format(self) -> str:
        return (
            f"{self.path}:{self.line_no} [{self.rule_type}]: {self.message}\n"
            f"    {self.line_text.rstrip()}"
        )


def iter_source_files(root: Path, scan_path: Optional[Path] = None) -> Iterable[Path]:
    """Iterate over Python source files to check."""
    if scan_path:
        if scan_path.is_file() and scan_path.suffix == ".py":
            yield scan_path
        elif scan_path.is_dir():
            for path in scan_path.rglob("*.py"):
                if not any(part in IGNORED_DIR_NAMES for part in path.parts):
                    yield path
        return

    # Default: scan engine/ and ai/
    for pattern in SCAN_PATTERNS:
        for path in root.glob(pattern):
            if path.is_file() and path.suffix == ".py":
                if not any(part in IGNORED_DIR_NAMES for part in path.parts):
                    yield path


def check_cache_recalculations(path: Path, text: str) -> List[RuleViolation]:
    """
    Detect unnecessary cache recalculations.

    Violations:
    - build_enemy_adjacent_hexes() called outside phase_start functions
    - build_position_cache() called outside phase_start functions
    """
    violations: List[RuleViolation] = []

    # Functions that should only be called in phase_start
    cache_functions = [
        ("build_enemy_adjacent_hexes", "enemy_adjacent_hexes cache should be built once at phase start, not recalculated"),
        ("build_position_cache", "position_cache should be built once at phase start, not recalculated"),
    ]

    lines = text.splitlines()

    # Track whether we're inside a phase_start function (def at column 0 matching *_phase_start)
    in_phase_start = False
    phase_start_pattern = re.compile(r"def\s+(\w+_phase_start|phase_start)\s*\(")

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()

        # Entering phase_start: def at column 0
        if not line.startswith(" ") and not line.startswith("\t") and phase_start_pattern.search(line):
            in_phase_start = True
            continue

        # Leaving: next top-level def (column 0)
        if in_phase_start and stripped.startswith("def ") and not line.startswith(" ") and not line.startswith("\t"):
            in_phase_start = False

        # Skip if inside phase_start
        if in_phase_start:
            continue

        for func_name, message in cache_functions:
            if re.search(rf"def\s+{func_name}\s*\(", line):
                continue
            if re.search(rf"from\s+.*\s+import.*{re.escape(func_name)}|import.*{re.escape(func_name)}", line):
                continue
            if "#" in line:
                comment_pos = line.find("#")
                func_pos = line.find(func_name)
                if func_pos > comment_pos:
                    continue
            if '"""' in line or "'''" in line:
                continue

            call_pattern = re.compile(rf"\b{re.escape(func_name)}\s*\(")
            if not call_pattern.search(line):
                continue

            if re.search(rf"(raise|ValueError|KeyError|Exception).*{re.escape(func_name)}", line, re.IGNORECASE):
                continue
            if re.search(rf"(use|call|must|should).*{re.escape(func_name)}", line, re.IGNORECASE):
                code_part = line.split("#")[0].replace('"""', "").replace("'''", "")
                if not call_pattern.search(code_part):
                    continue

            violations.append(RuleViolation(
                path, idx,
                f"{message}. Found in non-phase_start function.",
                line,
                "cache_recalculation"
            ))
            break

    return violations


def check_coordinate_normalization(path: Path, text: str) -> List[RuleViolation]:
    """
    Detect direct coordinate comparisons without normalization.

    Violations:
    - Direct comparisons: unit["col"] == other["col"] or unit['col'] == other['col']
    - Same for "row" / 'row'
    - Should use get_unit_coordinates() or normalize_coordinates()
    """
    violations: List[RuleViolation] = []

    lines = text.splitlines()

    # Patterns: support both double and single quotes
    patterns = [
        (re.compile(r'\[["\']col["\']\]\s*[=!<>]+\s*\w+\[["\']col["\']\]'),
         "Direct col comparison without normalization. Use get_unit_coordinates() or normalize_coordinates()"),
        (re.compile(r'\[["\']row["\']\]\s*[=!<>]+\s*\w+\[["\']row["\']\]'),
         "Direct row comparison without normalization. Use get_unit_coordinates() or normalize_coordinates()"),
        (re.compile(r'\w+\[["\']col["\']\]\s*[=!<>]+\s*\w+\[["\']col["\']\]'),
         "Direct col comparison without normalization. Use get_unit_coordinates() or normalize_coordinates()"),
        (re.compile(r'\w+\[["\']row["\']\]\s*[=!<>]+\s*\w+\[["\']row["\']\]'),
         "Direct row comparison without normalization. Use get_unit_coordinates() or normalize_coordinates()"),
    ]

    allowed_patterns = [
        re.compile(r'get_unit_coordinates'),
        re.compile(r'normalize_coordinates'),
        re.compile(r'#.*normalize'),
        re.compile(r'"""'),
    ]

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        if any(ap.search(line) for ap in allowed_patterns):
            continue
        for pattern, message in patterns:
            if pattern.search(line):
                violations.append(RuleViolation(path, idx, message, line, "coordinate_normalization"))
                break

    return violations


def check_fallback_anti_error(path: Path, text: str) -> List[RuleViolation]:
    """
    Detect anti-error fallbacks.

    Violations:
    - .get(key, None), .get(key, 0), .get(key, []), .get(key, {})
    - Signal even without "if" on next line; use require_key() or explicit KeyError.
    """
    violations: List[RuleViolation] = []

    lines = text.splitlines()

    fallback_patterns = [
        (re.compile(r'\.get\([^,]+,\s*None\)'),
         "Fallback to None may hide missing data. Use require_key() or explicit KeyError."),
        (re.compile(r'\.get\([^,]+,\s*0\)'),
         "Fallback to 0 may hide missing data. Use require_key() or explicit KeyError."),
        (re.compile(r'\.get\([^,]+,\s*\[\]\)'),
         "Fallback to [] may hide missing data. Use require_key() or explicit KeyError."),
        (re.compile(r'\.get\([^,]+,\s*\{\}\)'),
         "Fallback to {} may hide missing data. Use require_key() or explicit KeyError."),
    ]

    allowed_contexts = [
        re.compile(r'require_key\s*\('),
        re.compile(r'require_present\s*\('),
        re.compile(r'#\s*(fallback|get).*allowed', re.IGNORECASE),
        re.compile(r'#\s*TODO.*fix', re.IGNORECASE),
        re.compile(r'#\s*exception.*get', re.IGNORECASE),
    ]

    for idx, line in enumerate(lines, start=1):
        if any(ac.search(line) for ac in allowed_contexts):
            continue
        for pattern, message in fallback_patterns:
            if pattern.search(line):
                violations.append(RuleViolation(path, idx, message, line, "fallback_anti_error"))
                break

    return violations


def check_forbidden_terms(path: Path, text: str) -> List[RuleViolation]:
    """
    Detect forbidden terms (workaround, fallback, magic number).

    Skip lines that document the prohibition (e.g. "no fallback", "fallback forbidden", "do not use workaround").
    """
    violations: List[RuleViolation] = []

    forbidden_patterns = [
        (re.compile(r"\bworkaround\b", re.IGNORECASE),
         "Use a proper, simple solution instead of a workaround."),
        (re.compile(r"\bfallback\b", re.IGNORECASE),
         "Do not rely on fallback behaviors; raise on missing data instead."),
        (re.compile(r"\bmagic\s+number\b", re.IGNORECASE),
         "Replace magic numbers with named configuration values."),
    ]

    # Comment lines that document the rule (skip these)
    prohibition_comment_terms = [
        "no fallback", "no workaround", "no magic number",
        "fallback forbidden", "workaround forbidden", "interdit", "forbidden",
        "do not use fallback", "do not use workaround", "do not use magic",
        "ne pas utiliser", "avoid fallback", "avoid workaround", "éviter",
        "pas de fallback", "pas de workaround",
    ]

    for idx, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        # Skip full-line comments that document the prohibition
        if stripped.startswith("#"):
            comment_lower = stripped[1:].strip().lower()
            if any(term in comment_lower for term in prohibition_comment_terms):
                continue
        # Skip lines that are documentation of the rule (allowed/exception/todo)
        if "#" in line and any(term in line.lower() for term in ["allowed", "exception", "todo"]):
            continue

        for pattern, message in forbidden_patterns:
            if pattern.search(line):
                violations.append(RuleViolation(path, idx, message, line, "forbidden_term"))
                break

    return violations


def check_end_activation_patterns(path: Path, text: str) -> List[RuleViolation]:
    """
    Check end_activation() calls use proper constants, not string literals.
    """
    violations: List[RuleViolation] = []

    end_activation_pattern = re.compile(r'end_activation\s*\(')
    string_literal_pattern = re.compile(r'["\'](ACTION|WAIT|NO|ERROR|MOVE|SHOOTING|CHARGE|FIGHT|FLED|ADVANCE|PASS|NOT_REMOVED)["\']')

    for idx, line in enumerate(text.splitlines(), start=1):
        if end_activation_pattern.search(line) and string_literal_pattern.search(line):
            violations.append(RuleViolation(
                path, idx,
                "end_activation() should use constants, not string literals. Import from shared_utils.",
                line,
                "end_activation_pattern"
            ))

    return violations


def main(argv: List[str]) -> int:
    """Main entry point."""
    root = Path(__file__).resolve().parents[1]
    scan_path: Optional[Path] = None

    if len(argv) > 0:
        if argv[0] == "--path":
            if len(argv) <= 1:
                print("Error: --path requires a path argument.", file=sys.stderr)
                return 1
            scan_path = Path(argv[1]).resolve()
            if not scan_path.exists():
                print(f"Error: Path does not exist: {scan_path}", file=sys.stderr)
                return 1
        elif argv[0] in ["-h", "--help"]:
            print(__doc__)
            return 0

    all_violations: List[RuleViolation] = []
    log_path = root / "check_ai_rules.log"
    log_lines: List[str] = []

    log_lines.append("AI Rules Checker (check_ai_rules)")
    log_lines.append("=" * 70)
    log_lines.append("")

    for file_path in iter_source_files(root, scan_path):
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            all_violations.append(
                RuleViolation(file_path, 0, f"Unable to read file: {e}", "", "file_error")
            )
            continue

        all_violations.extend(check_cache_recalculations(file_path, text))
        all_violations.extend(check_coordinate_normalization(file_path, text))
        all_violations.extend(check_fallback_anti_error(file_path, text))
        all_violations.extend(check_forbidden_terms(file_path, text))
        all_violations.extend(check_end_activation_patterns(file_path, text))

    violations_by_type: dict[str, List[RuleViolation]] = {}
    for v in all_violations:
        if v.rule_type not in violations_by_type:
            violations_by_type[v.rule_type] = []
        violations_by_type[v.rule_type].append(v)

    if not all_violations:
        log_lines.append("✅ No violations detected.")
        log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
        print("✅ check_ai_rules.py : Aucune erreur détectée   -   Output : check_ai_rules.log")
        return 0

    log_lines.append(f"❌ {len(all_violations)} violation(s) detected:\n")
    for rule_type, vlist in sorted(violations_by_type.items()):
        log_lines.append(f"\n[{rule_type.upper()}] {len(vlist)} violation(s):")
        log_lines.append("-" * 70)
        for v in vlist:
            log_lines.append(v.format())

    log_lines.append("\n" + "=" * 70)
    log_lines.append("Failing per repository AI coding rules.")
    log_lines.append("Please address the messages above before committing or merging.")
    log_lines.append("=" * 70)

    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    for rule_type, vlist in sorted(violations_by_type.items()):
        print(f"[{rule_type.upper()}] {len(vlist)} violation(s)")
    n = len(all_violations)
    print(f"⚠️  check_ai_rules.py : {n} erreur(s) détectée(s)   -   Output : check_ai_rules.log")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
