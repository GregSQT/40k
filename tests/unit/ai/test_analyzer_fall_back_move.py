"""09.07 FALL-BACK MOVE : le seul des six déplacements qui n'était contrôlé par rien.

Vert vacant V10 de `Documentation/Implémentation/analyzer_couverture.md`. `_handle_fled` ne
regardait que la collision d'ancre et le mur d'arrivée : ni budget, ni chemin, ni éligibilité,
ni post-condition. Une unité pouvait traverser le plateau en battant en retraite, finir encore
engagée, ou battre en retraite sans jamais avoir été engagée — le rapport affichait 0.

« 09 Movement phase.pdf », 09.07, mot pour mot :

    MAXIMUM DISTANCE: Your unit's M characteristic.
    ELIGIBLE IF: Your unit is engaged.
    EFFECT: Your unit moves as described in Moving (03).
    AFTER MOVING: ▪ Your unit must be unengaged.

Les quatre tests ci-dessous construisent chacun LA situation qu'ils observent — aucun ne dépend
d'une graine, d'un ordre d'exécution ou d'une config absente. Le premier est la PRÉMISSE
géométrique : sans lui, « 0 erreur » ne prouverait que la mort du contrôle.

Le volet « WHILE MOVING ▪ Desperate Escape » n'est PAS testé, et c'est délibéré : le mode de
fall-back n'est pas journalisé (§7 L11), donc l'analyzer laisse les figurines ennemies
traversables. Le jour où `[MOVE_TYPE:fall_back]` portera son mode, ce fichier devra gagner un
cinquième test — et `force_thru_enemy` disparaître.
"""
from __future__ import annotations

import re

from tests.unit.ai._fabriques import entete_step_log

# Échelle x5 : M=6" d'un AssaultIntercessor vaut 30 subhex, la zone d'engagement 10 subhex.
# Toutes les distances ci-dessous sont choisies pour tomber sans ambiguïté d'un côté ou de
# l'autre de ces deux seuils — jamais dessus.
MOVE_SUBHEX = 30          # M=6" × inches_to_subhex=5
ENGAGEMENT_SUBHEX = 10    # 2" × 5

START = (50, 50)          # unité qui bat en retraite
ENEMY = (50, 58)          # 8 d'ancre => ENGAGÉE (et pourtant jamais « adjacente »)
LEGAL_DEST = (50, 80)     # 30 du départ (= budget), 22 de l'ennemi => désengagée
OVER_DEST = (50, 85)      # 35 du départ => AU-DELÀ du budget
ENGAGED_DEST = (50, 54)   # 4 du départ, 4 de l'ennemi => finit ENCORE engagée

LONE_START = (150, 150)   # unité sans aucun ennemi à portée d'engagement
LONE_DEST = (150, 160)    # 10 du départ, très en deçà du budget

OBJECTIVES = ";".join(f"(200,{r})" for r in range(150, 156))


def _xy(p):
    return f"({p[0]},{p[1]})"


_SETUP = (
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{_xy(START)} DEPLOYED from (-1,-1) to {_xy(START)} [R:+0.0] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 2{_xy(LONE_START)} DEPLOYED from (-1,-1) to {_xy(LONE_START)} [R:+0.0] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101{_xy(ENEMY)} DEPLOYED from (-1,-1) to {_xy(ENEMY)} [R:+0.0] [SUCCESS]\n"
)
_UNITS = (
    "[10:00:00] Unit 1 (AssaultIntercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
    "[10:00:00] Unit 2 (AssaultIntercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
    "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
)


# Clôture minimale exigée par `parse_step_log` : sans l'instantané d'objectifs et sans
# `AGENT_PLAYER=`, il LÈVE plutôt que de supposer (VP recalculés, siège de l'agent deviné) —
# deux gardes délibérées, pas des obstacles de test.
_END = ("[10:00:08] T2 OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none\n"
        "[10:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, "
        "Total=0, Duration=1.000s\n")


