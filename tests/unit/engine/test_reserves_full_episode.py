"""Critere de sortie du chantier « reserves : tous les chemins hors table ».

Le defaut de classe : une unite HORS TABLE (en attente de deploiement, ou en reserves 20.01) est
VIVANTE, presente dans `units_cache`, a la sentinelle (-1,-1), avec `occupied_hexes` VIDE. Tout
filtre ecrit sur « vivante » la laisse donc passer, et la geometrie se mesure alors depuis le
neant. Deux formes, selon le chemin :

- via `occupied_hexes` (vide) -> `min_distance_between_sets` LEVE (« empty sets ») ;
- via `occupied_hexes_by_model` (PLEINE, de sentinelles) -> le chemin 3D reconstruit une empreinte
  REELLE hors plateau (`compute_occupied_hexes(-1, -1, 'round', 32, 0)` rend 691 cases) et rend un
  verdict FAUX, en silence. C'est la forme la plus dangereuse, et celle qui a survecu au
  chantier 04.

`_require_measurable_entry` (spatial_relations) refuse desormais les deux : une entree hors table
ne se mesure pas, exactement comme une escouade detruite encore dans le cache. Ce fichier verifie
que plus AUCUN chemin d'un episode reel ne l'atteint.

VERT VACANT — ce test ne prouverait rien si l'episode ne produisait jamais d'unite hors table, ou
s'il s'arretait au deploiement. Les deux sont donc verifies explicitement : `test_the_fixture_
really_puts_units_off_the_battlefield` construit le constat, et la boucle d'episode exige d'avoir
depasse la phase de deploiement.
"""
from __future__ import annotations

import sys

from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
# Rosters a reserves DECLAREES des deux cotes (agent ET adversaire) — cf. l'en-tete de la fixture.
from tests.unit.engine._config_helpers import both_terrains

SCENARIO = (
    PROJECT_ROOT / "config" / "agents" / "ArmageddonAgent" / "scenarios" / "training"
    / "reserves_full_episode_fixture1.json"
)

# Ce fichier est REJOUÉ SUR LES DEUX TERRAINS : ce qu'il vérifie dépend des murs, des zones de
# déploiement ou des pièces d'objectif, et ces trois-là changent entièrement entre `terrain-mc1`
# et `terrain-mc2`. La fixture réécrit `SCENARIO` le temps de chaque test (cf. `both_terrains`).
_terrain = both_terrains(sys.modules[__name__])


SENTINEL_COL = -1
# 0-3 : echantillon de base. 16 et 18 elargissent la couverture de trajectoires (leurs parties se
# terminent sans phase de charge, cf. `test_the_seed_sample_really_exercises_the_measuring_phases`
# qui verifie la couverture sur l'UNION et non graine par graine).
SEEDS = (0, 1, 2, 3, 16, 18)


def _engine(seed: int):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent", training_config_name="x5_debug",
        controlled_agent="ArmageddonAgent", scenario_file=str(SCENARIO),
        unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
    )
    # Le scheduler par-episode peut rejouer le scenario en placement 'fixed' : ce test exige le
    # deploiement ACTIF, seul mode ou les unites transitent par la sentinelle avant d'etre posees.
    assert eng.training_config is not None
    sched = eng.training_config.get("deployment_mode_schedule")
    if isinstance(sched, dict):
        sched["enabled"] = False
    eng.reset(seed=seed)
    return eng


def _off_table_sids(gs: Dict[str, Any]) -> List[str]:
    return [
        str(sid) for sid, e in gs["units_cache"].items()
        if int(e["col"]) == SENTINEL_COL
    ]


