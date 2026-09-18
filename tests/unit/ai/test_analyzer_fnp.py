"""`fnp_threshold_mismatch` (ai/analyzer_save.py, PROJ.2.3.fnp, 24.12) — journal FABRIQUÉ, roster réel.

Plateau 100×100 à x1 (le socle EST son ancre : la clause positionnelle d'Unbreakable Resolve se
juge), objectif en (50,50)-(50,52). Tireur : Unit 1 (Intercessor, P1). Cibles : Unit 101 (Boyz +
PainBoy 101#2 : Dok's Toolz 5+), Unit 102 (Intercessor + Ancient 102#1 : Unbreakable Resolve 4+),
Unit 103 (Boyz sans PainBoy). Journal correct → 0 ; FNP 5+ sur 103 (aucune source) → 1 ; FNP 5+
sur 101 après la mort du PainBoy (DEAD avant l'activation) → 1 ; Unbreakable Resolve hors
objectif (l'Ancient à (80,80)) → 1 ; à portée → 0 ; seuil 6+ à la place de 5+ → 1 ; Dmg ≠ n − s →
1 ; Dmg>0 sans [FNP:] alors que le PainBoy vit → 1 ; blessures mortelles [FNP:n] sans source → 1.
"""
from __future__ import annotations

import pytest

from ai.analyzer_save import FNP_MARKER_GRAMMAR
from tests.unit.ai._fabriques import entete_step_log

_OBJECTIVES = ";".join(f"(50,{r})" for r in range(50, 53))
_UNITS = (
    "[10:00:00] Unit 1 (Intercessor) P1: Starting position (20,20), HP_MAX=2 base=round/1"
    " [MODELS: 1#0@(20,20,z0)] [MODEL_TYPES: 1#0=Intercessor]\n"
    "[10:00:00] Unit 101 (Boyz) P2: Starting position (30,20), HP_MAX=1 base=round/1"
    " [MODELS: 101#0@(30,20,z0) 101#1@(31,20,z0) 101#2@(32,20,z0)]"
    " [MODEL_TYPES: 101#0=Boyz 101#1=Boyz 101#2=PainBoy]\n"
    "[10:00:00] Unit 102 (Intercessor) P2: Starting position (80,80), HP_MAX=2 base=round/1"
    " [MODELS: 102#0@(80,80,z0) 102#1@(81,80,z0)] [MODEL_TYPES: 102#0=Intercessor 102#1=Ancient]\n"
    "[10:00:00] Unit 103 (Boyz) P2: Starting position (30,40), HP_MAX=1 base=round/1"
    " [MODELS: 103#0@(30,40,z0) 103#1@(31,40,z0)] [MODEL_TYPES: 103#0=Boyz 103#1=Boyz]\n"
)
_SETUP = (
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(20,20) DEPLOYED from (-1,-1) to (20,20)"
    " [R:+0.0] [MODELS: 1#0@(20,20,z0)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(30,20) DEPLOYED from (-1,-1) to (30,20)"
    " [R:+0.0] [MODELS: 101#0@(30,20,z0) 101#1@(31,20,z0) 101#2@(32,20,z0)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 102(80,80) DEPLOYED from (-1,-1) to (80,80)"
    " [R:+0.0] [MODELS: 102#0@(80,80,z0) 102#1@(81,80,z0)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 103(30,40) DEPLOYED from (-1,-1) to (30,40)"
    " [R:+0.0] [MODELS: 103#0@(30,40,z0) 103#1@(31,40,z0)] [SUCCESS]\n"
)
_END = ("[10:00:08] T2 OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none\n"
        "[10:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, "
        "Total=0, Duration=1.000s\n")


def _shot(target: str, pos: str, mid: str, tail: str, sec: int = 3, wound: int = 5) -> str:
    """Un tir de 1#0 sur `target`, alloué à `mid` ; `tail` = segment Save/Dmg/FNP."""
    return (
        f"[10:00:{sec:02d}] E1 T1 P1 SHOOT : Unit 1(20,20) SHOT [DESIGNATED:{target}] Unit {target}{pos} with [Bolt Rifle]"
        f" - Hit 4(3+) - Wound {wound}(4+) - → {mid} - {tail} [MODELS: 1#0@(20,20,z0)]"
        f" [SHOOTER_MODELS: 1#0] [ALLOC_MODEL: {mid}] [TARGET_DECL:1] [R:+0.0] [SUCCESS]\n"
    )


