"""`assert_worktree` doit refuser le depot PRINCIPAL, y compris quand le banc en est lance.

Bug d'origine : le depot principal etait defini comme le parent du SCRIPT EXECUTE
(`os.path.dirname(os.path.abspath(__file__))`). Or le banc vit dans le depot, donc le lancer
depuis le worktree — le cas d'usage normal — faisait valoir `main_repo` = worktree. Un
`--repo <depot principal>` differait alors de cette reference et PASSAIT : le banc entrainait
dans le depot principal et ecrasait `ai/models/<agent>/model_<agent>.zip`, le fichier que le
message d'erreur dit proteger. Un garde-fou qui autorise exactement ce qu'il interdit.

Le controle interroge desormais git sur la CIBLE (`--absolute-git-dir` vs `--git-common-dir`,
distincts dans un worktree lie, identiques dans le depot principal) au lieu de la comparer a
une reference deduite de sa propre position.

Les tests construisent de vrais depots git et un vrai worktree : la propriete testee est une
propriete de git, la simuler ne prouverait rien.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   capture_output=True, text=True)


@pytest.fixture
def repo_and_worktree(tmp_path: Path):
    """Un vrai depot principal + un vrai worktree lie."""
    main = tmp_path / "main"
    main.mkdir()
    _git("init", "-q", "-b", "main", cwd=main)
    _git("config", "user.email", "t@t.t", cwd=main)
    _git("config", "user.name", "t", cwd=main)
    (main / "f.txt").write_text("x", encoding="utf-8")
    _git("add", "f.txt", cwd=main)
    _git("commit", "-qm", "init", cwd=main)
    wt = tmp_path / "wt"
    _git("worktree", "add", "-q", str(wt), "HEAD", cwd=main)
    assert (wt / "f.txt").exists(), "le worktree n'a pas ete cree : test vacant"
    return main, wt


def test_main_repo_is_refused(repo_and_worktree) -> None:
    """Le cas nominal : --repo pointe le depot principal."""
    from ab_train_common import assert_worktree

    main, _ = repo_and_worktree
    with pytest.raises(SystemExit, match="depot principal"):
        assert_worktree(str(main), "AnyAgent")


def test_worktree_is_accepted(repo_and_worktree) -> None:
    """Contrepartie : refuser TOUT ferait passer le test precedent sans rien proteger."""
    from ab_train_common import assert_worktree

    _, wt = repo_and_worktree
    assert assert_worktree(str(wt), "AnyAgent") == os.path.realpath(str(wt))


def test_main_repo_refused_even_when_launched_from_the_worktree(
    repo_and_worktree, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LE contournement d'origine : cwd dans le worktree, --repo sur le principal. ROUGE avant."""
    from ab_train_common import assert_worktree

    main, wt = repo_and_worktree
    monkeypatch.chdir(wt)
    with pytest.raises(SystemExit, match="depot principal"):
        assert_worktree(str(main), "AnyAgent")


def test_symlink_to_main_repo_is_refused(repo_and_worktree, tmp_path: Path) -> None:
    """Un lien symbolique vers le principal ne doit pas ouvrir une porte derobee."""
    from ab_train_common import assert_worktree

    main, _ = repo_and_worktree
    link = tmp_path / "link"
    link.symlink_to(main)
    with pytest.raises(SystemExit, match="depot principal"):
        assert_worktree(str(link), "AnyAgent")


def test_non_git_directory_is_refused(tmp_path: Path) -> None:
    """Ne pas pouvoir conclure = refuser. Un dossier hors git ne doit pas passer."""
    from ab_train_common import assert_worktree

    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(SystemExit):
        assert_worktree(str(plain), "AnyAgent")


def test_missing_directory_is_refused(tmp_path: Path) -> None:
    from ab_train_common import assert_worktree

    with pytest.raises(SystemExit, match="absent"):
        assert_worktree(str(tmp_path / "nope"), "AnyAgent")
