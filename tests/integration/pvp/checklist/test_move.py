"""Checklist MOUVEMENT — chaque item backend de la phase de mouvement, via GameClient, en x5 et x1.

Scénario FIGÉ ``scenario_pvp_checklist.json`` (terrain ``divers/terrain-checklist.json``), joueur 1
ADEPTUS ASTARTES, joueur 2 TYRANIDS. Régions et escouades (identifiants du scénario) :

  A  libre           : ``1`` Intercessors ×5, aucun ennemi à portée.
  B  réaction        : ``2`` Intercessors à 10" au nord des Termagants ``101`` (reactive_move) ;
                       ``12`` Intercessors DÉJÀ à moins de 9" de ``101``.
  B2 réaction refusée: ``13`` Intercessors ×3 engagés avec les Termagants ``106``.
  C  repli infanterie: ``3`` Intercessors ×5 engagés avec la ligne de 10 Hormagaunts ``102``.
  C2 repli VEHICLE   : ``4`` Dreadnought engagé avec la ligne de 10 Hormagaunts ``103``.
  F  traversée 17.01 : ``9`` Dreadnought face à la ligne ``107`` ; ``14`` face au Psychophage ``108``.
  D  murs            : ``5`` Intercessors au nord du mur W1 ; ``6`` jump packs (FLY) au nord du mur W2.
  E  ruine à étage   : ``7`` Intercessors et ``8`` Dreadnought au pied d'un plancher à 3".
  G  03.01           : ``15`` Intercessor seul, ``16`` Intercessor ami juste au sud ;
                       ``17`` Intercessor seul, ``110`` Hormagaunt ennemi juste au sud.
  réserves           : ``10`` Land Speeder (Deep Strike, Purgation Run) ; ``104`` Hormagaunts ×5 ;
                       ``109`` Hormagaunts dans la zone du joueur 2 (distance d'arrivée).

Toute valeur attendue est dérivée de la règle EN POUCES × ``inches_to_subhex`` (jamais un nombre
de cases en dur) et les positions sont LUES dans l'état : le chargeur convertit le scénario x5 en
x1 (``_downscale_fixed_unit``), donc une coordonnée écrite ici serait fausse dans l'une des deux
résolutions. Les dés sont figés par monkeypatch (``roll_advance_for_squad`` importé par nom dans
``movement_handlers``, ``random.randint`` par séquence pour ``roll_hazard_for_unit``,
``roll_battle_shock`` et le D6 du mouvement réactif) — jamais par graine.

Les écarts code/règle connus sont écrits en ``xfail(strict=True)`` avec la clause en raison, jamais
en test vert qui les figerait. Ceux découverts pendant l'écriture (résolution x1 des étages,
fenêtre réactive absente du commit par-figurine, crash de la réaction en x5, move_after_shooting
jamais proposé et distance en pouces, échelle √3 de la cohérence euclidienne) ont été corrigés le
2026-09-17 et sont désormais des tests verts dans les deux résolutions.
"""

from __future__ import annotations

import json
import math
import random
from unittest import mock
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pytest

import engine.phase_handlers.movement_handlers as movement_handlers
import services.api_server as api_server
from engine.hex_utils import downscale_cell, hex_distance
from tests.integration.pvp.checklist.conftest import CHECKLIST_SCENARIO

pytestmark = pytest.mark.integration

TERRAIN_FILE = "config/board/44x60x5/terrain/divers/terrain-checklist.json"
#: Résolution NATIVE du scénario et de son terrain (dossier ``44x60x5``).
SCENARIO_NATIVE_SUBHEX = 5

# Règles, EN POUCES — la seule forme sous laquelle un nombre entre ici.
ENGAGEMENT_RANGE_INCHES = 2          # 03.04
COHERENCY_NEAR_INCHES = 2            # 03.03, 1re puce
COHERENCY_SPREAD_INCHES = 9          # 03.03, 2e puce
FLY_PENALTY_INCHES = 2               # 21.03
REACTIVE_TRIGGER_INCHES = 9          # datasheet Termagant (Skulking Horrors), config/unit_rules.json
INGRESS_EDGE_BAND_INCHES = 6         # 20.04
INGRESS_ENEMY_CLEARANCE_INCHES = 8   # 20.04 / 24.09
INGRESS_FIRST_ROUND = 2              # 20.03
INGRESS_OPPONENT_ZONE_OPEN_ROUND = 3 # 20.04
RESERVES_LAST_ROUND = 3              # 20.04
MAX_D6 = 6


# ─────────────────────────────────────────────────────────────────────────────
# Lectures d'état
# ─────────────────────────────────────────────────────────────────────────────

def _engine_state() -> Dict[str, Any]:
    """``game_state`` du moteur en cours — pour la géométrie que l'API ne sérialise pas
    (``wall_hexes``, ``terrain_areas``, ``action_logs`` : `_GAME_STATE_EXCLUDE_KEYS`)."""
    engine = api_server.engine
    assert engine is not None, "aucune partie en cours"
    return engine.game_state


def _ish(game) -> int:
    return int(game.state["inches_to_subhex"])


def _inches(game, value: float) -> int:
    """``value`` pouces → cases du plateau joué."""
    return int(round(value * _ish(game)))


def _pos(game, model_id: str) -> Tuple[int, int]:
    model = game.state["models_cache"][model_id]
    return int(model["col"]), int(model["row"])


def _placement(game, model_id: str) -> List[Any]:
    model = game.state["models_cache"][model_id]
    return [model_id, int(model["col"]), int(model["row"]), int(model["level"])]


def _alive_models(game, unit_id: str) -> List[str]:
    return [m for m in game.models_of(unit_id) if m in game.state["models_cache"]]


def _hp(game, model_id: str) -> int:
    return int(game.state["models_cache"][model_id]["HP_CUR"])


def _datasheet_move_inches(game, unit_id: str) -> int:
    """Caractéristique M de la datasheet, EN POUCES (le moteur la porte déjà convertie)."""
    from ai.unit_registry import UnitRegistry

    return int(UnitRegistry().get_unit_data(game.unit(unit_id)["unitType"])["MOVE"])


def _row_step(game) -> float:
    """Coût d'un pas le long d'une COLONNE dans la métrique du move : 1 en géométrie hex (x1),
    √3/1,5 en euclidien (centres d'hex flat-top, ``_hex_center`` normalisé par la largeur 1,5)."""
    metric = movement_handlers._move_distance_metric(_engine_state())
    if metric == "hex":
        return 1.0
    assert metric == "euclidean", metric
    return math.sqrt(3.0) / 1.5


def _straight_reach(game, budget_subhex: int) -> int:
    """Nombre de rangs atteignables EN LIGNE DROITE le long d'une colonne avec ``budget_subhex``.

    En hex c'est le budget lui-même : la case à exactement ce nombre de rangs est le point où un
    détour d'une seule case (+1) dépasse le budget — c'est ce qui rend un obstacle d'UNE case
    discriminant. En euclidien un rang coûte plus qu'une case, d'où la division.
    """
    return int(math.floor(budget_subhex / _row_step(game)))


def _pending(game) -> Optional[Dict[str, Any]]:
    return game.state.get("pending_agent_decision")


def _in(game, key: str, unit_id: str) -> bool:
    return str(unit_id) in [str(u) for u in game.state[key]]


def _scenario_walls_in_board_units(game) -> Dict[str, List[Tuple[Tuple[int, int], Tuple[int, int]]]]:
    """Segments de murs du terrain, nommés, convertis dans la résolution jouée (même conversion
    que le chargeur : ``downscale_cell``)."""
    with open(TERRAIN_FILE, encoding="utf-8") as fh:
        terrain = json.load(fh)
    ratio = SCENARIO_NATIVE_SUBHEX // _ish(game)
    out: Dict[str, List[Tuple[Tuple[int, int], Tuple[int, int]]]] = {}
    for group in terrain["walls"]:
        out[group["name"]] = [
            (downscale_cell(a[0], a[1], ratio), downscale_cell(b[0], b[1], ratio))
            for a, b in group["segments"]
        ]
    return out


def _wall_cells(game, name: str) -> List[Tuple[int, int]]:
    """Cases de mur rasterisées d'UN segment horizontal nommé (la rasterisation alterne la rangée
    selon la parité de colonne : on garde ±1 rang autour de la rangée écrite)."""
    (a, b), = _scenario_walls_in_board_units(game)[name]
    walls = {(int(w[0]), int(w[1])) for w in _engine_state()["wall_hexes"]}
    c0, c1 = min(a[0], b[0]), max(a[0], b[0])
    row = a[1]
    return sorted(w for w in walls if c0 <= w[0] <= c1 and abs(w[1] - row) <= 1)


