"""Contrôles analyzer des modificateurs de jet (Primitive A, chantier 06, passe 1).

Depuis cette passe, trois seuils du journal ne sont plus la caractéristique de l'arme :

    `Hit N(x+)`   = clamp(WS - Might Is Right + suppression, 2, 6)
    `Wound N(x+)` = table 05.02 - Oath - Litany of Hate, plancher 2
    `[Roll: N]`   = 2D6 + Somethin' to Prove

Deux dangers symétriques, et ce fichier verrouille les deux :

- LE FAUX POSITIF. Le contrôle de seuil de blessure existait déjà et ne connaissait pas Litany
  of Hate : chaque ligne de mêlée d'une escouade menée par un Chaplain serait sortie en « seuil
  faux » alors que le moteur a raison. C'est la régression la plus probable de la passe.
- LE VERT VACANT. Un contrôle qui lirait le TOKEN du moteur pour deviner le bonus confronterait
  deux sorties du même moteur et ne prouverait rien. Le bonus est donc dérivé des DATASHEETS des
  figurines vivantes (19.04) — ce qui rend détectable un `+1` OUBLIÉ, pas seulement un `+1` de
  trop.
"""

from __future__ import annotations

from typing import Any, Dict

import ai.analyzer_hit as ah
import ai.analyzer_wound as aw
from ai.analyzer_state import AnalyzerState
from tests.unit.ai._fabriques import analyzer_config

#: Escouade « 1 » : deux troupiers et un Warboss attaché. C'est le Warboss qui porte
#: `hit_roll_bonus_fight` — l'escouade, elle, ne le porte pas : sans la lecture par FIGURINE, le
#: bonus serait invisible, exactement le trou que 19.04 ouvre.
MODEL_TYPES = {"1#0": "Trooper", "1#1": "Trooper", "1#2": "Warboss", "9#0": "Trooper"}
UNIT_RULES_BY_TYPE = {
    "Trooper": set(),
    "Warboss": {"hit_roll_bonus_fight"},
    "Chaplain": {"wound_roll_bonus_fight"},
    "Bigboss": {"charge_roll_bonus"},
}
ATTACK_LIMITS = {
    "Trooper": {
        "cc_atk_by_weapon": {"Choppa": 4},
        "cc_str_by_weapon": {"Choppa": 4},
        "rng_str_by_weapon": {},
    },
    "Warboss": {
        "cc_atk_by_weapon": {"Choppa": 2},
        "cc_str_by_weapon": {"Choppa": 4},
        "rng_str_by_weapon": {},
    },
    "Chaplain": {
        "cc_atk_by_weapon": {"Choppa": 4},
        "cc_str_by_weapon": {"Choppa": 4},
        "rng_str_by_weapon": {},
    },
    "Bigboss": {
        "cc_atk_by_weapon": {"Choppa": 4},
        "cc_str_by_weapon": {"Choppa": 4},
        "rng_str_by_weapon": {},
    },
}


class _Registry:
    units = {t: {"UNIT_RULES": []} for t in UNIT_RULES_BY_TYPE}


def _config(**overrides: Any):
    rule_to_units: Dict[str, set] = {}
    for unit_type, rules in UNIT_RULES_BY_TYPE.items():
        for rule in rules:
            rule_to_units.setdefault(rule, set()).add(unit_type)
    return analyzer_config(**{
        "unit_registry": _Registry(),
        "unit_rules_by_type": UNIT_RULES_BY_TYPE,
        "unit_attack_limits": ATTACK_LIMITS,
        "unit_toughness_by_type": {"Trooper": 4, "Warboss": 5, "Chaplain": 4, "Bigboss": 5},
        "rule_to_units": rule_to_units,
        "effect_display_tokens": {"charge_roll_bonus": {"SOMETHIN' TO PROVE"}},
        **overrides,
    })


