"""[HEAVY] 24.16 au TIR dans le chemin VIF (_manual_roll_intent).

PDF 24.16 (source de verite, arbitrage utilisateur 2026-07-26) : « add 1 to the hit roll if ALL
of the following apply to the attacking unit : that unit is UNENGAGED ; that unit was not set up
on the battlefield this turn ; no model in that unit has moved more than 3" this turn. »

+1 au jet de touche = seuil BS ameliore de 1 (plancher 2 : un 1 non modifie rate toujours, 05.01).

Etat des trois clauses dans ce moteur :
- unengaged            : TESTE (meme predicat que le gate de tir 10.06).
- pas pose ce tour     : TESTE sur `deployed_on_turn` (0 = pre-bataille, N = arrivee de
                         reserve au tour N). Aucune arrivee en cours de bataille n existe encore
                         (reserves 20 non modelisees), mais la clause est cablee.
- aucune fig > 3"      : EXACT depuis le 2026-07-26 — teste sur la DISTANCE reellement
                         parcourue par figurine (`moved_distance_by_model`, accumulee par
                         `commit_move` en distance de CHEMIN geodesique). L ancienne borne
                         conservatrice (« aucune figurine n a bouge ») refusait le bonus a une
                         escouade qui s etait repositionnee de 2", ce que le PDF accorde.

Discrimination verrouillee (contre-epreuve mutation : neutraliser `bs = max(2, bs-1)` => rouge) :
- HEAVY + stationnaire + unengaged   -> BS ameliore (4 -> 3)
- HEAVY + a bouge de 4" (> 3")       -> pas de bonus (4)
- HEAVY + a bouge de 2" (<= 3")      -> bonus CONSERVE (3) — la clause est une distance
- HEAVY + a bouge de 3" pile         -> bonus CONSERVE (3) — « MORE than 3\" », comparaison stricte
- HEAVY + stationnaire mais ENGAGE   -> pas de bonus (4)
- HEAVY + POSEE CE TOUR (arrivee de reserve) -> pas de bonus (4)
- sans HEAVY + stationnaire          -> pas de bonus (4)
"""
import random

import pytest

from engine.phase_handlers import shooting_handlers
from engine.game_state import initial_faction_ability_state
from tests.unit.engine._roll_helpers import roll_shoot_intent


def _neutralise(monkeypatch, *, engaged=False):
    monkeypatch.setattr(random, "randint", lambda a, b: 4)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})
    # Clause 1 de 24.16 : « that unit is unengaged » — meme predicat que le gate de tir.
    monkeypatch.setattr(
        shooting_handlers, "_is_adjacent_to_enemy_within_cc_range", lambda gs, u: engaged
    )


INCHES_TO_SUBHEX = 5


def _game_state(weapon_rules, *, moved_inches=0.0, deployed_on_turn=0, bs=4):
    """1 tireur (escouade '1', BS4 par defaut) + 1 cible. `moved_inches` = distance parcourue par A1."""
    weapon = {"ATK": bs, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "WEAPON_RULES": weapon_rules, "display_name": "Gun"}
    attacker = {"id": "A1", "squad_id": "1", "T": 4, "player": 0, "RNG_WEAPONS": [weapon]}
    target_model = {"id": "T1", "T": 4, "HP_CUR": 2, "HP_MAX": 2, "ARMOR_SAVE": 3,
                    "INVUL_SAVE": 7, "role": None, "unitType": "Grunt", "player": 1}
    gs = {
        # Etat de depart des capacites de faction, par le constructeur canonique du moteur
        # (`w40k_core` l'appelle a l'init ET au reset). La resolution d'une attaque lit
        # `oath_target` / `waaagh_active` en `require_key` : un game_state litteral qui les
        # omet decrit une partie impossible.
        **initial_faction_ability_state(),
        "models_cache": {"A1": attacker, "T1": target_model},
        "squad_models": {"2": ["T1"]},
        "squad_cache": {"2": {"model_count_at_start": 1}},
        "units_cache": {"2": {"col": 9, "row": 9, "VALUE": 10.0, "player": 1}},
        "unit_by_id": {"1": {"id": "1", "UNIT_RULES": [], "deployed_on_turn": deployed_on_turn},
                       "2": {"id": "2", "UNIT_RULES": [], "deployed_on_turn": 0}},
        "objectives": [], "turn": 2,
        "inches_to_subhex": INCHES_TO_SUBHEX,
        "moved_distance_by_model": {"A1": float(moved_inches) * INCHES_TO_SUBHEX},
    }
    gs["squad_models"]["1"] = ["A1"]
    intent = {"model_id": "A1", "target_unit_id": "2", "weapon_index": 0, "n_attacks_resolved": 1}
    return gs, intent


