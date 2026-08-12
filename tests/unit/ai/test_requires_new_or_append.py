"""Une commande d'entraînement DOIT dire ce qu'elle fait du modèle en place.

`--new` et `--append` sont exclusifs entre eux, mais aucun des deux n'était obligatoire, et la
cascade `if new_model or not os.path.exists(model_path) / elif append_training / else` répondait
n'importe quoi aux deux invocations qu'elle ne savait pas trancher :

- ni `--new` ni `--append` sur un modèle EXISTANT : `train_with_scenario_rotation` (`--scenario
  bot`, le chemin d'entraînement réel) construisait un modèle NEUF depuis des poids aléatoires
  puis l'enregistrait par-dessus le modèle entraîné SANS l'archiver — des heures de training
  détruites derrière une seule ligne `⚠️` — pendant que `create_multi_agent_model` (scénario
  unique) rechargeait l'existant. Deux réponses opposées à la même commande ;
- `--append` alors qu'AUCUN modèle n'existe (agent mal orthographié, modèle déplacé) : le second
  terme de la condition l'envoyait dans la branche « modèle neuf ». Des heures d'entraînement
  depuis zéro sous un drapeau qui promet exactement le contraire, sortie en code 0.

`check_model_lifecycle` porte les deux refus, et il est le SEUL à les porter : `main()` l'appelle
au plus tôt (avant le StepLogger et `node scripts/copy-configs.js`), `prepare_run_artifacts` —
prologue commun des deux points d'entrée — le rejoue après l'installation du checkpoint de
`--resume-from`. La cascade en aval n'a plus que deux états atteignables, donc plus de troisième
réponse à inventer.

Verrous :
- REFUS : modèle présent + aucun des deux drapeaux → `ValueError` ;
- REFUS JUMEAU : `--append` sans modèle à continuer → `ValueError` ;
- MESSAGE : chacun nomme le modèle concerné et l'option à passer ;
- LAISSER-PASSER : `--new`, `--append` sur un modèle présent, l'absence de modèle sans drapeau,
  `--new --append` (où `--new` gagne), et `--resume-from` avant promotion du checkpoint ;
- HORS SUJET : `--test-only`, `--convert-steplog`, `--replay` ne s'entraînent pas ;
- PROLOGUE : `prepare_run_artifacts` refuse avant son premier effet de bord ;
- PLACEMENT : `main()` refuse avant le `try:` qui monte tout le reste.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

import pytest

from ai.train import (
    append_without_model,
    check_model_lifecycle,
    is_training_invocation,
    model_lifecycle_conflict,
    prepare_run_artifacts,
)

# Reutilise plutot que redeclare : ce stub expose `get_models_root` ET
# `_resolve_agent_config_key`, les deux seuls services que `build_agent_model_path` consomme.
# Sans le second, le test dependrait de l'arborescence reelle `config/agents/<agent>/` et
# casserait au premier renommage d'agent, pour une raison sans rapport avec ce qu'il verrouille.
from .test_resume_from_checkpoint import _FakeConfigLoader

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TRAIN_PY = PROJECT_ROOT / "ai" / "train.py"


def _model(tmp_path: Path, *, existant: bool) -> str:
    """Le chemin canonique d'un modèle, posé ou non.

    `check_model_lifecycle` ne prend qu'un chemin : le test n'a donc besoin d'aucun agent réel,
    d'aucun stub de config loader, et ne casse pas si un agent est renommé.
    """
    model_path = tmp_path / "TestAgent" / "model_TestAgent.zip"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    if existant:
        model_path.write_bytes(b"PK\x03\x04 modele entraine")
    return str(model_path)


def test_un_modele_existant_sans_flag_est_refuse(tmp_path) -> None:
    """LE défaut : sans refus, ce lancement écrasait le modèle par des poids aléatoires."""
    model_path = _model(tmp_path, existant=True)

    with pytest.raises(ValueError) as excinfo:
        check_model_lifecycle(model_path, False, False)

    assert model_path in str(excinfo.value), (
        "l'erreur doit nommer le modèle concerné : c'est ce qui distingue « je me suis trompé "
        "d'agent » de « j'ai oublié un drapeau »"
    )


def test_append_sans_modele_a_continuer_est_refuse(tmp_path) -> None:
    """JUMEAU du refus ci-dessus, sur l'autre branche de la même cascade.

    Ça n'échouait bruyamment que PAR ACCIDENT, quand les stats VecNormalize compagnonnes
    manquaient à l'appel : un profil `vec_normalize.enabled: false` sortait en code 0.
    """
    model_path = _model(tmp_path, existant=False)

    with pytest.raises(ValueError) as excinfo:
        check_model_lifecycle(model_path, False, True)

    assert model_path in str(excinfo.value), "le modèle absent est nommé"


def test_les_deux_messages_disent_quoi_faire() -> None:
    """Refuser sans dire quoi passer déplacerait la perte de temps au lieu de la supprimer."""
    conflit = str(model_lifecycle_conflict("/m/model_X.zip"))
    assert "--new" in conflit and "--append" in conflit
    # Chaque option porte ce qu'elle FAIT du modèle en place, pas seulement son nom.
    assert "ECART" in conflit.upper(), "--new doit annoncer l'archivage, pas un écrasement"
    assert "CONTINUE" in conflit.upper(), "--append doit annoncer la reprise"

    absent = str(append_without_model("/m/model_X.zip"))
    assert "--new" in absent, "l'option d'un PREMIER entraînement doit être rappelée"


@pytest.mark.parametrize(
    "existant, new_model, append_training, resume_pending",
    [
        (True, True, False, False),    # --new sur un modèle existant : il sera archivé
        (True, False, True, False),    # --append sur un modèle existant : la reprise nominale
        (False, False, False, False),  # premier entraînement d'un agent : rien à écraser
        (False, True, False, False),   # --new sur un dossier vide
        (False, True, True, False),    # `--new` GAGNE sur `--append` (cf. prepare_run_artifacts)
        (False, False, True, True),    # --resume-from : le checkpoint est installé plus tard
    ],
)
def test_les_invocations_realisables_passent(
    tmp_path, existant, new_model, append_training, resume_pending
) -> None:
    check_model_lifecycle(
        _model(tmp_path, existant=existant), new_model, append_training,
        resume_pending=resume_pending,
    )


@pytest.mark.parametrize(
    "mode", [{"test_only": True}, {"convert_steplog": "step.log"}, {"replay": True}]
)
def test_les_modes_sans_entrainement_ne_sont_pas_concernes(mode) -> None:
    """Ils ne lisent ni `--new` ni `--append` : les exiger interdirait d'évaluer un modèle."""
    base = dict(test_only=False, convert_steplog=None, replay=False)
    assert is_training_invocation(argparse.Namespace(**base)), (
        "sans aucun de ces modes, la commande entraîne — sinon la garde ne se déclenche jamais"
    )
    assert not is_training_invocation(argparse.Namespace(**{**base, **mode}))


