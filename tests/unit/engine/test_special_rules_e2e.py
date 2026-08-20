"""Regles speciales de TIR en INTERACTION, bout-en-bout sur le chemin VIF.

Chaque regle prise isolement a son fichier : [HEAVY] -> test_heavy_shoot.py,
[HAZARDOUS] -> test_hazardous.py, [DEVASTATING WOUNDS] -> test_devastating_wounds_shoot.py,
le socle de la boucle -> test_weapon_rules_attack_sequence.py. Ce fichier verrouille ce
qu aucun d eux ne voit : PLUSIEURS regles portees par la MEME activation de tir, resolues
dans le meme passage `build_manual_shoot_allocation`.

Il remplace la version qui appelait le code mort de tir (supprime en V11 §0.38).
Deux ecarts du mort contre les PDF ont ete constates en migrant, et ne sont donc PAS
reportes ici — c est le vif qui a raison :
  - [HAZARDOUS] 24.15 : le mort jetait UN de PAR ATTAQUE, pendant la sequence, declenchait
    sur 1 seulement et n appliquait AUCUNE blessure mortelle. Le PDF (24.15 + 06.03) dit :
    apres que l unite a resolu TOUTES ses attaques, un jet PAR ARME HAZARDOUS selectionnee,
    echec sur 1-2, 1 blessure mortelle (3 si toutes les figurines sont MONSTER/VEHICLE).
  - [HEAVY] 24.16 : le mort accordait le bonus des que l unite n etait ni dans `units_moved`
    ni dans `units_advanced`, sans les clauses « unengaged » et « not set up this turn », et
    sans la borne exacte des 3". Le vif teste les trois clauses du PDF.

Ordre des des : par attaque touche -> blessure -> sauvegarde, PUIS les jets de hasard de fin
d activation. `_seq` echoue si le moteur en tire plus ou moins que la sequence declaree.
"""
import random

from engine.phase_handlers import shooting_handlers
from engine.phase_handlers.shared_utils import build_manual_shoot_allocation
from tests._state_invariants import turn_state_invariants


def _seq(monkeypatch, rolls):
    seq = list(rolls)

    def fake(a, b):
        assert seq, "sequence RNG epuisee : le moteur a tire plus de des que prevu"
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})
    # Clause 1 de [HEAVY] 24.16 : « that unit is unengaged » (hors sujet ici, jamais engage).
    monkeypatch.setattr(
        shooting_handlers, "_is_adjacent_to_enemy_within_cc_range", lambda gs, u: False
    )
    return seq


INCHES_TO_SUBHEX = 5


def _kw(*names):
    return [{"keywordId": n} for n in names]


from tests.unit.engine._state_builders import units_cache_entry as _uc


