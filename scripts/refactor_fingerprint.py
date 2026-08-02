#!/usr/bin/env python3
"""Empreinte de refactoring — prouve qu'un changement n'altere NI le jeu joue, NI le travail fourni.

POURQUOI CET OUTIL
------------------
Optimiser le moteur d'entrainement demande de repondre a deux questions que le wall-clock ne
sait pas trancher :

1. « Est-ce que je joue toujours exactement la meme partie ? »   -> l'EMPREINTE (hash)
2. « Est-ce que je fais toujours la meme quantite de travail ? » -> les COMPTEURS

Le hash couvre tout ce qui definit la partie : actions choisies, recompenses, tour/phase/joueur
a chaque pas, PV et positions PAR FIGURINE en fin d'episode, points de victoire, vainqueur, et
les tenseurs d'observation rendus a PPO. Deux hashes identiques = trajectoires byte-identiques.

Les compteurs sont INSENSIBLES A LA CHARGE MACHINE, contrairement a toute mesure de temps. Sur
un portable qui throttle, le meme code peut mettre 2 a 3 fois plus longtemps d'une heure a
l'autre : un ralentissement observe ne prouve alors rien. Les compteurs, eux, distinguent
« le code fait plus de travail » de « la machine va moins vite ».

USAGE — comparaison A/B
-----------------------
    python3 scripts/refactor_fingerprint.py                 # etat courant
    git stash push <fichiers modifies>
    python3 scripts/refactor_fingerprint.py                 # etat de reference
    git stash pop

Les deux sorties doivent etre IDENTIQUES pour un refactoring a comportement constant.

PIEGE VECU : apres un `git stash pop`, le mtime restaure peut coincider a la seconde pres avec
celui du `.pyc` compile entre-temps — Python reutilise alors du bytecode PERIME et l'outil
compare deux fois la meme version. Purger avant chaque mesure :

    find engine ai -name __pycache__ -type d -exec rm -rf {} +

VERIFIER QUE L'OUTIL DISCRIMINE VRAIMENT
----------------------------------------
Une empreinte qui ne bouge jamais donne un faux feu vert. Avant de s'y fier pour un gros
refactoring, injecter une mutation et verifier que le hash CHANGE. Le faire par monkeypatch,
JAMAIS en editant un fichier du depot : une sauvegarde/restauration par copie ecrase l'edition
en cours de quelqu'un d'autre si elle tombe entre les deux.

    import sys; sys.path[:0] = ["<repo>", "<repo>/scripts"]
    from engine.observation_builder import ObservationBuilder
    _orig = ObservationBuilder.build_squad_grid
    ObservationBuilder.build_squad_grid = lambda s, gs, sid: _decale(_orig(s, gs, sid))
    import refactor_fingerprint
    sys.argv = ["refactor_fingerprint", "--episodes", "6"]
    refactor_fingerprint.main()

Mesure faite a la creation de l'outil (8 episodes, x1) : decaler UNE SEULE cellule de la grille
d'observation change le hash sans bouger aucun compteur — les deux controles sont bien
complementaires, le hash voit ce que les compteurs ne peuvent pas voir.

CE QUE CET OUTIL N'EST PAS
--------------------------
Ce n'est pas un test de non-regression et il n'a pas sa place dans `tests/` : le hash change
LEGITIMEMENT des qu'une regle du jeu, une recompense ou le schema d'observation evolue. Fige
dans un test, il serait rouge en permanence — donc neutralise en une semaine. C'est un outil de
comparaison ponctuel, a lancer de part et d'autre d'un changement cense ne rien changer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys

# Resolution du plateau AVANT tout import moteur : elle conditionne la geometrie (cf.
# `geometry_is_hex`). La poser apres laisserait le config-loader memoiser l'autre plateau.
os.environ.setdefault("W40K_BOARD_PATH", "board/44x60x1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402


def _install_work_counters() -> dict:
    """Compte le travail moteur. Les compteurs sont verifies non nuls a la fin (cf. `main`).

    Les fonctions sont remplacees SUR LEUR MODULE, pas sur une reference importee : c'est le
    seul point d'interception qui reste valide quel que soit l'appelant. Si un renommage cassait
    l'interception, le compteur resterait a zero — d'ou la garde de non-vacuite.
    """
    import engine.action_decoder as action_decoder_module
    import engine.phase_handlers.charge_handlers as charge_handlers
    import engine.phase_handlers.movement_handlers as movement_handlers
    import engine.w40k_core as w40k_core

    counters = {
        "action_mask": 0,
        "move_pool": 0,
        "charge_phase_start": 0,
        "engine_step": 0,
        "episode_steps": 0,
    }

    def count(owner, attribute: str, key: str) -> None:
        """Enveloppe `owner.attribute` d'un compteur. Les quatre interceptions ont la meme forme ;
        l'ecrire une fois evite qu'une cinquieme copie diverge d'une lettre."""
        wrapped = getattr(owner, attribute)

        def counted(*args, **kwargs):
            counters[key] += 1
            return wrapped(*args, **kwargs)

        setattr(owner, attribute, counted)

    # `action_mask` compte les CONSTRUCTIONS DE MASQUE, seul compteur sensible a la suppression
    # d'un appel redondant. `move_pool` ne l'est pas : le pool de destinations est memoise pour la
    # duree de l'activation, donc un second appel de masque sur le meme etat le retrouve sans le
    # reconstruire — deux appels et un seul se lisent identiquement sur ce compteur-la.
    count(action_decoder_module.ActionDecoder, "get_squad_action_mask_and_eligible_units", "action_mask")
    count(movement_handlers, "movement_build_valid_destinations_pool", "move_pool")
    count(charge_handlers, "charge_phase_start", "charge_phase_start")
    # `step_with_mask` et NON `step` : `step` n'est plus que l'adaptateur gym 5-uplet, et le
    # wrapper d'entrainement appelle l'implementation directement pour transmettre le masque
    # (cf. `ai/env_wrappers._engine_step`). Enveloppee sur `step`, la sonde comptait 0 — le garde
    # de non-vacuite plus bas l'a signale au premier run. Compter l'implementation couvre les DEUX
    # chemins d'appel, puisque l'adaptateur y delegue.
    count(w40k_core.W40KEngine, "step_with_mask", "engine_step")
    return counters


