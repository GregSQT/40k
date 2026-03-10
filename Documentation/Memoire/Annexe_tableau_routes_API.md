# Annexe – Tableau des routes API (Trazyn's Trials)

| Méthode | URL | Paramètres / corps | Codes retour | Remarques |
|---------|-----|--------------------|--------------|-----------|
| GET | /api/health | — | 200 | Healthcheck (Docker, monitoring). |
| POST | /api/auth/register | Body: `{ "login", "password" }` | 201, 400, 409 | Création de compte (profil base). |
| POST | /api/auth/login | Body: `{ "login", "password" }` | 200, 400, 401 | Retourne `access_token`, `user`, `permissions`. |
| GET | /api/auth/me | Header: `Authorization: Bearer <token>` | 200, 401 | Session courante et permissions. |
| POST | /api/game/start | Header: Bearer. Body: `{ "pve_mode"?, "mode_code"?, "scenario_file"? }` | 200, 400, 401, 403, 500 | Démarre une partie (mode selon droits). |
| POST | /api/game/action | Header: Bearer. Body: action sémantique (ex. move, shoot, wait) | 200, 400, 401, 403, 500 | Exécute une action joueur. |
| GET | /api/game/state | Header: Bearer | 200, 400, 401 | État courant de la partie. |
| POST | /api/game/reset | Header: Bearer | 200, 400, 401 | Réinitialise la partie. |
| POST | /api/game/ai-turn | Header: Bearer | 200, 400, 401, 403, 500 | Déclenche le tour de l’IA (PvE). |
| GET | /api/armies | — | 200 | Liste des armées (config). |
| GET | /api/config/board | — | 200 | Configuration plateau (scénario). |
| GET | /api/replay/list | Header: Bearer | 200, 401 | Liste des fichiers replay. |
| GET | /api/replay/file/<filename> | Header: Bearer. Param: filename | 200, 400, 401, 404 | Contenu d’un replay (path traversal vérifié). |
| GET | /api/replay/default | Header: Bearer | 200, 401 | Replay par défaut. |
| POST | /api/replay/parse | Header: Bearer. Body: contenu ou référence | 200, 400, 401 | Parse un replay. |
| GET | /api/debug/engine-test | Header: Bearer (admin) | 200, 401, 403 | Test moteur (debug). |
| GET | /api/debug/actions | Header: Bearer (admin) | 200, 401, 403 | Liste des actions possibles (debug). |
| GET | / | — | 200 | Servi par le frontend (Nginx en prod). |

*Routes protégées : toutes sauf `/api/health`, `/api/auth/register`, `/api/auth/login`, `/api/armies`, `/api/config/board`. Les modes `pve_test` et `pvp_test` sont réservés au profil admin.*
