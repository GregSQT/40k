"""Journal des episodes TRONQUES — ecriture, nommage, borne. Source unique.

POURQUOI (V11 §0.61).
Le moteur coupe un episode qui depasse son plafond de pas (`w40k_core._get_episode_step_limit`).
Ce n'est PAS une fin de partie : c'est le symptome d'une BOUCLE. Le moteur assemblait deja tout
ce qu'il faut pour reproduire — tour, phase, scenario, unite active, pools, derniere action — et
l'envoyait dans un `print` du WORKER, noye dans la console a `n_envs=48` et perdu au scroll.

Ce fichier vit a cote des evenements TensorBoard de l'agent (`log_dir`), pas a cote du `.zip` :
ce n'est pas un compagnon de modele (cf. ai/companion_paths.py, dont la regle est un nom PAR
MODELE), c'est le journal d'un dossier de run. Il n'est donc ni copie ni supprime avec le modele,
et c'est voulu — une trace d'incident survit a l'artefact qui l'a produite.

`log_dir` porte l'agent et le profil mais PAS le run (« continuous TensorBoard graphs across
runs », cf. `tb_log_name` dans ai/train.py) : le journal TRAVERSE les runs. Chaque ligne porte
donc `run`, sans quoi deux entrainements successifs seraient indiscernables — `num_timesteps`
repart de zero a chaque `--new`.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import Counter
from typing import Any, Dict, List, Mapping, Optional, Sequence

FILENAME = "truncations.jsonl"

#: Portees annoncees SEPAREMENT, et libelle de chacune dans le bilan. Une boucle qui ne se
#: reproduit qu'en eval (`deterministic=True`, rosters du holdout) et une boucle d'entrainement
#: ne se cherchent pas au meme endroit ; un total unique le cacherait. L'ordre est celui de
#: l'affichage. Source unique : les compteurs du tracker sont construits sur ces cles.
SCOPE_LABELS: Dict[str, str] = {"training": "entrainement", "eval": "eval"}
TRUNCATION_SCOPES = tuple(SCOPE_LABELS)

#: Au-dela, on cesse d'ecrire — mais on continue de COMPTER, et le bilan le dit.
#:
#: Une troncature est censee ne jamais arriver ; si une boucle en produit des milliers, les 500
#: premieres portent deja le diagnostic, et les suivantes n'apprennent rien qu'un compteur ne
#: dise mieux. La borne existe pour ne pas remplir un disque pendant un run de 47 h. Elle n'est
#: pas silencieuse : c'est la difference entre borner et tronquer en douce.
MAX_LINES = 500


def agent_log_dir(tensorboard_log: str, agent_key: str) -> str:
    """Dossier de run d'un agent. SOURCE UNIQUE — le tracker et l'eval seule s'y accordent.

    Sans elle, un mode qui ne construit pas de tracker devait recopier ce `join` et pouvait
    poser son journal a cote du bon dossier plutot que dedans.
    """
    return os.path.join(tensorboard_log, agent_key)


class TruncationLog:
    """Compte ET trace les troncatures d'UN dossier de run.

    Le compte vit ICI et pas dans le tracker de metriques : le mode « eval seule » n'a pas de
    tracker (il ne produit aucune courbe) et doit pourtant compter ses troncatures, sans quoi
    elles sortent en NUL dans le score publie — le moteur pose `winner = -1` dessus. Un objet
    qui compte sans savoir ecrire, plus un objet qui ecrit sans savoir compter, obligeait a
    reassembler les deux dans chaque mode ; ici les deux modes partagent le meme.

    `log_dir=None` : comptage sans journal, pour un mode qui n'a pas de dossier de run. Le
    bilan le DIT — c'est une degradation annoncee, pas un journal silencieusement perdu.
    """

    def __init__(self, log_dir: Optional[str], max_lines: int = MAX_LINES) -> None:
        self.path = os.path.join(log_dir, FILENAME) if log_dir is not None else None
        self.max_lines = int(max_lines)
        self.run_tag = time.strftime("%Y%m%d-%H%M%S")
        self.written = 0
        self.dropped = 0
        #: Lignes perdues sur erreur d'ecriture (disque plein, droits). Annoncees dans le bilan :
        #: un journal qui n'a pas pu ecrire doit le DIRE, sinon son silence se lit comme un zero.
        self.failed = 0
        self.last_error: Optional[str] = None
        self.counts: Dict[str, Counter] = {scope: Counter() for scope in TRUNCATION_SCOPES}
        # L'eval de gating tourne sur le thread `bot-eval` (`_submit_async_eval` dans
        # ai/training_callbacks.py), l'entrainement sur le thread principal. `Counter[reason] += 1`
        # et l'ecriture sont des lire-modifier-ecrire non atomiques : entrelaces, ils PERDENT un
        # increment et le bilan sous-compte par rapport aux lignes reellement ecrites. Un compteur
        # d'incidents qui sous-compte est la meme faute que le silence qu'il existe pour fermer.
        self._lock = threading.Lock()

    def record(self, scope: str, reason: str, payload: Mapping[str, Any]) -> None:
        """Compte + trace UNE troncature. Site unique : la portee n'est qu'une cle.

        Le compte est ventile PAR RAISON. Il n'y a qu'un site de troncature dans le moteur
        aujourd'hui, mais un total agrege cesserait de repondre a la question le jour ou un
        second apparait — « 37 troncatures » obligerait a lire le journal pour savoir quel
        garde a tire.
        """
        if scope not in self.counts:
            raise KeyError(
                f"Unknown truncation scope {scope!r} (expected one of {TRUNCATION_SCOPES})"
            )
        with self._lock:
            self.counts[scope][reason] += 1
            self._write({"scope": scope, "reason": reason, **payload})

    def record_eval_batch(self, entries: Sequence[Mapping[str, Any]]) -> None:
        """Troncatures d'une campagne d'EVAL, qui remontent en lot des process workers."""
        for entry in entries:
            payload = dict(entry)
            # `reason` devient une cle de premier plan de la ligne : la laisser AUSSI dans le
            # payload ecraserait celle que `record` pose (meme valeur aujourd'hui, mais deux
            # sources pour un champ est ce qui finit par diverger).
            self.record("eval", payload.pop("reason"), payload)

    def _write(self, payload: Mapping[str, Any]) -> None:
        """Ecrit une ligne JSON.

        Le journal CREE son dossier. S'en remettre au `SummaryWriter` du tracker ne tient pas :
        le mode « eval seule » construit un `TruncationLog` sans writer, a partir du
        `tensorboard_log` du modele — dossier qui peut avoir ete purge, ou ne jamais avoir
        existe pour un modele copie d'ailleurs. La premiere troncature levait alors
        `FileNotFoundError` au milieu de `record_eval_batch` et faisait echouer l'evaluation
        AVANT que le score ne soit imprime : perdre la mesure a cause de sa trace.

        `default=str` : un champ du moteur non serialisable (type numpy, enum) doit degrader en
        texte, pas faire echouer l'entrainement. Perdre un run pour une ligne de diagnostic
        serait le contraire de ce que ce journal existe pour eviter.
        """
        if self.path is None:
            return
        if self.written >= self.max_lines:
            self.dropped += 1
            return
        entry = {"run": self.run_tag, **payload}
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, default=str) + "\n")
        except OSError as exc:
            # Disque plein, droits, montage disparu. La ligne est perdue, PAS l'evaluation :
            # le score qu'on vient de mesurer coute des heures, la trace de l'incident non.
            # Ce n'est pas un repli silencieux — `failed` est annonce dans le bilan, et le
            # COMPTE, lui, est deja pris (`record` incremente avant d'ecrire).
            self.failed += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            return
        self.written += 1

    def summary_lines(self) -> List[str]:
        """Bilan de fin de run. Un ZERO s'affiche : « aucune troncature » est un resultat."""
        total = sum(sum(counts.values()) for counts in self.counts.values())
        if total == 0:
            return ["✅ Troncatures : 0 (aucun episode coupe par le garde anti-runaway)"]
        detail = " | ".join(
            f"{SCOPE_LABELS[scope]} "
            + ", ".join(f"{reason}={n}" for reason, n in sorted(self.counts[scope].items()))
            for scope in TRUNCATION_SCOPES
            if self.counts[scope]
        )
        lines = [
            f"⚠️  Troncatures : {total} episode(s) coupe(s) par le garde anti-runaway ({detail}).",
        ]
        if self.path is None:
            lines.append(
                "   Aucun journal ecrit : ce mode n'a pas de dossier de run. Le detail par "
                "troncature n'existe que dans la sortie des workers."
            )
        else:
            lines.append(
                f"   Diagnostic complet (une ligne JSON par troncature) : {self.path}"
            )
        if self.dropped:
            lines.append(
                f"   {self.dropped} non ecrite(s) : journal borne a {self.max_lines} lignes "
                f"(les {self.max_lines} premieres suffisent a reproduire)."
            )
        if self.failed:
            lines.append(
                f"   ⚠️  {self.failed} ligne(s) PERDUE(S) a l'ecriture ({self.last_error}) — "
                f"le compte ci-dessus reste juste, le detail de ces lignes non."
            )
        return lines
