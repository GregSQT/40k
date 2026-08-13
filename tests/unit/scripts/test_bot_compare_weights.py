"""Verrouille scripts/bot_compare_weights.py.

Les fonctions internes (_episodes_by_bot, _check_controls, _compute_delta) sont verrouillées
une à une ; tout ce qui se lit en sortie — drift, mean, std, IC 95 % — l'est À TRAVERS main(),
sur des fichiers JSON réels, jamais en recalculant la formule ici : un test qui refait le
calcul du script valide sa propre copie et laisse la divergence passer. Le quantile de Student
est donc écrit en dur (t(3)=3,182), pas relu de `scipy` : c'est ce qui distingue l'intervalle
du 1,96 normal qu'il remplace.

Rouge prouvé par mutation (2026-08-13, `__pycache__` purgé) sur : la vérification de seed dans
_compute_delta, le n−1 du std, l'exclusion des épisodes courts (retour au `.get("5", 0)`), les
deux gardes de longueur, le quantile de Student (retour à 1,96) et le vert vacant des contrôles.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

from tests._chargeur_script import charger_script


@pytest.fixture(scope="module")
def script():
    return charger_script("scripts/bot_compare_weights.py")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ep(bot: str, episode: int, seed: int, zones_fin: int, dernier_tour: int = 5) -> Dict[str, Any]:
    """Épisode minimal : seuls `seed` et `zones_by_turn` comptent pour ce script.

    `dernier_tour` reproduit la forme réelle d'un épisode terminé avant la fin de la bataille
    (bot_zone_direct.py:531-534 ne pose une clé que pour les tours joués) : à 3, il n'y a PAS de
    clé "5", et `zones_fin` est alors la valeur du T3 — que le script doit ignorer, pas lire.
    """
    zones = {str(t): 1 for t in range(1, dernier_tour + 1)}
    zones[str(dernier_tour)] = zones_fin
    return {
        "bot": bot,
        "episode": episode,
        "seed": seed,
        "bot_player": 1,
        "zones_by_turn": zones,
    }


# ---------------------------------------------------------------------------
# _episodes_by_bot
# ---------------------------------------------------------------------------


def test_episodes_by_bot_groupe_correctement(script):
    eps = [
        _ep("decapitation", 0, 10, 1),
        _ep("racer", 0, 20, 2),
        _ep("decapitation", 1, 11, 0),
    ]
    result = script._episodes_by_bot(eps)
    assert list(result["decapitation"]) == [eps[0], eps[2]]
    assert list(result["racer"]) == [eps[1]]


# ---------------------------------------------------------------------------
# _check_controls — cas normal, drift, et tout ce qui rend le contrôle vacant
# ---------------------------------------------------------------------------


def test_check_controls_identiques_affiche_zero_drift_et_le_nombre_de_comparaisons(script, capsys):
    ref_by_bot = script._episodes_by_bot([
        _ep("decapitation", 0, 42, 1),
        _ep("racer", 0, 100, 2),
        _ep("racer", 1, 101, 2),
    ])
    var_by_bot = script._episodes_by_bot([
        _ep("decapitation", 0, 42, 3),   # cible peut varier
        _ep("racer", 0, 100, 2),         # contrôle identique
        _ep("racer", 1, 101, 2),
    ])
    script._check_controls(ref_by_bot, var_by_bot, "decapitation")
    captured = capsys.readouterr()
    # Le compte est la SUBSTANCE de la coche : sans lui, « ✓ » s'affiche aussi bien après zéro
    # comparaison qu'après deux.
    assert "drift contrôles = 0.000 ✓  (1 bots, 2 épisodes comparés)" in captured.out


def test_check_controls_drift_non_nul_leve_runtime_error(script):
    ref_by_bot = script._episodes_by_bot([
        _ep("decapitation", 0, 42, 1),
        _ep("racer", 0, 100, 2),
    ])
    var_by_bot = script._episodes_by_bot([
        _ep("decapitation", 0, 42, 3),
        _ep("racer", 0, 100, 3),   # zones_by_turn différent → drift
    ])
    with pytest.raises(RuntimeError, match="drift non nul"):
        script._check_controls(ref_by_bot, var_by_bot, "decapitation")


def test_check_controls_drift_hors_zones_leve_aussi(script):
    """Le relevé ENTIER est comparé : une graine de contrôle qui bouge est une dérive de protocole."""
    ref_by_bot = script._episodes_by_bot([
        _ep("decapitation", 0, 42, 1),
        _ep("racer", 0, 100, 2),
    ])
    var_by_bot = script._episodes_by_bot([
        _ep("decapitation", 0, 42, 3),
        _ep("racer", 0, 999, 2),   # zones identiques, seed différente
    ])
    with pytest.raises(RuntimeError, match="drift non nul"):
        script._check_controls(ref_by_bot, var_by_bot, "decapitation")


def test_check_controls_bot_absent_d_un_fichier_leve(script):
    """« racer » absent de var : le panel a changé, les contrôles ne se rétrécissent pas en silence."""
    ref_by_bot = script._episodes_by_bot([
        _ep("decapitation", 0, 42, 1),
        _ep("racer", 0, 100, 2),
    ])
    var_by_bot = script._episodes_by_bot([
        _ep("decapitation", 0, 42, 3),
    ])
    with pytest.raises(RuntimeError, match="panels différents"):
        script._check_controls(ref_by_bot, var_by_bot, "decapitation")


def test_check_controls_longueurs_inegales_levent(script):
    """Un run de contrôle tronqué : le zip n'en comparait que le préfixe et affichait vert."""
    ref_by_bot = script._episodes_by_bot([
        _ep("decapitation", 0, 42, 1),
        _ep("racer", 0, 100, 2),
        _ep("racer", 1, 101, 2),
    ])
    var_by_bot = script._episodes_by_bot([
        _ep("decapitation", 0, 42, 3),
        _ep("racer", 0, 100, 2),
    ])
    with pytest.raises(RuntimeError, match="nombres d'épisodes différents"):
        script._check_controls(ref_by_bot, var_by_bot, "decapitation")