class _State(AnalyzerState):
    """Escouade attaquante « 1 » aux socles CONNUS — c'est le cas de production sur une ligne
    de mêlée : l'attaquant vient d'agir, donc son `[MODELS:]` est celui de la ligne."""

    def __init__(self, attacker_models=("1#0", "1#1", "1#2")) -> None:
        super().__init__(stats=_stats())
        self.model_types = dict(MODEL_TYPES)
        self.unit_models_alive = {"1": len(attacker_models), "9": 1}
        self.positions_by_model = {
            "1": {mid: (0, 0) for mid in attacker_models},
            "9": {"9#0": (5, 5)},
        }
        self.active_effects = {}
        self.current_episode_num = 1


def _stats() -> Dict[str, Any]:
    return {
        "fight_hit_threshold_mismatch": {1: 0, 2: 0},
        "fight_hit_threshold_unverifiable": {1: 0, 2: 0},
        "fight_wound_threshold_mismatch": {1: 0, 2: 0},
        "fight_wound_threshold_unverifiable": {1: 0, 2: 0},
        "shoot_wound_threshold_mismatch": {1: 0, 2: 0},
        "shoot_wound_threshold_unverifiable": {1: 0, 2: 0},
        "charge_roll_out_of_range": {1: 0, 2: 0},
        "first_error_lines": {
            "fight_hit_threshold_mismatch": {1: None, 2: None},
            "fight_wound_threshold_mismatch": {1: None, 2: None},
            "shoot_wound_threshold_mismatch": {1: None, 2: None},
            "charge_roll_out_of_range": {1: None, 2: None},
        },
        "rule_usage": {"PROJ.1.3.charge_roll_bonus": {1: 0, 2: 0}},
    }


def _check_hit(state, stats, desc, *, shooters=("1#0",), config=None):
    ah.check_melee_hit_threshold(
        state, config if config is not None else _config(),
        stats, desc, desc, 1, "1", "Trooper", "Choppa", shooters,
    )


# ---------------------------------------------------------------------------
# Seuil de touche en mêlée
# ---------------------------------------------------------------------------


def test_le_seuil_nu_est_la_caracteristique_de_l_arme():
    """Sans capacité en vigueur, WS 4 → seuil 4+ : aucun écart."""
    state = _State(attacker_models=("1#0", "1#1"))
    stats = state.stats
    _check_hit(state, stats, "FOUGHT Unit 9 with [Choppa] - Hit 4(4+) - Wound 4(4+)")
    assert stats["fight_hit_threshold_mismatch"][1] == 0
    assert stats["fight_hit_threshold_unverifiable"][1] == 0, "vert vacant : rien n'a été jugé"


def test_un_seuil_faux_est_compte_et_explique():
    """WS 4 sans capacité, mais le journal imprime 3+ : le moteur se contredit."""
    state = _State(attacker_models=("1#0", "1#1"))
    stats = state.stats
    _check_hit(state, stats, "FOUGHT Unit 9 with [Choppa] - Hit 4(3+) - Wound 4(4+)")
    assert stats["fight_hit_threshold_mismatch"][1] == 1
    detail = stats["first_error_lines"]["fight_hit_threshold_mismatch"][1]["detail"]
    assert "3+" in detail and "4+" in detail, f"le diagnostic ne nomme pas l'écart : {detail}"


def test_might_is_right_du_leader_attache_abaisse_le_seuil_attendu():
    """19.04 : le Warboss est dans l'escouade, donc 3+ est le seuil CORRECT pour un troupier.

    C'est le test qui empêche le faux positif : sans la lecture par figurine, le contrôle
    n'aurait vu que « Trooper », qui ne porte pas la capacité, et aurait crié.
    """
    state = _State()
    stats = state.stats
    _check_hit(state, stats, "FOUGHT [MIGHT IS RIGHT] Unit 9 with [Choppa] - Hit 4(3+) - Wound 4(4+)")
    assert stats["fight_hit_threshold_mismatch"][1] == 0


