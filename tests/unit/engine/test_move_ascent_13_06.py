"""13.06 — une escouade du pipeline gym peut FINIR SON MOVE EN HAUTEUR.

Avant ce lot, le move d'escouade atterrissait toujours au sol : `build_rigid_plan` écrivait
`SQUAD_RIGID_MOVE_DESTINATION_LEVEL` pour toutes ses figurines, et le pool d'ancre sortait avant
son bloc multi-niveaux. Mesuré alors sur 6 épisodes gym : 710 275 destinations, AUCUNE à l'étage.

Ce que ces tests verrouillent, dans l'ordre où ils importent :

  1. le CRITÈRE DE CLÔTURE — une escouade partie du sol finit à un niveau > 0 ET le masque
     proposait la cellule qui l'y envoie ;
  2. le RÉGIME PAR DÉFAUT — sans déclaration, rien ne monte, jamais : c'est ce qui rend le lot
     inoffensif pour tout ce qui existait ;
  3. le COÛT VERTICAL — 13.06 « add the distance moved vertically up ... to any other distance
     that model has moved » : une cellule dont le trajet + la montée dépasse le budget n'est PAS
     offerte. C'est l'invariant « masque ⊆ exécutable » sur la montée ;
  4. le JOURNAL — la figurine en hauteur sort avec sa hauteur dans `[MODELS:]` ;
  5. l'OBSERVATION — l'agent VOIT qu'il est en hauteur, sans quoi la montée serait un état caché.

Les tests jouent le VRAI moteur sur les scénarios d'entraînement (le seul terrain du dépôt qui
porte des étages) plutôt qu'un `game_state` fabriqué : c'est le pipeline complet
masque → décodeur → plan → validation → commit qui est en cause, et un état fabriqué prouverait
seulement que la fonction qu'on vient d'écrire fait ce qu'on vient d'écrire.
"""

import os
import random

import pytest

from tests.unit.engine._config_helpers import bank_training_scenarios


BOARD = "board/44x60x1"
MAX_STEPS = 400


@pytest.fixture()
def board_x1():
    """Plateau x1 — la résolution d'entraînement. Une figurine y tient dans UNE case."""
    previous = os.environ.get("W40K_BOARD_PATH")
    os.environ["W40K_BOARD_PATH"] = BOARD
    try:
        yield BOARD
    finally:
        if previous is None:
            os.environ.pop("W40K_BOARD_PATH", None)
        else:
            os.environ["W40K_BOARD_PATH"] = previous


def _engine(seed, scenario):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    engine = W40KEngine(
        rewards_config="ArmageddonAgent_x1",
        training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent_x1",
        scenario_file=scenario,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
        training_n_envs=1,
    )
    engine.reset(seed=seed)
    return engine


def _live_cell_map(engine):
    """`(squad_id, {cell_index: ((col,row), cout)})` de l'escouade dont la carte est CONSTRUITE
    à ce step, ou `None`.

    UN seul retour et non un couple d'`Optional` : les deux valeurs sont présentes ou absentes
    ENSEMBLE, et un couple obligerait chaque appelant à re-garder la seconde après avoir testé la
    première (ou à ne pas le faire, ce que le vérificateur de types signale).

    Même lecture que `test_move_mask_is_executable` : le dépôt `MOVE_CELL_MAP_CACHE_KEY` garde
    aussi des cartes périmées d'activations précédentes, et les valider reviendrait à juger un
    masque que personne n'a produit.
    """
    from engine.phase_handlers.shared_utils import MOVE_CELL_MAP_CACHE_KEY

    gs = engine.game_state
    if gs.get("phase") != "move":
        return None
    from tests.unit.engine.test_move_mask_is_executable import _live_map_squad

    squad_id = _live_map_squad(engine)
    if squad_id is None:
        return None
    stored = (gs.get(MOVE_CELL_MAP_CACHE_KEY) or {}).get(squad_id)
    cell_map = stored.get("map") if isinstance(stored, dict) else stored
    if not isinstance(cell_map, dict):
        return None
    return squad_id, cell_map


