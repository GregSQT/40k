"""Ce que les scenarios « rule-checker » ne verifiaient pas : que les regles marquees IMPLEMENTEE
existent vraiment dans le moteur, et que leurs unites se jouent.

Le dossier `config/rule_checker/scenarios/` a longtemps porte des milliers de fichiers commites,
et personne ne les executait : ils ont pourri (cle `objectives_ref` d'avant la migration V11,
refusee par le loader) sans qu'aucun controle ne bouge. Ils ne sont plus versionnes — ils sont
regeneres a la demande par `shared/rule_checker_scenarios.py` — et ce fichier prend le relais de
ce qu'ils pretendaient couvrir.

PORTEE EXACTE, plutot qu'un titre qui laisserait croire a une verification des EFFETS :
  - le contrat de CABLAGE (rapide) : une regle marquee `RULES_STATUS == 2` dans un roster existe
    au registre, est portee par la datasheet, et sa chaine d'alias se resout. C'est ce qui attrape
    la derive « marquee implementee, mais le moteur n'en sait rien » ;
  - le SMOKE moteur (un episode par regle) : les unites porteuses se deploient, jouent et
    terminent une partie. C'est ce que faisaient les scenarios generes, en version verifiable.
Ce que ce fichier ne fait PAS : verifier l'EFFET d'une regle (le +1, la relance, le mouvement
gratuit). Chaque effet a son test dedie sous tests/unit/engine/ ; un episode a actions aleatoires
ne declencherait pas ces situations de facon fiable, et pretendre le contraire serait un vert
vacant.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pytest

from ai.unit_registry import UnitRegistry
from engine.phase_handlers.shared_utils import (
    _get_unit_rules_registry,
    _resolve_effect_rule_id_to_technical,
)
from shared.rule_checker_scenarios import (
    DEFAULT_BOARD_REF,
    DEFAULT_SCALE,
    DEFAULT_TERRAIN_REF,
    build_scenario_payload,
    select_units,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]

_SELECTED_DETAILS = select_units(PROJECT_ROOT)[1]


def _pairs() -> List[Tuple[str, str]]:
    """(type d'unite, regle marquee implementee), tel que le roster le declare."""
    return [(row["unit_type"], rule) for row in _SELECTED_DETAILS for rule in row["implemented_rules"]]


def _one_unit_per_rule() -> Dict[str, str]:
    """UN type porteur par regle : le smoke coute un episode moteur, le carre n'apporte rien.

    Le premier par ordre alphabetique — deterministe, donc reproductible d'un run a l'autre.
    """
    by_rule: Dict[str, str] = {}
    for unit_type, rule in sorted(_pairs()):
        by_rule.setdefault(rule, unit_type)
    return by_rule


def test_the_selection_is_not_empty() -> None:
    """VERT VACANT : sans cet appui, une selection vide rendrait tout ce fichier trivialement vert."""
    assert _SELECTED_DETAILS, "aucune unite a RULES_STATUS == 2 : les tests ci-dessous ne verraient rien"
    assert len(_one_unit_per_rule()) >= 10, "trop peu de regles distinctes pour un controle utile"


@pytest.mark.parametrize("unit_type, rule_id", _pairs())
def test_a_rule_marked_implemented_is_wired_to_the_engine(unit_type: str, rule_id: str) -> None:
    """Marquer 2 dans un roster n'implemente rien : le cablage doit exister en face."""
    registry = _get_unit_rules_registry()
    assert rule_id in registry, (
        f"{unit_type} : RULES_STATUS declare {rule_id!r} implementee, mais la regle est absente "
        "de config/unit_rules.json — le moteur ne peut pas la resoudre"
    )

    # La resolution suit la chaine d'alias (les regles d'AFFICHAGE pointent vers l'effet
    # technique) et leve sur un alias inconnu ou cyclique.
    technical = _resolve_effect_rule_id_to_technical(rule_id)
    assert technical in registry

    entries = UnitRegistry().get_unit_data(unit_type).get("UNIT_RULES") or []
    carried = {e["ruleId"] for e in entries} | {
        granted for e in entries for granted in (e.get("grants_rule_ids") or [])
    }
    assert rule_id in carried, (
        f"{unit_type} : RULES_STATUS declare {rule_id!r} implementee, mais la datasheet ne la "
        f"porte pas (UNIT_RULES : {sorted(carried)}) — le moteur ne l'appliquera jamais a cette "
        "unite"
    )


@pytest.mark.parametrize("rule_id, unit_type", sorted(_one_unit_per_rule().items()))
def test_a_unit_carrying_the_rule_can_play_a_whole_episode(rule_id: str, unit_type: str) -> None:
    """Le matchup rule-checker, joue pour de vrai : 2v2 du meme type, actions legales au hasard.

    C'est exactement ce que `--rule-checker` fait jouer a l'agent. Le verifier ici sur UN episode
    par regle attrape ce que les fichiers commites ne pouvaient plus attraper : une datasheet, un
    profil d'arme ou une regle qui fait lever le moteur en cours de partie.
    """
    from engine.w40k_core import W40KEngine

    payload = build_scenario_payload(
        unit_type, unit_type, DEFAULT_SCALE, DEFAULT_BOARD_REF, DEFAULT_TERRAIN_REF
    )
    with tempfile.TemporaryDirectory() as tmp:
        scenario_path = Path(tmp) / f"rule_checker_{rule_id}.json"
        scenario_path.write_text(json.dumps(payload), encoding="utf-8")

        engine = W40KEngine(
            rewards_config="ArmageddonAgent_x1",
            training_config_name="x1_debug",
            controlled_agent="ArmageddonAgent_x1",
            scenario_file=str(scenario_path),
            unit_registry=UnitRegistry(),
            quiet=True,
            gym_training_mode=True,
            training_n_envs=1,
        )
        engine.reset(seed=0)

        rng = np.random.default_rng(0)
        steps = 0
        while steps < 3000 and not engine.game_state.get("game_over"):
            legal = np.flatnonzero(np.asarray(engine.get_action_mask(), dtype=bool))
            assert legal.size > 0, (
                f"{unit_type} ({rule_id}) : masque vide au step {steps} — le moteur est bloque, "
                "aucune action legale a jouer"
            )
            engine.step_with_mask(int(rng.choice(legal)))
            steps += 1

        assert engine.game_state.get("game_over"), (
            f"{unit_type} ({rule_id}) : {steps} steps sans fin de partie — episode qui boucle"
        )
        assert steps > 1, "episode termine sans avoir rien joue : rien n'a ete observe"
