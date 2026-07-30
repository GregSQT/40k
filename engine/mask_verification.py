#!/usr/bin/env python3
"""Verification par RECALCUL des donnees memoisees entre le masque et l'execution.

POURQUOI
--------
Le masque d'action ne se contente pas d'annoncer les actions legales : il MEMOISE la carte
``cellule -> (destination, cout)`` que le decodage rejouera (``store_squad_move_cell_map``).
Rejouer une carte construite sur un etat anterieur, c'est deplacer une figurine vers une case
calculee pour une autre situation — une divergence masque/execution qui, dans le pire cas, ne
leve pas : le moteur execute quelque chose de coherent mais faux, et l'agent apprend sur des
transitions qui ne correspondent pas a ce qu'on lui a montre. Rien dans les logs ne le signale.

``read_squad_move_cell_map`` se protege deja en tamponnant la carte par ``(ancre, phase)``. Cette
garde est PARTIELLE par construction : elle ne voit que le deplacement du mover et le changement
de phase. Toute autre evolution de l'etat qui modifierait le pool — un ennemi qui bouge, une
figurine qui meurt, une zone d'engagement qui change — la laisse passer.

Ce module repond a la question par la MESURE plutot que par la lecture : il recalcule la carte
et la compare a la version memoisee. Toute divergence devient une erreur explicite, nommant les
cellules en cause.

ACTIVATION (jamais active en production) — DEUX NIVEAUX
--------------------------------------------------------
- ``W40K_MASK_VERIFY=1`` (ou ``true`` / ``yes`` / ``on`` / ``y``), ou
  ``game_state["mask_verification"]`` a ``True``, ``1`` ou ``"1"`` :
  controles de MEMOISATION — carte de cellules et cycle des jets d'Advance. ~113 verifications par
  episode.
- ``W40K_MASK_VERIFY=2`` (ou ``game_state["mask_verification"]`` a ``2`` / ``"2"``) : ajoute les
  controles de MASQUE TRANSMIS (``verify_supplied_mask``), ~315 verifications par episode, chacune
  avec copie profonde et recalcul complet du masque.

Les DEUX sources passent par le meme parseur strict (``_parse_level``) : desarmement explicite
(``0`` / ``false`` / ``no`` / ``off`` / ``n``), niveau, ou erreur. Aucune valeur n'est ignoree en
silence — c'est par la que se glisse un run entierement vert sans qu'aucun controle ne tourne.

    W40K_MASK_VERIFY=1 python3 ai/train.py --agent ArmageddonAgent --training-config x1_debug \\
        --scenario bot --new --resolution 1

POURQUOI DEUX NIVEAUX, et pas un seul. Mesure sur 2 episodes du banc d'empreinte : 3,8 s sans
drapeau, 18,2 s au niveau 1, 60,6 s au niveau 2. Les controles de masque transmis, ajoutes apres
coup, TRIPLAIENT le cout d'un mode deja a x4,7 — un run d'entrainement passait de 2,6 a 55 s par
episode et devenait inutilisable, alors que le niveau 1 repond a une question differente et reste
abordable. Fondre les deux dans un seul drapeau revenait a supprimer en pratique le seul mode de
diagnostic utilisable sur un run un peu long.

Compter ~50 ms par verification : c'est un mode de diagnostic, pas une option de run long.

LE CONTROLE NE DOIT PAS ALTERER CE QU'IL OBSERVE
------------------------------------------------
Recalculer le masque n'est PAS neutre : il reecrit la carte memoisee et peut tirer le jet
d'Advance. Recalculer sur l'etat vivant ecraserait donc la carte par la version fraiche —
le controle detruirait la preuve qu'il cherche, et changerait ce que le decodage executera
ensuite. Un controle qui modifie son objet est pire que pas de controle.

Le recalcul se fait donc sur une COPIE PROFONDE jetable. L'etat vivant n'est jamais touche,
donc aucune cle mutee par le masque n'a besoin d'etre restauree — et aucune ne peut etre
oubliee. La justesse ne depend pas d'une liste a tenir a jour.
"""

from __future__ import annotations

import copy
import os
from typing import Any, Dict, Optional, Tuple

CellMap = Dict[int, Tuple[Tuple[int, int], float]]

#: Anti-reentrance : le recalcul rejoue le masque, qui pourrait a son tour atteindre un point
#: de verification. Sans ce verrou, la premiere divergence partirait en recursion infinie au
#: lieu d'etre signalee.
_VERIFYING = False


