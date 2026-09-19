"""05.03 / 06.02 / 24.28 — l'analyzer juge la figurine ALLOUÉE (`[ALLOC_MODEL:]`) : un
CHARACTER n'encaisse qu'après les bodyguards de son unité, sauf override [PRECISION] légal.

Chantier « chaîne d'attaque 100 % » (2026-09-18). La clé `alloc.precision_mw_to_character` de
l'entête `Run rules:` (miroir de `game_rules.precision_mortal_wounds_to_character`, lue par le
moteur dans `shared_utils._precision_mortal_wounds_to_character`) tranche le cas
[PRECISION] + blessure MORTELLE ([DEVASTATING WOUNDS] 24.10) : `False` = cascade 06.02
(bodyguards d'abord), `True` = le CHARACTER imposé encaisse. Journal sans la clé : indécidable,
rien n'est compté.

Règles lues : 05 Attack sequence (05.03 « No CHARACTER group can be earlier in the allocation
order than a non-CHARACTER group »), 06 Other concepts (06.02 « Otherwise, if that unit contains
one or more non-CHARACTER models, you must select one of those models »), 24 Core abilities
(24.28 [PRECISION]).
"""
from __future__ import annotations

import pytest

import ai.analyzer as an
from ai.analyzer_rules import (
    RUN_RULE_PRECISION_MW_TO_CHARACTER,
    character_allocation_fault,
    line_inflicts_mortal_wound,
)
from tests.unit.ai._fabriques import EPISODE_TAIL, entete_step_log

S = "(50,50)"
T = "(80,50)"

# Cible P2 : deux Intercessors (bodyguards) + un Ancient rattaché (CHARACTER, rôle support).
_UNITS = (
    f"[10:00:00] Unit 1 (Intercessor) P1: Starting position {S}, HP_MAX=2 base=round/6"
    f" [MODELS: 1#0@(50,50)] [MODEL_TYPES: 1#0=Intercessor]\n"
    f"[10:00:00] Unit 102 (Intercessor) P2: Starting position {T}, HP_MAX=2 base=round/6"
    f" [MODELS: 102#0@(80,50) 102#1@(80,51) 102#2@(80,52)]"
    f" [MODEL_TYPES: 102#0=Intercessor 102#1=Intercessor 102#2=Ancient]\n"
)


def _shot(alloc: str, *, save: str = "Save 2(3+)", tags: str = "") -> str:
    """Une ligne SHOT de l'unité 1 sur l'unité 102, allouée à `alloc`."""
    return (
        f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{S} SHOT{tags} [DESIGNATED:102] Unit 102{T} with [Bolt Rifle]"
        f" - Hit 4(3+) - Wound 5(4+) - {save} - Dmg:1HP [R:+0.0] [MODELS: 1#0@(50,50)]"
        f" [ALLOC_MODEL: {alloc}] [SUCCESS]\n"
    )


def _fought(alloc: str, *, save: str = "Save 2(3+)", tags: str = "") -> str:
    return (
        f"[10:00:02] E1 T1 P1 FIGHT : Unit 1{S} FOUGHT{tags} Unit 102{T} with [Bolt Pistol]"
        f" - Hit 4(3+) - Wound 5(4+) - {save} - Dmg:1HP [R:+0.0] [MODELS: 1#0@(50,50)]"
        f" [ALLOC_MODEL: {alloc}] [SUCCESS]\n"
    )


def _command_p2() -> str:
    """Première ligne du tour de P2 : la phase change, la phase FIGHT qui suivra est une NOUVELLE
    entrée en combat (`fight_phase_seq_id`), donc une autre activation pour l'unité 1."""
    return f"[10:00:03] E1 T1 P2 COMMAND : Unit 102{T} WAITED [SUCCESS]\n"


