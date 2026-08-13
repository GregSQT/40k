"""Verrouille le relevé `--json-out` de scripts/bot_zone_direct.py.

Le script joue de vrais épisodes (modèle + moteur) : rien de tout cela n'est instancié ici.
Ce qui est exercé, ce sont les fonctions qui portent le contrat du drapeau : la forme d'un
relevé d'épisode, l'agrégation qui alimente le tableau texte, et le passage par l'écriture
atomique partagée. Le point qui compte : le tableau texte est désormais DÉRIVÉ des relevés par
épisode, donc les moyennes affichées et le JSON ne peuvent plus diverger.

Le contrat du brouillon `.part` lui-même (fichier précédent intact, aucun résidu, destination
refusée si vide / dossier / absente / en lecture seule, fermeture qui rate) est verrouillé UNE
fois pour les quatre scripts
dans `test_json_atomic.py` — il n'est plus rejoué ici. Ce qui reste ici du drapeau, c'est ce qui
n'appartient qu'à ce script : le fail-fast AVANT le chargement du modèle.
"""
import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests._chargeur_script import charger_script

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "bot_zone_direct.py"


def _FINGERPRINT(script):
    """Empreinte d'un fichier qui existe — ce script tient lieu de checkpoint pour les tests."""
    return script._model_fingerprint(str(SCRIPT_PATH))


@pytest.fixture(scope="module")
def script():
    return charger_script("scripts/bot_zone_direct.py")


def test_episode_record_porte_graine_joueur_et_zones_triees(script):
    rec = script._episode_record("bot_zone", 3, 987654, 2, {5: 1, 1: 2, 2: 0})

    assert rec["bot"] == "bot_zone"
    assert rec["episode"] == 3
    assert rec["seed"] == 987654
    assert rec["bot_player"] == 2
    # clés JSON = chaînes, dans l'ordre des tours (un dict de tours int ne survit pas à json.dump)
    assert list(rec["zones_by_turn"].items()) == [("1", 2), ("2", 0), ("5", 1)]


def test_aggregation_conserve_chaque_episode_dans_l_ordre(script):
    records = [
        script._episode_record("a", 0, 1, 2, {1: 0, 2: 3}),
        script._episode_record("a", 1, 2, 2, {1: 1, 2: 3}),
        script._episode_record("b", 0, 3, 1, {1: 2}),
    ]

    agg = script._aggregate_zones(records)

    # doublons conservés (3 apparaît deux fois) et ordre = ordre des épisodes : c'est ce dont
    # dépend la moyenne du tableau texte.
    assert agg == {"a": {1: [0, 1], 2: [3, 3]}, "b": {1: [2]}}
    assert sum(agg["a"][2]) / len(agg["a"][2]) == 3.0


def test_aggregation_supporte_les_tours_absents_de_certains_episodes(script):
    records = [
        script._episode_record("a", 0, 1, 2, {1: 1, 2: 2}),
        script._episode_record("a", 1, 2, 2, {1: 0}),  # épisode terminé au tour 1
    ]

    agg = script._aggregate_zones(records)

    assert agg["a"][1] == [1, 0]
    assert agg["a"][2] == [2]


def test_n_est_le_nombre_d_episodes_parvenus_au_dernier_tour(script):
    # colonne N du tableau : les épisodes plus courts ne comptent pas au dernier tour observé.
    assert script._n_at_last_turn({1: [0, 1, 2], 2: [1, 1]}) == 2
    assert script._n_at_last_turn({}) == 0


def test_json_out_relit_les_episodes_un_par_un(script, tmp_path):
    records = [
        script._episode_record("bot_zone", 0, 111, 2, {1: 0, 2: 1}),
        script._episode_record("bot_zone", 1, 222, 2, {1: 2, 2: 2}),
    ]
    out = tmp_path / "sub" / "zones.json"
    out.parent.mkdir()
    meta = script._run_meta(_FINGERPRINT(script), "holdout_1.json", 2, 42, "p1", 42, {"bot_zone": 0.1})

    with script.json_out_draft(str(out)) as handle:
        script._write_json_out(handle, meta, records)
    payload = json.loads(out.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 2
    assert payload["run"]["scenario_file"] == "holdout_1.json"
    assert payload["run"]["episodes_requested"] == 2
    assert [ep["seed"] for ep in payload["episodes"]] == [111, 222]
    assert payload["episodes"][1]["zones_by_turn"] == {"1": 2, "2": 2}
    # rejouable : l'agrégat relu vaut l'agrégat d'origine
    assert script._aggregate_zones(payload["episodes"]) == script._aggregate_zones(records)
    assert not (tmp_path / "sub" / "zones.json.part").exists()


def test_le_releve_dit_ce_qui_distingue_deux_runs(script):
    # sans ces champs, un « avant » et un « après » §12.7 sont indiscernables, et la graine
    # d'épisode ne suffit pas à reconstruire la doctrine du bot.
    meta = script._run_meta(_FINGERPRINT(script), "holdout_1.json", 20, 42, "alternate", 7, {"bot_zone": 0.25})

    assert meta["base_seed"] == 42
    assert meta["agent_seat_mode"] == "alternate"
    assert meta["agent_seat_seed"] == 7
    assert meta["bot_randomness"] == {"bot_zone": 0.25}
    # le chemin du modèle est constant d'un run à l'autre : ce qui l'identifie, c'est le fichier.
    assert meta["model_bytes"] == SCRIPT_PATH.stat().st_size
    assert meta["model_mtime"].startswith("20")


def test_l_empreinte_du_modele_est_relevee_avant_son_chargement(script):
    # la seule raison d'être de `_model_fingerprint` : un entraînement qui réécrit le .zip
    # pendant le run ferait consigner un checkpoint qui n'a pas joué. Rien d'observable à
    # l'exécution ne l'atteste sans vrai modèle — l'ordre est donc verrouillé sur l'AST réel.
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    main_fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")

    def line_of(pred) -> int:
        return next(n.lineno for n in ast.walk(main_fn) if isinstance(n, ast.Call) and pred(n.func))

    fingerprint = line_of(lambda f: isinstance(f, ast.Name) and f.id == "_model_fingerprint")
    load = line_of(lambda f: isinstance(f, ast.Attribute) and f.attr == "load")

    assert fingerprint < load


def test_la_destination_est_ouverte_avant_de_jouer_le_moindre_episode(tmp_path):
    # VERROU du fail-fast : la destination fausse doit tuer le run AVANT le chargement du
    # modèle — sinon l'erreur tombe après des minutes de jeu et les graines sont perdues.
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--episodes", "1", "--json-out", str(tmp_path / "absent" / "z.json")],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=300,
    )

    assert proc.returncode != 0
    assert "FileNotFoundError" in proc.stderr
    assert "Modèle" not in proc.stdout  # première trace de main() après les imports lourds


def test_le_drapeau_existe_sur_la_ligne_de_commande():
    # --help sort pendant parse_args, avant les imports lourds de main() : aucun modèle chargé.
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--help"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120,
    )

    assert proc.returncode == 0, proc.stderr
    assert "--json-out" in proc.stdout
    assert "--episodes" in proc.stdout
