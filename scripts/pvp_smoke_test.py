#!/usr/bin/env python3
"""Smoke test fonctionnel du flux PvP via l'API Flask (sans navigateur).

Teste ce que le front AFFICHE mais au niveau de sa source de vérité :
les pools/previews renvoyés par le backend. Le front (BoardPvp/useEngineAPI)
ne fait que dessiner ces données :
  - cercle vert d'activation  = move_activation_pool / shoot_activation_pool / ...
  - preview de move           = valid_move_destinations_pool + mask loops + span
  - preview de tir (cibles)   = valid_target_pool de l'unité activée

Usage :
  python3 scripts/pvp_smoke_test.py --spawn-server --token-from-db
  python3 scripts/pvp_smoke_test.py --base-url http://localhost:5001 --token <TOKEN>
  python3 scripts/pvp_smoke_test.py --base-url http://localhost:5001 --login greg --password <MDP>

Auth (précédence stricte, erreur explicite si rien n'est fourni) :
  1. --token          jeton Bearer déjà valide
  2. --login/--password  via POST /api/auth/login
  3. --token-from-db  réutilise le dernier jeton de session de config/users.db (LECTURE SEULE)

Code retour : 0 si tous les checks passent, 1 sinon, 2 si erreur d'exécution.
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"


# --------------------------------------------------------------------------- #
# Client API
# --------------------------------------------------------------------------- #

class ApiError(RuntimeError):
    """Erreur HTTP/applicative renvoyée par le backend."""

    def __init__(self, message: str, payload: Optional[Dict[str, Any]] = None, status: Optional[int] = None):
        super().__init__(message)
        self.payload = payload or {}
        self.status = status


class ApiClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def _request(self, path: str, payload: Optional[Dict[str, Any]], method: str) -> Dict[str, Any]:
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"},
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            try:
                body = json.load(exc)
            except Exception:
                body = {"error": exc.read().decode(errors="replace")}
            raise ApiError(
                f"{method} {path} -> HTTP {exc.code}: {body.get('error')}",
                payload=body,
                status=exc.code,
            ) from None

    def get(self, path: str) -> Dict[str, Any]:
        return self._request(path, None, "GET")

    def post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request(path, payload, "POST")

    def action(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST /api/game/action ; lève ApiError si success est False."""
        result = self.post("/api/game/action", payload)
        if not result.get("success"):
            raise ApiError(f"action {payload.get('action')} refusée: {result.get('error')}", payload=result)
        return result

    def try_action(self, payload: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Comme action() mais renvoie (succès, réponse) sans lever — pour tester les rejets."""
        try:
            result = self.post("/api/game/action", payload)
        except ApiError as exc:
            return False, exc.payload
        return bool(result.get("success")), result


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #

def resolve_token(args: argparse.Namespace, base_url: str) -> str:
    if args.token:
        return args.token
    if args.login or args.password:
        if not (args.login and args.password):
            raise SystemExit("--login et --password doivent être fournis ensemble.")
        req = urllib.request.Request(
            base_url.rstrip("/") + "/api/auth/login",
            data=json.dumps({"login": args.login, "password": args.password}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.load(resp)
        if not body.get("success"):
            raise SystemExit(f"Login refusé: {body.get('error')}")
        return body["access_token"]
    if args.token_from_db:
        db_path = os.path.join(PROJECT_ROOT, "config", "users.db")
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = connection.execute(
                "SELECT token FROM sessions ORDER BY CAST(created_at AS INTEGER) DESC LIMIT 1"
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise SystemExit("Aucune session dans config/users.db — connecte-toi une fois via le front, ou utilise --login/--password.")
        return row[0]
    raise SystemExit(
        "Aucune authentification fournie. Utilise --token, --login/--password, ou --token-from-db."
    )


# --------------------------------------------------------------------------- #
# Serveur dédié (optionnel)
# --------------------------------------------------------------------------- #

def spawn_server(port: int) -> subprocess.Popen:
    """Lance un serveur Flask SANS reloader Werkzeug (un restart efface la partie en cours)."""
    code = (
        "from services.api_server import app; "
        f"app.run(host='127.0.0.1', port={port}, debug=False, use_reloader=False)"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    atexit.register(proc.terminate)
    deadline = time.time() + 60
    url = f"http://127.0.0.1:{port}/api/health"
    while time.time() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"Le serveur spawné s'est arrêté (code {proc.returncode}).")
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                json.load(resp)
            return proc
        except Exception:
            time.sleep(0.5)
    raise SystemExit("Le serveur spawné ne répond pas sur /api/health après 60s.")


# --------------------------------------------------------------------------- #
# Harnais de checks
# --------------------------------------------------------------------------- #

@dataclass
class CheckResult:
    name: str
    status: str  # PASS | FAIL | SKIP
    details: str = ""


@dataclass
class Harness:
    client: ApiClient
    results: List[CheckResult] = field(default_factory=list)
    game_state: Dict[str, Any] = field(default_factory=dict)

    # -- infra ------------------------------------------------------------- #

    def record(self, name: str, ok: bool, details: str = "") -> bool:
        self.results.append(CheckResult(name, "PASS" if ok else "FAIL", details))
        color = GREEN if ok else RED
        print(f"  {color}{'PASS' if ok else 'FAIL'}{RESET} {name}" + (f" — {details}" if details else ""))
        return ok

    def skip(self, name: str, reason: str) -> None:
        self.results.append(CheckResult(name, "SKIP", reason))
        print(f"  {YELLOW}SKIP{RESET} {name} — {reason}")

    def refresh(self, response: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if response is not None and "game_state" in response:
            self.game_state = response["game_state"]
        else:
            self.game_state = self.client.get("/api/game/state")["game_state"]
        return self.game_state

    # -- accès état -------------------------------------------------------- #

    def unit(self, unit_id: str) -> Dict[str, Any]:
        for candidate in self.game_state["units"]:
            if str(candidate["id"]) == str(unit_id):
                return candidate
        raise KeyError(f"Unité {unit_id} absente de game_state.units")

    def alive_ids(self, player: Optional[int] = None) -> List[str]:
        return [
            str(candidate["id"])
            for candidate in self.game_state["units"]
            if candidate["HP_CUR"] > 0 and (player is None or candidate["player"] == player)
        ]

    def is_single_model(self, unit_id: str) -> bool:
        models = self.game_state["squad_models"].get(str(unit_id))
        if models is None:
            raise KeyError(f"Unité {unit_id} absente de squad_models")
        return len(models) == 1

    def pool(self, name: str) -> List[str]:
        raw = self.game_state.get(name)
        if raw is None:
            raise KeyError(f"Pool '{name}' absent du game_state")
        return [str(uid) for uid in raw]

    # ------------------------------------------------------------------ #
    # Checks
    # ------------------------------------------------------------------ #

    def check_start(self, mode_code: str, board_path: Optional[str]) -> None:
        payload: Dict[str, Any] = {"mode_code": mode_code}
        if board_path:
            payload["board_path"] = board_path
        response = self.client.post("/api/game/start", payload)
        ok = bool(response.get("success"))
        self.record("start.success", ok, response.get("error", ""))
        if not ok:
            raise SystemExit("Impossible de démarrer la partie — arrêt.")
        gs = self.refresh(response)
        self.record(
            "start.phase_initiale_move",
            gs["phase"] == "move",
            f"phase={gs['phase']}, joueur={gs['current_player']}, tour={gs['turn']}",
        )

    def check_state_sanity(self) -> None:
        gs = self.game_state
        units = gs["units"]
        ids = [str(u["id"]) for u in units]
        self.record("sanity.ids_uniques", len(ids) == len(set(ids)), f"{len(ids)} unités")
        # HP par figurine (au niveau unité, HP_CUR est le total d'escouade et HP_MAX le max par figurine).
        bad_hp = [
            model_id
            for model_id, model in gs["models_cache"].items()
            if not (0 <= model["HP_CUR"] <= model["HP_MAX"])
        ]
        self.record("sanity.hp_figurines_bornés", not bad_hp, f"hors bornes: {bad_hp}" if bad_hp else "")
        # Égalité HP unité == somme des figurines : seulement pour les escouades homogènes.
        # Avec un leader attaché (unitType différent dans models_cache), le HP_CUR d'unité
        # ne compte pas le leader — vérifié sur les données, pas asserté ici.
        mismatch = []
        for u in units:
            model_ids = gs["squad_models"][str(u["id"])]
            types = {gs["models_cache"][m]["unitType"] for m in model_ids}
            if len(types) != 1:
                continue
            total = sum(gs["models_cache"][m]["HP_CUR"] for m in model_ids)
            if total != u["HP_CUR"]:
                mismatch.append(f"{u['id']}: unité={u['HP_CUR']} vs figurines={total}")
        self.record("sanity.hp_unité_égal_somme_figurines_(escouades_homogènes)", not mismatch, "; ".join(mismatch))
        cols, rows = gs["board_cols"], gs["board_rows"]
        out = [u["id"] for u in units if u["HP_CUR"] > 0 and not (0 <= u["col"] < cols and 0 <= u["row"] < rows)]
        self.record("sanity.positions_dans_board", not out, f"hors board: {out}" if out else f"board {cols}x{rows}")

    def check_move_pool_composition(self) -> None:
        """Cercle vert (phase move) : le pool = source du front pour eligibleUnitIds."""
        gs = self.game_state
        player = gs["current_player"]
        pool = self.pool("move_activation_pool")
        alive = set(self.alive_ids(player))
        moved = {str(u) for u in gs["units_moved"]} | {str(u) for u in gs["units_fled"]}
        strangers = [uid for uid in pool if uid not in alive]
        self.record(
            "move.pool_que_des_unités_vivantes_du_joueur_actif",
            not strangers,
            f"intrus: {strangers}" if strangers else f"{len(pool)} unités dans le pool",
        )
        already = [uid for uid in pool if uid in moved]
        self.record("move.pool_sans_unités_déjà_déplacées", not already, f"déjà déplacées: {already}" if already else "")
        # Règle 09.02 : chaque unité doit être sélectionnée pour bouger dans la phase
        # (même pour rester stationnaire) → en début de phase, pool = toutes les vivantes.
        missing = sorted(alive - set(pool) - moved)
        self.record(
            "move.pool_complet_début_de_phase",
            not missing,
            f"vivantes hors pool: {missing}" if missing else "",
        )

    def check_enemy_activation_rejected(self) -> None:
        gs = self.game_state
        enemy_player = 2 if gs["current_player"] == 1 else 1
        enemies = self.alive_ids(enemy_player)
        if not enemies:
            self.skip("move.activation_ennemie_rejetée", "aucun ennemi vivant")
            return
        ok, response = self.client.try_action({"action": "activate_unit", "unitId": enemies[0]})
        self.record(
            "move.activation_ennemie_rejetée",
            not ok,
            "" if not ok else f"ACCEPTÉE À TORT: {json.dumps(response.get('result'))[:120]}",
        )
        self.refresh()

    def check_activation_and_move_preview(self, unit_id: str) -> None:
        """Activer une unité en phase move doit produire le preview (destinations + masque)."""
        response = self.client.action({"action": "activate_unit", "unitId": unit_id})
        gs = self.refresh(response)
        self.record(
            "move.activation_ok",
            str(gs.get("active_movement_unit")) == str(unit_id),
            f"unité {unit_id} ({self.unit(unit_id)['unitType']})",
        )
        destinations = gs.get("valid_move_destinations_pool") or []
        self.record("move.preview_destinations_non_vide", len(destinations) > 0, f"{len(destinations)} hexes")
        loops = gs.get("move_preview_footprint_mask_loops")
        self.record(
            "move.preview_masque_présent",
            isinstance(loops, list) and len(loops) > 0,
            f"{len(loops) if isinstance(loops, list) else loops} loop(s), span={gs.get('move_preview_footprint_span')}",
        )
        cols, rows = gs["board_cols"], gs["board_rows"]
        out = [d for d in destinations if not (0 <= d[0] < cols and 0 <= d[1] < rows)]
        self.record("move.preview_destinations_dans_board", not out, f"hors board: {out[:5]}" if out else "")

    def check_move_commit(self, unit_id: str) -> None:
        gs = self.game_state
        destinations = gs.get("valid_move_destinations_pool") or []
        if not destinations:
            self.skip("move.commit", "pas de destination disponible")
            return
        dest = destinations[0]
        response = self.client.action(
            {"action": "move", "unitId": unit_id, "destCol": dest[0], "destRow": dest[1]}
        )
        gs = self.refresh(response)
        moved_unit = self.unit(unit_id)
        self.record(
            "move.commit_position_mise_à_jour",
            [moved_unit["col"], moved_unit["row"]] == [dest[0], dest[1]],
            f"attendu {dest}, obtenu [{moved_unit['col']}, {moved_unit['row']}]",
        )
        self.record("move.commit_sorti_du_pool", unit_id not in self.pool("move_activation_pool"))
        tracked = {str(u) for u in gs["units_moved"]} | {str(u) for u in gs["units_fled"]}
        self.record("move.commit_tracé_units_moved_ou_fled", unit_id in tracked)
        self.record(
            "move.commit_preview_nettoyé",
            not (gs.get("valid_move_destinations_pool") or []) and gs.get("active_movement_unit") is None,
            f"active={gs.get('active_movement_unit')}",
        )
        ok, response = self.client.try_action({"action": "activate_unit", "unitId": unit_id})
        self.record(
            "move.réactivation_unité_déjà_déplacée_rejetée",
            not ok,
            "" if not ok else "ACCEPTÉE À TORT",
        )
        self.refresh()

    def check_skip_and_drain_move_phase(self) -> None:
        """Skip toutes les unités restantes ; la phase doit finir par basculer."""
        first_skip_checked = False
        for _ in range(200):
            gs = self.game_state
            if gs["phase"] != "move" or not self.pool("move_activation_pool"):
                break
            uid = self.pool("move_activation_pool")[0]
            response = self.client.action({"action": "skip", "unitId": uid})
            gs = self.refresh(response)
            if not first_skip_checked:
                first_skip_checked = True
                self.record(
                    "move.skip_sort_du_pool",
                    uid not in self.pool("move_activation_pool") or gs["phase"] != "move",
                    f"unité {uid}",
                )
        else:
            self.record("move.drain_termine", False, "200 itérations sans vider le pool")
            return
        gs = self.refresh()
        if gs["phase"] == "move":
            # Miroir du front : quand le pool est vide, il envoie advance_phase.
            response = self.client.action({"action": "advance_phase"})
            result = response.get("result") or {}
            gs = self.refresh(response)
            self.record(
                "move.advance_phase_confirme_pool_vide",
                bool(result.get("phase_complete")) and result.get("reason") == "pool_empty",
                json.dumps(result)[:120],
            )
        self.record(
            "move.transition_vers_shoot",
            gs["phase"] == "shoot",
            f"phase={gs['phase']}",
        )

    def check_shoot_pool_composition(self, fled_ids: List[str]) -> None:
        gs = self.game_state
        if gs["phase"] != "shoot":
            self.skip("shoot.pool", f"phase={gs['phase']} (attendu shoot)")
            return
        player = gs["current_player"]
        pool = self.pool("shoot_activation_pool")
        alive = set(self.alive_ids(player))
        strangers = [uid for uid in pool if uid not in alive]
        self.record(
            "shoot.pool_que_des_unités_vivantes_du_joueur_actif",
            not strangers,
            f"intrus: {strangers}" if strangers else f"{len(pool)} unités",
        )
        # Règle 09.07 : une unité qui a fait un fall-back ne peut pas tirer ce tour.
        offenders = [uid for uid in pool if uid in set(fled_ids)]
        self.record(
            "shoot.pool_exclut_les_unités_ayant_fui (09.07)",
            not offenders,
            f"fuyardes dans le pool: {offenders}" if offenders else f"fuyardes: {fled_ids or 'aucune'}",
        )

    def check_shoot_preview(self) -> None:
        gs = self.game_state
        if gs["phase"] != "shoot":
            self.skip("shoot.preview_cibles", f"phase={gs['phase']}")
            return
        pool = self.pool("shoot_activation_pool")
        if not pool:
            self.skip("shoot.preview_cibles", "pool de tir vide")
            return
        uid = pool[0]
        # Chemin escouade obligatoire en phase shoot (le moteur rejette activate_unit ici).
        ok, response = self.client.try_action({"action": "squad_shoot_activate", "unitId": uid})
        if not ok:
            self.record("shoot.activation_ok", False, f"unité {uid}: {response.get('error')}")
            return
        gs = self.refresh(response)
        # Miroir du front : le surlignage des cibles vient de squad_shoot_los_overview
        # (result.valid_targets + cover/count par cible).
        overview_response = self.client.action({"action": "squad_shoot_los_overview", "unitId": uid})
        overview = overview_response.get("result") or {}
        targets = overview.get("valid_targets")
        self.record(
            "shoot.los_overview_expose_les_cibles",
            isinstance(targets, list),
            f"unité {uid}: {len(targets) if isinstance(targets, list) else 'valid_targets absent'} cible(s)",
        )
        if isinstance(targets, list) and targets:
            enemy_player = 2 if gs["current_player"] == 1 else 1
            enemy_alive = set(self.alive_ids(enemy_player))
            bad = [t for t in targets if str(t) not in enemy_alive]
            self.record(
                "shoot.cibles_toutes_ennemies_et_vivantes",
                not bad,
                f"cibles invalides: {bad[:3]}" if bad else f"{len(targets)} cible(s) valides",
            )
        ok, response = self.client.try_action({"action": "squad_shoot_cancel", "unitId": uid})
        self.record("shoot.annulation_activation_ok", ok, "" if ok else str(response.get("error"))[:120])
        if ok:
            self.refresh(response)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:5011")
    parser.add_argument("--spawn-server", action="store_true",
                        help="Lancer un serveur dédié (sans reloader) sur le port de --base-url")
    parser.add_argument("--mode", default="pvp_test", choices=["pvp_test", "pvp"])
    parser.add_argument("--board", default=None, help="board_path (x1/x5/x10/x5_44x60) — pvp_test uniquement")
    parser.add_argument("--token")
    parser.add_argument("--login")
    parser.add_argument("--password")
    parser.add_argument("--token-from-db", action="store_true")
    args = parser.parse_args()

    if args.spawn_server:
        port = int(args.base_url.rsplit(":", 1)[1])
        print(f"Lancement d'un serveur dédié sur le port {port} (use_reloader=False)...")
        spawn_server(port)

    token = resolve_token(args, args.base_url)
    client = ApiClient(args.base_url, token)
    try:
        client.get("/api/health")
    except Exception as exc:
        raise SystemExit(
            f"Backend injoignable sur {args.base_url} ({exc}). Lance-le, ou utilise --spawn-server."
        )

    harness = Harness(client)

    print(f"\n=== Démarrage partie ({args.mode}) ===")
    harness.check_start(args.mode, args.board)

    print("\n=== Cohérence du state ===")
    harness.check_state_sanity()

    print("\n=== Phase MOVE : cercle vert (pool d'activation) ===")
    harness.check_move_pool_composition()
    harness.check_enemy_activation_rejected()

    print("\n=== Phase MOVE : preview + commit ===")
    pool = harness.pool("move_activation_pool")
    single = next((uid for uid in pool if harness.is_single_model(uid)), None)
    if single is None:
        harness.skip("move.activation", "aucune unité mono-figurine dans le pool")
    else:
        harness.check_activation_and_move_preview(single)
        harness.check_move_commit(single)

    print("\n=== Phase MOVE : skip + transition ===")
    harness.check_skip_and_drain_move_phase()
    fled_ids = [str(u) for u in harness.game_state["units_fled"]]

    print("\n=== Phase SHOOT : cercle vert + cibles ===")
    harness.check_shoot_pool_composition(fled_ids)
    harness.check_shoot_preview()

    failed = [r for r in harness.results if r.status == "FAIL"]
    skipped = [r for r in harness.results if r.status == "SKIP"]
    passed = [r for r in harness.results if r.status == "PASS"]
    print(f"\n=== Bilan : {len(passed)} PASS, {len(failed)} FAIL, {len(skipped)} SKIP ===")
    for r in failed:
        print(f"  {RED}FAIL{RESET} {r.name} — {r.details}")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ApiError as exc:
        print(f"{RED}ERREUR API{RESET}: {exc}", file=sys.stderr)
        sys.exit(2)