def _play_episode(eng, max_steps: int = 4000, seed: int = 0) -> Dict[str, Any]:
    """Joue jusqu'a la fin. Rend un constat de COUVERTURE, pas seulement « ca n'a pas leve ».

    L'action est TIREE parmi les legales, pas prise en `legal[0]`. Avec `legal[0]`, une graine =
    UNE trajectoire, toujours la meme famille d'action en tete de masque : l'episode s'arretait de
    fait avant les sous-phases de combat, et le fichier certifiait un critere de sortie qu'il
    n'exercait pas. Les phases reellement traversees sont donc rendues a l'appelant, qui les
    EXIGE — sans quoi « aucune levee » ne veut rien dire.
    """
    import random

    rng = random.Random(seed)
    gs = eng.game_state
    max_off = len(_off_table_sids(gs))
    phases_seen: set = set()
    steps = 0
    while steps < max_steps:
        mask = eng.get_action_mask()
        legal = [i for i, ok in enumerate(mask) if ok]
        if not legal:
            break
        phases_seen.add(str(gs.get("phase")))
        _obs, _r, terminated, truncated, _info = eng.step(int(rng.choice(legal)))
        steps += 1
        max_off = max(max_off, len(_off_table_sids(gs)))
        if terminated or truncated:
            break
    phases_seen.add(str(gs.get("phase")))
    return {"steps": steps, "max_off": max_off, "phases": phases_seen}


@pytest.mark.parametrize("seed", SEEDS)
def test_the_fixture_really_puts_units_off_the_battlefield(seed: int) -> None:
    """VERT VACANT : sans unite hors table au reset, tout le reste du fichier serait creux."""
    eng = _engine(seed)
    off = _off_table_sids(eng.game_state)
    assert off, (
        "aucune unite hors table au reset : la fixture ne construit pas le cas, les tests "
        "d'episode ci-dessous ne prouveraient rien"
    )
    # Les DEUX joueurs doivent etre concernes — le chantier exige le cote agent ET l'adversaire.
    players = {int(eng.game_state["units_cache"][sid]["player"]) for sid in off}
    assert players == {1, 2}, (
        f"unites hors table sur les seuls joueurs {sorted(players)} : le cas adversaire ou le cas "
        "agent n'est pas construit"
    )


@pytest.mark.parametrize("seed", SEEDS)
def test_a_reserves_roster_survives_a_whole_episode(seed: int) -> None:
    """Le critere de sortie : aucun chemin ne mesure une geometrie depuis la sentinelle.

    Toute levee de `_require_measurable_entry` remonte ici telle quelle — c'est VOULU. Ce test ne
    capture pas l'exception pour la traduire : le message nomme l'escouade et le site fautif, et
    c'est exactement le diagnostic qu'on veut lire quand il casse.
    """
    eng = _engine(seed)
    run = _play_episode(eng, seed=seed)
    assert run["steps"] > 0, "l'episode n'a joue aucun step : masque vide des le reset"
    assert run["max_off"] > 0, "aucune unite hors table pendant l'episode : test creux"
    # Par graine, la seule exigence tenable est d'avoir QUITTE le deploiement : au-dela, les phases
    # atteintes dependent de la partie. Une trajectoire ou toutes les unites finissent engagees ne
    # verra jamais de phase de charge, et c'est une partie valide, pas un test casse — exiger les
    # quatre phases de CHAQUE graine faisait echouer 16 et 18 pour cette raison.
    # La couverture des quatre phases est verifiee sur l'ECHANTILLON, cf. le test suivant.
    assert run["phases"] - {"deployment"}, (
        f"l'episode n'a jamais quitte le deploiement en {run['steps']} steps : aucune phase de "
        "mesure geometrique n'est exercee"
    )


def test_the_seed_sample_really_exercises_the_measuring_phases() -> None:
    """VERT VACANT du fichier entier : « aucune levee » ne vaut que si les phases qui MESURENT
    une geometrie sont reellement traversees quelque part dans l'echantillon.

    Verifie sur l'UNION des graines, pas graine par graine (cf. le test precedent). Si cette
    assertion tombe, ce n'est pas un bug moteur : c'est que l'echantillon de graines a cesse de
    couvrir le critere de sortie du chantier, et le reste du fichier ne prouve plus grand-chose.
    """
    seen: set = set()
    for seed in SEEDS:
        seen |= _play_episode(_engine(seed), seed=seed)["phases"]
    missing = {"move", "shoot", "charge", "fight"} - seen
    assert not missing, (
        f"phases jamais atteintes sur les graines {SEEDS} : {sorted(missing)} — le critere de "
        f"sortie n'est pas exerce (vues : {sorted(seen)})"
    )


