"""Primitive A — modificateurs de jet portés par une règle d'unité (chantier 06, passe 1).

Quatre capacités, une seule mécanique : le modificateur porte sur le SEUIL, jamais sur le dé.
`clamp(base - bonus + malus, 2, 6)`, exactement comme le couvert 13.08 et le +1 d'Oath.

    Might Is Right (Warboss)          `hit_roll_bonus_fight`        +1 touche, MÊLÉE
    Litany of Hate (Chaplain JP)      `wound_roll_bonus_fight`      +1 blessure, MÊLÉE
    Somethin' to Prove (Bigboss)      `charge_roll_bonus`           +1 au 2D6 de charge
    (suppression, Wartrakk)           `hit_roll_malus_suppressed`   -1 touche, TOUTES PHASES

CE QUE CES TESTS VERROUILLENT, et pourquoi chacun existe :

- le seuil bouge du bon côté, au TIR comme en MÊLÉE là où la règle le dit, et NULLE PART
  ailleurs — c'est le motif d'échec n°1 de ce dépôt, un effet câblé d'un seul côté ;
- les DEUX bornes du clamp, séparément. Un plancher à 2 sans plafond à 6 (ou l'inverse) est
  précisément ce qui passe inaperçu tant qu'aucune datasheet n'atteint la borne ;
- le 1 non modifié reste un ÉCHEC (05.01) même sous un seuil ramené à 2 : le clamp ne doit
  jamais transformer un 1 en réussite. Le seul verrou qui distingue « modifier le seuil » de
  « modifier le dé » ;
- le CUMUL avec Oath of Moment côté blessure — deux +1 sur le même jet, chacun plafonné par le
  même plancher ;
- le token de journal, sur les deux formateurs.
"""
import random

import pytest

from engine.game_state import initial_faction_ability_state
from tests.unit.engine._roll_helpers import roll_fight_intent, roll_shoot_intent
from tests.unit.engine._state_builders import units_cache_entry as _uc

#: Règles d'unité de la passe, sous la forme exacte des `UNIT_RULES` de datasheet : un
#: `displayName` non vide est un CONTRAT (`get_source_unit_rule_display_name_for_effect`), et
#: c'est ce nom que le journal affiche.
_MIGHT_IS_RIGHT = {"ruleId": "hit_roll_bonus_fight", "displayName": "Might Is Right"}
_LITANY_OF_HATE = {"ruleId": "wound_roll_bonus_fight", "displayName": "Litany of Hate"}
_SOMETHIN_TO_PROVE = {"ruleId": "charge_roll_bonus", "displayName": "Somethin' to Prove"}


def _fixed(monkeypatch, value):
    """Tous les dés valent `value` : le VERDICT ne dépend alors que du seuil."""
    monkeypatch.setattr(random, "randint", lambda a, b: value)


def _seq(monkeypatch, rolls):
    """Dés SCRIPTÉS ; épuisement = erreur explicite, dé en trop = séquence non vide à la fin."""
    seq = list(rolls)

    def fake(a, b):
        assert seq, "sequence RNG epuisee : le moteur a tire plus de des que prevu"
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)
    return seq


def _fight_state(unit_rules, *, ws=4, strength=4, toughness=4, suppressed=False):
    """Attaquant '1' au contact d'une cible '2'. `ws` = caractéristique de l'arme de mêlée."""
    weapon = {"ATK": ws, "STR": strength, "AP": 0, "DMG": 1, "NB": 1,
              "WEAPON_RULES": [], "code": "test_choppa", "display_name": "Choppa"}
    attacker = {"id": "A1", "squad_id": "1", "player": 1, "T": 4, "CC_WEAPONS": [weapon]}
    target_model = {
        "id": "T1", "squad_id": "2", "player": 2, "T": toughness, "HP_CUR": 2, "HP_MAX": 2,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "role": None, "unitType": "Grunt",
        "col": 9, "row": 9, "level": 0, "BASE_SHAPE": "round", "BASE_SIZE": 1,
    }
    game_state = {
        **initial_faction_ability_state(),
        "models_cache": {"A1": attacker, "T1": target_model},
        "squad_models": {"1": ["A1"], "2": ["T1"]},
        "squad_cache": {"1": {"model_count_at_start": 1}, "2": {"model_count_at_start": 1}},
        "units_cache": {
            "1": {"col": 0, "row": 0, "VALUE": 10.0, "player": 1, "orientation": 0},
            "2": {"col": 9, "row": 9, "VALUE": 10.0, "player": 2, "orientation": 0},
        },
        "unit_by_id": {
            "1": {"id": "1", "player": 1, "UNIT_RULES": unit_rules},
            "2": {"id": "2", "player": 2, "UNIT_RULES": []},
        },
        "objectives": [{"id": "o1", "hexes": [[5, 5]]}],
        "suppressed_squads": {"1": 2} if suppressed else {},
        "config": {"game_rules": {"bonus_malus_cap": 0}},
    }
    intent = {"model_id": "A1", "target_unit_id": "2", "weapon_index": 0, "n_attacks_resolved": 1}
    return game_state, intent


