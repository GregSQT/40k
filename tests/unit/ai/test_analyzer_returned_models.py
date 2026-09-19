"""Ligne `RETURNED` (Grot Orderly, grammaire 10) — lecteur de l'analyzer.

Avant cette ligne, une figurine rendue n'existait pour l'analyzer qu'au détour du `[MODELS:]`
d'une ligne suivante, sous un id `<escouade>#r<n>` d'où aucune datasheet ne se déduisait :
PV pleins de l'ESCOUADE au lieu de la figurine, et abstention de tout verdict 19.04
(`living_datasheets`) pour l'escouade entière.

Ce que ce fichier verrouille :
- la datasheet du socle rendu est absorbée AVANT le recalage des socles vivants, donc le socle
  entre à SES PV pleins (PainBoy : 3, pas 1) ;
- l'usage §1.7 de `return_destroyed_models` est relevé sur l'escouade ;
- la restitution est une mise en place : 03.03 (coherency) s'y juge ;
- en grammaire 10, un id `#r` vu dans `[MODELS:]` sans ligne `RETURNED` est une panne du
  producteur ; en grammaire antérieure, rien n'est inventé ;
- une ligne qui annonce k figurines et en déclare j ≠ k est une erreur de format.
"""
from __future__ import annotations

from ai.step_logger import LOG_GRAMMAR_VERSION
from tests.unit.ai._fabriques import entete_step_log
from tests.unit.ai._fabriques import analyzer_config as fab_config

_OBJECTIVES = ";".join(f"(30,{r})" for r in range(30, 33))


class _Registry:
    units = {
        "Boyz": {"HP_MAX": 1, "MOVE": 6, "MODEL_HEIGHT": 1.0, "UNIT_RULES": []},
        # `support` : le PainBoy est un CHARACTER (rôle d'allocation) — « bodyguard models »
        # ne le désigne jamais (`returned_models_invalid`).
        "PainBoy": {"HP_MAX": 3, "MOVE": 6, "MODEL_HEIGHT": 1.0,
                    "UNIT_RULES": [{"ruleId": "support", "displayName": "Support"}]},
        "Grunt": {"HP_MAX": 5, "MOVE": 6, "MODEL_HEIGHT": 1.0, "UNIT_RULES": []},
        # Second profil BODYGUARD, distinct de `Boyz` : la ligne que le moteur produit doit
        # porter la datasheet de CHAQUE socle rendu, pas celle de l'escouade.
        "Nob": {"HP_MAX": 2, "MOVE": 6, "MODEL_HEIGHT": 1.0, "UNIT_RULES": []},
    }


_UNITS = (
    "[10:00:00] Unit 1 (Boyz) P1: Starting position (20,20), HP_MAX=1 base=round/1 "
    "[MODELS: 1#0@(20,20,z0) 1#1@(20,21,z0)] [MODEL_TYPES: 1#0=Boyz 1#1=PainBoy]\n"
    "[10:00:00] Unit 101 (Grunt) P2: Starting position (21,21), HP_MAX=5 base=round/1\n"
)
_PAINBOY_MORT = (
    "[10:00:01] E1 T1 P2 SHOOT : Unit 1 DEAD model=1#1 reason=combat "
    "[MODELS: 1#0@(20,20,z0)] [SUCCESS]\n"
)


def _returned(types: str, models: str, count: int = 1) -> str:
    return (
        f"[10:00:02] E1 T2 P1 COMMAND : Unit 1(20,20) RETURNED {count} models [GROT ORDERLY] (D3=1) "
        f"[MODEL_TYPES: {types}] [MODELS: {models}] [SUCCESS]\n"
    )


#: Blessure mortelle sur l'escouade 1 : la ligne nomme le socle alloué, dont on lit les PV.
def _mw_sur_socle(mid: str, n: int) -> str:
    return (
        f"[10:00:03] E1 T2 P2 FIGHT : Unit 1(20,20) SUFFERS {n} Mortal Wounds [DESPERATE ESCAPE] "
        f"[ALLOC_MODEL: {mid}] [R:+0.0] [SUCCESS]\n"
    )


