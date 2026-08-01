"""Verrou du scheduler par-épisode fixed↔active (`deployment_mode_schedule`).

Pilote le VRAI W40KEngine sur `scenario_fixed_brawl_sm_orks.json` et vérifie :
  - active_ratio 0.0/0.0  → tous les épisodes en 'fixed'  (pas de phase 'deployment') ;
  - active_ratio 1.0/1.0  → tous les épisodes en 'active' (phase 'deployment') ;
  - rampe 0.0→1.0         → part 'active' croissante entre 1re et 2e moitié du training.

Le scheduler lit `self.training_config` ; le test l'injecte après construction (`training_only:
false` pour isoler la logique du split de chemin). Chemin gym réel, pas de reconstruction offline.

Rapatrié de `scripts/deployment_mode_schedule_test.py` (2026-07-26) : ce fichier vivait hors de
`tests/` et son nom `*_test.py` ne correspondait pas à `python_files = test_*.py`, donc il n'était
jamais collecté par la suite.
"""

from __future__ import annotations

import json
import os

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SCENARIO = os.path.join(PROJECT_ROOT, "config/board/44x60x5/scenario/scenario_fixed_brawl_sm_orks.json")
AGENT_CONFIG = os.path.join(
    PROJECT_ROOT, "config/agents/ArmageddonAgent/ArmageddonAgent_training_config.json"
)


def _make_env(start: float, end: float, total_episodes: int, freeze: float = 1.0):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    env = W40KEngine(
        rewards_config="ArmageddonAgent",
        training_config_name="x5_new",
        controlled_agent="ArmageddonAgent",
        scenario_file=SCENARIO,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
    )
    # Injection du contrat scheduler (training_only:false = on ne dépend pas du split de chemin).
    # Chemin training : la config de phase est chargée à l'init (le moteur lève sinon).
    assert env.training_config is not None
    env.training_config = dict(env.training_config)
    env.training_config["total_episodes"] = total_episodes
    env.training_config["deployment_mode_schedule"] = {
        "enabled": True,
        "training_only": False,
        "active_ratio_start": start,
        "active_ratio_end": end,
        "schedule": "linear",
        "freeze_after_progress": freeze,
    }
    return env


def _collect_modes(env, n: int) -> list[str]:
    """Rejoue `n` épisodes et renvoie le mode tiré, en vérifiant la cohérence mode ↔ phase moteur."""
    modes = []
    for _ in range(n):
        env.reset(seed=None)
        gs = env.game_state
        mode = gs["deployment_mode_schedule_mode"]
        phase = gs["phase"]
        if mode == "fixed":
            assert phase != "deployment", "mode 'fixed' mais phase 'deployment'"
        else:
            assert phase == "deployment", f"mode 'active' mais phase {phase!r}"
        modes.append(mode)
    return modes


def test_ratio_zero_always_fixed():
    """Borne basse : active_ratio 0.0 → 20/20 épisodes en placement manuel."""
    modes = _collect_modes(_make_env(0.0, 0.0, 100), 20)
    assert set(modes) == {"fixed"}, f"ratio 0.0 devrait ne donner que 'fixed', obtenu {set(modes)}"


def test_ratio_one_always_active():
    """Borne haute : active_ratio 1.0 → 20/20 épisodes avec phase de déploiement."""
    modes = _collect_modes(_make_env(1.0, 1.0, 100), 20)
    assert set(modes) == {"active"}, f"ratio 1.0 devrait ne donner que 'active', obtenu {set(modes)}"


def test_linear_ramp_increases_active_share():
    """Rampe 0→1 : la 2e moitié du training contient strictement plus d'épisodes 'active'."""
    modes = _collect_modes(_make_env(0.0, 1.0, 60), 60)
    first = sum(1 for m in modes[:30] if m == "active")
    second = sum(1 for m in modes[30:] if m == "active")
    assert second > first, f"rampe non croissante : 1re moitié={first} >= 2e moitié={second}"


# --- Le VRAI fichier de config : aucun profil ne doit perdre la rampe --------------------------
#
# `x5_append` et `x1_debug` n'avaient AUCUN bloc, `x5_new` et `x5_debug` finissaient à 0.0 : ils
# entraînaient un agent qui ne se déploie jamais, puis le notaient sur des parties à déployer
# (l'évaluation impose TOUJOURS une phase de déploiement). Aucun test ne lisait ce fichier.

with open(AGENT_CONFIG, encoding="utf-8-sig") as _f:
    PROFILES = {k: v for k, v in json.load(_f).items() if isinstance(v, dict)}

# Contrat lu dans `W40KEngine._configure_deployment_mode_for_episode` : toutes ces clés y passent
# par `require_key`, sans aucune valeur par défaut.
SCHEDULE_KEYS = {
    "enabled",
    "training_only",
    "active_ratio_start",
    "active_ratio_end",
    "schedule",
    "freeze_after_progress",
}


