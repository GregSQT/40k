"""Verrou : une etape REPRISE A CHAUD ne redemarre pas la rampe de deploiement.

`active_ratio_start -> active_ratio_end` est une fraction de la duree du run
(`engine/episode_schedule.py::ramp_progress`). Une etape qui reprend les poids d'une autre
herite d'un modele ayant deja parcouru sa rampe ; la redemarrer a `active_ratio_start` renvoie
la majorite des episodes en deploiement 'auto' pour un modele qui sait se deployer, alors que
l'evaluation impose toujours le deploiement actif.

Mesure qui motive ce verrou (run du 2026-09-03, P1 repris de P00) : `active_ratio` valait 0.315
a l'episode 5000 d'un run de 200 000, la ou P00 avait termine a 0.9.

Ce que ces tests separent :
  - reprise a chaud  -> `start` est fige sur `end` ;
  - demarrage a froid -> la rampe est INTACTE (elle sert a ne pas jeter une politique naive
    dans le deploiement complet) ;
  - etape exploiteur  -> couverte comme les autres, alors qu'elle n'a droit a aucun
    `training_config_overrides` : c'est ce que le passage par le code, et non par le JSON,
    permet de garantir.
"""

import os

import pytest

from ai.train import (
    _install_stage_config_overrides,
    _pin_deployment_ramp_for_warm_start,
)

AGENT = "ArmageddonAgent_x1"
# Quatre `dirname` : ce fichier est a tests/unit/ai/, la racine est donc quatre crans au-dessus.
# Trois pointait sur tests/ et faisait chercher ai/train.py sous tests/ai/.
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)


@pytest.fixture
def restore_global_loader():
    """Rend au singleton `get_config_loader()` sa methode d'origine.

    `_install_stage_config_overrides` DECORE le loader du processus, et ce loader est un
    singleton partage par toute la suite. Sans cette restauration, le premier test qui l'installe
    laisse tous les suivants — y compris d'autres FICHIERS — lire une config figee a 0.9. Le
    defaut a ete constate ici meme avant d'etre ferme.
    """
    from config_loader import get_config_loader

    loader = get_config_loader()
    original = loader.load_agent_training_config
    try:
        yield loader
    finally:
        loader.load_agent_training_config = original


def _schedule(start: float, end: float) -> dict:
    """Bloc complet : le moteur exige les six cles par `require_key`, sans defaut."""
    return {
        "enabled": True,
        "training_only": True,
        "active_ratio_start": start,
        "active_ratio_end": end,
        "schedule": "linear",
        "freeze_after_progress": 1.0,
    }


def _cfg(start: float = 0.3, end: float = 0.9) -> dict:
    return {"total_episodes": 200000, "deployment_mode_schedule": _schedule(start, end)}


class _StubConfig:
    """Substitut de config loader : rend une config NEUVE a chaque appel.

    Neuve et non partagee, sinon un test verrait la mutation du precedent et le verrou serait
    vert sans rien prouver.
    """

    def __init__(self, start: float = 0.3, end: float = 0.9) -> None:
        self._start = start
        self._end = end
        self.calls = 0

    def load_agent_training_config(self, agent_key: str, phase=None) -> dict:
        self.calls += 1
        return _cfg(self._start, self._end)


# ── _pin_deployment_ramp_for_warm_start ─────────────────────────────────────

def test_warm_start_pins_start_on_end():
    cfg = _cfg(0.3, 0.9)
    _pin_deployment_ramp_for_warm_start(cfg)
    assert cfg["deployment_mode_schedule"]["active_ratio_start"] == 0.9
    assert cfg["deployment_mode_schedule"]["active_ratio_end"] == 0.9


def test_already_constant_ramp_is_left_alone():
    cfg = _cfg(0.9, 0.9)
    _pin_deployment_ramp_for_warm_start(cfg)
    assert cfg["deployment_mode_schedule"]["active_ratio_start"] == 0.9


def test_absent_block_is_left_to_the_engine():
    # Le moteur refuse deja l'absence par require_key, avec le contexte utile : dupliquer le
    # refus ici ferait diverger deux messages pour une meme faute.
    cfg = {"total_episodes": 200000}
    _pin_deployment_ramp_for_warm_start(cfg)  # ne leve pas


def test_missing_ratio_key_raises():
    schedule = _schedule(0.3, 0.9)
    del schedule["active_ratio_end"]
    with pytest.raises(Exception):
        _pin_deployment_ramp_for_warm_start({"deployment_mode_schedule": schedule})


# ── _install_stage_config_overrides ─────────────────────────────────────────

def test_warm_start_pins_the_ramp_on_every_reload():
    """La config est rechargee a plusieurs endroits : toutes doivent voir la meme rampe.

    C'est la raison d'etre du decorateur — figer sur un seul exemplaire laisserait les
    callbacks et `build_training_opponents` sur la rampe non figee, en silence.
    """
    stub = _StubConfig(0.3, 0.9)
    _install_stage_config_overrides(stub, AGENT, None, {}, warm_start=True)
    for _ in range(3):
        cfg = stub.load_agent_training_config(AGENT)
        assert cfg["deployment_mode_schedule"]["active_ratio_start"] == 0.9
    assert stub.calls == 3


def test_cold_start_keeps_the_ramp_intact():
    stub = _StubConfig(0.3, 0.9)
    _install_stage_config_overrides(stub, AGENT, None, {}, warm_start=False)
    cfg = stub.load_agent_training_config(AGENT)
    assert cfg["deployment_mode_schedule"]["active_ratio_start"] == 0.3
    assert cfg["deployment_mode_schedule"]["active_ratio_end"] == 0.9


