"""05.01 HIT ROLLS : le verdict de touche journalisé doit être celui de la table du PDF.

Jumeau de `test_analyzer_wound_threshold`. Le moteur était seul juge de son propre affichage :
rien ne recoupait `Hit 1(3+)` suivi d'une blessure, ni `Hit 6(3+)` suivi de rien.

« 05 Attack sequence.pdf », 05.01, table normative dans son ordre :

    Unmodified 1 → FAILS ; Unmodified 6 → CRITICAL HIT ; ≥ BS/WS → HIT ; sinon FAILS.

Le verdict n'est pas écrit en toutes lettres dans `step.log` — il se LIT : le formateur n'ajoute
le segment `Wound …` que si la touche a réussi (`step_logger.py:803`). C'est cette équivalence
que le contrôle exploite, et c'est elle que le premier test verrouille : si le formateur cessait
d'être conditionnel, le contrôle deviendrait un vert vacant sans que rien ne le dise.
"""
from __future__ import annotations

import pytest

from ai.analyzer_hit import expected_hit_success, parse_hit_roll_and_target


# ── 1. La table 05.01, cas par cas, dans l'ordre du PDF ─────────────────────────────────────

@pytest.mark.parametrize(("roll", "target", "expected", "why"), [
    (1, 2, False, "unmodified 1 échoue même contre un seuil de 2+"),
    (1, 1, False, "…et même si le seuil est atteignable par tout dé"),
    (6, 6, True, "unmodified 6 touche"),
    (6, 7, True, "…et touche même contre un seuil hors d'atteinte (critique)"),
    (3, 3, True, "égal au seuil : touche"),
    (4, 3, True, "supérieur au seuil : touche"),
    (2, 3, False, "inférieur au seuil : échec"),
])
def test_la_table_0501(roll, target, expected, why):
    assert expected_hit_success(roll, target) is expected, why


def test_le_seuil_critique_vient_du_moteur_pas_dun_6_en_dur():
    """Anti-régression du vert vacant V8, qui suppose que seul un 6 est critique.

    Si le moteur abaissait un jour son seuil critique, ce contrôle doit suivre — pas contredire.
    """
    from engine.phase_handlers.attack_sequence import CRITICAL_HIT_ROLL, NATURAL_FAIL_ROLL
    import ai.analyzer_hit as ah

    assert ah.CRITICAL_HIT_ROLL is CRITICAL_HIT_ROLL
    assert ah.NATURAL_FAIL_ROLL is NATURAL_FAIL_ROLL


# ── 2. Ce que la regex accepte, et ce qu'elle laisse passer ─────────────────────────────────

def test_le_seuil_lu_est_leffectif_pas_le_base():
    """[HEAVY] 24.16 / [COVER] 13.08 affichent `base+->eff+` : c'est `eff` qui a joué."""
    assert parse_hit_roll_and_target("- Hit 4(3+->4+) [COVER] - Wound 5(4+)") == (4, 4)
    assert parse_hit_roll_and_target("- Hit 4(3+) - Wound 5(4+)") == (4, 3)


def test_une_blessure_automatique_reste_une_touche_reussie():
    """[LETHAL HITS] 24.23 : `wound_roll = None` → le journal écrit `Wound None(4+)`.

    C'est un segment `Wound` comme un autre, donc une touche RÉUSSIE. Une regex exigeant des
    chiffres après `Wound` ne le reconnaissait pas et déclarait l'attaque manquée : chaque
    touche critique d'une arme [LETHAL HITS] était comptée en faute. Aucun roster du projet ne
    porte la règle aujourd'hui — le défaut était armé, pas absent.
    """
    from ai.analyzer_hit import WOUND_SEGMENT_PRESENT_RE

    lethal = "- Hit 6(3+) - Wound None(4+) - Save 2(3+) - Dmg:1HP"
    assert WOUND_SEGMENT_PRESENT_RE.search(lethal), "la blessure automatique doit compter comme touche"
    # …et une ligne qui s'arrête après la touche reste bien un ÉCHEC.
    assert not WOUND_SEGMENT_PRESENT_RE.search("- Hit 2(3+)")


def test_lethal_hits_ne_declenche_aucune_faute_de_bout_en_bout(tmp_path):
    """Le jumeau du test ci-dessus par le VRAI chemin : sans lui, la regex seule ne prouve rien."""
    lethal = (
        f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{S} SHOT Unit 101{T} with [Heavy Bolt Pistol]"
        " - Hit 6(3+) - Wound None(4+) - Save 2(3+) - Dmg:1HP [R:+0.0] [SUCCESS]\n"
    )
    stats = _stats(tmp_path, lethal)
    assert stats["shoot_hit_result_mismatch"][1] == 0, stats["first_error_lines"]["shoot_hit_result_mismatch"][1]
    assert stats["shoot_hit_result_checked"][1] == 1, "la ligne doit bien avoir été jugée"