def _fled(unit_id: str, frm, to) -> str:
    return (
        f"[10:00:02] E1 T2 P1 MOVE : Unit {unit_id}{_xy(frm)} FLED from {_xy(frm)} to {_xy(to)}"
        " [R:+0.0] [SUCCESS]\n"
    )


def _stats(tmp_path, body: str):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(entete_step_log(
        _SETUP + body,
        units=_UNITS,
        rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)",
        objectives=OBJECTIVES,
        ez_vertical_inches=None,
    ))
    return an.parse_step_log(str(log))


def test_geometry_premise():
    """Sans cette prémisse, les quatre tests suivants ne prouveraient rien.

    Chaque distance doit tomber du bon côté des DEUX seuils du run, et aucune ne doit tomber
    dessus : un test posé sur la frontière change de verdict au premier arrondi.
    """
    from ai.analyzer import calculate_hex_distance as d

    assert d(*START, *ENEMY) == 8 <= ENGAGEMENT_SUBHEX, "le départ doit être engagé"
    assert d(*START, *LEGAL_DEST) == MOVE_SUBHEX, "la destination légale doit épuiser le budget"
    assert d(*LEGAL_DEST, *ENEMY) == 22 > ENGAGEMENT_SUBHEX, "elle doit désengager"
    assert d(*START, *OVER_DEST) == 35 > MOVE_SUBHEX, "sinon le dépassement n'en est pas un"
    assert d(*ENGAGED_DEST, *ENEMY) == 4 <= ENGAGEMENT_SUBHEX, "elle doit rester engagée"
    assert d(*START, *ENGAGED_DEST) == 4 <= MOVE_SUBHEX, "sans dépasser le budget par ailleurs"
    assert d(*LONE_START, *ENEMY) > ENGAGEMENT_SUBHEX, "l'unité isolée ne doit voir personne"
    assert d(*LONE_START, *LONE_DEST) <= MOVE_SUBHEX


def test_a_legal_fall_back_raises_nothing(tmp_path):
    """Engagée au départ, dans le budget, désengagée à l'arrivée : les trois compteurs à 0."""
    stats = _stats(tmp_path, _fled("1", START, LEGAL_DEST))
    assert stats["move_distance_over_limit"]["flee"][1] == 0
    assert stats["flee_from_unengaged"][1] == 0
    assert stats["flee_still_engaged"][1] == 0


def test_fall_back_beyond_M_is_counted(tmp_path):
    """MAXIMUM DISTANCE : 35 subhex parcourus pour un budget de 30."""
    stats = _stats(tmp_path, _fled("1", START, OVER_DEST))
    assert stats["move_distance_over_limit"]["flee"][1] == 1
    # La faute est UNE faute : le dépassement ne doit pas déclencher aussi les deux autres.
    assert stats["flee_from_unengaged"][1] == 0
    assert stats["flee_still_engaged"][1] == 0


def test_fall_back_while_unengaged_is_counted(tmp_path):
    """ELIGIBLE IF: Your unit is engaged — l'unité 2 n'a aucun ennemi à portée."""
    stats = _stats(tmp_path, _fled("2", LONE_START, LONE_DEST))
    assert stats["flee_from_unengaged"][1] == 1
    assert stats["move_distance_over_limit"]["flee"][1] == 0
    assert stats["flee_still_engaged"][1] == 0


def test_fall_back_that_stays_engaged_is_counted(tmp_path):
    """AFTER MOVING: Your unit must be unengaged — ici elle recule de 4 et reste dans l'EZ."""
    stats = _stats(tmp_path, _fled("1", START, ENGAGED_DEST))
    assert stats["flee_still_engaged"][1] == 1
    assert stats["flee_from_unengaged"][1] == 0
    assert stats["move_distance_over_limit"]["flee"][1] == 0


