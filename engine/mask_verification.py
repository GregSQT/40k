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

ACTIVATION (jamais active en production)
----------------------------------------
- variable d'environnement ``W40K_MASK_VERIFY=1`` (ou ``true`` / ``yes``), ou
- ``game_state["mask_verification"] is True``.

    W40K_MASK_VERIFY=1 python3 ai/train.py --agent ArmageddonAgent --training-config x1_debug \\
        --scenario bot --new --resolution 1

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


def mask_verification_enabled(game_state: Optional[Dict[str, Any]] = None) -> bool:
    """Le mode de verification est-il arme ? Faux par defaut, y compris si la cle est absente."""
    if game_state is not None and game_state.get("mask_verification") is True:  # get allowed
        return True
    return os.environ.get("W40K_MASK_VERIFY", "").strip().lower() in {"1", "true", "yes"}


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
    if _VERIFYING or not mask_verification_enabled(game_state):
        return

    _VERIFYING = True
    try:
        from engine.action_decoder import ActionDecoder

        scratch = copy.deepcopy(game_state)
        fresh_mask, fresh_eligible = ActionDecoder(
            scratch["config"]
        ).get_squad_action_mask_and_eligible_units(scratch)
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
