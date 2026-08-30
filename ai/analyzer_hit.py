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


def attacker_melee_hit_characteristics(
    state: Any,
    config: Any,
    weapon_display_name: str,
    attacker_unit_type: str,
    fighters: Tuple[str, ...],
) -> Optional[Tuple[int, ...]]:
    """WS de CHAQUE profil de mêlée que la ligne couvre, résolue PAR FIGURINE. ``None`` = irrésoluble.

    JUMEAU EXACT de `analyzer_wound.attacker_weapon_strengths`, pour l'autre caractéristique de la
    même ligne — mêmes cartes (`unit_attack_limits`), même résolution `resolve_weapon_characteristic`
    sans aucune agrégation, mêmes conditions d'irrésolubilité. La WS entre dans un CALCUL de règle
    (table 05.01) : une valeur agrégée ne serait portée par AUCUNE figurine.
    """
    from ai.analyzer_perfig import resolve_weapon_characteristic

    if fighters:
        types = [state.model_types.get(mid) for mid in fighters]  # get allowed
    else:
        # Journal SANS `[SHOOTER_MODELS:]` : l'escouade est le seul porteur connu. Mode dégradé
        # assumé des vieux journaux, comme côté Force.
        types = [attacker_unit_type]
    values = set()
    for model_type in types:
        if model_type is None:
            return None
        limits = config.unit_attack_limits.get(model_type)  # get allowed : type hors registre
        if limits is None:
            return None
        per_unit = limits.get("cc_atk_by_weapon")  # get allowed : datasheet sans arme de mêlée
        if per_unit is None:
            return None
        resolved = resolve_weapon_characteristic(weapon_display_name, per_unit)
        # `None` = profil porté par une AUTRE figurine de la ligne (composite inter-datasheets),
        # ou caractéristique symbolique du registre. Une figurine qui n'en connaît aucun
        # n'apporte simplement rien : ce n'est pas une donnée manquante.
        values.update(int(v) for v in resolved.values() if v is not None)
    return tuple(sorted(values)) if values else None


def check_melee_hit_threshold(
    state: Any,
    config: Any,
    stats: Dict[str, Any],
    line: str,
    action_desc: str,
    attacker_player: int,
    attacker_unit_id: str,
    attacker_unit_type: str,
    weapon_display_name: str,
    fighters: Tuple[str, ...],
) -> None:
    """Compare le seuil de touche IMPRIMÉ en mêlée au seuil attendu (05.01 + Primitive A).

    JUMEAU DÉCLARÉ de `analyzer_wound.check_wound_threshold`, et il existe pour la même raison :
    depuis la passe 1 du chantier 06, le seuil imprimé n'est plus la caractéristique de l'arme —
    `clamp(WS - bonus + malus, 2, 6)`. Sans ce contrôle, un bonus appliqué à tort, oublié, ou
    appliqué deux fois produirait un seuil que RIEN ne contredit : le moteur redeviendrait seul
    juge de son propre affichage, exactement l'état que 05.01/05.02 ont fermé.

    LES DEUX SENS DE L'ERREUR SONT COUVERTS, et c'est le point :
      - le BONUS est dérivé des DATASHEETS des figurines vivantes de l'escouade (19.04,
        `unit_effect_in_force`), pas du token du journal. Un `+1` oublié par le moteur sort donc
        en écart, alors qu'un contrôle lisant le token serait resté muet — le token et le seuil
        viennent tous deux du moteur, les confronter ne prouve rien.
      - le MALUS de suppression, lui, n'a pas d'autre source que le journal : l'état `suppressed`
        est posé pendant la partie et n'est reconstructible d'aucune donnée statique. Il est donc
        lu sur le token, dont le nom vient de la CONSTANTE du moteur, jamais d'une copie.

    Mêlée SEULE. Au tir, le seuil imprimé compose couvert 13.08, [HEAVY] 24.16, 10.06 et
    §22.05, dont plusieurs dépendent d'un état de tour que le journal ne porte pas : un contrôle
    y rendrait des faux positifs en série. La mêlée n'a aucun de ces modificateurs.
    """
    from ai.analyzer_perfig import unit_effect_in_force
    from engine.phase_handlers.shared_utils import SUPPRESSED_MALUS_DISPLAY_NAME

    parsed = parse_hit_roll_and_target(action_desc)
    if parsed is None:
        return
    _roll, logged = parsed
    bases = attacker_melee_hit_characteristics(
        state, config, weapon_display_name, attacker_unit_type, fighters
    )
    # Roster d'abord, socles ensuite — MÊME court-circuit que le jumeau de blessure : aucune
    # datasheet vue ne porte Might Is Right ⇒ bonus 0, sans consulter les socles vivants. Sinon
    # une partie sans Warboss cesserait de juger ses seuils de touche pour une capacité absente.
    bonus_in_force: Optional[bool] = False
    if config.rule_to_units.get("hit_roll_bonus_fight"):  # get allowed
        bonus_in_force = unit_effect_in_force(
            state, config, attacker_unit_id, "hit_roll_bonus_fight"
        )
    if bases is None or bonus_in_force is None:
        stats["fight_hit_threshold_unverifiable"][attacker_player] += 1
        return
    malus = 1 if f"[{SUPPRESSED_MALUS_DISPLAY_NAME.upper()}]" in action_desc.upper() else 0
    bonus = 1 if bonus_in_force else 0
    # Appliqué PAR PROFIL avant l'unanimité, comme le +1 d'Oath côté blessure : les clamps
    # rapprochent deux WS voisines, et ce qui doit être unique c'est la valeur IMPRIMABLE.
    expected_set = {max(2, min(6, base - bonus + malus)) for base in bases}
    if len(expected_set) != 1:
        stats["fight_hit_threshold_unverifiable"][attacker_player] += 1
        return
    expected = expected_set.pop()
    if expected == logged:
        return
    stats["fight_hit_threshold_mismatch"][attacker_player] += 1
    first = stats["first_error_lines"]["fight_hit_threshold_mismatch"]
    if first[attacker_player] is None:
        first[attacker_player] = {
            "episode": state.current_episode_num,
            "line": line.strip(),
            "detail": (
                f"seuil imprimé {logged}+ vs attendu {expected}+ "
                f"(WS {sorted(bases)}, bonus {bonus}, malus {malus})"
            ),
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
    expected_success = expected_hit_success(roll, effective_target)
    if expected_success == bool(WOUND_SEGMENT_PRESENT_RE.search(action_desc)):
        return
    stats[f"{key}_mismatch"][attacker_player] += 1
    first = stats["first_error_lines"][f"{key}_mismatch"]
    if first[attacker_player] is None:
        expected = "TOUCHE" if expected_success else "ÉCHEC"
        first[attacker_player] = {
            "episode": state.current_episode_num,
            "line": line.strip(),
            "detail": f"jet {roll} vs seuil {effective_target}+ → {expected} attendu",
        }
