"""
Vérifie que les lignes de commande `ai/train.py` documentées dans CLAUDE.md
parsent correctement et passent les gardes de compatibilité, sans lancer
d'entraînement.

Point de régression : `--scenario bot` était documenté sur la ligne « Valider »
alors que train.py lève ValueError dans ce cas (ligne ~4747). Ce test devient
ROUGE si on remet `--scenario bot` sur cette ligne.
"""
from __future__ import annotations

import functools
import io
import os
import shlex
import sys
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

RACINE = Path(__file__).resolve().parents[3]
CLAUDE_MD = RACINE / "CLAUDE.md"

# Ajout au path une seule fois au chargement du module
sys.path.insert(0, str(RACINE / "ai"))
sys.path.insert(0, str(RACINE))

# Headers CLAUDE.md §ENTRAÎNEMENT IA → label interne utilisé par les tests
_LABEL_HEADERS: dict[str, str] = {
    "Entraîner": "Lancer",
    "Évaluer le modèle existant sur HOLDOUT": "Valider",
}
_TRAIN_CMD_PREFIX = "python3 ai/train.py"

# Module factice pour engine.w40k_core (import lourd, évité dans les tests)
_FAKE_ENGINE_MODULE = MagicMock()
_FAKE_ENGINE_MODULE.reset_debug_log_flag = lambda: None
_FAKE_ENGINE_MODULE.W40KEngine = MagicMock()


def _make_common_patches() -> list:
    # Retourne des patchers prêts à l'emploi (plus besoin d'inspecter les cibles)
    return [
        patch.dict("sys.modules", {"engine.w40k_core": _FAKE_ENGINE_MODULE}),
        patch("subprocess.run", MagicMock(returncode=0, stdout="", stderr="")),
    ]


# ---------------------------------------------------------------------------
# Extraction des commandes depuis CLAUDE.md
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=None)
def _extract_train_commands() -> list[tuple[str, list[str]]]:
    """
    Retourne [(label, argv_list)] pour chaque commande train.py de CLAUDE.md.

    Format attendu dans §ENTRAÎNEMENT IA :
      <Header> :
      python3 ai/train.py <args…>
    """
    commands: list[tuple[str, list[str]]] = []
    lines = CLAUDE_MD.read_text().splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        for header, label in _LABEL_HEADERS.items():
            if stripped == f"{header} :":
                # Cherche la commande sur les 2 lignes suivantes
                for j in range(i + 1, min(i + 3, len(lines))):
                    cmd = lines[j].strip()
                    if cmd.startswith(_TRAIN_CMD_PREFIX):
                        raw = cmd[len(_TRAIN_CMD_PREFIX):].strip().replace("<X>", "1")
                        commands.append((label, shlex.split(raw)))
                        break
    return commands


def _get_command(label: str) -> list[str]:
    """Retourne argv pour la commande dont le label correspond."""
    for lbl, argv in _extract_train_commands():
        if lbl == label:
            return argv
    raise KeyError(f"Commande '{label}' introuvable dans CLAUDE.md")


# ---------------------------------------------------------------------------
# Helpers d'exécution
# ---------------------------------------------------------------------------

def _run_main(argv: list[str], extra_patches: dict | None = None) -> tuple[int, str]:
    """
    Appelle train.main() avec argv contrôlé et les patchs minimaux.

    Retourne (exit_code, stdout_capturé).
    """
    # Import tardif : les dépendances ML (~1.3 s) ne sont chargées qu'une fois
    # dans le processus pytest (sys.modules les met en cache).
    from ai import train as train_module  # noqa: PLC0415

    old_argv = sys.argv
    # `main()` pose `W40K_BOARD_PATH` (ai/train.py, dérivé de `--resolution`) dans
    # l'environnement du PROCESSUS, et ne le retire jamais : c'est voulu pour un vrai run, où
    # tout ce qui suit doit lire ce plateau. Ici, `main()` rend la main au worker pytest, donc
    # sans restauration tous les tests suivants du même worker héritent du plateau x1 — le
    # config-loader résout `geometry_is_hex` dessus, la géométrie passe en hex, et un test
    # moteur qui n'a rien demandé change de métrique. Mesuré : `test_returned_models_placement`
    # rougissait selon la répartition xdist. Même restauration que `sys.argv`, même raison.
    old_board = os.environ.get("W40K_BOARD_PATH")
    buf = io.StringIO()
    result: int = 1

    try:
        sys.argv = ["train.py"] + argv

        with ExitStack() as stack:
            for p in _make_common_patches():
                stack.enter_context(p)

            if extra_patches:
                for target, side_effect_or_value in extra_patches.items():
                    # Callables (lambdas, classes exception) et instances BaseException
                    # → side_effect ; toute autre valeur (dict, str…) → new.
                    use_side_effect = callable(side_effect_or_value) or isinstance(
                        side_effect_or_value, BaseException
                    )
                    if use_side_effect:
                        stack.enter_context(patch(target, side_effect=side_effect_or_value))
                    else:
                        stack.enter_context(patch(target, new=side_effect_or_value))

            with redirect_stdout(buf):
                try:
                    result = train_module.main()
                except SystemExit as exc:
                    result = exc.code if isinstance(exc.code, int) else 0
    finally:
        sys.argv = old_argv
        if old_board is None:
            os.environ.pop("W40K_BOARD_PATH", None)
        else:
            os.environ["W40K_BOARD_PATH"] = old_board

    return (result if isinstance(result, int) else 1), buf.getvalue()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_claude_md_contient_commandes_train() -> None:
    """Vérifie que CLAUDE.md contient exactement une ligne Lancer et une ligne Valider."""
    labels = [lbl for lbl, _ in _extract_train_commands()]
    for expected in ("Lancer", "Valider"):
        n = labels.count(expected)
        assert n == 1, (
            f"Label '{expected}' doit apparaître exactement une fois dans CLAUDE.md §ENTRAÎNEMENT IA "
            f"(trouvé {n} fois)"
        )


