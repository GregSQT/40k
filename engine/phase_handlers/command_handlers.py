#!/usr/bin/env python3
"""
command_handlers.py - Command Phase Implementation
Pure stateless functions implementing command phase specification

The command phase handles all administrative tasks (reset marks, clear caches, etc.)
before the movement phase. In Phase 2, the agent may take zone intent free steps
(up to MAX_OBJECTIVES) before transitioning to move.
"""

from typing import Dict, List, Tuple, Set, Optional, Any
from shared.data_validation import require_key
from engine.game_state import (
    CORE_CP_GAIN_PER_COMMAND_PHASE, GameStateManager, gain_command_points,
    OATH_FACTION_KEYWORD, WAAAGH_FACTION_KEYWORD,
    army_faction_keywords, call_waaagh, expire_faction_abilities_for_player,
    set_oath_target, waaagh_is_available,
)


def command_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Initialize command phase - do all maintenance/resets, then either:
    - Stay in command if zone intent free steps are available (Phase 2), or
    - Auto-advance to move (no free steps or bot player).

    LES CINQ ÉTAPES DE LA PHASE (PDF 08) — l'ordre est celui du PDF, et c'est un contrat :
      08.01 `command_step_start_of_phase`     — début de phase (remises à zéro, caches)
      08.02 `command_step_gain_core_cp`       — les DEUX joueurs gagnent 1 CP
      08.03 `command_step_battle_shock`       — jets du joueur ACTIF seulement
      08.04 `command_step_command_abilities`  — capacités « in your command phase »
      08.05 `command_phase_end`               — fin de phase
    Elles sont découpées en fonctions nommées parce que plusieurs capacités se déclenchent à une
    étape PRÉCISE (Waaagh! et Oath au début, Get da Good Bitz en fin) : sans les étapes, il n'y a
    aucun endroit où les accrocher, et elles finiraient au petit bonheur dans le corps de la phase.

    Phase 2 changes:
    - Initializes zone_intent_free_steps_remaining = MAX_OBJECTIVES
    - Populates unit_zone_assignments (one per alive friendly unit)
    - Returns without phase_complete if free steps > 0 (agent will issue zone intent actions)
    """
    from engine.macro_intents import INTENT_INVADE, MAX_OBJECTIVES, get_nearest_objective_zone

    command_step_start_of_phase(game_state)   # 08.01
    command_step_gain_core_cp(game_state)     # 08.02
    command_step_battle_shock(game_state)     # 08.03

    # Build activation pool (empty for now, structure ready for future)
    command_build_activation_pool(game_state)

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    command_pool = require_key(game_state, "command_activation_pool")
    add_debug_file_log(game_state, f"[POOL BUILD] E{episode} T{turn} command command_activation_pool={command_pool}")

    # Console log
    from engine.game_utils import add_console_log
    add_console_log(game_state, "COMMAND PHASE START")

    command_step_command_abilities(game_state)  # 08.04

    # Primary objective scoring (command phase). Règle de MISSION (14.03), pas une des cinq
    # étapes : elle est laissée APRÈS 08.03 parce qu'elle lit l'OC, que le battle-shock vient de
    # modifier à '-' (01.07) — l'avancer changerait les VP marqués.
    state_manager = GameStateManager(require_key(game_state, "config"))
    state_manager.apply_primary_objective_scoring(game_state, "command")

    # Populate unit_zone_assignments for ALL alive units (both players)
    from engine.phase_handlers.shared_utils import is_unit_alive
    assignments = {}
    for unit in game_state["units"]:
        if not is_unit_alive(str(unit["id"]), game_state):
            continue
        if unit.get("col", -1) >= 0 and unit.get("row", -1) >= 0:
            zone_idx = get_nearest_objective_zone(unit, game_state)
        else:
            zone_idx = 0
        assignments[str(unit["id"])] = zone_idx
    game_state["unit_zone_assignments"] = assignments

    return command_phase_resume(game_state)


def command_phase_resume(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """Suite de la phase de commandement, une fois 08.04 posé — ou une fois ses décisions jouées.

    SCINDÉ de `command_phase_start` parce que la phase a désormais un point d'ARRÊT : les
    capacités « at the start of your Command phase » (Waaagh!, Oath of Moment) sont des décisions
    de joueur, et le moteur doit rendre la main dessus exactement comme il le fait sur un
    `waiting_for_player` PvP. Le décideur (agent via le masque, bot, ou humain) rappelle ensuite
    cette fonction, qui reprend là où la phase s'était interrompue.

    IDEMPOTENTE : rejouée après chaque décision. Elle ne fait que (re)poser le compteur de free
    steps et trancher entre « rester en command » et « passer au move ». Aucun intent ne peut
    avoir été joué entre-temps — le masque est EXCLUSIF tant qu'une décision est en attente.
    """
    from engine.macro_intents import MAX_OBJECTIVES

    gym_training_mode = game_state.get("gym_training_mode", False)
    current_player = game_state.get("current_player")
    config = game_state["config"]
    controlled_player = config.get("controlled_player")

    is_agent_turn = (
        gym_training_mode
        and controlled_player is not None
        and current_player == controlled_player
    )

    # Reset zone_intent_free_steps_remaining to MAX_OBJECTIVES.
    # Cette valeur PLEINE est aussi le signal qu'aucun intent n'a encore ete joue ce tour :
    # `W40KEngine._process_command_phase` s'en sert pour solder la declaration du tour
    # precedent exactement une fois (cf. `settle_pending_zone_intent_declaration`).
    # Posée AVANT le test de décision en attente : le masque de la phase de commandement la lit
    # sans défaut, y compris sur le step où la décision est jouée.
    game_state["zone_intent_free_steps_remaining"] = MAX_OBJECTIVES if is_agent_turn else 0

    # 08.04 non soldé : le moteur reste en phase de commandement et n'avance PAS. Sans cet arrêt,
    # la phase enchaînerait sur le move et la décision serait perdue — l'agent n'appellerait
    # jamais son Waaagh!, la capacité serait du code mort.
    # `current_player` et pas « n'importe qui » : la phase de commandement appartient au joueur
    # actif, et lui seul peut répondre. Arrêter sa phase sur une décision de l'ADVERSAIRE la
    # bloquerait définitivement — rien dans son tour ne peut la résoudre.
    if faction_decision_is_pending(game_state, current_player):
        return {"phase_complete": False, "phase": "command"}

    if is_agent_turn:
        # Stay in command phase — agent will issue zone intent actions
        return {"phase_complete": False, "phase": "command"}

    # Bot player or non-training: skip free steps, auto-advance to move
    return command_phase_end(game_state)


def command_step_start_of_phase(game_state: Dict[str, Any]) -> None:
    """08.01 START OF PHASE — pose la phase et remet à zéro l'état « ce tour ».

    Point d'accrochage des capacités « at the start of your Command phase ». Rien ne s'y
    déclenche aujourd'hui : les capacités qui le feront appartiennent aux chantiers 03 et 06.
    """
    # Set phase
    game_state["phase"] = "command"

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    units_cache = require_key(game_state, "units_cache")
    add_debug_file_log(game_state, f"[PHASE START] E{episode} T{turn} command units_cache={units_cache}")

    # Snapshot last turn's shooting BEFORE reset (rule 13.09 Hidden: "did not make ranged
    # attacks during this turn or during the previous turn"). Captured at each turn start so
    # it holds the previous player-turn's shots when evaluating enemy targets.
    game_state["units_shot_previous_turn"] = set(game_state.get("units_shot", set()))

    # Reset ALL tracking sets (moved from movement_phase_start)
    game_state["units_moved"] = set()
    # Distance parcourue par figurine (V11 §9.2.5) — MEME cycle de vie que `units_moved` :
    # c'est la version continue du meme fait ("cette figurine a bouge de X ce tour").
    game_state["moved_distance_by_model"] = {}
    game_state["units_fled"] = set()
    game_state["units_shot"] = set()
    game_state["units_charged"] = set()
    game_state["units_fought"] = set()
    game_state["units_attacked"] = set()
    game_state["units_advanced"] = set()
    game_state["advance_rolls"] = {}
    game_state["units_took_to_skies"] = set()
    game_state["units_took_to_skies_charge"] = set()
    game_state["units_reacted_this_enemy_turn"] = set()

    game_state["reactive_macro_order_current_window"] = []
    game_state["reaction_window_active"] = False
    game_state["reactive_decision_payload"] = {}

    # Clear movement preview state
    game_state["valid_move_destinations_pool"] = []
    game_state["preview_hexes"] = []
    game_state["move_preview_footprint_zone"] = set()
    game_state["move_preview_footprint_mask_loops"] = None
    game_state["move_preview_footprint_span"] = None
    game_state["active_movement_unit"] = None

    # Clear enemy reachable positions cache (enemy positions may have changed)
    # Used by RewardCalculator._get_enemy_reachable_positions for defensive threat calculation
    game_state["enemy_reachable_cache"] = {}


def command_step_gain_core_cp(game_state: Dict[str, Any]) -> None:
    """08.02 GAIN CORE CP — « Both players gain 1 Command Point (CP). »

    LES DEUX joueurs, pas le seul joueur actif : c'est la différence avec 08.03 juste en dessous,
    et l'erreur que la lecture rapide du PDF produit. Le montant est la constante du PDF, pas un
    réglage de scénario.
    """
    for player in (1, 2):
        gain_command_points(
            game_state, player, CORE_CP_GAIN_PER_COMMAND_PHASE, "08.02 Core CP"
        )


def command_step_battle_shock(game_state: Dict[str, Any]) -> None:
    """08.03 BATTLE-SHOCK — un jet par unité concernée, pour le joueur ACTIF seulement.

    « The active player must now make one battle-shock roll for each unit IN THEIR ARMY that
    fulfils one or both of the following conditions : that unit is currently battle-shocked ;
    that unit is at, or below, half-strength. » Les deux conditions sont une UNION : une unité
    déjà battle-shocked rejette même revenue au-dessus du demi-effectif — c'est ce jet qui lui
    permet d'en sortir (clause de sortie appliquée par `roll_battle_shock`).
    """
    from engine.phase_handlers.shared_utils import (
        is_unit_alive, is_unit_at_or_below_half_strength, roll_battle_shock,
    )

    current_player = require_key(game_state, "current_player")
    for unit in require_key(game_state, "units"):
        if require_key(unit, "player") != current_player:
            continue
        unit_id = str(unit["id"])
        if not is_unit_alive(unit_id, game_state):
            continue
        needs_roll = require_key(unit, "battle_shocked") or is_unit_at_or_below_half_strength(
            unit_id, game_state
        )
        if needs_roll:
            # `roll_battle_shock` journalise le jet (action log + trace debug) : il connaît déjà
            # le seuil qu'il a employé, le recalculer ici pour le logger le balayait deux fois.
            roll_battle_shock(unit_id, game_state)


def command_step_command_abilities(game_state: Dict[str, Any]) -> None:
    """08.04 COMMAND ABILITIES — capacités qui se déclenchent « in your Command phase ».

    Portent ICI les deux capacités de faction (chantier 03) : Waaagh! (ORKS) et Oath of Moment
    (ADEPTUS ASTARTES). Les deux sont déclarées « at the start of your Command phase » et durent
    « until the start of your next Command phase » — c'est la MÊME étape qui les éteint et qui
    les repose, pour le joueur ACTIF seulement.

    ORDRE, et il n'est pas indifférent :
      1. EXTINCTION de ce que le joueur actif avait posé au tour précédent. Elle a lieu ici et
         PAS en fin de tour : les deux effets doivent survivre au tour adverse.
      2. Waaagh! — décision binaire, une seule fois par partie.
      3. Oath — désignation d'une unité ennemie, obligatoire, chaque tour.

    Le moteur ne tranche rien : il POSE la décision et `command_phase_resume` rend la main.
    (Grot Orderly et les autres capacités « in your command phase » viendront au chantier 06.)
    """
    current_player = int(require_key(game_state, "current_player"))

    # 1. « Until the start of your NEXT Command phase » — la borne est ici.
    expire_faction_abilities_for_player(game_state, current_player)

    # 2. Waaagh! — « once per battle, at the start of your Command phase, YOU CAN call a Waaagh! ».
    #    « You can » : c'est optionnel, d'où deux candidats. L'ordre est CONTRACTUEL (§9.6) et
    #    c'est lui qui distingue les deux (cf. AGENT_DECISION_TYPE_IDS) : 0 = appeler, 1 = passer.
    if (
        WAAAGH_FACTION_KEYWORD in army_faction_keywords(game_state, current_player)
        and waaagh_is_available(game_state, current_player)
    ):
        from engine.agent_decision import set_pending_agent_decision

        set_pending_agent_decision(
            game_state,
            decision_type="waaagh_call",
            player=current_player,
            # La décision n'appartient à aucune unité : c'est une capacité d'ARMÉE. Le champ est
            # exigé par le mécanisme générique (il identifie le point de choix côté PvP), d'où un
            # identifiant de joueur explicite plutôt qu'une unité arbitrairement choisie, qui
            # aurait laissé croire que le Waaagh! est une capacité de datasheet.
            unit_id=f"player_{current_player}",
            options=[
                {"label": "Call the Waaagh!", "effect_ids": (), "payload": {"call": True}},
                {"label": "Do not call the Waaagh!", "effect_ids": (), "payload": {"call": False}},
            ],
        )
        # Une seule décision à la fois : le moteur rend la main maintenant. L'Oath ci-dessous ne
        # peut de toute façon pas concerner le même joueur (aucune armée n'est ORKS et ADEPTUS
        # ASTARTES à la fois), mais l'ordre reste explicite plutôt qu'implicitement sûr.
        return None

    # 3. Oath of Moment — « select one unit from your opponent's army ». NON OPTIONNEL : pas de
    #    candidat « aucune cible ». S'il n'existe aucune unité ennemie vivante, il n'y a rien à
    #    désigner et la clause est sans objet (elle ne peut alors bénéficier à personne).
    if OATH_FACTION_KEYWORD in army_faction_keywords(game_state, current_player):
        if oath_selectable_enemy_ids(game_state, current_player):
            game_state["pending_oath_selection"] = current_player
    return None


def oath_selectable_enemy_ids(game_state: Dict[str, Any], player: int) -> List[str]:
    """Unités ennemies VIVANTES désignables par l'Oath of Moment de `player`.

    SOURCE UNIQUE de la désignation : le masque d'action l'utilise pour ouvrir les `OATH_SLOTS`,
    le décodeur pour traduire le slot joué, la politique bot pour choisir. Trois lecteurs, une
    définition — sans quoi le masque pourrait ouvrir un slot que le décodeur refuserait.
    """
    from engine.phase_handlers.shared_utils import is_unit_alive

    player_int = int(player)
    return [
        str(require_key(unit, "id"))
        for unit in require_key(game_state, "units")
        if int(require_key(unit, "player")) != player_int
        and is_unit_alive(str(require_key(unit, "id")), game_state)
    ]


def faction_decision_is_pending(game_state: Dict[str, Any], player: Optional[int] = None) -> bool:
    """True tant qu'une décision de 08.04 attend son décideur (Waaagh! ou Oath).

    Les deux mécanismes sont volontairement distincts : le Waaagh! est un choix binaire dont les
    candidats ne sont PAS des entités observées (`pending_agent_decision` + `CHOICE_i`), l'Oath
    désigne littéralement une escouade ennemie et se paramètre donc en DIMENSION D'ACTION +
    pointeur (`OATH_SLOTS`), conformément à `macro_intents`. Ce prédicat est ce qui les réunit
    pour le seul consommateur qui n'a pas à connaître la différence : l'arrêt de la phase.

    ⚠️ `player` N'EST PAS UN CONFORT. Une décision APPARTIENT à un joueur : 08.04 ne la pose que
    pour le joueur ACTIF, et seul lui peut y répondre. Sans ce filtre, une décision que le joueur
    1 n'a pas jouée arrête AUSSI la phase de commandement du joueur 2 — et comme rien dans le
    tour de 2 ne peut la résoudre, la partie ne repart jamais. Le défaut n'est pas théorique :
    il suffit qu'un siège reste sans réponse un tour (`/code-review` du 2026-08-05, finding 3).

    `player=None` répond « une décision est-elle en attente, pour n'importe qui ? » — c'est la
    question des lecteurs qui n'agissent pas sur la phase (diagnostic, sérialisation).
    """
    from engine.agent_decision import read_pending_agent_decision

    pending_oath = game_state.get("pending_oath_selection")  # get allowed : None = aucune
    if pending_oath is not None and (player is None or int(pending_oath) == int(player)):
        return True
    decision = read_pending_agent_decision(game_state)
    if decision is None or str(require_key(decision, "type")) != "waaagh_call":
        return False
    return player is None or int(require_key(decision, "player")) == int(player)


def apply_waaagh_call_decision(game_state: Dict[str, Any], player: int, called: bool) -> None:
    """Applique le candidat choisi pour `waaagh_call`, puis enchaîne sur l'Oath si nécessaire.

    EFFACE la décision en attente elle-même : c'est le pendant exact d'`apply_oath_selection`,
    et l'oublier laisserait le moteur arrêté sur une décision déjà jouée. Le faire ICI plutôt
    que chez l'appelant donne UN seul endroit où la séquence « appliquer puis effacer » existe —
    elle a trois appelants (gym, siège IA, PvP).

    « Passer » n'est PAS un non-événement à ignorer : ne pas appeler ne consomme pas le
    « once per battle », donc `waaagh_called` reste à False et la décision se represente au tour
    suivant. C'est exactement ce qui fait du Waaagh! une décision de TEMPO.
    """
    from engine.agent_decision import clear_pending_agent_decision, read_pending_agent_decision

    pending = read_pending_agent_decision(game_state)
    if pending is None or str(require_key(pending, "type")) != "waaagh_call":
        raise RuntimeError(
            "apply_waaagh_call_decision: aucune decision 'waaagh_call' en attente — le masque "
            "n'aurait pas du ouvrir d'action CHOICE."
        )
    if int(require_key(pending, "player")) != int(player):
        raise RuntimeError(
            f"apply_waaagh_call_decision: la decision en attente appartient au joueur "
            f"{pending['player']}, pas a {player}."
        )
    clear_pending_agent_decision(game_state)
    if called:
        call_waaagh(game_state, int(player))
    # Un joueur ORKS n'est pas ADEPTUS ASTARTES : cet appel ne pose rien dans les rosters
    # actuels. Il est là parce que la règle ne l'interdit pas — une armée qui porterait les deux
    # mots-clés déclarerait les deux capacités, et l'ordre de 08.04 doit rester le même.
    if OATH_FACTION_KEYWORD in army_faction_keywords(game_state, int(player)):
        if oath_selectable_enemy_ids(game_state, int(player)):
            game_state["pending_oath_selection"] = int(player)


def apply_oath_selection(game_state: Dict[str, Any], player: int, target_unit_id: str) -> None:
    """Applique la désignation d'Oath of Moment (écrivain unique : `set_oath_target`)."""
    if game_state.get("pending_oath_selection") is None:  # get allowed : None = aucune
        raise RuntimeError(
            "apply_oath_selection: aucune designation d'Oath n'est en attente — le masque "
            "n'aurait pas du ouvrir de slot d'Oath."
        )
    if int(require_key(game_state, "pending_oath_selection")) != int(player):
        raise RuntimeError(
            f"apply_oath_selection: la designation en attente appartient au joueur "
            f"{game_state['pending_oath_selection']}, pas a {player}."
        )
    set_oath_target(game_state, int(player), str(target_unit_id))