def _game_state(weapon_rules, *, bs=4, dmg=1, moved_inches=0.0, shooter_hp=3, target_hp=9):
    """1 tireur (escouade '1', BS4, S4, arme sans portee courte) vs 1 cible T4 Sv2+."""
    weapon = {"ATK": bs, "STR": 4, "AP": 0, "DMG": dmg, "NB": 1, "RNG": 24,
              "WEAPON_RULES": list(weapon_rules), "display_name": "Plasma"}
    attacker = {"id": "A1", "squad_id": "1", "player": 0, "T": 4, "SHOOT_LEFT": 1,
                "HP_CUR": shooter_hp, "HP_MAX": shooter_hp, "ARMOR_SAVE": 3, "INVUL_SAVE": 7,
                "role": None, "unitType": "Shooter", "points_per_hp": 5.0, "VALUE": 10.0,
                "col": 0, "row": 0, "UNIT_KEYWORDS": _kw("INFANTRY"), "RNG_WEAPONS": [weapon]}
    target = {"id": "T1", "squad_id": "2", "player": 1, "T": 4,
              "HP_CUR": target_hp, "HP_MAX": target_hp, "ARMOR_SAVE": 2, "INVUL_SAVE": 7,
              "role": None, "unitType": "Grunt", "points_per_hp": 5.0, "VALUE": 10.0,
              "col": 9, "row": 9, "UNIT_KEYWORDS": _kw("INFANTRY")}
    return {**turn_state_invariants(),
        "gym_training_mode": True,
        "config": {"game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5}},
        "turn": 2, "phase": "shoot",
        "action_logs": [], "action_log_seq": 0,
        "models_cache": {"A1": attacker, "T1": target},
        "squad_models": {"1": ["A1"], "2": ["T1"]},
        "squad_cache": {"1": {"model_count_at_start": 1}, "2": {"model_count_at_start": 1}},
        "units_cache": {"1": _uc(0, 0, player=0), "2": _uc(9, 9, player=1)},
        "units": [{"id": "1", "player": 0, "UNIT_KEYWORDS": _kw("INFANTRY")},
                  {"id": "2", "player": 1, "UNIT_KEYWORDS": _kw("INFANTRY")}],
        "unit_by_id": {
            "1": {"id": "1", "player": 0, "UNIT_RULES": [], "deployed_on_turn": 0,
                  "UNIT_KEYWORDS": _kw("INFANTRY")},
            "2": {"id": "2", "player": 1, "UNIT_RULES": [], "deployed_on_turn": 0,
                  "UNIT_KEYWORDS": _kw("INFANTRY")},
        },
        "objectives": [], "units_moved": set(), "units_advanced": set(),
        "inches_to_subhex": INCHES_TO_SUBHEX,
        "moved_distance_by_model": {"A1": float(moved_inches) * INCHES_TO_SUBHEX},
        "pending_squad_shoot_intents": {
            "1": [{"model_id": "A1", "target_unit_id": "2", "weapon_index": 0,
                   "n_attacks_resolved": 1, "target_squad_size_at_declaration": 1}]
        },
    }


def _hp(gs, mid):
    return gs["models_cache"][mid]["HP_CUR"]


def _records(gs):
    out = []
    for log in gs["action_logs"]:
        out.extend(log.get("shootDetails", []) if isinstance(log, dict) else [])
    return out


# ─────────────────────────────────────────────────────────────────────────────
# [DEVASTATING WOUNDS] × [HAZARDOUS] : deux effets independants, deux porteurs
# ─────────────────────────────────────────────────────────────────────────────

def test_devastating_et_hazardous_les_deux_se_declenchent(monkeypatch):
    """Blessure critique (save sautee sur la CIBLE) et hasard rate (MW sur le TIREUR)."""
    # 3 des seulement : la sauvegarde n est PAS faite sur un critique DEVASTATING (24.10).
    seq = _seq(monkeypatch, [4, 6, 1])  # touche, blessure critique, hasard rate
    gs = _game_state(["DEVASTATING_WOUNDS", "HAZARDOUS"])

    build_manual_shoot_allocation(gs, "1")

    assert _hp(gs, "T1") == 8, "critique DEVASTATING : la save 6 (Sv2+) ne protege pas"
    assert _hp(gs, "A1") == 2, "hasard rate : 1 blessure mortelle sur le tireur"
    assert seq == []


def test_devastating_seul_quand_le_hasard_reussit(monkeypatch):
    """Discrimination : hasard reussi (4) -> le tireur est indemne, la cible non."""
    seq = _seq(monkeypatch, [4, 6, 4])  # touche, blessure critique, hasard reussi
    gs = _game_state(["DEVASTATING_WOUNDS", "HAZARDOUS"])

    build_manual_shoot_allocation(gs, "1")

    assert _hp(gs, "T1") == 8
    assert _hp(gs, "A1") == 3, "hasard reussi : aucune blessure mortelle"
    assert seq == []


def test_hazardous_seul_quand_la_blessure_n_est_pas_critique(monkeypatch):
    """Blessure reussie NON critique (5) : la save 6 protege la cible ; le hasard, lui, tombe."""
    seq = _seq(monkeypatch, [4, 5, 6, 1])
    gs = _game_state(["DEVASTATING_WOUNDS", "HAZARDOUS"])

    build_manual_shoot_allocation(gs, "1")

    assert _hp(gs, "T1") == 9, "blessure non critique : la sauvegarde s exerce"
    assert _hp(gs, "A1") == 2, "le jet de hasard est independant du sort de l attaque"
    assert seq == []


def test_hazardous_est_jete_meme_si_toutes_les_attaques_ratent(monkeypatch):
    """24.15 : le jet a lieu « after that unit has resolved all of its attacks » — que ces
    attaques aient touche ou non. Le risque est celui de l ARME, pas celui du resultat."""
    seq = _seq(monkeypatch, [1, 1])  # touche ratee (05.01), puis hasard rate
    gs = _game_state(["HAZARDOUS"])

    build_manual_shoot_allocation(gs, "1")

    assert _hp(gs, "T1") == 9, "aucune touche : la cible est intacte"
    assert _hp(gs, "A1") == 2, "le hasard est jete quand meme"
    assert seq == []


# ─────────────────────────────────────────────────────────────────────────────
# [HEAVY] × [DEVASTATING WOUNDS] : un modificateur de seuil et un effet de blessure
# ─────────────────────────────────────────────────────────────────────────────

def test_heavy_fait_toucher_un_de_qui_aurait_rate_puis_devastating_saute_la_save(monkeypatch):
    """BS4 ameliore a 3 par HEAVY : le 3 touche, la blessure critique saute la save 6."""
    seq = _seq(monkeypatch, [3, 6])  # touche 3 (grace a HEAVY), blessure critique -> pas de save
    gs = _game_state(["HEAVY", "DEVASTATING_WOUNDS"], dmg=2)

    build_manual_shoot_allocation(gs, "1")

    assert _records(gs)[0]["hitResult"] == "HIT", "3 >= seuil 3 grace a HEAVY"
    assert _hp(gs, "T1") == 7, "DEVASTATING : les 2 degats passent malgre la save 6"
    assert seq == []


def test_sans_le_bonus_heavy_le_meme_de_rate_et_devastating_ne_sert_a_rien(monkeypatch):
    """Contre-epreuve : l unite a parcouru 6" (> 3", clause 3 de 24.16) -> seuil 4, le 3 rate,
    et la sequence s arrete avant tout jet de blessure."""
    seq = _seq(monkeypatch, [3])
    gs = _game_state(["HEAVY", "DEVASTATING_WOUNDS"], dmg=2, moved_inches=6.0)

    build_manual_shoot_allocation(gs, "1")

    assert _records(gs)[0]["hitResult"] == "MISS"
    assert _hp(gs, "T1") == 9
    assert seq == [], "aucun de de blessure apres une touche ratee"


# ─────────────────────────────────────────────────────────────────────────────
# Contre-epreuve globale : une arme nue ne declenche rien
# ─────────────────────────────────────────────────────────────────────────────

def test_arme_sans_regle_aucun_effet_special(monkeypatch):
    """Aucune regle : pas de bonus au seuil, pas de save sautee, pas de jet de hasard."""
    seq = _seq(monkeypatch, [3, 6, 6])  # touche 3 (< seuil 4 sans HEAVY) -> MISS
    gs = _game_state([])

    build_manual_shoot_allocation(gs, "1")

    rec = _records(gs)[0]
    assert rec["hitResult"] == "MISS", "aucun bonus de seuil sans HEAVY"
    assert rec["hitTarget"] == 4
    assert _hp(gs, "T1") == 9
    assert _hp(gs, "A1") == 3, "aucun jet de hasard sans HAZARDOUS"
    assert seq == [6, 6], "les des de blessure/sauvegarde n ont pas ete consommes"


def test_arme_sans_regle_la_blessure_critique_reste_sauvable(monkeypatch):
    """Sans DEVASTATING, un 6 au jet de blessure reste une blessure CRITIQUE (05.02) mais la
    sauvegarde s exerce normalement."""
    seq = _seq(monkeypatch, [4, 6, 6])
    gs = _game_state([])

    build_manual_shoot_allocation(gs, "1")

    rec = _records(gs)[0]
    assert rec.get("criticalWound") is True, "6 non modifie = blessure critique (05.02)"
    assert rec["saveSuccess"] is True, "sans DEVASTATING, la save 6 protege sur Sv2+"
    assert _hp(gs, "T1") == 9
    assert seq == []
