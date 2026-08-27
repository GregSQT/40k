# Sécurité — Analyse et plan d'implémentation

> Date : 2026-07-15 — mise à jour **2026-08-18** : étapes **4, 5 et 7 livrées**, étape 8 partielle.
> **Les quinze failles F1–F15 sont résolues.** Ce qui reste n'est plus du code mais trois actions
> de déploiement, listées au bas de ce fichier (§6) : changer le mot de passe du compte `greg`
> (trouvé trivial par l'audit de l'étape 8), fournir les certificats TLS et exécuter
> `docker compose up`, valider en navigateur le passage au cookie de session.
>
> Historique : étapes 1, 2, 3 faites le 2026-08-02/10 (F1, F2, F6, F7, F8, F11, F12, F14) ;
> étape 3 durcie après revue (IP réelle du client, comptage atomique, journal `auth_events`
> append-only) ; étape 6 faite le 2026-08-11 (`scripts/security_check.sh`, verrou de dépendances
> de production, montée torch 2.13/sb3 2.9, F5).
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
- **Backend + modèles IA** : c'est là qu'est la valeur (moteur de règles, agents entraînés). Ce code ne quitte jamais le serveur **sauf si** un attaquant obtient une exécution de code ou une lecture de fichiers arbitraire. Toute la stratégie consiste donc à fermer ces vecteurs — F1, F6, F7 et F11 sont résolus (étapes 1 et 2) : plus d'exécution de code ni d'écriture disque atteignables depuis le réseau. L'étape 3 a fermé la session éternelle et le brute-force, les étapes 4 et 5 l'exposition et le transport (TLS, WSGI de production, backend non publié, traceback fermé). Aucun vecteur de prise de contrôle du serveur ne reste ouvert dans le code.

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
| F13 | ✅ Résolu | Token de session en `localStorage` | Étape 4 : le token est porté par un cookie `HttpOnly` + `SameSite=Strict` (+ `Secure` en HTTPS), hors de portée de JavaScript ; `localStorage` ne garde plus que l'identité et les permissions, et l'ancienne clé est effacée à l'import. En-tête anti-CSRF exigé sur toute authentification par cookie. | `api_server.py` (`_attach_session_cookie`, `_extract_session_token`), `frontend/src/auth/authStorage.ts`, `frontend/src/services/apiFetch.ts` |
| F9 | ✅ Résolu | Flask dev server + pas de TLS | Étape 5 : `services/wsgi.py` (waitress) remplace le dev server dans le `CMD` ; nginx sert en `listen 443 ssl` (TLS 1.2/1.3) et redirige le port 80. Le `app.run(host='127.0.0.1')` du bloc `__main__` reste, volontairement, le chemin de développement. | `services/wsgi.py`, `Dockerfile`, `frontend/nginx.conf` |
| F15 | ✅ Résolu | Backend conteneurisé injoignable + tournant en root | Étape 5 : écoute sur `0.0.0.0` **dans le WSGI** (pas dans `app.run`), `user: "0:0"` retiré du compose (le `USER appuser` s'applique), `ports: 5001:5001` retiré (seul nginx est publié). | `services/wsgi.py`, `docker-compose.yml` |
| F3 | ✅ Résolu | CORS ouvert à toutes les origines | Étape 4 : `origins=CORS_ORIGINS`, liste explicite validée au démarrage (vide, `*` et origine sans schéma refusés). | `api_server.py` (`_resolve_cors_origins`, appel `CORS(`) |
| F10 | ✅ Résolu | Traceback complet renvoyé au client | Étape 4 : traceback dans le log serveur uniquement, sauf `W40K_EXPOSE_TRACEBACK` (tri-état, non définie = fermé, rouverte par le lancement de développement). Réponse générique + `error_id` corrélable. | `api_server.py` (`handle_uncaught_exception`, `_resolve_expose_traceback`) |
| F4 | ✅ Résolu | Journal d'audit partiel | Étapes 3 et 7 : `auth_events` trace tentatives, succès, échecs, refus et déconnexions avec l'IP réelle, et `scripts/auth_journal.py` l'exploite (agrégats, détection de balayage de comptes, code de sortie non nul). Les événements d'administration restent sans chemin de code : les écrire serait du code mort. | `api_server.py` (`_record_auth_event`), `scripts/auth_journal.py` |
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

Ordre = priorité. **Les étapes 1 à 5 étaient des prérequis absolus avant toute exposition Internet : elles sont livrées.** Ce qui suit garde le détail de chaque livraison — le motif d'une décision est aussi utile après coup qu'avant.

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

**Tests :** `tests/unit/services/test_api_session_hardening.py` (32 tests), **preuve rouge sur 23 verrous**. Quatre tests ne verrouillaient rien au moment de leur écriture et ont été corrigés : deux à la livraison initiale (l'un observait `expires_at` là où un renouvellement inutile réécrit la même valeur, l'autre ne consommait pas assez du budget d'échecs), un troisième a cessé de voir quoi que ce soit quand les écritures sont passées par le context manager — son compteur visait l'ancienne fonction — et le quatrième ne couvrait pas `BEGIN IMMEDIATE`, qui n'était donc verrouillé par rien. Un test compare désormais le schéma produit par `initialize_auth_db()` à celui du script de référence `Documentation/Memoire RNCP/Annexe_script_BDD_auth.sql`, qui avait divergé en silence.

**Validation :** token expiré forcé en SQL → 401 ; 6 logins ratés en rafale → 429 ; logout → token refusé immédiatement. Runtime PvP à valider (déconnexion depuis le menu).

### Étape 4 — Réduction de la surface d'information (F3, F10, F13) ✅ faite le 2026-08-18

**CORS (F3).** `origins` est désormais une liste explicite (`CORS_ORIGINS`, `_resolve_cors_origins`), surchargeable par `W40K_CORS_ORIGINS`. Trois refus **au démarrage**, pas à l'usage : variable définie mais vide, entrée `*`, entrée sans schéma (`exemple.tld`). Le joker est refusé nommément parce que Flask-CORS accepterait `supports_credentials=True` avec lui dans certaines configurations, et que le cookie de session part désormais avec les identifiants : `*` rendrait toute page du web capable de lire l'API au nom de l'utilisateur connecté, soit F3 réintroduite par configuration. Défaut hors variable : les deux origines du serveur Vite (`http://localhost:5175`, `http://127.0.0.1:5175`), rien d'autre.

**Traceback (F10).** `handle_uncaught_exception` écrit toujours le traceback complet dans le **log serveur**, et ne le met dans la réponse que si `EXPOSE_TRACEBACK` l'autorise. La réponse fermée ne porte ni `str(error)` ni `error_type` — un message d'exception porte régulièrement un chemin, une requête SQL ou un nom de classe interne — mais un `error_id` (12 hex) présent aussi dans le log : sans lui, fermer le traceback rendrait tout incident non diagnosticable à partir d'un rapport d'utilisateur.

`W40K_DEBUG` n'a **pas** été réutilisée, conformément à l'avertissement ci-dessus : variable distincte `W40K_EXPOSE_TRACEBACK`. Elle est **tri-état** (`_resolve_expose_traceback` rend `None`/`True`/`False`) et non booléenne : non définie vaut FERMÉ, et c'est le bloc `__main__` — le lancement de développement — qui la rouvre. Un booléen simple aurait obligé à choisir entre « le développement perd son diagnostic » et « la production expose par défaut ». Le tri-état permet en outre à un `W40K_EXPOSE_TRACEBACK=false` posé exprès de ne pas être écrasé par le lancement de dev. Une valeur illisible est une erreur au démarrage : interprétée comme vraie, elle serait la fuite.

**Session en cookie `HttpOnly` (F13) — faite, pas reportée.** Le token ne va plus en `localStorage`.
- Backend : `SESSION_COOKIE_NAME` posé par `login_user` (`_attach_session_cookie`), effacé par `logout_user` (`_clear_session_cookie`), attributs `HttpOnly` + `SameSite=Strict` + `Path=/`.
- `Secure` est **conditionnel** (`_request_is_https`) : le poser en HTTP ferait purement ignorer le cookie par le navigateur et casserait le login du poste de développement. En production, TLS se termine sur nginx et le tronçon interne est en clair — `request.is_secure` rendrait donc toujours faux ; c'est `X-Forwarded-Proto` qui tranche, lu **uniquement** depuis un proxy listé dans `W40K_TRUSTED_PROXIES`, comme `X-Forwarded-For`.
- **CSRF.** Un cookie part avec toute requête vers l'origine, y compris déclenchée par un autre site — là où `Authorization` doit être posé, donc suppose de détenir le token. Deux verrous : `SameSite=Strict`, et l'en-tête `CSRF_HEADER_NAME` (`X-W40K-Client`) exigé sur toute authentification **par cookie**. Un `<form>` cross-site ne peut poser aucun en-tête personnalisé, et un `fetch` cross-site qui en pose déclenche un préflight que `CORS_ORIGINS` refuse. Seule la présence est contrôlée : ce n'est pas un secret, c'est la preuve que la requête vient du JS de notre origine. La valeur est déclarée **deux fois** (Python et TypeScript, pas de constante partageable) ; un test lit la source du front pour interdire la dérive, dont la panne serait un 401 sur tout appel.
- **Le cookie est prioritaire sur `Bearer`**, même valide. Pour le navigateur, un cookie périmé signifie que l'utilisateur est réellement déconnecté ; le repêcher par l'autre canal serait le repli que T1 interdit.
- Le chemin `Bearer` **reste** (`_extract_session_token` → `_extract_bearer_token`) : ce n'est pas un repli mais un second chemin métier, celui des clients sans bocal à cookies (`scripts/pvp_smoke_test.py`, tests d'API). Le corps de la réponse de login continue donc de porter `access_token` — le front, lui, ne le stocke plus, et le corps d'une réponse ne se relit pas après coup.
- **Le cookie glisse avec la session** (`_slide_session_cookie`, `after_request`). L'échéance serveur est glissante (F2) ; sans cela le cookie garderait celle du login et le navigateur déconnecterait un utilisateur actif au septième jour. Reposé seulement quand un renouvellement a réellement eu lieu (≈ 1×/h) et seulement pour un appelant authentifié par cookie. `logout_user` annule ce glissement avant de répondre : la porte a pu le programmer avant que la vue ne décide de révoquer.
- Frontend : `authStorage.ts` ne garde que l'identité et les permissions (contexte de **routage**, revalidé côté serveur à chaque requête). La clé de stockage passe à `w40k_auth_session_v2` et **l'ancienne est effacée à l'import** : cesser de lire le token ne suffisait pas, il fallait le retirer des postes déjà connectés, où il reste valide sept jours.

**Limite assumée, écrite ici plutôt que découverte plus tard :** `HttpOnly` empêche l'**exfiltration** du token par XSS, pas l'usage de la session par un script injecté dans la page (le navigateur joint le cookie tout seul). C'est le bénéfice attendu du mécanisme et celui que visait F13 — « volable par tout XSS » — pas une immunité à l'XSS.

**Validation :** `tests/unit/services/test_api_information_surface.py` (35 tests), preuve ROUGE sur 13 verrous (joker CORS, origine étrangère, traceback fermé par défaut, valeur illisible refusée, `HttpOnly`, `Secure` derrière proxy, proxy non déclaré, en-tête anti-CSRF, priorité du cookie, effacement au logout, glissement, absence de cookie pour un client `Bearer`, synchronisation du nom d'en-tête front/back). Runtime navigateur à valider (login, jeu, déconnexion).

### Étape 5 — Infrastructure d'exposition (F9, F15) ✅ faite le 2026-08-18

> ⚠️ **Ce n'était pas un chantier vierge.** Une stack Docker existait déjà dans le dépôt et n'était
> pas décrite ici (constaté le 2026-08-10). L'étape 5 a donc **durci l'existant** au lieu de repartir
> d'une feuille blanche. Le tableau ci-dessous est l'état de DÉPART, gardé parce qu'il explique
> pourquoi chaque correctif ressemble à ce qu'il est.

**État de départ (vérifié dans les fichiers le 2026-08-10) — les trois écarts sont fermés**

| Fichier | Ce qu'il faisait déjà | Écart, et ce qui l'a fermé |
|---|---|---|
| `Dockerfile` | Image python:3.11-slim, `requirements.runtime.txt`, `useradd appuser` + `USER appuser`, `EXPOSE 5001`, healthcheck sur `/api/health` | `CMD ["python", "services/api_server.py"]` = **dev server Werkzeug** (F9) → `CMD ["python", "-m", "services.wsgi"]` |
| `docker-compose.yml` | backend + frontend, `restart: unless-stopped`, `users.db`/`ai/models`/`runtime` montés en volumes, `W40K_DEBUG=false` | `user: "0:0"` **annulait** le `USER appuser` → root (F15) ; `ports: 5001:5001` publiait le backend en clair → les deux **retirés** |
| `frontend/Dockerfile` | Build Vite (`VITE_API_URL=/api`) puis nginx:1.27-alpine servant `dist/`, `proxy_pass` vers `backend:5001`, `X-Real-IP` et `X-Forwarded-For` posés | `listen 80` **seul**, aucun TLS → config sortie en `frontend/nginx.conf`, `listen 443 ssl` + redirection 80→443 |

**Fait le 2026-08-18**

- **`services/wsgi.py`**, lancé par le `CMD` du `Dockerfile` (`python -m services.wsgi`). **waitress**, et le choix n'est pas de goût : le moteur de jeu est une **globale de process** (`api_server.engine`, `_ENGINE_STATE_LOCK` = `RLock` de threads). Gunicorn en mode par défaut lance N *processus* — chaque worker aurait sa propre partie, et deux requêtes consécutives du même joueur tomberaient sur deux états différents. Le jeu serait cassé, pas ralenti. waitress sert en threads dans un processus unique : exactement la sémantique du serveur de développement, donc aucun invariant du moteur ne bouge. `waitress==3.0.2` ajouté à `requirements.runtime.in`, **verrou régénéré** (55 → 56 paquets ; seuls autres mouvements : `charset-normalizer` et `filelock` d'un correctif). `ident=None` : waitress annonce sinon sa version dans l'en-tête `Server`.
- Écoute sur `0.0.0.0` **dans `services/wsgi.py` uniquement** (F15). Le `app.run(host='127.0.0.1')` du bloc `__main__` est **inchangé** et doit le rester : c'est lui qui garantit qu'un lancement direct sur le poste de développement n'expose rien.
- `user: "0:0"` **retiré** du compose : le `USER appuser` du `Dockerfile` s'applique de nouveau. `W40K_PERSIST_DIR=/app/runtime` est posé explicitement — le défaut (`logs/` dans l'arbre des sources) n'est plus inscriptible sans root. ⚠️ **Au déploiement** : les montages hôte `SYNO_RUNTIME_PATH` et `config/users.db` doivent appartenir à l'UID d'`appuser`, sinon le backend démarre et échoue à la première écriture (session, journal d'auth).
- `ports: 5001:5001` **retiré** : il publiait le backend **en clair** à côté d'un frontend TLS — mots de passe et cookie de session en clair sur l'hôte, et la porte d'authentification joignable hors du proxy. Le backend reste joignable par le réseau interne. Ne pas le remettre pour déboguer : `docker compose exec backend` suffit.
- **`frontend/nginx.conf`**, fichier versionné, remplace le `printf` du `Dockerfile`. `listen 443 ssl` + `http2`, TLS 1.2/1.3 uniquement, redirection 301 depuis le port 80, `server_tokens off`, HSTS (`max-age` volontairement court — 1 jour — tant que le déploiement est en phase de test : une erreur de certificat se corrige alors en un jour et non en six mois), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: same-origin`. `proxy_read_timeout 180s` : un tour d'IA dépasse le défaut de 60 s.
- **Certificats montés, jamais cuits dans l'image** (`SYNO_TLS_PATH` → `/etc/nginx/certs:ro`) : une clé privée dans une couche d'image est lisible par quiconque obtient l'image. nginx refuse de démarrer s'ils manquent — voulu, un démarrage en clair « pour dépanner » est exactement ce que cette étape ferme. Let's Encrypt (certbot/Caddy) reste à câbler au déploiement réel ; pour un essai local, une paire auto-signée suffit :
  `openssl req -x509 -newkey rsa:2048 -nodes -days 365 -keyout privkey.pem -out fullchain.pem -subj "/CN=localhost"`.
- **`W40K_TRUSTED_PROXIES` renseignée** (`172.28.0.10`). Comme `_resolve_trusted_proxies` n'accepte que des adresses IP (un nom d'hôte ne correspondrait jamais à `remote_addr`) et qu'un réseau compose par défaut attribue les adresses dynamiquement, le compose déclare un **réseau à sous-réseau fixe** (`172.28.0.0/24`) et une `ipv4_address` fixe pour nginx. Une adresse dynamique ferait ignorer `X-Forwarded-For` **en silence** au premier redémarrage qui change l'attribution — et le verrouillage de compte reviendrait sans alerte. Élargir la confiance à tout le sous-réseau a été écarté : une seule adresse est de confiance, autant le dire.
- `W40K_CORS_ORIGINS` posée depuis `W40K_PUBLIC_ORIGIN` (obligatoire, `:?`).
- `.dockerignore` **déjà conforme** (vérifié) : `.git`, `config/users.db` (3 motifs), `.claude/`, `tests/`, `ai/models/`. Rien à ajouter.
- Le WSGI reste joignable en **TCP** (waitress sur `host`/`port`, pas de socket UNIX) : `_client_ip()` lève si `remote_addr` est vide, ce qui casserait le login au premier appel.

**Finding bandit assumé, justification écrite (pas de `# nosec`) :** `B104 hardcoded_bind_all_interfaces` sur `services/wsgi.py` — `host="0.0.0.0"`. C'est précisément le correctif de F15 : écouter sur le loopback du conteneur rendait le backend injoignable par nginx. L'exposition réelle est fermée en amont (aucun port publié pour le backend), pas par l'adresse d'écoute. MEDIUM, donc sous le seuil bloquant ; le finding réapparaît à chaque exécution et n'est pas masqué.

