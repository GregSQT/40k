"""Capacités de FACTION (chantier 03) — Waaagh! (ORKS) et Oath of Moment (ADEPTUS ASTARTES).

SOURCES : `Documentation/40k_rules/Armageddon/Waaagh!.txt` et `.../OathOfMoment.txt`.

Ce que ce fichier verrouille, dans l'ordre de la chaîne :

1. **la décision** — 08.04 pose un `pending_agent_decision` (Waaagh!) ou une désignation
   `pending_oath_selection` (Oath), le masque devient EXCLUSIF, et le Waaagh! ne se propose
   qu'UNE fois par partie ;
2. **l'invariant D1** — `OATH_SLOT_i` désigne la MÊME escouade que la ligne *i* du tenseur
   ennemi. Les désolidariser ferait désigner à l'agent une cible autre que celle qu'il vise,
   sans que rien ne lève ;
3. **la durée** — « until the start of your next Command phase » enjambe le tour adverse. Un
   test qui n'observerait que le tour du déclarant ne verrouillerait rien ;
4. **les effets, sur le CHEMIN VIF** — invulnérable 5+, +1 S / +1 A en mêlée, relance de touche
   et +1 Wound d'Oath, aux deux sites de résolution (tir ET mêlée : c'est le motif d'échec
   n°1 du dépôt) ;
5. **la clause de détachement** — balayage réel des 4 mots-clés, et champ de config obligatoire.

Tous les tests CONSTRUISENT leur état : aucun n'espère un tirage, un ordre d'activation ou
l'absence d'une configuration.
"""

import inspect
import random

import pytest

from engine.action_decoder import ActionDecoder
from engine.agent_decision import read_pending_agent_decision
from engine.game_state import (
    OATH_EXCLUDING_KEYWORDS,
    call_waaagh,
    effective_invul_save,
    expire_faction_abilities_for_player,
    initial_faction_ability_state,
    oath_wound_roll_bonus,
    set_oath_target,
    unit_has_oath_ability,
    unit_is_oath_target_of,
    unit_can_charge_after_advance,
    waaagh_applies_to_unit,
    waaagh_is_active,
)
from engine.macro_intents import CHOICE_BASE, CHOICE_COUNT, OATH_SLOT_BASE
from engine.phase_handlers import command_handlers
from engine.phase_handlers.shared_utils import (
    build_manual_shoot_allocation,
    get_enemy_slot_mapping,
)
from engine.phase_handlers import shooting_handlers
from engine.w40k_core import W40KEngine
from tests._state_invariants import turn_state_invariants, unit_invariants
from tests.unit.engine._roll_helpers import roll_fight_intent


ORKS = [{"keywordId": "ORKS"}]
ASTARTES = [{"keywordId": "ADEPTUS ASTARTES"}]
#: Une faction qui ne porte AUCUNE des deux capacités : c'est elle qui rend visible la
#: différence entre « la Faction d'Armée est déclarée » et « le mot-clé est présent quelque part ».
TYRANIDS = [{"keywordId": "TYRANIDS"}]


def _seq(monkeypatch, rolls):
    """Dés SCRIPTÉS : épuisement = erreur explicite, dé en trop = liste non vide en fin de test.

    C'est ce couple qui fait d'une relance un fait OBSERVÉ et non déduit : une relance de touche
    consomme un dé de plus, et la longueur de la séquence le dit.
    """
    seq = list(rolls)

    def fake(a, b):
        assert seq, "sequence RNG epuisee : le moteur a tire plus de des que prevu"
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})
    return seq


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures — un état de partie MINIMAL mais complet, construit de bout en bout
# ─────────────────────────────────────────────────────────────────────────────


def _unit(uid, player, faction_keywords, **overrides):
    unit = {
        **unit_invariants(),
        "id": uid,
        "player": player,
        "col": 0,
        "row": 0,
        "HP_CUR": 3,
        "HP_MAX": 3,
        "VALUE": 100,
        "OC": 1,
        "LD": 7,
        "T": 4,
        "ARMOR_SAVE": 6,
        "INVUL_SAVE": 7,
        "MOVE": 6,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [],
        "CC_WEAPONS": [],
        "UNIT_RULES": [],
        "UNIT_KEYWORDS": [],
        "BASE_SHAPE": "round",
        "BASE_SIZE": 1,
        "MODEL_HEIGHT": 2.5,
    }
    unit["FACTION_KEYWORDS"] = list(faction_keywords)
    unit.update(overrides)
    return unit


def _shoot_state(
    *,
    attacker_faction,
    defender_faction,
    defender_armor=6,
    defender_invul=7,
    extra_enemy=False,
    # DICT par joueur, la seule forme acceptee — comme les 24 fichiers de config qui la
    # declarent. `None` sert au verrou « champ absent -> leve ».
    uses_codex_detachment: "dict | None" = None,
    attacker_extra_units=(),
    defender_extra_units=(),
    # Faction d'Armée DÉCLARÉE, quand elle DIVERGE des mots-clés de l'unité testée : c'est le
    # cas « une unité sans la capacité dans une armée qui l'a », que la déduction d'avant ne
    # savait pas exprimer. Par défaut, elle suit la datasheet des unités construites.
    declared_factions: "dict | None" = None,
):
    """Un tireur (escouade '1', joueur 1) contre une cible (escouade '2', joueur 2).

    `extra_enemy` ajoute une SECONDE escouade ennemie ('3') : c'est elle qui permet la
    contre-épreuve du ciblage d'Oath — sans une deuxième cible, « la relance s'applique à la
    bonne unité » et « la relance s'applique à toutes » sont indiscernables.
    """
    weapon = {
        "ATK": 4, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
        "WEAPON_RULES": [], "display_name": "Bolt Rifle",
    }
    attacker_model = {
        "id": "A1", "squad_id": "1", "player": 1, "T": 4, "SHOOT_LEFT": 1,
        "col": 0, "row": 0, "RNG_WEAPONS": [weapon],
    }
    models = {"A1": attacker_model}
    squad_models = {"1": ["A1"]}
    squad_cache = {"1": {"model_count_at_start": 1}}
    units_cache = {"1": _uc(0, 0, player=1)}
    units = [_unit("1", 1, attacker_faction)]

    for sid, col, row in (("2", 9, 9), ("3", 12, 12)) if extra_enemy else (("2", 9, 9),):
        mid = f"T{sid}"
        models[mid] = {
            "id": mid, "squad_id": sid, "player": 2, "T": 4,
            "HP_CUR": 3, "HP_MAX": 3, "ARMOR_SAVE": defender_armor,
            "INVUL_SAVE": defender_invul, "role": None, "unitType": "Grunt",
            "points_per_hp": 5.0, "VALUE": 10.0, "col": col, "row": row,
        }
        squad_models[sid] = [mid]
        squad_cache[sid] = {"model_count_at_start": 1}
        units_cache[sid] = _uc(col, row, player=2)
        units.append(_unit(sid, 2, defender_faction, ARMOR_SAVE=defender_armor,
                           INVUL_SAVE=defender_invul))

    for index, extra_faction in enumerate(attacker_extra_units):
        extra_id = f"9{index}"
        units.append(_unit(extra_id, 1, extra_faction))

    for index, extra_faction in enumerate(defender_extra_units):
        units.append(_unit(f"8{index}", 2, extra_faction))

    # `army_faction` est TOUJOURS déclarée, y compris quand la fixture retire la clause de
    # détachement : sans elle, aucune attaque n'atteint le +1 Wound (l'attaquant n'aurait pas
    # la capacité), et le verrou « clause de détachement absente → lève » testerait autre chose
    # que ce qu'il annonce.
    config = {
        "army_faction": declared_factions or {
            "1": _declared_faction(attacker_faction),
            "2": _declared_faction(defender_faction),
        }
    }
    if uses_codex_detachment != {}:
        config["uses_codex_detachment"] = uses_codex_detachment or {"1": True, "2": True}
    gs = {
        **turn_state_invariants(),
        "gym_training_mode": True,
        "turn": 1,
        "phase": "shoot",
        "current_player": 1,
        "config": config,
        "action_logs": [],
        "action_log_seq": 0,
        "models_cache": models,
        "squad_models": squad_models,
        "squad_cache": squad_cache,
        "units_cache": units_cache,
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "objectives": [],
        "pending_squad_shoot_intents": {
            "1": [{"model_id": "A1", "target_unit_id": "2", "weapon_index": 0,
                   "n_attacks_resolved": 1}]
        },
    }
    return gs


