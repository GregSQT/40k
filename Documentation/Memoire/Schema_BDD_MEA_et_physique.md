# Schéma de la base d'authentification – MEA et modèle physique

## 1. Modèle entité-association (MEA)

Les entités et relations ci-dessous décrivent le domaine « authentification et droits » de l'application. Chaque **utilisateur** est rattaché à un **profil**. Un **profil** a accès à des **modes de jeu** et à des **options** (paramètres par profil). Les **sessions** permettent d'authentifier les requêtes via un token.

```
┌─────────────────┐       ┌─────────────────┐
│    PROFIL       │       │   UTILISATEUR    │
├─────────────────┤       ├─────────────────┤
│ id (PK)         │───1:N─│ id (PK)         │
│ code (UK)       │       │ login (UK)       │
│ label           │       │ password_hash    │
└────────┬────────┘       │ profile_id (FK) │
         │                 └────────┬────────┘
         │ N                        │
         │    ┌─────────────────────┼─────────────────────┐
         │    │                     │ 1                   │
         ▼    ▼                     ▼                     ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ PROFILE_GAME_    │  │ PROFILE_OPTIONS   │  │    SESSION        │
│ MODES (table     │  │ (table            │  ├──────────────────┤
│ d'association)  │  │ d'association)    │  │ token (PK)        │
├──────────────────┤  ├──────────────────┤  │ user_id (FK)      │
│ profile_id (FK)  │  │ profile_id (FK)   │  │ created_at       │
│ game_mode_id(FK) │  │ option_id (FK)    │  └──────────────────┘
└────────┬─────────┘  │ enabled          │
         │ N          └────────┬─────────┘
         │                     │ N
         ▼                     ▼
┌─────────────────┐   ┌─────────────────┐
│   GAME_MODE     │   │    OPTION       │
├─────────────────┤   ├─────────────────┤
│ id (PK)         │   │ id (PK)         │
│ code (UK)       │   │ code (UK)       │
│ label           │   │ label           │
└─────────────────┘   └─────────────────┘
```

**Entités :**

| Entité | Rôle |
|--------|------|
| **Profil** | Rôle utilisateur (ex. « base », « admin »). Détermine les modes de jeu et options accessibles. |
| **Utilisateur** | Compte (login, mot de passe haché). Lié à un seul profil. |
| **Session** | Token d'authentification associé à un utilisateur (une session par connexion). |
| **ModeJeu** | Mode de jeu (pve, pvp, pve_test, pvp_test). Référencé par les profils. |
| **Option** | Option applicative (ex. show_advance_warning, auto_weapon_selection). Référencée par les profils avec un flag enabled. |

## 2. Modèle physique (tables SQLite)

Correspondance avec le script exécuté au démarrage de l'API (`initialize_auth_db` dans `services/api_server.py`).

| Table | Colonnes | Contraintes |
|-------|----------|-------------|
| **profiles** | id INTEGER PK AUTOINCREMENT, code TEXT NOT NULL UNIQUE, label TEXT NOT NULL | |
| **users** | id INTEGER PK AUTOINCREMENT, login TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, profile_id INTEGER NOT NULL REFERENCES profiles(id) | |
| **game_modes** | id INTEGER PK AUTOINCREMENT, code TEXT NOT NULL UNIQUE, label TEXT NOT NULL | |
| **options** | id INTEGER PK AUTOINCREMENT, code TEXT NOT NULL UNIQUE, label TEXT NOT NULL | |
| **profile_game_modes** | profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE, game_mode_id INTEGER NOT NULL REFERENCES game_modes(id) ON DELETE CASCADE | UNIQUE(profile_id, game_mode_id) |
| **profile_options** | profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE, option_id INTEGER NOT NULL REFERENCES options(id) ON DELETE CASCADE, enabled INTEGER NOT NULL | UNIQUE(profile_id, option_id) |
| **sessions** | token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, created_at TEXT NOT NULL | |

## 3. Intégration au mémoire

- **Corps du mémoire (section 3.5)** : insérer le schéma MEA (dessin ou image exportée) avec la légende « Modèle entité-association – Base d'authentification (config/users.db). »
- **Même section ou annexe** : tableau du modèle physique ci-dessus (ou extrait du script SQL en annexe).
- Le schéma existant `schema_bdd_auth.html` (Mermaid ER) reste valide ; ce document fournit une version MEA « métier » en français et un résumé physique pour le jury.
