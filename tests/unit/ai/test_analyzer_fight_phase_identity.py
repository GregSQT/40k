"""Deux contrôles qui mesuraient la mauvaise chose.

1. DOUBLE-ACTIVATION EN PHASE DE COMBAT — faux positifs. La clé de phase était
   `(tour, phase, joueur)`. Or un TOUR contient DEUX phases de combat (celle du tour de P1, celle
   du tour de P2) et les unités des deux camps agissent dans chacune : c'est la règle (12.04, les
   joueurs alternent leurs sélections). Le `joueur` d'une ligne est celui de l'unité qui agit, pas
   celui de la phase — les deux activations LÉGITIMES d'une unité tombaient donc sur la même clé.
   Mesuré sur un run de 12 épisodes : 55 unités « dupliquées », dont **zéro** vraie. Et
   `fight_phase_start` instrumenté sur 1427 phases : **jamais** appelé deux fois pour la même.
   La seule grandeur qui identifie une phase de combat est `fight_phase_seq_id`.

2. CAPACITÉS DE FACTION JAMAIS COMPTÉES — vert vacant. Waaagh! et Oath of Moment ne figurent dans
   AUCUN `UNIT_RULES` de datasheet (c'est le mot-clé de faction qui les donne), donc la table
   `rule_to_units` de la section 1.7, bâtie sur les datasheets, ne pouvait pas les voir.
   « 1.7 Special rules usage : 0 utilisations ✅ » sur un journal portant 1657 `[OATH OF MOMENT]`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import ai.analyzer as an
from tests.unit.ai._fabriques import entete_step_log

_UNITS = (
    "[10:00:00] Unit 1 (Intercessor) P1: Starting position (-1,-1), HP_MAX=2 "
    "[MODELS: 1#0@(-1,-1,z0)]\n"
    "[10:00:00] Unit 101 (Intercessor) P2: Starting position (-1,-1), HP_MAX=2 "
    "[MODELS: 101#0@(-1,-1,z0)]\n"
)
_END = "[12:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, Total=0, Duration=1.000s"
_COMMON: dict[str, Any] = dict(
    units=_UNITS,
    inches_to_subhex=1,
    board="cols=44 rows=60",
    walls="none",
    metric_ranged="hex",
    rosters="scale=500pts AGENT_PLAYER=1 AGENT=a (a.json) OPPONENT=o (o.json)",
    objectives=None,
)


def _run(tmp_path: Path, body: list) -> dict:
    path = tmp_path / "step.log"
    path.write_text(
        entete_step_log("\n".join(body) + "\n" + _END + "\n", **_COMMON),
        encoding="utf-8",
    )
    return an.parse_step_log(str(path))


def _consolidate(turn: int, player: int, uid: str) -> str:
    return (f"[12:00:0{turn}] E1 T{turn} P{player} FIGHT : Unit {uid}(5,5) CONSOLIDATED "
            f"from (5,5) to (5,5) [R:+0.0] [MODELS: {uid}#0@(5,5,z0)] [SUCCESS]")


def _move(turn: int, player: int, uid: str) -> str:
    return (f"[12:00:0{turn}] E1 T{turn} P{player} MOVE : Unit {uid}(5,5) MOVED "
            f"from (5,5) to (5,5)[R:+0.0] [MODELS: {uid}#0@(5,5,z0)] [SUCCESS]")


def test_une_unite_qui_agit_dans_les_DEUX_phases_de_combat_du_tour_nest_pas_un_doublon(tmp_path) -> None:
    """VERROU : c'est le cas LÉGITIME que l'ancienne clé comptait comme faute.

    Un tour contient deux phases de combat. Entre elles, une phase de move : c'est ce qui les
    sépare, et c'est ce que `fight_phase_seq_id` compte.
    """
    stats = _run(tmp_path, [
        _consolidate(1, 1, "1"),      # phase de combat du tour de P1
        _move(1, 2, "101"),           # tour de P2 : la phase de combat suivante est une AUTRE
        _consolidate(1, 1, "1"),      # même unité, phase différente → légitime
    ])
    assert stats["double_activation_by_phase"]["FIGHT"] == 0, stats["double_activation_by_phase"]


def test_deux_activations_dans_la_MEME_phase_restent_detectees(tmp_path) -> None:
    """Le contrôle doit rester capable de voir le vrai défaut, sinon il ne sert à rien."""
    stats = _run(tmp_path, [
        _consolidate(1, 1, "1"),
        _consolidate(1, 1, "1"),      # aucune phase intercalée → même phase
    ])
    assert stats["double_activation_by_phase"]["FIGHT"] == 1, stats["double_activation_by_phase"]


def test_les_capacites_de_faction_sont_comptees(tmp_path) -> None:
    """Elles n'ont pas d'unité porteuse : aucune ligne du tableau 1.7 ne pouvait les montrer."""
    stats = _run(tmp_path, [
        "[12:00:01] T1 EFFECTS: P1 none | P2 none",
        "[12:00:02] T1 EFFECTS: P1 oath_target=101 oath_wound=+1 | P2 waaagh=on waaagh_melee_atk=+1",
    ])
    activations = stats["faction_ability_activations"]
    assert activations["oath_of_moment"][1] == 1, activations
    assert activations["waaagh"][2] == 1, activations


def test_un_effet_qui_dure_ne_compte_QU_UNE_activation(tmp_path) -> None:
    """L'instantané se répète à chaque changement d'état : compter les lignes donnerait un nombre
    qui mesure les changements du plateau, pas les usages de la capacité."""
    stats = _run(tmp_path, [
        "[12:00:01] T1 EFFECTS: P1 none | P2 waaagh=on waaagh_melee_atk=+1",
        "[12:00:02] T1 EFFECTS: P1 oath_target=101 | P2 waaagh=on waaagh_melee_atk=+1",
        "[12:00:03] T1 EFFECTS: P1 none | P2 waaagh=on waaagh_melee_atk=+1",
    ])
    assert stats["faction_ability_activations"]["waaagh"][2] == 1


def test_une_capacite_relancee_apres_extinction_compte_une_seconde_fois(tmp_path) -> None:
    stats = _run(tmp_path, [
        "[12:00:01] T1 EFFECTS: P1 none | P2 waaagh=on waaagh_melee_atk=+1",
        "[12:00:02] T1 EFFECTS: P1 none | P2 none",
        "[12:00:03] T1 EFFECTS: P1 none | P2 waaagh=on waaagh_melee_atk=+1",
    ])
    assert stats["faction_ability_activations"]["waaagh"][2] == 2


def test_le_RESUME_1_7_compte_aussi_les_capacites_de_faction(tmp_path) -> None:
    """Corriger le tableau sans corriger le total laisse le vert vacant là où on le LIT.

    La ligne de résumé sommait les seules règles de datasheet : « 1.7 Special rules usage : 0
    utilisations ✅ » restait affiché alors que le tableau, juste au-dessus, montrait Oath of
    Moment activé des centaines de fois.
    """

    log = tmp_path / "step.log"
    log.write_text(
        entete_step_log(
            "[12:00:01] T1 EFFECTS: P1 none | P2 none\n"
            "[12:00:02] T1 EFFECTS: P1 oath_target=101 oath_wound=+1 | P2 waaagh=on waaagh_melee_atk=+1\n"
            + _END + "\n",
            **_COMMON,
        ),
        encoding="utf-8",
    )

    stats = an.parse_step_log(str(log))
    lines: list = []
    an.print_statistics(stats, output_lines=lines, emit_console=False)

    summary = [l for l in lines if "1.7 Special rules usage" in l]
    assert summary, "\n".join(lines[-40:])
    assert "0 utilisations" not in summary[0], summary[0]
    assert "2 utilisations" in summary[0], summary[0]
