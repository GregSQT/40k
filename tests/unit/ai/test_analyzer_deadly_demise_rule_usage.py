"""24.08 Deadly Demise dans la table §1.7 : relevé par unité SOURCE, verdict sur le socle DÉTRUIT.

Mesuré sur l'éval du 2026-09-13 : `deadly_demise_triggers` = 90 + 63 alors que la table §1.7
affichait `deadly_demise WeirdBoy 0 0` — la branche `[DEADLY DEMISE]` incrémentait le compteur
d'exercice sans jamais relever l'usage §1.7.

Le verdict 19.04 ne peut PAS se rendre sur la composition vivante : 24.08 s'exerce par une
figurine qui vient de MOURIR (sa ligne `DEAD model=` précède la ligne DEADLY DEMISE, écrite dans
`destroy_model`). La validité est donc « le socle détruit portait la règle », lue sur la datasheet
du `DEAD` de la source qui précède sa PREMIÈRE ligne DEADLY DEMISE du bloc. C'est aussi le seul
verdict qui distingue un WeirdBoy attaché qui explose (légal) d'un Boy de la même escouade qui
exploserait à sa place (illégal : la règle est « when a model with this ability is destroyed »,
pas une règle d'escouade).

UN relevé par jet de D6, pas une ligne par unité à 6" : `_apply_deadly_demise` écrit une ligne par
unité dans le rayon — la source comprise tant qu'il lui reste des socles, dont les pertes
`DEAD … reason=hazard` s'intercalent entre deux lignes du même jet.
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log

_WEIRDBOY_SEUL = (
    "[10:00:00] Unit 4 (WeirdBoy) P1: Starting position (50,50), HP_MAX=5 base=round/6 [MODELS: 4#0@(50,50,z0)] [MODEL_TYPES: 4#0=WeirdBoy]\n"
    "[10:00:00] Unit 105 (AssaultIntercessor) P2: Starting position (51,50), HP_MAX=2 base=round/6 [MODELS: 105#0@(51,50,z0)] [MODEL_TYPES: 105#0=AssaultIntercessor]\n"
)
_WEIRDBOY_ATTACHE = (
    "[10:00:00] Unit 4 (Boyz) P1: Starting position (50,50), HP_MAX=1 base=round/6 [MODELS: 4#0@(50,50,z0) 4#1@(50,51,z0)] [MODEL_TYPES: 4#0=Boyz 4#1=WeirdBoy]\n"
    "[10:00:00] Unit 105 (AssaultIntercessor) P2: Starting position (51,50), HP_MAX=2 base=round/6 [MODELS: 105#0@(51,50,z0)] [MODEL_TYPES: 105#0=AssaultIntercessor]\n"
)
_SANS_PORTEUR = (
    "[10:00:00] Unit 4 (Intercessor) P1: Starting position (50,50), HP_MAX=2 base=round/6 [MODELS: 4#0@(50,50,z0)] [MODEL_TYPES: 4#0=Intercessor]\n"
    "[10:00:00] Unit 105 (AssaultIntercessor) P2: Starting position (51,50), HP_MAX=2 base=round/6 [MODELS: 105#0@(51,50,z0)] [MODEL_TYPES: 105#0=AssaultIntercessor]\n"
)
_DEPLOIEMENTS = (
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 4(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [MODELS: 4#0@(50,50,z0)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 105(51,50) DEPLOYED from (-1,-1) to (51,50) [R:+0.0] [MODELS: 105#0@(51,50,z0)] [SUCCESS]\n"
)
_DEPLOIEMENTS_ATTACHE = (
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 4(50,50) DEPLOYED from (-1,-1) to (50,50) [R:+0.0] [MODELS: 4#0@(50,50,z0) 4#1@(50,51,z0)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 105(51,50) DEPLOYED from (-1,-1) to (51,50) [R:+0.0] [MODELS: 105#0@(51,50,z0)] [SUCCESS]\n"
)


def _dead(mid: str) -> str:
    return f"[10:00:02] E1 T1 P2 FIGHT : Unit 4 DEAD model={mid} reason=combat [SUCCESS]\n"


_DD_EFFET = "[10:00:02] E1 T1 P1 FIGHT : Unit 4 DEADLY DEMISE Roll:6 → Unit 105(51,50) SUFFERS 2 MW [DEADLY DEMISE] [SUCCESS]\n"
_DD_RATE = "[10:00:02] E1 T1 P1 FIGHT : Unit 4 DEADLY DEMISE Roll:3 → no effect [DEADLY DEMISE] [SUCCESS]\n"


def _parse(tmp_path, contenu: str):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(contenu)
    return an.parse_step_log(str(log))


def test_weirdboy_seul_alimente_la_table_1_7_en_valide(tmp_path):
    """Le cas de production (roster holdout : WeirdBoy autonome). Jet réussi ET jet raté sont
    chacun un exercice de la règle."""
    stats = _parse(tmp_path, entete_step_log(
        _DEPLOIEMENTS + _dead("4#0") + _DD_EFFET, units=_WEIRDBOY_SEUL, ez_vertical_inches=None,
    ))
    assert stats["parse_errors"] == [], stats["parse_errors"]
    assert stats["deadly_demise_triggers"][1] == 1
    assert stats["special_rule_usage"][("deadly_demise", "WeirdBoy")] == {1: 1, 2: 0}
    assert ("deadly_demise", "WeirdBoy") not in stats["special_rule_usage_invalid"]

    stats = _parse(tmp_path, entete_step_log(
        _DEPLOIEMENTS + _dead("4#0") + _DD_RATE, units=_WEIRDBOY_SEUL, ez_vertical_inches=None,
    ))
    assert stats["special_rule_usage"][("deadly_demise", "WeirdBoy")] == {1: 1, 2: 0}
    assert ("deadly_demise", "WeirdBoy") not in stats["special_rule_usage_invalid"]


def test_weirdboy_attache_qui_explose_est_valide_sous_la_cle_de_l_escouade(tmp_path):
    """La clé §1.7 est le type de l'escouade SOURCE (Boyz) ; le socle détruit (4#1) porte la règle."""
    stats = _parse(tmp_path, entete_step_log(
        _DEPLOIEMENTS_ATTACHE + _dead("4#1") + _DD_EFFET, units=_WEIRDBOY_ATTACHE, ez_vertical_inches=None,
    ))
    assert stats["special_rule_usage"][("deadly_demise", "Boyz")] == {1: 1, 2: 0}
    assert ("deadly_demise", "Boyz") not in stats["special_rule_usage_invalid"]


