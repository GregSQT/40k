"""[TARGET_DECL:N] corrige §1.2 portée quand les positions de la cible sont incomplètes.

Régression verrouillée (2026-08-19).

MÉCANISME. Après fix 2 (purge des entrées périmées dans dead_model_positions_episode),
des modèles tués dans une activation précédente disparaissent de la reconstruction. Si l'un
d'eux était le plus proche du tireur, l'analyzer ne le voit plus → mesure la distance au
survivant le plus proche, potentiellement hors portée → faux out_of_range.

FIX. Le moteur loge [TARGET_DECL:N] dans la ligne SHOT avec l'effectif de la cible au
Select Targets step. L'analyzer passe cette valeur comme alive_override à freeze_select_targets.
Quand len(positions) < alive_override, certains socles vivants n'ont pas de position connue :
le plus proche aurait peut-être légalisé le tir → shoot_range_unverifiable, pas out_of_range.

CE QUE CE TEST CONSTRUIT. Un log où la cible n'a qu'un socle (T#1, à 32 hex du tireur)
dans positions_by_model, mais le token [TARGET_DECL:2] indique que le moteur en voyait 2.
Le deuxième (T#0, à 12 hex) manque — exactement ce que fix 2 produit quand l'entrée périmée
est purgée. Un weapon range de 24 hex déclenche le cas.

AVANT le fix : alive=1, len(models)=1, pas de garde → out_of_range (violation).
APRÈS le fix : alive_override=2, len(models)=1 < 2 → shoot_range_unverifiable (pas de violation).

Verrou prouvé par mutation : retirer `alive_override` de freeze_select_targets (utiliser None
à la place) → le cas bascule de unverifiable à out_of_range → ROUGE.
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log

SHOOTER = (10, 20)
TARGET_ANCHOR = (22, 20)

# T#0 serait à 12 hex (dans les 24" du Sternguard Bolt Rifle) mais il est absent de positions_by_model.
# T#1 est à 32 hex (hors portée) et c'est le seul socle avec une position connue.
T1_POS = (42, 20)

S = f"({SHOOTER[0]},{SHOOTER[1]})"
T_ANCHOR = f"({TARGET_ANCHOR[0]},{TARGET_ANCHOR[1]})"
OBJECTIVES = ";".join(f"(60,{r})" for r in range(40, 46))

# La cible est déployée avec un seul socle (T#1) — T#0 n'est jamais dans [MODELS:].
# Le token [TARGET_DECL:2] dit que le moteur avait 2 socles au SelectTargets.
STEP_LOG_WITH_DECL = entete_step_log(
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{S} DEPLOYED from (-1,-1) to {S} [R:+0.0] "
    f"[MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)] [SUCCESS]\n"
    f"[10:00:02] E1 T1 P2 DEPLOYMENT : Unit 101{T_ANCHOR} DEPLOYED from (-1,-1) to {T_ANCHOR} [R:+0.0] "
    f"[MODELS: 101#1@({T1_POS[0]},{T1_POS[1]},z0)] [SUCCESS]\n"
    # Tir hors portée depuis positions reconstruites, mais [TARGET_DECL:2] indique 2 socles.
    f"[10:00:03] E1 T1 P1 SHOOT : Unit 1{S} [TARGET_DECL:2] SHOT Unit 101{T_ANCHOR} "
    f"with [Sternguard Bolt Rifle] - Hit 4(5+) - Wound 5(4+) - Save 2(5+) - Dmg:0HP [R:+0.0] "
    f"[MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)] [SHOOTER_MODELS: 1#0] [ALLOC_MODEL: 101#1] [SUCCESS]\n",
    inches_to_subhex=1,
    board="cols=44 rows=60",
    hex_radius="13.9",
    margin=5,
    objectives=OBJECTIVES,
    metric_ranged="hex",
    log_grammar=2,
    units=(
        "[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1: Starting position (-1,-1), HP_MAX=2 "
        "base=round/1\n"
        "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 "
        "base=round/1\n"
    ),
)

# Même log sans [TARGET_DECL:N] — comportement avant le fix (anciens logs).
STEP_LOG_WITHOUT_DECL = entete_step_log(
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{S} DEPLOYED from (-1,-1) to {S} [R:+0.0] "
    f"[MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)] [SUCCESS]\n"
    f"[10:00:02] E1 T1 P2 DEPLOYMENT : Unit 101{T_ANCHOR} DEPLOYED from (-1,-1) to {T_ANCHOR} [R:+0.0] "
    f"[MODELS: 101#1@({T1_POS[0]},{T1_POS[1]},z0)] [SUCCESS]\n"
    f"[10:00:03] E1 T1 P1 SHOOT : Unit 1{S} SHOT Unit 101{T_ANCHOR} "
    f"with [Sternguard Bolt Rifle] - Hit 4(5+) - Wound 5(4+) - Save 2(5+) - Dmg:0HP [R:+0.0] "
    f"[MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)] [SHOOTER_MODELS: 1#0] [ALLOC_MODEL: 101#1] [SUCCESS]\n",
    inches_to_subhex=1,
    board="cols=44 rows=60",
    hex_radius="13.9",
    margin=5,
    objectives=OBJECTIVES,
    metric_ranged="hex",
    log_grammar=2,
    units=(
        "[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1: Starting position (-1,-1), HP_MAX=2 "
        "base=round/1\n"
        "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 "
        "base=round/1\n"
    ),
)


def test_target_decl_elimine_faux_out_of_range(tmp_path):
    """VERROU : [TARGET_DECL:2] avec 1 seule position connue → unverifiable, pas out_of_range.

    Le moteur indique 2 socles au SelectTargets. L'analyzer n'en connaît qu'un (à 32 hex,
    hors portée). Le socle manquant aurait pu être le plus proche et légaliser le tir.
    Le contrôle doit suspendre le verdict, pas condamner.

    Mutation de preuve : changer alive_override=None dans freeze_select_targets quand le
    token est présent → shoot_range_unverifiable tombe à 0, out_of_range monte à 1 → ROUGE.
    """
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(STEP_LOG_WITH_DECL)
    stats = an.parse_step_log(str(log))
    assert stats["shoot_invalid"][1]["out_of_range"] == 0, (
        "[TARGET_DECL:2] avec 1 position connue : le tir est peut-être légal (socle T#0 "
        "manquant pourrait être à portée) — doit être unverifiable, pas out_of_range"
    )
    assert stats["shoot_range_unverifiable"][1] == 1, (
        "quand alive_override=2 et len(positions)=1 < 2, le garde doit marquer unverifiable"
    )


def test_sans_target_decl_comportement_inchange(tmp_path):
    """Sans [TARGET_DECL:N], le comportement est identique à l'état pré-fix (pas de régression).

    Le même log sans le token : alive reconstruit = 1, len(models) = 1, garde ne se déclenche
    pas → out_of_range normal (le tir semble vraiment hors portée depuis l'état reconstruit).
    """
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(STEP_LOG_WITHOUT_DECL)
    stats = an.parse_step_log(str(log))
    assert stats["shoot_invalid"][1]["out_of_range"] == 1, (
        "sans [TARGET_DECL:N], alive=1=len(models) : le garde ne se déclenche pas → out_of_range"
    )
    assert stats["shoot_range_unverifiable"][1] == 0