def command_build_activation_pool(game_state: Dict[str, Any]) -> None:
    """
    Build command activation pool (empty for now, structure ready for future).
    """
    game_state["command_activation_pool"] = []


def command_phase_end(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    08.05 END OF PHASE — end command phase and transition to move phase.

    Point d'accrochage des capacités « at the end of your Command phase » (Get da Good Bitz,
    chantier 06).

    CRITICAL: Returns ONLY the dict, does NOT call movement_phase_start() directly.
    The cascade loop in w40k_core.py handles the transition automatically.
    """
    from engine.game_utils import add_console_log
    add_console_log(game_state, "COMMAND PHASE COMPLETE")

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    command_pool = require_key(game_state, "command_activation_pool")
    add_debug_file_log(game_state, f"[POOL PRE-TRANSITION] E{episode} T{turn} command command_activation_pool={command_pool}")
    
    # Return only the dict - cascade loop will call movement_phase_start()
    return {
        "phase_complete": True,
        "next_phase": "move",
        "phase_transition": True,
        "clear_blinking_gentle": True
    }


def execute_action(game_state: Dict[str, Any], unit: Optional[Dict[str, Any]], action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Execute action for command phase (structure ready for future).
    
    For now, no actions - phase auto-advances.
    Structure ready for future unit actions in command phase.
    """
    # For now, no actions - phase auto-advances
    # Structure ready for future unit actions in command phase
    return True, command_phase_end(game_state)




