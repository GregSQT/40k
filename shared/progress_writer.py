#!/usr/bin/env python3
"""shared/progress_writer.py - SEUL point d'ecriture des barres d'avancement en place.

Deux barres se relaient sur LA MEME ligne de terminal : celle de l'entrainement
(ai/training_callbacks.py) et celle d'une evaluation bot (ai/bot_evaluation.py), qui prend la
main pendant que la premiere est figee. Elles partagent donc un etat : la longueur de la ligne
actuellement affichee, sans laquelle celle qui reprend la main laisse trainer la queue de
l'autre. Cet etat vit dans le dict `line_length_state` passe au constructeur (cote entrainement,
c'est `gate_display_state`), il est ECRIT et RELU par les deux — la poignee de main est
symetrique, et c'est ce qui la rend correcte : chacun efface ce que l'autre a laisse.

Le writer est instancie PAR BARRE (un run d'entrainement, une evaluation), jamais partage : le
verrou d'echec ci-dessous est un etat de cette barre-la, pas du processus.

ISOLE L'ECHEC D'ECRITURE, ET LUI SEUL. Sur une sortie cassee — run redirige dans `head`,
terminal ferme, session detachee — `sys.stdout.write` leve, et cette exception d'affichage
emportait ce qu'elle traversait : depuis le callback SB3 elle arretait un entrainement de 47 h
sur sa 50e ligne affichee ; depuis le callback d'un episode d'eval elle sortait de la collecte
parallele avant `must_abort_pool`, donc sans force-terminate ; depuis l'abandon en bloc elle
tronquait `results_list`, c'est-a-dire le denominateur du score ; depuis la ligne finale — hors
de tout `try` — elle perdait des resultats DEJA agreges.

Garder l'isolation ICI et non chez les appelants est ce qui la rend compatible avec T1 :
`_on_task_result` ne fait pas qu'afficher, il valide le resultat du worker (`require_key`) ; un
`try/except` pose autour de lui avalerait cette validation, c'est-a-dire masquerait un contrat
rompu derriere une barre de progression muette.

Desactive apres le PREMIER echec : une sortie cassee le reste, la rappeler rendrait une trace
par episode pour un affichage qui n'arrivera de toute facon plus.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Dict, Optional

__all__ = ["ProgressWriter", "SHARED_LINE_LEN_KEY"]

# Cle du dict partage entre les deux barres. Nommee ICI et lue nulle part ailleurs : les deux
# ecritures d'origine la recopiaient chacune de son cote, ce qui est exactement la forme que
# prend une poignee de main qui se desynchronise.
SHARED_LINE_LEN_KEY = "last_progress_line_len"


class ProgressWriter:
    """Ecrit une ligne de progression en place (`\\r`), en effacant la queue de la precedente."""

    def __init__(self, line_length_state: Optional[Dict[str, Any]] = None) -> None:
        self._line_length_state = line_length_state
        self._last_line_len = 0
        self._broken = False

    def write(self, line: str) -> None:
        if self._broken:
            return
        # Lire la longueur partagee AVANT de la reecrire : l'autre barre a pu afficher une ligne
        # plus longue que tout ce que celle-ci a jamais ecrit.
        prev_len = self._last_line_len
        state = self._line_length_state
        if state is not None and SHARED_LINE_LEN_KEY in state:
            prev_len = max(prev_len, int(state[SHARED_LINE_LEN_KEY]))
        clear_padding = " " * max(0, prev_len - len(line))
        try:
            sys.stdout.write(f"\r{line}{clear_padding}")
            sys.stdout.flush()
        except (OSError, ValueError, AttributeError):
            # OSError : pipe rompu, descripteur invalide. ValueError : ecriture sur un flux ferme.
            # AttributeError : sys.stdout est None (processus detache, spawn multiprocessing).
            self._broken = True
            logging.exception(
                "Progress display failed; disabled for the rest of this run"
            )
            return
        # Longueurs publiees seulement apres une ecriture REUSSIE : une longueur publiee pour une
        # ligne jamais affichee ferait effacer a l'autre barre ce que le terminal ne porte pas.
        self._last_line_len = len(line)
        if state is not None:
            state[SHARED_LINE_LEN_KEY] = len(line)
