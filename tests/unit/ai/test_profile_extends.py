"""Verrou — l'héritage entre profils d'entraînement (`extends`).

RAISON D'ÊTRE, mesurée le 2026-09-07 : les six profils du fichier d'entraînement partageaient
quinze clés recopiées à l'identique — `x1` et `x1_long` diffèrent sur quatre clés et en dupliquent
quinze, soit 15,1 Ko par profil. Rien n'empêchait ces copies de diverger, sauf un test
(`test_schedule_decay_fraction.py::test_long_profile_is_its_reference_recalibrated`). Ajouter un
septième profil pour la lignée aurait ajouté une septième copie ; `extends` la supprime.

CE QUE LE MÉCANISME DOIT GARANTIR, et que ce fichier verrouille :
1. la fusion est PROFONDE — un enfant qui surcharge six clés de `model_params` ne perd pas les
   neuf autres, ce qu'un remplacement de bloc ferait en silence puisque le profil resterait
   un dict valide ;
2. un scalaire de l'enfant ÉCRASE un dict du parent — c'est exactement ce qu'un profil de lignée
   demande en substituant une constante à une rampe ;
3. la clé `extends` ne survit pas à la résolution : elle décrit la construction du profil, pas le
   run ;
4. une chaîne cassée (parent absent, cycle, mauvais type) lève, sans jamais retomber sur le
   profil nu — un profil silencieusement non résolu tournerait des heures sous le mauvais régime.

PREUVE PAR MUTATION (mécanisme) : dans `config_loader._deep_merge_profile`, remplacer la branche
``if isinstance(current, dict) and isinstance(value, dict)`` par un simple ``merged[key] = value``
rend ROUGE `test_a_child_keeps_the_nested_keys_it_does_not_redeclare`. Restaurer → VERT. Purger
`__pycache__` si la mutation a la même longueur que l'original.
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest

from config_loader import ConfigLoader, _deep_merge_profile


# ── LA FUSION PROFONDE, EN ISOLATION ────────────────────────────────────────────────────────


def test_a_child_keeps_the_nested_keys_it_does_not_redeclare() -> None:
    """Le cœur du mécanisme : surcharger une clé d'un bloc n'efface pas ses voisines."""
    parent = {"model_params": {"n_epochs": 4, "gamma": 0.99, "vf_coef": 0.5}}
    enfant = {"model_params": {"vf_coef": 0.15}}

    fusionne = _deep_merge_profile(parent, enfant)

    assert fusionne["model_params"] == {"n_epochs": 4, "gamma": 0.99, "vf_coef": 0.15}


def test_a_scalar_of_the_child_replaces_a_dict_of_the_parent() -> None:
    """Une rampe remplacée par une constante : le cas d'usage même du profil de lignée."""
    parent = {"model_params": {"ent_coef": {"start": 0.1, "end": 0.01, "decay_fraction": 0.4}}}
    enfant = {"model_params": {"ent_coef": 0.03}}

    fusionne = _deep_merge_profile(parent, enfant)

    assert fusionne["model_params"]["ent_coef"] == pytest.approx(0.03)


def test_the_merge_mutates_neither_side() -> None:
    """Les deux viennent du JSON chargé, que l'appelant relit pour chaque profil de la chaîne."""
    parent = {"model_params": {"vf_coef": 0.5}}
    enfant = {"model_params": {"vf_coef": 0.15}}

    _deep_merge_profile(parent, enfant)

    assert parent["model_params"]["vf_coef"] == pytest.approx(0.5)
    assert enfant["model_params"]["vf_coef"] == pytest.approx(0.15)


# ── LA RÉSOLUTION, PAR LE VRAI CHARGEUR ─────────────────────────────────────────────────────


def _loader_sur(tmp_path, profils: Dict[str, Any]) -> ConfigLoader:
    """Un `ConfigLoader` dont le dossier de config ne porte que l'agent fabriqué ici."""
    agent = "AgentDeTest"
    dossier = tmp_path / "agents" / agent
    dossier.mkdir(parents=True)
    (dossier / f"{agent}_training_config.json").write_text(
        json.dumps(profils), encoding="utf-8"
    )
    loader = ConfigLoader.__new__(ConfigLoader)
    loader.config_dir = tmp_path
    loader._cache = {}
    return loader


_PARENT = {
    "total_episodes": 100000,
    "n_envs": 24,
    "agent_seat_p2_ratio": 0.75,
    "model_params": {
        "n_epochs": 4,
        "gamma": 0.99,
        "vf_coef": 0.5,
        "ent_coef": {"start": 0.1, "end": 0.01, "decay_fraction": 0.4},
    },
}