def _play_until_ascent(seed, scenario, *, declare=True, on_ascent_cell=None):
    """Déroule une partie en actions masquées, DÉCLARE (ou non) chaque montée proposée, et joue
    la première cellule dont le plan rigide porte un niveau > 0.

    Rend `(engine, squad_id, plan_avant, niveaux_apres)` ou `None` si aucune montée n'a été
    rencontrée. `on_ascent_cell` reçoit `(engine, squad_id, cell_map)` avant le coup joué, pour
    les tests qui inspectent le masque plutôt que le résultat.
    """
    from engine.macro_intents import CHOICE_BASE
    from engine.phase_handlers.shared_utils import build_rigid_plan

    engine = _engine(seed, scenario)
    rng = random.Random(seed)
    for _ in range(MAX_STEPS):
        mask = engine.get_action_mask()
        gs = engine.game_state
        pending = gs.get("pending_agent_decision")
        if pending is not None and str(pending.get("type")) == "ascent_declaration":
            # CHOICE_0 = monter, CHOICE_1 = rester au sol (ordre contractuel de
            # `arm_ascent_declaration_decision`).
            engine.step(CHOICE_BASE if declare else CHOICE_BASE + 1)
            continue

        live = _live_cell_map(engine)
        if live is not None:
            squad_id, cell_map = live
            if on_ascent_cell is not None:
                result = on_ascent_cell(engine, squad_id, cell_map)
                if result is not None:
                    return result
            for cell_idx, (cell, _cost) in cell_map.items():
                if not mask[cell_idx]:
                    continue
                plan = build_rigid_plan(cell[0], cell[1], squad_id, gs)
                if plan and any(int(entry[3]) > 0 for entry in plan):
                    asked = {entry[0]: int(entry[3]) for entry in plan}
                    engine.step(cell_idx)
                    written = {
                        mid: int(gs["models_cache"][mid]["level"])
                        for mid in asked
                        if mid in gs.get("models_cache", {})
                    }
                    return engine, squad_id, asked, written

        valid = [i for i in range(len(mask)) if mask[i]]
        if not valid:
            break
        _, _, terminated, truncated, _ = engine.step(rng.choice(valid))
        if terminated or truncated:
            break
    return None


# Les trois graines de la banque, comme les autres tests de move : une montée est un événement
# géométrique, donc c'est la variété des trajectoires qui la fait apparaître, pas la répétition.
SCENARIOS = bank_training_scenarios()
SEEDS = [(seed, SCENARIOS[seed % len(SCENARIOS)]) for seed in (0, 1, 2)]


def test_squad_ends_its_move_elevated_and_the_mask_offered_that_cell(board_x1):
    """CRITÈRE DE CLÔTURE — au moins une escouade part du sol et finit à un niveau > 0.

    Trois éléments sont vérifiés ensemble parce qu'ils ne valent que liés : la cellule était
    MASQUÉE (donc jouable), le plan la DEMANDAIT à l'étage, et le moteur l'y a ÉCRITE. Vérifier
    le seul niveau écrit laisserait passer une montée que le masque n'offrait pas — c'est-à-dire
    injouable pour l'agent.
    """
    outcome = None
    for seed, scenario in SEEDS:
        outcome = _play_until_ascent(seed, scenario, declare=True)
        if outcome is not None:
            break
    assert outcome is not None, (
        "aucune montée rencontrée sur 3 graines : soit le point de décision n'est plus armé, "
        "soit l'érosion retire toutes les cellules d'étage — dans les deux cas 13.06 est "
        "de nouveau hors de portée du pipeline gym."
    )
    engine, squad_id, asked, written = outcome
    elevated_asked = {mid: lv for mid, lv in asked.items() if lv > 0}
    assert elevated_asked, "le plan retenu ne demandait aucune figurine à l'étage"
    for mid, level in elevated_asked.items():
        assert written[mid] == level, (
            f"figurine {mid} : plan à l'étage {level}, niveau écrit {written[mid]} — "
            f"`place_model_at_effective_level` a ramené la figurine au sol, donc le masque "
            f"proposait une montée que le commit refuse."
        )


