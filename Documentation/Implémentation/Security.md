# Sécurité — Analyse et plan d'implémentation

> Date : 2026-07-15 — mise à jour 2026-08-10 (étapes 1, 2 et 3 faites : F1, F2, F6, F7, F8, F11, F12, F14 résolus ; étape 3 durcie après revue — IP réelle du client, comptage atomique, journal `auth_events` append-only qui pose le socle de l'étape 7 ; étape 5 réécrite à partir de la stack Docker existante, nouvelle faille F15 ; **étape 6 faite** : `scripts/security_check.sh`, verrou de dépendances de production, F5 résolu). **Reste à faire : étapes 4, 5, 8 et la fin de la 7** (F3, F4 partiel, F9, F10, F13, F15).
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
- **Backend + modèles IA** : c'est là qu'est la valeur (moteur de règles, agents entraînés). Ce code ne quitte jamais le serveur **sauf si** un attaquant obtient une exécution de code ou une lecture de fichiers arbitraire. Toute la stratégie consiste donc à fermer ces vecteurs — F1, F6, F7 et F11 sont résolus (étapes 1 et 2) : plus d'exécution de code ni d'écriture disque atteignables depuis le réseau. L'étape 3 a fermé la session éternelle et le brute-force. Ce qui reste à traiter (étapes 4 et 5) relève de l'exposition et du transport, pas de la prise de contrôle du serveur.

---

## 2. État des lieux (vérifié dans le code)

### Ce qui est déjà en place et correct

| Domaine | Implémentation | Référence |
|---|---|---|
| Hachage des mots de passe | PBKDF2-HMAC-SHA256 avec sel aléatoire 16 octets (`secrets.token_bytes`) | `api_server.py` (`_hash_password`, `_verify_password`) |
| Authentification (mécanisme) | Bearer token de session (`secrets.token_urlsafe(48)`), stocké dans `sessions` (SQLite) | `api_server.py` (`login_user`, `_SESSIONS_TABLE_SQL`) |
| Autorisation (RBAC) | Tables `profiles`, `profile_game_modes`, `profile_options` ; résolution des permissions par profil | `api_server.py` (`auth_db_read_cursor`, `_resolve_permissions_for_profile`) |
| Gestion mémoire | Python + TypeScript (mémoire managée) ; module WASM LoS en **Rust** (`frontend/wasm-los/`), memory-safe. Aucun code C/C++. | — |
| Endpoints replay | `/api/replay/file/<filename>` **et** `/api/replay/parse` filtrent le path traversal (`..`, `/`, `\` rejetés, extension `.log` imposée) | `api_server.py` (`get_replay_log_file`, `parse_replay_log`) |
| Frontend build | Pas de source maps dans `dist/` | vérifié |
| **F1 (ex-critique) — RCE via debugger Werkzeug** | **Résolu.** `app.run(host='127.0.0.1', port=5001, debug=False)` — plus de `debug=True`/`0.0.0.0`. | `api_server.py` (bloc `__main__`) |
| **F6 (ex-critique) — API non authentifiée** | **Résolu (étape 1).** `@app.before_request` ferme les 30 routes par défaut ; seules les vues portant `@public_endpoint` (`health_check`, `login_user`, `serve_frontend`) + les préflights `OPTIONS` sont ouvertes. RBAC appliqué dans la porte. Côté front, `apiFetch()` attache le Bearer sur tout `/api/*`. | `api_server.py` (`public_endpoint` et la porte `@app.before_request` ; vues publiques `health_check`, `login_user`, `serve_frontend`), `frontend/src/services/apiFetch.ts` |
| **F12 (ex-haute) — inscription ouverte** | **Résolu (étape 1).** `/api/auth/register` **supprimée** (0 occurrence) ; comptes créés manuellement en SQL. | vérifié par grep |
| **F14 (ex-moyenne) — filtre `replay/parse`** | **Résolu (étape 1).** Filtre aligné sur `/api/replay/file` : `.log` imposé, tout séparateur et `..` rejetés. | `api_server.py` (`parse_replay_log`) |
| **F2 (ex-haute) — sessions sans expiration** | **Résolu (étape 3).** `sessions.expires_at` NOT NULL, TTL 7 jours **glissant** ; validation `AND s.expires_at > ?` ; purge des échues au login ; `/api/auth/logout` révoque immédiatement. | `api_server.py` (`_SESSIONS_TABLE_SQL`, `_get_authenticated_user_or_response`, `_renew_session_if_stale`, `logout_user`) |
| **F8 (ex-haute) — pas de rate limiting** | **Résolu (étape 3, durci le 2026-08-10).** Journal `auth_events` : 5 tentatives par (login, IP réelle) sur 60 s → 429, comptage et inscription dans une même transaction `BEGIN IMMEDIATE`, **avant** PBKDF2. | `api_server.py` (`_count_login_attempts_since_success`, `_client_ip`, `login_user`) |

### Failles identifiées

| # | Sévérité | Faille | Détail | Référence |
|---|---|---|---|---|
| F7 | ✅ Résolu | Répertoire contrôlé par le client + `pickle.load` | Étape 2 : répertoire fixé par le serveur (`W40K_PERSIST_DIR`), `directory` de requête rejeté, pickle des snapshots supprimé, et dépickle des saves restreint à une liste blanche de classes (`_safe_loads`). | `api_server.py` (`_resolve_persist_dir`), `game_saves.py` (`_ALLOWED_CLASSES`) |
| F11 | ✅ Résolu | Endpoint `pick-directory` exécutait `subprocess`/`powershell.exe` | Route supprimée (étape 2) ; plus aucun `subprocess` atteignable. Sélecteur natif retiré du front. | — |
| F13 | Moyenne | Token de session en `localStorage` | Le token est stocké dans `localStorage` → volable par tout XSS (token = accès complet). Cible : cookie `HttpOnly`+`Secure`+`SameSite`. À défaut, risque à acter explicitement. | `frontend/src/auth/authStorage.ts` |
| F9 | **Haute** | Flask dev server + pas de TLS | Le serveur de dev Werkzeug n'est pas fait pour Internet (perf, robustesse). Sans HTTPS, tokens et mots de passe passent en clair. Indépendant de F1 (déjà résolu) : même avec `debug=False`, Werkzeug reste un serveur de dev. Le `Dockerfile` lance ce même dev server (`CMD python services/api_server.py`) — la conteneurisation n'a rien changé à F9 (cf. étape 5). | `api_server.py` (bloc `__main__`), `Dockerfile` |
| F15 | **Haute** | Backend conteneurisé injoignable + tournant en root | Constaté le 2026-08-10 : `app.run(host='127.0.0.1')` dans un conteneur n'écoute que sur le loopback **du conteneur** → ni le mapping `5001:5001` ni le `proxy_pass http://backend:5001/` de nginx ne l'atteignent. Et `docker-compose.yml` force `user: "0:0"`, ce qui annule le `USER appuser` du `Dockerfile` : le process tourne en root. | `Dockerfile`, `docker-compose.yml`, `frontend/Dockerfile` |
| F3 | Moyenne | CORS ouvert à toutes les origines | `CORS(app, ...)` sans `origins` = `*`. | `api_server.py` (appel `CORS(` au niveau module) |
| F10 | Moyenne | Traceback complet renvoyé au client | Le handler global d'exceptions renvoie type + message + traceback dans la réponse JSON → révèle chemins, structure du code, versions. Utile en dev, à désactiver en prod (log serveur uniquement). | `api_server.py` (`handle_uncaught_exception`) |
| F4 | Faible→Moyenne | Journal d'audit partiel | `auth_events` trace désormais tentatives, succès, échecs, refus et déconnexions avec l'IP réelle. Manquent les événements d'administration (aucun chemin de code aujourd'hui) et toute exploitation du journal. | `api_server.py` (`_record_auth_event`) |
| F5 | ✅ Résolu | Pas d'analyse automatisée | **Étape 6.** `scripts/security_check.sh` enchaîne bandit (dépôt entier moins une liste noire justifiée), `pip-audit --strict` sur le verrou de production et `npm audit --audit-level=high` ; sortie non nulle sur tout finding haut/critique, sur tout fichier non analysé et sur toute panne d'outil. Exceptions acceptées uniquement avec justification écrite. | `scripts/security_check.sh`, `scripts/security_audit_ignore.txt` |

---

## 3. Avis sur les sujets évoqués

### MFA
**Reporté, plus écarté.** Pour des tests publics avec quelques testeurs invités, des mots de passe forts + rate limiting + sessions expirantes suffisent. À implémenter (TOTP via `pyotp`) si le jeu passe en accès ouvert avec inscription libre. Réévaluation prévue à la fin du plan.

### Autorisation / RBAC
**Fait (étape 1).** Le mécanisme existait mais ne protégeait que 3 routes ; il est désormais appliqué **dans la porte `before_request`**, à chaque requête, avec les trois catégories décrites en étape 1 (`@changes_game_mode`, `@mode_agnostic`, défaut = mode courant).

### Audit
**Recommandé, sévérité remontée.** Exposé sur Internet, le journal d'audit (avec IP) est ton seul moyen de savoir si quelqu'un brute-force le login ou abuse de l'API.

### Analyse statique et dynamique
- **Statique : oui** — `bandit`, `pip-audit`, `npm audit` (étape 6, **faite**). NB : bandit aurait signalé le `pickle.load` (F7) dès l'origine — preuve de son utilité. Mesuré après correction de F7 : il ne signale plus `B301` sur `game_saves.py` (le dépickle passe par une sous-classe `pickle.Unpickler`, que bandit ne pointe pas) mais toujours `B403 import pickle`, en LOW. Ce finding est maintenu, non supprimé : aucun `# nosec` n'est posé, la justification écrite est en tête de `scripts/security_check.sh` et dans l'étape 6.
- **Dynamique : devient pertinent** avec l'exposition. Un scan OWASP ZAP en mode baseline contre l'instance de test, une fois les étapes 1–5 faites. Optionnel mais peu coûteux.

### Buffer overflow / gestion mémoire
**Non pertinent.** Python et TypeScript sont à mémoire managée ; le seul code natif (WASM LoS) est en Rust, memory-safe par construction. Redeviendrait pertinent uniquement si du C/C++ était introduit.

---

## 4. Plan d'implémentation

Ordre = priorité. **Les étapes 1 à 5 sont des prérequis absolus avant toute exposition Internet.**

> F1 (debugger Werkzeug exposé) est **résolu** (bloc `__main__` de `api_server.py` : `debug=False`, `host='127.0.0.1'`). L'étape 1 initiale (F1+F7+F11) a donc été scindée : l'auth globale (F6, ex-étape 2) est passée en premier — elle a supprimé l'exposition **anonyme** de F7/F11. L'étape 2 a ensuite fermé l'écriture arbitraire, supprimé `pick-directory` et restreint le dépickle des saves : F7 et F11 sont clos.

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
- le fichier de configuration de sauvegarde (`save_config`, JSON écrit à l'exécution) placé sous `_PERSIST_DIR` au lieu de `<repo>/logs/` en dur : sinon un déploiement pointant `W40K_PERSIST_DIR` hors du dépôt exigerait quand même un arbre de sources inscriptible. Chemin par défaut inchangé.
- `/api/game/pick-directory` **supprimée** (F11) — plus aucun `subprocess`/`powershell.exe` atteignable. Côté front : sélecteur natif, saisie manuelle du chemin et popup obligatoire au lancement retirés ; le répertoire s'affiche en lecture seule.
- Persistance pickle des snapshots **supprimée** : `pvp_snapshots.pkl` était écrit à chaque capture et **relu par aucun appelant** (`_load_snapshots_from_disk` était du code mort — la reprise passe par les saves). Il ne restait qu'un `pickle.dump` sans usage. Les snapshots de rewind vivent en mémoire, comme avant.
- Tests : `tests/unit/services/test_api_persist_dir.py` (rejet du `directory`, absence de la route, `.pkl` non écrit, résolution de `W40K_PERSIST_DIR`).

**Fait — désérialisation des saves : dépickle restreint**
`services/game_saves.py` (`_safe_loads`, `_ALLOWED_CLASSES`) relit chaque row en `pickle` sur le chemin Load/Select/Resume. Le format est conservé, mais toute désérialisation passe désormais par `_safe_loads` : un `pickle.Unpickler` dont `find_class` n'accepte que `_ALLOWED_CLASSES`. L'exécution de code au dépickle passe obligatoirement par `find_class` (opcode REDUCE sur un gadget type `os.system`) — privé de callable, le vecteur est fermé.
- Critère d'entrée dans la liste : constructeur de **données** uniquement (au pire un objet absurde, jamais un effet de bord). Aujourd'hui : `ParsedWeaponRule` et les trois entrées numpy (`ndarray`, `dtype`, `_reconstruct`, en double pour le renommage `numpy.core` → `numpy._core`).
- Écarté : **codec JSON typé** — mesuré sur un vrai état, il faudrait encoder 28 257 dicts à clés tuple (`occupation_map`), 3 056 tuples, 58 sets, des clés int et 389 objets `ParsedWeaponRule`, et casser le format des saves existantes, pour une surface d'attaque déjà nulle côté réseau. Écarté aussi : **signature HMAC** — ne protège que de qui peut écrire sans pouvoir lire la clé, là où la liste blanche tient même face à un accès disque complet.
- Limite assumée : un fichier falsifié peut toujours restituer un **état de jeu** faux (score, positions). Ce n'est pas de l'exécution de code, et cela suppose déjà un accès disque.
- Tests : `tests/unit/services/test_game_saves_restricted_unpickle.py` (gadget `os.system` refusé, contre-épreuve prouvant qu'il s'exécuterait sans le garde, chemin `SaveStore.point`) et `tests/integration/pvp/test_save_restricted_unpickle.py` (save d'une partie **réelle** relue à travers le garde — c'est ce test qui a révélé les entrées numpy manquantes).

**Validation :** requête POST avec `directory` → 400 ; `pick-directory` → 404 ; aucun `.pkl` écrit ; sauvegarde/rewind fonctionnels (runtime PvP à valider).

### Étape 3 — Durcissement des sessions (F2, F8) ✅ faite le 2026-08-10

**Sessions expirantes (F2)**
- `sessions.expires_at` INTEGER NOT NULL (et `created_at` passé en INTEGER : la colonne portait un entier dans un champ TEXT, où une comparaison est lexicographique et non numérique). TTL 7 jours.
- Migration : `_migrate_sessions_table` détecte l'absence de la colonne (`PRAGMA table_info`) et **DÉTRUIT puis recrée** la table. `ALTER TABLE ADD COLUMN` est écarté — SQLite exige un DEFAULT sur une colonne NOT NULL ajoutée, et ce DEFAULT survivrait à la migration : un INSERT futur omettant `expires_at` produirait une session à l'échéance arbitraire au lieu d'échouer (T1). Les tokens pré-existants sont révoqués : ce sont précisément ceux qui n'avaient aucune expiration.
- Validation : `AND s.expires_at > ?` dans la requête de la porte. Session échue = 401, **même message** qu'un token inconnu (distinguer les deux confirmerait à un attaquant que le token a existé).
- **Renouvellement glissant à seuil** (`SESSION_RENEW_AFTER_SECONDS`, 1 h) et non à chaque requête comme prévu initialement : la porte s'exécute jusqu'à ~40 fois par seconde sur les prévisualisations au survol, et renouveler à chaque passage transformerait chaque survol de souris en écriture SQLite, donc en verrou exclusif sur `users.db`. Effet utilisateur identique — une session active n'expire jamais — pour ~1 écriture par heure et par session.
- `/api/auth/logout` ajoutée (`@mode_agnostic`) : sans elle, l'expiration serait le seul moyen de tuer une session, et un token soupçonné volé resterait valide sept jours. Front : `logoutSession()` dans `apiFetch.ts` appelle le serveur **avant** d'effacer le `localStorage` et de rediriger — effacer le stockage local seul ne révoque rien.
- Purge des sessions échues au login (pas à chaque requête : ce serait la même écriture systématique que ci-dessus).

**Rate limiting du login (F8)**
- **Compteur maison en base**, et non `flask-limiter` comme prévu initialement. Motif : le stockage par défaut de `flask-limiter` est la mémoire du process, ce qui devient faux dès que l'étape 5 met un WSGI multi-workers — chaque worker aurait son compteur, donc N fois la limite réelle. Le compteur en base est juste avant comme après l'étape 5, et évite une dépendance.
- 5 tentatives par couple (login, IP) sur une fenêtre de 60 s → 429. Contrôlé **avant** la vérification du mot de passe : PBKDF2 à 200 000 itérations est le coût dominant, le laisser s'exécuter offrirait un déni de service en prime.
- Le plafond bloque le couple, y compris avec le **bon** mot de passe : sinon un attaquant qui le trouve passerait malgré la limitation. Un login réussi sous le plafond rend les tentatives antérieures non comptables.

#### Durcissement du 2026-08-10 (suite de `/code-review` et `/simplify`)

Trois défauts réels trouvés en revue, tous corrigés ; le lot a aussi remplacé la table de comptage.

- **IP du proxy prise pour celle du client — le plus grave.** `remote_addr` vaut la même valeur pour TOUS les utilisateurs dès qu'un proxy est devant, et il y en a toujours un : `vite.config.ts` en développement, le nginx de `frontend/Dockerfile` en conteneur. La clé (login, IP) dégénérait donc en (login) : cinq essais ratés suffisaient à verrouiller le compte de n'importe qui — la protection F8 se retournait en déni de service sur les comptes. `_client_ip()` lit désormais `X-Forwarded-For`, **uniquement** si la requête vient d'une adresse listée dans `W40K_TRUSTED_PROXIES`, en parcourant la chaîne de droite à gauche (la partie gauche est écrite par le client). Variable non définie = aucun proxy de confiance ; définie mais vide = erreur au démarrage. Un proxy de confiance qui ne pose pas l'en-tête lève une erreur explicite plutôt que de ranger tout le monde dans le même seau.
- **Comptage non atomique.** Le total était lu hors transaction, puis PBKDF2 s'exécutait, puis l'échec était écrit. Werkzeug crée un thread par requête : N tentatives simultanées lisaient toutes le même total, passaient toutes le plafond et lançaient toutes PBKDF2 — exactement le déni de service que le contrôle est censé empêcher. Comptage et inscription tiennent maintenant dans une seule transaction `BEGIN IMMEDIATE`, ce qui impose de poser le verrou d'écriture avant la lecture. La tentative est donc inscrite **avant** la vérification du mot de passe : c'est la condition pour qu'elle partage cette transaction.
- **Purge non indexée.** `WHERE attempted_at <= ?` ne pouvait pas se servir de l'index composite, dont ce n'était pas la colonne de tête : chaque échec balayait toute la table, sous verrou exclusif. Index dédié ajouté (vérifié à l'`EXPLAIN QUERY PLAN` : `SCAN` → `SEARCH`).

**`login_attempts` remplacée par `auth_events` (append-only).** L'ancienne table s'effaçait à la fenêtre du rate limiting (60 s) : elle ne pouvait donc pas servir de journal, et l'étape 7 aurait dû créer une seconde table quasi identique, avec deux écritures sur les mêmes chemins et deux versions de « qui a tenté de se connecter ». `auth_events(id, occurred_at, event, login, ip, details)` porte les deux usages. Le journal étant append-only, un succès ne peut plus **effacer** les tentatives : il les rend non comptables, via une borne sur l'`id` du dernier `login_success` (borne sur l'`id` et non sur l'horodatage — succès et échec peuvent tomber dans la même seconde). Rétention 30 jours, purgée au login réussi.

La **tentative** est distincte de son **issue** : `login_attempt` porte le comptage, `login_success` / `login_failure` portent la traçabilité. Sans cette séparation, chaque connexion réussie laissait dans le journal un échec provisoire qui n'avait jamais eu lieu. `rate_limited` est un événement à part : le compter comme une tentative ferait s'auto-prolonger le blocage indéfiniment, et il n'est écrit qu'**une fois par fenêtre** — sinon chaque requête refusée insérait une ligne, sur un chemin entièrement contrôlé par l'attaquant et sous le verrou d'écriture, ce qui faisait de la répétition un moyen de ralentir les logins légitimes. La rétention s'applique sur **toute** tentative, y compris refusée : cantonnée au login réussi, le seul chemin qui bornait la table était celui qu'un attaquant ne prend jamais.

**Conséquence assumée : six logins *simultanés* avec le bon mot de passe peuvent se refuser mutuellement.** Le compteur porte sur les tentatives et non sur les échecs — c'est ce qui permet de compter et d'inscrire dans la même transaction, donc de fermer la course. En séquentiel, aucun effet : chaque succès rend les tentatives précédentes non comptables. Il faut six connexions réellement concurrentes du même compte depuis la même IP, ce que le front ne produit pas. Revenir à un comptage d'échecs rouvrirait la course sur PBKDF2, qui est un vrai vecteur de déni de service — le compromis est pris dans ce sens en connaissance de cause.

**Le logout révoque avant de journaliser**, dans deux transactions distinctes. Réunies, `_client_ip()` pouvait lever (proxy de confiance sans en-tête exploitable) et le rollback annulait la révocation : l'utilisateur voyait un 500 en croyant s'être déconnecté, avec un token toujours valide.

**Les proxys de confiance sont validés au démarrage et comparés sur des adresses normalisées** (`ipaddress`). Une comparaison de chaînes distinguerait `::ffff:172.18.0.5` de `172.18.0.5` — la même adresse, rendue différemment selon la pile réseau — et un nom d'hôte accepté ne correspondrait jamais à `remote_addr` : dans les deux cas `X-Forwarded-For` serait ignoré **en silence**, ce qui restaure exactement le verrouillage de compte que le mécanisme empêche.

**Couche d'écriture partagée.** `auth_db_write_cursor()` (commit en sortie, rollback sur exception, fermeture garantie, `BEGIN IMMEDIATE` optionnel) répond au `auth_db_read_cursor()` existant, dont le docstring nommait déjà l'asymétrie. `login_user` comptait quatre `commit()` sur quatre sorties ; le commit vit maintenant à un seul endroit.

**Tests :** `tests/unit/services/test_api_session_hardening.py` (32 tests), **preuve rouge sur 23 verrous**. Quatre tests ne verrouillaient rien au moment de leur écriture et ont été corrigés : deux à la livraison initiale (l'un observait `expires_at` là où un renouvellement inutile réécrit la même valeur, l'autre ne consommait pas assez du budget d'échecs), un troisième a cessé de voir quoi que ce soit quand les écritures sont passées par le context manager — son compteur visait l'ancienne fonction — et le quatrième ne couvrait pas `BEGIN IMMEDIATE`, qui n'était donc verrouillé par rien. Un test compare désormais le schéma produit par `initialize_auth_db()` à celui du script de référence `Documentation/Memoire/Annexe_script_BDD_auth.sql`, qui avait divergé en silence.

**Validation :** token expiré forcé en SQL → 401 ; 6 logins ratés en rafale → 429 ; logout → token refusé immédiatement. Runtime PvP à valider (déconnexion depuis le menu).

### Étape 4 — Réduction de la surface d'information (F3, F10)
**Fichier :** `services/api_server.py`
- CORS : `origins` limité à l'URL du frontend, surchargeable par `W40K_CORS_ORIGINS` (liste séparée par virgules). Variable définie mais vide → erreur au démarrage.
- Handler d'exceptions : traceback dans la réponse JSON **uniquement si un flag de debug est actif** ; en prod, log serveur complet + réponse générique avec un identifiant d'erreur corrélable au log.
  > ⚠️ **Ne pas réutiliser `W40K_DEBUG` tel quel.** Cette variable existe déjà et pilote le **debug moteur** (`api_server.py` : `initialize_engine`, `execute_ai_turn` ; `engine/phase_handlers/fight_handlers.py` : `_fight_v11_log`), pas le format des réponses d'erreur. `docker-compose.yml` la met déjà à `"false"` : croire que la prod est donc protégée du traceback serait **faux** — le handler (`api_server.py`, `handle_uncaught_exception`) renvoie `"traceback"` inconditionnellement. Soit une variable distincte (`W40K_EXPOSE_TRACEBACK`), soit un élargissement assumé et documenté de `W40K_DEBUG` aux deux usages.
- Token de session (F13) : cible = cookie `HttpOnly`+`Secure`+`SameSite=Strict` au lieu de `localStorage` (immunise contre le vol par XSS). Chantier front + back non trivial ; si reporté, acter explicitement le risque en §5.

**Validation :** fetch cross-origin bloqué ; exception en prod → pas de traceback dans la réponse, traceback présent dans le log serveur.

### Étape 5 — Infrastructure d'exposition (F9, F15)

> ⚠️ **Ce n'est pas un chantier vierge.** Une stack Docker existe déjà dans le dépôt et n'était pas
> décrite ici (constaté le 2026-08-10). L'étape 5 est donc un **durcissement de l'existant**, pas une
> création. Ne pas repartir d'une feuille blanche : ce qui existe se corrige.

**État réel de la stack (vérifié dans les fichiers, 2026-08-10)**

| Fichier | Ce qu'il fait déjà | Écart à traiter |
|---|---|---|
| `Dockerfile` | Image python:3.11-slim, `requirements.runtime.txt`, `useradd appuser` + `USER appuser`, `EXPOSE 5001`, healthcheck sur `/api/health` | `CMD ["python", "services/api_server.py"]` = **dev server Werkzeug** (F9 intact) |
| `docker-compose.yml` | backend + frontend, `restart: unless-stopped`, `users.db`/`ai/models`/`runtime` montés en volumes, `W40K_DEBUG=false` | `user: "0:0"` **annule** le `USER appuser` → root (F15) ; `ports: 5001:5001` publie le backend en clair sur l'hôte |
| `frontend/Dockerfile` | Build Vite (`VITE_API_URL=/api`) puis nginx:1.27-alpine servant `dist/`, `proxy_pass` vers `backend:5001`, `X-Real-IP` et `X-Forwarded-For` posés | `listen 80` **seul** : aucun TLS, aucune redirection HTTP→HTTPS |

**À faire**
- Remplacer le `CMD` par un serveur WSGI de production : `waitress` (simple, pur Python) ou `gunicorn`, ajouté à `requirements.runtime.in` **puis verrou régénéré** (depuis l'étape 6, `requirements.runtime.txt` est généré — ne pas y écrire à la main). Le `app.run(...)` de `services/api_server.py` (bloc `__main__`, `serve_frontend` monté juste avant) reste le chemin de **développement local** (`host='127.0.0.1'` y est correct et doit le rester : c'est lui qui garantit qu'un lancement direct n'expose rien).
- Faire écouter le process de production sur `0.0.0.0` **à l'intérieur du conteneur uniquement** (via le WSGI, pas en modifiant `app.run`) — sans quoi ni nginx ni le mapping de port ne l'atteignent (F15).
- Retirer `user: "0:0"` du compose : le `USER appuser` du `Dockerfile` doit s'appliquer. Vérifier que `W40K_PERSIST_DIR` pointe alors sur un volume inscriptible par `appuser` (montage `runtime`), et que le reste de `/app` ne l'est pas.
- Retirer le `ports: 5001:5001` du backend : seul le frontend (nginx) doit être publié. Le backend reste joignable par le réseau interne compose.
- TLS sur nginx : certificat Let's Encrypt (companion certbot, ou bascule sur Caddy qui l'automatise), `listen 443 ssl`, redirection 80→443. La config nginx est aujourd'hui écrite en `printf` dans le `Dockerfile` — la sortir en fichier versionné avant de la complexifier.
- Ne jamais exposer : `config/users.db`, `ai/models/`, le repo git. NB : `COPY . /app` embarque **tout le dépôt** dans l'image, `.git` compris s'il n'est pas exclu — vérifier/écrire un `.dockerignore`.
- **Renseigner `W40K_TRUSTED_PROXIES`** avec l'adresse du conteneur nginx. Sans elle, `_client_ip()` retombe sur `remote_addr`, qui vaut l'IP du proxy pour tous les utilisateurs : le rate limiting du login perd sa composante IP et cinq essais ratés suffisent à verrouiller n'importe quel compte. L'en-tête `X-Forwarded-For` est déjà posé par le nginx du dépôt, c'est la déclaration côté backend qui manque.
- Le WSGI de production doit rester joignable en **TCP**. `_client_ip()` lève une erreur explicite si `remote_addr` est vide, ce qui est le cas sur un socket UNIX : un déploiement par socket casserait le login au premier appel.

**Validation :** `docker compose up` → frontend en HTTPS fonctionnel, HTTP redirigé, port 5001 **non** accessible depuis l'hôte, `docker exec ... whoami` → `appuser`, healthcheck vert.

### Étape 6 — Analyse statique automatisée (F5) ✅ Fait (2026-08-10)
**Fichiers :** `scripts/security_check.sh` (exécutable), `scripts/security_audit_ignore.txt`, `requirements-dev.txt`
- `bandit -r services/ engine/ ai/`, `pip-audit`, `cd frontend && npm audit --audit-level=high`.
- Dépendances dev (`bandit`, `pip-audit`) dans `requirements-dev.txt`, **hors** `requirements.runtime.txt` : ce dernier construit l'image de production, l'alourdir serait une régression.

**Périmètre bandit : le dépôt entier, moins une liste noire courte** (`tests/`, `node_modules/`, `frontend/node_modules/`, `frontend/dist/`, `.venv/`, `.git/`, `.claude/`, `Documentation/`), annoncée à chaque exécution. Le plan initial disait `services/ engine/ ai/` ; une **liste blanche** a été essayée puis abandonnée, parce qu'elle laisse hors scan tout fichier créé plus tard — `config/__init__.py` l'était déjà, et un futur module `loader` déposé dans `config/` avec un `shell=True` serait passé en vert. Avec une liste noire, le neuf est couvert par défaut : vérifié en déposant un `hashlib.md5` dans `config/`, la porte est passée au rouge.

Piège de ce basculement, corrigé : `bandit --exclude` **remplace** la liste d'exclusions par défaut de l'outil au lieu de s'y ajouter. Sans réinjection explicite, un venv nommé `venv/` (au lieu de `.venv/`), un `.tox/` ou un cache d'outillage retombaient dans le scan et faisaient échouer la porte sur du code tiers — mesuré : avec la liste noire seule, un fichier déposé dans `venv/` remonte en HIGH ; avec les défauts réinjectés, le script reste vert. Le script rappelle donc la liste par défaut de bandit (`.svn`, `CVS`, `.bzr`, `.hg`, `.git`, `__pycache__`, `.tox`, `.eggs`, `*.egg`) et y ajoute les variantes courantes ici (`venv/`, caches d'outillage). `tests/` est en outre sorti de l'image (`.dockerignore`), il n'est donc plus « embarqué mais non scanné ».

Effet immédiat du passage en liste noire : `frontend/src/roster/_HOW_TO_ADD_UNIT` a fait échouer le scan — il portait alors l'extension `.py` pour du **TypeScript** (il est en `.md` depuis). `pyrightconfig.json` avait dû l'exclure pour la même raison. Renommé en `.md`, et l'exclusion pyright supprimée : la cause est traitée, pas contournée deux fois.

**Seuils bloquants** (sortie non nulle, sinon le script serait décoratif) :
- bandit : sévérité **HIGH**, toutes confiances — **et** tout fichier que bandit n'a pas su analyser, ou un échec de l'outil (code > 1). Un scan planté rend un rapport à zéro finding : sans ce contrôle il se lirait comme un feu vert.
- pip-audit `--strict` : **toute** vulnérabilité de la surface de production (`requirements.runtime.txt`), hors exceptions justifiées **une par une** dans `scripts/security_audit_ignore.txt` — une ligne sans justification écrite fait échouer le script. `--strict` ferme côté pip-audit le même trou que `errors` côté bandit : sans lui, une dépendance dont la collecte échoue est simplement « skippée » (message de spinner, invisible hors terminal) et l'audit sort 0 sur une surface partielle. Le venv de développement est audité en parallèle mais **non bloquant** : son outillage local (jupyter, aider, pytest…) ne part pas dans l'image.

**Verrou de dépendances (2026-08-10).** Le portail n'a de sens que si le fichier audité est celui que le build installe. `requirements.runtime.txt` est donc devenu un **verrou complet généré** (56 paquets, transitives comprises), et les dépendances directes vivent dans `requirements.runtime.in`. Avant, seules les directes étaient épinglées : `Werkzeug`, `Jinja2`, `matplotlib`, `pillow`, `sympy`, `triton`, `nvidia-*` flottaient au build comme à l'audit, donc ni l'audit ni l'image n'étaient reproductibles. La résolution est faite pour le Python de l'image (`python:3.11-slim`, linux x86_64) — commande exacte en tête de `requirements.runtime.in`. Le `Dockerfile` n'est pas touché : il installe toujours `requirements.runtime.txt`.

Effet de bord corrigé au passage : `setuptools==84.0.0` est **réintroduit comme ligne explicite de `requirements.runtime.in`**, pas seulement présent dans le verrou. Le retrait du pin `>=70,<82` n'en supprimait que la borne haute (imposée par TensorBoard) ; sur `python:3.11-slim` plus rien ne le tire — `triton` 3.1.0 ne dépend que de `filelock`, et torch 2.5.1 ne le déclare que sous `python_version >= "3.12"`. Sans ligne explicite, une régénération faite depuis un vrai 3.11 le ferait **disparaître** du verrou et l'image retomberait sur le setuptools ancien de son image de base — invisible pour `pip-audit -r`, donc hors du portail.

**Limite connue de la commande de régénération**, mesurée : `pip --python-version 3.11` gouverne le choix des roues, mais l'évaluation des **marqueurs** suit l'interpréteur local. Résolue depuis un 3.12, elle a fait entrer `setuptools` par le marqueur `python_version >= "3.12"` de torch — d'où la ligne explicite ci-dessus, qui rend le verrou indépendant de l'interpréteur de résolution sur ce point. Le risque symétrique (un paquet requis seulement en 3.11 et absent du verrou) impose de contrôler la clôture du verrou après chaque régénération, ou de la refaire depuis un interpréteur 3.11 dès qu'il y en a un. C'est écrit dans l'en-tête de `requirements.runtime.in`.

**`scipy` manquait à la surface de production (2026-08-10).** Trouvé en auditant le verrou : `charge_handlers.py` (`charge_autoplace_plan`) et `fight_handlers.py` (`pile_in_autoplace_plan`) font un import **dur** de `scipy.optimize.milp` / `scipy.sparse`, atteint par l'action PvP `charge_autoplace` (`charge_handlers.py`, `execute_action`). `scipy` n'a jamais figuré dans `requirements.runtime.txt` — le défaut précède ce chantier : l'image répondait 500 sur cette action, et `pip-audit` ne voyait jamais scipy. Vérifié par exécution dans un venv sans le paquet : `ModuleNotFoundError: No module named 'scipy'`. Ajouté (`scipy==1.15.3`), verrou régénéré (57 paquets, seul ajout), audit toujours propre. La CI en hérite, puisqu'elle installe le verrou.

**Réduction de ce que l'image embarque (2026-08-10), `.dockerignore`.** Le `COPY . /app` n'excluait ni `config/users.db` (77 Ko de comptes et de hashes de mots de passe) ni `.claude/` (4,5 Go mesurés — les worktrees sont des copies complètes du dépôt). Le montage compose masque `users.db` à l'exécution, mais la copie reste lisible dans la couche d'image pour qui l'obtient. Exclusions ajoutées : `*.db` **et** `**/*.db` **et** `config/users.db` (les trois : Docker évalue les motifs avec `filepath.Match`, où `*` ne franchit pas un `/` — `*.db` seul ne couvrirait que la racine du contexte, pas `config/`), plus `.claude/` et `tests/`. Cette dernière rend au passage cohérent le périmètre bandit : `tests/` n'est plus « embarqué mais non scanné », il n'est plus embarqué du tout.

**Frontière image / tests (2026-08-10).** La CI installait le **verrou de production seul** puis lançait `pytest tests/unit` (`.github/workflows/unit-tests.yml`). Sortir `tensorboard` de l'image rendait donc la collecte pytest rouge : `ai/metrics_tracker.py` (`SummaryWriter`) fait, au niveau module, un `from torch.utils.tensorboard.writer import SummaryWriter` **non protégé** — contrairement à sb3 — et 12 fichiers de `tests/unit` importent ce module. Vérifié par exécution : sans le paquet, `import ai.metrics_tracker` lève `ImportError: TensorBoard logging requires TensorBoard version 1.15 or above`. Correctif : `requirements-test.txt` (pytest, pytest-cov, pytest-mock, tensorboard), et la CI installe `requirements.runtime.txt` **et** `requirements-test.txt`. L'image reste minimale, les tests déclarent ce qu'il leur faut.
- npm audit : `--audit-level=high` (high + critical), décidé sur le **rapport JSON**. `npm` sort en non-zéro aussi bien pour « j'ai trouvé des vulnérabilités » que pour « je n'ai pas pu auditer » (registre injoignable, lockfile absent) : le script lit `metadata.vulnerabilities` pour trancher et **arrête tout** si le rapport est absent, illisible ou porteur d'une erreur. Une panne d'outil n'est ni un feu vert, ni un problème de dépendances.

**Findings traités :**
- 3× bandit HIGH `B324` (SHA-1/MD5) — `ai/train.py` (`_materialize_scenario_with_refs`), `ai/bot_evaluation.py` (`_materialize_eval_scenario_refs`, `_episode_seed`) : usages non cryptographiques (nom de fichier de cache, graine déterministe). Corrigés par `usedforsecurity=False`, qui laisse le digest **inchangé** (vérifié) : ni les noms de cache ni les graines ne bougent. Aucun `# nosec`.
- pip-audit `PYSEC-2026-2151` (Flask 3.1.2, `Vary: Cookie` absent quand la session est lue → empoisonnement de cache sur des réponses porteuses de session) : Flask passé à **3.1.3** dans `requirements.runtime.in` (donc dans le verrou) et dans `requirements.txt`.
- npm audit : 2 critical + 8 high (dont `react-router-dom`, seul de la liste à partir dans le bundle livré) résolus par `npm audit fix` — `package.json` inchangé, seul `package-lock.json` bouge. Revalidé : `npm ci`, `tsc --noEmit`, `npm run build` verts.

**Pickle — justification écrite du finding maintenu (cf. §3, « l'écarter demandera une justification écrite, pas un `# nosec` muet ») :** bandit signale `B403 import pickle` sur `services/game_saves.py` (`_safe_loads` en aval), en LOW. Le format pickle est **conservé** ; le vecteur d'exécution est fermé par `_safe_loads`, un unpickler à liste blanche de classes (étape 2 / F7). Ce finding n'est ni supprimé ni masqué : aucun `# nosec` n'est posé, il réapparaît à chaque exécution du script, il est simplement sous le seuil bloquant. Le raisonnement est écrit en tête de `scripts/security_check.sh`.

**Findings non bloquants restants** (LOW/MEDIUM, laissés en l'état sciemment) — 131 au total sur le périmètre élargi, dont 13 MEDIUM :
- `B301 pickle.load` ×4 sur des artefacts locaux de training (`ai/vec_normalize_utils.py` : `normalize_observation_for_inference` ; `ai/bot_evaluation.py` : `_build_eval_obs_normalizer_for_worker` ; `engine/pve_controller.py` : `PvEController` ; `engine/action_decoder.py` : `ActionDecoder`).
- `B108` ×5 (chemin `/tmp` en dur) dans les bancs d'essai `scripts/ab_bench*.py`, `scripts/ab_sweep_nenvs.py` — outillage de mesure local, jamais exécuté par le serveur.
- `B302 marshal` ×1 (`scripts/profile_env_step_360x312.py`, `_top_cum_functions`) et `B310 urlopen` ×3 (`scripts/pvp_smoke_test.py`, `ApiClient`, URL construite dans le script vers `127.0.0.1`) — scripts de profilage et de smoke test, hors chemin serveur.
- LOW : 53× `B311 random` (aléatoire de jeu, non cryptographique), 17× `B101 assert`, 8× `B110`, 1× `B112`, 5× `B105` (faux positifs : `PASS = "PASS"`, regex nommées `_TOKEN`), `B403`/`B404`/`B603`/`B607` sur des `subprocess.run([...])` à arguments constants, sans shell.
- npm : 2 `qs` moderate.

**Exceptions torch — prémisse corrigée (2026-08-10).** La justification écrite dans `scripts/security_audit_ignore.txt` disait d'abord « les poids viennent de l'image ». C'est **faux** : `.dockerignore` exclut `ai/models/`, et les poids arrivent par un montage hôte (`${SYNO_MODELS_PATH}:/app/ai/models`, `docker-compose.yml:18`). Ce qui reste établi, et qui est désormais ce qui est écrit : les observations sont construites côté serveur, jamais reçues du client, et **aucune route de `services/api_server.py` n'écrit dans `ai/models`** (grep : 0 occurrence) — le contenu du montage dépend de l'opérateur. La fermeture définitive du vecteur n'est pas cette liste, c'est torch ≥ 2.6 (`torch.load` en `weights_only=True`).

**Vecteur fermé, exceptions supprimées (2026-08-11).** La montée est faite : **torch 2.13.0, sb3 et sb3-contrib 2.9.0**. `scripts/security_audit_ignore.txt` ne contient **plus aucune exception** — `pip-audit --strict` sur le verrou rend « No known vulnerabilities found » sans rien ignorer. Les 19 CVE torch ne sont pas acceptées autrement : elles n'existent plus sur la surface, et le dépickle restreint de `torch.load` ferme ce qu'elles visaient.

Ce que ce mode impose : `weights_only=True` refuse les scalaires numpy des checkpoints sb3. `shared/torch_safe_globals.py` autorise `numpy._core.multiarray.scalar`, `numpy.dtype` et l'ensemble **fermé** des classes de dtype numpy — rien d'autre. Un « jeu minimal » de deux entrées avait d'abord été retenu : il tenait sur les modèles Armageddon et **échouait** sur les CoreAgent, qui portent des `Float64DType`. Le jeu nécessaire dépend des dtypes présents dans chaque checkpoint, donc un ensemble fermé vaut mieux qu'une liste rallongée à chaque modèle qui casse. Ce sont des descripteurs de type, pas des appelables : les autoriser ne rouvre pas ce que `weights_only=True` ferme. Le module est appelé au niveau **module** dans les cinq fichiers qui chargent un modèle (`ai/train.py`, `ai/bot_evaluation.py`, `ai/env_wrappers.py`, `ai/replay_converter.py`, `engine/pve_controller.py`) et dans `tests/conftest.py` : un nouveau site de chargement dans l'un d'eux est couvert sans rien ajouter. **Ce qu'il ne faut pas faire à la place** : repasser `weights_only=False`, qui rouvrirait l'exécution de code arbitraire au chargement d'un `.zip` de modèle. La liste blanche est, côté modèles, le pendant de `_safe_loads` côté sauvegardes.

Gain collatéral : sb3 2.9 n'impose plus `matplotlib`, donc `pillow` sort de la surface de production — avec les 26 vulnérabilités qu'il y traînait. Le verrou passe de 57 à 55 paquets.

**Validation de la montée, exécutée le 2026-08-11 — rien n'est resté supposé :**
1. Chargement des 50 `.zip` de `ai/models/` : 22 OK, 28 `KeyError` d'espace d'observation périmé (défaut **préexistant**, identique sous torch 2.5.1), **zéro `UnpicklingError`**.
2. Évaluation réelle (`--test-only`, 60 épisodes sur GPU) : combined **0.86**, `vs_control` 0.80. Ce chiffre dit que les poids sont fonctionnellement intacts, pas seulement rechargeables — un modèle mal désérialisé ne bat pas `greedy` 10-0.
3. Entraînement réel (`x1_debug`, 96 épisodes, 48 environnements vectorisés) : `learn` va au bout, VecNormalize écrit, modèle sauvé, **0 troncature**. C'est la surface sb3 2.6 → 2.9 qui pouvait avoir bougé — callbacks de schedule, dimensionnement du rollout buffer (`n_steps=170` par env), metrics tracker, TensorBoard.

Deux avertissements nouveaux, tous deux bénins et propres à torch 2.13 : un *graph break* de `torch.compile` sur `ai/pointer_policy.py:406` (une garde `bool(torch.all(...))` que dynamo ne sait pas capturer — coût de compilation, la garde fonctionne), et `Not enough SMs to use max_autotune_gemm` (inductor constate que la RTX 4060 Laptop n'a pas assez de multiprocesseurs pour son auto-tuning le plus agressif).

**Allègement de l'image de production (2026-08-10), mesuré :** `tensorboard`, le pin `setuptools<82`, `torchvision` et `torchaudio` sont sortis de `requirements.runtime.in`. Preuve : `torchvision`/`torchaudio` n'ont **aucun** `import` dans le dépôt et ne sont jamais chargés ; le chemin serveur complet (engine, services, `ai.unit_registry`, `sb3_contrib`) a été importé et un modèle chargé dans un venv **sans** tensorboard — sb3 protège son import (`try: from torch.utils.tensorboard import SummaryWriter / except ImportError`). Conséquence : `PYSEC-2026-3447` (setuptools) disparaît de la liste d'exceptions, il n'en reste que torch.

**Purge du `package.json` racine (2026-08-10) :** ce fichier déclarait `react-scripts` et une pile CRA jamais installée (`node_modules/` à la racine est un **symlink** vers `frontend/node_modules`, posé par `scripts/link-root-node-modules.mjs`). Seul son `package-lock.json`, resté figé sur CRA, faisait remonter 2 critical + ~30 high à `npm audit` lancé depuis la racine, sur du code non déployé. Lockfile supprimé, `package.json` réduit à ses scripts réellement utilisés (biome + wrappers Python). Vérifié : `npx biome check frontend/src` (328 fichiers) et `npm run` inchangés. Piège mesuré en bac à sable : un `npm install` lancé **à la racine** supprime le symlink `node_modules` (`npm warn reify Removing non-directory …`) sans toucher au contenu réel de `frontend/node_modules` ; se rattrape par `npm --prefix frontend install`, dont le `postinstall` repose le lien. Comportement identique avant et après cette purge — ne pas lancer `npm install` à la racine.

**Validation :** script exécutable, exécuté, sortie 0. Réactivité de **chaque** porte prouvée en remettant le défaut, puis rétablie : SHA-1 sans `usedforsecurity` → rouge ; fichier à erreur de syntaxe déposé dans `shared/` → rouge (`bandit n'a pas pu analyser …`) ; ligne sans justification dans `security_audit_ignore.txt` → rouge, y compris indentée ; `Flask==3.1.2` → rouge ; `--audit-level=moderate` → rouge. Contrôle inverse : commentaires indentés (espaces **et** tabulations) et lignes vides de tabulations dans le fichier d'exceptions → vert, alors qu'ils faisaient échouer le script auparavant.

**Non vérifié :** l'effet propre de `pip-audit --strict`. Le drapeau est celui que documente pip-audit pour empêcher qu'une dépendance non collectée soit ignorée en silence, mais je n'ai pas su construire un cas qui distingue les deux modes — un paquet inexistant sort en 1 avec **et** sans `--strict`.

### Étape 7 — Journal d'audit (F4) 🟨 socle posé le 2026-08-10

**Déjà fait (livré avec le durcissement de l'étape 3, pas en anticipation gratuite : le rate limiting avait besoin des mêmes lignes)**
- Table `auth_events (id, occurred_at, event, login, ip, details)` dans `users.db`, **append-only**, rétention 30 jours.
- Événements écrits : `login_attempt`, `login_success`, `login_failure`, `rate_limited`, `logout`.
- IP réelle derrière le reverse proxy : `_client_ip()` lit `X-Forwarded-For` uniquement depuis un proxy listé dans `W40K_TRUSTED_PROXIES`, chaîne parcourue de droite à gauche.

**Reste à faire**
- Événements `user_created`, `profile_changed`, `password_changed` : ils n'ont aujourd'hui **aucun chemin de code** — les comptes sont créés à la main en SQL (décision F12). Ils n'apparaîtront que le jour où une route d'administration existera ; les écrire avant serait du code mort.
- Exploitation : au minimum une requête ou un petit script de lecture du journal. Une table que personne ne lit ne détecte rien.
- Renseigner `W40K_TRUSTED_PROXIES` au déploiement (étape 5) — sans lui, l'IP journalisée est celle du proxy pour tout le monde.

**Validation :** login réussi + raté → lignes correspondantes avec l'IP du client, pas celle du proxy.

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
| 1. Auth sur toutes les routes | F6, F12, F14 | ✅ Fait — vérifié dans le code le 2026-08-10 (30 routes, porte globale, `register` supprimée, `apiFetch`) | 2026-08-02 |
| 2. Fermer vecteurs écriture/désérialisation | F7, F11 | ✅ Fait (runtime PvP validé) | 2026-08-10 |
| 3. Durcissement sessions + rate limiting | F2, F8 | ✅ Fait, puis durci sur deux passes de revue (32 tests, preuve rouge sur 23 verrous ; runtime PvP à valider) | 2026-08-10 |
| 4. Réduction surface d'information | F3, F10, F13 | ⬜ À faire | — |
| 5. Infra d'exposition (WSGI + proxy + TLS) | F9, F15 | 🟨 Partiel — stack Docker + nginx existante (non documentée jusqu'au 2026-08-10), mais dev server, root et sans TLS ; **ne pas déployer en l'état** | — |
| 6. Analyse statique | F5 | ✅ Fait — `scripts/security_check.sh` exécuté, sortie 0 ; traités : 3 bandit HIGH, Flask 3.1.3, 10 npm high/critical, `scipy` manquant en production, `users.db`/`.claude` cuits dans l'image, et les 19 CVE torch **supprimées** par la montée 2.13.0/sb3 2.9.0 du 2026-08-11 — `security_audit_ignore.txt` est vide | 2026-08-11 |
| 7. Journal d'audit | F4 | 🟨 Socle posé (`auth_events` append-only + IP réelle) ; reste les événements d'administration et l'exploitation | 2026-08-10 |
| 8. Passe finale (ZAP, MFA ?, comptes) | — | ⬜ À faire | — |

**Jalon : ne pas exposer sur Internet avant la fin de l'étape 5.**
