"""Socle d'authentification SANS effet de bord à l'import : chemin de la base, hachage des
mots de passe, noms des événements du journal.

Motif de l'extraction. `services/api_server.py` appelle `initialize_auth_db()` AU NIVEAU
MODULE : l'importer suffit à écrire dans `config/users.db` — et à la CRÉER si elle n'existe
pas. C'est acceptable pour le serveur, dont c'est le travail, mais pas pour un outil de
lecture : `scripts/auth_journal.py` audite cette base, et un auditeur qui fabrique la base
qu'il est censé inspecter rend « aucun compte » indiscernable de « fichier absent ».

L'alternative — recopier le chemin et l'algorithme de hachage dans le script — a été écartée :
un doublon reste vert quand la production change de chemin ou d'algorithme, donc il rassure
exactement au moment où il devient faux. Ce module est la source UNIQUE des deux, et
`api_server` les prend ici.
"""

from __future__ import annotations

import hashlib
import os
import secrets

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Base d'authentification. La surcharge par variable d'environnement permet aux tests de viser
# une base jetable, `config/users.db` étant un fichier protégé (cf. CLAUDE.md). Aucune valeur
# de repli en production : sans la variable, c'est bien la base réelle qui est utilisée.
AUTH_DB_PATH = os.environ.get(
    "W40K_AUTH_DB_PATH", os.path.join(_REPO_ROOT, "config", "users.db")
)

PBKDF2_ITERATIONS = 200000


def hash_password(password: str) -> str:
    """Hache un mot de passe en PBKDF2-HMAC-SHA256, sel aléatoire de 16 octets.

    Le nombre d'itérations est stocké DANS le hash : le relever un jour n'invalidera pas les
    mots de passe existants, qui continueront d'être vérifiés avec le leur.
    """
    if not isinstance(password, str) or not password:
        raise ValueError("password is required and must be a non-empty string")
    salt = secrets.token_bytes(16)
    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${derived_key.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Vérifie un mot de passe candidat contre un hash stocké.

    La comparaison passe par `secrets.compare_digest` : un `==` sur les octets s'arrête au
    premier écart, et la durée de la comparaison renseignerait alors sur le nombre d'octets
    devinés.

    Un hash illisible LÈVE au lieu de rendre False : ce n'est pas « mauvais mot de passe »,
    c'est une base corrompue, et le confondre avec un refus laisserait un compte inaccessible
    sans que rien ne le signale.
    """
    if not isinstance(password, str) or not password:
        return False
    if not isinstance(stored_hash, str) or not stored_hash:
        raise ValueError("stored_hash must be a non-empty string")

    parts = stored_hash.split("$")
    if len(parts) != 4:
        raise ValueError("Invalid password hash format in database")
    algorithm, iterations_str, salt_hex, hash_hex = parts
    if algorithm != "pbkdf2_sha256":
        raise ValueError(f"Unsupported password hash algorithm: {algorithm}")
    iterations = int(iterations_str)
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(hash_hex)
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return secrets.compare_digest(candidate, expected)


# --- Noms des événements du journal `auth_events` --------------------------------------------
# La TENTATIVE est distincte de son ISSUE. C'est elle qui porte le rate limiting : inscrite
# avant la vérification du mot de passe, elle partage la transaction du comptage et le rend
# atomique. L'issue (`login_success` / `login_failure`) est écrite après, et c'est elle que lit
# l'audit — sans cette séparation, chaque connexion réussie laisserait dans le journal un échec
# provisoire qui n'a jamais eu lieu.
AUTH_EVENT_LOGIN_ATTEMPT = "login_attempt"
AUTH_EVENT_LOGIN_SUCCESS = "login_success"
AUTH_EVENT_LOGIN_FAILURE = "login_failure"
AUTH_EVENT_RATE_LIMITED = "rate_limited"
AUTH_EVENT_LOGOUT = "logout"
