"""Contrôle du seuil de blessure journalisé (05.02), tir et mêlée.

Le journal écrit le seuil qu'il applique (`Wound 4(4+)`) et rien ne le vérifiait : un seuil
amélioré restait inexplicable, et le +1 Force du Waaagh était journalisé
(`waaagh_melee_str=+1`) sans qu'aucun contrôle ne s'en serve.

Ce que ces tests verrouillent :
  - le seuil attendu vient de `calculate_wound_target`, la fonction du MOTEUR (une copie locale
    de la table 05.02 divergerait le jour où le moteur bouge) ;
  - la Force est celle de l'ARME DE LA FIGURINE qui frappe, pas de la datasheet d'escouade ;
  - le +1 Force du Waaagh s'applique en MÊLÉE seulement (08.04) ;
  - Oath of Moment abaisse le seuil de 1, plancher 2+ ;
  - l'Endurance est celle des BODYGUARDS (19.02), jamais celle du leader rattaché ;
  - une donnée manquante rend la ligne NON VÉRIFIABLE et comptée comme telle — jamais en erreur,
    et jamais silencieusement ignorée.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

import ai.analyzer_wound as aw
from ai.analyzer_config import AnalyzerConfig
from tests.unit.ai._fabriques import analyzer_config


# Roster hétérogène : bodyguards E4, personnage rattaché E5 — 19.02 doit ignorer le second.
MODEL_TYPES = {
    "9#0": "Trooper", "9#1": "Trooper", "9#2": "Leader",
}
TOUGHNESS = {"Trooper": 4, "Leader": 5, "Brute": 8, "Weakling": 3}
STR_CC = {"Trooper": {"Choppa": 4}, "Leader": {"Choppa": 6}, "Brute": {"Choppa": 4},
          "Weakling": {"Choppa": 3}}
STR_RNG = {"Trooper": {"Bolter": 4}, "Leader": {"Bolter": 4}, "Brute": {"Bolter": 4},
           "Weakling": {"Bolter": 3}}
CHARACTERS = {"Leader"}


ATTACK_LIMITS = {
    t: {"cc_str_by_weapon": STR_CC[t], "rng_str_by_weapon": STR_RNG[t]}
    for t in TOUGHNESS
}


class _Registry:
    """Registry PEUPLÉ : `_model_is_character` lit `UNIT_RULES` pour appliquer 19.02."""

    units = {
        t: {"UNIT_RULES": ([{"ruleId": "leader"}] if t in CHARACTERS else [])}
        for t in TOUGHNESS
    }


def _config(**overrides: Any) -> AnalyzerConfig:
    """`AnalyzerConfig` RÉEL, pas une classe canard (`_fabriques.analyzer_config`).

    Un stub local ne porte que les tables que la fonction consulte AUJOURD'HUI : le jour où
    `analyzer_wound` en lit une de plus, il lève un `AttributeError` au lieu de rougir sur ce
    qui a changé, et le vérificateur de types ne voit rien venir. Mesuré : la suppression des
    cartes globales de Force a demandé une édition à la main dans ce fichier, zéro dans les
    douze qui passent par la fabrique.
    """
    return analyzer_config(**{
        "unit_registry": _Registry(),
        "unit_toughness_by_type": TOUGHNESS,
        "unit_attack_limits": ATTACK_LIMITS,
        **overrides,  # un override REMPLACE la valeur par défaut, il ne la double pas
    })


class _State:
    def __init__(self, alive: int = 3, known_models: bool = False) -> None:
        self.model_types = dict(MODEL_TYPES)
        self.unit_models_alive = {"9": alive}
        self.positions_by_model = {"9": {m: (0, 0) for m in MODEL_TYPES}} if known_models else {}
        self.active_effects: Dict[int, Dict[str, str]] = {}
        self.current_episode_num = 1


def _expected(state, action_desc="", *, melee=True, attacker="Trooper", weapon="Choppa"):
    return aw.expected_wound_threshold(
        state, _config(), action_desc, 1, attacker, weapon, "9", (), is_melee=melee
    )


# ─────────────────────────────────────────────────────────────────────────────
# La table 05.02 vient du moteur
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("attacker,expected", [("Trooper", 4), ("Leader", 3)])
def test_threshold_follows_the_engine_table(attacker, expected):
    """F4 vs E4 → 4+ ; F6 vs E4 → 3+. Valeurs de `calculate_wound_target`, pas d'une copie."""
    assert _expected(_State(), attacker=attacker) == expected