def _parse(tmp_path, monkeypatch, body: str, *, log_grammar=10, units: str = _UNITS):
    import ai.analyzer as an
    import ai.analyzer_config as ac_mod

    cfg = fab_config(
        unit_registry=_Registry(), unit_weapons_cache={},
        rule_to_units={"return_destroyed_models": {"PainBoy"}},
    )
    monkeypatch.setattr(ac_mod, "load_analyzer_config", lambda: cfg)
    log = tmp_path / "step.log"
    log.write_text(entete_step_log(
        body, inches_to_subhex=1, board="cols=40 rows=40", objectives=_OBJECTIVES,
        units=units, log_grammar=log_grammar,
    ))
    return an.parse_step_log(str(log))


def test_la_ligne_est_lue_et_l_usage_releve(tmp_path, monkeypatch):
    """ROUGE avant le fix : la ligne tombait dans `other`, rien n'était compté. PainBoy vivant
    (1#1), un Boy rendu : usage VALIDE."""
    stats = _parse(tmp_path, monkeypatch, _returned("1#r0=Boyz", "1#0@(20,20,z0) 1#1@(20,21,z0) 1#r0@(20,22,z0)"))
    assert not stats["parse_errors"], stats["parse_errors"]
    assert stats["returned_models"][1] == 1
    assert stats["actions_by_type"]["returned_models"] == 1
    assert stats["special_rule_usage"][("return_destroyed_models", "Boyz")][1] == 1
    assert stats["special_rule_usage_invalid"][("return_destroyed_models", "Boyz")][1] == 0


def test_la_restitution_est_jugee_sur_la_composition_d_avant(tmp_path, monkeypatch):
    """Un PainBoy MORT qui se rend lui-même : Grot Orderly est SA capacité, éteinte avec lui
    (19.04). La ligne recale le socle rendu comme vivant AVANT que l'usage soit jugé — jugé sur
    l'après, l'usage ressortirait VALIDE et le seul cas illégal serait invisible."""
    stats = _parse(tmp_path, monkeypatch, _PAINBOY_MORT + _returned("1#r0=PainBoy", "1#0@(20,20,z0) 1#r0@(20,21,z0)"))
    assert not stats["parse_errors"], stats["parse_errors"]
    assert stats["special_rule_usage"][("return_destroyed_models", "Boyz")][1] == 1
    assert stats["special_rule_usage_invalid"][("return_destroyed_models", "Boyz")][1] == 1


def test_le_socle_rendu_entre_a_ses_pv_pleins_de_datasheet(tmp_path, monkeypatch):
    """Le PainBoy rendu a 3 PV (sa datasheet), pas 1 (l'escouade Boyz) : deux blessures
    mortelles allouées sur lui ne le tuent pas."""
    stats = _parse(
        tmp_path, monkeypatch,
        _PAINBOY_MORT + _returned("1#r0=PainBoy", "1#0@(20,20,z0) 1#r0@(20,21,z0)")
        + _mw_sur_socle("1#r0", 2),
    )
    assert not stats["parse_errors"], stats["parse_errors"]
    assert not stats["current_episode_deaths"], "le PainBoy rendu (3 PV) ne meurt pas de 2 BM"


def test_un_socle_rendu_non_declare_est_une_panne_en_grammaire_10(tmp_path, monkeypatch):
    """Sans ligne RETURNED, un `#r` dans [MODELS:] est une panne du producteur — mais seulement
    à partir de la grammaire qui le garantit."""
    body = (
        "[10:00:02] E1 T2 P1 MOVE : Unit 1(20,20) MOVED from (20,20) to (20,20) "
        "[MODELS: 1#0@(20,20,z0) 1#r0@(20,21,z0)] [R:+0.0] [SUCCESS]\n"
    )
    stats = _parse(tmp_path, monkeypatch, body, log_grammar=10)
    assert any("socle rendu 1#r0" in e["error"] for e in stats["parse_errors"]), stats["parse_errors"]
    stats = _parse(tmp_path, monkeypatch, body, log_grammar=9)
    assert not any("socle rendu" in e["error"] for e in stats["parse_errors"]), stats["parse_errors"]


def test_compte_et_datasheets_doivent_concorder(tmp_path, monkeypatch):
    body = _returned("1#r0=PainBoy", "1#0@(20,20,z0) 1#r0@(20,21,z0) 1#r1@(20,22,z0)", count=2)
    stats = _parse(tmp_path, monkeypatch, body)
    assert any("2 figurine(s) annoncee(s), 1 datasheet(s)" in e["error"] for e in stats["parse_errors"]), stats["parse_errors"]


