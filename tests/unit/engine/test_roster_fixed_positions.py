"""Verrou : positions top/bottom dans les rosters, chemin roster réel (rotation aléatoire SM/Orks).

Pilote le VRAI W40KEngine sur le template de training `scenario_training_armageddon.json`
(agent_roster_ref=training_random, opponent_roster_ref=[SM,Orks], siège aléatoire) et vérifie :
  - mode 'fixed'  : AUCUN déploiement, toutes les unités placées, joueur 1 en bande HAUTE (top),
    joueur 2 en bande BASSE (bottom) — quel que soit le roster tiré et le siège ;
  - mode 'active' : phase de déploiement, unités en sentinelle (positions ignorées).

Le mode est imposé via le scheduler `deployment_mode_schedule` injecté après construction.

Rapatrié de `scripts/roster_fixed_positions_test.py` (2026-07-26) : ce fichier vivait hors de
`tests/` et son nom `*_test.py` ne correspondait pas à `python_files = test_*.py`, donc il n'était
jamais collecté par la suite.
"""

from __future__ import annotations

import os

from engine.phase_handlers.shared_utils import validate_squad_coherency
from shared.data_validation import require_key

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
TEMPLATE = os.path.join(
    PROJECT_ROOT, "config/agents/ArmageddonAgent/scenarios/training/scenario_training_armageddon.json"
)
MIDLINE = 150  # séparation top/bottom du board 220x300


def _make_env(active_ratio: float):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    env = W40KEngine(
        rewards_config="ArmageddonAgent",
        training_config_name="x5_new",
        controlled_agent="ArmageddonAgent",
        scenario_file=TEMPLATE,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
        training_n_envs=1,  # UN environnement joue en serie (engine/episode_schedule.py)
    )
    # Chemin training : la config de phase est chargée à l'init (le moteur lève sinon).
    assert env.training_config is not None
    env.training_config = dict(env.training_config)
    env.training_config["deployment_mode_schedule"] = {
        "enabled": True,
        "training_only": False,
        "active_ratio_start": active_ratio,
        "active_ratio_end": active_ratio,
        "schedule": "linear",
        "freeze_after_progress": 1.0,
    }
    return env


def test_fixed_mode_places_players_in_their_own_band():
    """Mode 'fixed' : 8 épisodes, aucun déploiement, P1 en bande haute / P2 en bande basse."""
    env = _make_env(0.0)
    placed_total = 0
    reserved_total = 0
    for _ep in range(8):
        env.reset(seed=None)
        gs = env.game_state
        assert gs["deployment_mode_schedule_mode"] == "fixed", "scheduler n'a pas produit 'fixed' à ratio 0.0"
        assert gs["phase"] != "deployment", "mode fixed : phase 'deployment' rencontrée"

        for u in gs["units"]:
            # 20.01 — une unité MISE EN RÉSERVES démarre HORS TABLE, y compris en mode 'fixed' :
            # les coordonnées du roster ne la concernent pas, elle arrivera par un ingress 20.04.
            # Ce n'est pas une exception au contrat « fixed = tout est posé », c'est le contrat
            # lui-même : `fixed` fixe le PLACEMENT des unités déployées, pas la composition.
            # Sa mise en place a son propre verrou (tests/unit/engine/test_reserves_full_episode.py).
            if require_key(u, "in_strategic_reserves"):
                reserved_total += 1
                models = u.get("models", [u])  # get allowed (unité mono-figurine)
                for m in models:
                    assert int(m["col"]) < 0, (
                        f"unité {u['id']} en réserves 20.01 mais figurine POSÉE (col={m['col']}) "
                        "— une réserve n'est pas sur la table avant son ingress"
                    )
                continue
            models = u.get("models", [u])  # get allowed (unité mono-figurine)
            for m in models:
                assert m["col"] >= 0, f"mode fixed : figurine non placée (unité {u['id']})"
                placed_total += 1
                side_ok = (m["row"] < MIDLINE) if int(u["player"]) == 1 else (m["row"] >= MIDLINE)
                assert side_ok, (
                    f"joueur {u['player']} figurine hors de sa bande (row={m['row']}, "
                    f"midline={MIDLINE}) — convention P1=top / P2=bottom violée"
                )
            # Cohérence d'escouade via la SOURCE DE VÉRITÉ moteur (03.03) — pas de réimplémentation :
            # validate_squad_coherency lit models_cache et applique game_rules (voisins, bord-à-bord,
            # étalement 9"). Une formation non conforme au départ échouerait ici.
            if len(models) >= 2:
                assert validate_squad_coherency(gs, str(u["id"])), (
                    f"unité {u['id']} ({u['unitType']}) démarre NON-COHÉRENTE "
                    f"(validate_squad_coherency, règle moteur 03.03)"
                )

    assert placed_total > 0, "aucune figurine inspectée — test sans valeur"
    # `reserved_total` n'est PAS asserté : le roster est tiré au sort, une série de 8 épisodes
    # peut légitimement n'en tirer aucun à réserves. Le cas « réserves en mode fixed » est
    # construit — pas espéré d'un tirage — par `test_fixed_mode_leaves_reserves_off_the_table`.


