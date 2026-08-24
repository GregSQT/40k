"""Rerolls to-wound au TIR dans le chemin VIF (_manual_roll_intent).

Comble l'asymetrie tir/fight (V11 §9.2 P1) : `reroll_1_towound` et
`reroll_towound_target_on_objective` etaient appliques en melee
(_manual_roll_fight_intent) mais PAS au tir. Ces tests passent par `_manual_roll_intent`
(vrai `get_unit_by_id` + vrai `is_unit_on_objective`) : ils verrouillent le CABLAGE, pas un
helper isole. Le RNG est rendu deterministe en monkeypatchant shared_utils.random.randint.

Mecanique de reroll (miroir fight, conforme 01 Core « Re-rolls ») : un de ne se re-roll
qu'une fois ; le second resultat est accepte tel quel.
"""
import random

from engine.phase_handlers import shooting_handlers
from engine.game_state import initial_faction_ability_state
from tests.unit.engine._roll_helpers import roll_shoot_intent


# Une regle d unite qui ACCORDE un effet doit porter un `displayName` non vide : le moteur le
# lit pour nommer l abilite dans le combat log (contrat de
# `get_source_unit_rule_display_name_for_effect`, deja porteur ailleurs en production). Les
# fixtures minimales `{"ruleId": ...}` decrivaient une regle invalide.
_TARGETED_INTERCESSION = {"ruleId": "reroll_1_towound", "displayName": "Targeted Intercession"}


def _seq_randint(monkeypatch, rolls):
    """Force random.randint a rendre `rolls` dans l'ordre (_manual_roll_intent fait
    `import random` local -> on patche le module random lui-meme)."""
    seq = list(rolls)

    def fake(a, b):
        assert seq, "sequence RNG epuisee : le code a tire plus de des que prevu"
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)
    # Le tir non-IGNORES_COVER consulte la LoS : on neutralise le cover (hors sujet ici).
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})
    return seq


def _game_state(unit_rules, target_col=9, target_row=9, model_col=None, model_row=None,
                base_size=1):
    """1 tireur (arme sans regle speciale) + 1 cible ; objectif en (5,5).

    Regle 14.02 : « a model is within range of a terrain objective while it is within that
    terrain area » — la presence sur l objectif se juge PAR FIGURINE, sur l empreinte de socle.
    D ou deux jeux de coordonnees distincts dans cette doublure :
      - `target_col/row` : l ANCRE d escouade (units_cache), qui ne decide PLUS de rien ;
      - `model_col/row` + `base_size` : la FIGURINE (models_cache), qui decide.
    Par defaut la figurine est posee sur l ancre (cas courant, escouade a une figurine).
    """
    weapon = {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "WEAPON_RULES": [], "code": "test_gun", "display_name": "Gun"}
    attacker = {"id": "A1", "squad_id": "1", "T": 4, "RNG_WEAPONS": [weapon]}
    attacker_unit = {"id": "1", "UNIT_RULES": unit_rules}
    target_model = {
        "id": "T1", "T": 4, "HP_CUR": 2, "HP_MAX": 2,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "role": None, "unitType": "Grunt",
        "col": target_col if model_col is None else model_col,
        "row": target_row if model_row is None else model_row,
        "level": 0, "BASE_SHAPE": "round", "BASE_SIZE": base_size,
    }
    target_unit = {"id": "2", "UNIT_RULES": []}
    game_state = {
        # Etat de depart des capacites de faction, par le constructeur canonique du moteur
        # (`w40k_core` l'appelle a l'init ET au reset). La resolution d'une attaque lit
        # `oath_target` / `waaagh_active` en `require_key` : un game_state litteral qui les
        # omet decrit une partie impossible.
        **initial_faction_ability_state(),
        "models_cache": {"A1": attacker, "T1": target_model},
        "squad_models": {"2": ["T1"]},
        "squad_cache": {"2": {"model_count_at_start": 1}},
        "units_cache": {
            "2": {"col": target_col, "row": target_row, "VALUE": 10.0, "player": 1,
                  "orientation": 0},
        },
        "unit_by_id": {"1": attacker_unit, "2": target_unit},
        "objectives": [{"id": "o1", "hexes": [[5, 5]]}],
    }
    intent = {"model_id": "A1", "target_unit_id": "2", "weapon_index": 0, "n_attacks_resolved": 1}
    return game_state, intent


def test_reroll_1_towound_rerolls_a_failed_1(monkeypatch):
    """reroll_1_towound : wound=1 (echec) -> reroll=6 (succes). wth=4 (S4 vs T4)."""
    seq = _seq_randint(monkeypatch, [4, 1, 6, 2])  # hit, wound=1, reroll=6, save
    gs, intent = _game_state([_TARGETED_INTERCESSION])

    result = roll_shoot_intent(gs, intent)

    assert result["counts"]["wounds"] == 1
    assert result["shot_records"][0]["strengthResult"] == "SUCCESS"
    assert result["shot_records"][0]["strengthRoll"] == 6
    assert seq == [], "save tire apres succes"