def test_le_prologue_commun_des_deux_points_d_entree_refuse(tmp_path, monkeypatch) -> None:
    """`prepare_run_artifacts` rend le `model_path` dont dépend tout le reste des deux points
    d'entrée : y refuser, c'est refuser avant le premier effet de bord (création de dossier,
    archivage `--new`, ouverture d'un run TensorBoard qui réécrit le run-meta du modèle).

    Les deux refus y sont rejoués, et pas seulement délégués à `main()` : c'est le seul site
    joué APRÈS l'installation du checkpoint de `--resume-from`, donc le seul qui puisse
    constater qu'elle n'a pas produit de modèle.
    """
    models_root = tmp_path / "models"
    (models_root / "TestAgent").mkdir(parents=True)
    monkeypatch.setattr("ai.train.get_config_loader", lambda: _FakeConfigLoader(str(models_root)))
    (models_root / "TestAgent" / "model_TestAgent.zip").write_bytes(b"PK\x03\x04")

    with pytest.raises(ValueError):
        prepare_run_artifacts(str(models_root), "TestAgent", False, False, 1, log_fn=lambda _m: None)

    (models_root / "TestAgent" / "model_TestAgent.zip").unlink()
    with pytest.raises(ValueError):
        prepare_run_artifacts(str(models_root), "TestAgent", False, True, 1, log_fn=lambda _m: None)


def _main_body() -> list:
    tree = ast.parse(TRAIN_PY.read_text(encoding="utf-8"))
    main = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"), None
    )
    if main is None:
        pytest.fail("aucune fonction `main` trouvée dans ai/train.py")
    return main.body


def test_main_refuse_avant_tout_effet_de_bord() -> None:
    """PLACEMENT : le refus de `main()` précède le `try:` qui monte tout le reste.

    C'est la moitié de la valeur du deuxième site : le prologue seul refuserait aussi, mais
    APRÈS la construction du StepLogger et `node scripts/copy-configs.js` — deux minutes payées
    pour apprendre qu'un drapeau manque. Sans cette assertion, un déplacement plus bas laisserait
    la suite verte en rétablissant ce coût.
    """
    body = _main_body()
    guard = next(
        (
            i
            for i, node in enumerate(body)
            if any(
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id == "check_model_lifecycle"
                for inner in ast.walk(node)
            )
        ),
        None,
    )
    assert guard is not None, (
        "main() n'appelle plus check_model_lifecycle : l'invocation irréalisable ne serait plus "
        "refusée qu'au prologue, après le StepLogger et la sync des configs frontend"
    )
    first_try = next((i for i, node in enumerate(body) if isinstance(node, ast.Try)), None)
    assert first_try is not None, "le `try:` de main() a disparu, ce test ne repère plus rien"
    assert guard < first_try, (
        "la garde doit précéder le `try:` de main() : StepLogger, sync des configs frontend et "
        "construction d'environnement s'y trouvent"
    )