def _floor_cells_and_height(game) -> Tuple[set, float]:
    """Cases de l'étage 1 de la ruine et sa hauteur EN POUCES, lues dans le terrain chargé."""
    cells: set = set()
    heights: set = set()
    for area in _engine_state()["terrain_areas"]:
        for floor in area.get("floors", []):
            if int(floor["level"]) != 1:
                continue
            cells.update((int(h[0]), int(h[1])) for h in floor["hexes"])
            heights.add(float(floor["height_inches"]))
    assert cells and len(heights) == 1, (cells and heights)
    return cells, heights.pop()


# ─────────────────────────────────────────────────────────────────────────────
# Pilotage
# ─────────────────────────────────────────────────────────────────────────────

def _model_dests(game, model_id: str, plan: Optional[Mapping[str, Sequence[int]]] = None, **kw) -> List[List[int]]:
    body = game.act(
        "move_model_destinations",
        model_id=model_id,
        provisional_plan={k: list(v) for k, v in (plan or {}).items()},
        **kw,
    )
    return [[int(d[0]), int(d[1]), int(d[2])] for d in body["result"]["destinations"]]


def _farthest_reach(game, model_id: str, dests: Iterable[Sequence[int]]) -> int:
    col, row = _pos(game, model_id)
    return max((hex_distance(col, row, d[0], d[1]) for d in dests), default=0)


def _plan_by(game, unit_id: str, choose: Callable[[Tuple[int, int], List[List[int]]], List[int]]) -> List[List[Any]]:
    """Plan complet, figurine par figurine, chacune recalculée avec les sœurs déjà posées
    (le flux du front)."""
    plan: Dict[str, Tuple[int, int, int]] = {}
    for model_id in _alive_models(game, unit_id):
        dests = _model_dests(game, model_id, plan)
        assert dests, f"figurine {model_id} : aucune destination"
        chosen = choose(_pos(game, model_id), dests)
        plan[model_id] = (int(chosen[0]), int(chosen[1]), int(chosen[2]))
    return [[mid, c, r, lv] for mid, (c, r, lv) in plan.items()]


def _plan_one_step(game, unit_id: str) -> List[List[Any]]:
    return _plan_by(game, unit_id, lambda origin, dests: min(
        dests, key=lambda d: hex_distance(origin[0], origin[1], d[0], d[1]) or 99
    ))


def _plan_towards_row(game, unit_id: str, sign: int) -> List[List[Any]]:
    """Plan qui pousse chaque figurine le plus loin possible vers le sud (+1) ou le nord (-1)."""
    return _plan_by(game, unit_id, lambda origin, dests: max(dests, key=lambda d: sign * d[1]))


def _quick_move(game, unit_id: str, rank: Callable[[Sequence[int]], Any]) -> Dict[str, Any]:
    """Déplacement rapide à l'ancre (action ``move`` du clic PvP) vers la meilleure case du pool
    d'ancre selon ``rank`` (plus petit d'abord). Le pool d'ancre est calculé pour l'ancre seule :
    le bloc rigide peut être refusé sur une case (sœur sur une figurine amie), on prend alors la
    suivante — c'est le geste du joueur qui reclique."""
    game.act("activate_unit", unitId=unit_id)
    pool = [tuple(int(v) for v in cell) for cell in game.state["valid_move_destinations_pool"]]
    assert pool, f"unité {unit_id} : pool d'ancre vide"
    for dest in sorted(pool, key=rank)[:40]:
        accepted, body = game.try_act("move", unitId=unit_id, destCol=int(dest[0]), destRow=int(dest[1]))
        if accepted:
            return body
    raise AssertionError(f"unité {unit_id} : aucune des 40 meilleures cases d'ancre n'accepte le bloc")


def _at_round(game, battle_round: int, player: int = 1, phase: str = "move") -> None:
    game.play_nominal(
        max_actions=4000,
        until=lambda c: int(c.state["turn"]) == battle_round and c.current_player == player and c.phase == phase,
    )


def _settle_hazard_allocation(game, unit_id: str, body: Dict[str, Any], pick_model: Callable[[List[str]], str]) -> Dict[str, Any]:
    """Attribution manuelle 06.02 côté siège humain : ordre des groupes (si plusieurs) puis une
    figurine par blessure mortelle — calquée sur ``test_fight._resolve_manual_allocation``."""
    for _ in range(50):
        result = body["result"]
        if result.get("order_request"):
            order = [g["group_id"] for g in result["order_request"]["groups"]]
            body = game.act("squad_hazard_declare_order", unitId=unit_id, order=order)
            continue
        allocation = result.get("allocation")
        if not allocation:
            return body
        chosen = pick_model([choice["model_id"] for choice in allocation["choices"]])
        body = game.act("squad_hazard_allocate_model", unitId=unit_id, modelId=chosen)
    raise AssertionError("l'attribution du hazard ne se termine pas")


def _plan_row(game, unit_id: str, col: int, row: int) -> List[List[Any]]:
    """Formation en ligne pour une mise en place (ingress 20.04) : socles espacés de 1,6" — sans
    chevauchement à x5 (socle 25 mm ≈ 1,1"), en cohérence 03.03 (< 2")."""
    spacing = _inches(game, 1.6)
    return [[mid, col + i * spacing, row, 0] for i, mid in enumerate(game.models_of(unit_id))]


def _fix_dice(monkeypatch, values: Sequence[int]) -> Callable[[], int]:
    """Fige ``random.randint`` sur une séquence ; rend un compteur des dés consommés.

    Épuiser la séquence est une ERREUR de test (un jet non prévu), jamais un repli.
    """
    remaining = list(values)
    consumed = {"n": 0}

    def fake_randint(a: int, b: int) -> int:
        assert (a, b) == (1, 6), f"dé inattendu randint({a}, {b})"
        assert remaining, "séquence de dés épuisée : un jet non prévu a eu lieu"
        consumed["n"] += 1
        return remaining.pop(0)

    monkeypatch.setattr(random, "randint", fake_randint)
    return lambda: consumed["n"]


def _fix_advance_roll(monkeypatch, roll: int) -> Callable[[], int]:
    """Fige ``roll_advance_for_squad`` — importé PAR NOM dans ``movement_handlers`` (ligne 47),
    donc c'est cette liaison-là qu'il faut remplacer. Rend le nombre d'appels."""
    calls = {"n": 0}

    def fake_roll(squad_id: str, game_state: Dict[str, Any]) -> int:
        calls["n"] += 1
        game_state["current_advance_roll"] = int(roll)
        return int(roll)

    monkeypatch.setattr(movement_handlers, "roll_advance_for_squad", fake_roll)
    return lambda: calls["n"]


# ─────────────────────────────────────────────────────────────────────────────
# 09.02 — sélection, report, annulation
# ─────────────────────────────────────────────────────────────────────────────

class TestSelection0902:
    def test_pool_contient_toute_l_armee_sur_table_et_pas_les_reserves_au_round_1(self, checklist_game):
        """09.02 « every unit in their army will have been selected to make a move » ; 20.03 : une
        réserve ne peut arriver qu'à partir du 2e round, donc elle n'a rien à sélectionner au 1er."""
        game = checklist_game
        on_table = {
            str(u["id"]) for u in game.state["units"]
            if u["HP_CUR"] > 0 and u["player"] == game.current_player and not u["in_strategic_reserves"]
        }
        assert set(game.pool("move_activation_pool")) == on_table
        assert game.unit("10")["in_strategic_reserves"] is True
        assert "10" not in game.pool("move_activation_pool")

    def test_report_rend_l_unite_au_pool_sans_la_marquer(self, checklist_game):
        """09.02 : une unité n'est « selected to move » qu'une fois — un report (right_click) n'est
        pas une sélection achevée, elle reste à jouer et rien n'est marqué."""
        game = checklist_game
        game.act("activate_unit", unitId="1")
        before = [_pos(game, m) for m in game.models_of("1")]
        body = game.act("right_click", unitId="1")
        assert body["result"]["action"] == "postpone"
        assert body["result"]["activation_ended"] is False
        assert "1" in game.pool("move_activation_pool")
        assert not _in(game, "units_moved", "1")
        assert [_pos(game, m) for m in game.models_of("1")] == before
        assert game.act("activate_unit", unitId="1")["result"]["unit_activated"] is True

    def test_unite_deplacee_non_reactivable(self, checklist_game):
        """09.02 « Select one friendly unit that has not been selected to move this phase »."""
        game = checklist_game
        game.act("activate_unit", unitId="1")
        game.act("commit_move_plan", unitId="1", plan=_plan_one_step(game, "1"))
        assert _in(game, "units_moved", "1")
        assert "1" not in game.pool("move_activation_pool")
        accepted, body = game.try_act("activate_unit", unitId="1")
        assert not accepted
        assert body["result"]["error"] == "unit_not_eligible"


