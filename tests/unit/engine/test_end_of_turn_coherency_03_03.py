"""V11 T6-i — Etape End of Turn : REGAINING COHERENCY (03.03).

Regle (Documentation/40k_rules, 03 Moving / Unit Coherency) :
« In the End of Turn step of each player's turn, if one or more units on the battlefield are not
in coherency, those units' controlling players must remove models from them, one at a time, until
they are in coherency again. Models removed in this way are destroyed, but they do not trigger
rules that apply when a model is destroyed. »

Pourquoi ce fichier existe : le fix a ete livre le 2026-07-19 et n'etait couvert QUE par un run
bout-en-bout. Il avait deja bouge deux fois (branche d'abord sur `_advance_to_next_player`, qui
est du CODE MORT — le crash s'etait reproduit a l'identique). Un run n'est pas un test : il ne
rejouera pas au prochain refactor.

Le verrou le plus important est `test_both_fight_end_paths_call_the_step` : les deux chemins de
fin de Fight sont vivants et doivent appeler l'etape. C'est precisement ce qu'un futur refactor
cassera sans s'en apercevoir.
"""

import pytest

from engine.phase_handlers import fight_handlers
from engine.phase_handlers.shared_utils import (
    _coherency_seat_is_muet,
    arm_next_coherency_pending,
    end_of_turn_coherency_removal,
    end_of_turn_regain_coherency_all_squads,
    validate_squad_coherency,
)
from shared.data_validation import ConfigurationError


def _gs(positions, squad_id="1", player=1):
    """game_state minimal : ce que lisent la coherency (03.03) et `destroy_model`.

    `positions` : liste de (col, row), une par figurine, dans l'ordre des index (le tie-break de
    retrait est l'index croissant).
    """
    mids = [f"{squad_id}#{i}" for i in range(len(positions))]
    models_cache = {
        mid: {
            "col": int(col), "row": int(row), "level": 0, "player": player,
            "squad_id": squad_id, "HP_CUR": 1, "HP_MAX": 2,
            "T": 4, "ARMOR_SAVE": 3, "INVUL_SAVE": 7,
            "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
        }
        for mid, (col, row) in zip(mids, positions)
    }
    return {
        "models_cache": models_cache,
        "squad_models": {squad_id: list(mids)},
        "units_cache": {
            squad_id: {
                "col": int(positions[0][0]), "row": int(positions[0][1]), "player": player,
                "HP_CUR": len(positions), "BASE_SHAPE": "round", "BASE_SIZE": 1,
                "orientation": 0, "occupied_hexes": set(), "occupied_hexes_by_model": {},
            }
        },
        "board_cols": 44,
        "board_rows": 60,
        "wall_hexes": set(),
        # `destroy_model` invalide la LoS de l'escouade amputee : compteur present dans tout
        # game_state reel (w40k_core), donc requis ici aussi.
        "_unit_move_version": 0,
        # PvE bot : les DEUX sieges sont muets (retrait auto, critere geometrique).
        # Gym (gym_training_mode=True) rend les sieges non-muets (l'agent repond par masque) ;
        # human PvP aussi. Ici on simule le cas PvE ou les deux joueurs sont des IA.
        "player_types": {"1": "ai", "2": "ai"},
        # current_player requis par end_of_turn_regain_coherency_all_squads pour filtrer la queue.
        "current_player": player,
        # Valeurs de config/game_config.json, deja converties en subhex par w40k_core a l'init.
        "config": {"game_rules": {
            "unit_model_cohesion_range": 2,
            "unit_global_cohesion_range": 9,
            "squad_min_neighbors": 1,
            "cohesion_distance_mode": "euclidean",
            "engagement_zone": 1,
        }},
        # destroy_model émet un event "dead" via append_action_log → action_log_seq requis.
        "action_logs": [],
        "action_log_seq": 0,
        # _coherency_alive lit HP_MAX/T/ARMOR_SAVE/INVUL_SAVE via get_unit_by_id (unit_by_id).
        # HP_MAX=2 correspond à celui des modèles dans models_cache : squad_defence=(2,4,3,7)
        # fait passer les figurines de base par le branch `1` de _squad_models_for_observation.
        "unit_by_id": {
            squad_id: {
                "id": squad_id, "player": player,
                "HP_MAX": 2, "T": 4, "ARMOR_SAVE": 3, "INVUL_SAVE": 7,
            }
        },
    }


def _alive(gs, squad_id="1"):
    return [m for m in gs["squad_models"][squad_id] if m in gs["models_cache"]]


# --- (a) une escouade rendue incoherente redevient coherente apres la fin de tour -------------

