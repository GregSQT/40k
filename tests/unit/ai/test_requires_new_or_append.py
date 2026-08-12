"""Un entraînement sur un modèle existant DOIT dire `--new` ou `--append`.

`--new` et `--append` sont exclusifs entre eux, mais aucun des deux n'était obligatoire. Quand le
modèle canonique existait et que la commande n'en portait aucun, les deux points d'entrée
répondaient **l'inverse l'un de l'autre** :

- `train_with_scenario_rotation` (`--scenario bot`, le chemin d'entraînement réel) construisait un
  modèle NEUF depuis des poids aléatoires, puis l'enregistrait par-dessus le modèle entraîné SANS
  l'archiver — des heures de training détruites derrière une seule ligne `⚠️` ;
- `create_multi_agent_model` (scénario unique) rechargeait le modèle existant.

Verrous :
- REFUS : modèle présent + aucun des deux drapeaux → `ValueError` ;
- MESSAGE : il nomme les DEUX options et ce que chacune fait du modèle en place ;
- LAISSER-PASSER : `--new`, `--append` et l'absence de modèle passent ;
- HORS SUJET : `--test-only`, `--convert-steplog`, `--replay` ne s'entraînent pas, ils passent ;
- PLACEMENT : `main()` appelle la garde AVANT son `try:`, donc avant le StepLogger, avant
  `node scripts/copy-configs.js` et avant toute construction d'environnement ;
- JUMEAU : les DEUX points d'entrée lèvent sur leur `else` terminal — aucun ne peut plus créer ni
  recharger un modèle en silence si on l'appelle directement.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

import pytest

from ai.train import (
    build_agent_model_path,
    model_lifecycle_conflict,
    require_explicit_model_lifecycle,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TRAIN_PY = PROJECT_ROOT / "ai" / "train.py"

# Un agent RÉEL : `build_agent_model_path` résout le répertoire de config de l'agent
# (`_resolve_agent_config_key`), donc une clé inventée échouerait pour la mauvaise raison.
AGENT = "ArmageddonAgent"


class _ModelsRoot:
    """Le seul service que la garde demande à `config` : la racine des modèles."""

    def __init__(self, root: Path) -> None:
        self._root = str(root)

    def get_models_root(self) -> str:
        return self._root


def _args(**overrides) -> argparse.Namespace:
    base = dict(
        agent=AGENT,
        new=False,
        append=False,
        test_only=False,
        convert_steplog=None,
        replay=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def _existing_model(tmp_path: Path) -> str:
    model_path = build_agent_model_path(str(tmp_path), AGENT)
    Path(model_path).parent.mkdir(parents=True, exist_ok=True)
    Path(model_path).write_bytes(b"PK\x03\x04 modele entraine")
    return model_path


def test_un_modele_existant_sans_flag_est_refuse(tmp_path) -> None:
    """LE défaut : sans refus, ce lancement écrasait le modèle par des poids aléatoires."""
    model_path = _existing_model(tmp_path)

    with pytest.raises(ValueError) as excinfo:
        require_explicit_model_lifecycle(_ModelsRoot(tmp_path), _args())

    assert model_path in str(excinfo.value), (
        "l'erreur doit nommer le modèle concerné : c'est ce qui distingue « je me suis trompé "
        "d'agent » de « j'ai oublié un drapeau »"
    )


def test_le_message_nomme_les_deux_options_et_leur_effet() -> None:
    """Refuser sans dire quoi faire déplacerait la perte de temps au lieu de la supprimer."""
    message = str(model_lifecycle_conflict("/m/model_X.zip"))
    assert "--new" in message and "--append" in message
    # Chaque option doit porter ce qu'elle FAIT du modèle en place, pas seulement son nom.
    assert "ECART" in message.upper(), "--new doit annoncer l'archivage, pas un écrasement"
    assert "CONTINUE" in message.upper(), "--append doit annoncer la reprise"


@pytest.mark.parametrize("flag", ["new", "append"])
def test_une_intention_declaree_passe(tmp_path, flag) -> None:
    _existing_model(tmp_path)
    require_explicit_model_lifecycle(_ModelsRoot(tmp_path), _args(**{flag: True}))


def test_sans_modele_existant_aucun_flag_n_est_exige(tmp_path) -> None:
    """Le premier entraînement d'un agent n'a rien à écraser : il ne se justifie pas."""
    require_explicit_model_lifecycle(_ModelsRoot(tmp_path), _args())


@pytest.mark.parametrize(
    "mode", [{"test_only": True}, {"convert_steplog": "step.log"}, {"replay": True}]
)
def test_les_modes_sans_entrainement_ne_sont_pas_concernes(tmp_path, mode) -> None:
    """Ils ne lisent ni `--new` ni `--append` : les exiger interdirait d'évaluer un modèle."""
    _existing_model(tmp_path)
    require_explicit_model_lifecycle(_ModelsRoot(tmp_path), _args(**mode))


