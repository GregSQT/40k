"""Tests — UN dossier d'evenements par run, et UN ecrivain par courbe entre les deux ecrivains.

CE QUI A ETE MANQUE. Un agent produisait DEUX entrees TensorBoard, parce que deux dérivations
de chemin independantes n'ont jamais ete reconciliees :

  * le logger de SB3 ecrivait dans `<run>/<config>_<agent>_1`, sous-dossier que SB3 se derive
    lui-meme a chaque `learn()` tant qu'aucun logger explicite n'est pose (`_custom_logger`) ;
  * le tracker de metriques ecrivait dans `<run>/<agent>`, un suffixe que son constructeur
    ajoutait en silence.

Mesure sur le run P0 du 2026-09-07 : 651 fichiers d'evenements dans le premier dossier (un par
`learn()`, la boucle budgetee en episodes en enchainant un par tranche d'updates) et 3 dans le
second.

CE QUE LA SCISSION CACHAIT. Vingt courbes etaient ecrites par les DEUX ecrivains — les quatre
`game_critical/*`, les cinq `seat_aware/*`, `bot_split/*` et les onze `diag/*`. Tant que les
ecrivains visaient deux dossiers, TensorBoard en faisait deux runs distincts et personne ne
voyait le doublon. Reunir les dossiers sans dedoublonner aurait donne a ces courbes deux points
par episode sur deux abscisses differentes (pas PPO d'un cote, episodes de l'autre).

POURQUOI test_metrics_single_writer.py NE L'AURAIT PAS VU : il ne surveille qu'un seul ecrivain,
celui du tracker. Le controle generique de ce fichier porte sur le COUPLE d'ecrivains.
"""

from __future__ import annotations

import inspect
import os
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from ai.metrics_tracker import W40KMetricsTracker
from ai.train import attach_run_logger, run_events_dir

_AGENT_KEY = "ArmageddonAgent_x1"


class _StubModel:
    """Modele reduit a ce que `attach_run_logger` et `run_events_dir` touchent."""

    def __init__(self) -> None:
        self.logger: Any = None
        self.custom_logger_flag = False

    def set_logger(self, logger: Any) -> None:
        self.logger = logger
        self.custom_logger_flag = True


def test_le_tracker_ecrit_exactement_dans_le_dossier_qu_on_lui_donne(tmp_path: Path) -> None:
    """Le constructeur ne transforme plus le chemin recu.

    Il y appliquait `agent_log_dir(log_dir, agent_key)`. Comme les appelants n'etaient pas
    d'accord sur ce qu'ils passaient — un dossier de run cote entrainement, la racine cote eval
    seule — aucun choix ne pouvait etre juste pour les deux, et le suffixe eloignait le tracker
    du dossier que le logger de SB3 visait. C'est ce que ce controle interdit de reintroduire :
    sans egalite stricte, l'appelant ne peut plus garantir l'unicite du dossier.
    """
    tracker = W40KMetricsTracker(
        _AGENT_KEY, log_dir=str(tmp_path), show_banner=False,
        perf_window=1, perf_window_fast=1,
    )
    try:
        assert tracker.log_dir == str(tmp_path), (
            "le tracker doit ecrire dans le dossier recu, sans suffixe implicite"
        )
    finally:
        tracker.writer.close()


def test_attach_run_logger_rend_le_dossier_du_run_lisible_sur_le_modele(tmp_path: Path) -> None:
    """Apres la pose, le dossier du run se LIT sur le modele — c'est la source unique.

    Le tracker en est construit. Deriver son dossier par une expression jumelle de celle du
    logger tiendrait tant que les deux restent en phase ; le defaut corrige ici est justement
    deux derivations qui ne l'etaient pas.
    """
    events_dir = tmp_path / "run_20260907-120000" / _AGENT_KEY
    model = _StubModel()
    attach_run_logger(model, str(events_dir))

    assert model.custom_logger_flag is True, (
        "le logger doit etre pose via set_logger, sinon SB3 le reconstruit a chaque learn()"
    )
    assert run_events_dir(model) == str(events_dir)
    assert events_dir.is_dir(), "le dossier du run doit exister apres la pose"


