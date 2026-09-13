"""24.08 Deadly Demise dans la table §1.7 : relevé par unité SOURCE, verdict sur les vivants ∪ le socle qui explose.

Mesuré sur l'éval du 2026-09-13 : `deadly_demise_triggers` = 90 + 63 alors que la table §1.7
affichait `deadly_demise WeirdBoy 0 0` — la branche `[DEADLY DEMISE]` incrémentait le compteur
d'exercice sans jamais relever l'usage §1.7.

Règles lues (Documentation/40k_rules, 24.08 et 19.04) : « Each time a model IN THIS UNIT is
destroyed […] roll one D6 » — règle d'UNITÉ, conférée à toute l'escouade attachée « until the
source of that ability/rule is destroyed ». Donc un Boy mené par un WeirdBoy explose légalement
tant que le WeirdBoy est dans l'escouade, et plus jamais après sa disparition.

Le verdict se rend sur la composition vivante PLUS le socle qui vient d'exploser : sa ligne
`DEAD model=` précède la ligne DEADLY DEMISE (écrite dans `destroy_model`), et il faisait partie
de l'unité à l'instant du jet (exemple du PDF : le jet, puis l'Impulsor est retiré). Le socle est
celui du `DEAD` de la source qui précède sa PREMIÈRE ligne DEADLY DEMISE du bloc.

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


def test_un_boy_qui_explose_pendant_que_le_weirdboy_est_vivant_est_valide(tmp_path):
    """24.08 + 19.04 : la règle du WeirdBoy est conférée à tout Boy de l'escouade tant qu'il vit."""
    stats = _parse(tmp_path, entete_step_log(
        _DEPLOIEMENTS_ATTACHE + _dead("4#0") + _DD_EFFET, units=_WEIRDBOY_ATTACHE, ez_vertical_inches=None,
    ))
    assert stats["special_rule_usage"][("deadly_demise", "Boyz")] == {1: 1, 2: 0}
    assert ("deadly_demise", "Boyz") not in stats["special_rule_usage_invalid"]


def test_un_boy_qui_explose_apres_la_disparition_du_weirdboy_est_invalide(tmp_path):
    """19.04 : la source est détruite ET sortie de la composition (ligne `[MODELS:]` postérieure
    à sa mort) ; un Boy qui explose ensuite n'a plus la règle. C'est le détecteur du défaut
    moteur « clé `deadly_demise` d'escouade jamais rafraîchie » (shared_utils.py:1251/4520).

    Mutation : juger le socle exploseur SEUL (sans les vivants) → le Boy sortait déjà INVALID,
    mais le cas précédent (WeirdBoy vivant) sortait INVALID aussi — les deux tests ensemble
    verrouillent l'union."""
    weirdboy_mort = "[10:00:02] E1 T1 P2 FIGHT : Unit 4 DEAD model=4#1 reason=combat [SUCCESS]\n"
    mouvement_sans_lui = "[10:00:03] E1 T2 P1 MOVE : Unit 4(50,50) MOVED from (50,50) to (50,52) [R:+0.0] [MODELS: 4#0@(50,52,z0)] [SUCCESS]\n"
    boy_mort = "[10:00:04] E1 T2 P2 FIGHT : Unit 4 DEAD model=4#0 reason=combat [SUCCESS]\n"
    dd = "[10:00:04] E1 T2 P1 FIGHT : Unit 4 DEADLY DEMISE Roll:3 → no effect [DEADLY DEMISE] [SUCCESS]\n"
    stats = _parse(tmp_path, entete_step_log(
        _DEPLOIEMENTS_ATTACHE + weirdboy_mort + mouvement_sans_lui + boy_mort + dd,
        units=_WEIRDBOY_ATTACHE, ez_vertical_inches=None,
    ))
    assert stats["parse_errors"] == [], stats["parse_errors"]
    assert stats["special_rule_usage"][("deadly_demise", "Boyz")] == {1: 1, 2: 0}
    assert stats["special_rule_usage_invalid"][("deadly_demise", "Boyz")] == {1: 1, 2: 0}


