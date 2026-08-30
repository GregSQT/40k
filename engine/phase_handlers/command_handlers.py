#!/usr/bin/env python3
"""
command_handlers.py - Command Phase Implementation
Pure stateless functions implementing command phase specification

The command phase handles all administrative tasks (reset marks, clear caches, etc.)
before the movement phase. In Phase 2, the agent may take zone intent free steps
(up to MAX_OBJECTIVES) before transitioning to move.
"""

from typing import Dict, List, Sequence, Tuple, Set, Optional, Any
from shared.data_validation import require_key
from engine.action_log_utils import append_action_log
from .shared_utils import _build_enemy_adjacent_hexes_all_players
from engine.game_state import (
    CORE_CP_GAIN_PER_COMMAND_PHASE, GameStateManager, gain_command_points,
    WAAAGH_FACTION_KEYWORD,
    army_faction, army_has_oath_ability, call_waaagh, expire_faction_abilities_for_player,
    set_oath_target, waaagh_is_available,
)


def command_phase_start(game_state: Dict[str, Any]) -> None:
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

    _build_enemy_adjacent_hexes_all_players(game_state)

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

    # NE REND PAS la main sur la suite : c'est `W40KEngine.start_command_phase` qui enchaîne
    # (résolution des sièges sans masque, puis `command_phase_resume`). Rendre `resume` ici
    # obligeait l'appelant à le rejouer — donc à garder un `if` pour éviter que
    # `command_phase_end` ne soit exécuté deux fois sur le chemin sans décision.
    return None


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
    from engine.game_utils import enter_phase
    enter_phase(game_state, "command")

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
    game_state["units_advanced"] = set()
    game_state["advance_rolls"] = {}
    # Suppression (Indiscriminate Detonations, chantier 06) : « That enemy unit is suppressed
    # until the start of YOUR next Command phase. » La duree appartient au joueur QUI A
    # SUPPRIME, pas a la victime : elle traverse donc le tour adverse, et se purge ici, au
    # debut de la phase de commande du suppresseur. La ranger avec les sets ci-dessus (purges
    # a chaque debut de tour, quel que soit le camp) diviserait sa duree par deux.
    _suppressor = int(require_key(game_state, "current_player"))
    _suppressed = game_state.setdefault("suppressed_squads", {})
    for _sid in [s for s, p in _suppressed.items() if int(p) == _suppressor]:
        del _suppressed[_sid]
    # 21.03 `L6` — déclarations de vol ET traces « la question a été posée », les deux ayant le
    # MÊME cycle de vie (la question vaut pour le mouvement du tour, elle se repose au tour
    # suivant). Les clés sont DÉRIVÉES de `_TAKE_TO_THE_SKIES_BY_PHASE` : les réénumérer ici
    # ferait de tout ajout de phase un oubli silencieux (une escouade plus jamais interrogée).
    from engine.phase_handlers.movement_handlers import fly_declaration_reset_state

    game_state.update(fly_declaration_reset_state())
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
    Grot Orderly (chantier 06, passe 6) : return_destroyed_models — automatique, avant toute
    décision.
    """
    current_player = int(require_key(game_state, "current_player"))

    # 1. « Until the start of your NEXT Command phase » — la borne est ici.
    #    AVANT Grot Orderly, et ce n'est pas cosmétique : cette purge efface les décisions de
    #    08.04 restées en attente d'un tour précédent (siège sans décideur, partie rechargée).
    #    Poser la décision de placement avant elle ferait LEVER `set_pending_agent_decision`
    #    sur une `waaagh_call` périmée — le défaut du 2026-08-05, finding 3.
    expire_faction_abilities_for_player(game_state, current_player)

    # Grot Orderly (chantier 06, passe 6) — « Once per battle, at the start of your Command
    # phase, D3 destroyed models … are returned to that unit. »
    # Le PLACEMENT est un choix de joueur (REVIVED) : si une décision est posée, le moteur rend
    # la main ICI, comme il le fait pour le Waaagh!. La suite de 08.04 est jouée à la reprise.
    if _apply_return_destroyed_models(game_state, current_player):
        return None

    _command_abilities_after_returns(game_state, current_player)
    return None


def _command_abilities_after_returns(game_state: Dict[str, Any], current_player: int) -> None:
    """Suite de 08.04 une fois les figurines rendues placées — Waaagh!, puis Oath.

    SCINDÉ de `command_step_command_abilities` parce que la restitution peut poser une décision
    et rendre la main : la reprise doit pouvoir enchaîner ICI sans rejouer l'extinction des
    capacités de faction, qui n'a lieu qu'une fois par phase.
    """
    # 2. Waaagh! — « once per battle, at the start of your Command phase, YOU CAN call a Waaagh! ».
    #    « You can » : c'est optionnel, d'où deux candidats. L'ordre reste CONTRACTUEL (§9.6)
    #    pour le moteur — 0 = appeler, 1 = passer —, mais ce n'est PAS lui qui les distingue POUR
    #    L'AGENT : l'index n'est écrit dans aucun scalaire d'observation. C'est `declines` qui
    #    porte la différence (cf. DECISION_OPTION_BIN_FIELDS).
    #    Troisième condition, du même ordre que « aucune unité ennemie vivante » pour l'Oath juste
    #    en dessous : un joueur qui n'a plus AUCUNE escouade sur la table n'a rien à faire crier.
    #    Le Waaagh! n'accorde ses effets qu'à ses propres unités, et le « once per battle » n'est
    #    pas consommé (`waaagh_called` reste False) — la décision se repose au tour suivant si le
    #    joueur revient sur la table.
    if (
        army_faction(game_state, current_player) == WAAAGH_FACTION_KEYWORD
        and waaagh_is_available(game_state, current_player)
        and player_has_squads_on_board(game_state, current_player)
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
                # `effect_ids` vide des DEUX côtés : les effets du Waaagh! viennent de la faction,
                # pas d'un `grantsRuleIds` de datasheet, donc ils n'appartiennent pas au registre
                # des accordables. L'agent les voit ailleurs (`my_waaagh_active`, et la 5+
                # invulnérable repliée dans l'invul de chaque unité).
                {
                    "label": "Call the Waaagh!",
                    "effect_ids": (),
                    "declines": False,
                    "payload": {"call": True},
                },
                {
                    "label": "Do not call the Waaagh!",
                    "effect_ids": (),
                    "declines": True,
                    "payload": {"call": False},
                },
            ],
        )
        # Une seule décision à la fois : le moteur rend la main maintenant. L'Oath ci-dessous ne
        # peut pas concerner le même joueur — la Faction d'Armée est UNE déclaration
        # (`army_faction`), et elle vaut ORKS ici.
        return None

    # 3. Oath of Moment — « select one unit from your opponent's army ». NON OPTIONNEL : pas de
    #    candidat « aucune cible ». S'il n'existe aucune unité ennemie vivante, il n'y a rien à
    #    désigner et la clause est sans objet (elle ne peut alors bénéficier à personne).
    arm_oath_selection(game_state, current_player)
    return None


def player_has_squads_on_board(game_state: Dict[str, Any], player: int) -> bool:
    """True si `player` a encore au moins une escouade dans `units_cache`.

    Lit le cache, et PAS `game_state["units"]` filtré par PV : c'est exactement la ressource dont
    l'observation a besoin pour décrire une décision de 08.04 quand le pool d'activation est vide.
    `waaagh_call` ne porte sur aucune unité, donc `_observer_squad_for_pending_decision`
    (w40k_core) prend la première escouade du joueur décideur comme repère égocentrique et LÈVE
    s'il n'y en a aucune — poser la décision dans cet état plante l'épisode au step suivant
    (mesuré le 2026-08-11, eval `control` sur `fixed_brawl_sm_orks`). L'Oath ne lève pas mais
    échoue de l'autre façon : l'observation tombe à ZÉRO faute d'escouade à décrire, et l'agent
    doit quand même désigner une cible. Le prédicat et le besoin de l'observateur sont donc la
    même chose, pour les deux capacités.
    """
    player_int = int(player)
    return any(
        int(require_key(entry, "player")) == player_int
        for entry in require_key(game_state, "units_cache").values()
    )


def arm_oath_selection(game_state: Dict[str, Any], player: int) -> None:
    """Pose la désignation d'Oath si `player` la doit — ÉCRIVAIN UNIQUE de l'armement.

    « If your Army Faction is ADEPTUS ASTARTES » : la Faction d'Armée DÉCLARÉE, et non la
    présence du mot-clé quelque part dans le roster. Une armée TYRANIDS qui invite un
    `WolfGuardTerminator` n'a pas d'Oath of Moment — c'est ce que ce test-ci garantit.

    « Select one unit from your opponent's army » : s'il n'existe aucune unité ennemie vivante,
    il n'y a rien à désigner et la clause est sans objet — elle ne pourrait bénéficier à personne.

    JUMEAU du Waaagh! de la même étape, et pour la même raison : la clause est tout aussi sans
    objet quand c'est le DÉSIGNANT qui n'a plus d'escouade — ses effets (relance de touche,
    +1 Wound) ne s'appliquent qu'à ses propres modèles. Mesuré le 2026-08-11 sur l'état
    correspondant : la désignation restait armée, le pool d'activation était vide, et le SEUL
    coup ouvert du masque était un `OATH_SLOT` — que l'agent devait choisir sur une observation
    ENTIÈREMENT NULLE, faute d'escouade à décrire (`_build_observation_and_mask`, dernière
    branche).
    """
    player_int = int(player)
    if not army_has_oath_ability(game_state, player_int):
        return
    if not player_has_squads_on_board(game_state, player_int):
        return
    if oath_selectable_enemy_ids(game_state, player_int):
        game_state["pending_oath_selection"] = player_int


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


#: Types de `pending_agent_decision` qui appartiennent au cycle de vie de 08.04 — c'est-à-dire
#: ceux que la phase de commandement pose, arrête, et éteint « until the start of your next
#: Command phase ».
#:
#: NOMMÉ plutôt que comparé en dur, parce que trois sites en dépendent : l'arrêt de la phase
#: (`faction_decision_is_pending`), l'extinction (`game_state.expire_faction_abilities_for_player`)
#: et la résolution des sièges sans masque (`W40KEngine._resolve_faction_decisions_for_ai_seats`).
#: Le chantier 06 ajoute des capacités « in your command phase » : avec trois égalités de chaîne,
#: un oubli est SILENCIEUX dans deux cas sur trois — la décision périmée survit et la repose
#: suivante LÈVE, ou la phase ne s'arrête pas alors qu'un choix attend.
#:
#: `rule_choice` n'en fait PAS partie : il a son propre cycle (`pending_rule_choice_queue`) et
#: peut être posé hors phase de commandement (`trigger: on_deploy`).
COMMAND_PHASE_DECISION_TYPES: frozenset = frozenset(
    {"waaagh_call", "returned_models_placement"}
)


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
    if decision is None or str(require_key(decision, "type")) not in COMMAND_PHASE_DECISION_TYPES:
        return False
    return player is None or int(require_key(decision, "player")) == int(player)


def apply_returned_models_placement_decision(
    game_state: Dict[str, Any], player: int, intent: str
) -> None:
    """Applique l'intention de placement choisie pour `returned_models_placement`.

    EFFACE la décision elle-même (`consume_pending_agent_decision`), comme les autres
    `apply_*_decision`, puis enchaîne sur la suite de 08.04 : les unités que le balayage n'avait
    pas encore traitées, et — s'il n'en reste plus — l'extinction et le Waaagh!/Oath.
    """
    from engine.agent_decision import consume_pending_agent_decision
    from engine.phase_handlers.deployment_handlers import plan_returned_models_placement

    consume_pending_agent_decision(
        game_state, decision_type="returned_models_placement", player=int(player)
    )
    pending = game_state.pop("_pending_returned_placement", None)
    if pending is None:
        raise RuntimeError(
            "returned_models_placement: pas de _pending_returned_placement — l'etat a ete "
            "efface entre la pose de la decision et sa resolution."
        )
    squad_id = str(require_key(pending, "squad_id"))
    models_cache = require_key(game_state, "models_cache")
    template = models_cache.get(str(require_key(pending, "template_mid")))
    if template is None:
        raise RuntimeError(
            f"returned_models_placement: figurine modele "
            f"{pending['template_mid']!r} disparue entre la pose de la decision et sa resolution."
        )
    cells = plan_returned_models_placement(
        game_state, squad_id, template, int(require_key(pending, "to_restore")), str(intent)
    )
    if cells:
        apply_returned_models_placement(
            game_state, squad_id, cells,
            int(require_key(pending, "d3")), int(require_key(pending, "destroyed")),
        )

    if _apply_return_destroyed_models(game_state, int(player)):
        return
    _command_abilities_after_returns(game_state, int(player))


def apply_waaagh_call_decision(game_state: Dict[str, Any], player: int, called: bool) -> None:
    """Applique le candidat choisi pour `waaagh_call`.

    N'enchaîne sur RIEN : la Faction d'Armée est désormais une déclaration UNIQUE
    (`army_faction`), donc le joueur qui vient de décider de son Waaagh! est ORKS et ne peut pas
    être ADEPTUS ASTARTES. L'appel à `arm_oath_selection` qui suivait ici couvrait une armée
    portant les deux mots-clés — un état que le modèle de données ne produit plus.

    EFFACE la décision en attente elle-même, par le préambule commun à tout `apply_*_decision`
    (`consume_pending_agent_decision` : vérifie le type et le propriétaire, puis efface) : c'est
    le pendant exact d'`apply_oath_selection`, et l'oublier laisserait le moteur arrêté sur une
    décision déjà jouée. Le faire ICI plutôt que chez l'appelant donne UN seul endroit où la
    séquence « appliquer puis effacer » existe — elle a trois appelants (gym, siège IA, PvP).

    « Passer » n'est PAS un non-événement à ignorer : ne pas appeler ne consomme pas le
    « once per battle », donc `waaagh_called` reste à False et la décision se represente au tour
    suivant. C'est exactement ce qui fait du Waaagh! une décision de TEMPO.
    """
    from engine.agent_decision import consume_pending_agent_decision

    consume_pending_agent_decision(
        game_state, decision_type="waaagh_call", player=int(player)
    )
    if called:
        call_waaagh(game_state, int(player))
        append_action_log(game_state, {
            "type": "waaagh_call",
            "unitId": f"P{int(player)}",
            "player": int(player),
            "phase": "command",
            "turn": require_key(game_state, "turn"),
        })


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
    append_action_log(game_state, {
        "type": "oath_selection",
        "unitId": f"P{int(player)}",
        "player": int(player),
        "phase": "command",
        "turn": require_key(game_state, "turn"),
        "targetId": str(target_unit_id),
    })


def command_build_activation_pool(game_state: Dict[str, Any]) -> None:
    """
    Build command activation pool (empty for now, structure ready for future).
    """
    game_state["command_activation_pool"] = []


def command_phase_end(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    08.05 END OF PHASE — end command phase and transition to move phase.

    Point d'accrochage des capacités « at the end of your Command phase » (Get da Good Bitz /
    Objective Secured : `secure_objective_on_control`, Primitive E chantier 06).

    CRITICAL: Returns ONLY the dict, does NOT call movement_phase_start() directly.
    The cascade loop in w40k_core.py handles the transition automatically.
    """
    from engine.game_utils import add_console_log
    add_console_log(game_state, "COMMAND PHASE COMPLETE")

    from engine.game_state import apply_secure_objective_on_control
    apply_secure_objective_on_control(game_state)

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