def test_run_events_dir_refuse_un_logger_sans_dossier() -> None:
    """Logger sans dossier = pose manquante, donc erreur explicite et non un repli silencieux.

    Le site qui construisait le tracker du mode sans rotation repliait sur `./tensorboard/`
    quand il ne trouvait rien : les metriques du run partaient alors dans un dossier qui n'etait
    pas le sien, sans que rien ne le signale.
    """
    model = SimpleNamespace(logger=SimpleNamespace(get_dir=lambda: None))
    with pytest.raises(ValueError, match="attach_run_logger"):
        run_events_dir(model)


def test_sb3_cesse_de_reconstruire_son_logger_quand_on_en_pose_un() -> None:
    """Contrat de SB3 dont depend tout le correctif — canari sur une dependance externe.

    `attach_run_logger` ne tient que si `set_logger` leve `_custom_logger` ET si `_setup_learn`
    s'en sert pour NE PAS reconstruire le logger. Si une montee de version de SB3 retire cette
    garde, le sous-dossier `<tb_log_name>_<n>` revient et l'agent reproduit deux entrees : ce
    test doit alors rougir, plutot que la scission de revenir en silence.
    """
    from stable_baselines3.common.base_class import BaseAlgorithm

    cible = SimpleNamespace()
    sentinelle = object()
    BaseAlgorithm.set_logger(cible, sentinelle)  # type: ignore[arg-type]
    assert cible._logger is sentinelle
    assert cible._custom_logger is True

    source = inspect.getsource(BaseAlgorithm._setup_learn)
    assert "_custom_logger" in source, (
        "SB3 ne garde plus la reconstruction du logger derriere _custom_logger : "
        "attach_run_logger ne suffit plus a fixer le dossier du run"
    )


# --- Controle generique : un seul ecrivain par courbe, sur le COUPLE d'ecrivains -------------

_TRACKER_CALL = r"\.writer\.add_scalar"
_SB3_CALL = r"\.logger\.record"
#: Emetteurs a DEUX fenetres du tracker : chacun publie `X` et `X_<perf_window_fast>ep`. Ce
#: second tag n'apparait dans aucun litteral — il est construit par f-string sur une variable
#: (`f"{tag}_{fast_window}ep"`) — donc un releve qui ne lit que les litteraux ne peut pas le
#: voir. C'est exactement par la qu'un doublon a survecu au controle : le callback ecrivait
#: `game_critical/win_rate_100ep` en dur pendant que le tracker derive le meme nom de
#: `game_critical/win_rate` des que la fenetre reactive vaut 100.
_TRACKER_WINDOWED_CALLS = r"self\._emit_(?:windowed|game|ratio_of_means)"


def _normalise(tag: str) -> str:
    """Ramene un tag construit par f-string a son gabarit : `bot_split/{key}` -> `bot_split/*`.

    Sans cette normalisation, `bot_split/{key}` et `bot_split/{metric_key}` passeraient pour
    deux courbes differentes alors qu'ils produisent les MEMES tags a l'execution — c'etait le
    cas, les deux ecrivains parcourant le meme `scenario_split_scores`.
    """
    tag = re.sub(r"\{[^}]*\}", "*", tag)
    # Suffixe de fenetre reactive ramene a son gabarit : `_100ep` et `_250ep` designent la MEME
    # courbe a deux reglages de `metrics_smoothing.perf_window_fast`. Comparer les chiffres
    # ferait dependre le verdict du config du jour, alors que le doublon, lui, est structurel.
    return re.sub(r"_\d+ep$", "_*ep", tag)


def _tags_par_ecrivain(pattern: str) -> Dict[str, List[str]]:
    """Tags litteraux passes en premier argument, avec leur site — sur tout `ai/`.

    Lecture du SOURCE et non execution : le doublon se juge sur l'existence des deux sites
    d'ecriture, qu'aucun test unitaire ne fait cohabiter (l'un vit dans un callback branche sur
    le logger du modele, l'autre dans le tracker).
    """
    racine = Path(__file__).resolve().parents[3] / "ai"
    trouves: Dict[str, List[str]] = {}
    for fichier in sorted(racine.glob("*.py")):
        source = fichier.read_text(encoding="utf-8")
        for m in re.finditer(pattern + r"\(\s*f?['\"]([^'\"]+)['\"]", source, re.S):
            ligne = source[:m.start()].count("\n") + 1
            trouves.setdefault(_normalise(m.group(1)), []).append(f"{fichier.name}:{ligne}")
    return trouves


