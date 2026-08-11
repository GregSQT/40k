"""Verrous de la porte « un chantier livré prend sa ligne ».

Deux étages. `verdict` est PUR : la règle se vérifie sans fabriquer un dépôt. Les deux helpers
git, eux, sont testés sur un dépôt jetable — c'est là que vivaient les deux défauts de la première
livraison (accents échappés à l'impression, simplification d'historique), et les tester par le
seul cœur pur les aurait laissés passer une seconde fois.

Le calibrage du plafond est consigné en tête du module : un test ne peut pas le rejouer sans figer
un échantillon qui bouge à chaque fusion.
"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "check_roadmap_declared", ROOT / "scripts" / "check_roadmap_declared.py"
)
assert _SPEC is not None and _SPEC.loader is not None
gate = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gate)


def merges(count: int) -> list[str]:
    return [f"abc{i:04d} merge: chantier {i}" for i in range(count)]


def test_branch_that_declares_always_passes() -> None:
    """Le cas idéal : la ligne est écrite dans la branche. La dette antérieure n'y change rien."""
    ok, message = gate.verdict(merges(99), branch_declares=True)
    assert ok and "met la feuille de route à jour" in message


def test_no_debt_passes() -> None:
    ok, _message = gate.verdict([], branch_declares=False)
    assert ok


def test_the_calibrated_ceiling_is_three() -> None:
    """Le plafond est une MESURE, pas un réglage libre.

    Mesuré sur les merges postérieurs au 2026-08-10 : 1 → 8 refus sur 8, 2 → 4, 3 → 1, et ce
    refus unique tombe sur la fusion où trois chantiers s'étaient empilés. Le relever laisse
    repasser des trous, le baisser rend la porte rouge en permanence — donc elle sera contournée.
    Ce test existe parce que sans lui les suivants passent à N'IMPORTE QUEL plafond : vérifié en
    portant la constante à 999, la suite restait verte.
    """
    assert gate.MAX_UNDECLARED == 3


def test_two_undeclared_chantiers_still_pass() -> None:
    """Le suivi tardif reste permis : c'est le flux réel, mesuré sur 25 merges."""
    ok, message = gate.verdict(merges(2), branch_declares=False)
    assert ok
    assert "avant blocage" in message


def test_three_undeclared_chantiers_block() -> None:
    ok, message = gate.verdict(merges(3), branch_declares=False)
    assert not ok
    assert "sans que la feuille de route" in message


def test_the_refusal_names_the_undeclared_chantiers() -> None:
    """Un refus qui ne dit pas QUOI déclarer se contourne au lieu de se traiter."""
    listing = merges(gate.MAX_UNDECLARED)
    _ok, message = gate.verdict(listing, branch_declares=False)
    for line in listing:
        assert line in message


def test_the_refusal_states_its_escape_hatch() -> None:
    _ok, message = gate.verdict(merges(3), branch_declares=False)
    assert "--no-verify" in message