def test_incoherent_squad_regains_coherency():
    """3 figurines dont une isolee loin : apres l'etape, l'escouade est coherente."""
    gs = _gs([(10, 10), (11, 10), (30, 40)])
    assert not validate_squad_coherency(gs, "1"), "fixture invalide : squad deja coherent"

    removed = end_of_turn_regain_coherency_all_squads(gs)

    assert validate_squad_coherency(gs, "1")
    assert removed == {"1": ["1#2"]}, "la figurine retiree doit etre l'isolee"
    assert _alive(gs) == ["1#0", "1#1"]


def test_coherent_squad_is_untouched():
    """Aucune figurine retiree si la formation est deja coherente (l'etape n'est pas punitive)."""
    gs = _gs([(10, 10), (11, 10), (12, 10)])
    assert validate_squad_coherency(gs, "1")

    assert end_of_turn_regain_coherency_all_squads(gs) == {}
    assert len(_alive(gs)) == 3


def test_both_players_are_processed():
    """La regle vise « units on the battlefield » : les escouades des DEUX joueurs sont traitees.

    Ici les deux sieges sont muets (AI) → retrait geometrique immediat pour les deux.
    current_player=1 : l'escouade de player 2 est aussi resolue automatiquement.
    """
    gs = _gs([(10, 10), (11, 10), (30, 40)], squad_id="1", player=1)
    gs2 = _gs([(20, 20), (21, 20), (5, 50)], squad_id="2", player=2)
    gs["models_cache"].update(gs2["models_cache"])
    gs["squad_models"].update(gs2["squad_models"])
    gs["units_cache"].update(gs2["units_cache"])
    # current_player=1 : les deux escouades sont muetes → les deux resolues geometriquement.
    gs["current_player"] = 1

    removed = end_of_turn_regain_coherency_all_squads(gs)

    assert sorted(removed) == ["1", "2"]
    assert validate_squad_coherency(gs, "1") and validate_squad_coherency(gs, "2")


# --- (b) retrait UNE A UNE, et jamais la derniere figurine ------------------------------------

def test_removal_is_minimal_one_model_at_a_time():
    """Deux isolees : exactement 2 retraits, et retirer moins n'aurait pas suffi."""
    gs = _gs([(10, 10), (11, 10), (30, 40), (5, 55)])
    assert not validate_squad_coherency(gs, "1")

    removed = end_of_turn_regain_coherency_all_squads(gs)["1"]

    assert len(removed) == 2
    assert set(removed) == {"1#2", "1#3"}
    # Le retrait s'arrete des le retour en coherency : les 2 figurines groupees survivent.
    assert _alive(gs) == ["1#0", "1#1"]


def test_last_model_is_never_removed():
    """2 figurines eloignees l'une de l'autre : le retrait s'arrete a 1 survivante.

    Sans cette borne, une escouade incoherente de 2 figurines serait entierement effacee — la
    regle demande de retirer « until they are in coherency again », et une unite d'une figurine
    est coherente d'office (03.03).
    """
    gs = _gs([(10, 10), (35, 45)])
    assert not validate_squad_coherency(gs, "1")

    removed = end_of_turn_coherency_removal(gs, "1")

    assert len(removed) == 1
    assert len(_alive(gs)) == 1
    assert validate_squad_coherency(gs, "1")


# --- (c) le retrait ne doit declencher aucune regle « quand une figurine est detruite » --------

def test_removal_uses_coherency_removal_reason(monkeypatch):
    """`reason='coherency_removal'` est le discriminant qui evite reward kill et perte d'OC.

    Le comptage de kills se fait au SITE APPELANT du combat (`g['kills'] += 1`), jamais dans
    `destroy_model` : c'est la `reason` qui distingue le retrait reglementaire du combat.
    """
    import engine.phase_handlers.shared_utils as su

    seen = []
    real = su.destroy_model

    def spy(game_state, model_id, reason):
        seen.append((model_id, reason))
        return real(game_state, model_id, reason)

    monkeypatch.setattr(su, "destroy_model", spy)

    gs = _gs([(10, 10), (11, 10), (30, 40)])
    end_of_turn_regain_coherency_all_squads(gs)

    assert seen == [("1#2", "coherency_removal")]


def test_removal_does_not_increment_combat_kill_counters():
    """Aucun compteur de kills du contexte de combat n'est cree/incremente par l'etape."""
    gs = _gs([(10, 10), (11, 10), (30, 40)])
    end_of_turn_regain_coherency_all_squads(gs)

    for key in ("kills", "killed_model_ids", "shoot_ctx", "FIGHT_CTX"):
        assert key not in gs, f"l'etape 03.03 ne doit pas toucher {key!r}"


# --- (d) LES DEUX chemins de fin de Fight appellent l'etape ------------------------------------

