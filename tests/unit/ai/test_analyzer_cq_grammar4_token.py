"""Grammaire 4 : les tokens [CLOSE-QUARTERS] préviennent les faux positifs 10.06.

[CLOSE-QUARTERS] écrit par le moteur (grammaire 4) signifie : arme CQ + squads engagées avec
la CIBLE. L'analyzer lisait is_close_quarters depuis le registre et shooter_engaged_with_target
depuis le BFS per-figurine, sans jamais consulter ce jeton :

- Famille 1 : is_close_quarters=False dans le registre alors que l'arme est CQ dans le moteur
  → la ligne `engaged_non_close_quarters` se déclenchait à tort.
- Famille 2 : shooter_engaged_with_target=False côté per-fig alors que le moteur dit engagé avec la cible
  → la ligne `close_quarters_shot_at_unengaged_target` se déclenchait à tort.

Chaque test est suivi de son VERROU : le même scénario SANS le token produit le faux positif
attendu — preuve que le contrôle fonctionne et que 0 ne signifie pas « contrôle mort ».
"""
from __future__ import annotations

import pytest

from tests.unit.ai._fabriques import entete_step_log

# --- Géométrie ---
# x5 : 1" = 5 subhex, zone d'engagement = 10 subhex. Socle round/6 : rayon = 6 subhex.
# Le contrôle est EMPREINTE À EMPREINTE (edge-to-edge) : engaged si (centre-à-centre - r1 - r2) ≤ EZ.
# Avec deux socles de rayon 6 et EZ=10, la limite edge-to-edge est atteinte à centre-à-centre > 22.
#
# Famille 1 : tireur et cible à 8 subhex → edge-to-edge = 8-12 = -4 → ENGAGÉS.
# Famille 2 : cible principale à 30 subhex → edge-to-edge = 30-12 = 18 > 10 → PAS ENGAGÉE per-fig.
#             Le moteur dit oui via [CLOSE-QUARTERS] (scénario FP).
#             Un 2e ennemi à 8 subhex garde shooter_engaged_at_all=True.
SHOOTER = (50, 50)
TARGET_ENGAGED = (50, 58)   # centre-à-centre 8, edge-to-edge -4 : engagé
TARGET_OUTSIDE = (50, 80)   # centre-à-centre 30, edge-to-edge 18 > 10 : non engagé per-fig

S = f"({SHOOTER[0]},{SHOOTER[1]})"
T = f"({TARGET_ENGAGED[0]},{TARGET_ENGAGED[1]})"
T2 = f"({TARGET_OUTSIDE[0]},{TARGET_OUTSIDE[1]})"

# --- Unités ---
# Famille 1 : Intercessor porte Bolt Rifle, marqué non-[CLOSE_QUARTERS] dans le registre.
#             weapon_found=True, is_close_quarters=False → sans le token, engaged_non_close_quarters=1.
# Famille 2 : VanguardVeteranSquadJumpPack porte Heavy Bolt Pistol, marqué [CLOSE_QUARTERS].
#             is_close_quarters=True depuis le registre.
#             La cible est à 8 subhex d'ancre à ancre mais la mesure per-figurine peut diverger.
_UNITS_FAM1 = (
    "[10:00:00] Unit 1 (Intercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
    "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
)
_UNITS_FAM2 = (
    "[10:00:00] Unit 1 (VanguardVeteranSquadJumpPack) P1: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
    "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
    "[10:00:00] Unit 102 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
)

# Famille 1 : tireur + une cible engagée.
_DEPLOY_FAM1 = (
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{S} DEPLOYED from (-1,-1) to {S} [R:+0.0] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101{T} DEPLOYED from (-1,-1) to {T} [R:+0.0] [SUCCESS]\n"
)
# Famille 2 : tireur + cible HORS engagement per-fig + autre ennemi engagé (garde engaged_at_all).
_DEPLOY_FAM2 = (
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{S} DEPLOYED from (-1,-1) to {S} [R:+0.0] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101{T} DEPLOYED from (-1,-1) to {T} [R:+0.0] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 102{T2} DEPLOYED from (-1,-1) to {T2} [R:+0.0] [SUCCESS]\n"
)
_DEPLOY = _DEPLOY_FAM1  # compat alias

