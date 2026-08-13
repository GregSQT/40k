"""Verrouille le relevé `--json-out` de scripts/bot_zone_direct.py.

Le script joue de vrais épisodes (modèle + moteur) : rien de tout cela n'est instancié ici.
Ce qui est exercé, ce sont les trois fonctions pures qui portent le contrat du drapeau —
la forme d'un relevé d'épisode, l'agrégation qui alimente le tableau texte, et l'écriture du
fichier. Le point qui compte : le tableau texte est désormais DÉRIVÉ des relevés par épisode,
donc les moyennes affichées et le JSON ne peuvent plus diverger.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "bot_zone_direct.py"


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("bot_zone_direct_under_test", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module spec for {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def test_json_out_relit_les_episodes_un_par_un(script, tmp_path):
    records = [
        script._episode_record("bot_zone", 0, 111, 2, {1: 0, 2: 1}),
        script._episode_record("bot_zone", 1, 222, 2, {1: 2, 2: 2}),
    ]
    out = tmp_path / "sub" / "zones.json"
    out.parent.mkdir()

    script._write_json_out(str(out), "/x/model_ArmageddonAgent.zip", "holdout_1.json", 2, records)
    payload = json.loads(out.read_text(encoding="utf-8"))

    assert payload["model"] == "model_ArmageddonAgent.zip"
    assert payload["scenario_file"] == "holdout_1.json"
    assert payload["episodes_requested"] == 2
    assert [ep["seed"] for ep in payload["episodes"]] == [111, 222]
    assert payload["episodes"][1]["zones_by_turn"] == {"1": 2, "2": 2}
    # rejouable : l'agrégat relu vaut l'agrégat d'origine
    assert script._aggregate_zones(payload["episodes"]) == script._aggregate_zones(records)


def test_json_out_echoue_si_le_dossier_n_existe_pas(script, tmp_path):
    # pas de création silencieuse ni de repli sur le cwd : un chemin faux doit se voir.
    with pytest.raises(FileNotFoundError):
        script._write_json_out(str(tmp_path / "absent" / "z.json"), "m.zip", "s.json", 1, [])


def test_le_drapeau_existe_sur_la_ligne_de_commande():
    # --help sort pendant parse_args, avant les imports lourds de main() : aucun modèle chargé.
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--help"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120,
    )

    assert proc.returncode == 0, proc.stderr
    assert "--json-out" in proc.stdout
    assert "--episodes" in proc.stdout