def test_la_restitution_est_jugee_en_coherence(tmp_path, monkeypatch):
    """25 Rules appendix (Revived) : « must be set up … In coherency ». Un socle rendu posé
    loin de l'escouade est une formation fautive, comme après tout déplacement."""
    stats = _parse(tmp_path, monkeypatch, _returned("1#r0=Boyz", "1#0@(20,20,z0) 1#r0@(35,35,z0)"))
    assert stats["squad_coherency_violations"][1] == 1, stats["first_error_lines"]["squad_coherency_violations"]
    stats = _parse(tmp_path, monkeypatch, _returned("1#r0=Boyz", "1#0@(20,20,z0) 1#r0@(20,21,z0)"))
    assert stats["squad_coherency_violations"][1] == 0


# ─────────────────────────────────────────────────────────────────────────────
# `returned_models_invalid` (ai/analyzer_objectives.py, PROJ.2.3.returned_models) — REVIVED
# ─────────────────────────────────────────────────────────────────────────────

_BOY_MORT = (
    "[10:00:01] E1 T1 P2 SHOOT : Unit 1 DEAD model=1#0 reason=combat "
    "[MODELS: 1#1@(20,21,z0)] [SUCCESS]\n"
)


def _returned_at(types: str, models: str, count: int = 1, d3: int = 1, phase: str = "COMMAND",
                 player: int = 1, sec: int = 2) -> str:
    return (
        f"[10:00:{sec:02d}] E1 T2 P{player} {phase} : Unit 1(20,20) RETURNED {count} models [GROT ORDERLY] (D3={d3}) "
        f"[MODEL_TYPES: {types}] [MODELS: {models}] [SUCCESS]\n"
    )


def _invalid(stats) -> tuple:
    first = stats["first_error_lines"]["returned_models_invalid"]
    return stats["returned_models_invalid"], (first[1] or first[2] or {}).get("detail")


def test_un_boy_mort_rendu_en_phase_de_commandement_est_correct(tmp_path, monkeypatch):
    stats = _parse(tmp_path, monkeypatch, _BOY_MORT + _returned_at("1#r0=Boyz", "1#1@(20,21,z0) 1#r0@(20,22,z0)"))
    assert stats["returned_models_invalid"] == {1: 0, 2: 0}, _invalid(stats)
    assert stats["rule_usage"]["PROJ.2.3.returned_models"][1] == 1


def test_plus_de_figurines_que_le_d3_est_une_faute(tmp_path, monkeypatch):
    body = _BOY_MORT + (
        "[10:00:01] E1 T1 P2 SHOOT : Unit 1 DEAD model=1#1 reason=combat [MODELS: 1#0@(20,20,z0)] [SUCCESS]\n"
    )
    # Deux figurines annoncées pour un D3 de 1 (le PainBoy rendu est une seconde faute, comptée à part).
    stats = _parse(tmp_path, monkeypatch, body + _returned_at("1#r0=Boyz 1#r1=Boyz", "1#r0@(20,22,z0) 1#r1@(20,23,z0)", count=2, d3=1))
    counts, detail = _invalid(stats)
    assert counts[1] >= 1 and "D3 de 1" in str(detail), (counts, detail)


def test_un_second_grot_orderly_dans_la_partie_est_une_faute(tmp_path, monkeypatch):
    body = (
        _BOY_MORT + _returned_at("1#r0=Boyz", "1#1@(20,21,z0) 1#r0@(20,22,z0)", sec=2)
        + "[10:00:03] E1 T3 P2 SHOOT : Unit 1 DEAD model=1#r0 reason=combat [MODELS: 1#1@(20,21,z0)] [SUCCESS]\n"
        + "[10:00:04] E1 T4 P1 COMMAND : Unit 1(20,20) RETURNED 1 models [GROT ORDERLY] (D3=1) "
          "[MODEL_TYPES: 1#r1=Boyz] [MODELS: 1#1@(20,21,z0) 1#r1@(20,22,z0)] [SUCCESS]\n"
    )
    stats = _parse(tmp_path, monkeypatch, body)
    counts, detail = _invalid(stats)
    assert counts == {1: 1, 2: 0} and "Once per battle" in str(detail), (counts, detail)


