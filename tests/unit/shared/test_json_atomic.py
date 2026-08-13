"""Verrou de `shared/json_atomic.py` — l'écriture JSON atomique du dépôt.

Le défaut couvert : `open(path, "w")` DÉTRUIT le fichier précédent à l'ouverture, avant le
premier octet écrit. Une interruption à mi-écriture laissait donc un JSON tronqué à la place
d'un relevé valide — perte silencieuse, constatée seulement à la relecture suivante.

Deux comportements sont verrouillés partout, et ce sont eux que le prompt d'ouverture nomme :
  1. le fichier PRÉCÉDENT reste intact quand l'écriture rate, quelle qu'en soit la cause ;
  2. aucun brouillon ne survit — ni sur erreur, ni sur succès.

Un troisième verrou est STATIQUE (`test_aucune_publication_json_en_direct`) : sans lui, les deux
premiers ne prouveraient que le module, et un fichier qui réintroduirait son propre `_write_json`
privé — le point de départ de ce chantier — les laisserait tous verts. Il BALAYE les cinq arbres
de code au lieu de suivre une liste de fichiers convertis : une liste ne couvre pas le fichier
qui sera écrit demain, et c'est justement là que le défaut revient.
"""
from __future__ import annotations

import ast
import json
import os
import threading
from pathlib import Path

import pytest

from shared.json_atomic import dump_json, json_draft, json_out_draft, part_path, write_json_atomic

PROJECT_ROOT = Path(__file__).resolve().parents[3]

#: Les arbres de code balayés par le verrou statique. `tests/` en est exclu : un test qui pose un
#: JSON de travail dans son `tmp_path` ne publie rien — il n'y a pas de fichier précédent à
#: protéger, et l'écriture directe y est la forme lisible.
ARBRES = ("scripts", "ai", "engine", "services", "shared")

#: Fichiers autorisés à écrire un JSON sans passer par le module, avec la raison. Toute entrée
#: doit exister (vérifié) : une exclusion périmée masquerait un vrai site.
EXCLUS = {
    "shared/json_atomic.py": "l'implémentation : c'est elle qui ouvre le brouillon et le publie",
}

#: Modes d'ouverture qui DÉTRUISENT la destination. `"a"` en est absent exprès : un journal en
#: append (`.jsonl` de `scripts/ab_sweep_nenvs.py`, `ai/truncation_log.py`) n'écrase rien, il
#: n'a donc pas de fichier précédent à perdre — le convertir n'aurait aucun sens.
MODES_DESTRUCTIFS = ("w", "x")


def _boom_payload() -> dict:
    """Payload qui casse EN COURS de sérialisation : `json.dump` écrit en flux, donc le début
    est déjà parti dans le brouillon quand le `TypeError` tombe. C'est exactement la situation
    du disque plein ou du Ctrl-C — une écriture à moitié faite, pas une écriture refusée.
    """
    return {"debut": "x" * 200, "fin": object()}


# --- 1. le fichier précédent survit -----------------------------------------------------------

def test_write_json_atomic_laisse_le_fichier_precedent_intact_si_l_ecriture_casse(tmp_path):
    cible = tmp_path / "releve.json"
    cible.write_text('{"ancien": true}\n', encoding="utf-8")

    with pytest.raises(TypeError):
        write_json_atomic(cible, _boom_payload())

    assert json.loads(cible.read_text(encoding="utf-8")) == {"ancien": True}
    assert [p.name for p in tmp_path.iterdir()] == ["releve.json"]


def test_json_out_draft_laisse_le_fichier_precedent_intact_si_le_travail_est_interrompu(tmp_path):
    cible = tmp_path / "releve.json"
    cible.write_text('{"ancien": true}\n', encoding="utf-8")

    with pytest.raises(KeyboardInterrupt):
        with json_out_draft(cible) as handle:
            assert handle is not None
            handle.write('{"moiti')  # relevé à moitié écrit, comme un Ctrl-C en plein run
            raise KeyboardInterrupt

    assert json.loads(cible.read_text(encoding="utf-8")) == {"ancien": True}
    assert [p.name for p in tmp_path.iterdir()] == ["releve.json"]


# --- 2. aucun brouillon résiduel ---------------------------------------------------------------

def test_aucun_residu_apres_une_ecriture_reussie(tmp_path):
    cible = tmp_path / "releve.json"

    write_json_atomic(cible, {"ok": [1, 2]})

    assert json.loads(cible.read_text(encoding="utf-8")) == {"ok": [1, 2]}
    assert [p.name for p in tmp_path.iterdir()] == ["releve.json"]


