#!/usr/bin/env python3
"""engine/agent_decision.py — MÉCANISME GÉNÉRIQUE « DÉCISION AGENT » (V11 §9.3, P2).

Un point de choix joueur que le moteur atteint pendant une activation ne peut pas être résolu
par l'action gym en cours : cette action a été émise pour tout autre chose. Jusqu'ici, le gym
tranchait donc `raw_action_int % len(options)` — une **pseudo-décision** : l'agent « choisissait »
sans voir le prompt, et le résultat variait avec une action qui n'avait rien à voir (§9.4 point 0).

Le mécanisme ci-dessous est le MIROIR EXACT du flux PvP `waiting_for_player` (règle projet « le
flux gym copie le flux PvP »), avec un consommateur différent :

1. le moteur atteint un point de choix → il **pose** `pending_agent_decision` (type + liste
   ORDONNÉE et STABLE de candidats) et rend la main, exactement comme il rendrait la main à un
   humain ;
2. au step suivant, le masque n'expose QUE `CHOICE_0..K-1` (`macro_intents.CHOICE_SLOTS`) et
   l'observation décrit le contexte + chaque candidat
   (`observation_entities.DECISION_*`, `observation_builder`) ;
3. l'agent joue `CHOICE_i` ; le moteur applique le candidat `i` et efface la décision.

⚠️ **L'ordre des candidats est CONTRACTUEL** (§9.6) : `options[i]` est décrit par le slot `i` de
l'observation ET désigné par l'action `CHOICE_i`. Un ordre instable d'un step à l'autre brouille
l'assignation de crédit PPO — c'est le producteur du prompt qui garantit la stabilité.

⚠️ **Aucune troncature.** Une décision qui présenterait plus de `MAX_DECISION_OPTIONS` candidats
LÈVE. Un top-K silencieux exclurait l'optimum sans que rien ne le signale (§9.0bis réserve 2) :
une décision à grand espace se paramètre en **intentions scorées**, pas en top-K d'un espace brut.

Les heuristiques `_ai_select_*` restent en place pour le **bot adversaire** et pour le PvE
(`pve_controller`) : ce module ne concerne que le siège piloté par la politique en gym.
"""

from typing import Any, Dict, List, Optional, Sequence

from engine.observation_entities import (
    AGENT_DECISION_TYPE_IDS,
    DECISION_GRANTABLE_EFFECT_IDS,
    MAX_DECISION_OPTIONS,
)
from shared.data_validation import require_key

#: Clé du `game_state` portant la décision en attente. UNE seule décision à la fois : le moteur
#: rend la main dès qu'il en pose une, donc une seconde ne peut pas apparaître avant que la
#: première soit résolue. Tenter d'en poser deux LÈVE (état incohérent, jamais écrasé en silence).
PENDING_DECISION_KEY = "pending_agent_decision"


