"""Verrouille le relevé `--json-out` de scripts/bot_zone_direct.py.

Le script joue de vrais épisodes (modèle + moteur) : rien de tout cela n'est instancié ici.
Ce qui est exercé, ce sont les fonctions qui portent le contrat du drapeau : la forme d'un
relevé d'épisode, l'agrégation qui alimente le tableau texte, et le passage par l'écriture
atomique partagée. Le point qui compte : le tableau texte est désormais DÉRIVÉ des relevés par
épisode, donc les moyennes affichées et le JSON ne peuvent plus diverger.

Le contrat du brouillon `.part` lui-même (fichier précédent intact, aucun résidu, destination
refusée si vide / dossier / absente / en lecture seule, fermeture qui rate) est verrouillé UNE
fois pour tout le dépôt dans `tests/unit/shared/test_json_atomic.py` — il n'est plus rejoué ici. Ce qui reste ici du drapeau, c'est ce qui
n'appartient qu'à ce script : le fail-fast AVANT le chargement du modèle.
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


def _line_of(tree: ast.AST, pred, label: str) -> int:
    hits = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call) and pred(n.func)]
    assert hits, f"{label} introuvable dans main()"
    return min(hits)


@pytest.fixture(scope="module")
def fingerprint(script):
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


def test_json_out_relit_les_episodes_un_par_un(script, tmp_path, fingerprint):
    # DEUX bots, 1 épisode chacun : episodes_per_bot=1, n_bots=2, episodes_total=2, len(records)=2.
    # Avec un seul bot l'écart était invisible (1×1 == 1). C'est le seul scénario qui prouve
    # que episodes_total == len(payload["episodes"]) et non episodes_per_bot.
    records = [
        script._episode_record("bot_a", 0, 111, 2, {1: 0, 2: 1}),
        script._episode_record("bot_b", 0, 222, 1, {1: 2, 2: 2}),
    ]
    out = tmp_path / "sub" / "zones.json"
    out.parent.mkdir()
    meta = script._run_meta(fingerprint, "holdout_1.json", 1, 2, 42, "p1", 42, {"bot_a": 0.1, "bot_b": 0.2})

    with script.json_out_draft(str(out)) as handle:
        script._write_json_out(handle, meta, records)
    payload = json.loads(out.read_text(encoding="utf-8"))

    # 4 et non 3 : `focus_targets_by_turn` renommé `distinct_targets_by_turn` — un lecteur v3
    # lève un KeyError sur ce fichier. Cf. le commentaire du script pour l'historique complet.
    assert payload["schema_version"] == 4
    assert "episodes_requested" not in payload["run"]
    assert payload["run"]["scenario_file"] == "holdout_1.json"
    assert payload["run"]["episodes_per_bot"] == 1
    assert payload["run"]["episodes_total"] == 2
    assert payload["run"]["episodes_total"] == len(payload["episodes"])
    assert [ep["seed"] for ep in payload["episodes"]] == [111, 222]
    assert payload["episodes"][1]["zones_by_turn"] == {"1": 2, "2": 2}
    # rejouable : l'agrégat relu vaut l'agrégat d'origine
    assert script._aggregate_zones(payload["episodes"]) == script._aggregate_zones(records)
    assert list((tmp_path / "sub").glob("*.part")) == []


def test_le_releve_dit_ce_qui_distingue_deux_runs(script, fingerprint):
    # sans ces champs, un « avant » et un « après » §12.7 sont indiscernables, et la graine
    # d'épisode ne suffit pas à reconstruire la doctrine du bot.
    meta = script._run_meta(fingerprint, "holdout_1.json", 20, 6, 42, "alternate", 7, {"bot_zone": 0.25})

    assert meta["base_seed"] == 42
    assert meta["agent_seat_mode"] == "alternate"
    assert meta["agent_seat_seed"] == 7
    assert meta["bot_randomness"] == {"bot_zone": 0.25}
    assert meta["episodes_per_bot"] == 20
    assert meta["episodes_total"] == 120
    # le chemin du modèle est constant d'un run à l'autre : ce qui l'identifie, c'est le fichier.
    assert meta["model_bytes"] == SCRIPT_PATH.stat().st_size
    assert meta["model_mtime"].startswith("20")


@pytest.fixture(scope="module")
def main_ast():
    """`main()` charge un vrai modèle et une vraie config : les trois contrats ci-dessous ne
    sont atteignables ni en process ni en sous-processus, et se verrouillent donc sur l'AST
    RÉEL du script — un réordonnancement les rend rouges, une reformulation ne les touche pas.
    """
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    node = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"),
        None,
    )
    if node is None:
        pytest.fail("main() introuvable dans bot_zone_direct.py")
    return node


def test_l_empreinte_du_modele_est_relevee_avant_son_chargement(main_ast):
    # la seule raison d'être de `_model_fingerprint` : un entraînement qui réécrit le .zip
    # pendant le run ferait consigner un checkpoint qui n'a pas joué.
    fp = _line_of(main_ast, lambda f: isinstance(f, ast.Name) and f.id == "_model_fingerprint", "_model_fingerprint")
    load = _line_of(
        main_ast,
        lambda f: isinstance(f, ast.Attribute) and f.attr == "load" and isinstance(f.value, ast.Name) and f.value.id == "MaskablePPO",
        "MaskablePPO.load",
    )

    assert fp < load


def _require_key_args(main_ast) -> set:
    return {
        node.args[1].value
        for node in ast.walk(main_ast)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name) and node.func.id == "require_key"
        and len(node.args) == 2 and isinstance(node.args[1], ast.Constant)
    }


def test_le_panel_passe_par_le_chargeur_de_l_evaluation_reelle(main_ast):
    # relire `callback_params` à la main privait CE script — et lui seul — des trois contrôles
    # de `_load_bot_eval_params` : clés exigées, coercition float, poids qui somment à 1.0.
    # Il compare pourtant ses moyennes à celles que produit ai/bot_evaluation.py.
    appels = {
        node.func.id
        for node in ast.walk(main_ast)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_load_bot_eval_params" in appels

    # et plus aucune relecture directe du bloc callback_params
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert 'cb.get("bot_eval' not in source
    assert 'require_key(cb, "bot_eval' not in source


def test_les_cles_qui_decident_du_protocole_sont_exigees(main_ast):
    # `agent_seat_mode` : le défaut "p1" décidait du siège ET était recopié dans run_meta comme
    # s'il venait de la config. `opponent_player` : le défaut 2 comptait les zones de l'AGENT
    # dans la moitié des épisodes (agent_seat_mode="random" sur x1_panel). `turn` et
    # `objective_controllers` : posées par le reset du moteur, donc un défaut n'y masque qu'une
    # régression — sous forme d'un 0.00 crédible.
    exigees = _require_key_args(main_ast)

    assert {"agent_seat_mode", "opponent_player", "turn", "objective_controllers"} <= exigees

    defaultees = {
        (node.func.value.id, node.args[0].value)
        for node in ast.walk(main_ast)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get" and isinstance(node.func.value, ast.Name)
        and len(node.args) == 2 and isinstance(node.args[0], ast.Constant)
    }
    interdits = {
        ("tc", "agent_seat_mode"), ("info", "opponent_player"),
        ("gs", "turn"), ("gs", "objective_controllers"),
    }
    assert not (interdits & defaultees)


def test_la_ligne_de_succes_s_affiche_apres_la_publication(main_ast):
    # dans le `with`, un flush qui rate faisait lire « Relevé par épisode : … » juste avant la
    # trace, destination absente ou portant encore le run précédent.
    draft = next(
        (n for n in ast.walk(main_ast)
         if isinstance(n, ast.With)
         and any(isinstance(i.context_expr, ast.Call) and isinstance(i.context_expr.func, ast.Name)
                 and i.context_expr.func.id == "json_out_draft" for i in n.items)),
        None,
    )
    assert draft is not None, "bloc with json_out_draft introuvable dans main()"
    annonce = next(
        (n for n in ast.walk(main_ast)
         if isinstance(n, ast.Constant) and isinstance(n.value, str) and "Relevé par épisode" in n.value),
        None,
    )
    assert annonce is not None, "annonce 'Relevé par épisode' introuvable dans main()"

    assert annonce.lineno > draft.end_lineno


def test_la_destination_est_ouverte_avant_de_jouer_le_moindre_episode(tmp_path):
    # VERROU du fail-fast : la destination fausse doit tuer le run AVANT le chargement du
    # modèle — sinon l'erreur tombe après des minutes de jeu et les graines sont perdues.
    # W40K_BOARD_PATH est requis pour dépasser la garde de plateau (avant json_out_draft).
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--episodes", "1", "--json-out", str(tmp_path / "absent" / "z.json")],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=300,
        env={**os.environ, "W40K_BOARD_PATH": "board/44x60x1"},
    )

    assert proc.returncode != 0
    assert "FileNotFoundError" in proc.stderr
    assert "Modèle" not in proc.stdout  # première trace de main() après les imports lourds


def test_les_colonnes_du_tableau_viennent_de_la_duree_de_la_bataille(script):
    # `turns = [1,2,3,4,5]` en dur pendant que la colonne N suit `max(per_turn)` : rien ne
    # gardait le couplage à game_rules.max_turns.
    records = [script._episode_record("a", 0, 1, 2, {1: 0, 2: 1})]

    assert script._table_turns(5, records) == [1, 2, 3, 4, 5]
    assert script._table_turns(3, records) == [1, 2, 3]
    # bataille illimitée (Endless Duty) : il n'y a que des tours observés
    assert script._table_turns(None, records) == [1, 2]
    assert script._table_turns(None, []) == []


def test_zero_episode_est_refuse_avant_d_ouvrir_la_destination(tmp_path):
    # VERROU : `--episodes 0` jouait zéro épisode et publiait `"episodes": []` PAR-DESSUS le
    # relevé précédent, en sortant 0. Le fichier existant doit rester INTACT.
    dest = tmp_path / "zones.json"
    dest.write_text('{"schema_version": 3, "episodes": ["releve precedent"]}', encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--episodes", "0", "--json-out", str(dest)],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120,
        env={**os.environ, "W40K_BOARD_PATH": "board/44x60x1"},
    )

    assert proc.returncode != 0
    assert "--episodes" in proc.stderr
    assert json.loads(dest.read_text(encoding="utf-8"))["episodes"] == ["releve precedent"]
    assert list(tmp_path.glob("*.part")) == []


# ⚠️ Le finding 8 (« bot=P2 » alors que le siège est aléatoire) N'EST PAS verrouillé ici : la
# ligne de référence a été sortie de ce script vers `scripts/bot_panel_reference.py`, source
# unique partagée avec `bot_zone_check.py`, dont la docstring annonce son propre verrou
# (`tests/unit/scripts/test_bot_panel_reference.py`). Un second verrou écrit ici relirait le
# fichier appelant et rougirait à la prochaine factorisation, sans rien garder de plus.


def test_le_drapeau_existe_sur_la_ligne_de_commande():
    # --help sort pendant parse_args, avant les imports lourds de main() : aucun modèle chargé.
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--help"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120,
    )

    assert proc.returncode == 0, proc.stderr
    assert "--json-out" in proc.stdout
    assert "--episodes" in proc.stdout
