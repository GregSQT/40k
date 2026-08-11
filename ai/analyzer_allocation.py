"""Contrôle des attaques NON ALLOUÉES (05 Attack sequence), tir et mêlée.

JUMEAU DÉCLARÉ de `ai/analyzer_hit.py` et `ai/analyzer_wound.py` : même forme, même raison
d'exister — un fait que le moteur écrit dans `step.log` et dont il était jusqu'ici seul juge.

CE QUE DIT LE JOURNAL. Depuis le 2026-08-11, une attaque dont la sauvegarde n'a jamais été
résolue s'écrit `Save [NOT ALLOCATED]` au lieu du `Save <jet>(None+)` que le formateur
fabriquait. Le seuil de sauvegarde n'est écrit qu'à l'ALLOCATION (`_resolve_one_manual_wound`,
`engine/phase_handlers/shared_utils.py`) : sans elle, ni seuil, ni résultat, ni dégâts.

CE QUI EST LÉGITIME, ET QUI EST DONC LE CAS NORMAL. 05 Attack sequence — « excess attacks
lost » : quand la cible est DÉTRUITE avant que le pool d'attaques ne soit résolu, le moteur
cesse d'allouer. Les attaques restantes sont perdues, et c'est la règle. Sur le run du
2026-08-11, les 1 429 lignes concernées (14 % des lignes d'attaque) relèvent toutes de ce cas.

CE QUI EST UNE ERREUR, et le seul objet de ce contrôle : la même ligne alors que la cible est
ENCORE VIVANTE. Le moteur aurait alors cessé d'allouer sans raison — des attaques payées,
jetées, et un adversaire épargné sans que rien ne le dise.

⚠️ LIMITE ASSUMÉE, à lire avec le compteur : la vie de la cible est celle de l'ÉTAT RECONSTRUIT
par l'analyzer, pas celle du moteur. Les deux divergent parfois, et §2.8 compte exactement cet
écart — une divergence non nulle sur l'épisode invalide donc ce verdict comme elle invalide
toute mesure d'adjacence. C'est la même dépendance que `shoot_at_dead_unit`, à la même échelle.
"""

import re
from typing import Any, Dict

from shared.data_validation import require_key

#: Le segment qu'écrit `step_logger._save_segments` quand aucune allocation n'a eu lieu.
#: UN SEUL motif pour les deux phases : c'est un seul producteur, il n'aura jamais deux formes.
NOT_ALLOCATED_RE = re.compile(r'Save\s+\[NOT ALLOCATED\]', re.IGNORECASE)


def check_attack_not_allocated(
    stats: Dict[str, Any],
    unit_hp: Dict[str, int],
    action_desc: str,
    line: str,
    episode: int,
    target_id: str,
    player: int,
    stat_key: str,
) -> None:
    """Compte une erreur si l'attaque n'a pas été allouée ALORS QUE la cible est vivante.

    Appelé depuis les deux handlers d'attaque, sur toute ligne portant le segment. Le prédicat
    de mort est celui des autres contrôles du fichier (`unit_hp` ≤ 0 ou unité inconnue) : une
    seule définition de « morte » dans l'analyzer, sinon deux contrôles se contredisent sur la
    même ligne.

    `stat_key` nomme le compteur de la PHASE appelante (`shoot_…` / `fight_…`). Un compteur par
    phase et une logique partagée : c'est la forme des autres contrôles jumeaux du dépôt
    (`shoot_hit_result_mismatch` / `fight_hit_result_mismatch` pour `analyzer_hit.py`), et elle
    seule permet au rapport de ranger chaque faute dans sa section.
    """
    if NOT_ALLOCATED_RE.search(action_desc) is None:
        return
    target_alive = target_id in unit_hp and require_key(unit_hp, target_id) > 0
    if not target_alive:
        return
    stats[stat_key][player] += 1
    if stats['first_error_lines'][stat_key][player] is None:
        stats['first_error_lines'][stat_key][player] = {
            'episode': episode,
            'line': line.strip(),
        }
