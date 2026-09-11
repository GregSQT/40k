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

Le verdict est rendu AU MOMENT DU RELEVÉ (`note_special_rule_usage`), parce que la clé
`(règle, type d'escouade)` du tableau §1.7 ne dit ni QUELLE escouade a joué ni QUAND : jugée a
posteriori sur cette clé, la validité se prononçait sur la composition de DÉPLOIEMENT, unionnée
par type et sur les deux camps.

Ce fichier verrouille les six propriétés :
- la capacité d'un personnage attaché est jugée VALIDE sur l'escouade qui l'utilise ;
- une capacité que ne porte AUCUNE datasheet de l'escouade reste INVALIDE (le contrôle n'est
  pas relâché, c'est le seul point qui compte) ;
- la capacité devient INVALIDE dès que la figurine source est MORTE (19.04) ;
- une escouade attachée ne blanchit pas ses HOMONYMES non attachées ;
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
        # Figurine NATIVE de l'escouade Boyz dont la datasheet n'est pas `Boyz` — comme le
        # sergent ou la variante d'arme spéciale de tout bloc du roster.
        "BoyzNob": {"HP_MAX": 1, "MOVE": 6, "MODEL_HEIGHT": 1.0, "UNIT_RULES": []},
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

#: L'escouade attachée du roster ET une escouade du MÊME TYPE sans personnage : le cas que la
#: composition unionnée par type blanchissait en bloc.
_UNITS_DEUX_ESCOUADES_MEME_TYPE = (
    "[10:00:00] Unit 1 (Boyz) P1: Starting position (20,20), HP_MAX=1 base=round/1 "
    "[MODELS: 1#0@(20,20,z0) 1#1@(20,21,z0)] [MODEL_TYPES: 1#0=Boyz 1#1=PainBoy]\n"
    "[10:00:00] Unit 5 (Boyz) P1: Starting position (24,20), HP_MAX=1 base=round/1 "
    "[MODELS: 5#0@(24,20,z0) 5#1@(24,21,z0)] [MODEL_TYPES: 5#0=Boyz 5#1=Boyz]\n"
    "[10:00:00] Unit 101 (Grunt) P2: Starting position (21,21), HP_MAX=5 base=round/1\n"
)