def _uc(col, row, *, player):
    return {"BASE_SHAPE": "round", "BASE_SIZE": 1, "col": col, "row": row,
            "occupied_hexes": set(), "VALUE": 10.0, "player": player}


def _records(gs):
    out = []
    for log in gs["action_logs"]:
        out.extend(log.get("shootDetails", []) if isinstance(log, dict) else [])
    return out


def _fight_state(*, attacker_faction, defender_faction, weapon_str=4, weapon_nb=1):
    """Un attaquant (escouade '1', joueur 1) au contact d'une cible (escouade '2', joueur 2)."""
    weapon = {"ATK": 3, "STR": weapon_str, "AP": 0, "DMG": 1, "NB": weapon_nb,
              "WEAPON_RULES": [], "display_name": "Choppa"}
    attacker = {"id": "A1", "squad_id": "1", "player": 1, "T": 4, "CC_WEAPONS": [weapon]}
    target_model = {"id": "T1", "squad_id": "2", "player": 2, "T": 4, "HP_CUR": 5, "HP_MAX": 5,
                    "ARMOR_SAVE": 6, "INVUL_SAVE": 7, "role": None, "unitType": "Grunt"}
    units = [_unit("1", 1, attacker_faction), _unit("2", 2, defender_faction, ARMOR_SAVE=6)]
    gs = {
        **turn_state_invariants(),
        "config": {
            "uses_codex_detachment": {"1": True, "2": True},
            "army_faction": {
                "1": _declared_faction(attacker_faction),
                "2": _declared_faction(defender_faction),
            },
        },
        "models_cache": {"A1": attacker, "T1": target_model},
        "squad_models": {"1": ["A1"], "2": ["T1"]},
        "squad_cache": {"1": {"model_count_at_start": 1}, "2": {"model_count_at_start": 1}},
        "units_cache": {"1": _uc(0, 0, player=1), "2": _uc(1, 0, player=2)},
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "objectives": [],
    }
    intent = {"model_id": "A1", "target_unit_id": "2", "weapon_index": 0,
              "n_attacks_resolved": weapon_nb}
    return gs, intent


def _declared_faction(faction_keywords):
    """Le mot-clé qu'une liste DÉCLARE comme Faction d'Armée : le premier de sa datasheet.

    Les fixtures décrivent une armée par les `FACTION_KEYWORDS` de son unité ; la config, elle,
    porte une déclaration SCALAIRE. La conversion vit ici et pas dans le moteur — c'est
    exactement la déduction que `army_faction` refuse de faire.
    """
    first = faction_keywords[0]
    return str(first["keywordId"] if isinstance(first, dict) else first)


def _command_state(current_player, *, p1_faction, p2_faction, alive=("1", "2")):
    """Un état minimal pour jouer 08.04 : deux joueurs, une escouade chacun."""
    units = [_unit("1", 1, p1_faction), _unit("2", 2, p2_faction)]
    gs = {
        **turn_state_invariants(),
        "turn": 1,
        "phase": "command",
        "current_player": current_player,
        # `army_faction` est DÉCLARÉE, jamais déduite des unités présentes : c'est tout l'objet
        # du champ (une armée peut inviter une unité d'une autre faction sans changer de Faction
        # d'Armée). La fixture la déclare donc d'après les mêmes paramètres que les unités —
        # les cas où les deux DIVERGENT ont leurs tests dédiés.
        "config": {
            "uses_codex_detachment": {"1": True, "2": True},
            "army_faction": {
                "1": _declared_faction(p1_faction),
                "2": _declared_faction(p2_faction),
            },
            "gym_training_mode": True,
        },
        "gym_training_mode": True,
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "units_cache": {
            uid: _uc(int(uid), 0, player=int(uid))
            for uid in alive
        },
        "squad_models": {uid: [f"M{uid}"] for uid in alive},
        "models_cache": {
            f"M{uid}": {"id": f"M{uid}", "squad_id": uid, "player": int(uid),
                        "HP_CUR": 3, "HP_MAX": 3, "col": int(uid), "row": 0}
            for uid in alive
        },
        "action_logs": [],
        "action_log_seq": 0,
        "console_logs": [],
        "objectives": [],
        # Posé par `command_phase_resume` en production ; la fixture appelle 08.04 en isolation,
        # et le masque de la phase de commandement le lit sans défaut.
        "zone_intent_free_steps_remaining": 0,
        # Lu par `command_phase_end` (trace de transition) — posé par `command_build_activation_pool`
        # en production, que la fixture court-circuite en appelant 08.04 seul.
        "command_activation_pool": [],
        "episode_number": 1,
    }
    return gs


# ─────────────────────────────────────────────────────────────────────────────
# 1. La décision — 08.04, exclusivité du masque, once per battle
# ─────────────────────────────────────────────────────────────────────────────


def test_le_waaagh_est_propose_au_joueur_orke_et_a_deux_candidats():
    """« once per battle, at the start of your Command phase, you can call a Waaagh! »."""
    gs = _command_state(1, p1_faction=ORKS, p2_faction=ASTARTES)

    command_handlers.command_step_command_abilities(gs)

    decision = read_pending_agent_decision(gs)
    assert decision is not None
    assert decision["type"] == "waaagh_call"
    assert decision["player"] == 1
    assert len(decision["options"]) == 2
    # L'ORDRE est contractuel : c'est lui, et non un `effect_ids`, qui porte le sens.
    assert decision["options"][0]["payload"]["call"] is True
    assert decision["options"][1]["payload"]["call"] is False


def test_le_waaagh_n_est_pas_propose_a_une_armee_non_orke():
    """« If your Army Faction is ORKS » — le prédicat est réel, pas décoratif."""
    gs = _command_state(1, p1_faction=ASTARTES, p2_faction=ORKS)

    command_handlers.command_step_command_abilities(gs)

    decision = read_pending_agent_decision(gs)
    assert decision is None or decision["type"] != "waaagh_call"


def test_verrou_une_fois_par_partie_l_action_sort_du_masque():
    """VERROU 1×/PARTIE : après l'appel, plus aucune action CHOICE n'est ouverte.

    Le contrôle porte sur le MASQUE et non sur l'état : c'est le masque qui décide de ce que
    l'agent peut jouer, et un état correct derrière un masque permissif laisserait l'agent
    rappeler son Waaagh! — le `raise` de `call_waaagh` ne le rattraperait qu'en plein épisode.
    """
    gs = _command_state(1, p1_faction=ORKS, p2_faction=ASTARTES)
    decoder = ActionDecoder({"board": {"default": {"hex_radius": 1.0, "margin": 0.0}}})

    command_handlers.command_step_command_abilities(gs)
    mask, _ = decoder.get_squad_action_mask_and_eligible_units(gs)
    assert [i for i in range(CHOICE_BASE, CHOICE_BASE + CHOICE_COUNT) if mask[i]] == [
        CHOICE_BASE, CHOICE_BASE + 1
    ], "premier tour : les deux candidats sont ouverts"

    command_handlers.apply_waaagh_call_decision(gs, 1, called=True)
    assert waaagh_is_active(gs, 1)

    # Tour suivant du MÊME joueur : 08.04 rejoué, plus aucune décision de Waaagh!.
    gs["turn"] = 2
    command_handlers.command_step_command_abilities(gs)
    decision = read_pending_agent_decision(gs)
    assert decision is None, "le Waaagh! ne se represente pas : once per battle"
    mask, _ = decoder.get_squad_action_mask_and_eligible_units(gs)
    assert not any(mask[i] for i in range(CHOICE_BASE, CHOICE_BASE + CHOICE_COUNT))


