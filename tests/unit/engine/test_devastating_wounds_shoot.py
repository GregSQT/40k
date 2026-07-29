"""DEVASTATING_WOUNDS au TIR dans le chemin VIF (résolution complète, gym auto).

Regle d arme PROJET (config/weapon_rules.json) : « No saving throw can be made against a
critical wound rolled with this weapon. » Blessure critique = jet de blessure NON MODIFIE
de 6 (05.02). Portee du code MORT vers le vif.

ECART PDF ASSUME : la def projet = simple SKIP de la sauvegarde (degats normaux appliques),
PAS les blessures mortelles du PDF 24.10. On suit la config (cf. §9.2.1).

Test BOUT-EN-BOUT via build_manual_shoot_allocation en `gym_training_mode` (defenseur
programmatique -> allocation auto-resolue sans prompt) : verrouille les TROIS points du
cablage (flag pose au jet dans _manual_roll_intent -> propage dans _build_manual_allocation
-> consomme dans _resolve_one_manual_wound). RNG force : touche 4, blessure 6 (critique),
save 6 (qui REUSSIRAIT sur une Sv 2+). Contre-epreuve fonctionnelle : sans DEVASTATING, la
meme save 6 reussit et aucun degat n est inflige.
"""
import random

from engine.phase_handlers import shooting_handlers
from engine.phase_handlers.shared_utils import build_manual_shoot_allocation


def _seq(monkeypatch, rolls):
    seq = list(rolls)

    def fake(a, b):
        assert seq, "sequence RNG epuisee"
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})


def _uc(col, row, *, player):
    return {"BASE_SHAPE": "round", "BASE_SIZE": 1, "col": col, "row": row,
            "occupied_hexes": set(), "VALUE": 10.0, "player": player}


def _game_state(weapon_rules, *, dmg=1, hp=2):
    """Tireur '1' (arme S4 DMG1) vs cible '2' (Sv 2+, T4, HP2). gym_training_mode -> auto."""
    weapon = {"ATK": 3, "STR": 4, "AP": 0, "DMG": dmg, "NB": 1, "WEAPON_RULES": weapon_rules, "display_name": "Gun"}
    attacker = {"id": "A1", "squad_id": "1", "player": 0, "T": 4, "SHOOT_LEFT": 1,
                "col": 0, "row": 0, "RNG_WEAPONS": [weapon]}
    target = {"id": "T1", "squad_id": "2", "player": 1, "T": 4, "HP_CUR": hp, "HP_MAX": hp, "ARMOR_SAVE": 2,
              "INVUL_SAVE": 7, "role": None, "unitType": "Grunt", "points_per_hp": 5.0, "VALUE": 10.0,
              "col": 9, "row": 9}
    gs = {
        "gym_training_mode": True,
        "turn": 1, "phase": "shoot",
        "action_logs": [], "action_log_seq": 0,
        "models_cache": {"A1": attacker, "T1": target},
        "squad_models": {"1": ["A1"], "2": ["T1"]},
        "squad_cache": {"1": {"model_count_at_start": 1}, "2": {"model_count_at_start": 1}},
        "units_cache": {"1": _uc(0, 0, player=0), "2": _uc(9, 9, player=1)},
        "units": [{"id": "1", "player": 0}, {"id": "2", "player": 1}],
        "unit_by_id": {"1": {"id": "1", "UNIT_RULES": []}, "2": {"id": "2", "UNIT_RULES": []}},
        "objectives": [], "units_moved": set(), "units_advanced": set(),
        "pending_squad_shoot_intents": {
            "1": [{"model_id": "A1", "target_unit_id": "2", "weapon_index": 0, "n_attacks_resolved": 1}]
        },
    }
    return gs


def _shot_records(gs):
    """Concatène les records de tir (shootDetails) de tous les logs de tir émis."""
    out = []
    for log in gs.get("action_logs", []):
        out.extend(log.get("shootDetails", []) if isinstance(log, dict) else [])
    return out


def test_devastating_critique_ignore_la_save(monkeypatch):
    """Blessure critique (6) avec DEVASTATING : save 6 (qui réussirait) SAUTÉE -> 1 dégât,
    ET le record est tagué blessure mortelle (saveSkipped + mortalWound) pour log/FNP futur."""
    # 2 des : sur un critique DEVASTATING, aucune sauvegarde n est faite (24.10) — la
    # branche sans la regle en tire 3, ce qui discrimine les deux chemins.
    _seq(monkeypatch, [4, 6])  # hit=4, wound=6 (crit)
    gs = _game_state(["DEVASTATING_WOUNDS"])

    build_manual_shoot_allocation(gs, "1")

    assert gs["models_cache"]["T1"]["HP_CUR"] == 1, "critique DEVASTATING : dégât infligé malgré save 6"
    crit = [s for s in _shot_records(gs) if s.get("strengthRoll") == 6]
    assert crit, "record du tir critique attendu dans le log"
    assert crit[0].get("mortalWound") is True and crit[0].get("saveSkipped") is True, \
        "le crit DEVASTATING doit être tagué blessure mortelle (save sautée)"


def test_sans_devastating_la_save_reussit(monkeypatch):
    """Meme critique (6) SANS DEVASTATING : save 6 réussit sur Sv2+ -> aucun dégât,
    et aucun tag blessure mortelle."""
    _seq(monkeypatch, [4, 6, 6])
    gs = _game_state([])

    build_manual_shoot_allocation(gs, "1")

    assert gs["models_cache"]["T1"]["HP_CUR"] == 2, "sans DEVASTATING la save 6 protège"
    assert all(not s.get("mortalWound") for s in _shot_records(gs)), "aucun tag mortalWound sans DEVASTATING"


def test_blessure_non_critique_repasse_par_la_sauvegarde(monkeypatch):
    """Discrimination du CRITIQUE : une blessure REUSSIE mais non critique (5) laisse la
    sauvegarde s exercer, meme avec DEVASTATING sur l arme."""
    _seq(monkeypatch, [4, 5, 6])  # hit=4, wound=5 (succes non critique), save=6 (reussit sur Sv2+)
    gs = _game_state(["DEVASTATING_WOUNDS"])

    build_manual_shoot_allocation(gs, "1")

    assert gs["models_cache"]["T1"]["HP_CUR"] == 2, "blessure non critique : la save 6 protege"
    rec = [s for s in _shot_records(gs) if s.get("strengthRoll") == 5]
    assert rec and rec[0].get("saveSuccess") is True
    assert not rec[0].get("mortalWound"), "aucun tag mortelle hors blessure critique"


def test_les_degats_du_critique_sont_ceux_de_l_arme(monkeypatch):
    """La save sautee n altere pas la valeur des degats : DMG=2 retire bien 2 PV."""
    _seq(monkeypatch, [4, 6])
    gs = _game_state(["DEVASTATING_WOUNDS"], dmg=2, hp=5)

    build_manual_shoot_allocation(gs, "1")

    assert gs["models_cache"]["T1"]["HP_CUR"] == 3, "DMG=2 applique en entier"


def test_touche_ratee_aucun_critique_possible(monkeypatch):
    """Une touche ratee arrete la sequence : aucun de de blessure, donc aucun critique."""
    _seq(monkeypatch, [1])  # 05.01 : 1 non modifie = touche ratee
    gs = _game_state(["DEVASTATING_WOUNDS"])

    build_manual_shoot_allocation(gs, "1")

    assert gs["models_cache"]["T1"]["HP_CUR"] == 2
    assert all(not s.get("mortalWound") for s in _shot_records(gs))