def test_stale_permodel_positions_do_not_trigger_false_positive(tmp_path):
    """Faux positif 09.07 : la position périmée du modèle survivant masque l'engagement.

    Scénario réaliste : une escouade de 2 figurines dont la frontale (#1) est au contact de
    l'ennemi et l'arrière (#0) en est à 11 subhex (hors EZ). L'ennemi tue #1. L'escouade bat
    en retraite depuis son ancre (START = (50,50), à 8 subhex de l'ennemi = dans l'EZ).
    surviving_start_models({'0': REAR, '1': NEAR}, {'0': dest}) = {'0': REAR}.
    Le check per-figurine mesure REAR (11 > 10) → « pas engagée » → faux positif.
    Le fallback sur l'ancre (8 ≤ 10) doit corriger.
    """
    # REAR : hors EZ de l'ennemi (11 subhex), dans le budget fled depuis LEGAL_DEST (11 subhex).
    REAR = (50, 69)  # distance ENEMY=11>10, distance LEGAL_DEST=11<=30

    # Première action : logue les deux figurines (REAR + START = frontale).
    prev_models_line = (
        f"[10:00:02] E1 T1 P1 MOVE : Unit 1{_xy(START)} MOVED from {_xy(START)} to {_xy(START)}"
        f" [R:+0.0] [MODELS: 1#0@({REAR[0]},{REAR[1]}) 1#1@({START[0]},{START[1]})] [SUCCESS]\n"
    )
    # Fall-back : seul #0 survit (#1 tué par tirs adverses). Ancre reste START.
    # La destination de #0 est à 11 subhex de REAR → dans le budget.
    fled_line = (
        f"[10:00:03] E1 T2 P1 MOVE : Unit 1{_xy(START)} FLED from {_xy(START)} to {_xy(LEGAL_DEST)}"
        f" [R:+0.0] [MODELS: 1#0@({LEGAL_DEST[0]},{LEGAL_DEST[1]})] [SUCCESS]\n"
    )
    stats = _stats(tmp_path, prev_models_line + fled_line)
    # surviving_start_models({'0': REAR, '1': START}, {'0': LEGAL_DEST}) = {'0': REAR}
    # Per-model : REAR à 11 > 10 de ENEMY → sans fix : flee_from_unengaged = 1
    # Avec fix (fallback ancre START à 8 ≤ 10 de ENEMY) : flee_from_unengaged = 0
    assert stats["flee_from_unengaged"][1] == 0, (
        "L'ancre START est dans la zone d'engagement — le fallback doit supprimer le faux positif"
    )
    assert stats["flee_still_engaged"][1] == 0
    assert stats["move_distance_over_limit"]["flee"][1] == 0


def test_the_violations_reach_the_MOVE_error_total_of_the_summary(tmp_path):
    """Un compteur qui n'entre dans aucun total est un compteur que personne ne lira.

    C'est le mode d'échec de `damage_exceeds_hp` (V1) pris par l'autre bout : affiché, sommé,
    jamais incrémenté. Ici l'inverse — incrémenté mais absent du total — serait tout aussi
    silencieux. Le test lit donc la ligne RENDUE du SUMMARY, pas les compteurs : c'est elle que
    l'utilisateur regarde, et c'est elle qui doit bouger.
    """
    import ai.analyzer as an

    body = (
        _fled("1", START, OVER_DEST)        # budget
        + _fled("2", LONE_START, LONE_DEST)  # éligibilité
    )
    log = tmp_path / "step.log"
    log.write_text(entete_step_log(
        _SETUP + body + _END,
        units=_UNITS,
        rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)",
        objectives=OBJECTIVES,
        ez_vertical_inches=None,
    ))
    stats = an.parse_step_log(str(log))
    assert stats["move_distance_over_limit"]["flee"][1] == 1
    assert stats["flee_from_unengaged"][1] == 1

    rendered: list = []
    an.print_statistics(stats, output_lines=rendered, emit_console=False)
    summary = [l for l in rendered if "1.1 Erreurs en phase de move" in l]
    assert len(summary) == 1, rendered[-40:]
    # 2 fautes de fall-back et rien d'autre : le total DOIT valoir exactement 2. Un `> 0` aurait
    # laissé passer un total qui ne compte qu'une des deux.
    # La ligne peut porter un suffixe ⚠️ (règles jamais exercées) — on extrait le chiffre.
    m = re.search(r": (\d+)", summary[0])
    assert m and int(m.group(1)) == 2, summary[0]
