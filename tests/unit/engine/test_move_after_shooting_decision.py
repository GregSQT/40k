#!/usr/bin/env python3
"""Le repositionnement après tir est une DÉCISION D'AGENT — jalon J2.

CE QUE CE FICHIER VERROUILLE. `move_after_shooting` (Purgation Run du LandSpeeder, Gargoyle)
déplace l'escouade après son tir. Le siège humain a toujours choisi la destination ; le gym et le
bot PvE, eux, la recevaient d'une heuristique — `_select_move_after_shooting_destination_for_ai`,
qui retenait la case la PLUS PROCHE de l'ennemi le plus proche. J2 promet qu'aucune décision de
jeu n'est jouée par une heuristique à la place de l'agent : ces tests prouvent que la question
est posée, que ses candidats sont exploitables, et que la réponse déplace réellement l'escouade.

Le point de choix est paramétré en INTENTIONS scorées, jamais en top-K d'hex : §9.0bis réserve 2,
le pool d'un D6" dépassant `MAX_DECISION_OPTIONS` dès la résolution x1 — ce que le premier test
de la dernière section mesure au lieu de le supposer.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

import pytest

from tests.unit.engine._config_helpers import build_move_rules
from engine.agent_decision import read_pending_agent_decision
from engine.observation_entities import (
    AGENT_DECISION_TYPE_IDS,
    AGENT_DECISION_TYPE_SLOTS,
    DECISION_CTX_BIN_FIELDS,
    DECISION_OPTION_CONT_FIELDS,
    MAX_DECISION_OPTIONS,
)
from engine.phase_handlers.shared_utils import (
    build_enemy_adjacent_hexes,
    build_units_cache,
)
from engine.phase_handlers.shooting_handlers import (
    ACTION,
    SHOOTING,
    _handle_shooting_end_activation,
    apply_move_after_shooting_decision,
    arm_move_after_shooting_decision,
    _build_move_after_shooting_destinations,
)
from engine.w40k_core import W40KEngine
from tests._state_invariants import turn_state_invariants, unit_invariants


_SHOOTER = (10, 20)
_ENEMY = (10, 30)
#: Objectif placé sur un TROISIÈME axe : l'ennemi est au sud, donc le retrait part au nord, et
#: un objectif au nord se confondrait avec lui — les deux intentions désigneraient la même case
#: et la déduplication en retirerait une. À l'ouest, les trois intentions se séparent, ce qui est
#: la seule configuration où ce test peut voir que l'agent reçoit un vrai choix.
_OBJECTIVE = (2, 20)

#: Distance FIXE (pouces) au lieu du D6 de la datasheet : `_resolve_move_after_shooting_distance`
#: accepte les deux, et un jet rendrait le pool — donc les destinations attendues — aléatoire.
_MOVE_AFTER_SHOOTING_INCHES = 3


def _gs(
    *,
    gym: bool = True,
    pve: bool = False,
    with_enemy: bool = True,
    shooter_player: int = 1,
) -> Dict[str, Any]:
    """`game_state` minimal : un tireur porteur de la règle, un ennemi hors zone d'engagement.

    ``shooter_player`` existe pour le siège PvE : le bot y est le joueur 2 et LUI SEUL
    (`is_pve_ai` le vérifie), donc un tireur du joueur 1 y suivrait le chemin humain.
    """
    shooter: Dict[str, Any] = {**unit_invariants(),
        "id": "1", "player": shooter_player, "col": _SHOOTER[0], "row": _SHOOTER[1], "MOVE": 10,
        "HP_CUR": 2, "HP_MAX": 2, "VALUE": 50, "OC": 1, "T": 4,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "SHOOT_LEFT": 0, "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [], "CC_WEAPONS": [],
        "BASE_SIZE": 1, "BASE_SHAPE": "round", "MODEL_HEIGHT": 2.5,
        "UNIT_KEYWORDS": [],
        "UNIT_RULES": [
            {
                "ruleId": "move_after_shooting",
                "displayName": 'Purgation Run (test)',
                "rule_args": {"distance": _MOVE_AFTER_SHOOTING_INCHES},
            }
        ],
    }
    enemy: Dict[str, Any] = {**unit_invariants(),
        "id": "2", "player": 3 - shooter_player, "col": _ENEMY[0], "row": _ENEMY[1], "MOVE": 6,
        "HP_CUR": 2, "HP_MAX": 2, "VALUE": 50, "OC": 1, "T": 4,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "SHOOT_LEFT": 1, "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [], "CC_WEAPONS": [],
        "BASE_SIZE": 1, "BASE_SHAPE": "round", "MODEL_HEIGHT": 2.5,
        "UNIT_KEYWORDS": [], "UNIT_RULES": [],
    }
    units = [shooter, enemy] if with_enemy else [shooter]
    gs: Dict[str, Any] = {**turn_state_invariants(),
        "config": {
            "game_rules": {"engagement_zone": 1, "unit_model_cohesion_range": 2,
                           "unit_global_cohesion_range": 9,
                           "cohesion_distance_mode": "euclidean", "squad_min_neighbors": 1},
            "move": build_move_rules(),
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
            "gym_training_mode": gym,
            "pve_mode": pve,
        },
        "board_cols": 44,
        "board_rows": 60,
        "current_player": shooter_player,
        "phase": "shoot",
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "shoot_activation_pool": ["1"],
        "objectives": [{"id": "obj1", "hexes": [[_OBJECTIVE[0], _OBJECTIVE[1]]]}],
        "console_logs": [],
        "gym_training_mode": gym,
        "pve_mode": pve,
        "inches_to_subhex": 1,
    }
    build_units_cache(gs)
    build_enemy_adjacent_hexes(gs, 1)
    build_enemy_adjacent_hexes(gs, 2)
    return gs


def _shooter_position(gs: Dict[str, Any]) -> Tuple[int, int]:
    unit = gs["unit_by_id"]["1"]
    return (int(unit["col"]), int(unit["row"]))


def _end_shooting_activation(gs: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """Le VRAI chemin de production : la fin d'activation d'un tir réel (arg1/arg3/arg5)."""
    return _handle_shooting_end_activation(
        gs, gs["unit_by_id"]["1"], ACTION, 1, SHOOTING, SHOOTING, 1
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. LE CONTRAT D'OBSERVATION N'A PAS BOUGÉ
# ─────────────────────────────────────────────────────────────────────────────


def test_ouvrir_le_type_consomme_une_reserve_et_laisse_obs_size_intact():
    """Déclarer un type de plus consomme une colonne RÉSERVÉE, jamais n'en ajoute une.

    C'est la condition d'entrée du chantier : sans elle, rendre cette décision à l'agent
    imposerait un `--new` de plusieurs dizaines d'heures pour une seule capacité d'unité.
    """
    assert "move_after_shooting" in AGENT_DECISION_TYPE_IDS
    assert len(AGENT_DECISION_TYPE_IDS) <= AGENT_DECISION_TYPE_SLOTS
    assert len(DECISION_CTX_BIN_FIELDS) == 1 + AGENT_DECISION_TYPE_SLOTS


# ─────────────────────────────────────────────────────────────────────────────
# 2. LA QUESTION EST POSÉE — ET L'ESCOUADE N'A PAS BOUGÉ ENTRE-TEMPS
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("gym,pve,shooter_player", [(True, False, 1), (False, True, 2)])
def test_le_siege_pilote_par_le_modele_est_interroge_au_lieu_d_etre_deplace(
    gym, pve, shooter_player
):
    """Gym ET bot PvE : les deux sièges que l'heuristique servait reçoivent la question.

    L'assertion sur la position est le cœur du test : une décision posée APRÈS un déplacement
    déjà appliqué serait un choix sans objet.
    """
    gs = _gs(gym=gym, pve=pve, shooter_player=shooter_player)
    success, result = _end_shooting_activation(gs)

    assert success is True
    assert result["action"] == "waiting_for_agent_decision"
    assert result["waiting_for_player"] is True
    assert result["decision_type"] == "move_after_shooting"
    assert _shooter_position(gs) == _SHOOTER

    decision = read_pending_agent_decision(gs)
    assert decision is not None
    assert decision["type"] == "move_after_shooting"
    assert decision["unit_id"] == "1"
    assert decision["player"] == shooter_player


def test_le_siege_humain_garde_son_prompt_pvp_inchange():
    """Le flux PvP n'est pas touché : il conserve `move_after_shooting_select_destination`."""
    gs = _gs(gym=False, pve=False)
    success, result = _end_shooting_activation(gs)

    assert success is True
    assert result["action"] == "move_after_shooting_select_destination"
    assert result["can_skip_move_after_shooting"] is True
    assert read_pending_agent_decision(gs) is None
    assert _shooter_position(gs) == _SHOOTER


