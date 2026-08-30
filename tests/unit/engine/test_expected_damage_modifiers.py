"""expected_damage() — modificateurs de la Primitive A et du Waaagh!

Verrous :
  1. Sans attacker_unit / game_state → seuil brut ATK, aucun modificateur.
  2. Attaquant supprimé → malus de seuil +1 (harder to hit), dégâts réduits.
  3. Might Is Right (hit_roll_bonus_fight) en mêlée → bonus de seuil -1, dégâts augmentés.
  4. Might Is Right ignoré au TIR (is_melee=False) → aucun effet.
  5. Waaagh! actif en mêlée → STR+1 et NB+1 appliqués, dégâts augmentés.

Convention de calcul des valeurs de référence (voir commentaire dans le module) :
  Arme : ATK=4, STR=4, AP=0, NB=2, DMG=1
  Cible : T=4, ARMOR_SAVE=5, INVUL_SAVE=7
  => wound_threshold(4,4)=4, save_threshold(5,7,0)=5, p_fail_save=4/6
  Base (ATK=4) : ev_per_attack=1/6, total=2/6=1/3
  Supprimé (ATK=5) : ev_per_attack=1/9, total=2/9
  Might Is Right (ATK=3) : ev_per_attack=2/9, total=4/9
  Waaagh (STR=5→wound 3+, NB=3) : ev_per_attack=2/9, total=3×2/9=2/3
"""
from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import pytest

from engine.utils.expected_damage import expected_damage


# ---------------------------------------------------------------------------
# Fixtures communes
# ---------------------------------------------------------------------------

_WEAPON: Dict[str, Any] = {
    "ATK": 4, "STR": 4, "AP": 0, "NB": 2, "DMG": 1,
    "WEAPON_RULES": [], "code": "test_blade", "display_name": "Blade",
}
_TARGET: Dict[str, Any] = {
    "T": 4, "ARMOR_SAVE": 5, "INVUL_SAVE": 7,
    "UNIT_KEYWORDS": [], "FACTION_KEYWORDS": [],
}
_BASE_ATTACKER: Dict[str, Any] = {
    "id": "1", "player": 1,
    "UNIT_RULES": [],
    "FACTION_KEYWORDS": [],
}
_MIGHT_IS_RIGHT_RULE = {"ruleId": "hit_roll_bonus_fight", "displayName": "Might Is Right"}

_BASE_GAME_STATE: Dict[str, Any] = {
    "suppressed_squads": {},
    # waaagh_applies_to_unit appelle _player_flag_map(game_state, "waaagh_active") en premier;
    # si toutes les valeurs sont False, sortie anticipée sans lire army_faction ni "units".
    "waaagh_active": {1: False, 2: False},
    "config": {"game_rules": {"bonus_malus_cap": 0}},
}


def _waaagh_game_state() -> Dict[str, Any]:
    """game_state minimal avec Waaagh! actif pour le joueur 1.

    army_faction() lit game_state["units"] pour valider que la faction déclarée est portée
    par au moins une unité du joueur — il faut donc une entrée minimale dans "units".
    """
    return {
        "suppressed_squads": {},
        "waaagh_active": {1: True, 2: False},
        "config": {"army_faction": {"1": "ORKS", "2": "TYRANIDS"}, "game_rules": {"bonus_malus_cap": 0}},
        "units": [
            {"id": "1", "player": 1, "FACTION_KEYWORDS": ["ORKS"]},
        ],
    }


# ---------------------------------------------------------------------------
# 1. Aucun modificateur sans contexte
# ---------------------------------------------------------------------------

def test_no_context_returns_base_damage() -> None:
    """Sans attacker_unit ni game_state, le seuil brut ATK est utilisé.

    Verrou de régression : si la fonction commençait à lire un état absent,
    elle lèverait plutôt que de renvoyer la valeur de référence.
    """
    result = expected_damage(_WEAPON, _TARGET)
    assert result == pytest.approx(1 / 3)


# ---------------------------------------------------------------------------
# 2. Suppression → seuil +1 (ATK 4 → 5)
# ---------------------------------------------------------------------------

def test_suppressed_attacker_reduces_damage() -> None:
    """Un attaquant supprimé touche sur 5+ au lieu de 4+ : moins de dégâts espérés."""
    attacker = {**_BASE_ATTACKER}
    game_state = {**_BASE_GAME_STATE, "suppressed_squads": {"1": 1}}

    result_rng = expected_damage(_WEAPON, _TARGET, attacker, game_state, is_melee=False)
    result_cc = expected_damage(_WEAPON, _TARGET, attacker, game_state, is_melee=True)

    assert result_rng == pytest.approx(2 / 9)
    assert result_cc == pytest.approx(2 / 9)


def test_non_suppressed_attacker_unaffected() -> None:
    """game_state sans suppression = aucun malus, valeur identique au cas sans contexte."""
    attacker = {**_BASE_ATTACKER}
    result = expected_damage(_WEAPON, _TARGET, attacker, _BASE_GAME_STATE, is_melee=False)
    assert result == pytest.approx(1 / 3)