def _shoot_state(unit_rules, *, bs=4, suppressed=False):
    """Tireur '1' collé à une cible '2' — la portée n'entre dans aucun verdict de ce fichier."""
    from engine.phase_handlers import shooting_handlers

    weapon = {"ATK": bs, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
              "WEAPON_RULES": [], "code": "test_gun", "display_name": "Gun"}
    attacker = {"id": "A1", "squad_id": "1", "T": 4, "player": 0, "RNG_WEAPONS": [weapon]}
    target_model = {"id": "T1", "T": 4, "HP_CUR": 2, "HP_MAX": 2, "ARMOR_SAVE": 3,
                    "INVUL_SAVE": 7, "role": None, "unitType": "Grunt", "player": 1}
    gs = {
        **initial_faction_ability_state(),
        "models_cache": {"A1": attacker, "T1": target_model},
        "squad_models": {"2": ["T1"]},
        "squad_cache": {"2": {"model_count_at_start": 1}},
        "units_cache": {"1": _uc(0, 0, player=0), "2": _uc(0, 1)},
        "unit_by_id": {
            "1": {"id": "1", "UNIT_RULES": unit_rules},
            "2": {"id": "2", "UNIT_RULES": []},
        },
        "objectives": [], "units_moved": set(), "units_advanced": set(),
        "suppressed_squads": {"1": 2} if suppressed else {},
        "config": {"game_rules": {"bonus_malus_cap": 0}},
    }
    intent = {"model_id": "A1", "target_unit_id": "2", "weapon_index": 0, "n_attacks_resolved": 1}
    return gs, intent, shooting_handlers


def _neutralise_shoot(monkeypatch, shooting_handlers):
    """Couvert, LoS et métrique de distance neutralisés : seul le modificateur d'unité reste."""
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})
    monkeypatch.setattr(
        shooting_handlers, "_ranged_distance_metric", lambda *args, **kwargs: "euclidean"
    )


# ---------------------------------------------------------------------------
# hit_roll_bonus_fight — Might Is Right
# ---------------------------------------------------------------------------


def test_might_is_right_abaisse_le_seuil_de_touche_en_melee(monkeypatch):
    """WS 4+ et +1 au jet : le seuil imprimé descend à 3+, et un 3 touche."""
    _seq(monkeypatch, [3, 5, 2])  # touche=3, blessure, sauvegarde
    gs, intent = _fight_state([_MIGHT_IS_RIGHT], ws=4)

    result = roll_fight_intent(gs, intent)

    rec = result["shot_records"][0]
    assert rec["hitTarget"] == 3, "le +1 au jet se lit comme un seuil abaissé de 1"
    assert rec["hitResult"] == "HIT", "un 3 touche sur 3+"


def test_sans_might_is_right_le_meme_de_rate(monkeypatch):
    """CONTRE-ÉPREUVE, même dé, même arme : sans la capacité, 3 rate sur 4+."""
    _seq(monkeypatch, [3])
    gs, intent = _fight_state([], ws=4)

    result = roll_fight_intent(gs, intent)

    rec = result["shot_records"][0]
    assert rec["hitTarget"] == 4
    assert rec["hitResult"] == "MISS"