# ─────────────────────────────────────────────────────────────────────────────
# 3. LES CANDIDATS SONT EXPLOITABLES PAR L'AGENT
# ─────────────────────────────────────────────────────────────────────────────


def test_les_candidats_offrent_des_intentions_distinctes_et_un_seul_refus():
    """Un candidat par intention CONSTRUCTIBLE, plus le refus — et jamais deux fois la même case.

    Deux candidats à la même destination porteraient des `options_cont` identiques : logits
    égaux, gradients égaux, symétrie incassable — le défaut mesuré sur `waaagh_call`.
    """
    gs = _gs()
    _end_shooting_activation(gs)
    decision = read_pending_agent_decision(gs)
    assert decision is not None
    options = decision["options"]

    assert 2 <= len(options) <= MAX_DECISION_OPTIONS
    assert sum(1 for option in options if option["declines"]) == 1
    assert options[-1]["declines"] is True
    assert options[-1]["payload"] == {"skip_move_after_shooting": True}

    destinations = [
        (option["payload"]["destCol"], option["payload"]["destRow"])
        for option in options if not option["declines"]
    ]
    assert len(destinations) == len(set(destinations))
    assert _SHOOTER not in destinations

    assert len(decision["options_cont"]) == len(options)
    for row in decision["options_cont"]:
        assert len(row) == len(DECISION_OPTION_CONT_FIELDS)
        assert all(0.0 <= value <= 1.0 for value in row)


