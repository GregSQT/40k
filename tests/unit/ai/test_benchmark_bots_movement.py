"""Couche déplacement/intention des `reference_*` — chantier R0a (§3.1 à §3.4).

Quatre mécanismes, quatre verrous :

1. §3.1 assignation d'armée — UNE réclamante par objectif non tenu par le camp, mémoire de tour,
   rupture sur la mort d'une réclamante ;
2. §3.2 prime de tenue — une escouade ne quitte plus une zone qu'elle contrôle pour un hexe
   marginalement « meilleur » ;
3. §3.3 anti-empilement — les non-réclamantes fuient une zone que les alliés tiennent déjà large ;
4. §3.4 géométrie par AIRE — la distance à un objectif est celle de son aire (14.02), pas celle de
   son ancre (hexe de plus petites coordonnées).

Les scénarios sont construits ici de bout en bout : aucune graine, aucun ordre implicite.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import pytest

from ai import benchmark_bots as bb
from ai.benchmark_bots import ReferenceBalancedBot, ReferenceDenialBot, ReferenceReactiveBot
from engine import macro_intents as mi
from engine.combat_utils import calculate_hex_distance

# ─────────────────────────────────────────────────────────────────────────────────────────────
# Fabrique d'états de jeu
# ─────────────────────────────────────────────────────────────────────────────────────────────


def _zone(col_min: int, col_max: int, row_min: int, row_max: int) -> List[List[int]]:
    """Aire rectangulaire, bornes INCLUSES, au format `hexes` du loader de scénario."""
    return [
        [col, row]
        for col in range(col_min, col_max + 1)
        for row in range(row_min, row_max + 1)
    ]


def _game_state(
    objectives: Sequence[Dict[str, Any]],
    squads: Sequence[Tuple[str, int, Tuple[int, int]]],
    *,
    turn: int = 1,
    episode: int = 1,
    controllers: Optional[Dict[str, Optional[int]]] = None,
    phase: str = "move",
) -> Dict[str, Any]:
    """État minimal mais RÉEL : `objective_hex_zones`, les empreintes par figurine et les cartes
    de distance du moteur le lisent sans indulgence.

    `squads` : `(id, joueur, (col, row))`. Une figurine par escouade, socle rond de taille 1 —
    le chemin mono-hexe de `iter_living_model_footprints`, donc empreinte = ancre.
    """
    units_cache: Dict[str, Any] = {}
    models_cache: Dict[str, Any] = {}
    squad_models: Dict[str, Any] = {}
    units: List[Dict[str, Any]] = []
    for squad_id, player, (col, row) in squads:
        units.append({"id": squad_id, "player": player, "VALUE": 5.0, "OC": 1,
                      "battle_shocked": False})
        units_cache[squad_id] = {
            "col": col, "row": row, "orientation": 0, "HP_CUR": 10, "player": player,
        }
        model_id = f"{squad_id}_m1"
        models_cache[model_id] = {
            "col": col, "row": row, "HP_CUR": 10,
            "BASE_SHAPE": "round", "BASE_SIZE": 1, "unit_id": squad_id,
        }
        squad_models[squad_id] = [model_id]
    return {
        "units": units,
        "units_cache": units_cache,
        "models_cache": models_cache,
        "squad_models": squad_models,
        "objectives": list(objectives),
        "objective_controllers": dict(controllers or {}),
        "victory_points": {1: 0, 2: 0},
        "turn": turn,
        "episode_number": episode,
        "phase": phase,
    }


def _kill(game_state: Dict[str, Any], squad_id: str) -> None:
    """Retire l'escouade du cache — c'est la définition de « morte » (`is_unit_alive`)."""
    del game_state["units_cache"][squad_id]


#: Poids de test : géométrie SEULE (w_fire et w_risk nuls), pour que la destination retenue soit
#: entièrement expliquée par les termes que ce fichier verrouille.
def _weights(w_obj: float = 1.0, w_enn: float = 0.0, w_contest: float = 0.0):
    return (w_obj, w_enn, 0.0, 0.0, w_contest)


# ─────────────────────────────────────────────────────────────────────────────────────────────
# §3.1 — assignation d'armée
# ─────────────────────────────────────────────────────────────────────────────────────────────


def test_une_reclamante_par_objectif_non_tenu() -> None:
    """Trois objectifs dont un tenu par le camp, trois escouades → deux réclamantes distinctes."""
    objectives = [
        {"id": "A", "hexes": _zone(10, 11, 10, 11)},
        {"id": "B", "hexes": _zone(30, 31, 10, 11)},
        {"id": "C", "hexes": _zone(50, 51, 10, 11)},
    ]
    gs = _game_state(
        objectives,
        [("s1", 1, (12, 10)), ("s2", 1, (32, 10)), ("s3", 1, (52, 10))],
        controllers={"A": 1},
    )
    claims = bb._assign_claimants(gs, player=1)

    assert set(claims.values()) == {1, 2}, f"attendu les zones B et C réclamées, obtenu {claims}"
    assert len(set(claims.values())) == len(claims), "deux escouades sur le même objectif"
    assert claims == {"s2": 1, "s3": 2}, f"assignation gloutonne au plus proche attendue : {claims}"


def test_aucune_reclamation_quand_le_camp_tient_tout() -> None:
    """Tous les objectifs tenus par le camp → personne ne réclame, tout le monde joue la doctrine."""
    objectives = [{"id": "A", "hexes": _zone(10, 11, 10, 11)}]
    gs = _game_state(objectives, [("s1", 1, (12, 10))], controllers={"A": 1})
    assert bb._assign_claimants(gs, player=1) == {}


def test_objectif_neutre_est_reclamable() -> None:
    """Détenteur `None` = objectif NON tenu par le camp, donc réclamable (et non « inconnu »)."""
    objectives = [{"id": "A", "hexes": _zone(10, 11, 10, 11)}]
    gs = _game_state(objectives, [("s1", 1, (12, 10))], controllers={})
    assert bb._assign_claimants(gs, player=1) == {"s1": 0}


def test_une_escouade_ne_reclame_qu_un_objectif() -> None:
    """Deux objectifs libres, UNE seule escouade : elle ne réclame que le plus proche."""
    objectives = [
        {"id": "A", "hexes": _zone(10, 11, 10, 11)},
        {"id": "B", "hexes": _zone(40, 41, 10, 11)},
    ]
    gs = _game_state(objectives, [("s1", 1, (13, 10))])
    assert bb._assign_claimants(gs, player=1) == {"s1": 0}


def test_escouade_hors_table_ne_reclame_pas() -> None:
    """Une escouade en réserves (sentinelle (-1,-1)) n'occupe rien : elle ne peut rien réclamer."""
    objectives = [{"id": "A", "hexes": _zone(10, 11, 10, 11)}]
    gs = _game_state(objectives, [("s1", 1, (-1, -1)), ("s2", 1, (30, 10))])
    assert bb._assign_claimants(gs, player=1) == {"s2": 0}


