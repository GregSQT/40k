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


def _expected(state, action_desc="", *, melee=True, attacker="Trooper", weapon="Choppa",
              config=None, shooters=()):
    """Point d'appel unique d'`expected_wound_threshold`. `config=` porte une autre table,
    `shooters=` la résolution par FIGURINE."""
    return aw.expected_wound_threshold(
        state, config if config is not None else _config(),
        action_desc, 1, attacker, weapon, "9", shooters, is_melee=melee
    )


def _strengths(config=None, *, weapon="Choppa", shooters=(), melee=True, state=None):
    """Point d'appel unique d'`attacker_weapon_strengths`. Même rôle que `_expected` un cran
    plus bas : les invariants de RÉSOLUTION de Force se vérifient ici, ceux du VERDICT là-haut."""
    return aw.attacker_weapon_strengths(
        state if state is not None else _State(),
        config if config is not None else _config(),
        weapon, "Trooper", shooters, melee,
    )


def _composite(**overrides):
    """`_config` armé de `_COMPOSITE_LIMITS`, la table que toute la section « A / B » consulte."""
    return _config(unit_attack_limits=_COMPOSITE_LIMITS, **overrides)


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
    par_figurine = _expected(state, shooters=("9#2",))
    assert par_figurine == 3, (
        "la F est prise sur la datasheet d'ESCOUADE : un personnage rattaché serait mesuré à "
        "l'arme du troupier"
    )

    # Discrimination E : F6 vs E_bodyguard=5 → 3+, vs E_leader=7 → 5+ si target_bodyguard_toughness
    # incluait le leader. Sans cet assert, E_bodyguard=4 et E_leader=5 donnent tous deux 3+ avec F6,
    # donc un pool cassé passerait inaperçu.
    discriminant = _config(unit_toughness_by_type={**TOUGHNESS, "Trooper": 5, "Leader": 7})
    assert _expected(state, config=discriminant, shooters=("9#2",)) == 3, (
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


def _check(state, stats, desc, *, config=None, weapon="Choppa", melee=True):
    aw.check_wound_threshold(
        state, config if config is not None else _config(),
        stats, desc, desc, 1, "Trooper", weapon, "9", (), is_melee=melee,
    )


def test_a_wrong_threshold_is_counted_and_explained():
    stats = _stats()
    _check(_State(), stats, "FOUGHT Unit 9 with [Choppa] - Hit 4(3+) - Wound 4(5+)")
    assert stats["fight_wound_threshold_mismatch"][1] == 1
    detail = stats["first_error_lines"]["fight_wound_threshold_mismatch"][1]["detail"]
    assert "5+" in detail and "4+" in detail, f"le diagnostic ne nomme pas l'écart : {detail}"


# ─────────────────────────────────────────────────────────────────────────────
# Magnitude Oath of Moment lue depuis EFFECTS (TROU 2 — §1.4)
# ─────────────────────────────────────────────────────────────────────────────

def test_oath_magnitude_read_from_effects_not_hardcoded():
    """VERROU : remplacer `oath_mag` par `1` fixe rend ce test ROUGE.

    Scénario discriminant : F4 vs E8 → base 6+.
    - oath_wound=+2 dans EFFECTS + token ⟹ max(2, 6−2) = 4+.
    - ancienne logique (−1 fixe) ou fallback (−1 via `or 1`) ⟹ 5+.
    Le seul moyen d'obtenir 4+ est de lire la magnitude réelle dans EFFECTS.
    """
    # Escouade de Brutes (E8) : ni personnage, ni leader — 19.02 ne filtre rien.
    state = _State()
    state.model_types = {"9#0": "Brute", "9#1": "Brute"}
    state.unit_models_alive = {"9": 2}

    # Prémisse : sans Oath, F4 vs E8 → 6+.
    assert _expected(state, _NO_OATH) == 6, "prémisse : F4 vs E8 sans Oath doit valoir 6+"

    # Fallback `or 1` : token présent, EFFECTS absent ⟹ oath_mag=1 (retro-compat).
    state.active_effects = {}
    assert _expected(state, _WOUND_OATH) == 5, (
        "token Oath sans EFFECTS : fallback 1 attendu, seuil = max(2, 6−1) = 5+"
    )

    # Magnitude 2 lue depuis EFFECTS : le seuil doit descendre de 2, pas de 1.
    state.active_effects = {1: {"oath_wound": "+2"}}
    assert _expected(state, _WOUND_OATH) == 4, (
        "oath_wound=+2 dans EFFECTS doit abaisser le seuil de 2 (6+ → 4+), pas de 1 — "
        "si 5+, la magnitude est ignorée et la constante 1 est codée en dur"
    )

    # Sans token Oath, EFFECTS ignoré — le seuil ne bouge pas.
    assert _expected(state, _NO_OATH) == 6, (
        "sans token Oath, la clé EFFECTS ne doit pas abaisser le seuil"
    )


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

    assert _strengths(piege, weapon=weapon, melee=is_melee, state=state) is None, (
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

    assert _strengths(
        piege, weapon=weapon, shooters=("9#2",), melee=is_melee, state=state
    ) is None, (
        "la F de la figurine irrésolue a été reprise sur la datasheet d'ESCOUADE au lieu "
        "d'être déclarée irrésoluble"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Une ligne, PLUSIEURS profils d'arme (fusion moteur « A / B »)
#
# La carte de Force lue (`cc_str_by_weapon` / `rng_str_by_weapon`) est le seul écart entre le
# chemin de tir et celui de mêlée, et un correctif posé d'un seul côté est le défaut le plus
# fréquent de ce dépôt : les tests dont l'issue DÉPEND de cette carte sont donc paramétrés sur les
# deux phases. Les autres portent leur raison de rester en mêlée seule dans leur propre docstring —
# c'est le seul endroit qui ne peut pas se désynchroniser du code qu'ils gardent.
# ─────────────────────────────────────────────────────────────────────────────

#: Datasheets du composite. INVARIANT DE CETTE FIXTURE : chaque entrée modélise un cas RÉEL du
#: registre, et aucun profil n'y est ajouté pour le confort d'un test — un tel ajout lui donnerait
#: deux identités et le lecteur suivant ne saurait plus lequel fait foi. Elle porte deux cas :
#:   - fusion « A / B » sur une MÊME datasheet — le `DreadnoughtRedemptor` porte Heavy Onslaught
#:     Gatling Cannon F6 et Onslaught Gatling Cannon F5, de mêmes ATK/AP/DMG/règles, que la clé de
#:     fusion moteur réunit dès qu'ils blessent la cible pareil ; `Big Choppa` F6 tient ce rôle ;
#:   - composite à DEUX PORTEURS (règle 19) sur la datasheet du personnage rattaché.
_COMPOSITE_LIMITS = {
    **ATTACK_LIMITS,
    "Trooper": {
        "cc_str_by_weapon": {"Choppa": 4, "Choppa Lourd": 5, "Big Choppa": 6},
        "rng_str_by_weapon": {"Bolter": 4, "Bolter Lourd": 5, "Big Bolter": 6},
    },
    # Le personnage rattaché ne porte QUE son arme : chaque figurine ne connaît que son propre
    # profil (règle 19). Sa F6 diffère de la F4 du troupier, et c'est voulu — cf.
    # `test_a_composite_across_datasheets_resolves_each_profile_on_its_bearer`.
    "Leader": {"cc_str_by_weapon": {"Relic Weapon": 6}, "rng_str_by_weapon": {"Relic Bolter": 6}},
}


@pytest.mark.parametrize("is_melee,arme", [(True, "Choppa"), (False, "Bolter")])
def test_a_composite_line_never_invents_a_strength_no_model_carries(is_melee, arme):
    """Les DEUX Forces réelles de la ligne sont rendues, aucune n'est fabriquée.

    L'ancien résolveur de PLAFONDS retenait le `max()` des composantes : F6 pour une ligne qui
    couvre aussi un profil F4. Sur-évaluer un plafond ne peut que sur-autoriser ; sur-évaluer
    une Force fabrique une figurine qui n'existe pas, et le verdict 05.02 porte sur elle.
    """
    fortes = _strengths(_composite(), weapon=f"{arme} / Big {arme}", melee=is_melee)
    assert fortes == (4, 6), "les profils de la ligne ont été agrégés en une seule Force"


@pytest.mark.parametrize("is_melee,ligne", [
    (True, "Choppa Lourd / Big Choppa"), (False, "Bolter Lourd / Big Bolter"),
])
def test_a_composite_keeps_its_verdict_when_its_profiles_agree_on_the_threshold(is_melee, ligne):
    """F5 et F6 vs E4 : les deux blessent sur 3+, donc la ligne A un attendu unique.

    C'est le cas NOMINAL d'un composite, et non un cas de bord : la clé de fusion du moteur est
    bâtie sur le seuil AFFICHÉ, donc deux profils ne se retrouvent sur une ligne que s'ils
    blessent déjà la cible pareil. Décréter « non vérifiable » dès que les Forces diffèrent
    éteindrait le contrôle sur toutes ces lignes — un compteur qui ne regarde plus rien.
    """
    attendu = _expected(_State(), melee=is_melee, weapon=ligne, config=_composite())
    assert attendu == 3, "le contrôle s'est aveuglé sur un composite pourtant sans ambiguïté"


@pytest.mark.parametrize("is_melee,ligne", [
    (True, "Choppa / Relic Weapon"), (False, "Bolter / Relic Bolter"),
])
def test_a_composite_across_datasheets_resolves_each_profile_on_its_bearer(is_melee, ligne):
    """Composite inter-datasheets : la clé de fusion moteur ne porte pas l'id de la figurine.

    « Choppa / Relic Weapon » frappé par le troupier ET le personnage rattaché : AUCUNE datasheet
    ne porte les deux profils. Exiger que chacune les résolve tous rendrait toutes ces lignes
    non vérifiables ; les résoudre chacune sur son porteur donne F4 (troupier) et F6 (rattaché).

    Les DEUX F diffèrent, et c'est ce que le tuple verrouille : la correspondance profil → porteur.
    La non-agrégation, elle, est déjà tuée par quatre autres tests (mesuré).
    """
    assert _strengths(
        _composite(), weapon=ligne, shooters=("9#0", "9#2"), melee=is_melee,
    ) == (4, 6), (
        "un profil absent de la datasheet du socle a été pris pour un trou de donnée alors "
        "qu'il est porté par l'autre socle de la ligne"
    )


@pytest.mark.parametrize("is_melee,ligne", [
    (True, "Choppa / Relic Weapon"), (False, "Bolter / Relic Bolter"),
])
def test_a_composite_across_datasheets_keeps_its_verdict_when_its_bearers_converge(
    is_melee, ligne
):
    """Jumeau du composite d'accord, pour une ligne RÉPARTIE SUR DEUX DATASHEETS.

    Vs E2, F4 et F6 blessent tous deux sur 2+ (F ≥ 2×E) : la ligne garde donc un attendu unique,
    et c'est le seul endroit du fichier où un composite à deux PORTEURS va jusqu'au verdict — le
    composite d'accord, lui, tient ses deux profils sur la MÊME datasheet. Sans ce test, une garde
    qui refuserait purement et simplement les lignes multi-datasheets éteindrait le contrôle sur
    tout le cas d'attelage (règle 19).
    """
    assert _expected(
        _State(), melee=is_melee, weapon=ligne, shooters=("9#0", "9#2"),
        config=_composite(unit_toughness_by_type={**TOUGHNESS, "Trooper": 2}),
    ) == 2, "la ligne a perdu son verdict alors que ses deux porteurs convergent"


@pytest.mark.parametrize("is_melee,ligne", [
    (True, "Choppa / Big Choppa"), (False, "Bolter / Big Bolter"),
])
def test_a_composite_whose_profiles_disagree_is_counted_unverifiable_not_as_an_error(
    is_melee, ligne
):
    """F4 et F6 vs E4 : 4+ et 3+. Le seuil imprimé est unique, son attendu ne l'est pas.

    C'est là — et seulement là — que choisir une Force rendait un verdict sur un profil inventé.
    La ligne est écartée et COMPTÉE, jamais comptée en erreur. Le NOM du compteur (`shoot_` /
    `fight_`) n'a pas besoin d'un contrôle dédié : un incrément posté dans le mauvais compteur
    laisse celui-ci à zéro et rougit déjà l'assertion `== 1` ci-dessous.
    """
    key = "fight_wound_threshold" if is_melee else "shoot_wound_threshold"
    verbe = "FOUGHT" if is_melee else "SHOT"
    config = _composite()
    assert _expected(
        _State(), melee=is_melee, weapon=ligne, config=config
    ) is None, "un seul des deux profils a tranché pour toute la ligne"

    stats = _stats()
    desc = f"{verbe} Unit 9 with [{ligne}] - Hit 4(3+) - Wound 4(5+)"
    _check(_State(), stats, desc, config=config, weapon=ligne, melee=is_melee)
    assert stats[f"{key}_mismatch"][1] == 0
    assert stats[f"{key}_unverifiable"][1] == 1


def test_one_weapon_name_with_two_strengths_is_judged_on_the_threshold_not_on_the_force():
    """« Choppa » vaut F4 au troupier et F6 au personnage rattaché, et les deux ont frappé.

    Cas le plus courant du dépôt — « Close Combat Weapon » couvre F2 à F5 selon la datasheet —
    et c'est le cas d'attelage (règle 19) que ce contrôle existe pour surveiller. Deux Forces
    réelles ne rendent pas la ligne muette : elles la rendent muette seulement si elles blessent
    la cible différemment. Vs E2, F4 et F6 blessent toutes deux sur 2+ → verdict ; vs E4, c'est
    4+ et 3+ → le seuil unique imprimé n'a pas d'attendu unique.

    MÊLÉE SEULE : un jumeau de TIR serait vide. `STR_RNG` donne F4 au troupier COMME au personnage
    rattaché, donc la prémisse — deux Forces réelles sous un même nom — disparaîtrait en silence,
    et le test resterait vert sans plus rien mesurer.
    """
    state = _State()
    convergent = _config(unit_toughness_by_type={**TOUGHNESS, "Trooper": 2})
    assert _expected(
        state, config=convergent, shooters=("9#0", "9#2")
    ) == 2, "le contrôle s'est tu alors que les deux Forces de la ligne donnent le même seuil"
    assert _expected(
        state, shooters=("9#0", "9#2")
    ) is None, "une des deux Forces a tranché pour toute la ligne (4+ et 3+ vs E4)"


def test_a_striker_whose_datasheet_knows_no_profile_makes_the_line_unverifiable():
    """Le troupier résout « Choppa », le personnage rattaché ne le porte pas du tout.

    Sauter cette figurine rendrait un verdict sur la seule autre — le repli d'escouade que ce
    module refuse, déguisé en per-figurine. La ligne est écartée, pas moyennée.

    MÊLÉE SEULE : « Choppa » ne figure dans AUCUNE des deux cartes de `_COMPOSITE_LIMITS` au tir,
    pas même chez le troupier — un jumeau de tir déclinerait donc dès la première figurine, pour
    une prémisse qui n'existe plus.
    """
    assert _strengths(
        _composite(), weapon="Choppa", shooters=("9#0", "9#2"),
    ) is None, "une figurine dont la datasheet ignore l'arme a été silencieusement sautée"


def test_a_named_model_absent_from_model_types_is_unverifiable():
    """`[SHOOTER_MODELS:]` nomme un socle que `[MODEL_TYPES:]` ne décrit pas (segment optionnel).

    Retomber sur la datasheet d'ESCOUADE mesurerait un personnage rattaché à l'arme du troupier :
    faux « seuil de blessure faux », alors qu'on ne sait simplement pas qui a frappé.

    MÊLÉE SEULE : le socle `9#7` n'a AUCUN type, donc aucune carte de Force n'entre jamais en jeu
    — le chemin de tir refait le même trajet pour la même réponse. Raison de FIXTURE, pas d'ordre
    d'exécution : elle reste vraie quoi que fasse la boucle de production.
    """
    assert _strengths(
        weapon="Choppa", shooters=("9#7",),
    ) is None, "un socle de type inconnu a été mesuré à la datasheet d'escouade"


@pytest.mark.parametrize("is_melee,arme", [(True, "Choppa"), (False, "Bolter")])
def test_a_striker_whose_type_is_outside_the_registry_is_unverifiable(is_melee, arme):
    """Le socle est NOMMÉ et son type est connu — mais ce type n'a pas de datasheet.

    Distinct du socle hors `[MODEL_TYPES:]` : là on ignore QUI a frappé, ici on sait qui, et c'est
    sa datasheet qui manque. C'est la garde `limits is None → None`, celle qui décide vraiment,
    et rien ne la vérifiait.

    PIÈGE, et c'est lui qui fait le verrou : la ligne a DEUX porteurs, et l'AUTRE résout le profil
    en entier, donc sauter la figurine sans datasheet laisserait `missing` vide et rendrait `(4,)`.
    Mesuré : sans ce test, la mutation `return None` → `continue` garde toute la suite verte.
    """
    sans_leader = {t: v for t, v in ATTACK_LIMITS.items() if t != "Leader"}
    assert _strengths(
        _config(unit_attack_limits=sans_leader), weapon=arme,
        shooters=("9#0", "9#2"), melee=is_melee,
    ) is None, (
        "la figurine dont le type est hors registre a été sautée : la ligne a été jugée sur "
        "l'autre porteur seul"
    )


@pytest.mark.parametrize("is_melee,ligne", [
    (True, "Choppa / Big Choppa"), (False, "Bolter / Big Bolter"),
])
def test_oath_is_applied_per_profile_before_unanimity_not_after(is_melee, ligne):
    """L'ORDRE des deux étapes change le verdict, et un seul des deux ordres est juste.

    F4 et F6 vs E3 : 3+ et 2+ (F ≥ 2×E). Les deux profils DIVERGENT — sans Oath, la ligne n'a pas
    d'attendu unique et se déclare non vérifiable. Avec Oath, le plancher 2+ les RÉCONCILIE :
    3+ − 1 = 2+, et 2+ ne descend pas. La ligne retrouve un attendu unique, 2+.

    Ce qui doit être unique, c'est la valeur IMPRIMABLE, pas une étape de son calcul — un contrôle
    qui s'éteint sur les lignes Oath est un compteur qui ne regarde plus rien. Mesuré : sans ce
    test, déplacer le `max(2, threshold - 1)` après le test d'unanimité garde la suite verte.

    C'est l'ENDURANCE qui porte la divergence, pas une arme ajoutée — cf. l'invariant de
    `_COMPOSITE_LIMITS`.
    """
    config = _composite(unit_toughness_by_type={**TOUGHNESS, "Trooper": 3})

    assert _expected(
        _State(), _NO_OATH, melee=is_melee, weapon=ligne, config=config
    ) is None, "prémisse : sans Oath, F4 (3+) et F6 (2+) ne s'accordent pas"

    assert _expected(
        _State(), _WOUND_OATH, melee=is_melee, weapon=ligne, config=config
    ) == 2, (
        "Oath a été appliqué APRÈS le test d'unanimité : la ligne a été déclarée non vérifiable "
        "alors que le plancher 2+ réconcilie ses deux profils"
    )


def test_a_composite_profile_unknown_to_every_striker_is_unverifiable():
    """Un profil qu'AUCUNE figurine de la ligne ne connaît (F symbolique du registre, arme
    absente) : c'est un vrai trou de donnée, pas une répartition entre porteurs.

    MÊLÉE SEULE : l'arme inventée manque aux DEUX cartes, le tir ne peut pas casser seul."""
    assert _strengths(
        _composite(), weapon="Choppa / Choppa Inconnu",
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
