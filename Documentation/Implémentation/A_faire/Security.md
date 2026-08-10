# Sécurité — Analyse et plan d'implémentation

> Date : 2026-07-15 — mise à jour 2026-08-10 (étapes 1 et 2 faites : F1, F6, F7, F11, F12, F14 résolus ; ancres de ligne rafraîchies). **Reste à faire : étapes 3 à 8** (F2, F3, F4, F5, F8, F9, F10, F13).
> Périmètre : backend Flask (`services/api_server.py`), frontend React/Vite, base auth `config/users.db`.
> Contexte : jeu hobby, aujourd'hui local (WSL2), **bientôt exposé sur Internet pour des tests publics**.

---

## 1. Modèle de menace (exposition Internet)

Menaces retenues :
1. **Prise de contrôle du serveur (RCE)** → vol du code backend, des modèles IA, de `users.db`.
2. **Lecture de fichiers arbitraires** → vol du code source, secrets.
3. **Utilisation abusive de l'API** (endpoints non authentifiés, spam, corruption des parties).
4. **Vol de comptes** (tokens de session, mots de passe faibles).

### Sur le vol de code spécifiquement

- **Frontend** : le code JS/WASM est **par nature envoyé à chaque visiteur** — c'est impossible à empêcher. Le build Vite est minifié et ne contient pas de source maps (vérifié : aucun `.map` dans `frontend/dist/`). L'obfuscation supplémentaire est inutile (contournable en heures). La vraie protection du frontend est **juridique** (licence, pas de repo public), pas technique.
- **Backend + modèles IA** : c'est là qu'est la valeur (moteur de règles, agents entraînés). Ce code ne quitte jamais le serveur **sauf si** un attaquant obtient une exécution de code ou une lecture de fichiers arbitraire. Toute la stratégie consiste donc à fermer ces vecteurs — F1, F6, F7 et F11 sont résolus (étapes 1 et 2) : plus d'exécution de code ni d'écriture disque atteignables depuis le réseau. Ce qui reste à traiter (étapes 3 à 5) relève du vol de session et de l'exposition, pas de la prise de contrôle du serveur.

---

## 2. État des lieux (vérifié dans le code)

### Ce qui est déjà en place et correct

