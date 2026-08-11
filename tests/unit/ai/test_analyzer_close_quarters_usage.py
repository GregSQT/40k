"""§1.8 compte l'usage de [CLOSE-QUARTERS] sur l'ENGAGEMENT, comme §10.06 — plus sur l'adjacence.

Le rapport portait DEUX mesures de la même règle, sous le même nom :

  - §10.06 (« CLOSE_QUARTERS shots by engagement ») avait été réaligné sur
    `shooter_engaged_with_target` — bord-à-bord, par figurine, zone d'engagement du run —
    parce que c'est la grandeur de la règle (« enemy units that are ENGAGED WITH your unit ») ;
  - §1.8 (« weapon rules usage ») était resté sur
    `calculate_hex_distance(ancre_tireur, ancre_cible) == 1`.

Sur le run du 2026-08-11 : 1 280 tirs pour la première, 43 pour la seconde. Une escouade engagée
mais étalée — ou dont les socles sont larges — est engagée SANS que ses ancres soient à un hex,
et c'est le cas courant, pas le cas limite. Quatrième occurrence de la famille « ancre vs
par-figurine » dans ce fichier après la LoS, le fight non-adjacent et §10.06 lui-même.

GÉOMÉTRIE DU TEST : ancres distantes de 12 subhex — donc PAS adjacentes, l'ancien contrôle
rendait 0 — mais empreintes de socles assez proches pour que le moteur les tienne pour engagées.
C'est exactement la configuration que l'ancien compteur ne voyait pas. L'engagement n'est pas
affirmé ici par un calcul recopié : il est MESURÉ par `test_geometry_premise_engaged_but_not_adjacent`,
qui interroge §10.06 — la seule autorité sur cette grandeur.
"""
from __future__ import annotations

UNIT_TYPE = "Intercessor"
WEAPON = "Bolt Pistol"          # armurerie : ["CLOSE_QUARTERS"]

SHOOTER = (50, 50)
ENGAGED_TARGET = (62, 50)       # 12 subhex d'ancre à ancre : non adjacentes, mais engagées
FAR_TARGET = (110, 50)          # 60 subhex → hors zone d'engagement, dans la portée (12" = 60)
OBJECTIVES = ";".join(f"(150,{r})" for r in range(150, 156))


def _log(target: tuple[int, int]) -> str:
    s, t = f"({SHOOTER[0]},{SHOOTER[1]})", f"({target[0]},{target[1]})"
    return f"""=== STEP-BY-STEP ACTION LOG ===
================================================================================

[10:00:00] === EPISODE 1 START ===
[10:00:00] Scenario: scenario_bot-01
[10:00:00] Rosters: scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)
[10:00:00] Opponent: SelfplayBot
[10:00:00] Walls:
[10:00:00] Objectives: rect b NW:{OBJECTIVES}
[10:00:00] Board: cols=220 rows=300 inches_to_subhex=5 hex_radius=2.78 margin=1
[10:00:00] Run rules: engagement_zone_subhex=10 engagement_zone_vertical_inches=5.0 metric.engagement=hex metric.ranged=euclidean move.thru_ez=True move.thru_enemy=False move.thru_friendly=True cohesion.model_subhex=10 cohesion.global_subhex=45 cohesion.min_neighbors=1
[10:00:00] Unit 1 ({UNIT_TYPE}) P1: Starting position {s}, HP_MAX=2 base=round/6 [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)] [MODEL_TYPES: 1#0={UNIT_TYPE}]
[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position {t}, HP_MAX=2 base=round/6 [MODELS: 101#0@({target[0]},{target[1]},z0)]
[10:00:00] === ACTIONS START ===
[10:00:02] E1 T1 P1 SHOOT : Unit 1{s} SHOT Unit 101{t} with [{WEAPON}] - Hit 4(3+) - Wound 5(4+) - Save 2(3+) - Dmg:0HP [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)] [TARGET_MODELS: 101#0@({target[0]},{target[1]},z0)] [SHOOTER_MODELS: 1#0] [R:+0.0] [SUCCESS]
[10:00:08] T2 OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none
[10:00:09] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, Total=0, Duration=1.000s
"""


def _stats(tmp_path, target):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(_log(target))
    return an.parse_step_log(str(log))


def _cq_usage(stats) -> int:
    return sum(
        sum(v.values())
        for k, v in stats["weapon_rule_usage"].items()
        if k[0] == "CLOSE_QUARTERS"
    )


def test_geometry_premise_engaged_but_not_adjacent(tmp_path):
    """Prémisse : §10.06 doit voir l'engagement là où l'adjacence d'ancre ne le voit pas.

    Sans cet écart, les deux comptages seraient d'accord par accident et le test ne prouverait
    rien — c'est le vert vacant qu'il faut écarter d'abord.
    """
    stats = _stats(tmp_path, ENGAGED_TARGET)
    assert stats["close_quarters_shots"][1]["engaged_target"] == 1, stats["close_quarters_shots"]
    assert abs(ENGAGED_TARGET[0] - SHOOTER[0]) > 1, "les ancres ne doivent PAS être adjacentes"


def test_usage_is_counted_for_an_engaged_target(tmp_path):
    """Le cœur : §1.8 compte la règle là où §10.06 la voit jouer."""
    stats = _stats(tmp_path, ENGAGED_TARGET)
    assert _cq_usage(stats) == 1, (
        "0 signifie que §1.8 mesure encore l'adjacence des ancres, pas l'engagement"
    )


def test_the_two_sections_never_diverge(tmp_path):
    """Les deux sections comptent LE MÊME fait : leur égalité est l'invariant, pas une coïncidence."""
    stats = _stats(tmp_path, ENGAGED_TARGET)
    assert _cq_usage(stats) == stats["close_quarters_shots"][1]["engaged_target"]


def test_no_usage_when_the_target_is_not_engaged(tmp_path):
    """Anti-vert-vacant : une arme [CLOSE-QUARTERS] tirée à 12" reste une arme de tir ordinaire.

    La règle n'a pas joué, donc rien ne doit être compté — sans quoi « la règle est utilisée »
    ne voudrait plus rien dire.
    """
    stats = _stats(tmp_path, FAR_TARGET)
    assert stats["close_quarters_shots"][1]["unengaged_target"] == 1, stats["close_quarters_shots"]
    assert _cq_usage(stats) == 0