def test_the_hook_is_installed_and_executable() -> None:
    """Une porte non branchée ne garde rien : `core.hooksPath` doit viser le dossier versionné.

    Ce test lisait le fichier sans jamais lire la configuration git : `core.hooksPath` pouvait
    être désarmé, la porte muette, et le test restait vert.
    """
    import pytest

    # Hook versionné dans ce dépôt / worktree
    old_hook = ROOT / ".githooks" / "pre-merge-commit"
    assert not old_hook.exists(), "le hook obsolète `pre-merge-commit` doit être supprimé"
    hook = ROOT / ".githooks" / "prepare-commit-msg"
    assert hook.exists(), "le hook `prepare-commit-msg` est absent de `.githooks/`"
    assert hook.stat().st_mode & 0o111, "le hook n'est pas exécutable"
    content = hook.read_text(encoding="utf-8")
    assert "check_roadmap_declared.py" in content
    assert "MERGE_HEAD" in content, "le hook doit garder le contrôle via MERGE_HEAD"

    # Branchement actif
    configured = subprocess.run(
        ["git", "config", "core.hooksPath"],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout.strip()
    assert configured, "core.hooksPath n'est pas défini : le hook ne se déclenchera jamais"
    configured_path = pathlib.Path(configured)
    hooks_dir = configured_path if configured_path.is_absolute() else ROOT / configured
    if hooks_dir.resolve() != (ROOT / ".githooks").resolve():
        pytest.skip(
            f"core.hooksPath absolu vise {hooks_dir} (dépôt principal), pas ce worktree — "
            "vérification du branchement actif différée au merge dans main"
        )
    assert (hooks_dir / "prepare-commit-msg").exists(), (
        f"core.hooksPath vise {configured!r} mais `prepare-commit-msg` n'y est pas"
    )


# ----------------------------------------------------------------- les deux helpers git


def run(repo: pathlib.Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def scratch_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """Dépôt jetable reproduisant la forme qui compte : un chemin ACCENTUÉ et des fusions."""
    repo = tmp_path / "depot"
    (repo / "Documentation" / "Implémentation").mkdir(parents=True)
    run(repo.parent, "init", "-q", "-b", "main", str(repo))
    run(repo, "config", "user.email", "t@t")
    run(repo, "config", "user.name", "t")
    (repo / "socle.txt").write_text("x", encoding="utf-8")
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "socle")
    return repo


def commit_roadmap(repo: pathlib.Path, text: str) -> None:
    (repo / gate.ROADMAP).write_text(text, encoding="utf-8")
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "feuille de route")


def merge_branch(repo: pathlib.Path, name: str, touch_roadmap: bool) -> None:
    run(repo, "checkout", "-qb", name)
    if touch_roadmap:
        commit_roadmap(repo, f"ligne de {name}")
    else:
        (repo / f"{name}.py").write_text("x = 1\n", encoding="utf-8")
        run(repo, "add", "-A")
        run(repo, "commit", "-qm", f"code de {name}")
    run(repo, "checkout", "-q", "main")
    run(repo, "merge", "-q", "--no-ff", "--no-verify", "-m", f"merge: {name}", name)


def _install_hook(repo: pathlib.Path, hook_name: str, body: str) -> None:
    hooks_dir = repo / ".githooks"
    hooks_dir.mkdir(exist_ok=True)
    hook = hooks_dir / hook_name
    hook.write_text(body, encoding="utf-8")
    hook.chmod(0o755)
    run(repo, "config", "core.hooksPath", ".githooks")


def _setup_repo_with_script(repo: pathlib.Path) -> None:
    """Copie le script dans le dépôt de test.

    Permet au hook d'appeler `$(git rev-parse --show-toplevel)/scripts/check_roadmap_declared.py`
    et d'obtenir ROOT = dépôt de test, ce qui fait que toutes les opérations git du script
    s'exécutent dans le bon contexte (MERGE_HEAD, historique, feuille de route).
    """
    script_dir = repo / "scripts"
    script_dir.mkdir(exist_ok=True)
    src = ROOT / "scripts" / "check_roadmap_declared.py"
    (script_dir / "check_roadmap_declared.py").write_bytes(src.read_bytes())