def test_heavy_stationnaire_ameliore_le_seuil(monkeypatch):
    """HEAVY + stationnaire -> BS 4 ameliore a 3."""
    _neutralise(monkeypatch)
    gs, intent = _game_state(["HEAVY"])
    result = roll_shoot_intent(gs, intent)
    assert result["bs"] == 3


@pytest.mark.parametrize("moved_inches", [3.5, 4.0, 12.0])
def test_heavy_apres_plus_de_3_pouces_pas_de_bonus(monkeypatch, moved_inches):
    """24.16 clause 3 : une figurine a parcouru PLUS de 3" -> pas de bonus (BS reste 4)."""
    _neutralise(monkeypatch)
    gs, intent = _game_state(["HEAVY"], moved_inches=moved_inches)
    result = roll_shoot_intent(gs, intent)
    assert result["bs"] == 4


@pytest.mark.parametrize("moved_inches", [0.0, 2.0, 3.0])
def test_heavy_jusqu_a_3_pouces_bonus_conserve(monkeypatch, moved_inches):
    """24.16 clause 3 : « MORE than 3\" » — 3" pile conserve le bonus (comparaison stricte).

    C est le gain de conformite du 2026-07-26 : l ancienne borne « aucune figurine n a bouge »
    rendait ces trois cas ROUGES pour 2.0 et 3.0.
    """
    _neutralise(monkeypatch)
    gs, intent = _game_state(["HEAVY"], moved_inches=moved_inches)
    result = roll_shoot_intent(gs, intent)
    assert result["bs"] == 3


def test_heavy_clause_3_porte_sur_la_figurine_qui_a_le_plus_bouge(monkeypatch):
    """« NO MODEL in that unit has moved more than 3\" » : UNE figurine suffit a annuler."""
    _neutralise(monkeypatch)
    gs, intent = _game_state(["HEAVY"], moved_inches=0.0)
    # A1 (le tireur) n a pas bouge, mais une autre figurine de SON escouade a couru 6".
    gs["models_cache"]["A2"] = dict(gs["models_cache"]["A1"], id="A2")
    gs["squad_models"]["1"] = ["A1", "A2"]
    gs["moved_distance_by_model"]["A2"] = 6.0 * INCHES_TO_SUBHEX
    result = roll_shoot_intent(gs, intent)
    assert result["bs"] == 4


def test_heavy_engage_pas_de_bonus(monkeypatch):
    """24.16 clause 1 : stationnaire mais ENGAGE -> aucun bonus (BS reste 4)."""
    _neutralise(monkeypatch, engaged=True)
    gs, intent = _game_state(["HEAVY"])
    result = roll_shoot_intent(gs, intent)
    assert result["bs"] == 4


def test_heavy_pose_ce_tour_pas_de_bonus(monkeypatch):
    """24.16 clause 2 : unite arrivee de reserve CE TOUR -> aucun bonus (BS reste 4)."""
    _neutralise(monkeypatch)
    gs, intent = _game_state(["HEAVY"], deployed_on_turn=2)  # turn == 2 dans la fixture
    result = roll_shoot_intent(gs, intent)
    assert result["bs"] == 4


def test_heavy_pose_un_tour_avant_bonus_conserve(monkeypatch):
    """Discrimination : arrivee au tour PRECEDENT -> le bonus s applique."""
    _neutralise(monkeypatch)
    gs, intent = _game_state(["HEAVY"], deployed_on_turn=1)
    result = roll_shoot_intent(gs, intent)
    assert result["bs"] == 3