def test_une_source_qui_n_a_jamais_porte_la_regle_est_invalide(tmp_path):
    stats = _parse(tmp_path, entete_step_log(
        _DEPLOIEMENTS + _dead("4#0") + _DD_EFFET, units=_SANS_PORTEUR, ez_vertical_inches=None,
    ))
    assert stats["special_rule_usage"][("deadly_demise", "Intercessor")] == {1: 1, 2: 0}
    assert stats["special_rule_usage_invalid"][("deadly_demise", "Intercessor")] == {1: 1, 2: 0}


def test_deadly_demise_sans_dead_prealable_est_jugee_sur_les_vivants_seuls(tmp_path):
    """Journal tronqué (aucune ligne DEAD de la source avant l'explosion) : le verdict se rend sur
    la composition vivante, comme toute autre règle — une unité qui ne porte jamais la règle
    reste INVALID, un porteur vivant reste VALID."""
    stats = _parse(tmp_path, entete_step_log(
        _DEPLOIEMENTS + _DD_EFFET, units=_SANS_PORTEUR, ez_vertical_inches=None,
    ))
    assert stats["special_rule_usage"][("deadly_demise", "Intercessor")] == {1: 1, 2: 0}
    assert stats["special_rule_usage_invalid"][("deadly_demise", "Intercessor")] == {1: 1, 2: 0}
    stats = _parse(tmp_path, entete_step_log(
        _DEPLOIEMENTS + _DD_EFFET, units=_WEIRDBOY_SEUL, ez_vertical_inches=None,
    ))
    assert ("deadly_demise", "WeirdBoy") not in stats["special_rule_usage_invalid"]


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
    fait pas relever un second jet.

    Mutation : relever à chaque ligne → usage 2."""
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
    suivante de la même escouade est un nouveau jet. Ici le WeirdBoy reste dans la composition
    connue (aucun `[MODELS:]` de l'escouade 4 entre les deux) : les deux jets sont VALID.

    Mutation : ne pas vider `deadly_demise_exploder` hors bloc → usage 1."""
    mouvement = "[10:00:03] E1 T1 P2 MOVE : Unit 105(51,50) MOVED from (51,50) to (51,52) [R:+0.0] [MODELS: 105#0@(51,52,z0)] [SUCCESS]\n"
    stats = _parse(tmp_path, entete_step_log(
        _DEPLOIEMENTS_ATTACHE + _dead("4#1") + _DD_RATE + mouvement + _dead("4#0") + _DD_RATE,
        units=_WEIRDBOY_ATTACHE, ez_vertical_inches=None,
    ))
    assert stats["parse_errors"] == [], stats["parse_errors"]
    assert stats["special_rule_usage"][("deadly_demise", "Boyz")] == {1: 2, 2: 0}
    assert ("deadly_demise", "Boyz") not in stats["special_rule_usage_invalid"]


def test_le_socle_exploseur_compte_meme_deja_sorti_de_la_composition_vivante(tmp_path):
    """Le verdict est vivants ∪ exploseur. Aujourd'hui la ligne `DEAD model=` du moteur ne porte
    pas de `[MODELS:]`, donc le socle reste « vivant » jusqu'au prochain recalage (limite connue
    de `living_datasheets`) et l'union ne se voit pas ; ce journal, grammaticalement légal, retire
    le WeirdBoy sur sa propre ligne DEAD — c'est ce que produirait la levée de cette limite.

    Mutation : ignorer `include_mids` → INVALID 1."""
    weirdboy_mort_recale = "[10:00:02] E1 T1 P2 FIGHT : Unit 4 DEAD model=4#1 reason=combat [MODELS: 4#0@(50,50,z0)] [SUCCESS]\n"
    stats = _parse(tmp_path, entete_step_log(
        _DEPLOIEMENTS_ATTACHE + weirdboy_mort_recale + _DD_EFFET,
        units=_WEIRDBOY_ATTACHE, ez_vertical_inches=None,
    ))
    assert stats["parse_errors"] == [], stats["parse_errors"]
    assert stats["special_rule_usage"][("deadly_demise", "Boyz")] == {1: 1, 2: 0}
    assert ("deadly_demise", "Boyz") not in stats["special_rule_usage_invalid"]