def _stats(tmp_path, body: str, units: str = _UNITS, setup: str = _SETUP,
           log_grammar: int = FNP_MARKER_GRAMMAR) -> dict:
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(entete_step_log(
        setup + body + _END, units=units, objectives=_OBJECTIVES, inches_to_subhex=1,
        board="cols=100 rows=100", hex_radius="1.0", ez_vertical_inches=None,
        rosters="scale=1 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=ork (ref)", log_grammar=log_grammar,
    ))
    return an.parse_step_log(str(log))


def _stats_x5(tmp_path, body: str) -> dict:
    """Même journal, à la résolution où tourne le jeu : le socle y déborde de son ancre et la
    métrique de portée du run est euclidienne (bord-à-bord, 01.04)."""
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(entete_step_log(
        _SETUP + body + _END, units=_UNITS, objectives=_OBJECTIVES, inches_to_subhex=5,
        board="cols=100 rows=100", hex_radius="1.0", ez_vertical_inches=None,
        rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=ork (ref)",
        log_grammar=FNP_MARKER_GRAMMAR,
    ))
    return an.parse_step_log(str(log))


def _first(stats) -> str:
    first = stats["first_error_lines"]["fnp_threshold_mismatch"]
    return str((first[1] or first[2] or {}).get("detail"))


def test_dok_s_toolz_5_plus_avec_le_painboy_vivant_est_correct(tmp_path):
    stats = _stats(tmp_path, _shot("101", "(30,20)", "101#0", "Save 2(5+ AP-1 → 6+) - Dmg:0HP [FNP:1/5+ ×1]"))
    assert stats["fnp_threshold_mismatch"] == {1: 0, 2: 0}, _first(stats)
    assert stats["rule_usage"]["PROJ.2.3.fnp"][1] == 1


def test_fnp_sur_une_escouade_sans_source_est_une_faute(tmp_path):
    stats = _stats(tmp_path, _shot("103", "(30,40)", "103#0", "Save 2(5+ AP-1 → 6+) - Dmg:0HP [FNP:1/5+ ×1]"))
    assert stats["fnp_threshold_mismatch"] == {1: 0, 2: 1}
    assert "sans aucun Feel No Pain" in _first(stats)


def test_fnp_apres_la_mort_du_painboy_avant_l_activation_est_une_faute(tmp_path):
    """19.04 : la source est morte à une activation PRÉCÉDENTE (DEAD au tour 1 phase MOVE, puis
    l'escouade bouge sans lui) — au tir suivant, Dok's Toolz ne joue plus."""
    body = (
        "[10:00:02] E1 T1 P2 MOVE : Unit 101 DEAD model=101#2 reason=combat"
        " [MODELS: 101#0@(30,20,z0) 101#1@(31,20,z0)] [R:+0.0] [SUCCESS]\n"
        "[10:00:02] E1 T1 P2 MOVE : Unit 101(30,21) MOVED from (30,20) to (30,21)"
        " [MODELS: 101#0@(30,21,z0) 101#1@(31,21,z0)] [R:+0.0] [SUCCESS]\n"
        + _shot("101", "(30,21)", "101#0", "Save 2(5+ AP-1 → 6+) - Dmg:0HP [FNP:1/5+ ×1]", sec=4)
    )
    stats = _stats(tmp_path, body)
    assert stats["fnp_threshold_mismatch"] == {1: 0, 2: 1}, _first(stats)


def test_la_source_tuee_dans_la_meme_activation_couvre_encore_l_activation(tmp_path):
    """19.04 dernière clause : le PainBoy meurt sous CETTE activation (DEAD émis AVANT les lignes
    d'attaque) — Dok's Toolz joue jusqu'à la fin des attaques du tireur."""
    body = (
        # Comme le moteur l'écrit : la ligne DEAD porte les SURVIVANTS dans `[MODELS:]`.
        "[10:00:02] E1 T1 P1 SHOOT : Unit 101 DEAD model=101#2 reason=combat"
        " [MODELS: 101#0@(30,20,z0) 101#1@(31,20,z0)] [R:+0.0] [SUCCESS]\n"
        + _shot("101", "(30,20)", "101#2", "Save 2(5+ AP-1 → 6+) - Dmg:1HP [FNP:0/5+ ×1]", sec=3)
        + _shot("101", "(30,20)", "101#0", "Save 2(5+ AP-1 → 6+) - Dmg:0HP [FNP:1/5+ ×1]", sec=4)
    )
    stats = _stats(tmp_path, body)
    assert stats["fnp_threshold_mismatch"] == {1: 0, 2: 0}, _first(stats)


def test_unbreakable_resolve_hors_objectif_est_une_faute(tmp_path):
    stats = _stats(tmp_path, _shot("102", "(80,80)", "102#1", "Save 2(3+ AP-1 → 4+) - Dmg:0HP [FNP:1/4+ ×1]"))
    assert stats["fnp_threshold_mismatch"] == {1: 0, 2: 1}
    assert "sans aucun Feel No Pain" in _first(stats)


