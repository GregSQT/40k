"""Socle de sequence d attaque + regles d armes de la boucle (PDF 05 + PDF 24).

Verrouille `engine/phase_handlers/attack_sequence.py`, source UNIQUE des jets tir ET melee :
- 05.01 : 1 non modifie rate toujours ; 6 non modifie = touche CRITIQUE (touche meme sous BS).
- 05.02 : 1 non modifie rate toujours ; critique = blessure meme sous le seuil.
- [TORRENT] 24.37       : touche automatique, aucun de de touche, jamais critique.
- [SUSTAINED HITS] 24.36: touche critique -> X touches ADDITIONNELLES (pas des attaques).
- [LETHAL HITS] 24.23   : touche critique -> blessure automatique si c est le meilleur choix.
- [TWIN-LINKED] 24.38   : relance du de de blessure.
- [ANTI-X Y+] 24.03     : blessure critique sur Y+ si la cible a le keyword X.
- [DEVASTATING WOUNDS] 24.10 : blessure critique -> flag mortelle (consomme a l allocation).

Chaque test pilote les des par une SEQUENCE explicite (aucun aleatoire) : la valeur de chaque
de est donc lisible dans le test, et l ordre des tirages (touche -> blessure -> sauvegarde)
est verrouille par construction.
"""
import pytest

from engine.phase_handlers.attack_sequence import (
    RerollProfile,
    WeaponAttackProfile,
    build_weapon_attack_profile,
    lethal_hits_auto_wound_is_better,
    roll_attack_pool,
    unit_keywords_upper,
)


def _dice(values):
    """Des scriptes : chaque appel consomme la valeur suivante ; epuisement = erreur explicite."""
    seq = list(values)

    def _roll():
        if not seq:
            raise AssertionError("plus de des disponibles : la sequence de tirages a change")
        return seq.pop(0)

    return _roll


def _weapon(rules, **extra):
    w = {"WEAPON_RULES": list(rules), "display_name": "W", "NB": 1, "ATK": 3,
         "STR": 4, "AP": 0, "DMG": 1}
    w.update(extra)
    return w


def _roll(dice, *, n=1, hit=3, wound=4, save_th=3, profile=None, rerolls=None):
    return roll_attack_pool(
        n_attacks=n, hit_target=hit, wound_target=wound, save_threshold_value=save_th,
        profile=profile or WeaponAttackProfile(),
        rerolls=rerolls or RerollProfile(),
        roll_d6=_dice(dice),
    )


# --------------------------------------------------------------------------- socle 05.01/05.02

def test_un_non_modifie_rate_toujours_a_la_touche():
    """05.01 : un 1 rate meme si le seuil de touche est 1 (cas d un bonus qui descendrait a 1)."""
    out = _roll([1], hit=1)
    assert out["counts"] == {"attacks": 1, "hits": 0, "wounds": 0}
    assert out["shot_records"][0]["hitResult"] == "MISS"


def test_six_non_modifie_touche_meme_sous_le_seuil():
    """05.01 : la touche critique est une touche, meme avec un seuil inatteignable (7)."""
    out = _roll([6, 6, 4], hit=7)
    assert out["counts"]["hits"] == 1
    assert out["shot_records"][0]["criticalHit"] is True


def test_un_non_modifie_rate_toujours_a_la_blessure():
    """05.02 : un 1 au jet de blessure echoue meme si le seuil vaut 1."""
    out = _roll([4, 1], wound=1)
    assert out["counts"]["wounds"] == 0
    assert out["shot_records"][0]["strengthResult"] == "FAILED"


def test_six_non_modifie_blesse_meme_sous_le_seuil():
    """05.02 : la blessure critique blesse, meme avec un seuil inatteignable (7)."""
    out = _roll([4, 6, 4], wound=7)
    assert out["counts"]["wounds"] == 1
    assert out["shot_records"][0]["criticalWound"] is True


# ------------------------------------------------------------------------------------ TORRENT

def test_torrent_touche_sans_jeter_de_de():
    """24.37 : aucun de de touche n est consomme -> le 1er de va au jet de blessure."""
    profile = WeaponAttackProfile(torrent=True)
    out = _roll([5, 4], profile=profile)  # 5 = blessure, 4 = sauvegarde
    rec = out["shot_records"][0]
    assert out["counts"] == {"attacks": 1, "hits": 1, "wounds": 1}
    assert rec["autoHit"] is True and rec["attackRoll"] is None
    assert "criticalHit" not in rec  # un auto-hit n est jamais critique


def test_sans_torrent_le_premier_de_est_la_touche():
    """Contre-epreuve : la meme sequence sans TORRENT rate la touche (1 = echec)."""
    out = _roll([1, 4])
    assert out["counts"]["hits"] == 0


# ----------------------------------------------------------------------------- SUSTAINED HITS

def test_sustained_hits_ajoute_x_touches_sur_critique():
    """24.36 : une touche critique avec [SUSTAINED HITS 2] donne 3 touches au total."""
    profile = WeaponAttackProfile(sustained_hits=2)
    # 6 (crit) puis 3 couples (blessure, sauvegarde) pour les 3 touches.
    out = _roll([6, 5, 4, 5, 4, 5, 4], profile=profile)
    assert out["counts"] == {"attacks": 1, "hits": 3, "wounds": 3}
    extras = [r for r in out["shot_records"] if r.get("sustainedHit")]
    assert len(extras) == 2
    assert all(r["attackRoll"] is None for r in extras)