def test_un_boy_qui_explose_est_invalide_meme_si_le_weirdboy_est_vivant(tmp_path):
    """Le verdict se rend sur le socle DÉTRUIT (4#0 = Boyz), pas sur la composition vivante —
    qui contient encore le WeirdBoy et aurait blanchi l'explosion.

    Mutation : juger via `living_datasheets` → INVALID 0."""
    stats = _parse(tmp_path, entete_step_log(
        _DEPLOIEMENTS_ATTACHE + _dead("4#0") + _DD_EFFET, units=_WEIRDBOY_ATTACHE, ez_vertical_inches=None,
    ))
    assert stats["special_rule_usage"][("deadly_demise", "Boyz")] == {1: 1, 2: 0}
    assert stats["special_rule_usage_invalid"][("deadly_demise", "Boyz")] == {1: 1, 2: 0}


def test_une_source_qui_n_a_jamais_porte_la_regle_est_invalide(tmp_path):
    stats = _parse(tmp_path, entete_step_log(
        _DEPLOIEMENTS + _dead("4#0") + _DD_EFFET, units=_SANS_PORTEUR, ez_vertical_inches=None,
    ))
    assert stats["special_rule_usage"][("deadly_demise", "Intercessor")] == {1: 1, 2: 0}
    assert stats["special_rule_usage_invalid"][("deadly_demise", "Intercessor")] == {1: 1, 2: 0}


def test_deadly_demise_sans_dead_prealable_est_relevee_sans_verdict(tmp_path):
    """Journal tronqué (aucune ligne DEAD de la source avant l'explosion) : l'usage est relevé,
    le verdict s'abstient — jamais une faute inventée."""
    stats = _parse(tmp_path, entete_step_log(
        _DEPLOIEMENTS + _DD_EFFET, units=_SANS_PORTEUR, ez_vertical_inches=None,
    ))
    assert stats["special_rule_usage"][("deadly_demise", "Intercessor")] == {1: 1, 2: 0}
    assert ("deadly_demise", "Intercessor") not in stats["special_rule_usage_invalid"]


def test_ligne_deadly_demise_sans_source_est_une_erreur_de_parse(tmp_path):
    stats = _parse(tmp_path, entete_step_log(
        _DEPLOIEMENTS + _dead("4#0")
        + "[10:00:02] E1 T1 P1 FIGHT : Kaboom [DEADLY DEMISE] [SUCCESS]\n",
        units=_WEIRDBOY_SEUL, ez_vertical_inches=None,
    ))
    assert len(stats["parse_errors"]) == 1, stats["parse_errors"]
    assert "[DEADLY DEMISE] sans source" in stats["parse_errors"][0]["error"]
    assert ("deadly_demise", "WeirdBoy") not in stats["special_rule_usage"]