def test_la_destination_dossier_est_refusee_avant_d_ouvrir_quoi_que_ce_soit(tmp_path):
    # le brouillon s'ouvrirait très bien ici : c'est le `os.replace` FINAL qui casserait, après
    # tout le travail. Le cas se refuse donc à l'ouverture, pas à la publication.
    cible = tmp_path / "releve"
    cible.mkdir()

    with pytest.raises(IsADirectoryError):
        write_json_atomic(cible, {"ok": True})
    with pytest.raises(IsADirectoryError):
        with json_out_draft(cible):
            pass

    assert [p.name for p in tmp_path.iterdir()] == ["releve"]


def test_une_destination_vide_est_refusee_sans_rien_ecrire(tmp_path, monkeypatch):
    # `--json-out "$VAR"` avec VAR non définie : sans ce refus, le brouillon atterrit dans le cwd
    # (la racine du dépôt en usage réel) et seul le `os.replace` final casse, après le travail.
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError):
        write_json_atomic("", {"ok": True})
    with pytest.raises(ValueError):
        with json_out_draft(""):
            pass

    assert list(tmp_path.iterdir()) == []


def test_une_fermeture_qui_rate_ne_publie_pas_et_ne_masque_rien(tmp_path):
    # disque plein au flush : le contenu est incomplet, donc rien ne doit être publié, et
    # l'exception d'origine doit rester celle qu'on lit.
    cible = tmp_path / "releve.json"
    cible.write_text('{"ancien": true}\n', encoding="utf-8")

    class _CloseKO(OSError):
        pass

    with pytest.raises(KeyboardInterrupt):
        with json_out_draft(cible) as handle:
            assert handle is not None
            handle.close = lambda: (_ for _ in ()).throw(_CloseKO("ENOSPC"))
            raise KeyboardInterrupt

    assert json.loads(cible.read_text(encoding="utf-8")) == {"ancien": True}
    assert [p.name for p in tmp_path.iterdir()] == ["releve.json"]


def test_une_fermeture_qui_rate_en_sortie_normale_ne_publie_pas(tmp_path):
    # le flush casse alors que le corps s'est terminé SANS erreur : c'est le cas où un `close()`
    # hors du `try` publierait un fichier tronqué, ou laisserait le brouillon derrière lui.
    cible = tmp_path / "releve.json"
    cible.write_text('{"ancien": true}\n', encoding="utf-8")

    with pytest.raises(OSError):
        with json_out_draft(cible) as handle:
            assert handle is not None
            handle.close = lambda: (_ for _ in ()).throw(OSError("ENOSPC"))

    assert json.loads(cible.read_text(encoding="utf-8")) == {"ancien": True}
    assert [p.name for p in tmp_path.iterdir()] == ["releve.json"]


def test_un_dossier_absent_n_est_pas_cree_en_silence(tmp_path):
    # pas de `mkdir(parents=True)` implicite : un chemin faux doit se voir, pas se réparer.
    with pytest.raises(FileNotFoundError):
        write_json_atomic(tmp_path / "absent" / "releve.json", {"ok": True})

    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root écrit dans un dossier en lecture seule")
def test_un_dossier_en_lecture_seule_casse_a_l_ouverture(tmp_path):
    # motif de l'ouverture RÉELLE plutôt que d'un `isdir` : un dossier existant mais non
    # inscriptible passerait un test d'existence et casserait à la toute fin.
    readonly = tmp_path / "ro"
    readonly.mkdir()
    readonly.chmod(0o500)
    try:
        with pytest.raises(PermissionError):
            write_json_atomic(readonly / "releve.json", {"ok": True})
    finally:
        readonly.chmod(0o700)