def test_unbreakable_resolve_dans_l_aire_est_correct(tmp_path):
    body = (
        "[10:00:02] E1 T1 P2 MOVE : Unit 102(50,50) MOVED from (80,80) to (50,50)"
        " [MODELS: 102#0@(49,50,z0) 102#1@(50,51,z0)] [R:+0.0] [SUCCESS]\n"
        + _shot("102", "(50,50)", "102#1", "Save 2(3+ AP-1 → 4+) - Dmg:0HP [FNP:1/4+ ×1]")
    )
    stats = _stats(tmp_path, body)
    assert stats["fnp_threshold_mismatch"] == {1: 0, 2: 0}, _first(stats)


def test_unbreakable_resolve_ne_couvre_pas_l_intercessor_voisin(tmp_path):
    """« this model » : l'Intercessor 102#0 dans l'aire n'a pas le FNP de l'Ancient."""
    body = (
        "[10:00:02] E1 T1 P2 MOVE : Unit 102(50,50) MOVED from (80,80) to (50,50)"
        " [MODELS: 102#0@(50,50,z0) 102#1@(50,51,z0)] [R:+0.0] [SUCCESS]\n"
        + _shot("102", "(50,50)", "102#0", "Save 2(3+ AP-1 → 4+) - Dmg:0HP [FNP:1/4+ ×1]")
    )
    stats = _stats(tmp_path, body)
    assert stats["fnp_threshold_mismatch"] == {1: 0, 2: 1}, _first(stats)


def _ancient_a(col: int, row: int) -> str:
    """L'Ancient 102#1 seul en (col,row), hors de l'aire d'objectif, touché sans dégât."""
    return (
        f"[10:00:02] E1 T1 P2 MOVE : Unit 102({col},{row}) MOVED from (80,80) to ({col},{row})"
        f" [MODELS: 102#0@(1,1,z0) 102#1@({col},{row},z0)] [R:+0.0] [SUCCESS]\n"
        + _shot("102", f"({col},{row})", "102#1", "Save 2(3+ AP-1 → 4+) - Dmg:0HP [FNP:1/4+ ×1]")
    )


def test_unbreakable_resolve_juge_le_centre_a_x5_au_lieu_de_s_abstenir(tmp_path):
    """La clause « within 6" of the centre » se juge à la résolution où tourne le jeu.

    Le journal x5 porte `metric.ranged=euclidean` : l'analyzer mesure du BORD du socle (01.04)
    avec la primitive du moteur, au lieu de mesurer depuis l'ancre puis de s'abstenir. Board
    100×100 → centre (50,50) ; l'Ancient a un socle round/8 à x5 (rayon 4 subhex), et 6" = 30
    subhex. MIROIR VÉRIFIÉ : `_model_is_near_objective_or_center` bascule aux mêmes positions.

    VERROU : rétablir l'abstention x5 (`return False if ish <= 1 else None`) fait accepter le
    FNP à (50,80) — l'ambiguïté couvrait les deux réponses → rouge."""
    assert _stats_x5(tmp_path, _ancient_a(50, 79))["fnp_threshold_mismatch"] == {1: 0, 2: 0}, "29 rangées au sud"
    trop_loin = _stats_x5(tmp_path, _ancient_a(50, 80))
    assert trop_loin["fnp_threshold_mismatch"] == {1: 0, 2: 1}, "30 rangées au sud = 34,6 subhex"
    assert "sans aucun Feel No Pain" in _first(trop_loin)


def test_unbreakable_resolve_a_x5_est_anisotrope_comme_la_grille(tmp_path):
    """Même distance en cases, verdicts opposés : 34 colonnes à l'est sont dans les 6", 30
    rangées au sud n'y sont pas (√3/1,5 par rangée contre 1 par colonne). Une mesure en cases
    hex — celle que le moteur appliquait à toute résolution — les confondrait."""
    assert _stats_x5(tmp_path, _ancient_a(84, 50))["fnp_threshold_mismatch"] == {1: 0, 2: 0}, "34 colonnes à l'est"
    assert _stats_x5(tmp_path, _ancient_a(85, 50))["fnp_threshold_mismatch"] == {1: 0, 2: 1}, "35 colonnes à l'est"