def _fight_end_gs():
    """game_state minimal accepte par les deux chemins de fin de phase Fight (mode gym)."""
    gs = _gs([(10, 10), (11, 10), (30, 40)])
    gs.update({
        "current_player": 2,
        "turn": 1,
        "phase": "fight",
        "charging_activation_pool": [],
        "active_alternating_activation_pool": [],
        "non_active_alternating_activation_pool": [],
        "units_fought": [],
        "units_selected_to_fight": set(),
        "console_logs": [],
        # Journal d'actions : l'etape 03.03 y ecrit sa ligne de retrait (cf. section (e)). Present
        # dans tout game_state reel (initialise par w40k_core), et deja exige par les autres
        # `append_action_log` de la phase de combat.
        "action_logs": [],
        "action_log_seq": 0,
    })
    gs["config"]["game_rules"]["max_turns"] = 5
    return gs


@pytest.mark.parametrize(
    "phase_complete",
    [fight_handlers._fight_phase_complete, fight_handlers._fight_v11_phase_complete],
)
def test_both_fight_end_paths_call_the_step(monkeypatch, phase_complete):
    """Les deux chemins sont VIVANTS et ne doivent pas pouvoir diverger.

    Fight est la derniere phase du tour : c'est la que le tour s'acheve. Le helper est partage,
    mais rien n'empeche un refactor de ne rebrancher qu'un seul chemin — d'ou ce test.
    """
    calls = []
    real = fight_handlers.end_of_turn_regain_coherency_all_squads
    monkeypatch.setattr(
        fight_handlers,
        "end_of_turn_regain_coherency_all_squads",
        lambda gs: (calls.append(gs), real(gs))[1],
    )

    gs = _fight_end_gs()
    phase_complete(gs)

    assert len(calls) == 1, "l'etape End of Turn 03.03 n'est pas appelee sur ce chemin"
    assert validate_squad_coherency(gs, "1")


@pytest.mark.parametrize(
    "phase_complete",
    [fight_handlers._fight_phase_complete, fight_handlers._fight_v11_phase_complete],
)
def test_step_runs_before_the_turn_limit_test(monkeypatch, phase_complete):
    """L'etape precede le test de limite de tour : l'etat FINAL de la partie respecte la regle.

    On force la fin de partie (tour courant > max_turns au prochain increment) et on verifie que
    l'etape a quand meme tourne.
    """
    import engine.game_utils as game_utils

    monkeypatch.setattr(game_utils, "get_effective_turn_limit", lambda gs: 1)

    gs = _fight_end_gs()
    gs["turn"] = 1
    gs["current_player"] = 2

    phase_complete(gs)

    assert validate_squad_coherency(gs, "1")
    assert len(_alive(gs)) == 2


# --- (e) le retrait LAISSE UNE TRACE dans le journal -------------------------------------------
#
# 03.03 est la seule mort qui ne descend d'aucune attaque : sans ligne d'action, aucun lecteur
# reconstruisant l'etat par accumulation d'evenements (analyzer, replay) n'apprend le retrait, et
# la figurine retiree continue d'engager ses ennemis et de bloquer leurs chemins jusqu'a la
# prochaine action de son escouade. Mesure sur le run du 2026-08-12 (E485) : la figurine `2#9`,
# retiree ici, a fabrique a elle seule un « advance from adjacent » ET un « advance au-dela du
# budget » sur l'escouade adverse.


def _log_gs():
    """game_state du helper de journalisation : compteur de sequence + tour."""
    gs = _gs([(10, 10), (11, 10), (30, 40)])
    gs.update({"turn": 3, "action_log_seq": 0, "action_logs": []})
    return gs


def _coherency_entries(gs):
    return [e for e in gs["action_logs"] if e["type"] == "coherency_removal"]


def test_removal_emits_an_action_log_entry():
    """VERROU : supprimer l'`append_action_log` de `_log_end_of_turn_coherency_removals` rend ce
    test ROUGE — c'est exactement l'etat dans lequel le moteur a vecu jusqu'au 2026-08-12."""
    gs = _log_gs()

    fight_handlers._log_end_of_turn_coherency_removals(
        gs, end_of_turn_regain_coherency_all_squads(gs)
    )

    entries = _coherency_entries(gs)
    assert len(entries) == 1, "un retrait 03.03 doit produire UNE entree d'action_log par escouade"
    assert entries[0]["unitId"] == "1"
    assert entries[0]["removed_models"] == ["1#2"]
    assert entries[0]["player"] == 1
    assert entries[0]["turn"] == 3


def test_no_removal_emits_nothing():
    """Une escouade coherente ne produit aucune ligne : le journal ne se remplit pas a vide."""
    gs = _log_gs()
    gs["models_cache"]["1#2"].update({"col": 12, "row": 10})

    fight_handlers._log_end_of_turn_coherency_removals(
        gs, end_of_turn_regain_coherency_all_squads(gs)
    )

    assert _coherency_entries(gs) == []