def test_another_agent_is_not_touched():
    stub = _StubConfig(0.3, 0.9)
    _install_stage_config_overrides(stub, AGENT, None, {}, warm_start=True)
    cfg = stub.load_agent_training_config("AutreAgent")
    assert cfg["deployment_mode_schedule"]["active_ratio_start"] == 0.3


def test_pinned_ramp_uses_the_profile_end_not_one():
    """Fige sur `end`, jamais sur 1.0.

    Un profil garde deliberement une part d'episodes en 'auto' pour que la courbe de controle
    `r_win_rate_deploy_auto` continue de mesurer quelque chose ; figer a 1.0 la tuerait.
    """
    stub = _StubConfig(0.3, 0.8)
    _install_stage_config_overrides(stub, AGENT, None, {}, warm_start=True)
    cfg = stub.load_agent_training_config(AGENT)
    assert cfg["deployment_mode_schedule"]["active_ratio_start"] == 0.8


def test_hp_overrides_still_apply_alongside_the_pinning():
    stub = _StubConfig(0.3, 0.9)
    _install_stage_config_overrides(
        stub, AGENT, None, {"total_episodes": 12345}, warm_start=True
    )
    cfg = stub.load_agent_training_config(AGENT)
    assert cfg["total_episodes"] == 12345
    assert cfg["deployment_mode_schedule"]["active_ratio_start"] == 0.9


# ── Traversee de la frontiere de processus ──────────────────────────────────
#
# LE verrou du sujet. Le figeage est pose dans le parent en decorant le loader, mais un worker
# vectorise demarre en `forkserver`/`spawn` : il reimporte tout et rappelle un loader NON decore.
# Une premiere version du correctif ne passait QUE par le decorateur — verte sur tous les tests
# en-process ci-dessus, et pourtant un no-op complet en production (n_envs=24). Mesure du defaut :
# parent 0.9, worker 0.3. Ces deux tests separent ce que le decorateur ne peut pas faire de ce
# que le passage en donnee garantit.

def test_the_decorator_alone_does_not_cross_a_forkserver_boundary(restore_global_loader):
    """Constat, pas un regret : c'est CE fait qui impose de passer la valeur en argument.

    Si ce test devenait rouge, cela voudrait dire qu'un patch de loader se propage desormais aux
    workers — et alors seulement `parent_deploy_active_ratio_start` deviendrait superflu.
    """
    import multiprocessing as mp

    if "forkserver" not in mp.get_all_start_methods():
        pytest.skip("forkserver indisponible sur cette plateforme")

    loader = restore_global_loader
    _install_stage_config_overrides(loader, AGENT, None, {}, warm_start=True)
    parent = loader.load_agent_training_config(AGENT, "x1_long")
    assert parent["deployment_mode_schedule"]["active_ratio_start"] == 0.9

    ctx = mp.get_context("forkserver")
    queue = ctx.Queue()
    proc = ctx.Process(target=_read_ratio_in_child, args=(queue,))
    proc.start()
    proc.join(timeout=120)
    assert proc.exitcode == 0, "le worker n'a pas pu lire la config"
    assert queue.get(timeout=10) == 0.3, (
        "le worker verrait le figeage du parent : le passage en donnee ne serait plus la seule "
        "voie, et le commentaire de W40KEngine.__init__ serait faux."
    )


# Le pendant moteur — `training_deploy_active_ratio_start` applique sur un VRAI W40KEngine —
# vit dans tests/unit/engine/test_deployment_mode_schedule.py, qui possede deja le contrat de
# cette rampe et le fixture `board_x5` qu'un scenario 44x60x5 exige.


def _read_ratio_in_child(queue) -> None:
    """Cible du process enfant. Au niveau module : `forkserver` doit pouvoir la pickler."""
    from config_loader import get_config_loader

    cfg = get_config_loader().load_agent_training_config(AGENT, "x1_long")
    queue.put(cfg["deployment_mode_schedule"]["active_ratio_start"])


# ── Verrou structurel : aucun site de construction ne peut oublier l'argument ────────────────
#
# Le defaut d'origine n'etait pas une valeur fausse mais un site OUBLIE : le figeage n'atteignait
# pas le moteur du worker. Un test de comportement ne couvre pas un site qui n'existe pas encore ;
# celui-ci lit l'AST de `ai/train.py` et exige que la famille reste complete.
#
# `training_episode_start_index` sert de marqueur : c'est l'autre etat par-environnement qui doit
# traverser jusqu'au moteur. Tout site qui le passe monte un environnement d'ENTRAINEMENT et doit
# donc aussi poser le depart de rampe. Le chemin API/PvP, lui, ne le passe pas et n'est pas vise.

def test_every_training_env_site_also_passes_the_deploy_ratio():
    import ast

    train_py = os.path.join(PROJECT_ROOT, "ai", "train.py")
    with open(train_py, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())

    ratio_kwargs = {"training_deploy_active_ratio_start", "deploy_active_ratio_start"}
    markers = {"training_episode_start_index", "episode_start_index"}

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name not in ("W40KEngine", "make_training_env"):
            continue
        kwargs = {kw.arg for kw in node.keywords if kw.arg}
        if not (kwargs & markers):
            continue
        if not (kwargs & ratio_kwargs):
            offenders.append(f"{name} ligne {node.lineno}")

    assert not offenders, (
        "site(s) de construction d'environnement d'entrainement sans depart de rampe : "
        f"{offenders}. Un worker forkserver y relirait la valeur du JSON pendant que le parent "
        "croit avoir impose la valeur figee — c'est le no-op mesure a l'origine de ce fichier. "
        "Ajouter `deploy_active_ratio_start=parent_deploy_active_ratio_start(training_config)`, "
        "ou `training_deploy_active_ratio_start=` sur un W40KEngine direct."
    )