def _stats(tmp_path, body: str, *, precision_mw: str | None = "False") -> dict:
    extra = {} if precision_mw is None else {RUN_RULE_PRECISION_MW_TO_CHARACTER: precision_mw}
    log = tmp_path / "step.log"
    log.write_text(
        entete_step_log(
            body + EPISODE_TAIL, units=_UNITS, ez_vertical_inches=None, extra_rules=extra,
            rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)",
        )
    )
    return an.parse_step_log(str(log))


def _errors(stats: dict, bucket: str) -> int:
    return stats["alloc_character_over_bodyguard"][bucket][1]


# ─── fonction pure ───────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "desc, is_char, bodyguard, mortal, key, expected",
    [
        # 05.03 : CHARACTER alloué avant ses bodyguards, sans [PRECISION] → faute.
        ("SHOT", True, True, False, False, "05.03"),
        # 06.02 : blessure mortelle sur le CHARACTER avant ses bodyguards → faute.
        ("SHOT", True, True, True, False, "06.02"),
        # 24.28 : [PRECISION] impose le CHARACTER sur une blessure normale → droit.
        ("SHOT [PRECISION]", True, True, False, False, None),
        # [PRECISION] + mortelle, clé False → cascade 06.02 exigée → faute.
        ("SHOT [PRECISION]", True, True, True, False, "06.02+24.28"),
        # [PRECISION] + mortelle, clé True → le CHARACTER imposé encaisse → droit.
        ("SHOT [PRECISION]", True, True, True, True, None),
        # Journal sans la clé : indécidable → rien.
        ("SHOT [PRECISION]", True, True, True, None, None),
        # Bodyguard alloué, ou plus aucun bodyguard vivant → rien à juger.
        ("SHOT", False, True, False, False, None),
        ("SHOT", True, False, True, False, None),
    ],
)
def test_character_allocation_fault(desc, is_char, bodyguard, mortal, key, expected):
    assert character_allocation_fault(
        desc, alloc_is_character=is_char, non_character_alive=bodyguard,
        is_mortal=mortal, precision_mw_to_character=key,
    ) == expected


def test_line_inflicts_mortal_wound():
    assert line_inflicts_mortal_wound("... - Save [DEVASTATING WOUNDS] - Dmg:2HP")
    assert line_inflicts_mortal_wound("Unit 3(1,1) SUFFERS 1 mortal wound [HAZARDOUS]")
    assert not line_inflicts_mortal_wound("... - Save 2(3+) - Dmg:1HP")


# ─── à travers le journal (analyzer_core._note_character_allocation_in_lot → _flush) ────────

def test_bodyguard_alloue_en_premier_aucune_erreur(tmp_path):
    """Ordre légal : les deux Intercessors tombent, puis l'Ancient encaisse."""
    body = (
        _shot("102#0") + _shot("102#0")   # 102#0 : 2 PV → mort
        + _shot("102#1") + _shot("102#1")  # 102#1 : mort
        + _shot("102#2")                    # plus aucun bodyguard : l'Ancient encaisse
    )
    stats = _stats(tmp_path, body)
    assert _errors(stats, "shooting") == 0
    # Quatre occasions jugées (l'unité porte un CHARACTER et des bodyguards vivants à chaque ligne
    # sauf la dernière, où seul l'Ancient reste → homogène, non jugée).
    assert stats["rule_usage"]["PROJ.1.2.alloc_character"][1] == 4


def test_character_alloue_avant_ses_bodyguards_compte_05_03(tmp_path):
    """ROUGE sans le contrôle : l'Ancient encaisse alors que 102#0 et 102#1 sont vivants."""
    stats = _stats(tmp_path, _shot("102#2"))
    assert _errors(stats, "shooting") == 1
    first = stats["first_error_lines"]["alloc_character_over_bodyguard"]["shooting"][1]
    assert first is not None and first["line"].startswith("[05.03]")
    assert an.error_totals(stats)["shooting"] >= 1