def test_without_the_declaration_no_model_ever_leaves_the_ground(board_x1):
    """RÉGIME PAR DÉFAUT — sans déclaration, tout le pipeline reste celui d'avant.

    C'est ce qui borne le lot : `squad_ascent_declared` faux, aucun plan ne porte de niveau,
    aucun champ multi-niveaux n'est construit. Une régression ici voudrait dire que la
    verticalité s'est invitée dans des parties qui ne l'ont pas demandée.
    """
    from engine.macro_intents import CHOICE_BASE
    from engine.phase_handlers.shared_utils import build_rigid_plan

    seed, scenario = SEEDS[0]
    engine = _engine(seed, scenario)
    rng = random.Random(seed)
    declined = 0
    for _ in range(MAX_STEPS):
        mask = engine.get_action_mask()
        gs = engine.game_state
        pending = gs.get("pending_agent_decision")
        if pending is not None and str(pending.get("type")) == "ascent_declaration":
            declined += 1
            engine.step(CHOICE_BASE + 1)  # « Stay on ground level »
            continue
        live = _live_cell_map(engine)
        if live is not None:
            squad_id, cell_map = live
            for cell_idx, (cell, _cost) in cell_map.items():
                plan = build_rigid_plan(cell[0], cell[1], squad_id, gs)
                if plan is None:
                    continue
                assert all(int(entry[3]) == 0 for entry in plan), (
                    f"escouade {squad_id} : plan à l'étage sans déclaration de montée — "
                    f"{[e for e in plan if int(e[3]) > 0]}"
                )
        for model in gs.get("models_cache", {}).values():
            assert int(model.get("level", 0)) == 0, (
                "une figurine est en hauteur alors qu'aucune montée n'a été déclarée"
            )
        valid = [i for i in range(len(mask)) if mask[i]]
        if not valid:
            break
        _, _, terminated, truncated, _ = engine.step(rng.choice(valid))
        if terminated or truncated:
            break
    assert declined > 0, "aucune déclaration de montée proposée : le test n'a rien exercé"


def test_the_climb_cost_is_charged_so_the_mask_stays_executable(board_x1):
    """13.06 — la distance verticale s'AJOUTE au trajet, donc le masque doit l'avoir payée.

    Le défaut que ce test verrouille est précis et a été observé : le pool d'ancre est construit
    AU SOL, donc son coût ignore la montée. Deux chemins le laissaient passer — le court-circuit
    mono-figurine (« le coût de pool borne déjà le trajet ») et la porte cube (« sans obstacle, le
    trajet EST le cube ») — et le masque offrait alors des cellules que `validate_move_plan`
    refuse en « hors budget ». Mesuré avant correction : escouade 103, cellules de coût 12 à 14
    pour un budget de 14, trajet réel = coût + 3 de montée.

    On vérifie donc que TOUTE cellule masquée dont le plan monte est exécutable au budget que le
    décodeur appliquerait — le même contrat que `test_move_mask_is_executable`, restreint aux
    plans qui montent pour que l'échec désigne la montée et rien d'autre.
    """
    from engine.macro_intents import CHOICE_BASE
    from engine.phase_handlers.shared_utils import (
        build_rigid_plan, explain_move_plan_rejection,
    )
    from tests.unit.engine.test_move_mask_is_executable import _budget_for

    checked = 0
    failures = []
    for seed, scenario in SEEDS:
        engine = _engine(seed, scenario)
        rng = random.Random(seed)
        for _ in range(MAX_STEPS):
            mask = engine.get_action_mask()
            gs = engine.game_state
            pending = gs.get("pending_agent_decision")
            if pending is not None and str(pending.get("type")) == "ascent_declaration":
                engine.step(CHOICE_BASE)
                continue
            live = _live_cell_map(engine)
            if live is not None:
                squad_id, cell_map = live
                for cell_idx, (cell, cost) in cell_map.items():
                    if not mask[cell_idx]:
                        continue
                    budget = _budget_for(gs, squad_id, cost)
                    if budget is None:
                        continue
                    plan = build_rigid_plan(cell[0], cell[1], squad_id, gs)
                    if not plan or all(int(entry[3]) == 0 for entry in plan):
                        continue
                    checked += 1
                    reason = explain_move_plan_rejection(
                        plan, gs, {"budget_per_model": budget}
                    )
                    if reason is not None:
                        failures.append((squad_id, cell, cost, budget, reason))
            valid = [i for i in range(len(mask)) if mask[i]]
            if not valid:
                break
            _, _, terminated, truncated, _ = engine.step(rng.choice(valid))
            if terminated or truncated:
                break
    assert checked > 0, "aucune cellule de montée offerte : le test n'a rien exercé"
    assert not failures, (
        f"{len(failures)}/{checked} cellules de MONTÉE offertes par le masque sont refusées par "
        f"la validation — le coût vertical de 13.06 n'est pas facturé du côté du masque. "
        f"3 premières : {failures[:3]}"
    )


