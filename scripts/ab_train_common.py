#!/usr/bin/env python3
"""Socle commun aux bancs qui lancent de VRAIS entrainements (`ab_bench_param`, `ab_bench_perf`).

CE QUE CE MODULE POSSEDE, ET POURQUOI IL EXISTE
-----------------------------------------------
Trois choses sont identiques entre un banc de DEBIT et un banc de QUALITE, et une seule differe
(la grandeur mesuree) :
  1. la construction de la ligne de commande `ai/train.py` et la neutralisation des chemins qui
     parasitent la mesure ;
  2. la mise a mort du GROUPE de processus en cas de depassement de delai — `train.py` fait
     tourner `n_envs` sous-processus qui survivraient a la mort de leur parent et pollueraient
     toutes les mesures suivantes ;
  3. le CONTROLE ANTI-CONFUSION : la preuve que le parametre demande est bien celui qui a servi,
     et que le budget d'episodes demande est bien celui qui a ete joue.
Les recopier de banc en banc, c'est le motif d'echec n°1 de ce depot : une correction faite d'un
cote et pas de l'autre. `ab_bench_nenvs.py` importe deja `drift_cancelled`/`validate_paires` de
`ab_bench.py` pour cette raison exacte ; ce module pousse le meme raisonnement jusqu'au bout.

Ce module ne mesure RIEN et ne rend aucun verdict : c'est le role des bancs qui l'importent.

SEULS `bot`, `self` et `all` SONT ACCEPTES COMME SCENARIO
--------------------------------------------------------
`--total-episodes` n'est PAS lu partout : `train.py` l'honore sur le chemin bot/self/all
(train.py:5145) et en mode rule-checker (:5012), mais le mode curriculum « Single phase mode »
(:5091) prend `max_episodes_in_phase` de la config et le chemin final `create_multi_agent_model`
(:5175) l'ignore. Un banc lance avec `--scenario phase1` jouerait donc 30000 episodes la ou il en
demande 96 : debit faux d'un facteur 300, `--timeout` sans rapport avec la charge reelle, et aucun
signal.
Ces memes chemins divergent sur un second point (cf. `_expected_n_steps`), et le mode curriculum
appelle `train_with_scenario_rotation` avec `silent_chunk=True` (:4364), ce qui supprime les
lignes dont ces bancs tirent leurs preuves. D'ou un refus a l'entree plutot que trois jeux de
regles paralleles.

LE CONTROLE ANTI-CONFUSION SE FAIT SUR LE MODELE SAUVEGARDE, PAS SUR LA SORTIE TEXTE
-----------------------------------------------------------------------------------
`ab_bench_nenvs.py` prouve la valeur de `n_envs` en cherchant "Creating K parallel environments"
dans la sortie. Cette methode ne se generalise pas : `train.py` n'annonce PAS `batch_size`,
`n_epochs`, `gamma`... et la seule trace disponible pour eux serait la ligne
"⚙️  Override: <chemin> = <valeur>" (train.py:1484). Or cette ligne prouve que l'override a ete
APPLIQUE A LA CONFIG CHARGEE, pas qu'il a survecu jusqu'a PPO — c'est-a-dire exactement le
scenario contre lequel le garde-fou existe ("une surcharge de configuration ecrase --param, la
mesure comparerait deux fois la meme chose").

La preuve utilisee ici est AVAL : l'archive `ai/models/<agent>/model_<agent>.zip` ecrite en fin de
run contient un membre `data` (JSON) ou SB3 serialise les hyperparametres REELLEMENT instancies —
`n_envs`, `n_steps`, `batch_size`, `n_epochs`, `gamma`, `learning_rate`, `seed`... On y lit ce que
PPO a utilise, pas ce que la config annoncait.

Cette sauvegarde est inconditionnelle tant que `save_best_robust` est faux (train.py:3249-3251) —
les deux bancs l'imposent deja, pour une autre raison (`bot_eval_freq` repousse hors de portee rend
la configuration robuste invalide). Le mtime de l'archive est verifie contre l'instant de
lancement : une archive laissee par un run precedent prouverait la configuration de ce run-la.

CE QUI N'EST PAS VERIFIABLE, ET QUI EST DONC REFUSE (jamais mesure en silence)
------------------------------------------------------------------------------
- `model_params.clip_range` : SB3 le convertit en fonction (`get_schedule_fn`) et le serialise en
  cloudpickle. La valeur n'est pas relisible sans desérialiser du code arbitraire.
- `model_params.policy_kwargs.*` (dont `net_arch`) : meme serialisation opaque.
- tout chemin absent de `_PROOFS` : il vaut mieux un refus qu'un banc qui compare deux fois la
  meme chose sans le savoir.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
import zipfile

# `assert_clean_environment` vit dans `ab_bench.py` avec les autres regles communes aux QUATRE
# bancs (`drift_cancelled`, `validate_paires`, `print_spread`) : `ab_bench.py` ne lance pas
# d'entrainement, il ne peut donc pas dependre de ce module-ci, et la faille qu'elle couvre —
# l'heritage de l'environnement par `subprocess` — les concerne tous. Reexporte ici parce que
# les deux bancs de parametres l'importent de ce socle.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ab_bench import assert_clean_environment  # noqa: E402,F401

# Chemins de config PILOTABLES par les bancs, et leur preuve dans le membre `data` du zip SB3.
# La cle est le CHEMIN COMPLET dans la config, jamais un alias `--param` : dupliquer la table
# `_PARAM_ALIASES` de train.py:1433 en ferait un jumeau a maintenir en double.
_PROOFS = {
    "n_envs": "n_envs",
    "model_params.n_steps": "n_steps",  # cas particulier, cf. `_expected_n_steps`
    "model_params.batch_size": "batch_size",
    "model_params.n_epochs": "n_epochs",
    "model_params.gamma": "gamma",
    "model_params.gae_lambda": "gae_lambda",
    "model_params.vf_coef": "vf_coef",
    "model_params.max_grad_norm": "max_grad_norm",
    "model_params.target_kl": "target_kl",
    "model_params.learning_rate": "learning_rate",
    "model_params.ent_coef": "ent_coef",
    "model_params.seed": "seed",
}

# Chemins explicitement refuses, avec la raison — un message precis vaut mieux qu'un "inconnu".
_UNPROVABLE = {
    "model_params.clip_range": (
        "SB3 convertit clip_range en fonction (get_schedule_fn) et la serialise en cloudpickle : "
        "la valeur effective n'est pas relisible sans desérialiser du code arbitraire."
    ),
    "model_params.policy_kwargs": (
        "policy_kwargs (dont net_arch) est serialise en cloudpickle dans le zip : illisible."
    ),
}

# Ces deux cles portent un SCHEDULE quand la config les declare en dict, et un callback ecrase
# alors la valeur du modele pendant le run (train.py:3445-3461 pour learning_rate, :3464 pour
# ent_coef). Le zip de fin de run porterait la valeur FINALE du schedule, pas celle demandee.
# Une valeur scalaire passee en --param remplace le dict et desactive le callback : c'est le seul
# regime ou ces cles sont mesurables, et il differe de celui de la production.
_SCHEDULABLE = ("model_params.learning_rate", "model_params.ent_coef")

# Scenarios dont le chemin dans train.py honore --total-episodes ET applique le regime de n_steps
# documente dans `_expected_n_steps`. Cf. l'en-tete : les autres sont refuses.
_SUPPORTED_SCENARIOS = ("bot", "self", "all")

_CLI_EPISODES_RE = re.compile(r"Using total_episodes from CLI: (\d+)")
_EPISODES_TRAINED_RE = re.compile(r"Total episodes trained: (\d+)")
_N_STEPS_RE = re.compile(
    r"using n_steps=(\d+) per env \((\d+) total per update, config asked (\d+)\)"
)


class RunFailed(RuntimeError):
    """L'entrainement lui-meme a echoue (code de retour non nul, ou depassement du delai).

    Distincte de `SystemExit` : une incoherence de CONFIGURATION invalide toute la campagne et
    doit l'arreter, alors qu'un run qui echoue est une DONNEE — une valeur de parametre qui
    sature la machine repond a la question posee. Au banc de decider s'il continue sans elle.
    """


def model_zip_path(repo: str, agent: str) -> str:
    return os.path.join(repo, "ai", "models", agent, f"model_{agent}.zip")


def assert_scenario_supported(scenario: str) -> None:
    if scenario not in _SUPPORTED_SCENARIOS:
        raise SystemExit(
            f"--scenario {scenario} : non mesurable par ce banc. Seuls "
            f"{', '.join(_SUPPORTED_SCENARIOS)} honorent --total-episodes (train.py:5145) ; le "
            f"mode curriculum prend max_episodes_in_phase de la config (:5091) et le chemin "
            f"create_multi_agent_model ignore l'option (:5175). Le banc jouerait alors le budget "
            f"de la config au lieu de --episodes, sans aucun signal."
        )


def read_phase_config(repo: str, agent: str, phase: str) -> dict:
    """Config de phase RESOLUE, telle que `train.py` la verra.

    Passe par le `config_loader` DU WORKTREE plutot que par une lecture du JSON : une phase peut
    mettre une cle a `null` pour heriter de `config/agents/_training_common.json`
    (config_loader.py:326, idiome deja utilise par ArmageddonAgent). Une lecture brute verrait
    `n_envs: null` — controle de divisibilite en echec sur un cas parfaitement valide — et
    surtout ne verrait pas un `learning_rate` schedule herite, donc supprimerait le schedule sans
    l'avertissement prevu. Le sous-processus coute ~30 ms et n'importe pas torch.
    """
    proc = subprocess.run(
        [
            sys.executable, "-c",
            "import json,sys;from config_loader import get_config_loader;"
            "print(json.dumps(get_config_loader().load_agent_training_config(sys.argv[1], sys.argv[2])))",
            agent, phase,
        ],
        cwd=repo, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"config de phase '{phase}' illisible pour l'agent {agent} dans {repo} :\n"
            f"{proc.stderr[-2000:]}"
        )
    return json.loads(proc.stdout)


def config_lookup(block: dict, path: str):
    """Rend la valeur au chemin pointe dans un bloc de config, ou leve KeyError."""
    node = block
    for key in path.split("."):
        if not isinstance(node, dict) or key not in node:
            raise KeyError(path)
        node = node[key]
    return node


def assert_provable(path: str) -> None:
    """Refuse tout chemin dont la valeur effective ne peut pas etre prouvee apres le run."""
    if path in _UNPROVABLE:
        raise SystemExit(f"--param {path} n'est pas mesurable par ce banc : {_UNPROVABLE[path]}")
    if path not in _PROOFS:
        raise SystemExit(
            f"--param {path} n'a pas de preuve aval connue.\n"
            f"Le banc n'accepte que les chemins dont SB3 serialise la valeur effective dans "
            f"model_<agent>.zip :\n    " + "\n    ".join(sorted(_PROOFS)) + "\n"
            f"Attention : ce sont des CHEMINS COMPLETS, pas les alias courts de --param "
            f"(train.py:1433). Ecrire 'model_params.batch_size', pas 'batch_size'."
        )


def assert_not_scheduled(
    phase_block: dict, path: str, requested: str, allow_removal: bool = False
) -> None:
    """Interdit de mesurer une cle schedulee, et de la mesurer sans savoir qu'on la desactive.

    Deux refus distincts :
    - la valeur DEMANDEE est un dict : le banc ne sait pas comparer deux schedules ;
    - la config declare un schedule pour cette cle : l'override scalaire le SUPPRIME (le callback
      n'est branche que si la config est un dict). La mesure reste honnete — les deux cotes
      subissent la meme suppression — mais elle ne porte plus sur le regime de production, et
      cela doit etre un choix explicite, pas une surprise.
    """
    if path not in _SCHEDULABLE:
        return
    if requested.strip().startswith("{"):
        raise SystemExit(f"--param {path} : ce banc ne compare que des valeurs scalaires.")
    try:
        current = config_lookup(phase_block, path)
    except KeyError:
        return
    if isinstance(current, dict) and not allow_removal:
        raise SystemExit(
            f"{path} est declare comme SCHEDULE dans la config de phase resolue ({current}). Lui "
            f"donner une valeur scalaire supprime le callback de schedule des DEUX cotes : le "
            f"verdict ne porterait plus sur le regime de production. Relancer avec "
            f"--autoriser-suppression-schedule si c'est bien ce qui est voulu."
        )


def run_training(
    repo: str,
    agent: str,
    scenario: str,
    training_config: str,
    episodes: int,
    overrides: list,
    bot_eval_final: int,
    timeout: float | None = None,
) -> dict:
    """Un entrainement complet. Rend {'wall', 'output', 'effective', 'episodes_trained'}.

    `overrides` est une liste de (chemin, valeur) passee telle quelle a `--param`.
    `bot_eval_final` : 0 pour un banc de debit (l'evaluation finale n'a rien a voir avec ce qu'il
    mesure et l'ecrase — mesure : 6 episodes d'entrainement = 21 s, evaluation finale > 13 min),
    N > 0 pour un banc de qualite, dont c'est justement la grandeur mesuree.

    L'evaluation bot PERIODIQUE est repoussee hors de portee dans les deux cas : elle lance ses
    propres sous-processus au milieu du run, pour un cout etranger au parametre compare.
    """
    assert_scenario_supported(scenario)
    assert_clean_environment()
    zip_path = model_zip_path(repo, agent)
    command = [
        sys.executable, "ai/train.py",
        "--agent", agent,
        "--scenario", scenario,
        "--training-config", training_config,
        "--new",
        "--total-episodes", str(episodes),
        # Evaluation periodique hors de portee.
        "--param", "callback_params.bot_eval_freq", "1000000000",
        # Consequence obligatoire de la ligne precedente : `save_best_robust` exige au moins
        # `robust_window` evaluations et refuse la configuration sinon (train.py, "Invalid
        # robust-eval configuration"). C'est aussi ce qui rend la sauvegarde finale du modele
        # inconditionnelle (train.py:3249), donc ce qui rend le controle anti-confusion possible.
        "--param", "callback_params.save_best_robust", "false",
        "--param", "callback_params.bot_eval_final", str(bot_eval_final),
    ]
    for key, value in overrides:
        command += ["--param", key, str(value)]

    started_wall = time.perf_counter()
    started_stamp = time.time()
    proc = subprocess.Popen(
        command, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # Le GROUPE, pas le seul fils : les workers SubprocVecEnv survivraient a leur parent.
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        stdout, stderr = proc.communicate()
        wall = time.perf_counter() - started_wall
        raise RunFailed(
            f"{overrides} : delai de {timeout:.0f}s depasse (tue a {wall:.0f}s). Une "
            f"configuration qui ne tient pas dans ce delai est perdante par construction."
        )
    wall = time.perf_counter() - started_wall
    output = stdout + stderr
    if proc.returncode != 0:
        raise RunFailed(
            f"{overrides} : code de retour {proc.returncode}\n{stdout[-3000:]}{stderr[-3000:]}"
        )
    return {
        "wall": wall,
        "output": output,
        "effective": _read_effective(zip_path, started_stamp),
        "episodes_trained": _episodes_trained(output, episodes),
    }


def _episodes_trained(output: str, requested: int) -> int:
    """Nombre d'episodes REELLEMENT joues, apres controle que le budget CLI a bien ete pris.

    Deux traces distinctes et toutes deux necessaires : "Using total_episodes from CLI"
    (train.py:5150) prouve que `--total-episodes` a ete lu — un chemin qui l'ignore ne l'imprime
    pas — et "Total episodes trained" (train.py:3277) donne le compte final, qui depasse
    legerement le budget puisque les `n_envs` slots ne terminent pas au meme instant. Les bancs
    normalisent leur debit sur ce compte-la, jamais sur le budget demande.
    """
    cli = _CLI_EPISODES_RE.search(output)
    if cli is None:
        raise SystemExit(
            "train.py n'a pas annonce 'Using total_episodes from CLI' : le budget d'episodes "
            "vient de la config, pas de --episodes. La mesure porterait sur une autre charge que "
            "celle demandee."
        )
    if int(cli.group(1)) != requested:
        raise SystemExit(
            f"budget CLI annonce {cli.group(1)}, demande {requested} : incoherence de commande."
        )
    trained = _EPISODES_TRAINED_RE.search(output)
    if trained is None:
        raise SystemExit(
            "aucun 'Total episodes trained' dans la sortie : le run s'est-il arrete avant la fin "
            "de la boucle, ou le bloc de cloture a-t-il change de format ? Sans ce compte, le "
            "debit ne se calcule pas."
        )
    count = int(trained.group(1))
    if count <= 0:
        raise SystemExit("'Total episodes trained: 0' : aucun episode joue, rien a mesurer.")
    return count


def _read_effective(zip_path: str, started_stamp: float) -> dict:
    """Hyperparametres REELLEMENT instancies, lus dans le modele que le run vient d'ecrire."""
    if not os.path.isfile(zip_path):
        raise SystemExit(
            f"aucun modele sauvegarde en {zip_path} : sans lui, rien ne prouve quelle "
            f"configuration a servi. La sauvegarde finale est-elle desactivee "
            f"(save_best_robust) ou le run s'est-il arrete avant la fin ?"
        )
    if os.path.getmtime(zip_path) < started_stamp:
        raise SystemExit(
            f"{zip_path} est anterieur au lancement du run : c'est le modele d'un run precedent, "
            f"il prouverait la configuration de CE run-la. Le run courant n'a rien sauvegarde."
        )
    with zipfile.ZipFile(zip_path) as archive:
        return json.loads(archive.read("data"))