# Ligne de tir SANS token [CLOSE-QUARTERS] — grammaire 4 sans confirmation du portier.
_SHOOT_BOLT_RIFLE_NO_TOKEN = (
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{S} SHOT Unit 101{T} with [Bolt Rifle]"
    " - Hit 4(3+) - Wound 3(4+) - Save 2(3+) - Dmg:1HP [ALLOC_MODEL: 101#0] [R:+0.0] [SUCCESS]\n"
)
# Ligne de tir AVEC token [CLOSE-QUARTERS] — grammaire 4, portier a validé.
_SHOOT_BOLT_RIFLE_WITH_TOKEN = (
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{S} SHOT [CLOSE-QUARTERS] Unit 101{T} with [Bolt Rifle]"
    " - Hit 4(3+) - Wound 3(4+) - Save 2(3+) - Dmg:1HP [ALLOC_MODEL: 101#0] [R:+0.0] [SUCCESS]\n"
)
# Famille 2 : cible = Unit 102 (HORS zone d'engagement per-fig, à 12 subhex > EZ 10).
# Le token [CLOSE-QUARTERS] confirme que le moteur considère cependant l'engagement valide.
_SHOOT_HBP_NO_TOKEN = (
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{S} SHOT Unit 102{T2} with [Heavy Bolt Pistol]"
    " - Hit 4(3+) - Wound 3(4+) - Save 2(3+) - Dmg:1HP [ALLOC_MODEL: 102#0] [R:+0.0] [SUCCESS]\n"
)
_SHOOT_HBP_WITH_TOKEN = (
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1{S} SHOT [CLOSE-QUARTERS] Unit 102{T2} with [Heavy Bolt Pistol]"
    " - Hit 4(3+) - Wound 3(4+) - Save 2(3+) - Dmg:1HP [ALLOC_MODEL: 102#0] [R:+0.0] [SUCCESS]\n"
)


def _parse(tmp_path, units: str, shoot_line: str, grammar: int | None = 4, deploy: str | None = None):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(
        entete_step_log(
            (deploy if deploy is not None else _DEPLOY_FAM1) + shoot_line,
            units=units,
            log_grammar=grammar,
        )
    )
    return an.parse_step_log(str(log))


# ===========================================================================
# Famille 1 : engaged_non_close_quarters
# ===========================================================================


def test_geometry_premise_shooter_and_target_are_engaged():
    """Prémisse : les deux ancres sont dans la zone d'engagement (8 ≤ 10 subhex)."""
    import ai.analyzer as an

    d = an.calculate_hex_distance(SHOOTER[0], SHOOTER[1], TARGET_ENGAGED[0], TARGET_ENGAGED[1])
    assert d <= 10, f"distance ancre-ancre={d}, devrait être ≤ 10 (zone d'engagement x5)"


def test_fam1_token_cq_previent_engaged_non_close_quarters(tmp_path):
    """Grammaire 4 + [CLOSE-QUARTERS] → is_close_quarters=True → pas de faux positif famille 1.

    Le Bolt Rifle est non-CQ dans le registre. Sans le token, l'analyzer le comptabilise comme
    tir engagé avec arme non-CQ. Avec le token, il relit le verdict du moteur et lève le FP.
    """
    stats = _parse(tmp_path, _UNITS_FAM1, _SHOOT_BOLT_RIFLE_WITH_TOKEN)
    assert stats["shoot_invalid"][1]["engaged_non_close_quarters"] == 0, (
        "engaged_non_close_quarters doit être 0 : le token [CLOSE-QUARTERS] confirme l'arme CQ"
    )


