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

CE QUE CE FICHIER NE COUVRE PLUS, ET POURQUOI. Quatre des onze appels vivent sur des branches
d'ÉTAGE (montée, descente, ILP d'autoplace) qu'aucun pool de plain-pied n'exécute ; ils étaient
tenus par un garde qui relisait le TEXTE des handlers. Ce garde a été supprimé au profit de la
signature de la primitive : ``low_clearance_ground_hexes(terrain_areas, model_entry, squad_entry)``
n'accepte plus de hauteur nue, et l'héritage figurine→escouade appartient à ``_model_height_of``.
La faute n'est plus détectée après coup — elle n'est plus écrivable, sur ces quatre sites comme
sur les sept autres.

Règles : Documentation/40k_rules/13 Terrain (13.06).
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

import pytest

from engine.phase_handlers.charge_handlers import charge_model_plan_state
from engine.phase_handlers.deployment_handlers import (
    deployment_build_model_destinations_pool,
    deployment_preview_plan,
    generate_compact_formation,
)
from engine.phase_handlers.fight_handlers import (
    _fight_consolidation_build_model_pool,
    _fight_pile_in_build_model_pool,
)
from engine.phase_handlers.movement_handlers import movement_build_model_destinations_pool
from engine.phase_handlers.shared_utils import build_enemy_adjacent_hexes
from engine.terrain_utils import low_clearance_ground_hexes
from tests.unit.engine._state_builders import synthetic_state, synthetic_unit

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
_C0, _C1 = _ETAGE_COLS.start, _ETAGE_COLS.stop - 1
_R0, _R1 = _ETAGE_ROWS.start, _ETAGE_ROWS.stop - 1
#: Dérivé des deux ranges ci-dessus : écrit en dur, il faudrait penser à le suivre à chaque
#: déplacement du couloir, et un polygone désaccordé de ses hexes ne lève nulle part.
_ETAGE_POLY = [[_C0, _R0], [_C1, _R0], [_C1, _R1], [_C0, _R1]]

DEPART = (100, 100)
#: Case de référence AU CŒUR du couloir, hors de toute autre contrainte (zone, mur, bord).
_SOUS_ETAGE = (115, 100)
#: Ennemi posé DE L'AUTRE CÔTÉ du couloir : traverser rapproche, donc les cases sous l'étage
#: entrent dans les pools de pile-in, de consolidation et de charge. Sans lui, ces pools seraient
#: vides et les verrous correspondants ne mesureraient rien.
ENNEMI = (125, 100)


def _etat(models: Sequence[Dict[str, Any]], cohesion: int = 2) -> Dict[str, Any]:
    """Plateau x10 avec un couloir sous un étage bas, l'escouade ``S`` et un ennemi ``E``.

    ``cohesion`` : portée de cohésion en sous-hexes. Élargie par le test de SOCLE, où les deux
    figurines doivent s'écarter assez pour que le disque de la plus large ne chevauche pas sa
    voisine — sinon c'est la collision intra-escouade, et non la clairance, qui rougit.
    """
    unite = {
        # INFANTRY : sans mot-clé, une figurine ne peut pas finir en hauteur (13.06) et les
        # chemins d'étage sortent avant d'atteindre la clairance.
        "UNIT_KEYWORDS": [{"keywordId": "infantry"}],
        "MODEL_HEIGHT": HAUTEUR_ESCOUADE,
        # MOVE = 3" : le BFS atteint le couloir avec 107 cases de marge pour la contre-épreuve,
        # et coûte 4x moins que 6" (0,08 s contre 0,37 s par pool). En dessous de 2" il ne reste
        # que 6 cases — trop mince pour que la contre-épreuve prouve quoi que ce soit.
        "MOVE": 3 * ISH,
    }
    state = synthetic_state(
        [
            synthetic_unit("S", 1, list(models), **unite),
            synthetic_unit("E", 2, [{"col": ENNEMI[0], "row": ENNEMI[1]}], **unite),
        ],
        inches_to_subhex=ISH,
        board_cols=200, board_rows=200,
        terrain_areas=[{
            "id": "passage_bas",
            "polygon_vertices": _ETAGE_POLY,
            "hexes": _ETAGE_HEXES,
            "floors": [{
                "level": 1,
                "height_inches": CLAIRANCE_ETAGE,
                "hexes": _ETAGE_HEXES,
                "polygon_vertices": _ETAGE_POLY,
            }],
        }],
        game_rules={"engagement_zone": 2 * ISH, "unit_model_cohesion_range": cohesion},
        phase="move",
        # Zone de mise en place = tout le plateau : les tests de déploiement veulent que la
        # clairance soit la SEULE raison de refuser une case sous l'étage.
        deployment_pools={
            1: [(c, r) for c in range(60, 180) for r in range(60, 160)],
            2: [(c, r) for c in range(60, 180) for r in range(60, 160)],
        },
        # Jet de charge de 6" : le champ multi-niveaux balaie un rayon proportionnel au jet, et
        # 12" coûtaient 3,7 s par appel pour un ennemi à 2,5" — pools rendus IDENTIQUES à 6"
        # (312 et 237 destinations, 75 et 0 cases sous l'étage). À 3" le pool du personnage se
        # vide et la contre-épreuve deviendrait vacante.
        charge_roll_values={"S": 6},
        charge_target_selections={"S": ["E"]},
    )
    # Le pool de move lit la bande d'engagement ennemie dans un cache de phase (`require_key`) :
    # sans ce peuplement, il lève avant d'atteindre la clairance.
    build_enemy_adjacent_hexes(state, 1)
    return state


