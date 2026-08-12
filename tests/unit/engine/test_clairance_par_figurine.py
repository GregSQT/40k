"""Clairance verticale (§13.06) : c'est la HAUTEUR DE LA FIGURINE qui décide, pas celle du bloc.

LE DÉFAUT. Les pools de mouvement, de charge, de combat et de déploiement construisaient leur
« clairance de sol » — les cases où un étage bas empêche de passer ou de s'arrêter — avec
``unit["MODEL_HEIGHT"]``, c'est-à-dire la taille de l'ESCOUADE. Un personnage attaché plus grand
que la troupe qu'il rejoint se voyait donc proposer des passages où il ne tient pas ; un plus petit
s'en voyait refuser où il tient. Le socle, lui, était déjà lu par figurine sur ces mêmes pools :
la moitié du gabarit venait de la figurine, l'autre du bloc.

Aucune datasheet du dépôt ne porte aujourd'hui deux hauteurs dans une même escouade — c'est
précisément pour ça que ce fichier FABRIQUE le cas : sans lui, la correction serait invisible et
le défaut reviendrait au premier roster qui en portera une.

Règles : Documentation/40k_rules/13 Terrain (13.06).
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

import pytest

from engine.phase_handlers.shared_utils import build_enemy_adjacent_hexes, build_units_cache
from tests._state_invariants import turn_state_invariants, unit_invariants

#: 1" = 10 sous-hexes → géométrie EUCLIDIENNE. À x1, `geometry_is_hex` court-circuite le chemin
#: multi-niveaux et la clairance n'y est jamais consultée : un test monté à x1 serait vert sans
#: rien exécuter (mesuré en écrivant ce fichier).
ISH = 10
HAUTEUR_ESCOUADE = 2.0   # la troupe passe sous l'étage
HAUTEUR_PERSONNAGE = 4.0 # le personnage attaché ne passe pas
CLAIRANCE_ETAGE = 3.0    # hauteur libre sous le plancher : entre les deux

#: Bande de cases couvertes par l'étage bas — le couloir que la troupe peut traverser.
_ETAGE_COLS = range(110, 121)
_ETAGE_ROWS = range(80, 121)
_ETAGE_HEXES = [[c, r] for c in _ETAGE_COLS for r in _ETAGE_ROWS]
_ETAGE_POLY = [[110, 80], [120, 80], [120, 120], [110, 120]]

DEPART = (100, 100)
#: Ennemi posé DE L'AUTRE CÔTÉ du couloir : traverser rapproche, donc les cases sous l'étage
#: entrent dans les pools de pile-in, de consolidation et de charge. Sans lui, ces pools seraient
#: vides et les verrous correspondants ne mesureraient rien.
ENNEMI = (125, 100)


def _unit(uid: str, player: int, models: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    return {**unit_invariants(),
        "id": uid, "player": player,
        "col": models[0]["col"], "row": models[0]["row"],
        "HP_CUR": len(models), "HP_MAX": len(models), "VALUE": 100, "OC": 1, "T": 4,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "SHOOT_LEFT": 1, "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [], "CC_WEAPONS": [], "BASE_SIZE": 1, "BASE_SHAPE": "round",
        "MODEL_HEIGHT": HAUTEUR_ESCOUADE, "MOVE": 60, "UNIT_RULES": [],
        # INFANTRY : sans mot-clé, une figurine ne peut pas finir en hauteur (13.06) et les
        # chemins d'étage sortent avant d'atteindre la clairance.
        "UNIT_KEYWORDS": [{"keywordId": "infantry"}],
        "models": list(models),
    }


@pytest.fixture
def gs() -> Dict[str, Any]:
    """Deux figurines côte à côte : l'une à la taille de l'escouade, l'autre plus grande."""
    troupe = {"col": DEPART[0], "row": DEPART[1], "level": 0, "VALUE": 10}
    perso = {
        "col": DEPART[0], "row": DEPART[1] + 20, "level": 0, "VALUE": 10,
        "MODEL_HEIGHT": HAUTEUR_PERSONNAGE,
    }
    units = [
        _unit("S", 1, [troupe, perso]),
        _unit("E", 2, [{"col": ENNEMI[0], "row": ENNEMI[1], "level": 0, "VALUE": 10}]),
    ]
    state: Dict[str, Any] = {
        **turn_state_invariants(),
        "config": {
            "game_rules": {
                "engagement_zone": 2 * ISH,
                "engagement_zone_vertical": 5.0,
                "max_base_size_hex": 35,
                "unit_model_cohesion_range": 2,
                "unit_global_cohesion_range": 9,
                "squad_min_neighbors": 1,
                "cohesion_distance_mode": "euclidean",
            },
            "move": {"can_move_through_enemy_engagement_zone": True,
                     "can_move_through_enemy_model": False,
                     "can_move_through_friendly_model": True},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": 200, "board_rows": 200,
        "current_player": 1,
        "phase": "move",
        "wall_hexes": set(),
        "terrain_areas": [
            {
                "id": "passage_bas",
                "polygon_vertices": _ETAGE_POLY,
                "hexes": _ETAGE_HEXES,
                "floors": [{
                    "level": 1,
                    "height_inches": CLAIRANCE_ETAGE,
                    "hexes": _ETAGE_HEXES,
                    "polygon_vertices": _ETAGE_POLY,
                }],
            }
        ],
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "units_charged": set(), "units_fled": set(), "units_advanced": set(),
        "units_selected_to_fight": set(),
        # Zone de mise en place = tout le plateau : les tests de déploiement veulent que la
        # clairance soit la SEULE raison de refuser une case sous l'étage.
        "deployment_pools": {
            1: [(c, r) for c in range(60, 180) for r in range(60, 160)],
            2: [(c, r) for c in range(60, 180) for r in range(60, 160)],
        },
        "charge_roll_values": {"S": 12},
        "charge_target_selections": {"S": ["E"]},
        "_unit_move_version": 0,
        "inches_to_subhex": ISH,
        "action_logs": [],
        "action_log_seq": 0,
        "current_turn": 1,
    }
    build_units_cache(state)
    # Le pool de move lit la bande d'engagement ennemie dans un cache de phase (`require_key`) :
    # sans ce peuplement, il lève avant d'atteindre la clairance. Aucune unité ennemie ici → set
    # vide, ce que la fonction produit d'elle-même.
    build_enemy_adjacent_hexes(state, 1)
    return state


def _cases_sous_l_etage(destinations: List[Any]) -> List[Tuple[int, int]]:
    """Destinations AU SOL (niveau 0) situées sous l'étage bas — les seules que la clairance juge.

    Une destination est ``[col, row]`` ou ``[col, row, level]`` selon la phase — le move porte le
    niveau, les pools de combat et de charge rendent une ancre de sol. Le niveau compte : le
    niveau 1 est la SURFACE de l'étage, praticable pour tous, et la confondre avec le passage
    sous l'étage rendrait ce fichier faux.
    """
    return [
        (int(d[0]), int(d[1])) for d in destinations
        if (int(d[2]) if len(d) > 2 else 0) == 0
        and int(d[0]) in _ETAGE_COLS and int(d[1]) in _ETAGE_ROWS
    ]


def test_la_premisse_tient_les_deux_figurines_portent_des_hauteurs_differentes(gs):
    """Sans deux hauteurs, ce fichier ne mesurerait rien : `models_cache` doit les porter."""
    mc = gs["models_cache"]

    assert (mc["S#0"]["MODEL_HEIGHT"], mc["S#1"]["MODEL_HEIGHT"]) == (
        HAUTEUR_ESCOUADE, HAUTEUR_PERSONNAGE
    ), (
        f"hauteurs vues : {mc['S#0'].get('MODEL_HEIGHT')} / {mc['S#1'].get('MODEL_HEIGHT')} ; "
        "attendu celle de l'escouade pour la troupe et la sienne pour le personnage"
    )
    assert HAUTEUR_ESCOUADE < CLAIRANCE_ETAGE < HAUTEUR_PERSONNAGE, (
        "l'étage doit laisser passer l'une et pas l'autre, sinon le test ne discrimine pas"
    )


def test_la_troupe_peut_passer_sous_l_etage_bas(gs):
    """Contre-épreuve : si PERSONNE ne passe, le verrou suivant serait vert sans rien prouver."""
    from engine.phase_handlers.movement_handlers import movement_build_model_destinations_pool

    pool = movement_build_model_destinations_pool(gs, "S#0")

    assert _cases_sous_l_etage(pool["destinations"]), (
        f"aucune case sous l'étage n'est proposée à la figurine de {HAUTEUR_ESCOUADE}\" alors que "
        f"la hauteur libre est de {CLAIRANCE_ETAGE}\" — le couloir est infranchissable pour tous, "
        "donc le verrou ci-dessous ne mesurerait rien"
    )


def test_le_personnage_trop_haut_ne_passe_pas_sous_l_etage_bas(gs):
    """VERROU : mesurée à la hauteur de l'ESCOUADE, cette figurine se voit offrir le couloir."""
    from engine.phase_handlers.movement_handlers import movement_build_model_destinations_pool

    pool = movement_build_model_destinations_pool(gs, "S#1")

    offertes = _cases_sous_l_etage(pool["destinations"])
    assert not offertes, (
        f"{len(offertes)} cases sous un étage de {CLAIRANCE_ETAGE}\" de clairance sont proposées à "
        f"une figurine de {HAUTEUR_PERSONNAGE}\" : la clairance est mesurée à la hauteur de "
        f"l'escouade ({HAUTEUR_ESCOUADE}\"). Ex. {sorted(offertes)[:3]}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Les autres pools par-figurine — même règle, même verdict attendu
#
# Un pool par phase, chacun avec sa contre-épreuve : sans elle, un pool vide (mauvaise mise en
# scène, cible hors de portée, mode inattendu) rendrait le verrou vert sans rien exécuter — c'est
# exactement le faux vert déjà rencontré sur ce chantier.
# ─────────────────────────────────────────────────────────────────────────────

def _pool_pile_in(gs: Dict[str, Any], mid: str) -> List[Any]:
    from engine.phase_handlers.fight_handlers import _fight_pile_in_build_model_pool

    return _fight_pile_in_build_model_pool(gs, mid, ["E"], None, view_level=0)["closer"]


def _pool_consolidation(gs: Dict[str, Any], mid: str) -> List[Any]:
    from engine.phase_handlers.fight_handlers import _fight_consolidation_build_model_pool

    return _fight_consolidation_build_model_pool(
        gs, mid, tier_kind="enemy", tier=["E"], lock_base_contact=False, view_level=0
    )["closer"]


def _pool_charge(gs: Dict[str, Any], mid: str) -> List[Any]:
    from engine.phase_handlers.charge_handlers import charge_model_plan_state

    return charge_model_plan_state(gs, "S", {}, selected_model=mid)["pool"]


def _pool_deploiement(gs: Dict[str, Any], mid: str) -> List[Any]:
    from engine.phase_handlers.deployment_handlers import deployment_build_model_destinations_pool

    return deployment_build_model_destinations_pool(gs, mid)["destinations"]


_POOLS = {
    "pile-in (12.03)": _pool_pile_in,
    "consolidation (12.08)": _pool_consolidation,
    "charge (11.04)": _pool_charge,
    "déploiement (03.02)": _pool_deploiement,
}


@pytest.mark.parametrize("phase", sorted(_POOLS))
def test_la_troupe_recoit_des_cases_sous_l_etage_dans_chaque_pool(gs, phase):
    """Contre-épreuve, une par phase : le couloir doit être proposé à la figurine qui y tient."""
    cases = _cases_sous_l_etage(_POOLS[phase](gs, "S#0"))

    assert cases, (
        f"pool {phase} : aucune case sous l'étage pour la figurine de {HAUTEUR_ESCOUADE}\" — la "
        "mise en scène ne produit rien à filtrer, donc le verrou correspondant serait vacant"
    )


@pytest.mark.parametrize("phase", sorted(_POOLS))
def test_le_personnage_trop_haut_n_a_aucune_case_sous_l_etage_dans_chaque_pool(gs, phase):
    """VERROU : chaque pool par-figurine mesure la clairance à la hauteur de LA figurine."""
    offertes = _cases_sous_l_etage(_POOLS[phase](gs, "S#1"))

    assert not offertes, (
        f"pool {phase} : {len(offertes)} cases sous un étage de {CLAIRANCE_ETAGE}\" sont proposées "
        f"à une figurine de {HAUTEUR_PERSONNAGE}\". Ex. {sorted(offertes)[:3]}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Déploiement : les deux autres sites, où le RAYON DE SOCLE venait lui aussi de l'escouade
# ─────────────────────────────────────────────────────────────────────────────

_SOUS_ETAGE = (115, 100)  # au cœur du couloir, hors de toute autre contrainte


# ─────────────────────────────────────────────────────────────────────────────
# Garde opposable — les sites que les verrous ci-dessus n'atteignent pas
#
# Quatre des onze appels vivent sur des branches d'ÉTAGE (montée, descente, ILP d'autoplace) que
# les pools de plain-pied n'exécutent pas. Les couvrir par comportement demanderait une mise en
# scène multi-niveaux par site. Ce garde ne remplace pas un verrou de comportement — il ne dit
# rien de ce que le code CALCULE — mais il interdit la seule régression réaliste : quelqu'un qui
# repasse la hauteur de l'escouade à un appel, en silence.
# ─────────────────────────────────────────────────────────────────────────────

#: Les onze sites, nommés. Un appel ajouté ou retiré fait échouer le compte : c'est voulu, la
#: liste doit être RELUE à chaque fois qu'un pool apprend à consulter la clairance.
_FICHIERS_CLAIRANCE = {
    "engine/phase_handlers/movement_handlers.py": 1,
    "engine/phase_handlers/fight_handlers.py": 3,
    "engine/phase_handlers/charge_handlers.py": 4,
    "engine/phase_handlers/deployment_handlers.py": 3,
}
#: Formes qui prennent la hauteur sur l'ESCOUADE. C'est exactement ce qui a été corrigé.
_HAUTEUR_D_ESCOUADE = ('require_key(unit, "MODEL_HEIGHT")', 'unit["MODEL_HEIGHT"]')


def _appels_clairance(chemin: str) -> List[str]:
    """Les arguments de chaque appel à `low_clearance_ground_hexes` du fichier (texte brut)."""
    import re
    from pathlib import Path

    racine = Path(__file__).resolve().parents[3]
    source = (racine / chemin).read_text(encoding="utf-8")
    # L'appel tient parfois sur trois lignes : on prend la fenêtre qui suit la parenthèse
    # ouvrante, ce qui suffit à voir d'où vient la hauteur.
    return [source[m.end():m.end() + 200] for m in re.finditer(r"low_clearance_ground_hexes\(", source)
            if "def low_clearance_ground_hexes" not in source[max(0, m.start() - 20):m.start()]]


@pytest.mark.parametrize("chemin", sorted(_FICHIERS_CLAIRANCE))
def test_aucun_appel_de_clairance_ne_prend_la_hauteur_de_l_escouade(chemin):
    """VERROU DE SOURCE : la hauteur passée à la clairance vient toujours d'une FIGURINE."""
    appels = _appels_clairance(chemin)

    assert len(appels) == _FICHIERS_CLAIRANCE[chemin], (
        f"{chemin} : {len(appels)} appels à la clairance, {_FICHIERS_CLAIRANCE[chemin]} attendus. "
        "Un appel a été ajouté ou retiré — relire la liste de ce test, elle est opposable"
    )
    fautifs = [a for a in appels if any(f in a for f in _HAUTEUR_D_ESCOUADE)]
    assert not fautifs, (
        f"{chemin} : {len(fautifs)} appel(s) reprennent la hauteur de l'ESCOUADE alors que la "
        f"clairance est par figurine (§13.06). Passer par `_model_height_of(model, unit)`. "
        f"Extrait : {fautifs[0][:80]!r}"
    )


def test_le_voile_rouge_de_deploiement_refuse_le_personnage_sous_l_etage(gs):
    """VERROU + contre-épreuve dans le MÊME plan : deux figurines, deux verdicts, même case.

    Les avoir ensemble interdit qu'un refus global (zone, mur, hors plateau) passe pour une
    décision de clairance — il frapperait les deux.
    """
    from engine.phase_handlers.deployment_handlers import deployment_preview_plan

    # Écart de 2 sous-hexes : au-delà, la COHÉSION rougit les deux figurines et le test ne
    # mesurerait plus la clairance (constaté en le calibrant).
    etat = deployment_preview_plan(gs, "S", [
        ("S#0", _SOUS_ETAGE[0], _SOUS_ETAGE[1], 0),
        ("S#1", _SOUS_ETAGE[0], _SOUS_ETAGE[1] + 2, 0),
    ])

    assert etat["per_model"]["S#0"] is True, (
        f"la figurine de {HAUTEUR_ESCOUADE}\" est refusée sous un étage laissant "
        f"{CLAIRANCE_ETAGE}\" : le refus ne vient pas de la clairance, la mise en scène est fausse"
    )
    assert etat["per_model"]["S#1"] is False, (
        f"la figurine de {HAUTEUR_PERSONNAGE}\" est acceptée sous un étage laissant "
        f"{CLAIRANCE_ETAGE}\" : le voile rouge mesure la hauteur de l'escouade"
    )


def test_la_formation_compacte_ne_pose_pas_le_personnage_sous_l_etage(gs):
    """La formation automatique place les figurines une par une : chacune à SON gabarit."""
    from engine.phase_handlers.deployment_handlers import generate_compact_formation

    formation = {
        str(mid): (int(c), int(r))
        for mid, c, r in generate_compact_formation(gs, "S", *_SOUS_ETAGE)
    }

    assert _cases_sous_l_etage([formation["S#0"]]), (
        f"la figurine de {HAUTEUR_ESCOUADE}\" n'est pas posée sous l'étage alors que le centre "
        f"demandé y est ({formation['S#0']}) — la mise en scène ne discrimine rien"
    )
    assert not _cases_sous_l_etage([formation["S#1"]]), (
        f"la figurine de {HAUTEUR_PERSONNAGE}\" est posée en {formation['S#1']}, sous un étage "
        f"laissant {CLAIRANCE_ETAGE}\" : la formation mesure la hauteur de l'escouade"
    )
