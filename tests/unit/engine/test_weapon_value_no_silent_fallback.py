"""Valeurs d arme (D et NB) : aucune donnee invalide n est remplacee par « 1 » en silence.

Le chemin PvP/gym `build_manual_shoot_allocation` -> `_resolve_one_manual_wound` resolvait la
caracteristique D dans un `try/except Exception` qui retombait sur 1 degat : une expression de
des inconnue, une cle `DMG` absente ou un lot d attaques mal forme devenaient « 1 degat »,
donc une partie jouee avec de fausses valeurs sans le moindre signal.

Motif de reference (deja applique a `_auto_select_cc_weapon_index` dans le meme fichier) :
« Aucun repli silencieux : une valeur de DMG non resoluble est une donnee d arme invalide,
elle doit lever ». Ces tests verrouillent ce choix : ils redeviennent ROUGES si le
`try/except` ou le defaut `weapon.get("DMG", 1)` reviennent.

Trois autres sites du fichier portaient exactement le meme repli sur le NOMBRE d attaques
(`_resolve_intent_nb`, resolution de tir, `squad_declare_fight`) : ils sont couverts ici aussi.

Un test prouve l autre moitie du contrat : TOUTES les valeurs de D presentes dans les
rosters (1, 2, 3, 4, D3, D6, D6+1) passent sans lever.

SECONDE PASSE — les CARACTERISTIQUES de jet (`ATK`, `STR`, `AP`, `RNG`, et `T` /
`ARMOR_SAVE` / `INVUL_SAVE` cote cible) portaient le meme defaut sous une autre forme :
`weapon.get("ATK", weapon.get("BS", 4))`, `weapon.get("AP", 0)`, `t_sample.get("T", 4)`...
Ces valeurs de repli (4, 0, 7) sont des valeurs de jeu PLAUSIBLES : une donnee absente ne
produisait ni erreur ni resultat aberrant, juste une partie jouee avec de fausses
caracteristiques. Elles sont desormais requises, et le dernier test prouve sur les rosters
reels que chaque cle est presente partout ou le moteur la lit.
"""
import random

import pytest

from engine.phase_handlers import shared_utils, shooting_handlers
from engine.phase_handlers.shared_utils import (
    _resolve_intent_nb,
    build_manual_shoot_allocation,
    squad_declare_fight,
)
from tests._state_invariants import turn_state_invariants


def _seq(monkeypatch, rolls):
    seq = list(rolls)

    def fake(a, b):
        assert seq, "sequence RNG epuisee"
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})
    monkeypatch.setattr(shooting_handlers, "_ranged_distance_metric", lambda *args, **kwargs: "euclidean")


def _uc(col, row, *, player):
    return {"BASE_SHAPE": "round", "BASE_SIZE": 1, "col": col, "row": row,
            "occupied_hexes": set(), "VALUE": 10.0, "player": player}


def _game_state(weapon):
    """Tireur '1' en (0,0) avec `weapon`. Cible '2' HP 20, aucune sauvegarde."""
    attacker = {"id": "A1", "squad_id": "1", "player": 0, "T": 4, "SHOOT_LEFT": 1,
                "col": 0, "row": 0, "RNG_WEAPONS": [weapon]}
    target = {"id": "T1", "squad_id": "2", "player": 1, "T": 4, "HP_CUR": 20, "HP_MAX": 20,
              "ARMOR_SAVE": 7, "INVUL_SAVE": 7, "role": None, "unitType": "Grunt",
              "points_per_hp": 5.0, "VALUE": 10.0, "col": 0, "row": 1}
    return {**turn_state_invariants(),
        "gym_training_mode": True,
        "turn": 1, "phase": "shoot",
        "action_logs": [], "action_log_seq": 0,
        "models_cache": {"A1": attacker, "T1": target},
        "squad_models": {"1": ["A1"], "2": ["T1"]},
        "squad_cache": {"1": {"model_count_at_start": 1}, "2": {"model_count_at_start": 1}},
        "units_cache": {"1": _uc(0, 0, player=0), "2": _uc(0, 1, player=1)},
        "units": [{"id": "1", "player": 0}, {"id": "2", "player": 1}],
        "unit_by_id": {"1": {"id": "1", "UNIT_RULES": []}, "2": {"id": "2", "UNIT_RULES": []}},
        "objectives": [], "units_moved": set(), "units_advanced": set(),
        "pending_squad_shoot_intents": {
            "1": [{"model_id": "A1", "target_unit_id": "2", "weapon_index": 0,
                   "n_attacks_resolved": 1}]
        },
    }