def test_le_candidat_rester_est_decrit_par_la_position_actuelle():
    """« Rester » porte les distances de la case OCCUPÉE, pas des zéros.

    Des zéros décriraient une escouade collée à l'ennemi et à l'objectif : l'agent choisirait
    de ne pas bouger sur une description fausse.
    """
    from engine.observation_entities import DECISION_OPTION_CONT_FIELDS as fields

    gs = _gs()
    _end_shooting_activation(gs)
    decision = read_pending_agent_decision(gs)
    assert decision is not None

    stay_row = decision["options_cont"][-1]
    assert decision["options"][-1]["declines"] is True
    assert stay_row[fields.index("dist_enemy_norm")] > 0.0
    assert stay_row[fields.index("obj_dist_norm")] > 0.0

    # `> 0.0` ne distingue pas la case OCCUPÉE d'une destination quelconque : la ligne de
    # « Rester » et celles des candidats sortent du même producteur, et une case passée à tort
    # resterait strictement positive. Encadrer suffit à trancher — « Pression » est par
    # construction plus proche de l'ennemi que rester, « Retrait » plus loin.
    enemy = fields.index("dist_enemy_norm")
    assert decision["options"][0]["label"].startswith("Pression")
    assert decision["options"][1]["label"].startswith("Retrait")
    assert (
        decision["options_cont"][0][enemy]
        < stay_row[enemy]
        < decision["options_cont"][1][enemy]
    )


def test_l_intention_objectif_rapproche_du_marqueur_et_le_retrait_eloigne_de_l_ennemi():
    """Les intentions font ce que leur nom dit — sinon le choix offert est décoratif."""
    gs = _gs()
    _end_shooting_activation(gs)
    decision = read_pending_agent_decision(gs)
    assert decision is not None

    by_label = {
        option["label"].split(" ")[0]: option["payload"]
        for option in decision["options"] if not option["declines"]
    }
    # L'ennemi est au sud, l'objectif à l'ouest : chaque intention part de son côté. La colonne
    # sert de repère à l'objectif et la ligne à l'ennemi — sur une grille hex, un pas latéral
    # décale aussi la ligne, donc mesurer les trois sur le même axe ne prouverait rien.
    assert by_label["Objectif"]["destCol"] < _SHOOTER[0]
    assert by_label["Retrait"]["destRow"] < _SHOOTER[1]
    assert by_label["Pression"]["destRow"] > _SHOOTER[1]


def test_le_premier_candidat_est_la_destination_de_pression():
    """`options[0]` porte la case la PLUS PROCHE de l'ennemi le plus proche.

    Ce n'est pas une préférence d'ordre : c'est la seule destination que rendait
    `_select_move_after_shooting_destination_for_ai` avant J2, donc la baseline du bot adverse.
    `env_wrappers.bot_action_for_pending_choice` répond `CHOICE_0` à cette décision pour que
    l'adversaire de référence ne se remette pas à bouger au hasard sous l'agent qu'on mesure ;
    ce test est ce sur quoi ce choix repose.
    """
    gs = _gs()
    _end_shooting_activation(gs)
    decision = read_pending_agent_decision(gs)
    assert decision is not None

    assert decision["options"][0]["label"].startswith("Pression")

    enemy_column = DECISION_OPTION_CONT_FIELDS.index("dist_enemy_norm")
    distances = [row[enemy_column] for row in decision["options_cont"]]
    assert distances[0] == min(distances)


