"""Verrou de `scripts/json_atomic.py` — l'écriture JSON atomique du dépôt.

Le défaut couvert : `open(path, "w")` DÉTRUIT le fichier précédent à l'ouverture, avant le
premier octet écrit. Une interruption à mi-écriture laissait donc un JSON tronqué à la place
d'un relevé valide — perte silencieuse, constatée seulement à la relecture suivante.

Deux comportements sont verrouillés partout, et ce sont eux que le prompt d'ouverture nomme :
  1. le fichier PRÉCÉDENT reste intact quand l'écriture rate, quelle qu'en soit la cause ;
  2. aucun résidu `.part` ne survit — ni sur erreur, ni sur succès.

Un troisième verrou est STATIQUE (`test_les_scripts_n_ecrivent_plus_de_json_en_direct`) : sans
lui, les deux premiers ne prouveraient que le module, et un script qui réintroduirait son propre
`_write_json` privé — le point de départ de ce chantier — les laisserait tous verts.
"""
from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import json_atomic  # noqa: E402  (le module lui-même : les tests d'ordre monkeypatchent ses `os.*`)
from json_atomic import dump_json, json_out_draft, part_path, write_json_atomic  # noqa: E402


def _leve(exc: BaseException):
    """Remplaçant d'un appel système qui casse — la panne se construit, elle ne s'espère pas."""
    def _ko(*_args, **_kwargs):
        raise exc
    return _ko

#: Les scripts dont l'écriture JSON doit passer par le module. Les quatre `_write_json` privés
#: d'origine : trois écrivaient à même la destination, le quatrième portait la forme retenue.
JSON_WRITERS = (
    "scripts/bot_zone_direct.py",
    "scripts/migrate_scenario_bank_v11.py",
    "scripts/build_holdout_benchmark.py",
    "scripts/rebalance_holdout_hard_scenarios.py",
)


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
    assert not (tmp_path / "releve.json.part").exists()


def test_json_out_draft_laisse_le_fichier_precedent_intact_si_le_travail_est_interrompu(tmp_path):
    cible = tmp_path / "releve.json"
    cible.write_text('{"ancien": true}\n', encoding="utf-8")

    with pytest.raises(KeyboardInterrupt):
        with json_out_draft(cible) as handle:
            assert handle is not None
            handle.write('{"moiti')  # relevé à moitié écrit, comme un Ctrl-C en plein run
            raise KeyboardInterrupt

    assert json.loads(cible.read_text(encoding="utf-8")) == {"ancien": True}
    assert not (tmp_path / "releve.json.part").exists()


# --- 2. aucun résidu .part ---------------------------------------------------------------------

def test_aucun_residu_part_apres_une_ecriture_reussie(tmp_path):
    cible = tmp_path / "releve.json"

    write_json_atomic(cible, {"ok": [1, 2]})

    assert json.loads(cible.read_text(encoding="utf-8")) == {"ok": [1, 2]}
    assert [p.name for p in tmp_path.iterdir()] == ["releve.json"]


def test_la_destination_dossier_est_refusee_avant_d_ouvrir_quoi_que_ce_soit(tmp_path):
    # le brouillon `.part` s'ouvrirait très bien ici : c'est le `os.replace` FINAL qui casserait,
    # après tout le travail. Le cas se refuse donc à l'ouverture, pas à la publication.
    cible = tmp_path / "releve"
    cible.mkdir()

    with pytest.raises(IsADirectoryError):
        write_json_atomic(cible, {"ok": True})
    with pytest.raises(IsADirectoryError):
        with json_out_draft(cible):
            pass

    assert [p.name for p in tmp_path.iterdir()] == ["releve"]


def test_une_destination_vide_est_refusee_sans_rien_ecrire(tmp_path, monkeypatch):
    # `--json-out "$VAR"` avec VAR non définie : sans ce refus, le `.part` atterrit dans le cwd
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
    assert not (tmp_path / "releve.json.part").exists()


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
    assert not (tmp_path / "releve.json.part").exists()


