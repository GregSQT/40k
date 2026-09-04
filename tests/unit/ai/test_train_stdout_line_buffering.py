"""`import ai.train` rend stdout/stderr line-buffered, TTY ou pas.

Hors TTY (`| tee`, le mode nominal des runs) Python bufferise stdout par blocs de 8 Ko : le
2026-09-04, la barre de progression et le score d'une sonde terminée sont restés 18 min dans le
buffer, et le run a été diagnostiqué « bloqué ». Le line-buffering de train.py n'était activé
que sous Windows. Le sous-processus ci-dessous a son stdout sur un PIPE, exactement comme sous
`tee` : c'est le seul moyen d'observer le régime de buffering réel, un test in-process verrait
la capture de pytest.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_import_ai_train_makes_std_streams_line_buffered_when_piped():
    code = (
        "import sys\n"
        "import ai.train\n"
        "sys.stdout.write(f'LINE_BUFFERING={sys.stdout.line_buffering}|{sys.stderr.line_buffering}')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert "LINE_BUFFERING=True|True" in result.stdout, result.stdout[-500:]
