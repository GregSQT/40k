"""`RNG_WEAPONS` / `CC_WEAPONS` : liste vide = pas d'arme, cle absente = entite mal construite.

Une trentaine de sites des gestionnaires de phase lisaient ces collections par
`entity.get("RNG_WEAPONS", [])` (ou `if entity.get("CC_WEAPONS"):`). Ce defaut CONFOND deux
etats que la donnee distingue deja :

- LISTE VIDE : l'entite n'a pas d'arme de ce type. Cas metier reel et ecrit dans la donnee —
  21 des 179 datasheets declarent `RNG_WEAPONS: []` (Genestealer, Hormagaunt, Assault
  Terminator... la melee pure) et 1 declare `CC_WEAPONS: []` (Mucolid).
- CLE ABSENTE : dictionnaire incomplet. Tous les constructeurs posent la cle
  inconditionnellement, donc ca n'arrive que sur une entite mal construite.

Avec le defaut, une figurine incomplete se comportait EXACTEMENT comme un Genestealer :
elle passait tous les gates « a-t-elle une arme de tir ? » par la negative, sans un signal.
La lecture passe desormais par `engine.utils.weapon_helpers.ranged_weapons/melee_weapons`,
qui exigent la cle et laissent la liste vide etre ce qu'elle est.

Meme forme que `test_command_phase.py::test_engine_units_all_carry_battle_shocked_field` :
on verifie le CONSTRUCTEUR, pas seulement le consommateur.
"""
from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import numpy as np
import pytest

from engine.observation_builder import ObservationBuilder
from engine.reward_calculator import RewardCalculator
from engine.utils.weapon_helpers import melee_weapons, ranged_weapons
from engine.w40k_core import W40KEngine


# ─────────────────────────────────────────────────────────────────────────────
# Les accesseurs
# ─────────────────────────────────────────────────────────────────────────────

def test_liste_vide_est_un_etat_valide():
    """« Pas d'arme de tir » n'est pas une erreur : c'est ce que declarent 21 datasheets."""
    assert ranged_weapons({"id": "1", "RNG_WEAPONS": []}) == []
    assert melee_weapons({"id": "1", "CC_WEAPONS": []}) == []


def test_liste_pleine_rendue_telle_quelle():
    profils = [{"display_name": "Bolter"}]
    assert ranged_weapons({"id": "1", "RNG_WEAPONS": profils}) is profils
    assert melee_weapons({"id": "1", "CC_WEAPONS": profils}) is profils


@pytest.mark.parametrize(
    "accesseur,cle", [(ranged_weapons, "RNG_WEAPONS"), (melee_weapons, "CC_WEAPONS")]
)
def test_cle_absente_leve(accesseur, cle):
    """C'est TOUT l'objet du correctif : l'absence de cle ne peut plus se faire passer
    pour une unite de melee pure."""
    with pytest.raises(Exception) as exc:
        accesseur({"id": "7"})

    assert cle in str(exc.value)


@pytest.mark.parametrize(
    "accesseur,cle", [(ranged_weapons, "RNG_WEAPONS"), (melee_weapons, "CC_WEAPONS")]
)
def test_valeur_non_liste_leve(accesseur, cle):
    with pytest.raises(TypeError) as exc:
        accesseur({"id": "7", cle: "bolter"})

    assert cle in str(exc.value) and "7" in str(exc.value)


# ─────────────────────────────────────────────────────────────────────────────
# Le constructeur du moteur pose toujours les deux cles
# ─────────────────────────────────────────────────────────────────────────────

def _weapon_cfg() -> Dict[str, Any]:
    return {"ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
            "WEAPON_RULES": [], "display_name": "Test"}


def _unit_cfg(uid: int, player: int, col: int, row: int, *, ranged: bool) -> Dict[str, Any]:
    """`ranged=False` reproduit une unite de MELEE PURE : `RNG_WEAPONS` vide, pas absent."""
    return {"id": uid, "player": player, "col": col, "row": row,
            "unitType": "T", "DISPLAY_NAME": f"U{uid}",
            "HP_CUR": 3, "HP_MAX": 3, "MOVE": 6, "T": 4,
            "ARMOR_SAVE": 4, "INVUL_SAVE": 7,
            "SHOOT_LEFT": 1, "ATTACK_LEFT": 1,
            "RNG_WEAPONS": [_weapon_cfg()] if ranged else [],
            "CC_WEAPONS": [_weapon_cfg()],
            "UNIT_RULES": [], "UNIT_KEYWORDS": [],
            "LD": 7, "OC": 1, "VALUE": 100, "ICON": "t",
            "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
            "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5}


def _minimal_config() -> Dict[str, Any]:
    obs = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    return {
        "board": {"default": {"cols": 15, "rows": 13, "hex_radius": 1.0,
                              "margin": 0.0, "wall_hexes": [],
                              "objectives": [{"id": 1, "name": "Alpha", "hexes": [[5, 5]]}],
                              "inches_to_subhex": 1}},
        "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5,
                       "max_base_size_hex": 35},
        "charge": {"charge_max_distance": 12},
        "pve_mode": False,
        "observation_params": obs,
        "training_config": {"observation_params": obs, "max_turns_per_episode": 3},
        # Une unite de tir ET une unite de melee pure : le contrat doit tenir pour les deux.
        "units": [_unit_cfg(1, 1, 3, 3, ranged=True), _unit_cfg(2, 2, 10, 10, ranged=False)],
    }


