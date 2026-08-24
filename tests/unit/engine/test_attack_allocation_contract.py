"""05 Attack sequence — une blessure NON ALLOUÉE n'existe que sur une cible ANÉANTIE.

CE QUE CE FICHIER REMPLACE. Le journal écrit `Save [NOT ALLOCATED]` quand une blessure n'a
jamais été allouée à une figurine (`step_logger._save_segments`, seuil de sauvegarde absent).
Un contrôle de `ai/analyzer.py` recoupait ces lignes avec l'état de la cible pour dénoncer un
moteur qui cesserait d'allouer sans raison. Retiré le 2026-08-12 parce qu'il jugeait sur l'état
RECONSTRUIT par l'analyzer : il ne pouvait donc signaler que les dérives de cette reconstruction.
Mesures et chiffres dans `Documentation/Implémentation/analyzer_couverture.md`, table
« Contrôles SUPPRIMÉS » — ils ne sont pas recopiés ici, ils y vivraient en double.

L'invariant, lui, se vérifie EXACTEMENT ici, sur l'état du moteur : le seul chemin qui laisse
une blessure sans allocataire est `_mark_manual_overkill_wasted`, atteint uniquement quand
`_current_live_group` ne trouve plus un seul groupe d'allocation vivant — c'est-à-dire quand
l'escouade cible n'a plus aucune figurine (« excess attacks lost », 05). Ces tests fixent les
deux faces : le pool restant EST perdu quand la cible tombe, et il ne l'est JAMAIS tant qu'une
figurine vit.

TIR ET MÊLÉE, les deux. `FIGHT_CTX` délègue aujourd'hui à la même boucle d'allocation que le
tir et ne surcharge pas `resolve_wound_fn` — mais `HAZARD_CTX`, lui, le fait déjà : rien
n'interdit à la mêlée de diverger demain, et les tests de tir resteraient verts en silence.
Chaque test est donc joué sur les deux chemins, par leur VRAI point d'entrée respectif
(`build_manual_shoot_allocation` / `build_manual_fight_allocation`).

Même harnais que `test_devastating_wounds_shoot.py` : chemin VIF, `gym_training_mode` (le
défenseur est programmatique, l'allocation se résout sans prompt), RNG forcé.
"""
import random

import pytest

from engine.phase_handlers import shooting_handlers
from engine.phase_handlers.fight_handlers import build_manual_fight_allocation
from engine.phase_handlers.shared_utils import build_manual_shoot_allocation
from tests._state_invariants import turn_state_invariants
from tests.unit.engine._config_helpers import build_game_rules
from tests.unit.engine._state_builders import units_cache_entry as _uc

#: Les deux chemins d'allocation à couvrir : (phase, point d'entrée). Le paramètre porte la
#: phase plutôt qu'un booléen — c'est lui qui choisit l'arme, la clé d'intents et le libellé.
ALLOCATION_PATHS = [
    pytest.param("shoot", build_manual_shoot_allocation, id="tir"),
    pytest.param("fight", build_manual_fight_allocation, id="melee"),
]


def _seq(monkeypatch, rolls):
    seq = list(rolls)

    def fake(a, b):
        assert seq, "sequence RNG epuisee"
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})



def _target_model(index):
    """Figurine cible n°`index` : SANS sauvegarde possible (Sv 7+, pas d'invulnérable) et 1 PV.

    Chaque blessure qui lui est allouée la tue, donc le nombre de figurines mortes vaut
    exactement le nombre de blessures ALLOUÉES — c'est ce qui rend le compte lisible. Les jets
    de sauvegarde restent tirés (ils trient le pool, 05.04), aucun ne sauve.
    """
    return {"id": f"T{index}", "squad_id": "2", "player": 1, "T": 4, "HP_CUR": 1, "HP_MAX": 1,
            "ARMOR_SAVE": 7, "INVUL_SAVE": 7, "role": None, "unitType": "Grunt",
            "points_per_hp": 5.0, "VALUE": 10.0, "col": 9, "row": 9 + index,
            "RNG_WEAPONS": [], "CC_WEAPONS": [],
            # Exigés par `_recompute_squad_occupied_hexes` et `_recompute_squad_cache`, appelés
            # à chaque `destroy_model` : cette escouade perd des figurines, contrairement à
            # celles des fixtures de tir voisines.
            "level": 0, "BASE_SHAPE": "round", "BASE_SIZE": 1, "OC": 1}