def _build_env(agent: str, training_config: str):
    """Un environnement identique a un worker d'entrainement (memes bots, memes scenarios)."""
    from ai.training_utils import make_training_env
    from ai.unit_registry import UnitRegistry
    import ai.train as train
    from config_loader import get_config_loader

    config = get_config_loader()
    cfg = config.load_agent_training_config(agent, training_config)
    scenarios = train.get_scenario_list_for_phase(config, agent, training_config, scenario_type="bot")
    # UN environnement, joue en serie : le profil en declare 48, mais c'est le nombre REEL qui
    # sert de denominateur aux rampes par-episode (cf. engine/episode_schedule.py). Meme
    # reecriture que le chemin d'entrainement apres `_resolve_n_envs_for_step_logging`.
    cfg = {**cfg, "n_envs": 1}
    opponents = train.build_training_opponents(cfg, True, 100, lambda _message: None)
    return make_training_env(
        rank=0,
        scenario_file=scenarios[0],
        rewards_config_name=agent,
        training_config_name=training_config,
        controlled_agent_key=agent,
        unit_registry=UnitRegistry(),
        step_logger_enabled=False,
        scenario_files=scenarios,
        debug_mode=False,
        use_bots=True,
        training_bots=opponents["training_bots"],
        agent_seat_mode=opponents["agent_seat_mode"],
        global_seed=opponents["agent_seat_seed"],
        opponent_mix_config=opponents["opponent_mix_config"],
        n_envs=1,
    )()


