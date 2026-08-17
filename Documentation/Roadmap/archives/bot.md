# Archives Bot

| Date | Chantier | Détail |
|---|---|---|
| 2026-08-17 | Scorer réglé §12.17 | `w_contest` 3.5→2.0, `w_crowd` 6.0 ; fix moteur `no_gym_allocation_model` inclus |
| 2026-08-16 | C+D livrées | `ai/benchmark_bots.py` ; 3 bots `reference_*` ; `benchmark_floor` gate ; profil comportemental par adversaire ; 40 tests |
| 2026-08-16 | A+B livrées | Capacités communes (`late_game`, `preservation`, `persistence`) ; jitter SHA256 ; `config/bot_doctrine_profiles.json` ; 82 tests |
| 2026-08-16 | `AttritionBot.wants_charge` corrigé | `super()` manquant supprimait les capacités communes ; 3 tests verrouillage |
| 2026-08-16 | `bench_shortlist.py` livré §13.1 | K=8 → 8,5 % divergence, K=12 → 5,7 % ; 4 bots, 3 scénarios, 200 épisodes |
| 2026-08-15 | Cache contributions OC §13 | `objective_control_contributions` mis en cache par activation dans `_DoctrineBot` |
| 2026-08-13 | Scorer réglé §12.9 | 6 poids encadrés, 3 retenus ; passe de 1,93 à 2,33 zones au tour 5 |
| 2026-08-13 | Decapitation corrigé §12.11 | Marchait vers un ennemi et tirait sur un autre ; `w_objective` rejoué |
| 2026-08-13 | `bot_zone_direct --json-out` | Relevé par épisode ; bloc `run` avec graine/modèle/doctrine ; schéma v2 |
| 2026-08-13 | `bot_zone_direct` validation destination | Chemin vide/dossier/lecture seule échouent en 1 s ; écriture atomique |
| 2026-08-12 | §12.7 invalidé | Deux hausses de poids défaites après re-mesure isolée |
| 2026-08-13 | Nouvelle ligne de base | `combined = 0,7433`, pire bot `racer = 0,630`, rejoué §12.8 |
| 2026-08-11 | Six styles, panel étalé | Modèle de dégâts corrigé par figurine ; pire bot 0,837→0,62 ; §12.5 |