def parse_value(value: str):
    """Interprete une valeur d'option comme le fera `train.py` (_parse_param_value, train.py:1451).

    Necessaire pour comparer la valeur DEMANDEE (du texte, cote banc) a la valeur EFFECTIVE (un
    nombre, lu dans le zip). La regle est volontairement la meme que celle de train.py : si les
    deux divergeaient, le banc validerait une valeur que PPO n'a pas recue.
    """
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    return value


def _expected_n_steps(output: str, requested):
    """Valeur de `n_steps` attendue dans le zip — LUE dans la sortie, pas deduite.

    `n_steps` est un TOTAL par update : `apply_rollout_n_steps` (train.py) donne `base // n_envs`
    a PPO quand `n_envs > 1`. C'est desormais un invariant des TROIS chemins vectorises ; ca ne
    l'etait pas — `create_model` et `create_multi_agent_model` passaient `model_params` tel quel,
    d'ou les deux regimes visibles dans les zips de `ai/models/ArmageddonAgent/` a `n_envs=8`
    identique. La lecture de la ligne reste la methode : sa PRESENCE prouve le regime applique,
    plutot qu'une division deduite qui ferait echouer le controle sur un vieux modele.

    LE TOTAL ANNONCE EST CELUI OBTENU, PAS CELUI DEMANDE. `//` tronque : a `n_envs=48`, une
    demande de 8192 donne 170 x 48 = 8160. L'ancienne ligne rejouait la valeur DEMANDEE, ce qui
    masquait la troncature — et le clamp `max(1, ...)` avec elle. C'est le trou signale : a
    `n_envs=48`, comparer `n_steps` 32 et 40 validait les deux cotes alors que PPO tournait a
    1 x 48 dans les deux cas, donc le banc comparait deux fois la meme configuration. La
    troncature au plancher est maintenant un refus explicite.
    """
    match = _N_STEPS_RE.search(output)
    if match is None:
        # Pas de division annoncee : n_envs vaut 1, PPO recoit la valeur demandee telle quelle.
        return int(requested)
    per_env, total, asked = (int(match.group(i)) for i in (1, 2, 3))
    if asked != int(requested):
        raise SystemExit(
            f"train.py a recu {asked} comme n_steps total, {requested} demandes : une "
            f"surcharge de configuration ecrase --param."
        )
    n_envs = total // per_env
    if per_env == 1 and asked < n_envs:
        raise SystemExit(
            f"n_steps={asked} avec n_envs={n_envs} : `max(1, {asked} // {n_envs})` ramene PPO a "
            f"1 pas par env. Toute valeur inferieure a {n_envs} donne le MEME rollout, donc la "
            f"paire comparerait deux fois la meme configuration. Demander n_steps >= {n_envs}."
        )
    return per_env