def test_passer_ne_consomme_pas_le_once_per_battle():
    """« You can call » : refuser n'est pas dépenser. La décision revient au tour suivant."""
    gs = _command_state(1, p1_faction=ORKS, p2_faction=ASTARTES)

    command_handlers.command_step_command_abilities(gs)
    command_handlers.apply_waaagh_call_decision(gs, 1, called=False)
    assert not waaagh_is_active(gs, 1)

    gs["turn"] = 2
    command_handlers.command_step_command_abilities(gs)
    decision = read_pending_agent_decision(gs)
    assert decision is not None and decision["type"] == "waaagh_call"


def test_l_oath_est_obligatoire_et_n_offre_aucun_candidat_vide():
    """« select one unit from your opponent's army » : le masque n'ouvre QUE des cibles."""
    gs = _command_state(1, p1_faction=ASTARTES, p2_faction=ORKS)
    decoder = ActionDecoder({"board": {"default": {"hex_radius": 1.0, "margin": 0.0}}})

    command_handlers.command_step_command_abilities(gs)
    assert gs["pending_oath_selection"] == 1

    mask, eligible = decoder.get_squad_action_mask_and_eligible_units(gs)
    ouverts = [i for i, v in enumerate(mask) if v]
    assert eligible == []
    assert ouverts, "une designation en attente doit ouvrir au moins un slot"
    assert all(i >= OATH_SLOT_BASE for i in ouverts), (
        "la designation est EXCLUSIVE : aucun WAIT, aucun zone intent, aucun candidat « aucune "
        f"cible » — ouverts : {ouverts}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Invariant D1 — action `OATH_SLOT_i` ↔ ligne *i* du tenseur ennemi
# ─────────────────────────────────────────────────────────────────────────────


def test_verrou_invariant_d1_le_slot_oath_designe_la_ligne_du_tenseur_ennemi():
    """VERROU D1 : `OATH_SLOT_i` désigne la MÊME escouade que la ligne *i* observée.

    Les deux lectures viennent de `get_enemy_slot_mapping`, mais rien dans le code ne l'impose
    aux DEUX bouts : le décodeur pourrait recalculer un ordre à lui. Une divergence ne lèverait
    nulle part — l'agent scorerait une cible et en désignerait une autre.
    """
    gs = _command_state(1, p1_faction=ASTARTES, p2_faction=ORKS, alive=("1", "2"))
    # Trois ennemis : avec un seul, toute permutation serait l'identite (vert vacant).
    for uid, col in (("3", 5), ("4", 7)):
        gs["units"].append(_unit(uid, 2, ORKS))
        gs["unit_by_id"][uid] = gs["units"][-1]
        gs["units_cache"][uid] = _uc(col, 0, player=2)
        gs["squad_models"][uid] = [f"M{uid}"]
        gs["models_cache"][f"M{uid}"] = {
            "id": f"M{uid}", "squad_id": uid, "player": 2,
            "HP_CUR": 3, "HP_MAX": 3, "col": col, "row": 0,
        }

    command_handlers.command_step_command_abilities(gs)
    decoder = ActionDecoder({"board": {"default": {"hex_radius": 1.0, "margin": 0.0}}})
    slots = decoder.oath_selection_slots(gs)
    mapping = get_enemy_slot_mapping(gs, 1)

    assert slots, "aucun slot ouvert : le test ne regarderait rien"
    for action_int, squad_id in slots.items():
        row = action_int - OATH_SLOT_BASE
        assert mapping[row] == squad_id, (
            f"OATH_SLOT_{row} designe {squad_id} mais la ligne {row} du tenseur ennemi porte "
            f"{mapping[row]} — invariant D1 rompu"
        )
    # Et le decodage joue EXACTEMENT ce que le masque a ouvert.
    for action_int, squad_id in slots.items():
        assert decoder.convert_squad_action(action_int, gs) == {
            "action": "select_oath_target", "player": 1, "unitId": squad_id,
        }


def test_un_slot_oath_ferme_est_refuse_par_le_decodeur():
    """Contre-épreuve du masque : un slot sans escouade vivante n'est pas jouable."""
    gs = _command_state(1, p1_faction=ASTARTES, p2_faction=ORKS)
    command_handlers.command_step_command_abilities(gs)
    decoder = ActionDecoder({"board": {"default": {"hex_radius": 1.0, "margin": 0.0}}})
    slots = decoder.oath_selection_slots(gs)
    assert slots is not None, "une designation est en attente : le decodeur doit rendre des slots"
    ferme = next(i for i in range(OATH_SLOT_BASE, OATH_SLOT_BASE + 20) if i not in slots)

    with pytest.raises(ValueError, match="FERME"):
        decoder.convert_squad_action(ferme, gs)


def test_designer_une_unite_a_soi_ou_morte_est_refuse():
    """« one unit from your OPPONENT's army » : la garde est dans l'écrivain unique."""
    gs = _command_state(1, p1_faction=ASTARTES, p2_faction=ORKS)

    with pytest.raises(ValueError, match="OPPONENT"):
        set_oath_target(gs, 1, "1")
    with pytest.raises(KeyError, match="introuvable"):
        set_oath_target(gs, 1, "999")


# ─────────────────────────────────────────────────────────────────────────────
# 3. La durée — « until the start of your next Command phase »
# ─────────────────────────────────────────────────────────────────────────────


def test_verrou_de_duree_le_waaagh_survit_au_tour_adverse_et_expire_au_tour_suivant():
    """VERROU DE DURÉE : la borne est l'ouverture de MA phase de commandement, pas la fin du tour.

    Trois observations, et la deuxième est celle qui compte : un test qui n'observerait que le
    tour du déclarant resterait vert avec une extinction en fin de tour — or c'est précisément
    pendant le tour ADVERSE que l'invulnérable 5+ et le +1 S/A protègent l'armée orke.
    """
    gs = _command_state(1, p1_faction=ORKS, p2_faction=ASTARTES)

    # Tour N — phase de commandement du joueur ORKE : il appelle.
    command_handlers.command_step_command_abilities(gs)
    command_handlers.apply_waaagh_call_decision(gs, 1, called=True)
    assert waaagh_is_active(gs, 1) is True

    # Tour N — phase de commandement de l'ADVERSAIRE : 08.04 s'exécute pour LUI.
    gs["current_player"] = 2
    gs["turn"] = 1
    command_handlers.command_step_command_abilities(gs)
    assert waaagh_is_active(gs, 1) is True, (
        "le Waaagh! doit enjamber le tour adverse : 08.04 du joueur 2 n'eteint QUE ce que le "
        "joueur 2 a pose"
    )

    # Tour N+1 — phase de commandement du joueur ORKE : la borne est atteinte.
    gs["current_player"] = 1
    gs["turn"] = 2
    command_handlers.command_step_command_abilities(gs)
    assert waaagh_is_active(gs, 1) is False


def test_la_cible_d_oath_expire_a_l_ouverture_de_ma_phase_suivante():
    """Jumeau du verrou de durée, côté Oath : même borne, même symétrie entre joueurs."""
    gs = _command_state(1, p1_faction=ASTARTES, p2_faction=ORKS)

    command_handlers.command_step_command_abilities(gs)
    command_handlers.apply_oath_selection(gs, 1, "2")
    assert gs["oath_target"][1] == "2"

    gs["current_player"] = 2
    command_handlers.command_step_command_abilities(gs)
    assert gs["oath_target"][1] == "2", "l'Oath survit au tour adverse"

    gs["current_player"] = 1
    gs["turn"] = 2
    command_handlers.command_step_command_abilities(gs)
    # Expirée, puis immédiatement REDEMANDÉE : « at the start of your Command phase », chaque tour.
    assert gs["pending_oath_selection"] == 1
    assert gs["oath_target"][1] is None


def test_l_extinction_ne_touche_que_le_joueur_concerne():
    """08.04 du joueur X n'éteint QUE ce que X a posé — sinon un joueur annulerait l'autre."""
    gs = _command_state(1, p1_faction=ORKS, p2_faction=ORKS)
    gs.update(initial_faction_ability_state())
    call_waaagh(gs, 1)
    call_waaagh(gs, 2)

    expire_faction_abilities_for_player(gs, 1)

    assert waaagh_is_active(gs, 1) is False
    assert waaagh_is_active(gs, 2) is True


def test_appeler_deux_fois_leve():
    """L'écrivain unique refuse le second appel : un masque et un état divergents = incohérence."""
    gs = _command_state(1, p1_faction=ORKS, p2_faction=ASTARTES)
    call_waaagh(gs, 1)
    with pytest.raises(RuntimeError, match="once per battle"):
        call_waaagh(gs, 1)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Effets du Waaagh! — sur le chemin VIF
# ─────────────────────────────────────────────────────────────────────────────


def test_verrou_waaagh_invulnerable_la_sauvegarde_passe_a_5(monkeypatch):
    """VERROU INVULNÉRABLE : Boyz (`INVUL_SAVE=7`), Waaagh! actif → sauvegarde à 5+.

    Bout-en-bout sur le chemin vif (`build_manual_shoot_allocation` → `_manual_roll_intent` →
    `roll_attack_pool` → `_resolve_one_manual_wound`). Le seuil observé est `rec["saveTarget"]`,
    posé par `_resolve_one_manual_wound` : c'est LUI que la résolution compare, pas le seuil
    d'affichage calculé au jet.

    Les dés : touche 4 (≥ BS 4), blessure 4 (S4 vs T4), sauvegarde 5.
      - sans Waaagh! : seuil 6 (armure 6+, AP 0, aucune invulnérable) → un 5 ÉCHOUE, 1 PV perdu ;
      - avec Waaagh! : seuil 5 → le MÊME 5 RÉUSSIT, aucun dégât.
    Retirer l'override fait retomber le seuil à 6 : les deux assertions du bloc « avec » cassent.
    """
    # Sans Waaagh! — la contre-épreuve, construite et non supposée.
    seq = _seq(monkeypatch, [4, 4, 5])
    gs = _shoot_state(attacker_faction=ASTARTES, defender_faction=ORKS, defender_armor=6)
    build_manual_shoot_allocation(gs, "1")
    rec = _records(gs)[0]
    assert rec["saveTarget"] == 6
    assert rec["saveSuccess"] is False
    assert gs["models_cache"]["T2"]["HP_CUR"] == 2
    assert seq == []

    # Avec Waaagh! — même armée, mêmes dés, seule la capacité change.
    seq = _seq(monkeypatch, [4, 4, 5])
    gs = _shoot_state(attacker_faction=ASTARTES, defender_faction=ORKS, defender_armor=6)
    call_waaagh(gs, 2)
    build_manual_shoot_allocation(gs, "1")
    rec = _records(gs)[0]
    assert rec["saveTarget"] == 5, "« models with this ability have a 5+ invulnerable save »"
    assert rec["saveSuccess"] is True
    assert gs["models_cache"]["T2"]["HP_CUR"] == 3, "la sauvegarde 5+ annule les degats"
    assert seq == []


def test_le_waaagh_ne_degrade_jamais_une_invulnerable_deja_meilleure():
    """« have a 5+ invulnerable save » est un OCTROI, pas un plafond : une 4+ est conservée."""
    gs = _shoot_state(attacker_faction=ASTARTES, defender_faction=ORKS, defender_invul=4)
    call_waaagh(gs, 2)
    cible = gs["unit_by_id"]["2"]

    assert effective_invul_save(gs, cible, 4) == 4
    assert effective_invul_save(gs, cible, 7) == 5


def test_le_waaagh_ne_touche_pas_les_unites_sans_la_capacite():
    """« units from your army WITH THIS ABILITY » : une unité non-ORKS de l'armée orke n'a rien."""
    # L'armee du joueur 2 est ORKS : elle DECLARE la faction et contient une unite qui la porte.
    # L'unite testee, elle, n'a aucun mot-cle de faction — c'est l'invitee qui ne gagne rien.
    gs = _shoot_state(
        attacker_faction=ASTARTES,
        defender_faction=[],
        defender_extra_units=(ORKS,),
        declared_factions={"1": "ADEPTUS ASTARTES", "2": "ORKS"},
    )
    call_waaagh(gs, 2)
    sans_capacite = gs["unit_by_id"]["2"]

    assert waaagh_applies_to_unit(gs, sans_capacite) is False
    assert effective_invul_save(gs, sans_capacite, 7) == 7


def test_verrou_waaagh_melee_plus_un_en_force_et_en_attaques(monkeypatch):
    """« Add 1 to the Strength and Attacks characteristics of melee weapons ».

    S4 vs T4 blesse à 4+ ; S5 vs T4 blesse à 3+. Le seuil observé (`woundTarget`) le dit, et le
    NOMBRE de dés consommés dit le +1 Attaque : 1 attaque déclarée en produit 2.
    """
    _seq(monkeypatch, [3, 3, 6])  # 1 attaque : touche, blessure, sauvegarde
    gs, intent = _fight_state(attacker_faction=ORKS, defender_faction=ASTARTES)
    result = roll_fight_intent(gs, intent)
    assert result["counts"]["attacks"] == 1
    assert result["shot_records"][0]["woundTarget"] == 4

    seq = _seq(monkeypatch, [3, 3, 6, 3, 3, 6])  # 2 attaques : le +1 A en ajoute une
    gs, intent = _fight_state(attacker_faction=ORKS, defender_faction=ASTARTES)
    call_waaagh(gs, 1)
    result = roll_fight_intent(gs, intent)
    assert result["counts"]["attacks"] == 2, "+1 a la caracteristique d'Attaques"
    assert result["shot_records"][0]["woundTarget"] == 3, "+1 a la caracteristique de Force"
    assert seq == []


def test_le_waaagh_ouvre_la_charge_apres_advance():
    """« eligible to declare a charge in a turn in which they Advanced »."""
    gs = _shoot_state(attacker_faction=ORKS, defender_faction=ASTARTES)
    orke = gs["unit_by_id"]["1"]

    assert unit_can_charge_after_advance(gs, orke) is False
    call_waaagh(gs, 1)
    assert unit_can_charge_after_advance(gs, orke) is True


# ─────────────────────────────────────────────────────────────────────────────
# 5. Effets d'Oath — relance de touche et +1 Wound, tir ET mêlée
# ─────────────────────────────────────────────────────────────────────────────


def test_verrou_oath_ciblage_la_relance_ne_vaut_que_contre_la_cible_designee(monkeypatch):
    """VERROU CIBLAGE : les DEUX cas, construits l'un après l'autre.

    Une relance consomme un dé de plus. La séquence scriptée le mesure : contre la cible
    désignée, un 2 raté est relancé (2 dés de touche) ; contre l'autre escouade, le même 2
    termine l'attaque (1 seul dé).
    """
    # Cas 1 — l'attaque vise la cible d'Oath : la touche ratée est relancée.
    seq = _seq(monkeypatch, [2, 5, 4, 6])
    gs = _shoot_state(attacker_faction=ASTARTES, defender_faction=ORKS, extra_enemy=True)
    set_oath_target(gs, 1, "2")
    build_manual_shoot_allocation(gs, "1")
    rec = _records(gs)[0]
    assert rec["hitResult"] == "HIT"
    # La CAUSE est consommee par l'appelant et remplacee par le nom d'AFFICHAGE — jumeau exact
    # de `woundRerollCause` -> `woundAbility`. C'est ce nom qui atteint step.log.
    assert "hitRerollCause" not in rec
    assert rec["hitAbility"] == "Oath of Moment", (
        "sans cette trace, le log dit que la relance etait POSSIBLE, jamais qu'elle a EU LIEU"
    )
    assert seq == []

    # Cas 2 — MÊME état, MÊME dé, mais l'attaque vise l'AUTRE escouade : aucune relance.
    seq = _seq(monkeypatch, [2])
    gs = _shoot_state(attacker_faction=ASTARTES, defender_faction=ORKS, extra_enemy=True)
    set_oath_target(gs, 1, "3")
    gs["pending_squad_shoot_intents"]["1"][0]["target_unit_id"] = "2"
    build_manual_shoot_allocation(gs, "1")
    rec = _records(gs)[0]
    assert rec["hitResult"] == "MISS"
    assert "hitRerollCause" not in rec
    assert seq == [], "aucun de de relance contre une unite qui n'est pas la cible d'Oath"


def test_oath_relance_la_touche_en_melee_aussi(monkeypatch):
    """JUMEAU TIR/MÊLÉE : `hit_any_fail` est câblé aux DEUX rollers, pas au seul tir."""
    seq = _seq(monkeypatch, [1, 5, 5, 6])  # touche ratee -> relancee -> blessure -> sauvegarde
    gs, intent = _fight_state(attacker_faction=ASTARTES, defender_faction=ORKS)
    set_oath_target(gs, 1, "2")

    result = roll_fight_intent(gs, intent)

    assert result["counts"]["hits"] == 1
    assert result["shot_records"][0]["hitAbility"] == "Oath of Moment"
    assert seq == []


def test_oath_ajoute_un_au_jet_de_blessure(monkeypatch):
    """« add 1 to the Wound roll » — modélisé en abaissant le seuil (S4 vs T4 : 4+ → 3+)."""
    _seq(monkeypatch, [4, 4, 6])
    gs = _shoot_state(attacker_faction=ASTARTES, defender_faction=ORKS)
    build_manual_shoot_allocation(gs, "1")
    assert _records(gs)[0]["woundTarget"] == 4

    _seq(monkeypatch, [4, 4, 6])
    gs = _shoot_state(attacker_faction=ASTARTES, defender_faction=ORKS)
    set_oath_target(gs, 1, "2")
    build_manual_shoot_allocation(gs, "1")
    assert _records(gs)[0]["woundTarget"] == 3


def test_oath_ne_s_applique_pas_a_un_attaquant_sans_la_capacite():
    """« Each time A MODEL WITH THIS ABILITY makes an attack » : les DEUX moitiés du prédicat."""
    gs = _shoot_state(attacker_faction=ORKS, defender_faction=ASTARTES)
    gs["oath_target"][1] = "2"
    attaquant = gs["unit_by_id"]["1"]

    assert unit_is_oath_target_of(gs, attaquant, "2") is False
    assert oath_wound_roll_bonus(gs, attaquant, "2") == 0


# ─────────────────────────────────────────────────────────────────────────────
# 6. Clause de détachement du +1 Wound
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("sous_faction", sorted(OATH_EXCLUDING_KEYWORDS))
def test_verrou_clause_detachement_une_sous_faction_supprime_le_plus_un_wound(sous_faction):
    """VERROU DÉTACHEMENT : le +1 Wound tombe, la relance de touche RESTE.

    Les deux moitiés de la capacité n'ont pas la même condition : confondre les deux
    supprimerait la relance dans une armée BLOOD ANGELS, ce que la règle ne dit nulle part.
    Les quatre mots-clés sont testés — un balayage qui n'en connaîtrait que trois passerait
    avec un seul cas.
    """
    gs = _shoot_state(
        attacker_faction=ASTARTES,
        defender_faction=ORKS,
        attacker_extra_units=([{"keywordId": sous_faction}],),
    )
    set_oath_target(gs, 1, "2")
    attaquant = gs["unit_by_id"]["1"]

    assert oath_wound_roll_bonus(gs, attaquant, "2") == 0
    assert unit_is_oath_target_of(gs, attaquant, "2") is True


def test_le_plus_un_wound_tient_sans_sous_faction():
    """Contre-épreuve du test ci-dessus : sans unité exclue, le +1 s'applique."""
    gs = _shoot_state(attacker_faction=ASTARTES, defender_faction=ORKS)
    set_oath_target(gs, 1, "2")

    assert oath_wound_roll_bonus(gs, gs["unit_by_id"]["1"], "2") == 1


def test_verrou_champ_de_config_absent_leve():
    """VERROU CONFIG : `uses_codex_detachment` absent → ERREUR EXPLICITE, jamais un défaut.

    Deviner la valeur ferait apparaître ou disparaître un +1 au jet de blessure sans que
    personne ne l'ait décidé — c'est exactement ce qu'un fallback masquerait.
    """
    gs = _shoot_state(attacker_faction=ASTARTES, defender_faction=ORKS,
                      uses_codex_detachment={})
    set_oath_target(gs, 1, "2")

    with pytest.raises(KeyError, match="uses_codex_detachment"):
        oath_wound_roll_bonus(gs, gs["unit_by_id"]["1"], "2")


def test_verrou_faction_d_armee_une_unite_invitee_ne_donne_pas_la_capacite():
    """VERROU : « If your Army Faction is … » se lit dans la DÉCLARATION, pas dans le roster.

    Le défaut réel : le camp tyranide de `scenario_pvp_test.json` invite deux
    `WolfGuardTerminator` (ADEPTUS ASTARTES), et la Faction d'Armée était calculée comme l'UNION
    des mots-clés des unités présentes. Résultat mesuré : une désignation d'Oath of Moment
    réclamée au joueur tyranide à CHAQUE tour, popup compris.

    Les deux moitiés sont verrouillées ensemble parce qu'elles sont la même phrase de règle :
    l'armée n'a pas la capacité (rien n'est armé), et l'unité invitée ne l'a pas non plus
    (aucune relance de touche).
    """
    gs = _command_state(2, p1_faction=ASTARTES, p2_faction=TYRANIDS)
    # Un `WolfGuardTerminator` invité chez les tyranides : le mot-clé est là, la Faction
    # d'Armée déclarée reste TYRANIDS.
    invitee = _unit("21", 2, ASTARTES)
    gs["units"].append(invitee)
    gs["unit_by_id"]["21"] = invitee

    command_handlers.command_step_command_abilities(gs)

    assert gs["pending_oath_selection"] is None
    assert unit_has_oath_ability(gs, invitee) is False


def test_verrou_faction_d_armee_le_meme_roster_declare_astartes_arme_bien_l_oath():
    """CONTRE-ÉPREUVE du verrou ci-dessus : sans elle, « rien ne s'arme jamais » passerait aussi.

    Même état, même unité invitée — seule la DÉCLARATION change. C'est donc bien elle qui décide.
    """
    gs = _command_state(2, p1_faction=TYRANIDS, p2_faction=ASTARTES)
    porteuse = _unit("21", 2, ASTARTES)
    gs["units"].append(porteuse)
    gs["unit_by_id"]["21"] = porteuse

    command_handlers.command_step_command_abilities(gs)

    assert gs["pending_oath_selection"] == 2
    assert unit_has_oath_ability(gs, porteuse) is True


def test_verrou_faction_d_armee_declaree_absente_leve():
    """VERROU CONFIG, jumeau d'`uses_codex_detachment` : pas de déduction de secours.

    Deviner la Faction d'Armée ferait apparaître ou disparaître une capacité d'armée entière.
    """
    gs = _command_state(1, p1_faction=ASTARTES, p2_faction=TYRANIDS)
    del gs["config"]["army_faction"]

    with pytest.raises(KeyError, match="army_faction"):
        command_handlers.command_step_command_abilities(gs)


def test_verrou_faction_d_armee_declaree_que_personne_ne_porte_leve():
    """VERROU COQUILLE : une faction déclarée qu'aucune unité ne porte est une faute de frappe.

    Sans cette garde, « ADPETUS ASTARTES » éteindrait l'Oath of Moment de toute une partie en
    silence — l'échec inverse de celui qu'on corrige, et tout aussi invisible.
    """
    gs = _command_state(1, p1_faction=ASTARTES, p2_faction=TYRANIDS)
    gs["config"]["army_faction"]["1"] = "ADPETUS ASTARTES"

    with pytest.raises(ValueError, match="ADPETUS ASTARTES"):
        command_handlers.command_step_command_abilities(gs)


def test_champ_de_config_par_joueur():
    """Forme par joueur : un seul des deux camps peut jouer un détachement Codex."""
    gs = _shoot_state(attacker_faction=ASTARTES, defender_faction=ORKS,
                      uses_codex_detachment={"1": False, "2": True})
    set_oath_target(gs, 1, "2")

    assert oath_wound_roll_bonus(gs, gs["unit_by_id"]["1"], "2") == 0


# ─────────────────────────────────────────────────────────────────────────────
# 7. Sièges — le moteur ne laisse aucune décision de 08.04 sans décideur
# ─────────────────────────────────────────────────────────────────────────────


def _engine(gs):
    """Un `W40KEngine` minimal, HORS gym : c'est le siège que la politique interne tranche."""
    from engine.observation_builder import ObservationBuilder

    engine = object.__new__(W40KEngine)
    engine.game_state = gs
    engine.gym_training_mode = False
    engine.is_pve_mode = True
    engine.config = gs["config"]
    engine.config.setdefault("inches_to_subhex", 1)
    engine.config.setdefault("board", {"default": {"hex_radius": 1.0, "margin": 0.0}})
    engine.config.setdefault(
        "observation_params", {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    )
    engine.step_logger = None
    engine.action_decoder = ActionDecoder(
        {"board": {"default": {"hex_radius": 1.0, "margin": 0.0}}}
    )
    engine.obs_builder = ObservationBuilder(engine.config)
    gs["gym_training_mode"] = False
    gs["player_types"] = {"1": "ai", "2": "ai"}
    return engine


def test_un_siege_ia_hors_gym_tranche_les_deux_decisions():
    """Aucune décision de 08.04 ne peut rester en attente sans décideur.

    C'est le mode de défaillance que la scission `command_phase_start` /
    `command_phase_resume` introduit : une phase arrêtée sur un choix que PERSONNE ne joue ne
    repart jamais. Le gym répond par le masque, l'humain par l'UI — reste le siège IA hors gym,
    tranché ici. Sans ce test, ce chemin serait du code jamais exécuté.
    """
    gs = _command_state(1, p1_faction=ORKS, p2_faction=ASTARTES)
    engine = _engine(gs)

    command_handlers.command_step_command_abilities(gs)
    assert command_handlers.faction_decision_is_pending(gs)

    engine._resolve_faction_decisions_for_ai_seats()

    assert not command_handlers.faction_decision_is_pending(gs), (
        "la phase resterait arretee sur un choix que personne ne joue"
    )
    assert read_pending_agent_decision(gs) is None


def test_la_politique_ia_d_oath_designe_l_ennemi_le_plus_cher():
    """« select ONE unit » est obligatoire : la politique ne peut pas rendre « aucune »."""
    gs = _command_state(1, p1_faction=ASTARTES, p2_faction=ORKS)
    gs["units"].append(_unit("3", 2, ORKS, VALUE=500))
    gs["unit_by_id"]["3"] = gs["units"][-1]
    gs["units_cache"]["3"] = _uc(5, 0, player=2)
    gs["squad_models"]["3"] = ["M3"]
    gs["models_cache"]["M3"] = {"id": "M3", "squad_id": "3", "player": 2,
                                "HP_CUR": 3, "HP_MAX": 3, "col": 5, "row": 0}
    engine = _engine(gs)

    command_handlers.command_step_command_abilities(gs)
    engine._resolve_faction_decisions_for_ai_seats()

    assert gs["oath_target"][1] == "3", "l'ennemi le plus couteux"
    assert gs["pending_oath_selection"] is None


def test_la_relance_de_touche_atteint_step_log():
    """CHAÎNE COMPLÈTE : record → mapping `w40k_core` → token de `step.log`.

    Le record seul ne suffit pas : `w40k_core` ne recopie dans `step.log` que les clés d'une
    LISTE BLANCHE, et le formateur du `StepLogger` ne rend que les champs qu'il connaît. Une
    trace posée au record mais absente de l'un des deux maillons n'existe pas pour l'analyzer —
    c'est exactement le défaut que ce chantier devait éviter (« relance possible » vs
    « relance effectuée »). Les trois maillons sont donc vérifiés ensemble.
    """
    from ai.step_logger import StepLogger
    from engine.w40k_core import W40KEngine as _Engine

    assert _Engine._SHOT_RECORD_FIELD_MAP["hitAbility"] == "hit_ability_display_name", (
        "sans cette entree, `hitAbility` n'atteint jamais step.log"
    )
    source = inspect.getsource(StepLogger)
    # Le RENDU, pas la lecture : compter les occurrences du nom laisserait passer un formateur
    # qui lit le champ sans jamais l'afficher — un « vert vacant » de manuel.
    assert source.count("hit_ability_display_name.strip().upper()") == 2, (
        "le champ doit etre RENDU par les DEUX formateurs (tir ET melee) — le cabler d'un seul "
        "cote est le motif d'echec n°1 du depot"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 8. Les quatre défauts de la review du 2026-08-05
#
# Aucun n'était visible depuis le gym : ils vivent tous là où le gym ne passe pas — la clause
# d'exclusion (aucun roster ne pouvait la déclencher), les appelants hors moteur, et la
# propriété d'une décision entre deux joueurs.
# ─────────────────────────────────────────────────────────────────────────────


def test_la_clause_d_exclusion_lit_les_deux_tables_de_mots_cles() -> None:
    """FINDING 1 : la clause interrogeait `FACTION_KEYWORDS` SEULE, donc elle était morte.

    La règle écrit « units with the BLOOD ANGELS […] KEYWORDS » sans dire de quelle table il
    s'agit, et ce dépôt les répartit entre les deux. Le test pose le mot-clé dans `UNIT_KEYWORDS`
    — le côté que l'ancienne implémentation ne regardait PAS — et exige que le +1 tombe quand
    même. La contre-épreuve `FACTION_KEYWORDS` est le test paramétré plus haut.
    """
    gs = _shoot_state(attacker_faction=ASTARTES, defender_faction=ORKS)
    intrus = _unit("90", 1, ASTARTES)
    intrus["UNIT_KEYWORDS"] = [{"keywordId": "SPACE WOLVES"}]
    gs["units"].append(intrus)
    gs["unit_by_id"]["90"] = intrus
    set_oath_target(gs, 1, "2")

    assert oath_wound_roll_bonus(gs, gs["unit_by_id"]["1"], "2") == 0
    assert unit_is_oath_target_of(gs, gs["unit_by_id"]["1"], "2") is True


def test_le_roster_declare_reellement_des_sous_factions() -> None:
    """VERT VACANT : la clause peut être correcte et ne servir à rien si RIEN ne la déclenche.

    C'est exactement l'état livré le 2026-08-05 : aucune des 89 datasheets Space Marines ne
    portait de sous-faction, donc `oath_wound_bonus_applies` se réduisait à la config. Ce test
    lit les VRAIES datasheets par `UnitRegistry` — pas une fixture — et échoue si les quatre
    mots-clés redeviennent introuvables.
    """
    from ai.unit_registry import UnitRegistry

    from engine.game_state import OATH_FACTION_KEYWORD, _normalize_keyword

    registry = UnitRegistry()
    declares = set()
    for unit_type in ("GreyHunter", "DeathCompanyMarineEviscerator",
                      "DeathwingTerminatorPlasmaCannon"):
        # Par `_normalize_keyword`, pas par un `.upper()` maison : le test doit comparer dans la
        # MÊME forme que le moteur, sinon il verrouille une orthographe au lieu d'un fait.
        for entry in registry.get_unit_data(unit_type)["FACTION_KEYWORDS"]:
            declares.add(_normalize_keyword(entry))

    assert OATH_FACTION_KEYWORD in declares, "la faction d'armee doit rester declaree"
    assert declares & OATH_EXCLUDING_KEYWORDS, (
        "aucune sous-faction declaree : la clause d'exclusion d'Oath ne peut rien exclure"
    )


def test_une_decision_d_un_joueur_ne_bloque_pas_la_phase_de_l_autre() -> None:
    """FINDING 3 : le prédicat ignorait le joueur, donc la partie se figeait définitivement.

    Une désignation restée en attente pour le joueur 1 faisait rendre `phase_complete: False` à
    la phase de commandement du joueur 2 — et rien dans le tour de 2 ne peut la résoudre.
    """
    gs = _command_state(1, p1_faction=ASTARTES, p2_faction=ORKS)
    command_handlers.command_step_command_abilities(gs)
    assert gs["pending_oath_selection"] == 1

    # Le tour passe au joueur 2 SANS que 1 ait répondu (siège sans décideur).
    gs["current_player"] = 2
    assert command_handlers.faction_decision_is_pending(gs, 2) is False
    assert command_handlers.faction_decision_is_pending(gs, 1) is True
    resume = command_handlers.command_phase_resume(gs)
    assert resume["phase_complete"] is True, (
        "la phase du joueur 2 est arretee par une decision qui ne lui appartient pas"
    )


def test_l_expiration_purge_une_designation_restee_en_attente() -> None:
    """FINDING 3, seconde moitié : sans purge, la clé survit et 08.04 en repose une par-dessus."""
    gs = _command_state(1, p1_faction=ASTARTES, p2_faction=ORKS)
    command_handlers.command_step_command_abilities(gs)
    assert gs["pending_oath_selection"] == 1

    expire_faction_abilities_for_player(gs, 2)
    assert gs["pending_oath_selection"] == 1, "expirer le joueur 2 ne touche pas la cle du joueur 1"
    expire_faction_abilities_for_player(gs, 1)
    assert gs["pending_oath_selection"] is None


def test_aucun_appelant_hors_moteur_n_appelle_le_handler_nu() -> None:
    """FINDING 2 : quatre appelants jetaient le retour et enchaînaient sur la phase de mouvement.

    Le contrôle porte sur la SOURCE et non sur un scénario, parce que le défaut est structurel :
    n'importe quel nouvel appelant qui court-circuiterait `W40KEngine.start_command_phase`
    reproduirait le même trou, et un test de comportement ne couvrirait que les appelants
    d'aujourd'hui. Endless Duty commence avec un Intercessor (ADEPTUS ASTARTES) : la désignation
    d'Oath y restait posée pour tout le run.
    """
    from pathlib import Path

    racine = Path(__file__).resolve().parents[3]
    fautifs = []
    for chemin in sorted((racine / "services").rglob("*.py")):
        if "command_handlers.command_phase_start" in chemin.read_text(encoding="utf-8"):
            fautifs.append(chemin.name)
    assert fautifs == [], (
        f"{fautifs} appelle(nt) le handler nu : 08.04 peut poser une decision, et seul "
        f"`W40KEngine.start_command_phase` sait qui pilote le siege et resout"
    )


def test_le_cycle_pvp_complet_s_arrete_puis_repart(tmp_path) -> None:
    """FINDING 4 : le PvP doit S'ARRÊTER sur la désignation, puis REPARTIR sur l'action de l'UI.

    Le seul test de ce fichier qui monte un `W40KEngine` RÉEL sur un scénario réel, hors gym,
    avec deux sièges humains — c'est-à-dire le mode PvP. Les fixtures des tests précédents
    appellent 08.04 en isolation : elles ne prouvent ni que la phase s'arrête pour de vrai, ni
    qu'elle repart.

    Les deux moitiés comptent. « S'arrête » sans « repart » est un blocage de partie ; « repart »
    sans « s'arrête » est une capacité qui ne s'applique jamais. Le défaut mesuré le 2026-08-05
    était le second, et il n'était visible ni en gym ni dans les tests d'isolation.
    """
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    scenario = "config/board/44x60x5/scenario/scenario_attached_unit_test.json"
    engine = W40KEngine(
        config=None, rewards_config="ArmageddonAgent", training_config_name="x1",
        controlled_agent="ArmageddonAgent", active_agents=["ArmageddonAgent"],
        scenario_file=scenario, unit_registry=UnitRegistry(),
        quiet=True, gym_training_mode=False, training_n_envs=1,
    )
    engine.reset()
    gs = engine.game_state
    gs["player_types"] = {"1": "human", "2": "human"}
    engine.current_mode_code = "pvp"
    engine.config["uses_codex_detachment"] = {"1": True, "2": True}
    gs["current_player"] = 1
    gs["phase"] = "command"

    result = engine.start_command_phase()

    assert gs["pending_oath_selection"] == 1, (
        "aucune designation posee : l'armee du scenario doit etre ADEPTUS ASTARTES"
    )
    assert result.get("phase_complete") is not True, (
        "la phase a enchaine sur le mouvement : la designation est perdue (finding 2)"
    )

    cible = next(str(u["id"]) for u in gs["units"] if int(u["player"]) == 2)
    # `execute_semantic_action` — LE point d'entrée du frontend (`/api/game/action` y aboutit),
    # et PAS `_process_squad_action`, qui est celui du gym. La première version de ce test
    # exerçait le second : elle passait au vert sur un chemin que le widget n'emprunte jamais,
    # pendant que le vrai tombait dans `_process_command_phase` et sautait à la phase de
    # mouvement sans rien appliquer. « Code testé mais jamais appelé » — dans le test censé
    # fermer ce motif-là (`/code-review` du 2026-08-05, finding 1).
    ok, out = engine.execute_semantic_action({"action": "select_oath_target", "unitId": cible})

    assert ok, "l'action que le widget envoie n'est pas routee par le moteur"
    assert gs["oath_target"][1] == cible
    assert gs["pending_oath_selection"] is None
    assert out.get("phase_complete") is True, (
        "la phase ne repart pas : la partie resterait bloquee apres la designation"
    )
    # « Repart » = la phase suivante DEMARRE, pas « le moteur annonce qu'elle va demarrer ».
    # Les deux routes de decision sortent avant la boucle de cascade, seul endroit ou une
    # transition s'execute : le `next_phase` rendu au client a decrit pendant un temps une
    # bascule qui n'avait pas eu lieu, et le PvP n'a aucun verbe pour sortir de cette phase.
    assert gs["phase"] == "move", (
        "phase annoncee mais pas demarree : la partie reste en phase de commandement"
    )
    assert gs["move_activation_pool"], "phase de mouvement demarree sans pool d'activation"


def test_le_waaagh_passe_aussi_par_le_chemin_de_l_ui() -> None:
    """JUMEAU du cycle PvP, côté Waaagh! : `execute_semantic_action` doit router `agent_decision`.

    Les deux actions ont été ajoutées ensemble et oubliées ensemble sur le chemin humain. Tester
    la seule désignation d'Oath laisserait la moitié orke retomber dans
    `_process_command_phase`, qui ignore l'action et rend `command_phase_end()` : le clic
    sauterait à la phase de mouvement sans que le Waaagh! soit appelé.
    """
    gs = _command_state(1, p1_faction=ORKS, p2_faction=ASTARTES)
    engine = _engine(gs)
    gs["player_types"] = {"1": "human", "2": "human"}
    engine.gym_training_mode = True  # le siège ne doit pas être tranché par la politique interne
    # Siège d'agent : la phase de commandement ne se TERMINE pas ici (elle garde ses free steps
    # de zone intent). Ce qui est mesuré est le ROUTAGE du verbe, pas la sortie de phase — et
    # depuis que le retour de la reprise est honoré, une sortie DÉMARRE la phase de mouvement,
    # qu'un état de fixture ne peut pas construire (plateau, `game_rules`, caches). La sortie,
    # elle, est verrouillée sur un `W40KEngine` réel par `test_le_cycle_pvp_complet_...`.
    gs["gym_training_mode"] = True
    gs["config"]["controlled_player"] = 1
    command_handlers.command_step_command_abilities(gs)
    assert read_pending_agent_decision(gs) is not None

    ok, _out = engine.execute_semantic_action({"action": "agent_decision", "option_index": 0})

    assert ok, "`agent_decision` n'est pas routee sur le chemin du frontend"
    assert waaagh_is_active(gs, 1) is True
    assert read_pending_agent_decision(gs) is None


def test_l_expiration_purge_aussi_un_waaagh_reste_en_attente() -> None:
    """FINDING 3 : le jumeau oublié. Une décision `waaagh_call` survivante FAIT CRASHER 08.04.

    `set_pending_agent_decision` lève quand une décision est déjà en attente : la phase de
    commandement suivante ne resterait pas bloquée, elle planterait. Le cas visé est celui que
    la docstring de l'expiration revendique — siège sans décideur, partie rechargée.
    """
    gs = _command_state(1, p1_faction=ORKS, p2_faction=ASTARTES)
    command_handlers.command_step_command_abilities(gs)
    assert read_pending_agent_decision(gs) is not None

    # Le tour du joueur 1 revient sans que la décision ait été jouée.
    expire_faction_abilities_for_player(gs, 2)
    assert read_pending_agent_decision(gs) is not None, "expirer 2 ne touche pas la decision de 1"
    expire_faction_abilities_for_player(gs, 1)
    assert read_pending_agent_decision(gs) is None

    # Et 08.04 peut la reposer au lieu de lever.
    command_handlers.command_step_command_abilities(gs)
    assert read_pending_agent_decision(gs) is not None


def test_le_demarrage_pvp_ne_bascule_pas_sur_une_decision_en_attente() -> None:
    """FINDING 2 : `/api/game/start` écrasait la phase arrêtée en forçant le joueur 2.

    Le contrôle porte sur la SOURCE : le second `start_command_phase()` du bloc d'auto-déploiement
    doit être gardé par `faction_decision_is_pending`. Monter un vrai serveur Flask pour ce seul
    fait coûterait bien plus que ce qu'il rapporte, et le défaut est structurel — c'est la
    ligne qui manque, pas un cas de jeu particulier.
    """
    import inspect
    from pathlib import Path

    source = (Path(__file__).resolve().parents[3] / "services" / "api_server.py").read_text(
        encoding="utf-8"
    )
    bascule = source.index('gs["current_player"] = 2')
    garde = source.rindex("faction_decision_is_pending", 0, bascule)
    assert bascule - garde < 800, (
        "la bascule vers le joueur 2 n'est plus gardee par `faction_decision_is_pending` : "
        "une decision du joueur 1 serait orphelinee au demarrage de la partie"
    )


def test_verrou_l_arret_de_08_04_est_opposable_a_toute_autre_action(tmp_path) -> None:
    """L'arrêt de phase doit REFUSER les autres actions, pas seulement les attendre.

    Le défaut : `advance_phase` est intercepté AVANT le dispatch de phase, dans les DEUX points
    d'entrée. Envoyé pendant que la désignation d'Oath est en attente, il terminait la phase de
    commandement et rendait `next_phase: move`, désignation encore posée — donc purgée sans
    avoir servi à l'ouverture de la command phase suivante. Le joueur perdait ses relances de
    touche pour tout le tour, sans message. Un clic hors overlay suffisait.

    Les deux points d'entrée sont exercés : `execute_semantic_action` (UI PvP) et
    `_process_squad_action` (gym). Le second n'est jamais atteint en pratique — le masque est
    exclusif — mais c'est le jumeau, et un garde posé d'un seul côté est le motif d'échec n°1.
    """
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    scenario = "config/board/44x60x5/scenario/scenario_attached_unit_test.json"
    engine = W40KEngine(
        config=None, rewards_config="ArmageddonAgent", training_config_name="x1",
        controlled_agent="ArmageddonAgent", active_agents=["ArmageddonAgent"],
        scenario_file=scenario, unit_registry=UnitRegistry(),
        quiet=True, gym_training_mode=False, training_n_envs=1,
    )
    engine.reset()
    gs = engine.game_state
    gs["player_types"] = {"1": "human", "2": "human"}
    engine.current_mode_code = "pvp"
    engine.config["uses_codex_detachment"] = True
    gs["current_player"] = 1
    gs["phase"] = "command"
    engine.start_command_phase()
    assert gs["pending_oath_selection"] == 1, "la fixture doit poser une designation en attente"

    for point_d_entree, appel in (
        ("execute_semantic_action", lambda a: engine.execute_semantic_action(a)),
        ("_process_squad_action", lambda a: engine._process_squad_action(a)),
    ):
        for action in ({"action": "advance_phase"}, {"action": "command_wait"}):
            ok, out = appel(dict(action))
            assert not ok, (
                f"{point_d_entree} a accepte {action['action']!r} : la phase se termine et la "
                f"designation d'Oath est perdue pour tout le tour"
            )
            assert out["error"] == "faction_decision_pending"
            assert gs["phase"] == "command"
            assert gs["pending_oath_selection"] == 1

    # Et la réponse à la décision, elle, passe toujours : le garde ferme la phase, il ne la bloque pas.
    cible = next(str(u["id"]) for u in gs["units"] if int(u["player"]) == 2)
    ok, out = engine.execute_semantic_action({"action": "select_oath_target", "unitId": cible})
    assert ok and gs["pending_oath_selection"] is None
    assert out.get("phase_complete") is True


def test_verrou_la_phase_de_commandement_refuse_les_verbes_hors_vocabulaire() -> None:
    """Hors décision en attente, la command phase n'accepte que `zone_intent` et `skip`.

    Tout autre verbe était traité comme une « sortie volontaire des free steps » et terminait la
    phase en rendant `success: True` : un verbe inexistant, ou un `activate_unit` sur une unité
    ADVERSE, faisaient basculer la partie vers le mouvement. Le refus doit être INERTE — ni
    solde de la déclaration du tour précédent, ni consommation des free steps.
    """
    from engine.macro_intents import MAX_OBJECTIVES

    # Aucune des deux armées ne porte de mot-clé de faction : rien n'est en attente, c'est bien
    # le vocabulaire qui est mesuré ici et pas le garde de 08.04.
    gs = _command_state(1, p1_faction=[{"keywordId": "NECRONS"}], p2_faction=[{"keywordId": "NECRONS"}])
    engine = _engine(gs)
    gs["zone_intent_free_steps_remaining"] = MAX_OBJECTIVES
    # Sans ce champ, le solde de la déclaration lèverait : le refus serait « rouge » pour une
    # raison qui n'est pas celle qu'on mesure. Vide = aucune déclaration en attente.
    gs["_zone_intent_declarations"] = {}

    for action in (
        {"action": "action_qui_nexiste_pas"},
        {"action": "activate_unit", "unitId": "2"},
        {"action": "move", "destCol": 5, "destRow": 5},
    ):
        ok, out = engine._process_command_phase(dict(action))
        assert not ok, f"{action['action']!r} accepte : la phase de commandement se termine"
        assert out["error"] == "invalid_action_for_phase"
        assert gs["phase"] == "command"
        assert gs["zone_intent_free_steps_remaining"] == MAX_OBJECTIVES, (
            "refus non inerte : les free steps ont ete consommes"
        )

    # Le verbe de sortie, lui, reste accepté.
    gs["zone_intent_free_steps_remaining"] = 0
    ok, out = engine._process_command_phase({"action": "skip"})
    assert ok and out["phase_complete"] is True
    _ = inspect