def test_sans_ennemi_sur_la_table_seules_les_intentions_constructibles_sont_offertes():
    """Aucun ennemi (détruits, ou tous en réserves 20.01) : pas d'intention scorée sur du vide."""
    gs = _gs(with_enemy=False)
    _end_shooting_activation(gs)
    decision = read_pending_agent_decision(gs)
    assert decision is not None

    labels = [option["label"] for option in decision["options"]]
    assert not any(label.startswith(("Pression", "Retrait")) for label in labels)
    assert any(label.startswith("Objectif") for label in labels)
    # `CHOICE_0` n'est donc PAS « Pression » dans ce cas, et la baseline du bot
    # (`env_wrappers.bot_action_for_pending_choice`) joue « Objectif ». Ce n'est pas une
    # divergence : l'heuristique supprimée rendait ici `destinations[0]`, départage arbitraire du
    # pool BFS. Ce qui est verrouillé est que le premier candidat reste DÉTERMINISTE.
    assert labels[0].startswith("Objectif")


def test_ni_ennemi_ni_objectif_ne_pose_aucune_decision():
    """Rien à arbitrer : l'activation se termine plutôt que de poser un choix à candidat unique."""
    gs = _gs(with_enemy=False)
    gs["objectives"] = []
    success, result = _end_shooting_activation(gs)

    assert success is True
    assert read_pending_agent_decision(gs) is None
    assert result["activation_complete"] is True
    assert _shooter_position(gs) == _SHOOTER


# ─────────────────────────────────────────────────────────────────────────────
# 4. LA RÉPONSE DE L'AGENT DÉPLACE RÉELLEMENT L'ESCOUADE
# ─────────────────────────────────────────────────────────────────────────────


def test_choisir_une_intention_deplace_l_escouade_a_sa_destination():
    """`CHOICE_k` → l'escouade est à la case du candidat, et l'activation se termine."""
    gs = _gs()
    _end_shooting_activation(gs)
    decision = read_pending_agent_decision(gs)
    assert decision is not None
    payload = decision["options"][0]["payload"]

    success, result = apply_move_after_shooting_decision(
        gs, gs["unit_by_id"]["1"], payload
    )

    assert success is True
    assert _shooter_position(gs) == (payload["destCol"], payload["destRow"])
    assert result["activation_complete"] is True
    # L'état d'attente est purgé : `shooting_clear_activation_state` retire jusqu'au drapeau
    # `_move_after_shooting_resolved`, de sorte que la prochaine activation reparte à zéro.
    assert "_pending_move_after_shooting" not in gs["unit_by_id"]["1"]
    assert "_move_after_shooting_resolved" not in gs["unit_by_id"]["1"]
    # La ligne d'`action_logs` est ce que lisent le replay et l'analyzer : passer par le handler
    # du PvP la produit, là où la branche gym supprimée la faisait remonter par un relais à part.
    assert any(entry.get("type") == "move_after_shooting" for entry in gs["action_logs"])


def test_refuser_laisse_l_escouade_sur_place_et_termine_l_activation():
    """Le candidat `declines` est un vrai choix de la règle, pas un repli silencieux."""
    gs = _gs()
    _end_shooting_activation(gs)
    decision = read_pending_agent_decision(gs)
    assert decision is not None

    success, result = apply_move_after_shooting_decision(
        gs, gs["unit_by_id"]["1"], decision["options"][-1]["payload"]
    )

    assert success is True
    assert _shooter_position(gs) == _SHOOTER
    assert result["activation_complete"] is True


def test_une_reponse_visant_une_escouade_sans_attente_est_refusee():
    """La garde qui remplace le contrôle d'`unit_id` : sans `_pending_move_after_shooting`, non."""
    gs = _gs()
    success, result = apply_move_after_shooting_decision(
        gs, gs["unit_by_id"]["1"], {"skip_move_after_shooting": True}
    )

    assert success is False
    assert result["error"] == "no_pending_move_after_shooting"