# ---------------------------------------------------------------------------
# 3. Might Is Right en mêlée → seuil -1 (ATK 4 → 3)
# ---------------------------------------------------------------------------

def test_might_is_right_increases_melee_damage() -> None:
    """Might Is Right (hit_roll_bonus_fight) abaisse le seuil en mêlée : plus de dégâts."""
    attacker = {**_BASE_ATTACKER, "UNIT_RULES": [_MIGHT_IS_RIGHT_RULE]}

    result = expected_damage(_WEAPON, _TARGET, attacker, _BASE_GAME_STATE, is_melee=True)

    assert result == pytest.approx(4 / 9)


# ---------------------------------------------------------------------------
# 4. Might Is Right ignoré au tir
# ---------------------------------------------------------------------------

def test_might_is_right_does_not_apply_to_ranged() -> None:
    """Might Is Right est une règle de mêlée : aucun effet au tir (is_melee=False)."""
    attacker = {**_BASE_ATTACKER, "UNIT_RULES": [_MIGHT_IS_RIGHT_RULE]}

    result_rng = expected_damage(_WEAPON, _TARGET, attacker, _BASE_GAME_STATE, is_melee=False)
    result_no_ctx = expected_damage(_WEAPON, _TARGET)

    assert result_rng == pytest.approx(result_no_ctx)


# ---------------------------------------------------------------------------
# 5. Waaagh! en mêlée → STR+1, NB+1
# ---------------------------------------------------------------------------

def test_waaagh_increases_melee_damage() -> None:
    """Waaagh! (08.04) : +1 STR et +1 NB sur toutes les armes de mêlée de l'unité ORKS."""
    attacker = {**_BASE_ATTACKER, "FACTION_KEYWORDS": ["ORKS"]}
    game_state = _waaagh_game_state()

    result = expected_damage(_WEAPON, _TARGET, attacker, game_state, is_melee=True)

    # STR 4→5 : wound sur 3+ ; NB 2→3 ; ATK inchangé (pas de Might Is Right)
    assert result == pytest.approx(2 / 3)


def test_waaagh_does_not_apply_to_ranged() -> None:
    """Waaagh! ne modifie que les armes de mêlée : is_melee=False → aucun bonus STR/NB."""
    attacker = {**_BASE_ATTACKER, "FACTION_KEYWORDS": ["ORKS"]}
    game_state = _waaagh_game_state()

    result_rng = expected_damage(_WEAPON, _TARGET, attacker, game_state, is_melee=False)
    assert result_rng == pytest.approx(1 / 3)


def test_waaagh_inactive_no_bonus() -> None:
    """Waaagh! non actif (waaagh_active=False) → aucun bonus même pour une unité ORKS."""
    attacker = {**_BASE_ATTACKER, "FACTION_KEYWORDS": ["ORKS"]}
    game_state = {
        **_waaagh_game_state(),
        "waaagh_active": {1: False, 2: False},
    }

    result = expected_damage(_WEAPON, _TARGET, attacker, game_state, is_melee=True)
    assert result == pytest.approx(1 / 3)


# ---------------------------------------------------------------------------
# 6. expected_damage utilise le hit_target retourné par resolve_hit_roll_modifiers
# ---------------------------------------------------------------------------

def test_hit_modifier_applied_via_resolve_hit_roll_modifiers() -> None:
    """Le hit_target ajusté par resolve_hit_roll_modifiers est bien utilisé dans le calcul.

    On patch resolve_hit_roll_modifiers pour simuler bonus=2 cappé à 1 (hit 3+)
    puis bonus=2 sans cap (hit 2+). La logique de cap est interne à resolve_hit_roll_modifiers
    (testée dans shared_utils) ; ici on vérifie que expected_damage utilise le retour.

    Arme ATK=4, hit 3+ → p_hit=4/6, wound(4,4)=4+, save(5,7,0)=5+ → p_fail=4/6
      ev/atk = 4/6×3/6×4/6×1 = 2/9   total = 2×2/9 = 4/9

    hit 2+ → p_hit=5/6   →   ev/atk = 5/6×3/6×4/6 = 5/18   total = 2×5/18 = 5/9
    """
    attacker = {**_BASE_ATTACKER}
    game_state = {**_BASE_GAME_STATE}

    _resolve = "engine.utils.expected_damage.resolve_hit_roll_modifiers"

    with patch(_resolve, return_value=(3, None, None)):
        result_cap1 = expected_damage(_WEAPON, _TARGET, attacker, game_state, is_melee=True)

    with patch(_resolve, return_value=(2, None, None)):
        result_cap0 = expected_damage(_WEAPON, _TARGET, attacker, game_state, is_melee=True)

    assert result_cap1 == pytest.approx(4 / 9)
    assert result_cap0 == pytest.approx(5 / 9)
