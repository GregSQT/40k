"""Verrou — le REGIME DE LIGNEE gouverne toute etape reprise a chaud, et il n'a plus de rampe.

REMPLACE `tests/unit/ai/test_entropy_ramp_warm_start.py`, supprime le 2026-09-07 avec le
mecanisme qu'il verrouillait (`_pin_entropy_ramp_for_warm_start`).

CE QUI A CHANGE, ET POURQUOI. Chaque etape declarait sa propre rampe d'entropie et de learning
rate. Une rampe s'exprime en FRACTION de la duree du run, donc chaque etape reprise reparcourait
la sienne depuis le debut : un modele portant des centaines de milliers d'episodes se voyait
rendre le regime d'exploration d'un demarrage. Mesure du 2026-09-04 : P1 s'etait arretee a un
`ent_coef` de ~0,018, P2 est repartie a 0,100, l'evaluation bots est tombee de 0,911 a 0,694 et
le score contre P1 — garanti a 0,50 par construction puisque P2 EST P1 a l'episode 0 — est tombe
a 0,118.

Le correctif d'alors faisait partir la rampe de la valeur ATTEINTE par le modele. Il a ete mesure
a son tour le 2026-09-05 : parti de 0,0177, le score de la sonde est reste PLAT a 0,496 sur six
mesures et 60 000 episodes (chi2 de 2,16 pour 5 degres de liberte, indistinguable d'une
constante) pendant que l'evaluation bots retombait sous celle du modele de depart. Les deux
regimes echouaient pour la meme raison de fond : la valeur d'entropie etait une consequence de
l'HISTOIRE du modele, jamais une decision.

Le bloc `lineage_regime` pose des SCALAIRES, les memes a toutes les etapes reprises. Il n'y a
donc plus de rampe a poser, plus de depart a choisir, et ce qui reste a verrouiller est : (1) le
regime atteint bien TOUTE lecture de config, (2) il ne touche ni le fichier multi-profils ni un
autre agent, (3) un demarrage a froid garde les rampes du profil, (4) le controle de continuite
ANNONCE l'ecart avec le modele repris sans jamais le corriger.
"""

from __future__ import annotations

import json
import zipfile
from typing import Any, Dict, List

import pytest

#: Le bloc de lignee livre, recopie ici depuis la specification et non relu du JSON.
LINEAGE = {
    "model_params": {
        "learning_rate": 0.001,
        "ent_coef": 0.03,
        "n_steps": 32640,
        "batch_size": 4080,
        "vf_coef": 0.15,
        "max_grad_norm": 0.5,
    },
    "agent_seat_p2_ratio": 0.6,
}


def _model_zip(
    tmp_path, ent_coef: Any = 0.0177, learning_rate: Any = 0.0005, *, omises: tuple = ()
) -> str:
    """Un zip SB3 reduit a ce que la lecture regarde : son membre `data`."""
    path = str(tmp_path / "model.zip")
    data: Dict[str, Any] = {"n_steps": 340, "n_epochs": 2}
    if "ent_coef" not in omises:
        data["ent_coef"] = ent_coef
    if "learning_rate" not in omises:
        data["learning_rate"] = learning_rate
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("data", json.dumps(data))
    return path


def _cfg() -> Dict[str, Any]:
    """Profil AVANT regime : les rampes du profil x1_long, et son `agent_seat_p2_ratio`."""
    return {
        "total_episodes": 100000,
        "agent_seat_p2_ratio": 0.75,
        "model_params": {
            "ent_coef": {"start": 0.1, "end": 0.01, "decay_fraction": 0.4},
            "learning_rate": {"initial": 0.002, "final": 0.0005, "decay_fraction": 0.9},
            "n_steps": 8160,
            "batch_size": 1020,
            "n_epochs": 4,
            "vf_coef": 0.5,
            "max_grad_norm": 0.5,
        },
    }


