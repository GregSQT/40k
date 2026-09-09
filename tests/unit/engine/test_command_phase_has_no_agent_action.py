"""Verrous du RETRAIT des intentions de zone (2026-09-09) : la phase de commandement ne rend
plus la main a l'agent, et ses quinze ids restent reserves.

CE QUI A ETE RETIRE, ET POURQUOI. La phase de commandement offrait a l'agent 5 « free steps »
par tour, chacun declarant une intention (INVADE / DEFEND / ATTACK) sur un objectif. Leur unique
consequence etait une prime de reward (`zone_intent_shaping`), DEBRANCHEE le 2026-08-11 sur
mesure : la part des declarations payees valait 0.269 contre 0.355 pour la meme politique tirant
son intent au hasard. Depuis, ces actions n'avaient plus aucun effet sur la partie — ni sur
l'etat, ni sur la recompense — et coutaient 1,6 a 5,2 steps par episode (TensorBoard
`o_intent_zone_steps`, runs P1 et x1_long du 2026-09-09), soit autant de bruit dans le gradient.

CE QUE LES REGLES EN DISENT, verifie sur les PDF et non sur les commentaires du code :
`16 Actions.pdf` decrit les ACTIONS reelles (STARTS / UNITS / USE LIMIT / COMPLETES / EFFECT,
venues des mission packs) — les intentions de zone n'en sont pas ; `08 Command phase.pdf`
enumere cinq etapes (08.01 a 08.05) que `command_handlers.command_phase_start` implemente
toutes ; ni `14 Objectives.pdf` ni `26 Primary_missions.pdf` ne demandent de declaration.

⚠️ CE QUI RESTE A FAIRE, et c'est pourquoi les ids sont RESERVES et non recycles :
`15 Stratagems.pdf` place une vraie decision joueur dans cette phase — INSANE BRAVERY 15.04,
« WHEN: Battle-shock step of your Command phase, just before you make a battle-shock roll ».
Aucun stratagemme n'est implemente et les CP n'ont donc aucun puits ; le jour ou l'un arrive,
son slot s'ouvrira sur cette plage.
"""

from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pytest

from engine import macro_intents as mi
from engine.phase_handlers import command_handlers
from engine.phase_handlers.shared_utils import SQUAD_ACTION_WAIT


def _resume_state(*, current_player: int = 1, controlled_player: int = 1) -> Dict[str, Any]:
    """Etat minimal pour `command_phase_resume` : c'est elle seule qui est mesuree ici.

    `gym_training_mode` et `controlled_player == current_player` reproduisent EXACTEMENT le
    « siege d'agent » sur lequel la fonction gardait la phase ouverte. C'est le cas qui doit
    maintenant avancer comme les autres.
    """
    return {
        "phase": "command",
        "current_player": current_player,
        "gym_training_mode": True,
        "config": {"controlled_player": controlled_player, "gym_training_mode": True},
        "units": [],
        "unit_by_id": {},
        "units_cache": {},
        "console_logs": [],
        "action_logs": [],
        "action_log_seq": 0,
        "episode_number": 1,
        "turn": 1,
        # Lu par `command_phase_end` (trace de transition), pose en production par
        # `command_build_activation_pool` — que ce montage court-circuite.
        "command_activation_pool": [],
    }


def test_the_command_phase_no_longer_holds_the_agent_on_its_own_turn(monkeypatch) -> None:
    """Sur le siege de l'AGENT, la phase de commandement se termine au lieu de rester ouverte.

    C'est le coeur du retrait. `command_phase_resume` posait
    `zone_intent_free_steps_remaining = MAX_OBJECTIVES` puis rendait `phase_complete: False`
    pour que l'agent vienne jouer ses intents — et un `wait` de plus pour en sortir. Le bot,
    lui, passait deja directement. Les deux sieges suivent desormais le meme chemin.
    """
    ended: list[bool] = []
    monkeypatch.setattr(
        command_handlers, "command_phase_end",
        lambda _gs: ended.append(True) or {"phase_complete": True, "phase": "command"},
    )

    out = command_handlers.command_phase_resume(_resume_state())

    assert ended == [True], "la phase de commandement du siege agent ne s'est pas terminee"
    assert out["phase_complete"] is True


def test_the_resume_no_longer_publishes_any_free_step_counter() -> None:
    """Le compteur de free steps ne doit pas RENAITRE dans la reprise de phase.

    Les cinq cles restent publiees par le RESET — elles appartiennent au format de save `TL05` et
    y sont laissees inertes plutot que retirees (cf. `services/game_saves._MAGIC`). C'est
    justement ce qui rend ce test necessaire : leur presence dans un game_state ne prouve plus
    rien, seul compte le fait que la REPRISE n'en repose aucune. Une reecriture ici rouvrirait le
    robinet sans qu'aucun contrat de format ne rougisse.
    """
    gs = _resume_state()
    command_handlers.command_phase_resume(gs)

    for key in (
        "zone_intent_free_steps_remaining", "zone_intents", "_zone_intent_declarations",
        "unit_zone_assignments", "_pending_zone_shaping",
    ):
        assert key not in gs, f"la cle retiree {key!r} a ete reposee par la reprise"


def test_the_command_phase_mask_opens_wait_and_nothing_else() -> None:
    """Le masque de la phase de commandement n'ouvre plus QUE `wait`.

    Verifie sur le masque REEL construit par le decodeur, pas sur une relecture de la branche :
    c'est le masque qui decide de ce que l'agent peut jouer.
    """
    from tests.unit.engine.test_action_decoder import _build_gs, _make_decoder, _unit

    decoder = _make_decoder()
    gs = _build_gs([_unit("1", 1, 5, 5), _unit("2", 2, 20, 15)], "command")

    mask, _eligible = decoder.get_squad_action_mask_and_eligible_units(gs)

    opened = np.flatnonzero(mask).tolist()
    assert opened == [SQUAD_ACTION_WAIT], (
        f"la phase de commandement ouvre {opened}, attendu le seul WAIT ({SQUAD_ACTION_WAIT})"
    )


def test_no_reserved_id_is_ever_opened_by_the_command_mask() -> None:
    """Les quinze ids reserves restent fermes — c'est ce qui rend leur conservation sans effet."""
    from tests.unit.engine.test_action_decoder import _build_gs, _make_decoder, _unit

    decoder = _make_decoder()
    gs = _build_gs([_unit("1", 1, 5, 5), _unit("2", 2, 20, 15)], "command")

    mask, _eligible = decoder.get_squad_action_mask_and_eligible_units(gs)

    for action in range(mi.BASE_ZONE_INTENT, mi.CHOICE_BASE):
        assert not mask[action], f"l'id reserve {action} est ouvert par le masque"


@pytest.mark.parametrize("phase", ["command", "move", "shoot", "fight"])
def test_a_reserved_id_cannot_be_classified_as_an_action_family(phase: str) -> None:
    """`action_family` LEVE sur la plage reservee, dans toute phase.

    Elle rendait « zone_intent » par un FOURRE-TOUT terminal, qui avalait aussi tout id d'une
    famille livree sans branche — defaut reel, trouve par ce retrait sur `SHOOT_WEAPON_SEL`
    (P3-8) et `COHERENCY` (P3-0), toutes deux comptees en intentions depuis leur livraison.
    """
    with pytest.raises(ValueError, match="RESERVEE"):
        mi.action_family(mi.BASE_ZONE_INTENT, phase)
