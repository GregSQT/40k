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
    end_of_turn_coherency_removal,
    end_of_turn_regain_coherency_all_squads,
    validate_squad_coherency,
)


def _gs(positions, squad_id="1", player=1):
    """game_state minimal : ce que lisent la coherency (03.03) et `destroy_model`.

    `positions` : liste de (col, row), une par figurine, dans l'ordre des index (le tie-break de
    retrait est l'index croissant).
    """
    mids = [f"{squad_id}#{i}" for i in range(len(positions))]
    models_cache = {
        mid: {
            "col": int(col), "row": int(row), "level": 0, "player": player,
            "squad_id": squad_id, "HP_CUR": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1,
            "orientation": 0,
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
        # Valeurs de config/game_config.json, deja converties en subhex par w40k_core a l'init.
        "config": {"game_rules": {
            "unit_model_cohesion_range": 2,
            "unit_global_cohesion_range": 9,
            "squad_min_neighbors": 1,
            "cohesion_distance_mode": "euclidean",
            "engagement_zone": 1,
        }},
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
    """La regle vise « units on the battlefield » : les escouades des DEUX joueurs sont traitees."""
    gs = _gs([(10, 10), (11, 10), (30, 40)], squad_id="1", player=1)
    gs2 = _gs([(20, 20), (21, 20), (5, 50)], squad_id="2", player=2)
    gs["models_cache"].update(gs2["models_cache"])
    gs["squad_models"].update(gs2["squad_models"])
    gs["units_cache"].update(gs2["units_cache"])

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
    """game_state minimal accepte par les deux chemins de fin de phase Fight."""
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
