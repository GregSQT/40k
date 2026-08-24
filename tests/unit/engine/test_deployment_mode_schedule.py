"""Verrou du scheduler par-épisode auto↔active (`deployment_mode_schedule`).

Pilote le VRAI W40KEngine sur `scenario_fixed_brawl_sm_orks.json` et vérifie :
  - active_ratio 0.0/0.0  → tous les épisodes en 'auto'   (déploiement joué PAR LE MOTEUR) ;
  - active_ratio 1.0/1.0  → tous les épisodes en 'active' (déploiement joué par la politique) ;
  - rampe 0.0→1.0         → part 'active' croissante entre 1re et 2e moitié du training.

Ce que la rampe oppose a CHANGÉ le 2026-08-08, et c'est le sujet de ce fichier. Elle opposait
'active' à 'fixed' : rejouer les positions par figurine écrites dans le roster, SANS phase de
déploiement. Ces positions étaient générées hors ligne contre un seul terrain — elles tombaient
sur des murs dès qu'on en ajoutait un second (mesuré : jusqu'à 10 hex de mur sous un socle sur
`terrain-mc2`, `ValueError ... on wall hex` au chargement) et se plaçaient hors des zones de
déploiement même sur le terrain d'origine (12 à 17 figurines sur 23-37).

'auto' joue une VRAIE phase de déploiement ; seul change QUI décide des poses — le moteur, pas la
politique. Les deux modes ont donc désormais la même phase, et c'est justement ce qui rend ce
verrou nécessaire : leur différence n'est plus lisible dans `phase`, elle l'est dans le compteur
`_deployment_auto_steps`. Un test qui continuerait de séparer les modes par la phase serait vert
sans rien vérifier.

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


@pytest.fixture(autouse=True)
def _pin_board(board_x5):
    pass


def _make_env(start: float, end: float, total_episodes: int, freeze: float = 1.0, n_envs: int = 1):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    env = W40KEngine(
        rewards_config="ArmageddonAgent",
        training_config_name="x1",
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
    """Rejoue `n` épisodes et renvoie le mode tiré, en vérifiant la cohérence mode ↔ phase moteur.

    Les DEUX modes ouvrent la phase de déploiement : 'auto' n'est pas un raccourci qui la saute,
    c'est un déploiement joué. Une assertion de phase par mode ne dirait donc plus rien — elle est
    remplacée par l'invariant commun.
    """
    modes = []
    for _ in range(n):
        env.reset(seed=None)
        gs = env.game_state
        mode = gs["deployment_mode_schedule_mode"]
        phase = gs["phase"]
        assert mode in ("auto", "active"), f"mode inattendu {mode!r}"
        assert phase == "deployment", f"mode {mode!r} mais phase {phase!r} — les deux déploient"
        modes.append(mode)
    return modes


def test_ratio_zero_always_auto():
    """Borne basse : active_ratio 0.0 → 20/20 épisodes déployés par le moteur."""
    modes = _collect_modes(_make_env(0.0, 0.0, 100), 20)
    assert set(modes) == {"auto"}, f"ratio 0.0 devrait ne donner que 'auto', obtenu {set(modes)}"


def test_ratio_one_always_active():
    """Borne haute : active_ratio 1.0 → 20/20 épisodes avec phase de déploiement."""
    modes = _collect_modes(_make_env(1.0, 1.0, 100), 20)
    assert set(modes) == {"active"}, f"ratio 1.0 devrait ne donner que 'active', obtenu {set(modes)}"


def test_auto_mode_deploys_through_the_engine_and_never_into_reserves():
    """CE QUI SÉPARE 'auto' de 'active' : les poses viennent du moteur, et ce sont des POSES.

    Deux affirmations, indissociables. La première — le moteur a bien joué — se lit dans
    `_deployment_auto_steps` : sans elle, un 'auto' qui ne déploierait rien laisserait les unités
    hors table et le test précédent resterait vert (les modes et la phase seraient corrects).

    La seconde tient à un piège d'espace d'action : `ACTION_WAIT` est OUVERT en phase de
    déploiement et n'y est pas une attente — le jouer met l'unité en RÉSERVES STRATÉGIQUES
    (20.01). Un tirage uniforme sur le masque brut envoie donc des unités en réserves sans que
    personne l'ait demandé ; c'est le défaut mesuré côté bots au chantier 04c (TacticalBot,
    400 déploiements sur 400 en réserves). Le moteur tire sur `open_placement_slots`, jamais sur
    le masque brut, et c'est cette assertion qui l'exige.
    """
    env = _make_env(0.0, 0.0, 100)
    env.reset(seed=7)
    gs = env.game_state
    assert gs["deployment_mode_schedule_mode"] == "auto"
    controlled = int(env.config["controlled_player"])
    # Compté AVANT que le déploiement soit joué : c'est la déclaration du roster (20.01), la seule
    # référence contre laquelle une réserve créée en cours de déploiement se voit.
    reserves_declared = sum(1 for u in gs["units"]
                            if int(u["player"]) == controlled and u["in_strategic_reserves"])

    import numpy as np

    steps = 0
    while steps < 400 and str(gs["phase"]) == "deployment":
        mask = env.get_action_mask()
        legal = np.flatnonzero(mask)
        assert legal.size > 0, "plus aucune action légale en phase de déploiement"
        env.step(int(legal[0]))
        steps += 1
    assert str(gs["phase"]) != "deployment", f"toujours en déploiement après {steps} steps"

    auto_steps = gs.get("_deployment_auto_steps", 0)
    assert auto_steps > 0, (
        "le moteur n'a posé AUCUNE unité en mode 'auto' : le mode ne fait rien, et les "
        "assertions de mode/phase resteraient vertes sans lui"
    )

    # Le déploiement ne CRÉE pas de réserves : seules celles déclarées par le roster en sont.
    # Sans ce compte, un tirage qui jouerait `ACTION_WAIT` passerait inaperçu — les unités
    # envoyées en réserves sortent des boucles de vérification par la porte du `continue`.
    reserves_now = sum(1 for u in gs["units"]
                       if int(u["player"]) == controlled and u["in_strategic_reserves"])
    assert reserves_now == reserves_declared, (
        f"{reserves_now - reserves_declared} unité(s) mise(s) en réserves PAR LE DÉPLOIEMENT "
        f"(déclarées : {reserves_declared}). `ACTION_WAIT` a été joué comme si c'était une pose ; "
        "en phase de déploiement il met l'unité en réserves stratégiques (20.01)."
    )

    # VERT VACANT : sans figurine posée, l'assertion « dans la zone » ne regarderait rien.
    models_cache = gs["models_cache"]
    squad_models = gs["squad_models"]
    pools = {int(p): {(int(c), int(r)) for c, r in hexes}
             for p, hexes in gs["deployment_pools"].items()}
    placed = 0
    for unit in gs["units"]:
        if int(unit["player"]) != controlled or unit["in_strategic_reserves"]:
            continue
        for model_id in squad_models[str(unit["id"])]:
            model = models_cache[model_id]
            if int(model["col"]) < 0:
                continue
            placed += 1
            assert (int(model["col"]), int(model["row"])) in pools[controlled], (
                f"figurine {model_id} posée en ({model['col']},{model['row']}), hors de la zone "
                f"de déploiement du joueur {controlled} — c'est précisément ce que les positions "
                "pré-calculées du mode 'fixed' ne garantissaient pas"
            )
    assert placed > 0, "aucune figurine posée : le contrôle de zone ci-dessus ne regarde rien"


def test_engine_placement_pick_never_returns_action_wait():
    """Le tirage de pose ne rend JAMAIS `ACTION_WAIT`, même quand le masque l'ouvre.

    Verrou DÉTERMINISTE, et c'est le point : le test d'intégration ci-dessus ne peut pas prouver
    ça, parce qu'il faudrait espérer que `random.choice` tombe sur `ACTION_WAIT` pendant les
    quelques poses d'un épisode. On construit donc directement le masque piégeur — `ACTION_WAIT`
    ouvert à côté des slots de stratégie — et on épuise le tirage.

    Ce qui casse si la garde saute : `ACTION_WAIT` en phase de déploiement met l'unité en RÉSERVES
    STRATÉGIQUES (20.01). Une unité que l'agent croit sur la table joue son premier tour hors
    table, et le reward la note sur une partie qu'elle ne joue pas.
    """
    import numpy as np

    from engine import macro_intents as mi

    env = _make_env(0.0, 0.0, 100)
    mask = np.zeros(mi.TOTAL_ACTION_SIZE, dtype=bool)
    mask[mi.ACTION_WAIT] = True
    for slot in mi.DEPLOY_STRATEGY_SLOTS:
        mask[slot] = True

    picks = {env._pick_placement_action(mask, "test") for _ in range(200)}
    assert mi.ACTION_WAIT not in picks, (
        f"le tirage a rendu ACTION_WAIT ({mi.ACTION_WAIT}) : en déploiement ce n'est pas une "
        "attente, c'est une mise en RÉSERVES (20.01)"
    )
    assert picks <= set(mi.DEPLOY_STRATEGY_SLOTS), f"ids hors slots de stratégie : {picks}"
    # VERT VACANT : si le tirage ne rendait qu'un seul id, l'assertion ci-dessus tiendrait sans
    # rien dire du filtre. 200 tirages sur 7 slots ouverts doivent tous les visiter.
    assert picks == set(mi.DEPLOY_STRATEGY_SLOTS), (
        f"tous les slots ouverts devraient être atteignables, obtenu {sorted(picks)}"
    )


def test_engine_placement_pick_raises_when_no_slot_is_open():
    """Aucun slot de pose ouvert → erreur explicite, jamais un repli sur `ACTION_WAIT`.

    Un repli mettrait l'unité en réserves pour masquer un défaut moteur — c'est le fallback
    anti-erreur que ce dépôt proscrit. Le décodeur lève « Deployment deadlock » en amont ; si on
    arrive ici, l'état est faux et doit être bruyant.
    """
    import numpy as np
    import pytest as _pytest

    from engine import macro_intents as mi

    env = _make_env(0.0, 0.0, 100)
    mask = np.zeros(mi.TOTAL_ACTION_SIZE, dtype=bool)
    mask[mi.ACTION_WAIT] = True  # seul l'id piège est ouvert

    with _pytest.raises(RuntimeError, match="aucun slot de pose"):
        env._pick_placement_action(mask, "test")


def test_every_mode_the_ramp_can_emit_is_accepted_by_the_metrics_tracker():
    """Les modes PRODUITS par la rampe sont exactement ceux que les métriques ACCEPTENT.

    Ce verrou existe parce que son absence a coûté un défaut bloquant. En renommant `fixed` en
    `auto` (2026-08-08), `W40KMetricsTracker.DEPLOY_MODES` est resté sur `('active', 'fixed')` :
    `info["deployment_mode"] = 'auto'` remontait au tracker, qui lève `ValueError` en fin
    d'épisode — donc TOUT run d'entraînement mourait au premier épisode non-actif, soit ~70 % des
    épisodes en début de rampe. Rien ne le voyait : le test des métriques vérifiait `'fixed'` de
    son côté, le test de la rampe `'auto'` du sien, et les deux restaient verts.

    Le contrat est ici, entre les deux, et il est vérifié sur les modes RÉELLEMENT tirés par le
    moteur — pas sur une liste réécrite à la main, qui divergerait de la même façon.
    """
    from ai.metrics_tracker import W40KMetricsTracker

    emitted = set(_collect_modes(_make_env(0.0, 0.0, 100), 5))
    emitted |= set(_collect_modes(_make_env(1.0, 1.0, 100), 5))
    assert emitted, "aucun mode collecté — ce test ne prouverait rien"
    unknown = emitted - set(W40KMetricsTracker.DEPLOY_MODES)
    assert not unknown, (
        f"mode(s) {sorted(unknown)} produits par la rampe mais absents de "
        f"W40KMetricsTracker.DEPLOY_MODES {W40KMetricsTracker.DEPLOY_MODES} : le tracker lèvera en fin "
        "d'épisode et le run entier mourra"
    )
    # Symétrique : un mode déclaré côté métriques que la rampe ne produit plus laisse une série
    # TensorBoard vide en permanence, qu'on lit comme « pas de données » et non comme un oubli.
    assert set(W40KMetricsTracker.DEPLOY_MODES) == emitted, (
        f"DEPLOY_MODES {W40KMetricsTracker.DEPLOY_MODES} et modes réellement tirés {sorted(emitted)} "
        "ont divergé"
    )


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
        training_config_name="x1",
        controlled_agent="ArmageddonAgent",
        scenario_file=SCENARIO,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
        training_n_envs=1,
    )
    assert env.training_config is not None
    declared = json.loads(open(AGENT_CONFIG, encoding="utf-8-sig").read())["x1"]["n_envs"]
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
        training_config_name="x1",
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
# Tous les profils actifs (x1, x1_long, x1_debug) portent le bloc ; l'évaluation impose TOUJOURS
# une phase de déploiement. Aucun test ne lisait ce fichier avant ce verrou.

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
    ce fichier existe pour attraper, et un `len` non contraint le laisserait passer.
    Six profils actifs : `x1`/`x5_new` (runs courts de développement), `x1_long`/`x5_long`
    (runs de mesure), `x1_debug`/`x5_debug` (smoke tests). Les préfixes x1/x5 désignent la
    résolution du plateau, pas la longueur. `x1_selfplay` supprimé le 2026-08-17.
    """
    assert len(PROFILES) == 6, f"profils attendus : 6, trouvés {sorted(PROFILES)}"
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
