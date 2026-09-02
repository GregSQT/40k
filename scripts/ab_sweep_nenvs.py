#!/usr/bin/env python3
"""BALAYAGE de `n_envs` : classer PLUSIEURS valeurs, la nuit, sans arbitrage humain.

POURQUOI UN SECOND OUTIL PLUTOT QUE `ab_bench_nenvs.py`
------------------------------------------------------
`ab_bench_nenvs.py` compare DEUX valeurs par appariement strict (A,B / B,A). Classer N valeurs
avec lui demande N-1 comparaisons contre un pivot, soit 6*(N-1) runs : 18 runs pour 4 valeurs,
hors de portee d'une nuit. Ce balayage-ci troque l'appariement par paires contre un protocole
par TOURS, qui mesure les N configurations dans chaque tour et n'en compare que des mesures
issues du MEME tour. Il garde donc la propriete essentielle du banc — ne jamais comparer deux
mesures separees par des heures — en divisant le nombre de runs par trois.

CE QUE CET OUTIL IMPOSE
-----------------------
1. TOURS, ORDRE INVERSE A CHAQUE TOUR. Une derive monotone de la machine (temperature, charge de
   fond) penalise les configurations mesurees tard dans un tour ; inverser l'ordre au tour suivant
   les place tot. Le biais change de signe et se compense entre tours consecutifs.
2. RATIO AU PIVOT DU MEME TOUR, jamais une moyenne de secondes entre tours. Un tour entier peut
   etre 20 % plus lent qu'un autre sans que cela dise quoi que ce soit sur `n_envs` ; seul le
   rapport interne au tour est porteur.
3. LE PREMIER TOUR EST JETE (remplissage des caches disque et allocateur), comme la premiere
   paire du banc — mais seulement s'il reste au moins deux tours pour le verdict. Avec moins,
   il est retenu ET signale : jeter la moitie des donnees ne rend pas un verdict plus sur.
4. NOMBRE D'EPISODES DIVISIBLE PAR TOUTES LES VALEURS BALAYEES. Sinon le run s'arrete en laissant
   des episodes a moitie joues sur certains slots, et la configuration qui en laisse le plus est
   avantagee. Le contrele porte sur TOUTES les valeurs, pas seulement sur deux.
5. ECHEANCE HORAIRE FERME. L'outil tourne sans surveillance : avant chaque run il verifie qu'il
   a le temps de le finir, sinon il s'arrete et publie ce qu'il a. Un resultat partiel exploitable
   au reveil vaut mieux qu'un run tue en cours.
6. EXECUTION DANS UN ARBRE DE TRAVAIL SECONDAIRE, jamais dans le depot principal : un
   entrainement ecrit `ai/models/<agent>/model_<agent>.zip`, fichier protege. Meme garde que le
   banc, meme raison — et il a deja servi.

CE QUI EST MESURE, ET CE QUI NE L'EST PAS
-----------------------------------------
Le DEBIT EN REGIME ETABLI : l'inverse des secondes par episode mesurees entre deux
rafraichissements de la barre (cf. `read_steady_rate` dans `ab_bench.py`). Trois couts en sont
exclus, et tous trois croissent avec `n_envs` — les compter fabriquerait une pente sur l'axe
classe : le DEMARRAGE du process, la CLOTURE (sauvegarde, arret des workers), et le STOCK
d'episodes en vol (`n_envs` parties commencees et non terminees a tout instant, qui gonflent un
rapport cumule de `n_envs / episodes` : 33 % a n_envs=48 sur 144 episodes contre 4 % a n_envs=6).
LES CLASSEMENTS ANTERIEURS AU 2026-08-02 ONT ETE ETABLIS SUR LE WALL COMPLET et sont a reprendre.
Le wall, la part hors boucle et la fenetre de mesure restent journalises par run (`wall_s`,
`outside_loop_s`, `steady_window_ep`) : ils disent ce que coute la campagne, pas ce que vaut la
configuration. La cle de debit a ete RENOMMEE (`throughput_ep_s` -> `steady_throughput_ep_s`) le
2026-08-02 : le journal est ouvert en append, une meme cle pour deux grandeurs rendrait les lignes
d'avant et d'apres indiscernables.

NI le temps CPU, NI la part hors boucle AU VERDICT : le CPU sous-compte (les workers de
SubprocVecEnv n'entrent pas dans `getrusage`), et le hors-boucle est affiche a titre
d'information. Les durees de campagne annoncees dans le classement sont des WALL MESURES, jamais
une extrapolation du debit de regime — c'est sur le wall que se dimensionnent `--deadline` et
`--timeout`.

L'evaluation bot est desactivee sur ses deux chemins par `_run` (periodique et finale) : elle
lance ses propres sous-processus pendant le chronometre pour un cout etranger a `n_envs`. Le
verdict porte sur la BOUCLE D'ENTRAINEMENT SEULE.

Une passe d'apprentissage PPO coute identiquement dans toutes les configurations (meme nombre
d'echantillons, meme lot, meme GPU) : elle ne discrimine pas les configurations, elle ne fait que
reduire l'ecart relatif entre elles. `--episodes` doit malgre tout en contenir au moins une, sinon
le regime mesure — collecte pure, jamais d'apprentissage — n'existe dans aucun entrainement reel.

UN RUN QUI ECHOUE EST UNE DONNEE
--------------------------------
Une valeur de `n_envs` qui sature la memoire ou depasse le delai REPOND a la question posee. Elle
est retiree des tours suivants (elle ne peut plus etre comparee a rien) et rapportee comme telle.
C'est le seul endroit ou cet outil continue apres une erreur, et c'est un choix de mesure, pas un
filet de securite : l'echec est publie, jamais avale.

USAGE
-----
    git worktree add /tmp/40k-bench HEAD
    python3 scripts/ab_sweep_nenvs.py --envs 6,8,16,48 --episodes 144 --deadline 08:30
    git worktree remove /tmp/40k-bench
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import threading
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ab_bench_nenvs import RunFailed, _run  # noqa: E402

# Mesure du 2026-08-01 sur ArmageddonAgent/x1 (TensorBoard `game_critical/episode_length` : 70,
# 72, 80 pas sur trois episodes consecutifs ; le writer indexe par pas de temps confirme 480 pas
# pour 6 episodes). Sert uniquement a refuser en amont un `--episodes` trop court pour declencher
# la moindre passe d'apprentissage ; une valeur trop optimiste rendrait ce garde-fou permissif,
# d'ou la borne BASSE de l'intervalle observe.
TIMESTEPS_PER_EPISODE = 70
ROLLOUT_TIMESTEPS = 8192


class _MemorySampler:
    """Echantillonne la memoire disponible pendant un run et retient son minimum.

    Sans cette mesure, une configuration qui frole la saturation est indiscernable d'une
    configuration confortable : les deux rendent un wall-clock, et seule la premiere expliquera
    un echec au tour suivant.
    """

    def __init__(self, period: float = 5.0) -> None:
        self._period = period
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.min_available_mb: float | None = None

    @staticmethod
    def _available_mb() -> float:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return float(line.split()[1]) / 1024.0
        raise RuntimeError("/proc/meminfo ne publie pas MemAvailable")

    def _loop(self) -> None:
        while not self._stop.is_set():
            available = self._available_mb()
            if self.min_available_mb is None or available < self.min_available_mb:
                self.min_available_mb = available
            self._stop.wait(self._period)

    def __enter__(self) -> "_MemorySampler":
        self.min_available_mb = self._available_mb()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._period + 1.0)


def _parse_deadline(text: str) -> datetime:
    """Convertit `HH:MM` en instant absolu ; une heure deja passee designe demain."""
    try:
        hour, minute = (int(part) for part in text.split(":", 1))
    except ValueError:
        raise SystemExit(f"--deadline attendu au format HH:MM (recu {text!r})")
    now = datetime.now()
    deadline = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if deadline <= now:
        deadline += timedelta(days=1)
    return deadline


def _append_journal(path: str, record: dict) -> None:
    """Ajoute une ligne au journal JSON, vidée sur disque immediatement.

    Une campagne de plusieurs heures sans surveillance doit rester exploitable si la machine
    s'arrete : chaque run est ecrit des qu'il est connu, jamais accumule en memoire.
    """
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _lcm_all(values: list[int]) -> int:
    result = 1
    for value in values:
        result = result * value // math.gcd(result, value)
    return result


def _summarise(rounds: list[dict], envs: list[int], episodes: int, warmup_dropped: bool) -> str:
    """Classement par debit relatif au pivot du meme tour, puis mediane entre tours."""
    lines: list[str] = []
    # Pivot : la configuration presente dans TOUS les tours retenus. Prendre la premiere de la
    # liste triee garantit un choix stable et independant des resultats — un pivot choisi d'apres
    # les mesures (« la plus rapide ») deplacerait tous les ratios a chaque nouveau tour.
    common = [env for env in envs if all(env in rnd["throughput"] for rnd in rounds)]
    if not rounds or not common:
        return "aucun tour exploitable : pas une seule configuration mesuree dans tous les tours."
    pivot = common[0]

    ratios: dict[int, list[float]] = {env: [] for env in envs}
    for rnd in rounds:
        base = rnd["throughput"].get(pivot)
        if base is None:
            continue
        for env, throughput in rnd["throughput"].items():
            ratios[env].append(throughput / base)

    lines.append(
        f"\n{'=' * 78}\nCLASSEMENT — debit relatif a n_envs={pivot} (>1 = plus rapide que le pivot)\n"
        f"{len(rounds)} tour(s) retenu(s)"
        f"{' ; tour de chauffe jete' if warmup_dropped else ' ; AUCUN tour de chauffe jete'}\n{'=' * 78}"
    )
    ranked = sorted(
        ((env, values) for env, values in ratios.items() if values),
        key=lambda item: statistics.median(item[1]),
        reverse=True,
    )
    # Le wall MESURE, pas une extrapolation du debit de regime : celui-ci ignore le demarrage et
    # la cloture, donc il sous-estimerait la duree d'une campagne — or c'est sur cette duree que
    # se dimensionnent `--deadline` et `--timeout`.
    walls: dict = {}
    for rnd in rounds:
        for env, detail in rnd.get("details", {}).items():
            walls.setdefault(env, []).append(detail["wall"])
    for rank, (env, values) in enumerate(ranked, start=1):
        median = statistics.median(values)
        absolute = [
            rnd["throughput"][env] for rnd in rounds if env in rnd["throughput"]
        ]
        lines.append(
            f"{rank}. n_envs={env:3d}  debit relatif median={median:5.3f}  "
            f"etendue={min(values):5.3f}-{max(values):5.3f}  "
            f"debit absolu median={statistics.median(absolute):.4f} ep/s de regime  "
            f"(wall mesure median {statistics.median(walls[env]) / 60:.1f} min"
            f" pour {episodes} episodes)"
        )

    # Deux configurations dont les etendues se chevauchent ne sont pas departagees par cette
    # campagne. Le taire produirait un classement d'apparence nette sur des ecarts que la mesure
    # ne soutient pas — exactement ce que la ligne « L'ETENDUE ENJAMBE 1.000 » du banc previent.
    undecided: list[str] = []
    for first in range(len(ranked)):
        for second in range(first + 1, len(ranked)):
            env_a, values_a = ranked[first]
            env_b, values_b = ranked[second]
            if min(values_a) <= max(values_b) and min(values_b) <= max(values_a):
                undecided.append(f"n_envs={env_a} vs n_envs={env_b}")
    if undecided:
        lines.append(
            "\nNON TRANCHE (etendues qui se chevauchent — l'ordre affiche entre ces "
            "configurations n'est pas soutenu par la mesure) :\n  " + "\n  ".join(undecided)
        )
    else:
        lines.append("\nToutes les etendues sont disjointes : l'ordre ci-dessus est tranche.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="/tmp/40k-bench", help="arbre de travail secondaire")
    parser.add_argument("--envs", default="6,8,16,48", help="valeurs de n_envs, separees par des virgules")
    parser.add_argument("--episodes", type=int, default=144)
    parser.add_argument("--deadline", default="08:30", help="heure limite HH:MM")
    # L'echeance seule ne permet pas de commander un nombre de tours : il faut deviner leur duree,
    # et une estimation basse fait demarrer un tour de plus qui sera coupe en cours.
    parser.add_argument(
        "--tours", type=int, default=None,
        help="nombre de tours a executer (defaut : autant que l'echeance en autorise)",
    )
    parser.add_argument("--agent", default="ArmageddonAgent_x1")
    parser.add_argument("--scenario", default="bot")
    parser.add_argument("--training-config", default="x1")
    parser.add_argument("--journal", default=None, help="journal JSONL (defaut: a cote du script)")
    parser.add_argument(
        "--run-timeout-factor", type=float, default=3.0,
        help="delai maximal d'un run, en multiple de la duree observee la plus longue",
    )
    args = parser.parse_args()

    envs = sorted({int(value) for value in args.envs.split(",") if value.strip()})
    if len(envs) < 2:
        raise SystemExit("--envs doit contenir au moins deux valeurs distinctes.")

    main_repo = os.path.realpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    repo = os.path.realpath(args.repo)
    if repo == main_repo:
        raise SystemExit(
            "refus de mesurer dans le depot principal : chaque run ecrit "
            f"ai/models/{args.agent}/model_{args.agent}.zip, fichier protege.\n"
            f"    git -C {main_repo} worktree add {args.repo} HEAD"
        )
    if not os.path.isdir(repo):
        raise SystemExit(
            f"arbre de travail absent. Le creer une fois :\n"
            f"    git -C {main_repo} worktree add {args.repo} HEAD"
        )

    indivisible = [env for env in envs if args.episodes % env]
    if indivisible:
        lcm = _lcm_all(envs)
        raise SystemExit(
            f"--episodes {args.episodes} n'est pas divisible par {indivisible} : ces runs "
            f"laisseraient des episodes a moitie joues, inegalement selon la configuration. "
            f"Prendre un multiple de {lcm} (ex. {lcm * max(1, args.episodes // lcm)})."
        )
    timesteps = args.episodes * TIMESTEPS_PER_EPISODE
    if timesteps < ROLLOUT_TIMESTEPS:
        minimum = math.ceil(ROLLOUT_TIMESTEPS / TIMESTEPS_PER_EPISODE)
        lcm = _lcm_all(envs)
        raise SystemExit(
            f"--episodes {args.episodes} ne produit aucune passe d'apprentissage PPO "
            f"(~{timesteps} pas contre {ROLLOUT_TIMESTEPS} requis) : la mesure porterait sur la "
            f"collecte seule, un regime qui n'existe dans aucun entrainement reel. "
            f"Minimum {minimum} episodes, arrondi au multiple de {lcm} superieur : "
            f"{math.ceil(minimum / lcm) * lcm}."
        )

    deadline = _parse_deadline(args.deadline)
    journal = args.journal or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "ab_sweep_nenvs.jsonl"
    )

    print(
        f"balayage n_envs={envs}  episodes={args.episodes}  phase={args.training_config}\n"
        f"echeance {deadline:%Y-%m-%d %H:%M} ({(deadline - datetime.now()).total_seconds() / 60:.0f} min)\n"
        f"journal {journal}\n",
        flush=True,
    )

    rounds: list[dict] = []
    alive = list(envs)
    failures: list[str] = []
    durations: list[float] = []
    round_index = 0

    if args.tours is not None and args.tours < 1:
        raise SystemExit("--tours doit valoir au moins 1.")
    if args.tours is not None and args.tours < 3:
        print(
            f"AVERTISSEMENT : {args.tours} tour(s) demande(s). Le tour de chauffe n'est ecarte "
            f"qu'a partir de 3 tours ; en dessous il est RETENU, avec le biais de remplissage des "
            f"caches qu'il porte (mesure du 2026-08-01 : n_envs=16 a 664 s au tour 1 contre ~575 s "
            f"ensuite, soit 13 %).\n",
            flush=True,
        )

    while alive and (args.tours is None or round_index < args.tours):
        round_index += 1
        # Ordre inverse un tour sur deux. Le premier tour part des grandes valeurs : c'est la ou
        # une saturation memoire est le plus probable, et il vaut mieux la decouvrir au premier
        # run qu'apres des heures de mesures qui ne serviront a rien.
        order = sorted(alive, reverse=True) if round_index % 2 == 1 else sorted(alive)
        measured: dict[int, float] = {}
        details: dict[int, dict] = {}
        stopped = False

        for n_envs in order:
            remaining = (deadline - datetime.now()).total_seconds()
            estimate = max(durations) if durations else args.episodes * 10.0
            if remaining < estimate:
                print(
                    f"\nECHEANCE : {remaining / 60:.0f} min restantes, dernier run le plus long "
                    f"{estimate / 60:.0f} min. Arret avant le run n_envs={n_envs}.",
                    flush=True,
                )
                stopped = True
                break

            timeout = min(estimate * args.run_timeout_factor, remaining)
            started_at = datetime.now()
            try:
                with _MemorySampler() as sampler:
                    result = _run(
                        repo, args.agent, args.scenario, args.training_config,
                        args.episodes, n_envs, timeout=timeout,
                    )
            except RunFailed as failure:
                message = f"tour {round_index} n_envs={n_envs} : {failure}"
                print(f"  ECHEC {message}", flush=True)
                failures.append(message)
                alive = [env for env in alive if env != n_envs]
                _append_journal(journal, {
                    "round": round_index, "n_envs": n_envs, "status": "failed",
                    "started": started_at.isoformat(timespec="seconds"), "error": str(failure),
                })
                continue

            # Debit en REGIME ETABLI (cf. `read_steady_rate` dans ab_bench.py) : le fork
            # de N workers coute d'autant plus cher que N est grand, et un entrainement de
            # production de 150k a 200k episodes l'amortit jusqu'a le rendre negligeable. Le
            # compter penaliserait les grandes valeurs de `n_envs` sur un cout qui n'existe pas a
            # l'echelle ou elles servent — c'est ce que faisaient les campagnes anterieures au
            # 2026-08-02, dont les classements sont a reprendre.
            throughput = 1.0 / result["loop_rate"]
            measured[n_envs] = throughput
            details[n_envs] = result
            durations.append(result["wall"])
            record = {
                "round": round_index,
                "n_envs": n_envs,
                "status": "ok",
                "started": started_at.isoformat(timespec="seconds"),
                "wall_s": round(result["wall"], 2),
                "loop_s": round(result["loop_seconds"], 2),
                # Pas "startup" : ce delta couvre aussi la sauvegarde du modele, la fermeture des
                # workers et la sortie de l'interpreteur, qui suivent le dernier rafraichissement.
                "outside_loop_s": round(result["wall"] - result["loop_seconds"], 2),
                "steady_s_per_ep": result["loop_rate"],
                "steady_window_ep": list(result["rate_window"]),
                # Cle RENOMMEE le 2026-08-02 : `throughput_ep_s` designait un debit calcule sur le
                # wall complet. Le journal etant ouvert en append, garder le nom aurait rendu les
                # deux grandeurs indiscernables d'une campagne a l'autre.
                "steady_throughput_ep_s": round(throughput, 5),
                "min_available_mb": round(sampler.min_available_mb or 0.0, 1),
            }
            _append_journal(journal, record)
            print(
                f"  tour {round_index}  n_envs={n_envs:3d}  wall={result['wall']:7.1f}s  "
                f"hors-boucle={record['outside_loop_s']:6.1f}s  boucle={result['loop_seconds']:6.1f}s  "
                f"debit regime={throughput:.4f} ep/s  "
                f"RAM libre min={record['min_available_mb']:.0f} Mo",
                flush=True,
            )

        if measured:
            rounds.append({"index": round_index, "throughput": measured, "details": details})
        if stopped:
            break

    # Le tour de chauffe n'est ecarte que s'il reste de quoi conclure sans lui.
    warmup_dropped = len(rounds) >= 3
    retained = rounds[1:] if warmup_dropped else rounds

    print(_summarise(retained, envs, args.episodes, warmup_dropped), flush=True)
    if failures:
        print(
            "\nCONFIGURATIONS ECARTEES EN COURS DE CAMPAGNE :\n  " + "\n  ".join(failures),
            flush=True,
        )
    print(f"\njournal complet : {journal}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
