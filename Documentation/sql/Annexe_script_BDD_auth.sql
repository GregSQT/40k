-- =============================================================================
-- Script de création et amorçage de la base d'authentification
-- Trazyn's Trials – config/users.db
-- Extrait équivalent à initialize_auth_db() dans services/api_server.py
-- =============================================================================

-- Tables principales
CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    login TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    profile_id INTEGER NOT NULL REFERENCES profiles(id)
);

CREATE TABLE IF NOT EXISTS game_modes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS options (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profile_game_modes (
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    game_mode_id INTEGER NOT NULL REFERENCES game_modes(id) ON DELETE CASCADE,
    UNIQUE(profile_id, game_mode_id)
);

CREATE TABLE IF NOT EXISTS profile_options (
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    option_id INTEGER NOT NULL REFERENCES options(id) ON DELETE CASCADE,
    enabled INTEGER NOT NULL,
    UNIQUE(profile_id, option_id)
);

-- `expires_at` : durée de vie glissante des sessions (F2 du plan sécurité). Colonne NOT NULL
-- SANS valeur par défaut — une session sans échéance est une erreur, pas un cas à couvrir.
-- Une base créée avant cette colonne est migrée au démarrage par `_migrate_sessions_table`
-- (destruction puis recréation : les tokens sans échéance sont précisément ceux à révoquer).
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);

-- Journal d'authentification APPEND-ONLY : porte à la fois le rate limiting du login (F8)
-- et la traçabilité (étape 7). Événements : login_attempt, login_success, login_failure,
-- rate_limited, logout. `login_attempt` est écrit AVANT la vérification du mot de passe —
-- c'est ce qui place le comptage et l'inscription dans la même transaction.
CREATE TABLE IF NOT EXISTS auth_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at INTEGER NOT NULL,
    event TEXT NOT NULL,
    login TEXT NOT NULL,
    ip TEXT NOT NULL,
    details TEXT
);

CREATE INDEX IF NOT EXISTS idx_auth_events_lookup
    ON auth_events (login, ip, event, id);

-- Index séparé : la purge de rétention filtre sur `occurred_at`, qui n'est pas colonne de
-- tête de l'index ci-dessus. Sans lui, chaque purge balaie toute la table.
CREATE INDEX IF NOT EXISTS idx_auth_events_retention
    ON auth_events (occurred_at);

-- `login_attempts` (compteur jetable purgé à 60 s) a été remplacée par `auth_events`.
DROP TABLE IF EXISTS login_attempts;

-- Amorçage des profils
INSERT OR IGNORE INTO profiles (code, label) VALUES ('base', 'Joueur Base');
INSERT OR IGNORE INTO profiles (code, label) VALUES ('admin', 'Administrateur');

-- Amorçage des modes de jeu
INSERT OR IGNORE INTO game_modes (code, label) VALUES ('pve', 'Player vs Environment');
INSERT OR IGNORE INTO game_modes (code, label) VALUES ('pve_test', 'Player vs Environment Test');
INSERT OR IGNORE INTO game_modes (code, label) VALUES ('pvp', 'Player vs Player');
INSERT OR IGNORE INTO game_modes (code, label) VALUES ('pvp_test', 'Player vs Player Test');

-- Amorçage des options
INSERT OR IGNORE INTO options (code, label) VALUES ('show_advance_warning', 'Afficher avertissement mode advance');
INSERT OR IGNORE INTO options (code, label) VALUES ('auto_weapon_selection', 'Selection automatique d''arme');

-- Droits : profil base → pve, pve_test, pvp, pvp_test (via profile_game_modes)
-- Droits : profil admin → tous les modes (idem)
-- Options : profile_options lie chaque profil aux options avec enabled = 1
-- (Les INSERT exacts dépendent des id retournés par les SELECT ; en production
--  ils sont effectués par initialize_auth_db() en Python.)
