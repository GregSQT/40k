"""Une escouade HÉTÉROGÈNE ne doit pas mourir avant l'heure dans l'état reconstruit.

DÉFAUT VERROUILLÉ (mesuré le 2026-08-09, section 2.8 « unités tuées à tort »). L'analyzer
donnait à CHAQUE figurine d'une escouade le `HP_MAX` de la datasheet de tête
(`unit_hp_max_per_model`, une seule valeur par escouade). L'escouade 105 est déclarée
`HP_MAX=2` mais porte un CaptainRelicShield à 6 PV et un Ancient à 4 : **20 PV côté moteur,
14 côté analyzer**. L'analyzer l'épuisait six points trop tôt et la déclarait détruite alors
que l'Ancient tenait encore.

Ce n'est pas qu'une ligne de rapport fausse. Les contrôles filtrent leurs unités sur
`unit_hp > 0` — une escouade tuée à tort DISPARAÎT de la mesure et produit des faux
**négatifs** ailleurs (l'engagement du move, notamment). Un instrument qui perd des unités
rend des rapports propres pour la mauvaise raison.

Second défaut, découvert en corrigeant le premier : `unit_models_alive` est resynchronisé
depuis le `[MODELS:]` de chaque ligne alors que la file des PV ne se vidait qu'aux pertes que
l'analyzer attribue lui-même. Les deux dérivaient, et l'escouade mourait avec des PV encore en
attente dans la file (mesuré : `alive=0` avec `queue=[6, 4]`). Corriger les PV sans recaler la
file ne réparait donc rien.
"""

from __future__ import annotations

from typing import Dict, List

import pytest

import ai.analyzer as an
import ai.analyzer_core as core


SQUAD = "105"
# Composition réelle du témoin : 5 troupiers à 2 PV, un Captain à 6, un Ancient à 4 = 20 PV.
MODEL_TYPES = {
    "105#0": "Intercessor", "105#1": "Intercessor", "105#2": "Intercessor",
    "105#3": "IntercessorGrenadeLauncher", "105#4": "IntercessorSergeant",
    "105#5": "CaptainRelicShield", "105#6": "Ancient",
}
HP_BY_TYPE = {
    "Intercessor": 2, "IntercessorGrenadeLauncher": 2, "IntercessorSergeant": 2,
    "CaptainRelicShield": 6, "Ancient": 4,
}
CHARACTERS = {"CaptainRelicShield", "Ancient"}
SQUAD_TOTAL_HP = sum(HP_BY_TYPE[t] for t in MODEL_TYPES.values())
SQUAD_HP_MAX = 2          # la datasheet de TÊTE — l'ancienne valeur unique


class _FakeState:
    """État minimal : uniquement ce que lisent les helpers de PV par figurine."""

    def __init__(self) -> None:
        self.model_types: Dict[str, str] = dict(MODEL_TYPES)
        self.unit_hp_squad_max: Dict[str, int] = {SQUAD: SQUAD_HP_MAX}
        self.unit_model_hp_queue: Dict[str, List[int]] = {}


class _FakeConfig:
    """Registry minimal. Les `UNIT_RULES` portent le rôle d'allocation, comme en production :
    c'est le moteur (`_derive_model_role`) qui les lit, jamais une table locale."""

    class _Registry:
        units = {
            t: {
                "HP_MAX": hp,
                "UNIT_RULES": ([{"ruleId": "leader"}] if t in CHARACTERS else []),
            }
            for t, hp in HP_BY_TYPE.items()
        }

    unit_registry = _Registry()


@pytest.fixture
def state_config():
    return _FakeState(), _FakeConfig()


def _mids() -> List[str]:
    return list(MODEL_TYPES)


# ─────────────────────────────────────────────────────────────────────────────
# Prémisses : sans elles, un vert ne prouverait rien
# ─────────────────────────────────────────────────────────────────────────────

def test_premise_the_squad_is_heterogeneous():
    assert SQUAD_TOTAL_HP != SQUAD_HP_MAX * len(MODEL_TYPES), (
        "escouade homogène : l'ancien modèle à valeur unique donnerait le même total et ce "
        "fichier ne verrouillerait rien"
    )
    assert SQUAD_TOTAL_HP == 20 and SQUAD_HP_MAX * len(MODEL_TYPES) == 14


# ─────────────────────────────────────────────────────────────────────────────
# Le verrou
# ─────────────────────────────────────────────────────────────────────────────

def test_total_squad_hp_matches_the_datasheets(state_config):
    state, config = state_config
    hps = core._hps_in_loss_order(state, config, SQUAD, _mids())
    assert sum(hps) == SQUAD_TOTAL_HP, (
        f"total {sum(hps)} au lieu de {SQUAD_TOTAL_HP} : les PV ne sont pas lus par figurine, "
        "l'escouade mourra trop tôt dans l'état reconstruit (section 2.8)"
    )


def test_characters_absorb_last(state_config):
    """Ordre 06.02, et c'est ce que montre le témoin : l'Ancient survit à ses Intercessors."""
    state, config = state_config
    hps = core._hps_in_loss_order(state, config, SQUAD, _mids())
    assert hps[-2:] == [6, 4], f"CHARACTER pas en fin d'ordre d'encaissement : {hps}"
    assert hps[:5] == [2, 2, 2, 2, 2]


def test_unknown_datasheet_falls_back_to_the_squad_value(state_config):
    """Journal sans `[MODEL_TYPES:]` : ancien comportement, pas une composition inventée."""
    state, config = state_config
    state.model_types = {}
    hps = core._hps_in_loss_order(state, config, SQUAD, _mids())
    assert hps == [SQUAD_HP_MAX] * len(MODEL_TYPES), (
        "sans datasheet par socle, la file doit retomber sur le HP_MAX d'escouade"
    )


def test_queue_is_resynced_with_the_surviving_models(state_config):
    """Le second défaut : effectif et file doivent suivre la MÊME source.

    Deux figurines perdues hors attribution (le log les montre simplement absentes) → la file
    doit se réduire d'autant, sinon l'escouade meurt avec des PV en attente.
    """
    state, config = state_config
    core._resync_hp_queue(state, config, SQUAD, _mids())
    assert len(state.unit_model_hp_queue[SQUAD]) == len(MODEL_TYPES) - 1

    survivors = ["105#0", "105#5", "105#6"]
    core._resync_hp_queue(state, config, SQUAD, survivors)
    queue = state.unit_model_hp_queue[SQUAD]
    assert len(queue) == len(survivors) - 1, (
        f"file de {len(queue)} pour {len(survivors)} figurines vivantes : elle a dérivé de "
        "l'effectif, et c'est exactement ce qui tuait l'escouade avec [6, 4] en attente"
    )
    assert queue == [6, 4], f"la relève doit être Captain puis Ancient : {queue}"


def test_state_snapshot_hps_are_the_current_ones_not_the_full_ones(state_config):
    """Un instantané `T{n} STATE:` porte les PV RÉELS : la file les prend tels quels."""
    state, config = state_config
    blesses = {mid: 1 for mid in _mids()}
    hps = core._hps_in_loss_order(state, config, SQUAD, _mids(), blesses)
    assert hps == [1] * len(MODEL_TYPES), (
        "les PV de l'instantané sont ignorés au profit des PV pleins — l'état reconstruit "
        "« soignerait » l'escouade à chaque instantané"
    )
