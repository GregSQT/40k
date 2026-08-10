"""Verrou des trois marqueurs perf qui couvrent le coeur d'un step agent.

Motif d'echec deja vecu dans ce depot : `SHOOT_ACTIVATION_START` est declare dans la doc et dans
`ROWS`, mais son emetteur n'est jamais atteint — 0 ligne sur un log de 222 000 lignes, sans que
rien ne le signale (le rapport affiche simplement une ligne de moins). Une instrumentation muette
est PIRE qu'une instrumentation absente : elle fait croire que la zone est mesuree et propre.

Mesure du 2026-08-10 qui a motive ces marqueurs : sur une evaluation `--test-only --step`, les
compteurs perf existants ne couvraient que 6,5 % du temps reel, alors que `SQUAD_OBSERVATION`,
`SQUAD_ACTION_MASK` et `SQUAD_MOVE_CELL_MAP` en font ~42 % a eux trois.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest

from engine import perf_timing
from engine.observation_builder import ObservationBuilder
from engine.phase_handlers.shared_utils import (
    build_squad_action_mask,
    build_squad_move_cell_map,
)
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config


def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
        "WEAPON_RULES": [], "display_name": "Test Bolter",
    }


def _unit_cfg(uid: int, player: int, positions: List[Tuple[int, int]]) -> Dict[str, Any]:
    specs = [{"col": c, "row": r, "HP_CUR": 1, "HP_MAX": 1, "VALUE": 10} for c, r in positions]
    return {
        "id": uid, "player": player, "col": positions[0][0], "row": positions[0][1],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": len(specs), "HP_MAX": 1, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [_weapon_cfg()],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}],
        "LD": 7, "OC": 2, "VALUE": 10 * len(specs),
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "models": specs,
    }


def _config(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    return {
        "board": {
            "default": {
                "cols": 60, "rows": 40, "hex_radius": 1.0, "margin": 0.0,
                "wall_hexes": [], "inches_to_subhex": 1,
            }
        },
        "game_rules": {
            "engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35,
            "unit_model_cohesion_range": 2, "unit_global_cohesion_range": 9,
            "squad_min_neighbors": 1, "cohesion_distance_mode": "euclidean",
        },
        "charge": {"charge_max_distance": 12},
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "pve_mode": False,
        "scenario_objectives": [],
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": units,
    }


@pytest.fixture
def engine() -> W40KEngine:
    units = [_unit_cfg(1, 1, [(10, 10), (11, 10)]), _unit_cfg(2, 2, [(30, 10)])]
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(_config(units)))
    eng.reset()
    eng.game_state["phase"] = "move"
    return eng


@pytest.fixture
def perf_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Active la perf sur un fichier dedie et rend un lecteur qui flushe avant de lire."""
    log = tmp_path / "perf.log"
    monkeypatch.setenv("W40K_PERF_TIMING", "1")
    monkeypatch.setenv("W40K_PERF_TIMING_LOG", str(log))
    monkeypatch.delenv("W40K_PERF_TIMING_MIN_EPISODE", raising=False)
    # Le handle est un GLOBAL du module, potentiellement deja ouvert sur un autre chemin par un
    # test precedent : sans purge, les lignes iraient dans l'ancien fichier et le test lirait vide.
    perf_timing._flush_perf_file()

    def _read() -> List[str]:
        perf_timing._flush_perf_file()
        if not log.exists():
            return []
        return [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]

    yield _read
    perf_timing._flush_perf_file()


def _events(lines: List[str], name: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for line in lines:
        parts = line.split()
        if parts and parts[0] == name:
            out.append(dict(p.split("=", 1) for p in parts[1:] if "=" in p))
    return out


def test_observation_emet_sa_ligne(engine: W40KEngine, perf_log) -> None:
    engine.obs_builder.build_squad_observation(engine.game_state, "1")
    rows = _events(perf_log(), "SQUAD_OBSERVATION")
    assert len(rows) == 1
    row = rows[0]
    assert row["outcome"] == "built"
    assert row["squad"] == "1"
    # `entities_n` compte les lignes REELLEMENT ecrites : 1 allie (l'active) + 1 ennemi.
    assert int(row["entities_n"]) == 2
    assert float(row["total_s"]) > 0.0
    # La decoupe doit sommer au total, sinon un segment entier echappe a la mesure.
    assert float(row["ctx_s"]) + float(row["entities_s"]) == pytest.approx(
        float(row["total_s"]), abs=1e-6
    )


def test_masque_emet_sa_ligne(engine: W40KEngine, perf_log) -> None:
    mask = build_squad_action_mask(engine.game_state, "1")
    rows = _events(perf_log(), "SQUAD_ACTION_MASK")
    assert len(rows) == 1
    row = rows[0]
    assert row["outcome"] == "built"
    assert row["phase"] == "move"
    # `ones_n` doit decrire le masque rendu, pas un compteur interne desynchronise.
    assert int(row["ones_n"]) == sum(mask)
    assert float(row["total_s"]) > 0.0


def test_masque_squad_absent_emet_quand_meme(engine: W40KEngine, perf_log) -> None:
    """Le retour anticipe « squad absent -> all-zero » est un chemin de production (unite morte).
    Sans ligne, il devient un trou invisible dans la mesure."""
    build_squad_action_mask(engine.game_state, "999")
    rows = _events(perf_log(), "SQUAD_ACTION_MASK")
    assert len(rows) == 1
    assert rows[0]["outcome"] == "squad_absent"
    assert int(rows[0]["ones_n"]) == 0


def test_cell_map_distingue_hit_et_miss(engine: W40KEngine, perf_log) -> None:
    """Le champ `cache_hit` est la raison d'etre du marqueur : sans lui on ne sait pas si le
    cout vient du BFS ou du fingerprint recalcule a chaque appel."""
    build_squad_move_cell_map(engine.game_state, "1", None)
    build_squad_move_cell_map(engine.game_state, "1", None)
    rows = _events(perf_log(), "SQUAD_MOVE_CELL_MAP")
    assert len(rows) == 2
    miss, hit = rows[0], rows[1]
    assert miss["cache_hit"] == "0"
    assert hit["cache_hit"] == "1"
    # Sur un miss, le BFS et l'erosion sont payes ; sur un hit, seul le fingerprint l'est.
    assert float(miss["pool_s"]) > 0.0
    assert float(hit["pool_s"]) == 0.0
    assert float(hit["fp_s"]) > 0.0
    assert float(hit["total_s"]) < float(miss["total_s"])
    assert miss["cells_n"] == hit["cells_n"]


def test_perf_desactivee_n_ecrit_rien(engine: W40KEngine, tmp_path: Path,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """Contre-epreuve du VERT VACANT : si les trois marqueurs ecrivaient inconditionnellement,
    les tests ci-dessus passeraient aussi avec la perf coupee — et le moteur paierait le log en
    entrainement. On verifie donc que le silence est reel, sur les MEMES appels."""
    log = tmp_path / "perf_off.log"
    monkeypatch.delenv("W40K_PERF_TIMING", raising=False)
    monkeypatch.setenv("W40K_PERF_TIMING_LOG", str(log))
    perf_timing._flush_perf_file()
    engine.obs_builder.build_squad_observation(engine.game_state, "1")
    build_squad_action_mask(engine.game_state, "1")
    build_squad_move_cell_map(engine.game_state, "1", None)
    perf_timing._flush_perf_file()
    assert not log.exists() or log.read_text(encoding="utf-8").strip() == ""