def test_un_type_jamais_mort_rendu_est_une_faute(tmp_path, monkeypatch):
    stats = _parse(tmp_path, monkeypatch, _returned_at("1#r0=Boyz", "1#0@(20,20,z0) 1#1@(20,21,z0) 1#r0@(20,22,z0)"))
    counts, detail = _invalid(stats)
    assert counts[1] >= 1 and "rendable" in str(detail), (counts, detail)


def test_un_support_rendu_est_une_faute(tmp_path, monkeypatch):
    """« return up to D3 destroyed BODYGUARD models » : le PainBoy (support) ne revient jamais."""
    stats = _parse(tmp_path, monkeypatch, _PAINBOY_MORT + _returned_at("1#r0=PainBoy", "1#0@(20,20,z0) 1#r0@(20,21,z0)"))
    counts, detail = _invalid(stats)
    assert counts == {1: 1, 2: 0} and "bodyguard" in str(detail), (counts, detail)


def test_une_restitution_hors_phase_de_commandement_ou_hors_tour_est_une_faute(tmp_path, monkeypatch):
    fight = _parse(tmp_path, monkeypatch, _BOY_MORT + _returned_at("1#r0=Boyz", "1#1@(20,21,z0) 1#r0@(20,22,z0)", phase="FIGHT"))
    assert fight["returned_models_invalid"][1] == 1 and "phase FIGHT" in str(_invalid(fight)[1])
    other = _parse(tmp_path, monkeypatch, _BOY_MORT + _returned_at("1#r0=Boyz", "1#1@(20,21,z0) 1#r0@(20,22,z0)", player=2))
    assert other["returned_models_invalid"][2] == 1 and "tour de 2" in str(_invalid(other)[1])


# ─────────────────────────────────────────────────────────────────────────────
# Le dernier maillon : moteur → step.log → analyzer, sans ligne écrite à la main
# ─────────────────────────────────────────────────────────────────────────────
#
# Tout ce qui précède réécrit la ligne `RETURNED` à la main (`_returned_at`) : l'analyzer y est
# jugé sur une grammaire que le test décide, pas sur celle que le moteur émet. Côté moteur,
# `tests/unit/engine/test_returned_models_placement.py` remonte la chaîne réelle jusqu'au
# formateur (`StepLogger._format_replay_style_message`) et s'y arrête. Aucun test ne DONNAIT
# donc à `parse_step_log` une ligne réellement produite par le moteur : le jour où le formateur
# change un token (`[MODEL_TYPES:]`, `(D3=n)`, le verbe `RETURNED`), les deux moitiés restent
# vertes et `check_returned_models` cesse de juger quoi que ce soit, en silence.
#
# Ici, rien n'est écrit à la main sur la ligne : l'écrivain de la restitution
# (`apply_returned_models_placement`), la traduction des clés
# (`W40KEngine._build_step_log_details`) et le vrai `StepLogger.log_action` la produisent
# entièrement — donc aussi le préfixe `E1 T1 P1 COMMAND`, que `check_returned_models` lit pour
# juger la phase et le joueur. Seul le décor (entête d'épisode, lignes `DEAD`) reste fabriqué :
# ce n'est pas le sujet.

#: Survivantes de l'escouade, puis les deux cases où les socles rendus reviennent — celles-là
#: mêmes que les figurines détruites occupaient, donc en cohésion avec les survivantes (03.03).
_CHAINE_VIVANTS = ((6, 4), (6, 5), (6, 6))
_CHAINE_CASES_RENDUES = ((6, 7), (6, 8))
_CHAINE_SEG_VIVANTS = "[MODELS: 1#0@(6,4,z0) 1#1@(6,5,z0) 1#2@(6,6,z0)]"