def test_check_controls_sans_aucun_controle_leve(script, capsys):
    """Relevé produit avec le seul bot cible : il n'y a RIEN à vérifier, donc rien à afficher en vert."""
    ref_by_bot = script._episodes_by_bot([_ep("decapitation", 0, 42, 1)])
    var_by_bot = script._episodes_by_bot([_ep("decapitation", 0, 42, 3)])
    with pytest.raises(RuntimeError, match="aucun bot de contrôle"):
        script._check_controls(ref_by_bot, var_by_bot, "decapitation")
    assert "✓" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _compute_delta — appariement, graines, épisodes courts
# ---------------------------------------------------------------------------


def test_compute_delta_cas_normal(script):
    ref_eps = [_ep("decapitation", i, 10 + i, i) for i in range(3)]
    var_eps = [_ep("decapitation", i, 10 + i, i + 1) for i in range(3)]
    assert script._compute_delta(ref_eps, var_eps) == ([1.0, 1.0, 1.0], 0, 0)


def test_compute_delta_graines_desappariees_leve_runtime_error(script):
    ref_eps = [_ep("decapitation", 0, 42, 2)]
    var_eps = [_ep("decapitation", 0, 99, 3)]   # seed différente
    with pytest.raises(RuntimeError, match="graines désappariées"):
        script._compute_delta(ref_eps, var_eps)


def test_compute_delta_longueurs_inegales_levent(script):
    """Les graines sont indexées : un var tronqué s'apparie sur son préfixe sans rien signaler."""
    ref_eps = [_ep("decapitation", i, 10 + i, 1) for i in range(3)]
    var_eps = [_ep("decapitation", i, 10 + i, 2) for i in range(2)]
    with pytest.raises(RuntimeError, match="nombres d'épisodes différents"):
        script._compute_delta(ref_eps, var_eps)


