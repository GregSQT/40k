"""Engagement 3D de la phase FIGHT (règle 03.04 : 2" horizontal ET 5" vertical).

Pourquoi ce fichier existe. La CHARGE mesurait déjà l'engagement en 3D
(``_charge_vertical_zone`` → ``unit_entries_within_engagement_zone(vertical_zone_inches=)``) ;
le FIGHT le mesurait en 2D pure, partout — prédicats d'éligibilité, pools de destinations,
validation des plans. Conséquence : une escouade posée deux étages au-dessus d'un ennemi au sol
était considérée engagée avec lui, donc autorisée à le piler, le combattre et le consolider.

⚠️ Résolution. ``geometry_is_hex()`` bascule toute la géométrie en HEX dès
``inches_to_subhex <= 1`` : un test monté à l'échelle 1 n'exécute PAS les chemins euclidiens
multi-niveaux et passe au vert sans rien vérifier. Ce fichier monte donc le plateau à
``inches_to_subhex = 10`` (1" = 10 cases) — c'est la condition pour que ces verrous mordent.

Règles citées : Documentation/40k_rules/03 Moving (03.04), /12 Fights phase, /13 Terrain (13.06).
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

import pytest

from engine.phase_handlers import fight_handlers as fh
from tests.unit.engine._state_builders import synthetic_state, synthetic_unit


ISH = 10                     # 1" = 10 sous-hexes → géométrie EUCLIDIENNE (cf. geometry_is_hex)
ENGAGEMENT_ZONE = 2 * ISH    # 2" (03.04), déjà scalé comme le fait w40k_core au chargement
VERTICAL_ZONE = 5.0          # 5" (03.04), en POUCES — jamais scalé
MODEL_HEIGHT = 2.5
FLOOR_HEIGHT = 10.0          # plancher très au-dessus des 5" → hors zone verticale

# Plancher de niveau 1 : large, pour qu'un socle rond y tienne ENTIÈREMENT (13.06).
_FLOOR_COLS = range(10, 41)
_FLOOR_ROWS = range(10, 41)
_FLOOR_HEXES = [[c, r] for c in _FLOOR_COLS for r in _FLOOR_ROWS]
# `resolve_model_floor_level` exige le POLYGONE pour les socles ronds (confinement euclidien) :
# un plancher décrit par ses seuls `hexes` renvoie toute figurine ronde au sol.
_FLOOR_POLYGON = [[10, 10], [40, 10], [40, 40], [10, 40]]


def _unit(uid: str, player: int, models: Sequence[Tuple[int, int, int]]) -> Dict[str, Any]:
    """Unité dont chaque figurine porte SA position ET SON étage ``(col, row, level)``."""
    return synthetic_unit(
        uid, player,
        [{"col": c, "row": r, "level": lv} for c, r, lv in models],
        MODEL_HEIGHT=MODEL_HEIGHT,
    )


def _make_gs(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    return synthetic_state(
        units,
        inches_to_subhex=ISH,
        game_rules={
            "engagement_zone": ENGAGEMENT_ZONE,
            "engagement_zone_vertical": VERTICAL_ZONE,
        },
        phase="fight",
        terrain_areas=[{
            "id": "ruin",
            "polygon_vertices": _FLOOR_POLYGON,
            "hexes": _FLOOR_HEXES,
            "floors": [{
                "level": 1,
                "height_inches": FLOOR_HEIGHT,
                "hexes": _FLOOR_HEXES,
                "polygon_vertices": _FLOOR_POLYGON,
            }],
        }],
    )


def _duel(attacker_level: int) -> Dict[str, Any]:
    """Attaquant en (20,20) à ``attacker_level``, défenseur au SOL en (21,20).

    Les deux socles sont horizontalement à 1 sous-hex l'un de l'autre, donc TRÈS largement
    dans les 2" horizontales : seul l'axe vertical peut les séparer.
    """
    return _make_gs([
        _unit("1", 1, [(20, 20, attacker_level)]),
        _unit("2", 2, [(21, 20, 0)]),
    ])


def _only(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """L'entrée synthétique UNIQUE d'une escouade à socle homogène.

    ``_fight_synth_cache_entries_at_footprint`` rend une entrée PAR SOCLE distinct (un personnage
    attaché n'est plus mesuré au gabarit de la troupe). Les escouades de ce fichier sont
    homogènes : en attendre exactement une, sinon le test mesurerait une classe au hasard.
    """
    assert len(entries) == 1, (
        f"escouade homogène attendue → 1 entrée par socle, obtenu {len(entries)}"
    )
    return entries[0]


# ─────────────────────────────────────────────────────────────────────────────
# Prémisses du harnais — un test qui ne construit pas sa situation ne vérifie rien
# ─────────────────────────────────────────────────────────────────────────────

def test_the_harness_really_puts_one_unit_upstairs_and_one_on_the_ground():
    """VERT VACANT : si le plancher ne portait pas la figurine (polygone manquant, hexes trop
    étroits), elle retomberait au sol et TOUS les tests ci-dessous mesureraient un duel au sol —
    ils passeraient au vert sans jamais exécuter le gate vertical."""
    from engine.spatial_relations import geometry_is_hex

    gs = _duel(attacker_level=1)
    assert not geometry_is_hex(gs), (
        "prémisse : à inches_to_subhex=10 la géométrie doit être EUCLIDIENNE, sinon les chemins "
        "multi-niveaux ne sont pas exécutés"
    )
    assert int(gs["models_cache"]["1#0"]["level"]) == 1, (
        f"prémisse : l'attaquant doit être à l'étage, obtenu {gs['models_cache']['1#0']['level']}"
    )
    assert int(gs["models_cache"]["2#0"]["level"]) == 0, "prémisse : le défenseur doit être au sol"
    floors = gs["units_cache"]["1"]["floor_height_by_model"]
    assert floors["1#0"] == pytest.approx(FLOOR_HEIGHT), (
        f"prémisse : la hauteur de plancher doit être {FLOOR_HEIGHT}\", obtenu {floors}"
    )
    gap = FLOOR_HEIGHT - MODEL_HEIGHT
    assert gap > VERTICAL_ZONE, (
        f"prémisse : l'écart vertical ({gap}\") doit dépasser les {VERTICAL_ZONE}\" de 03.04, "
        "sinon le test ne sépare rien"
    )


def test_two_units_on_the_ground_are_engaged():
    """L'autre moitié du verrou : le gate vertical ne doit pas tout refuser. Au sol des deux
    côtés, une seule classe verticale → le résultat est EXACTEMENT celui du 2D."""
    gs = _duel(attacker_level=0)
    assert fh._fight_v11_engaged_now(gs, gs["unit_by_id"]["1"]) is True, (
        "deux unités adjacentes AU SOL ne sont plus engagées : le gate vertical mord à tort"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 03.04 — le verrou : la hauteur sépare
# ─────────────────────────────────────────────────────────────────────────────

def test_a_unit_two_floors_above_an_enemy_is_not_engaged_with_it():
    """03.04 : la zone d'engagement est de 2" horizontalement ET 5" verticalement.

    L'attaquant est à 10" au-dessus du sol, l'ennemi au sol : leurs intervalles verticaux
    ``[plancher, plancher + MODEL_HEIGHT]`` sont séparés de 7,5" > 5". Ils ne sont pas engagés,
    quelle que soit leur proximité horizontale.
    """
    gs = _duel(attacker_level=1)
    assert fh._fight_v11_engaged_now(gs, gs["unit_by_id"]["1"]) is False, (
        "une escouade deux étages au-dessus d'un ennemi au sol est comptée engagée avec lui (03.04)"
    )
    assert fh._fight_v11_engaged_now(gs, gs["unit_by_id"]["2"]) is False, (
        "l'engagement doit être symétrique : l'ennemi au sol se croit engagé avec l'étage"
    )


def test_a_unit_two_floors_above_an_enemy_is_not_eligible_to_fight():
    """12.04 « units that are engaged » : l'éligibilité au combat dérive de l'engagement.

    Sans le gate vertical, l'unité de l'étage entrait dans le pool 12.04 et pouvait frapper un
    ennemi qu'elle ne touche pas.
    """
    gs = _duel(attacker_level=1)
    gs["engaged_at_fight_step_start"] = fh.fight_compute_engaged_snapshot(gs)
    assert gs["engaged_at_fight_step_start"] == {"1": False, "2": False}, (
        f"le snapshot 12.04 compte un engagement inter-étages : {gs['engaged_at_fight_step_start']}"
    )
    assert fh.fight_v11_is_eligible_to_fight(gs, gs["unit_by_id"]["1"]) is False
    assert fh.fight_v11_is_pile_in_eligible(gs, gs["unit_by_id"]["1"]) is False, (
        "12.03 : une unité non engagée et qui n'a pas chargé ne peut pas piler"
    )


def test_the_ground_case_still_makes_everyone_eligible():
    """Contre-épreuve du test précédent — sinon « tout est False » passerait pour un succès."""
    gs = _duel(attacker_level=0)
    gs["engaged_at_fight_step_start"] = fh.fight_compute_engaged_snapshot(gs)
    assert gs["engaged_at_fight_step_start"] == {"1": True, "2": True}
    assert fh.fight_v11_is_eligible_to_fight(gs, gs["unit_by_id"]["1"]) is True
    assert fh.fight_v11_is_pile_in_eligible(gs, gs["unit_by_id"]["1"]) is True


def test_the_valid_target_pool_excludes_an_enemy_out_of_vertical_reach():
    """12.04 « select one enemy unit that it is engaged with » : le pool de cibles suit 03.04.

    Vérifie le JUMEAU du prédicat : corriger l'éligibilité sans corriger le pool de cibles
    laisserait une unité éligible viser une cible qu'elle ne peut pas atteindre.
    """
    upstairs = _duel(attacker_level=1)
    assert fh._fight_build_valid_target_pool(upstairs, upstairs["unit_by_id"]["1"]) == [], (
        "le pool de cibles 12.04 propose un ennemi hors de portée verticale (03.04)"
    )
    ground = _duel(attacker_level=0)
    assert [str(t) for t in fh._fight_build_valid_target_pool(ground, ground["unit_by_id"]["1"])] == ["2"], (
        "au sol, la cible adjacente a disparu du pool : le gate vertical écarte trop"
    )


def test_engaged_units_listing_follows_the_vertical_zone():
    """``_fight_units_engaged_with`` alimente le pile-in (engagements à conserver) : le laisser
    en 2D ferait exiger la conservation d'un engagement qui n'existe pas."""
    assert fh._fight_units_engaged_with(_duel(1), _duel(1)["unit_by_id"]["1"]) == []
    ground = _duel(attacker_level=0)
    assert fh._fight_units_engaged_with(ground, ground["unit_by_id"]["1"]) == ["2"]


# ─────────────────────────────────────────────────────────────────────────────
# L'entrée synthétique d'empreinte candidate — état APRÈS, pas état AVANT
# ─────────────────────────────────────────────────────────────────────────────

def test_the_candidate_synthetic_entry_describes_the_candidate_position():
    """``_fight_synth_cache_entries_at_footprint`` décrit une position CANDIDATE.

    Elle héritait ``occupied_hexes_by_model`` de l'entrée réelle, c'est-à-dire les positions
    d'AVANT le mouvement. Or en métrique euclidienne ``socle_from_cache_entry`` mesure depuis
    cette carte et IGNORE ``occupied_hexes`` : tout contrôle « après mouvement » répondait donc
    sur l'état d'avant. Le même champ est la source du gate vertical (``_vertical_classes``).
    """
    gs = _make_gs([_unit("1", 1, [(20, 20, 0)]), _unit("2", 2, [(21, 20, 0)])])
    unit = gs["unit_by_id"]["1"]
    origin = gs["units_cache"]["1"]["occupied_hexes_by_model"]["1#0"]
    assert tuple(origin) == (20, 20), f"prémisse : origine attendue (20,20), obtenue {origin}"

    synth = _only(fh._fight_synth_cache_entries_at_footprint(unit, gs, 30, 20))

    assert tuple(synth["occupied_hexes_by_model"]["1#0"]) == (30, 20), (
        "la carte par-figurine de l'entrée candidate pointe encore la position de DÉPART "
        f"({synth['occupied_hexes_by_model']}) : toute mesure euclidienne « après mouvement » "
        "répond sur l'état d'avant"
    )
    assert synth["floor_height_by_model"]["1#0"] == pytest.approx(0.0)
    assert "MODEL_HEIGHT" in synth, (
        "sans MODEL_HEIGHT l'engagement 3D lève (_vertical_classes) : câblage incomplet"
    )


def test_the_candidate_synthetic_entry_accepts_a_per_model_plan():
    """Une escouade à cheval sur DEUX étages : chaque figurine garde SON niveau.

    C'est le cas qui a produit le bug d'origine — l'autoplace de pile-in n'émettait pas l'étage,
    le commit supposait « niveau de vue », et les deux figurines devenaient invalidables.
    """
    gs = _make_gs([_unit("1", 1, [(20, 20, 0), (21, 20, 1)]), _unit("2", 2, [(30, 30, 0)])])
    unit = gs["unit_by_id"]["1"]

    synth = _only(fh._fight_synth_cache_entries_at_footprint(
        unit, gs, 20, 20,
        model_placements={"1#0": (20, 20, 0), "1#1": (21, 20, 1)},
    ))

    assert synth["floor_height_by_model"] == {
        "1#0": pytest.approx(0.0),
        "1#1": pytest.approx(FLOOR_HEIGHT),
    }, (
        "les deux figurines sont ramenées au même étage : une escouade à cheval sur deux niveaux "
        f"est décrite comme plate ({synth['floor_height_by_model']})"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Un niveau ne se transporte pas d'une position à l'autre (§13.06)
# ─────────────────────────────────────────────────────────────────────────────

def test_a_rigid_translation_off_the_floor_lands_on_the_ground():
    """Les pools d'ancres translatent le bloc rigidement. Reconduire le niveau de départ tel quel
    vers une case SANS plancher faisait lever ``floor_height_at`` (« figurine marquée à l'étage
    mais hors empreinte de plancher ») — un crash du pool là où la règle 13.06 demande simplement
    de poser la figurine au sol."""
    gs = _make_gs([_unit("1", 1, [(20, 20, 1)]), _unit("2", 2, [(50, 50, 0)])])
    assert int(gs["models_cache"]["1#0"]["level"]) == 1, "prémisse : la fig part de l'étage"
    off_floor = (50, 20)
    assert off_floor[0] not in _FLOOR_COLS, "prémisse : l'ancre visée doit être HORS du plancher"

    placements = fh._fight_rigid_model_placements(gs, "1", off_floor[0], off_floor[1])

    assert placements["1#0"] == (off_floor[0], off_floor[1], 0), (
        f"une figurine translatée hors du plancher doit être au SOL, obtenu {placements['1#0']}"
    )
    # Le vrai symptôme : l'entrée synthétique se construisait avec ce niveau et levait.
    synth = _only(fh._fight_synth_cache_entries_at_footprint(
        gs["unit_by_id"]["1"], gs, off_floor[0], off_floor[1]
    ))
    assert synth["floor_height_by_model"]["1#0"] == pytest.approx(0.0)


def test_a_rigid_translation_that_stays_on_the_floor_keeps_its_level():
    """Contre-épreuve : le résolveur ne doit pas tout ramener au sol."""
    gs = _make_gs([_unit("1", 1, [(20, 20, 1)]), _unit("2", 2, [(50, 50, 0)])])

    placements = fh._fight_rigid_model_placements(gs, "1", 25, 25)

    assert placements["1#0"] == (25, 25, 1), (
        f"une figurine restée sur son plancher garde son étage, obtenu {placements['1#0']}"
    )


def test_a_read_only_preview_of_an_off_floor_plan_does_not_raise():
    """Un plan qui pose une figurine hors plancher est INVALIDE, pas corrompu.

    L'aperçu PvP est en LECTURE SEULE : il doit rendre « can_validate: False », pas une 500.
    Le niveau d'un plan est une DEMANDE — `resolved_floor_height_at` laisse le plancher trancher,
    là où `floor_height_at` seule levait « figurine marquée à l'étage mais hors empreinte ».
    """
    gs = _make_gs([_unit("1", 1, [(20, 20, 1)]), _unit("2", 2, [(50, 50, 0)])])
    off_floor = (50, 20)
    assert off_floor[0] not in _FLOOR_COLS, "prémisse : la case visée est hors du plancher"

    synth = _only(fh._fight_synth_cache_entries_at_footprint(
        gs["unit_by_id"]["1"], gs, off_floor[0], off_floor[1],
        model_placements={"1#0": (off_floor[0], off_floor[1], 1)},  # étage DEMANDÉ, plancher absent
    ))

    assert synth["floor_height_by_model"]["1#0"] == pytest.approx(0.0), (
        "un étage demandé sur une case sans plancher doit être résolu au SOL, pas lever"
    )


def test_moving_a_squad_off_its_floor_resyncs_its_level_and_height():
    """Racine du crash de commit : la translation rigide d'ancre ne réécrit PAS les niveaux.

    Le resync de cache doit donc RÉSOUDRE le niveau (§13.06), sinon `floor_height_at` lève en
    plein commit — sur un état déjà à moitié muté, et l'exception est avalée par le pile-in auto.
    """
    from engine.phase_handlers.shared_utils import translate_squad_to_destination

    # MULTI-figurine : c'est `_recompute_squad_occupied_hexes` qui recalcule les cartes. Une
    # escouade mono-figurine passe par le resync d'ancre (`update_units_cache_position`) et
    # masquerait le défaut visé ici.
    gs = _make_gs([_unit("1", 1, [(20, 20, 1), (21, 20, 1)]), _unit("2", 2, [(50, 50, 0)])])
    assert [int(gs["models_cache"][m]["level"]) for m in ("1#0", "1#1")] == [1, 1], (
        "prémisse : les deux figs partent de l'étage"
    )

    translate_squad_to_destination(gs, "1", 50, 20)  # hors plancher

    assert [int(gs["models_cache"][m]["level"]) for m in ("1#0", "1#1")] == [0, 0], (
        "le niveau stocké contredit la position : figs hors plancher mais marquées à l'étage"
    )
    floors = gs["units_cache"]["1"]["floor_height_by_model"]
    assert floors["1#0"] == pytest.approx(0.0) and floors["1#1"] == pytest.approx(0.0)


def test_base_contact_does_not_reach_through_a_floor():
    """12.03 WHILE : « Models in base-contact with one or more enemy models cannot be moved. »

    Le contact est gaté verticalement comme l'engagement (§03.04) : deux socles superposés à des
    étages différents ne se touchent pas. Un contrôle 2D FIGEAIT une figurine sous un ennemi posé
    à l'étage — immobilisée pour le pile-in et la consolidation alors que le moteur déclare la
    paire non engagée.
    """
    def _touching(attacker_level: int) -> Dict[str, Any]:
        """Socles ASSEZ GROS pour se toucher à 1 sous-hex d'écart (BASE_SIZE 1 ne se touche pas :
        écart bord-à-bord 0,23 > 0 — la prémisse doit être construite, pas espérée)."""
        gs = _make_gs([
            _unit("1", 1, [(20, 20, attacker_level)]),
            _unit("2", 2, [(21, 20, 0)]),
        ])
        for entry in list(gs["models_cache"].values()) + list(gs["units_cache"].values()):
            entry["BASE_SIZE"] = 3
        return gs

    flat = _touching(attacker_level=0)
    assert fh._fight_model_in_base_contact(flat, "2#0", flat["models_cache"]["2#0"]), (
        "prémisse : au sol des deux côtés, ces deux socles DOIVENT être au contact"
    )

    upstairs = _touching(attacker_level=1)
    assert not fh._fight_model_in_base_contact(upstairs, "2#0", upstairs["models_cache"]["2#0"]), (
        "la figurine au sol est déclarée au contact d'un ennemi situé un étage au-dessus"
    )


def test_base_contact_reads_the_subjects_own_floor():
    """Le SUJET aussi a une altitude — elle était lue dans deux clés inexistantes.

    Complément indispensable de `test_base_contact_does_not_reach_through_a_floor`, qui ne teste
    que des sujets AU SOL : là, une hauteur de sujet erronée à 0,0 est juste par accident. Ici le
    sujet est À L'ÉTAGE, au contact d'un ennemi du MÊME étage.

    L'ancienne implémentation lisait `model_entry["floor_height"]` (clé qui n'existe nulle part)
    puis `floor_height_by_model[model_entry["id"]]` (une entrée `models_cache` porte `squad_id`,
    pas `id`) : le sujet était donc TOUJOURS mesuré à 0,0. Deux figurines côte à côte à 10" de
    haut ressortaient séparées de 7,5" — au-delà des 5" de §03.04 — donc « pas au contact », et
    12.03 ne les figeait plus alors qu'elles se touchent.
    """
    def _touching_at(level: int) -> Dict[str, Any]:
        gs = _make_gs([
            _unit("1", 1, [(20, 20, level)]),
            _unit("2", 2, [(21, 20, level)]),
        ])
        for entry in list(gs["models_cache"].values()) + list(gs["units_cache"].values()):
            entry["BASE_SIZE"] = 3
        return gs

    upstairs = _touching_at(level=1)
    # Prémisse CONSTRUITE, pas espérée : les deux figurines sont réellement en hauteur.
    floors = upstairs["units_cache"]["2"]["floor_height_by_model"]
    assert floors["2#0"] == pytest.approx(FLOOR_HEIGHT), (
        f"prémisse : le sujet doit être à {FLOOR_HEIGHT}\", obtenu {floors}"
    )
    assert upstairs["units_cache"]["1"]["floor_height_by_model"]["1#0"] == pytest.approx(
        FLOOR_HEIGHT
    ), "prémisse : l'ennemi doit être au MÊME étage"

    assert fh._fight_model_in_base_contact(upstairs, "2#0", upstairs["models_cache"]["2#0"]), (
        "deux figurines au contact sur le MÊME étage doivent être en base-contact — le sujet "
        "était mesuré à 0,0 quel que soit son plancher"
    )

    # Contre-épreuve : au sol, même géométrie, même verdict. Le correctif ne rend pas tout vrai.
    ground = _touching_at(level=0)
    assert fh._fight_model_in_base_contact(ground, "2#0", ground["models_cache"]["2#0"])


def test_the_gym_pile_in_uses_the_shared_base_contact_predicate():
    """12.03 WHILE MOVING : « Models in base-contact [...] cannot be moved » — des DEUX côtés.

    Le pile-in du gym (`_assign_cells_toward_enemies`, appelé par `fight_pile_in_plan` et
    `squad_consolidate_plan`) gardait sa propre géométrie du contact : distance de CENTRE à centre
    en cases (`== BASE_TO_BASE_SUBHEX`, 1 case) là où le PvP mesure BORD à bord. Deux socles au
    contact ont leurs centres à 3 cases (BASE_SIZE 3) ou 6 (BASE_SIZE 6) — `== 1` était donc
    IMPOSSIBLE dès qu'un socle dépasse une case, et la règle ne s'appliquait JAMAIS côté gym
    pendant que le PvP figeait bien la figurine.

    ⚠️ CE QUI EST VÉRIFIÉ, ET POURQUOI. La position finale ne discrimine PAS : une figurine au
    contact n'a de toute façon aucune case « strictement plus proche » qui soit légale (elle
    chevaucherait l'ennemi), donc elle reste sur place avec l'ancienne géométrie comme avec la
    nouvelle — un test sur sa position serait un vert vacant. Ce qui distingue les deux versions,
    c'est le CÂBLAGE : le plan doit suivre le prédicat partagé. On le force donc dans les deux
    sens et on vérifie que le plan change avec lui — impossible à satisfaire pour une
    implémentation qui garderait sa propre géométrie.
    """
    from unittest.mock import patch
    from engine.phase_handlers import shared_utils as su

    gs = _make_gs([_unit("1", 1, [(20, 20, 0), (14, 20, 0)]), _unit("2", 2, [(26, 20, 0)])])
    for entry in list(gs["models_cache"].values()) + list(gs["units_cache"].values()):
        entry["BASE_SIZE"] = 6
    mids = [m for m in gs["squad_models"]["1"] if m in gs["models_cache"]]
    origins = {m: (int(gs["models_cache"][m]["col"]), int(gs["models_cache"][m]["row"]))
               for m in mids}
    enemy_positions = []
    for esid in su._enemy_squad_ids(gs, 1):
        enemy_positions.extend(su._squad_model_positions(gs, esid))
    budget = 3 * int(gs["inches_to_subhex"])

    # Prémisse CONSTRUITE : les socles de 1#0 et de l'ennemi se touchent réellement, et leurs
    # CENTRES sont hors de l'ancien test `== 1` — sans quoi les deux géométries coïncideraient.
    from engine.hex_utils import euclidean_edge_clearance_round_round
    from engine.combat_utils import calculate_hex_distance

    assert euclidean_edge_clearance_round_round(20, 20, 6, 26, 20, 6) <= 0.0, (
        "prémisse : les socles doivent se toucher bord à bord"
    )
    assert calculate_hex_distance(20, 20, 26, 20) != su.BASE_TO_BASE_SUBHEX, (
        "prémisse : les centres doivent être hors de l'ancien test `== 1`"
    )
    assert su.model_in_base_contact(gs, mids[0], gs["models_cache"][mids[0]]), (
        "prémisse : le prédicat partagé doit voir le contact"
    )

    # Contre-épreuve : sans contact déclaré, la figurine arrière BOUGE — le plan n'est pas figé
    # par autre chose que le prédicat.
    with patch.object(su, "model_in_base_contact", lambda _gs, _mid, _m: False):
        libre = su._assign_cells_toward_enemies(gs, "1", mids, enemy_positions, budget)
    assert any(libre[m] != origins[m] for m in mids), (
        "prémisse : sans contact, au moins une figurine doit se déplacer"
    )

    # Contact déclaré pour TOUTES : le plan doit les laisser toutes sur place.
    with patch.object(su, "model_in_base_contact", lambda _gs, _mid, _m: True):
        figees = su._assign_cells_toward_enemies(gs, "1", mids, enemy_positions, budget)
    assert all(figees[m] == origins[m] for m in mids), (
        f"12.03 : le plan doit suivre le prédicat partagé, obtenu {figees} pour {origins}"
    )
