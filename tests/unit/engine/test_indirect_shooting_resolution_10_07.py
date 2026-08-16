"""10.07 — résolution du tir indirect : plancher d'échec, couvert octroyé, relances interdites.

Ce que le PDF 10 §10.07 dit, et que ce fichier vérifie attaque par attaque :

    ▪ The target has the benefit of cover against that attack (13.08).
    ▪ You cannot re-roll hit rolls.
    ▪ An unmodified hit roll of 1-5 fails, unless your unit remained stationary this turn and
      the target is visible to one or more friendly units, in which case an unmodified hit roll
      of 1-3 fails instead.

⚠️ LE POINT QUI A ÉTÉ COMPRIS DE TRAVERS DEUX FOIS avant d'être lu correctement : ce n'est ni
un « -1 à la touche » ni un « seuil substitué ». C'est un PLANCHER sur le dé NON MODIFIÉ, qui
s'insère dans la table 05.01 à la place de « unmodified 1 → FAILS ». Il se compose donc avec la
CT par un `max`, et la ligne « unmodified 6 → CRITICAL HIT » reste au-dessus de lui. D'où les
deux cas que ce fichier discrimine explicitement :

  - sans spotter, plancher 6 → seul un 6 touche, **quel que soit le BS** (6+ dur) ;
  - avec spotter, plancher 4 → ce n'est PAS un 4+ plat : un BS 5+ touche toujours sur 5+.

Le second est le test qui distingue une implémentation correcte d'une implémentation qui aurait
simplement écrit `hit_target = 4`.
"""
from __future__ import annotations

import pytest

from engine.phase_handlers.attack_sequence import (
    NATURAL_FAIL_ROLL,
    RerollProfile,
    WeaponAttackProfile,
    _evaluate_roll,
    roll_attack_pool,
)
from engine.phase_handlers.shared_utils import (
    INDIRECT_FAIL_BELOW,
    INDIRECT_FAIL_BELOW_SPOTTED,
    _squad_remained_stationary,
)


# ─────────────────────────────────────────────────────────────────────────────
# La table 05.01 généralisée — le cœur de la règle
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("roll", [1, 2, 3, 4, 5, 6])
def test_le_plancher_par_defaut_est_exactement_l_ancien_comportement(roll):
    """`fail_below` vaut 2 par défaut, ce qui est mot pour mot `roll != 1`.

    C'est ce qui garantit qu'aucune des attaques du jeu n'a changé en généralisant la table :
    la preuve tient sur les six faces, pas sur un argument."""
    crit, success = _evaluate_roll(roll, crit_on=6, target=3)
    attendu = crit or (roll != NATURAL_FAIL_ROLL and roll >= 3)

    assert success is attendu


@pytest.mark.parametrize("roll,touche", [(1, False), (2, False), (3, False),
                                         (4, False), (5, False), (6, True)])
def test_sans_spotter_seul_un_six_touche_quel_que_soit_le_bs(roll, touche):
    """Plancher 6 sur un BS 2+ : le meilleur tireur du jeu ne touche que sur 6.

    Un modèle « seuil substitué » donnerait le même résultat ici ; c'est le test suivant qui
    les sépare. Celui-ci fixe le 6+ DUR, y compris le fait qu'un 6 touche toujours (05.01,
    deuxième ligne) alors même que le plancher vaut 6."""
    _, success = _evaluate_roll(roll, crit_on=6, target=2, fail_below=INDIRECT_FAIL_BELOW)

    assert success is touche


@pytest.mark.parametrize("bs,roll,touche", [
    # BS 3+ : le plancher 4 mord (un 3 toucherait sans lui).
    (3, 3, False), (3, 4, True), (3, 5, True), (3, 6, True),
    # BS 5+ : c'est LE cas discriminant. Le plancher n'améliore RIEN — un 4 ne touche pas,
    # parce que la ligne « >= BS » de 05.01 s'applique après lui. Une implémentation qui aurait
    # écrit `hit_target = 4` ferait toucher ce 4, et ce test le prendrait.
    (5, 3, False), (5, 4, False), (5, 5, True), (5, 6, True),
])
def test_avec_spotter_le_plancher_4_ne_remplace_pas_la_ct(bs, roll, touche):
    """Plancher 4 = `max(BS, 4)`, jamais « touche sur 4+ »."""
    _, success = _evaluate_roll(
        roll, crit_on=6, target=bs, fail_below=INDIRECT_FAIL_BELOW_SPOTTED,
    )

    assert success is touche