def test_claims_stables_dans_le_tour() -> None:
    """Le marqueur (épisode, tour, joueur) gèle l'assignation : bouger n'en change pas."""
    objectives = [
        {"id": "A", "hexes": _zone(10, 11, 10, 11)},
        {"id": "B", "hexes": _zone(40, 41, 10, 11)},
    ]
    gs = _game_state(objectives, [("s1", 1, (12, 10)), ("s2", 1, (38, 10))])
    bot = ReferenceBalancedBot(randomness=0.0)
    premier = dict(bot._army_claims(gs, player=1))

    # s1 traverse la table : sans le marqueur, l'assignation basculerait.
    gs["units_cache"]["s1"]["col"] = 39
    gs["models_cache"]["s1_m1"]["col"] = 39

    assert bot._army_claims(gs, player=1) == premier


def test_claims_recalcules_au_tour_suivant() -> None:
    """Tour suivant = nouveau marqueur = nouvelle assignation sur l'état courant."""
    objectives = [
        {"id": "A", "hexes": _zone(10, 11, 10, 11)},
        {"id": "B", "hexes": _zone(40, 41, 10, 11)},
    ]
    gs = _game_state(objectives, [("s1", 1, (12, 10)), ("s2", 1, (38, 10))])
    bot = ReferenceBalancedBot(randomness=0.0)
    assert bot._army_claims(gs, player=1) == {"s1": 0, "s2": 1}

    gs2 = _game_state(
        objectives, [("s1", 1, (39, 10)), ("s2", 1, (12, 10))], turn=2,
    )
    assert bot._army_claims(gs2, player=1) == {"s1": 1, "s2": 0}


