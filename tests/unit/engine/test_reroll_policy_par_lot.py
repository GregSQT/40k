"""Politique de relance PAR LOT (decision utilisateur du 2026-09-18, chantier chaine d attaque 100 %).

« You can re-roll the Hit roll » (Oath of Moment) et « you can re-roll the wound roll »
([TWIN-LINKED] 24.38) autorisent la relance de TOUT jet, pas seulement des echecs. Quand un
critique vaut plus qu une reussite ([SUSTAINED HITS] / [LETHAL HITS] cote touche,
[DEVASTATING WOUNDS] cote blessure), relancer une reussite ordinaire est un choix du joueur :
`RerollProfile.hit_non_crit` / `wound_non_crit`. Un critique n est JAMAIS relance ; un de ne se
relance qu une fois (01 Core).

`reroll_policy_choices` dit quand la question a un sens : sans regle sur critique, « echecs
seulement » domine et la question n est pas posee.
"""
from engine.phase_handlers.attack_sequence import (
    RerollProfile,
    WeaponAttackProfile,
    reroll_policy_choices,
    roll_attack_pool,
)


def _dice(values):
    seq = list(values)

    def _roll():
        if not seq:
            raise AssertionError("plus de des disponibles : la sequence de tirages a change")
        return seq.pop(0)

    return _roll


def _roll(dice, *, hit=3, wound=4, profile=None, rerolls=None):
    return roll_attack_pool(
        n_attacks=1, hit_target=hit, wound_target=wound, save_threshold_value=3,
        profile=profile or WeaponAttackProfile(),
        rerolls=rerolls or RerollProfile(),
        roll_d6=_dice(dice),
    )


# ------------------------------------------------------------------------------ touche

def test_touche_non_critique_relancee_sous_la_politique_non_crit():
    """Oath + [SUSTAINED HITS] : une touche reussie ordinaire (4) est relancee ; le 6 obtenu est
    critique et produit la touche additionnelle."""
    profile = WeaponAttackProfile(sustained_hits=1)
    rerolls = RerollProfile(hit_any_fail=True, hit_non_crit=True)
    out = _roll([4, 6, 5, 2, 5, 2], profile=profile, rerolls=rerolls)  # hit 4 -> relance 6 ; 2 blessures + 2 saves
    rec = out["shot_records"][0]
    assert rec["attackRollInitial"] == 4 and rec["attackRoll"] == 6
    assert rec["hitRerollCause"] == "hit_any_fail"
    assert out["counts"]["hits"] == 2


def test_touche_critique_jamais_relancee():
    profile = WeaponAttackProfile(sustained_hits=1)
    rerolls = RerollProfile(hit_any_fail=True, hit_non_crit=True)
    out = _roll([6, 5, 2, 5, 2], profile=profile, rerolls=rerolls)
    assert "attackRollInitial" not in out["shot_records"][0]
    assert out["counts"]["hits"] == 2


def test_politique_par_defaut_ne_relance_pas_une_reussite():
    """Defaut : echecs seulement — la sequence de des est celle d avant le chantier."""
    profile = WeaponAttackProfile(sustained_hits=1)
    rerolls = RerollProfile(hit_any_fail=True)
    out = _roll([4, 5, 2], profile=profile, rerolls=rerolls)
    assert "attackRollInitial" not in out["shot_records"][0]
    assert out["counts"]["hits"] == 1


def test_non_crit_sans_relance_de_tout_jet_ne_relance_rien():
    """`hit_1` ne relance que des 1 : la politique ne peut pas ouvrir une relance absente."""
    profile = WeaponAttackProfile(sustained_hits=1)
    rerolls = RerollProfile(hit_1=True, hit_non_crit=True)
    out = _roll([4, 5, 2], profile=profile, rerolls=rerolls)
    assert "attackRollInitial" not in out["shot_records"][0]