def test_une_publication_qui_rate_n_abandonne_pas_le_brouillon(tmp_path, monkeypatch):
    # TOCTOU : la destination est devenue un dossier / a perdu ses droits PENDANT un run long.
    # `os.replace` casse alors après coup ; sans ce nettoyage, un `.part` reste sous `config/`.
    cible = tmp_path / "releve.json"
    cible.write_text('{"ancien": true}\n', encoding="utf-8")
    monkeypatch.setattr(json_atomic.os, "replace", _leve(OSError("EPERM")))

    with pytest.raises(OSError):
        write_json_atomic(cible, {"neuf": True})

    assert json.loads(cible.read_text(encoding="utf-8")) == {"ancien": True}
    assert not (tmp_path / "releve.json.part").exists()


def test_un_brouillon_deja_disparu_ne_masque_pas_l_exception_d_origine(tmp_path, monkeypatch):
    # le ménage de la sortie en erreur est best-effort : c'est le Ctrl-C qui doit remonter, pas
    # le `FileNotFoundError` du brouillon qu'un nettoyeur de /tmp a emporté entre-temps.
    cible = tmp_path / "releve.json"
    monkeypatch.setattr(json_atomic.os, "remove", _leve(FileNotFoundError("déjà parti")))

    with pytest.raises(KeyboardInterrupt):
        with json_out_draft(cible) as handle:
            assert handle is not None
            raise KeyboardInterrupt


def test_les_donnees_sont_sur_le_disque_avant_la_publication(tmp_path, monkeypatch):
    # un `os.replace` durable AVANT ses données rend un fichier VIDE là où une config valide
    # tenait, après un crash hôte. L'ordre fsync -> replace est donc le verrou, et il n'est
    # observable que sur la séquence des appels.
    appels: list[str] = []
    vrai_fsync, vrai_replace = json_atomic.os.fsync, json_atomic.os.replace
    monkeypatch.setattr(json_atomic.os, "fsync", lambda fd: (appels.append("fsync"), vrai_fsync(fd))[1])
    monkeypatch.setattr(json_atomic.os, "replace", lambda a, b: (appels.append("replace"), vrai_replace(a, b))[1])

    write_json_atomic(tmp_path / "releve.json", {"ok": True})

    # fsync du brouillon, PUIS publication, PUIS fsync du dossier (qui rend le renommage durable)
    assert appels == ["fsync", "replace", "fsync"]


def test_un_fsync_de_dossier_impossible_n_annule_pas_une_publication_reussie(tmp_path, monkeypatch):
    # certains montages ne savent pas fsyncer un dossier (FUSE, réseau, overlay : EINVAL). La
    # publication, elle, a déjà eu lieu : remonter l'erreur ferait lire « rien n'a été écrit » à
    # un appelant qui a DÉJÀ supprimé la version précédente de ses autres fichiers, et il
    # abandonnerait la banque à moitié reconstruite.
    cible = tmp_path / "releve.json"
    monkeypatch.setattr(json_atomic.os, "open", _leve(OSError("EINVAL")))

    write_json_atomic(cible, {"neuf": True})

    assert json.loads(cible.read_text(encoding="utf-8")) == {"neuf": True}
    assert not (tmp_path / "releve.json.part").exists()


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


# --- forme et contrat d'appel ------------------------------------------------------------------

def test_le_format_ecrit_est_celui_du_depot(tmp_path):
    # une seule forme pour les quatre scripts : indent 2, UTF-8 littéral, retour à la ligne final.
    cible = tmp_path / "releve.json"

    write_json_atomic(cible, {"nom": "Escouade d'Assaut", "n": 2})

    assert cible.read_text(encoding="utf-8") == '{\n  "nom": "Escouade d\'Assaut",\n  "n": 2\n}\n'


def test_str_et_path_donnent_le_meme_resultat(tmp_path):
    # les scripts migrés manipulent des `Path`, `bot_zone_direct` un `str` d'argparse.
    write_json_atomic(str(tmp_path / "a.json"), {"v": 1})
    write_json_atomic(tmp_path / "b.json", {"v": 1})

    assert (tmp_path / "a.json").read_text(encoding="utf-8") == (tmp_path / "b.json").read_text(encoding="utf-8")
    assert part_path(tmp_path / "a.json") == str(tmp_path / "a.json") + ".part"


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


