"""10.07 — éligibilité au tir indirect : le premier type de tir qui n'exclut pas les autres.

Ce que ce fichier verrouille, et pourquoi ça n'allait pas de soi :

`resolve_squad_shooting_type` DÉRIVAIT le type de tir, et son docstring justifiait cette
dérivation par un invariant — « un seul type peut s'appliquer, les conditions engaged/unengaged
et advance/pas d'advance sont exclusives ». L'invariant est vrai des trois types implémentés
jusqu'au 2026-08-16. **10.07 le casse** : sa condition d'éligibilité (« Unengaged and did not
make an advance move this turn ») est mot pour mot celle de 10.04 normal. Une unité unengaged,
qui n'a pas avancé et qui porte une arme [INDIRECT FIRE] est éligible aux DEUX, et §10.02 dit
que c'est le joueur qui tranche (« Select ONE shooting type that unit is eligible to make »).

D'où la séparation vérifiée ici : `eligible_squad_shooting_types` rend l'ENSEMBLE jouable,
`resolve_squad_shooting_type` rend le DÉFAUT. Le dernier test est le plus important du fichier :
il atteste que cette pièce ne rend l'indirect sélectionnable par PERSONNE. La spec impose la
résolution avant la décision — un type choisissable dont les pénalités ne seraient pas encore
appliquées produirait des parties fausses, et l'agent apprendrait dessus.
"""
from __future__ import annotations

import pytest

from engine.phase_handlers import shared_utils as SU
from engine.phase_handlers.shared_utils import (
    SHOOTING_TYPE_ASSAULT,
    SHOOTING_TYPE_INDIRECT,
    SHOOTING_TYPE_NORMAL,
    SQUAD_ACTION_SHOOT_INDIRECT_SLOT_BASE,
    build_squad_action_mask,
    eligible_squad_shooting_types,
    resolve_squad_shooting_type,
    shooting_type_allows_weapon,
)
from tests._state_invariants import turn_state_invariants

INDIRECT = {"display_name": "Impaler Cannon", "RNG": 180, "NB": 4, "ATK": 4, "STR": 5,
            "AP": -1, "DMG": 1, "WEAPON_RULES": ["HEAVY", "INDIRECT_FIRE"], "code": "test_indirect_weapon"}
DIRECT = {"display_name": "Bolt Rifle", "RNG": 120, "NB": 2, "ATK": 3, "STR": 4,
          "AP": -1, "DMG": 1, "WEAPON_RULES": [], "code": "test_direct_weapon"}


def _gs(weapons, *, advanced=False, engaged_enemy=False):
    """Un tireur '1' (unengagé, immobile) et un ennemi '101' hors zone d'engagement.

    `engaged_enemy` colle l'ennemi au contact : c'est ce qui bascule l'unité en 10.06 et doit
    donc RETIRER l'indirect de l'ensemble (10.07 exige « unengaged »).
    """
    enemy_pos = (51, 50) if engaged_enemy else (300, 300)
    models = {
        "1#0": {"id": "1#0", "squad_id": "1", "player": 0, "col": 50, "row": 50,
                "RNG_WEAPONS": list(weapons), "CC_WEAPONS": [], "unit_keywords": []},
        "101#0": {"id": "101#0", "squad_id": "101", "player": 1, "col": enemy_pos[0],
                  "row": enemy_pos[1], "RNG_WEAPONS": [], "CC_WEAPONS": [],
                  "unit_keywords": []},
    }
    return {
        **turn_state_invariants(),
        "turn": 1, "phase": "shoot",
        "models_cache": models,
        "squad_models": {"1": ["1#0"], "101": ["101#0"]},
        "units": [{"id": "1", "player": 0, "unitType": "HiveGuardImpalerCannon"},
                  {"id": "101", "player": 1, "unitType": "Intercessor"}],
        "unit_by_id": {
            "1": {"id": "1", "player": 0, "UNIT_RULES": [], "deployed_on_turn": 0},
            "101": {"id": "101", "player": 1, "UNIT_RULES": [], "deployed_on_turn": 0},
        },
        "units_cache": {
            "1": {"col": 50, "row": 50, "player": 0, "BASE_SHAPE": "round", "BASE_SIZE": 6,
                  "occupied_hexes": {(50, 50)}, "occupied_hexes_by_model": {"1#0": (50, 50)},
                  "floor_height_by_model": {"1#0": 0.0}},
            "101": {"col": enemy_pos[0], "row": enemy_pos[1], "player": 1,
                    "BASE_SHAPE": "round", "BASE_SIZE": 6, "occupied_hexes": {enemy_pos},
                    "occupied_hexes_by_model": {"101#0": enemy_pos},
                    "floor_height_by_model": {"101#0": 0.0}},
        },
        # `engagement_zone` est DÉJÀ en sous-hexes ici (w40k_core la scale au chargement) : c'est
        # elle qui décide « unengaged », donc la première clause d'éligibilité de 10.04 et 10.07.
        "config": {"game_rules": {"engagement_zone": 5}},
        "units_shot": set(),
        "units_fled": set(),
        "units_advanced": {"1"} if advanced else set(),
        "units_moved": set(),
        "inches_to_subhex": 5,
    }