def _etat_avec_archive(profils):
    """Escouade ORK jouable (caches construits par `build_units_cache`) dont l'archive des
    détruites porte UN PROFIL PAR ENTRÉE de `profils`.

    Deux datasheets distinctes : c'est le seul régime où la ligne peut mentir en déclarant
    celle de l'escouade pour tous les socles rendus.
    """
    import copy

    from tests.unit.engine._state_builders import synthetic_state, synthetic_unit

    escouade = synthetic_unit(
        "1", 1, [{"col": col, "row": row} for col, row in _CHAINE_VIVANTS],
        unitType="Boyz",
        UNIT_RULES=[{"ruleId": "return_destroyed_models", "displayName": "Grot Orderly"}],
    )
    ennemi = synthetic_unit("101", 2, [{"col": 18, "row": 5}], unitType="Grunt")
    gs = synthetic_state(
        [escouade, ennemi], phase="command", game_rules={},
        inches_to_subhex=1, board_cols=30, board_rows=30,
    )
    archive = []
    for unit_type in profils:
        # Une figurine détruite EST une ancienne figurine vivante : on part de son entrée de
        # `models_cache`, la seule structure que l'écrivain de la restitution sait recopier.
        model = copy.deepcopy(gs["models_cache"]["1#0"])
        # `UNIT_RULES` vient de la MÊME datasheet que `unitType` : c'est d'elle que le moteur
        # (`_derive_model_role`) comme l'analyzer (`_model_is_character`) tirent le rôle. Les
        # laisser à celles du socle Boyz recopié donnerait un « PainBoy » qui n'est support que
        # pour l'analyzer, et la moitié moteur du cas ne serait pas exercée.
        model.update({
            "unitType": unit_type, "HP_MAX": int(_Registry.units[unit_type]["HP_MAX"]),
            "UNIT_RULES": copy.deepcopy(_Registry.units[unit_type]["UNIT_RULES"]),
            "HP_CUR": 0, "col": -1, "row": -1,
        })
        archive.append(model)
    gs["destroyed_models"]["1"] = archive
    return gs


def _ligne_returned_du_moteur(tmp_path, profils):
    """La ligne `RETURNED` telle que le CHEMIN DE PRODUCTION l'écrit, du premier au dernier
    maillon : écrivain → `_STEP_LOG_TYPE_MAP` → `_build_step_log_details` → `log_action`."""
    from ai.step_logger import StepLogger
    from engine.phase_handlers.command_handlers import apply_returned_models_placement
    from engine.w40k_core import W40KEngine

    gs = _etat_avec_archive(profils)
    # Deux profils distincts posent une décision `returned_models_profile` en amont : on appelle
    # l'ÉCRIVAIN, avec les figurines de l'archive et les cases qu'elles occupaient.
    apply_returned_models_placement(
        gs, "1", list(_CHAINE_CASES_RENDUES), list(range(len(profils))),
        d3=len(profils), destroyed=len(profils),
    )
    entrees = [e for e in gs["action_logs"] if e["type"] == "return_destroyed_models"]
    assert len(entrees) == 1, entrees
    entree = entrees[0]

    engine = W40KEngine.__new__(W40KEngine)
    engine.game_state = gs
    action_type = W40KEngine._STEP_LOG_TYPE_MAP["return_destroyed_models"]
    sortie = tmp_path / "moteur.log"
    logger = StepLogger(output_file=str(sortie), enabled=True, buffer_size=1)
    logger.episode_number = 1
    logger.log_action(
        unit_id=entree["unitId"], action_type=action_type, phase=entree["phase"],
        player=entree["player"], success=True,
        # Expression du chemin de production, recopiée telle quelle : le set est clé par type
        # BRUT, jamais par le nom mappé. Rien ici n'en dépend — le sujet du test est la ligne,
        # pas le compteur, verrouillé par
        # tests/unit/ai/test_step_logger.py::test_aucun_type_non_incrementant_ne_consomme_de_step_au_drainage.
        step_increment="return_destroyed_models" not in W40KEngine._STEP_LOG_NON_INCREMENTING_TYPES,
        action_details=engine._build_step_log_details(entree, pre_action_turn=1),
    )
    logger._flush_buffer()
    lignes = [l for l in sortie.read_text().splitlines() if " RETURNED " in l]
    assert len(lignes) == 1, sortie.read_text()
    return lignes[0]