def test_an_elevated_model_is_journaled_with_its_floor_height(board_x1):
    """Le journal porte la hauteur de la figurine montée.

    `[MODELS:]` journalise une HAUTEUR en pouces et non un niveau (cf. `format_models_segment`) :
    c'est la grandeur que compare le gate vertical de l'engagement, et le step.log ne porte aucun
    terrain qui permettrait de re-dériver une hauteur depuis un niveau. Ce test vérifie que la
    montée y arrive — sans lui, replay et analyzer raisonneraient à plat sur une partie qui ne
    l'est plus.
    """
    from engine.action_log_utils import models_segment_for_unit

    outcome = None
    for seed, scenario in SEEDS:
        outcome = _play_until_ascent(seed, scenario, declare=True)
        if outcome is not None:
            break
    assert outcome is not None, "aucune montée rencontrée : le test n'a rien exercé"
    engine, squad_id, _asked, written = outcome
    elevated = [mid for mid, lv in written.items() if lv > 0]
    assert elevated, "aucune figurine écrite à l'étage"
    segment = models_segment_for_unit(engine.game_state, squad_id)
    assert segment, f"segment [MODELS:] vide pour l'escouade {squad_id}"
    for mid in elevated:
        token = f"{mid}@("
        assert token in segment, f"figurine montée {mid} absente de {segment}"
        height = segment.split(token, 1)[1].split(")", 1)[0].split(",z")[1]
        assert float(height) > 0.0, (
            f"figurine {mid} journalisée à la hauteur {height} alors qu'elle est à l'étage "
            f"{written[mid]} — le journal décrit une partie à plat : {segment}"
        )


def test_the_agent_observes_that_its_models_are_elevated(board_x1):
    """L'agent VOIT la hauteur — sinon la montée serait un état caché.

    Trois canaux d'information, vérifiés ensemble parce qu'ils répondent à trois questions
    différentes : `elevated` dit QUELLE figurine est en haut, `max_floor_height` donne la hauteur
    de tir de l'unité (l'échelle est le seuil de Plunging Fire, 22.05), et le canal de grille
    `occupant_level` désambiguïse les plans d'occupation, qui peignent à plat.

    Sans eux, l'observation d'une escouade montée serait identique à celle de la même escouade
    restée au sol : le +1 BS de 22.05, la ligne de vue et le coût de descente du move suivant
    deviendraient des conséquences invisibles de son propre choix.
    """
    import numpy as np

    from engine.observation_entities import self_model_bin_index, unit_cont_index, unit_bin_index
    from engine.spatial_grid import GRID_CH_OCCUPANT_LEVEL

    outcome = None
    for seed, scenario in SEEDS:
        outcome = _play_until_ascent(seed, scenario, declare=True)
        if outcome is not None:
            break
    assert outcome is not None, "aucune montée rencontrée : le test n'a rien exercé"
    engine, squad_id, _asked, written = outcome
    elevated = {mid for mid, lv in written.items() if lv > 0}
    assert elevated, "aucune figurine écrite à l'étage"

    gs = engine.game_state
    # On sort de la phase de MOVE avant d'observer : le canal de coût de move relit la carte de
    # cellules mémoïsée par le masque (`read_squad_move_cell_map`), et cette carte est purgée à la
    # fin de l'activation qui vient d'avoir lieu. Hors move, le canal vaut 0 et l'observation se
    # construit sans elle. Les niveaux, eux, sont écrits dans `models_cache` : ils survivent.
    rng = random.Random(0)
    for _ in range(MAX_STEPS):
        if gs.get("phase") != "move":
            break
        mask = engine.get_action_mask()
        valid = [i for i in range(len(mask)) if mask[i]]
        if not valid:
            break
        _, _, terminated, truncated, _ = engine.step(rng.choice(valid))
        if terminated or truncated:
            break
    assert gs.get("phase") != "move", "la phase de move ne s'est pas terminée"
    still_elevated = {mid for mid in elevated if int(gs["models_cache"][mid]["level"]) > 0}
    assert still_elevated == elevated, (
        f"des figurines sont redescendues avant l'observation : {sorted(elevated - still_elevated)}"
    )
    obs = engine.obs_builder.build_squad_observation(gs, str(squad_id))
    # ORDRE OPPOSABLE : la ligne i du bloc figurines est celle de
    # `_squad_models_for_observation` (exceptions d'abord), pas celle de `squad_models`. Le test
    # relit CETTE source plutôt que de recopier le tri — le recopier ferait passer un test vert
    # sur une observation qui décrit une autre figurine que celle qu'on croit.
    raw_alive = [m for m in gs["squad_models"].get(squad_id, []) if m in gs["models_cache"]]
    active_unit = next(u for u in gs["units"] if str(u["id"]) == str(squad_id))
    alive = engine.obs_builder._squad_models_for_observation(
        raw_alive,
        gs["models_cache"],
        (
            int(active_unit["HP_MAX"]), int(active_unit["T"]),
            int(active_unit["ARMOR_SAVE"]), int(active_unit["INVUL_SAVE"]),
        ),
    )

    sm_bin = obs["self_models_bin"]
    idx_elevated = self_model_bin_index("elevated")
    observed = {
        alive[k] for k in range(min(len(alive), sm_bin.shape[0]))
        if sm_bin[k][idx_elevated] > 0.0
    }
    assert observed == elevated, (
        f"figurines vues en hauteur {sorted(observed)} != figurines réellement à l'étage "
        f"{sorted(elevated)}"
    )

    # LIGNE 0 de `allies_*` = l'unité ACTIVE (contrat déclaré au layout de l'observation).
    assert obs["allies_bin"][0][unit_bin_index("is_active")] > 0.0, (
        "la ligne 0 du tenseur allié n'est pas l'unité active : le layout a changé"
    )
    assert float(obs["allies_cont"][0][unit_cont_index("max_floor_height")]) > 0.0, (
        "hauteur maximale observée nulle alors qu'une figurine est à l'étage"
    )
    ground_left = any(int(gs["models_cache"][mid]["level"]) == 0 for mid in alive)
    assert bool(obs["allies_bin"][0][unit_bin_index("has_ground_model")] > 0.0) == ground_left, (
        "le bit `has_ground_model` ne décrit pas l'état réel de l'escouade — c'est le prédicat "
        "exact que Plunging Fire (22.05) interroge sur la cible"
    )

    grid = engine.obs_builder.build_squad_grid(gs, str(squad_id))
    assert float(np.max(grid[GRID_CH_OCCUPANT_LEVEL])) > 0.0, (
        "aucune cellule du canal `occupant_level` n'est peinte alors qu'une figurine est en "
        "hauteur : les canaux d'occupation restent à plat et annoncent bloquée une case dont "
        "le sol est libre"
    )


