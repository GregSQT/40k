"""V11 §0.40 point 3 — l'observation décrit ce que CHAQUE slot de déploiement poserait.

**Le défaut fermé ici.** Les 5 actions du déploiement (4-8) ne sont pas « les 5 premiers hexes
valides » mais 5 STRATÉGIES (front agressif · pression sur objectif · sûr/cohésion · flanc
gauche · flanc droit) évaluées sur TOUS les hexes valides
(`ActionDecoder._select_deployment_hex_for_action`). L'observation n'en décrivait AUCUN : depuis
les points 1/2/4 l'agent sait où est sa zone et voit le terrain autour, mais la sémantique des
cinq slots restait à deviner — ni position, ni distance aux objectifs, ni couvert, ni exposition.

**Ce que ces verrous exigent, et pourquoi ils sont écrits ainsi.** La leçon de §0bis s'applique
directement : « un canal d'observation non vide ne prouve pas qu'il regarde au bon endroit — une
ancre fausse produit une grille plausible et fausse ». Un test qui vérifierait « le bloc candidat
contient des valeurs » serait donc SANS VALEUR. Chaque verrou ci-dessous affirme QUEL hexe un
slot décrit, en le comparant à ce que le décodeur choisirait pour ce slot — le CÂBLAGE, pas la
présence — ou recalcule la grandeur décrite depuis le `game_state` brut.

Le cas critique est celui des slots FERMÉS : le masque n'ouvre que `min(5, n_hexes)` slots, donc
en fin de déploiement il reste moins de 5 hexes valides et ce sont les stratégies d'INDICES BAS
qui survivent. Un slot fermé doit être décrit comme ABSENT (`present` = 0), jamais comme un
candidat plausible — d'où le test de parité obs ↔ masque, y compris sous troncature forcée.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from _config_helpers import assert_deployment_phase, pin_active_deployment
from engine.action_decoder import (
    DEPLOY_SLOT_CANDIDATES_CACHE_KEY,
    open_deploy_slot_count,
)
from engine.combat_utils import calculate_hex_distance
from engine.hex_utils import _hex_center
from engine.macro_intents import DEPLOY_SLOT_BASE, DEPLOY_SLOT_COUNT
from engine.observation_entities import (
    DEPLOY_CAND_BIN_FIELDS,
    N_DEPLOY_SLOTS,
    deploy_cand_bin_index,
    deploy_cand_cont_index,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCENARIO = (
    PROJECT_ROOT
    / "config" / "agents" / "ArmageddonAgent" / "scenarios" / "training"
    / "scenario_training_armageddon1.json"
)


def _load():
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent", training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent", scenario_file=str(SCENARIO),
        unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
    )
    # Déploiement ACTIF garanti. Lu par épisode → doit précéder le `reset`. Le scénario, la
    # graine et la géométrie sont inchangés : seul le tirage du MODE est forcé à la valeur que
    # ce fichier a toujours supposée. POURQUOI dans `_config_helpers.pin_active_deployment`.
    pin_active_deployment(eng)
    eng.reset(seed=0)
    assert_deployment_phase(eng)  # sinon ce fichier ne teste rien
    return eng


def _open_slots(mask) -> list[int]:
    return [a for a in range(DEPLOY_SLOT_BASE, DEPLOY_SLOT_BASE + DEPLOY_SLOT_COUNT) if mask[a]]


#: Borne de sécurité du pilotage : un déploiement réel tient en quelques dizaines de poses.
_MAX_DEPLOY_STEPS = 1000


def _deployment_steps(eng, *, limit: int | None = None):
    """Pilote le déploiement et rend `(step, mask, eligible)` AVANT chaque pose.

    Le pilotage était recopié dans chaque test — même boucle, même borne, même action jouée (le
    premier slot ouvert) — et deux copies avaient perdu l'assertion de fin, donc seraient restées
    vertes sur un déploiement bloqué. Ici la borne LÈVE au lieu de rendre la main : un test qui
    parcourt le déploiement ne peut plus s'arrêter à mi-chemin en silence.

    `limit` est un ÉCHANTILLONNAGE volontaire — les tests qui recalculent tout un bloc par slot
    n'ont pas besoin d'aller au bout — et lui seul autorise une sortie avant la fin.

    L'observation n'est PAS rendue : les tests qui pilotent seulement jusqu'à la fin ne doivent
    pas payer sa construction. Ceux qui la veulent appellent `eng._build_observation()` pendant
    le yield, donc avant la pose.
    """
    gs = eng.game_state
    dec = eng.action_decoder
    steps = 0
    while gs.get("phase") == "deployment":
        if limit is not None and steps >= limit:
            return
        assert steps < _MAX_DEPLOY_STEPS, (
            f"déploiement non terminé après {steps} steps (deadlock)"
        )
        mask, eligible = dec.get_squad_action_mask_and_eligible_units(gs)
        yield steps, mask, eligible
        eng.step(_open_slots(mask)[0])
        steps += 1


# ============================================================================
# CONTRAT DE CARDINALITÉ
# ============================================================================


def test_the_observation_describes_exactly_one_candidate_per_deployment_action():
    """`N_DEPLOY_SLOTS` DOIT valoir `DEPLOY_SLOT_COUNT` — invariant D1 appliqué au déploiement.

    `observation_entities` est un module FEUILLE : il recopie la constante au lieu de l'importer
    (comme `OBS_PHASE_IDS` / `GAME_PHASES`). Ce test est ce qui empêche les deux de dériver — une
    divergence ferait lire à l'agent la description d'un slot pour en jouer un autre.
    """
    assert N_DEPLOY_SLOTS == DEPLOY_SLOT_COUNT, (
        f"{N_DEPLOY_SLOTS} slots décrits par l'observation contre {DEPLOY_SLOT_COUNT} actions "
        f"de déploiement"
    )
    assert DEPLOY_CAND_BIN_FIELDS[-1] == "present", (
        "le masque `present` doit être le DERNIER champ du registre (convention §0.37) : "
        "l'extracteur le lit en `[..., -1]`"
    )


# ============================================================================
# CÂBLAGE — quel hexe chaque slot décrit
# ============================================================================


def test_each_open_slot_describes_the_hex_its_own_action_would_deploy():
    """Slot `i` décrit l'hexe que `_select_deployment_hex_for_action(4 + i)` choisirait.

    C'est LE verrou du point 3, et il porte sur le câblage : la position relative écrite dans
    l'observation est recomparée à la projection de l'hexe que le décodeur retiendrait pour CE
    slot, pas à « une valeur non nulle ». Le cache de candidats est purgé avant l'interrogation
    du décodeur, pour que celui-ci recalcule au lieu de relire ce que l'observation a écrit.
    """
    eng = _load()
    gs = eng.game_state
    dec = eng.action_decoder

    checked = 0
    for steps, mask, eligible in _deployment_steps(eng):
        uid = str(eligible[0]["id"])
        obs = eng._build_observation()
        anchor_col, anchor_row = eng.obs_builder.squad_grid_anchor(gs, uid)
        anchor_x, anchor_y = _hex_center(int(anchor_col), int(anchor_row))

        deployer = dec._get_current_deployer(gs)
        valid_hexes = dec._get_valid_deployment_hexes(gs, deployer, uid)

        # Purge : le décodeur doit RECALCULER son choix, sinon ce test comparerait le bloc
        # candidat à la mémo que `_build_observation()` vient elle-même de remplir. UNE fois par
        # step et non par slot : le cache porte la LISTE de candidats, commune aux cinq
        # stratégies et clée sur (unité, déployeur, snapshot) — le premier slot la recalcule donc
        # entièrement depuis le `game_state`, et les suivants relisent ce recalcul-là, pas la mémo
        # de l'observation. Purger par slot retriait les ~14 000 hexes de la zone cinq fois.
        gs.pop(DEPLOY_SLOT_CANDIDATES_CACHE_KEY, None)
        for action_int in _open_slots(mask):
            slot = action_int - DEPLOY_SLOT_BASE
            col, row = dec._select_deployment_hex_for_action(
                action_int, uid, gs, deployer, valid_hexes
            )
            hx, hy = _hex_center(int(col), int(row))
            assert obs["deploy_cand_cont"][slot, deploy_cand_cont_index("col_rel")] == pytest.approx(
                hx - anchor_x, abs=1e-3
            ), (
                f"step {steps}, slot {slot} : l'observation décrit une autre colonne que l'hexe "
                f"({col},{row}) que l'action {action_int} poserait"
            )
            assert obs["deploy_cand_cont"][slot, deploy_cand_cont_index("row_rel")] == pytest.approx(
                hy - anchor_y, abs=1e-3
            ), (
                f"step {steps}, slot {slot} : l'observation décrit une autre ligne que l'hexe "
                f"({col},{row}) que l'action {action_int} poserait"
            )
            checked += 1

    assert checked >= 20, f"trop peu de slots vérifiés ({checked})"


def test_candidate_positions_are_measured_from_the_zone_anchor_not_from_the_sentinel():
    """Contre-épreuve de la leçon §0bis : le repère est l'ancre de ZONE, pas la sentinelle.

    Une unité pas encore posée est à `(-1,-1)`. Mesurés depuis ce coin hors plateau, les
    candidats formeraient un bloc parfaitement plausible — et faux, exactement comme la grille
    du point 2 l'était. Le test exige donc que la valeur écrite DIFFÈRE de celle qu'aurait
    produite la sentinelle, sur un scénario où les deux origines sont bien distinctes.
    """
    eng = _load()
    gs = eng.game_state
    dec = eng.action_decoder

    mask, eligible = dec.get_squad_action_mask_and_eligible_units(gs)
    uid = str(eligible[0]["id"])
    obs = eng._build_observation()

    anchor_col, anchor_row = eng.obs_builder.squad_grid_anchor(gs, uid)
    assert (int(anchor_col), int(anchor_row)) != (-1, -1), (
        "l'ancre de zone vaut la sentinelle : ce test ne distinguerait rien"
    )
    anchor_x, anchor_y = _hex_center(int(anchor_col), int(anchor_row))
    sentinel_x, sentinel_y = _hex_center(-1, -1)

    deployer = dec._get_current_deployer(gs)
    candidates = dec.deployment_slot_candidates(gs, deployer, uid)
    assert candidates, "aucun slot ouvert au 1er step de déploiement"

    for action_int, candidate in candidates.items():
        slot = action_int - DEPLOY_SLOT_BASE
        col, row = candidate["hex"]
        hx, hy = _hex_center(int(col), int(row))
        written = float(obs["deploy_cand_cont"][slot, deploy_cand_cont_index("col_rel")])
        assert written == pytest.approx(hx - anchor_x, abs=1e-3)
        assert written != pytest.approx(hx - sentinel_x, abs=1e-3), (
            f"slot {slot} : la position du candidat est mesurée depuis la sentinelle (-1,-1), "
            f"pas depuis l'ancre de la zone de déploiement"
        )


def test_candidate_features_match_the_state_they_claim_to_describe():
    """Les grandeurs décrites sont recalculées depuis le `game_state` brut, pas relues du bloc.

    Distance au centre d'objectif le plus proche, appartenance à un hexe d'objectif (14.02) et
    bénéfice du couvert (13.08) sont réévalués ici sur l'hexe que le slot poserait. Un bloc qui
    porterait les grandeurs d'un AUTRE hexe (celui d'un autre slot, ou celui du step précédent)
    passerait tous les tests de « non-vacuité » et échouerait ici.
    """
    eng = _load()
    gs = eng.game_state
    dec = eng.action_decoder

    objective_centers = dec._get_objective_centers(gs)
    objective_hexes = {
        (int(h[0]), int(h[1])) if isinstance(h, (list, tuple))
        else (int(h["col"]), int(h["row"]))
        for objective in gs["objectives"] for h in objective["hexes"]
    }
    cover_hexes = {
        (int(h[0]), int(h[1]))
        for area in gs.get("terrain_areas", []) for h in area["hexes"]
    }

    checked = 0
    for steps, _mask, eligible in _deployment_steps(eng, limit=12):
        uid = str(eligible[0]["id"])
        obs = eng._build_observation()
        deployer = dec._get_current_deployer(gs)
        candidates = dec.deployment_slot_candidates(gs, deployer, uid)

        for action_int, candidate in candidates.items():
            slot = action_int - DEPLOY_SLOT_BASE
            col, row = candidate["hex"]
            expected_objective = min(
                calculate_hex_distance(col, row, cc, cr) for cc, cr in objective_centers
            )
            assert obs["deploy_cand_cont"][
                slot, deploy_cand_cont_index("objective_distance")
            ] == pytest.approx(float(expected_objective)), (
                f"step {steps}, slot {slot} : distance objectif décrite ≠ celle de l'hexe "
                f"({col},{row})"
            )
            assert bool(
                obs["deploy_cand_bin"][slot, deploy_cand_bin_index("on_objective")]
            ) is ((col, row) in objective_hexes), (
                f"step {steps}, slot {slot} : bit `on_objective` faux pour ({col},{row})"
            )
            assert bool(
                obs["deploy_cand_bin"][slot, deploy_cand_bin_index("in_cover")]
            ) is ((col, row) in cover_hexes), (
                f"step {steps}, slot {slot} : bit `in_cover` faux pour ({col},{row})"
            )
            checked += 1

    assert checked >= 20, f"trop peu de candidats vérifiés ({checked})"


def test_ally_distance_carries_its_own_mask():
    """`ally_distance` = 0 est ambigu sans `has_deployed_ally` : le bit doit suivre l'état réel.

    Aucun allié posé et « collé à un allié » produisent la MÊME valeur 0. Sans le masque, une
    stratégie de cohésion lirait la première situation comme la seconde.
    """
    eng = _load()
    gs = eng.game_state
    dec = eng.action_decoder

    seen_without = False
    seen_with = False
    for steps, mask, _eligible in _deployment_steps(eng):
        obs = eng._build_observation()
        deployer = dec._get_current_deployer(gs)
        allies_on_board = any(
            int(u["player"]) == int(deployer) and u["deployed_on_turn"] is not None
            for u in gs["units"]
        )
        for action_int in _open_slots(mask):
            slot = action_int - DEPLOY_SLOT_BASE
            bit = bool(obs["deploy_cand_bin"][slot, deploy_cand_bin_index("has_deployed_ally")])
            assert bit is allies_on_board, (
                f"step {steps}, slot {slot} : `has_deployed_ally`={bit} alors que le joueur "
                f"{deployer} a {'au moins un' if allies_on_board else 'aucun'} allié posé"
            )
        seen_without = seen_without or not allies_on_board
        seen_with = seen_with or allies_on_board

    assert seen_without and seen_with, (
        "le déploiement doit traverser les DEUX états (aucun allié posé, puis au moins un) — "
        "sinon ce test ne distingue rien"
    )


# ============================================================================
# PARITÉ OBS ↔ MASQUE — y compris avec moins de 5 hexes valides
# ============================================================================


def test_present_bits_are_exactly_the_slots_the_mask_opens():
    """Les slots décrits comme PRÉSENTS sont EXACTEMENT ceux que le masque ouvre."""
    eng = _load()

    for steps, mask, _eligible in _deployment_steps(eng):
        obs = eng._build_observation()
        present = {
            DEPLOY_SLOT_BASE + slot
            for slot in range(N_DEPLOY_SLOTS)
            if obs["deploy_cand_bin"][slot, deploy_cand_bin_index("present")] > 0
        }
        assert present == set(_open_slots(mask)), (
            f"step {steps} : l'observation déclare présents {sorted(present)} alors que le "
            f"masque ouvre {_open_slots(mask)}"
        )


def test_a_closed_slot_is_absent_not_a_plausible_candidate(monkeypatch):
    """Moins de 5 hexes valides : les slots fermés sont une LIGNE DE ZÉROS, `present` compris.

    Le cas ne se produit qu'en toute fin de déploiement (la zone fait ~14 000 hexes au 1er step),
    il est donc forcé ici en tronquant la liste d'hexes valides à la SOURCE — celle que le masque
    et le constructeur de candidats lisent tous les deux. C'est le cas où le lien slot ↔ stratégie
    cesse d'être stable : seules les stratégies d'indices bas survivent, et l'observation doit le
    dire au lieu de servir cinq candidats plausibles.
    """
    eng = _load()
    gs = eng.game_state
    dec = eng.action_decoder

    original = type(dec)._get_valid_deployment_hexes
    n_kept = 3

    def _truncated(self, game_state, current_deployer, unit_id):
        return original(self, game_state, current_deployer, unit_id)[:n_kept]

    monkeypatch.setattr(type(dec), "_get_valid_deployment_hexes", _truncated)
    gs.pop(DEPLOY_SLOT_CANDIDATES_CACHE_KEY, None)
    gs.pop("_deployment_scoring_cache", None)

    mask, _ = dec.get_squad_action_mask_and_eligible_units(gs)
    assert _open_slots(mask) == [DEPLOY_SLOT_BASE + i for i in range(n_kept)], (
        "le masque doit n'ouvrir que les n_kept premiers slots"
    )
    assert open_deploy_slot_count(n_kept) == n_kept

    obs = eng._build_observation()
    for slot in range(n_kept):
        assert obs["deploy_cand_bin"][slot, deploy_cand_bin_index("present")] == 1.0
    for slot in range(n_kept, N_DEPLOY_SLOTS):
        assert not obs["deploy_cand_bin"][slot].any(), (
            f"slot {slot} FERMÉ mais décrit par des drapeaux non nuls"
        )
        assert not obs["deploy_cand_cont"][slot].any(), (
            f"slot {slot} FERMÉ mais décrit par des grandeurs non nulles — un candidat "
            f"plausible pour une action que le masque interdit"
        )


# ============================================================================
# GARDE DE PHASE
# ============================================================================


def test_the_block_is_null_outside_the_deployment_phase():
    """Hors déploiement, le bloc entier est NUL — et son calcul n'est pas payé.

    Même patron que `is_charge_phase` pour `charge_reachable_max_roll` : la question n'a pas de
    sens hors de la phase qui l'ouvre, et le calcul (un tri par stratégie sur toute la zone, plus
    une formation validée par slot) ne doit pas grever chaque step de la partie.
    """
    eng = _load()
    gs = eng.game_state

    for _steps, _mask, _eligible in _deployment_steps(eng):
        pass

    for sid in list(gs["units_cache"].keys())[:4]:
        obs = eng.obs_builder.build_squad_observation(gs, str(sid))
        assert not obs["deploy_cand_cont"].any(), (
            f"phase {gs['phase']} : le bloc candidat de déploiement porte des valeurs"
        )
        assert not obs["deploy_cand_bin"].any(), (
            f"phase {gs['phase']} : le bloc candidat de déploiement porte des drapeaux"
        )


def test_an_already_placed_squad_never_queries_the_deployment_decoder(monkeypatch):
    """Une escouade DÉJÀ POSÉE n'a aucun candidat — et le décodeur n'est même pas interrogé.

    Ce n'est pas une précaution : par la règle, une unité sur le champ de bataille ne choisit pas
    où se déployer. La garde lit `deployed_on_turn`, la MÊME source que le bit
    `deploy_not_on_board`.

    Le verrou porte sur l'ABSENCE D'APPEL, pas sur le bloc vide : le bloc serait vide de toute
    façon (l'unité n'est pas celle du masque), donc l'assertion « bloc nul » ne distinguerait
    rien. Ce que la garde évite, c'est d'aller demander au décodeur l'état du déploiement pour une
    escouade que la question ne concerne pas — ce qui LÈVE sur un `game_state` dont la phase vaut
    « deployment » sans que personne n'ait à se déployer (cas rencontré par
    `test_squad_obs_geometry_phase_presence.py`, qui injecte les 6 phases à la main).
    """
    eng = _load()
    gs = eng.game_state
    dec = eng.action_decoder

    mask, _ = dec.get_squad_action_mask_and_eligible_units(gs)
    eng.step(_open_slots(mask)[0])
    assert gs.get("phase") == "deployment", "le déploiement doit continuer après la 1re pose"

    placed = [
        str(u["id"]) for u in gs["units"]
        if u["deployed_on_turn"] is not None and str(u["id"]) in gs["units_cache"]
    ]
    assert placed, "aucune escouade posée après un step de déploiement"

    # C'est `get_deployment_active_unit` qu'il faut espionner : c'est le PREMIER appel au
    # décodeur, celui qui lit `deployment_state` — donc celui qui lève quand cet état n'existe
    # pas. Espionner `deployment_slot_candidates` ne distinguerait rien : on y renonce de toute
    # façon plus loin, une fois l'unité active connue.
    queried: list[str] = []
    original = type(dec).get_deployment_active_unit

    def _spy(self, game_state):
        unit = original(self, game_state)
        queried.append(str(unit["id"]))
        return unit

    monkeypatch.setattr(type(dec), "get_deployment_active_unit", _spy)

    obs = eng.obs_builder.build_squad_observation(gs, placed[0])
    assert queried == [], (
        f"l'escouade {placed[0]} est déjà sur le plateau : observer son cas ne doit RIEN demander "
        f"au décodeur de déploiement (appels constatés : {queried})"
    )
    assert not obs["deploy_cand_bin"].any()
    assert not obs["deploy_cand_cont"].any()

    # Contre-contrôle : l'escouade que le masque déploie, elle, interroge bien le décodeur —
    # sinon ce test passerait aussi avec un bloc désactivé partout.
    _, eligible = dec.get_squad_action_mask_and_eligible_units(gs)
    active = str(eligible[0]["id"])
    eng.obs_builder.build_squad_observation(gs, active)
    assert queried == [active], (
        f"l'escouade active {active} doit interroger le décodeur (appels : {queried})"
    )


def test_a_squad_the_mask_does_not_act_on_gets_no_candidates():
    """Pendant le déploiement, seule l'unité du masque est décrite avec ses candidats.

    Décrire à une AUTRE escouade cinq candidats qu'aucune de ses actions ne pose serait le
    défaut du point 1 (obs décrivant A pendant que le masque agit sur B) rejoué une couche plus
    loin, sur le bloc le plus directement lié à l'action.
    """
    eng = _load()
    gs = eng.game_state
    dec = eng.action_decoder

    _, eligible = dec.get_squad_action_mask_and_eligible_units(gs)
    active = str(eligible[0]["id"])
    other = next(sid for sid in gs["units_cache"] if str(sid) != active)

    obs_other = eng.obs_builder.build_squad_observation(gs, str(other))
    assert not obs_other["deploy_cand_bin"].any(), (
        f"l'escouade {other} n'est pas celle que le masque déploie ({active}) : elle ne doit "
        f"porter aucun candidat"
    )
    obs_active = eng.obs_builder.build_squad_observation(gs, active)
    assert obs_active["deploy_cand_bin"][..., deploy_cand_bin_index("present")].any(), (
        "l'escouade active, elle, doit porter ses candidats"
    )


# ============================================================================
# SOURCE UNIQUE — la géométrie vectorisée EST celle du moteur
# ============================================================================


def test_the_vectorised_hex_distance_is_the_engine_one():
    """`_nearest_hex_distance_vec` rend EXACTEMENT `calculate_hex_distance`, minimum sur les refs.

    Le tri des 5 stratégies porte sur ces distances : une approximation vectorielle (parité de
    colonne oubliée, arrondi) ferait choisir au décodeur un autre hexe que celui que la version
    scalaire retenait — et l'observation décrirait fidèlement un mauvais choix.
    """
    from engine.action_decoder import ActionDecoder

    rng = np.random.default_rng(20260729)
    cols = rng.integers(0, 220, size=500).astype(np.int64)
    rows = rng.integers(0, 300, size=500).astype(np.int64)
    refs = [(int(c), int(r)) for c, r in zip(rng.integers(0, 220, 7), rng.integers(0, 300, 7))]

    vectorised = ActionDecoder._nearest_hex_distance_vec(cols, rows, refs)
    for i in range(len(cols)):
        expected = min(
            calculate_hex_distance(int(cols[i]), int(rows[i]), rc, rr) for rc, rr in refs
        )
        assert int(vectorised[i]) == expected, (
            f"hex ({cols[i]},{rows[i]}) : vectorisé {vectorised[i]} ≠ moteur {expected}"
        )

    with pytest.raises(ValueError, match="Reference hex list cannot be empty"):
        ActionDecoder._nearest_hex_distance_vec(cols, rows, [])


# ============================================================================
# CHEMIN DE PRODUCTION — le routage de la tête de déploiement (V11 §0.44, L1)
# ============================================================================


def test_the_real_deployment_observation_raises_the_routing_flag():
    """Le bit qui bascule les ids 4-11 vers la tête de pose est POSÉ par le vrai moteur.

    Les tests de la tête (`tests/unit/ai/test_pointer_head.py`) construisent l'observation à la
    main : ils prouvent le routage, pas que la production l'atteint. Ici on lit le drapeau à
    l'index que l'extracteur PUBLIE, sur une observation issue d'un vrai épisode — en phase de
    déploiement il vaut 1, et il retombe à 0 dès qu'on en sort (sans quoi l'agent scorerait des
    candidats nuls à la place de cellules de move parfaitement jouables).
    """
    import gymnasium as gym
    import torch

    from ai.spatial_extractor import SpatialCombinedExtractor
    from engine.observation_builder import ObservationBuilder
    from engine.spatial_grid import GRID_CHANNELS, GRID_SIZE

    spaces: dict[str, gym.spaces.Space] = {
        key: gym.spaces.Box(low=-np.inf, high=np.inf, shape=shape, dtype=np.float32)
        for key, shape in ObservationBuilder.squad_obs_shapes().items()
    }
    spaces["grid"] = gym.spaces.Box(
        low=0.0, high=1.0, shape=(GRID_CHANNELS, GRID_SIZE, GRID_SIZE), dtype=np.float32
    )
    extractor = SpatialCombinedExtractor(gym.spaces.Dict(spaces), cnn_features=8)
    extractor.eval()
    index = extractor.deployment_phase_flag_index()

    def _flag(observation) -> float:
        batched = {
            key: torch.as_tensor(value, dtype=torch.float32).unsqueeze(0)
            for key, value in observation.items()
        }
        with torch.no_grad():
            return float(extractor(batched)[0, index])

    eng = _load()
    gs = eng.game_state
    assert _flag(eng._build_observation()) == 1.0, (
        "phase de déploiement réelle : le drapeau de routage est à 0, les slots 4-11 seraient "
        "scorés par la conv des cellules de move"
    )

    for _steps, _mask, _eligible in _deployment_steps(eng):
        pass
    assert _flag(eng._build_observation()) == 0.0, (
        f"phase {gs.get('phase')} : le drapeau de routage est resté à 1"
    )
