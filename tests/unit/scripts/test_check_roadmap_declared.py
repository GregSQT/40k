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
import os
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


def test_the_calibrated_ceiling_is_two() -> None:
    """Le plafond est une MESURE, pas un réglage libre.

    Les chiffres du calibrage vivent en tête de `check_roadmap_declared.py`, AVEC leur méthode et
    leur date — et nulle part ailleurs. Ils étaient recopiés ici, les deux jeux se sont
    contredits (2026-08-12), et un chiffre recopié n'a aucun moyen de vieillir avec sa source.
    Ce test existe parce que les suivants sont écrits EN FONCTION du plafond : sans cette épingle,
    ils passeraient à n'importe quelle valeur — vérifié en portant la constante à 999.

    2 depuis le 2026-08-12 (décision utilisateur, option B de l'arbitrage) : à 3, la mesure montre
    que la porte ne se déclenchait plus une seule fois sur le flux moderne.
    """
    assert gate.MAX_UNDECLARED == 2


def test_debt_just_under_the_ceiling_still_passes() -> None:
    """Le suivi tardif reste permis : c'est le flux réel qui écrit la ligne juste après la fusion."""
    ok, message = gate.verdict(merges(gate.MAX_UNDECLARED - 1), branch_declares=False)
    assert ok
    assert "avant blocage" in message


def test_debt_at_the_ceiling_blocks() -> None:
    ok, message = gate.verdict(merges(gate.MAX_UNDECLARED), branch_declares=False)
    assert not ok
    assert "sans que la feuille de route" in message


def test_the_refusal_names_the_undeclared_chantiers() -> None:
    """Un refus qui ne dit pas QUOI déclarer se contourne au lieu de se traiter."""
    listing = merges(gate.MAX_UNDECLARED)
    _ok, message = gate.verdict(listing, branch_declares=False)
    for line in listing:
        assert line in message