# ─────────────────────────────────────────────────────────────────────────────
# 09.04 — rester stationnaire
# ─────────────────────────────────────────────────────────────────────────────

class TestRemainStationary0904:
    def test_stationnaire_termine_l_activation_sans_bouger_ni_declencher(self, checklist_game):
        """09.04 « No models are moved […] Units that remain stationary do not trigger any rules
        that are triggered when a unit starts or ends a move » : l'escouade ``12`` est déjà à
        moins de 9" des Termagants ``101`` (reactive_move), et rester ne pose aucune décision."""
        game = checklist_game
        termagant = _pos(game, game.models_of("101")[0])
        within = min(hex_distance(*_pos(game, m), *termagant) for m in game.models_of("12"))
        assert within <= _inches(game, REACTIVE_TRIGGER_INCHES), "prémisse : ``12`` doit être à ≤ 9\" de ``101``"
        before = [_pos(game, m) for m in game.models_of("12")]
        game.act("activate_unit", unitId="12")
        game.act("wait", unitId="12")
        assert [_pos(game, m) for m in game.models_of("12")] == before
        assert "12" not in game.pool("move_activation_pool")
        accepted, body = game.try_act("activate_unit", unitId="12")
        assert not accepted and body["result"]["error"] == "unit_not_eligible", "09.02 : sélectionnée une fois"
        assert _pending(game) is None


# ─────────────────────────────────────────────────────────────────────────────
# 09.05 + 03.01 — mouvement normal
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalMove0905:
    def test_portee_bornee_par_M(self, checklist_game):
        """09.05 « MAXIMUM DISTANCE: Your unit's M characteristic » — chaque figurine a son pool,
        aucune destination n'est à plus de M (datasheet, en pouces × inches_to_subhex)."""
        game = checklist_game
        budget = _inches(game, _datasheet_move_inches(game, "1"))
        game.act("activate_unit", unitId="1")
        for model_id in game.models_of("1"):
            dests = _model_dests(game, model_id)
            assert dests
            assert _farthest_reach(game, model_id, dests) <= budget
        # Le budget est atteint : le pool n'est pas plus étroit que la règle.
        assert _farthest_reach(game, "1#0", _model_dests(game, "1#0")) == budget

    def test_traverse_les_figurines_amies(self, checklist_game):
        """03.01 « It can be moved through friendly models » : la case droit derrière l'ami ``16``, à
        exactement la portée, n'est atteignable qu'à travers lui (un contournement coûte une case
        de plus en hex, bien plus en euclidien)."""
        game = checklist_game
        game.act("activate_unit", unitId="15")
        col, row = _pos(game, "15#0")
        friend = _pos(game, "16#0")
        assert friend[0] == col and friend[1] > row, "prémisse : l'ami ``16`` est droit au sud"
        target = (col, row + _straight_reach(game, _inches(game, _datasheet_move_inches(game, "15"))))
        assert target[1] > friend[1], "prémisse : la cible est au-delà de l'ami"
        dests = {(d[0], d[1]) for d in _model_dests(game, "15#0")}
        assert target in dests, "la traversée de la figurine amie est refusée (03.01)"
        # 03.01, fin de mouvement : jamais SUR une autre figurine.
        assert friend not in dests

    def test_ne_traverse_pas_les_figurines_ennemies(self, checklist_game, monkeypatch):
        """03.01 « Its base cannot be moved through enemy models » : même géométrie que l'ami de
        ``15``, mais l'obstacle de ``17`` est l'Hormagaunt ``110`` — la case droit derrière n'est
        plus atteignable (Advance de 6 pour que la case soit hors de la zone d'engagement)."""
        game = checklist_game
        _fix_advance_roll(monkeypatch, MAX_D6)
        game.act("activate_unit", unitId="17")
        game.act("advance", unitId="17")
        col, row = _pos(game, "17#0")
        enemy = _pos(game, "110#0")
        assert enemy[0] == col and enemy[1] > row
        budget = _inches(game, _datasheet_move_inches(game, "17") + MAX_D6)
        target = (col, row + _straight_reach(game, budget))
        assert hex_distance(*target, *enemy) > _inches(game, ENGAGEMENT_RANGE_INCHES), "prémisse : cible hors EZ"
        dests = {(d[0], d[1]) for d in _model_dests(game, "17#0")}
        assert target not in dests, "une figurine ennemie a été traversée (03.01)"
        assert enemy not in dests

    def test_bord_de_table_et_occupation(self, checklist_game):
        """03.01 « Its base cannot cross the edge of the battlefield » et fin de mouvement « No
        models in that unit are on another model » : le socle entier reste sur la table."""
        from engine.phase_handlers.shared_utils import compute_candidate_footprint

        game = checklist_game
        state = _engine_state()
        cols, rows = int(game.state["board_cols"]), int(game.state["board_rows"])
        game.act("activate_unit", unitId="9")  # Dreadnought à 6" du bord ouest
        model = state["models_cache"]["9#0"]
        dests = _model_dests(game, "9#0")
        assert dests
        for d in dests:
            for c, r in compute_candidate_footprint(d[0], d[1], model, state):
                assert 0 <= c < cols and 0 <= r < rows, f"empreinte hors table en {(c, r)} pour l'ancre {d[:2]}"
        occupied = {(int(m["col"]), int(m["row"])) for mid, m in state["models_cache"].items() if not mid.startswith("9#")}
        assert not occupied & {(d[0], d[1]) for d in dests}

    def test_zone_d_engagement_interdite_en_destination(self, checklist_game):
        """09.05 « AFTER MOVING: Your unit must be unengaged » (03.04 : 2") — une figurine posée à
        portée d'engagement d'un ennemi rend le plan invalide et le commit est refusé. La
        TRAVERSÉE de cette bande, elle, n'est interdite par aucune clause de 03.01."""
        game = checklist_game
        game.act("activate_unit", unitId="12")
        enemy_col, enemy_row = _pos(game, game.models_of("101")[0])
        # Case adjacente à l'ennemi, côté nord (vers ``12``), donc à moins de 2".
        adjacent = (enemy_col, enemy_row - 1)
        assert hex_distance(*adjacent, enemy_col, enemy_row) <= _inches(game, ENGAGEMENT_RANGE_INCHES)
        dests = {(d[0], d[1]) for d in _model_dests(game, "12#0")}
        assert adjacent not in dests
        plan = [_placement(game, m) for m in game.models_of("12")]
        plan[0] = ["12#0", adjacent[0], adjacent[1], 0]
        preview = game.act("preview_move_plan", unitId="12", plan=plan)["result"]
        assert preview["per_model"]["12#0"] is False
        assert preview["can_validate"] is False
        accepted, body = game.try_act("commit_move_plan", unitId="12", plan=plan)
        assert not accepted
        assert body["result"]["error"] == "invalid_move_plan"

    @pytest.mark.xfail(
        strict=True,
        reason="13.06 « INFANTRY/BEASTS/SWARM/MOBILE models can move horizontally through dense "
               "terrain features » — le moteur fait de tout mur un obstacle absolu hors FLY "
               "(tour_de_jeu.md « Murs : ni traversée ni arrêt dessus », shared_utils "
               "build_move_traversal_blocked « ils bloquent TOUJOURS »)",
    )
    def test_infanterie_traverse_un_mur_de_terrain_dense(self, checklist_game):
        """13.06 (Dense) : les Intercessors ``5`` au nord du mur W1 doivent pouvoir finir au sud,
        droit derrière — un détour par un bout du mur coûterait bien plus que M."""
        game = checklist_game
        w1 = _wall_cells(game, "W1_infantry")
        assert w1
        wall_row = max(r for _, r in w1)
        c0, c1 = min(c for c, _ in w1), max(c for c, _ in w1)
        game.act("activate_unit", unitId="5")
        beyond = [
            d for m in game.models_of("5") for d in _model_dests(game, m)
            if d[1] > wall_row and c0 <= d[0] <= c1
        ]
        assert beyond, "aucune destination au sud du mur W1 : l'INFANTRY est bloquée (13.06)"


# ─────────────────────────────────────────────────────────────────────────────
# 03.03 — cohérence au commit
# ─────────────────────────────────────────────────────────────────────────────

