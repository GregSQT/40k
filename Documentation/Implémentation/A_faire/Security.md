# Sécurité — Analyse et plan d'implémentation

> Date : 2026-07-15 — audit de conformité 2026-08-02 (ancres de ligne rafraîchies, F1 reclassé résolu, comptage F6 corrigé)
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
- **Backend + modèles IA** : c'est là qu'est la valeur (moteur de règles, agents entraînés). Ce code ne quitte jamais le serveur **sauf si** un attaquant obtient une exécution de code ou une lecture de fichiers arbitraire. Toute la stratégie consiste donc à fermer ces vecteurs — F1 est résolu, F6 et F7 existent encore aujourd'hui (voir ci-dessous).

---

## 2. État des lieux (vérifié dans le code)

### Ce qui est déjà en place et correct

| Domaine | Implémentation | Référence |
|---|---|---|
| Hachage des mots de passe | PBKDF2-HMAC-SHA256 avec sel aléatoire 16 octets (`secrets.token_bytes`) | `api_server.py:941` |
| Authentification (mécanisme) | Bearer token de session, stocké dans `sessions` (SQLite) | `api_server.py:979`, `api_server.py:1028` |
| Autorisation (RBAC) | Tables `profiles`, `profile_game_modes`, `profile_options` ; résolution des permissions par profil | `api_server.py:992`, `api_server.py:1057` |
| Gestion mémoire | Python + TypeScript (mémoire managée) ; module WASM LoS en **Rust** (`frontend/wasm-los/`), memory-safe. Aucun code C/C++. | — |
| Endpoint replay | `/api/replay/file/<filename>` filtre correctement le path traversal (`..`, `/`, `\` rejetés, extension `.log` imposée) | `api_server.py:4319` |
| Frontend build | Pas de source maps dans `dist/` | vérifié |
| **F1 (ex-critique) — RCE via debugger Werkzeug** | **Résolu.** `app.run(host='127.0.0.1', port=5001, debug=False)` — plus de `debug=True`/`0.0.0.0`. | `api_server.py:4440` |

### Failles identifiées

| # | Sévérité | Faille | Détail | Référence |
|---|---|---|---|---|
| F6 | **Critique** | API quasi entièrement non authentifiée | **30 des 32 routes** n'appellent pas `_get_authenticated_user_or_response()` et il n'y a aucun `before_request` global. Toutes les actions de jeu, la lecture des logs/replays et la configuration de persistance sont ouvertes à n'importe qui. | vérifié par comptage (`grep -c "^@app.route"` = 32 ; 2 seuls appels à `_get_authenticated_user_or_response()`) |
| F7 | **Critique** | Répertoire de persistance contrôlé par le client + `pickle.load` | `/api/game/snapshot/persist` accepte un `directory` arbitraire (créé via `os.makedirs`, aucune restriction) → **écriture disque n'importe où** avec les droits du process. Les snapshots sont ensuite relus via `pickle.load` → la désérialisation pickle d'un fichier influençable par un client est un **vecteur RCE classique**. | `api_server.py:3537` (directory), `api_server.py:3454` (pickle.load) |
| F11 | **Critique** | Endpoint `pick-directory` exécute `subprocess`/`powershell.exe` | `/api/game/pick-directory` (non authentifié) lance `powershell.exe` via `subprocess` pour ouvrir un dialogue Windows. Aucun sens fonctionnel sur un serveur exposé, et surface `subprocess` ouverte sur le réseau. **À supprimer purement** en prod (pas seulement authentifier). | `api_server.py:3567` |
| F12 | **Haute** | Inscription (`/api/auth/register`) totalement ouverte | Aucune auth, aucun rate limit → création de comptes en masse depuis Internet. Rend caduque la logique « testeurs invités » qui justifie de reporter le MFA. Fermer (création manuelle en SQL) ou protéger par jeton d'invitation. | `api_server.py:1961` |
| F13 | Moyenne | Token de session en `localStorage` | Le token est stocké dans `localStorage` → volable par tout XSS (token = accès complet). Cible : cookie `HttpOnly`+`Secure`+`SameSite`. À défaut, risque à acter explicitement. | `frontend/src/auth/authStorage.ts:23,40,44` |
| F14 | Moyenne | Filtre path-traversal faible sur `replay/parse` | `/api/replay/parse` rejette `..` et `/` en tête mais ouvre tout `log_path` relatif directement — moins strict que `/api/replay/file/<filename>` (extension `.log` imposée, ligne 4326). À harmoniser (couvert incidemment par l'auth globale F6). | `api_server.py:4265` |
| F2 | **Haute** | Sessions sans expiration | Table `sessions` : `created_at` seulement ; validation `WHERE token = ?` sans condition temporelle. Token volé = valide à vie. Le message "Invalid or expired session" est trompeur. | `api_server.py:1125-1129` (table), `api_server.py:1045` (validation) |
| F8 | **Haute** | Pas de rate limiting sur le login | Brute-force des mots de passe possible à pleine vitesse depuis Internet. | — |
| F9 | **Haute** | Flask dev server + pas de TLS | Le serveur de dev Werkzeug n'est pas fait pour Internet (perf, robustesse). Sans HTTPS, tokens et mots de passe passent en clair. Indépendant de F1 (déjà résolu) : même avec `debug=False`, Werkzeug reste un serveur de dev. | `api_server.py:4440` |
| F3 | Moyenne | CORS ouvert à toutes les origines | `CORS(app, ...)` sans `origins` = `*`. | `api_server.py:1302` |
| F10 | Moyenne | Traceback complet renvoyé au client | Le handler global d'exceptions renvoie type + message + traceback dans la réponse JSON → révèle chemins, structure du code, versions. Utile en dev, à désactiver en prod (log serveur uniquement). | `api_server.py:1309` |
| F4 | Faible→Moyenne | Pas de journal d'audit | Aucune trace des logins réussis/échoués, IP, créations d'utilisateurs. Indispensable pour détecter une attaque en cours une fois exposé. | — |
| F5 | Faible | Pas d'analyse automatisée | Aucun outil statique (bandit, pip-audit, npm audit) dans le workflow. | — |

---

## 3. Avis sur les sujets évoqués

### MFA
**Reporté, plus écarté.** Pour des tests publics avec quelques testeurs invités, des mots de passe forts + rate limiting + sessions expirantes suffisent. À implémenter (TOTP via `pyotp`) si le jeu passe en accès ouvert avec inscription libre. Réévaluation prévue à la fin du plan.

### Autorisation / RBAC
**Le mécanisme existe, mais il ne protège presque rien** (F6) : `_resolve_permissions_for_profile` n'est appelé que sur 3 routes (`/api/auth/login`, `/api/auth/me`, `/api/game/start`). Le chantier n'est pas de créer un RBAC, c'est de **l'appliquer partout** (étape 1).

### Audit
**Recommandé, sévérité remontée.** Exposé sur Internet, le journal d'audit (avec IP) est ton seul moyen de savoir si quelqu'un brute-force le login ou abuse de l'API.

### Analyse statique et dynamique
- **Statique : oui** — `bandit`, `pip-audit`, `npm audit` (étape 6). NB : bandit aurait signalé le `pickle.load` (F7) — preuve de son utilité.
- **Dynamique : devient pertinent** avec l'exposition. Un scan OWASP ZAP en mode baseline contre l'instance de test, une fois les étapes 1–5 faites. Optionnel mais peu coûteux.

### Buffer overflow / gestion mémoire
**Non pertinent.** Python et TypeScript sont à mémoire managée ; le seul code natif (WASM LoS) est en Rust, memory-safe par construction. Redeviendrait pertinent uniquement si du C/C++ était introduit.

---

## 4. Plan d'implémentation

Ordre = priorité. **Les étapes 1 à 5 sont des prérequis absolus avant toute exposition Internet.**

> F1 (debugger Werkzeug exposé) est **résolu** (`api_server.py:4440` : `debug=False`, `host='127.0.0.1'`). L'étape 1 initiale (F1+F7+F11) est donc scindée : l'auth globale (F6, ex-étape 2) passe en premier — elle neutralise d'un coup l'exposition réseau de F7/F11, qui redeviennent alors un nettoyage plutôt qu'une urgence.

### Étape 1 — Authentification sur toutes les routes (F6, F12, F14) 🔴 bloquant

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

### Étape 2 — Fermer les vecteurs d'écriture/désérialisation arbitraires (F7, F11) 🔴 bloquant
**Fichier :** `services/api_server.py`
- `/api/game/snapshot/persist` : supprimer la possibilité pour le client de choisir `directory`. Le répertoire de persistance devient une config **serveur** (variable d'environnement ou fichier de config), jamais une donnée de requête.
- Remplacer `pickle` par un format non exécutable pour les snapshots (JSON si la structure le permet, sinon garder pickle mais uniquement sur un chemin fixe non influençable par le client — à trancher au moment de l'implémentation selon le contenu de `GameSnapshotStore`).
- `/api/game/pick-directory` (F11) : supprimer l'endpoint en prod (via flag `W40K_DEBUG` ou retrait pur). Aucun `subprocess`/`powershell.exe` exposé sur le réseau. Le front doit basculer sur une config serveur du répertoire de persistance (voir point précédent).

**Validation :** requête POST avec `directory` → erreur explicite ; `pick-directory` absent/404 en prod ; snapshots toujours fonctionnels.

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
| 1. Auth sur toutes les routes | F6, F12, F14 | ✅ Fait (runtime PvP à valider) | 2026-08-02 |
| 2. Fermer vecteurs écriture/désérialisation | F7, F11 | ⬜ À faire | — |
| 3. Durcissement sessions + rate limiting | F2, F8 | ⬜ À faire | — |
| 4. Réduction surface d'information | F3, F10, F13 | ⬜ À faire | — |
| 5. Infra d'exposition (WSGI + proxy + TLS) | F9 | ⬜ À faire | — |
| 6. Analyse statique | F5 | ⬜ À faire | — |
| 7. Journal d'audit | F4 | ⬜ À faire | — |
| 8. Passe finale (ZAP, MFA ?, comptes) | — | ⬜ À faire | — |

**Jalon : ne pas exposer sur Internet avant la fin de l'étape 5.**
