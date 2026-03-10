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

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
);

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