_DD_EFFET_SUR_SOI = "[10:00:02] E1 T1 P1 FIGHT : Unit 4 DEADLY DEMISE Roll:6 → Unit 4(50,50) SUFFERS 1 MW [DEADLY DEMISE] [SUCCESS]\n"
_DEAD_4_0_HAZARD = "[10:00:02] E1 T1 P1 FIGHT : Unit 4 DEAD model=4#0 reason=hazard [SUCCESS]\n"
_DD_EFFET_106 = "[10:00:02] E1 T1 P1 FIGHT : Unit 4 DEADLY DEMISE Roll:6 → Unit 106(52,50) SUFFERS 2 MW [DEADLY DEMISE] [SUCCESS]\n"
_UNIT_106 = "[10:00:00] Unit 106 (AssaultIntercessor) P2: Starting position (52,50), HP_MAX=2 base=round/6 [MODELS: 106#0@(52,50,z0)] [MODEL_TYPES: 106#0=AssaultIntercessor]\n"
_DEPLOIEMENT_106 = "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 106(52,50) DEPLOYED from (-1,-1) to (52,50) [R:+0.0] [MODELS: 106#0@(52,50,z0)] [SUCCESS]\n"


def test_l_explosion_qui_tue_un_boy_de_sa_propre_escouade_reste_un_seul_releve_valide(tmp_path):
    """Ordre moteur : DEAD 4#1 (WeirdBoy), ligne sur l'escouade 4 elle-même, DEAD 4#0 (Boy,
    hazard), ligne sur 105. Le socle exploseur est figé à la première ligne : la perte du Boy ne
    fait pas juger la seconde ligne sur lui.

    Mutation : lire `last_dead_mid_by_unit` à chaque ligne → usage 2, INVALID 1."""
    stats = _parse(tmp_path, entete_step_log(
        _DEPLOIEMENTS_ATTACHE + _dead("4#1") + _DD_EFFET_SUR_SOI + _DEAD_4_0_HAZARD + _DD_EFFET,
        units=_WEIRDBOY_ATTACHE, ez_vertical_inches=None,
    ))
    assert stats["parse_errors"] == [], stats["parse_errors"]
    assert stats["deadly_demise_triggers"][1] == 2
    assert stats["special_rule_usage"][("deadly_demise", "Boyz")] == {1: 1, 2: 0}
    assert ("deadly_demise", "Boyz") not in stats["special_rule_usage_invalid"]


def test_une_explosion_illegale_pres_de_deux_unites_compte_une_faute_pas_deux(tmp_path):
    stats = _parse(tmp_path, entete_step_log(
        _DEPLOIEMENTS + _DEPLOIEMENT_106 + _dead("4#0") + _DD_EFFET + _DD_EFFET_106,
        units=_SANS_PORTEUR + _UNIT_106, ez_vertical_inches=None,
    ))
    assert stats["deadly_demise_triggers"][1] == 2
    assert stats["special_rule_usage"][("deadly_demise", "Intercessor")] == {1: 1, 2: 0}
    assert stats["special_rule_usage_invalid"][("deadly_demise", "Intercessor")] == {1: 1, 2: 0}


def test_deux_explosions_separees_de_la_meme_source_font_deux_releves(tmp_path):
    """Le bloc se ferme à la première ligne qui n'est ni DEAD ni DEADLY DEMISE : l'explosion
    suivante de la même escouade est un nouveau jet, jugé sur SON socle (ici un Boy : INVALID).

    Mutation : ne pas vider `deadly_demise_exploder` hors bloc → usage 1, INVALID 0."""
    mouvement = "[10:00:03] E1 T1 P2 MOVE : Unit 105(51,50) MOVED from (51,50) to (51,52) [R:+0.0] [MODELS: 105#0@(51,52,z0)] [SUCCESS]\n"
    stats = _parse(tmp_path, entete_step_log(
        _DEPLOIEMENTS_ATTACHE + _dead("4#1") + _DD_RATE + mouvement + _dead("4#0") + _DD_RATE,
        units=_WEIRDBOY_ATTACHE, ez_vertical_inches=None,
    ))
    assert stats["parse_errors"] == [], stats["parse_errors"]
    assert stats["special_rule_usage"][("deadly_demise", "Boyz")] == {1: 2, 2: 0}
    assert stats["special_rule_usage_invalid"][("deadly_demise", "Boyz")] == {1: 1, 2: 0}