class TestCoherency0303:
    def test_refus_figurine_a_plus_de_2_pouces_de_toute_soeur(self, checklist_game):
        """03.03 1re puce « Within 2" horizontally […] of at least one other model » : une figurine
        isolée à 3" rend le plan incohérent, preview et commit le refusent."""
        game = checklist_game
        game.act("activate_unit", unitId="1")
        plan = [_placement(game, m) for m in game.models_of("1")]
        lone = max(plan, key=lambda e: e[2])  # la plus au sud, poussée encore au sud
        lone[2] += _inches(game, COHERENCY_NEAR_INCHES + 1)
        preview = game.act("preview_move_plan", unitId="1", plan=plan)["result"]
        assert preview["coherency_ok"] is False
        assert preview["can_validate"] is False
        accepted, body = game.try_act("commit_move_plan", unitId="1", plan=plan)
        assert not accepted and body["result"]["error"] == "invalid_move_plan"
        assert [_pos(game, m) for m in game.models_of("1")] == [tuple(e[1:3]) for e in [_placement(game, m) for m in game.models_of("1")]]

    def test_refus_ecart_de_plus_de_9_pouces_dans_une_chaine_intacte(self, checklist_game):
        """03.03 2e puce « Within 9" horizontally […] of every other model » : la ligne de 10
        Hormagaunts ``102`` (tour du joueur 2) s'étend sur 9" de centre à centre ; pousser son
        dernier socle de 2" le laisse à moins de 2" (socle à socle) de son voisin mais porte
        l'écart extrême au-delà de 9", quelle que soit la mesure."""
        game = checklist_game
        game.play_nominal(max_actions=4000, until=lambda c: c.current_player == 2 and c.phase == "move")
        cells = sorted((_pos(game, m), m) for m in game.models_of("102"))
        (first, _), (last, last_id) = cells[0], cells[-1]
        assert first[1] == last[1] and hex_distance(*first, *last) == _inches(game, COHERENCY_SPREAD_INCHES), (
            "prémisse : la ligne fait exactement 9\" d'un bout à l'autre"
        )
        game.act("activate_unit", unitId="102")
        plan = [_placement(game, m) for m in game.models_of("102")]
        for entry in plan:
            if entry[0] == last_id:
                entry[1] += _inches(game, COHERENCY_NEAR_INCHES)
        preview = game.act("preview_move_plan", unitId="102", plan=plan)["result"]
        assert preview["coherency_ok"] is False
        accepted, body = game.try_act("commit_move_plan", unitId="102", plan=plan)
        assert not accepted and body["result"]["error"] == "invalid_move_plan"

    def test_refus_de_deux_groupes_coherents_entre_eux_mais_disjoints(self, checklist_game):
        """03.03 lu par le moteur comme UNE seule chaîne (``_validate_plan_coherency``, lecture FAQ
        hors texte du PDF) : deux sous-groupes chacun cohérent mais à plus de 2" l'un de l'autre
        sont refusés, même si l'écart extrême reste sous 9"."""
        game = checklist_game
        game.act("activate_unit", unitId="1")
        plan = [_placement(game, m) for m in game.models_of("1")]
        north_row = min(e[2] for e in plan)
        movers = [e for e in plan if e[2] == north_row]
        assert len(movers) >= 2 and len(movers) < len(plan)
        for entry in movers:
            entry[2] -= _inches(game, COHERENCY_NEAR_INCHES + 1)
        preview = game.act("preview_move_plan", unitId="1", plan=plan)["result"]
        assert preview["coherency_ok"] is False
        accepted, body = game.try_act("commit_move_plan", unitId="1", plan=plan)
        assert not accepted and body["result"]["error"] == "invalid_move_plan"


# ─────────────────────────────────────────────────────────────────────────────
# 09.06 — Advance
# ─────────────────────────────────────────────────────────────────────────────

class TestAdvance0906:
    def test_jet_unique_fige_et_budget_M_plus_jet(self, checklist_game, monkeypatch):
        """09.06 « BEFORE MOVING: Make an advance roll by rolling one D6 » et « MAXIMUM DISTANCE:
        Advance roll + your unit's M characteristic » : un seul jet, réutilisé après un report
        d'activation (le D6 est lancé avant de bouger, il ne se rejoue pas)."""
        game = checklist_game
        roll = 4
        calls = _fix_advance_roll(monkeypatch, roll)
        move_inches = _datasheet_move_inches(game, "1")
        game.act("activate_unit", unitId="1")
        body = game.act("advance", unitId="1")
        assert body["result"]["advance_roll"] == roll
        assert _in(game, "units_advanced", "1")
        reach = _farthest_reach(game, "1#0", _model_dests(game, "1#0"))
        assert _inches(game, move_inches) < reach <= _inches(game, move_inches + roll)
        game.act("right_click", unitId="1")
        again = game.act("activate_unit", unitId="1")["result"]
        assert again["advance_roll"] == roll
        assert calls() == 1, "le D6 d'Advance a été relancé"

    def test_refus_si_engagee(self, checklist_game):
        """09.06 « ELIGIBLE IF: Your unit is on the battlefield and unengaged »."""
        game = checklist_game
        game.act("activate_unit", unitId="3")
        accepted, body = game.try_act("advance", unitId="3")
        assert not accepted
        assert body["result"]["error"] == "unit_engaged"
        assert not _in(game, "units_advanced", "3")

    def test_pas_de_charge_apres_advance(self, checklist_game, monkeypatch):
        """09.06 « AFTER MOVING: Until the end of the turn […] your unit is not eligible to declare a
        charge »."""
        game = checklist_game
        _fix_advance_roll(monkeypatch, MAX_D6)
        game.act("activate_unit", unitId="1")
        game.act("advance", unitId="1")
        game.act("commit_move_plan", unitId="1", plan=_plan_one_step(game, "1"))
        game.drain_to("charge")
        assert "1" not in game.pool("charge_activation_pool")

    def test_tir_apres_advance_seulement_avec_des_armes_assault(self, checklist_game, monkeypatch):
        """10.05 (Assault shooting) « ELIGIBLE IF: Unengaged and made an advance move this turn ;
        Has one or more [ASSAULT] weapons » — les Intercessors (bolt rifle [ASSAULT]) tirent avec
        leurs seules armes [ASSAULT] ; le Dreadnought ``9`` (aucune) sort du pool de tir."""
        game = checklist_game
        _fix_advance_roll(monkeypatch, MAX_D6)
        for unit_id in ("1", "9"):
            game.act("activate_unit", unitId=unit_id)
            game.act("advance", unitId=unit_id)
            game.act("commit_move_plan", unitId=unit_id, plan=_plan_one_step(game, unit_id))
        game.drain_to("shoot")
        assert "9" not in game.pool("shoot_activation_pool")
        assert "1" in game.pool("shoot_activation_pool")
        activation = game.act("squad_shoot_activate", unitId="1")["result"]
        targets = game.act("squad_shoot_los_overview", unitId="1")["result"]["valid_targets"]
        assert targets
        offered = game.act("squad_shoot_weapons_for_target", unitId="1", targetId=targets[0])["result"]["weapons"]
        assert offered
        assert all("ASSAULT" in w["weapon"]["WEAPON_RULES"] for w in offered)
        non_assault = next(w for w in activation["available_weapons"] if "ASSAULT" not in w["weapon"]["WEAPON_RULES"])
        accepted, body = game.try_act(
            "squad_shoot_assign_weapon_qty",
            unitId="1", weaponCode=non_assault["weapon"]["code"], count=1, targetId=targets[0],
        )
        assert not accepted and body["result"]["error"] == "cannot_shoot"


# ─────────────────────────────────────────────────────────────────────────────
# 09.07 — Fall back : Ordered Retreat / Desperate Escape
# ─────────────────────────────────────────────────────────────────────────────

def _beyond_enemy_line(game, unit_id: str, line_unit_id: str, dests_by_model: Dict[str, List[List[int]]]) -> Dict[str, int]:
    """Destinations AU-DELÀ de la ligne ennemie (côté opposé à l'escouade), dans l'empan de la
    ligne et hors de sa zone d'engagement — atteignables seulement en la traversant."""
    line = [_pos(game, m) for m in game.models_of(line_unit_id)]
    line_row = max(r for _, r in line)
    c0, c1 = min(c for c, _ in line), max(c for c, _ in line)
    ez = _inches(game, ENGAGEMENT_RANGE_INCHES)
    return {
        mid: sum(1 for d in dests if d[1] > line_row + ez and c0 <= d[0] <= c1)
        for mid, dests in dests_by_model.items()
    }


def _hazard_logs() -> List[Dict[str, Any]]:
    return [entry for entry in _engine_state()["action_logs"] if entry.get("type") == "hazard"]


