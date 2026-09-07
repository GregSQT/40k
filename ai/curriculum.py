"""Curriculum d'entrainement par ETAPES : learners `P0..P10`, exploiteurs `E1..E3`.

Une ETAPE est un run complet d'`ai/train.py`. Elle declare comment le modele DEMARRE (`init`),
contre QUI il joue (`ratio_start`/`ratio_end`/`warmup_episodes` + `pool`) et combien de temps
(`total_episodes`). Elle ne declare PLUS ses hyperparametres depuis le 2026-09-07 : le bloc
`lineage_regime` du curriculum les porte pour toute la lignee des qu'une etape reprend des poids
(`init: from:`), et `--training-config` ne vaut plus que pour le seul depart a froid. La raison
mesuree vit dans le `_doc` de ce bloc — une rampe s'exprime en fraction de la duree du RUN, donc
chaque etape reprise reparcourait la sienne et rendait a un modele converge le regime
d'exploration d'un demarrage.

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
import tempfile
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from ai.run_state import load_run_state
from shared.data_validation import (
    ConfigurationError,
    require_key,
    require_non_negative_int,
    require_positive_int,
)

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

#: Cles obligatoires du bloc `early_stop` (racine et surcharge par etape). Toutes les decisions
#: se prennent sur la MOYENNE GLISSANTE des `probe_window` dernieres sondes, jamais sur une sonde
#: brute : deux sondes d'un meme modele rendent le meme score (graines figees jusqu'au 2026-09-07),
#: donc les sauts de ±5 points entre sondes voisines ne sont pas du bruit d'echantillonnage mais
#: des bascules de blocs de parties correlees — decider dessus, c'est decider sur leur amplitude.
_EARLY_STOP_REQUIRED_KEYS = (
    "probe_window",
    "promote_score_vs_champion",
    "promote_score_vs_others",
    "promote_min_episodes",
    "destroy_score_vs_champion",
    "destroy_min_episodes",
    "full_pool_probe_every",
)

#: Cles obligatoires du bloc `gate`.
_GATE_REQUIRED_KEYS = (
    "min_score_vs_champion", "min_score_vs_others", "eval_episodes", "eval_repeats",
)

#: Cles obligatoires du bloc `parity_check`.
_PARITY_CHECK_REQUIRED_KEYS = ("min_score", "max_score")

#: Cle du bloc de regime de lignee, applique a TOUTE etape reprise a chaud (`init: from:`).
LINEAGE_REGIME_KEY = "lineage_regime"

#: Cles autorisees au niveau racine de `training_config_overrides` d'une etape learner.
#: Toute cle absente de cette liste est refusee a la validation du curriculum.
#: Les cles structurelles (deployment_mode_schedule, obs_size, vec_normalize, n_envs, seed)
#: ne sont PAS autorisees : elles doivent rester identiques entre toutes les etapes pour
#: que les modeles soient comparables et que les tests de profil ne divergent pas.
#: `deployment_mode_schedule` reste donc hors de cette liste, MAIS sa rampe est figee a sa
#: valeur terminale pour toute etape reprise a chaud — c'est un comportement porte par
#: `ai/train.py::_pin_deployment_ramp_for_warm_start`, pas une cle declarable. Le faire en code
#: et non en JSON est ce qui couvre aussi les etapes exploiteur, auxquelles
#: `_validate_stage_hp_overrides` interdit tout `training_config_overrides`.
#: `agent_seat_p2_ratio` EST autorise, et c'est la seule cle non structurelle de la liste : il
#: ne decrit pas le modele mais l'EXPOSITION — quelle part des episodes l'agent joue en second,
#: le siege ou il est le plus faible. Il varie donc legitimement d'une etape a l'autre, comme le
#: pool et la rampe, et pour la meme raison : c'est de l'adversite. Il ne compromet pas la
#: comparabilite que cette liste protege, parce que `ai/bot_evaluation.py` ne le lit JAMAIS —
#: l'evaluation construit ses environnements sans le passer et garde un tirage equitable
#: (cf. `ai/env_wrappers.py::_resolve_seat_p2_ratio`), donc les scores publies restent mesures
#: dans les memes conditions quelle que soit l'etape.
STAGE_HP_OVERRIDES_ALLOWED_TOP_KEYS: frozenset = frozenset({
    "total_episodes", "model_params", "callback_params", "agent_seat_p2_ratio",
})


class _ModelParamSpec(NamedTuple):
    """Contrainte d'une sous-cle de `model_params` surchargeable par une etape."""

    integer: bool  # entier strict : `5.0` est refuse
    allow_zero: bool  # borne basse inclusive plutot que stricte
    allow_schedule: bool  # un objet schedule est accepte a la place du scalaire


