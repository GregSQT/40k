"""§1.7 — validité d'un usage de règle dans une escouade ATTACHÉE (règle 19.04).

Mesuré sur le run holdout du 2026-09-11 : `mortal_wounds_on_fight_activation` relevée 90 fois
sur `VanguardVeteranSquadJumpPack` et `mortal_wounds_on_critical_wound` 4 fois sur `Boyz`, les
deux marquées INVALID — soit 4 des 4 erreurs du rapport. Les deux capacités sont déclarées par
le personnage REPLIÉ dans l'escouade (`ChaplainJumpPack`, `PainBoy`), et le journal, lui, nomme
l'escouade de bloc.

Documentation/40k_rules/19 Attached units.pdf §19.04 : « abilities/rules that affect a unit (or
models in it) apply to every model in an attached unit, until the source of that ability/rule is
destroyed ». Les datasheets d'Armageddon le confirment dans les deux sens : VANGUARD VETERAN
SQUAD WITH JUMP PACKS ne porte que « CORE: Deep Strike / FACTION: Oath of Moment / Vanguard
Assault », et BOYZ que « FACTION: Waaagh! / Get da Good Bitz ». Le moteur applique 19.04
(`compute_unit_rules_in_effect`) ; c'est le registre de l'analyzer qui l'ignorait.

Ce fichier verrouille les quatre propriétés du prédicat :
- la capacité d'un personnage attaché est jugée VALIDE sur l'escouade qui l'utilise ;
- une capacité que ne porte AUCUNE datasheet de l'escouade reste INVALIDE (le contrôle n'est
  pas relâché, c'est le seul point qui compte) ;
- un marqueur de RÔLE ne remonte pas au niveau escouade (jumeau de `strip_role_rules`) ;
- sans `[MODEL_TYPES:]`, le verdict retombe sur la datasheet d'escouade — le journal ne déclare
  alors aucune composition.
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log
from tests.unit.ai._fabriques import analyzer_config as fab_config

_OBJECTIVES = ";".join(f"(30,{r})" for r in range(30, 33))


class _Registry:
    units = {
        "Boyz": {"HP_MAX": 1, "MOVE": 6, "MODEL_HEIGHT": 1.0, "UNIT_RULES": []},
        "PainBoy": {"HP_MAX": 3, "MOVE": 6, "MODEL_HEIGHT": 1.0, "UNIT_RULES": []},
        "Grunt": {"HP_MAX": 5, "MOVE": 6, "MODEL_HEIGHT": 1.0, "UNIT_RULES": []},
    }


#: Escouade 1 = Boyz avec un PainBoy replié (19.01), exactement la composition que le journal du
#: run déclare : `Unit 1 (Boyz) … [MODEL_TYPES: … 1#11=PainBoy]`.
_UNITS_ATTACHEE = (
    "[10:00:00] Unit 1 (Boyz) P1: Starting position (20,20), HP_MAX=1 base=round/1 "
    "[MODELS: 1#0@(20,20,z0) 1#1@(20,21,z0)] [MODEL_TYPES: 1#0=Boyz 1#1=PainBoy]\n"
    "[10:00:00] Unit 101 (Grunt) P2: Starting position (21,21), HP_MAX=5 base=round/1\n"
)

#: MÊME escouade, journal SANS `[MODEL_TYPES:]` (grammaire antérieure) : aucune composition
#: déclarée, donc aucun attachement connaissable.
_UNITS_SANS_COMPOSITION = (
    "[10:00:00] Unit 1 (Boyz) P1: Starting position (20,20), HP_MAX=1 base=round/1\n"
    "[10:00:00] Unit 101 (Grunt) P2: Starting position (21,21), HP_MAX=5 base=round/1\n"
)

_HOLD_STILL = (
    "[10:00:02] E1 T1 P1 FIGHT : Unit 101(21,21) SUFFERS 3 Mortal Wounds "
    "[HOLD STILL AND SAY AARGH] MW:1,2 [FROM:1] [R:+0.0] [SUCCESS]\n"
)


def _parse(tmp_path, monkeypatch, units: str, rule_to_units):
    import ai.analyzer as an
    import ai.analyzer_config as ac_mod

    cfg = fab_config(
        unit_registry=_Registry(), unit_weapons_cache={}, rule_to_units=rule_to_units
    )
    monkeypatch.setattr(ac_mod, "load_analyzer_config", lambda: cfg)

    log = tmp_path / "step.log"
    log.write_text(entete_step_log(
        _HOLD_STILL,
        inches_to_subhex=1,
        board="cols=40 rows=40",
        objectives=_OBJECTIVES,
        units=units,
    ))
    return an.parse_step_log(str(log))


def test_capacite_du_personnage_attache_est_valide(tmp_path, monkeypatch):
    """19.04 : le PainBoy replié dans les Boyz confère sa capacité à l'escouade attachée.

    ROUGE avec l'ancien prédicat (`unit_type in rule_to_units[rule_id]`) : l'usage est relevé
    sur `Boyz`, que le registre ne déclare pas porteur → 1 erreur §1.7, celle du run.
    """
    import ai.analyzer as an

    stats = _parse(
        tmp_path, monkeypatch, _UNITS_ATTACHEE,
        {"mortal_wounds_on_critical_wound": {"PainBoy"}},
    )
    assert not stats["parse_errors"], f"aucune erreur de format attendue, got {stats['parse_errors']}"
    assert stats["special_rule_usage"][("mortal_wounds_on_critical_wound", "Boyz")][1] == 1, (
        "l'usage se compte bien sur l'escouade SOURCE nommée par [FROM:]"
    )
    assert an.error_totals(stats)["special_rules_invalid"] == 0, (
        "une capacité conférée par un personnage attaché n'est pas une faute du moteur"
    )


def test_capacite_portee_par_personne_reste_invalide(tmp_path, monkeypatch):
    """Le contrôle n'est PAS relâché : aucune datasheet de l'escouade ne porte la règle."""
    import ai.analyzer as an

    stats = _parse(
        tmp_path, monkeypatch, _UNITS_ATTACHEE,
        # Le porteur déclaré est absent de l'escouade : ni `Boyz` ni `PainBoy`.
        {"mortal_wounds_on_critical_wound": {"WeirdBoy"}},
    )
    assert an.error_totals(stats)["special_rules_invalid"] == 1, (
        "une règle que ne porte aucune figurine de l'escouade doit rester INVALID"
    )


def test_sans_model_types_le_verdict_reste_celui_de_la_datasheet(tmp_path, monkeypatch):
    """Journal sans `[MODEL_TYPES:]` : aucune composition déclarée, donc aucun attachement
    connaissable — le verdict reste celui d'avant ce prédicat, pas un blanchiment par défaut."""
    import ai.analyzer as an

    stats = _parse(
        tmp_path, monkeypatch, _UNITS_SANS_COMPOSITION,
        {"mortal_wounds_on_critical_wound": {"PainBoy"}},
    )
    assert an.error_totals(stats)["special_rules_invalid"] == 1


def test_marqueur_de_role_ne_remonte_pas_a_l_escouade():
    """Jumeau de `strip_role_rules` : `leader` qualifie la FIGURINE (05.04 / 19.02), et le
    moteur le retire des règles de figurine avant l'union 19.04. Le prédicat doit faire pareil,
    sinon l'analyzer déclarerait une escouade entière « leader »."""
    from ai.analyzer import _special_rule_pair_is_valid

    composition = {"Boyz": {"Boyz", "PainBoy"}}
    assert _special_rule_pair_is_valid(
        "mortal_wounds_on_critical_wound", "Boyz", {"mortal_wounds_on_critical_wound": {"PainBoy"}}, composition
    )
    assert not _special_rule_pair_is_valid(
        "leader", "Boyz", {"leader": {"PainBoy"}}, composition
    ), "un marqueur de rôle ne se propage jamais du personnage à son escouade"
    assert _special_rule_pair_is_valid(
        "leader", "PainBoy", {"leader": {"PainBoy"}}, composition
    ), "le porteur lui-même garde son marqueur de rôle"