def test_the_refusal_states_the_escape_hatch_that_exists() -> None:
    """Le refus indiquait `--no-verify`, qui ne désarme pas cette porte : une issue murée.

    Il doit nommer celle qui marche, ET la remédiation qui débloque sans annuler la fusion.
    """
    _ok, message = gate.verdict(merges(gate.MAX_UNDECLARED), branch_declares=False)
    assert f"{gate.GATE_OFF_ENV}=off git commit" in message, (
        "mi-fusion, `git merge` répond « You have not concluded your merge » : le refus doit "
        "nommer la commande qui marche DANS l'état où il s'affiche"
    )
    assert "git add" in message


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
        # UN SEUL état justifie de ne pas conclure : `core.hooksPath` est absolu et vise les
        # `.githooks` du dépôt PRINCIPAL, que ce worktree partage. Tout autre valeur DÉSARME la
        # porte — `git config core.hooksPath .git/hooks` la rendait muette et ce test passait en
        # SKIPPED, c'est-à-dire vert : exactement le vert vacant que sa docstring prétend fermer.
        commun = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
        # `--git-common-dir` rend un chemin tantôt absolu, tantôt relatif à ROOT selon la version
        # de git : le résoudre contre ROOT couvre les deux sans dépendre d'un `--path-format`.
        principal = (ROOT / commun).resolve().parent
        assert hooks_dir.resolve() == (principal / ".githooks").resolve(), (
            f"core.hooksPath vise {hooks_dir} : ni les `.githooks` de ce worktree, ni ceux du "
            f"dépôt principal ({principal}) — la porte est DÉSARMÉE"
        )
        assert (hooks_dir / "prepare-commit-msg").exists(), (
            f"core.hooksPath vise {hooks_dir}, où `prepare-commit-msg` est absent"
        )
        pytest.skip(
            f"core.hooksPath vise les `.githooks` du dépôt principal ({hooks_dir}), partagés par "
            "ce worktree — branchement vérifié là-bas, rien de plus à conclure ici"
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
    """Dépôt jetable reproduisant la forme qui compte : un chemin ACCENTUÉ et des fusions.

    Les fixtures fabriquent leur historique AVANT d'installer le moindre hook : elles portaient un
    `--no-verify` qui n'avait donc aucun effet observable, et laissait croire qu'un test couvrait
    la sortie de secours. Il est retiré ; la sortie de secours a désormais son propre test.
    """
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
    run(repo, "merge", "-q", "--no-ff", "-m", f"merge: {name}", name)


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
        run(repo, "merge", "-q", "--no-ff", "-m", f"merge: ch{i}", f"ch{i}")
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
    même avec la dette au plafond, la fusion suivante passe sans contrôle. Ce test prouve le DÉFAUT :
    il doit PASSER (le merge est incorrectement laissé passer). Si ce test devient ROUGE,
    c'est que la porte s'est réveillée dans pre-merge-commit — ce qui serait inattendu.
    """
    repo = scratch_repo_with_debt(tmp_path, gate.MAX_UNDECLARED)
    _setup_repo_with_script(repo)
    _install_hook(repo, "pre-merge-commit", _NEW_HOOK_BODY)

    def fusionne(nom: str) -> subprocess.CompletedProcess[str]:
        run(repo, "checkout", "-qb", nom)
        (repo / f"{nom}.py").write_text("x\n", encoding="utf-8")
        run(repo, "add", "-A")
        run(repo, "commit", "-qm", f"code {nom}")
        run(repo, "checkout", "-q", "main")
        return subprocess.run(
            ["git", "merge", "--no-ff", "-m", f"merge: {nom}", nom],
            cwd=repo, capture_output=True, text=True,
        )

    mort = fusionne("ch-mal-branche")
    assert mort.returncode == 0, (
        "avec pre-merge-commit, la porte est morte : le merge doit passer sans contrôle "
        f"(rc={mort.returncode}, stderr={mort.stderr!r})"
    )
    assert "feuille de route" not in mort.stdout + mort.stderr, (
        "la porte n'a pas dû dire un mot : ce hook s'exécute avant l'écriture de MERGE_HEAD"
    )

    # CONTRASTE — sans lui ce test ne vaut rien : « rc 0 » est aussi le résultat d'un script
    # absent, d'un chemin faux ou d'un hook jamais installé. Le MÊME corps, branché au bon
    # moment, doit refuser sur le MÊME dépôt : c'est ce qui prouve que le montage est vivant et
    # que seul le moment du déclenchement fait la différence.
    (repo / ".githooks" / "pre-merge-commit").unlink()
    _install_hook(repo, "prepare-commit-msg", _NEW_HOOK_BODY)
    vivant = fusionne("ch-bien-branche")
    assert vivant.returncode != 0, (
        "le même corps en prepare-commit-msg doit refuser : sinon le vert ci-dessus ne prouve "
        f"rien (stderr={vivant.stderr!r})"
    )
    assert "sans que la feuille de route" in vivant.stderr


def run_gate(repo: pathlib.Path, mode: str) -> subprocess.CompletedProcess[str]:
    """Lance la porte comme le hook la lance : en PROCESSUS, depuis le dépôt jetable.

    L'appeler en import ne prouverait rien sur ce qui compte ici — le code de sortie et ce que
    l'utilisateur LIT quand git s'arrête.
    """
    _setup_repo_with_script(repo)
    return subprocess.run(
        ["python3", str(repo / "scripts" / "check_roadmap_declared.py"), mode],
        cwd=repo, capture_output=True, text=True,
    )


def test_merge_mode_without_merge_head_refuses_and_says_what_to_do(
    tmp_path: pathlib.Path,
) -> None:
    """LE défaut du 2026-08-11 : `--merge` hors fusion mourait sur une trace Python.

    Refus, PAS feu vert : `pre-merge-commit` tourne avant l'écriture de MERGE_HEAD, donc un
    « sans objet » ici rendrait la porte muette sans que rien ne le signale.
    """
    repo = scratch_repo(tmp_path)
    result = run_gate(repo, "--merge")

    assert "Traceback" not in result.stderr and "Traceback" not in result.stdout
    assert result.returncode == 2, (
        "sans MERGE_HEAD la porte ne peut pas se prononcer : elle refuse, elle ne dit pas oui"
    )
    lisible = result.stdout + result.stderr
    assert "MERGE_HEAD" in lisible and "prepare-commit-msg" in lisible
    assert "--status" in lisible


def start_merge(repo: pathlib.Path, branch: str) -> None:
    subprocess.run(
        ["git", "merge", "--no-ff", "--no-commit", "--no-verify", branch],
        cwd=repo, capture_output=True, text=True,
    )
    assert (repo / ".git" / "MERGE_HEAD").exists(), "le test doit VRAIMENT être en cours de fusion"


def test_merge_on_a_detached_head_is_out_of_scope(tmp_path: pathlib.Path) -> None:
    """VRAIE fusion, MERGE_HEAD présent, mais HEAD détaché : `symbolic-ref` sort 128.

    Ce chemin-là est atteignable par le hook réel. Feu vert légitime : fusionner sur un HEAD
    détaché ne livre rien dans `main`, donc la porte n'a pas d'objet — ce n'est pas un défaut masqué.

    Le CONTRASTE est la moitié du verrou : sans lui, le test se contente de « rc 0 + sans objet »,
    qui est aussi la sortie de n'importe quelle PANNE de `symbolic-ref` — vérifié, avec un
    `git_maybe` rendant `None` en toutes circonstances le test restait vert. La même fusion, faite
    sur `main`, doit faire se prononcer la porte : c'est ce qui prouve que le feu vert vient du
    détachement et de rien d'autre.
    """
    repo = scratch_repo(tmp_path)
    run(repo, "checkout", "-qb", "chantier")
    (repo / "code.py").write_text("x = 1\n", encoding="utf-8")
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "code de chantier")
    run(repo, "checkout", "-q", "main")

    start_merge(repo, "chantier")
    sur_main = run_gate(repo, "--merge")
    assert "sans objet" not in sur_main.stdout, (
        "sur `main`, la porte doit se PRONONCER — sinon le feu vert du cas détaché ne prouve rien"
    )
    assert sur_main.returncode == 0 and "chantier(s) livré(s)" in sur_main.stdout
    run(repo, "merge", "--abort")

    run(repo, "checkout", "-q", "--detach", "HEAD")
    start_merge(repo, "chantier")
    result = run_gate(repo, "--merge")

    assert "Traceback" not in result.stderr and "Traceback" not in result.stdout
    assert result.returncode == 0, result.stdout + result.stderr
    assert "sans objet" in result.stdout


def test_unrelated_histories_still_get_a_verdict(tmp_path: pathlib.Path) -> None:
    """`--allow-unrelated-histories` : aucune base commune, donc aucun diff trois points possible.

    Le diff trois points sortait 128 « no merge base » et la porte refusait en « contrôle
    impossible » une fusion qui déclare pourtant sa ligne. Elle doit RENDRE UN VERDICT.
    """
    repo = scratch_repo(tmp_path)
    run(repo, "checkout", "-q", "--orphan", "venu-d-ailleurs")
    run(repo, "rm", "-rqf", ".")
    (repo / gate.ROADMAP).parent.mkdir(parents=True, exist_ok=True)
    (repo / gate.ROADMAP).write_text("ligne du chantier venu d'ailleurs", encoding="utf-8")
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "chantier sans ancêtre commun")
    run(repo, "checkout", "-q", "main")
    subprocess.run(
        ["git", "merge", "--no-ff", "--no-commit", "--no-verify",
         "--allow-unrelated-histories", "venu-d-ailleurs"],
        cwd=repo, capture_output=True, text=True,
    )
    assert (repo / ".git" / "MERGE_HEAD").exists()

    result = run_gate(repo, "--merge")

    assert "contrôle impossible" not in result.stderr, result.stderr
    assert result.returncode == 0
    assert "met la feuille de route à jour" in result.stdout, (
        "la branche écrit la ligne : la porte doit le VOIR, base commune ou pas"
    )


def test_an_octopus_merge_is_judged_on_all_its_heads(tmp_path: pathlib.Path) -> None:
    """`git merge A B` : MERGE_HEAD porte DEUX têtes, `rev-parse` n'en rend qu'une.

    La porte jugeait donc la première seule et refusait une livraison déclarée par la seconde.
    Le test met la ligne sur la SECONDE tête, celle que l'ancien code ne regardait pas.
    """
    repo = scratch_repo_with_debt(tmp_path, gate.MAX_UNDECLARED)
    run(repo, "checkout", "-qb", "muette")
    (repo / "code.py").write_text("x = 1\n", encoding="utf-8")
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "chantier sans ligne")
    run(repo, "checkout", "-q", "main")
    run(repo, "checkout", "-qb", "declarante")
    commit_roadmap(repo, "la ligne est sur la seconde tête")
    run(repo, "checkout", "-q", "main")

    subprocess.run(
        ["git", "merge", "--no-ff", "--no-commit", "--no-verify", "muette", "declarante"],
        cwd=repo, capture_output=True, text=True,
    )
    heads = (repo / ".git" / "MERGE_HEAD").read_text(encoding="utf-8").split()
    assert len(heads) == 2, "le test ne prouve rien si la fusion n'est pas une pieuvre"

    result = run_gate(repo, "--merge")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "met la feuille de route à jour" in result.stdout, (
        "une seule tête qui déclare suffit : la livraison a sa ligne"
    )


def test_the_refusal_carries_gits_own_words(tmp_path: pathlib.Path) -> None:
    """Un refus qui dit « exit status 128 » ne dit à personne quoi réparer.

    La cause lisible est le stderr de git. On la compare à ce que git dit LUI-MÊME dans le même
    répertoire, pour ne pas figer une formulation ni une langue.
    """
    hors_depot = tmp_path / "sans-git"
    (hors_depot / "scripts").mkdir(parents=True)
    src = ROOT / "scripts" / "check_roadmap_declared.py"
    (hors_depot / "scripts" / "check_roadmap_declared.py").write_bytes(src.read_bytes())

    mot_de_git = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=hors_depot, capture_output=True, text=True,
    ).stderr.strip()
    assert mot_de_git, "le test ne prouve rien si git ne dit rien"

    result = subprocess.run(
        ["python3", str(hors_depot / "scripts" / "check_roadmap_declared.py"), "--merge"],
        cwd=hors_depot, capture_output=True, text=True,
    )

    assert result.returncode == 2
    assert mot_de_git in result.stderr, (
        f"le refus doit porter la cause dite par git ({mot_de_git!r}) :\n{result.stderr}"
    )


def test_merge_mode_outside_a_git_repo_refuses(tmp_path: pathlib.Path) -> None:
    """« git ne répond pas » n'est PAS « HEAD détaché ».

    Mesuré le 2026-08-12 avant correctif : hors dépôt, `--merge` imprimait « fusion hors `main`,
    sans objet » et sortait **0** — un feu vert silencieux, quand `--status` refusait sur le même
    répertoire. Une porte qui ne peut pas lire le dépôt ne laisse pas passer la fusion.
    """
    hors_depot = tmp_path / "pas-un-depot-merge"
    (hors_depot / "scripts").mkdir(parents=True)
    src = ROOT / "scripts" / "check_roadmap_declared.py"
    (hors_depot / "scripts" / "check_roadmap_declared.py").write_bytes(src.read_bytes())

    result = subprocess.run(
        ["python3", str(hors_depot / "scripts" / "check_roadmap_declared.py"), "--merge"],
        cwd=hors_depot, capture_output=True, text=True,
    )

    assert "Traceback" not in result.stderr and "Traceback" not in result.stdout
    assert "sans objet" not in result.stdout, "une panne de git ne se déguise pas en « sans objet »"
    assert result.returncode == 2
    assert "contrôle impossible" in result.stderr


def test_status_mode_reports_without_blocking(tmp_path: pathlib.Path) -> None:
    """`--status` n'a pas le chemin MERGE_HEAD : il doit rester un rapport, jamais un blocage."""
    repo = scratch_repo_with_debt(tmp_path, gate.MAX_UNDECLARED)
    result = run_gate(repo, "--status")

    assert "Traceback" not in result.stderr and "Traceback" not in result.stdout
    assert result.returncode == 0, "`--status` ne bloque rien, même dette au plafond"
    assert "sans que la feuille de route" in result.stdout


def test_an_unexpected_git_failure_refuses_readably(tmp_path: pathlib.Path) -> None:
    """Filet : hors dépôt git, tout appel git échoue. La porte refuse en clair, sans trace.

    C'est la garantie de fond demandée — QUEL QUE SOIT l'état, feu vert ou refus lisible.
    """
    hors_depot = tmp_path / "pas-un-depot"
    (hors_depot / "scripts").mkdir(parents=True)
    src = ROOT / "scripts" / "check_roadmap_declared.py"
    (hors_depot / "scripts" / "check_roadmap_declared.py").write_bytes(src.read_bytes())

    result = subprocess.run(
        ["python3", str(hors_depot / "scripts" / "check_roadmap_declared.py"), "--status"],
        cwd=hors_depot, capture_output=True, text=True,
    )

    assert "Traceback" not in result.stderr and "Traceback" not in result.stdout
    assert result.returncode == 2
    assert "contrôle impossible" in result.stderr
    # Le filet aussi doit indiquer une issue qui existe : il annonçait `git merge --no-verify`,
    # murée deux fois (n'atteint pas `prepare-commit-msg`, et `git merge` est refusé mi-fusion).
    assert f"{gate.GATE_OFF_ENV}=off git commit" in result.stderr


def _repo_at_the_ceiling_with_the_gate_armed(tmp_path: pathlib.Path) -> pathlib.Path:
    """Dépôt où la PROCHAINE fusion sera refusée, porte réellement branchée."""
    repo = scratch_repo_with_debt(tmp_path, gate.MAX_UNDECLARED)
    _setup_repo_with_script(repo)
    _install_hook(repo, "prepare-commit-msg", _NEW_HOOK_BODY)
    run(repo, "checkout", "-qb", "ch-refuse")
    (repo / "extra.py").write_text("x\n", encoding="utf-8")
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "code ch-refuse")
    run(repo, "checkout", "-q", "main")
    return repo