def test_deux_ecrivains_concurrents_ne_partagent_pas_le_brouillon(tmp_path):
    # le cas mesuré : `services/api_server.py` publie `save_config.json` depuis deux routes
    # Flask, servies en fils concurrents. Avec un brouillon COMMUN, le second écrivain tronque
    # celui du premier, et la publication du premier reprend le contenu du second. Ici, le
    # second écrit et publie pendant que le premier tient encore son brouillon ouvert.
    cible = tmp_path / "config.json"
    brouillon_du_fil: list[str] = []

    def _second() -> None:
        with json_out_draft(cible) as second:
            assert second is not None
            brouillon_du_fil.append(part_path(cible))
            dump_json(second, {"ecrivain": 2})

    with json_out_draft(cible) as premier:
        assert premier is not None
        brouillon_du_principal = part_path(cible)
        dump_json(premier, {"ecrivain": 1})

        fil = threading.Thread(target=_second)
        fil.start()
        fil.join()

        assert brouillon_du_fil == [brouillon_du_principal.replace(
            str(threading.main_thread().ident), str(fil.ident)
        )]
        assert brouillon_du_fil[0] != brouillon_du_principal
        # le fil a publié SA version, et le brouillon du principal a survécu intact.
        assert json.loads(cible.read_text(encoding="utf-8")) == {"ecrivain": 2}
        assert Path(brouillon_du_principal).exists()

    # la publication du principal écrase celle du fil avec SON contenu, pas avec un mélange.
    assert json.loads(cible.read_text(encoding="utf-8")) == {"ecrivain": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["config.json"]


# --- forme et contrat d'appel ------------------------------------------------------------------

def test_le_format_ecrit_est_celui_du_depot(tmp_path):
    # la forme commune : indent 2, UTF-8 littéral, retour à la ligne final.
    cible = tmp_path / "releve.json"

    write_json_atomic(cible, {"nom": "Escouade d'Assaut", "n": 2})

    assert cible.read_text(encoding="utf-8") == '{\n  "nom": "Escouade d\'Assaut",\n  "n": 2\n}\n'


def test_un_producteur_garde_sa_propre_forme_dans_le_brouillon(tmp_path):
    # l'autre moitié du contrat : l'atomicité SANS le format du dépôt, pour les sorties dont la
    # forme est imposée ailleurs (table compacte lue par le moteur, cache avec `default=str`).
    cible = tmp_path / "table.json"

    with json_draft(cible) as handle:
        json.dump({"b": 1, "a": 2}, handle, separators=(",", ":"), sort_keys=True)

    assert cible.read_text(encoding="utf-8") == '{"a":2,"b":1}'


def test_str_et_path_donnent_le_meme_resultat(tmp_path):
    # les scripts migrés manipulent des `Path`, `bot_zone_direct` un `str` d'argparse.
    write_json_atomic(str(tmp_path / "a.json"), {"v": 1})
    write_json_atomic(tmp_path / "b.json", {"v": 1})

    assert (tmp_path / "a.json").read_text(encoding="utf-8") == (tmp_path / "b.json").read_text(encoding="utf-8")
    assert part_path(tmp_path / "a.json").startswith(str(tmp_path / "a.json") + ".")
    assert part_path(tmp_path / "a.json").endswith(".part")


def test_sans_destination_aucun_fichier_n_est_touche(tmp_path, monkeypatch):
    # le cwd EST tmp_path : un brouillon écrit « quelque part » se verrait ici.
    monkeypatch.chdir(tmp_path)

    with json_out_draft(None) as handle:
        assert handle is None

    assert list(tmp_path.iterdir()) == []


def test_dump_json_ecrit_dans_le_brouillon_pas_dans_la_destination(tmp_path):
    # ce que `bot_zone_direct` fait vraiment : le brouillon est ouvert AVANT le travail, la
    # destination n'existe pas encore pendant qu'on écrit dedans.
    cible = tmp_path / "releve.json"

    with json_out_draft(cible) as handle:
        assert handle is not None
        dump_json(handle, {"episodes": [1]})
        assert not cible.exists()
        assert Path(part_path(cible)).exists()

    assert json.loads(cible.read_text(encoding="utf-8")) == {"episodes": [1]}


# --- 3. verrou statique : plus aucune publication JSON en direct --------------------------------


def _mode_douverture(node: ast.Call) -> str:
    """Mode d'un `open(...)` / `X.open(...)`, `"r"` par défaut comme la bibliothèque standard."""
    for mot in node.keywords:
        if mot.arg == "mode" and isinstance(mot.value, ast.Constant):
            return str(mot.value.value)
    # `open(chemin, mode)` pour la fonction native, `chemin.open(mode)` pour la méthode de Path.
    rang = 1 if isinstance(node.func, ast.Name) else 0
    if len(node.args) > rang and isinstance(node.args[rang], ast.Constant):
        return str(node.args[rang].value)
    return "r"


def _est_ouverture_destructive(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    nomme_open = (isinstance(func, ast.Name) and func.id == "open") or (
        isinstance(func, ast.Attribute) and func.attr == "open"
    )
    if not nomme_open:
        return False
    return any(lettre in _mode_douverture(node) for lettre in MODES_DESTRUCTIFS)


_PORTEURS_DE_PORTEE = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)


def _portees(tree: ast.AST) -> list[list[ast.AST]]:
    """Le module et chaque fonction, chacun avec SES noeuds — sans ceux des fonctions imbriquées.

    Le nom d'un handle ne vaut que dans sa fonction : `f` ouvert en `"w"` dans un écrivain CSV
    et `f` ouvert en `"a"` dans un journal cohabitent dans le même fichier (mesuré sur
    `scripts/aggregate_seed_results.py`). Un ensemble de noms tenu au niveau du MODULE ferait
    passer le second pour le premier — un faux positif qu'on ne peut pas corriger sans casser
    le vrai cas.
    """
    resultat: list[list[ast.AST]] = []
    for porteur in [tree] + [n for n in ast.walk(tree) if isinstance(n, _PORTEURS_DE_PORTEE) and n is not tree]:
        propres: list[ast.AST] = []
        pile: list[ast.AST] = list(ast.iter_child_nodes(porteur))
        while pile:
            node = pile.pop()
            propres.append(node)
            if not isinstance(node, _PORTEURS_DE_PORTEE):
                pile.extend(ast.iter_child_nodes(node))
        resultat.append(propres)
    return resultat


def _blocs_brouillon(noeuds: list[ast.AST]) -> list[tuple[str, int, int]]:
    """`with json_out_draft(...) as X:` — le nom, et les lignes où il désigne un brouillon.

    Une même fonction peut lier `f` à un fichier CSV ouvert en `"w"` PUIS à un brouillon (mesuré
    sur `scripts/unit_classifier.py`, qui écrit une matrice et un CSV dans `main()`). C'est la
    ligne du `json.dump`, pas le nom seul, qui dit lequel des deux il vise.
    """
    blocs = []
    for node in noeuds:
        if not isinstance(node, ast.With):
            continue
        for item in node.items:
            appel = item.context_expr
            nom_appele = ""
            if isinstance(appel, ast.Call):
                if isinstance(appel.func, ast.Name):
                    nom_appele = appel.func.id
                elif isinstance(appel.func, ast.Attribute):
                    nom_appele = appel.func.attr
            nomme_brouillon = nom_appele in {"json_draft", "json_out_draft"}
            if nomme_brouillon and isinstance(item.optional_vars, ast.Name):
                blocs.append((item.optional_vars.id, node.lineno, node.end_lineno or node.lineno))
    return blocs


def _handles_destructifs(noeuds: list[ast.AST]) -> set[str]:
    """Noms liés à un fichier ouvert en écrasement — les seuls qui peuvent perdre un précédent."""
    noms: set[str] = set()
    for node in noeuds:
        if isinstance(node, ast.With):
            for item in node.items:
                if _est_ouverture_destructive(item.context_expr) and isinstance(item.optional_vars, ast.Name):
                    noms.add(item.optional_vars.id)
        elif isinstance(node, ast.Assign) and _est_ouverture_destructive(node.value):
            noms.update(cible.id for cible in node.targets if isinstance(cible, ast.Name))
    return noms


def _est_json_dumps(node: ast.AST) -> bool:
    """`json.dumps(...)` écrit TEL QUEL — éventuellement concaténé à un `"\\n"`.

    Volontairement aveugle à `json.dumps(...)` glissé dans une f-string ou suivi de `.encode()` :
    un message de log ou un corps de requête HTTP ne publie pas de fichier.
    """
    if isinstance(node, ast.BinOp):
        return _est_json_dumps(node.left) or _est_json_dumps(node.right)
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "dumps"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "json"
    )


