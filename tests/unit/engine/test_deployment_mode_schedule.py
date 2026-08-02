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


def _make_env(start: float, end: float, total_episodes: int, freeze: float = 1.0, n_envs: int = 1):
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
        training_n_envs=1,  # UN environnement joue en serie (engine/episode_schedule.py)
    )
    # Injection du contrat scheduler (training_only:false = on ne dépend pas du split de chemin).
    # Chemin training : la config de phase est chargée à l'init (le moteur lève sinon).
    assert env.training_config is not None
    env.training_config = dict(env.training_config)
    env.training_config["total_episodes"] = total_episodes
    # `n_envs` est le SECOND terme du dénominateur de la rampe : le compteur d'épisodes du moteur
    # est LOCAL à un environnement, donc la progression se rapporte à `total_episodes / n_envs`.
    # Les tests mono-env doivent donc poser n_envs=1 — le profil du fichier en déclare 48.
    env.training_config["n_envs"] = n_envs
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


# --- Vectorisation : la rampe se rapporte aux épisodes joués PAR ENVIRONNEMENT ----------------
#
# Défaut trouvé le 2026-08-02 sur le run x1_long (n_envs=48, total_episodes=200000) :
# `s_deploy_active_share` valait 0.3040 à 78 477 épisodes GLOBAUX, soit `active_ratio_start`,
# là où la rampe 0.3→0.8 attendait 0.496. Cause : le moteur divisait son compteur d'épisodes
# LOCAL (un par worker `SubprocVecEnv`) par le total GLOBAL — la rampe avançait 48 fois trop
# lentement et restait figée à sa valeur de départ sur toute la durée du run.
#
# Les tests ci-dessus n'exerçaient qu'UN environnement avec `total_episodes` égal au nombre
# d'épisodes rejoués : le compteur local ÉTAIT le compteur global, donc ils restaient verts.


def _p_active_sequence(env, n_episodes: int) -> list[float]:
    """Rejoue `n_episodes` sur UN environnement et renvoie la proba d''active' de chacun."""
    values = []
    for _ in range(n_episodes):
        env.reset(seed=None)
        values.append(float(env.game_state["deployment_mode_schedule_p_active"]))
    return values


def test_ramp_progresses_over_the_per_env_episode_budget() -> None:
    """4 environnements se partageant 40 épisodes : chacun doit parcourir la rampe ENTIÈRE.

    Contrôle DÉTERMINISTE sur `p_active` (et non sur le mode tiré) : c'est la rampe elle-même
    qui est en cause, pas le tirage. Avec le défaut, chaque env s'arrête à 9/39 = 0.23.
    """
    n_envs, total_episodes = 4, 40
    episodes_per_env = total_episodes // n_envs

    sequences = []
    for _ in range(n_envs):
        env = _make_env(0.0, 1.0, total_episodes, n_envs=n_envs)
        sequences.append(_p_active_sequence(env, episodes_per_env))

    for seq in sequences:
        assert seq == pytest.approx(sequences[0]), "envs identiques → même rampe attendue"
        assert seq[0] == pytest.approx(0.0), f"1er épisode hors rampe : {seq[0]}"
        assert seq[-1] == pytest.approx(1.0), (
            f"dernier épisode de l'env à p_active={seq[-1]:.3f} : la rampe n'a pas été parcourue "
            f"({episodes_per_env} épisodes par env pour {total_episodes} globaux)."
        )
    # Croissance stricte : une rampe gelée ou en escalier plat passerait les bornes ci-dessus
    # si elles étaient seules (elles ne le sont pas, mais l'intérieur doit aussi monter).
    assert all(b > a for a, b in zip(sequences[0], sequences[0][1:])), sequences[0]


def test_ramp_matches_the_measured_run_x1_long() -> None:
    """Reproduit le point de mesure du run : n_envs=48, 200 000 épisodes globaux.

    À 78 477 épisodes globaux chaque env a joué ~1 635 épisodes ; la rampe 0.3→0.8 doit valoir
    0.496. Avec le défaut elle vaut 0.3041 — la valeur relevée dans TensorBoard.
    """
    env = _make_env(0.3, 0.8, 200000, n_envs=48)
    env.episode_number = 1635  # compteur LOCAL au worker (pré-incrément dans reset)
    env._configure_deployment_mode_for_episode()
    p_active = float(env.game_state["deployment_mode_schedule_p_active"])
    assert p_active == pytest.approx(0.496, abs=0.005), (
        f"p_active={p_active:.4f} au point de mesure du run (attendu 0.496 ; 0.3041 = le défaut)"
    )


