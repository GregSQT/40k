#!/usr/bin/env python3
"""Mesure directe de l'étalement des bots (zones, distance, pertes) par tour.

Joue des épisodes de bot eval sans passer par train.py ni step_logger.
Lit game_state après chaque step pour mesurer trois grandeurs par tour :
  - zones contrôlées par le bot player (objective_controllers)
  - distance hex moyenne de chaque escouade bot au plus proche ennemi vivant
  - taux d'escouades bot perdues (∆ depuis T1)

⚠️ DEUX ENTRÉES DÉCIDENT DU CHIFFRE AUTANT QUE LES POIDS MESURÉS, et les deux étaient
silencieuses (corrigé le 2026-08-13) :

1. LE MODÈLE. Le script lisait le chemin canonique `model_ArmageddonAgent.zip`, que le moindre
   entraînement réécrit. Toutes les mesures du §12 sont faites sur le checkpoint robust_0.8463
   (md5 794335b…). Le checkpoint est désormais NOMMÉ et VÉRIFIÉ AU MD5 — le jour où il change,
   le script lève au lieu de rendre un tableau incomparable.
2. LE PLATEAU. Sans `W40K_BOARD_PATH`, c'est `config/config.json` qui décide (x5), où le
   classement des bots n'est pas le même. La variable est EXIGÉE, pas défaultée.

Usage (protocole §12.8) :
    W40K_BOARD_PATH=board/44x60x1 python3 scripts/bot_zone_direct.py --episodes 60 [--json-out F]

`--json-out` écrit le relevé PAR ÉPISODE (graine, joueur du bot, grandeurs par tour) : la sortie
texte agrégée reste identique, seul s'y ajoute le chemin du fichier écrit.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, TextIO, cast

import gymnasium

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot_panel_reference import print_panel_reference  # noqa: E402  (dépend du sys.path ci-dessus)
from shared.json_atomic import dump_json, json_out_draft  # noqa: E402  (dépend du sys.path ci-dessus)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 2 : `run` regroupe les métadonnées du run, `model` (basename) devient `model_path`/`model_bytes`
# /`model_mtime`. Un lecteur de la v1 lèverait un KeyError sur un fichier v2 — d'où le numéro.
# 3 : `run.episodes_requested` (nombre d'épisodes PAR BOT, malgré le nom) disparaît au profit de
# `run.episodes_per_bot` et `run.episodes_total`. Un lecteur de la v2 lève un KeyError sur un
# fichier v3, donc le numéro DOIT bouger.
# 4 : `focus_targets_by_turn` renommé `distinct_targets_by_turn` dans `episodes[*]` : les deux noms
# désignaient des métriques différentes (géométrique nearest-enemy vs doctrine _focus_target), le
# préfixe `focus_` commun induisait en erreur. Un lecteur de la v3 qui lit `focus_targets_by_turn`
# lève un KeyError sur un fichier v4.
# ⚠️ CE NUMÉRO A DÉJÀ MENTI DEUX FOIS, et les deux fois de la même façon : la forme a changé
# sans lui. Le commit a4668891 a émis la forme v2 en la marquant `1` ; les commits e8db6180 et
# 046478e7 ont retiré `episodes_requested` en gardant `2`, si bien que DEUX formes incompatibles
# portent le numéro 2. Aucun fichier du dépôt n'en vient (aucun JSON n'y porte `schema_version`,
# vérifié le 2026-08-13), mais un lecteur qui branche sur le numéro doit tester les CLÉS qu'il
# lit, jamais le seul entier. Corollaire pour la suite : toute clé retirée ou renommée dans
# `run`/`episodes` incrémente cette constante DANS LE MÊME commit.
_JSON_SCHEMA_VERSION = 4

#: Checkpoint sur lequel TOUTES les mesures du §12 sont faites. Remplacer ici est une décision
#: de protocole : elle périme les chiffres du chantier, donc elle ne se prend pas par accident.
#: v1 (0.8721, ancien panel, bots control/greedy/…) — perdu le 2026-08-17 par runs croisés.
#: v2 (0.8692, nouveau panel new_bots, 2026-08-17) — NE CHARGE PLUS depuis le 2026-08-20.
#: v3 (0.8463, 2026-08-21) — référence courante.
#:
#: ⛔ RUPTURE DE COMPARABILITÉ, 2026-08-21. Le commit d5ddffb5 (charge multi-cibles, P3 L9) a ajouté
#: la tête dense `charge_pair_net` à `PointerMaskablePolicy`. Tout checkpoint antérieur lève au
#: chargement (`Missing key(s) in state_dict: "charge_pair_net.weight", "charge_pair_net.bias"`),
#: v2 compris : les 22 archives d'avant ce commit sont définitivement immesurables, et aucune
#: greffe de tête ne les sauve — une tête non entraînée sur des actions LÉGALES mesurerait une
#: politique qui n'a jamais existé. Les chiffres du §12 mesurés sur v2 ne se comparent donc à
#: AUCUN relevé pris sur v3 : la ligne de base doit être rejouée avant toute comparaison.
#: v3 est la seule archive nommée `_robust_` postérieure à d5ddffb5 (chargement des 28 archives
#: du dossier vérifié le 2026-08-21 : 6 chargent, 22 lèvent).
REFERENCE_MODEL = "ArmageddonAgent_12345_robust_0.8463.zip"
REFERENCE_MD5 = "794335b6979b9532f7ce7c83c59c950e"

#: Chemin ABSOLU de l'archive de référence. Séparé de REFERENCE_MODEL pour être monkeypatchable
#: dans les tests sans toucher au nom qui identifie le checkpoint dans les logs et justifications.
_DEFAULT_MODEL = os.path.join(_PROJECT_ROOT, "ai", "models", "ArmageddonAgent", REFERENCE_MODEL)

#: Config d'entraînement sur laquelle TOUTES les mesures du §12 sont faites.
_TRAINING_CONFIG = "x1_long"


def _prepare_model_input(model_obs: Any, model_known: set) -> Any:
    """Adapte l'observation brute au format attendu par model.predict."""
    if isinstance(model_obs, dict):
        if not model_known.issubset(model_obs.keys()):
            raise RuntimeError(f"Clés d'observation absentes du step : {model_known - model_obs.keys()!r}")
        return {k: v for k, v in model_obs.items() if k in model_known}
    import numpy as np
    arr = np.asarray(model_obs, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    return arr


def _md5(path: str) -> str:
    """Empreinte MD5 du fichier, en lecture par blocs (fichiers > 1 Mio)."""
    h = hashlib.md5(usedforsecurity=False)
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _require_reference_model(path: Optional[str] = None) -> str:
    """Chemin du modèle vérifié au md5. Lève plutôt que de mesurer un autre modèle.

    `path` est un ALIAS DE CHEMIN vers le checkpoint de référence, PAS un sélecteur de modèle :
    il subit le même contrôle md5 que le défaut, donc pointer une autre archive lève. C'est
    délibéré — `test_require_reference_model_chemin_non_canonique_verifie_md5` le verrouille,
    précisément pour qu'un chemin détourné (`..`, lien, copie) ne fasse pas entrer un autre
    modèle dans un tableau du §12. Mesurer un autre checkpoint = acter le nouvel étalon dans
    `REFERENCE_MODEL`/`REFERENCE_MD5` ci-dessus, ce qui périme les chiffres publiés.

    Sans argument : utilise _DEFAULT_MODEL (archive de référence §12).
    """
    if path is None:
        resolved = _DEFAULT_MODEL
        if not os.path.exists(resolved):
            raise RuntimeError(
                f"Modèle de référence absent : {resolved}. Toutes les mesures du §12 sont faites sur lui ; "
                "mesurer avec un autre rend le tableau incomparable."
            )
    else:
        resolved = os.path.realpath(path)
        if not os.path.exists(resolved):
            raise RuntimeError(f"Modèle introuvable : {path}")
    digest = _md5(resolved)
    if digest != REFERENCE_MD5:
        raise RuntimeError(
            f"md5 attendu {REFERENCE_MD5}, obtenu {digest} : {resolved!r} "
            "n'est pas le checkpoint de référence."
        )
    return resolved


def _require_board_path() -> str:
    """Le plateau vient de l'environnement, jamais de config.json (cf. l'en-tête)."""
    board = os.environ.get("W40K_BOARD_PATH")
    if not board:
        raise RuntimeError(
            "W40K_BOARD_PATH non défini : sans elle le plateau est celui de config.json (x5), où "
            "le classement des bots diffère. Relancer avec W40K_BOARD_PATH=board/44x60x1."
        )
    return board


def _collect_live_enemies(gs: Dict[str, Any], bot_player: int) -> List[tuple]:
    """(sid, col, row) de chaque ennemi vivant sur table."""
    from engine.phase_handlers.shared_utils import is_unit_alive, require_unit_from_cache
    from engine.spatial_relations import entry_is_on_battlefield

    result: List[tuple] = []
    for u in gs.get("units", []):
        if int(u.get("player", 0)) == bot_player:
            continue
        sid = str(u["id"])
        if not is_unit_alive(sid, gs):
            continue
        entry = require_unit_from_cache(sid, gs, "_enemies:enemy")
        if entry_is_on_battlefield(entry):
            result.append((sid, int(entry["col"]), int(entry["row"])))
    return result


def _collect_live_bot_positions(gs: Dict[str, Any], bot_player: int) -> List[tuple]:
    """(col, row) de chaque escouade bot vivante sur table."""
    from engine.phase_handlers.shared_utils import is_unit_alive, require_unit_from_cache
    from engine.spatial_relations import entry_is_on_battlefield

    result: List[tuple] = []
    for u in gs.get("units", []):
        if int(u.get("player", 0)) != bot_player:
            continue
        sid = str(u["id"])
        if not is_unit_alive(sid, gs):
            continue
        entry = require_unit_from_cache(sid, gs, "_bots:bot")
        if entry_is_on_battlefield(entry):
            result.append((int(entry["col"]), int(entry["row"])))
    return result


def _avg_bot_enemy_distance(
    gs: Dict[str, Any],
    bot_player: int,
    enemies: Optional[List[tuple]] = None,
    bot_positions: Optional[List[tuple]] = None,
) -> Optional[float]:
    """Distance hex moyenne de chaque escouade bot vivante au plus proche ennemi vivant sur table.

    Retourne None si aucun ennemi n'est sur la table (réserves seules ou tous éliminés).
    Les escouades en réserves sont exclues côté bot ET côté ennemi.
    `enemies` et `bot_positions` peuvent être pré-collectés pour éviter de re-traverser gs à
    chaque métrique dans la boucle de pas.
    """
    from engine.combat_utils import calculate_hex_distance

    if enemies is None:
        enemies = _collect_live_enemies(gs, bot_player)
    if not enemies:
        return None
    if bot_positions is None:
        bot_positions = _collect_live_bot_positions(gs, bot_player)
    enemy_positions = [(col, row) for _, col, row in enemies]
    distances = [
        min(calculate_hex_distance(bc, br, ec, er) for ec, er in enemy_positions)
        for bc, br in bot_positions
    ]
    return sum(distances) / len(distances) if distances else None


def _count_distinct_focus_targets(
    gs: Dict[str, Any],
    bot_player: int,
    enemies: Optional[List[tuple]] = None,
    bot_positions: Optional[List[tuple]] = None,
) -> Optional[int]:
    """Nombre d'ennemis DISTINCTS élus « plus proche » par au moins une escouade bot sur table.

    1 = toutes les escouades convergent vers le même ennemi ; N = chacune part de son côté.
    C'est la mesure de convergence qui distingue une hausse de `dist_by_turn` due à l'élection
    d'une cible commune (progrès) d'une hausse due à autre chose (régression).

    Retourne None si aucun ennemi n'est sur la table, ou si aucune escouade bot ne l'est.
    `enemies` et `bot_positions` peuvent être pré-collectés (voir `_avg_bot_enemy_distance`).
    """
    from engine.combat_utils import calculate_hex_distance

    if enemies is None:
        enemies = _collect_live_enemies(gs, bot_player)
    if not enemies:
        return None
    if bot_positions is None:
        bot_positions = _collect_live_bot_positions(gs, bot_player)
    chosen: set = set()
    for bc, br in bot_positions:
        nearest = min(enemies, key=lambda e: calculate_hex_distance(bc, br, e[1], e[2]))
        chosen.add(nearest[0])
    return len(chosen) if chosen else None


def _avg_focus_target_distance(
    gs: Dict[str, Any], bot: Any, bot_player: int, bot_positions: Optional[List[tuple]] = None
) -> Optional[float]:
    """Distance hex moyenne des escouades bot sur table à la cible FOCALISÉE du bot.

    N'existe que pour les doctrines qui élisent une cible commune (DecapitationBot) : les autres
    n'ont pas d'attribut `_focus_target`, et la métrique est alors ABSENTE — pas nulle, pas 0.

    On lit `bot._focus_target` NU, jamais `bot._focus(game_state)` : `_focus` périme la cible sur
    le marqueur de tour, donc l'appeler depuis l'instrumentation muterait l'état du bot à la
    frontière de tour et changerait la mesure elle-même.

    ⚠️ COROLLAIRE, et il a FAIT PLANTER LE RUN DE RÉFÉRENCE (2026-08-13) : lire nu, c'est aussi
    lire une cible que `_focus` n'a pas encore périmée. Entre deux épisodes, `_focus_target` garde
    celle de l'épisode précédent jusqu'au premier appel du bot, et `agent_seat_mode` vaut
    « random » — le bot change donc de siège, et l'ancienne cible ennemie devient une escouade
    À LUI. Le garde de joueur ci-dessous levait alors « bot mal configuré » au 2e épisode de
    `decapitation`, sur un bot parfaitement configuré. Diagnostic relevé : marqueur `(1, 5)`
    contre un état `episode=2, turn=1`.
    La péremption se CONSTATE ici au lieu d'être provoquée : le marqueur du bot est comparé à
    l'état courant, et une cible périmée rend `None` — la métrique est absente pour ce relevé,
    ce qui est la vérité (aucune cible n'est élue à cet instant), pas un repli.
    """
    from engine.phase_handlers.shared_utils import is_unit_alive, require_unit_from_cache
    from engine.spatial_relations import entry_is_on_battlefield
    from engine.combat_utils import calculate_hex_distance

    if not hasattr(bot, "_focus_target"):
        return None
    focused = bot._focus_target
    if focused is None:
        return None
    # Même critère de péremption que `DecapitationBot._focus`, LU et non appliqué.
    if getattr(bot, "_focus_turn", None) != (gs.get("episode_number"), int(gs.get("turn", 0))):
        return None
    focused = str(focused)
    focused_player = next(
        (int(u.get("player", 0)) for u in gs.get("units", []) if str(u["id"]) == focused),
        None,
    )
    if focused_player is None:
        print(f"\n[WARN] focus_dist: cible introuvable '{focused}' dans gs['units']", file=sys.stderr)
        return None
    if focused_player == bot_player:
        print(
            f"\n[WARN] focus_dist: cible '{focused}' appartient au bot-player {bot_player} "
            "(marqueur à jour — ce n'est pas un résidu inter-épisode)",
            file=sys.stderr,
        )
        return None
    if not is_unit_alive(focused, gs):
        return None
    target_entry = require_unit_from_cache(focused, gs, "_focus_dist:target")
    if not entry_is_on_battlefield(target_entry):
        return None
    tc, tr = int(target_entry["col"]), int(target_entry["row"])
    if bot_positions is None:
        bot_positions = _collect_live_bot_positions(gs, bot_player)
    distances = [
        calculate_hex_distance(bc, br, tc, tr)
        for bc, br in bot_positions
    ]
    return sum(distances) / len(distances) if distances else None


def _count_alive_bot_squads(gs: Dict[str, Any], bot_player: int) -> int:
    """Nombre d'escouades bot vivantes (sur table + réserves — pas encore éliminées)."""
    from engine.phase_handlers.shared_utils import is_unit_alive

    return sum(
        1
        for u in gs.get("units", [])
        if int(u.get("player", 0)) == bot_player and is_unit_alive(str(u["id"]), gs)
    )


def _episode_record(
    bot_name: str,
    episode: int,
    seed: int,
    bot_player: int,
    turn_snapshot: Dict[int, int],
    dist_snapshot: Optional[Dict[int, float]] = None,
    squad_snapshot: Optional[Dict[int, int]] = None,
    focus_targets_snapshot: Optional[Dict[int, int]] = None,
    focus_dist_snapshot: Optional[Dict[int, float]] = None,
) -> Dict[str, Any]:
    """Relevé d'UN épisode, suffisant pour le rejouer (graine) et l'inspecter (zones/tour)."""
    rec: Dict[str, Any] = {
        "bot": bot_name,
        "episode": episode,
        "seed": seed,
        "bot_player": bot_player,
        "zones_by_turn": {str(t): turn_snapshot[t] for t in sorted(turn_snapshot)},
    }
    if dist_snapshot:
        rec["dist_by_turn"] = {str(t): dist_snapshot[t] for t in sorted(dist_snapshot)}
    if squad_snapshot:
        rec["squads_by_turn"] = {str(t): squad_snapshot[t] for t in sorted(squad_snapshot)}
    if focus_targets_snapshot:
        rec["distinct_targets_by_turn"] = {
            str(t): focus_targets_snapshot[t] for t in sorted(focus_targets_snapshot)
        }
    if focus_dist_snapshot:
        rec["focus_dist_by_turn"] = {
            str(t): focus_dist_snapshot[t] for t in sorted(focus_dist_snapshot)
        }
    return rec


def _turns_of(records: List[Dict[str, Any]]) -> Dict[int, List[int]]:
    """{tour: [zones, un par épisode]} pour les relevés d'UN seul bot, dans l'ordre des épisodes."""
    per_turn: Dict[int, List[int]] = {}
    for rec in records:
        for turn_key, zones in rec["zones_by_turn"].items():
            per_turn.setdefault(int(turn_key), []).append(zones)
    return per_turn


def _turns_of_key(records: List[Dict[str, Any]], key: str) -> Dict[int, List]:
    """{tour: [valeur, un par épisode]} pour n'importe quelle clé `*_by_turn` du relevé."""
    per_turn: Dict[int, List] = {}
    for rec in records:
        for turn_str, val in rec.get(key, {}).items():
            per_turn.setdefault(int(turn_str), []).append(val)
    return per_turn


def _loss_rate_by_turn(records: List[Dict[str, Any]]) -> Dict[int, List[float]]:
    """Taux de perte cumulé (0–1) par tour : (squads_T1 − squads_T) / squads_T1, par épisode."""
    per_turn: Dict[int, List[float]] = {}
    for rec in records:
        squads = rec.get("squads_by_turn", {})
        if not squads:
            continue
        sorted_turns = sorted(int(k) for k in squads)
        baseline = squads[str(sorted_turns[0])]
        if baseline == 0:
            continue
        for t in sorted_turns:
            alive = squads[str(t)]
            per_turn.setdefault(t, []).append((baseline - alive) / baseline)
    return per_turn


def _aggregate_zones(records: List[Dict[str, Any]]) -> Dict[str, Dict[int, List[int]]]:
    """Agrège les relevés par épisode en {bot: {tour: [zones, ...]}} — source du tableau texte."""
    by_bot: Dict[str, List[Dict[str, Any]]] = {}
    for rec in records:
        by_bot.setdefault(rec["bot"], []).append(rec)
    return {bot: _turns_of(bot_records) for bot, bot_records in by_bot.items()}


def _table_turns(turn_limit: Optional[int], records: List[Dict[str, Any]]) -> List[int]:
    """Colonnes des trois tableaux : les tours de LA BATAILLE, pas une liste écrite à la main.

    `turn_limit` vient de `get_effective_turn_limit`, source unique de la durée d'une bataille
    (`game_rules.max_turns`). Elle vaut 5 aujourd'hui, exactement les colonnes qui étaient
    codées en dur — mais rien ne gardait le couplage : changer `max_turns` aurait laissé le
    tableau s'arrêter à T5 pendant que la colonne `N`, elle, suit `max(per_turn)`.

    `None` = bataille illimitée (Endless Duty) : il n'y a alors pas de durée à lire, seulement
    des tours OBSERVÉS. Ce n'est pas un repli sur une valeur commode, c'est le seul sens
    disponible dans ce cas ; une liste vide (aucun épisode) reste vide.
    """
    if turn_limit is not None:
        return list(range(1, int(turn_limit) + 1))
    observed = {int(turn) for rec in records for turn in rec["zones_by_turn"]}
    return list(range(1, max(observed) + 1)) if observed else []


def _n_at_last_turn(per_turn: Dict[int, List]) -> int:
    """Nombre d'épisodes parvenus au dernier tour observé — le `N` de la ligne et du tableau."""
    if not per_turn:
        return 0
    return len(per_turn[max(per_turn)])


def _write_json_out(handle: TextIO, run_meta: Dict[str, Any], records: List[Dict[str, Any]]) -> None:
    payload = {"schema_version": _JSON_SCHEMA_VERSION, "run": run_meta, "episodes": records}
    dump_json(handle, payload)


def _model_fingerprint(model_path: str) -> Dict[str, Any]:
    """Identité du checkpoint, à relever AVANT de le charger : un entraînement qui réécrit le
    `.zip` pendant le run ferait sinon consigner les métadonnées d'un modèle qui n'a pas joué.
    Le chemin seul est constant d'un run à l'autre, donc muet — c'est la taille et la date
    qui distinguent deux checkpoints.
    """
    return {
        "model_path": model_path,
        "model_bytes": os.path.getsize(model_path),
        "model_mtime": datetime.fromtimestamp(os.path.getmtime(model_path)).isoformat(timespec="seconds"),
    }


def _run_meta(
    model_fingerprint: Dict[str, Any],
    scenario_file: str,
    episodes_per_bot: int,
    n_bots: int,
    base_seed: int,
    agent_seat_mode: str,
    agent_seat_seed: Optional[int],
    bot_randomness: Dict[str, Any],
    doctrine_weights: Dict[str, Dict[str, float]],
    hold_bonus: float,
    training_config: str,
    label: Optional[str] = None,
) -> Dict[str, Any]:
    """Ce qui distingue DEUX relevés l'un de l'autre — sans ça, un avant et un après §12.7
    sont indiscernables, et une graine d'épisode ne suffit pas à reconstruire la doctrine du bot.

    `doctrine_weights` et `hold_bonus` sont les poids RÉELLEMENT CONSOMMÉS, relus par l'entrée
    publique `load_doctrine_weights` et non recopiés du fichier de config : c'est ce tuple-là qui
    a joué. Sans eux, deux relevés d'une campagne de réglage ne se distinguent par RIEN — le
    protocole du §12.8 ne change qu'un poids d'un run à l'autre, tout le reste étant identique au
    bit, et une comparaison appariée dont on ne sait pas ce qui a changé ne compare rien.
    `hold_bonus` s'y ajoute parce qu'il est le seul terme du score qui ne soit pas par bot : il
    fixe l'échelle à laquelle `w_crowd` se lit, donc il périme la campagne entière s'il bouge.
    """
    meta: Dict[str, Any] = {
        "agent": "ArmageddonAgent",
        "training_config": training_config,
        **model_fingerprint,
        "scenario_file": scenario_file,
        "episodes_per_bot": episodes_per_bot,
        "episodes_total": episodes_per_bot * n_bots,
        "base_seed": base_seed,
        "agent_seat_mode": agent_seat_mode,
        "agent_seat_seed": agent_seat_seed,
        "bot_randomness": dict(bot_randomness),
        "doctrine_weights": doctrine_weights,
        "hold_bonus": hold_bonus,
    }
    if label is not None:
        meta["label"] = label
    return meta


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", type=int, default=10)
    parser.add_argument(
        "--json-out",
        dest="json_out",
        default=None,
        help="Fichier JSON où écrire le relevé par épisode (graine, joueur du bot, grandeurs par tour)",
    )
    parser.add_argument(
        "--label",
        default=None,
        help="Étiquette libre associée à ce run, stockée dans run_meta (absent du JSON si omis)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Autre CHEMIN vers le checkpoint de référence §12 (copie, montage). Le md5 est "
            "vérifié comme sur le défaut : ce n'est pas un moyen de mesurer un autre modèle"
        ),
    )
    args = parser.parse_args()
    # AVANT d'ouvrir la destination : `--episodes 0` jouait zéro épisode, publiait
    # `"episodes": []` PAR-DESSUS le relevé précédent et sortait 0. Le fichier écrasé était le
    # seul exemplaire d'une mesure de plusieurs heures, et rien dans la sortie ne le disait.
    if args.episodes < 1:
        parser.error(f"--episodes doit valoir au moins 1 (reçu {args.episodes})")
    model_path = _require_reference_model(args.model)
    _require_board_path()

    episode_records: List[Dict[str, Any]] = []
    turn_limit: Optional[int] = None

    # le brouillon s'ouvre AVANT les imports lourds : un chemin faux coûte une seconde, et il
    # n'est publié que si le run va au bout (sinon refermé et effacé, cf. `json_out_draft`).
    with json_out_draft(args.json_out) as json_handle:
        import numpy as np
        from sb3_contrib import MaskablePPO
        from sb3_contrib.common.wrappers import ActionMasker
        from sb3_contrib.common.maskable.utils import get_action_masks
        from config_loader import get_config_loader
        from ai.unit_registry import UnitRegistry
        from ai.bot_registry import build_bot
        from ai.bot_doctrines import load_doctrine_weights, load_hold_bonus, DOCTRINE_BOTS
        from ai.evaluation_bots import load_movement_weights
        from ai.env_wrappers import BotControlledEnv
        from ai.training_utils import get_scenario_list_for_phase
        from ai.bot_evaluation import (
            _build_eval_obs_normalizer_for_worker, _episode_seed, _load_bot_eval_params,
        )
        from engine.game_utils import get_effective_turn_limit
        from engine.w40k_core import W40KEngine
        from shared.data_validation import require_key

        config = get_config_loader()
        tc = config.load_agent_training_config("ArmageddonAgent", _TRAINING_CONFIG)

        vec_norm_enabled = bool(tc.get("vec_normalize", {}).get("enabled", False))
        vec_eval_enabled = bool(tc.get("vec_normalize_eval", {}).get("enabled", False))

        if args.label:
            print(f"Run    : {args.label}")
        print(f"Modèle : {os.path.basename(model_path)}")
        model_fingerprint = _model_fingerprint(model_path)  # avant le chargement : cf. docstring
        model = MaskablePPO.load(model_path, device="cpu")
        normalize = _build_eval_obs_normalizer_for_worker(model, model_path, vec_norm_enabled, vec_eval_enabled)
        obs_space = model.observation_space
        if not isinstance(obs_space, gymnasium.spaces.Dict):
            raise TypeError(f"Espace d'observation Dict attendu, reçu {type(obs_space)}")
        model_known = set(obs_space.spaces.keys())

        # Le panel se lit par la MÊME fonction que l'évaluation réelle, jamais à la main : elle
        # exige les deux clés (un panel vide ferait tourner la boucle zéro fois et publier
        # `"episodes": []` en sortant 0), coerce les valeurs en float, et vérifie que les poids
        # somment à 1.0. Relire `cb` ici privait CE script — et lui seul — de ces trois contrôles,
        # alors qu'il compare ses moyennes à celles produites par `ai/bot_evaluation.py`.
        bot_eval_params = _load_bot_eval_params(config, "ArmageddonAgent", _TRAINING_CONFIG)
        bot_weights: dict = bot_eval_params["weights"]
        bot_randomness: dict = bot_eval_params["randomness"]
        # `require_key` : `agent_seat_mode` décide de quel siège occupe le bot, et le défaut
        # « p1 » était de surcroît RECOPIÉ dans `run_meta` comme s'il venait de la config — un
        # relevé qui documente un protocole que personne n'a écrit.
        agent_seat_mode: str = require_key(tc, "agent_seat_mode")
        if "seed" not in tc:
            raise RuntimeError(f"Clé 'seed' absente de la config d'entraînement ArmageddonAgent/{_TRAINING_CONFIG} — run non reproductible")
        base_seed: int = int(tc["seed"])
        agent_seat_seed: Optional[int] = tc.get("agent_seat_seed", base_seed)

        scenarios = get_scenario_list_for_phase(config, "ArmageddonAgent", _TRAINING_CONFIG, scenario_type="holdout")
        if not scenarios:
            raise RuntimeError(f"Aucun scénario holdout trouvé pour ArmageddonAgent/{_TRAINING_CONFIG} — vérifier config/agents/ArmageddonAgent/scenarios/")
        scenario_file = scenarios[0]

        for bot_name in bot_weights:
            print(f"  {bot_name:<16}", end=" ", flush=True)
            bot = build_bot(bot_name, dict(bot_randomness))
            unit_registry = UnitRegistry()

            base_env = W40KEngine(
                rewards_config="ArmageddonAgent",
                training_config_name=_TRAINING_CONFIG,
                controlled_agent="ArmageddonAgent",
                active_agents=None,
                scenario_file=scenario_file,
                unit_registry=unit_registry,
                quiet=True,
                gym_training_mode=True,
                training_n_envs=1,
            )

            masked = ActionMasker(base_env, lambda e: cast(W40KEngine, e).get_action_mask())
            env = BotControlledEnv(
                masked, bot, unit_registry,
                agent_seat_mode=agent_seat_mode,
                global_seed=agent_seat_seed,
                env_rank=0,
            )

            bot_records: List[Dict[str, Any]] = []

            for ep_idx in range(args.episodes):
                ep_seed = _episode_seed(base_seed, bot_name, 0, ep_idx)
                obs, info = env.reset(seed=ep_seed)
                # Désactive le chemin P3-4 (allocation async) : le modèle de référence
                # est pré-P3-4 et ne sait pas traiter une décision `allocation_model`.
                env.engine.game_state["no_gym_allocation_model"] = True
                # `require_key` : `agent_seat_mode` vaut « random » sur x1_long, donc le bot est
                # P1 dans la moitié des épisodes. Le défaut `2` comptait alors les zones de
                # l'AGENT et les publiait sous le nom du bot, sans rien signaler. Même lecture
                # que `scripts/bot_ranking.py:132-133` sur `winner`/`controlled_player`.
                bot_player: int = int(require_key(info, "opponent_player"))
                if turn_limit is None:
                    turn_limit = get_effective_turn_limit(env.engine.game_state)
                done = False
                turn_snapshot: Dict[int, int] = {}
                dist_snapshot: Dict[int, float] = {}
                squad_snapshot: Dict[int, int] = {}
                focus_targets_snapshot: Dict[int, int] = {}
                focus_dist_snapshot: Dict[int, float] = {}

                while not done:
                    model_obs = normalize(obs) if normalize else obs
                    action_masks = np.asarray(get_action_masks(env), dtype=bool)
                    if action_masks.ndim == 1:
                        action_masks = action_masks.reshape(1, -1)
                    model_input = _prepare_model_input(model_obs, model_known)
                    action, _ = model.predict(model_input, action_masks=action_masks, deterministic=True)
                    action_scalar = int(np.asarray(action).flat[0])
                    obs, _, terminated, truncated, _ = env.step(action_scalar)
                    done = bool(terminated or truncated)

                    gs = env.engine.game_state
                    # Les deux clés sont posées par le reset du moteur (`w40k_core.py:1672`
                    # pour `objective_controllers`) : un défaut ne peut donc masquer qu'une
                    # RÉGRESSION, et il la masque sous une forme parfaitement crédible — `turn`
                    # à 0 saute le relevé du pas, `objective_controllers` vide rend un 0.00 qui
                    # se lit comme « le bot ne tient rien ».
                    cur_turn: int = int(require_key(gs, "turn"))
                    if cur_turn >= 1:
                        controllers: dict = require_key(gs, "objective_controllers")
                        zones = sum(1 for v in controllers.values() if v == bot_player)
                        turn_snapshot[cur_turn] = zones

                        live_enemies = _collect_live_enemies(gs, bot_player)
                        live_bot_pos = _collect_live_bot_positions(gs, bot_player)

                        avg_d = _avg_bot_enemy_distance(gs, bot_player, live_enemies, live_bot_pos)
                        if avg_d is not None:
                            dist_snapshot[cur_turn] = avg_d

                        ft = _count_distinct_focus_targets(gs, bot_player, live_enemies, live_bot_pos)
                        if ft is not None:
                            focus_targets_snapshot[cur_turn] = ft
                        fd = _avg_focus_target_distance(gs, bot, bot_player, live_bot_pos)
                        if fd is not None:
                            focus_dist_snapshot[cur_turn] = fd

                        squad_snapshot[cur_turn] = _count_alive_bot_squads(gs, bot_player)

                bot_records.append(_episode_record(
                    bot_name, ep_idx, ep_seed, bot_player,
                    turn_snapshot, dist_snapshot, squad_snapshot,
                    focus_targets_snapshot, focus_dist_snapshot,
                ))
                print(".", end="", flush=True)

            env.close()
            episode_records.extend(bot_records)
            print(f" {_n_at_last_turn(_turns_of(bot_records))} ep")

        turns = _table_turns(turn_limit, episode_records)
        hdr = " | ".join(f"T{t}" for t in turns)
        sep = "-" * (22 + 4 + 3 + len(turns) * 6 + 4)

        by_bot: Dict[str, List[Dict[str, Any]]] = {}
        for rec in episode_records:
            by_bot.setdefault(rec["bot"], []).append(rec)

        # les trois tableaux sont DÉRIVÉS des mêmes relevés que le JSON : pas de divergence possible.
        print(f"\nZones contrôlées (objectifs)")
        print(f"{'Bot':<22} {'N':>4} | {hdr}")
        print(sep)
        aggregated = _aggregate_zones(episode_records)
        for bot in sorted(bot_weights):
            tdata = aggregated.get(bot, {})
            cells = []
            for t in turns:
                vals = tdata.get(t, [])
                cells.append(f"{sum(vals)/len(vals):.2f}" if vals else "  - ")
            print(f"{bot:<22} {_n_at_last_turn(tdata):>4} | " + " | ".join(f"{c:>4}" for c in cells))

        print(f"\nDistance hex bot → ennemi le plus proche")
        print(f"{'Bot':<22} {'N':>4} | {hdr}")
        print(sep)
        for bot in sorted(bot_weights):
            bot_recs = by_bot.get(bot, [])
            tdata = _turns_of_key(bot_recs, "dist_by_turn")
            cells = []
            for t in turns:
                vals = tdata.get(t, [])
                cells.append(f"{sum(vals)/len(vals):4.1f}" if vals else "   -")
            print(f"{bot:<22} {_n_at_last_turn(tdata):>4} | " + " | ".join(f"{c:>4}" for c in cells))

        print(f"\nTaux escouades bot perdues (∆ depuis T1)")
        print(f"{'Bot':<22} {'N':>4} | {hdr}")
        print(sep)
        for bot in sorted(bot_weights):
            bot_recs = by_bot.get(bot, [])
            tdata = _loss_rate_by_turn(bot_recs)
            cells = []
            for t in turns:
                vals = tdata.get(t, [])
                cells.append(f"{sum(vals)/len(vals):.2f}" if vals else "  - ")
            print(f"{bot:<22} {_n_at_last_turn(tdata):>4} | " + " | ".join(f"{c:>4}" for c in cells))

        print(f"\nCibles ennemies distinctes (convergence)")
        print(f"{'Bot':<22} {'N':>4} | {hdr}")
        print(sep)
        for bot in sorted(bot_weights):
            bot_recs = by_bot.get(bot, [])
            tdata = _turns_of_key(bot_recs, "distinct_targets_by_turn")
            cells = []
            for t in turns:
                vals = tdata.get(t, [])
                cells.append(f"{sum(vals)/len(vals):.2f}" if vals else "  - ")
            print(f"{bot:<22} {_n_at_last_turn(tdata):>4} | " + " | ".join(f"{c:>4}" for c in cells))

        # Seul un bot à cible élue (DecapitationBot) alimente cette clé : les autres n'ont pas
        # d'attribut `_focus_target`, leur ligne reste « — » plutôt que d'afficher un zéro faux.
        print(f"\nDistance à la cible focalisée (DecapitationBot)")
        print(f"{'Bot':<22} {'N':>4} | {hdr}")
        print(sep)
        for bot in sorted(bot_weights):
            bot_recs = by_bot.get(bot, [])
            tdata = _turns_of_key(bot_recs, "focus_dist_by_turn")
            cells = []
            for t in turns:
                vals = tdata.get(t, [])
                cells.append(f"{sum(vals)/len(vals):4.1f}" if vals else "   —")
            print(f"{bot:<22} {_n_at_last_turn(tdata):>4} | " + " | ".join(f"{c:>4}" for c in cells))

        if json_handle is not None:
            run_meta = _run_meta(
                model_fingerprint, scenario_file, args.episodes, len(bot_weights),
                base_seed, agent_seat_mode, agent_seat_seed, bot_randomness,
                {
                    bot: (
                        dict(zip(
                            ("w_objective", "w_enemy", "w_fire", "w_risk", "w_contest", "w_crowd"),
                            load_doctrine_weights(bot),
                        ))
                        if bot in DOCTRINE_BOTS
                        else dict(zip(("w_objective", "w_enemy"), load_movement_weights(bot)))
                    )
                    for bot in bot_weights
                },
                load_hold_bonus(),
                _TRAINING_CONFIG,
                label=args.label,
            )
            _write_json_out(json_handle, run_meta, episode_records)

    # hors du `with` : la ligne ne s'affiche qu'une fois le fichier VRAIMENT publié. Dedans,
    # un flush qui rate la faisait lire juste avant la trace, destination absente ou périmée.
    if args.json_out:
        print(f"\nRelevé par épisode : {args.json_out} ({len(episode_records)} épisodes)")

    print()
    print_panel_reference()


if __name__ == "__main__":
    main()
