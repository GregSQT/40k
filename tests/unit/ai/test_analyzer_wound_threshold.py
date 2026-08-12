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

    # Discrimination E : F6 vs E_bodyguard=5 → 3+, vs E_leader=7 → 5+ si target_bodyguard_toughness
    # incluait le leader. Sans cet assert, E_bodyguard=4 et E_leader=5 donnent tous deux 3+ avec F6,
    # donc un pool cassé passerait inaperçu.
    discriminant = _config(unit_toughness_by_type={**TOUGHNESS, "Trooper": 5, "Leader": 7})
    assert aw.expected_wound_threshold(
        state, discriminant, "", 1, "Trooper", "Choppa", "9", ("9#2",), is_melee=True
    ) == 3, (
        "l'Endurance du leader (E7) a été incluse dans le pool des bodyguards (E5) — "
        "résultat None (garde hétérogénéité active) ou 5+ (deux gardes cassées), jamais 3+"
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


# ─────────────────────────────────────────────────────────────────────────────
# Une ligne, PLUSIEURS profils d'arme (fusion moteur « A / B »)
# ─────────────────────────────────────────────────────────────────────────────

#: Datasheets du composite. Cas réel du registre : le `DreadnoughtRedemptor` porte Heavy
#: Onslaught Gatling Cannon F6 et Onslaught Gatling Cannon F5, de mêmes ATK/AP/DMG/règles — la
#: clé de fusion moteur les réunit dès que les deux blessent la cible sur le même seuil, et la
#: ligne loguée s'appelle alors « A / B ». `Big Choppa` F6 tient le rôle de la seconde arme.
_COMPOSITE_LIMITS = {
    **ATTACK_LIMITS,
    "Trooper": {
        "cc_str_by_weapon": {"Choppa": 4, "Choppa Lourd": 5, "Big Choppa": 6},
        "rng_str_by_weapon": {"Bolter": 4, "Bolter Lourd": 5, "Big Bolter": 6},
    },
    # Le personnage rattaché ne porte QUE son arme : sur un composite inter-datasheets, chaque
    # figurine ne connaît que son propre profil (règle 19).
    "Leader": {"cc_str_by_weapon": {"Relic Weapon": 4}, "rng_str_by_weapon": {"Relic Bolter": 4}},
}


@pytest.mark.parametrize("is_melee,arme", [(True, "Choppa"), (False, "Bolter")])
def test_a_composite_line_never_invents_a_strength_no_model_carries(is_melee, arme):
    """Les DEUX Forces réelles de la ligne sont rendues, aucune n'est fabriquée.

    L'ancien résolveur de PLAFONDS retenait le `max()` des composantes : F6 pour une ligne qui
    couvre aussi un profil F4. Sur-évaluer un plafond ne peut que sur-autoriser ; sur-évaluer
    une Force fabrique une figurine qui n'existe pas, et le verdict 05.02 porte sur elle.
    """
    fortes = aw.attacker_weapon_strengths(
        _State(), _config(unit_attack_limits=_COMPOSITE_LIMITS),
        f"{arme} / Big {arme}", "Trooper", (), is_melee,
    )
    assert fortes == (4, 6), "les profils de la ligne ont été agrégés en une seule Force"


def test_a_composite_keeps_its_verdict_when_its_profiles_agree_on_the_threshold():
    """F5 et F6 vs E4 : les deux blessent sur 3+, donc la ligne A un attendu unique.

    C'est le cas NOMINAL d'un composite, et non un cas de bord : la clé de fusion du moteur est
    bâtie sur le seuil AFFICHÉ, donc deux profils ne se retrouvent sur une ligne que s'ils
    blessent déjà la cible pareil. Décréter « non vérifiable » dès que les Forces diffèrent
    éteindrait le contrôle sur toutes ces lignes — un compteur qui ne regarde plus rien.
    """
    attendu = aw.expected_wound_threshold(
        _State(), _config(unit_attack_limits=_COMPOSITE_LIMITS), "", 1, "Trooper",
        "Choppa Lourd / Big Choppa", "9", (), is_melee=True,
    )
    assert attendu == 3, "le contrôle s'est aveuglé sur un composite pourtant sans ambiguïté"


def test_a_composite_across_datasheets_resolves_each_profile_on_its_bearer():
    """Composite inter-datasheets : la clé de fusion moteur ne porte pas l'id de la figurine.

    « Choppa / Relic Weapon » frappé par le troupier ET le personnage rattaché : AUCUNE datasheet
    ne porte les deux profils. Exiger que chacune les résolve tous rendrait toutes ces lignes
    non vérifiables ; les résoudre chacune sur son porteur donne ici F4 et F4 → 4+.
    """
    attendu = aw.expected_wound_threshold(
        _State(), _config(unit_attack_limits=_COMPOSITE_LIMITS), "", 1, "Trooper",
        "Choppa / Relic Weapon", "9", ("9#0", "9#2"), is_melee=True,
    )
    assert attendu == 4, (
        "un profil absent de la datasheet du socle a été pris pour un trou de donnée alors "
        "qu'il est porté par l'autre socle de la ligne"
    )


def test_a_composite_whose_profiles_disagree_is_counted_unverifiable_not_as_an_error():
    """F4 et F6 vs E4 : 4+ et 3+. Le seuil imprimé est unique, son attendu ne l'est pas.

    C'est là — et seulement là — que choisir une Force rendait un verdict sur un profil inventé.
    La ligne est écartée et COMPTÉE, jamais comptée en erreur.
    """
    config = _config(unit_attack_limits=_COMPOSITE_LIMITS)
    assert aw.expected_wound_threshold(
        _State(), config, "", 1, "Trooper", "Choppa / Big Choppa", "9", (), is_melee=True,
    ) is None, "un seul des deux profils a tranché pour toute la ligne"

    stats = _stats()
    desc = "FOUGHT Unit 9 with [Choppa / Big Choppa] - Hit 4(3+) - Wound 4(5+)"
    aw.check_wound_threshold(
        _State(), config, stats, desc, desc, 1, "Trooper", "Choppa / Big Choppa", "9", (),
        is_melee=True,
    )
    assert stats["fight_wound_threshold_mismatch"][1] == 0
    assert stats["fight_wound_threshold_unverifiable"][1] == 1


def test_one_weapon_name_with_two_strengths_is_judged_on_the_threshold_not_on_the_force():
    """« Choppa » vaut F4 au troupier et F6 au personnage rattaché, et les deux ont frappé.

    Cas le plus courant du dépôt — « Close Combat Weapon » couvre F2 à F5 selon la datasheet —
    et c'est le cas d'attelage (règle 19) que ce contrôle existe pour surveiller. Deux Forces
    réelles ne rendent pas la ligne muette : elles la rendent muette seulement si elles blessent
    la cible différemment. Vs E2, F4 et F6 blessent toutes deux sur 2+ → verdict ; vs E4, c'est
    4+ et 3+ → le seuil unique imprimé n'a pas d'attendu unique.
    """
    state = _State()
    convergent = _config(unit_toughness_by_type={**TOUGHNESS, "Trooper": 2})
    assert aw.expected_wound_threshold(
        state, convergent, "", 1, "Trooper", "Choppa", "9", ("9#0", "9#2"), is_melee=True
    ) == 2, "le contrôle s'est tu alors que les deux Forces de la ligne donnent le même seuil"
    assert aw.expected_wound_threshold(
        state, _config(), "", 1, "Trooper", "Choppa", "9", ("9#0", "9#2"), is_melee=True
    ) is None, "une des deux Forces a tranché pour toute la ligne (4+ et 3+ vs E4)"


def test_a_striker_whose_datasheet_knows_no_profile_makes_the_line_unverifiable():
    """Le troupier résout « Choppa », le personnage rattaché ne le porte pas du tout.

    Sauter cette figurine rendrait un verdict sur la seule autre — le repli d'escouade que ce
    module refuse, déguisé en per-figurine. La ligne est écartée, pas moyennée.
    """
    assert aw.attacker_weapon_strengths(
        _State(), _config(unit_attack_limits=_COMPOSITE_LIMITS),
        "Choppa", "Trooper", ("9#0", "9#2"), is_melee=True,
    ) is None, "une figurine dont la datasheet ignore l'arme a été silencieusement sautée"


def test_a_composite_profile_unknown_to_every_striker_is_unverifiable():
    """Un profil qu'AUCUNE figurine de la ligne ne connaît (F symbolique du registre, arme
    absente) : c'est un vrai trou de donnée, pas une répartition entre porteurs."""
    assert aw.attacker_weapon_strengths(
        _State(), _config(unit_attack_limits=_COMPOSITE_LIMITS),
        "Choppa / Choppa Inconnu", "Trooper", (), is_melee=True,
    ) is None, "un profil irrésolu a été silencieusement ignoré au lieu d'écarter la ligne"


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