def test_a_profile_that_extends_gets_the_keys_of_its_parent(tmp_path) -> None:
    loader = _loader_sur(tmp_path, {
        "base": _PARENT,
        "enfant": {"extends": "base", "model_params": {"vf_coef": 0.15, "ent_coef": 0.03}},
    })

    resolu = loader.load_agent_training_config("AgentDeTest", "enfant")

    assert resolu["n_envs"] == 24, "clé de premier niveau non héritée"
    assert resolu["total_episodes"] == 100000
    assert resolu["agent_seat_p2_ratio"] == pytest.approx(0.75)
    assert resolu["model_params"]["n_epochs"] == 4, "clé imbriquée non héritée"
    assert resolu["model_params"]["gamma"] == pytest.approx(0.99)
    assert resolu["model_params"]["vf_coef"] == pytest.approx(0.15), "surcharge non appliquée"
    assert resolu["model_params"]["ent_coef"] == pytest.approx(0.03)


def test_the_extends_key_does_not_survive_the_resolution(tmp_path) -> None:
    """Elle décrit la construction du profil, pas le run.

    La laisser obligerait chaque consommateur — et chaque test qui compare deux profils — à la
    connaître pour l'écarter.
    """
    loader = _loader_sur(tmp_path, {"base": _PARENT, "enfant": {"extends": "base"}})

    resolu = loader.load_agent_training_config("AgentDeTest", "enfant")

    assert "extends" not in resolu


def test_a_profile_without_extends_is_returned_as_is(tmp_path) -> None:
    """VERT VACANT évité : le mécanisme ne doit rien changer aux six profils qui n'héritent pas."""
    loader = _loader_sur(tmp_path, {"base": _PARENT})

    resolu = loader.load_agent_training_config("AgentDeTest", "base")

    assert resolu == _PARENT


def test_a_chain_of_two_levels_is_resolved_oldest_first(tmp_path) -> None:
    """Chaque descendant écrase ce qu'il redéclare, et seulement cela."""
    loader = _loader_sur(tmp_path, {
        "base": _PARENT,
        "milieu": {"extends": "base", "model_params": {"vf_coef": 0.25, "gamma": 0.95}},
        "feuille": {"extends": "milieu", "model_params": {"vf_coef": 0.15}},
    })

    resolu = loader.load_agent_training_config("AgentDeTest", "feuille")

    assert resolu["model_params"]["vf_coef"] == pytest.approx(0.15), "la feuille doit gagner"
    assert resolu["model_params"]["gamma"] == pytest.approx(0.95), "le milieu doit gagner"
    assert resolu["model_params"]["n_epochs"] == 4, "la base doit rester"


def test_the_whole_file_is_returned_unresolved(tmp_path) -> None:
    """Une lecture SANS phase rend la carte des profils telle qu'elle est écrite.

    Ses deux appelants n'en lisent que les NOMS — liste des profils disponibles dans
    `ai/train.py`, menus de `services/api_server.py`.
    """
    loader = _loader_sur(tmp_path, {"base": _PARENT, "enfant": {"extends": "base"}})

    fichier = loader.load_agent_training_config("AgentDeTest")

    assert set(fichier) == {"base", "enfant"}
    assert fichier["enfant"] == {"extends": "base"}


# ── LES CHAÎNES CASSÉES LÈVENT, JAMAIS DE PROFIL NON RÉSOLU ─────────────────────────────────


def test_an_unknown_parent_is_refused(tmp_path) -> None:
    """Retomber sur le profil nu ferait tourner le run sous un régime que personne n'a écrit."""
    loader = _loader_sur(tmp_path, {"base": _PARENT, "enfant": {"extends": "absent"}})

    # `ValueError` et non `KeyError` : le chargeur lève déjà un `KeyError` pour une PHASE
    # inconnue, et ses appelants le lisent comme « profil inconnu ». Les confondre enverrait
    # corriger la ligne de commande alors que le défaut est dans le fichier.
    with pytest.raises(ValueError, match="absent") as leve:
        loader.load_agent_training_config("AgentDeTest", "enfant")
    assert not isinstance(leve.value, KeyError), (
        "un parent inconnu ne doit pas se confondre avec une phase inconnue"
    )


def test_a_cycle_is_refused(tmp_path) -> None:
    loader = _loader_sur(tmp_path, {
        "a": {"extends": "b", "n_envs": 1},
        "b": {"extends": "a", "n_envs": 2},
    })

    with pytest.raises(ValueError, match="Cycle"):
        loader.load_agent_training_config("AgentDeTest", "a")


def test_a_profile_that_extends_itself_is_refused(tmp_path) -> None:
    loader = _loader_sur(tmp_path, {"seul": {"extends": "seul", "n_envs": 1}})

    with pytest.raises(ValueError, match="Cycle"):
        loader.load_agent_training_config("AgentDeTest", "seul")


def test_a_non_string_parent_is_refused(tmp_path) -> None:
    loader = _loader_sur(tmp_path, {"base": _PARENT, "enfant": {"extends": 4080}})

    with pytest.raises(TypeError, match="extends"):
        loader.load_agent_training_config("AgentDeTest", "enfant")


def test_a_parent_that_is_not_an_object_is_refused(tmp_path) -> None:
    loader = _loader_sur(tmp_path, {"_note": "prose", "enfant": {"extends": "_note"}})

    with pytest.raises(TypeError, match="_note"):
        loader.load_agent_training_config("AgentDeTest", "enfant")