def test_runtime_n_envs_overrides_the_declared_profile_value() -> None:
    """`training_n_envs` (nombre d'envs RÉELLEMENT ouverts) prime sur le `n_envs` du profil.

    `--step`/`--replay` forcent un environnement unique alors que le profil en déclare 48. Sans
    cet écrasement, la rampe du moteur diviserait par 48 dans un run qui n'a qu'un env — 48 fois
    trop vite — pendant que la rampe self-play, elle, utilise le nombre résolu : deux
    dénominateurs pour la même grandeur dans le même run.
    """
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
        training_n_envs=1,
    )
    assert env.training_config is not None
    declared = json.loads(open(AGENT_CONFIG, encoding="utf-8-sig").read())["x5_new"]["n_envs"]
    assert declared > 1, "le profil doit déclarer plusieurs envs, sinon ce test ne prouve rien"
    assert env.training_config["n_envs"] == 1

    env.training_config = dict(env.training_config)
    env.training_config["total_episodes"] = 100
    env.training_config["deployment_mode_schedule"] = {
        "enabled": True, "training_only": False, "active_ratio_start": 0.0,
        "active_ratio_end": 1.0, "schedule": "linear", "freeze_after_progress": 1.0,
    }
    env.episode_number = 99  # dernier épisode du SEUL environnement
    env._configure_deployment_mode_for_episode()
    assert float(env.game_state["deployment_mode_schedule_p_active"]) == pytest.approx(1.0)


def test_unresolved_n_envs_refuses_to_ramp() -> None:
    """Un moteur construit SANS `training_n_envs` refuse de ramper, il ne devine pas.

    C'est le verrou anti-récidive : une fois dans `training_config`, le `n_envs` déclaré par le
    profil (48) et le `n_envs` du run (1 sous `--step`) sont indiscernables. Un site qui oublie
    de le résoudre repartirait donc en silence sur 48 environnements imaginaires.
    """
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
    assert env.training_config is not None
    assert env.training_config["n_envs"] > 1, "le profil déclare bien plusieurs envs"
    env.training_config = dict(env.training_config)
    env.training_config["deployment_mode_schedule"] = {
        "enabled": True, "training_only": False, "active_ratio_start": 0.0,
        "active_ratio_end": 1.0, "schedule": "linear", "freeze_after_progress": 1.0,
    }
    with pytest.raises(KeyError, match="training_n_envs"):
        env._configure_deployment_mode_for_episode()


def test_n_envs_missing_is_an_explicit_error() -> None:
    """Sans `n_envs`, la rampe n'a pas de dénominateur : erreur explicite, pas de valeur par défaut."""
    env = _make_env(0.3, 0.8, 1000, n_envs=4)
    assert env.training_config is not None
    del env.training_config["n_envs"]
    with pytest.raises(KeyError, match="n_envs"):
        env._configure_deployment_mode_for_episode()


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
    """Tous les profils portent EXACTEMENT le bloc de `x1` : aucune dérive possible entre eux.

    `x1` est la référence (profil de production) : c'est lui qu'on ajuste, les autres suivent.
    Le compte est figé exprès : un profil ajouté sans son bloc de déploiement est le défaut que
    ce fichier existe pour attraper, et un `len` non contraint le laisserait passer. Passé de 5
    à 6 le 2026-08-02 avec `x1_long` (runs longs), puis à 7 le même jour avec `x1_selfplay`
    (phase 2 — self-play sur un agent déjà entraîné vs bots).

    ⚠️ `x1_selfplay` porte le MÊME bloc que les autres, et ce n'est pas un oubli : la rampe de
    déploiement est une COMPÉTENCE ACQUISE, elle reprend là où la phase 1 l'a laissée (V11 §0.58).
    Le bloc y décrit donc le plafond atteint, pas une rampe rejouée.
    """
    assert len(PROFILES) == 7, f"profils attendus : 7, trouvés {sorted(PROFILES)}"
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