@pytest.mark.parametrize("profile_name", sorted(PROFILES))
def test_every_profile_carries_the_deployment_ramp(profile_name: str) -> None:
    """Chaque profil porte le bloc, et ce bloc a du SENS.

    Les valeurs de la rampe sont un réglage d'entraînement : les figer ici en dur ferait de ce
    test un miroir du fichier, rouge à chaque ajustement légitime sans rien prouver. Ce qui est
    verrouillé, c'est ce qui rend la rampe utilisable — et le fait qu'aucun profil ne dérive des
    autres (`test_all_profiles_share_the_same_ramp`, référence = `x1`).
    """
    profile = PROFILES[profile_name]
    assert "deployment_mode_schedule" in profile, (
        f"profil '{profile_name}' sans deployment_mode_schedule : la rampe serait désactivée "
        f"en silence et l'agent n'apprendrait jamais à se déployer."
    )
    cfg = profile["deployment_mode_schedule"]
    # `justification` : convention du fichier (cf. `observation_params.justification`). Elle porte
    # le raisonnement d'asymétrie entraînement/évaluation, qui ne doit pas vivre que dans le code.
    assert set(cfg) == SCHEDULE_KEYS | {"justification"}
    assert "EVALUATION IMPOSE TOUJOURS" in cfg["justification"]
    assert cfg["enabled"] is True
    assert cfg["training_only"] is True
    assert cfg["schedule"] == "linear"
    start, end = cfg["active_ratio_start"], cfg["active_ratio_end"]
    freeze = cfg["freeze_after_progress"]
    for key, val in (("active_ratio_start", start), ("active_ratio_end", end),
                     ("freeze_after_progress", freeze)):
        assert isinstance(val, (int, float)) and not isinstance(val, bool), key
        assert 0.0 <= float(val) <= 1.0, f"profil '{profile_name}' : {key}={val} hors [0,1]"
    assert start <= end, (
        f"profil '{profile_name}' : rampe DÉCROISSANTE ({start} → {end}) — la part d'épisodes en "
        f"déploiement actif baisserait au fil du run."
    )
    # PLAFOND EFFECTIF, et non `active_ratio_end` : `freeze_after_progress` gèle la progression,
    # donc la rampe s'arrête à `start + (end - start) * freeze`. Avec un gel à mi-run,
    # `active_ratio_end` n'est JAMAIS atteint et le lire seul surestime ce que l'agent voit.
    # C'est ce plafond qui doit rester majoritaire : sous 0.5, l'agent finit son entraînement en
    # jouant surtout des parties déjà déployées, alors que l'évaluation le déploie TOUJOURS.
    reached = start + (end - start) * freeze
    assert reached >= 0.5, (
        f"profil '{profile_name}' : plafond effectif {reached:.2f} (start={start}, end={end}, "
        f"freeze={freeze}) — la majorité des épisodes de fin de run reste en placement fixe."
    )
    # `total_episodes` est le dénominateur de la rampe : le scheduler lève sans lui.
    assert isinstance(profile["total_episodes"], int) and profile["total_episodes"] > 0


def test_all_profiles_share_the_same_ramp() -> None:
    """Les cinq profils portent EXACTEMENT le bloc de `x1` : aucune dérive possible entre eux.

    `x1` est la référence (profil de production) : c'est lui qu'on ajuste, les autres suivent.
    """
    assert len(PROFILES) == 5, f"profils attendus : 5, trouvés {sorted(PROFILES)}"
    reference = json.dumps(PROFILES["x1"]["deployment_mode_schedule"], sort_keys=True)
    diverged = {
        name: p.get("deployment_mode_schedule")
        for name, p in PROFILES.items()
        if json.dumps(p.get("deployment_mode_schedule"), sort_keys=True) != reference
    }
    assert not diverged, f"profils divergents de la référence x1 : {sorted(diverged)}"


def test_missing_block_in_an_agent_profile_is_an_explicit_error() -> None:
    """Un profil d'entraînement SANS bloc lève ; un fragment de config API n'est pas concerné.

    C'est le mécanisme qui a laissé deux profils diverger : `.get(...)` puis `return None`
    désactivait la rampe sans erreur ni trace.
    """
    env = _make_env(0.0, 0.8, 100)
    assert env._training_config_is_agent_profile is True
    # `W40KEngine.training_config` est legitimement Optional : le chemin API/PvP peut n'en
    # charger aucun (w40k_core l.316/330), et `_configure_deployment_mode_for_episode` rend
    # alors None sans lever. Ici c'est `_make_env` qui a POSE le profil : on l'affirme, sinon
    # le `del` ci-dessous echouerait pour la mauvaise raison et le test ne prouverait rien
    # sur le contrat vise (bloc manquant DANS un profil).
    profile_config = env.training_config
    assert profile_config is not None, "_make_env n'a pas injecte de profil d'entrainement"
    del profile_config["deployment_mode_schedule"]

    with pytest.raises(KeyError, match="deployment_mode_schedule est OBLIGATOIRE"):
        env._configure_deployment_mode_for_episode()

    # Chemin API/PvP (fragment de config, pas de profil) : absence légitime, pas d'erreur.
    env._training_config_is_agent_profile = False
    assert env._configure_deployment_mode_for_episode() is None
