"""Deadly Demise §24.08 différée à la fin des attaques (25 DESTROYED), mesurée à la figurine,
attribuée par le défenseur humain (06.02).

PDF 25 Rules appendix, DESTROYED : « When a model is destroyed, first resolve any rules that are
triggered when it is destroyed […] if the model was destroyed as the result of an attack, unless
otherwise stated, those rules are only resolved and that model is only removed after the
attacking unit's attacks have been resolved. »
PDF 24.08 : « each unit within 6" of that model suffers a number of mortal wounds denoted by X ».
PDF 01.04 / 17.02 : la distance se mesure à la partie la plus proche — de la figurine détruite à
la figurine la plus proche de chaque unité, pas à son ancre.
PDF 06.02 : le propriétaire de l'unité qui subit des blessures mortelles choisit la figurine
(entre égales) — Deadly Demise ne fait pas exception.

Une version précédente jouait l'explosion À L'INSTANT de la mort (au milieu du lot), depuis
l'ancre de l'unité, et attribuait les blessures d'office chez un défenseur humain.
"""
import random
from typing import Any, Dict, List

from engine.constants import (
    MORTAL_WOUND_QUEUE_KEY, PENDING_HAZARD_ALLOCATION_KEY, PENDING_HAZARD_RESUME_RESULT_KEY,
)
from engine.phase_handlers import shooting_handlers
from engine.phase_handlers.shared_utils import (
    HAZARD_CTX, SHOOT_CTX,
    apply_manual_shoot_allocation, build_manual_shoot_allocation,
    drain_mortal_wound_queue, post_attack_effects,
)
from tests._state_invariants import turn_state_invariants
from tests.unit.engine._config_helpers import build_game_rules
from tests.unit.engine._state_builders import units_cache_entry as _uc

_DD_RULE_1 = {"ruleId": "deadly_demise", "displayName": "Deadly Demise 1", "rule_args": {"value": 1}}


def _kw(*names):
    return [{"keywordId": n} for n in names]


def _model(mid: str, squad: str, player: int, *, hp: int, col: int, row: int, rules=(), hp_max=None) -> Dict[str, Any]:
    return {"id": mid, "squad_id": squad, "player": player, "T": 4, "HP_CUR": hp, "HP_MAX": hp if hp_max is None else hp_max,
            "ARMOR_SAVE": 7, "INVUL_SAVE": 7, "role": None, "unitType": "Grunt", "SHOOT_LEFT": 1,
            "points_per_hp": 5.0, "VALUE": 10.0, "col": col, "row": row,
            "level": 0, "BASE_SHAPE": "round", "BASE_SIZE": 1, "OC": 1, "orientation": 0,
            "RNG_WEAPONS": [], "CC_WEAPONS": [],
            "UNIT_KEYWORDS": _kw("INFANTRY"), "UNIT_RULES": list(rules)}