def test_une_arme_indirecte_ouvre_un_second_type_de_tir():
    """Le cœur du chantier : deux types éligibles pour la MÊME unité, dans le MÊME état.

    C'est ce que l'ancienne dérivation ne pouvait pas représenter."""
    gs = _gs([INDIRECT])

    assert eligible_squad_shooting_types(gs, "1") == (
        SHOOTING_TYPE_NORMAL, SHOOTING_TYPE_INDIRECT,
    )


def test_sans_arme_indirecte_l_ensemble_se_reduit_au_defaut():
    """Contre-épreuve : la deuxième clause de 10.07 (« has one or more [INDIRECT FIRE]
    weapons ») est bien testée, et pas seulement la première."""
    gs = _gs([DIRECT])

    assert eligible_squad_shooting_types(gs, "1") == (SHOOTING_TYPE_NORMAL,)


def test_apres_un_advance_l_indirect_disparait():
    """10.07 exige « did not make an advance move this turn ». Une unité qui a avancé bascule en
    10.05 assault — et l'indirect n'est PAS ouvert, même si elle porte l'arme.

    Discrimination réelle : l'arme [INDIRECT FIRE] du décor est aussi [HEAVY], jamais [ASSAULT],
    donc sans une seconde arme l'unité ne tirerait pas du tout. On en ajoute une pour que le cas
    testé soit bien « advance ⇒ pas d'indirect » et non « advance ⇒ pas de tir »."""
    assault_weapon = {**DIRECT, "WEAPON_RULES": ["ASSAULT"]}
    gs = _gs([INDIRECT, assault_weapon], advanced=True)

    assert resolve_squad_shooting_type(gs, "1") == SHOOTING_TYPE_ASSAULT
    assert SHOOTING_TYPE_INDIRECT not in eligible_squad_shooting_types(gs, "1")


def test_la_perte_de_la_seule_porteuse_referme_l_indirect():
    """L'éligibilité se lit sur les figurines VIVANTES, et ce test doit exercer CE filtre-là.

    ⚠️ Écrit d'abord avec une escouade d'UNE figurine, il passait sans rien prouver : sans
    figurine vivante, `resolve_squad_shooting_type` rend déjà `None` et l'ensemble est vide pour
    cette raison-là, jamais parce qu'on a regardé les armes. La mutation qui retire le filtre le
    laissait VERT. Le scénario réel est une escouade qui **survit à la perte de sa porteuse** :
    deux figurines, seule celle qui porte l'Impaler Cannon meurt. L'unité tire toujours (10.04
    normal), mais 10.07 doit s'être refermé.
    """
    gs = _gs([DIRECT])
    gs["models_cache"]["1#1"] = {
        "id": "1#1", "squad_id": "1", "player": 0, "col": 50, "row": 51,
        "RNG_WEAPONS": [INDIRECT], "CC_WEAPONS": [], "unit_keywords": [],
    }
    gs["squad_models"]["1"] = ["1#0", "1#1"]

    assert eligible_squad_shooting_types(gs, "1") == (
        SHOOTING_TYPE_NORMAL, SHOOTING_TYPE_INDIRECT,
    ), "prémisse : la porteuse vivante ouvre bien l'indirect"

    del gs["models_cache"]["1#1"]

    assert resolve_squad_shooting_type(gs, "1") == SHOOTING_TYPE_NORMAL, (
        "l'escouade tire toujours : c'est bien le filtre des ARMES qu'on observe ensuite"
    )
    assert eligible_squad_shooting_types(gs, "1") == (SHOOTING_TYPE_NORMAL,)


def test_une_escouade_qui_ne_peut_pas_tirer_rend_un_ensemble_vide():
    """Même état que le `None` de la dérivation, et lu au même endroit : une escouade ayant déjà
    tiré n'a aucun type jouable, pas « le type normal »."""
    gs = _gs([INDIRECT])
    gs["units_shot"] = {"1"}

    assert resolve_squad_shooting_type(gs, "1") is None
    assert eligible_squad_shooting_types(gs, "1") == ()


def test_le_tir_indirect_ne_restreint_pas_la_selection_d_armes():
    """Encadré du PDF 10 : « its other weapons can still target other visible targets ».

    10.07 est le seul type de tir qui ne filtre pas les armes — 10.05 n'autorise que les
    [ASSAULT], 10.06 que les [CLOSE-QUARTERS] pour les figurines non-M/V. Les pénalités de 10.07
    portent sur les ATTAQUES des armes indirectes, pas sur ce qui est sélectionnable."""
    unit = {"id": "1", "UNIT_RULES": []}
    model = {"id": "1#0", "unit_keywords": []}

    assert shooting_type_allows_weapon(SHOOTING_TYPE_INDIRECT, unit, model, INDIRECT) is True
    assert shooting_type_allows_weapon(SHOOTING_TYPE_INDIRECT, unit, model, DIRECT) is True