#: Sous-cles de `model_params` autorisees dans un override d'etape, et contrainte de chacune.
#: Toutes decrivent l'OPTIMISATION, jamais le modele ni le retour : elles changent la facon dont
#: le gradient est calcule et applique, pas ce que le reseau voit ni ce qu'il apprend a predire.
#: C'est ce qui les distingue des cles refusees ici — `policy_kwargs`/`net_arch` (architecture),
#: `n_steps`/`batch_size` (taille du rollout), `gamma`/`gae_lambda` (definition du retour) —, dont
#: la variation d'une etape a l'autre rendrait les modeles de la lignee chainee incomparables.
#: `max_grad_norm` ajoute le 2026-09-06 a ce titre, meme famille que `vf_coef` : il borne la norme
#: du gradient avant l'application. La MESURE qui a motive sa valeur vit au `_doc` de P2.
#:
#: La contrainte est portee ICI et non par une branche du validateur, pour qu'ouvrir une cle et
#: dire ce qu'elle accepte soient le MEME geste : les branches separees avaient laisse quatre
#: orthographes du meme predicat, dont trois sans rejet des booleens (`vf_coef: true` etait
#: accepte et arrivait au modele en 1.0).
STAGE_HP_OVERRIDES_MODEL_PARAM_SPECS: Dict[str, _ModelParamSpec] = {
    "learning_rate": _ModelParamSpec(integer=False, allow_zero=False, allow_schedule=True),
    "ent_coef": _ModelParamSpec(integer=False, allow_zero=True, allow_schedule=True),
    "n_epochs": _ModelParamSpec(integer=True, allow_zero=False, allow_schedule=False),
    "vf_coef": _ModelParamSpec(integer=False, allow_zero=False, allow_schedule=False),
    "max_grad_norm": _ModelParamSpec(integer=False, allow_zero=False, allow_schedule=False),
}

STAGE_HP_OVERRIDES_ALLOWED_MODEL_PARAMS: frozenset = frozenset(
    STAGE_HP_OVERRIDES_MODEL_PARAM_SPECS
)

#: `model_params` que le bloc `lineage_regime` impose a toute etape reprise a chaud, et la
#: contrainte de chacun. La liste est CLOSE : une cle de plus doit etre declaree ici avant de
#: pouvoir etre ecrite dans le JSON, sans quoi un hyperparametre voyagerait jusqu'au modele sans
#: qu'aucun controle ne l'ait lu.
#:
#: `allow_schedule=False` PARTOUT, et c'est le fond de la decision du 2026-09-07 : une rampe est
#: exprimee en fraction de la duree du RUN, donc chaque etape reprise reparcourait la sienne
#: depuis le debut et rendrait a un modele converge le regime d'exploration d'un demarrage. Le
#: bloc de lignee n'accepte donc que des scalaires. La justification mesuree vit dans son `_doc`.
LINEAGE_REGIME_MODEL_PARAM_SPECS: Dict[str, _ModelParamSpec] = {
    "learning_rate": _ModelParamSpec(integer=False, allow_zero=False, allow_schedule=False),
    "ent_coef": _ModelParamSpec(integer=False, allow_zero=True, allow_schedule=False),
    "n_steps": _ModelParamSpec(integer=True, allow_zero=False, allow_schedule=False),
    "batch_size": _ModelParamSpec(integer=True, allow_zero=False, allow_schedule=False),
    "vf_coef": _ModelParamSpec(integer=False, allow_zero=False, allow_schedule=False),
    "max_grad_norm": _ModelParamSpec(integer=False, allow_zero=False, allow_schedule=False),
}

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