def publications_directes(source: str) -> list[str]:
    """Les endroits de `source` qui publient un JSON à même sa destination, sans brouillon."""
    fautifs: list[str] = []
    for noeuds in _portees(ast.parse(source)):
        handles = _handles_destructifs(noeuds)
        brouillons = _blocs_brouillon(noeuds)

        def _vise_un_brouillon(nom: str, ligne: int) -> bool:
            return any(n == nom and debut <= ligne <= fin for n, debut, fin in brouillons)

        for node in noeuds:
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            func = node.func
            cible_json = isinstance(func.value, ast.Name) and func.value.id == "json"
            if func.attr == "dump" and cible_json and len(node.args) > 1:
                destination = node.args[1]
                vise_un_fichier = (
                    isinstance(destination, ast.Name)
                    and destination.id in handles
                    and not _vise_un_brouillon(destination.id, node.lineno)
                ) or _est_ouverture_destructive(destination)
                if vise_un_fichier:
                    fautifs.append(f"json.dump() ligne {node.lineno}")
            elif func.attr == "write_text" and any(_est_json_dumps(a) for a in node.args):
                fautifs.append(f"write_text(json.dumps()) ligne {node.lineno}")
            elif (
                func.attr == "write"
                and isinstance(func.value, ast.Name)
                and func.value.id in handles
                and not _vise_un_brouillon(func.value.id, node.lineno)
                and any(_est_json_dumps(a) for a in node.args)
            ):
                fautifs.append(f"write(json.dumps()) ligne {node.lineno}")
    return sorted(set(fautifs))