def test_le_dispatcher_de_decision_route_bien_le_type():
    """`_handle_agent_decision_action` traite le type — sinon rien de ce qui précède n'est atteint.

    La méthode de production est appelée telle quelle ; seul le porteur d'état est simulé, la
    branche ne lisant de `self` que `game_state`.
    """
    gs = _gs()
    _end_shooting_activation(gs)
    decision = read_pending_agent_decision(gs)
    assert decision is not None
    expected = decision["options"][0]["payload"]

    # Instance sans `__init__` : la branche ne lit de `self` que `game_state`, et monter un
    # moteur complet ferait dépendre ce test du chargement d'un scénario.
    engine = W40KEngine.__new__(W40KEngine)
    engine.game_state = gs
    success, result = engine._handle_agent_decision_action({"option_index": 0})

    assert success is True
    assert result["decision_type"] == "move_after_shooting"
    assert result["option_index"] == 0
    assert read_pending_agent_decision(gs) is None
    assert _shooter_position(gs) == (expected["destCol"], expected["destRow"])

    # DEUX entrées de journal pour UN step gym, et c'est l'invariant de COMPTAGE : la ligne
    # d'EFFET (`move_after_shooting`, incrémentante) compte le step que `CHOICE_i` a consommé, le
    # RELEVÉ (`agent_decision`, non incrémentant) le NOMME sans le recompter. C'est mot pour mot
    # ce que le commentaire de `_STEP_LOG_NON_INCREMENTING_TYPES` affirme des types « qui
    # produisent une ligne d'effet », et aucun test ne le couvrait : `reserves_declaration`, seul
    # type journalisé de bout en bout (`test_step_log_agent_decision.py`), n'en produit AUCUNE —
    # sur lui, les deux comptages sont indiscernables.
    journalises = [str(entry["type"]) for entry in gs["action_logs"]]
    assert journalises == ["move_after_shooting", "agent_decision"], journalises
    assert "move_after_shooting" not in W40KEngine._STEP_LOG_NON_INCREMENTING_TYPES
    assert "agent_decision" in W40KEngine._STEP_LOG_NON_INCREMENTING_TYPES
    for _journalise in journalises:
        assert _journalise in W40KEngine._STEP_LOG_TYPE_MAP, (
            f"'{_journalise}' hors de la liste blanche : la ligne n'atteint jamais step.log"
        )

    releve = gs["action_logs"][-1]
    assert releve["decision_type"] == "move_after_shooting"
    assert releve["decision_option_index"] == 0
    assert releve["decision_option_declines"] is False, "CHOICE_0 se déplace, il ne passe pas"
    assert str(releve["unitId"]) == "1"
    assert releve["message"], "le relevé doit nommer le candidat joué, pas une case vide"
    # VIDE et non absent : `_build_step_log_details` lit la clé, et son absence le ferait aller
    # chercher les positions LIVE par socle sur une ligne qui n'observe aucun déplacement.
    assert releve["models_segment"] == ""


# ─────────────────────────────────────────────────────────────────────────────
# 5. POURQUOI DES INTENTIONS, ET PAS LES HEX EUX-MÊMES
# ─────────────────────────────────────────────────────────────────────────────


def test_le_pool_de_destinations_depasse_le_plafond_de_candidats():
    """§9.0bis réserve 2, MESURÉE ici : un top-K d'hex tronquerait l'espace de choix.

    Le pool est mesuré sur le vrai énumérateur ; si un jour il tenait sous le plafond, exposer
    les cases elles-mêmes redeviendrait légitime et ce test le signalerait.
    """
    gs = _gs()
    destinations = _build_move_after_shooting_destinations(
        gs, gs["unit_by_id"]["1"], _MOVE_AFTER_SHOOTING_INCHES
    )
    assert len(destinations) > MAX_DECISION_OPTIONS


def test_l_heuristique_de_destination_n_existe_plus():
    """Le verrou de non-régression du jalon J2 : plus aucun siège ne peut la rappeler."""
    import engine.phase_handlers.shooting_handlers as shooting_handlers

    assert not hasattr(shooting_handlers, "_select_move_after_shooting_destination_for_ai")


def test_l_armement_est_le_seul_a_poser_l_etat_d_attente():
    """L'armement pose l'état que le handler PvP consomme — c'est ce qui mutualise les sièges."""
    gs = _gs()
    unit = gs["unit_by_id"]["1"]
    destinations = _build_move_after_shooting_destinations(
        gs, unit, _MOVE_AFTER_SHOOTING_INCHES
    )

    assert arm_move_after_shooting_decision(
        gs, unit, destinations, _MOVE_AFTER_SHOOTING_INCHES
    ) is not None
    assert unit["_pending_move_after_shooting"] is True
    assert unit["_move_after_shooting_destinations"] == destinations
    assert unit["_move_after_shooting_distance"] == _MOVE_AFTER_SHOOTING_INCHES
