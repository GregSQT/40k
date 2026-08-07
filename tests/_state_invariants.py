"""Socles d'invariants pour les ``game_state`` et les unités littéraux des tests.

Deux socles, même principe et même mode de verrouillage :

- ``turn_state_invariants()`` — l'état de tour du ``game_state``, verrouillé contre ``reset()`` ;
- ``unit_invariants()`` — les champs d'état d'une unité, verrouillés contre ``create_unit()``.

POURQUOI CE FICHIER
-------------------
Le moteur pose **toujours** les clés ci-dessous (dict de reset de ``W40KEngine.reset()`` dans
``engine/w40k_core.py``, plus ``units_fought`` et le CP de 08.02 posés par ``command_phase_start``,
que la cascade command du reset appelle aussitôt). Un ``game_state`` littéral qui les omet décrit un
état **impossible en production**, et la production le lit de deux façons :

- ``require_key(...)`` / ``gs["..."]`` → le test casse bruyamment (cas ``units_advanced`` / 10.05) ;
- ``.get("...", <défaut>)`` → le test observe un comportement faux et reste **vert**.

C'est le second cas qui rend l'omission dangereuse. La fixture s'aligne donc sur le moteur, et
**jamais l'inverse** : assouplir une lecture de production en ``.get`` pour faire passer un test
est interdit — c'est ce qui aurait désactivé 10.05 en silence.

⚠️ Le dict d'``__init__`` n'est PAS la référence : il omet ``units_advanced``, ``advance_rolls``,
``units_took_to_skies`` et ``units_took_to_skies_charge``. Seul le dict de ``reset()`` est complet,
et tout chemin de production passe par ``engine.reset()``. La conformité de ce socle avec ce dict
est verrouillée par ``tests/unit/engine/test_engine_reset.py`` (classe
``TestTurnStateInvariantsConformity``) : le dict ci-dessous est **répliqué** à la main (une fixture
unitaire ne peut pas construire un engine complet), et ces tests rougissent si le moteur ajoute,
retire ou renomme un invariant. Ce dict est la seule source : rien ne recopie sa liste de clés.

USAGE
-----
Fusionner en tête du littéral, pour que les clés propres à la fixture gagnent :

    game_state = {
        **turn_state_invariants(),
        "phase": "shoot",
        "units_advanced": {"3"},   # écrase le set() vide du socle
        ...
    }

    unit = {
        **unit_invariants(),
        "id": "1", "player": 1, "col": 5, "row": 10,
        "battle_shocked": True,    # écrase le False du socle
        ...
    }

⚠️ Une unité littérale n'a besoin du socle que si elle représente une unité DU ``game_state``.
Une **config d'entrée** (le dict passé à ``W40KEngine(config=...)``, qui porte ``ICON`` /
``ILLUSTRATION_RATIO``) n'en veut pas : ``create_unit`` pose ces champs lui-même, et les y mettre
ferait décrire à la fixture un état que le constructeur va de toute façon recalculer.
"""

from __future__ import annotations

from typing import Any, Dict


def turn_state_invariants() -> Dict[str, Any]:
    """Retourne les invariants d'état de tour, aux valeurs exactes d'un ``game_state`` post-reset.

    ``units_fought`` n'est pas dans le dict de ``reset()`` : c'est ``command_phase_start`` qui le
    pose, à chaque tour. Il est néanmoins présent dans tout ``game_state`` de production (la
    cascade command suit immédiatement le reset) et lu en ``require_key`` par la phase fight —
    il appartient donc au socle.

    Un dict neuf à chaque appel : les valeurs sont mutables et ne doivent jamais être
    partagées entre deux fixtures.
    """
    return {
        # Compteur de tour : present dans TOUT game_state de production (`reset()` le pose a 1).
        # Les emetteurs d'action_log le lisent en `require_key` depuis la suppression du repli
        # silencieux `game_state["current_turn"] ... else 1` — une cle qui n'a jamais existe et
        # qui datait toutes les lignes pile-in/consolidation de step.log au tour 1.
        "turn": 1,
        # Stock de CP des deux joueurs (regle 08.02), lu en `require_key` par
        # `gain_command_points` (cascade command) et par l'observation. `reset()` le pose a
        # `initial_command_points(config)` = 0, puis la cascade command du tour 1 accorde le CP
        # de 08.02 aux deux joueurs : la valeur post-reset est 1, comme pour `units_fought`.
        "command_points": {1: 1, 2: 1},
        "units_moved": set(),
        "units_fled": set(),
        "units_cannot_charge": set(),
        "units_shot": set(),
        "units_shot_previous_turn": set(),
        "units_charged": set(),
        "units_attacked": set(),
        "units_fought": set(),
        "units_advanced": set(),
        "advance_rolls": {},
        "units_took_to_skies": set(),
        "units_took_to_skies_charge": set(),
        # 21.03 `L6` : « la question a ete posee » (distinct de « le vol est declare »).
        "units_fly_declaration_resolved": set(),
        "units_fly_declaration_resolved_charge": set(),
        "units_reacted_this_enemy_turn": set(),
        "reaction_window_active": False,
        "last_move_event_id": 0,
        "last_move_cause": "normal",
        "reactive_mode": "micro",
        "reactive_macro_order_current_window": [],
        "reactive_decision_mode": "auto",
        "reactive_decision_payload": {},
        # Capacites de faction (chantier 03), posees par `initial_faction_ability_state()` a
        # l'init ET au reset. Lues en `require_key` par l'observation (les 6 drapeaux de
        # `global_bin`) et par 08.04 : une fixture qui les omet fait lever la construction de
        # l'observation. `waaagh_called` porte le « once per battle », `waaagh_active` la duree.
        # Depuis le 2026-08-06 l'observation lit AUSSI la clause du +1 Wound d'Oath (bits
        # `*_oath_wound_bonus_active`) : une fixture qui declare une armee ADEPTUS ASTARTES
        # doit porter `uses_codex_detachment` dans sa CONFIG, comme tout scenario de production.
        "waaagh_called": {1: False, 2: False},
        "waaagh_active": {1: False, 2: False},
        "oath_target": {1: None, 2: None},
        "pending_oath_selection": None,
    }


