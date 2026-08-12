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

from pathlib import Path
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
from engine.phase_handlers.shared_utils import build_enemy_adjacent_hexes, build_units_cache
from tests._state_invariants import turn_state_invariants, unit_invariants
from tests.unit.engine._config_helpers import build_game_rules, build_move_rules

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


def _unit(uid: str, player: int, models: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    return {**unit_invariants(),
        "id": uid, "player": player,
        "col": models[0]["col"], "row": models[0]["row"],
        "HP_CUR": len(models), "HP_MAX": len(models), "VALUE": 100, "OC": 1, "T": 4,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "SHOOT_LEFT": 1, "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [], "CC_WEAPONS": [], "BASE_SIZE": 1, "BASE_SHAPE": "round",
        # MOVE = 3" : le BFS atteint le couloir avec 107 cases de marge pour la contre-épreuve,
        # et coûte 4x moins que 6" (0,08 s contre 0,37 s par pool). En dessous de 2" il ne reste
        # que 6 cases — trop mince pour que la contre-épreuve prouve quoi que ce soit.
        "MODEL_HEIGHT": HAUTEUR_ESCOUADE, "MOVE": 3 * ISH, "UNIT_RULES": [],
        # INFANTRY : sans mot-clé, une figurine ne peut pas finir en hauteur (13.06) et les
        # chemins d'étage sortent avant d'atteindre la clairance.
        "UNIT_KEYWORDS": [{"keywordId": "infantry"}],
        "models": list(models),
    }


def _etat(models: Sequence[Dict[str, Any]], cohesion: int = 2) -> Dict[str, Any]:
    """Plateau x10 avec un couloir sous un étage bas, l'escouade ``S`` et un ennemi ``E``.

    ``cohesion`` : portée de cohésion en sous-hexes. Élargie par le test de SOCLE, où les deux
    figurines doivent s'écarter assez pour que le disque de la plus large ne chevauche pas sa
    voisine — sinon c'est la collision intra-escouade, et non la clairance, qui rougit.
    """
    units = [
        _unit("S", 1, list(models)),
        _unit("E", 2, [{"col": ENNEMI[0], "row": ENNEMI[1], "level": 0, "VALUE": 10}]),
    ]
    state: Dict[str, Any] = {
        **turn_state_invariants(),
        # Règles RÉELLES (`build_game_rules` / `build_move_rules`) : un sous-ensemble recopié à la
        # main laisserait ce test sur des règles figées, et toute clé nouvellement requise par le
        # moteur manquerait ici en silence. Seules les deux valeurs que le test PILOTE sont
        # surchargées — la zone d'engagement à l'échelle du plateau, et la cohésion.
        "config": {
            "game_rules": build_game_rules(
                engagement_zone=2 * ISH, unit_model_cohesion_range=cohesion
            ),
            "move": build_move_rules(),
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
        # Jet de charge de 6" : le champ multi-niveaux balaie un rayon proportionnel au jet, et
        # 12" coûtaient 3,7 s par appel pour un ennemi à 2,5" — pools rendus IDENTIQUES à 6"
        # (312 et 237 destinations, 75 et 0 cases sous l'étage). À 3" le pool du personnage se
        # vide et la contre-épreuve deviendrait vacante.
        "charge_roll_values": {"S": 6},
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
# Garde de source — les sites que les verrous ci-dessus n'atteignent pas
#
# Quatre des onze appels vivent sur des branches d'ÉTAGE (montée, descente, ILP d'autoplace) que
# les pools de plain-pied n'exécutent pas. Les couvrir par comportement demanderait une mise en
# scène multi-niveaux par site. Ce garde ne remplace pas un verrou de comportement — il ne dit
# rien de ce que le code CALCULE — mais il interdit la seule régression réaliste : quelqu'un qui
# repasse la hauteur de l'escouade, en silence.
#
# Deux choix de portée, tous deux payés d'un faux vert avant d'être pris :
# - il balaie TOUT `engine/phase_handlers/`, pas une liste de fichiers : le jour où une cinquième
#   phase apprend à consulter la clairance, elle est surveillée sans que personne y pense ;
# - dans chaque fichier trouvé, il interdit la PRÉSENCE des formes de lecture d'escouade au lieu
#   d'inspecter le voisinage de l'appel : la hauteur y transite parfois par une variable calculée
#   cinq lignes plus haut, qu'une fenêtre de texte ne verrait jamais.
# ─────────────────────────────────────────────────────────────────────────────

_PHASE_HANDLERS = Path(__file__).resolve().parents[3] / "engine" / "phase_handlers"
#: Les fichiers dont on SAIT qu'ils consultent la clairance. Ils ne bornent pas le balayage — ils
#: le rendent non vacant : si le motif cessait d'être trouvé (renommage de la primitive, appel
#: déplacé), un garde qui ne regarde rien afficherait « tout va bien ».
_CONSOMMATEURS_CONNUS = {
    "movement_handlers.py", "fight_handlers.py", "charge_handlers.py", "deployment_handlers.py",
}
#: Lectures de la hauteur d'ESCOUADE. `unit` est le nom que ces handlers donnent à l'entrée
#: d'escouade ; la figurine s'y appelle `model`, `m`, `sib` ou `rep_model`.
_HAUTEUR_D_ESCOUADE = (
    'require_key(unit, "MODEL_HEIGHT")',
    'unit["MODEL_HEIGHT"]',
    'unit.get("MODEL_HEIGHT"',
)


def _fichiers_consultant_la_clairance() -> Dict[str, str]:
    """{nom de fichier: source} des handlers qui appellent `low_clearance_ground_hexes`.

    Sa DÉFINITION vit dans `terrain_utils`, jamais ici : tout ce qui est trouvé est un APPEL.
    """
    trouves = {}
    for chemin in sorted(_PHASE_HANDLERS.glob("*.py")):
        source = chemin.read_text(encoding="utf-8")
        if "low_clearance_ground_hexes(" in source:
            trouves[chemin.name] = source
    return trouves


def test_le_balayage_de_la_clairance_voit_tous_les_consommateurs_connus():
    """Prémisse du garde : un balayage qui ne trouve rien passerait au vert sans rien vérifier."""
    trouves = set(_fichiers_consultant_la_clairance())

    assert _CONSOMMATEURS_CONNUS <= trouves, (
        f"consommateurs de clairance vus : {sorted(trouves)} ; il en manque parmi "
        f"{sorted(_CONSOMMATEURS_CONNUS)}. La primitive a été renommée ou l'appel déplacé — le "
        "garde ci-dessous ne surveille plus ce qu'il croit surveiller"
    )


def test_aucun_consommateur_de_clairance_ne_lit_la_hauteur_de_l_escouade():
    """VERROU DE SOURCE : la hauteur passée à la clairance vient toujours d'une FIGURINE."""
    fautifs = {
        nom: [f for f in _HAUTEUR_D_ESCOUADE if f in source]
        for nom, source in _fichiers_consultant_la_clairance().items()
        if any(f in source for f in _HAUTEUR_D_ESCOUADE)
    }

    assert not fautifs, (
        f"{fautifs} : ces fichiers consultent la clairance ET lisent la hauteur de l'ESCOUADE, "
        "alors que leurs pools raisonnent par figurine (§13.06). Passer par "
        "`_model_height_of(model, unit)`"
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
