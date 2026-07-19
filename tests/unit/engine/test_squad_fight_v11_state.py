"""Le chemin gym avance la machine V11 de la phase de combat (12.01-12.09).

Rupture corrigée (V11 T6-d) : il existait DEUX résolutions du combat. Le PvP
(`_process_semantic_action` → `fight_handlers`) avançait la machine état par état ; le gym
(`_process_squad_action` → `squad_fight`) résolvait pile-in + fight + consolidation par escouade,
en une passe, sans jamais y toucher. Mesuré sur épisode réel : `fight_subphase` restait à
`'pile_in'` du début à la fin, `engaged_at_fight_step_start` n'était jamais posé,
`units_selected_to_fight` restait vide.

Conséquences réglementaires, toutes vérifiées ici :
- 12.02 exige que TOUS les pile-in des DEUX joueurs précèdent le premier combat ; le gym
  intercalait le pile-in d'une escouade entre deux combats ;
- 12.04 date son snapshot d'éligibilité (« was engaged at the start of this step ») du début de
  l'étape FIGHT — snapshot jamais pris, donc branche inapplicable ;
- 12.04 interdit à une escouade d'être sélectionnée deux fois dans la phase — rien ne
  l'enregistrait, donc rien ne l'interdisait ;
- 12.08 réserve la consolidation aux unités « eligible to fight this phase », dérivé du même set.

Le fix découpe `squad_fight` en UNE sélection de l'étape FIGHT, encadrée par les deux étapes
groupées résolues par `_fight_v11_gym_settle`.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from smoke_t5_bare import MELEE_SCENARIO  # noqa: E402


@pytest.fixture()
def melee_scenario_file():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "melee.json"
        path.write_text(json.dumps(MELEE_SCENARIO))
        yield str(path)


def _engine_in_fight_phase(scenario_file: str, seed: int = 1):
    """Moteur gym amené en phase de combat par le vrai chemin d'entrée (12.01 + déroulement)."""
    from ai.unit_registry import UnitRegistry
    from engine.game_utils import get_unit_by_id

    from shared.data_validation import require_present
    from engine.phase_handlers import fight_handlers
    from engine.phase_handlers.fight_handlers import _fight_build_valid_target_pool
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent", training_config_name="x1_debug", controlled_agent="ArmageddonAgent",
        scenario_file=scenario_file, unit_registry=UnitRegistry(), quiet=True,
        gym_training_mode=True,
    )
    eng.reset(seed=seed)
    gs = eng.game_state
    gs["phase"] = "fight"
    # Le scénario mêlée est pré-engagé : on prend la main du joueur qui a une cible en ER, sinon
    # la phase se compléterait à vide et il n'y aurait pas d'étape FIGHT à observer.
    engaged = [
        sid for sid in gs["units_cache"]
        if _fight_build_valid_target_pool(gs, require_present(get_unit_by_id(str(sid), gs), f"unit {sid}"))
    ]
    assert engaged, "le scénario mêlée doit être pré-engagé"
    gs["current_player"] = int(gs["units_cache"][str(engaged[0])]["player"])
    gs["units_fought"] = set()

    res = fight_handlers.fight_phase_start(gs)
    eng._fight_v11_gym_after_phase_start(res)
    return eng


def test_subphase_advances_past_pile_in(melee_scenario_file):
    """12.02 → 12.04 : le PILE IN groupé est résolu à l'entrée, la machine atteint l'étape FIGHT.

    Échoue sur l'ancien code : `fight_subphase` restait figé à `'pile_in'`.
    """
    eng = _engine_in_fight_phase(melee_scenario_file)
    assert eng.game_state["fight_subphase"] == "fight"


def test_pile_in_step_consumed_before_fight(melee_scenario_file):
    """12.02 : « Each unit cannot make more than one pile-in move during this step ».

    Le set `pile_in_done` matérialise la consommation de l'étape ; il restait vide, si bien que
    l'étape n'était jamais épuisée et ne pouvait jamais céder la place à l'étape FIGHT.
    """
    eng = _engine_in_fight_phase(melee_scenario_file)
    assert eng.game_state["pile_in_done"], "le pile-in groupé doit avoir été résolu et marqué"