def _fichiers_balayes() -> list[str]:
    trouves = []
    for arbre in ARBRES:
        for chemin in sorted((PROJECT_ROOT / arbre).rglob("*.py")):
            relatif = chemin.relative_to(PROJECT_ROOT).as_posix()
            if relatif not in EXCLUS:
                trouves.append(relatif)
    return trouves


@pytest.mark.parametrize("relative", _fichiers_balayes())
def test_aucune_publication_json_en_direct(relative: str) -> None:
    source = (PROJECT_ROOT / relative).read_text(encoding="utf-8")

    fautifs = publications_directes(source)

    assert not fautifs, (
        f"{relative} publie un JSON à même sa destination ({', '.join(fautifs)}) : une "
        "interruption y laisserait un JSON tronqué à la place du fichier précédent. Passer par "
        "`shared.json_atomic.write_json_atomic`, ou par `json_draft` si la forme écrite "
        "doit rester celle du site."
    )


def test_le_balayage_couvre_reellement_les_arbres_de_code() -> None:
    # VERT VACANT : une énumération qui ne rend rien rendrait le verrou vert partout. On vérifie
    # qu'elle voit chacun des cinq arbres, et un fichier connu qui publie du JSON.
    balayes = _fichiers_balayes()

    assert len(balayes) > 100
    for arbre in ARBRES:
        assert any(f.startswith(f"{arbre}/") for f in balayes), f"{arbre} n'est pas balayé"
    assert "scripts/build_holdout_benchmark.py" in balayes


def test_les_exclusions_existent_toutes() -> None:
    # une exclusion périmée (fichier renommé, supprimé) masquerait un vrai site sans rien dire.
    for relatif in EXCLUS:
        assert (PROJECT_ROOT / relatif).exists(), f"exclusion périmée : {relatif}"


def test_le_verrou_voit_les_publications_et_ignore_ce_qui_n_en_est_pas() -> None:
    # VERT VACANT, l'autre face : un analyseur devenu aveugle rendrait une liste vide, donc
    # VERTE sur les 138 fichiers. Les deux moitiés comptent — ce qu'il doit attraper, et ce
    # qu'il ne doit PAS attraper, sinon le verrou devient impossible à garder vert.
    fautif = (
        "import json\n"
        "from pathlib import Path\n"
        "def a(p, d):\n"
        "    Path(p).write_text(json.dumps(d))\n"
        "def b(p, d):\n"
        "    with open(p, 'w') as f:\n"
        "        json.dump(d, f)\n"
        "def c(p, d):\n"
        "    with p.open('w', encoding='utf-8') as f:\n"
        "        json.dump(d, f, indent=2)\n"
        "def d_(p, d):\n"
        "    f = open(p, mode='w')\n"
        "    f.write(json.dumps(d) + '\\n')\n"
    )
    assert len(publications_directes(fautif)) == 4

    innocent = (
        "import csv, json, sys\n"
        "from pathlib import Path\n"
        "def journal(p, rec):\n"
        "    with open(p, 'a', encoding='utf-8') as f:\n"        # journal .jsonl en append
        "        f.write(json.dumps(rec) + '\\n')\n"
        "def texte(p, proc):\n"
        "    Path(p).write_text(proc.stdout, encoding='utf-8')\n"  # texte brut
        "def tableur(p, lignes):\n"
        "    with p.open('w', newline='') as f:\n"                # CSV
        "        csv.writer(f).writerows(lignes)\n"
        "def metrique(model, pas):\n"
        "    model.logger.dump(step=pas)\n"                       # logger SB3
        "def trace(f, d):\n"
        "    f.write(f'payload={json.dumps(d)}')\n"               # json dans un message de log
        "def http(d):\n"
        "    return json.dumps(d).encode()\n"                     # corps de requête
        "def console(d):\n"
        "    json.dump(d, sys.stdout, indent=2)\n"                # sortie standard
        "def deux_sorties(p, q, d, lignes):\n"                    # le cas d'unit_classifier :
        "    with q.open('w', newline='') as f:\n"                # même nom, deux liaisons
        "        csv.writer(f).writerows(lignes)\n"
        "    with json_draft(p) as f:\n"
        "        json.dump(d, f, sort_keys=True)\n"
        "def drapeau(p, d):\n"                                    # `--json-out` absent possible
        "    with json_out_draft(p) as f:\n"
        "        json.dump(d, f, indent=0)\n"
    )
    assert publications_directes(innocent) == []