def _game_state(*, n_attacks: int, victim_models: List[Dict[str, Any]], victim_human: bool):
    """Tireur A0 (escouade 1, joueur 0, programmatique) à (5,9) tire `n_attacks` fois sur
    l'escouade 2 : B0 (1/3 PV — entamée, donc allouée d'office, 05.04 — Deadly Demise 1) à
    (9,9) et B1 (3 PV) à (10,9), même groupe 05.03. Escouade 3 = victime potentielle de
    l'explosion (`victim_models`, joueur 1)."""
    weapon = {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": n_attacks, "RNG": 24,
              "WEAPON_RULES": [], "code": "gun", "display_name": "GUN"}
    shooter = {**_model("A0", "1", 0, hp=2, col=5, row=9), "RNG_WEAPONS": [weapon]}
    b0 = _model("B0", "2", 1, hp=1, hp_max=3, col=9, row=9, rules=[_DD_RULE_1])
    b1 = _model("B1", "2", 1, hp=3, col=10, row=9)
    models = {"A0": shooter, "B0": b0, "B1": b1, **{m["id"]: m for m in victim_models}}
    units = [{"id": "1", "player": 0, "UNIT_KEYWORDS": _kw("INFANTRY"), "UNIT_RULES": [], "hideable": False},
             {"id": "2", "player": 1, "UNIT_KEYWORDS": _kw("INFANTRY"), "UNIT_RULES": [], "hideable": False},
             {"id": "3", "player": 1, "UNIT_KEYWORDS": _kw("INFANTRY"), "UNIT_RULES": [], "hideable": False}]
    uc3 = _uc(victim_models[0]["col"], victim_models[0]["row"], player=1)
    uc3["occupied_hexes_by_model"] = {m["id"]: (m["col"], m["row"]) for m in victim_models}
    uc2 = _uc(9, 9, player=1)
    uc2["occupied_hexes_by_model"] = {"B0": (9, 9), "B1": (10, 9)}
    uc1 = _uc(5, 9, player=0)
    uc1["occupied_hexes_by_model"] = {"A0": (5, 9)}
    return {
        **turn_state_invariants(),
        "gym_training_mode": False,
        "player_types": {"0": "ai", "1": "human" if victim_human else "ai"},
        "config": {"game_rules": build_game_rules(engagement_zone=1)},
        "inches_to_subhex": 1,
        "turn": 1, "phase": "shoot",
        "action_logs": [], "action_log_seq": 0,
        "models_cache": models,
        "squad_models": {"1": ["A0"], "2": ["B0", "B1"], "3": [m["id"] for m in victim_models]},
        "squad_cache": {"1": {"model_count_at_start": 1}, "2": {"model_count_at_start": 2},
                        "3": {"model_count_at_start": len(victim_models)}},
        "units_cache": {"1": uc1, "2": uc2, "3": uc3},
        "units": units,
        "unit_by_id": {u["id"]: u for u in units},
        "objectives": [], "units_moved": set(), "units_advanced": set(),
        "board_cols": 44, "board_rows": 60, "wall_hexes": set(), "_unit_move_version": 0,
        "terrain_areas": [],
        "pending_squad_shoot_intents": {"1": [
            {"model_id": "A0", "target_unit_id": "2", "weapon_index": 0,
             "n_attacks_resolved": n_attacks, "target_squad_size_at_declaration": 2},
        ]},
    }


def _dice(monkeypatch, rolls):
    seq = list(rolls)

    def fake(a, b):
        assert seq, "un dé a été jeté là où la règle n'en attend aucun"
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})
    return seq


def _types(gs):
    return [e["type"] for e in gs["action_logs"]]


def test_l_explosion_suit_les_attaques_et_non_la_mort(monkeypatch):
    """Deux attaques : la 1re tue B0 (Deadly Demise), la 2e blesse B1 (3 -> 2) — PUIS
    l'explosion (6) touche chaque unité à 6" : le tireur A0 (2 -> 1) et l'escouade de B0
    elle-même, B1 (2 -> 1). La ligne `deadly_demise` vient APRÈS la ligne de tir."""
    # attaque 1 : 4,4,1 (B0 meurt) ; attaque 2 : 4,4,1 (B1 3->2) ; explosion : 6
    seq = _dice(monkeypatch, [4, 4, 1, 4, 4, 1, 6])
    gs = _game_state(n_attacks=2, victim_models=[_model("V0", "3", 1, hp=3, col=30, row=30)], victim_human=False)

    result = build_manual_shoot_allocation(gs, "1")

    assert result["done"] is True and seq == []
    assert "B0" not in gs["models_cache"]
    assert gs["models_cache"]["B1"]["HP_CUR"] == 1, "attaque 2 puis l'explosion de sa propre escouade"
    assert gs["models_cache"]["A0"]["HP_CUR"] == 1, "le tireur, à 4 cases, encaisse l'explosion"
    assert gs["models_cache"]["V0"]["HP_CUR"] == 3, "à 30 cases, hors des 6 pouces"
    types = _types(gs)
    assert types.index("shoot") < types.index("deadly_demise"), types
    assert MORTAL_WOUND_QUEUE_KEY not in gs