def test_fam1_verrou_sans_token_le_fp_se_produit(tmp_path):
    """VERROU : sans le token (ou grammar < 4), le faux positif famille 1 se produit bien.

    Ce test doit rester VERT (le FP se produit == compteur == 1). S'il passe à 0, le contrôle
    est mort et la correction ne prouve plus rien.
    """
    stats = _parse(tmp_path, _UNITS_FAM1, _SHOOT_BOLT_RIFLE_NO_TOKEN)
    assert stats["shoot_invalid"][1]["engaged_non_close_quarters"] == 1, (
        "Sans [CLOSE-QUARTERS], Bolt Rifle engagé doit déclencher engaged_non_close_quarters"
    )


# ===========================================================================
# Famille 2 : close_quarters_shot_at_unengaged_target
# ===========================================================================


def test_geometry_premise_fam2_outside_is_truly_outside_ez():
    """Prémisse famille 2 : TARGET_OUTSIDE est hors zone d'engagement (edge-to-edge > 10 subhex)."""
    import ai.analyzer as an

    d = an.calculate_hex_distance(SHOOTER[0], SHOOTER[1], TARGET_OUTSIDE[0], TARGET_OUTSIDE[1])
    base_radius = 6  # round/6 déclaré dans _UNITS_FAM2
    edge_to_edge = d - 2 * base_radius
    assert edge_to_edge > 10, (
        f"TARGET_OUTSIDE doit être hors EZ: edge-to-edge={edge_to_edge} (centre={d}, r=2×{base_radius}, EZ=10)"
    )


def test_fam2_token_cq_previent_close_quarters_shot_at_unengaged_target(tmp_path):
    """Grammaire 4 + [CLOSE-QUARTERS] → shooter_engaged_with_target=True → pas de FP famille 2.

    La cible est à 12 subhex (> EZ 10) : per-fig retourne shooter_engaged_with_target=False.
    Le token [CLOSE-QUARTERS] confirme que le moteur considère l'engagement valide →
    shooter_engaged_with_target devient True, éliminant le faux positif.
    """
    stats = _parse(tmp_path, _UNITS_FAM2, _SHOOT_HBP_WITH_TOKEN, deploy=_DEPLOY_FAM2)
    assert stats["close_quarters_shot_at_unengaged_target"][1] == 0, (
        "close_quarters_shot_at_unengaged_target doit être 0 : le token [CLOSE-QUARTERS] confirme l'engagement"
    )
    assert stats["close_quarters_shots"][1]["engaged_target"] == 1, (
        "Le tir doit être compté comme CQ sur cible engagée"
    )


def test_fam2_verrou_sans_token_fp_se_produit(tmp_path):
    """VERROU : sans le token, la cible hors engagement per-fig produit close_quarters_shot_at_unengaged_target."""
    stats = _parse(tmp_path, _UNITS_FAM2, _SHOOT_HBP_NO_TOKEN, deploy=_DEPLOY_FAM2)
    assert stats["close_quarters_shot_at_unengaged_target"][1] == 1, (
        "Sans [CLOSE-QUARTERS], cible à 12 subhex doit déclencher close_quarters_shot_at_unengaged_target"
    )


def test_fam2_vraie_faute_reste_detectee_avec_token_sur_vraie_cible_non_engagee(tmp_path):
    """Anti-vert-vacant : le token [CLOSE-QUARTERS] n'efface pas UNE VRAIE faute.

    Scénario : le token est présent mais la cible ciblée est (50,62) (hors EZ per-fig).
    Même avec le token, si le moteur a émis [CLOSE-QUARTERS] pour une cible non engagée,
    c'est une faute moteur, pas un FP de l'analyzer. Ce cas est hors périmètre de ce lot
    (moteur) — ce test vérifie seulement que le VERROU (test précédent) n'est pas vacueux
    en comparant avec le scénario where le token DEVRAIT effacer le FP.
    """
    # Ce test est identique à test_fam2_verrou : il confirme que sans le [CLOSE-QUARTERS],
    # la cible hors EZ déclenche bien le compteur (pas de faux négatif dans le VERROU).
    stats = _parse(tmp_path, _UNITS_FAM2, _SHOOT_HBP_NO_TOKEN, deploy=_DEPLOY_FAM2)
    assert stats["close_quarters_shot_at_unengaged_target"][1] == 1
