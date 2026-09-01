"""Ligne DEAD sans [MODELS:] retire le modèle de positions_by_model immédiatement.

Avant le fix, un modèle tué via ALLOC_MODEL restait dans `pending_model_removals` et
dans `positions_by_model` jusqu'à ce qu'un AUTRE acteur émette `[MODELS:]`. Si l'unité
n'avait qu'UN seul modèle et que personne d'autre n'agissait ensuite avec `[MODELS:]`,
le modèle restait indéfiniment comme « fantôme ».

Conséquence mesurée : au STATE snapshot, l'unité est absente du moteur mais l'analyzer
voit encore ses coordonnées dans `positions_by_model` (hp > 0, sur le terrain) → le
contrôle `dead_missed` incrémente. Avec le fix, le handler DEAD purge le socle avant
le STATE → `dead_missed == 0`.

Scénario :
  - Unit 1 (Warboss, 6HP) déployé avec [MODELS: 1#0@...]
  - Unit 102 (Intercessor) tire sur Unit 1 : Dmg:1HP → unit_hp["1"] = 5 (vivant côté analyzer)
  - Ligne DEAD: "Unit 1 DEAD model=1#0" SANS [MODELS:]  ← le ghost serait créé ici sans fix
  - T1 STATE: ne mentionne QUE unit 102 (unit 1 disparue côté moteur)
  - Sans fix : positions_by_model["1"] contient encore 1#0 → dead_missed = 1
  - Avec fix : positions_by_model["1"] est purgé par DEAD → dead_missed = 0
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log

WARBOSS = (30, 20)
INTERCESSOR = (50, 50)
W = f"({WARBOSS[0]},{WARBOSS[1]})"
I = f"({INTERCESSOR[0]},{INTERCESSOR[1]})"

_UNITS = (
    "[10:00:00] Unit 1 (Warboss) P2: Starting position (-1,-1), HP_MAX=6 base=round/20\n"
    "[10:00:00] Unit 102 (Intercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
)

_DEPLOY = (
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 1{W} DEPLOYED from (-1,-1) to {W}"
    f" [R:+0.0] [MODELS: 1#0@({WARBOSS[0]},{WARBOSS[1]},z0)] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 102{I} DEPLOYED from (-1,-1) to {I}"
    f" [R:+0.0] [MODELS: 102#0@({INTERCESSOR[0]},{INTERCESSOR[1]},z0)] [SUCCESS]\n"
)

# Tir avec Dmg:1HP → unit_hp["1"] = 5 (Warboss toujours vivant côté analyzer)
# ALLOC_MODEL présent mais n'entre pas dans pending_model_removals (grammar < 6)
_SHOOT = (
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 102{I} SHOT Unit 1{W} with [Bolt Rifle]"
    " - Hit 5(3+) - Wound 4(4+) - Save 1(4+) - Dmg:1HP [R:+0.0]"
    f" [MODELS: 102#0@({INTERCESSOR[0]},{INTERCESSOR[1]},z0)]"
    " [SHOOTER_MODELS: 102#0] [SUCCESS]\n"
)

# DEAD sans [MODELS:] : c'est le seul modèle, unit 1 disparaît côté moteur
_DEAD = (
    f"[10:00:03] E1 T1 P2 SHOOT : Unit 1{W} DEAD model=1#0 reason=combat [SUCCESS]\n"
)

# T1 STATE: ne mentionne que unit 102 (unit 1 morte côté moteur)
# Format : <unit_id>[<model_id>@(col,row,z?):<pv>]
_STATE = (
    f"[10:00:04] T1 STATE:"
    f" 102[102#0@({INTERCESSOR[0]},{INTERCESSOR[1]}):2]\n"
)


def test_dead_event_retire_le_modele_de_positions_by_model(tmp_path):
    """Après DEAD sans [MODELS:], le fantôme n'est plus dans positions_by_model."""
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(
        entete_step_log(
            _DEPLOY + _SHOOT + _DEAD + _STATE,
            units=_UNITS,
            ez_vertical_inches=None,
        )
    )
    stats = an.parse_step_log(str(log))
    # dead_missed = unités vivantes côté analyzer (positions on-board) absentes du STATE.
    # Sans fix : 1#0 reste dans positions_by_model → unit 1 = ghost → dead_missed = 1.
    # Avec fix  : DEAD retire 1#0 → positions_by_model["1"] vide → dead_missed = 0.
    assert stats["state_resync"]["dead_missed"] == 0, (
        f"dead_missed={stats['state_resync']['dead_missed']} : "
        "le fantôme 1#0 est encore dans positions_by_model après la ligne DEAD"
    )
