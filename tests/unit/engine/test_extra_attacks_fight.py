"""[EXTRA ATTACKS] 24.11 — Select Weapons step de la phase de combat.

PDF 24.11 : « Each time a unit containing one or more models with an [EXTRA ATTACKS] weapon
fights, those models will make attacks with those weapons IN ADDITION to any others. In the
Select Weapons step (04.01), for each of those models, you must select: ALL of that model's
[EXTRA ATTACKS] weapons ; one of that model's other melee weapons, IF POSSIBLE. »

Concernees dans les rosters de training : `urty_syringe` (PainBoy), `relic_blade_captain`,
`relic_fist_captain`, `teeth_and_claws`, `redemptor_fist`.

Verrouille les deux niveaux : la selection (`_select_fight_weapon_indices_for_fig`) et le
CABLAGE dans `squad_declare_fight` (un intent par arme selectionnee + ATTACK_LEFT cumule).
"""
from engine.phase_handlers import shared_utils
from tests._state_invariants import turn_state_invariants
from engine.phase_handlers.shared_utils import (
    _select_fight_weapon_indices_for_fig,
    squad_declare_fight,
)


def _w(name, rules, *, dmg=1, nb=2):
    return {"display_name": name, "code": name, "WEAPON_RULES": list(rules), "ATK": 3, "STR": 4,
            "AP": 0, "DMG": dmg, "NB": nb}


def _fig(weapons):
    return {"id": "A1", "squad_id": "1", "player": 0, "T": 4, "CC_WEAPONS": weapons}


def test_selection_ajoute_les_armes_extra_attacks():
    """Arme normale (index 0) + arme EXTRA ATTACKS (index 1) -> les DEUX sont selectionnees."""
    fig = _fig([_w("Choppa", []), _w("Syringe", ["EXTRA_ATTACKS"])])
    assert _select_fight_weapon_indices_for_fig(fig, 4, 3, 7) == [0, 1]


def test_arme_principale_choisie_parmi_les_non_extra():
    """« one of that model's OTHER melee weapons » : la meilleure arme NON-EXTRA est choisie,
    meme si l arme EXTRA a une meilleure esperance de degats."""
    fig = _fig([
        _w("Faible", [], dmg=1),
        _w("Syringe", ["EXTRA_ATTACKS"], dmg=6),
        _w("Fort", [], dmg=3),
    ])
    assert _select_fight_weapon_indices_for_fig(fig, 4, 3, 7) == [2, 1]


def test_toutes_les_armes_extra_sont_selectionnees():
    """« ALL of that model's [EXTRA ATTACKS] weapons » : deux armes EXTRA -> les deux."""
    fig = _fig([_w("Choppa", []), _w("E1", ["EXTRA_ATTACKS"]), _w("E2", ["EXTRA_ATTACKS"])])
    assert _select_fight_weapon_indices_for_fig(fig, 4, 3, 7) == [0, 1, 2]


def test_que_des_armes_extra_pas_d_arme_principale():
    """« if possible » : sans autre arme de melee, seules les armes EXTRA sont selectionnees."""
    fig = _fig([_w("E1", ["EXTRA_ATTACKS"])])
    assert _select_fight_weapon_indices_for_fig(fig, 4, 3, 7) == [0]


def test_sans_extra_attacks_une_seule_arme():
    """Contre-epreuve : comportement anterieur inchange sans la regle."""
    fig = _fig([_w("A", [], dmg=1), _w("B", [], dmg=3)])
    assert _select_fight_weapon_indices_for_fig(fig, 4, 3, 7) == [1]


def test_declaration_produit_un_intent_par_arme(monkeypatch):
    """Cablage : `squad_declare_fight` emet 2 intents pour la figurine, et ATTACK_LEFT cumule
    les attaques des deux armes (sinon la 2e arme ne se resout jamais)."""
    monkeypatch.setattr(shared_utils, "get_fighting_models", lambda gs, sid, tid=None: ["A1"])
    fig = _fig([_w("Choppa", [], nb=3), _w("Syringe", ["EXTRA_ATTACKS"], nb=1)])
    target = {"id": "T1", "T": 4, "ARMOR_SAVE": 3, "INVUL_SAVE": 7}
    gs = {
        # Socle d'etat de tour : `squad_declare_fight` lit l'etat des capacites de faction pour
        # scorer les armes (+1 S/A du Waaagh!). Une doublure qui l'omet decrit un game_state
        # que le moteur ne produit jamais — cf. `tests/_state_invariants`.
        **turn_state_invariants(),
        "models_cache": {"A1": fig, "T1": target},
        "squad_models": {"1": ["A1"], "2": ["T1"]},
        "pending_squad_fight_intents": {"1": []},
        "pending_squad_shoot_intents": {},
        # Keywords de la cible : exiges par [ANTI-X] 24.03, que l heuristique de choix d arme
        # consulte desormais (elle passe par le socle de resolution).
        "unit_by_id": {"1": {"id": "1", "UNIT_KEYWORDS": [], "UNIT_RULES": []},
                       "2": {"id": "2", "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}], "UNIT_RULES": []}},
        # `bonus_malus_cap` : lu par `_bonus_malus_cap` dans squad_declare_fight (seuil de touche).
        "config": {"game_rules": {"bonus_malus_cap": 0}},
    }

    intents = squad_declare_fight(gs, "1", "2")

    assert [i["weapon_index"] for i in intents] == [0, 1]
    assert sum(i["n_attacks_resolved"] for i in intents) == 4
    assert fig["ATTACK_LEFT"] == 4
    assert fig["selectedCcWeaponIndex"] == 0


def test_declaration_sans_extra_reste_a_un_intent(monkeypatch):
    """Contre-epreuve du cablage : une figurine sans arme EXTRA declare une seule arme."""
    monkeypatch.setattr(shared_utils, "get_fighting_models", lambda gs, sid, tid=None: ["A1"])
    fig = _fig([_w("Choppa", [], nb=3)])
    gs = {
        **turn_state_invariants(),
        "models_cache": {"A1": fig, "T1": {"id": "T1", "T": 4, "ARMOR_SAVE": 3, "INVUL_SAVE": 7}},
        "squad_models": {"1": ["A1"], "2": ["T1"]},
        "pending_squad_fight_intents": {"1": []},
        "pending_squad_shoot_intents": {},
        # Keywords de la cible : exiges par [ANTI-X] 24.03, que l heuristique de choix d arme
        # consulte desormais (elle passe par le socle de resolution).
        "unit_by_id": {"1": {"id": "1", "UNIT_KEYWORDS": [], "UNIT_RULES": []},
                       "2": {"id": "2", "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}], "UNIT_RULES": []}},
        # `bonus_malus_cap` : lu par `_bonus_malus_cap` dans squad_declare_fight (seuil de touche).
        "config": {"game_rules": {"bonus_malus_cap": 0}},
    }

    intents = squad_declare_fight(gs, "1", "2")

    assert len(intents) == 1 and fig["ATTACK_LEFT"] == 3
