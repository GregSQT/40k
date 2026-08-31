"""Point d'entrée de PRODUCTION du backend (F9).

`services/api_server.py` garde son bloc `__main__` : c'est le lancement de DÉVELOPPEMENT, sur
le serveur Werkzeug, en `127.0.0.1`. Werkzeug se documente lui-même comme impropre à la
production (robustesse, gestion des connexions lentes, absence de limites de requête), et
`debug=False` n'y change rien — la faille F9 ne portait pas sur le debugger, résolu depuis
(F1), mais sur le serveur lui-même.

**Pourquoi waitress et pas gunicorn.** Ce n'est pas une préférence de goût. Le moteur de jeu
est une GLOBALE DE PROCESS (`api_server.engine`, protégée par `_ENGINE_STATE_LOCK`, un `RLock`
de threads). Gunicorn en mode par défaut lance N *processus* : chaque worker aurait sa propre
partie, et deux requêtes consécutives du même joueur tomberaient sur deux états de jeu
différents — le jeu serait cassé, pas ralenti. Waitress sert en THREADS dans un processus
unique : exactement la sémantique que le serveur de développement offrait déjà, donc aucun
invariant du moteur ne bouge. Le jour où le moteur cessera d'être une globale, gunicorn
redeviendra un choix ouvert.

**Écoute sur 0.0.0.0.** Uniquement ici, et uniquement pour l'intérieur du conteneur (F15) :
`app.run(host='127.0.0.1')` dans un conteneur n'écoute que sur le loopback DU CONTENEUR, donc
ni le reverse proxy ni un mapping de port ne l'atteignent. L'exposition réelle est fermée
ailleurs — `docker-compose.yml` ne publie plus le port du backend, seul nginx est publié.
Le `127.0.0.1` du bloc `__main__` doit RESTER tel quel : c'est lui qui garantit qu'un
lancement direct sur le poste de développement n'expose rien sur le réseau local.
"""

from __future__ import annotations

import os
import sys

# Le conteneur lance `python -m services.wsgi` depuis `/app`, mais un lancement direct
# (`python services/wsgi.py`) placerait `services/` en tête du chemin d'import et rendrait
# `engine`, `shared` et `config` introuvables. La racine du dépôt est donc posée explicitement.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from services.api_server import app, initialize_engine  # noqa: E402

# Objet WSGI exposé, pour un serveur qui prendrait `services.wsgi:application` en cible.
application = app

# Port d'écoute INTERNE au conteneur. Le reverse proxy est le seul à s'y connecter.
DEFAULT_PORT = 5001

# Threads de service. Waitress les alloue une fois pour toutes ; le moteur étant sérialisé par
# `_ENGINE_STATE_LOCK`, en ajouter n'accélère pas une partie — cela évite qu'une requête longue
# (chargement de plateau, tour d'IA) bloque les lectures courtes du même joueur.
DEFAULT_THREADS = 8


def _resolve_positive_int(variable: str, default: int) -> int:
    """Entier > 0 lu dans l'environnement, ou le défaut si la variable n'est pas définie.

    Une valeur illisible ou nulle est refusée bruyamment : la corriger en silence par le défaut
    ferait démarrer le serveur avec une configuration que personne n'a demandée, et le port est
    exactement le réglage dont une erreur muette rend la panne incompréhensible.
    """
    raw = os.environ.get(variable)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        raise SystemExit(f"{variable} : {raw!r} n'est pas un entier")
    if value <= 0:
        raise SystemExit(f"{variable} : {value} doit être strictement positif")
    return value


def _resolve_waitress_trusted_proxy() -> str | None:
    """IP du proxy nginx de confiance pour waitress, lue depuis W40K_TRUSTED_PROXIES.

    Waitress 3.0+ filtre X-Forwarded-For et X-Forwarded-Proto par défaut (comportement
    sécurisé : un client ne peut pas forger REMOTE_ADDR). Sans cette configuration,
    Flask ne voit jamais ces headers et _client_ip() lève RuntimeError au premier login.
    Si W40K_TRUSTED_PROXIES n'est pas définie (mode développement direct sans nginx),
    aucune configuration trusted_proxy n'est posée et waitress laisse REMOTE_ADDR intact.
    Une seule adresse est attendue (nginx) ; si plusieurs sont configurées, la première est prise.
    """
    raw = os.environ.get("W40K_TRUSTED_PROXIES", "").strip()
    if not raw:
        return None
    first = raw.split(",")[0].strip()
    if not first:
        raise SystemExit(f"W40K_TRUSTED_PROXIES : {raw!r} — premier élément vide (virgule initiale ?)")
    return first


def main() -> None:
    from waitress import serve  # pyright: ignore[reportMissingModuleSource]  # dép. runtime uniquement (requirements.runtime.txt), absente du venv dev

    port = _resolve_positive_int("W40K_PORT", DEFAULT_PORT)
    threads = _resolve_positive_int("W40K_WSGI_THREADS", DEFAULT_THREADS)
    trusted_proxy = _resolve_waitress_trusted_proxy()

    # Même séquence qu'en développement : le moteur est monté au démarrage, pas à la première
    # requête. Un échec n'arrête pas le serveur — `/api/health` doit pouvoir répondre pour que
    # le healthcheck du conteneur distingue « moteur en panne » de « conteneur mort ».
    if initialize_engine():
        print("⚡ W40K engine initialized")
    else:
        print("⚠️  Engine initialization failed - will retry on first request")

    print(f"🚀 W40K API (waitress) on 0.0.0.0:{port} — {threads} threads")
    serve(
        app,
        host="0.0.0.0",
        port=port,
        threads=threads,
        # Waitress annonce sinon sa version dans l'en-tête `Server` de chaque réponse, ce qui
        # renseigne gratuitement un attaquant sur la pile à cibler.
        ident=None,
        # Expose X-Forwarded-For (→ REMOTE_ADDR) et X-Forwarded-Proto (→ wsgi.url_scheme)
        # posés par nginx. Sans cela, Flask voit REMOTE_ADDR = IP nginx et ne peut pas
        # déduire l'IP client ni si la connexion est HTTPS — _client_ip() lève et le cookie
        # Secure n'est pas posé.
        trusted_proxy=trusted_proxy,
        trusted_proxy_count=1,
        trusted_proxy_headers={"x-forwarded-for", "x-forwarded-proto"},
    )


if __name__ == "__main__":
    main()
