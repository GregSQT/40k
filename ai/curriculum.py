"""Curriculum d'entrainement par ETAPES : learners `P0..P10`, exploiteurs `E1..E3`.

Une ETAPE est un run complet d'`ai/train.py`. Elle declare comment le modele DEMARRE (`init`),
et contre QUI il joue (`ratio_start`/`ratio_end`/`warmup_episodes` + `pool`). Le nombre
d'episodes et les hyperparametres restent la propriete de `--training-config` : une etape ne
decrit QUE l'adversite.

DEUX AXES ORTHOGONAUX, et c'est tout le point de ce module :

1. La FRONTIERE bots / pool est pilotee par la rampe (`ramped_ratio`). Elle vaut `ratio_start`
   pendant le warmup, puis interpole lineairement jusqu'a `ratio_end`. C'est un tirage
   PAR EPISODE, local a chaque environnement.

2. La COMPOSITION INTERNE du pool est FIXE, et realisee PAR ENVIRONNEMENT
   (`assign_pool_members_to_envs`) : chaque environnement se voit attribuer UN adversaire fige,
   une fois pour toutes, et le charge une seule fois. C'est ce qui garde l'empreinte memoire a
   un modele fige par processus (`BotControlledEnv._frozen_model`) malgre un pool de treize
   membres sur quarante-huit processus. Un tirage par episode aurait exige de garder les treize
   modeles vivants dans CHAQUE worker.

Les deux axes se recomposent exactement : l'environnement affecte au membre `m` joue contre lui
avec la probabilite `ramped_ratio(t)`, et la part des environnements affectes a `m` vaut
`poids(m) / ratio_end`. La part globale de `m` en fin de rampe vaut donc
`ratio_end * poids(m) / ratio_end = poids(m)` — le poids ecrit dans le JSON est une part du
budget TOTAL d'episodes, pas une part du pool.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

from shared.data_validation import require_key, require_non_negative_int, require_positive_int

#: Tolerance des sommes de ratios. Les poids sont ecrits a deux decimales dans le JSON ; la
#: somme flottante de treize d'entre eux ne retombe pas sur 1.0 au bit pres.
RATIO_SUM_TOLERANCE = 1e-9

#: Roles possibles d'une etape. `learner` = champion candidat (la lignee `P`), `exploiter` =
#: agent dedie a exploiter UN champion (la lignee `E`), jamais promu champion lui-meme.
STAGE_ROLES = ("learner", "exploiter")

#: Natures de membre du pool, telles qu'ecrites dans `curriculum.json`. `champion` designe le
#: champion le PLUS RECENT : c'est lui, et lui seul, que le gate de fin d'etape mesure.
POOL_KINDS = ("champion", "ancients", "exploiters")

CURRICULUM_FILENAME = "curriculum.json"

#: Nom du journal d'etapes, en APPEND a la racine du projet. Jumeau de `step.log`.
CURRICULUM_LOG_FILENAME = "curriculum.log"

#: Cles obligatoires du bloc `exploiter_config` dans `curriculum.json`.
_EXPLOITER_CONFIG_REQUIRED_KEYS = (
    "probe_every_episodes",
    "probe_cheap_n",
    "probe_confirm_n",
    "win_rate_target",
)

#: Cles obligatoires du bloc `early_stop` (racine et surcharge par etape).
_EARLY_STOP_REQUIRED_KEYS = ("win_rate_threshold", "min_steps", "consecutive_evals")

#: Cles autorisees au niveau racine de `training_config_overrides` d'une etape learner.
#: Toute cle absente de cette liste est refusee a la validation du curriculum.
#: Les cles structurelles (deployment_mode_schedule, obs_size, vec_normalize, n_envs, seed)
#: ne sont PAS autorisees : elles doivent rester identiques entre toutes les etapes pour
#: que les modeles soient comparables et que les tests de profil ne divergent pas.
STAGE_HP_OVERRIDES_ALLOWED_TOP_KEYS: frozenset = frozenset({
    "total_episodes", "model_params", "callback_params",
})

#: Sous-cles de `model_params` autorisees dans un override d'etape.
STAGE_HP_OVERRIDES_ALLOWED_MODEL_PARAMS: frozenset = frozenset({
    "learning_rate", "ent_coef", "n_epochs", "vf_coef",
})

#: Sous-cles de `callback_params` autorisees dans un override d'etape.
#: `bot_eval_freq` et `bot_eval_final` sont les seuls parametres d'evaluation qui dependent
#: directement de `total_episodes` : les declarer explicitement ici co-localise la decision
#: d'evaluation avec la decision de duree, sans creer deux sources de verite pour les valeurs
#: par defaut qui restent dans x1_long.
STAGE_HP_OVERRIDES_ALLOWED_CALLBACK_PARAMS: frozenset = frozenset({
    "bot_eval_freq", "bot_eval_final",
})


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def curriculum_path(agent_key: str) -> str:
    """Chemin de `config/agents/<agent>/curriculum.json`."""
    if not isinstance(agent_key, str) or not agent_key.strip():
        raise ValueError(f"agent_key doit etre une chaine non vide (got {agent_key!r})")
    return os.path.join(_project_root(), "config", "agents", agent_key, CURRICULUM_FILENAME)


def load_curriculum(agent_key: str) -> Dict[str, Any]:
    """Lit et VALIDE le curriculum de l'agent. Absent = erreur explicite, jamais un curriculum vide."""
    path = curriculum_path(agent_key)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Curriculum absent pour l'agent {agent_key!r} : {path}. "
            "--etape exige ce fichier ; sans lui aucune etape n'est definissable."
        )
    with open(path, "r", encoding="utf-8-sig") as handle:
        curriculum = json.load(handle)
    if not isinstance(curriculum, dict):
        raise TypeError(f"{path} doit contenir un objet JSON (got {type(curriculum).__name__})")
    validate_curriculum(curriculum, path)
    return curriculum