def test_reclamante_morte_declenche_une_reassignation_dans_le_tour() -> None:
    """RUPTURE §3.1 : une réclamante morte libère son objectif SANS attendre le tour suivant."""
    objectives = [{"id": "A", "hexes": _zone(10, 11, 10, 11)}]
    gs = _game_state(objectives, [("s1", 1, (12, 10)), ("s2", 1, (20, 10))])
    bot = ReferenceBalancedBot(randomness=0.0)
    assert bot._army_claims(gs, player=1) == {"s1": 0}

    _kill(gs, "s1")  # même tour, même marqueur
    assert bot._army_claims(gs, player=1) == {"s2": 0}, (
        "l'objectif d'une réclamante morte doit être réattribué à la lecture suivante"
    )


def test_reclamante_joue_score_et_ne_charge_pas() -> None:
    """Une réclamante joue SCORE : son intention doctrinale n'est pas consultée en charge."""
    from ai.evaluation_bots import WAIT_ACTION

    objectives = [{"id": "A", "hexes": _zone(10, 11, 10, 11)}]
    gs = _game_state(
        objectives, [("s1", 1, (12, 10)), ("e1", 2, (13, 10))], phase="charge",
    )
    bot = ReferenceBalancedBot(randomness=0.0)
    active = gs["units"][0]
    assert bot._is_claimant(gs, active) is True
    assert bot.select_action_with_state([WAIT_ACTION, 999], gs, active) == WAIT_ACTION


def test_denial_reclamante_ne_charge_pas_meme_si_ennemi_sur_objectif() -> None:
    """ReferenceDenialBot : la garde _is_claimant bloque la charge avant le test de zone ennemi."""
    from ai.evaluation_bots import WAIT_ACTION

    # Ennemi placé SUR l'objectif A → sans la garde claimant, le bot chargerait (ligne 724).
    objectives = [{"id": "A", "hexes": _zone(10, 11, 10, 11)}]
    gs = _game_state(
        objectives,
        [("s1", 1, (12, 10)), ("e1", 2, (10, 10))],
        phase="charge",
    )
    bot = ReferenceDenialBot(randomness=0.0)
    active = gs["units"][0]
    assert bot._is_claimant(gs, active) is True, "précondition : s1 est réclamante"
    assert bot.select_action_with_state([WAIT_ACTION, mi.CHARGE_SLOTS[0]], gs, active) == WAIT_ACTION


def test_reactive_reclamante_ne_charge_pas_en_plan_kill() -> None:
    """ReferenceReactiveBot : _is_claimant bloque la charge même quand le plan est KILL (ligne 862)."""
    from ai.evaluation_bots import WAIT_ACTION

    objectives = [{"id": "A", "hexes": _zone(10, 11, 10, 11)}]
    gs = _game_state(
        objectives,
        [("s1", 1, (12, 10)), ("e1", 2, (20, 10))],
        phase="charge",
    )
    bot = ReferenceReactiveBot(randomness=0.0)
    # Forcer le plan KILL en gel du marqueur de tour : _update_plan retourne immédiatement.
    bot._snapshot_episode = gs["episode_number"]
    bot._plan_turn_marker = (gs["episode_number"], int(gs["turn"]))
    bot._plan = "KILL"

    active = gs["units"][0]
    assert bot._is_claimant(gs, active) is True, "précondition : s1 est réclamante"
    assert bot.select_action_with_state([WAIT_ACTION, mi.CHARGE_SLOTS[0]], gs, active) == WAIT_ACTION


# ─────────────────────────────────────────────────────────────────────────────────────────────
# §3.2 — prime de tenue
# ─────────────────────────────────────────────────────────────────────────────────────────────


