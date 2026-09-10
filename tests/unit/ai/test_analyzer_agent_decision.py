"""L'analyzer rend le TAUX de déclaration 20.01 depuis les lignes DECISION de step.log.

TROU RÉPARÉ (2026-09-10) : `grep -rn "reserves_declaration|CHOICE_0|agent_decision" ai/analyzer.py
ai/analyzer_phases/` rendait 0 hit. Même une fois la ligne écrite par le moteur, personne ne la
lisait : impossible de distinguer « l'agent décline systématiquement » de « l'agent n'a jamais eu
la question », alors que chaque épisode porte désormais une décision par unité déclarable.

CE QUE CE FICHIER VERROUILLE :
  - les lignes `DECISION [<type>] CHOICE_<i>` alimentent `agent_decision_totals` (dénominateur)
    et `agent_decision_options` (numérateur), ventilés par joueur ;
  - `agent_decision_option_rate` rend `K/N` pour `reserves_declaration` / `CHOICE_0` ;
  - AUCUNE décision de ce type dans le journal → `None`, et non `0.0` : un taux sur zéro décision
    n'existe pas, et le rendre nul le ferait lire comme « jamais déclaré » ;
  - le libellé du candidat est du texte LIBRE : une ligne dont le libellé contient « WAIT » reste
    lue comme une décision (ordre des branches du parseur).
"""
from __future__ import annotations

OBJECTIVES = ";".join(f"(30,{r})" for r in range(30, 33))

_HEADER = (
    "=== STEP-BY-STEP ACTION LOG ===\n"
    "================================================================================\n\n"
    "[10:00:00] === EPISODE 1 START ===\n"
    "[10:00:00] Scenario: scenario_bot-01\n"
    "[10:00:00] Rosters: scale=1 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)\n"
    "[10:00:00] Opponent: SelfplayBot\n"
    "[10:00:00] Walls: none\n"
    f"[10:00:00] Objectives: rect b NW:{OBJECTIVES}\n"
    "[10:00:00] Board: cols=40 rows=40 inches_to_subhex=1 hex_radius=2.78 margin=1\n"
    "[10:00:00] Log grammar: 8\n"
    "[10:00:00] Run rules: engagement_zone_subhex=2 engagement_zone_vertical_inches=5.0 "
    "metric.engagement=hex metric.ranged=euclidean move.thru_ez=True move.thru_enemy=False "
    "move.thru_friendly=True cohesion.model_subhex=2 cohesion.global_subhex=9 "
    "cohesion.min_neighbors=1\n"
    "[10:00:00] Unit 1 (Intercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
    "[10:00:00] Unit 2 (Intercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
    "[10:00:00] Unit 101 (Intercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
    "[10:00:00] === ACTIONS START ===\n"
)

_END = (
    "[10:00:08] T3 OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none\n"
    "[10:00:09] EPISODE END: Winner=2, Method=objectives, Actions=0, Steps=0, "
    "Total=0, Duration=1.000s\n"
)


def _decision_line(unit_id: str, player: int, option_index: int, label: str) -> str:
    declined = " [DECLINED]" if option_index == 1 else ""
    return (
        f"[10:00:01] E1 T1 P{player} DEPLOYMENT : Unit {unit_id} "
        f"DECISION [reserves_declaration] CHOICE_{option_index} [{label}]{declined} [SUCCESS]\n"
    )


# N = 4 décisions, K = 1 déclaration effective (`CHOICE_0`) → taux attendu 1/4.
_BODY_N4_K1 = (
    _decision_line("1", 1, 0, "Place in strategic reserves")
    + _decision_line("2", 1, 1, "Deploy normally")
    + _decision_line("101", 2, 1, "Deploy normally")
    + _decision_line("102", 2, 1, "Deploy normally")
)


def _stats(tmp_path, body: str = ""):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(_HEADER + body + _END)
    return an.parse_step_log(str(log))


def test_declaration_rate_is_k_over_n(tmp_path):
    """VERROU : retirer la branche DECISION du parseur rend ce test ROUGE."""
    from ai.analyzer_core import agent_decision_option_rate

    stats = _stats(tmp_path, _BODY_N4_K1)
    rate = agent_decision_option_rate(stats, "reserves_declaration", 0)
    assert rate is not None, "4 décisions 20.01 dans le journal, aucun taux rendu"
    declared, total, ratio = rate
    assert (declared, total) == (1, 4), f"attendu 1/4, obtenu {declared}/{total}"
    assert ratio == 0.25


def test_totals_and_options_are_split_by_player(tmp_path):
    """Le dénominateur et le numérateur sont ventilés par joueur, comme tout compteur du dépôt."""
    stats = _stats(tmp_path, _BODY_N4_K1)
    assert stats["agent_decision_totals"]["reserves_declaration"] == {1: 2, 2: 2}
    assert stats["agent_decision_options"][("reserves_declaration", 0)] == {1: 1, 2: 0}
    assert stats["agent_decision_options"][("reserves_declaration", 1)] == {1: 1, 2: 2}


def test_no_decision_yields_no_rate_not_zero(tmp_path):
    """Journal SANS décision 20.01 → `None`. Rendre 0.0 se lirait « l'agent ne déclare jamais »."""
    from ai.analyzer_core import agent_decision_option_rate

    stats = _stats(tmp_path)
    assert agent_decision_option_rate(stats, "reserves_declaration", 0) is None
    assert not stats["agent_decision_totals"]


def test_every_unit_declined_gives_a_zero_rate_over_a_real_denominator(tmp_path):
    """Tout décliner rend 0/3 — un taux NUL sur un dénominateur RÉEL, pas une absence de taux.

    C'est la distinction que le journal ne savait pas faire avant ce relevé, et la seule qui
    permette de conclure quoi que ce soit sur la politique.
    """
    from ai.analyzer_core import agent_decision_option_rate

    body = (
        _decision_line("1", 1, 1, "Deploy normally")
        + _decision_line("2", 1, 1, "Deploy normally")
        + _decision_line("101", 2, 1, "Deploy normally")
    )
    stats = _stats(tmp_path, body)
    assert agent_decision_option_rate(stats, "reserves_declaration", 0) == (0, 3, 0.0)


def test_free_text_label_does_not_reroute_the_line(tmp_path):
    """Un libellé contenant « WAIT » reste lu comme une décision, pas comme une action WAIT.

    Le libellé vient du moteur et n'est contraint par rien ; la branche DECISION passe donc AVANT
    celles qui reconnaissent des verbes d'action.
    """
    stats = _stats(tmp_path, _decision_line("1", 1, 0, "WAIT for reserves"))
    assert stats["agent_decision_totals"]["reserves_declaration"] == {1: 1, 2: 0}
    assert stats["actions_by_type"]["agent_decision"] == 1
    assert stats["actions_by_type"]["wait"] == 0


def test_other_decision_types_are_counted_separately(tmp_path):
    """Le relevé est GÉNÉRIQUE : un autre type ne pollue pas le dénominateur de 20.01."""
    from ai.analyzer_core import agent_decision_option_rate

    body = _BODY_N4_K1 + (
        "[10:00:02] E1 T1 P1 FIGHT : Unit 1 DECISION [rule_choice] CHOICE_0 "
        "[Aggression Imperative] [SUCCESS]\n"
    )
    stats = _stats(tmp_path, body)
    assert agent_decision_option_rate(stats, "reserves_declaration", 0) == (1, 4, 0.25)
    assert agent_decision_option_rate(stats, "rule_choice", 0) == (1, 1, 1.0)
