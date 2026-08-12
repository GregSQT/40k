"""La priorité de ciblage se juge sur les blessés d'AVANT le tir, pas d'après.

`stats['wounded_enemies']` est muté par `_apply_damage_and_handle_death`, que `analyzer_core`
appelle AVANT d'aiguiller la ligne vers son handler. La cible y ENTRE quand le tir qu'on juge la
blesse, et en SORT quand il l'achève. Lu tel quel, le contrôle rendait deux verdicts faux en sens
inverse — et c'est un compteur publié au rapport (§ TARGET PRIORITY).

Même famille que le gel du Select Targets step (2026-08-12), sur un set de `stats` que la géométrie
ne couvrait pas.
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log

OBJECTIVES = ";".join(f"(60,{r})" for r in range(40, 46))

# Board x1, tout le monde en ligne de vue, personne engagé : seule la priorité est en jeu.
SHOOTER = (10, 20)
FRESH = (14, 20)     # cible intacte
WOUNDED = (18, 20)   # cible que l'on blesse au tour 1

_HEADER = entete_step_log(
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(10,20) DEPLOYED from (-1,-1) to (10,20) [R:+0.0] [MODELS: 1#0@(10,20,z0)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 2(13,20) DEPLOYED from (-1,-1) to (13,20) [R:+0.0] [MODELS: 2#0@(13,20,z0)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(14,20) DEPLOYED from (-1,-1) to (14,20) [R:+0.0] [MODELS: 101#0@(14,20,z0)] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 102(18,20) DEPLOYED from (-1,-1) to (18,20) [R:+0.0] [MODELS: 102#0@(18,20,z0)] [SUCCESS]\n",
    units=(
        "[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
        "[10:00:00] Unit 2 (AssaultIntercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
        "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
        "[10:00:00] Unit 102 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
    ),
    inches_to_subhex=1,
    board="cols=60 rows=60",
    hex_radius="13.9",
    margin=5,
    objectives=OBJECTIVES,
    metric_ranged="hex",
)

_SHOT = (
    "[10:00:0{t}] E1 T{t} P1 SHOOT : Unit 1(10,20) SHOT Unit {target}({tc},20)"
    " with [Sternguard Bolt Rifle] - Hit 4(5+) - Wound 5(4+) - Save 2(5+) - Dmg:{dmg}HP"
    " [R:+0.0] [MODELS: 1#0@(10,20,z0)] [SHOOTER_MODELS: 1#0] [SUCCESS]\n"
)


def _stats(tmp_path, body: str):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(_HEADER + body)
    return an.parse_step_log(str(log))


def test_le_premier_tir_sur_une_cible_intacte_n_est_pas_un_tir_sur_blesse(tmp_path):
    """La cible entre dans `wounded_enemies` À CAUSE de ce tir : elle était intacte au choix.

    Aucun blessé n'existe encore, donc ce tir ne peut être ni une réussite « a visé un blessé »
    ni un échec : le contrôle le classe en réussite par défaut (aucun blessé en vue). Ce qu'on
    verrouille ici, c'est qu'il ne le fasse pas pour la MAUVAISE raison — le compteur d'échecs
    doit rester à zéro, et la suite du test le prouve en le faisant monter.
    """
    stats = _stats(tmp_path, _SHOT.format(t=1, target=102, tc=18, dmg=1))
    assert stats["target_priority"][1]["total_shots"] == 1
    assert stats["target_priority"][1]["shots_at_full_hp_while_wounded_in_los"] == 0


def test_tirer_sur_une_cible_intacte_alors_qu_un_blesse_est_en_vue_est_un_echec(tmp_path):
    """Prémisse : le contrôle voit bien la faute quand elle existe. Sinon rien ne prouve rien."""
    body = (
        _SHOT.format(t=1, target=102, tc=18, dmg=1)   # 102 devient blessé
        + _SHOT.format(t=2, target=101, tc=14, dmg=1)  # on vise l'intacte alors que 102 est blessé
    )
    stats = _stats(tmp_path, body)
    assert stats["target_priority"][1]["shots_at_full_hp_while_wounded_in_los"] == 1


def test_achever_un_blesse_n_est_pas_un_tir_sur_cible_intacte(tmp_path):
    """VERROU de l'autre sens : la cible SORT de `wounded_enemies` quand ce tir la tue.

    Lu après les dégâts, le tir mortel sur 102 — blessé au tour 1, achevé au tour 2 — ressortait
    « a visé du plein PV alors qu'un blessé était en vue », alors qu'il visait précisément le
    blessé.

    Le second blessé (101) est fait EN MÊLÉE, pas au tir : une blessure de tir compterait
    elle-même dans la priorité de ciblage et masquerait l'effet qu'on mesure ici (c'est ce que le
    test précédent verrouille). La mêlée alimente le même set `wounded_enemies` sans passer par
    `target_priority` : le compteur d'échecs doit donc rester à ZÉRO sur ce journal.
    """
    body = (
        # T1 : 102 est visé alors qu'aucun blessé n'existe -> aucune faute possible.
        _SHOT.format(t=1, target=102, tc=18, dmg=1)
        # T1 : l'allié 2 blesse 101 au corps à corps. 101 rejoint les blessés en vue.
        + "[10:00:01] E1 T1 P1 FIGHT : Unit 2(13,20) FOUGHT Unit 101(14,20)"
          " with [Close Combat Weapon] - Hit 5(3+) - Wound 4(4+) - Save 2(3+) - Dmg:1HP"
          " [R:+0.0] [FIGHT_SUBPHASE:fight] [SUCCESS]\n"
        # T2 : on ACHÈVE 102, blessé. C'est le bon choix de cible, pas une faute.
        + _SHOT.format(t=2, target=102, tc=18, dmg=1)
    )
    stats = _stats(tmp_path, body)
    assert stats["target_priority"][1]["total_shots"] == 2
    assert stats["target_priority"][1]["shots_at_full_hp_while_wounded_in_los"] == 0