def _validate_options(decision_type: str, options: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Valide la liste ORDONNÉE de candidats et la rend normalisée (copie défensive)."""
    if not isinstance(options, (list, tuple)):
        raise TypeError(
            f"pending_agent_decision: 'options' doit etre une sequence, recu {type(options).__name__}"
        )
    if len(options) < 2:
        raise ValueError(
            f"pending_agent_decision: une decision agent exige au moins 2 candidats "
            f"(recu {len(options)}) — un choix unique n'est pas une decision."
        )
    if len(options) > MAX_DECISION_OPTIONS:
        raise ValueError(
            f"pending_agent_decision: {len(options)} candidats pour {MAX_DECISION_OPTIONS} "
            f"actions CHOICE. Tronquer exclurait silencieusement l'optimum (§9.0bis reserve 2) : "
            f"parametrer cette decision en intentions scorees, ou elargir MAX_DECISION_OPTIONS "
            f"(l'action space change -> retrain --new)."
        )
    normalized: List[Dict[str, Any]] = []
    for index, option in enumerate(options):
        if not isinstance(option, dict):
            raise TypeError(
                f"pending_agent_decision: candidat {index} doit etre un dict, "
                f"recu {type(option).__name__}"
            )
        label = require_key(option, "label")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"pending_agent_decision: candidat {index} sans 'label' non vide")
        effect_ids = require_key(option, "effect_ids")
        if not isinstance(effect_ids, (list, tuple)):
            raise TypeError(
                f"pending_agent_decision: 'effect_ids' du candidat {index} doit etre une sequence"
            )
        for effect_id in effect_ids:
            # Garde resserree le 2026-08-04 : le registre du bloc candidat n'est plus le
            # vocabulaire observe ENTIER mais les seuls effets ACCORDABLES. Un effet observable
            # mais absent d'ici n'a pas de bit `grants_*` : le candidat serait decrit par un
            # vecteur nul, donc indiscernable d'un autre. C'est exactement ce que la garde large
            # laissait passer.
            if effect_id not in DECISION_GRANTABLE_EFFECT_IDS:
                raise KeyError(
                    f"pending_agent_decision: effet '{effect_id}' du candidat {index} absent de "
                    f"DECISION_GRANTABLE_EFFECT_IDS. L'agent ne pourrait pas percevoir ce que ce "
                    f"candidat lui accorde : ajouter l'effet au registre des accordables "
                    f"(obs_size change -> retrain --new) plutot que de le decrire par un zero."
                )
        # `declines` est EXIGÉ, jamais déduit de `not effect_ids` : « n'accorde aucun effet
        # observable » et « ne fait rien » sont deux choses différentes — un candidat peut très
        # bien agir par un effet hors du registre des accordables (c'est le cas des DEUX
        # candidats du Waaagh!, dont les effets sont de faction). Le déduire aurait marqué
        # `declines` sur celui qui APPELLE le Waaagh!, soit l'inverse exact du sens.
        declines = require_key(option, "declines")
        if not isinstance(declines, bool):
            raise TypeError(
                f"pending_agent_decision: 'declines' du candidat {index} doit etre un booleen, "
                f"recu {type(declines).__name__}. C'est le seul champ qui distingue un candidat "
                f"qui PASSE d'un candidat qui agit sans accorder d'effet observable."
            )
        if declines and effect_ids:
            raise ValueError(
                f"pending_agent_decision: candidat {index} declare `declines` ET accorde "
                f"{tuple(effect_ids)}. Un candidat qui passe n'accorde rien."
            )
        normalized.append(
            {
                "label": label.strip(),
                "effect_ids": tuple(str(effect_id) for effect_id in effect_ids),
                "declines": declines,
                "payload": require_key(option, "payload"),
            }
        )
    if sum(1 for option in normalized if option["declines"]) > 1:
        raise ValueError(
            f"pending_agent_decision: {sum(1 for o in normalized if o['declines'])} candidats "
            f"declarent `declines` pour la decision '{decision_type}'. Deux facons de ne rien "
            f"faire sont indiscernables pour l'agent — c'est un seul candidat."
        )
    return normalized


def set_pending_agent_decision(
    game_state: Dict[str, Any],
    *,
    decision_type: str,
    player: int,
    unit_id: str,
    options: Sequence[Dict[str, Any]],
    options_cont: Optional[List[List[float]]] = None,
) -> Dict[str, Any]:
    """Pose LA décision en attente. Retourne la décision normalisée telle que stockée.

    `options_cont` — liste PARALLÈLE à `options` de vecteurs continus par candidat
    (P3-4 `DECISION_OPTION_CONT_FIELDS`). Absent pour les types qui n'ont pas de traits
    continus (rule_choice, waaagh_call, fly_declaration).
    """
    if decision_type not in AGENT_DECISION_TYPE_IDS:
        raise KeyError(
            f"pending_agent_decision: type '{decision_type}' inconnu. "
            f"Types declares : {AGENT_DECISION_TYPE_IDS}"
        )
    existing = game_state.get(PENDING_DECISION_KEY)  # get allowed : absence = aucune decision
    if existing is not None:
        raise RuntimeError(
            f"pending_agent_decision: une decision '{require_key(existing, 'type')}' est deja en "
            f"attente. Le moteur doit rendre la main apres CHAQUE decision posee ; en empiler une "
            f"seconde ecraserait un choix que l'agent n'a pas encore joue."
        )
    decision: Dict[str, Any] = {
        "type": decision_type,
        "player": int(player),
        "unit_id": str(unit_id),
        "options": _validate_options(decision_type, options),
    }
    if options_cont is not None:
        if len(options_cont) != len(options):
            raise ValueError(
                f"set_pending_agent_decision: options_cont ({len(options_cont)} rangs) != "
                f"options ({len(options)} candidats) — les deux listes doivent avoir la même longueur"
            )
        decision["options_cont"] = [list(row) for row in options_cont]
    game_state[PENDING_DECISION_KEY] = decision
    return decision


def read_pending_agent_decision(game_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Décision en attente, ou None. Toute valeur non conforme LÈVE."""
    decision = game_state.get(PENDING_DECISION_KEY)  # get allowed : absence = aucune decision
    if decision is None:
        return None
    if not isinstance(decision, dict):
        raise TypeError(
            f"game_state['{PENDING_DECISION_KEY}'] doit etre un dict ou None, "
            f"recu {type(decision).__name__}"
        )
    options = require_key(decision, "options")
    if not isinstance(options, list) or not options:
        raise ValueError(
            f"game_state['{PENDING_DECISION_KEY}'] porte une liste de candidats vide ou invalide"
        )
    return decision


def clear_pending_agent_decision(game_state: Dict[str, Any]) -> None:
    """Efface la décision en attente. Appelé APRÈS son application, jamais pour l'annuler."""
    game_state[PENDING_DECISION_KEY] = None


def consume_pending_agent_decision(
    game_state: Dict[str, Any],
    *,
    decision_type: str,
    player: Optional[int] = None,
    unit_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Préambule COMMUN à tout `apply_*_decision` : vérifie, EFFACE, et rend la décision.

    Trois contrôles, puis l'effacement — la séquence que chaque type rejouait à la main :
      1. une décision est en attente et elle est bien du type que l'appelant applique. Sinon le
         masque n'aurait pas dû ouvrir d'action `CHOICE` : c'est une incohérence, pas un cas ;
      2. `player` / `unit_id`, quand l'appelant les fournit — une décision APPARTIENT à un siège,
         et l'appliquer au nom d'un autre écrirait l'effet sur le mauvais joueur ou la mauvaise
         escouade. Chaque type fournit ce qui l'identifie : le Waaagh! est une décision d'ARMÉE
         (`player`, aucune unité), la déclaration de vol une décision d'ESCOUADE (`unit_id`) ;
      3. l'effacement. Le faire ICI donne UN seul endroit où « appliquer puis effacer » existe :
         l'oublier laisserait le moteur arrêté sur une décision déjà jouée.

    ⚠️ Ce socle existe parce que les copies avaient DÉJÀ divergé : `waaagh_call` contrôlait le
    joueur et jamais l'unité, `fly_declaration` l'unité et jamais le joueur. Un 3e type aurait
    apporté un 3e sous-ensemble de gardes.

    ⚠️ RÈGLE D'APPEL, sans laquelle ces contrôles ne contrôlent RIEN : `player` et `unit_id`
    doivent venir d'une source INDÉPENDANTE de la décision — l'état (`current_player`), le pool
    d'activation, l'identité du siège appelant. Les relire dans la décision pour les repasser ici
    compare la décision à elle-même : le contrôle ne peut alors jamais se déclencher, tout en
    ayant l'apparence d'une garde. C'est exactement l'état dans lequel les deux appelants ont été
    trouvés (audit du 2026-08-07), et l'omettre coûte plus cher que de ne pas contrôler du tout —
    un « vert vacant » se lit comme un feu vert. Un argument qui n'a AUCUNE source indépendante
    (l'entité sur laquelle on écrit, par exemple) reste légitime : il barre les autres appelants,
    présents et futurs. Ce qui est interdit, c'est de le croire actif là où il ne l'est pas.
    """
    decision = read_pending_agent_decision(game_state)
    if decision is None or str(require_key(decision, "type")) != str(decision_type):
        raise RuntimeError(
            f"consume_pending_agent_decision: aucune decision '{decision_type}' en attente "
            f"(en attente : {None if decision is None else decision['type']!r}) — le masque "
            "n'aurait pas du ouvrir d'action CHOICE."
        )
    if player is not None and int(require_key(decision, "player")) != int(player):
        raise RuntimeError(
            f"consume_pending_agent_decision: la decision '{decision_type}' appartient au joueur "
            f"{decision['player']}, pas a {player}."
        )
    if unit_id is not None and str(require_key(decision, "unit_id")) != str(unit_id):
        raise RuntimeError(
            f"consume_pending_agent_decision: la decision '{decision_type}' porte sur l'unite "
            f"{decision['unit_id']}, pas sur {unit_id}."
        )
    clear_pending_agent_decision(game_state)
    return decision


def initialize_agent_decision_state(game_state: Dict[str, Any]) -> None:
    """Pose la clé à None si elle manque (init d'épisode). N'écrase jamais une décision vive."""
    if PENDING_DECISION_KEY not in game_state:
        game_state[PENDING_DECISION_KEY] = None