def test_precision_impose_le_character_sur_une_blessure_normale(tmp_path):
    """24.28 : la ligne porte [PRECISION] → l'allocation sur l'Ancient est un droit."""
    stats = _stats(tmp_path, _shot("102#2", tags=" [PRECISION]"))
    assert _errors(stats, "shooting") == 0
    assert stats["rule_usage"]["PROJ.1.2.alloc_character"][1] == 1


def test_precision_et_blessure_mortelle_suivent_la_cle_du_run(tmp_path):
    """[DEVASTATING WOUNDS] + [PRECISION] : la clé du run tranche, pas le config du jour."""
    line = _shot("102#2", tags=" [PRECISION]", save="Save [DEVASTATING WOUNDS]")
    assert _errors(_stats(tmp_path, line, precision_mw="False"), "shooting") == 1
    assert _errors(_stats(tmp_path, line, precision_mw="True"), "shooting") == 0
    # Journal antérieur (sans la clé) : indécidable, rien n'est compté.
    assert _errors(_stats(tmp_path, line, precision_mw=None), "shooting") == 0


def test_blessure_mortelle_sans_precision_compte_06_02(tmp_path):
    stats = _stats(tmp_path, _shot("102#2", save="Save [DEVASTATING WOUNDS]"))
    assert _errors(stats, "shooting") == 1
    first = stats["first_error_lines"]["alloc_character_over_bodyguard"]["shooting"][1]
    assert first is not None and first["line"].startswith("[06.02]")


def test_melee_meme_regle_bucket_fight(tmp_path):
    """Miroir mêlée : même contrôle, compteur de la section 1.4."""
    stats = _stats(tmp_path, _fought("102#2"))
    assert _errors(stats, "fight") == 1
    assert _errors(stats, "shooting") == 0
    assert stats["rule_usage"]["PROJ.1.4.alloc_character"][1] == 1
    assert an.error_totals(stats)["fight"] >= 1


# ─── verdict PAR LOT : l'ordre des lignes est celui des jets, pas de l'allocation ──────────────

def test_ligne_du_character_avant_celles_des_bodyguards_meme_lot_aucune_erreur(tmp_path):
    """ROUGE avec un verdict ligne à ligne. Le lot tue 102#0 et 102#1 PUIS blesse l'Ancient
    (allocation légale), mais sa ligne est écrite en premier : `g["shots"]` suit l'ordre des
    jets, le pool d'allocation est trié par sauvegarde croissante (`_roll_batch`, 05.04)."""
    body = (
        _shot("102#2")                      # l'Ancient : jet écrit en premier, alloué en dernier
        + _shot("102#0") + _shot("102#0")   # 102#0 : 2 PV → mort
        + _shot("102#1") + _shot("102#1")   # 102#1 : mort
    )
    stats = _stats(tmp_path, body)
    assert _errors(stats, "shooting") == 0
    # Cinq occasions : l'unité est mixte AVANT chacune des cinq lignes.
    assert stats["rule_usage"]["PROJ.1.2.alloc_character"][1] == 5


def test_melee_ligne_du_character_avant_celles_des_bodyguards_aucune_erreur(tmp_path):
    body = (
        _fought("102#2")
        + _fought("102#0") + _fought("102#0")
        + _fought("102#1") + _fought("102#1")
    )
    stats = _stats(tmp_path, body)
    assert _errors(stats, "fight") == 0
    assert stats["rule_usage"]["PROJ.1.4.alloc_character"][1] == 5


def test_bodyguard_survivant_en_fin_de_lot_reste_une_faute(tmp_path):
    """Un seul bodyguard tombe, l'autre survit au lot : l'Ancient n'avait pas le droit
    d'encaisser, quel que soit le rang de sa ligne."""
    body = _shot("102#0") + _shot("102#2") + _shot("102#0")
    stats = _stats(tmp_path, body)
    assert _errors(stats, "shooting") == 1
    first = stats["first_error_lines"]["alloc_character_over_bodyguard"]["shooting"][1]
    assert first is not None and "[ALLOC_MODEL: 102#2]" in first["line"]


