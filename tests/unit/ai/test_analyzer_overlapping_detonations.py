"""Overlapping Detonations (grant_weapon_rule_vs_designated_target) : +target_size//5 A au Heavy Bolter.

Avant le fix, `max_allowed_shots` n'incluait pas ce bonus : cap = NB seulement.
Heavy Bolter : NB=3. Cible de 6 fig → OD +1 A/tireur → cap correct = 4/tireur.
3 tireurs (EradicatorHeavyBolter×2 + EradicatorHeavyBolterSergeant×1) : cap total = 3×4 = 12.
Sans le fix : cap=3×3=9 → 3 erreurs sur 12 tirs légitimes.

Scénarios :
  1. 3 tireurs, cible 6 fig (non-M/V) : cap=12 → 0 erreur sur 12 tirs.
  2. Idem 13 tirs → 1 erreur (témoin inverse).
  3. Cible 4 fig → OD=0 (4//5=0), cap=9 → 0 erreur sur 9 tirs.
  4. Cible 4 fig, 10 tirs → 1 erreur.
  5. Cible est un WarTrakk (VEHICLE) : OD n'applique pas, cap=9 → 0 erreur sur 9 tirs.
  6. Idem 10 tirs VEHICLE → 1 erreur.
"""
from __future__ import annotations

from ai.analyzer_perfig import unit_blast_per5_nonmv_bonus
from tests.unit.ai._fabriques import entete_step_log

_MODEL_TYPES = {"1#0": "EradicatorHeavyBolter", "1#1": "EradicatorHeavyBolter", "1#2": "EradicatorHeavyBolterSergeant"}
_LIMITS = {
    "EradicatorHeavyBolter": {"blast_per5_nonmv_weapons": {"Heavy Bolter"}},
    "EradicatorHeavyBolterSergeant": {"blast_per5_nonmv_weapons": {"Heavy Bolter"}},
}


def _cap(living_mids=None, model_types=None, target_models_alive=6):
    return unit_blast_per5_nonmv_bonus(
        ("1#0", "1#1", "1#2"), model_types if model_types is not None else _MODEL_TYPES,
        "1", "EradicatorHeavyBolter", "Heavy Bolter", _LIMITS, target_models_alive, 3,
        living_mids=living_mids,
    )


def test_od_living_mids_vide_perd_bonus():
    """living_mids={} → aucun socle vivant → 0, pas de fallback squad_unit_type."""
    assert _cap(living_mids=set()) == 0


def test_od_porteurs_types_morts_mid_vivant_non_type_perd_bonus():
    """Porteurs typés morts, mid vivant absent de model_types → 0 (pas de faux positif)."""
    assert _cap(living_mids={"1#3"}, model_types={"1#0": "EradicatorHeavyBolter"}) == 0


def test_od_mids_vivants_non_types_repli_squad_unit_type():
    """model_types={} mais mids vivants → fallback squad_unit_type → bonus OD accordé."""
    assert _cap(living_mids={"1#0", "1#1", "1#2"}, model_types={}) == 3  # 6//5=1 × 3 tireurs

SHOOTER_POS = (50, 50)
TARGET_POS = (80, 80)
S = f"({SHOOTER_POS[0]},{SHOOTER_POS[1]})"
T = f"({TARGET_POS[0]},{TARGET_POS[1]})"

_UNITS_NON_MV = (
    "[10:00:00] Unit 1 (EradicatorHeavyBolter) P1: Starting position (-1,-1), HP_MAX=2 base=round/40"
    " [MODEL_TYPES: 1#0=EradicatorHeavyBolter 1#1=EradicatorHeavyBolter"
    " 1#2=EradicatorHeavyBolterSergeant]\n"
    "[10:00:00] Unit 101 (Boyz) P2: Starting position (-1,-1), HP_MAX=1 base=round/6\n"
)

_UNITS_VEHICLE = (
    "[10:00:00] Unit 1 (EradicatorHeavyBolter) P1: Starting position (-1,-1), HP_MAX=2 base=round/40"
    " [MODEL_TYPES: 1#0=EradicatorHeavyBolter 1#1=EradicatorHeavyBolter"
    " 1#2=EradicatorHeavyBolterSergeant]\n"
    "[10:00:00] Unit 101 (DreadnoughtBallistus) P2: Starting position (-1,-1), HP_MAX=10 base=round/65\n"
)


def _setup(target_size: int) -> str:
    models_str = " ".join(
        f"101#{i}@({TARGET_POS[0]},{TARGET_POS[1]},z0)" for i in range(target_size)
    )
    return (
        f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{S} DEPLOYED from (-1,-1) to {S}"
        f" [R:+0.0] [MODELS: 1#0@({SHOOTER_POS[0]},{SHOOTER_POS[1]},z0)"
        f" 1#1@({SHOOTER_POS[0]},{SHOOTER_POS[1]},z0)"
        f" 1#2@({SHOOTER_POS[0]},{SHOOTER_POS[1]},z0)] [SUCCESS]\n"
        f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101{T} DEPLOYED from (-1,-1) to {T}"
        f" [R:+0.0] [MODELS: {models_str}] [SUCCESS]\n"
        "[10:00:01] T1 EFFECTS: P1 none | P2 none\n"
    )