def test_une_ligne_sans_jet_de_touche_nest_pas_jugee():
    """[TORRENT] 24.37 et [SUSTAINED HITS] 24.36 n'ont AUCUN jet : `Hit None(None+)`.

    Le contrôle ne doit pas se prononcer — ni compter une faute, ni compter un contrôle. Ce
    n'est pas une exception codée : le journal ne présente simplement pas de dé.
    """
    assert parse_hit_roll_and_target("- Hit None(None+) [SUSTAINED HITS] - Wound 5(4+)") is None


# ── 3. Bout en bout : le contrôle est-il ATTEINT par le vrai chemin ? ────────────────────────
#
# « du code corrigé/testé mais JAMAIS APPELÉ ne corrige rien » : les deux tests ci-dessous
# passent par `parse_step_log`, donc par les handlers de tir et de mêlée.

SHOOTER = (50, 50)
TARGET = (50, 56)
S = f"({SHOOTER[0]},{SHOOTER[1]})"
T = f"({TARGET[0]},{TARGET[1]})"
OBJECTIVES = ";".join(f"(200,{r})" for r in range(150, 156))

_HEADER = f"""=== STEP-BY-STEP ACTION LOG ===
================================================================================

[10:00:00] === EPISODE 1 START ===
[10:00:00] Scenario: scenario_bot-01
[10:00:00] Rosters: scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)
[10:00:00] Opponent: SelfplayBot
[10:00:00] Walls:
[10:00:00] Objectives: rect b NW:{OBJECTIVES}
[10:00:00] Board: cols=220 rows=300 inches_to_subhex=5 hex_radius=2.78 margin=1
[10:00:00] Run rules: engagement_zone_subhex=10 metric.engagement=hex metric.ranged=euclidean move.thru_ez=True move.thru_enemy=False move.thru_friendly=True cohesion.model_subhex=10 cohesion.global_subhex=45 cohesion.min_neighbors=1
[10:00:00] Unit 1 (AssaultIntercessor) P1: Starting position {S}, HP_MAX=2 base=round/6
[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position {T}, HP_MAX=2 base=round/6
[10:00:00] === ACTIONS START ===
"""

_END = ("[10:00:08] T2 OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none\n"
        "[10:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, "
        "Total=0, Duration=1.000s\n")

_LEGAL_HIT = (
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{S} SHOT Unit 101{T} with [Heavy Bolt Pistol]"
    " - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:1HP [R:+0.0] [SUCCESS]\n"
)
_LEGAL_MISS = (
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{S} SHOT Unit 101{T} with [Heavy Bolt Pistol]"
    " - Hit 2(3+) [R:+0.0] [FAILED]\n"
)
# Un 1 non modifié qui blesse quand même : la faute que 05.01 interdit explicitement.
_ONE_THAT_WOUNDS = (
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{S} SHOT Unit 101{T} with [Heavy Bolt Pistol]"
    " - Hit 1(3+) - Wound 5(4+) - Save 2(3+) - Dmg:1HP [R:+0.0] [SUCCESS]\n"
)
# Un 6 non modifié rendu comme un échec : la faute symétrique.
_SIX_THAT_MISSES = (
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{S} SHOT Unit 101{T} with [Heavy Bolt Pistol]"
    " - Hit 6(3+) [R:+0.0] [FAILED]\n"
)


def _stats(tmp_path, body: str):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(_HEADER + body + _END)
    return an.parse_step_log(str(log))


def test_des_tirs_conformes_ne_declenchent_rien(tmp_path):
    stats = _stats(tmp_path, _LEGAL_HIT + _LEGAL_MISS)
    assert stats["shoot_hit_result_mismatch"][1] == 0
    # …et le contrôle a bien REGARDÉ les deux lignes. Sans cette seconde assertion, un contrôle
    # mort passerait ce test sans rien mesurer — c'est la définition même du vert vacant.
    assert stats["shoot_hit_result_checked"][1] == 2


def test_un_1_non_modifie_qui_blesse_est_compte(tmp_path):
    stats = _stats(tmp_path, _ONE_THAT_WOUNDS)
    assert stats["shoot_hit_result_mismatch"][1] == 1
    first = stats["first_error_lines"]["shoot_hit_result_mismatch"][1]
    assert "jet 1 vs seuil 3+ → ÉCHEC attendu" in first["detail"], first


def test_un_6_non_modifie_rendu_comme_un_echec_est_compte(tmp_path):
    stats = _stats(tmp_path, _SIX_THAT_MISSES)
    assert stats["shoot_hit_result_mismatch"][1] == 1


def test_le_jumeau_melee_est_branche(tmp_path):
    """Le tir et la mêlée doivent tomber sur le MÊME contrôle — c'est le défaut n°1 du dépôt."""
    fight = (
        f"[10:00:03] E1 T1 P1 FIGHT : Unit 1{S} FOUGHT Unit 101{T} with [Astartes Chainsword]"
        " - Hit 1(3+) - Wound 5(4+) - Save 2(3+) - Dmg:1HP [R:+0.0] [SUCCESS]\n"
    )
    stats = _stats(tmp_path, fight)
    assert stats["fight_hit_result_mismatch"][1] == 1
    assert stats["fight_hit_result_checked"][1] == 1
