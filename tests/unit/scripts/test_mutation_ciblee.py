"""Le harnais qui verifie que les tests MORDENT — verifie a son tour.

CE QUE CE FICHIER VERROUILLE. `scripts/mutation_ciblee.py` abime volontairement des lignes de
production pour voir si la suite s'en apercoit. Trois de ses proprietes ne sont pas negociables,
et chacune a son test ici :

1. il ne mute que du CODE — un `==` dans une chaine ou un `and` dans un commentaire produirait un
   mutant qu'aucun test ne peut tuer, donc un faux survivant, et un rapport de faux survivants ne
   se lit plus ;
2. il mute UNE occurrence a la fois, reperee par ligne ET colonne ;
3. il RESTAURE le fichier, meme quand les tests plantent — un mutant laisse dans l'arbre serait
   pire que tout ce que le harnais mesure.

Le test central est `test_un_mutant_survit_quand_le_test_ne_regarde_pas` : il met en scene le
defaut que l'outil existe pour trouver — un test vert qui ne verifie pas ce qu'il pretend.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import mutation_ciblee as mc  # noqa: E402


# --------------------------------------------------------------------------- lecture du diff


DIFF = """diff --git a/engine/foo.py b/engine/foo.py
index 111..222 100644
--- a/engine/foo.py
+++ b/engine/foo.py
@@ -10,0 +11,2 @@ def f():
+    if a < b:
+        return True
diff --git a/tests/unit/engine/test_foo.py b/tests/unit/engine/test_foo.py
--- a/tests/unit/engine/test_foo.py
+++ b/tests/unit/engine/test_foo.py
@@ -5,0 +6 @@
+    assert f() is True
"""


def test_seules_les_lignes_ajoutees_sont_retenues() -> None:
    touches = mc.lignes_modifiees(DIFF)

    assert touches["engine/foo.py"] == {11, 12}
    assert touches["tests/unit/engine/test_foo.py"] == {6}


def test_une_ligne_supprimee_ne_produit_aucune_cible() -> None:
    """Il n'y a rien a muter dans une ligne qui n'existe plus."""
    diff = (
        "--- a/engine/foo.py\n+++ b/engine/foo.py\n"
        "@@ -10,2 +10,0 @@\n-    if a < b:\n-        return True\n"
    )
    assert mc.lignes_modifiees(diff).get("engine/foo.py", set()) == set()


@pytest.mark.parametrize(
    "fichier, attendu",
    [
        ("engine/foo.py", True),
        ("ai/train.py", True),
        ("services/api_server.py", True),
        ("shared/json_atomic.py", True),
        # Muter un test ne dit rien de la qualite des tests : il se testerait lui-meme.
        ("tests/unit/engine/test_foo.py", False),
        ("frontend/src/utils/a.ts", False),
        ("config/agents/x.json", False),
        ("Documentation/x.md", False),
    ],
)
def test_le_perimetre_est_le_code_de_production(fichier: str, attendu: bool) -> None:
    assert mc.dans_le_perimetre(fichier) is attendu


# --------------------------------------------------------------------------- generation


def _ecris(tmp_path: Path, nom: str, contenu: str) -> Path:
    chemin = tmp_path / nom
    chemin.write_text(contenu, encoding="utf-8")
    return chemin


def test_les_operateurs_de_comparaison_sont_mutes(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mc, "RACINE", tmp_path)
    source = _ecris(tmp_path, "m.py", "def f(a, b):\n    return a < b\n")

    mutants = mc.mutants_du_fichier(source, [2])

    assert {m.apres for m in mutants} == {"<=", ">"}
    assert all(m.ligne == 2 and m.avant == "<" for m in mutants)


def test_les_booleens_et_les_mots_cles_sont_mutes(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mc, "RACINE", tmp_path)
    source = _ecris(tmp_path, "m.py", "def f(a, b):\n    return a and b\n")

    assert [m.apres for m in mc.mutants_du_fichier(source, [2])] == ["or"]


def test_une_chaine_et_un_commentaire_ne_sont_pas_du_code(tmp_path, monkeypatch) -> None:
    """LE faux positif a ne pas produire : un mutant qu'aucun test ne peut tuer.

    Sans tokenisation, une expression reguliere sur la ligne muterait le `==` de la chaine et le
    `and` du commentaire — deux survivants garantis, qui rendraient le rapport illisible.
    """
    monkeypatch.setattr(mc, "RACINE", tmp_path)
    source = _ecris(
        tmp_path, "m.py",
        'def f():\n    message = "a == b and c"  # a and b, a == b\n    return message\n',
    )

    assert mc.mutants_du_fichier(source, [2]) == []


def test_seules_les_lignes_du_diff_sont_mutees(tmp_path, monkeypatch) -> None:
    """Le ciblage EST la raison d'etre du script : une campagne complete ne serait jamais lancee."""
    monkeypatch.setattr(mc, "RACINE", tmp_path)
    source = _ecris(tmp_path, "m.py", "def f(a, b):\n    x = a < b\n    y = a > b\n    return x, y\n")

    mutants = mc.mutants_du_fichier(source, [3])

    assert {m.ligne for m in mutants} == {3}