def _game_state(phase, n_target_models, n_attacks):
    """Attaquant '1' (une arme, `n_attacks` attaques) vs escouade '2' de `n_target_models` figs.

    `phase` choisit le miroir : arme de tir + `pending_squad_shoot_intents`, ou arme de corps à
    corps + `pending_squad_fight_intents`. Tout le reste du décor est commun — c'est le même
    moteur d'allocation en aval.
    """
    melee = phase == "fight"
    weapon = {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": n_attacks, "RNG": 24,
              "WEAPON_RULES": [], "code": "test_gun", "display_name": "Gun"}
    attacker = {"id": "A1", "squad_id": "1", "player": 0, "T": 4,
                "SHOOT_LEFT": 1, "ATTACK_LEFT": n_attacks, "col": 0, "row": 0,
                "RNG_WEAPONS": [] if melee else [weapon],
                "CC_WEAPONS": [weapon] if melee else []}
    targets = {f"T{i}": _target_model(i) for i in range(n_target_models)}
    return {**turn_state_invariants(),
        # PvE (GreedyBot) : heuristique sans prompt, sans décision agent.
        # gym_training_mode=True poserait une pending_agent_decision à chaque sélection de
        # figurine — ce fichier teste les RÈGLES d'allocation, pas le mécanisme décision.
        "player_types": {"0": "human", "1": "ai"},
        "turn": 1, "phase": phase,
        "action_logs": [], "action_log_seq": 0,
        "models_cache": {"A1": attacker, **targets},
        "squad_models": {"1": ["A1"], "2": list(targets)},
        "squad_cache": {"1": {"model_count_at_start": 1},
                        "2": {"model_count_at_start": n_target_models}},
        "units_cache": {"1": _uc(0, 0, player=0), "2": _uc(9, 9, player=1)},
        "units": [{"id": "1", "player": 0}, {"id": "2", "player": 1}],
        # `player` sur l'attaquant : exigé par le décideur d'allocation du COMBAT
        # (`_is_ai_controlled_fight_unit`), qui lève sinon avant tout log.
        "unit_by_id": {"1": {"id": "1", "UNIT_RULES": [], "player": 0},
                       "2": {"id": "2", "UNIT_RULES": [], "player": 1}},
        "objectives": [], "units_moved": set(), "units_advanced": set(),
        # `destroy_model` invalide la LoS de l'escouade amputée et recalcule son cache :
        # compteur et plateau présents dans tout game_state réel (w40k_core), donc requis ici.
        "_unit_move_version": 0,
        "board_cols": 44, "board_rows": 60, "wall_hexes": set(),
        # Règles RÉELLES (`config/game_config.json`), pas un sous-ensemble épinglé à la main :
        # une règle ajoutée au moteur n'a pas à casser ce fichier. `engagement_zone=1` est la
        # seule valeur neutralisée, comme dans les autres fixtures moteur.
        "config": {"game_rules": build_game_rules(engagement_zone=1)},
        ("pending_squad_fight_intents" if melee else "pending_squad_shoot_intents"): {
            "1": [{"model_id": "A1", "target_unit_id": "2", "weapon_index": 0,
                   "n_attacks_resolved": n_attacks, "target_squad_size_at_declaration": 1}]
        },
    }


def _shot_records(gs):
    out = []
    for log in gs.get("action_logs", []):
        out.extend(log.get("shootDetails", []) if isinstance(log, dict) else [])
    return out


