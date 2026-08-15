"""Doublure partagee de sys.stdout pour les tests du writer de progression.

Deux suites de tests patchent sys.stdout pour observer les ecritures de ProgressWriter :
- test_progress_writer.py (teste le writer directement)
- tests/unit/ai/test_progress_wall_per_episode.py (teste le callback via le writer)

Une seule definition evite qu'elles divergent silencieusement si l'interface de
ProgressWriter.write() change (ex : bascule vers builtins.print).
"""

from __future__ import annotations

from typing import List


class RecordingStdout:
    """Doublure de sys.stdout : enregistre les ecritures, ou casse comme un pipe rompu."""

    def __init__(self, broken: bool = False) -> None:
        self.writes: List[str] = []
        self._broken = broken

    def write(self, text: str) -> None:
        self.writes.append(text)
        if self._broken:
            raise BrokenPipeError("stdout casse")

    def flush(self) -> None:
        pass