def test_l_ordre_de_l_ensemble_est_stable_et_commence_par_le_defaut():
    """Un masque d'action bâti sur un ensemble non ordonné rendrait le comportement de l'agent
    non reproductible d'une exécution à l'autre. L'ordre est donc contractuel, et le défaut
    vient en tête — c'est lui que joue une unité qui ne choisit rien."""
    gs = _gs([INDIRECT])
    types = eligible_squad_shooting_types(gs, "1")

    assert types[0] == resolve_squad_shooting_type(gs, "1")
    assert list(types) == sorted(types, key=lambda t: 0 if t == SHOOTING_TYPE_NORMAL else 1)


def test_cette_piece_ne_rend_l_indirect_selectionnable_par_personne():
    """⚠️ LE TEST LE PLUS IMPORTANT DU FICHIER, et le seul qui protège les parties.

    La spec impose la RÉSOLUTION avant la DÉCISION : tant que le plancher d'échec, le couvert
    octroyé et l'interdiction de relance ne sont pas appliqués, une unité qui jouerait l'indirect
    tirerait sans aucune de ses pénalités — une règle à moitié appliquée, sur laquelle l'agent
    s'entraînerait. Cette pièce ne fait qu'AJOUTER un type à un ensemble consultatif ; le type
    RETENU, celui que le moteur résout réellement, ne doit pas avoir bougé d'un iota.

    Ce test reste VERT même une fois la pièce « décision » câblée : il appelle
    `resolve_squad_shooting_type` directement, sans poser de choix via
    `squad_shooting_type_choose`. Seul un test qui pose le choix puis vérifie la résolution
    deviendrait ROUGE — et devrait alors être remplacé par son inverse.
    """
    gs = _gs([INDIRECT])

    assert resolve_squad_shooting_type(gs, "1") == SHOOTING_TYPE_NORMAL, (
        "le type RETENU doit rester 10.04 normal : rien ne choisit encore l'indirect"
    )


def test_slot_indirect_masque_si_ennemi_verrouille_par_un_allie(monkeypatch):
    """Le garde locked_by_ally de la boucle INDIRECT est symétrique au garde du tir normal.

    Ennemi E bord-à-bord d'un allié A : le slot indirect de E doit rester à 0 même si l'arme
    peut l'atteindre. Sans le garde, `_squad_can_shoot_target_under_type` retournerait True et
    le slot s'ouvrirait — permettant à l'agent de tirer à travers le corps à corps de ses alliés.

    Double monkeypatch pour isoler le garde :
    - `_squad_can_shoot_target_under_type` → True : l'arme atteindrait E sans le garde.
    - `_model_can_shoot_target_with_weapon` → False : slots normaux fermés, seul le chemin
      indirect est exercé ; évite aussi les KeyError de géométrie sur les modèles légers de _gs.
    """
    monkeypatch.setattr(SU, "_squad_can_shoot_target_under_type", lambda gs, sid, esid, t: True)
    monkeypatch.setattr(SU, "_model_can_shoot_target_with_weapon", lambda gs, m, esid, widx: False)

    # Allié "2" en (300, 299) : 1 colonne de l'ennemi "101" (300, 300) — dans l'EZ de 5.
    ally_pos = (300, 299)
    gs = _gs([INDIRECT])
    # Ajoute l'allié dans units_cache et squad_models.
    gs["units_cache"]["2"] = {
        "col": ally_pos[0], "row": ally_pos[1], "player": 0,
        "BASE_SHAPE": "round", "BASE_SIZE": 6, "occupied_hexes": {ally_pos},
        "occupied_hexes_by_model": {"2#0": ally_pos},
        "floor_height_by_model": {"2#0": 0.0},
    }
    gs["squad_models"]["2"] = ["2#0"]
    gs["models_cache"]["2#0"] = {
        "id": "2#0", "squad_id": "2", "player": 0,
        "col": ally_pos[0], "row": ally_pos[1],
        "RNG_WEAPONS": [], "CC_WEAPONS": [], "unit_keywords": [],
    }

    slot_map = ["101", None, None, None, None]
    mask = build_squad_action_mask(gs, "1", enemy_slot_ids=slot_map)

    assert mask[SQUAD_ACTION_SHOOT_INDIRECT_SLOT_BASE] == 0, (
        "ennemi dans l'EZ d'un allié : slot indirect doit rester fermé"
    )

    # Contre-épreuve : sans allié, le slot s'ouvre (monkeypatch retourne True).
    del gs["units_cache"]["2"]
    mask_sans_allie = build_squad_action_mask(gs, "1", enemy_slot_ids=slot_map)

    assert mask_sans_allie[SQUAD_ACTION_SHOOT_INDIRECT_SLOT_BASE] == 1, (
        "sans allié bord-à-bord : le slot indirect doit s'ouvrir"
    )