class TestFallBack0907:
    def test_ordered_retreat_sans_hazard_et_desengage(self, checklist_game):
        """09.07 « Ordered Retreat: If your unit is not battle-shocked, you can select this mode »
        — aucun jet de hazard, aucun test de battle-shock ; « AFTER MOVING: Your unit must be
        unengaged »."""
        game = checklist_game
        hp_before = {m: _hp(game, m) for m in game.models_of("3")}
        body = game.act("activate_unit", unitId="3")
        assert body["result"]["would_flee"] is True
        assert body["result"]["fall_back_mode"] == "ordered_retreat"
        plan = _plan_towards_row(game, "3", -1)
        game.act("commit_move_plan", unitId="3", plan=plan)
        assert _in(game, "units_fled", "3") and _in(game, "units_moved", "3")
        assert {m: _hp(game, m) for m in game.models_of("3")} == hp_before
        assert _hazard_logs() == []
        assert game.unit("3")["battle_shocked"] is False
        assert not _engaged_per_engine(game, "3")

    def test_desperate_escape_selectionnable_par_une_unite_saine(self, checklist_game, monkeypatch):
        """09.07 encart SELECTING MODES « ordered retreat is not mandatory, so you could select
        desperate escape instead » ; « Make a hazard roll for each model » (06.03 : 1 blessure
        mortelle par 1-2) ; « WHILE MOVING — Desperate Escape: Each model […] can be moved
        through enemy models » ; « AFTER MOVING — Desperate Escape: If your unit is not
        battle-shocked, you must make a battle-shock roll » (01.07)."""
        game = checklist_game
        models = game.models_of("3")
        game.act("activate_unit", unitId="3")
        ordered = {m: _model_dests(game, m) for m in models}
        assert all(n == 0 for n in _beyond_enemy_line(game, "3", "102", ordered).values())
        # Un seul échec (le 1er dé), puis 2D6 = 12 pour le battle-shock d'après mouvement.
        rolls = [1] + [MAX_D6] * (len(models) - 1)
        consumed = _fix_dice(monkeypatch, rolls + [MAX_D6, MAX_D6])
        body = game.act("hazard_confirm", unitId="3")
        assert consumed() == len(models), "un hazard roll par figurine (09.07)"
        victim = models[-1]
        body = _settle_hazard_allocation(game, "3", body, lambda choices: victim)
        assert body["result"]["fall_back_mode"] == "desperate_escape"
        assert _hp(game, victim) == 1, "06.02 : la blessure mortelle va à la figurine désignée"
        assert all(_hp(game, m) == 2 for m in models if m != victim)
        desperate = {m: _model_dests(game, m) for m in models}
        assert all(n > 0 for n in _beyond_enemy_line(game, "3", "102", desperate).values()), (
            "Desperate Escape n'ouvre pas la traversée des figurines ennemies"
        )
        plan = _plan_towards_row(game, "3", +1)
        assert max(e[2] for e in plan) > max(_pos(game, m)[1] for m in game.models_of("102"))
        game.act("commit_move_plan", unitId="3", plan=plan)
        assert _in(game, "units_fled", "3")
        assert consumed() == len(models) + 2, "le battle-shock roll d'AFTER MOVING n'a pas eu lieu"
        assert game.unit("3")["battle_shocked"] is False  # 12 ≥ Ld

    def test_desperate_escape_battle_shock_rate_apres_le_mouvement(self, checklist_game, monkeypatch):
        """09.07 AFTER MOVING — Desperate Escape « you must make a battle-shock roll » : 2D6 = 2
        sous le Ld rend l'unité battle-shocked à l'issue de sa retraite."""
        game = checklist_game
        models = game.models_of("3")
        game.act("activate_unit", unitId="3")
        _fix_dice(monkeypatch, [MAX_D6] * len(models) + [1, 1])
        game.act("hazard_confirm", unitId="3")
        game.act("commit_move_plan", unitId="3", plan=_plan_towards_row(game, "3", +1))
        assert game.unit("3")["battle_shocked"] is True

    def test_desperate_escape_3_blessures_mortelles_si_tout_monster_vehicle(self, checklist_game, monkeypatch):
        """06.03 (hazard roll) : « 3 mortal wounds instead if each model in that unit is a
        MONSTER/VEHICLE model » — le Dreadnought ``4`` engagé perd 3 PV sur un 1."""
        game = checklist_game
        hp = _hp(game, "4#0")
        game.act("activate_unit", unitId="4")
        _fix_dice(monkeypatch, [1])
        body = game.act("hazard_confirm", unitId="4")
        _settle_hazard_allocation(game, "4", body, lambda choices: choices[0])
        assert _hp(game, "4#0") == hp - 3

    def test_desperate_escape_impose_a_une_unite_battle_shocked(self, checklist_game, monkeypatch):
        """09.07 « Desperate Escape: Otherwise, you must select this mode » : engagée ET
        battle-shocked, l'activation ne propose pas Ordered Retreat, elle exige le hazard."""
        game = checklist_game
        _fix_dice(monkeypatch, [1, 1])  # 2D6 = 2 < Ld → battle-shocked (01.07)
        assert game.act("force_battle_shock", unitId="3")["result"]["battle_shocked"] is True
        body = game.act("activate_unit", unitId="3")
        assert body["result"]["action"] == "requires_hazard"
        assert body["result"]["requires_hazard"] is True
        accepted, refused = game.try_act("commit_move_plan", unitId="3", plan=[_placement(game, m) for m in game.models_of("3")])
        assert not accepted, "un déplacement a été accepté avant la résolution du hazard imposé"

    def test_hazard_ne_se_rejoue_pas(self, checklist_game, monkeypatch):
        """09.07 BEFORE MOVING : le mode est arrêté une fois — une seconde confirmation (double
        clic, report puis ré-activation) ne relance pas les dés."""
        game = checklist_game
        models = game.models_of("3")
        game.act("activate_unit", unitId="3")
        _fix_dice(monkeypatch, [MAX_D6] * len(models))
        game.act("hazard_confirm", unitId="3")
        accepted, body = game.try_act("hazard_confirm", unitId="3")
        assert not accepted and body["result"]["error"] == "hazard_already_resolved"

    def test_unite_ayant_fui_ne_tire_ni_ne_charge(self, checklist_game):
        """09.07 « AFTER MOVING: Until the end of the turn […] your unit is not eligible to shoot,
        declare a charge » (sauf règle de datasheet, ``charge_after_flee`` — aucun porteur ici)."""
        game = checklist_game
        game.act("activate_unit", unitId="3")
        game.act("commit_move_plan", unitId="3", plan=_plan_towards_row(game, "3", -1))
        assert _in(game, "units_fled", "3")
        game.drain_to("shoot")
        assert "3" not in game.pool("shoot_activation_pool")
        game.drain_to("charge")
        assert "3" not in game.pool("charge_activation_pool")


def _engaged_per_engine(game, unit_id: str) -> bool:
    """Engagement d'une escouade DÉJÀ déplacée : le preview n'est plus disponible, on mesure
    socle-à-socle avec la primitive du moteur (03.04)."""
    from engine.phase_handlers.shared_utils import (
        get_engagement_zone, require_unit_by_id, unit_within_engagement_zone_footprints,
    )

    state = _engine_state()
    return bool(unit_within_engagement_zone_footprints(
        state, require_unit_by_id(state, unit_id), engagement_zone=get_engagement_zone(state), max_distance=None
    ))


# ─────────────────────────────────────────────────────────────────────────────
# 17.01 — Monstres et véhicules
# ─────────────────────────────────────────────────────────────────────────────