def assert_effective(run: dict, path: str, requested) -> None:
    """Verifie que PPO a bien recu la valeur demandee. Leve `SystemExit` sinon.

    C'est LE garde-fou de ces bancs : sans lui, une surcharge de configuration ferait comparer
    deux fois la meme chose et le verdict serait du bruit presente comme un resultat.
    """
    assert_provable(path)
    effective = run["effective"]
    key = _PROOFS[path]
    if key not in effective:
        raise SystemExit(
            f"cle '{key}' absente du modele sauvegarde : la serialisation SB3 a-t-elle change ? "
            f"Sans cette cle, la valeur effective de {path} n'est pas prouvable."
        )
    got = effective[key]
    if isinstance(got, dict):
        raise SystemExit(
            f"{path} vaut un objet serialise dans le modele ({sorted(got)[:3]}...) : c'est un "
            f"schedule ou une fonction, pas une valeur. Comparaison impossible."
        )
    if path == "model_params.n_steps":
        expected = _expected_n_steps(run["output"], requested)
    else:
        expected = requested
    if isinstance(expected, float) or isinstance(got, float):
        # Passage par --param -> texte -> float : l'egalite exacte est le bon test tant que la
        # valeur vient d'un decimal court, mais une tolerance relative evite un faux echec sur
        # une valeur issue d'un arrondi de config.
        agree = abs(float(got) - float(expected)) <= 1e-9 * max(1.0, abs(float(expected)))
    else:
        agree = got == expected
    if not agree:
        detail = f" (attendu {expected} apres division par n_envs)" if expected != requested else ""
        raise SystemExit(
            f"{path} demande {requested}, valeur effective dans le modele {got}{detail} : une "
            f"surcharge de configuration ecrase --param, la mesure comparerait deux fois la meme "
            f"chose."
        )