def test_logged_anchor_is_the_post_removal_one():
    """L'ancre journalisee est celle d'APRES retrait — `destroy_model` la recalcule quand c'est
    l'ancre qui tombe, et une ligne qui porterait l'ancienne contredirait son propre `[MODELS:]`."""
    # L'isolee est ici la figurine d'INDEX 0, donc l'ancre initiale de l'escouade.
    gs = _gs([(30, 40), (10, 10), (11, 10)])
    gs.update({"turn": 1, "action_log_seq": 0, "action_logs": []})

    fight_handlers._log_end_of_turn_coherency_removals(
        gs, end_of_turn_regain_coherency_all_squads(gs)
    )

    entry = _coherency_entries(gs)[0]
    assert entry["removed_models"] == ["1#0"]
    assert (entry["col"], entry["row"]) == (
        gs["units_cache"]["1"]["col"], gs["units_cache"]["1"]["row"]
    ), "l'ancre journalisee doit etre celle que le cache porte APRES le retrait"
    assert (entry["col"], entry["row"]) != (30, 40)


# --- (f) FIXES code-review : double-pop v11, T1 player_types, queue inter-joueurs ---------------


def test_arm_next_coherency_pending_preserves_v11_flag():
    """VERROU fix #1 : arm_next_coherency_pending ne doit pas consommer pending_coherency_removal_v11.

    Le flag est lu par _handle_select_coherency_removal APRES arm_next_coherency_pending :
    le pop premature causait toujours _fight_end_progression_v10 meme en pipeline V11.
    """
    gs = {
        "pending_coherency_removal_queue": [],
        "pending_coherency_removal_v11": True,
    }
    result = arm_next_coherency_pending(gs)
    assert result is False
    assert "pending_coherency_removal_v11" in gs, (
        "arm_next_coherency_pending ne doit pas pop pending_coherency_removal_v11"
    )


def test_coherency_seat_is_muet_raises_without_player_types():
    """VERROU fix #2 (T1) : player_types absent en mode non-gym → ConfigurationError explicite.

    Sans ce fix, .get('player_types') or {} retournait {} et le siege n'etait jamais considere
    muet, laissant la queue manuelle non drainee et le tour en suspens indefiniment.
    """
    gs = {"gym_training_mode": False}
    with pytest.raises(ConfigurationError):
        _coherency_seat_is_muet(gs, 1)


def test_opponent_non_mute_squads_resolved_geometrically():
    """VERROU fix #3 : en PvP, l'escouade adversaire incoherente est resolue geometriquement.

    Avant le fix, les deux escouades (joueurs 1 et 2, sièges human donc non muets) allaient dans
    la meme queue et le joueur courant desginait pour l'adversaire.
    Apres le fix : seulement l'escouade du current_player va en queue ; l'adversaire est auto-traite.
    """
    gs = _gs([(10, 10), (11, 10), (30, 40)], squad_id="1", player=1)
    gs["player_types"] = {"1": "human", "2": "human"}
    gs["current_player"] = 1

    # Escouade adversaire (player 2) incoherente, non muette
    sq2_positions = [(20, 20), (21, 20), (5, 50)]
    mids2 = [f"2#{i}" for i in range(3)]
    for mid, (col, row) in zip(mids2, sq2_positions):
        gs["models_cache"][mid] = {
            "col": col, "row": row, "level": 0, "player": 2,
            "squad_id": "2", "HP_CUR": 1, "HP_MAX": 2,
            "T": 4, "ARMOR_SAVE": 3, "INVUL_SAVE": 7,
            "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
        }
    gs["squad_models"]["2"] = list(mids2)
    gs["units_cache"]["2"] = {
        "col": sq2_positions[0][0], "row": sq2_positions[0][1], "player": 2,
        "HP_CUR": 3, "BASE_SHAPE": "round", "BASE_SIZE": 1,
        "orientation": 0, "occupied_hexes": set(), "occupied_hexes_by_model": {},
    }

    auto_removed = end_of_turn_regain_coherency_all_squads(gs)

    # Escouade adversaire resolue automatiquement
    assert "2" in auto_removed, "l'escouade adversaire non muette doit etre resolue geometriquement"
    assert validate_squad_coherency(gs, "2")
    # Escouade du joueur courant en queue manuelle (non resolue automatiquement)
    assert "1" not in auto_removed, "l'escouade du joueur courant ne doit pas etre auto-resolue"
    assert gs.get("pending_coherency_removal") is not None, (
        "l'escouade du joueur courant doit etre en attente de designation manuelle"
    )