#: Escouade Boyz dont le seul socle NATIF est un `BoyzNob` (datasheet distincte du type
#: d'escouade), mené par le PainBoy : la composition que `native_alive` du moteur juge vivante
#: alors qu'aucun socle ne porte la datasheet `Boyz`.
_UNITS_NATIF_NON_HOMONYME = (
    "[10:00:00] Unit 1 (Boyz) P1: Starting position (20,20), HP_MAX=1 base=round/1 "
    "[MODELS: 1#0@(20,20,z0) 1#1@(20,21,z0)] [MODEL_TYPES: 1#0=BoyzNob 1#1=PainBoy]\n"
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

#: Le PainBoy (source de la capacité) est retiré AVANT le relevé : le `[MODELS:]` de la ligne
#: DEAD ne liste plus que le socle Boyz, et c'est lui que `_resync_living_models` retient.
_PAINBOY_MORT = (
    "[10:00:01] E1 T1 P2 SHOOT : Unit 1 DEAD model=1#1 reason=combat "
    "[MODELS: 1#0@(20,20,z0)] [SUCCESS]\n"
)

#: MÊME mort du PainBoy, mais l'escouade compte aussi une figurine RENDUE
#: (`apply_returned_models_placement`, engine/phase_handlers/command_handlers.py) : elle entre
#: dans `[MODELS:]` avec un id neuf `1#r0` qu'aucune entête ne déclare, donc de datasheet
#: inconnue. Format observé sur le run du 2026-09-11 (`101#r0@(21,21,z0)`).
_PAINBOY_MORT_AVEC_SOCLE_RENDU = (
    "[10:00:01] E1 T1 P2 SHOOT : Unit 1 DEAD model=1#1 reason=combat "
    "[MODELS: 1#0@(20,20,z0) 1#r0@(20,21,z0)] [SUCCESS]\n"
)

#: Relevé par l'escouade 5 (Boyz sans personnage), même type que l'escouade attachée 1.
_HOLD_STILL_UNITE_5 = (
    "[10:00:02] E1 T1 P1 FIGHT : Unit 101(21,21) SUFFERS 3 Mortal Wounds "
    "[HOLD STILL AND SAY AARGH] MW:1,2 [FROM:5] [R:+0.0] [SUCCESS]\n"
)


def _parse(tmp_path, monkeypatch, units: str, rule_to_units, body: str = _HOLD_STILL):
    import ai.analyzer as an
    import ai.analyzer_config as ac_mod

    cfg = fab_config(
        unit_registry=_Registry(), unit_weapons_cache={}, rule_to_units=rule_to_units
    )
    monkeypatch.setattr(ac_mod, "load_analyzer_config", lambda: cfg)

    log = tmp_path / "step.log"
    log.write_text(entete_step_log(
        body,
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


def test_capacite_de_la_source_morte_devient_invalide(tmp_path, monkeypatch):
    """19.04 : « until the source of that ability/rule is destroyed ».

    Le PainBoy est retiré au tour 1, l'escouade relève la capacité ensuite : le moteur ne devrait
    plus l'appliquer (`compute_unit_rules_in_effect` ne reçoit plus sa source dans
    `alive_attached_sources`), donc §1.7 doit compter la faute. Jugée sur la composition de
    DÉPLOIEMENT, elle était affichée OK.
    """
    import ai.analyzer as an

    stats = _parse(
        tmp_path, monkeypatch, _UNITS_ATTACHEE,
        {"mortal_wounds_on_critical_wound": {"PainBoy"}},
        body=_PAINBOY_MORT + _HOLD_STILL,
    )
    assert not stats["parse_errors"], f"aucune erreur de format attendue, got {stats['parse_errors']}"
    assert stats["special_rule_usage"][("mortal_wounds_on_critical_wound", "Boyz")][1] == 1, (
        "prémisse : l'usage est bien relevé après la mort du porteur"
    )
    assert an.error_totals(stats)["special_rules_invalid"] == 1, (
        "capacité utilisée après la mort de sa source : 19.04 ne la propage plus"
    )


def test_une_escouade_attachee_ne_blanchit_pas_son_homonyme(tmp_path, monkeypatch):
    """Deux escouades du même type, une seule menée par le personnage porteur.

    L'escouade 5 n'a jamais eu de PainBoy : son usage est une faute, que la composition
    unionnée par TYPE (`{Boyz, PainBoy}`) déclarait valide.
    """
    import ai.analyzer as an

    stats = _parse(
        tmp_path, monkeypatch, _UNITS_DEUX_ESCOUADES_MEME_TYPE,
        {"mortal_wounds_on_critical_wound": {"PainBoy"}},
        body=_HOLD_STILL + _HOLD_STILL_UNITE_5,
    )
    assert not stats["parse_errors"], f"aucune erreur de format attendue, got {stats['parse_errors']}"
    assert stats["special_rule_usage"][("mortal_wounds_on_critical_wound", "Boyz")][1] == 2, (
        "prémisse : les deux escouades relèvent la MÊME clé (règle, type)"
    )
    assert an.error_totals(stats)["special_rules_invalid"] == 1, (
        "seul l'usage de l'escouade sans PainBoy est une faute"
    )
    assert stats["special_rule_usage_invalid"][
        ("mortal_wounds_on_critical_wound", "Boyz")
    ][1] == 1


def test_socle_rendu_de_datasheet_inconnue_suspend_le_verdict(tmp_path, monkeypatch):
    """19.04 : « Should those models later be revived, those abilities will once more apply ».

    Une figurine rendue reçoit un id `1#r0` absent de `[MODEL_TYPES:]` : sa datasheet est
    inconnue, donc l'analyzer ne peut pas dire si la source est de retour. Il s'abstient — la
    compter INVALID accuserait le moteur d'une faute que la règle lui permet, et une escouade
    dont tous les survivants sont des socles rendus verrait TOUS ses usages comptés fautifs.
    """
    import ai.analyzer as an

    stats = _parse(
        tmp_path, monkeypatch, _UNITS_ATTACHEE,
        {"mortal_wounds_on_critical_wound": {"PainBoy"}},
        body=_PAINBOY_MORT_AVEC_SOCLE_RENDU + _HOLD_STILL,
    )
    assert not stats["parse_errors"], f"aucune erreur de format attendue, got {stats['parse_errors']}"
    assert stats["special_rule_usage"][("mortal_wounds_on_critical_wound", "Boyz")][1] == 1, (
        "prémisse : l'usage est bien relevé, socle rendu présent"
    )
    assert an.error_totals(stats)["special_rules_invalid"] == 0, (
        "datasheet du socle rendu inconnue : abstention, pas une faute inventée"
    )


def test_regle_de_la_datasheet_d_escouade_reste_valide(tmp_path, monkeypatch):
    """La règle déclarée par la datasheet de l'ESCOUADE n'est jamais jugée sur les datasheets
    vivantes : son échéance 19.04 est la mort du dernier socle du BLOC bodyguard, et le journal
    ne dit pas quel socle est natif. Le moteur applique `own_rules` dès qu'une native vit
    (`native_alive`) : exiger `Boyz` parmi les datasheets vivantes serait PLUS STRICT que la
    règle pour une escouade réduite à son sergent.

    Mise en scène : le seul socle vivant est un `BoyzNob`, le PainBoy est mort, et la capacité
    est déclarée sur `Boyz` — donc sur AUCUNE datasheet vivante."""
    import ai.analyzer as an

    stats = _parse(
        tmp_path, monkeypatch, _UNITS_NATIF_NON_HOMONYME,
        {"mortal_wounds_on_critical_wound": {"Boyz"}},
        body=_PAINBOY_MORT + _HOLD_STILL,
    )
    assert stats["special_rule_usage"][("mortal_wounds_on_critical_wound", "Boyz")][1] == 1, (
        "prémisse : l'usage est relevé sur l'escouade réduite à son Nob"
    )
    assert an.error_totals(stats)["special_rules_invalid"] == 0


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
    from ai.analyzer_rules import special_rule_usage_is_valid

    presentes = {"Boyz", "PainBoy"}
    assert special_rule_usage_is_valid(
        "mortal_wounds_on_critical_wound", "Boyz", presentes,
        {"mortal_wounds_on_critical_wound": {"PainBoy"}},
    )
    assert not special_rule_usage_is_valid(
        "leader", "Boyz", presentes, {"leader": {"PainBoy"}}
    ), "un marqueur de rôle ne se propage jamais du personnage à son escouade"
    assert special_rule_usage_is_valid(
        "leader", "PainBoy", presentes, {"leader": {"PainBoy"}}
    ), "le porteur lui-même garde son marqueur de rôle"