def _weapon(**overrides):
    w = {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
         "WEAPON_RULES": [], "display_name": "Bolter"}
    w.update(overrides)
    return w


def test_dmg_non_resoluble_leve_au_lieu_de_faire_1_degat(monkeypatch):
    """« D5 » n est pas une expression de des supportee : erreur explicite, pas 1 degat."""
    _seq(monkeypatch, [4, 5, 1])  # touche, blesse, sauvegarde ratee -> resolution des degats
    gs = _game_state(_weapon(DMG="D5"))

    with pytest.raises(ValueError) as exc:
        build_manual_shoot_allocation(gs, "1")

    # L erreur NOMME la valeur rencontree et la figurine attaquante.
    assert "D5" in str(exc.value)
    assert "squad_shoot_dmg_A1" in str(exc.value)
    # Et surtout : aucun degat n a ete applique en douce.
    assert gs["models_cache"]["T1"]["HP_CUR"] == 20


def test_dmg_absent_leve_au_lieu_de_valoir_1(monkeypatch):
    """Une arme sans caracteristique D est une datasheet invalide, pas une arme a 1 degat."""
    weapon = _weapon()
    del weapon["DMG"]
    _seq(monkeypatch, [4, 5, 1])
    gs = _game_state(weapon)

    with pytest.raises(Exception) as exc:
        build_manual_shoot_allocation(gs, "1")

    assert "DMG" in str(exc.value)
    assert gs["models_cache"]["T1"]["HP_CUR"] == 20


def test_nb_absent_leve_au_lieu_de_valoir_1_attaque(monkeypatch):
    """Meme regle pour le nombre d attaques : NB absent = donnee invalide, pas 1 attaque."""
    weapon = _weapon()
    del weapon["NB"]
    _seq(monkeypatch, [4, 5, 1])
    gs = _game_state(weapon)
    # Sans `n_attacks_resolved` dans l intent, le NB de l arme est lu a la resolution.
    gs["pending_squad_shoot_intents"]["1"][0].pop("n_attacks_resolved")

    with pytest.raises(Exception) as exc:
        build_manual_shoot_allocation(gs, "1")

    assert "NB" in str(exc.value)
    assert gs["models_cache"]["T1"]["HP_CUR"] == 20


@pytest.mark.parametrize(
    "dmg,d6,attendu",
    [
        (1, None, 1),
        (2, None, 2),
        (3, None, 3),
        (4, None, 4),
        ("D3", 5, 3),     # D3 = (D6 + 1) // 2 -> (5+1)//2 = 3
        ("D6", 5, 5),
        ("D6+1", 5, 6),
    ],
)
def test_toutes_les_valeurs_de_dmg_des_rosters_passent(monkeypatch, dmg, d6, attendu):
    """Les 7 valeurs de D presentes dans `frontend/src/roster` se resolvent sans lever."""
    rolls = [4, 5, 1] + ([d6] if d6 is not None else [])
    _seq(monkeypatch, rolls)
    gs = _game_state(_weapon(DMG=dmg))

    build_manual_shoot_allocation(gs, "1")

    assert gs["models_cache"]["T1"]["HP_CUR"] == 20 - attendu


def test_resolve_intent_nb_leve_sur_expression_inconnue():
    """Declaration de tir : « D5 » doit lever, pas retomber sur 1 attaque."""
    weapons = [{"NB": "D5", "DMG": 1}]

    with pytest.raises(ValueError) as exc:
        _resolve_intent_nb(weapons, 0, "squad_declare_shoot_NB_A1_0")

    assert "D5" in str(exc.value)
    assert "squad_declare_shoot_NB_A1_0" in str(exc.value)


def test_resolve_intent_nb_resout_les_valeurs_valides(monkeypatch):
    """Contre-epreuve : les expressions supportees restent resolues normalement."""
    monkeypatch.setattr(random, "randint", lambda a, b: 5)
    assert _resolve_intent_nb([{"NB": 3}], 0, "t") == 3
    assert _resolve_intent_nb([{"NB": "D6+1"}], 0, "t") == 6


