"""Contrôle des attaques NON ALLOUÉES (05 Attack sequence), tir et mêlée.

JUMEAU DÉCLARÉ de `ai/analyzer_hit.py` et `ai/analyzer_wound.py` : même forme, même raison
d'exister — un fait que le moteur écrit dans `step.log` et dont il était jusqu'ici seul juge.

CE QUE DIT LE JOURNAL. Une attaque dont la sauvegarde n'a jamais été résolue s'écrit
`Save [NOT ALLOCATED]`. Le seuil de sauvegarde n'est écrit qu'à l'ALLOCATION
(`_resolve_one_manual_wound`, `engine/phase_handlers/shared_utils.py`) : sans elle, ni seuil,
ni résultat, ni dégâts.

CE QUI EST LÉGITIME, ET QUI EST LE CAS NORMAL. 05 Attack sequence — « excess attacks lost » :
la cible DÉTRUITE avant que le pool ne soit résolu, le moteur cesse d'allouer. C'est la règle.

CE QUI EST UNE ERREUR, et le seul objet de ce contrôle : la même ligne alors que la cible a
SURVÉCU À L'ACTIVATION. Le moteur aurait cessé d'allouer sans raison — des blessures réussies
jetées, et un défenseur épargné sans que rien ne le dise.

⚠️⚠️ POURQUOI LE VERDICT EST DIFFÉRÉ À LA FIN DE L'ACTIVATION, et pas rendu sur la ligne.
Première version de ce contrôle (2026-08-11) : elle jugeait la cible VIVANTE OU MORTE au moment
de LIRE la ligne, et a rendu **334 fausses erreurs** sur le run du jour — que j'ai failli
rapporter comme un défaut moteur. L'ordre des LIGNES n'est pas l'ordre d'ALLOCATION :

  - le pool d'un lot est trié par jet de sauvegarde CROISSANT (05.04 INFLICT DAMAGE) ;
  - les lots s'enchaînent par (cible × profil d'arme, 04.03), un profil entier après l'autre.

Une attaque loguée tôt peut donc être résolue tard, et inversement. Mesuré sur E79 T2 P1
(Unit 6 → Unit 104) : le lot Blitzcannon tue la cible, puis le lot Rokkit Launcha entier est
perdu — y compris une sauvegarde de 1, qui rate toujours et aurait été allouée en premier si
son lot avait encore eu une cible. L'unité 104 est absente de l'instantané `T3 STATE:` qui
suit : elle était bien morte. L'analyzer, lui, applique les dégâts dans l'ordre des lignes et
la voyait encore vivante.

La seule référence temporelle honnête est donc la FIN DE L'ACTIVATION de l'attaquant : à cet
instant, toute la casse de l'activation est appliquée des deux côtés.

⚠️ LIMITE ASSUMÉE : la vie de la cible est celle de l'ÉTAT RECONSTRUIT par l'analyzer. §2.8
compte l'écart avec le moteur — une divergence non nulle sur l'épisode invalide ce verdict
comme elle invalide toute mesure d'adjacence. Même dépendance que `shoot_at_dead_unit`.
"""

import re
from typing import TYPE_CHECKING, Any, Dict

from shared.data_validation import require_key

if TYPE_CHECKING:
    from ai.analyzer_state import AnalyzerState

#: Le segment qu'écrit `step_logger._save_segments` quand aucune allocation n'a eu lieu.
#: UN SEUL motif pour les deux phases : c'est un seul producteur, il n'aura jamais deux formes.
NOT_ALLOCATED_RE = re.compile(r'Save\s+\[NOT ALLOCATED\]', re.IGNORECASE)


def note_not_allocated(
    state: "AnalyzerState",
    action_desc: str,
    line: str,
    attacker_id: str,
    target_id: str,
    player: int,
    stat_key: str,
) -> None:
    """Met la ligne EN ATTENTE de verdict, sans juger — cf. le différé, en tête de module.

    Appelé depuis les deux handlers d'attaque, sur toute ligne d'attaque. Le verdict est rendu
    par `flush_not_allocated` quand l'activation de `attacker_id` se termine.
    """
    if NOT_ALLOCATED_RE.search(action_desc) is None:
        return
    key = (attacker_id, target_id, int(player), stat_key)
    if key not in state.not_allocated_pending:
        state.not_allocated_pending[key] = []
    state.not_allocated_pending[key].append((state.current_episode_num, line.strip()))


def flush_not_allocated(
    state: "AnalyzerState",
    stats: Dict[str, Any],
    *,
    current_attacker_id: str = "",
) -> None:
    """Rend le verdict des activations TERMINÉES : cible encore vivante ⇒ erreur.

    `current_attacker_id` vide (fin d'épisode) vide toute la table. Sinon, seules les entrées
    d'un AUTRE attaquant sont jugées : celles de l'attaquant courant appartiennent à une
    activation qui n'est pas finie, et dont les dégâts restants ne sont pas encore appliqués.
    """
    for key in [k for k in state.not_allocated_pending if k[0] != current_attacker_id]:
        occurrences = state.not_allocated_pending.pop(key)
        _attacker_id, target_id, player, stat_key = key
        target_alive = target_id in state.unit_hp and require_key(state.unit_hp, target_id) > 0
        if not target_alive:
            continue
        for episode, line in occurrences:
            stats[stat_key][player] += 1
            if stats['first_error_lines'][stat_key][player] is None:
                stats['first_error_lines'][stat_key][player] = {
                    'episode': episode,
                    'line': line,
                }
