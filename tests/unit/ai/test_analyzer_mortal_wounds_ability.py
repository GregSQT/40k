"""Ligne `SUFFERS N Mortal Wounds` d'une CAPACITÉ (06.02) — lecteur de l'analyzer.

Hold Still and Say Aargh et Exhortation de Rage infligent des blessures mortelles. Leur ligne
n'existait pas : leurs types d'action_log n'étaient dans aucune entrée de `_STEP_LOG_TYPE_MAP`,
donc le journal ne gardait des blessures qu'un event `dead` sans cause, et l'analyzer suivait des
points de vie qui ne correspondaient plus à l'état du moteur.

Ce que ce fichier verrouille :
- les points de vie de la VICTIME sont retirés (la ligne nomme la victime, pas l'attaquant) ;
- l'usage est compté §1.7 sur l'unité SOURCE, désignée par `[FROM:<unité>]`, et son camp ;
- ces blessures n'entrent NI dans `hazardous_mortal_wounds` (24.15) NI dans son contrôle
  d'armurerie — c'est tout l'intérêt d'un tag distinct ;
- une ligne sans `[FROM:]` est une erreur de format, pas une ligne silencieusement ignorée.
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log
from tests.unit.ai._fabriques import analyzer_config as fab_config

_OBJECTIVES = ";".join(f"(30,{r})" for r in range(30, 33))


class _Registry:
    units = {
        "PainBoy": {"HP_MAX": 3, "MOVE": 6, "MODEL_HEIGHT": 1.0, "UNIT_RULES": []},
        "Grunt": {"HP_MAX": 5, "MOVE": 6, "MODEL_HEIGHT": 1.0, "UNIT_RULES": []},
    }


# Unité 1 (P1) = PainBoy attaquant ; unité 101 (P2) = victime.
_UNITS = (
    "[10:00:00] Unit 1 (PainBoy) P1: Starting position (20,20), HP_MAX=3 base=round/1\n"
    "[10:00:00] Unit 101 (Grunt) P2: Starting position (21,21), HP_MAX=5 base=round/1\n"
)

_HOLD_STILL_3_MW = (
    "[10:00:02] E1 T1 P1 FIGHT : Unit 101(21,21) SUFFERS 3 Mortal Wounds "
    "[HOLD STILL AND SAY AARGH] MW:1,2 [FROM:1] [R:+0.0] [SUCCESS]\n"
)
_EXHORTATION_2_MW = (
    "[10:00:03] E1 T1 P1 FIGHT : Unit 101(21,21) SUFFERS 2 Mortal Wounds "
    "[EXHORTATION DE RAGE] [FROM:1] [R:+0.0] [SUCCESS]\n"
)
_SANS_SOURCE = (
    "[10:00:02] E1 T1 P1 FIGHT : Unit 101(21,21) SUFFERS 5 Mortal Wounds "
    "[HOLD STILL AND SAY AARGH] MW:2,3 [R:+0.0] [SUCCESS]\n"
)
# 5 BM sur une victime à HP_MAX=5 : la mort est le signal observable que les points de vie
# ont réellement été retirés (`stats` n'expose pas `unit_hp`).
_HOLD_STILL_FATAL = (
    "[10:00:02] E1 T1 P1 FIGHT : Unit 101(21,21) SUFFERS 5 Mortal Wounds "
    "[HOLD STILL AND SAY AARGH] MW:2,3 [FROM:1] [R:+0.0] [SUCCESS]\n"
)


def _parse(tmp_path, monkeypatch, body: str = ""):
    import ai.analyzer as an
    import ai.analyzer_config as ac_mod

    cfg = fab_config(unit_registry=_Registry(), unit_weapons_cache={})
    monkeypatch.setattr(ac_mod, "load_analyzer_config", lambda: cfg)

    log = tmp_path / "step.log"
    log.write_text(entete_step_log(
        body,
        inches_to_subhex=1,
        board="cols=40 rows=40",
        objectives=_OBJECTIVES,
        units=_UNITS,
    ))
    return an.parse_step_log(str(log))


def test_points_de_vie_retires_a_la_victime(tmp_path, monkeypatch):
    """ROUGE sans la branche : la ligne tombe dans action_type='other', les points de vie ne
    sont jamais retirés et la mort n'est jamais enregistrée."""
    stats = _parse(tmp_path, monkeypatch, _HOLD_STILL_FATAL)
    assert not stats["parse_errors"], f"aucune erreur attendue, got {stats['parse_errors']}"
    deaths = stats["current_episode_deaths"]
    assert any(d[1] == "101" for d in deaths), (
        f"la VICTIME doit mourir de ses 5 blessures mortelles, got {deaths}"
    )
    assert not any(d[1] == "1" for d in deaths), "l'unité SOURCE ne perd rien"