@pytest.fixture
def gs() -> Dict[str, Any]:
    """Deux figurines : l'une à la taille de l'escouade, l'autre plus grande. Même socle."""
    return _etat([
        {"col": DEPART[0], "row": DEPART[1], "level": 0, "VALUE": 10},
        {
            "col": DEPART[0], "row": DEPART[1] + 20, "level": 0, "VALUE": 10,
            "MODEL_HEIGHT": HAUTEUR_PERSONNAGE,
        },
    ])


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


# ─────────────────────────────────────────────────────────────────────────────
# Les pools par-figurine — même règle, même verdict attendu
#
# Un pool par phase, chacun avec sa contre-épreuve : sans elle, un pool vide (mauvaise mise en
# scène, cible hors de portée, mode inattendu) rendrait le verrou vert sans rien exécuter — c'est
# exactement le faux vert déjà rencontré sur ce chantier.
# ─────────────────────────────────────────────────────────────────────────────

def _pool_move(gs: Dict[str, Any], mid: str) -> List[Any]:
    return movement_build_model_destinations_pool(gs, mid)["destinations"]


def _pool_pile_in(gs: Dict[str, Any], mid: str) -> List[Any]:
    return _fight_pile_in_build_model_pool(gs, mid, ["E"], None, view_level=0)["closer"]


def _pool_consolidation(gs: Dict[str, Any], mid: str) -> List[Any]:
    return _fight_consolidation_build_model_pool(
        gs, mid, tier_kind="enemy", tier=["E"], lock_base_contact=False, view_level=0
    )["closer"]


def _pool_charge(gs: Dict[str, Any], mid: str) -> List[Any]:
    return charge_model_plan_state(gs, "S", {}, selected_model=mid)["pool"]


def _pool_deploiement(gs: Dict[str, Any], mid: str) -> List[Any]:
    return deployment_build_model_destinations_pool(gs, mid)["destinations"]


_POOLS = {
    "mouvement (09.01)": _pool_move,
    "pile-in (12.03)": _pool_pile_in,
    "consolidation (12.08)": _pool_consolidation,
    "charge (11.04)": _pool_charge,
    "déploiement (03.02)": _pool_deploiement,
}
_PHASES = sorted(_POOLS)


@pytest.mark.parametrize("phase", _PHASES)
def test_la_troupe_recoit_des_cases_sous_l_etage_dans_chaque_pool(gs, phase):
    """Contre-épreuve, une par phase : le couloir doit être proposé à la figurine qui y tient."""
    cases = _cases_sous_l_etage(_POOLS[phase](gs, "S#0"))

    assert cases, (
        f"pool {phase} : aucune case sous l'étage pour la figurine de {HAUTEUR_ESCOUADE}\" — la "
        "mise en scène ne produit rien à filtrer, donc le verrou correspondant serait vacant"
    )