def test_compute_delta_ecarte_les_paires_terminees_avant_le_t5(script):
    """Une paire dont un côté s'arrête au T3 sort du calcul — elle ne vaut pas « 0 zone tenue ».

    Le T3 porte ici 99 zones : s'il était lu comme un T5, il déborderait de tous les Δ.
    """
    ref_eps = [
        _ep("decapitation", 0, 10, 1),                     # complet
        _ep("decapitation", 1, 11, 99, dernier_tour=3),    # ref courte
        _ep("decapitation", 2, 12, 1),                     # complet, var courte
        _ep("decapitation", 3, 13, 2),                     # complet
    ]
    var_eps = [
        _ep("decapitation", 0, 10, 3),
        _ep("decapitation", 1, 11, 2),
        _ep("decapitation", 2, 12, 99, dernier_tour=2),
        _ep("decapitation", 3, 13, 2),
    ]
    assert script._compute_delta(ref_eps, var_eps) == ([2.0, 0.0], 1, 1)


def test_compute_delta_asymetrie_des_exclusions_rapportee(script):
    """Les deux compteurs sont distincts : leur écart est le signal (« la variante finit plus tôt »)."""
    ref_eps = [_ep("decapitation", i, 10 + i, 1) for i in range(3)]
    var_eps = [
        _ep("decapitation", 0, 10, 2),
        _ep("decapitation", 1, 11, 1, dernier_tour=4),
        _ep("decapitation", 2, 12, 1, dernier_tour=3),
    ]
    assert script._compute_delta(ref_eps, var_eps) == ([1.0], 0, 2)


# ---------------------------------------------------------------------------
# main() — câblage argparse, _load, gardes bot, sortie stdout
# ---------------------------------------------------------------------------


def _write_json(path: Path, episodes: List[Dict[str, Any]]) -> None:
    import json
    path.write_text(
        json.dumps({"schema_version": 3, "run": {}, "episodes": episodes}),
        encoding="utf-8",
    )


def test_main_cas_normal_affiche_sortie(script, tmp_path, monkeypatch, capsys):
    ref_eps = [_ep("decapitation", i, 10 + i, 1) for i in range(5)] + [
        _ep("racer", i, 20 + i, 2) for i in range(5)
    ]
    var_eps = [_ep("decapitation", i, 10 + i, 2) for i in range(5)] + [
        _ep("racer", i, 20 + i, 2) for i in range(5)
    ]
    ref_file = tmp_path / "ref.json"
    var_file = tmp_path / "var.json"
    _write_json(ref_file, ref_eps)
    _write_json(var_file, var_eps)

    monkeypatch.setattr(sys, "argv", ["prog", str(ref_file), str(var_file), "--bot", "decapitation"])
    script.main()

    out = capsys.readouterr().out
    assert "drift contrôles = 0.000 ✓  (1 bots, 5 épisodes comparés)" in out
    assert "Bot cible : decapitation  (n=5)" in out
    assert "épisodes écartés (terminés avant le T5) : ref 0, var 0" in out
    assert "mean(Δ_T5) = +1.000" in out


def test_main_std_et_ic_sur_deltas_disperses(script, tmp_path, monkeypatch, capsys):
    """Δ = [0, 1, 2, 3] → mean 1,5, std (n−1) √(5/3) = 1,291, IC = t(3)·std/√n = 3,182·0,645.

    Seul test qui verrouille les DEUX formules de main() : un std en n au lieu de n−1 rendrait
    1,118, et le quantile normal 1,96 rendrait un IC de 1,265 — soit [+0,235 ; +2,765], qui
    EXCLUT 0 et déclare l'effet significatif là où Student ne conclut pas.
    """
    ref_eps = [_ep("decapitation", i, 10 + i, 0) for i in range(4)] + [
        _ep("racer", i, 20 + i, 2) for i in range(4)
    ]
    var_eps = [_ep("decapitation", i, 10 + i, i) for i in range(4)] + [
        _ep("racer", i, 20 + i, 2) for i in range(4)
    ]
    ref_file = tmp_path / "ref_disperse.json"
    var_file = tmp_path / "var_disperse.json"
    _write_json(ref_file, ref_eps)
    _write_json(var_file, var_eps)

    monkeypatch.setattr(sys, "argv", ["prog", str(ref_file), str(var_file), "--bot", "decapitation"])
    script.main()

    out = capsys.readouterr().out
    assert "Bot cible : decapitation  (n=4)" in out
    assert "mean(Δ_T5) = +1.500" in out
    assert "std(Δ_T5)  =  1.291" in out
    assert "IC 95 %    = +1.500 ± 2.054  [-0.554 ; +3.554]  (Student t=3.182, ddl=3)" in out