def _apply_return_destroyed_models(game_state: Dict[str, Any], current_player: int) -> bool:
    """Grot Orderly (chantier 06, passe 6) — « Once per battle, at the start of your Command
    phase, D3 destroyed models of that unit are returned. »

    Traite chaque unité vivante du joueur actif portant la règle et n'ayant pas encore utilisé
    l'effet. Le PLACEMENT des figurines rendues (25 Rules appendix, REVIVED) est un choix de
    joueur : la fonction retourne ``True`` quand elle a POSÉ une décision d'agent et interrompu
    son balayage — l'appelant doit alors rendre la main, et rappeler cette fonction une fois la
    décision jouée pour traiter les unités suivantes.
    """
    from engine.agent_decision import set_pending_agent_decision
    from engine.combat_utils import resolve_dice_value
    from engine.phase_handlers.deployment_handlers import RETURNED_PLACEMENT_INTENTS
    from engine.phase_handlers.shared_utils import (
        unit_has_rule_effect, is_unit_alive, model_is_on_board,
    )
    from engine.game_utils import add_debug_file_log

    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    squad_cache = game_state.get("squad_cache", {})
    used: set = game_state.setdefault("return_destroyed_models_used", set())

    for unit in require_key(game_state, "units"):
        if int(require_key(unit, "player")) != current_player:
            continue
        unit_id = str(require_key(unit, "id"))
        if unit_id in used:
            continue
        if not is_unit_alive(unit_id, game_state):
            continue
        if not unit_has_rule_effect(unit, "return_destroyed_models"):
            continue

        cache_entry = squad_cache.get(unit_id)
        if cache_entry is None:
            continue
        count_start = int(cache_entry.get("model_count_at_start", 0))
        count_now = int(cache_entry.get("model_count", 0))
        destroyed = count_start - count_now
        if destroyed <= 0:
            continue

        d3 = resolve_dice_value("D3", "grot_orderly_return")
        to_restore = min(d3, destroyed)

        # Template = première figurine vivante (bodyguard, pas personnage attaché).
        mid_list = squad_models.get(unit_id, [])
        template = None
        for mid in mid_list:
            m = models_cache.get(mid)
            if m is not None and model_is_on_board(m) and "attached_from" not in m:
                template = m
                break
        if template is None:
            # Repli : n'importe quel modèle vivant.
            for mid in mid_list:
                m = models_cache.get(mid)
                if m is not None and model_is_on_board(m):
                    template = m
                    break
        if template is None:
            continue  # impossible si is_unit_alive, défense en profondeur

        # REVIVED (25 Rules appendix) : les figurines rendues sont POSÉES en cohérence, sur des
        # cases légales — jamais empilées sur le template. Le placement est un choix de joueur
        # (intention), il est donc soumis à l'agent quand plusieurs intentions aboutissent à des
        # positions différentes ; sinon il n'y a rien à choisir et l'effet s'applique ici.
        plans = _returned_placement_plans(game_state, unit_id, template, to_restore)
        if not plans:
            # Aucune case légale : rien n'est rendu, et le « once per battle » n'est PAS
            # consommé — la règle exige un placement conforme, elle n'ouvre aucune pose de repli.
            add_debug_file_log(
                game_state,
                f"[GROT ORDERLY] E{game_state.get('episode_number', '?')} "
                f"T{game_state.get('turn', '?')} unit={unit_id} aucune case legale — "
                f"aucune figurine rendue"
            )
            continue

        distinct = {tuple(cells) for cells in plans.values()}
        if len(distinct) > 1:
            game_state["_pending_returned_placement"] = {
                "squad_id": unit_id,
                "template_mid": str(require_key(template, "id")),
                "to_restore": int(to_restore),
                "d3": int(d3),
                "destroyed": int(destroyed),
            }
            set_pending_agent_decision(
                game_state,
                decision_type="returned_models_placement",
                player=current_player,
                unit_id=unit_id,
                options=[
                    {
                        "label": intent,
                        "effect_ids": (),
                        "declines": False,
                        "payload": {"intent": intent},
                    }
                    for intent in RETURNED_PLACEMENT_INTENTS
                    if intent in plans
                ],
            )
            return True

        apply_returned_models_placement(
            game_state, unit_id, next(iter(distinct)), d3, destroyed
        )

    return False