def _main_body() -> list:
    tree = ast.parse(TRAIN_PY.read_text(encoding="utf-8"))
    main = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"), None
    )
    if main is None:
        pytest.fail("aucune fonction `main` trouvée dans ai/train.py")
    return main.body


def test_la_garde_est_appelee_avant_tout_effet_de_bord_de_main() -> None:
    """PLACEMENT : dans le corps de `main()`, avant le `try:` qui monte tout le reste.

    Sans cette assertion, déplacer l'appel plus bas laisserait la suite verte tout en rendant
    l'erreur au bout de la construction du StepLogger et de `node scripts/copy-configs.js` —
    exactement le coût que la garde existe pour supprimer.
    """
    body = _main_body()
    guard_index = next(
        (
            i
            for i, node in enumerate(body)
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "require_explicit_model_lifecycle"
        ),
        None,
    )
    assert guard_index is not None, (
        "main() n'appelle plus require_explicit_model_lifecycle : l'invocation ambiguë "
        "repasserait jusqu'aux points d'entrée d'entraînement"
    )
    try_index = next(
        (i for i, node in enumerate(body) if isinstance(node, ast.Try)), None
    )
    assert try_index is not None, "le `try:` de main() a disparu, ce test ne repère plus rien"
    assert guard_index < try_index, (
        "la garde doit précéder le `try:` de main() : StepLogger, sync des configs frontend et "
        "construction d'environnement s'y trouvent"
    )


@pytest.mark.parametrize(
    "func_name", ["create_multi_agent_model", "train_with_scenario_rotation"]
)
def test_aucun_point_d_entree_ne_garde_un_else_silencieux(func_name: str) -> None:
    """JUMEAU : les deux `else` terminaux divergeaient. Ils lèvent maintenant la MÊME erreur.

    La garde de `main()` les rend inatteignables depuis la ligne de commande, mais les deux
    fonctions restent importables et appelables : un `else` qui construit ou recharge un modèle
    y ré-ouvrirait la divergence sans passer par argparse.
    """
    tree = ast.parse(TRAIN_PY.read_text(encoding="utf-8"))
    # `train_with_scenario_rotation` porte des `@overload` : leur corps est un `...`, et prendre
    # la PREMIÈRE définition du nom ferait porter le test sur une signature vide.
    candidates = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == func_name and n.body
    ]
    if not candidates:
        pytest.fail(f"aucune fonction `{func_name}` trouvée dans ai/train.py")
    func = max(candidates, key=lambda n: len(n.body))

    # Le `if new_model or not os.path.exists(model_path): ... elif append_training: ... else: ...`
    branches = [
        node
        for node in ast.walk(func)
        if isinstance(node, ast.If)
        and node.orelse
        and any(
            isinstance(inner, ast.If) and "append_training" in ast.dump(inner.test)
            for inner in node.orelse
        )
    ]
    assert branches, (
        f"la cascade new/append de `{func_name}` est introuvable : ce test ne verrouille plus rien"
    )
    for branch in branches:
        terminal = branch.orelse[0].orelse  # type: ignore[attr-defined]
        assert terminal, f"`{func_name}` a perdu son `else` terminal"
        assert all(isinstance(stmt, ast.Raise) for stmt in terminal), (
            f"le `else` terminal de `{func_name}` doit lever : y créer ou y charger un modèle "
            "rétablit la divergence entre les deux points d'entrée"
        )
        raised = terminal[0]
        assert isinstance(raised.exc, ast.Call) and isinstance(raised.exc.func, ast.Name), (
            "l'erreur doit venir de la fabrique commune"
        )
        assert raised.exc.func.id == "model_lifecycle_conflict", (
            "source UNIQUE du message : deux formulations divergeraient à nouveau"
        )