def test_un_bonus_oublie_est_detecte():
    """L'AUTRE sens de l'erreur. Le Warboss est là, le moteur imprime 4+ : le +1 n'a pas joué.

    Un contrôle qui aurait dérivé le bonus du TOKEN serait resté muet ici — token absent, donc
    bonus attendu nul, donc accord parfait avec un moteur qui a tort.
    """
    state = _State()
    stats = state.stats
    _check_hit(state, stats, "FOUGHT Unit 9 with [Choppa] - Hit 4(4+) - Wound 4(4+)")
    assert stats["fight_hit_threshold_mismatch"][1] == 1


def test_le_malus_de_suppression_est_lu_sur_le_token():
    """L'état `suppressed` n'est reconstructible d'AUCUNE donnée statique : le token le porte.

    WS 4, escouade sans Warboss, supprimée → 5+ attendu.
    """
    state = _State(attacker_models=("1#0", "1#1"))
    stats = state.stats
    _check_hit(state, stats, "FOUGHT [SUPPRESSED] Unit 9 with [Choppa] - Hit 4(5+) - Wound 4(4+)")
    assert stats["fight_hit_threshold_mismatch"][1] == 0


def test_bonus_et_malus_se_compensent_dans_l_attendu():
    """Warboss + suppression : `clamp(4 - 1 + 1, 2, 6)` = 4+."""
    state = _State()
    stats = state.stats
    _check_hit(
        state, stats,
        "FOUGHT [MIGHT IS RIGHT] [SUPPRESSED] Unit 9 with [Choppa] - Hit 4(4+) - Wound 4(4+)",
    )
    assert stats["fight_hit_threshold_mismatch"][1] == 0


def test_une_ligne_sans_jet_de_touche_n_est_pas_jugee():
    """[SUSTAINED HITS] / [TORRENT] impriment `Hit None(None+)` : aucun seuil à vérifier."""
    state = _State()
    stats = state.stats
    _check_hit(state, stats, "FOUGHT Unit 9 with [Choppa] - Hit None(None+) - Wound 4(4+)")
    assert stats["fight_hit_threshold_mismatch"][1] == 0
    assert stats["fight_hit_threshold_unverifiable"][1] == 0


def test_deux_ws_divergentes_rendent_la_ligne_non_verifiable():
    """Un troupier (WS4) et le Warboss (WS2) sur la MÊME ligne : le seuil imprimé est unique,
    l'attendu ne l'est pas. On le DIT au lieu de trancher pour l'un des deux."""
    state = _State()
    stats = state.stats
    _check_hit(
        state, stats,
        "FOUGHT [MIGHT IS RIGHT] Unit 9 with [Choppa] - Hit 4(3+) - Wound 4(4+)",
        shooters=("1#0", "1#2"),
    )
    assert stats["fight_hit_threshold_mismatch"][1] == 0
    assert stats["fight_hit_threshold_unverifiable"][1] == 1


def test_socles_vivants_inconnus_rendent_la_ligne_non_verifiable():
    """Sans socles, impossible de savoir si le Warboss vit encore — donc si le +1 s'applique."""
    state = _State()
    state.positions_by_model = {}
    stats = state.stats
    _check_hit(state, stats, "FOUGHT Unit 9 with [Choppa] - Hit 4(4+) - Wound 4(4+)")
    assert stats["fight_hit_threshold_unverifiable"][1] == 1


# ---------------------------------------------------------------------------
# Seuil de blessure — non-régression Litany of Hate
# ---------------------------------------------------------------------------


def _expected_wound(state, desc, *, attacker_id="1", config=None):
    return aw.expected_wound_threshold(
        state, config if config is not None else _config(),
        desc, 1, attacker_id, "Trooper", "Choppa", "9", ("1#0",), is_melee=True,
    )


def test_litany_of_hate_abaisse_le_seuil_de_blessure_attendu():
    """F4 vs E4 = 4+ ; le Chaplain dans l'escouade rend 3+ CORRECT.

    Sans cette prise en compte, toute ligne de mêlée d'une escouade menée par un Chaplain
    sortirait en erreur — le faux positif systématique que cette passe risquait d'introduire.
    """
    state = _State(attacker_models=("1#0", "1#3"))
    state.model_types["1#3"] = "Chaplain"
    assert _expected_wound(state, "FOUGHT Unit 9 - Wound 4(3+)") == 3


