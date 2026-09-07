"""Verrou findings 1&2 — Desperate Escape dans le chemin gym fall_back.

Le chemin gym `squad_fall_back` passait par `execute_squad_move` sans appeler
`desperate_escape_pre_move`, donc `_flee_mode` n'était jamais posé : step.log émettait
toujours [ORDERED RETREAT] même pour une unité battle-shocked + engagée, et les jets
hazard (06.03) n'étaient pas résolus.

Chaîne exercée :
  _process_squad_action(squad_fall_back)
  → si battle_shocked + engagée → desperate_escape_pre_move(auto_resolve=True)
  → game_state["_flee_mode"] = "desperate_escape"
  → action_log["fleeMode"] = "desperate_escape"

Cycle rouge→vert : supprimer le bloc d'injection `if move_type == "fall_back":`
dans la branche `squad_normal_move / squad_advance / squad_fall_back` de
`_process_squad_action` fait passer `test_gym_fall_back_battleshocked_sets_desperate_escape`
en rouge.
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from engine.phase_handlers.shared_utils import (
    DESPERATE_ESCAPE_MODE_KEY,
    MOVE_CELL_MAP_CACHE_KEY,
)
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import (
    _fall_back_base_config as _base_config,
    _fall_back_make_engine as _make_engine,
    _fall_back_unit_cfg as _unit_cfg,
    _fall_back_weapon_cfg as _weapon_cfg,
)


def _engine_engaged() -> W40KEngine:
    """Moteur avec unités en engagement range (col 20/21, même row)."""
    return _make_engine(_base_config([
        _unit_cfg(1, 1, 20, 20),  # J1 — sera battle-shocked
        _unit_cfg(2, 2, 21, 20),  # J2 — adjacent (ER 1 hex)
    ]))


def _unit_cfg_3models(uid: int, player: int) -> Dict[str, Any]:
    """Escouade de 3 figurines en formation pont : A(20,20) — B(22,20) — C(24,20).

    Coh = 2 subhexes (ISH=1). A et B sont à 2 hexes, B et C aussi. Si B (pont) meurt,
    A et C sont à 4 hexes → incoherents.
    """
    base = _unit_cfg(uid, player, 20, 20)
    base["HP_CUR"] = 3
    base["HP_MAX"] = 3
    base["VALUE"] = 300
    base["models"] = [
        {"col": 20, "row": 20, "VALUE": 100},  # 1#0 — ancre A
        {"col": 22, "row": 20, "VALUE": 100},  # 1#1 — pont B
        {"col": 24, "row": 20, "VALUE": 100},  # 1#2 — queue C
    ]
    return base


def _engine_bridge_formation() -> W40KEngine:
    """Moteur : escouade 1 en formation pont (3 fig), ennemi (25,20) adjacent à C."""
    return _make_engine(_base_config([
        _unit_cfg_3models(1, 1),       # J1 — 3 figs en pont
        _unit_cfg(2, 2, 25, 20),       # J2 — adjacent à C (24,20), déclenche l'ER
    ]))


def _engine_battle_shocked() -> tuple:
    """Moteur prêt pour un fall_back avec unité 1 battle-shocked et engagée."""
    eng = _engine_engaged()
    gs = eng.game_state
    gs["phase"] = "move"
    gs["move_activation_pool"] = ["1"]
    unit1 = next(u for u in gs["units"] if str(u["id"]) == "1")
    unit1["battle_shocked"] = True
    return eng, gs


def test_gym_fall_back_battleshocked_sets_desperate_escape() -> None:
    """fall_back avec battle_shocked + engagée → fleeMode=desperate_escape dans action_log."""
    eng, gs = _engine_battle_shocked()

    # Destination de fall_back : case (18, 20) — loin de l'ennemi en (21,20).
    before = len(gs.get("action_logs", []))
    ok, result = eng._process_squad_action(
        {"action": "squad_fall_back", "squad_id": "1", "destCol": 18, "destRow": 20}
    )

    assert ok, f"squad_fall_back a échoué : {result}"

    move_logs = [
        e for e in gs["action_logs"][before:]
        if e.get("type") == "move"
    ]
    assert len(move_logs) == 1, (
        f"attendu 1 action_log move, obtenu {len(move_logs)}: {gs['action_logs'][before:]}"
    )
    assert move_logs[0]["fleeMode"] == "desperate_escape", (
        f"fleeMode attendu 'desperate_escape', obtenu {move_logs[0].get('fleeMode')!r}"
    )


def test_gym_desperate_escape_died_clears_game_state_keys() -> None:
    """Hazard détruit l'unité → _flee_mode et _desperate_escape_rolls absents du game_state.

    Régression : l'ancien chemin retournait sans purger ces clés ; le prochain fall_back
    dans le même épisode héritait de _flee_mode="desperate_escape" même pour une unité
    non-battle-shocked.
    """
    eng, gs = _engine_battle_shocked()

    # Simuler desperate_escape_pre_move qui pose les clés PUIS retourne is_alive=False.
    def _fake_pre_move(
        squad_id: str, game_state: Dict[str, Any], was_engaged: bool, auto_resolve: bool
    ) -> tuple:
        game_state["_flee_mode"] = "desperate_escape"
        game_state["_desperate_escape_rolls"] = [1, 2]
        return True, False, 2  # is_desperate, is_alive=False, wounds

    with patch(
        "engine.phase_handlers.shared_utils.desperate_escape_pre_move",
        side_effect=_fake_pre_move,
    ):
        ok, result = eng._process_squad_action(
            {"action": "squad_fall_back", "squad_id": "1", "destCol": 18, "destRow": 20}
        )

    assert ok, f"desperate_escape_died a échoué : {result}"
    assert result.get("action") == "desperate_escape_died"
    assert "_flee_mode" not in gs, (
        f"_flee_mode stale dans game_state : {gs['_flee_mode']!r}"
    )
    assert "_desperate_escape_rolls" not in gs, (
        "_desperate_escape_rolls stale dans game_state"
    )


def test_gym_fall_back_not_battleshocked_keeps_ordered_retreat() -> None:
    """fall_back sans battle_shock → fleeMode=ordered_retreat (comportement normal préservé)."""
    eng = _engine_engaged()
    gs = eng.game_state

    gs["phase"] = "move"
    gs["move_activation_pool"] = ["1"]

    unit1 = next(u for u in gs["units"] if str(u["id"]) == "1")
    unit1["battle_shocked"] = False

    before = len(gs.get("action_logs", []))
    ok, result = eng._process_squad_action(
        {"action": "squad_fall_back", "squad_id": "1", "destCol": 18, "destRow": 20}
    )

    assert ok, f"squad_fall_back a échoué : {result}"

    move_logs = [
        e for e in gs["action_logs"][before:]
        if e.get("type") == "move"
    ]
    assert len(move_logs) == 1
    assert move_logs[0]["fleeMode"] == "ordered_retreat", (
        f"fleeMode attendu 'ordered_retreat', obtenu {move_logs[0].get('fleeMode')!r}"
    )


def test_gym_desperate_escape_bridge_death_keeps_the_unit_stationary() -> None:
    """Mort du pont en Desperate Escape → formation rompue → l'unité NE se replie PAS.

    Scénario : escouade 3 figs A(20,20)–B(22,20)–C(24,20), ennemi en (25,20).
    Coh = 2 subhexes (ISH=1). B est le seul lien A–C (chacun à 2", limite de coh).
    Le mock simule un Desperate Escape qui tue B : A et C restent vivants, à 4 hexes l'un
    de l'autre → incohérents.

    Ce test verrouillait auparavant le comportement INVERSE — le mouvement était exécuté avec
    `require_coherency=False` — sur une lecture erronée de 03.03. Le PDF tranche dans l'autre
    sens : « A unit that contains more than one model must be set up and end ANY KIND OF MOVE in
    coherency » (03.03), et 03.01 ENDING A MOVE : « If one or more of the above conditions are not
    met, that unit cannot make that move and its models are returned to their positions at the
    start of that move » — l'unité « could either attempt another set up or remain stationary
    (09.04) ». REGAINING COHERENCY (End of Turn) retire des figurines pour réparer des PERTES ;
    elle n'autorise pas à terminer un mouvement brisé.

    Mesuré avant correction : 1 violation 03.03 sur un run de 600 épisodes (épisode 204).

    L'issue est celle, déjà câblée, du décalage d'ancre : activation close en WAIT, et surtout
    PAS `FLED` — aucun repli n'a eu lieu, donc aucun interdit 09.07 à porter.
    """
    eng = _engine_bridge_formation()
    gs = eng.game_state

    gs["phase"] = "move"
    gs["move_activation_pool"] = ["1"]
    unit1 = next(u for u in gs["units"] if str(u["id"]) == "1")
    unit1["battle_shocked"] = True

    bridge_mid = "1#1"

    def _kill_bridge(
        squad_id: str, game_state: Dict[str, Any], was_engaged: bool, auto_resolve: bool
    ) -> tuple:
        """Simule la mort de B (pont) par le Desperate Escape."""
        game_state["models_cache"].pop(bridge_mid, None)
        game_state["squad_models"]["1"] = [
            m for m in game_state["squad_models"].get("1", []) if m != bridge_mid
        ]
        game_state["_flee_mode"] = "desperate_escape"
        return True, True, 1  # is_desperate, is_alive (A et C survivent), wounds

    # Destination ancre : A(20,20) → (16,20) ; C(24,20) → (20,20). Budget 6 ≥ 4. Pas en ER ennemi.
    with patch(
        "engine.phase_handlers.shared_utils.desperate_escape_pre_move",
        side_effect=_kill_bridge,
    ):
        ok, result = eng._process_squad_action(
            {"action": "squad_fall_back", "squad_id": "1", "destCol": 16, "destRow": 20}
        )

    assert ok, f"l'activation doit se clore proprement, pas lever : {result}"
    assert result.get("action") != "desperate_escape_died", (
        "A et C survivent → l'action ne doit pas être desperate_escape_died"
    )
    assert result.get("action") == "fall_back_anchor_shifted", (
        "formation rompue par le hazard → 03.01 « cannot make that move », l'unité reste "
        f"stationnaire ; obtenu {result.get('action')!r}"
    )
    # Les survivants n'ont pas bougé : c'est le « returned to their positions » de 03.01.
    assert gs["models_cache"]["1#0"]["col"] == 20
    assert gs["models_cache"]["1#2"]["col"] == 24
    move_logs = [e for e in gs.get("action_logs", []) if e.get("type") == "move"]
    assert move_logs == [], f"aucune ligne de mouvement ne doit être journalisée : {move_logs}"


def test_gym_fall_back_anchor_shifted_skips_move() -> None:
    """Desperate Escape tue une figurine d'ancre → pool périmé → activation_complete sans move.

    Scenario reproduisant le crash bot_ranking :
    - Unité multi-modèles battle-shocked + engagée (squad 1 en (20,20)).
    - desperate_escape_pre_move tue la figurine d'ancre : units_cache passe à (20,22).
    - La destination choisie par le masque (18,20) n'est plus atteignable depuis (20,22)
      (elle était dans le pool bâti depuis (20,20)).
    - Attendu : fall_back_anchor_shifted est retourné, pas de ValueError.
    """
    eng, gs = _engine_battle_shocked()

    def _fake_pre_move(
        squad_id: str, game_state: Dict[str, Any], was_engaged: bool, auto_resolve: bool
    ) -> tuple:
        # Simuler la mort de la figurine d'ancre : units_cache se décale.
        # units_cache est keyé par str → utiliser squad_id directement (déjà str).
        game_state["_flee_mode"] = "desperate_escape"
        game_state["_desperate_escape_rolls"] = [1]
        uc = game_state["units_cache"]
        entry = dict(uc[squad_id])
        entry["row"] = 22  # ancre passe de (20,20) à (20,22)
        uc[squad_id] = entry
        return True, True, 1  # is_desperate=True, is_alive=True, 1 wound

    # Pré-seeder une entrée pour simuler un masque déjà calculé pour cette escouade.
    gs.setdefault(MOVE_CELL_MAP_CACHE_KEY, {})["1"] = {"map": {}, "anchor": (20, 20), "phase": "move"}

    with patch(
        "engine.phase_handlers.shared_utils.desperate_escape_pre_move",
        side_effect=_fake_pre_move,
    ):
        ok, result = eng._process_squad_action(
            {"action": "squad_fall_back", "squad_id": "1", "destCol": 18, "destRow": 20}
        )

    assert ok, f"fall_back_anchor_shifted a échoué : {result}"
    assert result.get("action") == "fall_back_anchor_shifted", (
        f"action attendue 'fall_back_anchor_shifted', obtenu {result.get('action')!r}"
    )
    assert result.get("activation_complete") is True
    assert "_flee_mode" not in gs, f"_flee_mode stale : {gs.get('_flee_mode')!r}"
    assert "_desperate_escape_rolls" not in gs, "_desperate_escape_rolls stale"
    assert "1" not in gs[MOVE_CELL_MAP_CACHE_KEY], "cell map stale après fall_back_anchor_shifted"

    # L'ACTIVATION EST-ELLE RÉELLEMENT CLOSE ? `activation_complete` ci-dessus n'a AUCUN lecteur
    # dans engine/ai/services : l'assertion précédente était VACANTE. Seul `end_activation` retire
    # du `move_activation_pool` (generic_handlers ~L170), et ce pool est la SEULE source de
    # `_raw_eligible_units_for_current_phase` en phase move. Sans retrait, l'escouade était
    # réactivée dans la MÊME phase (2e mouvement, interdit par 09.04) — et comme les pertes de
    # Desperate Escape peuvent avoir rompu sa coherency, chacune de ses destinations levait
    # « execute_squad_move a échoué … (formation actuelle DEJA incoherente) ».
    assert "1" not in gs["move_activation_pool"], (
        "escouade toujours dans move_activation_pool après fall_back_anchor_shifted : "
        f"{gs['move_activation_pool']} — elle sera réactivée dans la même phase de move"
    )
    assert "1" in gs["units_moved"], (
        "activation non comptabilisée : units_moved="
        f"{gs['units_moved']}"
    )
    # PAS de `units_fled` : aucun fall back n'a eu lieu (le move a été sauté), donc l'unité ne
    # doit pas porter les interdits 09.07 (pas de tir ni de charge après une retraite).
    assert "1" not in gs.get("units_fled", set()), (
        "units_fled posé alors qu'aucun fall back n'a été exécuté : "
        f"{gs.get('units_fled')}"
    )


# ─────────────────────────────────────────────────────────────────────────────────────────────
# 09.07 — le MODE survit à ses propres jets de hazard
#
# « BEFORE MOVING: Select fall-back mode … Desperate Escape … Make a hazard roll for each model »
# puis « WHILE MOVING — Desperate Escape: Each model that is moved can be moved through enemy
# models », et l'encart SELECTING MODES : « Those that are labelled with a mode name only apply
# if you selected that mode ». Le mode est donc arrêté AVANT les jets, et tout ce qu'il étiquette
# vaut pour le mouvement entier.
#
# Le moteur re-dérivait le mode de `squad_is_battle_shocked_in_enemy_er` À CHAQUE lecture. Quand
# les jets tuaient les seules figurines engagées, ce prédicat basculait à False au milieu du
# mouvement et le mode disparaissait avec lui. Les trois tests ci-dessous verrouillent les trois
# conséquences mesurées.
# ─────────────────────────────────────────────────────────────────────────────────────────────

#: Ligne de figurines ennemies infranchissable sans l'exemption 09.07 : le contournement dépasse
#: le budget. Le fixture pose `can_move_through_enemy_model: False`, donc seules les figurines
#: ennemies bloquent (la bande d'EZ est traversable) — l'exemption est isolée.
_BARRIER_COL = 22
_BARRIER_ROWS = list(range(6, 35))
#: Ancre HORS de l'ER ennemie ; c'est `1#1` qui engage l'escouade, et c'est lui que le hazard tue.
_DE_ANCHOR = (19, 20)
_DE_ENGAGED_MODEL = (21, 20)
#: Au-delà de la ligne ennemie : 5 pas en la traversant, hors budget en la contournant.
_DE_DEST = (24, 20)


def _barrier_cfg() -> Dict[str, Any]:
    base = _unit_cfg(2, 2, _BARRIER_COL, _BARRIER_ROWS[0])
    base["HP_CUR"] = len(_BARRIER_ROWS)
    base["HP_MAX"] = len(_BARRIER_ROWS)
    base["models"] = [{"col": _BARRIER_COL, "row": r, "VALUE": 10} for r in _BARRIER_ROWS]
    return base


def _engine_behind_enemy_line() -> W40KEngine:
    """Escouade 1 battle-shocked, engagée par `1#1` seul, derrière une ligne ennemie.

    L'escouade 3 ne sert qu'à garder le pool d'activation non vide : sans elle, la fin
    d'activation de l'escouade 1 clôt la phase de move du joueur, ce qui RÉINITIALISE
    `units_moved` / `units_fled` — les assertions de ces tests liraient alors des sets vides
    sans rien prouver. Elle est hors de portée de tout le reste (coin opposé du plateau).
    """
    squad = _unit_cfg(1, 1, _DE_ANCHOR[0], _DE_ANCHOR[1])
    squad["MOVE"] = 10
    squad["HP_CUR"] = 2
    squad["HP_MAX"] = 2
    squad["models"] = [
        {"col": _DE_ANCHOR[0], "row": _DE_ANCHOR[1], "VALUE": 100},
        {"col": _DE_ENGAGED_MODEL[0], "row": _DE_ENGAGED_MODEL[1], "VALUE": 100},
    ]
    eng = _make_engine(_base_config([squad, _barrier_cfg(), _unit_cfg(3, 1, 5, 5)]))
    gs = eng.game_state
    gs["phase"] = "move"
    gs["move_activation_pool"] = ["1", "3"]
    next(u for u in gs["units"] if str(u["id"]) == "1")["battle_shocked"] = True
    return eng


def _hazard_kills_engaged_model(squad_id, game_state, auto_resolve, **kwargs) -> int:
    """Jets 06.03 : seule la figurine engagée meurt, l'ancre survit et ne bouge pas.

    Remplace UNIQUEMENT la résolution des jets. `desperate_escape_pre_move` — qui sélectionne le
    mode — reste le vrai code : c'est lui qui est sous test.
    """
    from engine.phase_handlers.shared_utils import destroy_model

    destroy_model(game_state, "1#1", "hazard")
    return 1


def test_desperate_escape_keeps_enemy_traversal_after_hazard_losses() -> None:
    """Masque ⊆ exécutable à travers les pertes du hazard (crash training P2, 2026-09-05).

    Le masque offre (24,20) parce que l'exemption 09.07 laisse le pool traverser la ligne
    ennemie. Les jets tuent ensuite `1#1`, seule figurine engagée : l'escouade sort de l'ER
    ennemie sans que l'ancre bouge, donc le garde `fall_back_anchor_shifted` ne se déclenche pas.
    Sans le verrou de mode, `validate_move_plan` re-bloque les figurines ennemies et refuse la
    destination que le masque venait d'offrir → `ValueError: execute_squad_move a échoué …
    incohérence masque/exécution`, qui tue les workers `SubprocVecEnv` du training.

    Cycle rouge→vert : supprimer `game_state[DESPERATE_ESCAPE_MODE_KEY] = str(squad_id)` de
    `desperate_escape_pre_move` fait remonter ce ValueError.
    """
    from engine.phase_handlers.shared_utils import build_squad_move_cell_map

    eng = _engine_behind_enemy_line()
    gs = eng.game_state

    offered = {cell for (cell, _cost) in build_squad_move_cell_map(gs, "1", None).values()}
    assert _DE_DEST in offered, (
        f"fixture caduque : le masque n'offre pas {_DE_DEST} avant le hazard, le test "
        f"n'exercerait plus l'invariant masque ⊆ exécutable"
    )

    with patch(
        "engine.phase_handlers.shared_utils.roll_hazard_for_unit",
        side_effect=_hazard_kills_engaged_model,
    ):
        ok, result = eng._process_squad_action(
            {"action": "squad_fall_back", "squad_id": "1",
             "destCol": _DE_DEST[0], "destRow": _DE_DEST[1]}
        )

    assert ok, f"squad_fall_back a échoué après les pertes du hazard : {result}"
    assert result.get("action") == "squad_fall_back", (
        f"le move a été sauté au lieu d'être exécuté : {result.get('action')!r}"
    )
    assert (gs["units_cache"]["1"]["col"], gs["units_cache"]["1"]["row"]) == _DE_DEST, (
        "l'escouade n'a pas atteint la destination offerte par le masque : "
        f"{(gs['units_cache']['1']['col'], gs['units_cache']['1']['row'])}"
    )
    assert "1" in gs["units_fled"], "fall back exécuté mais units_fled absent (09.07)"
    # LE MODE MEURT AVEC L'ACTIVATION : sinon l'escouade garderait la traversée des figurines
    # ennemies pour tous ses mouvements suivants.
    assert DESPERATE_ESCAPE_MODE_KEY not in gs, (
        f"verrou de mode non purgé en fin d'activation : {gs.get(DESPERATE_ESCAPE_MODE_KEY)!r}"
    )


def test_desperate_escape_model_pool_keeps_enemy_traversal_after_hazard_losses() -> None:
    """Pool par-figurine (preview PvP) : la traversée 09.07 survit aux pertes du hazard.

    `movement_build_model_destinations_pool` lit le même prédicat de mode. Sans le verrou, le
    survivant ne se voyait plus offrir la moindre case au-delà de la ligne ennemie — la preview
    PvP amputait un mouvement que la règle autorise.
    """
    from engine.phase_handlers.movement_handlers import (
        movement_build_model_destinations_pool,
    )
    from engine.phase_handlers.shared_utils import desperate_escape_pre_move

    eng = _engine_behind_enemy_line()
    gs = eng.game_state

    with patch(
        "engine.phase_handlers.shared_utils.roll_hazard_for_unit",
        side_effect=_hazard_kills_engaged_model,
    ):
        is_desperate, is_alive, _ = desperate_escape_pre_move("1", gs, True, True)
    assert is_desperate and is_alive, "fixture caduque : Desperate Escape non déclenché"

    pool = movement_build_model_destinations_pool(gs, "1#0")
    reachable = {(int(d[0]), int(d[1])) for d in pool["destinations"]}
    assert _DE_DEST in reachable, (
        f"{_DE_DEST} absent du pool par-figurine : l'exemption de traversée 09.07 a été perdue "
        f"avec les figurines tuées par le hazard"
    )


def test_desperate_escape_commits_as_fall_back_after_hazard_losses() -> None:
    """Commit PvP : le move reste un fall-back, donc `units_fled` est posé.

    `movement_commit_move_plan_handler` déduisait le type de move de l'engagement relu AU COMMIT.
    Après des pertes qui sortent l'escouade de l'ER ennemie, il committait `normal` — et
    `commit_move` ne pose `units_fled` que pour `fall_back`. L'unité repartait avec son tir et sa
    charge intacts, contre 09.07 AFTER MOVING (« not eligible to shoot, declare a charge or start
    an action »).

    Cycle rouge→vert : retirer le terme `DESPERATE_ESCAPE_MODE_KEY` de `was_engaged` dans
    `movement_commit_move_plan_handler` fait tomber l'assertion `units_fled`.
    """
    from engine.phase_handlers.movement_handlers import (
        movement_commit_move_plan_handler,
    )
    from engine.phase_handlers.shared_utils import desperate_escape_pre_move

    eng = _engine_behind_enemy_line()
    gs = eng.game_state

    with patch(
        "engine.phase_handlers.shared_utils.roll_hazard_for_unit",
        side_effect=_hazard_kills_engaged_model,
    ):
        desperate_escape_pre_move("1", gs, True, True)

    # Repli d'UN hexe vers l'arrière : le type de move est ce qui est testé, pas le trajet.
    ok, result = movement_commit_move_plan_handler(
        gs, "1", {"plan": [["1#0", _DE_ANCHOR[0] - 1, _DE_ANCHOR[1], 0]]}
    )

    assert ok, f"commit du plan de fall back refusé : {result}"
    assert "1" in gs.get("units_fled", set()), (
        "fall back committé sans units_fled : le move a été reclassé en normal parce que les "
        "pertes du hazard ont sorti l'escouade de l'ER ennemie — l'unité garde tir et charge"
    )


def test_desperate_escape_preview_badge_matches_commit_after_hazard_losses() -> None:
    """Preview PvP : le badge « fui » dit ce que le bouton Valider va faire.

    `movement_preview_move_plan` et le handler de commit lisent désormais la même source
    (`squad_move_is_fall_back`). Sans elle, la preview annonçait `would_flee=False` sur un ghost
    que le commit enregistre en fall-back : l'affichage contredisait l'action.
    """
    from engine.phase_handlers.movement_handlers import movement_preview_move_plan
    from engine.phase_handlers.shared_utils import desperate_escape_pre_move

    eng = _engine_behind_enemy_line()
    gs = eng.game_state

    with patch(
        "engine.phase_handlers.shared_utils.roll_hazard_for_unit",
        side_effect=_hazard_kills_engaged_model,
    ):
        desperate_escape_pre_move("1", gs, True, True)

    preview = movement_preview_move_plan(
        gs, "1", [("1#0", _DE_ANCHOR[0] - 1, _DE_ANCHOR[1], 0)]
    )
    assert preview["would_flee"] is True, (
        "preview annonce un move normal alors que le commit posera units_fled"
    )


def test_desperate_escape_quick_move_marks_flee_after_hazard_losses() -> None:
    """Commit rapide à l'ancre (PvP) : le marquage flee survit aux pertes du hazard.

    `_attempt_movement_to_destination` déduisait la fuite du même engagement relu au commit.
    C'est ce marquage qui pose `units_fled` sur ce chemin-là : sans le mode retenu, une retraite
    désespérée y était enregistrée comme un déplacement ordinaire.
    """
    from engine.phase_handlers.movement_handlers import (
        movement_build_valid_destinations_pool,
        movement_destination_selection_handler,
    )
    from engine.phase_handlers.shared_utils import desperate_escape_pre_move

    eng = _engine_behind_enemy_line()
    gs = eng.game_state

    with patch(
        "engine.phase_handlers.shared_utils.roll_hazard_for_unit",
        side_effect=_hazard_kills_engaged_model,
    ):
        desperate_escape_pre_move("1", gs, True, True)

    gs["active_movement_unit"] = "1"
    movement_build_valid_destinations_pool(gs, "1")
    dest = (_DE_ANCHOR[0] - 1, _DE_ANCHOR[1])
    assert dest in gs["valid_move_destinations_pool"], (
        f"fixture caduque : {dest} absent du pool de repli"
    )

    ok, result = movement_destination_selection_handler(
        gs, "1", {"destCol": dest[0], "destRow": dest[1]}
    )

    assert ok, f"commit rapide refusé : {result}"
    assert "1" in gs.get("units_fled", set()), (
        "commit rapide enregistré comme move normal : le marquage flee 09.07 a été perdu avec "
        "les figurines tuées par le hazard"
    )


def test_desperate_escape_mode_survives_activation_postpone() -> None:
    """Report d'activation (`postpone`) : le mode retenu tient jusqu'à la fin RÉELLE.

    `_handle_movement_postpone` repose l'unité sans clore son activation — elle reste dans
    `move_activation_pool` et sera ré-activée plus tard dans la même phase. Ses jets de hazard
    sont faits et ne se rejoueront pas : le mode Desperate Escape vaut encore. Le payload de
    ré-activation doit donc annoncer `would_flee=True`, sans quoi l'UI reproposerait les modes
    Move/Advance sur un mouvement que le commit enregistre en `flee`.
    """
    from engine.phase_handlers.movement_handlers import (
        _handle_movement_postpone,
        movement_unit_execution_loop,
    )
    from engine.phase_handlers.shared_utils import (
        desperate_escape_mode_selected, desperate_escape_pre_move,
    )

    eng = _engine_behind_enemy_line()
    gs = eng.game_state
    unit = next(u for u in gs["units"] if str(u["id"]) == "1")

    with patch(
        "engine.phase_handlers.shared_utils.roll_hazard_for_unit",
        side_effect=_hazard_kills_engaged_model,
    ):
        desperate_escape_pre_move("1", gs, True, True)
    gs["active_movement_unit"] = "1"

    ok, _ = _handle_movement_postpone(gs, unit)
    assert ok, "report d'activation refusé"
    assert "1" in gs["move_activation_pool"], (
        "fixture caduque : le report doit LAISSER l'escouade dans le pool"
    )
    assert desperate_escape_mode_selected(gs, "1"), (
        "mode purgé au report : la ré-activation reperdrait l'exemption de traversée alors que "
        "les jets de hazard, eux, ne se rejouent pas"
    )

    ok, payload = movement_unit_execution_loop(gs, "1")
    assert ok, f"ré-activation refusée : {payload}"
    assert payload["would_flee"] is True, (
        "la ré-activation annonce un move normal alors que le commit posera units_fled"
    )