def test_might_is_right_ne_descend_jamais_sous_2(monkeypatch):
    """PLANCHER du clamp : WS 2+ reste 2+, la capacité ne peut pas créer un 1+."""
    _seq(monkeypatch, [2, 5, 2])
    gs, intent = _fight_state([_MIGHT_IS_RIGHT], ws=2)

    rec = roll_fight_intent(gs, intent)["shot_records"][0]

    assert rec["hitTarget"] == 2, "clamp bas : aucun modificateur ne descend le seuil sous 2"


def test_le_1_non_modifie_rate_meme_sous_un_seuil_de_2(monkeypatch):
    """05.01, première ligne de la table : « unmodified 1 → FAILS ».

    LE verrou qui distingue « le modificateur agit sur le SEUIL » de « il agit sur le DÉ ». Un
    seuil de 2 accepte tout sauf le 1 — et c'est le socle de résolution qui l'impose, sur le dé
    brut, pas le calcul du seuil.
    """
    _seq(monkeypatch, [1])
    gs, intent = _fight_state([_MIGHT_IS_RIGHT], ws=2)

    rec = roll_fight_intent(gs, intent)["shot_records"][0]

    assert rec["hitTarget"] == 2
    assert rec["hitResult"] == "MISS", "un 1 non modifié rate toujours (05.01)"


def test_might_is_right_ne_touche_pas_le_tir(monkeypatch):
    """« This unit's MELEE WEAPONS have +1 to hit rolls » : aucun jumeau au tir.

    Le câbler des deux côtés serait le défaut symétrique de celui qu'on évite d'habitude — un
    effet appliqué là où le PDF ne le met pas.
    """
    gs, intent, sh = _shoot_state([_MIGHT_IS_RIGHT], bs=4)
    _neutralise_shoot(monkeypatch, sh)
    _fixed(monkeypatch, 4)

    rec = roll_shoot_intent(gs, intent)["shot_records"][0]

    assert rec["hitTarget"] == 4, "le seuil de tir est la caractéristique de l'arme, inchangée"


# ---------------------------------------------------------------------------
# hit_roll_malus_suppressed — suppression
# ---------------------------------------------------------------------------


def test_suppression_degrade_le_seuil_de_touche_au_tir(monkeypatch):
    """« While a unit is suppressed, it has -1 to hit rolls » — aucune restriction de phase."""
    gs, intent, sh = _shoot_state([], bs=4, suppressed=True)
    _neutralise_shoot(monkeypatch, sh)
    _fixed(monkeypatch, 4)

    rec = roll_shoot_intent(gs, intent)["shot_records"][0]

    assert rec["hitTarget"] == 5, "-1 au jet se lit comme un seuil dégradé de 1"
    assert rec["hitResult"] == "MISS", "un 4 ne touche plus sur 5+"


def test_suppression_degrade_aussi_le_seuil_en_melee(monkeypatch):
    """JUMEAU MÊLÉE du test précédent : la règle ne parle d'aucune phase, donc des deux."""
    _seq(monkeypatch, [4])
    gs, intent = _fight_state([], ws=4, suppressed=True)

    rec = roll_fight_intent(gs, intent)["shot_records"][0]

    assert rec["hitTarget"] == 5
    assert rec["hitResult"] == "MISS"


def test_suppression_ne_depasse_jamais_6(monkeypatch):
    """PLAFOND du clamp : une arme à 6+ supprimée reste à 6+, jamais 7+ (injouable)."""
    _seq(monkeypatch, [6, 5, 2])
    gs, intent = _fight_state([], ws=6, suppressed=True)

    rec = roll_fight_intent(gs, intent)["shot_records"][0]

    assert rec["hitTarget"] == 6, "clamp haut : le seuil ne sort pas du D6"


def test_bonus_et_malus_se_compensent(monkeypatch):
    """`clamp(base - bonus + malus, 2, 6)` : les deux sur la même attaque s'annulent.

    Un moteur qui appliquerait les modificateurs en séquence avec un clamp intermédiaire
    rendrait un autre résultat sur les seuils extrêmes ; ici la somme est faite avant le clamp.
    """
    _seq(monkeypatch, [4, 5, 2])
    gs, intent = _fight_state([_MIGHT_IS_RIGHT], ws=4, suppressed=True)

    rec = roll_fight_intent(gs, intent)["shot_records"][0]

    assert rec["hitTarget"] == 4