@pytest.fixture(autouse=True)
def mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        W40KEngine, "_build_observation",
        lambda self, *_a, **_k: np.zeros(ObservationBuilder.SQUAD_OBS_SIZE_TARGET),
    )
    monkeypatch.setattr(RewardCalculator, "calculate_reward", lambda self, *a, **kw: 0.0)


def _make_engine() -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        return W40KEngine(config=_minimal_config())


def test_toutes_les_unites_du_moteur_portent_les_deux_cles():
    """Le constructeur d'unites pose les deux collections, meme vides."""
    eng = _make_engine()
    eng.reset()

    units = eng.game_state["units"]
    assert units, "moteur sans unites : test aveugle"
    for unit in units:
        assert ranged_weapons(unit) is not None
        assert melee_weapons(unit) is not None
    # Et l'unite de melee pure porte bien une LISTE VIDE, pas une cle absente.
    melee_pure = next(u for u in units if str(u["id"]) == "2")
    assert ranged_weapons(melee_pure) == []


def test_toutes_les_figurines_du_models_cache_portent_les_deux_cles():
    """`_build_models_for_unit` propage les deux collections a chaque figurine."""
    eng = _make_engine()
    eng.reset()

    models = eng.game_state["models_cache"]
    assert models, "models_cache vide : test aveugle"
    for mid, model in models.items():
        assert "RNG_WEAPONS" in model, f"figurine {mid} sans RNG_WEAPONS"
        assert "CC_WEAPONS" in model, f"figurine {mid} sans CC_WEAPONS"


# ─────────────────────────────────────────────────────────────────────────────
# Les sites d'appel : la distinction doit se voir DEPUIS le moteur, pas seulement
# dans l'accesseur
# ─────────────────────────────────────────────────────────────────────────────

def test_selection_d_arme_de_melee_distingue_vide_et_absent():
    """`_select_fight_weapon_indices_for_fig` lisait `attacker.get("CC_WEAPONS", [])` :
    une figurine incomplete rendait « aucune arme selectionnee », exactement comme une
    figurine sans arme de melee."""
    from engine.phase_handlers.shared_utils import _select_fight_weapon_indices_for_fig

    # Liste vide : etat valide -> aucune arme selectionnee, sans erreur.
    assert _select_fight_weapon_indices_for_fig({"id": "A1", "CC_WEAPONS": []}, 4, 3, 7) == []

    # Cle absente : figurine mal construite -> erreur explicite.
    with pytest.raises(Exception) as exc:
        _select_fight_weapon_indices_for_fig({"id": "A1"}, 4, 3, 7)
    assert "CC_WEAPONS" in str(exc.value)


def test_eligibilite_de_tir_distingue_vide_et_absent():
    """Jumeau au tir : `_model_can_shoot_target` lisait `attacker_model.get("RNG_WEAPONS", [])`."""
    from engine.phase_handlers.shared_utils import _model_can_shoot_target

    # Liste vide : la figurine ne peut pas tirer, sans erreur.
    fig_vide = {"id": "A1", "SHOOT_LEFT": 1, "RNG_WEAPONS": [], "selectedRngWeaponIndex": None}
    assert _model_can_shoot_target({}, fig_vide, "2") is False

    # Cle absente : erreur explicite.
    with pytest.raises(Exception) as exc:
        _model_can_shoot_target({}, {"id": "A1", "SHOOT_LEFT": 1}, "2")
    assert "RNG_WEAPONS" in str(exc.value)


# ─────────────────────────────────────────────────────────────────────────────
# La donnee reelle
# ─────────────────────────────────────────────────────────────────────────────

def test_les_rosters_portent_toujours_les_deux_cles_et_utilisent_la_liste_vide():
    """Preuve que la cle peut etre exigee ET que la liste vide est le cas metier reel."""
    from ai.unit_registry import UnitRegistry

    registry = UnitRegistry()
    sans_tir = []
    sans_melee = []
    for name, data in registry.units.items():
        assert "RNG_WEAPONS" in data, f"{name} sans RNG_WEAPONS"
        assert "CC_WEAPONS" in data, f"{name} sans CC_WEAPONS"
        if data["RNG_WEAPONS"] == []:
            sans_tir.append(name)
        if data["CC_WEAPONS"] == []:
            sans_melee.append(name)

    assert len(registry.units) == 179
    # Le cas metier existe VRAIMENT : sans lui, exiger la cle serait sans objet.
    assert len(sans_tir) == 21 and "Genestealer" in sans_tir
    assert sans_melee == ["Mucolid"]
