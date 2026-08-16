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
  - une blessure AUTOMATIQUE ([LETHAL HITS] 24.23) reste une touche réussie : son segment
    `Wound None(4+)` doit être reconnu comme tel. Cf. `WOUND_SEGMENT_PRESENT_RE`.

Les deux compteurs de lignes RÉELLEMENT jugées (`*_hit_result_checked`) sont là pour la même
raison que les `*_wound_threshold_unverifiable` : un compteur d'erreurs à zéro parce qu'il ne
regarde plus rien est le défaut le plus coûteux de ce dépôt.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from engine.phase_handlers.attack_sequence import CRITICAL_HIT_ROLL, NATURAL_FAIL_ROLL

from ai.analyzer_core import ACTION_ABILITY_TOKENS

#: Extrait le plancher du token `[INDIRECT FIRE:X+]` (10.07).
_INDIRECT_FIRE_TOKEN_RE = re.compile(r'\[INDIRECT FIRE:(\d+)\+\]', re.IGNORECASE)

#: Extrait base (optionnelle) et seuil effectif de `Hit N(base+->eff+)` ou `Hit N(eff+)`.
#: Groupe 1 = base (None si la flèche est absente), groupe 2 = seuil effectif.
_INDIRECT_HIT_FULL_RE = re.compile(r'Hit\s+\d+\((?:(\d+)\+->)?(\d+)\+\)')

#: `Hit 4(3+) [TOKEN…]` — le jet et le seuil EFFECTIF. Deux formes de seuil coexistent :
#: `3+` (nu) et `3+->4+` ([HEAVY] 24.16, [COVER] 13.08), et c'est le SECOND nombre qui a joué.
#: `Hit None(None+)` (torrent, touche soutenue) ne correspond volontairement à rien.
#: Même raison qu'en 05.02 pour la queue de tokens : un token appartient au segment qu'il SUIT.
HIT_SEGMENT_RE = re.compile(
    r"Hit\s+(\d+)\((?:\d+\+->)?(\d+)\+\)(" + ACTION_ABILITY_TOKENS + r")"
)

#: Le segment qui atteste la RÉUSSITE : le formateur ne l'écrit que sous `hit_result == "HIT"`.
#:
#: ⚠️ LE JET PEUT ÊTRE `None`, ET LE SEGMENT RESTE UN SEGMENT. `[LETHAL HITS]` 24.23 blesse
#: automatiquement : le moteur pose `wound_roll = None` (`attack_sequence.py:396`) et le
#: formateur écrit sans condition `Wound {wound_roll}({wound_target}+)`
#: (`step_logger.py:816`) — soit `Wound None(4+)`. Une regex exigeant des chiffres après
#: `Wound` ne le reconnaît pas et déclare l'attaque MANQUÉE : chaque touche critique d'une arme
#: [LETHAL HITS] était alors comptée en faute. Aucun roster du projet ne porte la règle
#: aujourd'hui, mais elle est implémentée dans le moteur et déclarée dans `weapon_rules.json` :
#: le défaut était armé, pas absent. On reconnaît donc la GRAMMAIRE du segment
#: (`Wound <jet|None>(<seuil>+)`), jamais la valeur du jet.
WOUND_SEGMENT_PRESENT_RE = re.compile(r"\bWound\s+(?:\d+|None)\(\d+\+\)")


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


def check_indirect_fire_rule(
    state: Any,
    stats: Dict[str, Any],
    line: str,
    action_desc: str,
    attacker_player: int,
) -> None:
    """10.07 : un tir indirect doit porter [COVER] (couvert accordé inconditionnellement).

    Ce qui est vérifié : le token [COVER] est présent sur toute ligne portant [INDIRECT FIRE:X+].

    Ce qui n'est PAS vérifié (et pourquoi ce n'est pas un trou) : le seuil `eff` affiché dans
    `Hit N(base+->eff+)` est le BS APRÈS COUVERT, pas `max(BS_après_couvert, plancher)`. Le
    plancher est appliqué séparément dans `_evaluate_roll` via `hit_fail_below`, mais le moteur
    ne le répercute pas dans le champ `hit_target` du record — `eff` peut légitimement être < X.
    Exemple : `Hit 3(3+->4+) [COVER] [INDIRECT FIRE:6+]` est une ligne légale (4 < 6, et c'est
    normal). Vérifier `eff >= floor` depuis le log serait un faux positif systématique.

    Exception légale : [IGNORES COVER] court-circuite le couvert dans ce moteur (24.18 prime même
    sur 10.07) → la ligne est ignorée pour éviter un faux positif systématique.
    """
    if _INDIRECT_FIRE_TOKEN_RE.search(action_desc) is None:
        return

    # [IGNORES COVER] + [INDIRECT FIRE] : couvert non accordé → pas de jugement
    if '[IGNORES COVER]' in action_desc:
        return

    # Pas de jet (torrent, etc.) → pas de seuil à vérifier
    if _INDIRECT_HIT_FULL_RE.search(action_desc) is None:
        return

    stats['indirect_fire_checked'][attacker_player] += 1

    if '[COVER]' in action_desc:
        return

    stats['indirect_fire_mismatch'][attacker_player] += 1
    first = stats['first_error_lines']['indirect_fire_mismatch']
    if first[attacker_player] is None:
        first[attacker_player] = {
            'episode': state.current_episode_num,
            'line': line.strip(),
            'detail': '[COVER] absent sur tir indirect',
        }


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
    # 10.07 tir indirect : le seuil effectif = max(BS_après_couvert, plancher).
    # `hit_target` loggué = BS seul ; sans ce max, roll=4 vs BS=4+ sous plancher 6+ serait un
    # faux positif (expected HIT, observed MISS — le moteur a raison).
    m_indirect = _INDIRECT_FIRE_TOKEN_RE.search(action_desc)
    effective_target = max(target, int(m_indirect.group(1))) if m_indirect else target
    stats[f"{key}_checked"][attacker_player] += 1
    if expected_hit_success(roll, effective_target) == bool(WOUND_SEGMENT_PRESENT_RE.search(action_desc)):
        return
    stats[f"{key}_mismatch"][attacker_player] += 1
    first = stats["first_error_lines"][f"{key}_mismatch"]
    if first[attacker_player] is None:
        expected = "TOUCHE" if expected_hit_success(roll, effective_target) else "ÉCHEC"
        first[attacker_player] = {
            "episode": state.current_episode_num,
            "line": line.strip(),
            "detail": f"jet {roll} vs seuil {effective_target}+ → {expected} attendu",
        }
