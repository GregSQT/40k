"""Verrous de la sonde `scripts/family_entropy_probe.py`.

La sonde sert à lire l'effet de l'entropie normalisée par l'état FAMILLE par famille. Ses façons
de mentir : une entropie ou une KL fausses, une famille mal attribuée (une arrivée de réserves
comptée comme un déplacement), une moyenne rendue sans son effectif, un plancher qui ne
plancherait rien. Chacune est verrouillée ici sur des distributions construites à la main. Le
reste (rollouts, chargement de modèles) exige moteur et poids et n'est pas testable ici ; le
plancher à l'exécution (politique UNIFORME → H = ln n par famille, code de sortie 2 sinon) en
tient lieu ; vérifié le 2026-09-12 sur 2 épisodes, H_A = H_max sur les cinq familles visitées.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from engine.macro_intents import CHARGE_SLOTS, DEPLOY_SLOTS, MOVE_CELLS
from scripts.family_entropy_probe import (
    COLUMNS,
    entropy_nats,
    family_of,
    floor_violations,
    kl_nats,
    new_accumulator,
    record_state,
    render_table,
    summarize,
)


def test_entropie_nats() -> None:
    """Uniforme sur n → ln n ; masse concentrée → 0 ; les zéros exacts du masque n'entrent pas."""
    assert entropy_nats(np.array([0.25, 0.25, 0.25, 0.25])) == pytest.approx(math.log(4))
    assert entropy_nats(np.array([1.0, 0.0, 0.0])) == 0.0
    assert entropy_nats(np.array([0.5, 0.5, 0.0, 0.0])) == pytest.approx(math.log(2))


def test_kl_nats() -> None:
    """KL(p‖p) = 0, KL ≥ 0, et une action jouée par A mais exclue par B donne un terme FINI."""
    p = np.array([0.7, 0.2, 0.1])
    q = np.array([0.2, 0.3, 0.5])
    assert kl_nats(p, p) == 0.0
    expected = sum(pi * math.log(pi / qi) for pi, qi in zip(p, q))
    assert kl_nats(p, q) == pytest.approx(expected)
    assert kl_nats(p, q) > 0.0
    exclu = kl_nats(np.array([0.5, 0.5]), np.array([1.0, 0.0]))
    assert math.isfinite(exclu)
    assert exclu == pytest.approx(0.5 * math.log(0.5 / 1.0) + 0.5 * math.log(0.5 / 1e-12), rel=1e-6)


def test_famille_lit_setting_up_dans_le_resultat_du_step() -> None:
    """Les ids 4-8 sont des cellules de move OU des stratégies de pose : c'est `ingress_move`
    dans le résultat du step qui tranche, comme dans `w40k_core.py`."""
    slot = min(DEPLOY_SLOTS)
    assert slot in MOVE_CELLS, "le test suppose le recouvrement ids 4-8 / cellules de move"
    assert family_of(slot, "move", {"action": "move"}) == "move_cell"
    assert family_of(slot, "move", {"action": "ingress_move"}) == "deploy_slot"
    assert family_of(slot, "deployment", {}) == "deploy_slot"
    assert family_of(min(CHARGE_SLOTS), "charge", {"action": "charge"}) == "charge_slot"


def test_accumulation_et_moyennes_par_famille() -> None:
    """Deux états `charge_slot`, un `move_cell` : n, legal, H, H_max, pmax, KL, argmax≠ moyennés."""
    acc = new_accumulator()
    record_state(acc, "charge_slot", np.array([0.5, 0.5]), np.array([0.9, 0.1]), 2)
    record_state(acc, "charge_slot", np.array([1.0, 0.0]), np.array([1.0, 0.0]), 2)
    uniform4 = np.full(4, 0.25)
    record_state(acc, "move_cell", uniform4, np.array([0.7, 0.1, 0.1, 0.1]), 4)

    rows = summarize(acc)

    assert [r["famille"] for r in rows] == ["charge_slot", "move_cell"], "tri par effectif"
    charge = rows[0]
    assert charge["n"] == 2 and charge["legal"] == 2.0
    assert charge["H_A"] == pytest.approx(math.log(2) / 2)
    assert charge["H_B"] == pytest.approx(entropy_nats(np.array([0.9, 0.1])) / 2)
    assert charge["H_max"] == pytest.approx(math.log(2))
    assert charge["pmax_A"] == pytest.approx(0.75) and charge["pmax_B"] == pytest.approx(0.95)
    assert charge["KL(A|B)"] == pytest.approx(kl_nats(np.array([0.5, 0.5]), np.array([0.9, 0.1])) / 2)
    assert charge["argmax≠"] == 0.0
    move = rows[1]
    assert move["n"] == 1 and move["H_A"] == pytest.approx(math.log(4)) and move["H_max"] == pytest.approx(math.log(4))
    assert move["argmax≠"] == 0.0  # argmax de [0.25]*4 est 0, comme celui de B


def test_etat_sans_decision_refuse() -> None:
    """n_legal < 2 : rien à mesurer, l'appelant a filtré avant — une ligne ici fausserait `n`."""
    with pytest.raises(ValueError, match="sans décision"):
        record_state(new_accumulator(), "wait", np.array([1.0]), np.array([1.0]), 1)


def test_plancher_a_tolerance_explicite() -> None:
    """Sous (1 - tol) × ln n → famille listée ; à la limite ou au-dessus → rien.

    Le bras UNIFORME vaut ln n exactement : un plancher qui laisserait passer 0,10 × ln n
    d'écart ne verrait pas un masque lu décalé d'une colonne sur une tête à trois actions."""
    rows = [
        {"famille": "ok", "H_B": 0.95 * math.log(3), "H_max": math.log(3)},
        {"famille": "limite", "H_B": 0.90 * math.log(3), "H_max": math.log(3)},
        {"famille": "effondree", "H_B": 0.10 * math.log(3), "H_max": math.log(3)},
    ]
    assert floor_violations(rows, "H_B", 0.10) == ["effondree"]
    assert floor_violations(rows, "H_B", 0.0) == ["ok", "limite", "effondree"], "tol 0 : tout ce qui est sous ln n"
    with pytest.raises(ValueError, match="floor-tol"):
        floor_violations(rows, "H_B", 1.0)


def test_tableau_porte_toutes_les_colonnes_et_l_effectif() -> None:
    acc = new_accumulator()
    record_state(acc, "shoot_slot", np.array([0.6, 0.4]), np.array([0.5, 0.5]), 2)
    table = render_table(summarize(acc))
    head, line = table.splitlines()
    for col in COLUMNS:
        assert col in head
    assert line.startswith("shoot_slot") and line.split()[1] == "1"