def _journal_de_la_chaine(tmp_path, monkeypatch, ligne_moteur, morts):
    """Monte un journal autour de la ligne du moteur et le donne au vrai `parse_step_log`.

    `morts` : datasheet de `1#3` et `1#4`, les deux figurines que l'escouade perd avant la
    restitution — ce sont ELLES que la ligne est censée rendre. Les faire diverger des
    datasheets que le moteur a écrites sur la ligne est ce qui falsifie le vert.
    """
    vivants_puis_morts = _CHAINE_VIVANTS + _CHAINE_CASES_RENDUES
    models_seg = " ".join(
        f"1#{i}@({col},{row},z0)" for i, (col, row) in enumerate(vivants_puis_morts)
    )
    types_seg = " ".join(["1#0=Boyz", "1#1=Boyz", "1#2=Boyz"]
                         + [f"1#{3 + i}={t}" for i, t in enumerate(morts)])
    units = (
        f"[10:00:00] Unit 1 (Boyz) P1: Starting position (6,4), HP_MAX=1 base=round/1 "
        f"[MODELS: {models_seg}] [MODEL_TYPES: {types_seg}]\n"
        "[10:00:00] Unit 101 (Grunt) P2: Starting position (18,5), HP_MAX=5 base=round/1\n"
    )
    morts_lignes = (
        "[10:00:01] E1 T1 P2 SHOOT : Unit 1 DEAD model=1#3 reason=combat "
        "[MODELS: 1#0@(6,4,z0) 1#1@(6,5,z0) 1#2@(6,6,z0) 1#4@(6,8,z0)] [SUCCESS]\n"
        "[10:00:02] E1 T1 P2 SHOOT : Unit 1 DEAD model=1#4 reason=combat "
        f"{_CHAINE_SEG_VIVANTS} [SUCCESS]\n"
    )
    return _parse(
        tmp_path, monkeypatch, f"{morts_lignes}{ligne_moteur}\n",
        log_grammar=LOG_GRAMMAR_VERSION, units=units,
    )


def test_la_ligne_du_moteur_est_lue_sans_faute_par_l_analyzer(tmp_path, monkeypatch):
    """Deux socles rendus, deux datasheets distinctes, en phase de commandement du propriétaire :
    `check_returned_models` ne relève aucune faute et compte l'exercice de PROJ.2.3.

    Le verdict 19.04 (`special_rule_usage_invalid`) n'est PAS jugé ici : le décor attribue la
    capacité au seul PainBoy (`rule_to_units` de `_parse`, partagé avec les cas du haut du
    fichier), donc une escouade sans PainBoy vivant y ressort invalide — c'est le sujet de
    `test_la_restitution_est_jugee_sur_la_composition_d_avant`, pas celui de la chaîne.
    """
    ligne = _ligne_returned_du_moteur(tmp_path, ("Boyz", "Nob"))
    assert "[MODEL_TYPES: 1#r0=Boyz 1#r1=Nob]" in ligne, ligne

    stats = _journal_de_la_chaine(tmp_path, monkeypatch, ligne, ("Boyz", "Nob"))
    assert not stats["parse_errors"], stats["parse_errors"]
    assert stats["returned_models_invalid"] == {1: 0, 2: 0}, _invalid(stats)
    assert stats["rule_usage"]["PROJ.2.3.returned_models"][1] == 1
    assert stats["returned_models"][1] == 2


def test_la_datasheet_ecrite_par_le_moteur_est_bien_celle_que_l_analyzer_juge(tmp_path, monkeypatch):
    """VERT NON VACANT : la ligne est la MÊME, seule l'escouade change — aucun `Nob` n'y est
    jamais mort. Si l'analyzer lisait la datasheet de l'ESCOUADE (Boyz) au lieu de celle que le
    moteur a écrite par socle, le verdict resterait vert."""
    ligne = _ligne_returned_du_moteur(tmp_path, ("Boyz", "Nob"))

    stats = _journal_de_la_chaine(tmp_path, monkeypatch, ligne, ("Boyz", "Boyz"))
    counts, detail = _invalid(stats)
    assert counts == {1: 1, 2: 0} and "1#r1=Nob" in str(detail), (counts, detail)


def test_un_support_rendu_par_le_moteur_est_vu_par_l_analyzer(tmp_path, monkeypatch):
    """La faute remise en place sur la CHAÎNE ENTIÈRE : l'écrivain accepte l'index d'un profil
    `support` (le filtre bodyguard vit en amont, dans la sélection), donc le moteur PEUT émettre
    cette ligne — et c'est l'analyzer qui doit la refuser (« BODYGUARD models »)."""
    ligne = _ligne_returned_du_moteur(tmp_path, ("Boyz", "PainBoy"))
    assert "1#r1=PainBoy" in ligne, ligne

    stats = _journal_de_la_chaine(tmp_path, monkeypatch, ligne, ("Boyz", "PainBoy"))
    assert not stats["parse_errors"], stats["parse_errors"]
    counts, detail = _invalid(stats)
    assert counts == {1: 1, 2: 0} and "bodyguard" in str(detail), (counts, detail)