def test_prime_de_tenue_retient_dans_la_zone() -> None:
    """Sur zone, l'escouade y reste plutôt que de gagner 3 hexes vers l'ennemi.

    Sans la prime, le score de la position courante vaut -9 (distance à l'ennemi) contre -8 à la
    candidate hors zone : le bot sort de la zone qu'il contrôle et perd le VP du tour. La prime
    (`_BENCH_HOLD_BONUS` = 3, pondérée par w_obj) porte la position courante à -6.
    """
    objectives = [{"id": "A", "hexes": _zone(10, 12, 10, 12)}]
    gs = _game_state(objectives, [("s1", 1, (11, 11)), ("e1", 2, (20, 11))])
    unit = gs["units"][0]
    dehors = (14, 11)

    choisi = bb._score_destinations_weighted(
        unit, (11, 11), [dehors], _weights(w_obj=1.0, w_enn=1.0), gs, contributions={},
    )
    assert choisi == (11, 11), (
        f"la prime de tenue doit garder l'escouade sur la zone, obtenu {choisi}"
    )


def test_prime_de_tenue_lue_par_figurine_et_non_par_ancre_pour_la_position_courante() -> None:
    """La position courante est lue PAR FIGURINE (14.02) : une figurine dans l'aire suffit.

    L'ancre d'escouade est hors zone ; la figurine, elle, y est. Sans la lecture par figurine la
    prime ne s'appliquerait pas et l'escouade sortirait.
    """
    objectives = [{"id": "A", "hexes": _zone(10, 12, 10, 12)}]
    gs = _game_state(objectives, [("s1", 1, (13, 11)), ("e1", 2, (20, 11))])
    gs["models_cache"]["s1_m1"]["col"] = 12  # la figurine est DANS l'aire, l'ancre non
    unit = gs["units"][0]

    # w_enn = 1.5 : sans la prime, la candidate l'emporte STRICTEMENT (-10,5 contre -11,5).
    choisi = bb._score_destinations_weighted(
        unit, (13, 11), [(15, 11)], _weights(w_obj=1.0, w_enn=1.5), gs, contributions={},
    )
    assert choisi == (13, 11), f"prime attendue sur la position courante, obtenu {choisi}"


# ─────────────────────────────────────────────────────────────────────────────────────────────
# §3.3 — anti-empilement des non-réclamantes
# ─────────────────────────────────────────────────────────────────────────────────────────────


def test_penalite_d_encombrement_renvoie_vers_la_zone_decouverte() -> None:
    """Une zone que les alliés tiennent déjà large repousse la non-réclamante vers l'autre.

    Sans la pénalité, la zone A (1 hexe de moins) l'emporte. Avec un surplus d'OC allié de 4 sur
    A, la distance effective de A monte de `_W_CROWD_BENCH x 4` et B devient la meilleure.
    """
    objectives = [
        {"id": "A", "hexes": _zone(10, 11, 10, 11)},
        {"id": "B", "hexes": _zone(20, 21, 10, 11)},
    ]
    gs = _game_state(objectives, [("s1", 1, (14, 10)), ("ally", 1, (10, 10))])
    unit = gs["units"][0]
    vers_a, vers_b = (12, 10), (18, 10)
    # `ally` apporte 4 d'OC sur la zone A et rien sur B — les contributions sont fournies telles
    # que le moteur les rendrait, sans repasser par le comptage complet.
    contributions = {"ally": (1, [4, 0])}

    choisi = bb._score_destinations_weighted(
        unit, (14, 10), [vers_a, vers_b], _weights(w_obj=1.0), gs, contributions=contributions,
    )
    assert choisi == vers_b, (
        f"la non-réclamante doit fuir la zone déjà tenue large, obtenu {choisi}"
    )


def test_sans_surplus_allie_la_non_reclamante_va_au_plus_proche() -> None:
    """Contrôle du test précédent : surplus nul → la géométrie seule décide, donc la zone A."""
    objectives = [
        {"id": "A", "hexes": _zone(10, 11, 10, 11)},
        {"id": "B", "hexes": _zone(20, 21, 10, 11)},
    ]
    gs = _game_state(objectives, [("s1", 1, (14, 10)), ("ally", 1, (10, 10))])
    unit = gs["units"][0]

    choisi = bb._score_destinations_weighted(
        unit, (14, 10), [(12, 10), (18, 10)], _weights(w_obj=1.0), gs, contributions={},
    )
    assert choisi == (12, 10), f"sans surplus, l'objectif le plus proche gagne : {choisi}"