def validate_early_stop_block(block: Any, context: str) -> None:
    """Valide un bloc `early_stop` (racine ou par etape). Leve si une cle est absente ou invalide.

    Les cles de SEUIL decrivent DEUX decisions opposees, toutes deux prises sur la moyenne
    glissante des `probe_window` dernieres sondes : la PROMOTION (l'etape a fini son travail, le
    budget restant serait paye pour rien) et la DESTRUCTION (l'etape a defait la politique qu'elle
    avait recue). Le seuil de destruction doit rester SOUS celui de promotion, sinon les deux
    branches peuvent etre vraies au meme instant et le verdict dependrait de l'ordre des tests.

    `full_pool_probe_every` est une cle de COUT et non de seuil : elle dit tous les combien de
    sondes le pool ENTIER est mesure, le champion l'etant a chaque fois. 1 = tout le pool a chaque
    sonde. Elle existe parce que le cout d'une sonde suit la taille du pool, qui croit d'une etape
    a l'autre — cf. `PoolEarlyStoppingCallback`, ou le chiffre est justifie.
    """
    if not isinstance(block, dict):
        raise TypeError(f"{context} doit etre un objet JSON.")
    for key in _EARLY_STOP_REQUIRED_KEYS:
        if key not in block:
            raise ConfigurationError(
                f"{context} manque la cle '{key}'. Cles requises : {_EARLY_STOP_REQUIRED_KEYS}"
            )
    window = require_positive_int(require_key(block, "probe_window"), f"{context}.probe_window")
    if window < 2:
        raise ValueError(
            f"{context}.probe_window doit valoir au moins 2 (got {window}) : une fenetre d'un "
            "seul point n'est pas une moyenne, c'est la sonde brute — precisement ce que ces "
            "decisions ne veulent plus lire."
        )
    require_non_negative_int(
        require_key(block, "promote_min_episodes"), f"{context}.promote_min_episodes"
    )
    require_non_negative_int(
        require_key(block, "destroy_min_episodes"), f"{context}.destroy_min_episodes"
    )
    require_positive_int(
        require_key(block, "full_pool_probe_every"), f"{context}.full_pool_probe_every"
    )
    scores = {}
    for key in (
        "promote_score_vs_champion", "promote_score_vs_others", "destroy_score_vs_champion",
    ):
        value = float(require_key(block, key))
        if not (0.0 < value <= 1.0):
            raise ValueError(f"{context}.{key} doit etre dans ]0,1] (got {value})")
        scores[key] = value
    if scores["destroy_score_vs_champion"] >= scores["promote_score_vs_champion"]:
        raise ValueError(
            f"{context}: destroy_score_vs_champion ({scores['destroy_score_vs_champion']}) doit "
            f"etre STRICTEMENT sous promote_score_vs_champion "
            f"({scores['promote_score_vs_champion']}) — sinon une meme moyenne declencherait a la "
            "fois la promotion et l'arret pour destruction."
        )


def _validate_early_stop_against_gate(early_stop: Any, gate: Any, context: str) -> None:
    """Interdit un seuil de PROMOTION sous le plancher du GATE qui jugera la meme etape.

    `_pool_score_shortfalls` est deja la source unique du CALCUL des deux decisions, mais rien ne
    croisait leurs SEUILS : chaque bloc etait valide seul, et deux nombres coherents pris
    separement pouvaient se contredire. Un `promote_score_vs_champion` de 0.50 sous un
    `gate.min_score_vs_champion` de 0.55 laisse `evaluate_pool_decision` arreter le run a 0.51 en
    annoncant que « le budget restant serait paye pour rien », puis `evaluate_stage_gate` refuser
    l'etape a 0.55 et jeter le budget non depense avec elle — exactement ce que la docstring de
    `_pool_score_shortfalls` affirme impossible.

    L'egalite est TOLEREE : les deux decisions comparent avec `>=`, donc une moyenne qui promeut
    atteint le plancher. Elle ne le franchit pas avec MARGE, et les deux mesures sont des
    echantillons distincts (graines tirees) — le gate peut donc encore refuser par variance. Poser
    une marge minimale au-dessus de l'erreur-type serait une decision de conception a prendre, pas
    un invariant a supposer ici.
    """
    pairs = (
        ("promote_score_vs_champion", "min_score_vs_champion"),
        ("promote_score_vs_others", "min_score_vs_others"),
    )
    for promote_key, gate_key in pairs:
        promote_value = float(require_key(early_stop, promote_key))
        gate_value = float(require_key(gate, gate_key))
        if promote_value < gate_value:
            raise ValueError(
                f"{context}.{promote_key} ({promote_value}) est SOUS gate.{gate_key} "
                f"({gate_value}) : le run s'arreterait en se declarant promu sur un score que le "
                "gate de fin d'etape refusera, et le budget non depense serait perdu avec "
                "l'etape. Le seuil d'arret anticipe doit valoir au moins le plancher qui juge."
            )


def _validate_gate_block(block: Any, context: str) -> None:
    """Valide le bloc `gate`. Deux planchers, un nombre d'episodes, un nombre de blocs moyennes."""
    if not isinstance(block, dict):
        raise TypeError(f"{context} doit etre un objet.")
    for key in _GATE_REQUIRED_KEYS:
        if key not in block:
            raise ConfigurationError(
                f"{context} manque la cle '{key}'. Cles requises : {_GATE_REQUIRED_KEYS}"
            )
    for key in ("min_score_vs_champion", "min_score_vs_others"):
        value = float(require_key(block, key))
        if not (0.0 <= value <= 1.0):
            raise ValueError(f"{context}.{key} doit etre dans [0,1] (got {value})")
    require_positive_int(require_key(block, "eval_episodes"), f"{context}.eval_episodes")
    repeats = require_positive_int(require_key(block, "eval_repeats"), f"{context}.eval_repeats")
    if repeats < 2:
        raise ValueError(
            f"{context}.eval_repeats doit valoir au moins 2 (got {repeats}) : le gate decide sur "
            "une MOYENNE de blocs a graines tirees, un bloc unique n'en est pas une."
        )


