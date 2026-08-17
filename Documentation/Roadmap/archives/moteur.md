# Archives Moteur

| Date | Chantier | Détail |
|---|---|---|
| 2026-08-17 | INDIRECT FIRE 24.19 | 7 pièces ; `TOTAL_ACTION_SIZE` 1139→1159 ; gym+PvP+journal+analyzer ; 8 tests analyzer |
| 2026-08-17 | Root cause 03.01/09.05 + fix renforcé | `_recompute_squad_occupied_hexes` ; 6 tests, 4 mutations ROUGE ; commits `640cdb53`, `8c2a85f2` |
| 2026-08-17 | `ANTI_INFANTRY:1→2` + garde domaine | `urty_syringe` corrigé ; `MIN_ANTI_THRESHOLD = 2` ; balayage corpus |
| 2026-08-17 | Marqueur activation SHOOT 10.02 | `is_shoot_activation_start` ; `analyzer_couverture.md` mis à jour |
| 2026-08-16 | Réorganisation metrics par phase | `ai/metrics_tracker.py` restructuré ; compteurs charges par épisode |
| 2026-08-12 | Empreinte par figurine fight (pile-in destinations) | 21 sites → `_fight_model_fp_pair` ; 3 cases sur 330 changées ; → `Implémenté/empreinte_par_figurine_fight_2026-08-12.md` |
| 2026-08-12 | Engagement par figurine socle | 13 sites + 14ᵉ jumeau ; 21 530 cases sur 575 515 changées ; `MODEL_HEIGHT` par-figurine |
| 2026-08-12 | Clairance par figurine | 11 appels `low_clearance_ground_hexes` ; `FloorIndex.low_clearance` mémoïsé par hauteur |
| 2026-08-12 | Primitive commune « poser un plan » | `resolve_model_effective_level` + `place_model_at_effective_level` ; 18 sites (6 annoncés + 12 au grep) ; garde dur |
| 2026-08-12 | Contrôle objectif — phases enchaînées | `game_utils.enter_phase` = écrivain unique ; file de frontières ; `run_objective_control_checkpoint` |
| 2026-08-12 | Distance objectif mesurée à l'aire | `engine/objective_distance.py` ; 0,3 µs/appel ; 4 sites migrés ; centroïdes supprimés |
| 2026-08-12 | Deux familles move soldées (empreinte escouade) | `update_units_cache_position` ; 2 violations → 0 sur 2 259 moves ; 2 appelants migrés |
| 2026-08-11 | Socle vs mur — géométrie unique | `hex_utils.socle_blocked_anchor_cells` ; 9 sites placement ; Fall Back 0→1 277 destinations ; 125 tests |
| 2026-08-11 | PvE figé (aperçu tir sans position) | `_require_preview_destination_on_table` ; sort sans requête si unité hors table |
| 2026-08-11 | Masque move exact socles non ronds | Somme de Minkowski ; violation 09.05 0→0 sur WarTrakk |
| 2026-08-11 | Déploiement auto — positions figées supprimées | Déploiement joué par le moteur ; générateur de positions fixées supprimé |
| 2026-08-11 | Perf géométrie — cache engagement par paire | +3,42 s x1, +0,76 s x5 ; 32 Mo/processus ; 18 tests |
| 2026-08-11 | Résidus T1/T2/T3 move pool | `hex_utils.offset_slice_windows` ; `numba` acté non-dépendance ; cache pool d'ancres déploiement |