def test_no_rule_does_not_reroll(monkeypatch):
    """Sans reroll : wound=1 reste un echec (pas de reroll)."""
    seq = _seq_randint(monkeypatch, [4, 1])  # hit, wound=1 -> FAILED, pas de 3e de
    gs, intent = _game_state([])

    result = roll_shoot_intent(gs, intent)

    assert result["counts"]["wounds"] == 0
    assert result["shot_records"][0]["strengthResult"] == "FAILED"
    assert seq == [], "aucun de de reroll ni de save tire"


def test_reroll_1_towound_ignores_non_1_failure(monkeypatch):
    """reroll_1_towound ne reroll QUE le 1 : un echec a 3 (non-1) n'est pas rejoue."""
    seq = _seq_randint(monkeypatch, [4, 3])  # hit, wound=3 (<4, mais != 1) -> FAILED, pas de reroll
    gs, intent = _game_state([{"ruleId": "reroll_1_towound"}])

    result = roll_shoot_intent(gs, intent)

    assert result["counts"]["wounds"] == 0
    assert seq == []


def test_reroll_towound_on_objective_rerolls_any_failure(monkeypatch):
    """reroll_towound_target_on_objective : cible sur objectif -> reroll de TOUT echec (ici 3)."""
    seq = _seq_randint(monkeypatch, [4, 3, 5, 2])  # hit, wound=3 (echec), reroll=5 (succes), save
    gs, intent = _game_state([dict(_TARGETED_INTERCESSION, ruleId="reroll_towound_target_on_objective")],
                             target_col=5, target_row=5)

    result = roll_shoot_intent(gs, intent)

    assert result["counts"]["wounds"] == 1
    assert result["shot_records"][0]["strengthRoll"] == 5
    assert seq == []


def test_reroll_towound_on_objective_inactive_off_objective(monkeypatch):
    """Meme regle, cible HORS objectif -> pas de reroll (discrimination on/off objectif)."""
    seq = _seq_randint(monkeypatch, [4, 3])  # hit, wound=3 -> FAILED, pas de reroll
    gs, intent = _game_state([{"ruleId": "reroll_towound_target_on_objective"}], target_col=9, target_row=9)

    result = roll_shoot_intent(gs, intent)

    assert result["counts"]["wounds"] == 0
    assert seq == []


# --- 14.02 : la presence sur l objectif se lit PAR FIGURINE, pas sur l ancre d escouade -------
#
# `is_unit_on_objective` comparait l ANCRE d escouade a un hexe d objectif, par egalite stricte.
# Deux erreurs cumulees, et le meme moteur repondait deja autrement a la meme question pour le
# CONTROLE d objectif (`sum_objective_control_oc_multi` : empreinte de socle, par figurine) :
#   1. l ancre n est pas une figurine — une escouade etalee a des figurines dans la zone sans
#      que son ancre y soit (et l inverse) ;
#   2. l egalite de centre ignore l empreinte du socle — un socle large recouvre la zone sans
#      que son centre y soit.
# Les deux cas ci-dessous construisent exactement ces situations. Ils sont ROUGES sur l ancienne
# lecture par ancre : le reroll ne se declenchait pas, le 3 restait un echec.

def test_reroll_on_objective_follows_the_model_not_the_squad_anchor(monkeypatch):
    """ANCRE hors zone, FIGURINE dans la zone -> l unite est sur l objectif (14.02)."""
    seq = _seq_randint(monkeypatch, [4, 3, 5, 2])  # hit, wound=3 (echec), reroll=5 (succes), save
    gs, intent = _game_state(
        [dict(_TARGETED_INTERCESSION, ruleId="reroll_towound_target_on_objective")],
        target_col=9, target_row=9,   # ancre d escouade LOIN de l objectif (5,5)
        model_col=5, model_row=5,     # la figurine, elle, est dessus
    )

    result = roll_shoot_intent(gs, intent)

    assert result["counts"]["wounds"] == 1
    assert result["shot_records"][0]["strengthRoll"] == 5
    assert seq == []


def test_reroll_on_objective_follows_the_base_footprint(monkeypatch):
    """CENTRE de figurine hors zone, EMPREINTE de socle dessus -> l unite est sur l objectif.

    Socle rond de 3 centre en (4,5) : son empreinte contient (5,5), l hexe de l objectif.
    """
    from engine.hex_utils import compute_occupied_hexes
    assert (5, 5) in compute_occupied_hexes(4, 5, "round", 3)
    assert (4, 5) != (5, 5)

    seq = _seq_randint(monkeypatch, [4, 3, 5, 2])
    gs, intent = _game_state(
        [dict(_TARGETED_INTERCESSION, ruleId="reroll_towound_target_on_objective")],
        target_col=9, target_row=9,
        model_col=4, model_row=5, base_size=3,
    )

    result = roll_shoot_intent(gs, intent)

    assert result["counts"]["wounds"] == 1
    assert result["shot_records"][0]["strengthRoll"] == 5
    assert seq == []


