"""Les profils d'un combi se comptent PAR SOCLE, et le combi se résout par le MODEL-TYPE.

Le contrôle §1.2 `COMBI profiles in same phase` était MORT. `unit_combi_by_weapon` est indexé
par la datasheet qui PORTE l'arme (`VanguardVeteranSquadJumpPackPlasma`, dont les deux profils
de Plasma Pistol partagent la clé `plasma_pistol`), mais il était interrogé sous le type
d'ESCOUADE (`VanguardVeteranSquadJumpPack`, un Heavy Bolt Pistol sans combi) : il rendait un
dictionnaire vide, `combi_key` restait None, et ni l'exercice ni le contrôle ne tournaient.
Mesuré sur le step.log du 2026-09-07 : 114 lignes de Plasma Pistol des deux profils, 57 conflits
réels, 0 exercice et 0 erreur au rapport.

Le GRAIN est la figurine : le profil engage le socle qui tire, donc deux porteurs d'un même
combi choisissent chacun le leur. C'est ce qui sépare le contrôle réel du faux positif, et
aucun des deux ne se voyait tant que la résolution rendait None.
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log

SQUAD_TYPE = "VanguardVeteranSquadJumpPack"            # Heavy Bolt Pistol : AUCUN combi
PLASMA_TYPE = "VanguardVeteranSquadJumpPackPlasma"     # les deux profils, COMBI_WEAPON commun
STANDARD = "Plasma Pistol (Standard)"
SUPERCHARGE = "Plasma Pistol (Supercharge)"

A = (50, 50)     # ancre d'escouade, socle SANS combi
B = (50, 51)     # premier porteur de plasma  (1#1)
C = (50, 52)     # second porteur de plasma   (1#2)
T = (50, 56)     # cible, dans la portée du pistolet
OBJECTIVES = ";".join(f"(200,{r})" for r in range(150, 156))

_MODELS = f"[MODELS: 1#0@({A[0]},{A[1]},z0) 1#1@({B[0]},{B[1]},z0) 1#2@({C[0]},{C[1]},z0)]"

_HEADER = entete_step_log(
    units=(
        f"[10:00:00] Unit 1 ({SQUAD_TYPE}) P1: Starting position ({A[0]},{A[1]}), HP_MAX=2 base=round/6"
        f" {_MODELS}"
        f" [MODEL_TYPES: 1#0={SQUAD_TYPE} 1#1={PLASMA_TYPE} 1#2={PLASMA_TYPE}]\n"
        f"[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position ({T[0]},{T[1]}), HP_MAX=2 base=round/6"
        f" [MODELS: 101#0@({T[0]},{T[1]},z0)]\n"
    ),
    rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)",
    objectives=OBJECTIVES,
)


def _shot(profile: str, shooter: str, turn: int = 1) -> str:
    return (
        f"[10:00:02] E1 T{turn} P1 SHOOT : Unit 1({A[0]},{A[1]}) SHOT Unit 101({T[0]},{T[1]})"
        f" with [{profile}] - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:0HP"
        f" {_MODELS} [SHOOTER_MODELS: {shooter}] [R:+0.0] [SUCCESS]\n"
    )


def _move(turn: int) -> str:
    """Phase intercalée entre deux tours — c'est elle qui vide `combi_profile_usage`.

    Mesuré sur le step.log du 2026-09-07 : 0 transition SHOOT→SHOOT directe sur 5000, un tour
    passe toujours par MOVE. Le test emprunte donc le chemin de production, il ne le suppose pas.
    """
    return (
        f"[10:00:03] E1 T{turn} P1 MOVE : Unit 1({A[0]},{A[1]}) MOVED from ({A[0]},{A[1]})"
        f" to ({A[0]},{A[1]}) [MOVE_TYPE:normal] [R:+0.0] {_MODELS} [SUCCESS]\n"
    )


def _end(last_turn: int) -> str:
    return (
        f"[10:00:08] T{last_turn} OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none\n"
        "[10:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, "
        "Total=0, Duration=1.000s\n"
    )


def _parse(tmp_path, body: str, last_turn: int = 2):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(_HEADER + body + _end(last_turn))
    return an.parse_step_log(str(log))


def test_registry_premise_the_combi_lives_on_the_model_type_not_the_squad():
    """Anti-vert-vacant : sans cet écart de datasheet, le bug corrigé n'existerait pas."""
    from ai.unit_registry import UnitRegistry

    units = UnitRegistry().units
    combi = {
        w["display_name"]: w.get("COMBI_WEAPON")
        for w in units[PLASMA_TYPE]["RNG_WEAPONS"]
    }
    assert combi[STANDARD] is not None, "le model-type doit porter un COMBI_WEAPON"
    assert combi[STANDARD] == combi[SUPERCHARGE], "les deux profils doivent partager la clé"
    squad_combi = {
        w["display_name"]: w.get("COMBI_WEAPON")
        for w in units[SQUAD_TYPE]["RNG_WEAPONS"]
    }
    assert STANDARD not in squad_combi, "prémisse : le type d'escouade ne déclare PAS le plasma"
    assert not any(squad_combi.values()), "prémisse : le type d'escouade ne porte aucun combi"