def _climb_subhex(game_state, model, col, row, level):
    """Coût vertical (sous-hexes) que paierait `model` en finissant en `(col, row, level)`.

    Recalculé ICI depuis `floor_height_at` plutôt qu'emprunté à la borne testée : un oracle qui
    appellerait la fonction sous test ne prouverait rien. La forme (hauteur d'arrivée moins
    hauteur de départ, convertie en sous-hexes) est celle de 13.06.
    """
    import math

    from engine.terrain_utils import floor_height_at

    terrain_areas = game_state.get("terrain_areas", [])  # get allowed (scénario sans terrain)
    inches_to_subhex = int(game_state["inches_to_subhex"])
    origin = floor_height_at(
        terrain_areas, int(model["col"]), int(model["row"]), int(model["level"])
    )
    return math.floor(
        max(0.0, floor_height_at(terrain_areas, col, row, int(level)) - origin) * inches_to_subhex
    )


def test_the_arming_bound_never_steals_a_legal_ascent(board_x1):
    """La borne d'armement écarte des questions stériles, jamais une montée que la règle autorise.

    `_squad_has_reachable_floor_cell` refuse de poser la question quand `distance + montée` dépasse
    le budget. C'est une condition NÉCESSAIRE — le trajet réel contourne murs et figurines, donc il
    est toujours >= la distance à vol d'oiseau — mais une erreur de signe, un maximum au lieu d'un
    minimum ou un arrondi au supérieur la rendraient trop serrée, et l'agent perdrait en silence
    un choix que 13.06 lui donne. C'est la seule façon dont ce resserrement peut nuire.

    La borne utilise désormais le budget Advance maximum (jet = 6) comme borne haute. Le contrôle
    porte sur les activations où la borne dit NON : pour chacune on vérifie contre un ORACLE
    INDÉPENDANT — le pool d'ancre du masque, en lecture seule, au même budget — qu'aucune cellule
    n'aurait pu poser une figurine sur un plancher. Le pool est un sur-ensemble de l'exécutable :
    s'il n'offre rien, rien n'était perdu.
    """
    from engine.combat_utils import calculate_hex_distance
    from engine.hex_utils import cube_to_offset, offset_to_cube
    from engine.phase_handlers.movement_handlers import (
        _squad_has_reachable_floor_cell,
        movement_build_valid_destinations_pool,
        squad_floor_level_map,
    )
    from engine.phase_handlers.shared_utils import get_squad_move_budget

    gates_fired = 0  # borne a dit OUI au moins une fois (test non-trivial)
    inspected = 0    # borne a dit NON → oracle vérifié
    stolen = []
    for seed, scenario in SEEDS:
        engine = _engine(seed, scenario)
        rng = random.Random(seed)
        for _ in range(MAX_STEPS):
            mask = engine.get_action_mask()
            gs = engine.game_state
            live = _live_cell_map(engine)
            if live is not None:
                squad_id, _cell_map = live
                alive = [m for m in gs["squad_models"].get(squad_id, []) if m in gs["models_cache"]]
                maps = {mid: squad_floor_level_map(gs, gs["models_cache"][mid]) for mid in alive}
                # Budget Advance max (jet=6) : même référence que la borne depuis la correction
                # F5 (section 3bis du masque tire le jet en section 4, trop tard pour la borne).
                budget = get_squad_move_budget(str(squad_id), gs, "advance", advance_roll=6)
                near = any(
                    calculate_hex_distance(
                        int(gs["models_cache"][mid]["col"]),
                        int(gs["models_cache"][mid]["row"]),
                        fcol, frow,
                    ) <= budget
                    for mid in alive for (fcol, frow) in maps[mid]
                )
                # On interroge LA BORNE et non `ascent_declaration_decision_is_due` : cette
                # dernière refuse aussi pour des raisons étrangères au resserrement — question
                # déjà posée ce tour, vol déclaré, mauvais joueur.
                reachable = _squad_has_reachable_floor_cell(gs, squad_id)
                if near and reachable:
                    gates_fired += 1
                if near and not reachable:
                    inspected += 1
                    costs = {}
                    # `read_only=True` : aucune écriture d'état, aucun cache de carte de cellules
                    # touché. Une sonde qui rejoue `roll_advance_for_squad` empoisonne au contraire
                    # le cache que le décodeur relit, et fait lever le moteur au step suivant.
                    movement_build_valid_destinations_pool(
                        gs, squad_id, read_only=True, move_budget_override=budget,
                        out_costs=costs, destination_level=0,
                    )
                    anchor = gs["models_cache"][alive[0]]
                    ax, ay, az = offset_to_cube(int(anchor["col"]), int(anchor["row"]))
                    for (ccol, crow), cost in costs.items():
                        bx, by, bz = offset_to_cube(ccol, crow)
                        delta = (bx - ax, by - ay, bz - az)
                        hit = None
                        for mid in alive:
                            m = gs["models_cache"][mid]
                            mx, my, mz = offset_to_cube(int(m["col"]), int(m["row"]))
                            ncol, nrow = cube_to_offset(
                                mx + delta[0], my + delta[1], mz + delta[2]
                            )
                            if (ncol, nrow) not in maps[mid]:
                                continue
                            # 13.06 : le coût de la cellule est HORIZONTAL. La montée s'y AJOUTE,
                            # donc une cellule du pool n'héberge une montée que si le total tient
                            # dans le budget. Sans ce terme, l'oracle déclare volée une montée qui
                            # n'a jamais été légale — mesuré, 82 faux positifs sur 87.
                            climb = _climb_subhex(gs, m, ncol, nrow, maps[mid][(ncol, nrow)])
                            if cost + climb <= budget:
                                hit = (mid, ncol, nrow, cost, climb)
                                break
                        if hit is not None:
                            stolen.append((squad_id, (ccol, crow), hit, budget))
                            break
            valid = [i for i in range(len(mask)) if mask[i]]
            if not valid:
                break
            _, _, terminated, truncated, _ = engine.step(rng.choice(valid))
            if terminated or truncated:
                break

    assert gates_fired > 0, (
        "la borne n'a jamais dit OUI sur un plancher proche : soit il n'y a aucun terrain en "
        "hauteur dans les scénarios SEEDS, soit la borne bloque tout — le test n'exerce rien"
    )
    # DEUX sentinelles, et la seconde est celle qui garde l'oracle. `stolen` ne se remplit que
    # dans la branche « la borne dit NON » : si elle ne s'exécute jamais, `assert not stolen`
    # passe sans avoir rien interrogé. `gates_fired` compte l'exact contraire (la borne dit OUI)
    # et ne dit donc rien de cette branche-là. Mesuré sur les SEEDS : 210 OUI, 37 NON.
    assert inspected > 0, (
        "la borne n'a jamais dit NON sur un plancher proche : l'oracle anti-vol n'a pas tourné "
        "une seule fois, et l'absence de vol constatée plus bas ne prouve rien"
    )
    assert not stolen, (
        f"{len(stolen)}/{inspected} activations où la question n'est PAS posée alors que le pool "
        f"(budget Advance max) offre une cellule posant une figurine sur un plancher — la borne "
        f"retire une montée légale. 3 premières : {stolen[:3]}"
    )


