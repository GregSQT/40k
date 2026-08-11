"""Règle 14.02 — le checkpoint de contrôle d'objectif tourne AUSSI en entraînement.

DÉFAUT CORRIGÉ (2026-08-04, mesuré). `run_objective_control_checkpoint` sortait immédiatement sur
``if not check_cfg`` quand la section ``objective_control_check`` manquait de la config du moteur.
Les deux constructeurs de l'API/PvP la posaient ; la branche d'ENTRAÎNEMENT de
`W40KEngine.__init__` l'avait omise. Le checkpoint 14.02 était donc un **no-op complet en gym** :
`objective_controllers` n'y était rafraîchi que par effet de bord des chemins de scoring VP
(`calculate_objective_control` appelé en direct), à des moments qui ne sont pas ceux de la règle.
Mesuré avant correction : le contrôle restait figé tout le tour 1, et ne changeait qu'aux phases
de commandement.

C'est le motif « code testé mais jamais appelé » : `refresh_objective_control_on_boundary` avait
été écrite pour partager le checkpoint entre gym et PvP, sa docstring l'annonce, et la config ne
l'a jamais atteinte du côté gym.

MÉCANISME CORRIGÉ (même date). Le contrat était recopié à la main sur QUATRE sites de
construction, dont `main.load_config` qui omettait en plus `move` et `charge`, et il était lu
en `.get()` — donc un oubli n'échouait nulle part. Il vit désormais en UN endroit,
`config_loader.GAME_CONFIG_SECTIONS_REQUIRED_BY_ENGINE` /
`require_engine_game_config_sections`, avec `require_key` sur chaque section. Ce fichier LIT ce
contrat de production : le redéclarer ici ne prouverait que sa propre copie.

Ce fichier verrouille les deux moitiés : la config est complète, ET le checkpoint tire vraiment.
"""
from __future__ import annotations

import pytest

from config_loader import GAME_CONFIG_SECTIONS_REQUIRED_BY_ENGINE

from tests.unit.engine._config_helpers import TRAINING_SCENARIO, build_armageddon_engine


@pytest.fixture(scope="module")
def gym_engine():
    return build_armageddon_engine(
        seed=0, scenario_file=TRAINING_SCENARIO, training_n_envs=1,
    )


def test_la_config_dentrainement_porte_toutes_les_sections_du_moteur(gym_engine) -> None:
    """Chaque section de `game_config.json` dont le moteur dépend est PRÉSENTE.

    Le contenu de la section n'est PAS comparé à celui du loader : celui-ci est mémoïsé et la
    config du moteur en stocke la RÉFÉRENCE, donc l'égalité comparerait l'objet avec lui-même
    (`a is b` vaut True) — une assertion qui ne peut jamais échouer. On vérifie ce qui a un sens :
    la section est présente et EXPLOITABLE, c'est-à-dire qu'elle déclare au moins un point de
    contrôle. Une section vide rendrait `run_objective_control_checkpoint` inerte exactement
    comme son absence (`if not points: return`), sans qu'aucune présence ne le signale.
    """
    for section in GAME_CONFIG_SECTIONS_REQUIRED_BY_ENGINE:
        assert section in gym_engine.config, (
            f"section '{section}' absente de la config du moteur d'ENTRAÎNEMENT : la "
            f"fonctionnalité qu'elle porte s'éteint en silence (cf. en-tête du fichier)"
        )
    points = gym_engine.config["objective_control_check"]["points"]
    assert points, (
        "`objective_control_check.points` est vide : `run_objective_control_checkpoint` sort "
        "sur `if not points` et la règle 14.02 s'éteint, comme si la section manquait"
    )
    assert {"phase": "command", "moment": "end"} in points, (
        "la fin de la phase de commandement n'est plus un point de contrôle : c'est elle qui "
        "détermine le contrôle lu au début de la phase de mouvement (cp_gain_on_objective)"
    )