def test_usage_compte_sur_la_source(tmp_path, monkeypatch):
    """§1.7 : l'usage se compte sur le porteur de la règle et son camp — sans `[FROM:]`, la
    table afficherait 0 utilisation sur une règle qui a tiré."""
    stats = _parse(tmp_path, monkeypatch, _HOLD_STILL_3_MW + _EXHORTATION_2_MW)
    assert stats["special_rule_usage"][("mortal_wounds_on_critical_wound", "PainBoy")][1] == 1
    assert stats["special_rule_usage"][("mortal_wounds_on_fight_activation", "PainBoy")][1] == 1


def test_pas_compte_comme_hazardous(tmp_path, monkeypatch):
    """24.15 a son propre compteur ET son contrôle d'armurerie : y verser des blessures de
    capacité ferait remonter « arme HAZARDOUS absente » sur une unité qui n'en porte pas."""
    stats = _parse(tmp_path, monkeypatch, _HOLD_STILL_3_MW)
    assert stats["hazardous_mortal_wounds"][1] == 0
    assert stats["hazardous_no_hazardous_weapon_fight"][1] == 0


def test_ligne_sans_source_est_une_erreur_de_format(tmp_path, monkeypatch):
    """T1 : une ligne incomplète est signalée, jamais absorbée en silence."""
    stats = _parse(tmp_path, monkeypatch, _SANS_SOURCE)
    assert stats["parse_errors"], "une ligne sans [FROM:] doit produire une parse_error"
    assert not any(d[1] == "101" for d in stats["current_episode_deaths"]), (
        "aucun dégât ne doit être appliqué depuis une ligne mal formée"
    )


# ── FNP partiels ─────────────────────────────────────────────────────────────
# Grunt (HP_MAX=5) subit 5 BM mais sauve 2 via FNP → 3 BM nettes → survit.
# ROUGE sans le fix : l'analyzer appliquait le total pré-FNP (5) → mort fausse.
_FNP_PARTIEL_5MW_2SAVES = (
    "[10:00:02] E1 T1 P1 FIGHT : Unit 101(21,21) SUFFERS 5 Mortal Wounds "
    "[HOLD STILL AND SAY AARGH] MW:2,3 [FROM:1] [FNP:2] [ALLOC_MODEL: 101_m0] "
    "[R:+0.0] [SUCCESS]\n"
)
# Grunt (HP_MAX=5) subit 5 BM mais toutes sauvées par FNP → 0 BM nettes → survit.
# ROUGE sans le fix : l'analyzer appliquait 5 BM → mort fausse.
_FNP_TOTAL_5MW_ALL_SAVED = (
    "[10:00:02] E1 T1 P1 FIGHT : Unit 101(21,21) SUFFERS 5 Mortal Wounds "
    "[HOLD STILL AND SAY AARGH] MW:2,3 [FROM:1] [ALL FNP SAVED] "
    "[R:+0.0] [SUCCESS]\n"
)


def test_fnp_partiel_soustrait_des_blessures(tmp_path, monkeypatch):
    """ROUGE sans le fix : le total pré-FNP (5) était appliqué ; Grunt (HP=5) mourait alors
    que le moteur lui avait laissé 2 PV. VERT avec le fix : [FNP:2] soustrait 2 → 3 BM nettes
    → Grunt (HP=5) survit."""
    stats = _parse(tmp_path, monkeypatch, _FNP_PARTIEL_5MW_2SAVES)
    assert not stats["parse_errors"], f"aucune erreur attendue, got {stats['parse_errors']}"
    deaths = stats["current_episode_deaths"]
    assert not any(d[1] == "101" for d in deaths), (
        f"Grunt (HP=5) doit survivre à 3 BM nettes (5−2 FNP), got deaths={deaths}"
    )


def test_fnp_total_annule_toutes_les_blessures(tmp_path, monkeypatch):
    """ROUGE sans le fix : [ALL FNP SAVED] ignoré ; 5 BM appliquées → Grunt mourait.
    VERT avec le fix : 0 BM nettes → Grunt (HP=5) survit."""
    stats = _parse(tmp_path, monkeypatch, _FNP_TOTAL_5MW_ALL_SAVED)
    assert not stats["parse_errors"], f"aucune erreur attendue, got {stats['parse_errors']}"
    deaths = stats["current_episode_deaths"]
    assert not any(d[1] == "101" for d in deaths), (
        f"Grunt (HP=5) doit survivre à 0 BM nettes ([ALL FNP SAVED]), got deaths={deaths}"
    )