# --- 3. verrou statique : plus aucune écriture JSON en direct ----------------------------------

def _ouvre_en_ecriture(node: ast.Call, methode: bool) -> bool:
    """Le mode d'un `open(...)`, où qu'il soit passé.

    Trois formes à couvrir, et elles ne se ressemblent pas : `open(p, "w")` (mode en 2e
    positionnel), `open(p, mode="w")` (mot-clé — la forme qu'une première version de ce contrôle
    ne regardait pas, donc laissait passer) et `Path(p).open("w")` (méthode : le mode est le
    PREMIER argument). `x` compte autant que `w` et `a` : il tronque tout autant la destination.
    """
    positionnels = node.args if methode else node.args[1:]
    modes = [a.value for a in positionnels if isinstance(a, ast.Constant)]
    modes += [
        kw.value.value for kw in node.keywords
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant)
    ]
    return any(c in str(m) for m in modes for c in "wax")


def _direct_write_calls(path: Path) -> list[str]:
    """Appels qui écriraient un JSON à même sa destination, sans brouillon."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fautifs = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        methode = isinstance(func, ast.Attribute)
        nom = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if nom in {"dump", "write_text"}:
            fautifs.append(f"{nom}() ligne {node.lineno}")
        elif nom == "open" and _ouvre_en_ecriture(node, methode):
            fautifs.append(f"open en écriture ligne {node.lineno}")
    return fautifs


@pytest.mark.parametrize("relative", JSON_WRITERS)
def test_les_scripts_n_ecrivent_plus_de_json_en_direct(relative: str) -> None:
    chemin = PROJECT_ROOT / relative
    assert chemin.exists(), f"{relative} a disparu : la liste JSON_WRITERS est périmée"

    fautifs = _direct_write_calls(chemin)

    assert not fautifs, (
        f"{relative} écrit à même sa destination ({', '.join(fautifs)}) : une interruption y "
        "laisserait un JSON tronqué à la place du fichier précédent. Passer par "
        "`json_atomic.write_json_atomic` / `json_out_draft`."
    )


def test_le_verrou_statique_voit_reellement_une_ecriture_directe(tmp_path) -> None:
    # VERT VACANT : un analyseur qui ne reconnaît plus rien rendrait la liste vide, donc VERTE
    # sur les quatre scripts. On lui donne les trois formes qu'il doit attraper.
    faux = tmp_path / "faux.py"
    faux.write_text(
        "import json\n"
        "from pathlib import Path\n"
        "def a(p, d):\n"
        "    Path(p).write_text(json.dumps(d))\n"
        "def b(p, d):\n"
        "    with open(p, 'w') as f:\n"
        "        json.dump(d, f)\n"
        "def c(p, d):\n"                       # mode en MOT-CLÉ
        "    with open(p, mode='w') as f:\n"
        "        f.write(json.dumps(d))\n"
        "def e(p, d):\n"                       # méthode : le mode est le 1er argument
        "    with Path(p).open('x') as f:\n"
        "        f.write(json.dumps(d))\n",
        encoding="utf-8",
    )

    # 5 : write_text, open(w) + json.dump, open(mode=w), Path.open(x). Les deux dernières formes
    # sont celles qu'un contrôle borné au 2e argument positionnel laisserait passer.
    assert len(_direct_write_calls(faux)) == 5


def test_le_verrou_statique_ne_confond_pas_une_lecture_avec_une_ecriture(tmp_path) -> None:
    # les scripts couverts lisent leurs entrées par `open(p, "r")` / `Path(p).open()` : un
    # contrôle qui les compterait serait rouge en permanence, donc désarmé le jour même.
    lecteur = tmp_path / "lecteur.py"
    lecteur.write_text(
        "import json\n"
        "from pathlib import Path\n"
        "def a(p):\n"
        "    with open(p, 'r', encoding='utf-8-sig') as f:\n"
        "        return json.load(f)\n"
        "def b(p):\n"
        "    with Path(p).open() as f:\n"
        "        return json.load(f)\n",
        encoding="utf-8",
    )

    assert _direct_write_calls(lecteur) == []