@pytest.mark.parametrize("phase", _PHASES)
def test_le_personnage_trop_haut_n_a_aucune_case_sous_l_etage_dans_chaque_pool(gs, phase):
    """VERROU : chaque pool par-figurine mesure la clairance à la hauteur de LA figurine."""
    offertes = _cases_sous_l_etage(_POOLS[phase](gs, "S#1"))

    assert not offertes, (
        f"pool {phase} : {len(offertes)} cases sous un étage de {CLAIRANCE_ETAGE}\" sont proposées "
        f"à une figurine de {HAUTEUR_PERSONNAGE}\". Ex. {sorted(offertes)[:3]}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# La signature de la primitive — ce qui a remplacé le garde de source
# ─────────────────────────────────────────────────────────────────────────────

def test_la_primitive_de_clairance_refuse_tout_ce_qui_n_est_pas_une_figurine():
    """VERROU DE CONTRAT : les quatre façons d'écrire l'ancien défaut sont refusées.

    C'est ce test qui rend inutile le garde qui relisait le texte des handlers. Les deux dernières
    formes sont celles qu'une signature « deux entrées de même forme » laisserait passer, et que
    la `/code-review` avait relevées : rien n'oblige un appelant à mettre la figurine en premier,
    ni à ne pas passer l'escouade deux fois sous deux visages. Les branches d'ÉTAGE (montée,
    descente, ILP d'autoplace), qu'aucun pool de plain-pied n'exécute, sont couvertes par là.
    """
    terrain = [{"floors": [{
        "level": 1, "height_inches": CLAIRANCE_ETAGE, "hexes": [[10, 10]],
        "polygon_vertices": [[10, 10], [12, 10], [12, 12], [10, 12]],
    }]}]
    #: Les MARQUES de rôle : `squad_id` n'existe que sur une figurine, `id` que sur une unité.
    escouade = {"id": "S", "MODEL_HEIGHT": HAUTEUR_ESCOUADE}
    figurine = {"squad_id": "S", "MODEL_HEIGHT": HAUTEUR_PERSONNAGE}
    ligne_d_escouade = {"MODEL_HEIGHT": HAUTEUR_ESCOUADE}  # une entrée `units_cache`

    with pytest.raises(TypeError):
        low_clearance_ground_hexes(terrain, HAUTEUR_ESCOUADE)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="squad_id"):
        low_clearance_ground_hexes(terrain, escouade, escouade)
    with pytest.raises(ValueError, match="squad_id"):
        low_clearance_ground_hexes(terrain, ligne_d_escouade, escouade)
    with pytest.raises(ValueError, match="squad_id"):
        low_clearance_ground_hexes(terrain, escouade, figurine)  # arguments inversés

    assert low_clearance_ground_hexes(terrain, figurine, escouade) == {(10, 10)}, (
        "la figurine plus haute que la clairance doit voir la case bloquée"
    )
    assert low_clearance_ground_hexes(terrain, {"squad_id": "S"}, escouade) == set(), (
        "une figurine sans hauteur propre hérite de celle de son escouade (`_model_height_of`), "
        "qui passe sous l'étage : sans cet héritage, un état de test 2D lèverait"
    )


def test_le_voile_rouge_de_deploiement_refuse_le_personnage_sous_l_etage(gs):
    """VERROU + contre-épreuve dans le MÊME plan : deux figurines, deux verdicts, même case.

    Les avoir ensemble interdit qu'un refus global (zone, mur, hors plateau) passe pour une
    décision de clairance — il frapperait les deux.
    """
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


#: Colonne d'où un socle LARGE déborde sous l'étage alors qu'un socle étroit non. Calibrée par
#: balayage : à x10, les rayons 1 et 5 changent de verdict entre les colonnes 107 et 110.
_HORS_ETAGE_MAIS_LARGE = 107


@pytest.fixture
def gs_socles() -> Dict[str, Any]:
    """Deux figurines de MÊME hauteur, de socles différents — l'escouade porte le socle étroit.

    La hauteur est neutralisée (les deux dépassent la clairance) : seul le RAYON peut décider,
    donc le test ne peut pas passer au vert par l'effet de la correction voisine.
    """
    return _etat([
        {
            "col": DEPART[0], "row": DEPART[1], "level": 0, "VALUE": 10,
            "MODEL_HEIGHT": HAUTEUR_PERSONNAGE,
        },
        {
            "col": DEPART[0], "row": DEPART[1] + 20, "level": 0, "VALUE": 10,
            "MODEL_HEIGHT": HAUTEUR_PERSONNAGE, "BASE_SIZE": 5,
        },
    ], cohesion=20)


def test_le_voile_rouge_de_deploiement_mesure_le_socle_de_la_figurine(gs_socles):
    """VERROU : le disque de clairance a le RAYON de la figurine, pas celui de l'escouade.

    Le déploiement testait le débordement avec le socle de l'ESCOUADE alors qu'il lisait déjà
    celui de la figurine pour le reste de son verdict — l'autre moitié du même gabarit.
    """
    # Écart de 6 sous-hexes, calibré entre deux murs : en dessous, le disque du socle large
    # chevauche sa voisine (collision intra-escouade) ; au-delà, la cohésion rougit les deux.
    # Dans les deux cas le test cesserait de mesurer le rayon de clairance.
    etat = deployment_preview_plan(gs_socles, "S", [
        ("S#0", _HORS_ETAGE_MAIS_LARGE, 100, 0),
        ("S#1", _HORS_ETAGE_MAIS_LARGE, 106, 0),
    ])

    assert etat["per_model"]["S#0"] is True, (
        f"le socle étroit est refusé en colonne {_HORS_ETAGE_MAIS_LARGE} : il ne déborde pas sous "
        "l'étage, le refus vient d'ailleurs et le test ne mesure plus le rayon"
    )
    assert etat["per_model"]["S#1"] is False, (
        "le socle LARGE est accepté alors que son disque déborde sous un étage qui ne le laisse "
        "pas passer : le rayon de clairance est pris sur l'escouade"
    )


def test_la_formation_compacte_ne_pose_pas_le_personnage_sous_l_etage(gs):
    """La formation automatique place les figurines une par une : chacune à SON gabarit."""
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