def test_same_model_firing_two_profiles_in_one_turn_is_an_error(tmp_path):
    """Le cœur du lot : ce conflit est resté invisible tant que le combi se résolvait mal."""
    body = _shot(STANDARD, "1#1") + _shot(SUPERCHARGE, "1#1")
    stats = _parse(tmp_path, body)
    assert stats["shoot_combi_profile_conflicts"][1] == 1


def test_the_control_is_exercised_at_all(tmp_path):
    """L'autre moitié du défaut : le compteur d'EXERCICE restait à 0, donc « JAMAIS EXERCÉE »."""
    body = _shot(STANDARD, "1#1") + _shot(SUPERCHARGE, "1#1")
    stats = _parse(tmp_path, body)
    assert stats["rule_usage"]["PROJ.1.2.combi"][1] == 2


def test_two_distinct_models_each_with_their_own_profile_is_legal(tmp_path):
    """GRAIN : chaque socle choisit son profil. Compté par escouade, ceci serait une fausse faute."""
    body = _shot(STANDARD, "1#1") + _shot(SUPERCHARGE, "1#2")
    stats = _parse(tmp_path, body)
    assert stats["shoot_combi_profile_conflicts"][1] == 0, (
        stats["first_error_lines"]["shoot_combi_profile_conflicts"][1]
    )
    assert stats["rule_usage"]["PROJ.1.2.combi"][1] == 2, "le contrôle doit avoir jugé les deux"


def test_the_same_model_may_change_profile_from_one_turn_to_the_next(tmp_path):
    """La contrainte vaut pour UNE phase de tir, pas pour la partie."""
    body = (
        _shot(STANDARD, "1#1", turn=1)
        + _move(2)
        + _shot(SUPERCHARGE, "1#1", turn=2)
    )
    stats = _parse(tmp_path, body, last_turn=3)
    assert stats["shoot_combi_profile_conflicts"][1] == 0, (
        stats["first_error_lines"]["shoot_combi_profile_conflicts"][1]
    )
    assert stats["rule_usage"]["PROJ.1.2.combi"][1] == 2, (
        "les deux tirs (tours distincts) doivent avoir atteint le bloc combi"
    )


def test_a_weapon_without_combi_never_arms_the_control(tmp_path):
    """Le socle 1#0 ne porte aucun combi : ni exercice, ni erreur, quoi qu'il tire."""
    body = _shot("Heavy Bolt Pistol", "1#0") * 2
    stats = _parse(tmp_path, body)
    assert stats["rule_usage"]["PROJ.1.2.combi"][1] == 0
    assert stats["shoot_combi_profile_conflicts"][1] == 0


def test_multi_bearer_group_each_violation_counted_per_bearer(tmp_path):
    """Boucle par-porteur avec N>1 : 2 porteurs qui changent de profil = 2 conflits distincts.

    `[SHOOTER_MODELS: 1#1 1#2]` liste les deux socles sur chaque ligne du groupe.
    Standard puis Supercharge par les DEUX → chaque socle viole la règle indépendamment.
    """
    body = _shot(STANDARD, "1#1 1#2") + _shot(SUPERCHARGE, "1#1 1#2")
    stats = _parse(tmp_path, body)
    assert stats["shoot_combi_profile_conflicts"][1] == 2, (
        "un conflit par porteur (1#1 et 1#2 violent chacun la règle)"
    )
    assert stats["rule_usage"]["PROJ.1.2.combi"][1] == 4, (
        "2 porteurs × 2 lignes = 4 occasions jugées"
    )