def test_le_plancher_ne_prime_pas_sur_la_touche_critique():
    """05.01 teste « unmodified 6 → CRITICAL HIT » AVANT « >= BS ». Un 6 touche donc sous
    n'importe quel plancher — c'est ce qui rend le 6+ de 10.07 atteignable."""
    crit, success = _evaluate_roll(6, crit_on=6, target=2, fail_below=INDIRECT_FAIL_BELOW)

    assert (crit, success) == (True, True)


def test_le_plancher_ne_touche_que_le_jet_de_touche():
    """10.07 ne parle que des jets de TOUCHE. Une arme sous plancher 6 blesse et sauvegarde
    normalement — vérifié sur le socle de résolution, pas sur `_evaluate_roll` seul.

    Dés scriptés : touche 6 (passe le plancher), blessure 2 (échouerait sous un plancher 6,
    réussit sur un seuil de 2+), sauvegarde 1."""
    des = iter([6, 2, 1])
    rolled = roll_attack_pool(
        n_attacks=1, hit_target=3, wound_target=2, save_threshold_value=4,
        profile=WeaponAttackProfile(), rerolls=RerollProfile(),
        roll_d6=lambda: next(des), hit_fail_below=INDIRECT_FAIL_BELOW,
    )

    rec = rolled["shot_records"][0]
    assert rec["hitResult"] == "HIT"
    assert rec["strengthResult"] == "SUCCESS", (
        "un plancher de TOUCHE ne doit pas faire échouer une blessure de 2 sur un seuil de 2+"
    )


def test_le_plancher_s_applique_aussi_au_de_de_relance():
    """Une relance qui échapperait au plancher rendrait la règle contournable par une capacité.

    Ce test n'est atteignable que par un chemin où la relance existe encore — il vaut donc pour
    les relances de touche autres que celles interdites par 10.07 elles-mêmes, et il fixe la
    règle au niveau du socle : le plancher qualifie LE JET, pas son rang."""
    des = iter([1, 5])  # 1 → relancé par hit_1 → 5, qui reste sous le plancher 6
    rolled = roll_attack_pool(
        n_attacks=1, hit_target=2, wound_target=2, save_threshold_value=4,
        profile=WeaponAttackProfile(), rerolls=RerollProfile(hit_1=True),
        roll_d6=lambda: next(des), hit_fail_below=INDIRECT_FAIL_BELOW,
    )

    rec = rolled["shot_records"][0]
    assert rec["hitResult"] == "MISS", "le dé de relance subit le plancher comme le premier"
    assert rec["attackRollInitial"] == 1, "la relance a bien eu lieu (sinon le test est vacant)"


# ─────────────────────────────────────────────────────────────────────────────
# « remained stationary » — plus fort que « n'a pas avancé »
# ─────────────────────────────────────────────────────────────────────────────

def _gs_moved(distance):
    return {
        "models_cache": {"1#0": {"id": "1#0"}},
        "squad_models": {"1": ["1#0"]},
        "moved_distance_by_model": {"1#0": distance},
        "inches_to_subhex": 5,
    }


def test_immobile_exige_zero_deplacement():
    """Le piège nommé par la spec : « remained stationary » n'est pas « n'a pas fait d'advance ».

    Une unité qui s'est repositionnée de 1" reste éligible au tir indirect (10.07 n'exclut que
    l'advance) mais perd le plancher de 4+. Confondre les deux donnerait le meilleur seuil à une
    unité qui a bougé."""
    assert _squad_remained_stationary(_gs_moved(0.0), "1") is True
    assert _squad_remained_stationary(_gs_moved(5.0), "1") is False, (
        "1\" de déplacement (5 sous-hexes) ferme le plancher de 4+"
    )


def test_une_figurine_morte_ne_rend_pas_l_escouade_mobile():
    """Même convention que la clause 3 de [HEAVY] : une figurine détruite ne tire plus, sa
    distance ne compte pas. Sans ça, une escouade immobile perdrait son plancher parce qu'un
    socle mort avait bougé avant de mourir.

    ⚠️ Écrit d'abord sans inscrire la figurine morte dans `squad_models`, ce test ne prouvait
    rien : la boucle ne la parcourait même pas, et la mutation qui retire le filtre le laissait
    VERT. Une figurine détruite reste dans `squad_models` — c'est `models_cache` qu'elle quitte.
    """
    gs = _gs_moved(0.0)
    gs["squad_models"]["1"] = ["1#0", "1#9"]
    gs["moved_distance_by_model"]["1#9"] = 40.0  # a bougé, puis est morte
    assert "1#9" not in gs["models_cache"], "prémisse : elle est bien retirée du cache"

    assert _squad_remained_stationary(gs, "1") is True