def test_engaged_snapshot_posed_at_fight_step_start(melee_scenario_file):
    """12.04 : le snapshot d'engagement est pris au début de l'étape FIGHT, après les pile-in.

    Échoue sur l'ancien code : la clé était absente (jamais posée), rendant inapplicables la
    branche « was engaged at the start of this step » (12.04) et sa négation (overrun, 12.06).
    """
    eng = _engine_in_fight_phase(melee_scenario_file)
    gs = eng.game_state
    snapshot = gs["engaged_at_fight_step_start"]
    assert isinstance(snapshot, dict)
    # Scénario pré-engagé : le snapshot doit constater au moins une unité engagée.
    assert any(snapshot.values()), f"snapshot sans aucune unité engagée: {snapshot}"


def test_squad_fight_registers_selection_and_cannot_fight_twice(melee_scenario_file):
    """12.04 : « has not already been selected to fight this phase ».

    Échoue sur l'ancien code : `units_selected_to_fight` restait vide, donc l'escouade restait
    dans le pool et pouvait être re-sélectionnée dans la même phase.
    """
    from engine.phase_handlers.fight_handlers import fight_v11_current_pool

    eng = _engine_in_fight_phase(melee_scenario_file)
    gs = eng.game_state
    pool = fight_v11_current_pool(gs)
    assert pool, "l'étape FIGHT doit proposer au moins une sélection"
    squad_id = str(pool[0])

    ok, _result = eng._process_squad_action({"action": "squad_fight", "squad_id": squad_id})
    assert ok is True
    assert squad_id in {str(x) for x in gs["units_selected_to_fight"]}
    assert squad_id not in [str(x) for x in fight_v11_current_pool(gs)]


def test_squad_fight_outside_selection_pool_is_rejected(melee_scenario_file):
    """Parité masque/commit : le commit n'accepte que ce que le pool 12.04 propose.

    Le masque gym dérive du même `fight_v11_current_pool` ; une escouade hors pool est une
    rupture masque/commit, qui doit lever plutôt que résoudre un combat que la règle interdit.
    """
    from engine.phase_handlers.fight_handlers import fight_v11_current_pool

    eng = _engine_in_fight_phase(melee_scenario_file)
    gs = eng.game_state
    pool = {str(x) for x in fight_v11_current_pool(gs)}
    outsiders = [str(sid) for sid in gs["units_cache"] if str(sid) not in pool]
    assert outsiders, "le scénario doit comporter une escouade non sélectionnable"

    with pytest.raises(ValueError, match="hors du pool de selection 12.04"):
        eng._process_squad_action({"action": "squad_fight", "squad_id": outsiders[0]})


def test_squad_fight_rejected_when_machine_not_at_fight_step(melee_scenario_file):
    """`squad_fight` est une sélection de l'étape FIGHT : hors de cette étape, elle n'existe pas.

    Verrouille la rupture d'origine : l'ancien code résolvait un combat complet en sous-phase
    `'pile_in'`, c'est-à-dire avant que le snapshot 12.04 n'existe. Plutôt que de deviner un
    état, le moteur doit dire que la machine n'a pas été déroulée.
    """
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent", training_config_name="x1_debug", controlled_agent="ArmageddonAgent",
        scenario_file=melee_scenario_file, unit_registry=UnitRegistry(), quiet=True,
        gym_training_mode=True,
    )
    eng.reset(seed=1)
    gs = eng.game_state
    # Phase forcée sans démarrer la machine : `fight_subphase` reste None.
    gs["phase"] = "fight"
    squad_id = str(next(iter(gs["units_cache"])))

    with pytest.raises(RuntimeError, match="n a pas ete deroulee jusqu a l etape FIGHT"):
        eng._process_squad_action({"action": "squad_fight", "squad_id": squad_id})