def test_une_relance_de_touche_non_crit_ratee_reste_un_echec():
    """La relance remplace le de : un 2 apres un 4 relance est un echec (un seul reroll)."""
    profile = WeaponAttackProfile(lethal_hits=True)
    rerolls = RerollProfile(hit_any_fail=True, hit_non_crit=True)
    out = _roll([4, 2], profile=profile, rerolls=rerolls)
    assert out["counts"]["hits"] == 0
    assert out["shot_records"][0]["attackRollInitial"] == 4


# ----------------------------------------------------------------------------- blessure

def test_blessure_non_critique_relancee_sous_la_politique_non_crit_twin_linked():
    """[TWIN-LINKED] + [DEVASTATING WOUNDS] : la blessure 5 est relancee ; le 6 est critique et
    devient une blessure mortelle (aucune sauvegarde jetee)."""
    profile = WeaponAttackProfile(twin_linked=True, devastating=True)
    rerolls = RerollProfile(wound_non_crit=True)
    out = _roll([4, 5, 6], profile=profile, rerolls=rerolls)
    rec = out["shot_records"][0]
    assert rec["strengthRollInitial"] == 5 and rec["strengthRoll"] == 6
    assert rec["woundRerollCause"] == "twin_linked"
    assert rec["devastating"] is True
    assert out["pending_wounds"][0]["devastating"] is True


def test_blessure_critique_jamais_relancee():
    profile = WeaponAttackProfile(twin_linked=True, devastating=True)
    rerolls = RerollProfile(wound_non_crit=True)
    out = _roll([4, 6], profile=profile, rerolls=rerolls)
    assert "strengthRollInitial" not in out["shot_records"][0]


def test_politique_par_defaut_twin_linked_ne_relance_pas_une_reussite():
    profile = WeaponAttackProfile(twin_linked=True, devastating=True)
    out = _roll([4, 5, 3], profile=profile)
    rec = out["shot_records"][0]
    assert "strengthRollInitial" not in rec and rec["saveRoll"] == 3


def test_wound_non_crit_via_ability_de_relance_de_tout_echec():
    """`wound_any_fail` (relance de tout jet de blessure) ouvre aussi la politique non-crit."""
    profile = WeaponAttackProfile(devastating=True)
    rerolls = RerollProfile(wound_any_fail=True, wound_non_crit=True)
    out = _roll([4, 5, 6], profile=profile, rerolls=rerolls)
    assert out["shot_records"][0]["woundRerollCause"] == "wound_any_fail"


def test_wound_non_crit_sans_relance_ne_relance_rien():
    profile = WeaponAttackProfile(devastating=True)
    rerolls = RerollProfile(wound_1=True, wound_non_crit=True)
    out = _roll([4, 5, 3], profile=profile, rerolls=rerolls)
    assert "strengthRollInitial" not in out["shot_records"][0]


# ---------------------------------------------------------------------- quand poser la question

def test_question_touche_seulement_si_relance_et_regle_sur_critique():
    assert reroll_policy_choices(WeaponAttackProfile(sustained_hits=1), RerollProfile(hit_any_fail=True))["hit"]
    assert reroll_policy_choices(WeaponAttackProfile(lethal_hits=True), RerollProfile(hit_any_fail=True))["hit"]
    assert not reroll_policy_choices(WeaponAttackProfile(), RerollProfile(hit_any_fail=True))["hit"]
    assert not reroll_policy_choices(WeaponAttackProfile(sustained_hits=1), RerollProfile(hit_1=True))["hit"]
    # [TORRENT] : aucun de de touche, donc rien a relancer.
    assert not reroll_policy_choices(
        WeaponAttackProfile(sustained_hits=1, torrent=True), RerollProfile(hit_any_fail=True)
    )["hit"]


def test_question_blessure_seulement_si_relance_et_devastating():
    assert reroll_policy_choices(WeaponAttackProfile(twin_linked=True, devastating=True), RerollProfile())["wound"]
    assert reroll_policy_choices(WeaponAttackProfile(devastating=True), RerollProfile(wound_any_fail=True))["wound"]
    assert not reroll_policy_choices(WeaponAttackProfile(twin_linked=True), RerollProfile())["wound"]
    assert not reroll_policy_choices(WeaponAttackProfile(devastating=True), RerollProfile(wound_1=True))["wound"]