class _Loader:
    """Loader double, FIDELE a la forme du vrai.

    `config_loader.load_agent_training_config` rend le FICHIER multi-profils entier quand `phase`
    vaut None — `_require_training_config_phase` s'en sert justement pour lister les profils
    disponibles — et le profil seul sinon. Les deux formes traversent le decorateur : un double
    qui rendrait le profil dans les deux cas laisserait passer une pose de regime sur le fichier
    entier, qui ecrirait des cles a cote des profils.
    """

    def __init__(self, cfg: Dict[str, Any], phase: str = "x1_long") -> None:
        self._cfg = cfg
        self._phase = phase
        self.lectures = 0

    def load_agent_training_config(self, agent_key: str, phase: Any = None) -> Dict[str, Any]:
        self.lectures += 1
        profil = json.loads(json.dumps(self._cfg))
        return profil if phase is not None else {self._phase: profil}


# ── LECTURE DES SCALAIRES DU MODELE ────────────────────────────────────────────────────────


#: Les deux fonctions que le chemin de production execute reellement. Elles ont REMPLACE
#: `read_model_ent_coef` / `read_model_learning_rate` / `_read_model_scalar`, supprimees le
#: 2026-09-07 : `announce_lineage_continuity` appelait le troisieme directement, les deux premiers
#: n'avaient plus aucun appelant hors de ce fichier, et les tests portaient donc sur une surface
#: qu'aucun run n'empruntait.


def test_the_entropy_is_read_from_the_model_on_disk(tmp_path) -> None:
    """La valeur vient du zip, pas de la config."""
    from ai.train import _model_scalar, _read_model_data

    path = _model_zip(tmp_path, ent_coef=0.0177)
    assert _model_scalar(_read_model_data(path), "ent_coef", path) == pytest.approx(0.0177)


def test_the_learning_rate_is_read_from_the_model_on_disk(tmp_path) -> None:
    """Jumeau du precedent : le controle de continuite lit les deux."""
    from ai.train import _model_scalar, _read_model_data

    path = _model_zip(tmp_path, learning_rate=0.0005)
    assert _model_scalar(_read_model_data(path), "learning_rate", path) == pytest.approx(0.0005)


@pytest.mark.parametrize("cle", ["ent_coef", "learning_rate"])
def test_a_model_without_the_key_is_refused(tmp_path, cle: str) -> None:
    """Absente, la valeur ne se devine pas : le controle comparerait un chiffre invente."""
    from ai.train import _model_scalar, _read_model_data

    path = _model_zip(tmp_path, omises=(cle,))
    with pytest.raises(KeyError, match=f"sans `{cle}`"):
        _model_scalar(_read_model_data(path), cle, path)


def test_a_non_numeric_scalar_is_refused(tmp_path) -> None:
    from ai.train import _model_scalar, _read_model_data

    path = _model_zip(tmp_path, ent_coef="0.02")
    with pytest.raises(TypeError, match="n'est pas un nombre"):
        _model_scalar(_read_model_data(path), "ent_coef", path)


def test_a_nan_scalar_is_refused(tmp_path) -> None:
    """NaN est un flottant en regle, et toute comparaison avec lui est fausse : il traverserait
    le controle d'ecart en silence."""
    from ai.train import _model_scalar, _read_model_data

    path = str(tmp_path / "model.zip")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("data", '{"ent_coef": NaN, "learning_rate": 0.001}')
    with pytest.raises(ValueError, match="ni fini"):
        _model_scalar(_read_model_data(path), "ent_coef", path)