#: Valeurs qui DESARMENT explicitement, distinguees d'une valeur inattendue (cf. plus bas).
#: `off` et `n` figurent ici par SYMETRIE avec `no`/`false` : sans eux, un `W40K_MASK_VERIFY=off`
#: — intention de desarmement sans la moindre ambiguite — faisait echouer au chargement `train.py`,
#: `api_server.py` et la collecte des tests. Lever n'y apporte aucune surete : rien n'est saute en
#: silence, le run ne demarre simplement pas.
_DISARMING_VALUES = {"", "0", "false", "no", "off", "n"}
#: Valeurs qui arment le niveau 1, symetriques des precedentes.
_LEVEL_ONE_VALUES = {"1", "true", "yes", "on", "y"}

#: Niveau requis par les controles de masque TRANSMIS — les plus chers (cf. en-tete du module).
SUPPLIED_MASK_LEVEL = 2


def _parse_level(raw: str) -> int:
    """Traduit la valeur brute du drapeau en niveau. Leve sur une valeur inattendue.

    Lever plutot que desarmer : un `W40K_MASK_VERIFY=ues` mal tape rendrait un run entier vert
    sans qu'aucun controle ne tourne — le faux feu vert exact que ce module existe pour empecher.
    """
    raw = raw.strip().lower()
    if raw in _DISARMING_VALUES:
        return 0
    if raw in _LEVEL_ONE_VALUES:
        return 1
    if raw.isdigit():
        return int(raw)
    raise ValueError(
        f"W40K_MASK_VERIFY={raw!r} n'est pas une valeur reconnue. Attendu : un entier "
        f"(0 desarme, 1 controles de memoisation, {SUPPLIED_MASK_LEVEL} + masques transmis) "
        f"ou l'une de {sorted(_LEVEL_ONE_VALUES | (_DISARMING_VALUES - {''}))}."
    )


# Validation AU CHARGEMENT du module : sans elle, la valeur n'etait lue que depuis le chemin
# moteur par pas de simulation, donc un `W40K_MASK_VERIFY=on` faisait echouer la premiere phase
# de mouvement d'un run (ou d'une requete API) au lieu d'echouer au lancement. Une erreur de
# drapeau doit se voir avant que quoi que ce soit ne tourne. La valeur n'est PAS memoisee ici :
# elle reste relue a chaque appel, sinon les tests ne pourraient plus l'armer dynamiquement.
_parse_level(os.environ.get("W40K_MASK_VERIFY", ""))


def mask_verification_level(game_state: Optional[Dict[str, Any]] = None) -> int:
    """Niveau arme : 0 desarme, 1 memoisation, 2 (et au-dela) + masques transmis.

    Deux sources, on garde la PLUS ELEVEE : la variable d'environnement, et
    ``game_state["mask_verification"]`` pour les appelants qui ne peuvent pas en poser une (serveur
    API, harnais embarque) — cf. ``_level_from_game_state`` pour ce que cette seconde voie accepte.
    Elle plafonnait a 1, ce qui rendait le niveau 2 structurellement inaccessible : un masque
    transmis perime y serait passe sans bruit, alors meme que l'appelant croyait avoir arme la
    verification.
    """
    level = _parse_level(os.environ.get("W40K_MASK_VERIFY", ""))
    if game_state is not None:
        level = max(level, _level_from_game_state(game_state))
    return level


def _level_from_game_state(game_state: Dict[str, Any]) -> int:
    """Niveau demande par ``game_state["mask_verification"]``, avec la MEME rigueur que le drapeau.

    Cette voie sert les appelants qui ne peuvent pas poser de variable d'environnement (serveur
    API, harnais embarque) — c'est-a-dire des valeurs qui arrivent souvent par JSON. Ignorer en
    silence tout ce qui n'est ni ``True`` ni un entier y recreait exactement le faux feu vert que
    ``_parse_level`` vient d'eliminer cote environnement : un ``"mask_verification": "2"`` rendait
    un run entierement vert avec zero verification. Les deux sources partagent donc un seul
    parseur, et une valeur inexploitable leve au lieu de desarmer.
    """
    value = game_state.get("mask_verification")  # get allowed : absente = desarme
    if value is None or value is False:
        return 0
    if value is True:  # forme historique
        return 1
    if isinstance(value, int):  # les bool sont deja traites au-dessus
        return value
    if isinstance(value, str):
        return _parse_level(value)
    raise ValueError(
        f"game_state['mask_verification'] = {value!r} ({type(value).__name__}) est inexploitable. "
        f"Attendu : un booleen, un entier, ou une chaine acceptee par W40K_MASK_VERIFY."
    )


def mask_verification_enabled(game_state: Optional[Dict[str, Any]] = None) -> bool:
    """Le niveau 1 est-il arme ? Faux par defaut, y compris si la cle est absente."""
    return mask_verification_level(game_state) >= 1


