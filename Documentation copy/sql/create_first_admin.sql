-- SQLite script: create/promote first admin user for W40K auth
-- DB file: config/users.db
--
-- Usage:
--   sqlite3 config/users.db < Documentation/sql/create_first_admin.sql
--
-- This script:
-- 1) Ensures profile/mode seeds for admin exist
-- 2) Grants admin mode access (pve, pve_old, pvp, pvp_old, debug, test)
-- 3) Grants admin options
-- 4) Promotes an existing user (replace __ADMIN_LOGIN__)
--
-- IMPORTANT:
-- Replace __ADMIN_LOGIN__ before running.

BEGIN;

INSERT OR IGNORE INTO profiles (code, label) VALUES ('admin', 'Administrateur');
INSERT OR IGNORE INTO game_modes (code, label) VALUES ('pve', 'Player vs Environment');
INSERT OR IGNORE INTO game_modes (code, label) VALUES ('pve_old', 'Player vs Environment (Old)');
INSERT OR IGNORE INTO game_modes (code, label) VALUES ('pvp', 'Player vs Player');
INSERT OR IGNORE INTO game_modes (code, label) VALUES ('pvp_old', 'Player vs Player (Old)');
INSERT OR IGNORE INTO game_modes (code, label) VALUES ('debug', 'Debug Mode');
INSERT OR IGNORE INTO game_modes (code, label) VALUES ('test', 'Test Mode');
INSERT OR IGNORE INTO options (code, label) VALUES ('show_advance_warning', 'Afficher avertissement mode advance');
INSERT OR IGNORE INTO options (code, label) VALUES ('auto_weapon_selection', 'Selection automatique d''arme');

INSERT OR IGNORE INTO profile_game_modes (profile_id, game_mode_id)
SELECT p.id, gm.id
FROM profiles p
JOIN game_modes gm ON gm.code IN ('pve', 'pve_old', 'pvp', 'pvp_old', 'debug', 'test')
WHERE p.code = 'admin';

INSERT OR REPLACE INTO profile_options (profile_id, option_id, enabled)
SELECT p.id, o.id, 1
FROM profiles p
JOIN options o ON o.code IN ('show_advance_warning', 'auto_weapon_selection')
WHERE p.code = 'admin';

-- Promote existing user to admin profile
UPDATE users
SET profile_id = (SELECT id FROM profiles WHERE code = 'admin')
WHERE login = '__ADMIN_LOGIN__';

COMMIT;