def test_sustained_hits_ne_declenche_pas_sur_touche_normale():
    """24.36 : seule une touche CRITIQUE declenche les touches additionnelles."""
    profile = WeaponAttackProfile(sustained_hits=2)
    out = _roll([5, 5, 4], profile=profile)
    assert out["counts"]["hits"] == 1


def test_sustained_hits_additionnelle_ne_peut_pas_recritiquer():
    """Une touche additionnelle n est pas une attaque : elle ne redeclenche pas SUSTAINED."""
    profile = WeaponAttackProfile(sustained_hits=1)
    out = _roll([6, 1, 6, 4], profile=profile)  # crit, blessure ratee, blessure 6, save
    assert out["counts"]["hits"] == 2  # et pas 3


# -------------------------------------------------------------------------------- LETHAL HITS

def test_lethal_hits_blessure_automatique_sur_critique():
    """24.23 : sans DEVASTATING, la touche critique blesse d office (aucun de de blessure)."""
    profile = WeaponAttackProfile(lethal_hits=True)
    out = _roll([6, 4], profile=profile)  # 6 = crit, 4 = sauvegarde (pas de de de blessure)
    rec = out["shot_records"][0]
    assert out["counts"]["wounds"] == 1
    assert rec["lethalHit"] is True and rec["strengthRoll"] is None
    assert "criticalWound" not in rec  # une blessure automatique n est jamais critique


def test_lethal_hits_arbitrage_devastating_prefere_le_jet_quand_il_paie():
    """24.23 (Designer's Note) : avec DEVASTATING et une cible bien protegee, jeter le de
    de blessure vaut mieux que la blessure automatique (le critique ignore la sauvegarde)."""
    profile = WeaponAttackProfile(lethal_hits=True, devastating=True)
    # Sauvegarde 2+ (P(echec)=1/6) et blessure sur 3+ : le jet domine largement l auto.
    assert lethal_hits_auto_wound_is_better(profile, wound_target=3, save_threshold_value=2) is False
    out = _roll([6, 6, 4], profile=profile, wound=3, save_th=2)
    assert out["shot_records"][0]["devastating"] is True


def test_lethal_hits_arbitrage_devastating_prefere_l_auto_quand_il_paie():
    """Cible sans sauvegarde utile + blessure difficile : l auto-blessure domine le jet."""
    profile = WeaponAttackProfile(lethal_hits=True, devastating=True)
    assert lethal_hits_auto_wound_is_better(profile, wound_target=6, save_threshold_value=7) is True


def test_lethal_hits_sans_devastating_toujours_auto():
    """Sans DEVASTATING, l auto-blessure ne perd jamais rien : elle est toujours choisie."""
    profile = WeaponAttackProfile(lethal_hits=True)
    for wound_target in range(2, 7):
        for save_th in range(2, 8):
            assert lethal_hits_auto_wound_is_better(profile, wound_target, save_th) is True


# -------------------------------------------------------------------------------- TWIN-LINKED

def test_twin_linked_relance_le_de_de_blessure_rate():
    """24.38 : la blessure ratee est relancee une fois ; la relance reussie compte."""
    profile = WeaponAttackProfile(twin_linked=True)
    out = _roll([4, 2, 5, 4], profile=profile, wound=4)  # touche, blessure 2 (ratee), relance 5, save
    assert out["counts"]["wounds"] == 1


def test_twin_linked_ne_relance_pas_deux_fois():
    """Un de ne se relance qu une fois : la 2e valeur ratee reste un echec."""
    profile = WeaponAttackProfile(twin_linked=True)
    out = _roll([4, 2, 2], profile=profile, wound=4)
    assert out["counts"]["wounds"] == 0


def test_sans_twin_linked_pas_de_relance():
    """Contre-epreuve : la meme sequence sans TWIN-LINKED s arrete sur l echec."""
    out = _roll([4, 2, 5, 4], wound=4)
    assert out["counts"]["wounds"] == 0


# ------------------------------------------------------------------- VERROUS jets AVANT relance
# Le combat log affiche « initial->final ». Sans le de d'origine, une relance est indiscernable
# d un jet direct : un 2 relance en 5 s affiche « (5) », comme un 5 du premier coup. Le jumeau
# `attackRollInitial` est verrouille cote touche (test_faction_abilities.py, relance d Oath) ;
# ces deux-ci fermaient un trou : ils n etaient tenus par AUCUN test Python, seulement par le
# rendu du navigateur. Les supprimer du moteur laissait pytest, pyright et biome verts.