def _recompute_move_cell_map(game_state: Dict[str, Any], squad_id: str) -> Optional[CellMap]:
    """Recalcule la carte de cellules sur une COPIE de l'etat. Rend None si le masque n'en produit pas.

    Import differe : ``action_decoder`` importe ``shared_utils``, qui appelle ce module.
    """
    from engine.action_decoder import ActionDecoder
    from engine.phase_handlers.shared_utils import MOVE_CELL_MAP_CACHE_KEY

    scratch = copy.deepcopy(game_state)
    decoder = ActionDecoder(scratch["config"])
    decoder.get_squad_action_mask_and_eligible_units(scratch)
    entry = scratch.get(MOVE_CELL_MAP_CACHE_KEY, {}).get(str(squad_id))  # get allowed
    return entry["map"] if entry is not None else None


def _recompute_supplied_mask(game_state: Dict[str, Any]) -> Tuple[Any, Any]:
    """Recalcule ``(masque, pool)`` sur une COPIE PROFONDE de l'etat, pour comparaison.

    Fonction nommee et non corps inline : c'est le SEUL joint ou une doublure peut se poser pour
    tester la comparaison qui suit. Inline, un test ne pouvait atteindre cette comparaison qu'avec
    un ``game_state`` complet — et le premier essai a produit un vert vacant, l'etat minimal du
    test faisant lever le decodeur AVANT toute comparaison.

    Copie profonde pour la meme raison que ``_recompute_move_cell_map`` : le recalcul reecrit la
    carte de cellules memoisee et peut tirer le jet d'Advance. Cf. l'en-tete du module.
    """
    from engine.action_decoder import ActionDecoder

    scratch = copy.deepcopy(game_state)
    return ActionDecoder(scratch["config"]).get_squad_action_mask_and_eligible_units(scratch)


def _describe_divergence(memoised: CellMap, fresh: CellMap) -> str:
    only_memoised = sorted(set(memoised) - set(fresh))
    only_fresh = sorted(set(fresh) - set(memoised))
    changed = sorted(
        cell for cell in set(memoised) & set(fresh) if memoised[cell] != fresh[cell]
    )
    parts = []
    if only_memoised:
        parts.append(f"{len(only_memoised)} cellule(s) memoisee(s) disparue(s) du recalcul {only_memoised[:8]}")
    if only_fresh:
        parts.append(f"{len(only_fresh)} cellule(s) apparue(s) au recalcul {only_fresh[:8]}")
    if changed:
        example = changed[0]
        parts.append(
            f"{len(changed)} cellule(s) de destination/cout differents, ex. cellule {example} : "
            f"memoisee={memoised[example]} recalculee={fresh[example]}"
        )
    return " ; ".join(parts) if parts else "cartes de meme contenu (divergence non caracterisee)"


def verify_advance_rolls_cycle(game_state: Dict[str, Any]) -> None:
    """A l'ouverture d'une phase move, aucun jet d'Advance ne doit avoir survecu a la precedente.

    Ce controle n'est PAS un recalcul-comparaison, et ne peut pas l'etre : un jet est un tirage,
    pas une derivee de l'etat — le recomparer a un nouveau tirage produirait un faux positif a
    chaque appel. L'invariant verifiable ici est son CYCLE DE VIE.

    Le masque ne re-tire que si la cle est absente (``action_decoder``, phase move). Un jet qui
    survit a la phase move qui l'a tire est donc REUTILISE au tour suivant : la meme escouade
    avance de la meme valeur, en violation de la regle 09.06 (un jet par Advance) — sans qu'aucune
    erreur ne se declenche. Seuls deux chemins depilent le jet (``squad_wait`` en move, et un
    ``execute_squad_move`` reussi) : un troisieme chemin de sortie qui l'oublierait passerait
    inapercu.

    Mesure a la mise en place : 60 ouvertures de phase move sur 6 episodes, 0 survivant.
    """
    if not mask_verification_enabled(game_state):
        return
    survivors = game_state.get("_squad_advance_rolls") or {}  # get allowed
    if survivors:
        raise RuntimeError(
            f"mask_verification: jet(s) d'Advance survivant(s) a l'ouverture d'une phase move "
            f"(tour {game_state.get('turn')}, joueur {game_state.get('current_player')}) : "
            f"{dict(survivors)}. Le masque ne re-tire que si la cle est absente — ces escouades "
            f"rejoueraient le dé du tour precedent (regle 09.06 : un jet par Advance)."
        )


