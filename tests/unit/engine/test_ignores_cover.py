"""IGNORES COVER (24.18) dans le chemin VIF de resolution du tir.

Regle projet (Documentation/40k_rules/24 Core abilities.pdf, 24.18) :
« Each time an attack is made with an [IGNORES COVER] weapon, the target cannot have
the benefit of cover against that attack (13.08). »

Verrou : `_cover_worsened_bs` (shared_utils, chemin vif partage gym/PvP) doit court-circuiter
le Benefit of Cover (13.08) quand l'arme active porte la regle IGNORES_COVER, AVANT tout calcul
de LoS. Sans le flag, le couvert s'applique normalement (worsen BS by 1) — c'est la
contre-epreuve : si le court-circuit disparait, `test_ignores_cover_bypasses_cover` rougit.
"""
import pytest

from engine.phase_handlers import shooting_handlers
from engine.phase_handlers.shared_utils import _cover_worsened_bs, _manual_roll_intent


def _minimal_shoot_game_state(weapon_rules):
    """game_state minimal pour exercer _manual_roll_intent end-to-end (1 tireur, 1 cible)."""
    weapon = {
        "ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1,
        "WEAPON_RULES": weapon_rules, "display_name": "Test Gun",
    }
    attacker = {"id": "A1", "squad_id": "1", "T": 4, "RNG_WEAPONS": [weapon]}
    target = {
        "id": "T1", "T": 4, "HP_CUR": 2, "HP_MAX": 2,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "role": None, "unitType": "Grunt",
    }
    game_state = {
        "models_cache": {"A1": attacker, "T1": target},
        "squad_models": {"2": ["T1"]},
        "units_cache": {"2": {"VALUE": 10.0, "player": 1}},
        "squad_cache": {"2": {"model_count_at_start": 1}},
        # _manual_roll_intent résout attaquant/cible (rerolls to-wound) via get_unit_by_id -> unit_by_id.
        "unit_by_id": {"1": {"id": "1", "UNIT_RULES": []}, "2": {"id": "2", "UNIT_RULES": []}},
    }
    intent = {"model_id": "A1", "target_unit_id": "2", "weapon_index": 0, "n_attacks_resolved": 1}
    return game_state, intent


def _force_cover_true(monkeypatch, calls):
    """compute_unit_los renvoie cover=True ; enregistre chaque appel pour prouver
    (ou non) le court-circuit. _get_unit_by_id renvoie une unite factice non-None."""
    def fake_los(game_state, shooter, target):
        calls.append(("los", shooter, target))
        return {"cover": True}

    monkeypatch.setattr(shooting_handlers, "compute_unit_los", fake_los)
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})


def test_ignores_cover_bypasses_cover(monkeypatch):
    """Arme IGNORES_COVER : pas de malus (cover=False) MEME si la LoS donnerait cover=True,
    et le calcul de LoS n'est jamais atteint (court-circuit en tete)."""
    calls = []
    _force_cover_true(monkeypatch, calls)
    weapon = {"WEAPON_RULES": ["IGNORES_COVER"], "display_name": "Ignore Gun"}

    bs, cover = _cover_worsened_bs({}, {"squad_id": "1"}, "2", 3, weapon)

    assert bs == 3, "seuil de touche inchange sous IGNORES_COVER"
    assert cover is False, "IGNORES_COVER (24.18) : la cible ne peut pas avoir le benefit of cover"
    assert calls == [], "court-circuit avant LoS : compute_unit_los ne doit pas etre appele"


def test_no_ignores_cover_applies_cover(monkeypatch):
    """Sans IGNORES_COVER : le Benefit of Cover (13.08) s'applique — BS aggrave de 1."""
    calls = []
    _force_cover_true(monkeypatch, calls)
    weapon = {"WEAPON_RULES": ["HEAVY"], "display_name": "Plain Gun"}

    bs, cover = _cover_worsened_bs({}, {"squad_id": "1"}, "2", 3, weapon)

    assert bs == 4, "worsen the BS characteristic by 1 (13.08)"
    assert cover is True
    assert len(calls) == 1, "sans IGNORES_COVER, la LoS est bien consultee"


def test_ignores_cover_case_insensitive_and_parametrized(monkeypatch):
    """La detection tolere la casse et les entrees parametrees 'NAME:x'."""
    calls = []
    _force_cover_true(monkeypatch, calls)
    weapon = {"WEAPON_RULES": ["ignores_cover:1"], "display_name": "Odd Decl"}

    bs, cover = _cover_worsened_bs({}, {"squad_id": "1"}, "2", 5, weapon)

    assert (bs, cover) == (5, False)
    assert calls == []


def test_ignores_cover_bs6_stays_touch_on_6(monkeypatch):
    """Non-regression du clamp 13.08 : sans le flag, BS6 sous cover reste 6 (pas 7)."""
    calls = []
    _force_cover_true(monkeypatch, calls)
    weapon = {"WEAPON_RULES": [], "display_name": "Bad Shot"}

    bs, cover = _cover_worsened_bs({}, {"squad_id": "1"}, "2", 6, weapon)

    assert bs == 6 and cover is True


# --- Bout-en-bout : verrouille le CABLAGE (appelant -> _cover_worsened_bs), pas la fonction seule.
#     Un test de helper ne couvre jamais son appelant (cf. V11 §0.19.3) : ceux-ci passent par
#     _manual_roll_intent, donc si le `weapon` n'etait plus transmis, ils rougiraient.

def test_e2e_ignores_cover_result_has_no_cover(monkeypatch):
    """Chaine complete : arme IGNORES_COVER -> resultat porte cover=False et bs==bs_base,
    MEME si la LoS donnerait cover (non appelee : court-circuit)."""
    calls = []
    _force_cover_true(monkeypatch, calls)
    game_state, intent = _minimal_shoot_game_state(["IGNORES_COVER"])

    result = _manual_roll_intent(game_state, intent, {})

    assert result is not None
    assert result["cover"] is False
    assert result["bs"] == result["bs_base"] == 3
    assert calls == [], "court-circuit : LoS non consultee sur toute la chaine"


def test_e2e_no_ignores_cover_result_has_cover(monkeypatch):
    """Meme chaine sans le flag : cover=True et bs = bs_base+1 (13.08) — prouve la discrimination.

    Arme NUE (aucune regle) : depuis que HEAVY est vif (V11 P1), une arme HEAVY stationnaire
    ameliorerait le seuil de 1 et MASQUERAIT le +1 de cover teste ici — d'ou le profil sans regle."""
    calls = []
    _force_cover_true(monkeypatch, calls)
    game_state, intent = _minimal_shoot_game_state([])

    result = _manual_roll_intent(game_state, intent, {})

    assert result is not None
    assert result["cover"] is True
    assert result["bs"] == 4 and result["bs_base"] == 3
    assert len(calls) == 1