def test_the_two_faces_of_off_table_agree_across_episodes() -> None:
    """`col >= 0` (units_cache) et `deployed_on_turn is not None` (unit) sont le MEME etat.

    `entry_is_on_battlefield` et `unit_is_on_battlefield` se declarent « jumelles exactes » : la
    premiere lit le cache, la seconde l'unite. Trois ecrivains posent cet etat — `_apply_deploy_
    plan` (arrivee), `reposition_unit_to_strategic_reserves` (20.02, retrait), et le reset du
    moteur pour le deploiement ACTIF. Le troisieme ne remettait QUE la position : les objets
    `unit` survivant d'un episode a l'autre, l'episode 2 demarrait avec 10 unites sur 10 a col=-1
    et `deployed_on_turn=0` herite de l'episode 1 (mesure). L'observation batit son
    `on_battlefield` sur ce champ — elle declarait donc « posees » des escouades a la sentinelle,
    et [HEAVY] 24.16 lit le meme champ.

    Ce verrou est INDEPENDANT de `_require_measurable_entry` : la garde de mesure faisait lever le
    cas, mais elle pourrait etre relachee un jour, et la fuite reviendrait alors en silence.
    """
    eng = _engine(seed=0)

    def _diverging() -> List[str]:
        gs = eng.game_state
        return [
            f"{sid}: col={int(e['col'])} deployed_on_turn="
            f"{gs['unit_by_id'][str(sid)].get('deployed_on_turn')!r}"
            for sid, e in gs["units_cache"].items()
            if (int(e["col"]) >= 0)
            is not (gs["unit_by_id"][str(sid)].get("deployed_on_turn") is not None)
        ]

    assert not _diverging(), f"divergence des le 1er reset : {_diverging()}"
    run = _play_episode(eng, max_steps=400, seed=0)
    assert "move" in run["phases"], "l'episode n'a pas quitte le deploiement : le 2e reset ne prouverait rien"
    assert not _diverging(), f"divergence en fin d'episode 1 : {_diverging()}"

    eng.reset(seed=1)
    assert not _diverging(), (
        f"le reset du 2e episode remet la sentinelle sans remettre `deployed_on_turn` : "
        f"{_diverging()}"
    )


def test_a_reserves_roster_is_still_a_reserves_roster_on_the_second_episode() -> None:
    """La declaration de reserves du roster (20.01) doit survivre au reset.

    Les objets `unit` sont REUTILISES d'un episode a l'autre (mesure : 10/10). Une unite declaree
    en reserves arrive pendant l'episode 1, ce qui met `in_strategic_reserves` a False — c'est
    correct pendant l'episode (`_apply_deploy_plan` : « une fois posee, elle est arrivee »). Mais
    rien ne la restaurait au reset : l'episode 2 repartait sans reserve, et un roster
    `strategic_reserves: true` ne se comportait comme tel qu'au PREMIER episode de chaque worker.
    En entrainement, cela rend la fonctionnalite inerte sans qu'aucun test ne le voie.

    Ce verrou est INDEPENDANT de `_require_measurable_entry` : la fuite ne LEVE pas, elle rend
    silencieusement un roster ordinaire.
    """
    import random

    eng = _engine(seed=0)
    declared = {
        str(u["id"]) for u in eng.game_state["units"]
        if u.get("in_strategic_reserves")
    }
    assert declared, (
        "la fixture ne declare aucune reserve : ce verrou serait creux (verifier "
        "`strategic_reserves` dans les rosters referencees)"
    )

    rng = random.Random(0)
    arrived = False
    for _ in range(2000):
        mask = eng.get_action_mask()
        legal = [i for i, ok in enumerate(mask) if ok]
        if not legal:
            break
        _o, _r, term, trunc, _i = eng.step(int(rng.choice(legal)))
        if not any(
            u.get("in_strategic_reserves") for u in eng.game_state["units"]
            if str(u["id"]) in declared
        ):
            arrived = True
        if term or trunc:
            break
    assert arrived, (
        "aucune reserve n'est arrivee pendant l'episode 1 : le drapeau n'a jamais ete mute, "
        "donc le reset n'a rien a restaurer et ce verrou ne prouverait rien"
    )

    eng.reset(seed=1)
    still = {
        str(u["id"]) for u in eng.game_state["units"]
        if u.get("in_strategic_reserves")
    }
    assert still == declared, (
        f"la declaration de reserves du roster n'a pas survecu au reset : attendu {sorted(declared)}, "
        f"obtenu {sorted(still)}"
    )