def test_sans_chaplain_le_seuil_de_blessure_reste_nu():
    """CONTRE-ÉPREUVE : mêmes F et E, sans porteur → 4+."""
    state = _State(attacker_models=("1#0", "1#1"))
    assert _expected_wound(state, "FOUGHT Unit 9 - Wound 4(4+)") == 4


def test_charge_le_jet_nu_tient_dans_2_12():
    """Sans la capacité, `[Roll: 12]` est le maximum d'un 2D6 : aucun écart."""
    from ai.analyzer_phases.charge_handler import _check_charge_roll_range

    state = _State(attacker_models=("1#0", "1#1"))
    _check_charge_roll_range(
        state, _config(), "l", "Unit 1(0,0) CHARGED Unit 9(5,5) from (0,0) to (4,4) [Roll: 12]",
        "1", 1,
    )
    assert state.stats["charge_roll_out_of_range"][1] == 0


def test_charge_un_13_sans_la_capacite_est_une_erreur():
    """13 est HORS d'un 2D6 nu : le jet imprimé contredit la règle 11.02."""
    from ai.analyzer_phases.charge_handler import _check_charge_roll_range

    state = _State(attacker_models=("1#0", "1#1"))
    _check_charge_roll_range(
        state, _config(), "l", "Unit 1(0,0) CHARGED Unit 9(5,5) from (0,0) to (4,4) [Roll: 13]",
        "1", 1,
    )
    assert state.stats["charge_roll_out_of_range"][1] == 1


def test_charge_un_13_avec_bigboss_et_son_token_est_legitime():
    """2D6+1 va jusqu'à 13, et le token doit le dire. Les deux conditions, ensemble."""
    from ai.analyzer_phases.charge_handler import _check_charge_roll_range

    state = _State(attacker_models=("1#0", "1#4"))
    state.model_types["1#4"] = "Bigboss"
    _check_charge_roll_range(
        state, _config(), "l",
        "Unit 1(0,0) CHARGED Unit 9(5,5) from (0,0) to (4,4) [Roll: 13] [SOMETHIN' TO PROVE]",
        "1", 1,
    )
    assert state.stats["charge_roll_out_of_range"][1] == 0
    assert state.stats["rule_usage"]["PROJ.1.3.charge_roll_bonus"][1] == 1


def test_charge_le_token_manquant_est_une_erreur():
    """Le Bigboss est là, le jet est dans les bornes, mais RIEN ne nomme la capacité.

    Un journal qui tait un modificateur appliqué est un journal qu'aucun lecteur ne peut
    vérifier — c'est le défaut que le token existe pour fermer, donc il se contrôle.
    """
    from ai.analyzer_phases.charge_handler import _check_charge_roll_range

    state = _State(attacker_models=("1#0", "1#4"))
    state.model_types["1#4"] = "Bigboss"
    _check_charge_roll_range(
        state, _config(), "l", "Unit 1(0,0) CHARGED Unit 9(5,5) from (0,0) to (4,4) [Roll: 9]",
        "1", 1,
    )
    assert state.stats["charge_roll_out_of_range"][1] == 1


def test_aucun_porteur_au_roster_ne_coute_aucune_ligne_non_verifiable():
    """Court-circuit par le ROSTER : sans datasheet porteuse, les socles ne sont pas consultés.

    Sans lui, une partie SANS Chaplain paierait la même « ligne non vérifiable » qu'avec, dès
    que les socles vivants de l'attaquant manquent — un contrôle qui cesse de juger là où il
    n'y avait rien à juger.
    """
    state = _State()
    state.positions_by_model = {}
    config = _config(rule_to_units={})
    assert _expected_wound(state, "FOUGHT Unit 9 - Wound 4(4+)", config=config) == 4
