"""Verrouille le relevé `--json-out` de scripts/bot_zone_direct.py.

Le script joue de vrais épisodes (modèle + moteur) : rien de tout cela n'est instancié ici.
Ce qui est exercé, ce sont les fonctions qui portent le contrat du drapeau : la forme d'un
relevé d'épisode, l'agrégation qui alimente le tableau texte, et l'écriture du fichier. Le
point qui compte : le tableau texte est désormais DÉRIVÉ des relevés par épisode, donc les
moyennes affichées et le JSON ne peuvent plus diverger.
"""
import ast
import json
import os
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

    with script._json_out_draft(str(out)) as handle:
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


def test_un_run_interrompu_ne_laisse_ni_degat_ni_residu(script, tmp_path):
    # VERROU : le run meurt en plein jeu (Ctrl-C, crash moteur). Le relevé précédent doit être
    # intact, et aucun brouillon ne doit rester à trier à la main.
    out = tmp_path / "zones.json"
    out.write_text('{"ancien": true}\n', encoding="utf-8")

    with pytest.raises(KeyboardInterrupt):
        with script._json_out_draft(str(out)) as handle:
            handle.write('{"moiti')  # relevé à moitié écrit
            raise KeyboardInterrupt

    assert json.loads(out.read_text(encoding="utf-8")) == {"ancien": True}
    assert not (tmp_path / "zones.json.part").exists()


def test_json_out_echoue_avant_de_jouer_si_la_destination_est_un_dossier(script, tmp_path):
    # le brouillon `.part` s'ouvrirait très bien ici : c'est le os.replace FINAL qui casserait,
    # après tous les épisodes. Le cas se refuse donc à l'ouverture, pas à la publication.
    target = tmp_path / "zones"
    target.mkdir()

    with pytest.raises(IsADirectoryError):
        with script._json_out_draft(str(target)):
            pass
    assert not (tmp_path / "zones.part").exists()


def test_json_out_echoue_si_le_dossier_n_existe_pas(script, tmp_path):
    # pas de création silencieuse ni de repli sur le cwd : un chemin faux doit se voir.
    with pytest.raises(FileNotFoundError):
        with script._json_out_draft(str(tmp_path / "absent" / "z.json")):
            pass


@pytest.mark.skipif(os.geteuid() == 0, reason="root écrit dans un dossier en lecture seule")
def test_json_out_echoue_si_le_dossier_est_en_lecture_seule(script, tmp_path):
    # motif de l'ouverture réelle plutôt que d'un `isdir` : un dossier existant mais
    # non inscriptible passerait le test d'existence et casserait à la toute fin.
    readonly = tmp_path / "ro"
    readonly.mkdir()
    readonly.chmod(0o500)
    try:
        with pytest.raises(PermissionError):
            with script._json_out_draft(str(readonly / "z.json")):
                pass
    finally:
        readonly.chmod(0o700)


def test_sans_le_drapeau_aucun_fichier_n_est_touche(script, tmp_path, monkeypatch):
    # le cwd EST tmp_path : un brouillon écrit « quelque part » se verrait ici.
    monkeypatch.chdir(tmp_path)

    with script._json_out_draft(None) as handle:
        assert handle is None

    assert list(tmp_path.iterdir()) == []


def test_json_out_vide_echoue_avant_de_jouer_sans_rien_ecrire(script, tmp_path, monkeypatch):
    # `--json-out "$VAR"` avec VAR non définie : sans ce refus, `.part` atterrit dans le cwd
    # (la racine du dépôt en usage réel) et seul le os.replace final casse, après la partie.
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError):
        with script._json_out_draft(""):
            pass

    assert list(tmp_path.iterdir()) == []


def test_une_fermeture_qui_rate_ne_publie_pas_et_ne_masque_rien(script, tmp_path):
    # disque plein au flush : le relevé est incomplet, donc rien ne doit être publié, et
    # l'exception d'origine doit rester celle qu'on lit.
    out = tmp_path / "zones.json"
    out.write_text('{"ancien": true}\n', encoding="utf-8")

    class _CloseKO(OSError):
        pass

    with pytest.raises(KeyboardInterrupt):
        with script._json_out_draft(str(out)) as handle:
            handle.close = lambda: (_ for _ in ()).throw(_CloseKO("ENOSPC"))
            raise KeyboardInterrupt

    assert json.loads(out.read_text(encoding="utf-8")) == {"ancien": True}
    assert not (tmp_path / "zones.json.part").exists()


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