# ---------------------------------------------------------------------------
# wound_roll_bonus_fight — Litany of Hate
# ---------------------------------------------------------------------------


def test_litany_of_hate_abaisse_le_seuil_de_blessure_en_melee(monkeypatch):
    """F4 vs E4 = 4+ (05.02) ; avec +1 au jet, 3+."""
    _seq(monkeypatch, [4, 3, 2])  # touche, blessure=3, sauvegarde
    gs, intent = _fight_state([_LITANY_OF_HATE], ws=4, strength=4, toughness=4)

    rec = roll_fight_intent(gs, intent)["shot_records"][0]

    assert rec["woundTarget"] == 3
    assert rec["strengthResult"] in ("WOUND", "SUCCESS"), "un 3 blesse sur 3+"


def test_sans_litany_le_meme_de_ne_blesse_pas(monkeypatch):
    """CONTRE-ÉPREUVE : F4 vs E4 reste 4+, et 3 échoue."""
    _seq(monkeypatch, [4, 3])
    gs, intent = _fight_state([], ws=4, strength=4, toughness=4)

    rec = roll_fight_intent(gs, intent)["shot_records"][0]

    assert rec["woundTarget"] == 4
    assert rec["strengthResult"] == "FAILED"


def test_litany_ne_touche_pas_le_tir(monkeypatch):
    """« melee weapons » : le roller de tir n'appelle pas ce helper."""
    gs, intent, sh = _shoot_state([_LITANY_OF_HATE], bs=4)
    _neutralise_shoot(monkeypatch, sh)
    _fixed(monkeypatch, 4)

    rec = roll_shoot_intent(gs, intent)["shot_records"][0]

    assert rec["woundTarget"] == 4, "F4 vs E4 = 4+, inchangé au tir"


def test_litany_se_cumule_avec_oath_et_respecte_le_plancher(monkeypatch):
    """Deux +1 sur le même jet de blessure, un seul plancher.

    F4 vs E8 = 6+ ; Oath -1 = 5+ ; Litany -1 = 4+. Le cumul est le comportement attendu (deux
    sources distinctes, aucune ne s'annule), et le plancher 2 les borne toutes les deux.
    """
    _seq(monkeypatch, [4, 4, 2])
    gs, intent = _fight_state([_LITANY_OF_HATE], ws=4, strength=4, toughness=8)
    # Oath ARMÉ POUR DE VRAI : la cible désignée ne suffit pas, le +1 au jet porte en plus la
    # clause de détachement (`oath_wound_bonus_applies`). Poser le seul `oath_target` rendrait
    # un test vert qui ne mesure QUE Litany — le vert vacant que ce fichier doit éviter.
    gs["oath_target"] = {1: "2", 2: None}
    gs["config"] = {
        "uses_codex_detachment": {"1": True, "2": True},
        "army_faction": {"1": "ADEPTUS ASTARTES", "2": "ORKS"},
        "game_rules": {"bonus_malus_cap": 0},
    }
    gs["unit_by_id"]["1"]["FACTION_KEYWORDS"] = [{"keywordId": "ADEPTUS ASTARTES"}]
    gs["units"] = [gs["unit_by_id"]["1"], gs["unit_by_id"]["2"]]

    rec = roll_fight_intent(gs, intent)["shot_records"][0]

    assert rec["woundTarget"] == 4, "6+ moins Oath moins Litany"


def test_litany_ne_descend_pas_le_seuil_de_blessure_sous_2(monkeypatch):
    """PLANCHER 05.02 : F8 vs E4 vaut déjà 2+, la capacité ne peut pas créer un 1+."""
    _seq(monkeypatch, [4, 2, 2])
    gs, intent = _fight_state([_LITANY_OF_HATE], ws=4, strength=8, toughness=4)

    rec = roll_fight_intent(gs, intent)["shot_records"][0]

    assert rec["woundTarget"] == 2


# ---------------------------------------------------------------------------
# charge_roll_bonus — Somethin' to Prove
# ---------------------------------------------------------------------------


