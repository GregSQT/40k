"""Helpers de config partagés pour les tests moteur.

But : éviter que chaque fixture réinvente un sous-ensemble de ``game_rules`` qui
diverge du contrat moteur réel. Les fixtures partent désormais des vraies règles
(config/game_config.json) et n'overrident que les valeurs sensibles au test.
Conséquence : l'ajout d'une nouvelle règle requise (ex: detection_range) ne casse
plus les tests — la clé est présente automatiquement.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from config_loader import require_engine_game_config_sections

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "game_config.json"


def _read_game_config() -> Dict[str, Any]:
    """Relecture FRAÎCHE du fichier, à chaque appel.

    Volontairement PAS `get_config_loader().get_game_config()` : le loader mémoïse et rend une
    référence partagée par tout le process. Or des tests mutent les sous-dicts en place
    (`cfg["game_rules"]["engagement_zone"] = 2`, `gs["config"]["game_rules"]["max_turns"] = 5`) —
    ils contamineraient les tests suivants. Le moteur se protège du même piège en `copy.deepcopy`
    avant de scaler (`w40k_core`, « cumulative ×10 on each game restart »).
    """
    return json.loads(_CONFIG_PATH.read_text())


def _real_game_rules() -> Dict[str, Any]:
    return _read_game_config()["game_rules"]


def build_game_rules(**overrides: Any) -> Dict[str, Any]:
    """``game_rules`` réels (toutes les clés requises par le moteur) + overrides de test.

    Les overrides servent à neutraliser les valeurs sensibles aux tests
    (ex: cover_ratio=0.0, engagement_zone=1).
    """
    rules = _real_game_rules()
    rules.update(overrides)
    return rules


#: Faction d'Armée NEUTRE des tests, à l'unité : le mot-clé que les fixtures posent dans leurs
#: `FACTION_KEYWORDS`.
#:
#: Ce n'est PAS une valeur de repli anti-erreur. `army_faction` (`engine/game_state.py`) exige une
#: DÉCLARATION et refuse de la deviner depuis les unités présentes — c'est le défaut corrigé le
#: 2026-08-06. Une fixture qui construit sa config en mémoire ne passe par aucun fichier de
#: scénario ni par aucun roster : elle doit donc porter cette déclaration elle-même, et c'est
#: exactement ce que fait un roster de production (`"army_faction"` en tête de fichier).
#:
#: POURQUOI TYRANIDS. Les unités de fixture sont des `TestUnit` génériques, sans identité de
#: faction. Leur coller ADEPTUS ASTARTES leur en inventerait une ET armerait l'Oath of Moment à
#: chaque phase de commandement dans 45 fichiers qui ne l'ont pas demandé — un déplacement de
#: comportement, pas une correction. TYRANIDS est la seule des trois factions du dépôt à ne porter
#: AUCUNE capacité de commandement (ni Waaagh! ni Oath), donc 08.04 se comporte pour ces fixtures
#: comme pour une armée sans capacité de faction : leur état d'avant.
#:
#: CE N'EST PAS UN VERT VACANT. 08.04 reste exercé pour de vrai ailleurs : `build_armageddon_engine`
#: joue le scénario RÉEL (rosters `..._space_marines.json`, `ADEPTUS ASTARTES` des deux côtés, Oath
#: armé), et `test_faction_abilities` / `test_army_faction_declaration` déclarent leur propre
#: faction — `config` gagne sur ce socle (cf. `merged.update(config)`).
NEUTRAL_TEST_FACTION = "TYRANIDS"

#: La même chose sous la forme attendue par `config["army_faction"]` : un mot-clé PAR JOUEUR.
#: `build_engine_config` la pose d'office ; les fixtures qui bâtissent un `game_state` LITTÉRAL,
#: sans passer par ce helper, la déclarent elles-mêmes sous le nom `NEUTRAL_TEST_ARMY_FACTION`.
DEFAULT_TEST_ARMY_FACTION: Dict[str, str] = {
    "1": NEUTRAL_TEST_FACTION,
    "2": NEUTRAL_TEST_FACTION,
}

#: Alias de lecture pour ces fixtures à `game_state` littéral. Même valeur, même raison — un seul
#: endroit à changer si la faction neutre des tests change.
NEUTRAL_TEST_ARMY_FACTION = DEFAULT_TEST_ARMY_FACTION


def _declare_faction_on_units(config: Dict[str, Any], by_player: Dict[str, str]) -> None:
    """Appose sur les unités du test le mot-clé de la Faction d'Armée déclarée pour leur joueur.

    LA GARDE QU'ON SATISFAIT. `army_faction` refuse une faction que PERSONNE ne porte
    (« declare X, mais aucune unite du joueur N ne porte ce mot-cle ») : c'est sa garde
    anti-coquille, et elle est juste — une déclaration qu'aucune unité ne confirme est une faute de
    frappe. Un roster de production n'a pas ce problème : il déclare sa faction ET ses unités la
    portent. Une config de test en mémoire doit donc être cohérente de la même façon.

    Poser le mot-clé n'est PAS deviner la faction : le sens de lecture est l'inverse de celui qui
    a produit le défaut. Le moteur déduisait la déclaration des unités ; ici la déclaration est
    première et les unités s'y conforment, exactement comme dans un fichier de roster.

    Une unité qui déclare DÉJÀ ses `FACTION_KEYWORDS` est laissée intacte : le test l'a voulue
    ainsi (unité invitée d'une autre faction, cas 19.03), et l'écraser détruirait ce qu'il mesure.
    """
    for unit in config.get("units", ()):  # get allowed : une config sans `units` n'a rien à faire
        if "FACTION_KEYWORDS" in unit:
            continue
        declared = by_player.get(str(unit["player"]))
        if declared is not None:
            unit["FACTION_KEYWORDS"] = [declared]


def build_engine_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Config de moteur de test : le CONTRAT de production, surcharge par ce que le test déclare.

    Le moteur exige toutes les sections de
    ``config_loader.GAME_CONFIG_SECTIONS_REQUIRED_BY_ENGINE`` (``require_key`` au point de
    lecture — cf. ``GameStateManager.run_objective_control_checkpoint``). Un test qui construit
    sa config à la main n'en déclare qu'une partie : les autres viennent d'ici, telles qu'elles
    sont dans ``config/game_config.json``, donc le test tourne sur les VRAIES règles au lieu
    d'éteindre en silence celles qu'il ignore.

    Ce n'est pas un défaut anti-erreur : les sections que le test déclare gagnent intégralement,
    et une section absente du fichier de config lève toujours (``require_key``). C'est ce que
    faisaient déjà ``build_game_rules`` / ``build_move_rules``, généralisé à la config entière.

    ⚠️ Avant ce helper, 44 fichiers omettaient ``objective_control_check`` : le checkpoint 14.02
    y sortait à sa première ligne. Deux d'entre eux (``test_objective_held_samples``,
    ``test_zone_intent_control_axis``) PRÉTENDAIENT mesurer l'axe de contrôle d'objectif alors
    qu'aucun contrôle n'était jamais établi.
    """
    merged = require_engine_game_config_sections(_read_game_config())
    # Déclaration de scénario, posée AVANT l'override : cf. `DEFAULT_TEST_ARMY_FACTION`.
    merged["army_faction"] = dict(DEFAULT_TEST_ARMY_FACTION)
    merged.update(config)
    # APRÈS l'override : les unités doivent se conformer à la déclaration RETENUE, celle du test
    # quand il en pose une, pas au socle qu'elle vient de remplacer.
    _declare_faction_on_units(merged, merged["army_faction"])
    return merged


def _real_move_rules() -> Dict[str, Any]:
    return _read_game_config()["move"]


def build_move_rules(**overrides: Any) -> Dict[str, Any]:
    """``move`` réels (toggles de traversée, Règles 03.01) + overrides de test."""
    rules = _real_move_rules()
    rules.update(overrides)
    return rules


#: Scénario `deployment_type: active` réel. Le harnais habituel construit le moteur depuis une
#: config en mémoire, qui démarre TOUJOURS en placement fixe (`deployment_type` ne vient que
#: d'un fichier de scénario) : un test qui veut voir une phase de déploiement doit passer par un
#: fichier, sinon il observe un état qui ne se produit jamais et affiche « tout va bien » — le
#: VERT VACANT déjà payé en V11 §0.56.
ACTIVE_DEPLOYMENT_SCENARIO = (
    "config/agents/ArmageddonAgent/scenarios/holdout_regular/scenario_bot-01.json"
)


#: Racine de la banque de scénarios d'entraînement.
TRAINING_BANK = (
    Path(__file__).resolve().parents[3]
    / "config" / "agents" / "ArmageddonAgent" / "scenarios" / "training"
)


def bank_training_scenarios() -> List[str]:
    """Les scénarios d'entraînement « pleins » de la banque — un par TERRAIN, DÉCOUVERTS.

    Ils ne diffèrent que par leur `terrain_ref`. Tout test dont l'assertion lit le PLATEAU (murs,
    zones de déploiement, objectifs, couvert) doit tourner sur tous, sans quoi il ne dit rien du
    second terrain : le 2026-08-08, des positions de roster valides sur `terrain-mc1` tombaient
    sur un mur de `terrain-mc2` sans qu'un seul test bouge.

    DÉCOUVERTS et non listés : chaque liste littérale est un site à rééditer le jour où un
    `terrain-mc3` arrive, et celui qu'on oublie reste vert en ne couvrant plus la banque. Le
    motif de nom est celui du scénario de training (`scenario_training_*`), pas des fixtures
    `reserves_*` posées à côté (nommées hors motif exprès, chantier 04c).
    """
    found = sorted(str(p) for p in TRAINING_BANK.glob("scenario_training_*.json"))
    if not found:
        raise FileNotFoundError(
            f"Aucun scenario d'entrainement dans {TRAINING_BANK} — banque vide ou deplacee"
        )
    return found


#: Scénario d'ENTRAÎNEMENT réel, le pendant de `ACTIVE_DEPLOYMENT_SCENARIO` pour les tests qui
#: veulent la config et l'état du chemin gym plutôt qu'une phase de déploiement active. UN seul :
#: c'est le défaut des tests dont l'assertion ne lit PAS le plateau (contrats, caches, registres),
#: pour qui un second terrain ne serait qu'un doublement du temps d'exécution. Les autres passent
#: par `bank_training_scenarios()`.
TRAINING_SCENARIO = (
    "config/agents/ArmageddonAgent/scenarios/training/scenario_training_armageddon1.json"
)


def build_armageddon_engine(seed: int, **overrides):
    """Construit et `reset` un `W40KEngine` ArmageddonAgent / `x1_debug`.

    Fonction et non fixture : une fixture de `scope="module"` ne peut pas dépendre d'une
    fixture de portée fonction, et plusieurs fichiers amortissent volontairement la
    construction sur tout leur module. Les deux formes partagent donc ce corps unique — un
    argument ajouté à `W40KEngine.__init__` ne casse plus les copies une par une.
    """
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    kwargs = {
        "rewards_config": "ArmageddonAgent",
        "training_config_name": "x1_debug",
        "controlled_agent": "ArmageddonAgent",
        "scenario_file": ACTIVE_DEPLOYMENT_SCENARIO,
        "unit_registry": UnitRegistry(),
        "quiet": True,
        "gym_training_mode": True,
    }
    kwargs.update(overrides)
    engine = W40KEngine(**kwargs)
    engine.reset(seed=seed)
    return engine


#: Répertoire de travail des scénarios de test, UN par processus pytest. Créé à la demande et
#: supprimé à la sortie — voir `load_engine_from_scenario` pour les deux contraintes qui
#: interdisent un `TemporaryDirectory` refermé plus tôt.
_SESSION_SCRATCH: List[str] = []


def _session_scratch_dir() -> Path:
    """Répertoire de scénarios du processus courant, créé au premier appel.

    `atexit` et non un `TemporaryDirectory` : le moteur doit pouvoir relire le fichier pendant
    toute sa vie (cf. `load_engine_from_scenario`), donc le nettoyage ne peut pas être borné par
    un `with`. Il est en revanche légitime EN TEST, où personne n'ouvre le replay après coup —
    la raison même pour laquelle `ai.scenario_scratch` s'interdit un `atexit` côté production.
    """
    if not _SESSION_SCRATCH:
        import atexit
        import shutil

        from ai.scenario_scratch import make_scenario_scratch_dir

        chemin = make_scenario_scratch_dir("pytest_")
        _SESSION_SCRATCH.append(chemin)
        atexit.register(shutil.rmtree, chemin, True)
    return Path(_SESSION_SCRATCH[0])


def load_engine_from_scenario(scenario: Dict[str, Any], *, seed: int = 0, **overrides):
    """Matérialise `scenario` sur disque et construit le moteur dessus.

    Le chaînon qui manquait à `build_armageddon_engine` pour que les tests à scénario AD HOC
    puissent l'utiliser : sans lui, chacun recopiait les 7 kwargs de `W40KEngine.__init__`.

    DEUX contraintes, apprises ailleurs et payées deux fois — d'où la délégation à
    `ai.scenario_scratch`, dont c'est exactement la raison d'être :

    1. **Sous le dépôt, pas dans `/tmp`.** `repo_relative_scenario_path`
       (`engine/w40k_core.py`) LÈVE sur un chemin hors dépôt, et `reset()` l'appelle dès qu'un
       StepLogger est actif. Un scénario dans `/tmp` fait donc mourir l'épisode au démarrage
       chez tout appelant qui journalise.
    2. **Survivre à l'appel.** Le moteur retient le chemin dans `_current_scenario_file` et le
       RELIT à tout `reset()` ultérieur qui demande un rechargement — changement de joueur
       contrôlé, scénario aléatoire, scheduler de déploiement. Un `TemporaryDirectory` refermé à
       la sortie de cette fonction donnait un `FileNotFoundError` au second `reset()`.

    La purge de `ai.scenario_scratch` ne touche PAS un répertoire dont le processus propriétaire
    vit encore, quel que soit son âge (empreinte `OWNER_PID`) : lancer `pytest` pendant un
    entraînement long ne peut plus lui supprimer son scénario. C'était le cas jusqu'au
    2026-08-10, et ce helper l'avait aggravé en faisant des tests un troisième créateur de
    répertoires de travail.

    Le fichier vit donc aussi longtemps que le PROCESSUS de test — c'est ce dont le moteur a
    besoin, et c'est tout : `_session_scratch_dir` le supprime à la sortie de pytest. Ne PAS
    reprendre ce nettoyage pour un run réel, où le replay ouvre le scénario après coup (c'est
    exactement ce que la docstring de `ai.scenario_scratch` interdit).
    """
    scratch = _session_scratch_dir()
    # Un fichier par appel, dans UN répertoire : un répertoire par appel laissait 37 dossiers
    # derrière lui dans ce dépôt, que `_purge_stale` re-balayait à chaque construction de moteur.
    path = scratch / f"scenario_{len(list(scratch.iterdir()))}.json"
    path.write_text(json.dumps(scenario), encoding="utf-8")
    return build_armageddon_engine(seed, scenario_file=str(path), **overrides)


# ---------------------------------------------------------------------------
# Unités ATTACHÉES (règle 19) — scénario et fixtures partagés
# ---------------------------------------------------------------------------

#: Datasheets du couple leader/bodyguard des tests 19.xx, et les deux règles qui les opposent.
#: RÉUNIES ICI parce que deux fichiers les partagent (`test_attached_units_abilities_19_04`,
#: `test_squad_obs_unit_rules`) : elles y étaient recopiées à l'identique, et la bascule du
#: 2026-08-10 a dû être appliquée deux fois à la main. Rien n'aurait cassé si l'une avait été
#: oubliée — le fichier d'observation serait resté vert, la source qu'il suit étant le bodyguard.
#:
#: Le couple est DISCRIMINANT DANS LES DEUX SENS, c'est sa raison d'être : le Chaplain porte
#: `deep_strike` et pas `charge_impact`, l'escouade l'inverse, et 19.01 autorise l'attachement
#: (le `CAN_LEAD` du Chaplain couvre le keyword « ASSAULT INTERCESSORS WITH JUMP PACKS »).
#: Deux VRAIES datasheets : ces fixtures reposaient sur un placeholder INVENTÉ jusqu'à sa purge
#: par le chantier 05, et rien ne doit en réintroduire un pour la commodité d'un test.
ATTACHED_LEADER_RULE = "deep_strike"
ATTACHED_BODYGUARD_RULE = "charge_impact"

#: Escouade de 3 figurines : l'unité attachée en comptera 4 (le Chaplain replié).
ATTACHED_BODYGUARD: Dict[str, Any] = {
    "id": 101, "unit_type": "AssaultIntercessorJumpPack", "player": 2, "col": 12, "row": 10,
    "models": [{"col": 12, "row": 10}, {"col": 13, "row": 10}, {"col": 14, "row": 10}],
}
ATTACHED_LEADER: Dict[str, Any] = {
    "id": 102, "unit_type": "ChaplainJumpPack", "player": 2,
    "attached_squad": 101, "col": 15, "row": 10,
}
ATTACHED_ENEMY: Dict[str, Any] = {
    "id": 1, "unit_type": "Intercessor", "player": 1, "col": 3, "row": 3,
}


def attached_scenario(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Scénario minimal des tests d'unités attachées, pour la liste d'unités donnée."""
    return {
        "board_ref": "44x60x5",
        "primary_objectives": ["objectives_control"],
        "wall_ref": "walls-none.json",
        # 08.04 exige la Faction d'Armée DÉCLARÉE à chaque phase de commandement et refuse de la
        # déduire des unités. ADEPTUS ASTARTES est celle des datasheets ci-dessus.
        "army_faction": {"1": "ADEPTUS ASTARTES", "2": "ADEPTUS ASTARTES"},
        # Corollaire OBLIGATOIRE d'une armée ADEPTUS ASTARTES : la clause du +1 Wound d'Oath en
        # dépend, et la construction de l'observation la lit à chaque reset.
        "uses_codex_detachment": {"1": True, "2": True},
        "units": units,
    }


#: Réglages PAR ÉPISODE qu'un test observant la phase de déploiement doit ÉPINGLER au lieu de
#: les subir. Injectés dans le ``training_config`` de l'INSTANCE — jamais dans le fichier de
#: config, qui porte une décision utilisateur (la rampe 0.0 → 0.8 est délibérée).
_ACTIVE_DEPLOYMENT_PINS: Dict[str, Dict[str, Any]] = {
    # Déploiement ACTIF à tous les épisodes. Le tirage du moteur est
    # ``random.random() < p_active`` ; ``random.random()`` vit dans [0.0, 1.0), donc p_active
    # = 1.0 rend « active » CERTAIN — déterminisme par construction, pas par chance.
    # ``start == end`` rend le tirage indépendant de la progression, donc de ``total_episodes``.
    # ``training_only: false`` l'affranchit du split de chemin ``/scenarios/training/``.
    "deployment_mode_schedule": {
        "enabled": True,
        "training_only": False,
        "active_ratio_start": 1.0,
        "active_ratio_end": 1.0,
        "schedule": "linear",
        "freeze_after_progress": 1.0,
    },
    # Épinglé À L'ARRÊT. Activé, ``W40KEngine._should_force_random_deployment_action`` REMPLACE
    # l'action de déploiement choisie par une action valide tirée au hasard : un test qui pilote
    # le déploiement (clustering forcé, slot précis…) verrait ses choix silencieusement écrasés
    # et continuerait de passer en ne testant plus ce qu'il annonce.
    "deployment_random_mix": {
        "enabled": False,
        "training_only": False,
        "force_random_ratio_start": 0.0,
        "force_random_ratio_end": 0.0,
        "schedule": "linear",
        "freeze_after_progress": 1.0,
        "apply_to": "agent_only",
    },
}


def pin_active_deployment(engine: Any) -> Any:
    """Force une phase de déploiement ACTIVE et reproductible. À appeler AVANT ``reset()``.

    POURQUOI CE HELPER EXISTE. Quatre fichiers observaient la phase de déploiement en la tenant
    pour acquise. Ils ne l'obtenaient en fait que parce que le profil ``x1_debug`` ne portait
    AUCUN bloc ``deployment_mode_schedule`` : ``_configure_deployment_mode_for_episode`` rendait
    ``None`` et le mode retombait sur le JSON du scénario (``active``). Le jour où les cinq
    profils ont reçu ce bloc avec ``active_ratio_start: 0.0``, le premier épisode est passé en
    placement figé et les quatre fichiers sont tombés d'un coup. **Un test ne doit pas dépendre
    de l'ABSENCE d'une configuration : il doit déclarer l'état de jeu qu'il exige.**

    CE QUE CE HELPER NE FAIT PAS. Il ne change ni le scénario, ni la géométrie, ni les graines,
    ni aucune règle de jeu : le déploiement passe par le VRAI chemin moteur (le scheduler tire
    « active », le moteur ouvre la phase et construit ses pools). Seul le tirage du MODE est
    forcé à la valeur que ces tests supposaient déjà. C'est ce qui permet de corriger sans
    toucher aux scénarios — et donc sans altérer les propriétés géométriques testées.

    Même technique que ``test_deployment_mode_schedule.py``, qui pilote ce mécanisme depuis le
    test. Retourne le moteur, pour s'enchaîner sur la construction.
    """
    if engine.training_config is None:
        raise ValueError(
            "pin_active_deployment: `engine.training_config` est None — ce helper s'applique "
            "aux moteurs construits sur un profil d'entraînement."
        )
    # Copie défensive AVANT écriture : `training_config` peut être l'objet même que sert le
    # cache de configuration. Le muter en place contaminerait les autres tests du process.
    engine.training_config = dict(engine.training_config)
    engine.training_config.update(_ACTIVE_DEPLOYMENT_PINS)
    # Un test joue UN environnement, en serie. Le moteur REFUSE de ramper sur un `n_envs` non
    # resolu (le profil en declare 48, cf. engine/episode_schedule.py) : on declare le nombre
    # reel, comme le fait `ai/train.py` pour ses branches mono-env.
    engine.training_config["n_envs"] = 1
    engine._episode_ramp_n_envs_is_runtime = True
    return engine


def assert_deployment_phase(engine: Any) -> None:
    """Garde-fou commun : le moteur DOIT être en phase de déploiement après ``reset()``.

    C'est cette assertion qui a signalé la régression de la rampe. Elle reste en place dans
    chaque fichier : sans elle, un test de déploiement qui ne déploie plus passerait au vert.
    """
    phase = engine.game_state["phase"]
    if phase != "deployment":
        raise AssertionError(
            f"phase {phase!r} au lieu de 'deployment' malgré `pin_active_deployment`. "
            f"Le mécanisme de sélection du mode de déploiement a changé : réaligner "
            f"`_ACTIVE_DEPLOYMENT_PINS` sur le contrat du moteur, ne pas contourner l'assertion."
        )
