"""Traces `[TRAIN DEBUG]` — point d'émission UNIQUE, par canal, à formatage différé.

POURQUOI CE MODULE (V11 §0.46 point 3, axes B et C).

AXE B — le préfixe `[TRAIN DEBUG]` et le `flush=True` étaient recopiés sur 37 sites, plus un
helper local qui refaisait le même formatage dans son coin (`train._debug_train_marker`,
désormais un simple appel à `trace`). C'est le motif JUMEAU du dépôt appliqué à de
l'outillage : deux écritures du même format, qui divergent à la première évolution.
(`ai/analyzer._debug_log` n'est PAS concerné : il écrit dans un fichier de log de l'analyzer,
pas sur la sortie standard, et ne porte pas ce préfixe.)

AXE C — `debug_mode` allumait les 37 traces d'un coup. Chercher une boucle bot qui se fige
noyait le signal sous le flux de `W40KEngine.step`, le chemin le plus chaud du moteur. Les
canaux permettent de n'allumer que le sous-système observé.

⚠️ RÈGLE D'USAGE — JAMAIS DE f-STRING EN ARGUMENT.
    OUI : trace(CH_STEP, "step enter episode=%s phase=%s", episode, phase)
    NON : trace(CH_STEP, f"step enter episode={episode} phase={phase}")
La f-string est évaluée AVANT l'appel, donc hors de toute garde : elle déplace le coût du
formatage sur le chemin de production, où il est censé être nul. C'est exactement la
régression que la forme précédente évitait par accident, et que ce module doit continuer
d'éviter par construction. `tests/unit/engine/test_debug_trace_guard.py` la verrouille.

SÉLECTION DES CANAUX — variable d'environnement `W40K_TRACE`, lue UNE FOIS au chargement :
    W40K_TRACE non définie  -> tous les canaux (comportement historique de `--debug`)
    W40K_TRACE=bot_loop     -> ce canal seul
    W40K_TRACE=step,deploy_cache
    W40K_TRACE=none         -> aucun canal, même sous `--debug`
Un nom inconnu LÈVE au chargement : une faute de frappe qui éteindrait silencieusement la
trace qu'on cherche est le pire résultat possible pour un outil de diagnostic.

Le `debug_mode` du moteur reste le commutateur maître : sans lui, aucun canal n'émet.
"""

import os
import sys
from typing import Any

#: Canaux déclarés. Un canal = un sous-système qu'on veut pouvoir observer SEUL.
CH_STEP = "step"
CH_BOT_LOOP = "bot_loop"
CH_DEPLOY_CACHE = "deploy_cache"
CH_TRAIN = "train"

TRACE_CHANNELS = (CH_STEP, CH_BOT_LOOP, CH_DEPLOY_CACHE, CH_TRAIN)

TRACE_PREFIX = "[TRAIN DEBUG]"

_ENV_VAR = "W40K_TRACE"


def _selected_channels() -> frozenset:
    """Canaux retenus par `W40K_TRACE`. Absente = tous, `none` = aucun, nom inconnu = lève."""
    raw = os.environ.get(_ENV_VAR)
    if raw is None:
        return frozenset(TRACE_CHANNELS)
    names = [part.strip() for part in raw.split(",") if part.strip()]
    if not names:
        # `W40K_TRACE=` (definie mais vide) est AMBIGUE : « pas de filtre » ou « rien » ? Elle
        # sort d'un `export W40K_TRACE=` ou d'une substitution de shell qui n'a rien rendu. La
        # traiter comme « rien » eteindrait toutes les traces en silence — le defaut meme que
        # ce module existe pour rendre impossible. On leve, et on nomme la sortie voulue.
        raise ValueError(
            f"{_ENV_VAR} est definie mais vide : intention ambigue. "
            f"Utiliser '{_ENV_VAR}=none' pour tout eteindre, ou desaffecter la variable "
            f"(`unset {_ENV_VAR}`) pour tout allumer."
        )
    if names == ["none"]:
        return frozenset()
    unknown = [name for name in names if name not in TRACE_CHANNELS]
    if unknown:
        raise ValueError(
            f"{_ENV_VAR} : canal(aux) inconnu(s) {unknown}. "
            f"Canaux declares : {list(TRACE_CHANNELS)} (ou 'none')."
        )
    return frozenset(names)


#: Résolu au chargement : la sélection ne change pas en cours de run, et la relire à chaque
#: trace mettrait un accès `os.environ` sur le chemin de `step`.
_SELECTED = _selected_channels()


def channel_enabled(channel: str, debug_mode: bool) -> bool:
    """Ce canal émet-il ? À utiliser dans le `if` quand préparer les arguments COÛTE.

    Sur les sites où les arguments sont des variables déjà calculées, `trace` suffit : sa
    propre garde est le premier test qu'il fait.
    """
    if not debug_mode:
        return False
    if channel not in TRACE_CHANNELS:
        raise ValueError(f"canal de trace inconnu : {channel!r} (declares : {list(TRACE_CHANNELS)})")
    return channel in _SELECTED


def trace(channel: str, debug_mode: bool, fmt: str, *args: Any) -> None:
    """Émet une trace si `debug_mode` et si le canal est sélectionné.

    `fmt % args` est appliqué APRÈS la garde : les arguments non formatés ne coûtent rien
    quand la trace est éteinte.
    """
    if not channel_enabled(channel, debug_mode):
        return
    message = fmt % args if args else fmt
    print(f"{TRACE_PREFIX} {message}", flush=True, file=sys.stdout)