def _validate_parity_check_block(block: Any, context: str) -> None:
    """Valide le bloc `parity_check` : la fenetre ou doit tomber la baseline d'ouverture."""
    if not isinstance(block, dict):
        raise TypeError(f"{context} doit etre un objet.")
    for key in _PARITY_CHECK_REQUIRED_KEYS:
        if key not in block:
            raise ConfigurationError(
                f"{context} manque la cle '{key}'. Cles requises : {_PARITY_CHECK_REQUIRED_KEYS}"
            )
    low = float(require_key(block, "min_score"))
    high = float(require_key(block, "max_score"))
    for key, value in (("min_score", low), ("max_score", high)):
        if not (0.0 <= value <= 1.0):
            raise ValueError(f"{context}.{key} doit etre dans [0,1] (got {value})")
    if not low < 0.5 < high:
        raise ValueError(
            f"{context}: la fenetre [{low}, {high}] doit ENCADRER la parite 0.5. Une etape reprise "
            "a chaud part des poids d'un membre de son pool : son score contre lui vaut 0.5 par "
            "identite, pas par esperance. Une fenetre qui ne la contient pas refuserait tout run."
        )


def _validate_lineage_regime(curriculum: Dict[str, Any], source: str) -> None:
    """Valide le bloc `lineage_regime`, obligatoire des qu'une etape reprend des poids.

    Il vaut pour TOUTE etape `init: from:` — learners comme exploiteurs —, donc son absence ne
    peut pas etre traitee comme « pas de regime » : ce serait rendre a chaque etape reprise les
    rampes du profil, c'est-a-dire exactement le defaut mesure le 2026-09-04 (entropie multipliee
    par cinq a la reprise, politique promue detruite en 10 000 episodes).
    """
    order = stage_order(curriculum)
    resumed = [
        name for name in order
        if stage_init_source(require_stage(curriculum, name)) is not None
    ]
    if LINEAGE_REGIME_KEY not in curriculum:
        if not resumed:
            return
        raise ConfigurationError(
            f"{source}: bloc '{LINEAGE_REGIME_KEY}' absent alors que {resumed} reprennent des "
            "poids. Sans lui, chaque etape reprise reparcourrait les rampes du profil depuis leur "
            "depart et rendrait a un modele converge le regime d'exploration d'un demarrage."
        )
    block = curriculum[LINEAGE_REGIME_KEY]
    if not isinstance(block, dict):
        raise TypeError(f"{source}: curriculum.{LINEAGE_REGIME_KEY} doit etre un objet JSON.")

    model_params = require_key(block, "model_params")
    if not isinstance(model_params, dict):
        raise TypeError(f"{source}: {LINEAGE_REGIME_KEY}.model_params doit etre un objet.")
    unknown = sorted(set(model_params) - set(LINEAGE_REGIME_MODEL_PARAM_SPECS))
    if unknown:
        raise ValueError(
            f"{source}: {LINEAGE_REGIME_KEY}.model_params contient des cles non autorisees : "
            f"{unknown}. Cles autorisees : {sorted(LINEAGE_REGIME_MODEL_PARAM_SPECS)}"
        )
    missing = sorted(set(LINEAGE_REGIME_MODEL_PARAM_SPECS) - set(model_params))
    if missing:
        raise ConfigurationError(
            f"{source}: {LINEAGE_REGIME_KEY}.model_params manque {missing}. Le bloc est COMPLET "
            "ou il n'est pas un regime : une cle omise laisserait la valeur du profil s'appliquer "
            "aux etapes reprises sans que rien ne le dise."
        )
    for key, spec in LINEAGE_REGIME_MODEL_PARAM_SPECS.items():
        _check_model_param(
            model_params[key], spec, f"{source}: {LINEAGE_REGIME_KEY}.model_params.{key}"
        )
    # PAS de controle `n_steps % batch_size` ici : il serait faux DANS LES DEUX SENS. `n_steps`
    # est un TOTAL par update, qu'`apply_rollout_n_steps` divise par `n_envs` avec troncature —
    # le rollout que SB3 decoupe vaut `(n_steps // n_envs) * n_envs`, pas `n_steps`. A n_envs=7,
    # 32640/4080 passait ce controle alors que le vrai rollout (32634) laisse un mini-lot tronque
    # de 3114 ; a l'inverse 100/33 sur 3 envs l'aurait refuse alors que le rollout reel (99) est
    # bien divisible. `n_envs` vient du profil d'entrainement (`--training-config`), que le
    # curriculum ne connait pas : le controle vit donc la ou les deux grandeurs se rencontrent,
    # dans `apply_rollout_n_steps` (ai/train.py).

    ratio = require_key(block, "agent_seat_p2_ratio")
    if not isinstance(ratio, (int, float)) or isinstance(ratio, bool):
        raise TypeError(
            f"{source}: {LINEAGE_REGIME_KEY}.agent_seat_p2_ratio doit etre un nombre (got {ratio!r})"
        )
    if not 0.0 <= float(ratio) <= 1.0:
        raise ValueError(
            f"{source}: {LINEAGE_REGIME_KEY}.agent_seat_p2_ratio doit etre dans [0.0, 1.0] "
            f"(got {ratio!r}) : c'est une PART des episodes."
        )


