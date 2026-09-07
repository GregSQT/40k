"""Verrou — chaque étape de curriculum exige SON profil d'entraînement, et le refus est dur.

Une étape qui démarre à froid et une étape qui reprend des poids n'ont pas le même régime
d'optimisation : rampes d'exploration pour une politique naïve dont le critic part de zéro,
scalaires constants pour un modèle déjà entraîné. Se tromper de profil ne casse rien de visible —
le run démarre, tourne des heures, et rend un modèle formé sous un régime que personne n'a voulu.

MESURE QUI L'IMPOSE, 2026-09-04 : une étape reprise a reparcouru la rampe d'entropie du profil
depuis son départ. P1 s'était arrêtée vers `ent_coef` 0,018, P2 est repartie à 0,100 ;
l'évaluation bots est tombée de 0,911 à 0,694 et le score contre P1 — garanti à 0,50 par
construction, puisque P2 EST P1 à l'épisode 0 — est tombé à 0,118. La politique promue était
détruite avant d'avoir rencontré son adversaire.

Le curriculum nomme les deux profils dans son bloc `training_configs` ; le fichier de profils
porte les valeurs, `x1_lineage` héritant de `x1_long` par `extends`. Ce fichier verrouille les
deux bouts : le nom qu'une étape exige, et ce que le profil ainsi nommé contient réellement.

PREUVE PAR MUTATION : dans `ai/train.py::_prepare_curriculum_stage`, supprimer le `raise` du
contrôle `args.training_config != expected_training_config` rend ROUGE
`test_the_wrong_profile_is_refused_before_anything_is_built`. Restaurer → VERT.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from ai.curriculum import (
    load_curriculum,
    require_stage,
    required_training_config,
    stage_order,
)
from config_loader import get_config_loader

AGENT = "ArmageddonAgent_x1"


@pytest.fixture(scope="module")
def curriculum() -> Dict[str, Any]:
    return load_curriculum(AGENT)


@pytest.fixture(scope="module")
def profil_lignee() -> Dict[str, Any]:
    """Le profil de lignée RÉSOLU, `extends` appliqué — ce que le run recevra."""
    return get_config_loader().load_agent_training_config(AGENT, "x1_lineage")


@pytest.fixture(scope="module")
def profil_froid() -> Dict[str, Any]:
    return get_config_loader().load_agent_training_config(AGENT, "x1_long")


# ── QUEL PROFIL CHAQUE ÉTAPE EXIGE ──────────────────────────────────────────────────────────


def test_only_the_cold_started_stage_asks_for_the_cold_profile(curriculum) -> None:
    """Le critère est l'`init`, et lui seul. Une étape ne le déclare jamais elle-même.

    Le dériver de la chaîne plutôt que de le déclarer par étape est ce qui empêche la contrainte
    de se désynchroniser : il n'y a pas de seconde liste à tenir à jour quand la chaîne bouge.
    """
    par_profil: Dict[str, list] = {}
    for name in stage_order(curriculum):
        profil = required_training_config(curriculum, require_stage(curriculum, name))
        par_profil.setdefault(profil, []).append(name)

    assert par_profil["x1_long"] == ["P0"]
    assert set(par_profil["x1_lineage"]) == set(stage_order(curriculum)) - {"P0"}
    # VERT VACANT évité : les deux natures existent et portent des noms DIFFÉRENTS, donc une
    # implémentation qui rendrait une constante échouerait ici.
    assert len(par_profil) == 2, sorted(par_profil)
    assert len(par_profil["x1_lineage"]) == 13


def test_the_exploiters_take_the_lineage_profile_like_the_learners(curriculum) -> None:
    """Un exploiteur reprend les poids de P0 : c'est une reprise à chaud comme une autre.

    Lui laisser les rampes du profil de démarrage rendrait à un modèle déjà entraîné le régime
    d'exploration d'un run neuf — la destruction mesurée le 2026-09-04.
    """
    for name in ("E1", "E2", "E3"):
        stage = require_stage(curriculum, name)
        assert stage["role"] == "exploiter", name
        assert required_training_config(curriculum, stage) == "x1_lineage", name


# ── CE QUE LE PROFIL DE LIGNÉE CONTIENT ─────────────────────────────────────────────────────


def test_the_lineage_profile_pins_the_six_values_of_the_regime(profil_lignee) -> None:
    """Les valeurs décidées le 2026-09-07, épinglées depuis la spécification.

    Ce ne sont pas « des valeurs par défaut » : elles remplacent vingt rampes `decay_fraction` et
    les surcharges d'étape de `vf_coef` / `max_grad_norm`, et c'est leur UNIFORMITÉ sur toute la
    lignée qui rend deux étapes comparables. Un réglage qui reviendrait se poser sur une seule
    étape rouvrirait exactement ce que cette conception ferme.
    """
    mp = profil_lignee["model_params"]
    assert mp["learning_rate"] == pytest.approx(0.001)
    assert mp["ent_coef"] == pytest.approx(0.03)
    assert mp["n_steps"] == 32640
    assert mp["batch_size"] == 4080
    assert mp["vf_coef"] == pytest.approx(0.15)
    assert profil_lignee["agent_seat_p2_ratio"] == pytest.approx(0.6)


def test_the_lineage_profile_carries_scalars_never_ramps(profil_lignee) -> None:
    """Un scalaire ne crée AUCUN callback de rampe : la valeur tient tout le run.

    `setup_callbacks` ne construit `EntropyScheduleCallback` / `LearningRateScheduleCallback` que
    sur un dict. Un dict ici réintroduirait la rampe que toute cette conception supprime.
    """
    for cle in ("learning_rate", "ent_coef"):
        valeur = profil_lignee["model_params"][cle]
        assert isinstance(valeur, (int, float)) and not isinstance(valeur, bool), (
            f"{cle} vaut {valeur!r} : une rampe, pas un scalaire"
        )


def test_the_lineage_profile_inherits_everything_it_does_not_redeclare(
    profil_lignee, profil_froid
) -> None:
    """Le point même de l'héritage : aucune des quinze clés partagées n'est recopiée.

    Avant `extends`, deux profils voisins dupliquaient quinze clés — 15,1 Ko — que seul un test
    empêchait de diverger. Un septième profil écrit à plat aurait ajouté une septième copie.
    """
    surcharge = {"model_params", "agent_seat_p2_ratio", "type", "_doc"}
    partagees = [
        cle for cle in profil_froid
        if cle not in surcharge and not cle.endswith(("_normal", "_detail"))
    ]
    assert len(partagees) >= 12, f"trop peu de clés comparées : {partagees}"
    divergentes = {
        cle: (profil_froid[cle], profil_lignee.get(cle))
        for cle in partagees
        if profil_lignee.get(cle) != profil_froid[cle]
    }
    assert not divergentes, f"clés non héritées : {sorted(divergentes)}"

    # Et dans `model_params`, tout ce que la lignée ne redéclare pas vient aussi du parent.
    for cle in ("n_epochs", "gamma", "gae_lambda", "clip_range", "target_kl", "max_grad_norm"):
        assert profil_lignee["model_params"][cle] == profil_froid["model_params"][cle], cle


def test_the_cold_profile_keeps_its_ramps(profil_froid) -> None:
    """VERT VACANT évité : sans cette assertion, les deux profils pourraient être identiques."""
    assert isinstance(profil_froid["model_params"]["ent_coef"], dict)
    assert isinstance(profil_froid["model_params"]["learning_rate"], dict)
    assert profil_froid["model_params"]["vf_coef"] == pytest.approx(0.5)
    assert profil_froid["agent_seat_p2_ratio"] == pytest.approx(0.75)


# ── LE REFUS EST DUR, ET IL TOMBE AVANT TOUT LE RESTE ───────────────────────────────────────


class _Args:
    """Les seuls attributs que `_prepare_curriculum_stage` lit avant le contrôle de profil."""

    def __init__(self, etape: str, training_config: str) -> None:
        self.agent = AGENT
        self.etape = etape
        self.training_config = training_config
        self.resume_from = None
        self.new = False
        self.append = False


@pytest.mark.parametrize(
    "etape,mauvais",
    [("P2", "x1_long"), ("P0", "x1_lineage"), ("E1", "x1_long"), ("P10", "x1_debug")],
)
def test_the_wrong_profile_is_refused_before_anything_is_built(etape: str, mauvais: str) -> None:
    """Le refus tombe dans `_prepare_curriculum_stage`, avant tout environnement ou modèle.

    Laisser le run démarrer coûterait des heures pour un modèle formé sous le mauvais régime, et
    rien d'autre ne lèverait : un profil est un profil, il se charge parfaitement.
    """
    from ai.train import _prepare_curriculum_stage

    with pytest.raises(ValueError, match="--training-config"):
        _prepare_curriculum_stage(_Args(etape, mauvais), get_config_loader())


@pytest.mark.parametrize("etape,mauvais", [("P2", "x1_long"), ("P0", "x1_debug")])
def test_closing_a_stage_refuses_the_wrong_profile_too(
    curriculum, etape: str, mauvais: str
) -> None:
    """`--close-stage` saute `_prepare_curriculum_stage` : le contrôle doit y être reposé.

    La clôture LIT le profil — `callback_params` pour les workers du gate, `eval_episodes` — donc
    un profil de mise au point y mesurerait et promouvrait l'étape sous des paramètres
    d'évaluation qui ne sont pas les siens, sans qu'aucun refus ne tombe.
    """
    import ai.train as train_module

    # Par `main()` et son argv, pas par un appel direct a la fonction : ce test verrouille le
    # CABLAGE de la branche `--close-stage`, pas la fonction — qui est deja couverte plus haut.
    # Retirer l'appel de cette branche doit rougir ici ; un test qui appellerait la fonction
    # resterait vert et ne prouverait rien.
    argv = [
        "ai/train.py", "--agent", AGENT, "--training-config", mauvais,
        "--scenario", "bot", "--etape", etape, "--close-stage",
    ]
    with pytest.raises(ValueError, match="--training-config"):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("sys.argv", argv)
            train_module.main()


@pytest.mark.parametrize("cle", ["learning_rate", "ent_coef"])
def test_a_ramp_inherited_by_the_lineage_profile_is_refused(cle: str) -> None:
    """Un profil de lignée qui HÉRITE d'une rampe au lieu de la surcharger est refusé au run.

    C'est le mode d'échec propre à l'héritage : retirer `learning_rate` de `x1_lineage` ne laisse
    pas un trou, cela lui rend la rampe de `x1_long`. Rien ne manque nulle part, et le run entier
    tourne sous le régime que cette conception supprime. Le test qui épingle les valeurs du
    profil ne couvre pas ce cas — il vérifie le profil livré, pas celui qu'on passera au run.
    """
    from ai.train import _require_scalar_lineage_regime

    herite = dict(get_config_loader().load_agent_training_config(AGENT, "x1_lineage")["model_params"])
    herite[cle] = get_config_loader().load_agent_training_config(AGENT, "x1_long")["model_params"][cle]

    with pytest.raises(ValueError, match=cle):
        _require_scalar_lineage_regime(herite, "x1_lineage", "P2")


def test_the_delivered_lineage_profile_passes_the_scalar_control(profil_lignee) -> None:
    """VERT VACANT évité : le contrôle doit laisser passer le profil réel."""
    from ai.train import _require_scalar_lineage_regime

    _require_scalar_lineage_regime(profil_lignee["model_params"], "x1_lineage", "P2")


def test_a_curriculum_without_the_block_imposes_nothing(curriculum) -> None:
    """Un curriculum entièrement à froid n'a pas de bloc, et le validateur l'accepte.

    Exiger le bloc au lancement rendrait injouable un curriculum que `validate_curriculum` vient
    d'accepter — les deux contrôles doivent dire la même chose.
    """
    from ai.train import _require_stage_training_config

    sans_bloc = {k: v for k, v in curriculum.items() if k != "training_configs"}
    stage = require_stage(sans_bloc, "P0")
    assert required_training_config(sans_bloc, stage) is None
    _require_stage_training_config(_Args("P0", "x1_debug"), sans_bloc, stage)  # ne lève pas


@pytest.mark.parametrize("etape,attendu", [("P0", "x1_long"), ("P2", "x1_lineage")])
def test_the_right_profile_passes_the_control(etape: str, attendu: str, monkeypatch) -> None:
    """VERT VACANT évité : le contrôle doit LAISSER PASSER le bon profil.

    Sans ce test, un refus inconditionnel serait vert sur tous les cas ci-dessus.

    `monkeypatch` sur la méthode du chargeur, et ce n'est pas de la précaution : passer le
    singleton `get_config_loader()` à `_prepare_curriculum_stage` lui fait remplacer
    `load_agent_training_config` par la fermeture de `_install_stage_config_overrides` — sur
    l'objet partagé par tout le processus, et sans restauration. Chaque test suivant du même
    worker lirait alors une config portant les surcharges de CETTE étape, et les deux
    paramétrages empileraient deux décorateurs.
    """
    from ai.train import _prepare_curriculum_stage

    loader = get_config_loader()
    monkeypatch.setattr(
        type(loader),
        "load_agent_training_config",
        type(loader).load_agent_training_config,
        raising=True,
    )
    monkeypatch.setattr(
        loader, "load_agent_training_config", loader.load_agent_training_config, raising=False
    )
    try:
        _prepare_curriculum_stage(_Args(etape, attendu), loader)
    except ValueError as exc:
        if "--training-config" in str(exc):
            pytest.fail(f"le bon profil {attendu} a été refusé pour {etape} : {exc}")
    except FileNotFoundError:
        # Le modèle source de l'étape peut être absent de ce poste : c'est APRÈS le contrôle de
        # profil, donc le contrôle a bien laissé passer.
        pass
