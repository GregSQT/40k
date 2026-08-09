"""PV par SOCLE dans l'état reconstruit : ni sous-évalués, ni soignés, ni comptés deux fois.

Trois défauts fermés ici, tous mesurés sur de vrais journaux.

1. PV SOUS-ÉVALUÉS (2026-08-09, section 2.8 « unités tuées à tort »). Chaque figurine recevait
   le `HP_MAX` de la datasheet de TÊTE. L'escouade 105 est `HP_MAX=2` mais porte un
   CaptainRelicShield à 6 PV et un Ancient à 4 : 20 PV côté moteur, 14 côté analyzer. Elle
   mourait six points trop tôt — et DISPARAISSAIT alors des contrôles qui filtrent sur les
   unités vivantes, produisant des faux NÉGATIFS ailleurs.

2. FIGURINES SOIGNÉES AU RECALAGE (2026-08-10). Le segment `[MODELS:]` d'une ligne d'action
   donne les socles vivants mais PAS leurs PV. La correction n°1 les stockait dans une FILE
   positionnelle, incapable de dire quel socle portait quels PV : au recalage, la relève était
   reconstruite à PV pleins et les figurines entamées remontaient (`[…, 1, 2, 4]` → `[…, 2, 5,
   4]`). Indexer par socle supprime la question.

3. OVERKILL COMPTÉ DEUX FOIS (2026-08-10). L'analyzer appliquait la règle « l'excès d'une
   blessure qui tue est perdu » à `Dmg:XHP`, qui est le dégât DÉJÀ APPLIQUÉ : mesuré, 14
   intervalles entre instantanés sur 14 donnent `somme(Dmg) == perte de PV réelle`. Retranchée
   deux fois, l'escouade 102 survivait à 4 PV de dégâts pour 4 PV restants, et le contrôle
   « tir sur cible engagée » sonnait sur un tir légal.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

import ai.analyzer as an
import ai.analyzer_core as core


SQUAD = "105"
MODEL_TYPES = {
    "105#0": "Trooper", "105#1": "Trooper", "105#2": "Trooper",
    "105#3": "Trooper", "105#4": "Trooper", "105#5": "Captain", "105#6": "Ancient",
}
HP_BY_TYPE = {"Trooper": 2, "Captain": 6, "Ancient": 4}
CHARACTERS = {"Captain", "Ancient"}
SQUAD_TOTAL_HP = sum(HP_BY_TYPE[t] for t in MODEL_TYPES.values())   # 20
SQUAD_HP_MAX = 2                                                     # datasheet de TÊTE


class _Config:
    class _Registry:
        units = {
            t: {"HP_MAX": hp, "UNIT_RULES": ([{"ruleId": "leader"}] if t in CHARACTERS else [])}
            for t, hp in HP_BY_TYPE.items()
        }

    unit_registry = _Registry()


class _State:
    def __init__(self) -> None:
        self.model_types: Dict[str, str] = dict(MODEL_TYPES)
        self.unit_hp_squad_max: Dict[str, int] = {SQUAD: SQUAD_HP_MAX}
        self.unit_model_hp: Dict[str, Dict[str, int]] = {}
        self.unit_hp: Dict[str, int] = {}
        self.unit_models_alive: Dict[str, int] = {}


@pytest.fixture
def st():
    s = _State()
    core._resync_living_models(s, _Config(), SQUAD, list(MODEL_TYPES))
    return s


def _hps(state) -> List[int]:
    return [state.unit_model_hp[SQUAD][m] for m in core._ordered_living_mids(state, _Config(), SQUAD)]


# ── 1. Les PV viennent de la datasheet de CHAQUE figurine ────────────────────────────────

def test_premise_the_squad_is_heterogeneous():
    assert SQUAD_TOTAL_HP == 20 and SQUAD_HP_MAX * len(MODEL_TYPES) == 14, (
        "escouade homogène : l'ancien modèle donnerait le même total et rien ne serait verrouillé"
    )


def test_total_squad_hp_matches_the_datasheets(st):
    assert sum(_hps(st)) == SQUAD_TOTAL_HP, (
        f"total {sum(_hps(st))} au lieu de {SQUAD_TOTAL_HP} : l'escouade mourra trop tôt (2.8)"
    )


def test_characters_absorb_last(st):
    """Ordre 06.02 — et c'est ce que montre le témoin : l'Ancient survit à ses Intercessors."""
    assert _hps(st)[-2:] == [6, 4], f"CHARACTER pas en fin d'ordre : {_hps(st)}"


def test_unknown_datasheet_falls_back_to_the_squad_value():
    """Journal sans `[MODEL_TYPES:]` : ancien comportement, pas une composition inventée."""
    s = _State()
    s.model_types = {}
    core._resync_living_models(s, _Config(), SQUAD, list(MODEL_TYPES))
    assert _hps(s) == [SQUAD_HP_MAX] * len(MODEL_TYPES)


# ── 2. Le recalage ne soigne personne ────────────────────────────────────────────────────

def test_resync_preserves_known_damage(st):
    """LE défaut du 2026-08-10 : `[MODELS:]` ne porte pas les PV, donc il ne doit pas les créer."""
    st.unit_model_hp[SQUAD]["105#0"] = 1                      # figurine entamée
    core._resync_living_models(st, _Config(), SQUAD, list(MODEL_TYPES))
    assert st.unit_model_hp[SQUAD]["105#0"] == 1, (
        "le recalage a rendu ses PV à une figurine entamée : l'escouade encaissera plus que "
        "ses PV réels et survivra à sa propre mort"
    )


def test_resync_drops_models_absent_from_the_segment(st):
    survivants = ["105#5", "105#6"]
    core._resync_living_models(st, _Config(), SQUAD, survivants)
    assert set(st.unit_model_hp[SQUAD]) == set(survivants)
    assert st.unit_models_alive[SQUAD] == 2
    assert st.unit_hp[SQUAD] == 6, "la front doit être la première de l'ordre 06.02 encore vivante"


def test_snapshot_hps_are_taken_verbatim(st):
    """Un instantané `T{n} STATE:` porte les PV RÉELS : ils s'imposent tels quels."""
    core._resync_living_models(
        st, _Config(), SQUAD, ["105#0", "105#5"], {"105#0": 1, "105#5": 2}
    )
    assert st.unit_model_hp[SQUAD] == {"105#0": 1, "105#5": 2}
    assert st.unit_hp[SQUAD] == 1