def test_le_log_de_tir_affiche_le_token_heavy(monkeypatch):
    """Le combat log doit montrer `Hit:X+ [HEAVY]` quand le bonus est APPLIQUE — le frontend
    y accroche le tooltip de la regle (meme mecanique que [COVER] / [HAZARD]).

    Discrimination : arme HEAVY mais unite ayant parcouru 6" -> aucun token (bonus non applique).
    """
    from engine.phase_handlers.shared_utils import _emit_squad_shoot_log, SHOOT_CTX

    def _log_message(*, moved_inches):
        _neutralise(monkeypatch)
        gs, intent = _game_state(["HEAVY"], moved_inches=moved_inches)
        r = roll_shoot_intent(gs, intent)
        gs.update({"units": [{"id": "1", "unitType": "Shooter"}, {"id": "2", "unitType": "Grunt"}],
                   "action_logs": [], "action_log_seq": 0, "turn": 2})
        group = {
            "weapon_name": "Gun", "target_sid": "2", "attacker_squad_id": "1",
            # Les DEUX positions sont capturées à la création du groupe (cf.
            # test_squad_shoot_log_dead_target_position) : l'émission ne relit plus units_cache.
            "attacker_col": 0, "attacker_row": 0,
            "target_col": 9, "target_row": 9, "attacks": 1, "damage": 0, "kills": 0,
            "bs": r["bs"], "display_wth": r["display_wth"], "display_save_th": r["display_save_th"],
            "heavy_applied": r["heavy_applied"], "shooter_mids": ["A1"], "shots": [],
            # Oath (08.04) : l emission exige les deux clefs, le vrai groupement les copie de
            # l intent — les relire ici garde la fixture alignee sur le producteur.
            "oath_hit_reroll": r["oath_hit_reroll"], "oath_wound_bonus": r["oath_wound_bonus"],
            # Waaagh! (08.04) : mêmes clés exigées par l'émission, mêmes copies depuis l'intent.
            "waaagh_melee_bonus": r["waaagh_melee_bonus"],
            "waaagh_target_invul": r["waaagh_target_invul"],
            # Arme + profil de regles : le vrai regroupement les garde par reference et c est
            # l emission qui en tire les tokens — dont [HEAVY], que ce test observe.
            "weapon": r["weapon"], "attack_profile": r["attack_profile"],
            "dmg_bonus": r["dmg_bonus"],
            # [PRECISION] : pose a l allocation, absente ici (aucun groupe CHARACTER).
            "precision_applied": False,
            # Regles additives [BLAST]/[CLEAVE] : reunies sur le groupe par le vrai
            # regroupement (ici une seule figurine, donc l etat de l intent).
            "additive_rules_applied": r["additive_rules_applied"],
            "point_blank_malus": r["point_blank_malus"],
            # [ASSAULT] 24.04 / [CLOSE-QUARTERS] 24.07 : l arme Gun ne declare ni l un ni
            # l autre ; ces deux cles sont exigees par require_key a l emission.
            "assault_applied": False,
            "close_quarters_applied": False,
            # [INDIRECT FIRE] 10.07 : posé à la création du groupe ; None si la règle ne joue pas.
            "indirect_fire_fail_below": None,
            "player": 0,
            "targetAliveCount": 1,
        }
        _emit_squad_shoot_log(gs, group, SHOOT_CTX)
        return gs["action_logs"][-1]["message"]

    stationnaire = _log_message(moved_inches=0.0)
    apres_mouvement = _log_message(moved_inches=6.0)

    assert "Hit:3+ [HEAVY]" in stationnaire, stationnaire
    assert "[HEAVY]" not in apres_mouvement, apres_mouvement


def test_heavy_ne_descend_jamais_le_seuil_sous_2(monkeypatch):
    """Plancher 05.01 : BS 2+ ameliore de 1 resterait 1+, or un 1 non modifie rate TOUJOURS.
    Le seuil effectif reste donc 2, et le seuil de BASE (affichage) n est pas altere."""
    _neutralise(monkeypatch)
    gs, intent = _game_state(["HEAVY"], bs=2)
    result = roll_shoot_intent(gs, intent)
    assert result["bs"] == 2, "max(2, bs-1) : le bonus ne cree pas de seuil 1+"
    assert result["bs_base"] == 2, "le seuil de base reste celui de l arme"
    assert result["heavy_applied"] is True, "le bonus est bien APPLIQUE, il est juste plafonne"


def test_le_seuil_de_base_est_conserve_quand_heavy_ameliore(monkeypatch):
    """`bs` (effectif) et `bs_base` (arme) sont distincts : le log affiche l amelioration."""
    _neutralise(monkeypatch)
    gs, intent = _game_state(["HEAVY"])
    result = roll_shoot_intent(gs, intent)
    assert (result["bs"], result["bs_base"]) == (3, 4)


def test_sans_heavy_pas_de_bonus(monkeypatch):
    """Sans HEAVY, meme stationnaire -> BS reste 4 (contre-epreuve fonctionnelle)."""
    _neutralise(monkeypatch)
    gs, intent = _game_state([])
    result = roll_shoot_intent(gs, intent)
    assert result["bs"] == 4
