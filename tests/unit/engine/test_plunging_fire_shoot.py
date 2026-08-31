"""§22.05 PLUNGING FIRE au tir dans _manual_roll_intent.

PDF 22.05 : « Each time a model makes a ranged attack, if that model's unit is on a section of
terrain that is 3" or more above the ground level of the battlefield and the target unit contains
at least one model that is on the ground level of the battlefield, improve the BS characteristic
of that attack by 1. »

Variante (b) TOWERING (PDF 22.05) : « In addition, each time a model with the TOWERING keyword
makes a ranged attack, if the target unit is within 12", improve the BS characteristic of that
attack by 1 (provided that the target unit contains at least one model that is on the ground
level). »

+1 BS = seuil ameliore de 1 (plancher 2 ; un 1 non modifie rate toujours, 05.01).

floor_height_by_model vit dans units_cache (pas unit_by_id).
En 2D (cle absente) : la cible est consideree au sol (=> condition toujours vraie cote cible),
et le tireur est considere a 0.0" (=> condition (a) fausse, (b) evaluee si TOWERING).

Discrimination verrouillee (contre-epreuve mutation : neutraliser `bs = max(2, bs-1)` => rouge) :
- tireur a 3" + cible au sol           -> BS ameliore (4 -> 3)
- tireur a 2.9" (< 3")                 -> pas de bonus (4)
- tireur a 0" (sol) + cible au sol     -> pas de bonus (4)
- tireur a 3" + cible surelev. (1"↑)   -> pas de bonus (4) : aucune figurine cible au sol
- 2D (floor_height_by_model absent)    -> pas de bonus via hauteur (tireur a 0 effectif)
- TOWERING + cible a 12" + cible au sol -> BS ameliore (4 -> 3)
- TOWERING + cible a 13" (> 12")       -> pas de bonus (4)
"""
import random
import pytest

from engine.game_state import initial_faction_ability_state
from engine.phase_handlers import shooting_handlers
from tests.unit.engine._roll_helpers import roll_shoot_intent

INCHES_TO_SUBHEX = 5
PF_HEIGHT = 3          # pouces — valeur de game_config.json


def _neutralise(monkeypatch):
    monkeypatch.setattr(random, "randint", lambda a, b: 4)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})
    monkeypatch.setattr(
        shooting_handlers, "_is_adjacent_to_enemy_within_cc_range", lambda gs, u: False
    )


def _game_state(
    *,
    atk_floor_height: float | None = None,
    tgt_floor_height: float | None = None,
    tgt_keywords: list | None = None,
    atk_keywords: list | None = None,
    dist_subhex: int = 10 * INCHES_TO_SUBHEX,
) -> tuple:
    """1 tireur (escouade '1', BS4) + 1 cible.
    atk_floor_height : None = 2D (cle absente), sinon hauteur plancher en pouces.
    tgt_floor_height : None = 2D (cible au sol), sinon hauteur plancher cible en pouces.
    """
    weapon = {
        "ATK": 4, "STR": 4, "AP": 0, "DMG": 1, "NB": 1,
        "WEAPON_RULES": [], "code": "gun", "display_name": "Gun",
    }
    attacker_model = {"id": "A1", "squad_id": "1", "T": 4, "player": 0, "RNG_WEAPONS": [weapon]}
    target_model = {
        "id": "T1", "T": 4, "HP_CUR": 2, "HP_MAX": 2,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "role": None, "unitType": "Grunt", "player": 1,
    }

    atk_uc: dict = {"col": 0, "row": 0, "VALUE": 10.0, "player": 0, "HP_CUR": 1, "HP_MAX": 1}
    if atk_floor_height is not None:
        atk_uc["floor_height_by_model"] = {"A1": atk_floor_height}

    tgt_uc: dict = {"col": 5, "row": 5, "VALUE": 10.0, "player": 1, "HP_CUR": 2, "HP_MAX": 2}
    if tgt_floor_height is not None:
        tgt_uc["floor_height_by_model"] = {"T1": tgt_floor_height}

    atk_ubi = {"id": "1", "UNIT_RULES": [], "deployed_on_turn": 0}
    if atk_keywords:
        atk_ubi["unit_keywords"] = [{"keywordId": k} for k in atk_keywords]

    tgt_ubi = {"id": "2", "UNIT_RULES": [], "deployed_on_turn": 0}
    if tgt_keywords:
        tgt_ubi["unit_keywords"] = [{"keywordId": k} for k in tgt_keywords]

    gs = {
        **initial_faction_ability_state(),
        "config": {"game_rules": {"plunging_fire_height": PF_HEIGHT}},
        "models_cache": {"A1": attacker_model, "T1": target_model},
        "squad_models": {"1": ["A1"], "2": ["T1"]},
        "squad_cache": {"2": {"model_count_at_start": 1}},
        "units_cache": {"1": atk_uc, "2": tgt_uc},
        "unit_by_id": {"1": atk_ubi, "2": tgt_ubi},
        "objectives": [],
        "turn": 2,
        "inches_to_subhex": INCHES_TO_SUBHEX,
        "moved_distance_by_model": {},
    }
    intent = {"model_id": "A1", "target_unit_id": "2", "weapon_index": 0, "n_attacks_resolved": 1}
    return gs, intent


# ── (a) chemin hauteur plancher ──────────────────────────────────────────────