def test_the_announced_escape_hatch_actually_works(tmp_path: pathlib.Path) -> None:
    """Une sortie de secours annoncée mais murée est pire que pas de sortie du tout.

    Mesuré le 2026-08-12 sur git 2.43 : `git merge --no-verify` — ce que le refus indiquait —
    ne saute PAS `prepare-commit-msg`, donc la porte refusait quand même et l'utilisateur restait
    coincé au milieu de sa fusion.

    ⚠️ LE TEST NE REVIENT PAS À UN DÉPÔT PROPRE. Il portait un `git merge --abort` avant
    d'exercer la sortie : il validait donc un état que l'utilisateur refusé n'a jamais sous la
    main. Or c'est exactement là qu'était le second défaut — `ROADMAP_GATE=off git merge` répond
    `fatal: You have not concluded your merge`. La sortie s'exerce DEPUIS l'état de refus,
    MERGE_HEAD présent, et c'est `git commit` qui la porte.
    """
    repo = _repo_at_the_ceiling_with_the_gate_armed(tmp_path)
    avant = run(repo, "log", "--oneline", "--first-parent").count("\n") + 1

    refuse = subprocess.run(
        ["git", "merge", "--no-ff", "--no-verify", "-m", "merge: ch-refuse", "ch-refuse"],
        cwd=repo, capture_output=True, text=True,
    )
    assert refuse.returncode != 0, (
        "`--no-verify` n'atteint pas `prepare-commit-msg` : la porte doit refuser malgré lui — "
        "c'est précisément pourquoi il ne peut pas servir de sortie de secours"
    )
    assert (repo / ".git" / "MERGE_HEAD").exists(), (
        "la sortie doit s'exercer depuis l'état de refus, pas depuis un dépôt propre"
    )

    desarme = {**os.environ, gate.GATE_OFF_ENV: "off"}
    relance = subprocess.run(
        ["git", "merge", "--no-ff", "-m", "merge: ch-refuse", "ch-refuse"],
        cwd=repo, capture_output=True, text=True, env=desarme,
    )
    assert relance.returncode != 0 and "MERGE_HEAD" in relance.stderr, (
        "mi-fusion, git refuse un nouveau `merge` : le message ne doit donc pas l'indiquer"
    )

    passe = subprocess.run(
        ["git", "commit", "-m", "merge: ch-refuse"],
        cwd=repo, capture_output=True, text=True, env=desarme,
    )
    apres = run(repo, "log", "--oneline", "--first-parent").count("\n") + 1

    assert passe.returncode == 0, (
        f"la sortie de secours annoncée doit laisser passer :\n{passe.stdout}{passe.stderr}"
    )
    assert apres == avant + 1, "le commit de fusion doit exister"
    assert "désarmée" in passe.stdout + passe.stderr, "le désarmement doit se DIRE, pas se taire"
    assert f"{gate.GATE_OFF_ENV}=off git commit" in refuse.stdout + refuse.stderr, (
        "le refus doit nommer la commande qui marche DANS l'état où il s'affiche"
    )