def test_le_checkpoint_1402_tire_reellement_en_entrainement(gym_engine) -> None:
    """VERT VACANT : une config complète ne prouve pas que le checkpoint s'exécute.

    On force une frontière de phase et on exige que `refresh_objective_control_on_boundary`
    rende True ET que `objective_controllers` soit renseigné. Sans la section, la méthode rend
    True aussi (elle a bien vu la frontière) mais `run_objective_control_checkpoint` sort avant
    d'écrire quoi que ce soit — d'où la vérification sur le CONTENU, pas sur le retour.
    """
    game_state = gym_engine.game_state
    game_state["objective_controllers"] = {}
    # Deux appels : le premier mémorise la frontière courante, le second en franchit une.
    game_state["_objective_control_last_boundary"] = ("command", int(game_state["turn"]))
    game_state["phase"] = "move"

    fired = gym_engine.state_manager.refresh_objective_control_on_boundary(game_state)

    assert fired is True, "la frontière command -> move n'a pas été détectée"
    assert game_state["objective_controllers"], (
        "le checkpoint 14.02 n'a rien écrit : la section `objective_control_check` manque de la "
        "config du moteur, et `run_objective_control_checkpoint` sort sur `if not check_cfg`"
    )
    objectives = game_state["objectives"]
    assert set(game_state["objective_controllers"]) == {str(o["id"]) for o in objectives}, (
        "le checkpoint n'a pas évalué tous les objectifs du scénario"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Cascade de phases : une frontière franchie SANS être observée doit être soldée
# ─────────────────────────────────────────────────────────────────────────────

def test_une_cascade_de_phases_solde_la_frontiere_intermediaire(gym_engine) -> None:
    """`deployment → command → move` en UNE action : la fin de commandement est soldée.

    DÉFAUT CORRIGÉ (2026-08-12, mesuré sur le scénario PvE). `execute_semantic_action` enchaîne
    les phases en cascade ; personne n'observe l'état entre deux. La méthode ne comparait que la
    dernière phase VUE et la phase courante, donc elle testait la frontière `deployment → move`,
    qui ne correspond à aucun point de `objective_control_check.points`. Résultat en jeu : un
    Dreadnought posé dans un terrain-objectif laissait l'objectif neutre et le journal muet
    pendant TOUTE la phase de mouvement du tour 1.

    Le test CONSTRUIT la cascade au lieu de l'espérer d'un enchaînement de handlers : c'est
    `enter_phase` qui enregistre la suite, et c'est elle qui est vérifiée ici.
    """
    from engine.game_utils import PHASES_TRAVERSED_KEY, enter_phase

    game_state = gym_engine.game_state
    game_state["objective_controllers"] = {}
    game_state["phase"] = "deployment"
    game_state.pop(PHASES_TRAVERSED_KEY, None)
    game_state["_objective_control_last_boundary"] = ("deployment", int(game_state["turn"]))

    enter_phase(game_state, "command")
    enter_phase(game_state, "move")
    assert game_state[PHASES_TRAVERSED_KEY] == ["command", "move"], (
        "`enter_phase` n'a pas enregistré la suite des phases franchies : sans elle, la "
        "frontière intermédiaire reste invisible"
    )

    fired = gym_engine.state_manager.refresh_objective_control_on_boundary(game_state)

    assert fired is True
    assert game_state["objective_controllers"], (
        "la fin de la phase de commandement n'a pas été soldée : seule la frontière "
        "`deployment -> move` a été testée, et elle ne correspond à aucun point configuré"
    )
    assert PHASES_TRAVERSED_KEY not in game_state, (
        "la file n'a pas été drainée : elle serait rejouée à la frontière suivante, sur un état "
        "qui n'est plus le sien"
    )


def test_enter_phase_ne_compte_pas_une_reecriture_de_la_meme_phase() -> None:
    """Reposer la phase courante n'est pas une frontière — sinon la file enflerait à chaque step.

    `movement_phase_start` et ses jumelles sont rappelées plusieurs fois par tour sur certains
    chemins ; compter ces réécritures ferait rejouer des frontières qui n'ont pas eu lieu.
    """
    from engine.game_utils import PHASES_TRAVERSED_KEY, enter_phase

    game_state: dict = {"phase": "move"}
    enter_phase(game_state, "move")
    enter_phase(game_state, "move")

    assert PHASES_TRAVERSED_KEY not in game_state
    assert game_state["phase"] == "move"


def _manager_et_etat_avec_un_objectif_tenu_par_p1():
    """Un objectif d'UN hexe, une figurine P1 (OC 2) posée dessus. Rien d'autre.

    État construit à la main plutôt qu'emprunté à un scénario : le test observe
    ``previous_controller``, donc il lui faut un objectif dont il MAÎTRISE le contrôleur —
    l'espérer d'un scénario, c'est le vert vacant garanti le jour où un roster bouge.
    """
    from engine.game_state import GameStateManager

    manager = GameStateManager({
        "objective_control_check": {
            "points": [
                {"phase": "move", "moment": "end"},
                {"phase": "shoot", "moment": "end"},
                {"phase": "charge", "moment": "end"},
            ]
        }
    })
    unit = {
        "id": "1", "player": 1, "OC": 2, "battle_shocked": False,
        "col": 0, "row": 0, "orientation": 0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "HP_CUR": 1,
    }
    game_state = {
        "turn": 1,
        "objectives": [{"id": "obj", "hexes": [[0, 0]]}],
        "primary_objective": {
            "control": {
                "method": "oc_sum_greater",
                "control_method": "default",
                "tie_behavior": "no_control",
            }
        },
        "units": [unit],
        "units_cache": {"1": {"orientation": 0}},
        "squad_models": {"1": ["1#0"]},
        "models_cache": {
            "1#0": {
                "col": 0, "row": 0, "HP_CUR": 1, "orientation": 0,
                "BASE_SHAPE": "round", "BASE_SIZE": 1,
            }
        },
    }
    return manager, game_state


def test_une_cascade_ne_rejoue_pas_la_determination_et_dit_bien_capture() -> None:
    """Une CAPTURE reste « captured », même si la cascade franchit plusieurs points.

    DÉFAUT CORRIGÉ (2026-08-12, vu en jeu). Solder chaque frontière une par une rejouait
    ``calculate_objective_control`` sur un état IDENTIQUE : au 2e passage,
    ``previous_controller`` valait déjà le contrôleur qu'on venait d'écrire, et le journal
    disait « held by P1 » sur un objectif que le joueur venait de prendre. Mesuré en partie :
    `tri_2 Centre` n'a jamais eu sa ligne « captured by P1 ».

    Les frontières d'une cascade séparent des états identiques : la détermination 14.02 est
    UNE, pas N.
    """
    from engine.game_utils import PHASES_TRAVERSED_KEY, enter_phase

    manager, game_state = _manager_et_etat_avec_un_objectif_tenu_par_p1()
    game_state["phase"] = "move"
    game_state["_objective_control_last_boundary"] = ("move", 1)
    # Cascade `move -> shoot -> charge` : DEUX points configurés franchis d'un coup.
    enter_phase(game_state, "shoot")
    enter_phase(game_state, "charge")
    assert game_state[PHASES_TRAVERSED_KEY] == ["shoot", "charge"]

    assert manager.refresh_objective_control_on_boundary(game_state) is True

    detail = game_state["_objective_control_detail"]["obj"]
    assert detail["controller"] == 1, "la figurine P1 (OC 2) tient l'objectif"
    assert detail["previous_controller"] is None, (
        "la détermination a été rejouée sur un état identique : `previous_controller` porte le "
        "contrôleur qu'on vient d'écrire, donc le journal dit « held by P1 » sur une CAPTURE"
    )


def test_une_frontiere_sans_point_configure_ne_declenche_rien() -> None:
    """`refresh` ne rend True que si la détermination a REELLEMENT eu lieu.

    Son retour pilote l'arrêt à la première frontière qui tire ; le confondre avec « une
    frontière a été vue » ferait s'arrêter la boucle avant d'avoir soldé quoi que ce soit —
    exactement le défaut de la cascade de déploiement, réintroduit par l'autre bout.
    """
    from engine.game_utils import enter_phase

    manager, game_state = _manager_et_etat_avec_un_objectif_tenu_par_p1()
    game_state["phase"] = "deployment"
    game_state["_objective_control_last_boundary"] = ("deployment", 1)
    enter_phase(game_state, "command")  # ni `deployment/end` ni `command/start` n'est un point

    assert manager.refresh_objective_control_on_boundary(game_state) is False
    assert "_objective_control_detail" not in game_state


def test_un_etat_sans_file_retombe_sur_les_deux_extremites(gym_engine) -> None:
    """Fixtures de test et sauvegardes restaurées n'ont pas de file : le comportement tient.

    Sans cette garantie, tout état reconstruit hors `enter_phase` cesserait de solder ses
    frontières — le défaut corrigé, déplacé au lieu d'être fermé.
    """
    from engine.game_utils import PHASES_TRAVERSED_KEY

    game_state = gym_engine.game_state
    game_state["objective_controllers"] = {}
    game_state.pop(PHASES_TRAVERSED_KEY, None)
    game_state["_objective_control_last_boundary"] = ("command", int(game_state["turn"]))
    game_state["phase"] = "move"  # écriture directe : aucune file n'existe

    fired = gym_engine.state_manager.refresh_objective_control_on_boundary(game_state)

    assert fired is True
    assert game_state["objective_controllers"], (
        "la frontière `command -> move` n'est plus soldée quand la file est absente"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Le MÉCANISME : une section oubliée doit ÉCHOUER, pas s'éteindre
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("missing", GAME_CONFIG_SECTIONS_REQUIRED_BY_ENGINE)
def test_lassembleur_de_config_refuse_une_section_manquante(missing: str) -> None:
    """`require_engine_game_config_sections` lève sur CHAQUE section absente.

    C'est l'unique porte d'entrée du contrat : si elle acceptait une section manquante, les
    quatre sites de construction se remettraient à diverger sans que rien ne le dise.
    """
    from config_loader import get_config_loader, require_engine_game_config_sections
    from shared.data_validation import ConfigurationError

    amputee = {k: v for k, v in get_config_loader().get_game_config().items() if k != missing}

    with pytest.raises(ConfigurationError, match=missing):
        require_engine_game_config_sections(amputee)


def test_le_checkpoint_leve_au_lieu_de_se_taire_si_la_section_manque() -> None:
    """Régime d'erreur EXPLICITE au point de lecture, comme la section jumelle `move`.

    Avant : `self.config.get("objective_control_check")` + `if not check_cfg: return` — un
    constructeur de config qui l'oubliait éteignait la règle 14.02 en silence. Un oubli de
    `move` plantait, lui, à la première action (`_get_move_traversal_rules`). C'est cette
    asymétrie entre deux sections du MÊME fichier de config que ce test verrouille.
    """
    from engine.game_state import GameStateManager
    from shared.data_validation import ConfigurationError

    manager = GameStateManager({"units": []})

    with pytest.raises(ConfigurationError, match="objective_control_check"):
        manager.run_objective_control_checkpoint({}, "command", "move", turn_changed=False)


def test_main_load_config_porte_toutes_les_sections_du_moteur() -> None:
    """Le QUATRIÈME site de construction, `main.load_config`, est complet.

    Il ne posait que `game_rules` : `move`, `charge` et `objective_control_check` manquaient —
    le contrat recopié à la main sur quatre sites, avec un site oublié. Il passe désormais par
    l'assembleur commun, donc toute section ajoutée au contrat lui arrive sans retouche.
    """
    import main

    config = main.load_config()

    for section in GAME_CONFIG_SECTIONS_REQUIRED_BY_ENGINE:
        assert section in config, (
            f"section '{section}' absente de `main.load_config` : ce chemin construit un moteur "
            f"amputé de la fonctionnalité qu'elle porte"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Cache des zones d'objectif
# ─────────────────────────────────────────────────────────────────────────────

def test_le_cache_de_zones_rend_les_memes_zones_et_se_perime_a_la_rotation() -> None:
    """`objective_hex_zones` mémoïse par IDENTITÉ de la liste source (perf, 1,46 % d'un épisode).

    Un cache de géométrie sur un chemin de RÈGLE (14.02) ne vaut que s'il est prouvé équivalent
    ET incapable de rester périmé. Les deux moitiés sont ici :
      - mêmes zones, au hexe près, avec et sans cache ;
      - remplacer `game_state["objectives"]` (reset, rotation de roster) suffit à l'invalider,
        parce que la clé du cache est la liste ELLE-MÊME, comparée par `is`. C'est ce qui évite
        d'avoir un site d'invalidation à ne pas oublier — le mode de défaillance d'un cache
        invalidé à la main.

    Mesuré le 2026-08-04 : 3,9 ms par appel sans cache (10 538 hexes reparsés et normalisés),
    0,2 µs avec, 62 appels par épisode d'entraînement.
    """
    from engine.game_state import objective_hex_zones

    game_state = {
        "objectives": [
            {"id": "a", "hexes": [[1, 1], [1, 2]]},
            {"id": "b", "hexes": [{"col": 5, "row": 5}]},
        ]
    }
    cached = objective_hex_zones(game_state)
    assert "_objective_hex_zones_cache" in game_state, "rien n'a été mémoïsé"

    fresh_state = {"objectives": game_state["objectives"]}
    fresh = objective_hex_zones(fresh_state)
    assert [(i, sorted(z)) for i, z in cached] == [(i, sorted(z)) for i, z in fresh], (
        "le cache ne rend pas les mêmes zones qu'un calcul neuf"
    )

    # Rotation de roster : une NOUVELLE liste est affectée -> le cache doit être ignoré.
    game_state["objectives"] = [{"id": "c", "hexes": [[9, 9]]}]
    after = objective_hex_zones(game_state)
    assert [i for i, _ in after] == ["c"], (
        "le cache a survécu au remplacement de `objectives` : il rendrait les zones de l'ancien "
        "scénario après une rotation de roster"
    )