def test_seuil_fnp_faux_et_compte_faux_sont_des_fautes(tmp_path):
    bad_threshold = _stats(tmp_path, _shot("101", "(30,20)", "101#0", "Save 2(5+ AP-1 → 6+) - Dmg:0HP [FNP:1/6+ ×1]"))
    assert bad_threshold["fnp_threshold_mismatch"] == {1: 0, 2: 1} and "seuil FNP 6+" in _first(bad_threshold)
    bad_count = _stats(tmp_path, _shot("101", "(30,20)", "101#0", "Save 2(5+ AP-1 → 6+) - Dmg:1HP [FNP:1/5+ ×1]"))
    assert bad_count["fnp_threshold_mismatch"] == {1: 0, 2: 1} and "tentatives" in _first(bad_count)


def test_degats_sans_jet_fnp_alors_que_le_painboy_vit_est_une_faute(tmp_path):
    stats = _stats(tmp_path, _shot("101", "(30,20)", "101#0", "Save 2(5+ AP-1 → 6+) - Dmg:1HP"))
    assert stats["fnp_threshold_mismatch"] == {1: 0, 2: 1}
    assert "sans [FNP:]" in _first(stats)


def test_blessures_mortelles_avec_fnp_sans_source_sont_une_faute(tmp_path):
    body = (
        "[10:00:03] E1 T1 P2 MOVE : Unit 103(30,40) SUFFERS 1 Mortal Wounds [DA JUMP] Trigger:1 MW:2"
        " [FROM:103] [FNP:1] [MODELS: 103#0@(30,40,z0) 103#1@(31,40,z0)] [ALLOC_MODEL: 103#0]"
        " [R:+0.0] [SUCCESS]\n"
    )
    stats = _stats(tmp_path, body)
    assert stats["fnp_threshold_mismatch"] == {1: 0, 2: 1}
    assert "blessures mortelles" in _first(stats)


# ─────────────────────────────────────────────────────────────────────────────
# Grammaire 16 : le marqueur est GARANTI sur toute ligne de dégâts, 24.10 comprise
# ─────────────────────────────────────────────────────────────────────────────

#: 24.10 « no saving throw can be made » : le moteur saute la sauvegarde, puis applique les
#: dégâts — et jette le Feel No Pain comme sur une sauvegarde ratée.
_DEVASTATING = "Save [DEVASTATING WOUNDS] - Dmg:1HP"


def test_sauvegarde_sautee_avec_marqueur_ne_compte_aucune_faute(tmp_path):
    """Ce que le producteur écrit depuis la grammaire 16 : le PainBoy vit, le dé a été jeté."""
    stats = _stats(tmp_path, _shot("101", "(30,20)", "101#0", _DEVASTATING + " [FNP:0/5+ ×1]", wound=6))
    assert stats["fnp_threshold_mismatch"] == {1: 0, 2: 0}, _first(stats)
    assert stats["rule_usage"]["PROJ.2.3.fnp"][1] == 1


def test_sauvegarde_sautee_sans_marqueur_reste_une_faute(tmp_path):
    """Le contrôle n'est PAS suspendu sur 24.10 : sans marqueur, l'application du Feel No Pain
    aux blessures dévastatrices serait invérifiable — c'est exactement ce qu'il contrôle."""
    stats = _stats(tmp_path, _shot("101", "(30,20)", "101#0", _DEVASTATING, wound=6))
    assert stats["fnp_threshold_mismatch"] == {1: 0, 2: 1}
    assert "sans [FNP:]" in _first(stats)


@pytest.mark.parametrize("tail", [_DEVASTATING, "Save 2(5+ AP-1 → 6+) - Dmg:1HP"])
def test_journal_anterieur_a_la_garantie_n_invente_aucune_faute(tmp_path, tail):
    """Le marqueur est apparu en grammaire 7 sans incrément, et la branche 24.10 l'a omis
    jusqu'à la 16 : aucune version antérieure ne le garantit, donc son absence n'y est pas
    jugeable — ni sur une sauvegarde sautée, ni sur une sauvegarde ratée."""
    stats = _stats(tmp_path, _shot("101", "(30,20)", "101#0", tail, wound=6),
                   log_grammar=FNP_MARKER_GRAMMAR - 1)
    assert stats["fnp_threshold_mismatch"] == {1: 0, 2: 0}, _first(stats)


def test_journal_anterieur_juge_toujours_ce_que_la_ligne_porte(tmp_path):
    """La garde ne couvre QUE l'absence : un `[FNP:]` sans source reste une faute à toute
    version, sa présence ne dépendant d'aucune garantie de grammaire."""
    stats = _stats(tmp_path, _shot("103", "(30,40)", "103#0", "Save 2(5+ AP-1 → 6+) - Dmg:0HP [FNP:1/5+ ×1]"),
                   log_grammar=FNP_MARKER_GRAMMAR - 1)
    assert stats["fnp_threshold_mismatch"] == {1: 0, 2: 1}
    assert "sans aucun Feel No Pain" in _first(stats)
