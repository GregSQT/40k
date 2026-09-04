"""Verrou — une etape reprise a chaud demarre sa rampe d'entropie ou le modele repris s'est arrete.

Chaque etape du curriculum declare son `ent_coef.start`, et jusqu'ici cette valeur s'appliquait
telle quelle a une etape qui REPREND les poids d'une autre. Le modele herite alors d'une rampe
deja parcourue, et la redeclarer depuis le debut efface ce que le run precedent a converge.

MESURE qui l'impose, etape P2 du 2026-09-04 : P1 s'est arretee a un `ent_coef` d'environ 0,018 et
P2 est repartie a 0,100, soit un facteur cinq. L'evaluation bots est tombee de 0,911 a 0,778
pendant les seuls 10 000 episodes de warmup — joues SANS pool, donc contre exactement les memes
bots que P1 — puis a 0,694 ; `03_selfplay/P1` a demarre a 0,118, la ou l'agent devait etre a 0,50
puisqu'il part de ses propres poids. La politique promue avait ete detruite avant meme de
rencontrer son adversaire.

Le mecanisme est le jumeau exact de `_pin_deployment_ramp_for_warm_start`, qui resout le meme
defaut pour la rampe de deploiement, et pour la meme raison : c'est un COMPORTEMENT porte par le
code, pas une cle a declarer dans chaque etape — les etapes exploiteur n'ont d'ailleurs droit a
aucun `training_config_overrides`.
"""

from __future__ import annotations

import json
import zipfile
from typing import Any, Dict

import pytest


def _model_zip(tmp_path, ent_coef: Any = 0.0177, *, sans_cle: bool = False) -> str:
    """Un zip SB3 reduit a ce que la lecture regarde : son membre `data`."""
    path = str(tmp_path / "model.zip")
    data: Dict[str, Any] = {"n_steps": 340, "n_epochs": 2}
    if not sans_cle:
        data["ent_coef"] = ent_coef
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("data", json.dumps(data))
    return path


def _cfg(start: float = 0.1, end: float = 0.01) -> Dict[str, Any]:
    return {
        "total_episodes": 250000,
        "model_params": {
            "ent_coef": {"start": start, "end": end, "decay_fraction": 0.65},
            "learning_rate": {"initial": 0.001, "final": 0.0005, "decay_fraction": 0.9},
        },
    }


# ── LECTURE DE L'ENTROPIE DU MODELE ────────────────────────────────────────────────────────


def test_the_entropy_is_read_from_the_model_on_disk(tmp_path) -> None:
    """La valeur vient du zip, pas de la config."""
    from ai.train import read_model_ent_coef

    assert read_model_ent_coef(_model_zip(tmp_path, 0.0177)) == pytest.approx(0.0177)


def test_a_model_without_ent_coef_is_refused(tmp_path) -> None:
    """Absente, la valeur ne se devine pas : la rampe partirait d'un chiffre invente."""
    from ai.train import read_model_ent_coef

    with pytest.raises(KeyError, match="sans `ent_coef`"):
        read_model_ent_coef(_model_zip(tmp_path, sans_cle=True))


def test_a_non_numeric_ent_coef_is_refused(tmp_path) -> None:
    """Un `ent_coef` non numerique n'est pas un point de depart de rampe."""
    from ai.train import read_model_ent_coef

    with pytest.raises(TypeError, match="n'est pas un nombre"):
        read_model_ent_coef(_model_zip(tmp_path, "0.02"))


# ── POSE DE LA RAMPE ───────────────────────────────────────────────────────────────────────


def test_the_ramp_starts_where_the_resumed_model_stopped() -> None:
    """Le `start` declare par l'etape est remplace par le niveau atteint.

    C'est le defaut mesure sur P2 : 0,1 declare contre 0,018 atteint.
    """
    from ai.train import _pin_entropy_ramp_for_warm_start

    cfg = _cfg(start=0.1)
    _pin_entropy_ramp_for_warm_start(cfg, 0.0177)

    assert cfg["model_params"]["ent_coef"]["start"] == pytest.approx(0.0177)


def test_the_end_and_the_decay_are_left_alone() -> None:
    """Seul le depart est repris du modele : le plancher et la duree restent ceux de l'etape."""
    from ai.train import _pin_entropy_ramp_for_warm_start

    cfg = _cfg(start=0.1, end=0.01)
    _pin_entropy_ramp_for_warm_start(cfg, 0.0177)

    ent = cfg["model_params"]["ent_coef"]
    assert ent["end"] == pytest.approx(0.01)
    assert ent["decay_fraction"] == pytest.approx(0.65)


def test_the_learning_rate_ramp_is_not_touched() -> None:
    """La rampe voisine ne doit pas bouger : le defaut ne concerne que l'entropie."""
    from ai.train import _pin_entropy_ramp_for_warm_start

    cfg = _cfg()
    _pin_entropy_ramp_for_warm_start(cfg, 0.0177)

    assert cfg["model_params"]["learning_rate"]["initial"] == pytest.approx(0.001)


def test_a_model_below_the_floor_is_refused() -> None:
    """Sous le plancher de l'etape, aucune pose n'est honnete : erreur explicite.

    Partir du plancher REMONTERAIT l'entropie du modele ; partir de sa valeur ferait MONTER la
    rampe au lieu de la faire descendre. Les deux trahissent l'intention, donc on leve.
    """
    from ai.train import _pin_entropy_ramp_for_warm_start

    with pytest.raises(ValueError, match="SOUS le plancher"):
        _pin_entropy_ramp_for_warm_start(_cfg(end=0.01), 0.005)