def test_verrou_le_jet_de_blessure_avant_relance_est_conserve():
    """`strengthRollInitial` : la relance TWIN-LINKED garde le de d origine."""
    profile = WeaponAttackProfile(twin_linked=True)
    out = _roll([4, 2, 5, 4], profile=profile, wound=4)  # touche, blessure 2 ratee, relance 5, save

    rec = out["shot_records"][0]
    assert rec["strengthRoll"] == 5, "le champ courant porte le jet FINAL"
    assert rec["strengthRollInitial"] == 2, "le jet d origine doit rester lisible"
    assert rec["woundRerollCause"] == "twin_linked"


def test_verrou_pas_de_jet_initial_sans_relance_de_blessure():
    """Contre-epreuve : sans relance, la clef est ABSENTE — jamais posee a None."""
    rec = _roll([4, 5, 4], wound=4)["shot_records"][0]

    assert rec["strengthRoll"] == 5
    assert "strengthRollInitial" not in rec
    assert "woundRerollCause" not in rec


def test_verrou_le_jet_de_sauvegarde_avant_relance_est_conserve():
    """`saveRollInitial` : `save_1` relance le 1 de sauvegarde, le de d origine est garde.

    Seule jambe SANS enum de cause (un unique declencheur), donc ce champ est le seul temoin
    de la relance : le retirer rend la relance de sauvegarde totalement muette dans le log.
    """
    out = _roll([4, 5, 1, 4], rerolls=RerollProfile(save_1=True), save_th=3)

    rec = out["shot_records"][0]
    assert rec["saveRoll"] == 4, "le champ courant porte le jet FINAL"
    assert rec["saveRollInitial"] == 1, "le 1 relance doit rester lisible"


def test_verrou_pas_de_jet_initial_sans_relance_de_sauvegarde():
    """Contre-epreuve : `save_1` arme mais aucun 1 jete -> aucune relance, clef absente."""
    rec = _roll([4, 5, 4], rerolls=RerollProfile(save_1=True), save_th=3)["shot_records"][0]

    assert rec["saveRoll"] == 4
    assert "saveRollInitial" not in rec


# --------------------------------------------------------------------------------------- ANTI

def test_anti_abaisse_le_seuil_de_blessure_critique_si_keyword_present():
    """24.03 : [ANTI-INFANTRY 4+] contre une cible INFANTRY -> critique des 4."""
    weapon = _weapon(["ANTI_INFANTRY:4"])
    target = {"UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}]}
    profile = build_weapon_attack_profile(weapon, target)
    assert profile.crit_wound_on == 4


def test_anti_sans_le_keyword_ne_s_applique_pas():
    """24.03 : contre une cible sans le keyword X, le seuil critique reste 6."""
    weapon = _weapon(["ANTI_INFANTRY:4"])
    target = {"UNIT_KEYWORDS": [{"keywordId": "VEHICLE"}]}
    assert build_weapon_attack_profile(weapon, target).crit_wound_on == 6


def test_anti_duplique_prend_le_seuil_le_plus_bas_applicable():
    """24.02 : instances multiples non cumulatives -> on choisit la meilleure applicable."""
    weapon = _weapon(["ANTI_INFANTRY:4", "ANTI_VEHICLE:2"])
    target = {"UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}, {"keywordId": "VEHICLE"}]}
    assert build_weapon_attack_profile(weapon, target).crit_wound_on == 2


def test_anti_sans_parametre_leve():
    """Aucun repli masquant : [ANTI] sans seuil Y+ est une donnee invalide -> erreur."""
    weapon = _weapon(["ANTI_INFANTRY"])
    target = {"UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}]}
    with pytest.raises(ValueError):
        build_weapon_attack_profile(weapon, target)


def test_anti_declenche_devastating_sur_le_seuil_abaisse():
    """Composition : [ANTI-INFANTRY 4+] + [DEVASTATING WOUNDS] -> un 4 devient mortelle."""
    weapon = _weapon(["ANTI_INFANTRY:4", "DEVASTATING_WOUNDS"])
    target = {"UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}]}
    profile = build_weapon_attack_profile(weapon, target)
    out = _roll([4, 4, 4], profile=profile, wound=5)  # blessure 4 : echec normal, mais critique ANTI
    assert out["counts"]["wounds"] == 1
    assert out["shot_records"][0]["devastating"] is True


def test_keywords_union_normalises():
    """Les keywords sont normalises (majuscules, espaces/tirets -> _) et unifies unite+faction."""
    unit = {"UNIT_KEYWORDS": [{"keywordId": "Adeptus Astartes"}], "FACTION_KEYWORDS": ["anti-tank"]}
    assert unit_keywords_upper(unit) == frozenset({"ADEPTUS_ASTARTES", "ANTI_TANK"})


# ------------------------------------------------------------------- profil construit des armes

def test_profil_lit_toutes_les_regles_de_la_boucle():
    weapon = _weapon(["TORRENT", "SUSTAINED_HITS:2", "LETHAL_HITS", "TWIN_LINKED",
                      "DEVASTATING_WOUNDS"])
    profile = build_weapon_attack_profile(weapon, None)
    assert (profile.torrent, profile.sustained_hits, profile.lethal_hits,
            profile.twin_linked, profile.devastating) == (True, 2, True, True, True)


def test_profil_arme_nue_est_neutre():
    profile = build_weapon_attack_profile(_weapon([]), None)
    assert profile == WeaponAttackProfile()
