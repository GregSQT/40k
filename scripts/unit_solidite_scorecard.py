#!/usr/bin/env python3
"""Scorecard binaire de solidite unitaire (OK/KO)."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "config" / "testing" / "unit_solidite_contract.json"
ANOMALIES_PATH = ROOT / "Documentation" / "KNOWN_ANOMALIES.md"
TESTS_ROOT = ROOT / "tests" / "unit"


@dataclass
class CheckResult:
    key: str
    ok: bool
    details: str


def _run_pytest(args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "pytest", *args]
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)


def _load_contract() -> dict[str, Any]:
    if not CONTRACT_PATH.exists():
        raise FileNotFoundError(f"Missing solidity contract: {CONTRACT_PATH}")
    with CONTRACT_PATH.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise TypeError("unit_solidite_contract.json must be an object")
    invariants = payload.get("invariants")
    if not isinstance(invariants, list) or len(invariants) == 0:
        raise ValueError("Contract must define a non-empty invariants array")
    return payload


def _check_contract_structure(contract: dict[str, Any]) -> CheckResult:
    invariants = contract["invariants"]
    bad_entries: list[str] = []
    for entry in invariants:
        if not isinstance(entry, dict):
            bad_entries.append(repr(entry))
            continue
        for required_key in ("id", "name", "nodeid"):
            value = entry.get(required_key)
            if not isinstance(value, str) or not value.strip():
                bad_entries.append(f"invalid {required_key} in {entry!r}")
    if bad_entries:
        return CheckResult(
            key="contract_structure",
            ok=False,
            details=f"{len(bad_entries)} invalid contract entries",
        )
    return CheckResult(
        key="contract_structure",
        ok=True,
        details=f"{len(invariants)} invariants declares",
    )


def _check_invariant_collection(invariants: list[dict[str, str]]) -> CheckResult:
    failures: list[str] = []
    for inv in invariants:
        nodeid = inv["nodeid"]
        result = _run_pytest(["--collect-only", "-q", nodeid])
        if result.returncode != 0:
            failures.append(nodeid)
    if failures:
        return CheckResult(
            key="invariant_collection",
            ok=False,
            details=f"cannot collect {len(failures)} nodeids",
        )
    return CheckResult(
        key="invariant_collection",
        ok=True,
        details=f"{len(invariants)} nodeids collectable",
    )


def _check_invariants_green(invariants: list[dict[str, str]]) -> CheckResult:
    nodeids = [inv["nodeid"] for inv in invariants]
    result = _run_pytest(["-q", *nodeids])
    if result.returncode != 0:
        return CheckResult(
            key="invariants_green",
            ok=False,
            details="one or more invariant tests failed",
        )
    return CheckResult(
        key="invariants_green",
        ok=True,
        details=f"{len(nodeids)} invariant tests passed",
    )


def _check_determinism(invariants: list[dict[str, str]]) -> CheckResult:
    nodeids = [inv["nodeid"] for inv in invariants]
    first = _run_pytest(["-q", *nodeids])
    second = _run_pytest(["-q", *nodeids])
    if first.returncode != 0 or second.returncode != 0:
        return CheckResult(
            key="determinism_smoke",
            ok=False,
            details="determinism smoke failed (at least one run is red)",
        )
    return CheckResult(
        key="determinism_smoke",
        ok=True,
        details="invariant suite green on two consecutive runs",
    )


def _extract_anomaly_statuses(markdown: str) -> dict[str, str]:
    statuses: dict[str, str] = {}
    current_id: str | None = None
    for line in markdown.splitlines():
        title = re.match(r"^##\s+(ANOM-\d+)\b", line.strip())
        if title:
            current_id = title.group(1)
            continue
        if current_id is None:
            continue
        status_match = re.match(r"^- Statut:\s*([a-zA-Z_]+)\s*$", line.strip())
        if status_match:
            statuses[current_id] = status_match.group(1).lower()
            current_id = None
    return statuses


def _check_anomaly_traceability() -> CheckResult:
    if not ANOMALIES_PATH.exists():
        return CheckResult("anomaly_traceability", False, "missing KNOWN_ANOMALIES.md")

    markdown = ANOMALIES_PATH.read_text(encoding="utf-8")
    statuses = _extract_anomaly_statuses(markdown)
    if not statuses:
        return CheckResult("anomaly_traceability", False, "no ANOM entries found")

    open_anomalies = {k for k, v in statuses.items() if v in {"ouvert", "en_cours"}}

    anomaly_tests = list(TESTS_ROOT.rglob("test_*.py"))
    anomaly_marked_files = 0
    xfail_mentions = 0
    for test_file in anomaly_tests:
        content = test_file.read_text(encoding="utf-8")
        if "@pytest.mark.anomaly" in content:
            anomaly_marked_files += 1
        if "pytest.mark.xfail" in content and "ANOM-" in content:
            xfail_mentions += 1

    if open_anomalies and xfail_mentions == 0:
        return CheckResult(
            "anomaly_traceability",
            False,
            f"{len(open_anomalies)} open anomalies but no xfail linked to ANOM id",
        )
    if anomaly_marked_files == 0:
        return CheckResult(
            "anomaly_traceability",
            False,
            "no test with @pytest.mark.anomaly found",
        )
    return CheckResult(
        "anomaly_traceability",
        True,
        f"{len(statuses)} anomalies tracked, {len(open_anomalies)} open, {anomaly_marked_files} anomaly-marked test files",
    )


def _build_report(results: list[CheckResult]) -> dict[str, Any]:
    all_ok = all(r.ok for r in results)
    return {
        "solidite_unitaire": "OK" if all_ok else "KO",
        "checks": [
            {"key": r.key, "ok": r.ok, "details": r.details}
            for r in results
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate unit solidity scorecard")
    parser.add_argument(
        "--output",
        default=str(ROOT / "reports" / "unit_solidite_scorecard.json"),
        help="Path to JSON report output",
    )
    args = parser.parse_args()

    try:
        contract = _load_contract()
        invariants = contract["invariants"]

        results = [
            _check_contract_structure(contract),
            _check_invariant_collection(invariants),
            _check_invariants_green(invariants),
            _check_determinism(invariants),
            _check_anomaly_traceability(),
        ]
        report = _build_report(results)
    except Exception as exc:  # explicit KO with message
        report = {
            "solidite_unitaire": "KO",
            "checks": [{"key": "scorecard_runtime", "ok": False, "details": str(exc)}],
        }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")

    print(f"SOLIDITE_UNITAIRE={report['solidite_unitaire']}")
    for check in report["checks"]:
        status = "OK" if check["ok"] else "KO"
        print(f"- [{status}] {check['key']}: {check['details']}")

    return 0 if report["solidite_unitaire"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