def test_branch_declaration_is_seen_through_an_accented_path(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    """LE bug de la première livraison : git échappe les accents des chemins qu'il imprime.

    Sans `core.quotePath=false`, la comparaison au chemin littéral est toujours fausse et la
    sortie de secours « la branche déclare » est du code mort.
    """
    repo = scratch_repo(tmp_path)
    monkeypatch.setattr(gate, "ROOT", repo)
    run(repo, "checkout", "-qb", "chantier")
    commit_roadmap(repo, "la branche déclare")
    run(repo, "checkout", "-q", "main")
    assert gate.branch_touches_roadmap("main", "chantier") is True


def test_debt_resets_after_a_declaration(tmp_path: pathlib.Path, monkeypatch) -> None:
    """Sans `--first-parent`, la dette repartait d'avant la fusion qui venait de la solder."""
    repo = scratch_repo(tmp_path)
    monkeypatch.setattr(gate, "ROOT", repo)
    for i in range(3):
        merge_branch(repo, f"chantier{i}", touch_roadmap=False)
    assert len(gate.undeclared_merges("HEAD")) == 3
    merge_branch(repo, "declaration", touch_roadmap=True)
    assert gate.undeclared_merges("HEAD") == [], (
        "la fusion qui écrit la feuille de route doit remettre la dette à zéro"
    )


def test_debt_counts_only_the_trunk(tmp_path: pathlib.Path, monkeypatch) -> None:
    repo = scratch_repo(tmp_path)
    monkeypatch.setattr(gate, "ROOT", repo)
    commit_roadmap(repo, "état initial")
    merge_branch(repo, "chantier-a", touch_roadmap=False)
    merge_branch(repo, "chantier-b", touch_roadmap=False)
    dette = gate.undeclared_merges("HEAD")
    assert len(dette) == 2 and all("merge: chantier-" in line for line in dette)


# -------------------------------------------- verrou end-to-end hook vs MERGE_HEAD


def scratch_repo_with_debt(tmp_path: pathlib.Path, count: int) -> pathlib.Path:
    """Dépôt avec `count` merges sans déclaration de feuille de route."""
    repo = scratch_repo(tmp_path)
    for i in range(count):
        run(repo, "checkout", "-qb", f"ch{i}")
        (repo / f"f{i}.py").write_text("x\n", encoding="utf-8")
        run(repo, "add", "-A")
        run(repo, "commit", "-qm", f"code ch{i}")
        run(repo, "checkout", "-q", "main")
        run(repo, "merge", "-q", "--no-ff", "--no-verify", "-m", f"merge: ch{i}", f"ch{i}")
    return repo


_NEW_HOOK_BODY = (
    "#!/bin/sh\n"
    '[ -f "$(git rev-parse --git-dir)/MERGE_HEAD" ] || exit 0\n'
    'exec python3 "$(git rev-parse --show-toplevel)/scripts/check_roadmap_declared.py" --merge\n'
)


def test_clean_merge_passes_with_prepare_commit_msg_hook(tmp_path: pathlib.Path) -> None:
    """Verrou GREEN fusion propre : prepare-commit-msg reçoit MERGE_HEAD présent → commit créé.

    git merge --no-ff -m "..." branch doit suffire — plus de git commit de rattrapage.
    """
    repo = scratch_repo(tmp_path)
    _setup_repo_with_script(repo)
    _install_hook(repo, "prepare-commit-msg", _NEW_HOOK_BODY)

    run(repo, "checkout", "-qb", "chantier-test")
    (repo / "code.py").write_text("x = 1\n", encoding="utf-8")
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "code de chantier-test")
    run(repo, "checkout", "-q", "main")

    count_before = run(repo, "log", "--oneline", "--first-parent").count("\n") + 1
    result = subprocess.run(
        ["git", "merge", "--no-ff", "-m", "merge: chantier-test", "chantier-test"],
        cwd=repo, capture_output=True, text=True,
    )
    count_after = run(repo, "log", "--oneline", "--first-parent").count("\n") + 1

    assert result.returncode == 0, (
        f"le merge doit réussir sans git commit de rattrapage :\n{result.stderr}"
    )
    assert count_after == count_before + 1, (
        "un commit de merge doit avoir été créé directement par git merge"
    )