def test_fixed_mode_leaves_reserves_off_the_table():
    """Mode 'fixed' + roster à réserves 20.01 : le reset PASSE, et la réserve reste hors table.

    VERROU DU DÉFAUT MESURÉ LE 2026-08-05. Les zones de déploiement ne vivaient que dans
    ``game_state["deployment_state"]``, écrit uniquement quand un joueur déploie en 'active'. En
    mode 'fixed', une unité en réserves est hors table dès le reset : ``squad_grid_anchor`` (ancre
    de grille d'une escouade non posée) et ``_opponent_deployment_zone_cells`` (clause « pas dans
    la zone adverse avant le 3e round », 20.04) levaient toutes deux « Required key
    'deployment_state' », et le reset entier avec — sur 20 à 70 % des épisodes des profils réels,
    qui tirent 'fixed' à ce taux.

    Ce test CONSTRUIT le cas au lieu de l'espérer d'un tirage : il épingle la fixture à réserves
    déclarées des deux côtés et force le mode 'fixed'.
    """
    import os as _os

    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    fixture = _os.path.join(
        PROJECT_ROOT,
        "config/agents/ArmageddonAgent/scenarios/training/reserves_full_episode_fixture.json",
    )
    env = W40KEngine(
        rewards_config="ArmageddonAgent",
        training_config_name="x5_new",
        controlled_agent="ArmageddonAgent",
        scenario_file=fixture,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
        training_n_envs=1,
    )
    assert env.training_config is not None
    env.training_config = dict(env.training_config)
    env.training_config["deployment_mode_schedule"] = {
        "enabled": True,
        "training_only": False,
        "active_ratio_start": 0.0,
        "active_ratio_end": 0.0,
        "schedule": "linear",
        "freeze_after_progress": 1.0,
    }
    env.reset(seed=0)
    gs = env.game_state

    assert gs["deployment_mode_schedule_mode"] == "fixed", "le mode 'fixed' n'a pas été produit"
    assert gs["phase"] != "deployment", "mode fixed : phase 'deployment' rencontrée"
    # Les zones sont lisibles HORS phase de déploiement — c'est la correction elle-même.
    assert "deployment_pools" in gs, (
        "les zones de déploiement ne sont pas publiées en mode 'fixed' : la clause 20.04 et "
        "l'ancre de grille d'une unité hors table redeviennent invérifiables"
    )

    reserves = [u for u in gs["units"] if require_key(u, "in_strategic_reserves")]
    assert reserves, (
        "la fixture ne met aucune unité en réserves : ce test ne prouverait rien (vert vacant)"
    )
    players = {int(u["player"]) for u in reserves}
    assert players == {1, 2}, f"réserves sur les seuls joueurs {sorted(players)} — un côté manque"
    for u in reserves:
        for m in u.get("models", [u]):  # get allowed (unité mono-figurine)
            assert int(m["col"]) < 0, (
                f"unité {u['id']} en réserves mais posée en mode fixed (col={m['col']})"
            )


def test_active_mode_keeps_units_at_sentinel():
    """Mode 'active' : 3 épisodes, phase 'deployment', positions du roster ignorées."""
    env = _make_env(1.0)
    for _ep in range(3):
        env.reset(seed=None)
        gs = env.game_state
        assert gs["deployment_mode_schedule_mode"] == "active", "scheduler n'a pas produit 'active' à ratio 1.0"
        assert gs["phase"] == "deployment", f"mode active : phase attendue 'deployment', obtenue {gs['phase']!r}"
        assert any(u["col"] < 0 for u in gs["units"]), "mode active : aucune unité en sentinelle"