def unit_invariants() -> Dict[str, Any]:
    """Retourne les champs d'état que TOUTE unité de production porte, à valeur constante.

    Les deux constructeurs du moteur (``GameStateManager.create_unit`` et
    ``_build_enhanced_unit``, ``engine/game_state.py``) posent ces clés sur chaque unité, aux
    valeurs ci-dessous, indépendamment du roster. Une unité littérale qui les omet décrit une
    unité **impossible** — et le mode d'échec est le même que pour le ``game_state`` : bruyant
    en ``require_key``, SILENCIEUX en ``.get(défaut)``.

    N'ENTRENT PAS ICI les champs DÉRIVÉS d'autres champs de l'unité, dont la valeur dépend du
    roster et qu'un socle figerait à une valeur fausse :
      - ``SHOOT_LEFT`` / ``ATTACK_LEFT`` — nombre d'attaques de l'arme sélectionnée ;
      - ``selectedRngWeaponIndex`` / ``selectedCcWeaponIndex`` — 0 si l'unité porte une arme de
        ce type, ``None`` sinon : la valeur dépend de ``RNG_WEAPONS`` / ``CC_WEAPONS`` ;
      - ``hideable`` — ``compute_hideable(UNIT_KEYWORDS)`` ;
      - ``_UNIT_RULES_OWN`` — copie de ``UNIT_RULES`` hors character replié (19.04).
    Une fixture qui en a besoin les pose elle-même, à une valeur cohérente avec ses armes et ses
    mots-clés. Le verrou ``TestUnitInvariantsConformity`` (tests/unit/engine/test_state_manager.py)
    interdit qu'une clé constante nouvelle échappe au socle sans être classée ici.

    Un dict neuf à chaque appel : les valeurs sont mutables et ne doivent jamais être partagées
    entre deux unités.
    """
    return {
        # Etage (format B, §2.5). 0 = rez-de-chaussee, cas metier par defaut.
        "level": 0,
        # Orientation du socle (degres) : oriente l'empreinte pour la LoS et les pivots.
        "orientation": 0,
        # Regle 24.16 / feature d'observation : 0 = posee avant la bataille. None (deploiement
        # actif en attente) et N > 0 (arrivee de reserve) sont des etats que la fixture pose
        # elle-meme — ils ne sont pas l'etat par defaut d'une unite sur le board.
        "deployed_on_turn": 0,
        # Regle 19.01 : mots-cles d'escouade auxquels ce leader peut s'attacher. [] pour toute
        # unite non-leader, cas metier valide (la regle LEADER est absente de sa datasheet).
        "CAN_LEAD": [],
        # Provenance 19.04 : {id du leader replie -> ses regles}. Vide tant qu'aucun character
        # n'est attache — l'immense majorite des fixtures.
        "_ATTACHED_RULE_GROUPS": {},
        # Regles 13.08-13.09 : etat runtime, et la liste par figurine qui le porte.
        "hidden": False,
        "hidden_models": [],
        # Regle 01.07 : remis a False au debut de la command phase du joueur.
        "battle_shocked": False,
        # Reserves strategiques 20.01/20.02 : False = l'unite commence sur la table. Le roster
        # (`strategic_reserves`) est ce qui bascule ce drapeau, jamais le moteur seul.
        "in_strategic_reserves": False,
        # 20.02 : une unite de reserve n'a pas encore ete repositionnee.
        "reserves_repositioned": False,
        # Parametres 20.03/20.04 a leur valeur GENERIQUE, portes par l'unite pour qu'une capacite
        # puisse les surcharger (Logan Grimnar fait arriver au 1er round, etc.). Valeurs definies
        # par INGRESS_FIRST_BATTLE_ROUND / INGRESS_SETUP_DISTANCE_INCHES /
        # INGRESS_ENEMY_CLEARANCE_INCHES (engine/phase_handlers/movement_handlers.py), que
        # `_default_reserves_parameters` ne fait que reexporter. Recopiees a la MAIN, jamais
        # importees : importer ferait suivre le socle en silence et le verrou se comparerait a
        # lui-meme. Recopiees, un changement de defaut rougit et impose de relire les fixtures.
        "reserves_arrival_round": 2,
        "reserves_edge_distance_inches": 6,
        "reserves_enemy_clearance_inches": 8,
        # Mots-cles de FACTION (chantier 03) : « If your Army Faction is ORKS / ADEPTUS
        # ASTARTES ». Poses par les DEUX constructeurs et lus en `require_key`
        # (`unit_faction_keywords`). Vide = aucune faction declaree, donc aucune capacite de
        # faction — c'est l'etat neutre, celui que veut une fixture qui ne teste pas Waaagh!
        # ni Oath. Une fixture qui les teste ecrase cette liste.
        "FACTION_KEYWORDS": [],
    }