def test_main_un_seul_episode_std_et_ic_non_definis(script, tmp_path, monkeypatch, capsys):
    """n=1 : la variance d'échantillon n'existe pas (n−1=0). « ± 0.000 » se lisait comme l'effet
    le plus significatif possible — c'est l'absence d'intervalle qui doit s'afficher."""
    ref_file = tmp_path / "ref_un.json"
    var_file = tmp_path / "var_un.json"
    _write_json(ref_file, [_ep("decapitation", 0, 42, 1), _ep("racer", 0, 20, 2)])
    _write_json(var_file, [_ep("decapitation", 0, 42, 3), _ep("racer", 0, 20, 2)])

    monkeypatch.setattr(sys, "argv", ["prog", str(ref_file), str(var_file), "--bot", "decapitation"])
    script.main()

    out = capsys.readouterr().out
    assert "(n=1)" in out
    assert "mean(Δ_T5) = +2.000" in out
    assert "std(Δ_T5)  =  non défini (n=1)" in out
    assert "IC 95 %    = non défini (n=1)" in out
    assert "±" not in out


def test_main_toutes_les_paires_ecartees_exit_1(script, tmp_path, monkeypatch, capsys):
    """Aucune partie ne va au T5 : il n'y a pas de moyenne à publier, et pas de division par zéro."""
    ref_file = tmp_path / "ref_courts.json"
    var_file = tmp_path / "var_courts.json"
    _write_json(ref_file, [
        _ep("decapitation", 0, 42, 1, dernier_tour=3), _ep("racer", 0, 20, 2),
    ])
    _write_json(var_file, [
        _ep("decapitation", 0, 42, 3, dernier_tour=4), _ep("racer", 0, 20, 2),
    ])

    monkeypatch.setattr(sys, "argv", ["prog", str(ref_file), str(var_file), "--bot", "decapitation"])
    with pytest.raises(SystemExit) as exc:
        script.main()
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "épisodes écartés (terminés avant le T5) : ref 1, var 1" in captured.out
    assert "aucune paire d'épisodes ne parvient au T5" in captured.err


def test_main_bot_absent_ref_exit_1(script, tmp_path, monkeypatch, capsys):
    ref_file = tmp_path / "ref_no_target.json"
    var_file = tmp_path / "var_no_target.json"
    _write_json(ref_file, [_ep("racer", 0, 10, 1)])
    _write_json(var_file, [_ep("decapitation", 0, 10, 2)])

    monkeypatch.setattr(sys, "argv", ["prog", str(ref_file), str(var_file), "--bot", "decapitation"])
    with pytest.raises(SystemExit) as exc:
        script.main()
    assert exc.value.code == 1
    assert "decapitation" in capsys.readouterr().err


def test_main_bot_absent_var_exit_1(script, tmp_path, monkeypatch, capsys):
    ref_file = tmp_path / "ref_only_target.json"
    var_file = tmp_path / "var_only_racer.json"
    _write_json(ref_file, [_ep("decapitation", 0, 10, 1)])
    _write_json(var_file, [_ep("racer", 0, 10, 2)])

    monkeypatch.setattr(sys, "argv", ["prog", str(ref_file), str(var_file), "--bot", "decapitation"])
    with pytest.raises(SystemExit) as exc:
        script.main()
    assert exc.value.code == 1
    assert "decapitation" in capsys.readouterr().err