def load_lineage_regime(curriculum: Dict[str, Any]) -> Dict[str, Any]:
    """Le bloc `lineage_regime` du curriculum. Absent = erreur explicite, jamais un dict vide."""
    block = require_key(curriculum, LINEAGE_REGIME_KEY)
    if not isinstance(block, dict):
        raise TypeError(f"curriculum.{LINEAGE_REGIME_KEY} doit etre un objet JSON.")
    return block


def load_parity_check(curriculum: Dict[str, Any]) -> Tuple[float, float]:
    """(min_score, max_score) du verrou de parite d'ouverture. Absent = erreur explicite."""
    block = require_key(curriculum, "parity_check")
    if not isinstance(block, dict):
        raise TypeError("curriculum.parity_check doit etre un objet JSON.")
    return float(require_key(block, "min_score")), float(require_key(block, "max_score"))


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

    _validate_gate_block(require_key(curriculum, "gate"), f"{source}: gate")
    _validate_parity_check_block(
        require_key(curriculum, "parity_check"), f"{source}: parity_check"
    )

    if "early_stop" in curriculum:
        validate_early_stop_block(curriculum["early_stop"], f"{source}: early_stop")
        _validate_early_stop_against_gate(
            curriculum["early_stop"], require_key(curriculum, "gate"), f"{source}: early_stop"
        )

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
            validate_early_stop_block(stage["early_stop"], f"{source}: stages[{name}].early_stop")
            # Le gate est UNIQUE (racine) : un `early_stop` par etape le rencontrera lui aussi.
            _validate_early_stop_against_gate(
                stage["early_stop"],
                require_key(curriculum, "gate"),
                f"{source}: stages[{name}].early_stop",
            )

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

    # EN DERNIER : le regime de lignee lit les `init` de toutes les etapes, donc il suppose que
    # « init nomme une etape ANTERIEURE » a deja ete tranche par la boucle ci-dessus. Le valider
    # avant ferait tomber un refus de regime la ou le defaut reel est un ordre d'etapes casse.
    _validate_lineage_regime(curriculum, source)


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