def _charge_state(unit_rules):
    """État minimal pour `roll_charge_distance` : l'escouade '1' et ses règles en vigueur."""
    return {"unit_by_id": {"1": {"id": "1", "player": 1, "UNIT_RULES": unit_rules}}}


def test_somethin_to_prove_ajoute_un_au_jet_de_charge(monkeypatch):
    """« This unit has +1 to charge rolls » : 3 + 3 + 1 = 7, jamais 6."""
    from engine.phase_handlers.shared_utils import roll_charge_distance

    _fixed(monkeypatch, 3)

    assert roll_charge_distance(_charge_state([_SOMETHIN_TO_PROVE]), "1") == 7


def test_sans_la_capacite_le_jet_de_charge_est_nu(monkeypatch):
    """CONTRE-ÉPREUVE, mêmes dés : 3 + 3 = 6."""
    from engine.phase_handlers.shared_utils import roll_charge_distance

    _fixed(monkeypatch, 3)

    assert roll_charge_distance(_charge_state([]), "1") == 6


def test_la_relance_de_charge_garde_le_bonus(monkeypatch):
    """Un dé relancé reste un jet de charge DE CETTE UNITÉ : le +1 s'applique aussi.

    Le bonus vit dans `roll_charge_distance`, seul producteur de jet du moteur, précisément
    pour que la relance ne puisse pas le perdre — c'est le chemin qu'un appelant qui ajouterait
    le +1 de son côté aurait oublié.
    """
    from engine.phase_handlers.shared_utils import roll_charge_distance

    _fixed(monkeypatch, 6)

    assert roll_charge_distance(_charge_state([_SOMETHIN_TO_PROVE]), "1", previous_roll=4) == 13


def test_le_bonus_de_charge_ne_touche_pas_les_jets_d_attaque(monkeypatch):
    """DISCRIMINATION : `charge_roll_bonus` ne modifie ni la touche ni la blessure."""
    _seq(monkeypatch, [4, 5, 2])
    gs, intent = _fight_state([_SOMETHIN_TO_PROVE], ws=4, strength=4, toughness=4)

    rec = roll_fight_intent(gs, intent)["shot_records"][0]

    assert rec["hitTarget"] == 4
    assert rec["woundTarget"] == 4


# ---------------------------------------------------------------------------
# Journal — le seuil imprimé est net, le token dit pourquoi
# ---------------------------------------------------------------------------


def test_les_modificateurs_sont_nommes_sur_le_record(monkeypatch):
    """Sans ces champs, le seuil bouge dans step.log et RIEN n'en donne la cause.

    Les trois sont posés sur le MÊME record : ce sont des propriétés de l'activation, pas d'un
    dé, et ils peuvent jouer ensemble.
    """
    _seq(monkeypatch, [4, 3, 2])
    gs, intent = _fight_state([_MIGHT_IS_RIGHT, _LITANY_OF_HATE], ws=4, suppressed=True)

    rec = roll_fight_intent(gs, intent)["shot_records"][0]

    # MAJUSCULES : `get_source_unit_rule_display_name_for_effect` normalise le `displayName` de
    # la datasheet, comme pour toutes les autres capacites nommees du moteur.
    assert rec["hitRollBonusAbility"] == "MIGHT IS RIGHT"
    assert rec["hitRollMalusAbility"] == "Suppressed"
    assert rec["woundRollBonusAbility"] == "LITANY OF HATE"


def test_aucun_nom_quand_aucun_modificateur_ne_joue(monkeypatch):
    """DISCRIMINATION : clé ABSENTE, jamais posée à None — même contrat que `woundBonusAbility`."""
    _seq(monkeypatch, [4, 5, 2])
    gs, intent = _fight_state([], ws=4)

    rec = roll_fight_intent(gs, intent)["shot_records"][0]

    assert "hitRollBonusAbility" not in rec
    assert "hitRollMalusAbility" not in rec
    assert "woundRollBonusAbility" not in rec