def test_a_profile_without_an_entropy_ramp_is_left_alone() -> None:
    """Rien a figer quand l'etape ne declare pas de rampe : pas de cle inventee."""
    from ai.train import _pin_entropy_ramp_for_warm_start

    cfg: Dict[str, Any] = {"model_params": {"ent_coef": 0.01}}
    _pin_entropy_ramp_for_warm_start(cfg, 0.0177)

    assert cfg["model_params"]["ent_coef"] == 0.01


# ── CABLAGE DANS LE DECORATEUR DE CONFIG ───────────────────────────────────────────────────


class _Loader:
    """Loader double : rend une copie fraiche de la config a chaque lecture, comme le vrai."""

    def __init__(self, cfg: Dict[str, Any]) -> None:
        self._cfg = cfg
        self.lectures = 0

    def load_agent_training_config(
        self, agent_key: str, phase: Any = None
    ) -> Dict[str, Any]:
        self.lectures += 1
        return json.loads(json.dumps(self._cfg))


def test_a_warm_started_stage_gets_the_pinned_ramp_on_every_read(tmp_path) -> None:
    """Le decorateur pose la rampe a CHAQUE lecture de config.

    La config est relue a plusieurs endroits — prologue, construction des adversaires, callbacks
    — et n'en servir qu'une laisserait les autres sur la valeur declaree, en silence.
    """
    from ai.train import _install_stage_config_overrides

    loader = _Loader(_cfg(start=0.1))
    _install_stage_config_overrides(
        loader, "ArmageddonAgent_x1", None, {}, True, stage_label="P2",
        warm_start_model_path=_model_zip(tmp_path, 0.0177),
    )

    for _ in range(3):
        cfg = loader.load_agent_training_config("ArmageddonAgent_x1")
        assert cfg["model_params"]["ent_coef"]["start"] == pytest.approx(0.0177)


def test_a_cold_started_stage_keeps_its_declared_start(tmp_path) -> None:
    """`init: "new"` n'a aucun modele d'ou partir : le `start` du JSON reste la verite."""
    from ai.train import _install_stage_config_overrides

    loader = _Loader(_cfg(start=0.1))
    _install_stage_config_overrides(
        loader, "ArmageddonAgent_x1", None, {}, False, stage_label="P00",
        warm_start_model_path=None,
    )

    cfg = loader.load_agent_training_config("ArmageddonAgent_x1")
    assert cfg["model_params"]["ent_coef"]["start"] == pytest.approx(0.1)


def test_the_stage_override_is_applied_before_being_pinned(tmp_path) -> None:
    """C'est le `start` de l'ETAPE qui est remplace, pas seulement celui du profil.

    `_apply_stage_hp_overrides` pose d'abord la valeur declaree par l'etape ; la pose doit venir
    apres, sans quoi l'override la reecrirait et le defaut resterait entier.
    """
    from ai.train import _install_stage_config_overrides

    loader = _Loader(_cfg(start=0.05))
    _install_stage_config_overrides(
        loader, "ArmageddonAgent_x1", None,
        {"model_params": {"ent_coef": {"start": 0.1, "end": 0.01, "decay_fraction": 0.65}}},
        True, stage_label="P2",
        warm_start_model_path=_model_zip(tmp_path, 0.0177),
    )

    cfg = loader.load_agent_training_config("ArmageddonAgent_x1")
    assert cfg["model_params"]["ent_coef"]["start"] == pytest.approx(0.0177)


def test_another_agent_is_not_decorated(tmp_path) -> None:
    """Le decorateur ne vaut que pour l'agent de l'etape."""
    from ai.train import _install_stage_config_overrides

    loader = _Loader(_cfg(start=0.1))
    _install_stage_config_overrides(
        loader, "ArmageddonAgent_x1", None, {}, True, stage_label="P2",
        warm_start_model_path=_model_zip(tmp_path, 0.0177),
    )

    cfg = loader.load_agent_training_config("UnAutreAgent")
    assert cfg["model_params"]["ent_coef"]["start"] == pytest.approx(0.1)


def test_the_model_is_read_once_not_at_every_config_read(tmp_path) -> None:
    """Le zip est ouvert une seule fois : la config, elle, est relue des dizaines de fois."""
    import ai.train as train_module
    from ai.train import _install_stage_config_overrides

    lectures: list = []
    vraie_lecture = train_module.read_model_ent_coef

    def _compte(path: str) -> float:
        lectures.append(path)
        return vraie_lecture(path)

    train_module.read_model_ent_coef = _compte  # type: ignore[assignment]
    try:
        loader = _Loader(_cfg(start=0.1))
        _install_stage_config_overrides(
            loader, "ArmageddonAgent_x1", None, {}, True, stage_label="P2",
            warm_start_model_path=_model_zip(tmp_path, 0.0177),
        )
        for _ in range(5):
            loader.load_agent_training_config("ArmageddonAgent_x1")
    finally:
        train_module.read_model_ent_coef = vraie_lecture  # type: ignore[assignment]

    assert len(lectures) == 1, f"{len(lectures)} ouvertures du zip pour 5 lectures de config"