def test_lancer_command_passes_guards() -> None:
    """
    La commande 'Lancer' de CLAUDE.md parse sans erreur et passe les gardes
    de compatibilité (pas de conflit --new/--append, check_model_lifecycle OK).

    On s'arrête juste avant le lancement effectif de l'entraînement en
    mockant get_scenario_list_for_phase pour lever SystemExit(0).
    """
    argv = _get_command("Lancer")
    code, output = _run_main(
        argv,
        extra_patches={"ai.train.get_scenario_list_for_phase": SystemExit(0)},
    )
    assert code == 0, (
        f"La commande 'Lancer' a échoué (code={code}).\nSortie : {output[-500:]}"
    )


def test_valider_command_passes_guards() -> None:
    """
    La commande 'Valider' de CLAUDE.md parse sans erreur et passe le garde
    `--scenario bot is not allowed in --test-only mode` (scénario = 'default').

    On s'arrête juste après le garde (avant l'évaluation réelle) en mockant
    resolve_final_eval_scenarios pour lever SystemExit(0).
    """
    argv = _get_command("Valider")
    code, output = _run_main(
        argv,
        extra_patches={
            "ai.unit_registry.UnitRegistry": lambda *a, **kw: MagicMock(),
            "ai.train.resolve_final_eval_scenarios": SystemExit(0),
        },
    )
    assert code == 0, (
        f"La commande 'Valider' a échoué (code={code}).\nSortie : {output[-500:]}"
    )


def test_valider_with_scenario_bot_fails_guard() -> None:
    """
    Régression : `--scenario bot` sur la ligne 'Valider' doit être refusé par
    train.py (ValueError ligne ~4747).

    Ce test DEVIENT ROUGE si on remet `--scenario bot` dans CLAUDE.md sur la
    ligne 'Valider' — ou si le garde est retiré de train.py.
    """
    argv = _get_command("Valider") + ["--scenario", "bot"]
    code, output = _run_main(
        argv,
        extra_patches={"ai.unit_registry.UnitRegistry": lambda *a, **kw: MagicMock()},
    )
    assert code != 0, (
        "Le garde '--scenario bot is not allowed in --test-only mode' n'a pas "
        "déclenché : main() a renvoyé 0 au lieu de 1."
    )
    assert "bot is not allowed in --test-only mode" in output, (
        f"Message d'erreur attendu absent de la sortie.\nSortie : {output[-500:]}"
    )


@pytest.mark.parametrize("avant", [None, "board/44x60x5"])
def test_main_ne_fuit_pas_le_plateau_dans_l_environnement(monkeypatch, avant) -> None:
    """`main()` ne doit rien laisser de son plateau à ce qui tourne après lui.

    `ai/train.py` pose `W40K_BOARD_PATH` (dérivé de `--resolution`) dans l'environnement du
    PROCESSUS et ne le retire jamais — correct pour un run réel, où tout ce qui suit doit lire
    ce plateau. Ici le processus est un worker pytest : la variable survit au test, le
    config-loader y résout `geometry_is_hex`, et les tests moteur suivants du même worker
    changent de géométrie sans l'avoir demandé. Défaut mesuré le 2026-09-07 :
    `tests/unit/engine/test_returned_models_placement.py` rougissait selon la répartition xdist,
    jamais lancé seul.

    L'état d'entrée est POSÉ, jamais lu : les tests voisins de ce module appellent `main()` avant
    celui-ci, donc lire `os.environ` à l'entrée revenait à comparer la fuite à elle-même — vert
    même sans restauration (mesuré). Les deux valeurs posées sont les deux branches de la
    restauration, et aucune n'est celle que `main()` écrit ici (`--resolution 1` → `44x60x1`).
    """
    if avant is None:
        monkeypatch.delenv("W40K_BOARD_PATH", raising=False)
    else:
        monkeypatch.setenv("W40K_BOARD_PATH", avant)

    argv = _get_command("Lancer")
    code, _output = _run_main(
        argv,
        extra_patches={"ai.train.get_scenario_list_for_phase": SystemExit(0)},
    )
    assert code == 0, f"la commande 'Lancer' doit atteindre le garde (code={code})"
    assert os.environ.get("W40K_BOARD_PATH") == avant, (
        f"main() a laissé W40K_BOARD_PATH={os.environ.get('W40K_BOARD_PATH')!r} alors que le "
        f"processus portait {avant!r} : tout test suivant du même worker hérite de cette "
        "résolution de plateau."
    )