def _unallocated(gs):
    """Records qui produisent la ligne `Save [NOT ALLOCATED]` au journal.

    Deux conditions, celles-là mêmes qu'applique `ai/step_logger.py` : l'attaque a BLESSÉ
    (sans quoi aucun segment `Save` n'est écrit) et son seuil de sauvegarde est absent — le
    seuil n'est écrit qu'à l'allocation, dans `_resolve_one_manual_wound`. La correspondance
    entre ce champ de record et le texte de la ligne est verrouillée de son côté par
    `tests/unit/ai/test_step_log_weapon_rule_tokens.py` (`_save_segments` → `[NOT ALLOCATED]`).
    """
    return [
        r for r in _shot_records(gs)
        if r.get("strengthResult") == "SUCCESS" and r.get("saveTarget") is None
    ]


def _squad_alive(gs, squad_id):
    return [m for m in gs["squad_models"][squad_id] if m in gs["models_cache"]]


@pytest.mark.parametrize("phase,build_allocation", ALLOCATION_PATHS)
def test_le_pool_restant_est_perdu_quand_la_cible_tombe(monkeypatch, phase, build_allocation):
    """2 figurines, 4 attaques toutes réussies : les 2 blessures excédentaires n'ont plus
    d'allocataire et l'escouade est vide. C'est le cas LÉGITIME de « excess attacks lost »."""
    # 4 attaques × (touche, blessure, sauvegarde). Le dé de sauvegarde est tiré pour TOUTES les
    # blessures, y compris celles qui ne seront jamais allouées : c'est lui qui trie le pool
    # (05.04), il précède donc l'allocation.
    _seq(monkeypatch, [4, 4, 1] * 4)
    gs = _game_state(phase, n_target_models=2, n_attacks=4)

    build_allocation(gs, "1")

    perdues = _unallocated(gs)
    assert _squad_alive(gs, "2") == [], "les 2 blessures allouées doivent anéantir l'escouade"
    assert len(perdues) == 2, "les 2 attaques excédentaires restent sans allocataire"
    assert all(r.get("wasted") is True for r in perdues), \
        "une attaque perdue doit être tagguée `wasted` (05, excess attacks lost)"


@pytest.mark.parametrize("phase,build_allocation", ALLOCATION_PATHS)
def test_aucune_attaque_non_allouee_tant_qu_une_figurine_vit(monkeypatch, phase, build_allocation):
    """3 figurines, 2 attaques réussies : une figurine survit, donc AUCUNE attaque ne peut
    rester sans allocataire. C'est l'invariant que le contrôle analyzer prétendait surveiller."""
    _seq(monkeypatch, [4, 4, 1, 4, 4, 1])
    gs = _game_state(phase, n_target_models=3, n_attacks=2)

    build_allocation(gs, "1")

    assert len(_squad_alive(gs, "2")) == 1, "2 blessures allouées sur 3 figurines : 1 survivante"
    assert _unallocated(gs) == [], \
        "une blessure ne peut rester non allouée tant qu'un groupe d'allocation vit (05.03)"


@pytest.mark.parametrize("phase,build_allocation", ALLOCATION_PATHS)
def test_les_touches_ratees_ne_produisent_pas_de_blessure_a_allouer(
    monkeypatch, phase, build_allocation
):
    """Contre-épreuve du compteur : une attaque qui rate n'entre pas dans le pool, donc ne
    compte ni comme allouée ni comme perdue. Sans quoi le test ci-dessus passerait pour une
    mauvaise raison (aucune blessure du tout)."""
    _seq(monkeypatch, [1, 1])  # 05.01 : 1 non modifié = touche ratée
    gs = _game_state(phase, n_target_models=3, n_attacks=2)

    build_allocation(gs, "1")

    assert len(_squad_alive(gs, "2")) == 3, "aucune touche : aucune perte"
    assert _shot_records(gs), "les tirs ratés doivent tout de même produire des records"
    assert _unallocated(gs) == [], "aucune blessure à allouer, donc aucune blessure perdue"