def _returned_placement_plans(
    game_state: Dict[str, Any], squad_id: str, template: Dict[str, Any], to_restore: int
) -> Dict[str, Tuple[Tuple[int, int], ...]]:
    """Positions retenues par intention, pour les intentions qui aboutissent à un placement."""
    from engine.phase_handlers.deployment_handlers import (
        RETURNED_PLACEMENT_INTENTS, plan_returned_models_placement,
    )

    plans: Dict[str, Tuple[Tuple[int, int], ...]] = {}
    for intent in RETURNED_PLACEMENT_INTENTS:
        cells = plan_returned_models_placement(
            game_state, squad_id, template, to_restore, intent
        )
        if cells:
            plans[intent] = tuple(cells)
    return plans


def apply_returned_models_placement(
    game_state: Dict[str, Any], squad_id: str,
    cells: Sequence[Tuple[int, int]], d3: int, destroyed: int,
) -> None:
    """Crée les figurines rendues aux positions `cells` — ÉCRIVAIN UNIQUE de la restitution.

    `cells` vient de `plan_returned_models_placement` : positions déjà validées par empreinte,
    en cohérence, hors engagement interdit. Une par figurine rendue.
    """
    import copy

    from engine.phase_handlers.shared_utils import (
        _recompute_squad_cache, _recompute_squad_occupied_hexes, _recompute_squad_hp_total,
    )
    from engine.game_utils import add_debug_file_log

    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    units_cache = require_key(game_state, "units_cache")
    squad_id = str(squad_id)
    mid_list = squad_models.get(squad_id, [])  # get allowed
    template = None
    for mid in mid_list:
        m = models_cache.get(mid)
        if m is not None:
            template = m
            break
    if template is None:
        raise KeyError(
            f"apply_returned_models_placement: escouade {squad_id} sans figurine vivante"
        )

    counter = game_state.get("_restored_model_counter", 0)
    for col, row in cells:
        new_mid = f"{squad_id}#r{counter}"
        counter += 1
        new_model = copy.copy(template)
        new_model["id"] = new_mid
        new_model["col"] = int(col)
        new_model["row"] = int(row)
        new_model["HP_CUR"] = int(new_model["HP_MAX"])
        # Transient shooting/fight state ne se copie jamais depuis le template.
        new_model.pop("SHOOT_LEFT", None)
        new_model.pop("ATTACK_LEFT", None)
        new_model["SHOOT_LEFT"] = int(template.get("SHOOT_LEFT", 1))
        new_model["ATTACK_LEFT"] = int(template.get("ATTACK_LEFT", 1))
        models_cache[new_mid] = new_model
        mid_list.append(new_mid)

    game_state["_restored_model_counter"] = counter
    _recompute_squad_cache(game_state, squad_id)
    _recompute_squad_occupied_hexes(game_state, squad_id)
    squad_total = _recompute_squad_hp_total(game_state, squad_id)
    uc = units_cache.get(squad_id)
    if uc is not None:
        uc["HP_CUR"] = squad_total
    game_state.setdefault("return_destroyed_models_used", set()).add(squad_id)

    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    add_debug_file_log(
        game_state,
        f"[GROT ORDERLY] E{episode} T{turn} unit={squad_id} restored={len(cells)} "
        f"(D3={d3}, destroyed={destroyed}) cells={list(cells)}"
    )
    append_action_log(game_state, {
        "type": "return_destroyed_models",
        "unitId": squad_id,
        "player": int(require_key(require_key(units_cache, squad_id), "player")),
        "phase": "command",
        "turn": require_key(game_state, "turn"),
        "restored": len(cells),
    })


def execute_action(game_state: Dict[str, Any], unit: Optional[Dict[str, Any]], action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Execute action for command phase (structure ready for future).
    
    For now, no actions - phase auto-advances.
    Structure ready for future unit actions in command phase.
    """
    # For now, no actions - phase auto-advances
    # Structure ready for future unit actions in command phase
    return True, command_phase_end(game_state)