def _ccw(name, nb, rules):
    return {"display_name": name, "WEAPON_RULES": list(rules), "ATK": 3,
            "STR": 4, "AP": 0, "DMG": 1, "NB": nb}


def _fight_state(weapons):
    """Etat minimal accepte par `squad_declare_fight` (jumeau de test_extra_attacks_fight)."""
    fig = {"id": "A1", "squad_id": "1", "player": 0, "T": 4, "CC_WEAPONS": list(weapons)}
    return {
        "models_cache": {"A1": fig,
                         "T1": {"id": "T1", "T": 4, "ARMOR_SAVE": 3, "INVUL_SAVE": 7}},
        "squad_models": {"1": ["A1"], "2": ["T1"]},
        "pending_squad_fight_intents": {"1": []},
        "pending_squad_shoot_intents": {},
        "unit_by_id": {"1": {"id": "1", "UNIT_KEYWORDS": []},
                       "2": {"id": "2", "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}]}},
    }


def test_declaration_de_combat_leve_sur_nb_non_resoluble(monkeypatch):
    """Melee : un NB non resoluble doit lever a la declaration, pas valoir 1 attaque.

    L arme fautive porte [EXTRA ATTACKS] : elle est selectionnee d office (24.11) SANS passer
    par l heuristique de choix d arme, donc c est bien la resolution de `squad_declare_fight`
    qui la rencontre (le tag d erreur le prouve).
    """
    monkeypatch.setattr(shared_utils, "get_fighting_models", lambda gs, sid, tid=None: ["A1"])
    gs = _fight_state([_ccw("Choppa", 3, []), _ccw("Syringe", "D5", ["EXTRA_ATTACKS"])])

    with pytest.raises(ValueError) as exc:
        squad_declare_fight(gs, "1", "2")

    assert "D5" in str(exc.value)
    assert "squad_declare_fight_NB_A1" in str(exc.value)


def test_declaration_de_combat_resout_les_nb_valides(monkeypatch):
    """Contre-epreuve : deux armes a NB valide -> attaques cumulees, aucune erreur."""
    monkeypatch.setattr(shared_utils, "get_fighting_models", lambda gs, sid, tid=None: ["A1"])
    gs = _fight_state([_ccw("Choppa", 3, []), _ccw("Syringe", 1, ["EXTRA_ATTACKS"])])

    intents = squad_declare_fight(gs, "1", "2")

    assert sum(i["n_attacks_resolved"] for i in intents) == 4


def test_resolve_intent_nb_leve_sur_index_hors_limites():
    """« 0 attaque » n est pas une reponse a un index d arme invalide : tous les appelants
    derivent l index de la liste d armes, un depassement est un defaut de construction."""
    with pytest.raises(IndexError) as exc:
        _resolve_intent_nb([{"NB": 2}], 3, "shoot_declare_model_NB_A1")

    assert "3" in str(exc.value) and "shoot_declare_model_NB_A1" in str(exc.value)


def test_resolve_intent_nb_leve_sur_profil_non_dict():
    with pytest.raises(TypeError) as exc:
        _resolve_intent_nb(["pas un profil"], 0, "shoot_declare_model_NB_A1")

    assert "shoot_declare_model_NB_A1" in str(exc.value)


def test_resolve_intent_nb_leve_sur_nb_absent():
    with pytest.raises(Exception) as exc:
        _resolve_intent_nb([{"DMG": 1}], 0, "shoot_declare_model_NB_A1")

    assert "NB" in str(exc.value)


# --------------------------------------------------------------------------------------
# Caracteristiques de jet : les replis « plausibles » (ATK 4, STR 4, AP 0, T 4, Sv 7)
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("cle", ["ATK", "STR", "AP"])
def test_caracteristique_d_arme_absente_leve_au_tir(monkeypatch, cle):
    """ATK/STR/AP manquants valaient 4/4/0 : des caracteristiques d arme credibles."""
    weapon = _weapon()
    del weapon[cle]
    _seq(monkeypatch, [4, 5, 1])
    gs = _game_state(weapon)

    with pytest.raises(Exception) as exc:
        build_manual_shoot_allocation(gs, "1")

    assert cle in str(exc.value)
    assert gs["models_cache"]["T1"]["HP_CUR"] == 20


def test_invul_save_absente_leve_au_tir(monkeypatch):
    """« Pas de sauvegarde invulnerable » s ecrit 7 DANS LA DONNEE (179/179 datasheets) :
    l absence de la cle est un defaut, pas le cas metier « aucune invulnerable »."""
    _seq(monkeypatch, [4, 5, 1])
    gs = _game_state(_weapon())
    del gs["models_cache"]["T1"]["INVUL_SAVE"]

    with pytest.raises(Exception) as exc:
        build_manual_shoot_allocation(gs, "1")

    assert "INVUL_SAVE" in str(exc.value)


@pytest.mark.parametrize("cle", ["T", "ARMOR_SAVE", "INVUL_SAVE"])
def test_caracteristique_defensive_absente_leve_en_melee(monkeypatch, cle):
    """`squad_declare_fight` lisait T/Sv/InSv de la cible avec 4/7/7 par defaut."""
    monkeypatch.setattr(shared_utils, "get_fighting_models", lambda gs, sid, tid=None: ["A1"])
    gs = _fight_state([_ccw("Choppa", 3, [])])
    del gs["models_cache"]["T1"][cle]

    with pytest.raises(Exception) as exc:
        squad_declare_fight(gs, "1", "2")

    assert cle in str(exc.value)


@pytest.mark.parametrize("cle", ["ATK", "STR", "AP"])
def test_caracteristique_d_arme_absente_leve_a_la_selection_melee(monkeypatch, cle):
    """Meme regle dans l heuristique de choix d arme CC (ex-`w.get("ATK", w.get("WS", 4))`)."""
    monkeypatch.setattr(shared_utils, "get_fighting_models", lambda gs, sid, tid=None: ["A1"])
    weapon = _ccw("Choppa", 3, [])
    del weapon[cle]
    gs = _fight_state([weapon])

    with pytest.raises(Exception) as exc:
        squad_declare_fight(gs, "1", "2")

    assert cle in str(exc.value)


def test_portee_d_arme_de_tir_absente_leve():
    """`_build_weapon_availability_enemy_precheck` ignorait en silence une arme sans RNG :
    l unite pouvait perdre sa portee maximale reelle et ne plus voir ses cibles."""
    from engine.phase_handlers.shooting_handlers import _build_weapon_availability_enemy_precheck

    gs = _game_state(_weapon())
    unit = {"id": "1", "player": 0, "col": 0, "row": 0}
    weapon_sans_rng = _weapon()
    del weapon_sans_rng["RNG"]

    with pytest.raises(Exception) as exc:
        _build_weapon_availability_enemy_precheck(gs, unit, [weapon_sans_rng])

    assert "RNG" in str(exc.value)


def test_toutes_les_cles_lues_sont_presentes_dans_les_rosters():
    """Preuve que ces cles peuvent etre exigees : elles sont portees par TOUTE la donnee.

    Les profils d armes sont resolus (`getWeapons`) pour les 179 datasheets, y compris les 18
    unites `endlessDuty` — ils sont donc tous verifies. Les caracteristiques de FIGURINE de ces
    18 unites sont des references statiques non resolues (cf. test_socle_invariant) : la cle
    existe, seule sa valeur est une chaine, et le moteur de combat ne les lit jamais.
    """
    from ai.unit_registry import UnitRegistry

    registry = UnitRegistry()
    n_rng = n_cc = n_units = 0
    for name, data in registry.units.items():
        n_units += 1
        for cle in ("T", "ARMOR_SAVE", "INVUL_SAVE"):
            assert cle in data, f"{name} n a pas de {cle}"
        for w in data["RNG_WEAPONS"]:
            n_rng += 1
            for cle in ("RNG", "NB", "ATK", "STR", "AP", "DMG"):
                assert cle in w, f"{name}/{w.get('display_name')} (tir) n a pas de {cle}"
        for w in data["CC_WEAPONS"]:
            n_cc += 1
            for cle in ("NB", "ATK", "STR", "AP", "DMG"):
                assert cle in w, f"{name}/{w.get('display_name')} (melee) n a pas de {cle}"
            # `RNG` n est PAS exige en melee : une arme de corps a corps n a pas de portee.
            # C est la raison metier pour laquelle seul `RNG_WEAPONS` peut l exiger.
            assert "RNG" not in w

    assert (n_units, n_rng, n_cc) == (179, 243, 185)