class TestMonstersVehicles1701:
    def test_traverse_l_infanterie_mais_pas_les_monstres_vehicules(self, checklist_game, monkeypatch):
        """17.01 « Each time you make a normal or advance move with a unit, MONSTER/VEHICLE models
        in that unit can be moved through friendly and enemy models (excluding other
        MONSTER/VEHICLE models) » : même géométrie pour ``9`` (ligne d'Hormagaunts) et ``14``
        (Psychophage), la case droit derrière à la portée exacte n'est atteignable que pour ``9``."""
        game = checklist_game
        _fix_advance_roll(monkeypatch, MAX_D6)
        reach = _straight_reach(game, _inches(game, _datasheet_move_inches(game, "9") + MAX_D6))
        results = {}
        for unit_id, obstacle_id in (("9", "107"), ("14", "108")):
            game.act("activate_unit", unitId=unit_id)
            game.act("advance", unitId=unit_id)
            col, row = _pos(game, f"{unit_id}#0")
            in_column = [p for p in (_pos(game, m) for m in game.models_of(obstacle_id)) if p[0] == col]
            assert in_column and all(row < p[1] < row + reach for p in in_column), (
                f"prémisse : {obstacle_id} droit au sud de {unit_id}, avant la cible"
            )
            target = (col, row + reach)
            results[unit_id] = target in {(d[0], d[1]) for d in _model_dests(game, f"{unit_id}#0")}
            game.act("right_click", unitId=unit_id)
        assert results["9"] is True, "un VEHICLE ne traverse pas l'infanterie ennemie (17.01)"
        assert results["14"] is False, "un VEHICLE traverse un MONSTER (17.01 : excluding other MONSTER/VEHICLE)"

    def test_jamais_en_fall_back(self, checklist_game, monkeypatch):
        """17.01 ne couvre que « a normal or advance move » : en Ordered Retreat le Dreadnought
        ``4`` ne traverse pas la ligne ``103`` (rien au-delà) ; seul Desperate Escape (09.07) l'ouvre."""
        game = checklist_game
        game.act("activate_unit", unitId="4")
        ordered = _beyond_enemy_line(game, "4", "103", {"4#0": _model_dests(game, "4#0")})
        assert ordered["4#0"] == 0
        _fix_dice(monkeypatch, [MAX_D6])
        body = game.act("hazard_confirm", unitId="4")
        assert body["result"]["fall_back_mode"] == "desperate_escape"
        desperate = _beyond_enemy_line(game, "4", "103", {"4#0": _model_dests(game, "4#0")})
        assert desperate["4#0"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# 21.03 — vol
# ─────────────────────────────────────────────────────────────────────────────

class TestFlying2103:
    def test_moins_2_pouces_et_traversee_des_murs(self, checklist_game):
        """21.03 « Subtract 2" from the maximum distance » ; « It can move horizontally and
        vertically through all categories of terrain feature » : sans déclaration les jump packs
        ``6`` butent sur le mur W2, déclarés ils finissent au-delà avec 2" de moins."""
        game = checklist_game
        w2_row = max(r for _, r in _wall_cells(game, "W2_fly"))
        move_inches = _datasheet_move_inches(game, "6")
        game.act("activate_unit", unitId="6")
        grounded = _model_dests(game, "6#0")
        assert _farthest_reach(game, "6#0", grounded) == _inches(game, move_inches)
        assert not [d for d in grounded if d[1] > w2_row]
        body = game.act("take_to_skies", unitId="6")
        assert body["result"]["took_to_skies"] is True
        flying = _model_dests(game, "6#0")
        assert _farthest_reach(game, "6#0", flying) == _inches(game, move_inches - FLY_PENALTY_INCHES)
        assert [d for d in flying if d[1] > w2_row], "le vol déclaré ne traverse pas le mur (21.03)"

    def test_declaration_par_mouvement(self, checklist_game):
        """21.03 « Each time a FLYING unit is selected to make a normal, advance, fall-back or
        charge move […] the active player can declare » : la déclaration vaut pour CE mouvement —
        elle ne vaut pas pour la charge du même tour ni pour le mouvement du tour suivant."""
        game = checklist_game
        game.act("activate_unit", unitId="6")
        game.act("take_to_skies", unitId="6")
        assert _in(game, "units_took_to_skies", "6")
        game.act("commit_move_plan", unitId="6", plan=_plan_one_step(game, "6"))
        game.drain_to("charge")
        assert not _in(game, "units_took_to_skies_charge", "6")
        _at_round(game, 2, player=1, phase="move")
        assert not _in(game, "units_took_to_skies", "6")
        assert game.act("activate_unit", unitId="6")["result"]["unit_activated"] is True
        assert _farthest_reach(game, "6#0", _model_dests(game, "6#0")) == _inches(game, _datasheet_move_inches(game, "6"))


# ─────────────────────────────────────────────────────────────────────────────
# 13.06 — étages
# ─────────────────────────────────────────────────────────────────────────────

class TestTerrainMovement1306:
    def test_infanterie_finit_en_hauteur_en_payant_la_montee(self, checklist_game):
        """13.06 « Models can also be set up or end a move on any surface […] if […] That model has
        one or more of the following keywords: INFANTRY/BEASTS/SWARM/FLY/MONSTER » et MOVING
        VERTICALLY « Add the distance moved vertically up […] to any other distance that model
        has moved » : les Intercessors ``7`` atteignent l'étage, mais pas au-delà de M − 3"."""
        game = checklist_game
        floor_cells, height_inches = _floor_cells_and_height(game)
        budget_inches = _datasheet_move_inches(game, "7")
        game.act("activate_unit", unitId="7")
        elevated = [d for d in _model_dests(game, "7#0", level=1) if d[2] == 1]
        assert elevated, "aucune case d'étage proposée à l'INFANTRY"
        assert {(d[0], d[1]) for d in elevated} <= floor_cells
        assert _farthest_reach(game, "7#0", elevated) <= _inches(game, budget_inches - height_inches)
        # Masque ⊆ exécutable : CHAQUE case d'étage offerte passe la validation individuelle du
        # voile rouge (`movement_preview_move_plan`, mêmes contraintes : budget, sans cohérence —
        # la cohérence dépend des sœurs, pas de la case).
        from engine.phase_handlers.shared_utils import explain_move_plan_rejection, get_squad_move_budget

        state = _engine_state()
        constraints = {"budget_per_model": get_squad_move_budget("7", state, "normal"), "require_coherency": False}
        for cell in elevated:
            reason = explain_move_plan_rejection([("7#0", cell[0], cell[1], 1)], state, constraints)
            assert reason is None, (cell, reason)
        plan = [["7#0", elevated[0][0], elevated[0][1], 1]] + [_placement(game, m) for m in game.models_of("7")[1:]]
        preview = game.act("preview_move_plan", unitId="7", plan=plan)["result"]
        assert preview["can_validate"] is True, preview
        game.act("commit_move_plan", unitId="7", plan=plan)
        assert int(game.state["models_cache"]["7#0"]["level"]) == 1

    def test_vehicule_ne_finit_pas_en_hauteur(self, checklist_game):
        """13.06 : sans mot-clé INFANTRY/BEASTS/SWARM/FLY/MONSTER, le Dreadnought ``8`` ne reçoit
        aucune case d'étage et un plan qui l'y pose est refusé au commit."""
        from engine.phase_handlers.shared_utils import compute_candidate_footprint

        game = checklist_game
        state = _engine_state()
        floor_cells, height_inches = _floor_cells_and_height(game)
        game.act("activate_unit", unitId="8")
        col, row = _pos(game, "8#0")
        model = state["models_cache"]["8#0"]
        # Case d'étage la plus proche où le socle ENTIER tient sur le plancher et que le budget
        # M − montée permet d'atteindre : la seule raison de refuser est alors le mot-clé.
        reachable = _inches(game, _datasheet_move_inches(game, "8") - height_inches)
        candidates = [
            cell for cell in floor_cells
            if hex_distance(col, row, *cell) <= reachable
            and set(compute_candidate_footprint(cell[0], cell[1], model, state)) <= floor_cells
        ]
        assert candidates, "prémisse : aucune case d'étage à portée du Dreadnought"
        target = min(candidates, key=lambda cell: hex_distance(col, row, *cell))
        preview = game.act("preview_move_plan", unitId="8", plan=[["8#0", target[0], target[1], 1]])["result"]
        assert preview["per_model"]["8#0"] is False
        accepted, body = game.try_act("commit_move_plan", unitId="8", plan=[["8#0", target[0], target[1], 1]])
        assert not accepted and body["result"]["error"] == "invalid_move_plan"
        assert int(game.state["models_cache"]["8#0"]["level"]) == 0
        assert not [d for d in _model_dests(game, "8#0", level=1) if d[2] == 1]


# ─────────────────────────────────────────────────────────────────────────────
# 20.01–20.04 + 24.09 — réserves stratégiques
# ─────────────────────────────────────────────────────────────────────────────

class TestStrategicReserves20:
    def test_20_01_plafond_50_pourcent_a_la_declaration(self, declaration_game):
        """20.01 « the combined points value of all of your strategic reserves units […] cannot
        exceed 50% of your points limit for your battle size » : à 300 pts (plafond 150) le
        Dreadnought (160) n'est jamais proposable ; le Psychophage (125) consomme le plafond du
        joueur 2 et retire les Termagants (30) de la liste."""
        game = declaration_game
        summary = game.state["strategic_reserves"]
        cap = int(game.state["points_limit"] * 0.5)
        assert summary["1"]["cap_points"] == cap and summary["declaring_player"] == 1
        assert "1" not in summary["declarable"] and "2" in summary["declarable"]
        accepted, body = game.try_act("deploy_strategic_reserves", unitId="1")
        assert not accepted
        assert body["result"]["error"] == "unit_not_declarable_in_strategic_reserves"
        assert body["result"]["reservesCap"] == cap
        game.act("deploy_strategic_reserves", unitId="2")
        game.act("validate_reserves_declaration")
        summary = game.state["strategic_reserves"]
        assert summary["declaring_player"] == 2 and set(summary["declarable"]) == {"101", "102"}
        game.act("deploy_strategic_reserves", unitId="101")
        summary = game.state["strategic_reserves"]
        assert summary["2"]["used_points"] == int(game.unit("101")["VALUE"])
        assert "102" not in summary["declarable"]
        accepted, body = game.try_act("deploy_strategic_reserves", unitId="102")
        assert not accepted and body["result"]["error"] == "unit_not_declarable_in_strategic_reserves"

    def test_20_03_aucune_arrivee_au_premier_round(self, checklist_game):
        """20.03 « Unless otherwise stated, they can only do so from the second battle round
        onwards »."""
        game = checklist_game
        assert int(game.state["turn"]) == 1
        accepted, body = game.try_act("ingress_commit", unitId="10", plan=_plan_row(game, "10", _inches(game, 12), _inches(game, 55)))
        assert not accepted and body["result"]["error"] == "unit_not_eligible"
        assert game.unit("10")["in_strategic_reserves"] is True

    def test_24_09_deep_strike_partout_a_plus_de_8_pouces(self, checklist_game):
        """24.09 « it can be set up anywhere on the battlefield that is more than 8" horizontally
        from all enemy units, even if that is within your opponent's deployment zone » : le Land
        Speeder ``10`` est refusé à moins de 8" des Hormagaunts ``109``, accepté dans la zone du
        joueur 2 loin d'eux ; 20.04 AFTER MOVING : plus aucun mouvement ensuite."""
        game = checklist_game
        _at_round(game, INGRESS_FIRST_ROUND)
        assert "10" in game.pool("move_activation_pool"), "09.02 : une réserve arrivable est sélectionnable"
        preview = game.act("ingress_preview", unitId="10")["result"]
        assert preview["eligible"] is True and preview["cells"] > 0
        enemy = _pos(game, game.models_of("109")[0])
        too_close = (enemy[0], enemy[1] - _inches(game, INGRESS_ENEMY_CLEARANCE_INCHES - 1))
        accepted, body = game.try_act("ingress_commit", unitId="10", plan=[["10#0", too_close[0], too_close[1], 0]])
        assert not accepted and body["result"]["error"] == "invalid_deploy_plan"
        assert body["result"]["per_model"]["10#0"] is False
        far = (enemy[0] - _inches(game, INGRESS_ENEMY_CLEARANCE_INCHES + 10), enemy[1] - _inches(game, 1))
        game.act("ingress_commit", unitId="10", plan=[["10#0", far[0], far[1], 0]])
        assert _pos(game, "10#0") == far
        assert game.unit("10")["in_strategic_reserves"] is False
        assert _in(game, "units_ingressed_no_move", "10") and _in(game, "units_moved", "10")
        accepted, body = game.try_act("activate_unit", unitId="10")
        assert not accepted and body["result"]["error"] == "unit_not_eligible"

    def test_20_04_bande_de_6_pouces_hors_zone_adverse_avant_le_3e_round(self, checklist_game):
        """20.04 « Set up your unit wholly within the set-up distance [6"] of one or more
        battlefield edges and more than 8" horizontally from all enemy units. Before the Third
        Battle Round: […] no models can be set up within your opponent's deployment zone » —
        les Hormagaunts ``104`` du joueur 2, au 2e round."""
        game = checklist_game
        _at_round(game, INGRESS_FIRST_ROUND, player=2)
        assert "104" in game.pool("move_activation_pool")
        rows = int(game.state["board_rows"])
        band = _inches(game, INGRESS_EDGE_BAND_INCHES)
        mid_col = int(game.state["board_cols"]) // 2
        refused = {
            "bande nord = zone du joueur 1": _north_west_corner(game),
            "hors bande": (mid_col, rows // 2),
        }
        for label, (col, row) in refused.items():
            accepted, body = game.try_act("ingress_commit", unitId="104", plan=_plan_row(game, "104", col, row))
            assert not accepted and body["result"]["error"] == "invalid_deploy_plan", label
        # À moins de 8" des Intercessors ``7`` (bande sud) : refusé aussi.
        near = _pos(game, game.models_of("7")[0])
        accepted, body = game.try_act(
            "ingress_commit", unitId="104",
            plan=_plan_row(game, "104", near[0], rows - band // 2),
        )
        assert not accepted and body["result"]["error"] == "invalid_deploy_plan"
        game.act("ingress_commit", unitId="104", plan=_plan_row(game, "104", mid_col, rows - band // 2))
        assert all(_pos(game, m)[1] >= rows - band for m in game.models_of("104"))
        assert _in(game, "units_ingressed_no_move", "104")

    def test_20_04_zone_adverse_ouverte_au_3e_round(self, checklist_game):
        """20.04 : la clause « no models can be set up within your opponent's deployment zone » ne
        vaut qu'« Before the Third Battle Round » — au 3e, la bande nord s'ouvre au joueur 2."""
        game = checklist_game
        _at_round(game, INGRESS_OPPONENT_ZONE_OPEN_ROUND, player=2)
        band = _inches(game, INGRESS_EDGE_BAND_INCHES)
        corner = _north_west_corner(game)
        game.act("ingress_commit", unitId="104", plan=_plan_row(game, "104", *corner))
        assert all(_pos(game, m)[1] < band for m in game.models_of("104"))

    def test_20_04_verrou_apres_ingress_jusqu_au_debut_de_la_charge(self, checklist_game):
        """20.04 « AFTER MOVING: Unless otherwise stated, until the start of the next Charge phase,
        your unit is not eligible to make any other type of move » : le Land Speeder ``10`` porte
        le verrou dès son arrivée, ne peut plus être activé, et le verrou tombe à la charge."""
        game = checklist_game
        _at_round(game, INGRESS_FIRST_ROUND)
        enemy = _pos(game, game.models_of("109")[0])
        far = (enemy[0] - _inches(game, INGRESS_ENEMY_CLEARANCE_INCHES + 10), enemy[1] - _inches(game, 1))
        game.act("ingress_commit", unitId="10", plan=[["10#0", far[0], far[1], 0]])
        assert _in(game, "units_ingressed_no_move", "10")
        accepted, body = game.try_act("activate_unit", unitId="10")
        assert not accepted and body["result"]["error"] == "unit_not_eligible"
        game.drain_to("shoot")
        assert _in(game, "units_ingressed_no_move", "10"), "le verrou couvre encore la phase de tir"
        game.drain_to("charge")
        assert not _in(game, "units_ingressed_no_move", "10"), "le verrou tombe au début de la phase de charge"

    def test_20_04_verrou_couvre_le_move_after_shooting(self, checklist_game):
        """20.04 AFTER MOVING : « any other type of move » inclut le repositionnement post-tir de
        la datasheet (Purgation Run, ``move_after_shooting``) — refusé le tour de l'arrivée,
        proposé le tour suivant, à D6" × ``inches_to_subhex`` (le D6 vaut 1 ici : tous les dés
        du tir sont figés à 1, celui de la distance compris)."""
        game = checklist_game
        _at_round(game, INGRESS_FIRST_ROUND)
        enemy = _pos(game, game.models_of("109")[0])
        far = (enemy[0] - _inches(game, INGRESS_ENEMY_CLEARANCE_INCHES + 10), enemy[1] - _inches(game, 1))
        game.act("ingress_commit", unitId="10", plan=[["10#0", far[0], far[1], 0]])
        assert _shoot_with(game, "10", "109")["action"] == "squad_shoot"
        _at_round(game, INGRESS_FIRST_ROUND + 1)
        result = _shoot_with(game, "10", "109")
        assert result["action"] == "move_after_shooting_select_destination"
        assert result["waiting_for_player"] is True
        origin = _pos(game, "10#0")
        dests = [(int(d["col"]), int(d["row"])) for d in result["move_after_shooting_destinations"]]
        assert dests
        # Budget 1" en cases du plateau : ≥ la portée en ligne droite le long d'une colonne
        # (métrique du move), ≤ le budget. Sans conversion, le D6 valait 1 CASE (0,2" à x5).
        reach = max(hex_distance(*origin, *d) for d in dests)
        assert _straight_reach(game, _inches(game, 1)) <= reach <= _inches(game, 1), reach
        assert game.state["active_shooting_unit"] == "10"
        # Le tour se termine par l'action `move_after_shooting` : renoncer ferme l'activation.
        body = game.act("move_after_shooting", unitId="10", skip_move_after_shooting=True)
        assert body["result"]["activation_ended"] is True
        assert "10" not in game.pool("shoot_activation_pool")
        assert _pos(game, "10#0") == origin

    def test_20_04_reserves_jamais_arrivees_detruites_a_la_fin_du_3e_round(self, checklist_game):
        """20.04 « At the end of the third battle round […] all strategic reserves units that have
        not made one or more ingress moves are destroyed »."""
        game = checklist_game
        _at_round(game, RESERVES_LAST_ROUND, player=2, phase="fight")
        assert game.unit("10")["HP_CUR"] > 0 and game.unit("104")["HP_CUR"] > 0
        _at_round(game, RESERVES_LAST_ROUND + 1)
        assert game.unit("10")["HP_CUR"] == 0 and game.unit("104")["HP_CUR"] == 0
        assert "10" not in game.pool("move_activation_pool")


def _north_west_corner(game) -> Tuple[int, int]:
    """Ancre d'une formation en ligne dans la bande nord (zone de déploiement du joueur 1), loin
    de toute unité du joueur 1 : à 1" du bord ouest, au milieu de la bande de 6"."""
    return (_inches(game, 1), _inches(game, INGRESS_EDGE_BAND_INCHES) // 2)


def _shoot_with(game, unit_id: str, target_id: str) -> Dict[str, Any]:
    """Tir complet de ``unit_id`` sur ``target_id`` (armes au maximum, tous les dés à 1 : aucune
    blessure, donc aucune attribution) ; rend le ``result`` de ``squad_shoot_validate``, dont
    l'``action`` vaut ``move_after_shooting_select_destination`` quand le repositionnement est
    proposé (son D6 de distance vaut alors 1 aussi)."""
    game.drain_to("shoot")
    assert unit_id in game.pool("shoot_activation_pool")
    game.act("squad_shoot_activate", unitId=unit_id)
    targets = game.act("squad_shoot_los_overview", unitId=unit_id)["result"]["valid_targets"]
    assert target_id in targets, targets
    weapons = game.act("squad_shoot_weapons_for_target", unitId=unit_id, targetId=target_id)["result"]["weapons"]
    assert weapons
    game.act("squad_shoot_assign_weapon_qty", unitId=unit_id, weaponCode=weapons[0]["code"], count=weapons[0]["m"], targetId=target_id)
    with mock.patch.object(random, "randint", lambda a, b: 1):
        body = game.act("squad_shoot_validate", unitId=unit_id)
    return body["result"]


# ─────────────────────────────────────────────────────────────────────────────
# reactive_move — Skulking Horrors (Termagants)
# ─────────────────────────────────────────────────────────────────────────────

def _southward(col: int) -> Callable[[Sequence[int]], Any]:
    """Rang « le plus au sud, puis le plus proche de la colonne ``col`` »."""
    return lambda cell: (-cell[1], abs(cell[0] - col))


class TestReactiveMove:
    def test_declenchement_a_9_pouces_et_attente_du_joueur_adverse(self, checklist_game):
        """config/unit_rules.json ``reactive_move`` : « when an enemy unit ends a Normal, Advance
        or Fall Back move within 9" of this unit, if this unit is not within Engagement Range […]
        it can make a Normal move of up to D6" ». Ici c'est le JOUEUR 2 qui décide pendant le
        tour du joueur 1 : toute autre action attend sa réponse."""
        game = checklist_game
        termagant = _pos(game, game.models_of("101")[0])
        before = min(hex_distance(*_pos(game, m), *termagant) for m in game.models_of("2"))
        assert before > _inches(game, REACTIVE_TRIGGER_INCHES), "prémisse : ``2`` part à plus de 9\""
        # Loin de tout Termagant, un mouvement ne pose aucune question.
        _quick_move(game, "1", _southward(_pos(game, "1#0")[0]))
        assert _pending(game) is None
        _quick_move(game, "2", _southward(termagant[0]))
        after = min(hex_distance(*_pos(game, m), *termagant) for m in game.models_of("2"))
        assert after <= _inches(game, REACTIVE_TRIGGER_INCHES)
        decision = _pending(game)
        assert decision is not None and decision["type"] == "reactive_move"
        assert int(decision["player"]) == 2 and str(decision["unit_id"]) == "101"
        assert any(option["declines"] for option in decision["options"])
        assert any(not option["declines"] for option in decision["options"])
        body = game.act("activate_unit", unitId="12")
        assert body["result"]["action"] == "waiting_for_reactive_move"
        assert game.state.get("active_movement_unit") in (None, "")

    def test_refus_possible(self, checklist_game):
        """« it CAN make a Normal move » : refuser laisse l'unité en place et rend la main."""
        game = checklist_game
        termagant = _pos(game, game.models_of("101")[0])
        positions = [_pos(game, m) for m in game.models_of("101")]
        _quick_move(game, "2", _southward(termagant[0]))
        decision = _pending(game)
        assert decision is not None
        declines = next(i for i, option in enumerate(decision["options"]) if option["declines"])
        game.act("agent_decision", option_index=declines)
        assert _pending(game) is None
        assert [_pos(game, m) for m in game.models_of("101")] == positions
        assert game.act("activate_unit", unitId="12")["result"]["unit_activated"] is True

    def test_pas_de_reaction_si_engagee(self, checklist_game):
        """« if this unit is not within Engagement Range of one or more enemy units » : les jump
        packs ``6`` finissent à moins de 9" des Termagants ``106``, engagés avec ``13`` — rien."""
        game = checklist_game
        assert _engaged_per_engine(game, "106"), "prémisse : ``106`` est engagée (avec ``13``)"
        termagant = _pos(game, game.models_of("106")[0])
        _quick_move(game, "6", lambda cell: hex_distance(cell[0], cell[1], *termagant))
        assert min(hex_distance(*_pos(game, m), *termagant) for m in game.models_of("6")) <= _inches(game, REACTIVE_TRIGGER_INCHES)
        assert _pending(game) is None

    def test_reaction_appliquee_une_fois_par_tour(self, checklist_game, monkeypatch):
        """« Once per turn » : la réaction accomplie déplace ``101`` (D6" figé) ; un second
        mouvement ennemi à moins de 9" (``12``) ne rouvre pas la fenêtre."""
        game = checklist_game
        termagant = _pos(game, game.models_of("101")[0])
        positions = [_pos(game, m) for m in game.models_of("101")]
        _fix_dice(monkeypatch, [MAX_D6])  # D6 de distance du mouvement réactif
        _quick_move(game, "2", _southward(termagant[0]))
        decision = _pending(game)
        assert decision is not None
        press = next(i for i, option in enumerate(decision["options"]) if not option["declines"])
        game.act("agent_decision", option_index=press)
        assert _pending(game) is None
        assert [_pos(game, m) for m in game.models_of("101")] != positions
        assert _in(game, "units_reacted_this_enemy_turn", "101")
        moved = max(hex_distance(*a, *b) for a, b in zip(positions, [_pos(game, m) for m in game.models_of("101")]))
        assert 0 < moved <= _inches(game, MAX_D6)
        _quick_move(game, "12", _southward(_pos(game, "12#0")[0]))
        assert _pending(game) is None

    def test_le_commit_par_figurine_declenche_aussi_la_fenetre(self, checklist_game):
        """config/unit_rules.json ``reactive_move`` : « when an enemy unit ends a Normal, Advance or
        Fall Back move within 9" » — le type de commit n'entre pas dans la règle. Le commit
        par-figurine est le chemin du front pour toute escouade ; sa réponse porte l'attente
        de l'adversaire, comme le move à l'ancre."""
        game = checklist_game
        termagant = _pos(game, game.models_of("101")[0])
        game.act("activate_unit", unitId="2")
        body = game.act("commit_move_plan", unitId="2", plan=_plan_towards_row(game, "2", +1))
        assert min(hex_distance(*_pos(game, m), *termagant) for m in game.models_of("2")) <= _inches(game, REACTIVE_TRIGGER_INCHES)
        decision = _pending(game)
        assert decision is not None and decision["type"] == "reactive_move"
        assert body["result"]["waiting_for_player"] is True
        assert game.act("activate_unit", unitId="12")["result"]["action"] == "waiting_for_reactive_move"


# ─────────────────────────────────────────────────────────────────────────────
# 09.03 — fin de la phase de mouvement
# ─────────────────────────────────────────────────────────────────────────────

class TestEndOfMovementPhase0903:
    def test_transition_au_tir_puis_actions_de_mouvement_refusees(self, checklist_game):
        """09.02/09.03 : la phase se termine quand toutes les unités ont été sélectionnées ; en
        phase de tir, aucune action de mouvement n'est plus acceptée."""
        game = checklist_game
        for unit_id in list(game.pool("move_activation_pool")):
            game.act("skip", unitId=unit_id)
        assert game.pool("move_activation_pool") == []
        if game.phase == "move":
            game.act("advance_phase")
        assert game.phase == "shoot"
        # `activate_unit` : verbe de la phase de mouvement, refusé lui aussi — il levait
        # `RuntimeError` (HTTP 500) là où les trois autres rendaient déjà le refus.
        for action, payload in (
            ("commit_move_plan", {"unitId": "1", "plan": [_placement(game, m) for m in game.models_of("1")]}),
            ("advance", {"unitId": "1"}),
            ("take_to_skies", {"unitId": "6"}),
            ("activate_unit", {"unitId": "1"}),
        ):
            accepted, body = game.try_act(action, **payload)
            assert not accepted, action
            assert body["result"]["error"] == "invalid_action_for_phase", (action, body["result"])
        assert not _in(game, "units_moved", "1") and not _in(game, "units_advanced", "1")