def _tags_derives_du_tracker() -> Dict[str, List[str]]:
    """Tags que le tracker publie EN PLUS de leur nom nu : le doublon `X_<N>ep`.

    Releve les appels aux emetteurs a deux fenetres et ajoute leur tag suffixe. Sans lui, le
    controle du couple d'ecrivains ne voit qu'une moitie de ce que le tracker ecrit.
    """
    return {
        f"{tag}_*ep": sites
        for tag, sites in _tags_par_ecrivain(_TRACKER_WINDOWED_CALLS).items()
    }


def test_aucune_courbe_n_est_ecrite_par_les_deux_ecrivains() -> None:
    """Aucun tag n'est ecrit a la fois par le tracker et par le logger de SB3.

    Les deux ecrivains partagent desormais le dossier du run : un tag present des deux cotes y
    recevrait deux points par episode, sur deux abscisses differentes. Le controle est generique
    et attrapera le prochain doublon, pas seulement les vingt qui existaient.

    Les tags DERIVES comptent comme des ecritures du tracker : `_emit_windowed` publie `X` et
    `X_<perf_window_fast>ep`, ce second nom n'existant nulle part en litteral. La version
    precedente n'en tenait pas compte et laissait passer `game_critical/win_rate_100ep`, ecrit
    en dur par le callback a cote du meme nom derive de `game_critical/win_rate`.
    """
    tracker = _tags_par_ecrivain(_TRACKER_CALL)
    derives = _tags_derives_du_tracker()
    assert derives, "aucun emetteur a deux fenetres trouve : le motif de lecture est casse"
    for _tag, _sites in derives.items():
        tracker.setdefault(_tag, []).extend(_sites)
    sb3 = _tags_par_ecrivain(_SB3_CALL)
    assert tracker, "aucune ecriture tracker trouvee : le motif de lecture est casse"
    assert sb3, "aucune ecriture logger trouvee : le motif de lecture est casse"

    doublons = {
        tag: {"tracker": tracker[tag], "sb3": sb3[tag]}
        for tag in sorted(set(tracker) & set(sb3))
    }
    assert doublons == {}, f"courbes ecrites par les deux ecrivains : {doublons}"


def test_le_dossier_du_tracker_vient_toujours_du_logger_du_modele() -> None:
    """Chaque tracker construit dans `ai/train.py` recoit le dossier LU sur le logger.

    C'est le cablage qui avait diverge, et non les fonctions prises separement : les deux sites
    derivaient le dossier chacun de leur cote — `specific_log_dir` pour l'un, `model.tensorboard_log`
    pour l'autre, ce dernier valant le dossier de run en creation et la racine en reprise. Tant
    qu'une derivation independante reste possible, l'unicite de l'entree TensorBoard n'est
    garantie que par l'accord de deux expressions, c'est-a-dire pas garantie.
    """
    source = (Path(__file__).resolve().parents[3] / "ai" / "train.py").read_text(encoding="utf-8")

    affectations = re.findall(r"^\s*model_tensorboard_dir\s*=\s*(.+)$", source, re.M)
    assert affectations, "plus aucun dossier de tracker dans ai/train.py : motif de lecture casse"
    for expression in affectations:
        assert expression.startswith("run_events_dir("), (
            f"le dossier du tracker doit etre lu sur le logger, pas redérive : {expression!r}"
        )

    constructions = re.findall(
        r"W40KMetricsTracker\(\s*[^,]+,\s*([A-Za-z_][A-Za-z_0-9]*)", source
    )
    assert constructions, "aucune construction de tracker trouvee dans ai/train.py"
    assert set(constructions) == {"model_tensorboard_dir"}, (
        f"un tracker recoit un dossier d'une autre provenance : {sorted(set(constructions))}"
    )