| Domaine | Implémentation | Référence |
|---|---|---|
| Hachage des mots de passe | PBKDF2-HMAC-SHA256 avec sel aléatoire 16 octets (`secrets.token_bytes`) | `api_server.py:1076` |
| Authentification (mécanisme) | Bearer token de session (`secrets.token_urlsafe(48)`), stocké dans `sessions` (SQLite) | `api_server.py:2256`, `api_server.py:1156` |
| Autorisation (RBAC) | Tables `profiles`, `profile_game_modes`, `profile_options` ; résolution des permissions par profil | `api_server.py:1120`, `api_server.py:1217` |
| Gestion mémoire | Python + TypeScript (mémoire managée) ; module WASM LoS en **Rust** (`frontend/wasm-los/`), memory-safe. Aucun code C/C++. | — |
| Endpoints replay | `/api/replay/file/<filename>` **et** `/api/replay/parse` filtrent le path traversal (`..`, `/`, `\` rejetés, extension `.log` imposée) | `api_server.py:4770`, `api_server.py:4729` |
| Frontend build | Pas de source maps dans `dist/` | vérifié |
| **F1 (ex-critique) — RCE via debugger Werkzeug** | **Résolu.** `app.run(host='127.0.0.1', port=5001, debug=False)` — plus de `debug=True`/`0.0.0.0`. | `api_server.py:4874` |
| **F6 (ex-critique) — API non authentifiée** | **Résolu (étape 1).** `@app.before_request` ferme les 31 routes par défaut ; seules les vues portant `@public_endpoint` (`login_user`, `health_check`, `serve_frontend`) + les préflights `OPTIONS` sont ouvertes. RBAC appliqué dans la porte. Côté front, `apiFetch()` attache le Bearer sur tout `/api/*`. | `api_server.py:2065`, `api_server.py:2153`, `frontend/src/services/apiFetch.ts` |
| **F12 (ex-haute) — inscription ouverte** | **Résolu (étape 1).** `/api/auth/register` **supprimée** (0 occurrence) ; comptes créés manuellement en SQL. | vérifié par grep |
| **F14 (ex-moyenne) — filtre `replay/parse`** | **Résolu (étape 1).** Filtre aligné sur `/api/replay/file` : `.log` imposé, tout séparateur et `..` rejetés. | `api_server.py:4729-4735` |

### Failles identifiées

| # | Sévérité | Faille | Détail | Référence |
|---|---|---|---|---|
| F7 | ✅ Résolu | Répertoire contrôlé par le client + `pickle.load` | Étape 2 : répertoire fixé par le serveur (`W40K_PERSIST_DIR`), `directory` de requête rejeté, pickle des snapshots supprimé, et dépickle des saves restreint à une liste blanche de classes (`_safe_loads`). | `api_server.py` (`_resolve_persist_dir`), `game_saves.py` (`_ALLOWED_CLASSES`) |
| F11 | ✅ Résolu | Endpoint `pick-directory` exécutait `subprocess`/`powershell.exe` | Route supprimée (étape 2) ; plus aucun `subprocess` atteignable. Sélecteur natif retiré du front. | — |
| F13 | Moyenne | Token de session en `localStorage` | Le token est stocké dans `localStorage` → volable par tout XSS (token = accès complet). Cible : cookie `HttpOnly`+`Secure`+`SameSite`. À défaut, risque à acter explicitement. | `frontend/src/auth/authStorage.ts:23,40,44` |
| F2 | **Haute** | Sessions sans expiration | Table `sessions` : `created_at` seulement ; validation `WHERE s.token = ?` sans condition temporelle. Token volé = valide à vie. Le message "Invalid or expired session" est trompeur. | `api_server.py:1255-1259` (table), `api_server.py:1172` (validation) |
| F8 | **Haute** | Pas de rate limiting sur le login | Brute-force des mots de passe possible à pleine vitesse depuis Internet. | `api_server.py:2223` |
| F9 | **Haute** | Flask dev server + pas de TLS | Le serveur de dev Werkzeug n'est pas fait pour Internet (perf, robustesse). Sans HTTPS, tokens et mots de passe passent en clair. Indépendant de F1 (déjà résolu) : même avec `debug=False`, Werkzeug reste un serveur de dev. | `api_server.py:4874` |
| F3 | Moyenne | CORS ouvert à toutes les origines | `CORS(app, ...)` sans `origins` = `*`. | `api_server.py:1432` |
| F10 | Moyenne | Traceback complet renvoyé au client | Le handler global d'exceptions renvoie type + message + traceback dans la réponse JSON → révèle chemins, structure du code, versions. Utile en dev, à désactiver en prod (log serveur uniquement). | `api_server.py:1438` |
| F4 | Faible→Moyenne | Pas de journal d'audit | Aucune trace des logins réussis/échoués, IP, créations d'utilisateurs. Indispensable pour détecter une attaque en cours une fois exposé. | — |
| F5 | Faible | Pas d'analyse automatisée | Aucun outil statique (bandit, pip-audit, npm audit) dans le workflow. | — |

---

## 3. Avis sur les sujets évoqués

### MFA
**Reporté, plus écarté.** Pour des tests publics avec quelques testeurs invités, des mots de passe forts + rate limiting + sessions expirantes suffisent. À implémenter (TOTP via `pyotp`) si le jeu passe en accès ouvert avec inscription libre. Réévaluation prévue à la fin du plan.

### Autorisation / RBAC
**Fait (étape 1).** Le mécanisme existait mais ne protégeait que 3 routes ; il est désormais appliqué **dans la porte `before_request`**, à chaque requête, avec les trois catégories décrites en étape 1 (`@changes_game_mode`, `@mode_agnostic`, défaut = mode courant).

### Audit
**Recommandé, sévérité remontée.** Exposé sur Internet, le journal d'audit (avec IP) est ton seul moyen de savoir si quelqu'un brute-force le login ou abuse de l'API.

### Analyse statique et dynamique
- **Statique : oui** — `bandit`, `pip-audit`, `npm audit` (étape 6). NB : bandit aurait signalé le `pickle.load` (F7) dès l'origine — preuve de son utilité. Il continuera de le signaler sur `game_saves.py` : le format est conservé, c'est `_safe_loads` qui neutralise le vecteur ; l'écarter demandera une justification écrite, pas un `# nosec` muet.
- **Dynamique : devient pertinent** avec l'exposition. Un scan OWASP ZAP en mode baseline contre l'instance de test, une fois les étapes 1–5 faites. Optionnel mais peu coûteux.

### Buffer overflow / gestion mémoire
**Non pertinent.** Python et TypeScript sont à mémoire managée ; le seul code natif (WASM LoS) est en Rust, memory-safe par construction. Redeviendrait pertinent uniquement si du C/C++ était introduit.

---

## 4. Plan d'implémentation

Ordre = priorité. **Les étapes 1 à 5 sont des prérequis absolus avant toute exposition Internet.**

> F1 (debugger Werkzeug exposé) est **résolu** (`api_server.py:4874` : `debug=False`, `host='127.0.0.1'`). L'étape 1 initiale (F1+F7+F11) a donc été scindée : l'auth globale (F6, ex-étape 2) est passée en premier — elle a supprimé l'exposition **anonyme** de F7/F11. L'étape 2 a ensuite fermé l'écriture arbitraire, supprimé `pick-directory` et restreint le dépickle des saves : F7 et F11 sont clos.

### Étape 1 — Authentification sur toutes les routes (F6, F12, F14) ✅ faite le 2026-08-02

> ⚠️ **Chantier backend ET frontend.** Constaté à l'implémentation : sur ~46 appels API du frontend,
> **4 seulement** envoient le token (tous sur `/game/start`). Fermer l'API côté serveur sans toucher au
> front casse l'intégralité du jeu. Il n'existe aucun client API centralisé — chaque site d'appel fait
> son `fetch` à la main.

**Backend — `services/api_server.py`**
- `@app.before_request` global : toute route exige un token de session valide, **sauf** liste blanche explicite. Pas de logique inversée (pas de "protéger certaines routes") : tout est fermé par défaut, une route oubliée est donc fermée et non ouverte.
- Liste blanche portée par un décorateur `@public_endpoint` posé **sur la vue**, et filtrage sur `request.endpoint` et non sur `request.path` : changer l'URL d'une route emporte son exemption avec elle. Une liste de chemins en dur se périmerait en silence — et pour `login` la panne serait un verrouillage total, pas une fuite. Trois vues exemptées : `login_user`, `health_check`, `serve_frontend`, plus les préflights `OPTIONS` (envoyés par le navigateur sans header d'auth — les bloquer casse le CORS).
- Une URL ne correspondant à aucune route a `endpoint = None` → 401 plutôt que 404, ce qui évite de révéler quelles routes existent.
- `g.auth_user` porte l'utilisateur validé par la porte ; `/api/auth/me` et `/api/game/start` le lisent au lieu de rejouer la jointure (2 connexions SQLite par requête au lieu de 3). `os.makedirs` sorti de `_get_auth_db_connection` vers `initialize_auth_db` : la porte s'exécute à chaque requête, y compris les prévisualisations au survol (~40/s).
- `/api/auth/register` (F12) : **route supprimée**, pas seulement retirée de la liste blanche — décision actée = *fermeture pure*, comptes testeurs créés manuellement en SQL. La garder derrière l'authentification ne suffirait pas : n'importe quel testeur au profil `base` pourrait créer des comptes en masse. Le jeton d'invitation à usage unique reste l'évolution prévue si le nombre de testeurs grandit ; la route réapparaîtra alors avec sa validation propre. Inscription libre = interdite tant que le MFA est reporté.
- `/api/replay/parse` (F14) : harmoniser le filtre avec `/api/replay/file/<filename>` (extension `.log` imposée, rejet strict de tout séparateur/`..`).
- RBAC (modes de jeu) appliqué **dans la porte**, à chaque requête : contrôlé au seul démarrage de partie, un utilisateur pouvait agir sur une partie déjà lancée dont son profil interdit le mode. Trois catégories, toutes portées par un décorateur sur la vue, le contrôle étant le défaut :
  - `@changes_game_mode` (`start_game`, `load_party`, `load_save`, `restore_snapshot`) — ces vues REMPLACENT le mode, les juger sur le mode courant bloquerait une bascule légitime. Elles valident le mode **cible** via `_forbidden_mode_response`, **avant** de muter l'engine. Charger une sauvegarde réécrit `current_mode_code` (`_sync_derived_engine_attrs`) : sans ce contrôle, un profil `pve` chargeait une partie `pvp` sans validation.
  - `@mode_agnostic` (catalogues, config, replays, `/api/auth/me`) — n'agissent pas sur la partie. `engine` étant une globale de process, les soumettre au contrôle renverrait 403 à un testeur `pve` sur toute la séquence de démarrage du front dès qu'une partie `pvp` traîne — et 403 n'est pas redirigé vers le login par `apiFetch`.
  - tout le reste : contrôle du mode courant. Une route nouvelle y tombe par défaut.
- Racine `/` rendue muette : elle publiait le catalogue des routes à tout visiteur non authentifié, ce qui annulait le choix « 401 plutôt que 404 sur URL inconnue ».
- Coût : une résolution de permissions par requête, **uniquement quand une partie tourne** et hors routes `@mode_agnostic`.

**Frontend — client API centralisé**
- Introduire un `apiFetch()` unique qui attache `Authorization: Bearer <token>` à tout appel `/api/*`, et migrer les sites d'appel dessus. Ajouter le header à la main sur chaque `fetch` est rejeté : la faille se rouvrirait au prochain `fetch` ajouté.
- Fichiers concernés : `hooks/useEngineAPI.ts` (27 appels), `components/BoardPvp.tsx` (15), `components/BoardReplay.tsx` (3), `components/SharedLayout.tsx` (1). `pages/AuthPage.tsx` (login/register) reste hors `apiFetch` — pas de token à ce stade.
- Traitement du 401 centralisé dans `apiFetch` (session expirée → retour à l'écran de login), plutôt que dupliqué sur chaque appelant.

**Validation :** toute route hors liste blanche sans token → 401 ; `register` sans token → refusé ; le jeu fonctionne normalement une fois loggé (validation runtime PvP obligatoire, le `tsc` ne prouve rien ici).

### Étape 2 — Fermer les vecteurs d'écriture/désérialisation arbitraires (F7, F11) ✅ faite le 2026-08-10

**Fait (2026-08-10) — écriture arbitraire et `subprocess` fermés**
- Répertoire de persistance = config **serveur** (`_resolve_persist_dir`, `W40K_PERSIST_DIR`, défaut `logs/`, variable vide = erreur au démarrage). `/api/game/snapshot/persist` **rejette** un `directory` reçu du client (400 explicite, pas d'ignorance silencieuse) ; `_load_save_config` ne relit plus le `directory` du fichier de config (il portait un chemin choisi par le client, le relire rouvrait le vecteur).
- `_PERSIST_DIR_SET` supprimé : le répertoire est toujours défini, le toggle « sauvegarde sur disque » devient le seul interrupteur (saves, timeline, ancre game_start).
- `save_config.json` écrit sous `_PERSIST_DIR` au lieu de `<repo>/logs/` en dur : sinon un déploiement pointant `W40K_PERSIST_DIR` hors du dépôt exigerait quand même un arbre de sources inscriptible. Chemin par défaut inchangé.
- `/api/game/pick-directory` **supprimée** (F11) — plus aucun `subprocess`/`powershell.exe` atteignable. Côté front : sélecteur natif, saisie manuelle du chemin et popup obligatoire au lancement retirés ; le répertoire s'affiche en lecture seule.
- Persistance pickle des snapshots **supprimée** : `pvp_snapshots.pkl` était écrit à chaque capture et **relu par aucun appelant** (`_load_snapshots_from_disk` était du code mort — la reprise passe par les saves). Il ne restait qu'un `pickle.dump` sans usage. Les snapshots de rewind vivent en mémoire, comme avant.
- Tests : `tests/unit/services/test_api_persist_dir.py` (rejet du `directory`, absence de la route, `.pkl` non écrit, résolution de `W40K_PERSIST_DIR`).

**Fait — désérialisation des saves : dépickle restreint**
`services/game_saves.py` relit chaque row en `pickle` sur le chemin Load/Select/Resume. Le format est conservé, mais toute désérialisation passe désormais par `_safe_loads` : un `pickle.Unpickler` dont `find_class` n'accepte que `_ALLOWED_CLASSES`. L'exécution de code au dépickle passe obligatoirement par `find_class` (opcode REDUCE sur un gadget type `os.system`) — privé de callable, le vecteur est fermé.
- Critère d'entrée dans la liste : constructeur de **données** uniquement (au pire un objet absurde, jamais un effet de bord). Aujourd'hui : `ParsedWeaponRule` et les trois entrées numpy (`ndarray`, `dtype`, `_reconstruct`, en double pour le renommage `numpy.core` → `numpy._core`).
- Écarté : **codec JSON typé** — mesuré sur un vrai état, il faudrait encoder 28 257 dicts à clés tuple (`occupation_map`), 3 056 tuples, 58 sets, des clés int et 389 objets `ParsedWeaponRule`, et casser le format des saves existantes, pour une surface d'attaque déjà nulle côté réseau. Écarté aussi : **signature HMAC** — ne protège que de qui peut écrire sans pouvoir lire la clé, là où la liste blanche tient même face à un accès disque complet.
- Limite assumée : un fichier falsifié peut toujours restituer un **état de jeu** faux (score, positions). Ce n'est pas de l'exécution de code, et cela suppose déjà un accès disque.
- Tests : `tests/unit/services/test_game_saves_restricted_unpickle.py` (gadget `os.system` refusé, contre-épreuve prouvant qu'il s'exécuterait sans le garde, chemin `SaveStore.point`) et `tests/integration/pvp/test_save_restricted_unpickle.py` (save d'une partie **réelle** relue à travers le garde — c'est ce test qui a révélé les entrées numpy manquantes).

**Validation :** requête POST avec `directory` → 400 ; `pick-directory` → 404 ; aucun `.pkl` écrit ; sauvegarde/rewind fonctionnels (runtime PvP à valider).

### Étape 3 — Durcissement des sessions (F2, F8)
**Fichier :** `services/api_server.py`
- Colonne `expires_at` sur `sessions` (migration `ALTER TABLE` — aucun pattern existant dans `initialize_auth_db()`, à introduire) ; durée 7 jours glissants, renouvelée à chaque requête ; purge au login ; `AND expires_at > ?` dans la validation. Session expirée = 401 explicite, pas de fallback.
- Rate limiting sur `/api/auth/login` : `flask-limiter` (ex. 5 tentatives/minute/IP). Échec → 429 explicite.

**Validation :** token expiré forcé en SQL → 401 ; 6 logins ratés en rafale → 429.

### Étape 4 — Réduction de la surface d'information (F3, F10)
**Fichier :** `services/api_server.py`
- CORS : `origins` limité à l'URL du frontend, surchargeable par `W40K_CORS_ORIGINS` (liste séparée par virgules). Variable définie mais vide → erreur au démarrage.
- Handler d'exceptions : traceback dans la réponse JSON **uniquement si `W40K_DEBUG=true`** ; en prod, log serveur complet + réponse générique avec un identifiant d'erreur corrélable au log.
- Token de session (F13) : cible = cookie `HttpOnly`+`Secure`+`SameSite=Strict` au lieu de `localStorage` (immunise contre le vol par XSS). Chantier front + back non trivial ; si reporté, acter explicitement le risque en §5.

**Validation :** fetch cross-origin bloqué ; exception en prod → pas de traceback dans la réponse, traceback présent dans le log serveur.

### Étape 5 — Infrastructure d'exposition (F9)
**Nouveaux fichiers :** config de déploiement (à définir selon l'hébergement choisi)
- Remplacer le dev server par un serveur WSGI de production : `waitress` (simple, pur Python) ou `gunicorn`.
- Reverse proxy devant (Caddy recommandé : HTTPS automatique via Let's Encrypt, config minimale) servant aussi le build frontend statique (`frontend/dist/`).
- Le process Python tourne sous un utilisateur dédié sans droits d'écriture hors `logs/` (limite les dégâts de toute écriture arbitraire résiduelle).
- Ne jamais exposer : `config/users.db`, `ai/models/`, le repo git.

**Validation :** accès HTTPS fonctionnel, HTTP redirigé, port 5001 non accessible directement depuis l'extérieur.

### Étape 6 — Analyse statique automatisée (F5)
**Nouveau fichier :** `scripts/security_check.sh`
- `bandit -r services/ engine/ ai/`, `pip-audit`, `cd frontend && npm audit --audit-level=high`.
- Dépendances dev dans un `requirements-dev.txt`.
- Traiter les findings critiques/hauts (itération dédiée).

**Validation :** script exécutable, findings critiques traités.

### Étape 7 — Journal d'audit (F4)
**Fichier :** `services/api_server.py`
- Table `audit_log (id, timestamp_utc, event, login, ip, details)` dans `users.db`.
- Événements : `login_success`, `login_failure`, `logout`, `user_created`, `profile_changed`, `password_changed`, `rate_limited`.
- IP réelle derrière le reverse proxy : lire `X-Forwarded-For` **uniquement** si la requête vient du proxy.

**Validation :** login réussi + raté → deux lignes avec IP correcte.

### Étape 8 — Passe finale avant ouverture
- Scan dynamique baseline (OWASP ZAP) contre l'instance de test.
- Revue : réévaluer MFA selon le mode d'inscription des testeurs (invitations = non ; inscription libre = oui).
- Vérifier les mots de passe des comptes existants (pas de comptes de test type `admin/admin`).

---

## 5. Hors périmètre (décisions actées)

| Sujet | Décision | Condition de réévaluation |
|---|---|---|
| MFA / TOTP | Reporté | Inscription libre des testeurs (étape 8) |
| Obfuscation du frontend | Non (inefficace) | Jamais — protection juridique à la place |
| Règles buffer overflow / mémoire | Non | Introduction de code C/C++ |
| WAF / anti-DDoS | Non (tests à petite échelle) | Trafic public significatif |

---

## 6. Suivi

| Étape | Failles | Statut | Date |
|---|---|---|---|
| — | F1 (debugger Werkzeug) | ✅ Résolu | ≤2026-08-02 |
| 1. Auth sur toutes les routes | F6, F12, F14 | ✅ Fait — vérifié dans le code le 2026-08-10 (31 routes, porte globale, `register` supprimée, `apiFetch`) | 2026-08-02 |
| 2. Fermer vecteurs écriture/désérialisation | F7, F11 | ✅ Fait (runtime PvP validé) | 2026-08-10 |
| 3. Durcissement sessions + rate limiting | F2, F8 | ⬜ À faire | — |
| 4. Réduction surface d'information | F3, F10, F13 | ⬜ À faire | — |
| 5. Infra d'exposition (WSGI + proxy + TLS) | F9 | ⬜ À faire | — |
| 6. Analyse statique | F5 | ⬜ À faire | — |
| 7. Journal d'audit | F4 | ⬜ À faire | — |
| 8. Passe finale (ZAP, MFA ?, comptes) | — | ⬜ À faire | — |

**Jalon : ne pas exposer sur Internet avant la fin de l'étape 5.**
