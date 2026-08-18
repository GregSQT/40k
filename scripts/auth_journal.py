#!/usr/bin/env python3
"""Lecture du journal d'authentification et audit des comptes (étapes 7 et 8 de Security.md).

L'étape 3 a posé la table `auth_events` (append-only : tentatives, succès, échecs, refus de
rate limiting, déconnexions, avec l'IP réelle du client). Il y manquait l'essentiel : quelqu'un
pour la lire. Une table que personne ne consulte ne détecte rien — elle documente après coup une
intrusion qu'on n'a pas vue passer.

Ce script est en LECTURE SEULE. Il n'ouvre la base qu'en mode `ro` (URI SQLite) : une faute de
frappe dans une commande d'audit ne peut pas modifier `config/users.db`, qui est par ailleurs un
fichier protégé du dépôt.

Sous-commandes :
  events    derniers événements, avec filtres (--event, --login, --ip, --since)
  suspects  agrégats qui méritent un regard : refus de rate limiting, IP à échecs répétés,
            logins inconnus visés depuis une même IP
  sessions  sessions actuellement valides (qui est connecté, depuis quand, jusqu'à quand)
  accounts  comptes existants et détection des mots de passe triviaux (étape 8)

Exemples :
  python3 scripts/auth_journal.py suspects --since 7d
  python3 scripts/auth_journal.py events --event login_failure --since 24h
  python3 scripts/auth_journal.py accounts
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
import time
from typing import List, Optional, Tuple

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Chemin de la base, vérificateur de mot de passe et noms d'événements viennent du code de
# PRODUCTION, jamais recopiés : une base déplacée par `W40K_AUTH_DB_PATH` ou un changement
# d'algorithme rendrait un doublon local silencieusement faux, donc rassurant à tort.
#
# L'import passe par `shared.auth_credentials` et NON par `services.api_server` : ce dernier
# appelle `initialize_auth_db()` au niveau module, donc l'importer écrirait dans
# `config/users.db` — et la créerait si elle manquait. Un auditeur qui fabrique la base qu'il
# audite rendrait « aucun compte » indiscernable de « fichier absent ».
from shared.auth_credentials import (  # noqa: E402
    AUTH_DB_PATH,
    AUTH_EVENT_LOGIN_FAILURE,
    AUTH_EVENT_LOGIN_SUCCESS,
    AUTH_EVENT_RATE_LIMITED,
    verify_password,
)

# Mots de passe testés par `accounts`. La liste vise le cas nommé par l'étape 8 — « pas de
# comptes de test type admin/admin » — et non une attaque par dictionnaire : ce sont les
# valeurs qu'on se donne à soi-même en montant un environnement, puis qu'on oublie.
_TRIVIAL_PASSWORDS = (
    "admin", "password", "motdepasse", "123456", "12345678", "azerty", "qwerty",
    "test", "test123", "changeme", "root", "user", "demo", "w40k", "40k",
)

_DURATION_PATTERN = re.compile(r"^(\d+)([smhdw])$")
_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(raw: str) -> int:
    """`30m`, `24h`, `7d`, `2w` -> secondes.

    Refuse tout le reste plutôt que de retomber sur une valeur par défaut : un `--since 7`
    interprété comme sept secondes rendrait un rapport vide et laisserait croire qu'il ne s'est
    rien passé, ce qui est le pire résultat possible pour un outil d'audit.
    """
    match = _DURATION_PATTERN.match(raw.strip())
    if match is None:
        raise argparse.ArgumentTypeError(
            f"{raw!r} : durée attendue sous la forme <nombre><unité>, unités s/m/h/d/w "
            f"(exemples : 30m, 24h, 7d)"
        )
    return int(match.group(1)) * _DURATION_UNITS[match.group(2)]


def open_readonly(db_path: str) -> sqlite3.Connection:
    """Connexion STRICTEMENT en lecture. `mode=ro` fait échouer toute écriture au niveau SQLite.

    `immutable` n'est PAS utilisé : le serveur écrit dans cette base pendant qu'on la lit, et
    `immutable=1` autoriserait SQLite à ignorer le journal WAL, donc à rendre un instantané
    périmé — un audit qui ne voit pas les dernières tentatives ne sert à rien.
    """
    if not os.path.exists(db_path):
        raise SystemExit(f"Base d'authentification introuvable : {db_path}")
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def format_time(epoch: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch))


def print_table(headers: List[str], rows: List[Tuple], empty_message: str) -> None:
    if not rows:
        print(f"  {empty_message}")
        return
    widths = [len(header) for header in headers]
    text_rows = [[str(cell) for cell in row] for row in rows]
    for row in text_rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    print("  " + "  ".join(header.ljust(widths[i]) for i, header in enumerate(headers)))
    print("  " + "  ".join("-" * width for width in widths))
    for row in text_rows:
        print("  " + "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))


def command_events(connection: sqlite3.Connection, args: argparse.Namespace) -> int:
    # Requête STATIQUE, filtres optionnels exprimés en `? IS NULL OR colonne = ?`. Assembler la
    # clause `WHERE` par concaténation aurait aussi été sûr (les valeurs restent paramétrées,
    # seuls des littéraux sont concaténés), mais la sûreté ne se lirait que dans le voisinage du
    # code — et bandit la signale en MEDIUM, ce qui use le portail de `scripts/security_check.sh`
    # à force de findings qu'on apprend à ignorer. Ici il n'y a plus rien à justifier.
    rows = connection.execute(
        """
        SELECT occurred_at, event, login, ip, details FROM auth_events
        WHERE occurred_at > ?
          AND (? IS NULL OR event = ?)
          AND (? IS NULL OR login = ?)
          AND (? IS NULL OR ip = ?)
        ORDER BY id DESC LIMIT ?
        """,
        (
            int(time.time()) - args.since,
            args.event, args.event,
            args.login, args.login,
            args.ip, args.ip,
            args.limit,
        ),
    ).fetchall()

    print(f"\n=== Événements ({len(rows)} affichés, plus récents d'abord) ===")
    print_table(
        ["QUAND", "ÉVÉNEMENT", "LOGIN", "IP", "DÉTAILS"],
        [
            (format_time(r["occurred_at"]), r["event"], r["login"], r["ip"], r["details"] or "")
            for r in rows
        ],
        "aucun événement sur la fenêtre demandée",
    )
    return 0


def command_suspects(connection: sqlite3.Connection, args: argparse.Namespace) -> int:
    """Ce qu'il faut regarder en premier, plutôt que le journal brut.

    Le code de sortie vaut 1 dès qu'un refus de rate limiting apparaît : c'est le seul
    événement du journal qui ne peut pas résulter d'un utilisateur maladroit — cinq tentatives
    en soixante secondes sur le même couple (login, IP) est un comportement de script. Il rend
    la commande utilisable dans une surveillance périodique, pas seulement à la main.
    """
    window_start = int(time.time()) - args.since
    exit_code = 0

    rate_limited = connection.execute(
        "SELECT login, ip, COUNT(*) AS hits, MAX(occurred_at) AS last_seen FROM auth_events "
        "WHERE event = ? AND occurred_at > ? GROUP BY login, ip ORDER BY hits DESC",
        (AUTH_EVENT_RATE_LIMITED, window_start),
    ).fetchall()

    print(f"\n=== Refus de rate limiting (fenêtre : {args.since_label}) ===")
    print_table(
        ["LOGIN", "IP", "FENÊTRES", "DERNIER"],
        [(r["login"], r["ip"], r["hits"], format_time(r["last_seen"])) for r in rate_limited],
        "aucun — personne n'a atteint le plafond de tentatives",
    )
    if rate_limited:
        exit_code = 1

    failures = connection.execute(
        "SELECT ip, COUNT(*) AS failures, COUNT(DISTINCT login) AS logins, "
        "       MAX(occurred_at) AS last_seen FROM auth_events "
        "WHERE event = ? AND occurred_at > ? GROUP BY ip "
        "HAVING failures >= ? ORDER BY failures DESC",
        (AUTH_EVENT_LOGIN_FAILURE, window_start, args.min_failures),
    ).fetchall()

    print(f"\n=== IP à échecs répétés (>= {args.min_failures}) ===")
    print_table(
        ["IP", "ÉCHECS", "LOGINS VISÉS", "DERNIER"],
        [
            (r["ip"], r["failures"], r["logins"], format_time(r["last_seen"]))
            for r in failures
        ],
        "aucune",
    )
    # Plusieurs LOGINS DIFFÉRENTS visés depuis une même IP est le signe distinctif d'un
    # balayage de comptes : un utilisateur qui se trompe se trompe sur son propre login.
    for row in failures:
        if row["logins"] > 1:
            print(
                f"  ⚠️  {row['ip']} a échoué sur {row['logins']} logins distincts "
                f"— balayage de comptes probable"
            )
            exit_code = 1

    successes = connection.execute(
        "SELECT login, ip, COUNT(*) AS logins, MAX(occurred_at) AS last_seen FROM auth_events "
        "WHERE event = ? AND occurred_at > ? GROUP BY login, ip ORDER BY last_seen DESC",
        (AUTH_EVENT_LOGIN_SUCCESS, window_start),
    ).fetchall()

    print("\n=== Connexions réussies, par (login, IP) ===")
    print_table(
        ["LOGIN", "IP", "CONNEXIONS", "DERNIÈRE"],
        [(r["login"], r["ip"], r["logins"], format_time(r["last_seen"])) for r in successes],
        "aucune",
    )
    # Un même compte utilisé depuis plusieurs IP n'est pas anormal en soi (mobile, VPN,
    # domicile/bureau) : signalé pour lecture humaine, il ne fait pas basculer le code de sortie.
    by_login: dict[str, set] = {}
    for row in successes:
        by_login.setdefault(row["login"], set()).add(row["ip"])
    for login, ips in by_login.items():
        if len(ips) > 1:
            print(f"  ℹ️  {login} s'est connecté depuis {len(ips)} IP distinctes : {', '.join(sorted(ips))}")

    return exit_code


def command_sessions(connection: sqlite3.Connection, args: argparse.Namespace) -> int:
    """Sessions VALIDES à cet instant. Le token n'est jamais affiché — le journaliser dans un
    terminal, un fichier de log ou un ticket le rendrait réutilisable par qui le lit."""
    now = int(time.time())
    rows = connection.execute(
        "SELECT u.login AS login, p.code AS profile, s.created_at, s.expires_at "
        "FROM sessions s JOIN users u ON u.id = s.user_id JOIN profiles p ON p.id = u.profile_id "
        "WHERE s.expires_at > ? ORDER BY s.created_at DESC",
        (now,),
    ).fetchall()

    print(f"\n=== Sessions valides ({len(rows)}) ===")
    print_table(
        ["LOGIN", "PROFIL", "OUVERTE LE", "EXPIRE LE"],
        [
            (r["login"], r["profile"], format_time(r["created_at"]), format_time(r["expires_at"]))
            for r in rows
        ],
        "aucune session ouverte",
    )

    expired = connection.execute(
        "SELECT COUNT(*) AS total FROM sessions WHERE expires_at <= ?", (now,)
    ).fetchone()["total"]
    if expired:
        print(f"\n  ({expired} session(s) échue(s) en attente de purge au prochain login réussi)")
    return 0


def command_accounts(connection: sqlite3.Connection, args: argparse.Namespace) -> int:
    """Inventaire des comptes + détection des mots de passe triviaux (étape 8).

    Les mots de passe sont hachés (PBKDF2, 200 000 itérations) : on ne peut pas les LIRE, on ne
    peut que tester des candidats. C'est exactement ce que demande l'étape 8 — repérer les
    `admin/admin` laissés par un montage d'environnement — et non retrouver un mot de passe fort.

    Le code de sortie vaut 1 si un compte est trouvé trivial : ce compte est une porte ouverte,
    et l'audit doit échouer bruyamment plutôt que l'écrire au milieu d'un tableau.
    """
    rows = connection.execute(
        "SELECT u.id, u.login, u.password_hash, p.code AS profile "
        "FROM users u JOIN profiles p ON p.id = u.profile_id ORDER BY u.login"
    ).fetchall()

    last_login = {
        r["login"]: r["last_seen"]
        for r in connection.execute(
            "SELECT login, MAX(occurred_at) AS last_seen FROM auth_events "
            "WHERE event = ? GROUP BY login",
            (AUTH_EVENT_LOGIN_SUCCESS,),
        ).fetchall()
    }

    weak: List[Tuple[str, str]] = []
    table_rows = []
    for row in rows:
        trivial = next(
            (candidate for candidate in _TRIVIAL_PASSWORDS
             if verify_password(candidate, row["password_hash"])),
            None,
        )
        # Le login lui-même comme mot de passe (`admin`/`admin`) est le cas nommé par l'étape 8 ;
        # il n'est pas forcément dans la liste ci-dessus, d'où ce test supplémentaire.
        if trivial is None and verify_password(row["login"], row["password_hash"]):
            trivial = row["login"]
        if trivial is not None:
            weak.append((row["login"], trivial))
        seen = last_login.get(row["login"])
        table_rows.append((
            row["login"],
            row["profile"],
            format_time(seen) if seen else "jamais (dans la rétention)",
            "TRIVIAL" if trivial else "ok",
        ))

    print(f"\n=== Comptes ({len(rows)}) ===")
    print_table(
        ["LOGIN", "PROFIL", "DERNIÈRE CONNEXION", "MOT DE PASSE"],
        table_rows,
        "aucun compte",
    )
    print(f"\n  ({len(_TRIVIAL_PASSWORDS)} mots de passe triviaux testés, plus le login lui-même)")

    if weak:
        print("\n🔴 Comptes à mot de passe trivial — à changer AVANT toute exposition :")
        for login, password in weak:
            print(f"     {login} : {password!r}")
        return 1
    print("\n🟢 Aucun mot de passe trivial détecté.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Lecture du journal d'authentification (lecture seule).",
    )
    parser.add_argument(
        "--db", default=AUTH_DB_PATH,
        help="Chemin de la base d'authentification (défaut : celui du serveur).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    events = subparsers.add_parser("events", help="Derniers événements du journal.")
    events.add_argument("--since", default="24h", help="Fenêtre (30m, 24h, 7d…). Défaut : 24h.")
    events.add_argument("--event", help="Filtre sur le type d'événement.")
    events.add_argument("--login", help="Filtre sur le login visé.")
    events.add_argument("--ip", help="Filtre sur l'IP source.")
    events.add_argument("--limit", type=int, default=100, help="Nombre de lignes. Défaut : 100.")
    events.set_defaults(handler=command_events)

    suspects = subparsers.add_parser("suspects", help="Agrégats à regarder en priorité.")
    suspects.add_argument("--since", default="7d", help="Fenêtre. Défaut : 7d.")
    suspects.add_argument(
        "--min-failures", type=int, default=5,
        help="Seuil d'échecs pour lister une IP. Défaut : 5.",
    )
    suspects.set_defaults(handler=command_suspects)

    sessions = subparsers.add_parser("sessions", help="Sessions actuellement valides.")
    sessions.set_defaults(handler=command_sessions)

    accounts = subparsers.add_parser("accounts", help="Comptes et mots de passe triviaux.")
    accounts.set_defaults(handler=command_accounts)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    raw_since = getattr(args, "since", None)
    if raw_since is not None:
        args.since_label = raw_since
        args.since = parse_duration(raw_since)

    connection = open_readonly(args.db)
    try:
        print(f"Base : {args.db}")
        return args.handler(connection, args)
    finally:
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
