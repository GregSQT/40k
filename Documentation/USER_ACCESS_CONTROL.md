# Gestion des users, profils et droits d'acces

## Objectif

Mettre en place un systeme d'authentification/autorisation permettant de:

- creer un compte (`login` / `password`)
- se connecter (`login` / `password`)
- limiter les modes de jeu et options selon le profil utilisateur
- stocker users, profils et droits en base de donnees
- rediriger automatiquement l'utilisateur connecte vers le mode `pve`

---

## Regles metier (version initiale)

### Profil `base`

Un joueur `base` peut acceder a:

- modes de jeu:
  - `pve`
  - `pvp`
- options:
  - `show_advance_warning` (afficher l'avertissement lors du mode advance)
  - `auto_weapon_selection` (selection automatique d'arme)

### Redirection apres connexion

Apres connexion reussie, l'utilisateur est redirige vers la route de jeu `pve`.

### Profil `admin` (ajoute)

Un utilisateur `admin` peut acceder a:

- modes de jeu:
  - `pve`
  - `pvp`
  - `debug`
  - `test`
- options:
  - `show_advance_warning`
  - `auto_weapon_selection`

---

## Principes d'architecture

### Frontend (React)

- ecran `Auth` avec deux actions:
  - connexion
  - creation de compte
- store global d'authentification:
  - user courant
  - profil
  - permissions resolues (modes + options)
- guards UI:
  - n'afficher/activer que les modes/options autorises

### Backend (Flask)

- endpoints d'authentification:
  - `POST /api/auth/register`
  - `POST /api/auth/login`
  - `GET /api/auth/me`
- middleware de verification des permissions
- protection serveur obligatoire:
  - toute action non autorisee doit renvoyer `403`

### Base de donnees

- source de verite pour:
  - comptes users
  - profils
  - droits par profil

---

## Modele de donnees

## Entites

### `profiles`

- `id` (PK)
- `code` (UNIQUE, ex: `base`, `admin`)
- `label`

### `users`

- `id` (PK)
- `login` (UNIQUE, NOT NULL)
- `password_hash` (NOT NULL)
- `profile_id` (FK -> `profiles.id`)
- `created_at`
- `updated_at`

### `game_modes`

- `id` (PK)
- `code` (UNIQUE, ex: `pve`, `pvp`)
- `label`

### `options`

- `id` (PK)
- `code` (UNIQUE, ex: `show_advance_warning`, `auto_weapon_selection`)
- `label`

## Tables de droits

### `profile_game_modes`

- `profile_id` (FK)
- `game_mode_id` (FK)
- contrainte unique (`profile_id`, `game_mode_id`)

### `profile_options`

- `profile_id` (FK)
- `option_id` (FK)
- `enabled` (BOOLEAN, NOT NULL, default explicite metier)
- contrainte unique (`profile_id`, `option_id`)

---

## Contrat API

## `POST /api/auth/register`

### Input

```json
{
  "login": "greg",
  "password": "motDePasseFort"
}
```

### Comportement

- cree un user
- affecte le profil par defaut `base`
- hash le mot de passe (argon2 ou bcrypt)

### Output (exemple)

```json
{
  "user_id": 12,
  "login": "greg",
  "profile": "base"
}
```

## `POST /api/auth/login`

### Input

```json
{
  "login": "greg",
  "password": "motDePasseFort"
}
```

### Output (exemple)

```json
{
  "access_token": "<jwt_or_session_token>",
  "user": {
    "id": 12,
    "login": "greg",
    "profile": "base"
  },
  "permissions": {
    "game_modes": ["pve", "pvp"],
    "options": {
      "show_advance_warning": true,
      "auto_weapon_selection": true
    }
  },
  "default_redirect_mode": "pve"
}
```

## `GET /api/auth/me`

Retourne l'utilisateur connecte et ses droits resolus depuis la base.

---

## Flux utilisateur

1. L'utilisateur arrive sur la page `/auth`.
2. Il choisit:
   - connexion
   - creation de compte
3. En cas de succes, le front recupere `permissions`.
4. Le front redirige automatiquement vers `pve`.
5. Les menus, boutons et toggles affichent uniquement les elements autorises.

---

## Autorisation: regle non negociable

Le frontend ne suffit pas pour securiser les acces.

- Le frontend gere l'UX (affichage/masquage).
- Le backend doit toujours verifier les droits avant execution.
- Toute tentative hors droits doit renvoyer `403`.

Exemples:

- user sans droit `game_mode:pvp` tente de lancer `pvp` -> `403`
- user sans droit `option:auto_weapon_selection` tente d'activer l'option -> `403`

---

## SQL de reference (PostgreSQL)

> Adapter les types (`SERIAL`/`BIGSERIAL`) selon votre standard.

```sql
BEGIN;

CREATE TABLE IF NOT EXISTS profiles (
  id BIGSERIAL PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
  id BIGSERIAL PRIMARY KEY,
  login TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  profile_id BIGINT NOT NULL REFERENCES profiles(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS game_modes (
  id BIGSERIAL PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS options (
  id BIGSERIAL PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profile_game_modes (
  profile_id BIGINT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  game_mode_id BIGINT NOT NULL REFERENCES game_modes(id) ON DELETE CASCADE,
  PRIMARY KEY (profile_id, game_mode_id)
);

CREATE TABLE IF NOT EXISTS profile_options (
  profile_id BIGINT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  option_id BIGINT NOT NULL REFERENCES options(id) ON DELETE CASCADE,
  enabled BOOLEAN NOT NULL,
  PRIMARY KEY (profile_id, option_id)
);

-- Seed: profils
INSERT INTO profiles (code, label)
VALUES ('base', 'Joueur Base')
ON CONFLICT (code) DO NOTHING;

-- Seed: modes
INSERT INTO game_modes (code, label)
VALUES
  ('pve', 'Player vs Environment'),
  ('pvp', 'Player vs Player')
ON CONFLICT (code) DO NOTHING;

-- Seed: options
INSERT INTO options (code, label)
VALUES
  ('show_advance_warning', 'Afficher avertissement mode advance'),
  ('auto_weapon_selection', 'Selection automatique d''arme')
ON CONFLICT (code) DO NOTHING;

-- Droits profil base -> modes pve/pvp
INSERT INTO profile_game_modes (profile_id, game_mode_id)
SELECT p.id, gm.id
FROM profiles p
JOIN game_modes gm ON gm.code IN ('pve', 'pvp')
WHERE p.code = 'base'
ON CONFLICT DO NOTHING;

-- Droits profil base -> options activees
INSERT INTO profile_options (profile_id, option_id, enabled)
SELECT p.id, o.id, TRUE
FROM profiles p
JOIN options o ON o.code IN ('show_advance_warning', 'auto_weapon_selection')
WHERE p.code = 'base'
ON CONFLICT (profile_id, option_id) DO UPDATE
SET enabled = EXCLUDED.enabled;

COMMIT;
```

---

## Integration frontend (resume pratique)

- Au login/register:
  - stocker token/session
  - charger `permissions`
- Dans l'ecran principal:
  - afficher onglet `pve`/`pvp` seulement si present dans `permissions.game_modes`
- Dans les reglages:
  - afficher `show_advance_warning` si `true`
  - afficher `auto_weapon_selection` si `true`
- Si l'utilisateur tente une route non autorisee:
  - redirection + message d'acces refuse

---

## Securite minimale recommandee

- hash mot de passe via Argon2 (prioritaire) ou bcrypt
- validation serveur stricte des inputs
- rate limit sur login/register
- message d'erreur neutre en auth (`identifiants invalides`)
- expiration token/session + mecanisme de refresh

---

## Criteres d'acceptation

- Un compte cree est associe au profil `base`.
- Un user `base` accede a `pve` et `pvp`.
- Les options `show_advance_warning` et `auto_weapon_selection` sont disponibles.
- Apres connexion, redirection automatique vers `pve`.
- Toute action hors droits est bloquee cote backend (`403`).

---

## Etat d'implementation dans ce repo

Cette section decrit ce qui a ete effectivement ajoute dans le code.

## Backend

- Fichier modifie: `services/api_server.py`
- Base de donnees SQLite: `config/users.db`
- Initialisation auto de la DB au demarrage du serveur (`initialize_auth_db()`), avec:
  - schema `profiles`, `users`, `game_modes`, `options`, `profile_game_modes`, `profile_options`, `sessions`
  - seed du profil `base`
  - seed des modes `pve`, `pvp`
  - seed des options `show_advance_warning`, `auto_weapon_selection`
  - association des droits du profil `base` (modes + options)

### Endpoints auth implementes

- `POST /api/auth/register`
  - cree un utilisateur `login/password`
  - assigne automatiquement le profil `base`
- `POST /api/auth/login`
  - verifie le mot de passe hash (PBKDF2-SHA256)
  - cree une session (`access_token`) en DB
  - renvoie user + permissions + `default_redirect_mode: "pve"`
- `GET /api/auth/me`
  - renvoie l'utilisateur courant et ses permissions selon le token bearer

### Protection des modes de jeu

- `POST /api/game/start` est maintenant protege:
  - token bearer obligatoire
  - verification des permissions du profil
  - refus `403` si le mode demande n'est pas autorise

## Script SQL admin

- Fichier: `Documentation/sql/create_first_admin.sql`
- Role:
  - seed `admin` + modes `debug/test` si absents
  - accorder les droits admin
  - promouvoir un user existant en admin

### Utilisation

1. Creer d'abord un user via `/auth` (ou via endpoint `POST /api/auth/register`)
2. Editer le script et remplacer `__ADMIN_LOGIN__` par le login cible
3. Executer:

```bash
sqlite3 config/users.db < Documentation/sql/create_first_admin.sql
```

4. Se reconnecter avec ce user
5. Le user aura acces a `pve`, `pvp`, `debug`, `test`

## Frontend

- Nouveau fichier: `frontend/src/auth/authStorage.ts`
  - stockage/lecture/suppression de session auth (`localStorage`)
- Nouvelle page: `frontend/src/pages/AuthPage.tsx`
  - connexion
  - creation de compte
  - connexion automatique apres creation de compte
  - redirection vers `/game?mode=pve`
- Routes protegees:
  - fichier modifie: `frontend/src/Routes.tsx`
  - ajout route `/auth`
  - route `/game` accessible seulement si session valide en local
  - controle des modes autorises cote front (redirection vers un mode autorise)
- Hook API:
  - fichier modifie: `frontend/src/hooks/useEngineAPI.ts`
  - envoi du bearer token sur `POST /api/game/start`
- Settings UI:
  - fichier modifie: `frontend/src/components/BoardWithAPI.tsx`
  - lecture des options autorisees depuis la session
  - activation des toggles seulement si permission presente
  - ajout action de deconnexion
  - fichier modifie: `frontend/src/components/SettingsMenu.tsx`
  - affichage conditionnel des options selon permissions
  - bouton `Se deconnecter`

## Notes de fonctionnement

- Profil `base`:
  - modes autorises: `pve`, `pvp`
  - options autorisees:
    - `show_advance_warning`
    - `auto_weapon_selection`
- Profil `admin`:
  - modes autorises: `pve`, `pvp`, `debug`, `test`
  - options autorisees:
    - `show_advance_warning`
    - `auto_weapon_selection`
- Redirection post-login:
  - le front redirige vers `/game?mode=pve`