def test_reclamante_ignore_l_encombrement_et_vise_son_objectif() -> None:
    """La réclamante vise SON objectif : ni la zone la plus proche, ni la pénalité d'empilement.

    Zone assignée = B (index 1), alors que A est plus proche et sans surplus. La destination
    retenue doit être celle qui se rapproche de B.
    """
    objectives = [
        {"id": "A", "hexes": _zone(10, 11, 10, 11)},
        {"id": "B", "hexes": _zone(20, 21, 10, 11)},
    ]
    gs = _game_state(objectives, [("s1", 1, (14, 10))])
    unit = gs["units"][0]

    choisi = bb._score_destinations_weighted(
        unit, (14, 10), [(12, 10), (18, 10)], _weights(w_obj=1.0), gs, assigned_zone=1,
    )
    assert choisi == (18, 10), f"la réclamante de B doit aller vers B, obtenu {choisi}"


# ─────────────────────────────────────────────────────────────────────────────────────────────
# §3.4 — géométrie par AIRE, et non par ancre
# ─────────────────────────────────────────────────────────────────────────────────────────────


def test_distance_mesuree_a_l_aire_et_non_a_l_ancre() -> None:
    """Sur une aire étendue, l'ancre (plus petites coordonnées) et l'aire ne classent PAS pareil.

    L'aire est une bande de 31 hexes de large. La candidate collée au bord DROIT en est à 1 hexe ;
    l'ancre de l'objectif est à son extrémité GAUCHE, donc à une trentaine d'hexes de cette même
    candidate. Le test vérifie les deux faces : la destination retenue est la plus proche de
    l'AIRE, et la métrique d'ancre aurait désigné l'autre.
    """
    objectives = [{"id": "A", "hexes": _zone(10, 40, 10, 10)}]
    gs = _game_state(objectives, [("s1", 1, (30, 14))])
    unit = gs["units"][0]
    pres_de_l_aire, pres_de_l_ancre = (38, 11), (14, 14)

    ancre = (10, 10)  # hexe de plus petites coordonnées de l'aire — l'ancienne géométrie
    d_ancre_aire = calculate_hex_distance(*pres_de_l_aire, *ancre)
    d_ancre_ancre = calculate_hex_distance(*pres_de_l_ancre, *ancre)
    assert d_ancre_ancre < d_ancre_aire, (
        "fixture invalide : la métrique d'ancre doit préférer l'autre candidate "
        f"({d_ancre_ancre} vs {d_ancre_aire})"
    )

    choisi = bb._score_destinations_weighted(
        unit, (30, 14), [pres_de_l_aire, pres_de_l_ancre], _weights(w_obj=1.0), gs,
        contributions={},
    )
    assert choisi == pres_de_l_aire, (
        f"la distance doit être mesurée à l'AIRE (14.02), obtenu {choisi}"
    )


def test_assignation_utilise_aussi_la_distance_a_l_aire() -> None:
    """L'assignation §3.1 mesure la même géométrie : l'escouade collée au bord de l'aire gagne."""
    objectives = [{"id": "A", "hexes": _zone(10, 40, 10, 10)}]
    gs = _game_state(objectives, [("s1", 1, (40, 12)), ("s2", 1, (10, 20))])
    # s1 est à 2 hexes de l'AIRE ; s2 est à 10 de l'aire mais colle presque l'ANCRE (10,10).
    assert bb._assign_claimants(gs, player=1) == {"s1": 0}


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Absence d'objectif — aucun terme d'objectif, aucun crash
# ─────────────────────────────────────────────────────────────────────────────────────────────


def test_scenario_sans_objectif_ne_leve_pas() -> None:
    """Sans objectif, seul le terme d'ennemi décide — et l'assignation est vide."""
    gs = _game_state([], [("s1", 1, (10, 10)), ("e1", 2, (20, 10))])
    unit = gs["units"][0]
    assert bb._assign_claimants(gs, player=1) == {}
    choisi = bb._score_destinations_weighted(
        unit, (10, 10), [(15, 10)], _weights(w_obj=1.0, w_enn=1.0), gs, contributions={},
    )
    assert choisi == (15, 10), "w_enn > 0 doit rapprocher de l'ennemi"