def test_a_squad_already_elevated_keeps_a_mask_that_stays_executable(board_x1):
    """« Masque ⊆ exécutable » vaut aussi au SECOND tour d'une montée, pas seulement au premier.

    Une figurine qui PART d'un étage et y RESTE ne monte pas : son niveau d'arrivée égale son
    niveau d'origine. Elle n'emprunte donc ni le champ de montée ni, comme au sol, le champ de
    plain-pied — elle chemine parmi les obstacles de SON étage, c'est-à-dire à l'intérieur du
    plancher, hors duquel il n'y a rien à fouler. `explain_move_plan_rejection` la borne bien
    ainsi (`model_reach_predicate` reçoit le niveau du plan) ; l'érosion du masque, elle, doit
    interroger le MÊME niveau, sans quoi elle offre le plateau entier à une figurine confinée à
    une ruine et le moteur lève à l'exécution.

    Le premier tour d'une montée ne montre rien de ce défaut : tout le monde part du sol. C'est
    la deuxième déclaration consécutive qui l'expose, et c'est ce que ce test met en scène.
    """
    from engine.macro_intents import CHOICE_BASE
    from engine.phase_handlers.shared_utils import (
        build_rigid_plan, explain_move_plan_rejection,
    )
    from tests.unit.engine.test_move_mask_is_executable import _budget_for

    checked = 0
    failures = []
    for seed, scenario in SEEDS:
        # La montée est jouée DÉLIBÉRÉMENT : sous actions aléatoires elle n'arrive que sur 0,8 %
        # des cellules, donc le cas « déjà en hauteur » ne se présenterait jamais et le test
        # serait vert à vide.
        outcome = _play_until_ascent(seed, scenario, declare=True)
        if outcome is None:
            continue
        engine = outcome[0]
        gs = engine.game_state
        rng = random.Random(seed)
        for _ in range(MAX_STEPS):
            mask = engine.get_action_mask()
            pending = gs.get("pending_agent_decision")
            if pending is not None and str(pending.get("type")) == "ascent_declaration":
                engine.step(CHOICE_BASE)
                continue
            live = _live_cell_map(engine)
            if live is not None:
                squad_id, cell_map = live
                alive = [m for m in gs["squad_models"].get(squad_id, []) if m in gs["models_cache"]]
                # Le cas visé : l'escouade active a DÉJÀ au moins une figurine en hauteur.
                if any(int(gs["models_cache"][mid]["level"]) > 0 for mid in alive):
                    for cell_idx, (cell, cost) in cell_map.items():
                        if not mask[cell_idx]:
                            continue
                        budget = _budget_for(gs, squad_id, cost)
                        if budget is None:
                            continue
                        plan = build_rigid_plan(cell[0], cell[1], squad_id, gs)
                        if plan is None:
                            continue
                        checked += 1
                        reason = explain_move_plan_rejection(
                            plan, gs, {"budget_per_model": budget}
                        )
                        if reason is not None:
                            failures.append((squad_id, cell, reason))
            valid = [i for i in range(len(mask)) if mask[i]]
            if not valid:
                break
            _, _, terminated, truncated, _ = engine.step(rng.choice(valid))
            if terminated or truncated:
                break

    assert checked > 0, (
        "aucune activation d'escouade déjà en hauteur : le test n'exerce rien. Sans elle il ne "
        "prouve pas que le second tour d'une montée reste exécutable."
    )
    assert not failures, (
        f"{len(failures)}/{checked} cellules offertes à une escouade DÉJÀ en hauteur sont refusées "
        f"par la validation — l'érosion et la validation ne bornent pas au même niveau. "
        f"3 premières : {failures[:3]}"
    )