def test_conflicting_merge_passes_with_prepare_commit_msg_hook(tmp_path: pathlib.Path) -> None:
    """Verrou GREEN fusion conflictuelle : MERGE_HEAD présent lors de git commit → porte active.

    Après résolution manuelle et git commit -m "...", le hook doit s'exécuter (MERGE_HEAD présent)
    et laisser passer la porte (dette < plafond dans un dépôt frais).
    """
    repo = scratch_repo(tmp_path)
    _setup_repo_with_script(repo)
    _install_hook(repo, "prepare-commit-msg", _NEW_HOOK_BODY)

    run(repo, "checkout", "-qb", "chantier-conflit")
    (repo / "shared.txt").write_text("version branche\n", encoding="utf-8")
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "chantier-conflit: shared")
    run(repo, "checkout", "-q", "main")
    (repo / "shared.txt").write_text("version main\n", encoding="utf-8")
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "main: shared concurrente")

    subprocess.run(
        ["git", "merge", "--no-ff", "chantier-conflit"],
        cwd=repo, capture_output=True, text=True,
    )
    assert (repo / ".git" / "MERGE_HEAD").exists(), (
        "MERGE_HEAD doit exister après un merge conflictuel"
    )

    (repo / "shared.txt").write_text("résolu\n", encoding="utf-8")
    run(repo, "add", "shared.txt")

    count_before = run(repo, "log", "--oneline", "--first-parent").count("\n") + 1
    result = subprocess.run(
        ["git", "commit", "-m", "merge: chantier-conflit résolu"],
        cwd=repo, capture_output=True, text=True,
    )
    count_after = run(repo, "log", "--oneline", "--first-parent").count("\n") + 1

    assert result.returncode == 0, (
        f"git commit après résolution de conflit doit réussir :\n{result.stderr}"
    )
    assert count_after == count_before + 1, (
        "un commit de merge doit avoir été créé"
    )


def test_gate_is_dead_with_pre_merge_commit_hook(tmp_path: pathlib.Path) -> None:
    """Verrou RED : avec pre-merge-commit + guard MERGE_HEAD, la porte ne s'exécute jamais.

    MERGE_HEAD est absent quand pre-merge-commit fire → le guard sort 0 silencieusement →
    même avec 3 merges sans déclaration, le 4e passe sans contrôle. Ce test prouve le DÉFAUT :
    il doit PASSER (le merge est incorrectement laissé passer). Si ce test devient ROUGE,
    c'est que la porte s'est réveillée dans pre-merge-commit — ce qui serait inattendu.
    """
    repo = scratch_repo_with_debt(tmp_path, gate.MAX_UNDECLARED)
    _setup_repo_with_script(repo)
    _install_hook(repo, "pre-merge-commit", _NEW_HOOK_BODY)

    run(repo, "checkout", "-qb", "ch-final")
    (repo / "extra.py").write_text("x\n", encoding="utf-8")
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "code ch-final")
    run(repo, "checkout", "-q", "main")

    result = subprocess.run(
        ["git", "merge", "--no-ff", "-m", "merge: ch-final", "ch-final"],
        cwd=repo, capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        "avec pre-merge-commit, la porte est morte : le merge doit passer sans contrôle "
        f"(rc={result.returncode}, stderr={result.stderr!r})"
    )


def test_gate_blocks_violations_with_prepare_commit_msg_hook(tmp_path: pathlib.Path) -> None:
    """Verrou GREEN : avec prepare-commit-msg, la porte s'exécute et bloque les violations.

    MERGE_HEAD est présent quand prepare-commit-msg fire → guard laisse passer → script tourne →
    3 merges sans déclaration = plafond atteint → le 4e est bloqué. Ce test prouve le CORRECTIF.
    """
    repo = scratch_repo_with_debt(tmp_path, gate.MAX_UNDECLARED)
    _setup_repo_with_script(repo)
    _install_hook(repo, "prepare-commit-msg", _NEW_HOOK_BODY)

    run(repo, "checkout", "-qb", "ch-final")
    (repo / "extra.py").write_text("x\n", encoding="utf-8")
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "code ch-final")
    run(repo, "checkout", "-q", "main")

    result = subprocess.run(
        ["git", "merge", "--no-ff", "-m", "merge: ch-final", "ch-final"],
        cwd=repo, capture_output=True, text=True,
    )
    assert result.returncode != 0, (
        "avec prepare-commit-msg, la porte doit bloquer quand la dette atteint le plafond"
    )
    assert "sans que la feuille de route" in result.stderr
