"""Contrôle du RÉSULTAT DE TOUCHE journalisé (05.01), tir et mêlée.

JUMEAU DÉCLARÉ de `ai/analyzer_wound.py`. Celui-ci recalcule le SEUIL de blessure et le compare
à celui que la ligne imprime ; celui-là recalcule le VERDICT de la touche et le compare à celui
que la ligne rend. Les deux vivent côte à côte, sont appelés depuis les deux mêmes sites, et
n'existent que parce que le moteur était jusqu'ici seul juge de son propre affichage.

« 05 Attack sequence.pdf », 05.01 HIT ROLLS — la table, dans son ordre, qui est normatif :

    Unmodified 1 ......................................... FAILS
    Unmodified 6 ......................................... CRITICAL HIT
    Equal to or greater than that attack's BS/WS ......... HIT
    Any other result ..................................... FAILS

CE QUI EST MESURÉ. Le VERDICT du moteur n'est pas écrit en toutes lettres dans `step.log`, et
c'est justement ce qui rend le contrôle possible sans nouveau champ : le formateur n'ajoute le
segment `Wound …` QUE si la touche a réussi (`step_logger.py:803`, `if hit_result == "HIT"`).
La présence du segment EST donc le verdict, et elle se lit. On compare :

    verdict attendu (table 05.01, appliquée au jet et au seuil imprimés)
    vs
    verdict observé (`Wound …` présent ⟺ touche réussie)

CE QUI EST DÉLIBÉRÉMENT ÉCARTÉ, et pourquoi ce n'est pas un trou :
  - `[TORRENT]` 24.37 (« does not make hit rolls ») et `[SUSTAINED HITS]` 24.36 (touche
    additionnelle, pas une attaque) n'ont AUCUN jet de touche. Le moteur écrit alors
    `attackRoll=None` ET `hitTarget=None` (`attack_sequence.py:366-368`), donc la ligne porte
    `Hit None(None+)` : la regex ci-dessous ne la reconnaît pas et le contrôle ne se prononce
    pas. Ce n'est pas une exception codée ici — c'est le journal qui ne présente pas de jet.
  - le jet IMPRIMÉ est celui d'APRÈS relance (`[REROLLED:n]` porte l'original). C'est le bon :
    05.01 juge le dé qui a compté, et « unmodified » qualifie le dé, pas l'ordre des relances.
  - le seuil IMPRIMÉ est déjà l'effectif (`base+->eff+` sous [HEAVY] / [COVER]) : les
    modificateurs de ce moteur dégradent le SEUIL, jamais le jet, donc le jet reste non modifié
    au sens du PDF et la comparaison est directe.

Les deux compteurs de lignes RÉELLEMENT jugées (`*_hit_result_checked`) sont là pour la même
raison que les `*_wound_threshold_unverifiable` : un compteur d'erreurs à zéro parce qu'il ne
regarde plus rien est le défaut le plus coûteux de ce dépôt.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from engine.phase_handlers.attack_sequence import CRITICAL_HIT_ROLL, NATURAL_FAIL_ROLL

from ai.analyzer_core import ACTION_ABILITY_TOKENS

#: `Hit 4(3+) [TOKEN…]` — le jet et le seuil EFFECTIF. Deux formes de seuil coexistent :
#: `3+` (nu) et `3+->4+` ([HEAVY] 24.16, [COVER] 13.08), et c'est le SECOND nombre qui a joué.
#: `Hit None(None+)` (torrent, touche soutenue) ne correspond volontairement à rien.
#: Même raison qu'en 05.02 pour la queue de tokens : un token appartient au segment qu'il SUIT.
HIT_SEGMENT_RE = re.compile(
    r"Hit\s+(\d+)\((?:\d+\+->)?(\d+)\+\)(" + ACTION_ABILITY_TOKENS + r")"
)

#: Le segment qui atteste la RÉUSSITE : le formateur ne l'écrit que sous `hit_result == "HIT"`.
#: `Wound 4` sans parenthèse (blessure automatique, [LETHAL HITS] 24.23) compte aussi — c'est
#: bien une touche qui a réussi, seule sa blessure est acquise.
WOUND_SEGMENT_PRESENT_RE = re.compile(r"\bWound\s+\d+")


def parse_hit_roll_and_target(action_desc: str) -> Optional[Tuple[int, int]]:
    """`(jet, seuil effectif)` de la ligne, ou ``None`` si elle ne porte pas de jet de touche."""
    m = HIT_SEGMENT_RE.search(action_desc)
    return (int(m.group(1)), int(m.group(2))) if m else None


def expected_hit_success(roll: int, target: int) -> bool:
    """Table 05.01, dans l'ordre du PDF. Les seuils viennent du MOTEUR, jamais d'un 6 en dur.

    Écrire `roll == 6` ici recréerait exactement le vert vacant V8 (`devastating_wounds`, qui
    suppose que seul un 6 est critique et se trompe dès qu'une règle abaisse le seuil critique).
    """
    if roll == NATURAL_FAIL_ROLL:
        return False
    if roll >= CRITICAL_HIT_ROLL:
        return True
    return roll >= target


def check_hit_result(
    state: Any,
    stats: Dict[str, Any],
    line: str,
    action_desc: str,
    attacker_player: int,
    is_melee: bool,
) -> None:
    """Compare le verdict de touche attendu à celui que la ligne rend. Compte l'écart."""
    parsed = parse_hit_roll_and_target(action_desc)
    key = "fight_hit_result" if is_melee else "shoot_hit_result"
    if parsed is None:
        return
    roll, target = parsed
    stats[f"{key}_checked"][attacker_player] += 1
    if expected_hit_success(roll, target) == bool(WOUND_SEGMENT_PRESENT_RE.search(action_desc)):
        return
    stats[f"{key}_mismatch"][attacker_player] += 1
    first = stats["first_error_lines"][f"{key}_mismatch"]
    if first[attacker_player] is None:
        expected = "TOUCHE" if expected_hit_success(roll, target) else "ÉCHEC"
        first[attacker_player] = {
            "episode": state.current_episode_num,
            "line": line.strip(),
            "detail": f"jet {roll} vs seuil {target}+ → {expected} attendu",
        }
