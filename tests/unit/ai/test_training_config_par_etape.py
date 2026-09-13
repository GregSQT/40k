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
    exploiter_stage_names,
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
def noms_exploiteurs(curriculum) -> list:
    """Les etapes exploiteur LUES du curriculum, jamais une liste ecrite ici.

    Une liste en dur laisserait une etape ajoutee plus tard hors des verrous ci-dessous : le
    fichier resterait VERT en ne mesurant rien d'elle, alors que `validate_exploiter_protocol`
    la refuserait au lancement du run. C'est le curriculum qui dit qui sont les exploiteurs.
    """
    noms = exploiter_stage_names(curriculum)
    assert noms, "curriculum sans etape exploiteur : les verrous exploiteur ne mesureraient rien"
    return noms


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

    Les exploiteurs sont couverts ici comme les learners, et c'est voulu : un exploiteur reprend
    les poids de P0, donc c'est une reprise à chaud comme une autre. Lui laisser les rampes du
    profil de démarrage rendrait à un modèle déjà entraîné le régime d'exploration d'un run neuf
    — la destruction mesurée le 2026-09-04.
    """
    par_profil: Dict[str, list] = {}
    for name in stage_order(curriculum):
        profil = required_training_config(curriculum, require_stage(curriculum, name))
        assert profil is not None, f"étape {name!r} sans profil d'entraînement requis"
        par_profil.setdefault(profil, []).append(name)

    assert par_profil["x1_long"] == ["P0"]
    assert set(par_profil["x1_lineage"]) == set(stage_order(curriculum)) - {"P0"}
    # VERT VACANT évité : les deux natures existent et portent des noms DIFFÉRENTS, donc une
    # implémentation qui rendrait une constante échouerait ici.
    assert len(par_profil) == 2, sorted(par_profil)
    assert len(par_profil["x1_lineage"]) == 13


def test_exploiter_budget_cap_never_exceeds_lineage_profile_total_episodes(
    curriculum, profil_lignee, noms_exploiteurs
) -> None:
    """Le profil de lignee doit pouvoir atteindre le budget_cap : total_episodes >= budget_cap.

    Un profil trop court rend la branche '>budget_cap' inatteignable, et le marqueur de censure
    n'est jamais emis. validate_exploiter_protocol le refuse avant le premier episode.
    training_config_overrides etant interdit sur les exploiteurs, la seule correction valide
    est de porter total_episodes dans le profil lui-meme.
    """
    total_ep = profil_lignee["total_episodes"]
    for name in noms_exploiteurs:
        stage = require_stage(curriculum, name)
        budget_cap = stage["budget_cap"]
        assert total_ep >= budget_cap, (
            f"{name}: x1_lineage.total_episodes={total_ep} < budget_cap={budget_cap} — "
            "augmenter total_episodes dans x1_lineage."
        )


# ── CE QUE LE PROFIL DE LIGNÉE CONTIENT ─────────────────────────────────────────────────────


def test_the_lineage_profile_pins_the_values_of_the_regime(profil_lignee) -> None:
    """Les valeurs du régime de lignée, épinglées depuis le `_doc` du profil (révision 2026-09-08).

    Ce ne sont pas « des valeurs par défaut » : elles remplacent vingt rampes `decay_fraction` et
    les surcharges d'étape de `vf_coef` / `max_grad_norm`, et c'est leur UNIFORMITÉ sur toute la
    lignée qui rend deux étapes comparables. Un réglage qui reviendrait se poser sur une seule
    étape rouvrirait exactement ce que cette conception ferme.

    Trois valeurs ont été redécidées le 2026-09-08, chacune sur une mesure inscrite dans le `_doc` :
    `n_steps` 32640 → 8160 (les 55 updates du run P2 du 2026-09-07 ont TOUTES été coupées par
    l'early-stop `target_kl`, soit une epoch sur quatre : le rollout quadruplé divisait par quatre
    l'apprentissage par épisode), `ent_coef` 0.03 → 0.01 et `vf_coef` 0.15 → 0.17.

    Trois valeurs redécidées le 2026-09-13 (run S23, dossier `plafonnement_p1.md` §7, mesure
    `scripts/grad_signal_probe.py`) : `n_steps` 8160 → 32640, `batch_size` 1020 → 2040 (surchargé
    à nouveau) et `gae_lambda` 0.95 → 0.2 (surchargé pour la première fois). Le gradient d'une
    update était du bruit à 98 % ; λ court ET lot ×4 ensemble prédisent f ≈ 0,18. Pas 4080 : la VRAM
    mesurée à 4080 (7,47 Go réservés sur 8,19 partagés avec l'hôte) replanterait comme le 2026-09-07,
    où le pic atteignait 8,89 Go — `CUDA driver error: device not ready` que rien ne rattachait à
    `batch_size`. Aucun garde-fou ne rattrape ce cas : `apply_rollout_n_steps` dimensionne sur la
    RAM SYSTÈME. 2040 = 16 mini-lots, la coupure KL à ~15 pas couvre une epoch entière.
    """
    mp = profil_lignee["model_params"]
    assert mp["learning_rate"] == pytest.approx(0.001)
    assert mp["ent_coef"] == pytest.approx(0.01)
    assert mp["n_steps"] == 32640
    assert mp["batch_size"] == 2040
    assert mp["gae_lambda"] == pytest.approx(0.2)
    assert mp["vf_coef"] == pytest.approx(0.17)
    # 12 envs (2026-09-13 23:55) : la RAM d'un rollout est proportionnelle au rollout TOTAL (chaque
    # worker garde sa trajectoire, le learner en tient 3 copies) ; 24 puis 16 envs ont été tués par
    # le watchdog à 1 et 2 Go disponibles. 32 640 / 12 = 2 720 pas par env, rollout divisible par le lot.
    assert profil_lignee["n_envs"] == 12
    assert (mp["n_steps"] // profil_lignee["n_envs"] * profil_lignee["n_envs"]) % mp["batch_size"] == 0
    # 0.70 depuis le 2026-09-11 (0.6 du 2026-09-07 au 2026-09-11), réglage posé par l'utilisateur.
    assert profil_lignee["agent_seat_p2_ratio"] == pytest.approx(0.7)


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
    # `n_envs` surchargé depuis le 2026-09-13 (12) : le coût RAM du rollout de 32 640 est porté par
    # les workers (trajectoire locale) et le learner (3 copies) ; 24 envs ont mis la VM à 1 Go (`_doc`).
    surcharge = {"model_params", "agent_seat_p2_ratio", "type", "_doc", "total_episodes", "n_envs"}
    partagees = [
        cle for cle in profil_froid
        if cle not in surcharge and not cle.endswith(("_normal", "_detail"))
    ]
    assert len(partagees) >= 11, f"trop peu de clés comparées : {partagees}"
    divergentes = {
        cle: (profil_froid[cle], profil_lignee.get(cle))
        for cle in partagees
        if profil_lignee.get(cle) != profil_froid[cle]
    }
    assert not divergentes, f"clés non héritées : {sorted(divergentes)}"

    # Et dans `model_params`, tout ce que la lignée ne redéclare pas vient aussi du parent.
    # `gae_lambda` et `batch_size` ne sont plus dans cette liste : surchargés depuis le 2026-09-13 (S23).
    for cle in ("n_epochs", "gamma", "clip_range", "target_kl", "max_grad_norm"):
        assert profil_lignee["model_params"][cle] == profil_froid["model_params"][cle], cle


def test_the_cold_profile_keeps_its_ramps(profil_froid) -> None:
    """VERT VACANT évité : sans ces assertions, les deux profils pourraient être identiques.

    Ce qui SÉPARE encore les deux profils : le froid exprime `ent_coef` et `learning_rate` en
    RAMPES là où la lignée pose des scalaires, et il sur-représente le siège faible (0.75 contre
    0.7). `vf_coef` ne les sépare plus — le 0.17 mesuré le 2026-09-08 a été porté dans `x1`,
    `x1_long` ET la lignée le même jour, la surcharge de la lignée n'étant plus qu'un rappel.
    """
    assert isinstance(profil_froid["model_params"]["ent_coef"], dict)
    assert isinstance(profil_froid["model_params"]["learning_rate"], dict)
    assert profil_froid["model_params"]["vf_coef"] == pytest.approx(0.17)
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

    loader = get_config_loader()
    herite = dict(loader.load_agent_training_config(AGENT, "x1_lineage")["model_params"])
    herite[cle] = loader.load_agent_training_config(AGENT, "x1_long")["model_params"][cle]

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