def test_the_continuity_check_opens_the_archive_once(tmp_path) -> None:
    """UNE ouverture de zip pour les DEUX cles, comme l'annonce le commentaire de l'appelant.

    La boucle appelait une fonction « chemin -> valeur » par cle : l'archive etait rouverte, son
    index reparcouru et son membre `data` redecompresse et reparse a chaque tour, deux fois par
    ouverture d'etape, la ou une seule lecture suffit.
    """
    import ai.train as train_mod

    path = _model_zip(tmp_path, ent_coef=0.0177, learning_rate=0.0005)
    ouvertures: List[str] = []
    vrai_lecteur = train_mod._read_model_data

    def _compte(p: str):
        ouvertures.append(p)
        return vrai_lecteur(p)

    train_mod._read_model_data = _compte  # type: ignore[assignment]
    try:
        train_mod.announce_lineage_continuity(
            path, LINEAGE["model_params"], "P2", log=lambda *_a: None
        )
    finally:
        train_mod._read_model_data = vrai_lecteur  # type: ignore[assignment]

    assert ouvertures == [path], f"une seule lecture du zip attendue, obtenu {len(ouvertures)}"


# ── CONTROLE DE CONTINUITE : IL ANNONCE, IL NE CORRIGE PAS ─────────────────────────────────


def test_continuity_reports_every_deviation_from_the_regime(tmp_path) -> None:
    """Un modele arrete a 0,0177 d'entropie repris sous un regime a 0,03 : l'ecart est ANNONCE.

    C'est le cas de la premiere etape jouee sous ce regime : P1 s'est arretee au bout de sa
    rampe. L'ecart n'est pas une erreur — c'est le changement de regime lui-meme, et le journal
    doit le porter pour qu'une courbe qui bouge a l'ouverture soit attribuable sans rouvrir un
    zip.
    """
    from ai.train import announce_lineage_continuity

    lignes: List[str] = []
    ecarts = announce_lineage_continuity(
        _model_zip(tmp_path, ent_coef=0.0177, learning_rate=0.0005),
        LINEAGE["model_params"], "P2", log=lignes.append,
    )

    assert set(ecarts) == {"ent_coef", "learning_rate"}
    assert ecarts["ent_coef"] == (pytest.approx(0.0177), pytest.approx(0.03))
    assert ecarts["learning_rate"] == (pytest.approx(0.0005), pytest.approx(0.001))
    texte = "\n".join(lignes)
    assert "CHANGE" in texte and "0.0177" in texte and "0.03" in texte


def test_continuity_says_so_when_the_model_already_matches(tmp_path) -> None:
    """Etape suivante : le modele porte deja le regime, il n'y a rien a signaler."""
    from ai.train import announce_lineage_continuity

    lignes: List[str] = []
    ecarts = announce_lineage_continuity(
        _model_zip(tmp_path, ent_coef=0.03, learning_rate=0.001),
        LINEAGE["model_params"], "P3", log=lignes.append,
    )

    assert ecarts == {}
    assert "identique au regime de lignee" in "\n".join(lignes)


def test_continuity_never_changes_the_regime(tmp_path) -> None:
    """Il ANNONCE. Le regime pose reste celui du curriculum, jamais celui du modele repris.

    C'est la difference de fond avec `_pin_entropy_ramp_for_warm_start`, qu'il remplace : ce
    dernier faisait decider le modele, ce qui a fige la lignee a l'entropie ou la premiere etape
    s'etait arretee (mesure du 2026-09-05, sonde plate a 0,496 sur 60 000 episodes).
    """
    from ai.train import announce_lineage_continuity

    regime = json.loads(json.dumps(LINEAGE["model_params"]))
    announce_lineage_continuity(
        _model_zip(tmp_path, ent_coef=0.0177, learning_rate=0.0005), regime, "P2",
        log=lambda *_a, **_k: None,
    )
    assert regime == LINEAGE["model_params"]


# ── POSE DU REGIME SUR LA CONFIG ───────────────────────────────────────────────────────────