def verify_supplied_mask(
    game_state: Dict[str, Any],
    supplied_mask: Any,
    supplied_eligible: Any,
    source: str,
) -> None:
    """Leve si un masque TRANSMIS par un appelant ne decrit plus l'etat sur lequel il est consomme.

    POURQUOI ce controle n'est pas redondant avec les deux ci-dessus. Ils verifient une donnee
    memoisee DANS ``game_state``. Celui-ci verifie une donnee qui voyage AUTREMENT : le masque passe
    en argument (``W40KEngine.step_with_mask``, ``_build_observation``) pour eviter de le
    reconstruire a l'identique. Sa validite repose sur une affirmation de l'appelant — « rien n'a
    touche ``game_state`` entre ma construction et cet appel » — que rien ne verifiait.

    Le mode de defaillance vise : le pool eligible ou la legalite ont bouge entre les deux (un bot
    tiers qui muterait l'etat pendant sa selection, un chemin d'observation qui avance une phase).
    Le moteur executerait alors une action legale au regard d'un masque PERIME. Comme partout dans
    ce module, ca ne leve pas tout seul : c'est coherent et faux.

    Recalcul sur COPIE PROFONDE, comme ``_recompute_move_cell_map`` et pour la meme raison : le
    masque reecrit la carte de cellules memoisee et peut tirer le jet d'Advance. Recalculer sur
    l'etat vivant ferait executer au decodage la carte du CONTROLE au lieu de celle du masque —
    le controle changerait ce qu'il observe.
    """
    global _VERIFYING
    # Niveau 2 et non 1 : ce controle coute une copie profonde et un recalcul complet par appel,
    # et il tourne ~315 fois par episode (contre ~113 pour ceux de niveau 1). Cf. l'en-tete du
    # module pour les temps mesures et la raison de la separation.
    if _VERIFYING or mask_verification_level(game_state) < SUPPLIED_MASK_LEVEL:
        return

    _VERIFYING = True
    try:
        fresh_mask, fresh_eligible = _recompute_supplied_mask(game_state)
    finally:
        _VERIFYING = False

    import numpy as np

    supplied_bits = np.asarray(supplied_mask, dtype=bool)
    fresh_bits = np.asarray(fresh_mask, dtype=bool)
    if supplied_bits.shape != fresh_bits.shape or not np.array_equal(supplied_bits, fresh_bits):
        diff = (
            sorted(np.flatnonzero(supplied_bits != fresh_bits).tolist())[:8]
            if supplied_bits.shape == fresh_bits.shape
            else []
        )
        raise RuntimeError(
            f"mask_verification: masque transmis perime ({source}) — tour "
            f"{game_state.get('turn')}, phase {game_state.get('phase')}, joueur "
            f"{game_state.get('current_player')}. Slots divergents (max 8) : {diff}"
            f"{'' if diff else f' ; formes {supplied_bits.shape} vs {fresh_bits.shape}'}. "
            f"L'etat a evolue entre la construction du masque et sa consommation : l'appelant ne "
            f"peut plus affirmer que rien n'a touche game_state entre les deux."
        )

    supplied_ids = [str(u.get("id")) for u in (supplied_eligible or [])]
    fresh_ids = [str(u.get("id")) for u in (fresh_eligible or [])]
    if supplied_ids != fresh_ids:
        raise RuntimeError(
            f"mask_verification: pool eligible transmis perime ({source}) — transmis "
            f"{supplied_ids}, recalcule {fresh_ids} (tour {game_state.get('turn')}, phase "
            f"{game_state.get('phase')}). Le masque peut concorder alors que le pool a change : "
            f"c'est le pool qui designe l'unite activee et l'observateur."
        )


def verify_memoised_move_cell_map(
    game_state: Dict[str, Any], squad_id: str, memoised: CellMap
) -> None:
    """Leve si la carte memoisee ne correspond plus a ce que le masque produirait MAINTENANT.

    No-op quand le mode n'est pas arme (cas de production) : cout nul, aucun effet.
    """
    global _VERIFYING
    if _VERIFYING or not mask_verification_enabled(game_state):
        return

    _VERIFYING = True
    try:
        fresh = _recompute_move_cell_map(game_state, squad_id)
    finally:
        _VERIFYING = False

    if fresh is None:
        raise RuntimeError(
            f"mask_verification: la carte de cellules de l'escouade {squad_id} est memoisee mais "
            f"le masque recalcule n'en produit plus aucune. L'etat a evolue depuis la construction "
            f"du masque : rejouer cette carte executerait des hexes que le masque n'autorise plus."
        )
    if fresh != memoised:
        raise RuntimeError(
            f"mask_verification: divergence masque/execution sur l'escouade {squad_id} — "
            f"{_describe_divergence(memoised, fresh)}. La carte memoisee au masque ne decrit plus "
            f"l'etat courant ; le tampon (ancre, phase) ne l'a pas vue passer."
        )