def test_le_choix_d_arme_de_melee_note_les_armes_sur_le_seuil_REELLEMENT_joue():
    """L'heuristique de sélection d'arme doit voir le même seuil que la résolution.

    Le clamp à 2 RAPPROCHE deux armes de seuils voisins : une arme déjà à 2+ ne gagne rien au
    +1, une arme à 4+ gagne un cran plein. Noter les armes sur leur `ATK` brut préfère donc
    parfois celle que le moteur jouera le moins bien — le défaut exact que le `melee_bonus` du
    Waaagh! a déjà corrigé pour la Force et le nombre d'attaques (« une seule définition de
    l'espérance de dégâts »).

    Scénario construit pour que le verdict BASCULE, pas seulement pour qu'il bouge.
    """
    from engine.phase_handlers.shared_utils import _auto_select_cc_weapon_for_fig

    def _w(name, atk, nb, dmg):
        return {"ATK": atk, "STR": 4, "AP": 0, "DMG": dmg, "NB": nb,
                "WEAPON_RULES": [], "code": name, "display_name": name}

    # Arme 0 : touche déjà à 2+, deux attaques à 1 dégât. Arme 1 : 4+, une attaque à 3 dégâts.
    attacker = {"id": "A1", "CC_WEAPONS": [_w("Fine", 2, 2, 1), _w("Lourde", 4, 1, 3)]}
    target = {"id": "2", "UNIT_KEYWORDS": []}

    sans = _auto_select_cc_weapon_for_fig(attacker, 4, 3, 7, target)
    avec = _auto_select_cc_weapon_for_fig(attacker, 4, 3, 7, target, hit_bonus=1)

    assert sans == 0, "sans bonus, l'arme fine touche plus souvent et l'emporte"
    assert avec == 1, "avec le +1, la lourde passe à 3+ et devient la meilleure — le score doit le voir"


def test_le_record_atteint_le_formateur_par_la_table_de_traduction():
    """CHAÎNON MANQUANT entre les deux tests voisins : le moteur nomme, le formateur affiche —
    encore faut-il que la clé du record soit traduite en clé de `details`.

    Sans cette entrée, le champ n'atteint QUE le Game Log PvP : step.log, le replay et l'analyzer
    voient un seuil déplacé sans cause. C'est exactement le trou qu'ont connu `woundAbility` puis
    `waaaghMelee`, et il ne se voit sur aucun des deux autres tests.
    """
    from engine.w40k_core import W40KEngine

    for record_key, details_key in (
        ("hitRollBonusAbility", "hit_roll_bonus_ability"),
        ("hitRollMalusAbility", "hit_roll_malus_ability"),
        ("woundRollBonusAbility", "wound_roll_bonus_ability"),
    ):
        assert W40KEngine._SHOT_RECORD_FIELD_MAP[record_key] == details_key


@pytest.mark.parametrize("formateur", ["shoot", "combat"])
def test_le_token_atteint_les_deux_formateurs(formateur):
    """`[MIGHT IS RIGHT]` en TAG DE LIGNE, sur SHOT comme sur FOUGHT.

    Tag de ligne et non suffixe de segment : `abilityTokensForRoll` (replayParser) ne retient
    qu'UNE capacité par segment de jet, et un second token accolé au segment `Hit` y écraserait
    silencieusement le nom de la relance de touche.
    """
    from ai.step_logger import StepLogger

    logger = StepLogger(enabled=True, buffer_size=1)
    details = {
        "current_turn": 1, "target_id": "2", "weapon_name": "Choppa",
        "hit_roll": 4, "hit_target": 3, "hit_result": "HIT",
        "wound_roll": 4, "wound_target": 3, "wound_result": "WOUND",
        "save_roll": 2, "save_target": 3, "save_result": "FAIL", "damage_dealt": 1,
        "hit_roll_bonus_ability": "Might Is Right",
        "wound_roll_bonus_ability": "Litany of Hate",
        "hit_roll_malus_ability": "Suppressed",
        # Contrat replay des lignes de melee (ignore par le formateur SHOT).
        "fight_subphase": "fight",
    }
    message = logger._format_replay_style_message("1", formateur, details)  # type: ignore[attr-defined]

    assert "[MIGHT IS RIGHT]" in message
    assert "[SUPPRESSED]" in message
    assert "[LITANY OF HATE]" in message