def test_strength_is_the_weapon_of_the_model_that_strikes():
    """`[SHOOTER_MODELS:]` désigne le socle : « Choppa » vaut F4 au troupier, F6 au leader."""
    state = _State()
    par_figurine = aw.expected_wound_threshold(
        state, _config(), "", 1, "Trooper", "Choppa", "9", ("9#2",), is_melee=True
    )
    assert par_figurine == 3, (
        "la F est prise sur la datasheet d'ESCOUADE : un personnage rattaché serait mesuré à "
        "l'arme du troupier"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Les modificateurs
# ─────────────────────────────────────────────────────────────────────────────

def test_waaagh_strength_bonus_applies_in_melee_only():
    """08.04 : le +1 F ne touche que les armes de mêlée. Au tir, il n'a pas de jumeau."""
    state = _State()
    assert _expected(state) == 4
    state.active_effects = {1: {"waaagh_melee_str": "+1"}}
    assert _expected(state) == 3, "le +1 F du Waaagh n'est pas lu (F5 vs E4 → 3+)"
    assert _expected(state, melee=False, weapon="Bolter") == 4, (
        "le +1 F de mêlée a été appliqué à un tir — 08.04 ne le prévoit pas"
    )


#: Lignes réalistes : le token Oath n'a de sens que RATTACHÉ à un segment.
_WOUND_OATH = "Hit 4(3+) - Wound 3(4+) [OATH OF MOMENT] - Save 2(4+)"
_HIT_OATH_ONLY = "Hit 4(3+) [REROLLED:2] [OATH OF MOMENT] - Wound 3(4+) - Save 2(4+)"
_NO_OATH = "Hit 4(3+) - Wound 3(4+) - Save 2(4+)"


def test_oath_lowers_the_roll_and_floors_at_two():
    """Oath est un +1 au JET, donc un seuil abaissé, plancher 2+ (`resolve_oath_effects`)."""
    state = _State()
    assert _expected(state, _NO_OATH) == 4, "prémisse : sans Oath, F4 vs E4 = 4+"
    assert _expected(state, _WOUND_OATH) == 3
    # PLANCHER : F6 vs E3, c'est déjà 2+ (F ≥ 2×E) — Oath ne peut pas descendre plus bas.
    faible = _State()
    faible.model_types = {"9#0": "Weakling", "9#1": "Weakling"}
    faible.unit_models_alive = {"9": 2}
    assert _expected(faible, _NO_OATH, attacker="Leader") == 2, "prémisse : base déjà 2+"
    assert _expected(faible, _WOUND_OATH, attacker="Leader") == 2, (
        "Oath descend sous 2+ : le plancher de `resolve_oath_effects` n'est pas respecté"
    )


def test_oath_on_the_hit_reroll_does_not_lower_the_wound_threshold():
    """Le MÊME token marque la relance de TOUCHE — il ne dit alors rien du jet de blessure.

    Mesuré sur le journal : 80 occurrences du token pour 60 lignes, donc des lignes qui le
    portent deux fois. Le chercher n'importe où dans la ligne abaissait le seuil attendu d'un
    point sur toute ligne qui ne l'a QUE côté touche — un faux « seuil de blessure faux ».
    """
    state = _State()
    assert _expected(state, _HIT_OATH_ONLY) == 4, (
        "le token de la relance de touche a été pris pour le bonus de blessure"
    )
    assert aw.wound_bonus_applies(_WOUND_OATH)
    assert not aw.wound_bonus_applies(_HIT_OATH_ONLY)
    assert not aw.wound_bonus_applies(_NO_OATH)


# ─────────────────────────────────────────────────────────────────────────────
# 19.02 : l'Endurance des bodyguards
# ─────────────────────────────────────────────────────────────────────────────

def test_toughness_ignores_the_attached_character():
    """Le leader est E5, les bodyguards E4 : F4 doit rester à 4+, pas passer à 5+."""
    assert _expected(_State(known_models=True)) == 4, (
        "l'E du leader rattaché a été retenue — 19.02 l'interdit explicitement"
    )


def test_falls_back_on_the_roster_when_living_models_are_unknown():
    """Les socles sont effacés à chaque perte : sans repli, le contrôle ne juge plus rien."""
    state = _State(alive=3, known_models=False)
    assert not state.positions_by_model, "prémisse : les socles vivants sont inconnus"
    assert _expected(state) == 4


def test_declines_when_no_bodyguard_is_guaranteed_alive():
    """Roster de 3 dont 1 personnage, 1 seul vivant : impossible de savoir si c'est lui."""
    assert _expected(_State(alive=1, known_models=False)) is None, (
        "le contrôle tranche sur une composition ambiguë au lieu de se déclarer non vérifiable"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Le compteur
# ─────────────────────────────────────────────────────────────────────────────

def _stats() -> Dict[str, Any]:
    keys = ["shoot_wound_threshold", "fight_wound_threshold"]
    stats: Dict[str, Any] = {"first_error_lines": {f"{k}_mismatch": {1: None, 2: None} for k in keys}}
    for k in keys:
        stats[f"{k}_mismatch"] = {1: 0, 2: 0}
        stats[f"{k}_unverifiable"] = {1: 0, 2: 0}
    return stats


def _check(state, stats, desc):
    aw.check_wound_threshold(
        state, _config(), stats, desc, desc, 1, "Trooper", "Choppa", "9", (), is_melee=True
    )


def test_a_wrong_threshold_is_counted_and_explained():
    stats = _stats()
    _check(_State(), stats, "FOUGHT Unit 9 with [Choppa] - Hit 4(3+) - Wound 4(5+)")
    assert stats["fight_wound_threshold_mismatch"][1] == 1
    detail = stats["first_error_lines"]["fight_wound_threshold_mismatch"][1]["detail"]
    assert "5+" in detail and "4+" in detail, f"le diagnostic ne nomme pas l'écart : {detail}"


def test_a_correct_threshold_is_not_counted():
    stats = _stats()
    _check(_State(), stats, "FOUGHT Unit 9 with [Choppa] - Hit 4(3+) - Wound 4(4+)")
    assert stats["fight_wound_threshold_mismatch"][1] == 0
    assert stats["fight_wound_threshold_unverifiable"][1] == 0


def test_an_unverifiable_line_is_counted_apart_never_as_an_error():
    stats = _stats()
    _check(_State(alive=1), stats, "FOUGHT Unit 9 with [Choppa] - Hit 4(3+) - Wound 4(5+)")
    assert stats["fight_wound_threshold_mismatch"][1] == 0
    assert stats["fight_wound_threshold_unverifiable"][1] == 1, (
        "une ligne écartée doit rester VISIBLE : un contrôle qui saute en silence affiche zéro "
        "et se fait oublier"
    )


def test_a_line_without_a_wound_segment_is_ignored_entirely():
    """Blessure automatique ([LETHAL HITS] 24.23) : aucun seuil à vérifier, rien à compter."""
    stats = _stats()
    _check(_State(), stats, "FOUGHT Unit 9 with [Choppa] - Hit 4(3+) - Wound 4")
    assert stats["fight_wound_threshold_mismatch"][1] == 0
    assert stats["fight_wound_threshold_unverifiable"][1] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Ce que le contrôle refuse d'inventer
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "is_melee,weapon,empruntable", [(True, "Choppa", 6), (False, "Bolter", 4)]
)
def test_an_unresolved_weapon_never_borrows_another_datasheets_strength(
    is_melee, weapon, empruntable
):
    """La F se résout sur la datasheet de la FIGURINE, ou pas du tout.

    Une agrégation inter-datasheets — `max()` des datasheets partageant un nom d'arme — est sûre
    pour un PLAFOND d'attaques (on ne peut que sur-autoriser) et INVENTÉE pour une Force :
    « Close Combat Weapon » vaudrait F6 parce qu'une datasheet quelconque le porte, et le
    contrôle crierait « seuil de blessure faux » sur une ligne correcte. Arme irrésolue sur la
    datasheet de la figurine → `None`, ligne écartée et COMPTÉE non vérifiable.

    PIÈGE, et il doit rester mordant : la datasheet de l'attaquant est vidée, les AUTRES restent
    peuplées, et l'arme demandée n'existe QUE chez elles (`Choppa` F6 / `Bolter` F4 sur le
    Leader). Tout emprunt INTER-DATASHEET — carte globale rebranchée, balayage des autres
    types — rend ce test rouge avec cette valeur-là. Vider TOUTES les datasheets rendrait `None`
    inévitable et le test tautologique. Les deux faces ont leur nœud : un emprunt côté tir seul
    ne se cache pas derrière la mêlée.

    Ce piège-ci résout par ESCOUADE (`shooters=()`), donc il ne peut RIEN dire du repli
    escouade — c'est son chemin nominal. Ce repli-là a son propre verrou :
    `test_a_per_model_weapon_never_falls_back_on_the_squad_datasheet`.
    """
    state = _State()
    piege = _config(
        unit_attack_limits={
            **ATTACK_LIMITS,
            "Trooper": {"cc_str_by_weapon": {}, "rng_str_by_weapon": {}},
        }
    )

    assert aw.attacker_weapon_strengths(
        state, piege, weapon, "Trooper", (), is_melee
    ) is None, (
        f"la Force a été empruntée à une autre datasheet (F{empruntable}) au lieu d'être "
        "déclarée irrésoluble"
    )


@pytest.mark.parametrize("is_melee,weapon", [(True, "Choppa"), (False, "Bolter")])
def test_a_per_model_weapon_never_falls_back_on_the_squad_datasheet(is_melee, weapon):
    """Arme irrésolue SUR LA FIGURINE : on décline, on ne retombe pas sur l'escouade.

    Jumeau du piège ci-dessus, sur l'autre chemin : celui-là résout par ESCOUADE
    (`shooters=()`), celui-ci par FIGURINE. Le repli d'escouade existe pour de bon chez le
    jumeau des PLAFONDS (`analyzer_perfig`, `value if value is not None else squad_value`) ;
    l'écrire ici mesurerait la F6 du personnage rattaché à la F4 du troupier — exactement le
    faux « seuil de blessure faux » que ce module existe pour éviter.

    PIÈGE : la datasheet du tireur (`9#2`, Leader) est vidée, celle de l'escouade (Trooper)
    reste peuplée. Tout repli sur l'escouade rend une valeur au lieu de `None` → rouge.
    """
    state = _State()
    piege = _config(
        unit_attack_limits={
            **ATTACK_LIMITS,
            "Leader": {"cc_str_by_weapon": {}, "rng_str_by_weapon": {}},
        }
    )

    assert aw.attacker_weapon_strengths(
        state, piege, weapon, "Trooper", ("9#2",), is_melee
    ) is None, (
        "la F de la figurine irrésolue a été reprise sur la datasheet d'ESCOUADE au lieu "
        "d'être déclarée irrésoluble"
    )


@pytest.mark.parametrize("is_melee,key", [(True, "cc_str_by_weapon"), (False, "rng_str_by_weapon")])
def test_a_composite_profile_of_divergent_strengths_is_unverifiable(is_melee, key):
    """Profil composite « A / B » : le moteur FUSIONNE deux armes sur une seule ligne.

    Cas réel du registre — `DreadnoughtRedemptor`, Heavy Onslaught Gatling Cannon F6 et
    Onslaught Gatling Cannon F5, mêmes ATK/AP/DMG/règles : la clé de fusion moteur les réunit
    dès que les deux blessent la cible sur le même seuil. Le `max()` des PLAFONDS rendait F6,
    une Force que le profil F5 de la même ligne ne porte pas — troisième face du même emprunt
    que les deux pièges ci-dessus, à l'intérieur d'une seule datasheet cette fois. Composantes
    de MÊME F → la ligne garde bien une valeur attendue unique, elle reste vérifiable.
    """
    state = _State()
    limits = {
        **ATTACK_LIMITS,
        "Trooper": {
            "cc_str_by_weapon": {"Choppa": 4, "Big Choppa": 6, "Choppa Jumelle": 4},
            "rng_str_by_weapon": {"Choppa": 4, "Big Choppa": 6, "Choppa Jumelle": 4},
        },
    }
    divergent = _config(unit_attack_limits=limits)

    assert aw.attacker_weapon_strengths(
        state, divergent, "Choppa / Big Choppa", "Trooper", (), is_melee
    ) is None, (
        "la F du composite a été agrégée (F6) : le contrôle 05.02 se prononce sur une valeur "
        "qu'aucune figurine de la ligne ne porte"
    )
    assert aw.attacker_weapon_strengths(
        state, divergent, "Choppa / Choppa Jumelle", "Trooper", (), is_melee
    ) == 4, "un composite HOMOGÈNE reste vérifiable — le contrôle ne doit pas s'aveugler"
    assert limits["Trooper"][key]  # la datasheet du tireur est peuplée : rien n'est tautologique


def test_a_divergent_composite_is_counted_unverifiable_not_as_an_error():
    """Face compteur du test ci-dessus : la ligne est écartée, jamais comptée en erreur."""
    stats = _stats()
    config = _config(unit_attack_limits={
        **ATTACK_LIMITS,
        "Trooper": {
            "cc_str_by_weapon": {"Choppa": 4, "Big Choppa": 6},
            "rng_str_by_weapon": {"Choppa": 4},
        },
    })
    desc = "FOUGHT Unit 9 with [Choppa / Big Choppa] - Hit 4(3+) - Wound 4(5+)"
    aw.check_wound_threshold(
        _State(), config, stats, desc, desc, 1, "Trooper", "Choppa / Big Choppa", "9", (),
        is_melee=True,
    )
    assert stats["fight_wound_threshold_mismatch"][1] == 0
    assert stats["fight_wound_threshold_unverifiable"][1] == 1


def test_roster_fallback_declines_when_bodyguards_have_mixed_toughness():
    """Repli sur le roster = les morts en font partie ; le moteur ne maxe que sur les vivants.

    Bodyguards d'E identiques → la mort d'un socle ne change pas le max, le repli reste exact.
    Bodyguards d'E DIFFÉRENTES → indécidable, et le dire vaut mieux que de trancher.
    """
    homogene = _State()
    homogene.model_types = {"9#0": "Trooper", "9#1": "Trooper", "9#2": "Leader"}
    homogene.unit_models_alive = {"9": 3}
    assert aw.target_bodyguard_toughness(homogene, _config(), "9") == 4

    mixte = _State()
    mixte.model_types = {"9#0": "Trooper", "9#1": "Brute", "9#2": "Leader"}
    mixte.unit_models_alive = {"9": 3}
    assert aw.target_bodyguard_toughness(mixte, _config(), "9") is None, (
        "E maxée sur un roster hétérogène qui contient peut-être des morts : le contrôle "
        "tranche là où la donnée ne permet pas de trancher"
    )

    # Socles vivants CONNUS : plus d'ambiguïté, même roster hétérogène.
    mixte.positions_by_model = {"9": {m: (0, 0) for m in mixte.model_types}}
    assert aw.target_bodyguard_toughness(mixte, _config(), "9") == 8