def _check_model_param(value: Any, spec: _ModelParamSpec, context: str) -> None:
    """Applique la contrainte d'un `_ModelParamSpec` a une valeur. Leve si elle n'est pas tenue.

    UN SEUL point d'application, partage par `training_config_overrides.model_params` (etape) et
    par `lineage_regime.model_params` (lignee). Ecrire le predicat a deux endroits est exactement
    ce qui avait laisse quatre orthographes du meme controle, dont trois sans rejet des booleens.
    """
    if spec.allow_schedule and isinstance(value, dict):
        return
    # `isinstance(True, int)` vaut vrai : sans ce rejet, `true` passerait pour 1 et s'appliquerait
    # au modele comme un reglage silencieux.
    numeric = not isinstance(value, bool) and isinstance(
        value, int if spec.integer else (int, float)
    )
    if numeric and (value >= 0 if spec.allow_zero else value > 0):
        return
    kind = "un entier" if spec.integer else "un nombre"
    operator = ">= 0" if spec.allow_zero else "> 0"
    schedule = " ou un objet schedule" if spec.allow_schedule else ""
    raise ValueError(f"{context} doit etre {kind} {operator}{schedule} (got {value!r})")


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
    if stage_init_source(stage) is not None:
        # REGIME DE LIGNEE (2026-09-07) : une etape reprise a chaud ne decide plus de ses
        # hyperparametres, `lineage_regime` les porte pour toute la lignee. Les laisser
        # declarables ferait coexister deux sources pour la meme valeur, et c'est la source
        # perdante — les overrides d'etape sont appliques AVANT le regime — qui aurait l'air
        # d'etre celle qui decide en relisant le JSON.
        governed = sorted(set(overrides) & {"model_params", "agent_seat_p2_ratio"})
        if governed:
            raise ValueError(
                f"{source}: stages[{name}] reprend des poids (init={stage['init']!r}) et declare "
                f"{governed} dans training_config_overrides. Ces cles appartiennent au bloc "
                f"'{LINEAGE_REGIME_KEY}' du curriculum, qui vaut pour TOUTES les etapes reprises "
                "a chaud. Une etape reprise ne declare que sa duree et son adversite."
            )
    unknown_top = sorted(set(overrides) - STAGE_HP_OVERRIDES_ALLOWED_TOP_KEYS)
    if unknown_top:
        raise ValueError(
            f"{source}: stages[{name}].training_config_overrides contient des cles non autorisees : "
            f"{unknown_top}. Cles autorisees : {sorted(STAGE_HP_OVERRIDES_ALLOWED_TOP_KEYS)}"
        )
    if "total_episodes" in overrides:
        ep = overrides["total_episodes"]
        if isinstance(ep, bool) or not isinstance(ep, int) or ep <= 0:
            raise ValueError(
                f"{source}: stages[{name}].training_config_overrides.total_episodes doit etre "
                f"un entier > 0 (got {ep!r})"
            )
    if "agent_seat_p2_ratio" in overrides:
        ratio = overrides["agent_seat_p2_ratio"]
        # Meme controle que `ai/train.py::build_training_opponents` sur la valeur du profil, pose
        # ici pour qu'une etape fautive soit refusee au chargement du curriculum et non au montage
        # des environnements, plusieurs minutes plus tard.
        if not isinstance(ratio, (int, float)) or isinstance(ratio, bool):
            raise TypeError(
                f"{source}: stages[{name}].training_config_overrides.agent_seat_p2_ratio doit "
                f"etre un nombre (got {ratio!r})"
            )
        if not 0.0 <= float(ratio) <= 1.0:
            raise ValueError(
                f"{source}: stages[{name}].training_config_overrides.agent_seat_p2_ratio doit "
                f"etre dans [0.0, 1.0] (got {ratio!r}) : c'est une PART des episodes."
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
        for _key, _spec in STAGE_HP_OVERRIDES_MODEL_PARAM_SPECS.items():
            if _key in mp:
                _check_model_param(
                    mp[_key], _spec,
                    f"{source}: stages[{name}].training_config_overrides.model_params.{_key}",
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
                if isinstance(val, bool) or not isinstance(val, int) or val <= 0:
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


def stage_source_model(canonical_model_path: str, stage: Dict[str, Any]) -> Optional[str]:
    """Chemin de l'archive que l'etape reprend (`init: from:<etape>`), None pour 'new'. LEVE si absente.

    Point unique pour tout ce qui se compte DEPUIS L'ETAPE : `stage_origin` (sondes du run) et
    `episodes_trained` de la cloture (`--close-stage`, ai/train.py). Deux lectures separees de
    la meme archive avaient deja diverge une fois (origine des sondes ancree sur le modele
    repris, cf. tests/unit/ai/test_probe_resume_offset.py).
    """
    source_stage = stage_init_source(stage)
    if source_stage is None:
        return None
    source_model = stage_model_path(canonical_model_path, source_stage)
    if not os.path.exists(source_model):
        raise FileNotFoundError(
            f"L'etape reprend 'from:{source_stage}', dont le modele est absent ({source_model}). "
            "Son etat est l'origine de cette etape ; sans lui, budgets, cadences et nombre "
            "d'episodes journalise seraient ceux de la vie entiere du modele."
        )
    return source_model


def stage_origin(canonical_model_path: str, stage: Dict[str, Any]) -> int:
    """Origine d'une etape = les episodes deja joues par l'archive qu'elle reprend ; 0 si 'new'.

    C'est l'origine des grandeurs D'ETAPE : cadence des sondes, `promote_min_episodes` et
    `destroy_min_episodes` de l'early-stop, `budget_cap` et budget journalise de l'exploiteur,
    `episodes_trained` de curriculum.log.
    Elle se lit sur l'ARCHIVE SOURCE et non sur le modele repris : apres un crash,
    `--resume-from <checkpoint>` reprend au milieu de l'etape, et un compteur ancre sur ce
    checkpoint remettrait budget et cadence a zero — le budget d'un exploiteur s'allongerait en
    silence du nombre d'episodes deja joues.

    Le compte vient de l'etat de run compagnon (`ai/run_state.py`), le zip SB3 ne persistant que
    les pas. Cette fonction rendait AUSSI le `num_timesteps` de l'archive, et ouvrait le zip pour
    lui seul : plus aucune decision ne se prend en pas depuis la suppression du garde `min_steps`
    le 2026-09-07.
    """
    source_model = stage_source_model(canonical_model_path, stage)
    if source_model is None:
        return 0
    return load_run_state(source_model)


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
    parent = os.path.dirname(target)
    target_tmp = tempfile.mkdtemp(dir=parent)
    try:
        shutil.copytree(run_dir, target_tmp, dirs_exist_ok=True)
        shutil.rmtree(target, ignore_errors=True)
        os.rename(target_tmp, target)
    except Exception:
        shutil.rmtree(target_tmp, ignore_errors=True)
        raise
    return target


# ── GATE ET DIAGNOSTIC ─────────────────────────────────────────────────────────────────────

#: Verdicts que rend `evaluate_pool_decision`. `continue` = rien a decider pour l'instant.
POOL_VERDICT_CONTINUE = "continue"
POOL_VERDICT_PROMOTE = "promote"
POOL_VERDICT_DESTROY = "destroy"


class PoolDecision(NamedTuple):
    """Verdict d'une lecture des moyennes de sondes, et la phrase qui l'explique au journal."""

    verdict: str
    reason: str


def _pool_score_shortfalls(
    champion_label: str,
    scores_vs_pool: Dict[str, float],
    floor_champion: float,
    floor_others: float,
) -> List[str]:
    """Membres du pool sous leur plancher, formates. Liste vide = tous les planchers sont tenus.

    Source UNIQUE des deux decisions qui lisent les memes chiffres : la promotion en cours de run
    (`evaluate_pool_decision`) et le gate de fin d'etape (`evaluate_stage_gate`). Les ecrire deux
    fois laisserait une etape s'arreter sur un critere plus faible que celui qui la jugera.

    LEVE quand le champion n'a pas ete mesure : un champion absent des scores ne peut pas etre
    « accepte par defaut », c'est le seul etalon du gate.
    """
    if champion_label not in scores_vs_pool:
        raise KeyError(
            f"Aucun score mesure contre le champion {champion_label!r}. "
            f"Scores disponibles : {sorted(scores_vs_pool)}"
        )
    shortfalls: List[str] = []
    champion_score = float(scores_vs_pool[champion_label])
    if champion_score < floor_champion:
        shortfalls.append(
            f"champion {champion_label}={champion_score:.3f} < {floor_champion:.2f}"
        )
    for label in sorted(scores_vs_pool):
        if label == champion_label:
            continue
        score = float(scores_vs_pool[label])
        if score < floor_others:
            shortfalls.append(f"{label}={score:.3f} < {floor_others:.2f}")
    return shortfalls


def evaluate_pool_decision(
    stage_name: str,
    champion_label: Optional[str],
    mean_scores_vs_pool: Dict[str, float],
    stage_episodes: int,
    early_stop_cfg: Dict[str, Any],
) -> PoolDecision:
    """Verdict d'arret pendant le run, lu sur les MOYENNES glissantes des sondes.

    Deux branches opposees, et la DESTRUCTION est testee la premiere : elle ouvre plus tot
    (`destroy_min_episodes` < `promote_min_episodes`) et son seuil est sous celui de la promotion
    (verrou `validate_early_stop_block`), donc les deux ne peuvent pas etre vraies ensemble —
    l'ordre est la pour que ca reste vrai si un jour les seuils se rapprochent.

    Une etape sans champion (P0) n'a pas de pool : rien a decider.
    """
    if champion_label is None:
        return PoolDecision(POOL_VERDICT_CONTINUE, f"{stage_name} : pas de pool, rien a decider.")
    if champion_label not in mean_scores_vs_pool:
        raise KeyError(
            f"Decision de {stage_name} : aucune moyenne contre le champion {champion_label!r}. "
            f"Moyennes disponibles : {sorted(mean_scores_vs_pool)}"
        )

    destroy_floor = float(require_key(early_stop_cfg, "destroy_score_vs_champion"))
    destroy_after = int(require_key(early_stop_cfg, "destroy_min_episodes"))
    champion_mean = float(mean_scores_vs_pool[champion_label])
    if stage_episodes >= destroy_after and champion_mean < destroy_floor:
        return PoolDecision(POOL_VERDICT_DESTROY, (
            f"{stage_name} : moyenne {champion_mean:.3f} contre le champion {champion_label} "
            f"a {stage_episodes} episodes d'etape — SOUS {destroy_floor:.2f}. L'etape part a 0.50 "
            "contre lui par construction : elle detruit la politique qu'elle a recue. Run ARRETE."
        ))

    promote_after = int(require_key(early_stop_cfg, "promote_min_episodes"))
    if stage_episodes < promote_after:
        return PoolDecision(POOL_VERDICT_CONTINUE, (
            f"{stage_name} : {stage_episodes} episodes d'etape, promotion ouverte a "
            f"{promote_after}."
        ))
    shortfalls = _pool_score_shortfalls(
        champion_label,
        mean_scores_vs_pool,
        float(require_key(early_stop_cfg, "promote_score_vs_champion")),
        float(require_key(early_stop_cfg, "promote_score_vs_others")),
    )
    if shortfalls:
        return PoolDecision(POOL_VERDICT_CONTINUE, (
            f"{stage_name} : seuils de promotion non atteints — " + " ; ".join(shortfalls)
        ))
    return PoolDecision(POOL_VERDICT_PROMOTE, (
        f"{stage_name} : tous les seuils de promotion tenus a {stage_episodes} episodes d'etape "
        f"({', '.join(f'{lbl}={mean_scores_vs_pool[lbl]:.3f}' for lbl in sorted(mean_scores_vs_pool))}). "
        "Le budget restant serait paye pour rien. Run ARRETE."
    ))


def evaluate_stage_gate(
    stage_name: str,
    champion_label: Optional[str],
    mean_scores_vs_pool: Dict[str, float],
    floor_champion: float,
    floor_others: float,
) -> Tuple[bool, str]:
    """(accepte, motif) — deux planchers sur les MOYENNES de fin d'etape.

    Remplace `benchmark_floor`, aveugle ici : les bots de reference sont satures a 1.00, donc un
    plancher pose dessus est franchi par n'importe quel modele et ne separe rien. Les membres du
    pool, eux, sont des adversaires dont la force suit celle de l'agent — les seuls etalons qui
    restent discriminants d'une etape a l'autre.

    DEUX PLANCHERS et non un : `floor_champion` contre le champion le plus recent, celui dont
    l'etape reprend les poids et contre qui elle part donc a 0.50 ; `floor_others` contre chacun
    des autres membres. Le second est a la parite et non au-dessus — un ancien qui tient encore
    l'agent en echec est une regression, mais l'agent n'a aucune raison de le DOMINER, il ne
    s'entraine contre lui qu'a une fraction de son budget. Le gate ne portait que sur le champion
    jusqu'au 2026-09-07, et une etape pouvait donc etre promue en ayant regresse contre tout le
    reste du pool sans que rien ne le refuse.

    Les scores attendus sont des MOYENNES de `gate.eval_repeats` blocs a graines tirees, pas une
    mesure unique — meme grandeur que celle sur laquelle l'early-stop decide.

    Une etape sans champion (P0) n'a rien a franchir : elle est acceptee, et le motif le dit.
    """
    if champion_label is None:
        return True, f"{stage_name} : pas de champion a battre (premiere etape), gate sans objet."
    shortfalls = _pool_score_shortfalls(
        champion_label, mean_scores_vs_pool, floor_champion, floor_others
    )
    detail = ", ".join(
        f"{label}={mean_scores_vs_pool[label]:.3f}" for label in sorted(mean_scores_vs_pool)
    )
    if shortfalls:
        return False, (
            f"{stage_name} : {detail} — sous plancher : {' ; '.join(shortfalls)}. "
            f"Etape REFUSEE, aucune promotion."
        )
    return True, (
        f"{stage_name} : {detail} — planchers tenus (champion >= {floor_champion:.2f}, "
        f"autres >= {floor_others:.2f})."
    )


def pool_monotonicity_diagnostic(
    scores_vs_pool: Dict[str, float], pool_order: Sequence[str]
) -> List[str]:
    """Lignes de DIAGNOSTIC sur la monotonie du pool. Jamais un gate.

    Attendu intuitif : plus un adversaire du pool est ancien, plus le score contre lui est eleve.

    La raison d'origine de ne PAS en faire un gate a disparu le 2026-09-04. Elle tenait a
    l'independance des runs : les learners demarraient tous `--new`, donc deux etapes voisines
    etaient des entrainements separes et pouvaient se departager dans le desordre par simple
    variance, sans qu'aucune anomalie ne se soit produite. La lignee est desormais CHAINEE
    (`_doc_lignees` de curriculum.json) : une etape REPREND les poids de la precedente, donc une
    inversion dit qu'un entrainement supplementaire a rendu le modele moins bon contre le meme
    etalon — une regression a l'interieur d'une seule lignee, pas un tirage.

    Reste un diagnostic malgre tout, pour une raison qui n'est plus celle-la : les scores viennent
    d'une evaluation FINIE (`gate.eval_episodes`, 300 episodes), ou l'erreur-type d'un taux proche
    de 0.5 vaut 2,9 points — soit presque tout l'ecart que le gate lui-meme doit trancher entre
    ses deux planchers (`min_score_vs_others` 0.50 et `min_score_vs_champion` 0.55). Une
    comparaison BRUTE de deux scores voisins refuserait donc des etapes saines sur du bruit. En
    faire un gate demanderait une MARGE au-dessus de cette erreur-type, pas l'inegalite stricte
    codee ici. Decision non prise : on journalise pour lire, pas pour trancher.
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