def stage_order(curriculum: Dict[str, Any]) -> List[str]:
    """Ordre d'execution DECLARE des etapes. C'est lui qui definit « anterieure a »."""
    order = require_key(curriculum, "order")
    if not isinstance(order, list) or not order:
        raise TypeError("curriculum.order doit etre une liste non vide de noms d'etapes.")
    return [str(name) for name in order]


def require_stage(curriculum: Dict[str, Any], stage_name: str) -> Dict[str, Any]:
    """L'etape nommee, ou un refus qui ENUMERE les etapes connues.

    Une etape inconnue est une faute de frappe dans une commande qui lance des heures
    d'entrainement : le refus doit donner de quoi la corriger sans ouvrir le JSON.
    """
    stages = require_key(curriculum, "stages")
    if not isinstance(stages, dict):
        raise TypeError("curriculum.stages doit etre un objet.")
    if stage_name not in stages:
        raise ValueError(
            f"Etape inconnue : {stage_name!r}. Etapes declarees (dans l'ordre d'execution) : "
            f"{', '.join(stage_order(curriculum))}."
        )
    stage = stages[stage_name]
    if not isinstance(stage, dict):
        raise TypeError(f"curriculum.stages[{stage_name!r}] doit etre un objet.")
    return stage


def stage_init_source(stage: Dict[str, Any]) -> Optional[str]:
    """L'etape dont celle-ci reprend les poids, ou None quand `init` vaut 'new'."""
    init = str(require_key(stage, "init")).strip()
    if init == "new":
        return None
    if not init.startswith("from:"):
        raise ValueError(f"stage.init doit valoir 'new' ou 'from:<etape>' (got {init!r})")
    source = init[len("from:"):].strip()
    if not source:
        raise ValueError("stage.init 'from:' doit nommer une etape (got 'from:').")
    return source