def test_writing_the_line_during_the_merge_unblocks_it(tmp_path: pathlib.Path) -> None:
    """La remédiation dictée par le refus doit débloquer. Elle ne débloquait pas.

    Ni la dette (historique) ni la branche fusionnée ne regardent l'index : l'utilisateur écrivait
    sa ligne, `git add`, `git commit` — et se faisait refuser à l'identique, sans issue.
    """
    repo = _repo_at_the_ceiling_with_the_gate_armed(tmp_path)
    refuse = subprocess.run(
        ["git", "merge", "--no-ff", "-m", "merge: ch-refuse", "ch-refuse"],
        cwd=repo, capture_output=True, text=True,
    )
    assert refuse.returncode != 0 and (repo / ".git" / "MERGE_HEAD").exists(), (
        "le test ne prouve rien sans un refus au milieu d'une fusion"
    )
    avant = run(repo, "log", "--oneline", "--first-parent").count("\n") + 1

    (repo / gate.ROADMAP).write_text("la ligne écrite pour se débloquer", encoding="utf-8")
    run(repo, "add", "-A")
    result = subprocess.run(
        ["git", "commit", "-m", "merge: ch-refuse + sa ligne"],
        cwd=repo, capture_output=True, text=True,
    )
    apres = run(repo, "log", "--oneline", "--first-parent").count("\n") + 1

    assert result.returncode == 0, (
        f"écrire la ligne et committer DOIT sortir de l'impasse :\n{result.stdout}{result.stderr}"
    )
    assert apres == avant + 1


def test_gate_blocks_violations_with_prepare_commit_msg_hook(tmp_path: pathlib.Path) -> None:
    """Verrou GREEN : avec prepare-commit-msg, la porte s'exécute et bloque les violations.

    MERGE_HEAD est présent quand prepare-commit-msg fire → guard laisse passer → script tourne →
    dette portée au plafond (`MAX_UNDECLARED`) → la fusion suivante est bloquée. Ce test prouve
    le CORRECTIF.
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