**Validation — ce qui reste à exécuter sur une vraie stack :** `docker compose up` → frontend en HTTPS fonctionnel, HTTP redirigé, port 5001 **non** accessible depuis l'hôte, `docker exec ... whoami` → `appuser`, healthcheck vert. Non exécuté ici : cette session n'a pas de démon Docker ni de certificats.

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

**Exceptions torch — prémisse corrigée (2026-08-10).** La justification écrite dans `scripts/security_audit_ignore.txt` disait d'abord « les poids viennent de l'image ». C'est **faux** : `.dockerignore` exclut `ai/models/`, et les poids arrivent par un montage hôte (`${SYNO_MODELS_PATH}:/app/ai/models`, dans le bloc `volumes` de `docker-compose.yml`). Ce qui reste établi, et qui est désormais ce qui est écrit : les observations sont construites côté serveur, jamais reçues du client, et **aucune route de `services/api_server.py` n'écrit dans `ai/models`** (grep : 0 occurrence) — le contenu du montage dépend de l'opérateur. La fermeture définitive du vecteur n'est pas cette liste, c'est torch ≥ 2.6 (`torch.load` en `weights_only=True`).

**Vecteur fermé, exceptions supprimées (2026-08-11).** La montée est faite : **torch 2.13.0, sb3 et sb3-contrib 2.9.0**. `scripts/security_audit_ignore.txt` ne contient **plus aucune exception** — `pip-audit --strict` sur le verrou rend « No known vulnerabilities found » sans rien ignorer. Les 19 CVE torch ne sont pas acceptées autrement : elles n'existent plus sur la surface, et le dépickle restreint de `torch.load` ferme ce qu'elles visaient.