# ── 3. L'excès n'est pas retranché deux fois ─────────────────────────────────────────────

def _damage(state, amount: int) -> None:
    stats: Dict[str, Any] = {
        "wounded_enemies": {1: set(), 2: set()}, "current_episode_deaths": [],
        "parse_errors": [], "damage_missing_unit_hp": {1: 0, 2: 0},
        "first_error_lines": {"damage_missing_unit_hp": {1: None, 2: None}},
    }
    an._apply_damage_and_handle_death(
        target_id=SQUAD, attacker_id="1", damage=amount, player=1, turn=1, phase="fight",
        line_number=1, current_episode_num=1, line_text="l",
        dead_units_current_episode=set(), unit_hp=state.unit_hp,
        unit_models_alive=state.unit_models_alive, unit_model_hp=state.unit_model_hp,
        ordered_living_mids=lambda u: core._ordered_living_mids(state, _Config(), u),
        unit_hp_squad_max=state.unit_hp_squad_max, unit_types={SQUAD: "Trooper"},
        unit_positions={SQUAD: (1, 1)}, unit_deaths=[], unit_kill_context={}, stats=stats,
    )


def test_damage_carries_over_to_the_next_model(st):
    """`Dmg:` est le dégât APPLIQUÉ : 3 sur une figurine à 2 PV doit en entamer une seconde."""
    core._resync_living_models(st, _Config(), SQUAD, ["105#0", "105#1"])  # 2 PV chacune
    _damage(st, 3)
    assert st.unit_models_alive[SQUAD] == 1, "la première figurine aurait dû tomber"
    assert st.unit_hp[SQUAD] == 1, (
        "l'excès a été perdu : l'analyzer retranche une seconde fois un overkill que le moteur "
        "a déjà appliqué, et l'escouade survit à des dégâts qui l'ont tuée"
    )


def test_the_witness_squad_dies_on_exactly_its_remaining_hp(st):
    """Le témoin 102 : 4 PV restants (1 + 3), 4 PV de dégâts journalisés → détruite."""
    core._resync_living_models(st, _Config(), SQUAD, ["105#0", "105#1"], {"105#0": 1, "105#1": 3})
    _damage(st, 2)
    _damage(st, 1)
    _damage(st, 1)
    assert SQUAD not in st.unit_hp, (
        "l'escouade survit à 4 PV de dégâts pour 4 PV restants — c'est exactement ce qui faisait "
        "sonner « tir sur cible engagée » (1.2) sur un tir légal"
    )


def test_overkill_stops_at_the_last_model(st):
    """Au-delà de la dernière figurine, l'excès n'a plus de destinataire : pas de récursion folle."""
    core._resync_living_models(st, _Config(), SQUAD, ["105#0"], {"105#0": 1})
    _damage(st, 99)
    assert SQUAD not in st.unit_hp