def test_la_distance_se_mesure_a_la_figurine_la_plus_proche(monkeypatch):
    """L'ancre de l'escouade 3 est à 30 cases, mais sa figurine V1 est à 4 cases de B0 : elle
    est dans les 6 pouces (01.04 : partie la plus proche), l'unité subit l'explosion."""
    _dice(monkeypatch, [4, 4, 1, 6])
    victims = [_model("V0", "3", 1, hp=3, col=30, row=30), _model("V1", "3", 1, hp=3, col=13, row=9)]
    gs = _game_state(n_attacks=1, victim_models=victims, victim_human=False)

    build_manual_shoot_allocation(gs, "1")

    assert gs["models_cache"]["V0"]["HP_CUR"] + gs["models_cache"]["V1"]["HP_CUR"] == 5, \
        "une blessure mortelle sur l'escouade 3, mesurée à V1"


def test_le_defenseur_humain_choisit_la_figurine_qui_encaisse_l_explosion(monkeypatch):
    """Escouade 3 (humaine) à portée avec deux figurines intactes : 06.02 laisse le choix ;
    l'attente porte `damage_type: mortal` et les deux candidates. Le résultat de l'activation
    est gardé pour la reprise, et rendu une fois la blessure attribuée."""
    _dice(monkeypatch, [4, 4, 1, 6])
    victims = [_model("V0", "3", 1, hp=3, col=12, row=9), _model("V1", "3", 1, hp=3, col=13, row=9)]
    gs = _game_state(n_attacks=1, victim_models=victims, victim_human=True)

    wait = build_manual_shoot_allocation(gs, "1")

    assert wait["waiting_for_player"] is True and wait["action"] == "squad_hazard_manual_alloc"
    assert wait["allocation"]["damage_type"] == "mortal"
    assert [c["model_id"] for c in wait["allocation"]["choices"]] == ["V0", "V1"]
    assert gs["hazard_origin"] == "shoot"
    state = gs[PENDING_HAZARD_RESUME_RESULT_KEY]
    assert state["result"]["done"] is True and state["attacker_squad_id"] == "1"

    # Le défenseur désigne V1 ; la reprise (comme `_resume_after_hazard`) sert le reste de la
    # file puis rend le résultat de l'activation.
    done = apply_manual_shoot_allocation(gs, "V1", HAZARD_CTX)
    assert done["done"] is True and PENDING_HAZARD_ALLOCATION_KEY not in gs
    assert gs["models_cache"]["V1"]["HP_CUR"] == 2 and gs["models_cache"]["V0"]["HP_CUR"] == 3
    assert drain_mortal_wound_queue(gs) is None
    outcome = post_attack_effects(gs, SHOOT_CTX, gs.pop(PENDING_HAZARD_RESUME_RESULT_KEY))
    assert outcome["done"] is True and outcome["shoot_result"]["models_killed"] == 1
    assert "hazard_origin" not in gs


def test_un_retrait_de_coherence_ne_declenche_pas_l_explosion(monkeypatch):
    """03.03 REGAINING COHERENCY : « Models removed in this way are destroyed, but they do not
    trigger rules that apply when a model is destroyed. » Le retrait de B0 (Deadly Demise 1)
    ne met RIEN en file : aucun dé n'est jeté, personne n'encaisse — ni maintenant, ni au
    prochain drain. Jumeau 20.04 (`strategic_reserves_timeout`) : une unité jamais arrivée n'est
    pas sur le champ de bataille, aucune unité n'est « within 6" » d'elle."""
    from engine.phase_handlers.shared_utils import destroy_model
    seq = _dice(monkeypatch, [])
    gs = _game_state(n_attacks=1, victim_models=[_model("V0", "3", 1, hp=3, col=12, row=9)], victim_human=False)

    destroy_model(gs, "B0", reason="coherency_removal")

    assert "B0" not in gs["models_cache"]
    assert MORTAL_WOUND_QUEUE_KEY not in gs
    assert drain_mortal_wound_queue(gs) is None and seq == []
    assert gs["models_cache"]["B1"]["HP_CUR"] == 3 and gs["models_cache"]["V0"]["HP_CUR"] == 3
    assert "deadly_demise" not in _types(gs)

    # Contrôle : la même mort par blessure mortelle hors attaque (`hazard`) est bien mise en file.
    gs2 = _game_state(n_attacks=1, victim_models=[_model("V0", "3", 1, hp=3, col=12, row=9)], victim_human=False)
    destroy_model(gs2, "B0", reason="hazard")
    assert [e["kind"] for e in gs2[MORTAL_WOUND_QUEUE_KEY]] == ["deadly_demise"]