def test_an_off_table_unit_is_never_a_declarable_charge_target() -> None:
    """Parite masque/commit sur la charge (11.02), le cas ou la mesure fausse ne LEVE pas.

    `charge_check_eligibility` est la source UNIQUE que le masque interroge pour ouvrir un slot de
    charge ET que le commit `squad_charge` re-verifie. Son test des 12" est une distance de GRILLE
    brute sur `_squad_model_positions`, qui rend la sentinelle (-1,-1) pour une unite hors table :
    tout chargeur assez proche de l'origine du plateau se retrouvait « a portee » d'une unite en
    reserves. Le masque ouvrait le slot, `charge_build_valid_plan` refusait ensuite, et
    l'activation partait en `charge_fail` — divergence masque/execution, pas simple mesure fausse.

    CAS CONSTRUIT, pas espere d'une trajectoire : le chargeur est AMENE pres de l'origine, sinon
    la distance depasse 12" pour une autre raison et le test passerait sans rien prouver. Les deux
    conditions du vert vacant sont donc verifiees avant l'assertion.
    """
    import random

    from engine.phase_handlers.movement_handlers import (
        reposition_unit_to_strategic_reserves,
    )
    from engine.phase_handlers.shared_utils import (
        charge_check_eligibility,
        update_model_position,
    )

    eng = _engine(seed=0)
    gs = eng.game_state

    # Sortir du deploiement : il faut des unites POSEES pour construire le cas.
    rng = random.Random(0)
    steps = 0
    while gs.get("phase") == "deployment" and steps < 500:
        mask = eng.get_action_mask()
        legal = [i for i, ok in enumerate(mask) if ok]
        if not legal:
            break
        eng.step(int(rng.choice(legal)))
        steps += 1
    assert gs.get("phase") != "deployment", "deploiement non termine : cas non construit"

    on_table = [sid for sid, e in gs["units_cache"].items() if int(e["col"]) >= 0]
    assert len(on_table) >= 2, "moins de deux unites posees : cas non construit"
    charger = on_table[0]
    charger_player = int(gs["units_cache"][charger]["player"])
    victim = next(
        (sid for sid in on_table if int(gs["units_cache"][sid]["player"]) != charger_player),
        None,
    )
    assert victim is not None, "aucun ennemi pose : cas non construit"

    # Le chargeur est AMENE pres de l'origine — c'est la que la sentinelle (-1,-1) tombe a moins
    # de 12". Ailleurs sur le plateau, le test des 12" echouerait pour une raison sans rapport et
    # ce verrou serait vert a vide.
    #
    # Le deplacement passe par `update_model_position` et SANS `build_units_cache` : apres un
    # deploiement ACTIF, `unit["models"]` n'est pas synchronise avec `models_cache` (mesure : le
    # rebuild leve « anchor ne correspond pas a models[0] » sur une unite tierce). Ce n'est pas un
    # contournement — `charge_check_eligibility` lit `models_cache` (`_squad_model_positions`) et
    # `units_cache`, jamais `unit["models"]` : l'etat construit ici est exactement celui qu'elle
    # consulte.
    # Les ennemis POSES partent au coin oppose AVANT le rapprochement du chargeur : sans cela
    # `_squad_is_in_enemy_er` (dernier controle de la fonction) repond True et court-circuite le
    # verdict — le test serait vert pour une raison sans rapport avec le filtre hors-table.
    # Mesure a l'appui : la version precedente de ce test avait `in_range=True` (le faux positif
    # etait bien construit) mais sortait sur `in_enemy_er=True`.
    far_col = int(gs["board_cols"]) - 1
    far_row = int(gs["board_rows"]) - 1
    for sid in on_table:
        if sid == charger or int(gs["units_cache"][sid]["player"]) == charger_player:
            continue
        for offset, mid in enumerate(gs["squad_models"][sid]):
            if mid in gs["models_cache"]:
                update_model_position(gs, mid, far_col - (offset % 3), far_row - (offset // 3))

    for offset, mid in enumerate(gs["squad_models"][charger]):
        if mid in gs["models_cache"]:
            update_model_position(gs, mid, offset % 3, offset // 3)

    # La victime part en reserves (20.02) : elle devient VIVANTE mais hors table.
    reposition_unit_to_strategic_reserves(gs, str(victim))
    assert int(gs["units_cache"][victim]["col"]) == SENTINEL_COL, "victime pas hors table"

    # VERT VACANT : sans cette borne, l'assertion finale pourrait tenir parce que le chargeur est
    # trop loin, et non parce que le filtre hors-table mord.
    from engine.phase_handlers.shared_utils import CHARGE_THRESHOLD_INCHES

    ish = int(gs["inches_to_subhex"])
    charger_cells = [
        (int(gs["models_cache"][m]["col"]), int(gs["models_cache"][m]["row"]))
        for m in gs["squad_models"][charger] if m in gs["models_cache"]
    ]
    closest = min(abs(c) + abs(r) for c, r in charger_cells)
    assert closest <= CHARGE_THRESHOLD_INCHES * ish, (
        f"le chargeur est a {closest} de l'origine, au-dela des 12\" ({CHARGE_THRESHOLD_INCHES * ish}) : "
        "la sentinelle ne serait pas 'a portee' meme sans filtre, le verrou serait vacant"
    )
    # 2e borne du vert vacant : le chargeur ne doit pas etre « locked » (dernier controle de
    # `charge_check_eligibility`), sinon elle repondrait False sans jamais atteindre le filtre.
    from engine.phase_handlers.shared_utils import _squad_is_in_enemy_er

    assert not _squad_is_in_enemy_er(gs, str(charger)), (
        "le chargeur est dans l'ER d'un ennemi : `charge_check_eligibility` sortirait sur ce "
        "controle-la et le verrou ne prouverait rien du filtre hors-table"
    )
    # 3e borne : une cible POSEE et a portee doit, elle, rester declarable — sinon l'assertion
    # finale passerait sur une fonction qui refuse tout.
    control = next(
        (sid for sid in on_table
         if sid != charger and int(gs["units_cache"][sid]["player"]) != charger_player
         and sid != victim),
        None,
    )
    # Placee DANS les 12" (seuil 60) mais HORS zone d'engagement (10) : au contact elle
    # verrouillerait le chargeur et  refuserait pour ce motif-la.
    if control is not None:
        for offset, mid in enumerate(gs["squad_models"][control]):
            if mid in gs["models_cache"]:
                update_model_position(gs, mid, 30 + (offset % 3), offset // 3)
        assert charge_check_eligibility(gs, str(charger), [str(control)]), (
            f"la cible POSEE {control}, placee a portee, n'est pas declarable : "
            "`charge_check_eligibility` refuse tout et l'assertion finale serait vacante"
        )

    assert not charge_check_eligibility(gs, str(charger), [str(victim)]), (
        f"l'escouade {charger} se declare eligible a charger {victim}, qui est HORS TABLE : le "
        "masque ouvrira un slot que `charge_build_valid_plan` refusera (divergence masque/commit)"
    )


@pytest.mark.parametrize("seed", SEEDS)
def test_an_off_table_entry_is_never_measured(seed: int) -> None:
    """Verrou DIRECT de la garde, independant du chemin emprunte par l'episode.

    Les tests ci-dessus prouvent qu'aucun chemin REEL n'atteint la garde ; celui-ci prouve que la
    garde EXISTE et mord. Sans lui, retirer `_require_measurable_entry` laisserait les deux autres
    verts (ils ne verifient qu'une absence de levee) et le silence reviendrait sans bruit.
    """
    from engine.spatial_relations import (
        get_engagement_zone,
        unit_entries_within_engagement_zone,
    )

    eng = _engine(seed)
    gs = eng.game_state
    off = _off_table_sids(gs)
    assert off, "aucune unite hors table : verrou creux"
    on = [str(sid) for sid, e in gs["units_cache"].items() if int(e["col"]) >= 0]
    other = on[0] if on else off[1]

    with pytest.raises(ValueError, match="HORS TABLE"):
        unit_entries_within_engagement_zone(
            gs["units_cache"][off[0]], gs["units_cache"][other], get_engagement_zone(gs)
        )
    # Symetrique : la garde porte sur les DEUX entrees, pas seulement la premiere.
    with pytest.raises(ValueError, match="HORS TABLE"):
        unit_entries_within_engagement_zone(
            gs["units_cache"][other], gs["units_cache"][off[0]], get_engagement_zone(gs)
        )