def _play(env, episodes: int, seed_base: int, counters: dict) -> str:
    """Rejoue `episodes` parties deterministes et rend l'empreinte du deroulement.

    La politique est un tirage uniforme parmi les actions MASQUEES, avec un generateur propre
    par episode : la trajectoire ne depend d'aucun modele entraine, donc l'empreinte reste
    comparable meme apres un reentrainement.
    """
    # Import differe, comme les autres dependances lourdes de ce module.
    from sb3_contrib.common.maskable.utils import get_action_masks

    digest = hashlib.sha256()
    for episode in range(episodes):
        # Les trois sources d'alea du moteur et des bots, fixees a l'identique a chaque episode.
        random.seed(seed_base + episode)
        np.random.seed(seed_base + episode)
        policy_rng = random.Random(seed_base * 7 + episode)

        obs, _info = env.reset(seed=seed_base + episode)
        game_state = env.unwrapped.game_state
        done = False
        while not done:
            # `get_action_masks` de sb3_contrib, c'est-a-dire EXACTEMENT ce qu'appelle MaskablePPO :
            # il resout `action_masks` via `get_wrapper_attr` sur le wrapper le PLUS EXTERNE.
            # Cet appel passait auparavant par `env.unwrapped.get_action_mask()`, au motif que
            # `mask_fn` recevait le moteur nu — la reserve inscrite ici prevoyait le cas ou un
            # wrapper servirait le masque lui-meme, et c'est arrive (`BotControlledEnv.action_masks`).
            # Le chemin nu contournait alors le depot et le compteur affichait « travail identique »
            # en regardant ailleurs. Ne JAMAIS revenir a `unwrapped` ici : ce banc ne vaut que s'il
            # emprunte le meme chemin que PPO.
            mask = np.asarray(get_action_masks(env))
            legal = np.flatnonzero(mask)
            if legal.size == 0:
                raise RuntimeError(
                    f"episode {episode} : masque vide — le moteur doit toujours exposer une action legale"
                )
            action = int(legal[policy_rng.randrange(legal.size)])
            obs, reward, terminated, truncated, _info = env.step(action)
            done = terminated or truncated

            digest.update(
                f"{action}|{reward:.6f}|{game_state.get('turn')}|"
                f"{game_state.get('phase')}|{game_state.get('current_player')}".encode()
            )
            # L'observation REELLEMENT rendue a PPO, tenseur par tenseur.
            for key in sorted(obs):
                digest.update(key.encode())
                digest.update(np.ascontiguousarray(obs[key]).tobytes())

        # Etat final PAR FIGURINE : une moyenne d'escouade masquerait un deplacement compense.
        final_units = sorted(
            (
                str(unit.get("id")),
                int(unit.get("col", -1)),
                int(unit.get("row", -1)),
                int(unit.get("CUR_HP", -1)),
            )
            for unit in game_state["units"]
        )
        digest.update(json.dumps(final_units).encode())
        digest.update(json.dumps(game_state.get("victory_points"), sort_keys=True, default=str).encode())
        counters["episode_steps"] += int(game_state.get("episode_steps", 0))
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agent", default="ArmageddonAgent")
    parser.add_argument("--training-config", default="x1_debug")
    parser.add_argument("--episodes", type=int, default=8)
    parser.add_argument("--seed-base", type=int, default=1000)
    args = parser.parse_args()

    counters = _install_work_counters()
    env = _build_env(args.agent, args.training_config)
    fingerprint = _play(env, args.episodes, args.seed_base, counters)

    # VACUITE : un compteur a zero ne veut pas dire « aucun travail », il veut dire que
    # l'interception ne mesure plus rien (fonction renommee, chemin d'appel change). Sans cette
    # garde, l'outil afficherait « travail identique » en ne regardant rien du tout.
    empty = [name for name, value in counters.items() if value == 0]
    if empty:
        raise RuntimeError(
            f"compteurs restes a zero : {empty}. L'interception ne mesure plus le chemin reel "
            f"(fonction renommee ou deplacee) — corriger `_install_work_counters` avant de "
            f"conclure quoi que ce soit de cette empreinte."
        )

    print(f"FINGERPRINT {fingerprint}")
    print(f"WORK        {json.dumps(counters, sort_keys=True)}")
    print(
        f"(agent={args.agent} config={args.training_config} "
        f"episodes={args.episodes} seed_base={args.seed_base} board={os.environ['W40K_BOARD_PATH']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