def assert_worktree(repo_arg: str, agent: str) -> str:
    """Impose un arbre de travail secondaire. Rend le chemin resolu.

    Le controle interroge GIT sur la cible, il ne la compare pas a une reference deduite.
    Dans un worktree lie, `--absolute-git-dir` vaut `<principal>/.git/worktrees/<nom>` tandis
    que `--git-common-dir` vaut `<principal>/.git` : ils DIFFERENT. Dans le depot principal ils
    sont identiques. C'est exactement la propriete voulue (« --repo est-il un worktree
    secondaire ? »), testee directement.

    L'implementation precedente definissait le depot principal comme le parent du SCRIPT
    EXECUTE (`os.path.dirname(__file__)`). Lancer le banc depuis le worktree — le cas d'usage
    normal, puisque c'est la que le code teste vit — faisait donc valoir `main_repo` = worktree,
    et `--repo /home/greg/40k` passait le controle : le banc entrainait dans le depot principal
    et ecrasait `ai/models/<agent>/model_<agent>.zip`, LE fichier que le message dit proteger.
    Le garde-fou se retournait contre son propre objet.

    Un `git` absent, une cible hors depot ou une sortie inattendue LEVENT : un controle de
    securite qui ne peut pas conclure doit refuser, jamais laisser passer.
    """
    repo = os.path.realpath(repo_arg)
    if not os.path.isdir(repo):
        raise SystemExit(
            f"arbre de travail absent : {repo_arg}\n"
            f"    git worktree add {repo_arg} HEAD"
        )
    try:
        proc = subprocess.run(
            ["git", "-C", repo, "rev-parse", "--absolute-git-dir", "--git-common-dir"],
            capture_output=True, text=True, check=True,
        )
    except FileNotFoundError:
        raise SystemExit("git introuvable : impossible de verifier que --repo est un worktree.")
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            f"--repo n'est pas un depot git : {repo}\n    {exc.stderr.strip()}"
        )
    parts = proc.stdout.split()
    if len(parts) != 2:
        raise SystemExit(
            f"sortie git rev-parse inattendue pour {repo} : {proc.stdout!r}"
        )
    git_dir = os.path.realpath(parts[0])
    # `--git-common-dir` peut etre relatif ; `-C repo` fait de `repo` le repertoire courant de git.
    common_raw = parts[1]
    git_common_dir = os.path.realpath(
        common_raw if os.path.isabs(common_raw) else os.path.join(repo, common_raw)
    )
    if git_dir == git_common_dir:
        raise SystemExit(
            "refus de mesurer dans le depot principal : chaque run ecrit "
            f"ai/models/{agent}/model_{agent}.zip, fichier protege.\n"
            f"    git -C {repo} worktree add ../bench-{agent} HEAD"
        )
    return repo