def test_a_warm_started_stage_gets_the_regime_on_every_read(tmp_path) -> None:
    """Le decorateur pose le regime a CHAQUE lecture de config.

    La config est relue a plusieurs endroits — prologue, construction des adversaires, callbacks
    — et n'en servir qu'une laisserait les autres sur les rampes du profil, en silence.
    """
    from ai.train import _install_stage_config_overrides

    loader = _Loader(_cfg())
    _install_stage_config_overrides(
        loader, "ArmageddonAgent_x1", None, {}, True, stage_label="P2",
        warm_start_model_path=_model_zip(tmp_path), lineage_regime=LINEAGE,
    )

    for _ in range(3):
        cfg = loader.load_agent_training_config("ArmageddonAgent_x1", "x1_long")
        assert cfg["model_params"]["ent_coef"] == pytest.approx(0.03)
        assert cfg["model_params"]["learning_rate"] == pytest.approx(0.001)
        assert cfg["model_params"]["n_steps"] == 32640
        assert cfg["model_params"]["batch_size"] == 4080
        assert cfg["model_params"]["vf_coef"] == pytest.approx(0.15)
        assert cfg["model_params"]["max_grad_norm"] == pytest.approx(0.5)
        assert cfg["agent_seat_p2_ratio"] == pytest.approx(0.6)


def test_the_posed_values_are_scalars_not_ramps(tmp_path) -> None:
    """Un scalaire ne cree AUCUN callback de rampe : la valeur tient tout le run.

    `setup_callbacks` ne construit `EntropyScheduleCallback` / `LearningRateScheduleCallback` que
    sur un dict `{start, end, decay_fraction}` / `{initial, final, decay_fraction}`. Laisser un
    dict passer ici, c'est reintroduire la rampe que ce bloc supprime.
    """
    from ai.train import _install_stage_config_overrides

    loader = _Loader(_cfg())
    _install_stage_config_overrides(
        loader, "ArmageddonAgent_x1", None, {}, True, stage_label="P2",
        warm_start_model_path=_model_zip(tmp_path), lineage_regime=LINEAGE,
    )

    cfg = loader.load_agent_training_config("ArmageddonAgent_x1", "x1_long")
    for cle in ("ent_coef", "learning_rate"):
        valeur = cfg["model_params"][cle]
        assert isinstance(valeur, float), f"{cle} vaut {valeur!r} : une rampe, pas un scalaire"


def test_the_regime_leaves_the_untouched_params_of_the_profile(tmp_path) -> None:
    """`n_epochs` n'est pas dans le bloc : il reste celui du profil."""
    from ai.train import _install_stage_config_overrides

    loader = _Loader(_cfg())
    _install_stage_config_overrides(
        loader, "ArmageddonAgent_x1", None, {}, True, stage_label="P2",
        warm_start_model_path=_model_zip(tmp_path), lineage_regime=LINEAGE,
    )

    cfg = loader.load_agent_training_config("ArmageddonAgent_x1", "x1_long")
    assert cfg["model_params"]["n_epochs"] == 4


def test_the_regime_comes_after_the_stage_overrides(tmp_path) -> None:
    """L'ORDRE : `_apply_stage_hp_overrides` d'abord, le regime ensuite.

    Le curriculum interdit deja `model_params` a une etape reprise
    (`_validate_stage_hp_overrides`), donc il n'y a normalement rien a ecraser. Cet ordre est ce
    qui garantit qu'un futur assouplissement de ce refus ne ferait pas silencieusement gagner
    l'etape contre la lignee — c'est-a-dire ne rouvrirait pas les surcharges par etape que le
    bloc existe pour fermer.
    """
    from ai.train import _install_stage_config_overrides

    loader = _Loader(_cfg())
    _install_stage_config_overrides(
        loader, "ArmageddonAgent_x1", None,
        {"total_episodes": 250000, "model_params": {"vf_coef": 0.7, "n_epochs": 6}},
        True, stage_label="P2",
        warm_start_model_path=_model_zip(tmp_path), lineage_regime=LINEAGE,
    )

    cfg = loader.load_agent_training_config("ArmageddonAgent_x1", "x1_long")
    assert cfg["model_params"]["vf_coef"] == pytest.approx(0.15), "l'etape a gagne contre la lignee"
    assert cfg["model_params"]["n_epochs"] == 6, "une cle hors regime a ete defaite"
    assert cfg["total_episodes"] == 250000