def test_reroll_on_objective_inactive_when_no_model_reaches_the_zone(monkeypatch):
    """Ancre ET figurine hors zone, socle de 1 -> pas de reroll (le controle reste discriminant)."""
    seq = _seq_randint(monkeypatch, [4, 3])  # hit, wound=3 -> FAILED, pas de reroll
    gs, intent = _game_state(
        [{"ruleId": "reroll_towound_target_on_objective"}],
        target_col=9, target_row=9, model_col=7, model_row=7,
    )

    result = roll_shoot_intent(gs, intent)

    assert result["counts"]["wounds"] == 0
    assert seq == []


# --- La cle `objectives` absente est un ETAT CORROMPU, jamais « pas d objectif » -------------
#
# `is_unit_on_objective` EXIGEAIT `game_state["objectives"]` avant l unification 14.02 ; celle-ci
# l avait relachee en `.get(...)` renvoyant `[]`. Consequence : un game_state ampute aurait rendu
# « pas sur l objectif » pour TOUTE unite, desarmant cette regle de relance sans un mot. Un
# scenario reellement sans objectif est une LISTE VIDE — que le moteur pose inconditionnellement
# (w40k_core : `"objectives": self._scenario_objectives`), et qui reste acceptee ci-dessous.


def test_a_missing_objectives_key_raises_instead_of_silently_disabling_the_rule():
    """VERROU : en remettant `.get("objectives")` dans `unit_is_within_objective`, ce test
    devient ROUGE — l appel rend `False` au lieu de lever, et la regle s eteint en silence."""
    import pytest

    from engine.game_state import unit_is_within_objective

    gs, _intent = _game_state(
        [{"ruleId": "reroll_towound_target_on_objective"}], model_col=5, model_row=5
    )
    assert unit_is_within_objective(gs, "2") is True, "montage inerte : l unite doit etre dessus"

    del gs["objectives"]
    with pytest.raises(Exception):
        unit_is_within_objective(gs, "2")


def test_a_table_without_objectives_is_an_empty_list_and_stays_legal():
    """Liste vide = configuration legitime : la reponse est False, sans erreur."""
    from engine.game_state import unit_is_within_objective

    gs, _intent = _game_state(
        [{"ruleId": "reroll_towound_target_on_objective"}], model_col=5, model_row=5
    )
    gs["objectives"] = []

    assert unit_is_within_objective(gs, "2") is False


# --- Parseur UNIQUE des zones d objectif ------------------------------------------------------
#
# `fight_handlers._fight_v11_objective_hex_sets` etait une SECONDE implementation de la meme
# question (« quels hexes forment la zone de chaque objectif ? »), tolerante la ou celle du
# moteur est stricte. Sur des donnees propres les deux coincidaient — mesure sur le scenario
# d entrainement : 5 zones, tailles identiques. Sur une entree abimee elles rendaient des listes
# de LONGUEURS DIFFERENTES dans le meme etat de jeu : l observation et la recompense voyaient N
# objectifs pendant que la consolidation 12.08 en voyait N-1, sans erreur ni log.


def test_a_malformed_objective_raises_instead_of_disappearing_from_the_fight_phase():
    """VERROU : la version fight `continue`-ait sur un objectif non-dict et ecartait un `hexes`
    absent. Les deux cas doivent lever, pour les DEUX appelants — c est le meme parseur."""
    import pytest

    from engine.game_state import objective_hex_sets, objective_hex_zones

    gs, _intent = _game_state([{"ruleId": "reroll_towound_target_on_objective"}])
    assert len(objective_hex_zones(gs)) == 1, "montage inerte : il faut un objectif valide"

    gs["objectives"] = [{"id": "o1"}]  # `hexes` absent
    for reader in (objective_hex_zones, objective_hex_sets):
        with pytest.raises(Exception):
            reader(gs)

    gs["objectives"] = [{"id": "o1", "hexes": [[5]]}]  # entree de longueur 1
    for reader in (objective_hex_zones, objective_hex_sets):
        with pytest.raises(Exception):
            reader(gs)


def test_an_empty_objective_zone_raises_where_it_names_the_objective():
    """Zone vide : erreur ICI, et pas `min_distance_between_sets` vingt appels plus loin.

    La version fight ECARTAIT l objectif (`if s:`), donc la consolidation 12.08 l ignorait en
    silence pendant que l observation et la recompense continuaient de le compter.
    """
    import pytest

    from engine.game_state import objective_hex_zones

    gs, _intent = _game_state([{"ruleId": "reroll_towound_target_on_objective"}])
    gs["objectives"] = [{"id": "o_vide", "hexes": []}]

    with pytest.raises(ValueError, match="o_vide"):
        objective_hex_zones(gs)


