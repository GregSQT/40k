"""04.03 : le plafond de TIR se compte par FIGURINE, comme celui de mêlée.

Vert vacant V14 de `Documentation/Implémentation/analyzer_couverture.md`. Le plafond de mêlée
était passé par figurine le 2026-08-09 ; celui du tir est resté au niveau ESCOUADE
(`NB du type de tête × socles vivants`) alors que les DEUX segments nécessaires —
`[MODEL_TYPES:]` et `[SHOOTER_MODELS:]` — étaient déjà dans le journal et déjà lus par la mêlée.
C'est le motif d'échec n°1 de ce dépôt : une correction faite d'un côté d'un miroir et pas de
l'autre. Le calcul est désormais UN SEUL objet (`analyzer_perfig.per_model_attack_cap`).

L'ESCOUADE DE CE TEST EST RÉELLE, et son hétérogénéité aussi : le Plasma Pistol (Standard) d'un
`CaptainPowerWeaponPlasmaPistol` a NB=1, celui d'un `AssaultIntercessorSergeant` a NB=D3 → 3.
Même nom d'arme, même escouade, trois fois plus de tirs. C'est exactement la configuration que
la règle 19 (Attached units) produit à chaque partie.

    plafond par FIGURINE  : 1 (Captain) + 3 (Sergent) = 4
    plafond par ESCOUADE  : 1 (type de tête) × 2 socles = 2   ← l'ancien calcul

Trois tirs légaux tombaient donc en faute, et le rapport annonçait « shots over RNG_NB ».
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log

SQUAD_TYPE = "CaptainPowerWeaponPlasmaPistol"   # NB=1 pour le Plasma Pistol (Standard)
SERGEANT_TYPE = "AssaultIntercessorSergeant"    # NB=D3 → 3 pour la MÊME arme
WEAPON = "Plasma Pistol (Standard)"

PER_MODEL_CAP = 4      # 1 + 3
PER_SQUAD_CAP = 2      # 1 × 2 socles — l'ancien calcul, faux

SHOOTER = (50, 50)
TARGET = (50, 56)      # 6 subhex = 1,2" — bien dans les 12" de portée du pistolet
OBJECTIVES = ";".join(f"(200,{r})" for r in range(150, 156))

S = f"({SHOOTER[0]},{SHOOTER[1]})"
T = f"({TARGET[0]},{TARGET[1]})"

_HEADER = entete_step_log(
    units=(
        f"[10:00:00] Unit 1 ({SQUAD_TYPE}) P1: Starting position {S}, HP_MAX=5 base=round/6"
        f" [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0) 1#1@({SHOOTER[0]},{SHOOTER[1] + 1},z0)]"
        f" [MODEL_TYPES: 1#0={SQUAD_TYPE} 1#1={SERGEANT_TYPE}]\n"
        f"[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position {T}, HP_MAX=2 base=round/6"
        f" [MODELS: 101#0@({TARGET[0]},{TARGET[1]},z0)]\n"
    ),
    rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)",
    objectives=OBJECTIVES,
)

_END = ("[10:00:08] T2 OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none\n"
        "[10:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, "
        "Total=0, Duration=1.000s\n")

_MODELS = f"[MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0) 1#1@({SHOOTER[0]},{SHOOTER[1] + 1},z0)]"
_SHOOTERS = "[SHOOTER_MODELS: 1#0 1#1]"


def _shot(n: int) -> str:
    """Une ligne d'attaque de tir, les DEUX socles désignés comme tireurs."""
    return (
        f"[10:00:0{n} ] E1 T1 P1 SHOOT : Unit 1{S} SHOT Unit 101{T} with [{WEAPON}]"
        f" - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:0HP {_MODELS} {_SHOOTERS}"
        " [R:+0.0] [SUCCESS]\n"
    ).replace(" ]", "]")


def _stats(tmp_path, n_shots: int):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(_HEADER + "".join(_shot(2) for _ in range(n_shots)) + _END)
    return an.parse_step_log(str(log))


def test_registry_premise_the_squad_is_really_heterogeneous():
    """Sans cet écart de NB, le test ne distinguerait pas les deux calculs : il serait inopérant."""
    from ai.unit_registry import UnitRegistry
    from ai.analyzer import max_dice_value

    units = UnitRegistry().units

    def _nb(unit_type: str) -> int:
        w = next(w for w in units[unit_type]["RNG_WEAPONS"] if w["display_name"] == WEAPON)
        return max_dice_value(w["NB"], f"{unit_type}/{WEAPON}")

    captain = _nb(SQUAD_TYPE)
    sergeant = _nb(SERGEANT_TYPE)
    assert captain == 1, captain
    assert sergeant == 3, sergeant
    assert captain + sergeant == PER_MODEL_CAP
    assert captain * 2 == PER_SQUAD_CAP
    assert PER_MODEL_CAP != PER_SQUAD_CAP, "les deux calculs doivent diverger, sinon rien n'est prouvé"


def test_the_shared_cap_reads_the_ranged_key():
    """`per_model_attack_cap` doit rendre le MÊME objet au tir et en mêlée, sur la clé du tir."""
    from ai.analyzer_perfig import per_model_attack_cap

    limits = {
        SQUAD_TYPE: {"rng_nb_by_weapon": {WEAPON: 1}},
        SERGEANT_TYPE: {"rng_nb_by_weapon": {WEAPON: 3}},
    }
    model_types = {"1#0": SQUAD_TYPE, "1#1": SERGEANT_TYPE}
    cap = per_model_attack_cap(
        ("1#0", "1#1"), model_types, SQUAD_TYPE, WEAPON, limits,
        "rng_nb_by_weapon", {}, 1, 2,
    )
    assert cap == PER_MODEL_CAP
    # Journal sans `[SHOOTER_MODELS:]` → repli EXPLICITE sur l'ancien calcul, pas un plantage.
    assert per_model_attack_cap((), model_types, SQUAD_TYPE, WEAPON, limits,
                                "rng_nb_by_weapon", {}, 1, 2) == PER_SQUAD_CAP


def test_four_shots_from_a_heterogeneous_squad_are_legal(tmp_path):
    """Le cœur de V14 : 4 tirs sont dans le plafond par figurine, hors du plafond par escouade.

    C'est le test qui distingue les deux calculs. Avec l'ancien, ces 4 lignes remontaient
    « shots over RNG_NB » deux fois — sur un tir parfaitement légal.
    """
    stats = _stats(tmp_path, PER_MODEL_CAP)
    assert stats["shoot_over_rng_nb"][1] == 0, stats["first_error_lines"]["shoot_over_rng_nb"][1]


def test_beyond_the_per_model_cap_is_still_caught(tmp_path):
    """Contrôle anti-vert-vacant : un VRAI dépassement doit toujours être compté.

    Sans ce cas, « 0 erreur » au test précédent ne prouverait que la mort du contrôle.
    """
    stats = _stats(tmp_path, PER_MODEL_CAP + 2)
    assert stats["shoot_over_rng_nb"][1] == 2