Ce que ce mode impose : `weights_only=True` refuse les scalaires numpy des checkpoints sb3. `shared/torch_safe_globals.py` autorise `numpy._core.multiarray.scalar`, `numpy.dtype` et l'ensemble **fermé** des classes de dtype numpy — rien d'autre. Un « jeu minimal » de deux entrées avait d'abord été retenu : il tenait sur les modèles Armageddon et **échouait** sur les CoreAgent, qui portent des `Float64DType`. Le jeu nécessaire dépend des dtypes présents dans chaque checkpoint, donc un ensemble fermé vaut mieux qu'une liste rallongée à chaque modèle qui casse. Ce sont des descripteurs de type, pas des appelables : les autoriser ne rouvre pas ce que `weights_only=True` ferme. Le module est appelé au niveau **module** dans les cinq fichiers qui chargent un modèle (`ai/train.py`, `ai/bot_evaluation.py`, `ai/env_wrappers.py`, `ai/replay_converter.py`, `engine/pve_controller.py`) et dans `tests/conftest.py` : un nouveau site de chargement dans l'un d'eux est couvert sans rien ajouter. **Ce qu'il ne faut pas faire à la place** : repasser `weights_only=False`, qui rouvrirait l'exécution de code arbitraire au chargement d'un `.zip` de modèle. La liste blanche est, côté modèles, le pendant de `_safe_loads` côté sauvegardes.

