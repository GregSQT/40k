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

from json_atomic import dump_json, json_out_draft, part_path, write_json_atomic  # noqa: E402

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


def test_sans_destination_aucun_fichier_n_est_touche(tmp_path):
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

def _direct_write_calls(path: Path) -> list[str]:
    """Appels qui écriraient un JSON à même sa destination, sans brouillon."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fautifs = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in {"dump", "write_text"}:
            fautifs.append(f"{func.attr}() ligne {node.lineno}")
        elif isinstance(func, ast.Name) and func.id == "open":
            modes = [a.value for a in node.args[1:] if isinstance(a, ast.Constant)]
            if any("w" in str(m) or "a" in str(m) for m in modes):
                fautifs.append(f"open(..., 'w') ligne {node.lineno}")
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
        "        json.dump(d, f)\n",
        encoding="utf-8",
    )

    assert len(_direct_write_calls(faux)) == 3