def _tir(seconde: int, coup: int, target_decl: int) -> str:
    # [TARGET_DECL:N] est loggué par le moteur sur chaque ligne du groupe de tir.
    # Tous les tirs utilisent le même [SHOOTER_MODELS: 1#0 1#1 1#2] pour que le
    # compteur seq_key s'accumule sans reset (clé = groupe, pas figurine individuelle).
    return (
        f"[10:00:{seconde:02d}] E1 T1 P1 SHOOT : Unit 1{S}"
        f" SHOT [TARGET_DECL:{target_decl}] Unit 101{T} with [Heavy Bolter]"
        f" - Hit {coup}(3+) - Wound 5(4+) - Save 2(3+) - Dmg:1HP [R:+0.0]"
        f" [MODELS: 1#0@({SHOOTER_POS[0]},{SHOOTER_POS[1]},z0)"
        f" 1#1@({SHOOTER_POS[0]},{SHOOTER_POS[1]},z0)"
        f" 1#2@({SHOOTER_POS[0]},{SHOOTER_POS[1]},z0)]"
        f" [SHOOTER_MODELS: 1#0 1#1 1#2] [SUCCESS]\n"
    )


def _stats(tmp_path, n_shots: int, units_header: str, target_size: int) -> dict:
    import ai.analyzer as an

    shots = "".join(_tir(i + 2, i + 1, target_size) for i in range(n_shots))

    log = tmp_path / "step.log"
    log.write_text(
        entete_step_log(
            _setup(target_size) + shots,
            units=units_header,
            ez_vertical_inches=None,
        )
    )
    return an.parse_step_log(str(log))


def test_12_tirs_heavy_bolter_cible_6_pas_d_erreur(tmp_path):
    """3 tireurs × (3 NB + 1 OD[6//5=1]) = 12 tirs max → 0 erreur."""
    stats = _stats(tmp_path, 12, _UNITS_NON_MV, target_size=6)
    assert stats["shoot_over_rng_nb"][1] == 0, (
        f"Attendu 0 erreur shoot_over_rng_nb P1, obtenu {stats['shoot_over_rng_nb'][1]}"
    )


def test_13_tirs_heavy_bolter_cible_6_declenche_erreur(tmp_path):
    """Témoin inverse : 13 tirs dépasse le plafond → 1 erreur."""
    stats = _stats(tmp_path, 13, _UNITS_NON_MV, target_size=6)
    assert stats["shoot_over_rng_nb"][1] == 1, (
        f"Attendu 1 erreur shoot_over_rng_nb P1, obtenu {stats['shoot_over_rng_nb'][1]}"
    )


def test_9_tirs_heavy_bolter_cible_4_pas_d_erreur(tmp_path):
    """Cible de 4 fig : 4//5=0 → OD pas activé, cap=3×3=9 → 0 erreur sur 9 tirs."""
    stats = _stats(tmp_path, 9, _UNITS_NON_MV, target_size=4)
    assert stats["shoot_over_rng_nb"][1] == 0, (
        f"Attendu 0 erreur shoot_over_rng_nb P1 (target_size=4), "
        f"obtenu {stats['shoot_over_rng_nb'][1]}"
    )


def test_10_tirs_heavy_bolter_cible_4_declenche_erreur(tmp_path):
    """Cible de 4 fig : cap=9 → 10 tirs déclenche 1 erreur."""
    stats = _stats(tmp_path, 10, _UNITS_NON_MV, target_size=4)
    assert stats["shoot_over_rng_nb"][1] == 1, (
        f"Attendu 1 erreur shoot_over_rng_nb P1 (target_size=4), "
        f"obtenu {stats['shoot_over_rng_nb'][1]}"
    )


def test_9_tirs_heavy_bolter_vehicle_pas_d_erreur(tmp_path):
    """Cible VEHICLE : OD ne s'applique pas, cap=3×3=9 → 0 erreur sur 9 tirs."""
    stats = _stats(tmp_path, 9, _UNITS_VEHICLE, target_size=6)
    assert stats["shoot_over_rng_nb"][1] == 0, (
        f"Attendu 0 erreur shoot_over_rng_nb P1 (VEHICLE, cap=9), "
        f"obtenu {stats['shoot_over_rng_nb'][1]}"
    )


def test_10_tirs_heavy_bolter_vehicle_declenche_erreur(tmp_path):
    """Cible VEHICLE : cap=9 → 10 tirs déclenche 1 erreur."""
    stats = _stats(tmp_path, 10, _UNITS_VEHICLE, target_size=6)
    assert stats["shoot_over_rng_nb"][1] == 1, (
        f"Attendu 1 erreur shoot_over_rng_nb P1 (VEHICLE), "
        f"obtenu {stats['shoot_over_rng_nb'][1]}"
    )
