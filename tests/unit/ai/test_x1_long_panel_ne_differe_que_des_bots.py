"""`x1_long_panel` ne doit différer de `x1_long` QUE par les adversaires.

C'est l'invariant dont dépend l'expérience du §12.16 du chantier des bots : mesurer si le panel
refondu est vraiment plus dur, ou seulement jamais affronté. La comparaison ne vaut que si le
SEUL facteur qui change entre un run `x1_long` et un run `x1_long_panel` est le panel — mêmes
hyperparamètres, même budget, mêmes rampes, même graine.

Une divergence installée plus tard (un `learning_rate` retouché d'un côté, un `total_episodes`
arrondi) ne se verrait pas : elle produirait deux chiffres qu'on comparerait quand même. C'est
exactement ce qui est arrivé à `x1_panel`, dont le plancher de `learning_rate` est resté à 0.0002
quand les quatre profils de la chaîne sont passés à 0.0005 le 2026-08-12 — personne ne l'a vu
parce qu'aucun test ne l'appariait à quoi que ce soit.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CONFIG = PROJECT_ROOT / "config" / "agents" / "ArmageddonAgent" / "ArmageddonAgent_training_config.json"

#: Clés dont la divergence est VOULUE, et la raison de chacune. Toute autre différence est une
#: dérive. La liste est volontairement close : y ajouter une entrée est une décision, pas un
#: ajustement pour faire passer le test.
DIVERGENCES_VOULUES = {
    "type": "en-tête du profil",
    "_justification_x1_long_panel": "explique le profil, absent de x1_long",
    "bot_training": "LE facteur mesuré : les adversaires d'entraînement",
}
DIVERGENCES_VOULUES_CALLBACK = {
    "bot_eval_weights": "LE facteur mesuré : les adversaires d'évaluation",
    "bot_eval_randomness": "va avec bot_eval_weights, une entrée par bot pondéré",
    "model_gating_min_vs_control": (
        "désarmé à 0.0 : le plancher fait require_key(results, 'control') même gating éteint, "
        "et `control` n'est pas dans ce panel — il aurait levé à la 1re évaluation"
    ),
}


@pytest.fixture(scope="module")
def profils() -> dict:
    return json.loads(_CONFIG.read_text(encoding="utf-8"))


def test_x1_long_panel_existe(profils):
    assert "x1_long_panel" in profils


def test_ne_diverge_que_sur_les_cles_voulues(profils):
    ref, var = profils["x1_long"], profils["x1_long_panel"]
    divergences = {
        k for k in set(ref) | set(var)
        if k == "callback_params" or ref.get(k) != var.get(k)
    } - {"callback_params"}

    assert divergences == set(DIVERGENCES_VOULUES), (
        f"divergences inattendues : {sorted(divergences - set(DIVERGENCES_VOULUES))} ; "
        f"attendues mais absentes : {sorted(set(DIVERGENCES_VOULUES) - divergences)}"
    )


def test_callback_params_ne_diverge_que_sur_les_cles_voulues(profils):
    ref = profils["x1_long"]["callback_params"]
    var = profils["x1_long_panel"]["callback_params"]
    divergences = {k for k in set(ref) | set(var) if ref.get(k) != var.get(k)}

    assert divergences == set(DIVERGENCES_VOULUES_CALLBACK), (
        f"divergences inattendues : {sorted(divergences - set(DIVERGENCES_VOULUES_CALLBACK))}"
    )


def test_le_budget_et_la_graine_sont_ceux_de_x1_long(profils):
    """Les deux grandeurs qui rendraient les deux runs incomparables si elles bougeaient."""
    ref, var = profils["x1_long"], profils["x1_long_panel"]
    assert var["total_episodes"] == ref["total_episodes"] == 50000
    assert var["seed"] == ref["seed"]


def test_le_panel_est_le_meme_des_deux_cotes(profils):
    """Entraînement et évaluation doivent porter LES MÊMES six styles.

    S'entraîner contre un panel et se mesurer contre un autre rendrait un chiffre qui ne répond
    à aucune des deux questions.
    """
    from ai.bot_registry import DOCTRINE_BOT_KEYS

    var = profils["x1_long_panel"]
    entrainement = {k for k in var["bot_training"]["ratios"] if k != "random"}
    evaluation = set(var["callback_params"]["bot_eval_weights"])

    assert entrainement == evaluation == set(DOCTRINE_BOT_KEYS)


def test_les_ratios_tombent_juste_sur_le_pool_de_cent(profils):
    """`_build_training_bots_from_config` fait `round(ratio * 100)` : un ratio qui n'est pas un
    centième déforme la fréquence réelle de l'adversaire (le défaut du pool de 10, déjà payé)."""
    ratios = profils["x1_long_panel"]["bot_training"]["ratios"]

    assert sum(ratios.values()) == pytest.approx(1.0)
    assert sum(round(r * 100) for r in ratios.values()) == 100
    for nom, r in ratios.items():
        assert round(r * 100) == pytest.approx(r * 100), f"{nom}={r} n'est pas un centième"


def test_le_profil_construit_reellement_ses_bots(profils):
    """VERT VACANT : les six tests ci-dessus lisent du JSON. Celui-ci vérifie que le profil
    PRODUIT le pool d'adversaires — c'est le chemin qui levait « Unknown bot name in ratios »."""
    from collections import Counter

    import ai.train as train
    from ai.bot_registry import BOT_DISPLAY_NAMES

    bots = train._build_training_bots_from_config(profils["x1_long_panel"])
    classes = Counter(type(b).__name__ for b in bots)

    assert len(bots) == 100
    for cle in profils["x1_long_panel"]["bot_training"]["ratios"]:
        attendu = "RandomBot" if cle == "random" else BOT_DISPLAY_NAMES[cle]
        assert classes[attendu] > 0, cle