def test_the_zone_order_matches_game_state_objectives():
    """L ordre EST un contrat : `get_objective_control(zone_idx)` indexe la meme liste."""
    from engine.game_state import objective_hex_sets, objective_hex_zones

    gs, _intent = _game_state([{"ruleId": "reroll_towound_target_on_objective"}])
    gs["objectives"] = [
        {"id": "a", "hexes": [[1, 1]]},
        {"id": "b", "hexes": [[2, 2], [3, 3]]},
        {"id": "c", "hexes": [[4, 4]]},
    ]

    assert [oid for oid, _z in objective_hex_zones(gs)] == ["a", "b", "c"]
    assert [len(z) for z in objective_hex_sets(gs)] == [1, 2, 1]


def test_the_footprint_follows_the_per_model_orientation_not_the_squad_one():
    """Une figurine PIVOTEE seule garde son orientation propre (socle non rond).

    LE DEFAUT. `iter_living_model_footprints` ne lisait QUE l orientation d ESCOUADE
    (`units_cache[uid]["orientation"]`), alors que `update_model_position` pose une orientation
    PAR FIGURINE lors d un pivot a la molette sans jamais synchroniser l entree d escouade — et
    que `shared_utils._recompute_squad_occupied_hexes`, qui ecrit les empreintes de reference,
    lit bien la valeur par figurine. Deux empreintes differentes pour la meme figurine dans le
    meme etat : le controle d objectif 14.02, la regle de relance et la recompense d objectif
    lisaient la mauvaise.

    VERROU. En remettant `orientation = squad_orientation`, ce test passe au ROUGE : l empreinte
    calculee est celle de l orientation d escouade, donc differente de la reference.

    Socle OVALE : sur un socle rond l orientation n a aucun effet, le controle serait vacant.
    """
    from engine.game_state import iter_living_model_footprints
    from engine.hex_utils import compute_occupied_hexes

    gs, _intent = _game_state([{"ruleId": "reroll_towound_target_on_objective"}])
    model = gs["models_cache"]["T1"]
    model["BASE_SHAPE"] = "oval"
    model["BASE_SIZE"] = [3, 1]
    gs["units_cache"]["2"]["orientation"] = 0
    model["orientation"] = 1  # la figurine a pivote, l escouade non

    attendu = compute_occupied_hexes(
        int(model["col"]), int(model["row"]), "oval", [3, 1], 1
    )
    par_escouade = compute_occupied_hexes(
        int(model["col"]), int(model["row"]), "oval", [3, 1], 0
    )
    assert attendu != par_escouade, "orientation sans effet sur ce socle : le controle serait vacant"

    assert list(iter_living_model_footprints(gs, "2")) == [attendu]


def test_verrou_la_relance_de_blessure_au_tir_est_nommee_sur_le_record(monkeypatch):
    """JUMEAU du fichier melee : `wound_1` -> `woundAbility` sur le record de TIR.

    Ce fichier verrouillait la MECANIQUE (des jetes, resultats) mais jamais le NOM. Le cote
    melee, lui, l'asserte depuis qu'il a ete repare — l'asymetrie classique : le chemin cassé
    gagne un test, le chemin qui marchait n'en a jamais eu. Or les deux passent desormais par
    le meme `stamp_reroll_abilities` : neutraliser sa branche blessure ne rougissait QUE la
    melee.
    """
    seq = _seq_randint(monkeypatch, [4, 1, 5, 2])  # hit, wound=1 (echec), reroll=5 (succes), save
    gs, intent = _game_state([_TARGETED_INTERCESSION])

    rec = roll_shoot_intent(gs, intent)["shot_records"][0]

    assert rec["strengthRoll"] == 5, "la relance a bien joue"
    assert rec["woundAbility"] == "TARGETED INTERCESSION"
    # La CAUSE est consommee : elle ne doit pas atteindre les consommateurs du record.
    assert "woundRerollCause" not in rec
    assert seq == []


def test_verrou_pas_de_nom_de_relance_au_tir_sans_relance(monkeypatch):
    """Contre-epreuve : sans relance, aucun nom — la cle est ABSENTE, pas vide."""
    seq = _seq_randint(monkeypatch, [4, 5, 2])  # hit, wound=5 (succes direct), save
    gs, intent = _game_state([_TARGETED_INTERCESSION])

    rec = roll_shoot_intent(gs, intent)["shot_records"][0]

    assert rec["strengthRoll"] == 5
    assert "woundAbility" not in rec
    assert seq == []