def test_un_autre_lot_de_la_meme_activation_ne_blanchit_pas_le_precedent(tmp_path):
    """Lot 1 (Bolt Rifle) : l'Ancient encaisse alors que les deux bodyguards sont intacts →
    faute. Lot 2 (Plasma Pistol, autre clé) tue ensuite les bodyguards : le verdict du lot 1 se
    rend sur l'état de FIN DU LOT 1, pas de fin d'activation."""
    plasma = _shot("102#0").replace("[Bolt Rifle]", "[Plasma Pistol]")
    plasma1 = _shot("102#1").replace("[Bolt Rifle]", "[Plasma Pistol]")
    body = _shot("102#2") + plasma + plasma + plasma1 + plasma1
    stats = _stats(tmp_path, body)
    assert _errors(stats, "shooting") == 1


def test_deux_combats_de_la_meme_paire_dans_le_meme_round_sont_deux_lots(tmp_path):
    """L'unité 1 combat l'unité 102 dans les DEUX phases FIGHT du round 1 (12.04) : même
    (épisode, tour, phase, attaquant, cible, arme, seuils), et le `P` des lignes est celui de
    l'unité, pas de la phase. Seule l'entrée en phase de combat (`fight_phase_seq_id`) sépare les
    deux activations : la faute du premier lot reste comptée même si le second tue les
    bodyguards. Le même corps SANS changement de phase est un seul lot et ne compte rien :
    `test_melee_ligne_du_character_avant_celles_des_bodyguards_aucune_erreur`."""
    body = (
        _fought("102#2")                                        # lot 1 : faute
        + _command_p2()                                         # tour de P2 → nouvelle phase FIGHT
        + _fought("102#0") + _fought("102#0")                   # lot 2 : tue les bodyguards
        + _fought("102#1") + _fought("102#1")
    )
    stats = _stats(tmp_path, body)
    assert _errors(stats, "fight") == 1


# ─── DEAD-before-SHOT/FOUGHT (lot fatal, ordre de flush moteur) ─────────────────────────────


def _dead_event(mid: str, phase: str = "SHOOT") -> str:
    """Ligne DEAD journalisée par le moteur avant les lignes d'attaque du lot fatal."""
    return (
        f"[10:00:01] E1 T1 P1 {phase} : Unit 102{T} DEAD model={mid} reason=combat [SUCCESS]\n"
    )


def test_dead_event_avant_shot_aucune_erreur(tmp_path):
    """DEAD-before-SHOT (lot fatal) : unité anéantie par ses DEAD avant les lignes SHOT → 0 faute.

    Mesuré 2026-09-18 : 22/22 erreurs alloc_character_over_bodyguard étaient ce cas.
    Remettre la garde return-sans-pop dans _apply_damage_and_handle_death rend ce test ROUGE.
    """
    dead_prefix = _dead_event("102#0") + _dead_event("102#1") + _dead_event("102#2")
    body = (
        dead_prefix
        + _shot("102#0") + _shot("102#0")
        + _shot("102#1") + _shot("102#1")
        + _shot("102#2")
    )
    stats = _stats(tmp_path, body)
    assert _errors(stats, "shooting") == 0


def test_dead_event_avant_fought_aucune_erreur(tmp_path):
    """Jumeau mêlée : DEAD-before-FOUGHT → 0 faute."""
    dead_prefix = (
        _dead_event("102#0", "FIGHT") + _dead_event("102#1", "FIGHT") + _dead_event("102#2", "FIGHT")
    )
    body = (
        dead_prefix
        + _fought("102#0") + _fought("102#0")
        + _fought("102#1") + _fought("102#1")
        + _fought("102#2")
    )
    stats = _stats(tmp_path, body)
    assert _errors(stats, "fight") == 0