def test_a_cold_started_stage_keeps_the_profile_ramps(tmp_path) -> None:
    """`init: "new"` n'est pas gouverne par la lignee : ses rampes sont legitimes.

    Une politique naive doit explorer avant de converger, et son critic part de zero — d'ou le
    `vf_coef` 0.5 du profil, que le regime abaisse ensuite a 0.15.
    """
    from ai.train import _install_stage_config_overrides

    loader = _Loader(_cfg())
    _install_stage_config_overrides(
        loader, "ArmageddonAgent_x1", None, {}, False, stage_label="P0",
        warm_start_model_path=None, lineage_regime=None,
    )

    cfg = loader.load_agent_training_config("ArmageddonAgent_x1", "x1_long")
    assert cfg["model_params"]["ent_coef"] == {"start": 0.1, "end": 0.01, "decay_fraction": 0.4}
    assert cfg["model_params"]["vf_coef"] == pytest.approx(0.5)
    assert cfg["agent_seat_p2_ratio"] == pytest.approx(0.75)


def test_the_whole_config_file_is_left_untouched(tmp_path) -> None:
    """Une lecture SANS phase rend le fichier multi-profils : il ne doit rien recevoir.

    `_require_training_config_phase` demande justement cette forme pour lister les profils
    disponibles, et elle traverse le decorateur comme les autres. Y poser un regime ecrirait des
    cles a cote des profils, que personne ne lit.
    """
    from ai.train import _install_stage_config_overrides

    loader = _Loader(_cfg(), phase="x1_long")
    _install_stage_config_overrides(
        loader, "ArmageddonAgent_x1", None, {}, True, stage_label="P2",
        warm_start_model_path=_model_zip(tmp_path), lineage_regime=LINEAGE,
    )

    fichier = loader.load_agent_training_config("ArmageddonAgent_x1")

    assert set(fichier) == {"x1_long"}, "le fichier a recu des cles de profil"
    assert fichier["x1_long"]["model_params"]["ent_coef"] == {
        "start": 0.1, "end": 0.01, "decay_fraction": 0.4
    }, "le regime a ete pose sur le fichier entier au lieu d'un profil"


def test_another_agent_is_not_decorated(tmp_path) -> None:
    """Le decorateur ne vaut que pour l'agent de l'etape."""
    from ai.train import _install_stage_config_overrides

    loader = _Loader(_cfg())
    _install_stage_config_overrides(
        loader, "ArmageddonAgent_x1", None, {}, True, stage_label="P2",
        warm_start_model_path=_model_zip(tmp_path), lineage_regime=LINEAGE,
    )

    cfg = loader.load_agent_training_config("UnAutreAgent", "x1_long")
    assert cfg["model_params"]["ent_coef"] == {"start": 0.1, "end": 0.01, "decay_fraction": 0.4}
    assert cfg["agent_seat_p2_ratio"] == pytest.approx(0.75)


def test_the_model_is_read_once_not_at_every_config_read(tmp_path) -> None:
    """Le zip est ouvert une seule fois : la config, elle, est relue des dizaines de fois."""
    import ai.train as train_module
    from ai.train import _install_stage_config_overrides

    lectures: List[str] = []
    vraie = train_module.announce_lineage_continuity

    def _compte(path, regime, label, log=print):
        lectures.append(path)
        return vraie(path, regime, label, log=lambda *_a, **_k: None)

    train_module.announce_lineage_continuity = _compte  # type: ignore[assignment]
    try:
        loader = _Loader(_cfg())
        _install_stage_config_overrides(
            loader, "ArmageddonAgent_x1", None, {}, True, stage_label="P2",
            warm_start_model_path=_model_zip(tmp_path), lineage_regime=LINEAGE,
        )
        for _ in range(5):
            loader.load_agent_training_config("ArmageddonAgent_x1", "x1_long")
    finally:
        train_module.announce_lineage_continuity = vraie  # type: ignore[assignment]

    assert len(lectures) == 1, f"{len(lectures)} ouvertures du zip pour 5 lectures de config"