Gain collatéral : sb3 2.9 n'impose plus `matplotlib`, donc `pillow` sort de la surface de production — avec les 26 vulnérabilités qu'il y traînait. Le verrou passe de 57 à 55 paquets.

**Validation de la montée, exécutée le 2026-08-11 — rien n'est resté supposé :**
1. Chargement des 50 `.zip` de `ai/models/` : 22 OK, 28 `KeyError` d'espace d'observation périmé (défaut **préexistant**, identique sous torch 2.5.1), **zéro `UnpicklingError`**.
2. Évaluation réelle (`--test-only`, 60 épisodes sur GPU) : combined **0.86**, `vs_control` 0.80. Ce chiffre dit que les poids sont fonctionnellement intacts, pas seulement rechargeables — un modèle mal désérialisé ne bat pas `greedy` 10-0.
3. Entraînement réel (`x1_debug`, 96 épisodes, 48 environnements vectorisés) : `learn` va au bout, VecNormalize écrit, modèle sauvé, **0 troncature**. C'est la surface sb3 2.6 → 2.9 qui pouvait avoir bougé — callbacks de schedule, dimensionnement du rollout buffer (`n_steps=170` par env), metrics tracker, TensorBoard.

Deux avertissements nouveaux, tous deux bénins et propres à torch 2.13 : un *graph break* de `torch.compile` sur `def _split_features` (`ai/pointer_policy.py`) (une garde `bool(torch.all(...))` que dynamo ne sait pas capturer — coût de compilation, la garde fonctionne), et `Not enough SMs to use max_autotune_gemm` (inductor constate que la RTX 4060 Laptop n'a pas assez de multiprocesseurs pour son auto-tuning le plus agressif).

**Allègement de l'image de production (2026-08-10), mesuré :** `tensorboard`, le pin `setuptools<82`, `torchvision` et `torchaudio` sont sortis de `requirements.runtime.in`. Preuve : `torchvision`/`torchaudio` n'ont **aucun** `import` dans le dépôt et ne sont jamais chargés ; le chemin serveur complet (engine, services, `ai.unit_registry`, `sb3_contrib`) a été importé et un modèle chargé dans un venv **sans** tensorboard — sb3 protège son import (`try: from torch.utils.tensorboard import SummaryWriter / except ImportError`). Conséquence : `PYSEC-2026-3447` (setuptools) disparaît de la liste d'exceptions, il n'en reste que torch.

**Purge du `package.json` racine (2026-08-10) :** ce fichier déclarait `react-scripts` et une pile CRA jamais installée (`node_modules/` à la racine est un **symlink** vers `frontend/node_modules`, posé par `scripts/link-root-node-modules.mjs`). Seul son `package-lock.json`, resté figé sur CRA, faisait remonter 2 critical + ~30 high à `npm audit` lancé depuis la racine, sur du code non déployé. Lockfile supprimé, `package.json` réduit à ses scripts réellement utilisés (biome + wrappers Python). Vérifié : `npx biome check frontend/src` (328 fichiers) et `npm run` inchangés. Piège mesuré en bac à sable : un `npm install` lancé **à la racine** supprime le symlink `node_modules` (`npm warn reify Removing non-directory …`) sans toucher au contenu réel de `frontend/node_modules` ; se rattrape par `npm --prefix frontend install`, dont le `postinstall` repose le lien. Comportement identique avant et après cette purge — ne pas lancer `npm install` à la racine.

**Validation :** script exécutable, exécuté, sortie 0. Réactivité de **chaque** porte prouvée en remettant le défaut, puis rétablie : SHA-1 sans `usedforsecurity` → rouge ; fichier à erreur de syntaxe déposé dans `shared/` → rouge (`bandit n'a pas pu analyser …`) ; ligne sans justification dans `security_audit_ignore.txt` → rouge, y compris indentée ; `Flask==3.1.2` → rouge ; `--audit-level=moderate` → rouge. Contrôle inverse : commentaires indentés (espaces **et** tabulations) et lignes vides de tabulations dans le fichier d'exceptions → vert, alors qu'ils faisaient échouer le script auparavant.

**Non vérifié :** l'effet propre de `pip-audit --strict`. Le drapeau est celui que documente pip-audit pour empêcher qu'une dépendance non collectée soit ignorée en silence, mais je n'ai pas su construire un cas qui distingue les deux modes — un paquet inexistant sort en 1 avec **et** sans `--strict`.

### Étape 7 — Journal d'audit (F4) ✅ faite le 2026-08-18 (socle posé le 2026-08-10)

**Déjà fait (livré avec le durcissement de l'étape 3, pas en anticipation gratuite : le rate limiting avait besoin des mêmes lignes)**
- Table `auth_events (id, occurred_at, event, login, ip, details)` dans `users.db`, **append-only**, rétention 30 jours.
- Événements écrits : `login_attempt`, `login_success`, `login_failure`, `rate_limited`, `logout`.
- IP réelle derrière le reverse proxy : `_client_ip()` lit `X-Forwarded-For` uniquement depuis un proxy listé dans `W40K_TRUSTED_PROXIES`, chaîne parcourue de droite à gauche.

**Fait le 2026-08-18 — exploitation : `scripts/auth_journal.py`**

Quatre sous-commandes, en **lecture seule** (`sqlite3` ouvert en `mode=ro`, une écriture échoue au niveau du moteur) :
- `events` — journal brut, filtres `--event/--login/--ip/--since`, requête statique à filtres optionnels ;
- `suspects` — ce qu'il faut regarder en premier : refus de rate limiting, IP à échecs répétés, **plusieurs logins distincts en échec depuis une même IP** (un utilisateur qui se trompe se trompe sur son propre login, pas sur ceux des autres), et connexions réussies par (login, IP). **Code de sortie 1** sur refus de rate limiting ou balayage de comptes, ce qui rend la commande utilisable en surveillance périodique et pas seulement à la main ;
- `sessions` — qui est connecté, depuis quand, jusqu'à quand. Le token n'est **jamais** affiché : le poser dans un terminal, un log ou un ticket le rendrait réutilisable par qui le lit ;
- `accounts` — voir étape 8.

`--since` refuse ce qu'il ne comprend pas au lieu de retomber sur une fenêtre par défaut : un `--since 7` lu comme sept secondes rendrait un rapport vide et laisserait croire qu'il ne s'est rien passé — le pire résultat possible pour un outil d'audit.

**`shared/auth_credentials.py` — défaut trouvé en écrivant le script.** `services/api_server.py` appelle `initialize_auth_db()` **au niveau module** : l'importer suffit à écrire dans `config/users.db`, et à la **créer** si elle manque. Un auditeur passant par lui aurait fabriqué la base qu'il vient auditer, rendant « aucun compte » indiscernable de « fichier absent » — et en écrivant dans un fichier protégé (CLAUDE.md). Le chemin de la base, le hachage PBKDF2 et les noms d'événements sont donc extraits dans un module **sans effet de bord à l'import**, dont `api_server` les réexporte (les tests continuent de monkeypatcher `api_server.AUTH_DB_PATH` et `api_server._verify_password`). Recopier chemin et algorithme dans le script a été écarté : un doublon reste vert quand la production change, donc il rassure exactement au moment où il devient faux.

**Reste à faire**
- Événements `user_created`, `profile_changed`, `password_changed` : ils n'ont toujours **aucun chemin de code** — les comptes sont créés à la main en SQL (décision F12). Ils n'apparaîtront que le jour où une route d'administration existera ; les écrire avant serait du code mort.
- ~~Renseigner `W40K_TRUSTED_PROXIES`~~ : fait à l'étape 5.

**Validation :** `tests/unit/services/test_auth_journal.py` (23 tests), preuve ROUGE sur 9 verrous. Exécuté sur la base réelle (`--db config/users.db`, les quatre sous-commandes) : mtime et taille du fichier **inchangés** avant/après, le mode lecture seule est donc effectif et non seulement déclaré.

### Étape 8 — Passe finale avant ouverture 🟨 partielle (2026-08-18)

**Comptes existants — fait, et il y a un résultat.** `scripts/auth_journal.py accounts` teste chaque compte contre 15 mots de passe triviaux **plus le login lui-même** (`admin/admin` est le cas nommé ici, et il n'est dans aucune liste statique). Les mots de passe sont hachés : on ne peut que tester des candidats, ce qui est exactement ce que demande cette étape — repérer ce qu'on se donne en montant un environnement puis qu'on oublie — et non casser un mot de passe fort. Sortie 1 si un compte est trouvé trivial, pour que l'audit échoue bruyamment au lieu de l'écrire au milieu d'un tableau.

> 🔴 **Exécuté le 2026-08-18 sur `config/users.db` : le compte unique `greg` (profil `admin`) a `greg` pour mot de passe.** À changer **avant toute exposition** — c'est le seul compte, et il est administrateur. Non corrigé ici : `config/users.db` est un fichier protégé (CLAUDE.md) et le mot de passe de remplacement est une décision utilisateur. Changement : `UPDATE users SET password_hash = ? WHERE login = 'greg'` avec la sortie de `shared.auth_credentials.hash_password("<nouveau>")`.

**MFA — décision confirmée, reportée.** La condition de réévaluation écrite en §5 est « inscription libre des testeurs ». Elle n'est **pas** remplie : `/api/auth/register` est supprimée (F12) et les comptes sont créés en SQL, donc l'accès reste sur invitation. Avec mots de passe forts (à obtenir, cf. ci-dessus), rate limiting, sessions expirantes et cookie `HttpOnly`, le TOTP n'apporte rien face au modèle de menace retenu. À rouvrir le jour où l'inscription s'ouvre.

**Reste à faire — actions de RUNTIME, pas de code**
- Changer le mot de passe du compte `greg` (bloquant pour l'exposition).
- Scan dynamique baseline (OWASP ZAP) contre l'instance de test, une fois la stack de l'étape 5 déployée avec ses certificats. Non exécutable ici : demande une instance déployée et joignable.

---

## 5. Hors périmètre (décisions actées)

| Sujet | Décision | Condition de réévaluation |
|---|---|---|
| MFA / TOTP | Reporté — **confirmé le 2026-08-18** (étape 8) : l'accès reste sur invitation, `register` est supprimée | Inscription libre des testeurs |
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
| 4. Réduction surface d'information | F3, F10, F13 | ✅ Fait — CORS explicite, traceback fermé par défaut + `error_id`, session en cookie `HttpOnly`/`SameSite=Strict` + en-tête anti-CSRF (35 tests, 13 preuves rouges) ; **runtime navigateur à valider** | 2026-08-18 |
| 5. Infra d'exposition (WSGI + proxy + TLS) | F9, F15 | ✅ Fait — waitress (`services/wsgi.py`), `user: "0:0"` et `ports: 5001` retirés, nginx versionné en TLS 1.2/1.3 + redirection 80→443, proxy de confiance à IP fixe ; **certificats et `docker compose up` restent à fournir/exécuter au déploiement** | 2026-08-18 |
| 6. Analyse statique | F5 | ✅ Fait — `scripts/security_check.sh` exécuté, sortie 0 ; traités : 3 bandit HIGH, Flask 3.1.3, 10 npm high/critical, `scipy` manquant en production, `users.db`/`.claude` cuits dans l'image, et les 19 CVE torch **supprimées** par la montée 2.13.0/sb3 2.9.0 du 2026-08-11 — `security_audit_ignore.txt` est vide | 2026-08-11 |
| 7. Journal d'audit | F4 | ✅ Fait — exploitation par `scripts/auth_journal.py` (4 sous-commandes, lecture seule, 23 tests) ; les événements d'administration restent sans chemin de code, donc hors périmètre tant qu'aucune route d'admin n'existe | 2026-08-18 |
| 8. Passe finale (ZAP, MFA ?, comptes) | — | 🟨 Partiel — audit des comptes fait (**1 mot de passe trivial trouvé**), MFA confirmé reporté ; restent le changement de mot de passe et le scan ZAP, qui sont des actions de runtime | 2026-08-18 |

**Jalon : ~~ne pas exposer sur Internet avant la fin de l'étape 5~~ — l'étape 5 est faite côté code.**
Trois conditions restent avant exposition, aucune n'étant du code :
1. changer le mot de passe du compte `greg` (`admin`, mot de passe = son login) ;
2. fournir les certificats TLS montés sur `/etc/nginx/certs` et vérifier `docker compose up` (HTTPS servi, HTTP redirigé, port 5001 injoignable depuis l'hôte, `whoami` → `appuser`) ;
3. valider en navigateur le passage au cookie de session (login, partie complète, déconnexion).
