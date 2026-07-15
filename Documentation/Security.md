# Sécurité — Analyse et plan d'implémentation

> Date : 2026-07-15 (mis à jour : exposition Internet prévue pour les tests)
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
- **Backend + modèles IA** : c'est là qu'est la valeur (moteur de règles, agents entraînés). Ce code ne quitte jamais le serveur **sauf si** un attaquant obtient une exécution de code ou une lecture de fichiers arbitraire. Toute la stratégie consiste donc à fermer ces vecteurs — ils existent aujourd'hui (F1, F6, F7 ci-dessous).

---

## 2. État des lieux (vérifié dans le code)

### Ce qui est déjà en place et correct

| Domaine | Implémentation | Référence |
|---|---|---|
| Hachage des mots de passe | PBKDF2-HMAC-SHA256 avec sel aléatoire 16 octets (`secrets.token_bytes`) | `api_server.py:810` |
| Authentification (mécanisme) | Bearer token de session, stocké dans `sessions` (SQLite) | `api_server.py:848`, `api_server.py:897` |
| Autorisation (RBAC) | Tables `profiles`, `profile_game_modes`, `profile_options` ; résolution des permissions par profil | `api_server.py:861`, `api_server.py:957` |
| Gestion mémoire | Python + TypeScript (mémoire managée) ; module WASM LoS en **Rust** (`frontend/wasm-los/`), memory-safe. Aucun code C/C++. | — |
| Endpoint replay | `/api/replay/file/<filename>` filtre correctement le path traversal (`..`, `/`, `\` rejetés, extension `.log` imposée) | `api_server.py:4165` |
| Frontend build | Pas de source maps dans `dist/` | vérifié |

### Failles identifiées

| # | Sévérité | Faille | Détail | Référence |
|---|---|---|---|---|
| F1 | **Critique** | Debugger Werkzeug exposé au réseau | `app.run(host='0.0.0.0', port=5001, debug=True)` : le debugger interactif Werkzeug donne une **exécution de code arbitraire** (donc vol de tout le code) à quiconque provoque une exception. Le flag `W40K_DEBUG` (ligne 4010) n'est pas utilisé ici. | `api_server.py:4285` |
| F6 | **Critique** | API quasi entièrement non authentifiée | **30 des 34 routes** n'appellent pas `_get_authenticated_user_or_response()` et il n'y a aucun `before_request` global. Toutes les actions de jeu, la lecture des logs/replays et la configuration de persistance sont ouvertes à n'importe qui. | vérifié par comptage |
| F7 | **Critique** | Répertoire de persistance contrôlé par le client + `pickle.load` | `/api/game/snapshot/persist` accepte un `directory` arbitraire (créé via `os.makedirs`, aucune restriction) → **écriture disque n'importe où** avec les droits du process. Les snapshots sont ensuite relus via `pickle.load` → la désérialisation pickle d'un fichier influençable par un client est un **vecteur RCE classique**. | `api_server.py:3415`, `api_server.py:3328` |
| F11 | **Critique** | Endpoint `pick-directory` exécute `subprocess`/`powershell.exe` | `/api/game/pick-directory` (non authentifié) lance `powershell.exe` via `subprocess` pour ouvrir un dialogue Windows. Aucun sens fonctionnel sur un serveur exposé, et surface `subprocess` ouverte sur le réseau. **À supprimer purement** en prod (pas seulement authentifier). | `api_server.py:3447` |
| F12 | **Haute** | Inscription (`/api/auth/register`) totalement ouverte | Aucune auth, aucun rate limit → création de comptes en masse depuis Internet. Rend caduque la logique « testeurs invités » qui justifie de reporter le MFA. Fermer (création manuelle en SQL) ou protéger par jeton d'invitation. | `api_server.py:1845` |
| F13 | Moyenne | Token de session en `localStorage` | Le token est stocké dans `localStorage` → volable par tout XSS (token = accès complet). Cible : cookie `HttpOnly`+`Secure`+`SameSite`. À défaut, risque à acter explicitement. | `frontend/src/auth/authStorage.ts:44` |
| F14 | Moyenne | Filtre path-traversal faible sur `replay/parse` | `/api/replay/parse` rejette `..` et `/` en tête mais ouvre tout `log_path` relatif directement — moins strict que `/api/replay/file/<filename>` (extension `.log` imposée, ligne 4177). À harmoniser (couvert incidemment par l'auth globale F6). | `api_server.py:4133` |
| F2 | **Haute** | Sessions sans expiration | Table `sessions` : `created_at` seulement ; validation `WHERE token = ?` sans condition temporelle. Token volé = valide à vie. Le message "Invalid or expired session" est trompeur. | `api_server.py:915`, `api_server.py:995` |
| F8 | **Haute** | Pas de rate limiting sur le login | Brute-force des mots de passe possible à pleine vitesse depuis Internet. | — |
| F9 | **Haute** | Flask dev server + pas de TLS | Le serveur de dev Werkzeug n'est pas fait pour Internet (perf, robustesse). Sans HTTPS, tokens et mots de passe passent en clair. | `api_server.py:4285` |
| F3 | Moyenne | CORS ouvert à toutes les origines | `CORS(app, ...)` sans `origins` = `*`. | `api_server.py:1194` |
| F10 | Moyenne | Traceback complet renvoyé au client | Le handler global d'exceptions renvoie type + message + traceback dans la réponse JSON → révèle chemins, structure du code, versions. Utile en dev, à désactiver en prod (log serveur uniquement). | `api_server.py:1201` |
| F4 | Faible→Moyenne | Pas de journal d'audit | Aucune trace des logins réussis/échoués, IP, créations d'utilisateurs. Indispensable pour détecter une attaque en cours une fois exposé. | — |
| F5 | Faible | Pas d'analyse automatisée | Aucun outil statique (bandit, pip-audit, npm audit) dans le workflow. | — |

---

## 3. Avis sur les sujets évoqués

### MFA
**Reporté, plus écarté.** Pour des tests publics avec quelques testeurs invités, des mots de passe forts + rate limiting + sessions expirantes suffisent. À implémenter (TOTP via `pyotp`) si le jeu passe en accès ouvert avec inscription libre. Réévaluation prévue à la fin du plan.

### Autorisation / RBAC
**Le mécanisme existe, mais il ne protège presque rien** (F6) : il n'est appliqué que sur 4 routes. Le chantier n'est pas de créer un RBAC, c'est de **l'appliquer partout** (étape 2).

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

### Étape 1 — Fermer les vecteurs RCE (F1, F7, F11) 🔴 bloquant
**Fichier :** `services/api_server.py`
- `app.run` : `debug` conditionné au flag `W40K_DEBUG` existant (défaut `False`) ; `host` = `127.0.0.1` par défaut, surchargeable par `W40K_HOST`. Erreur explicite au démarrage si debug + host non-local sont combinés.
- `/api/game/snapshot/persist` : supprimer la possibilité pour le client de choisir `directory`. Le répertoire de persistance devient une config **serveur** (variable d'environnement ou fichier de config), jamais une donnée de requête.
- Remplacer `pickle` par un format non exécutable pour les snapshots (JSON si la structure le permet, sinon garder pickle mais uniquement sur un chemin fixe non influençable par le client — à trancher au moment de l'implémentation selon le contenu de `GameSnapshotStore`).
- `/api/game/pick-directory` (F11) : supprimer l'endpoint en prod (via flag `W40K_DEBUG` ou retrait pur). Aucun `subprocess`/`powershell.exe` exposé sur le réseau. Le front doit basculer sur une config serveur du répertoire de persistance (voir point précédent).

**Validation :** API démarre sur 127.0.0.1 sans debugger ; requête POST avec `directory` → erreur explicite ; `pick-directory` absent/404 en prod ; snapshots toujours fonctionnels.

### Étape 2 — Authentification sur toutes les routes (F6, F12, F14) 🔴 bloquant
**Fichier :** `services/api_server.py`
- `@app.before_request` global : toute route exige un token de session valide, **sauf** liste blanche explicite (`/api/auth/login`, health check). Pas de logique inversée (pas de "protéger certaines routes") : tout est fermé par défaut.
- `/api/auth/register` (F12) : **ne pas** mettre en liste blanche. Créer les comptes testeurs manuellement en SQL, ou protéger register par un jeton d'invitation à usage unique. Inscription libre = interdite tant que le MFA est reporté.
- `/api/replay/parse` (F14) : harmoniser le filtre avec `/api/replay/file/<filename>` (extension `.log` imposée, rejet strict de tout séparateur/`..`).
- Vérifier que le RBAC (modes de jeu) est appliqué sur les routes de jeu, pas seulement au démarrage de partie.

**Validation :** toute route hors liste blanche sans token → 401 ; `register` sans invitation → refusé ; le jeu fonctionne normalement une fois loggé.

### Étape 3 — Durcissement des sessions (F2, F8)
**Fichier :** `services/api_server.py`
- Colonne `expires_at` sur `sessions` (migration `ALTER TABLE`, pattern existant ligne 1003) ; durée 7 jours glissants, renouvelée à chaque requête ; purge au login ; `AND expires_at > ?` dans la validation. Session expirée = 401 explicite, pas de fallback.
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
| 1. Fermer les vecteurs RCE | F1, F7, F11 | ⬜ À faire | — |
| 2. Auth sur toutes les routes | F6, F12, F14 | ⬜ À faire | — |
| 3. Durcissement sessions + rate limiting | F2, F8 | ⬜ À faire | — |
| 4. Réduction surface d'information | F3, F10, F13 | ⬜ À faire | — |
| 5. Infra d'exposition (WSGI + proxy + TLS) | F9 | ⬜ À faire | — |
| 6. Analyse statique | F5 | ⬜ À faire | — |
| 7. Journal d'audit | F4 | ⬜ À faire | — |
| 8. Passe finale (ZAP, MFA ?, comptes) | — | ⬜ À faire | — |

**Jalon : ne pas exposer sur Internet avant la fin de l'étape 5.**