def stage_pool_members(stage: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Les membres du pool, groupes DEPLIES, chaque membre portant son poids individuel.

    Le JSON ecrit `{"kind": "ancients", "members": ["P0", "P1"], "weight": 0.30}` : un groupe
    porte UN poids, reparti a parts egales entre ses membres. C'est la forme lisible de la
    specification (« P0-P1 30 ») ; deplier ici evite d'ecrire `0.15` deux fois dans le JSON et
    `0.0444...` neuf fois pour « P0-P8 40 ».
    """
    pool = require_key(stage, "pool")
    if not isinstance(pool, list):
        raise TypeError("stage.pool doit etre une liste de groupes.")
    members: List[Dict[str, Any]] = []
    for group_index, group in enumerate(pool):
        if not isinstance(group, dict):
            raise TypeError(f"stage.pool[{group_index}] doit etre un objet.")
        kind = str(require_key(group, "kind"))
        if kind not in POOL_KINDS:
            raise ValueError(
                f"stage.pool[{group_index}].kind doit valoir l'un de {POOL_KINDS} (got {kind!r})"
            )
        group_members = require_key(group, "members")
        if not isinstance(group_members, list) or not group_members:
            raise TypeError(f"stage.pool[{group_index}].members doit etre une liste non vide.")
        weight = float(require_key(group, "weight"))
        if not (0.0 < weight <= 1.0):
            raise ValueError(
                f"stage.pool[{group_index}].weight doit etre dans ]0,1] (got {weight})"
            )
        share = weight / float(len(group_members))
        for label in group_members:
            members.append({"label": str(label), "kind": kind, "weight": share})
    labels = [member["label"] for member in members]
    if len(set(labels)) != len(labels):
        raise ValueError(f"stage.pool nomme deux fois la meme etape : {labels}")
    return members


def stage_champion_label(stage: Dict[str, Any]) -> Optional[str]:
    """Le champion le plus recent du pool, cible du gate. None quand l'etape n'en a pas (P0)."""
    champions = [m["label"] for m in stage_pool_members(stage) if m["kind"] == "champion"]
    if not champions:
        return None
    if len(champions) > 1:
        raise ValueError(
            "une etape n'a qu'UN champion le plus recent, le gate ne sait pas lequel mesurer "
            f"(got {champions})"
        )
    return champions[0]


# ── EXPLOITEURS ────────────────────────────────────────────────────────────────────────────


def is_exploiter_stage(stage: Dict[str, Any]) -> bool:
    """Vrai quand l'etape a le role 'exploiter' (lignee E)."""
    return str(require_key(stage, "role")) == "exploiter"


def load_exploiter_config(curriculum: Dict[str, Any]) -> Dict[str, Any]:
    """Le bloc `exploiter_config` du curriculum. Absent = erreur explicite."""
    cfg = require_key(curriculum, "exploiter_config")
    if not isinstance(cfg, dict):
        raise TypeError("curriculum.exploiter_config doit etre un objet JSON.")
    return cfg


def validate_exploiter_protocol(
    curriculum: Dict[str, Any],
    stage: Dict[str, Any],
    stage_name: str,
    training_config_name: str,
    profile_total_episodes: Optional[int] = None,
) -> None:
    """Refuse le run si la configuration de l'etape exploiteur diverge du protocole gele.

    Trois verrous :
    1. Role exploiter, ratio_start==1.0, ratio_end==1.0, warmup_episodes==0.
    2. Un seul membre de pool a weight==1.0 (adversaire unique fige a 100%).
    3. total_episodes du profil >= budget_cap : un run plus court que le plafond rend la
       branche de censure inatteignable et le marqueur '>budget_cap' jamais emis.
       Fournir `profile_total_episodes` depuis le profil charge pour activer ce verrou.

    Appele dans `_prepare_curriculum_stage` AVANT le demarrage du run.
    """
    if not is_exploiter_stage(stage):
        raise ValueError(
            f"validate_exploiter_protocol : {stage_name} n'est pas une etape exploiteur "
            f"(role={stage.get('role')!r}). Appel incorrect."
        )
    ratio_start = float(require_key(stage, "ratio_start"))
    ratio_end = float(require_key(stage, "ratio_end"))
    warmup = int(require_key(stage, "warmup_episodes"))
    if ratio_start != 1.0 or ratio_end != 1.0 or warmup != 0:
        raise ValueError(
            f"Etape exploiteur {stage_name} : protocole gele exige ratio_start=1.0, "
            f"ratio_end=1.0, warmup_episodes=0 "
            f"(got ratio_start={ratio_start}, ratio_end={ratio_end}, warmup={warmup}). "
            "Corriger l'etape dans curriculum.json ou choisir une autre etape."
        )
    members = stage_pool_members(stage)
    if len(members) != 1 or abs(members[0]["weight"] - 1.0) > RATIO_SUM_TOLERANCE:
        raise ValueError(
            f"Etape exploiteur {stage_name} : un seul membre de pool a weight=1.0 est autorise "
            f"(got {[(m['label'], m['weight']) for m in members]!r})."
        )
    if profile_total_episodes is not None:
        budget_cap = int(require_key(stage, "budget_cap"))
        if profile_total_episodes < budget_cap:
            raise ValueError(
                f"Etape exploiteur {stage_name} : le profil '{training_config_name}' a "
                f"total_episodes={profile_total_episodes} < budget_cap={budget_cap}. "
                "La branche de censure '>budget_cap' est inatteignable — le run s'arreterait "
                "avant d'atteindre le plafond. Choisir un profil dont total_episodes >= budget_cap "
                "ou abaisser budget_cap dans l'etape du curriculum."
            )


def _validate_early_stop_block(block: Any, context: str) -> None:
    """Valide un bloc `early_stop` (racine ou par etape). Leve si une cle est absente ou invalide."""
    if not isinstance(block, dict):
        raise TypeError(f"{context} doit etre un objet JSON.")
    threshold = float(require_key(block, "win_rate_threshold"))
    require_non_negative_int(require_key(block, "min_steps"), "min_steps")
    require_positive_int(require_key(block, "consecutive_evals"), "consecutive_evals")
    if not (0.0 < threshold <= 1.0):
        raise ValueError(f"{context}.win_rate_threshold doit etre dans ]0,1] (got {threshold})")


def validate_curriculum(curriculum: Dict[str, Any], source: str = "<curriculum>") -> None:
    """Verrous structurels du curriculum. Tout manquement leve, aucun n'est rattrape.

    VERROU CENTRAL : la somme des ratios d'une etape vaut 1.0. Les bots prennent
    `1 - ratio_end`, le pool prend `ratio_end` reparti entre ses groupes — donc la somme des
    poids de groupes DOIT valoir `ratio_end`. Sans ce controle, un poids mal recopie deplace
    silencieusement de l'adversite vers les bots, ce qui ne se voit ni dans une courbe ni dans
    un score.
    """
    order = stage_order(curriculum)
    if len(set(order)) != len(order):
        raise ValueError(f"{source}: curriculum.order contient un doublon : {order}")
    stages = require_key(curriculum, "stages")
    if not isinstance(stages, dict):
        raise TypeError(f"{source}: curriculum.stages doit etre un objet.")
    missing = sorted(set(stages) - set(order))
    if missing:
        raise ValueError(
            f"{source}: etape(s) declaree(s) dans 'stages' mais absente(s) de 'order' : {missing}. "
            "L'ordre definit ce qu'est une etape ANTERIEURE ; une etape hors ordre n'a pas de place."
        )
    unknown = sorted(set(order) - set(stages))
    if unknown:
        raise ValueError(
            f"{source}: curriculum.order nomme des etapes absentes de 'stages' : {unknown}"
        )

    opponent = require_key(curriculum, "opponent")
    if not isinstance(opponent, dict):
        raise TypeError(f"{source}: curriculum.opponent doit etre un objet.")
    snapshot_device = str(require_key(opponent, "snapshot_device")).strip().lower()
    if snapshot_device not in {"cpu", "auto"}:
        raise ValueError(
            f"{source}: curriculum.opponent.snapshot_device doit valoir 'cpu' ou 'auto' "
            f"(got {snapshot_device!r})"
        )
    if not isinstance(require_key(opponent, "deterministic"), bool):
        raise TypeError(f"{source}: curriculum.opponent.deterministic doit etre un booleen.")

    gate = require_key(curriculum, "gate")
    if not isinstance(gate, dict):
        raise TypeError(f"{source}: curriculum.gate doit etre un objet.")
    floor = float(require_key(gate, "min_score_vs_champion"))
    target = float(require_key(gate, "target_score_vs_champion"))
    gate_episodes = int(require_key(gate, "eval_episodes"))
    if not (0.0 <= floor <= 1.0):
        raise ValueError(f"{source}: gate.min_score_vs_champion doit etre dans [0,1] (got {floor})")
    if not (floor <= target <= 1.0):
        raise ValueError(
            f"{source}: gate.target_score_vs_champion doit etre dans [min_score_vs_champion,1] "
            f"(got {target} pour un plancher de {floor})"
        )
    if gate_episodes <= 0:
        raise ValueError(f"{source}: gate.eval_episodes doit etre > 0 (got {gate_episodes})")

    if "early_stop" in curriculum:
        _validate_early_stop_block(curriculum["early_stop"], f"{source}: early_stop")

    for position, name in enumerate(order):
        stage = require_stage(curriculum, name)
        earlier = set(order[:position])

        role = str(require_key(stage, "role"))
        if role not in STAGE_ROLES:
            raise ValueError(
                f"{source}: stages[{name}].role doit valoir l'un de {STAGE_ROLES} (got {role!r})"
            )

        source_stage = stage_init_source(stage)
        if source_stage is not None and source_stage not in earlier:
            raise ValueError(
                f"{source}: stages[{name}].init reprend {source_stage!r}, qui n'est pas une etape "
                f"ANTERIEURE. Etapes disponibles a ce point : {sorted(earlier)}"
            )

        ratio_start = float(require_key(stage, "ratio_start"))
        ratio_end = float(require_key(stage, "ratio_end"))
        warmup_episodes = int(require_key(stage, "warmup_episodes"))
        for label, value in (("ratio_start", ratio_start), ("ratio_end", ratio_end)):
            if not (0.0 <= value <= 1.0):
                raise ValueError(
                    f"{source}: stages[{name}].{label} doit etre dans [0,1] (got {value})"
                )
        if ratio_start > ratio_end:
            raise ValueError(
                f"{source}: stages[{name}].ratio_start ({ratio_start}) > ratio_end ({ratio_end}) "
                "— la rampe serait decroissante (pool moins joue vers la fin de l'etape)."
            )
        if warmup_episodes < 0:
            raise ValueError(
                f"{source}: stages[{name}].warmup_episodes doit etre >= 0 (got {warmup_episodes})"
            )
        ramp_end_episodes = stage.get("ramp_end_episodes")
        if ramp_end_episodes is not None:
            ramp_end_episodes = int(ramp_end_episodes)
            if ramp_end_episodes <= warmup_episodes:
                raise ValueError(
                    f"{source}: stages[{name}].ramp_end_episodes ({ramp_end_episodes}) doit "
                    f"etre > warmup_episodes ({warmup_episodes})."
                )
            overrides = get_stage_hp_overrides(stage)
            override_total = overrides.get("total_episodes")
            if override_total is None:
                raise ValueError(
                    f"{source}: stages[{name}].ramp_end_episodes est present sans "
                    "training_config_overrides.total_episodes — impossible de garantir que "
                    "ratio_end sera atteint. Ajouter total_episodes dans "
                    "training_config_overrides de l'etape."
                )
            if ramp_end_episodes > int(override_total):
                raise ValueError(
                    f"{source}: stages[{name}].ramp_end_episodes ({ramp_end_episodes}) depasse "
                    f"training_config_overrides.total_episodes ({override_total}) : "
                    f"ratio_end ne serait jamais atteint en fin de run."
                )

        members = stage_pool_members(stage)

        if role == "exploiter":
            validate_exploiter_protocol(curriculum, stage, name, "")

        for member in members:
            if member["label"] not in earlier:
                raise ValueError(
                    f"{source}: stages[{name}].pool nomme {member['label']!r}, qui n'est pas une "
                    f"etape ANTERIEURE. Un adversaire fige doit exister avant d'etre joue. "
                    f"Etapes disponibles a ce point : {sorted(earlier)}"
                )

        pool_weight = sum(member["weight"] for member in members)
        bots_weight = 1.0 - ratio_end
        total = bots_weight + pool_weight
        if abs(total - 1.0) > RATIO_SUM_TOLERANCE:
            raise ValueError(
                f"{source}: stages[{name}] — la somme des ratios vaut {total!r} au lieu de 1.0 : "
                f"bots {bots_weight!r} + pool {pool_weight!r}. La somme des poids de groupes doit "
                f"valoir ratio_end ({ratio_end!r})."
            )
        if members and not any(m["kind"] == "champion" for m in members):
            raise ValueError(
                f"{source}: stages[{name}] a un pool sans membre 'champion' : le gate de fin "
                "d'etape n'aurait rien a mesurer."
            )
        if not members and ratio_end != 0.0:
            raise ValueError(
                f"{source}: stages[{name}] n'a pas de pool mais un ratio_end de {ratio_end!r} : "
                "la rampe conduirait a des episodes sans adversaire."
            )

        if "early_stop" in stage:
            _validate_early_stop_block(stage["early_stop"], f"{source}: stages[{name}].early_stop")

    # Validation du bloc exploiter_config si present (obligatoire des qu'il existe au moins
    # une etape exploiteur dans le curriculum).
    has_exploiter = any(
        is_exploiter_stage(require_stage(curriculum, name)) for name in order
    )
    if "exploiter_config" in curriculum:
        cfg = curriculum["exploiter_config"]
        if not isinstance(cfg, dict):
            raise TypeError(f"{source}: curriculum.exploiter_config doit etre un objet JSON.")
        for key in _EXPLOITER_CONFIG_REQUIRED_KEYS:
            if key not in cfg:
                raise KeyError(
                    f"{source}: curriculum.exploiter_config manque la cle '{key}'. "
                    f"Cles requises : {_EXPLOITER_CONFIG_REQUIRED_KEYS}"
                )
        probe_every = int(cfg["probe_every_episodes"])
        probe_cheap = int(cfg["probe_cheap_n"])
        probe_confirm = int(cfg["probe_confirm_n"])
        win_rate_target = float(cfg["win_rate_target"])
        if probe_every <= 0:
            raise ValueError(f"{source}: exploiter_config.probe_every_episodes doit etre > 0")
        if probe_cheap <= 0:
            raise ValueError(f"{source}: exploiter_config.probe_cheap_n doit etre > 0")
        if probe_confirm <= probe_cheap:
            raise ValueError(
                f"{source}: exploiter_config.probe_confirm_n ({probe_confirm}) doit etre "
                f"> probe_cheap_n ({probe_cheap})"
            )
        if not (0.0 < win_rate_target <= 1.0):
            raise ValueError(
                f"{source}: exploiter_config.win_rate_target doit etre dans ]0,1] "
                f"(got {win_rate_target})"
            )
    elif has_exploiter:
        raise KeyError(
            f"{source}: le curriculum a des etapes exploiteur mais pas de bloc "
            "'exploiter_config'. Ajouter ce bloc dans curriculum.json."
        )

    for name in order:
        stage = require_stage(curriculum, name)
        if is_exploiter_stage(stage):
            bc = stage.get("budget_cap")
            if bc is None:
                raise KeyError(
                    f"{source}: stages[{name}] est exploiteur mais n'a pas de 'budget_cap'. "
                    "Ajouter 'budget_cap' dans l'etape."
                )
            if int(bc) <= 0:
                raise ValueError(f"{source}: stages[{name}].budget_cap doit etre > 0")
        _validate_stage_hp_overrides(name, stage, source)


_ROBUST_WINDOW_MIN = 3


def _check_eval_coherence(source: str, name: str, total_episodes: int, bot_eval_freq: int) -> None:
    """Leve ValueError si total_episodes ne permet pas robust_window_min evaluations."""
    if total_episodes < bot_eval_freq * _ROBUST_WINDOW_MIN:
        raise ValueError(
            f"{source}: stages[{name}].training_config_overrides — "
            f"total_episodes ({total_episodes}) < bot_eval_freq ({bot_eval_freq}) * "
            f"robust_window_min ({_ROBUST_WINDOW_MIN}) = {bot_eval_freq * _ROBUST_WINDOW_MIN} : "
            "le modele robuste ne serait jamais selectionne (pas assez de points de mesure)."
        )


def _validate_stage_hp_overrides(name: str, stage: Dict[str, Any], source: str) -> None:
    """Valide le bloc `training_config_overrides` d'une etape learner si present.

    Les etapes exploiteur ignorent ce bloc : leur protocole impose une config fixe passee
    via --training-config, et un override la ferait diverger silencieusement.
    """
    overrides = stage.get("training_config_overrides")
    if overrides is None:
        return
    if not isinstance(overrides, dict):
        raise TypeError(
            f"{source}: stages[{name}].training_config_overrides doit etre un objet JSON."
        )
    if is_exploiter_stage(stage):
        raise ValueError(
            f"{source}: stages[{name}].training_config_overrides n'est pas autorise sur une "
            "etape exploiteur : la config est fixee via --training-config a la ligne de commande."
        )
    unknown_top = sorted(set(overrides) - STAGE_HP_OVERRIDES_ALLOWED_TOP_KEYS)
    if unknown_top:
        raise ValueError(
            f"{source}: stages[{name}].training_config_overrides contient des cles non autorisees : "
            f"{unknown_top}. Cles autorisees : {sorted(STAGE_HP_OVERRIDES_ALLOWED_TOP_KEYS)}"
        )
    if "total_episodes" in overrides:
        ep = overrides["total_episodes"]
        if not isinstance(ep, int) or ep <= 0:
            raise ValueError(
                f"{source}: stages[{name}].training_config_overrides.total_episodes doit etre "
                f"un entier > 0 (got {ep!r})"
            )
    if "model_params" in overrides:
        mp = overrides["model_params"]
        if not isinstance(mp, dict):
            raise TypeError(
                f"{source}: stages[{name}].training_config_overrides.model_params doit etre un objet."
            )
        unknown_mp = sorted(set(mp) - STAGE_HP_OVERRIDES_ALLOWED_MODEL_PARAMS)
        if unknown_mp:
            raise ValueError(
                f"{source}: stages[{name}].training_config_overrides.model_params contient des "
                f"cles non autorisees : {unknown_mp}. Cles autorisees : "
                f"{sorted(STAGE_HP_OVERRIDES_ALLOWED_MODEL_PARAMS)}"
            )
        if "n_epochs" in mp:
            n = mp["n_epochs"]
            if not isinstance(n, int) or n <= 0:
                raise ValueError(
                    f"{source}: stages[{name}].training_config_overrides.model_params.n_epochs "
                    f"doit etre un entier > 0 (got {n!r})"
                )
        if "vf_coef" in mp:
            v = mp["vf_coef"]
            if not isinstance(v, (int, float)) or v <= 0:
                raise ValueError(
                    f"{source}: stages[{name}].training_config_overrides.model_params.vf_coef "
                    f"doit etre un nombre > 0 (got {v!r})"
                )
        for _key, _allow_zero in (("learning_rate", False), ("ent_coef", True)):
            if _key in mp:
                v = mp[_key]
                _op = ">= 0" if _allow_zero else "> 0"
                if not (isinstance(v, dict) or (isinstance(v, (int, float)) and (v >= 0 if _allow_zero else v > 0))):
                    raise ValueError(
                        f"{source}: stages[{name}].training_config_overrides.model_params.{_key} "
                        f"doit etre un nombre {_op} ou un objet schedule (got {v!r})"
                    )
    if "callback_params" in overrides:
        cp = overrides["callback_params"]
        if not isinstance(cp, dict):
            raise TypeError(
                f"{source}: stages[{name}].training_config_overrides.callback_params doit etre un objet."
            )
        unknown_cp = sorted(set(cp) - STAGE_HP_OVERRIDES_ALLOWED_CALLBACK_PARAMS)
        if unknown_cp:
            raise ValueError(
                f"{source}: stages[{name}].training_config_overrides.callback_params contient des "
                f"cles non autorisees : {unknown_cp}. Cles autorisees : "
                f"{sorted(STAGE_HP_OVERRIDES_ALLOWED_CALLBACK_PARAMS)}"
            )
        for key in ("bot_eval_freq", "bot_eval_final"):
            if key in cp:
                val = cp[key]
                if not isinstance(val, int) or val <= 0:
                    raise ValueError(
                        f"{source}: stages[{name}].training_config_overrides.callback_params.{key} "
                        f"doit etre un entier > 0 (got {val!r})"
                    )
        # Detection precoce de l'incoherence quand les deux valeurs sont dans les overrides.
        # La verification sur valeurs EFFECTIVES (override partiel possible) est faite dans
        # _apply_stage_hp_overrides apres application, ou total_episodes est toujours connu.
        if "bot_eval_freq" in cp and "total_episodes" in overrides:
            _check_eval_coherence(source, name, overrides["total_episodes"], cp["bot_eval_freq"])


def get_stage_hp_overrides(stage: Dict[str, Any]) -> Dict[str, Any]:
    """Renvoie le bloc `training_config_overrides` de l'etape, ou {} si absent."""
    overrides = stage.get("training_config_overrides")
    return overrides if isinstance(overrides, dict) else {}


# ── RAMPE ──────────────────────────────────────────────────────────────────────────────────

def ramped_ratio(
    episode_index: int,
    warmup_episodes: int,
    total_episodes: int,
    ratio_start: float,
    ratio_end: float,
    ramp_end_episodes: Optional[int] = None,
) -> float:
    """Part du POOL a l'episode `episode_index` : palier a `ratio_start`, puis interpolation.

    SOURCE UNIQUE de la rampe : `BotControlledEnv._compute_pool_ratio_for_episode` l'appelle au
    lieu de la recalculer. Les indices sont LOCAUX a un environnement — l'appelant a deja ramene
    les budgets globaux au budget d'un env (cf. `engine/episode_schedule.py`).

    `ramp_end_episodes` (optionnel, en budget par env) : episode auquel `ratio_end` est atteint.
    Independant de `total_episodes` — permet d'allonger un run sans ralentir la montee en self-play.
    Quand absent, la rampe se termine a `total_episodes` (comportement d'origine).
    """
    if episode_index <= warmup_episodes:
        return ratio_start
    ramp_end = ramp_end_episodes if ramp_end_episodes is not None else total_episodes
    if episode_index >= ramp_end:
        return ratio_end
    effective_index = episode_index - warmup_episodes
    effective_total = ramp_end - warmup_episodes
    progress = float(effective_index) / float(effective_total)
    return ratio_start + ((ratio_end - ratio_start) * progress)


# ── REPARTITION PAR ENVIRONNEMENT ──────────────────────────────────────────────────────────

def assign_pool_members_to_envs(
    members: Sequence[Dict[str, Any]], n_envs: int
) -> List[Dict[str, Any]]:
    """Un membre du pool par environnement, dans l'ordre des rangs, au plus proche des poids.

    Methode du plus fort reste : chaque membre recoit `floor(n_envs * poids / poids_total)`
    environnements, puis les places restantes vont aux plus gros restes. C'est la seule facon
    d'honorer des poids fractionnaires avec un nombre ENTIER de processus.

    Un membre qui repartirait a zero environnement est REFUSE : il serait absent du run sans que
    rien ne le signale, alors que le curriculum l'a explicitement demande.
    """
    if not members:
        raise ValueError("assign_pool_members_to_envs: pool vide, rien a repartir.")
    if not isinstance(n_envs, int) or isinstance(n_envs, bool) or n_envs <= 0:
        raise ValueError(
            f"assign_pool_members_to_envs: n_envs doit etre un entier > 0 (got {n_envs!r})"
        )
    if n_envs < len(members):
        raise ValueError(
            f"assign_pool_members_to_envs: {n_envs} environnement(s) pour {len(members)} membres "
            f"de pool — au moins un membre ne serait jamais joue. Augmenter n_envs, ou reduire le "
            f"pool de l'etape."
        )
    total_weight = sum(float(member["weight"]) for member in members)
    if total_weight <= 0.0:
        raise ValueError(f"assign_pool_members_to_envs: poids total nul (membres={members!r})")

    exact = [n_envs * float(member["weight"]) / total_weight for member in members]
    counts = [int(value) for value in exact]
    leftover = n_envs - sum(counts)
    # Plus gros reste d'abord ; a reste egal, l'index le plus faible passe devant — la
    # repartition ne doit dependre que des poids, jamais d'un ordre d'iteration.
    ranking = sorted(range(len(members)), key=lambda i: (-(exact[i] - counts[i]), i))
    for position in range(leftover):
        counts[ranking[position]] += 1

    starved = [members[i]["label"] for i, count in enumerate(counts) if count == 0]
    if starved:
        raise ValueError(
            f"assign_pool_members_to_envs: membre(s) sans aucun environnement avec "
            f"n_envs={n_envs} : {starved}. Leur poids est trop faible pour ce nombre de processus."
        )

    assignment: List[Dict[str, Any]] = []
    for member, count in zip(members, counts):
        assignment.extend([member] * count)
    if len(assignment) != n_envs:
        raise RuntimeError(
            f"assign_pool_members_to_envs: {len(assignment)} affectations pour {n_envs} "
            "environnements — la repartition du plus fort reste est fausse."
        )
    return assignment


# ── ARTEFACTS D'ETAPE ──────────────────────────────────────────────────────────────────────

def stage_model_path(canonical_model_path: str, stage_name: str) -> str:
    """`model_<agent>_<etape>.zip`, derive du modele CANONIQUE.

    Le contrat de `build_agent_model_path` n'est pas touche : l'etape est un SUFFIXE pose sur le
    chemin qu'il rend, exactement comme les archives horodatees.
    """
    stem, ext = os.path.splitext(canonical_model_path)
    return f"{stem}_{stage_name}{ext}"


def promote_stage_model(canonical_model_path: str, stage_name: str) -> List[str]:
    """COPIE le modele canonique et ses compagnons sous le nom de l'etape. Rend les chemins ecrits.

    Une COPIE, pas un renommage : le modele canonique reste en place, c'est lui que l'etape
    suivante reprend via `--resume-from` quand son `init` le demande. Les compagnons suivent la
    convention d'`ai/model_artifacts` — un zip sans son `_vec_normalize.pkl` est injouable comme
    adversaire fige (V11 §0.35), donc les omettre reviendrait a promouvoir un artefact mort.
    """
    from ai.model_artifacts import model_companion_paths

    if not os.path.exists(canonical_model_path):
        raise FileNotFoundError(
            f"Promotion d'etape impossible : le modele canonique est absent "
            f"({canonical_model_path}). Le run n'a rien ecrit."
        )
    target_model = stage_model_path(canonical_model_path, stage_name)
    pairs: List[Tuple[str, str]] = [(canonical_model_path, target_model)]
    pairs.extend(
        zip(model_companion_paths(canonical_model_path), model_companion_paths(target_model))
    )

    written: List[str] = []
    for origin, target in pairs:
        if not os.path.exists(origin):
            continue
        shutil.copy2(origin, target)
        written.append(target)
    if target_model not in written:
        raise RuntimeError(f"Promotion d'etape : {target_model} n'a pas ete ecrit.")
    return written


def copy_tensorboard_run(run_dir: str, stage_name: str) -> str:
    """Recopie le repertoire TensorBoard du run dans `tensorboard_<etape>`, a cote de lui.

    L'etape suivante reprend la meme experience TensorBoard ; sans cette copie, ses courbes se
    melent a celles de l'etape precedente et ne sont plus attribuables.
    """
    if not os.path.isdir(run_dir):
        raise FileNotFoundError(
            f"Repertoire TensorBoard du run absent : {run_dir}. "
            f"Rien a copier pour l'etape {stage_name}."
        )
    target = os.path.join(
        os.path.dirname(os.path.abspath(run_dir)), f"tensorboard_{stage_name}"
    )
    if os.path.exists(target):
        shutil.rmtree(target)
    shutil.copytree(run_dir, target)
    return target


# ── GATE ET DIAGNOSTIC ─────────────────────────────────────────────────────────────────────

def evaluate_stage_gate(
    stage_name: str,
    champion_label: Optional[str],
    scores_vs_pool: Dict[str, float],
    floor: float,
    target: float,
) -> Tuple[bool, str]:
    """(accepte, motif) — plancher DUR sur le score contre le champion le PLUS RECENT.

    Remplace `benchmark_floor`, aveugle ici : les bots de reference sont satures a 1.00, donc un
    plancher pose dessus est franchi par n'importe quel modele et ne separe rien. Le champion
    precedent, lui, est un adversaire dont la force suit celle de l'agent — c'est le seul etalon
    qui reste discriminant d'une etape a l'autre.

    Une etape sans champion (P0) n'a rien a franchir : elle est acceptee, et le motif le dit.
    """
    if champion_label is None:
        return True, f"{stage_name} : pas de champion a battre (premiere etape), gate sans objet."
    if champion_label not in scores_vs_pool:
        raise KeyError(
            f"Gate de {stage_name} : aucun score mesure contre le champion {champion_label!r}. "
            f"Scores disponibles : {sorted(scores_vs_pool)}"
        )
    score = float(scores_vs_pool[champion_label])
    if score < floor:
        return False, (
            f"{stage_name} : score {score:.3f} contre le champion {champion_label} — SOUS le "
            f"plancher dur de {floor:.2f} (cible {target:.2f}). Etape REFUSEE, aucune promotion."
        )
    verdict = "au-dessus de la cible" if score >= target else "au-dessus du plancher, sous la cible"
    return True, (
        f"{stage_name} : score {score:.3f} contre le champion {champion_label} — {verdict} "
        f"(plancher {floor:.2f}, cible {target:.2f})."
    )


def pool_monotonicity_diagnostic(
    scores_vs_pool: Dict[str, float], pool_order: Sequence[str]
) -> List[str]:
    """Lignes de DIAGNOSTIC sur la monotonie du pool. Jamais un gate.

    Attendu intuitif : plus un adversaire du pool est ancien, plus le score contre lui est eleve.
    Ce n'est PAS une propriete garantie ici — les learners demarrent `--new`, donc deux etapes
    voisines sont des runs INDEPENDANTS et peuvent se departager dans le desordre sans qu'aucune
    anomalie ne se soit produite. En faire un gate refuserait des etapes saines ; on le
    journalise pour le lire, pas pour trancher.
    """
    ordered = [label for label in pool_order if label in scores_vs_pool]
    lines = [
        "MONOTONIE (diagnostic, hors gate) — score attendu decroissant du plus ancien au plus "
        "recent :"
    ]
    if len(ordered) < 2:
        lines.append("  pool de moins de deux membres : rien a comparer.")
        return lines
    inversions: List[str] = []
    for older, newer in zip(ordered, ordered[1:]):
        older_score = float(scores_vs_pool[older])
        newer_score = float(scores_vs_pool[newer])
        if newer_score > older_score:
            inversions.append(f"{older}={older_score:.3f} < {newer}={newer_score:.3f}")
    lines.append("  " + " · ".join(f"{label}={scores_vs_pool[label]:.3f}" for label in ordered))
    if inversions:
        lines.append(f"  {len(inversions)} inversion(s) : " + " ; ".join(inversions))
    else:
        lines.append("  aucune inversion.")
    return lines


# ── JOURNAL ────────────────────────────────────────────────────────────────────────────────

def curriculum_log_path() -> str:
    """`curriculum.log`, a la racine du projet. Jumeau de `step.log`."""
    return os.path.join(_project_root(), CURRICULUM_LOG_FILENAME)


#: Cle estampillee par `append_curriculum_log`, jamais fournie par l'appelant (cf. sa docstring).
WRITTEN_BY_KEY = "written_by"


def append_curriculum_log(entry: Dict[str, Any], log_path: Optional[str] = None) -> str:
    """Ajoute UNE entree d'etape au journal, en APPEND. Rend le chemin ecrit.

    APPEND et pas reecriture : le journal est la trace de la progression du curriculum sur
    quatorze runs etales sur des jours. Un mode 'w' perdrait tout l'historique au premier
    relancement d'une etape.

    ESTAMPILLE ``written_by`` — QUEL PROGRAMME a ecrit la ligne, depuis ``sys.argv[0]``.

    POURQUOI. Ce journal est en append public : n'importe quel script qui importe cette fonction
    peut y ajouter une entree, et rien ne distinguait ensuite la mesure du pipeline de celle d'un
    script jetable. Ce n'est pas theorique, c'est arrive : le 2026-08-26, `scripts/replay_p1_cloture.py`
    (script one-shot, jamais commite) a journalise un refus de l'etape P1 mesure sur 30 episodes
    au lieu des 300 de `curriculum.json`, en ecrivant lui-meme `gate_eval_episodes: 30`. A
    30 episodes l'erreur-type d'un taux proche de 0,5 vaut ~9 points : le verdict n'etait pas
    distinguable du bruit, mais rien dans la ligne ne permettait de le savoir en la relisant.

    DERIVE, PAS DECLARE. La valeur vient de ``sys.argv[0]``, pas d'un argument : un appelant ne
    peut ni l'oublier ni la falsifier en la laissant vide. C'est aussi la bonne semantique — la
    question est « quel programme a produit cette mesure », et le point d'entree y repond
    exactement (`ai/train.py` pour le pipeline, `scripts/<nom>.py` pour un script).

    Fournir la cle soi-meme LEVE plutot que d'etre ecrase en silence : une entree qui se declare
    ecrite par un autre programme que celui qui tourne est precisement ce que ce champ existe
    pour rendre impossible.
    """
    if WRITTEN_BY_KEY in entry:
        raise ValueError(
            f"append_curriculum_log: {WRITTEN_BY_KEY!r} est estampille par le journal, pas fourni "
            f"par l'appelant (recu {entry[WRITTEN_BY_KEY]!r}). Retirer la cle de l'entree."
        )
    stamped = {**entry, WRITTEN_BY_KEY: _writer_identity()}
    path = log_path if log_path is not None else curriculum_log_path()
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(stamped, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def _writer_identity() -> str:
    """Point d'entree du processus, relatif a la racine du projet quand il y est contenu.

    Relatif plutot qu'absolu : `ai/train.py` se relit d'un coup d'oeil la ou
    `/home/<user>/40k/ai/train.py` noie l'information dans un chemin machine. Un point d'entree
    hors du depot (interpreteur interactif, `pytest` installe dans le venv) reste absolu — il n'y
    a rien a raccourcir, et c'est justement le cas ou l'on veut voir d'ou ca vient.
    """
    entry_point = sys.argv[0] if sys.argv else ""
    if not entry_point:
        return "<inconnu>"  # `python -c`, embarque : argv[0] vide. Pas un repli, une valeur juste.
    resolved = os.path.abspath(entry_point)
    root = _project_root()
    return os.path.relpath(resolved, root) if resolved.startswith(root + os.sep) else resolved