def test_une_seule_occurrence_est_mutee_a_la_fois(tmp_path, monkeypatch) -> None:
    """Deux defauts a la fois ne se diagnostiquent pas, et un test qui n'en tue qu'un ferait
    passer le couple pour mort."""
    monkeypatch.setattr(mc, "RACINE", tmp_path)
    source = _ecris(tmp_path, "m.py", "def f(a, b, c, d):\n    return a < b and c < d\n")
    contenu = source.read_text(encoding="utf-8")

    premier = [m for m in mc.mutants_du_fichier(source, [2]) if m.avant == "<"][0]
    mute = mc.applique(contenu, premier)

    # Comparaison de la ligne ENTIERE : compter les `<` ne dirait rien, `<=` en contient un.
    assert mute == "def f(a, b, c, d):\n    return a <= b and c < d\n", (
        f"la seconde comparaison a bouge elle aussi : {mute}"
    )


def test_appliquer_un_mutant_perime_leve(tmp_path, monkeypatch) -> None:
    """Le fichier a change depuis la generation : muter a l'aveugle abimerait autre chose."""
    monkeypatch.setattr(mc, "RACINE", tmp_path)
    mutant = mc.Mutant("m.py", 1, 9, "<", "<=")

    with pytest.raises(ValueError, match="a change depuis"):
        mc.applique("x = a > b\n", mutant)


# --------------------------------------------------------------------------- choix des tests


def test_les_tests_du_diff_et_ceux_du_nommage_sont_cumules(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mc, "RACINE", tmp_path)
    (tmp_path / "tests" / "unit" / "engine").mkdir(parents=True)
    (tmp_path / "tests" / "unit" / "engine" / "test_foo.py").write_text("", encoding="utf-8")
    (tmp_path / "tests" / "unit" / "engine" / "test_foo_bis.py").write_text("", encoding="utf-8")
    (tmp_path / "tests" / "unit" / "engine" / "test_autre.py").write_text("", encoding="utf-8")

    candidats = mc.tests_candidats("engine/foo.py", ["tests/unit/engine/test_autre.py"])

    assert candidats[0] == "tests/unit/engine/test_autre.py", "le test du diff passe en premier"
    assert "tests/unit/engine/test_foo.py" in candidats
    assert "tests/unit/engine/test_foo_bis.py" in candidats


def test_aucun_test_candidat_est_un_resultat_pas_une_erreur(tmp_path, monkeypatch) -> None:
    """Un fichier que rien ne relie a un test : c'est precisement ce qu'on veut apprendre."""
    monkeypatch.setattr(mc, "RACINE", tmp_path)
    assert mc.tests_candidats("engine/orphelin.py", []) == []


# --------------------------------------------------------------------------- cycle complet


MODULE = "def seuil_atteint(valeur):\n    return valeur > 10\n"

TEST_QUI_MORD = (
    "from m import seuil_atteint\n"
    "def test_borne():\n"
    "    assert seuil_atteint(11) is True\n"
    "    assert seuil_atteint(10) is False\n"
)

TEST_QUI_NE_MORD_PAS = (
    "from m import seuil_atteint\n"
    "def test_borne():\n"
    "    assert seuil_atteint(11) is True\n"
)


def _bac_a_sable(tmp_path: Path, test_source: str) -> None:
    (tmp_path / "m.py").write_text(MODULE, encoding="utf-8")
    (tmp_path / "test_m.py").write_text(test_source, encoding="utf-8")


def test_un_mutant_est_tue_quand_le_test_regarde_la_borne(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mc, "RACINE", tmp_path)
    _bac_a_sable(tmp_path, TEST_QUI_MORD)
    mutant = [m for m in mc.mutants_du_fichier(tmp_path / "m.py", [2]) if m.apres == ">="][0]

    assert mc.evalue(mutant, ["test_m.py"], timeout=120) is True