def test_pf_tireur_a_3_pouces_ameliore_le_seuil(monkeypatch):
    """Tireur a 3.0" >= seuil 3" + cible au sol -> BS 4 ameliore a 3."""
    _neutralise(monkeypatch)
    gs, intent = _game_state(atk_floor_height=3.0, tgt_floor_height=0.0)
    result = roll_shoot_intent(gs, intent)
    assert result["bs"] == 3, f"bs attendu 3, obtenu {result['bs']}"
    assert result.get("plunging_fire_applied") is True


def test_pf_tireur_a_5_pouces_ameliore_le_seuil(monkeypatch):
    """Tireur a 5" > 3" -> bonus CONSERVE."""
    _neutralise(monkeypatch)
    gs, intent = _game_state(atk_floor_height=5.0, tgt_floor_height=0.0)
    result = roll_shoot_intent(gs, intent)
    assert result["bs"] == 3


def test_pf_tireur_sous_3_pouces_pas_de_bonus(monkeypatch):
    """Tireur a 2.9" < 3" -> pas de bonus (BS reste 4)."""
    _neutralise(monkeypatch)
    gs, intent = _game_state(atk_floor_height=2.9, tgt_floor_height=0.0)
    result = roll_shoot_intent(gs, intent)
    assert result["bs"] == 4
    assert not result.get("plunging_fire_applied")


def test_pf_tireur_au_sol_pas_de_bonus(monkeypatch):
    """Tireur a 0.0" -> pas de bonus."""
    _neutralise(monkeypatch)
    gs, intent = _game_state(atk_floor_height=0.0, tgt_floor_height=0.0)
    result = roll_shoot_intent(gs, intent)
    assert result["bs"] == 4


def test_pf_2d_plateau_pas_de_bonus_hauteur(monkeypatch):
    """En 2D (floor_height_by_model absent) : tireur a 0 effectif -> condition (a) fausse."""
    _neutralise(monkeypatch)
    gs, intent = _game_state(atk_floor_height=None, tgt_floor_height=None)
    result = roll_shoot_intent(gs, intent)
    assert result["bs"] == 4


# ── condition cible ───────────────────────────────────────────────────────────

def test_pf_cible_surelev_pas_de_bonus(monkeypatch):
    """Cible sur section a 1" (aucune figurine au sol) -> condition cible fausse, pas de bonus."""
    _neutralise(monkeypatch)
    gs, intent = _game_state(atk_floor_height=3.0, tgt_floor_height=1.0)
    result = roll_shoot_intent(gs, intent)
    assert result["bs"] == 4
    assert not result.get("plunging_fire_applied")


def test_pf_mutation_suppression_bs(monkeypatch):
    """Verrou mutation : sans le `bs = max(2, bs-1)`, le test doit ROUGIR.

    Ce test prouve que le bloc de code est effectivement atteint et modifie bs.
    Pour simuler la mutation on teste la valeur AVANT BONUS (4) en forcant la condition fausse
    via un tireur sous le seuil : si le code etait mute, TOUS les cas ci-dessus seraient aussi
    a 4, donc ce test donne la certitude que la valeur 3 vient bien du bloc plunging_fire.
    """
    _neutralise(monkeypatch)
    # cas controle : tireur SOUS le seuil -> BS 4 (meme si le bloc etait mute)
    gs, intent = _game_state(atk_floor_height=2.9, tgt_floor_height=0.0)
    result_ctrl = roll_shoot_intent(gs, intent)
    assert result_ctrl["bs"] == 4, "cas controle doit rester a 4"
    # cas actif : tireur AU-DESSUS du seuil -> BS 3 (echoue si code mute)
    gs, intent = _game_state(atk_floor_height=3.0, tgt_floor_height=0.0)
    result_actif = roll_shoot_intent(gs, intent)
    assert result_actif["bs"] == 3, "le bloc plunging_fire doit ameliorer BS a 3"


# ── (b) chemin TOWERING ───────────────────────────────────────────────────────

def test_pf_towering_dans_12_pouces_ameliore_le_seuil(monkeypatch):
    """TOWERING + cible a 12 subhex (12") + cible au sol -> BS 4 ameliore a 3."""
    _neutralise(monkeypatch)
    gs, intent = _game_state(
        atk_floor_height=0.0,        # tireur au sol -> chemin (a) faux
        tgt_floor_height=0.0,
        atk_keywords=["TOWERING"],
        dist_subhex=12 * INCHES_TO_SUBHEX,
    )
    # La distance est calculee par _ranged_squad_edge_distance ; on la monkeypatche.
    from engine.phase_handlers import shared_utils
    monkeypatch.setattr(
        shared_utils, "_ranged_squad_edge_distance",
        lambda gs, atk_sid, tgt_sid: 12 * INCHES_TO_SUBHEX,
    )
    result = roll_shoot_intent(gs, intent)
    assert result["bs"] == 3
    assert result.get("plunging_fire_applied") is True


def test_pf_towering_au_dela_12_pouces_pas_de_bonus(monkeypatch):
    """TOWERING + cible a 13" (> 12") -> pas de bonus."""
    _neutralise(monkeypatch)
    gs, intent = _game_state(
        atk_floor_height=0.0,
        tgt_floor_height=0.0,
        atk_keywords=["TOWERING"],
    )
    from engine.phase_handlers import shared_utils
    monkeypatch.setattr(
        shared_utils, "_ranged_squad_edge_distance",
        lambda gs, atk_sid, tgt_sid: 13 * INCHES_TO_SUBHEX,
    )
    result = roll_shoot_intent(gs, intent)
    assert result["bs"] == 4