def test_un_mutant_survit_quand_le_test_ne_regarde_pas(tmp_path, monkeypatch) -> None:
    """LE defaut que cet outil existe pour trouver.

    `seuil_atteint(11)` vaut True avec `> 10` comme avec `>= 10` : un test qui ne verifie que ce
    cas est vert, et le restera si la borne se decale. Il ne verrouille rien, et rien d'autre que
    la mutation ne le dit.
    """
    monkeypatch.setattr(mc, "RACINE", tmp_path)
    _bac_a_sable(tmp_path, TEST_QUI_NE_MORD_PAS)
    mutant = [m for m in mc.mutants_du_fichier(tmp_path / "m.py", [2]) if m.apres == ">="][0]

    assert mc.evalue(mutant, ["test_m.py"], timeout=120) is False


def test_le_fichier_est_restaure_apres_la_mutation(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mc, "RACINE", tmp_path)
    _bac_a_sable(tmp_path, TEST_QUI_MORD)
    mutant = mc.mutants_du_fichier(tmp_path / "m.py", [2])[0]

    mc.evalue(mutant, ["test_m.py"], timeout=120)

    assert (tmp_path / "m.py").read_text(encoding="utf-8") == MODULE


def test_le_fichier_est_restaure_meme_si_les_tests_explosent(tmp_path, monkeypatch) -> None:
    """La restauration est dans un `finally` : une exception ne doit pas laisser un mutant."""
    monkeypatch.setattr(mc, "RACINE", tmp_path)
    _bac_a_sable(tmp_path, TEST_QUI_MORD)
    mutant = mc.mutants_du_fichier(tmp_path / "m.py", [2])[0]

    def _explose(*_args, **_kwargs):
        raise OSError("pytest introuvable")

    monkeypatch.setattr(mc, "joue_les_tests", _explose)

    with pytest.raises(OSError):
        mc.evalue(mutant, ["test_m.py"], timeout=120)

    assert (tmp_path / "m.py").read_text(encoding="utf-8") == MODULE


def test_le_pycache_est_purge_autour_de_chaque_mutation(tmp_path, monkeypatch) -> None:
    """Un `.pyc` compile depuis le mutant survivrait a la restauration et serait rejoue.

    Mesure connue du depot : une mutation de MEME LONGUEUR restauree laisse Python executer le
    mutant tant que le cache n'est pas purge.
    """
    monkeypatch.setattr(mc, "RACINE", tmp_path)
    _bac_a_sable(tmp_path, TEST_QUI_MORD)
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "m.cpython-312.pyc").write_bytes(b"perime")
    mutant = mc.mutants_du_fichier(tmp_path / "m.py", [2])[0]

    mc.evalue(mutant, ["test_m.py"], timeout=120)

    assert not (cache / "m.cpython-312.pyc").exists(), "le .pyc du mutant a survecu"


def test_la_purge_s_arrete_aux_dependances(tmp_path, monkeypatch) -> None:
    """`.venv` ne contient aucun mutant, et le balayer coute plus cher que tout le reste.

    Mesure du 2026-09-09 : 539 `__pycache__` dans `.venv` contre 35 dans le depot. Les purger
    faisait recompiler torch, SB3 et numpy DEUX fois par mutant — devant chacun des quarante
    pytest — et laissait le venv nu a la fin du run.
    """
    monkeypatch.setattr(mc, "RACINE", tmp_path)
    depot = tmp_path / "engine" / "__pycache__"
    depot.mkdir(parents=True)
    (depot / "a.pyc").write_bytes(b"x")
    for abri in mc.HORS_PURGE:
        cache = tmp_path / abri / "paquet" / "__pycache__"
        cache.mkdir(parents=True)
        (cache / "b.pyc").write_bytes(b"x")

    mc.purge_pycache(tmp_path)

    assert not depot.exists(), "le cache du depot n'a pas ete purge"
    for abri in mc.HORS_PURGE:
        assert (tmp_path / abri / "paquet" / "__pycache__" / "b.pyc").exists(), (
            f"{abri} a ete purge : recompilation inutile devant chaque mutant"
        )


def test_un_depassement_de_delai_compte_le_mutant_comme_tue(tmp_path, monkeypatch) -> None:
    """Muter une comparaison peut rendre une boucle infinie — c'est meme un defaut recherche.

    Sans capture, `subprocess.TimeoutExpired` sortait du script en traceback : plus de
    recapitulatif, et aucun verdict pour les mutants suivants. Un rapport entier perdu a cause
    d'un mutant qui, lui, est correctement detecte.
    """
    monkeypatch.setattr(mc, "RACINE", tmp_path)

    def _expire(*args, **kwargs):
        raise mc.subprocess.TimeoutExpired(cmd="pytest", timeout=1)

    monkeypatch.setattr(mc.subprocess, "run", _expire)

    assert mc.joue_les_tests(["test_m.py"], timeout=1) is False, (
        "un depassement doit compter comme un mutant TUE, pas interrompre la campagne"
    )
