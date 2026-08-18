# Archives Analyzer

| Date | Chantier | Détail |
|---|---|---|
| 2026-08-12 | Conformité moteur — mort fantôme soldée | 3 chemins de retrait fixés (cohérence 03.03, MW par socle `str(unit_id)`, réserves timeout) ; tests `test_analyzer_coherency_removal_ghost.py` + `test_analyzer_hazard_models_ghost.py` ; 0 mort fantôme |
| 2026-08-17 | Trous couverture `hazardous` + `oath_wound` | Branche dispatcher + compteurs `hazardous_mortal_wounds` ; `oath_wound` magnitude depuis EFFECTS ; 5 tests |
| 2026-08-17 | Compteurs `abilities/` | 8 règles × 2 camps, count brut + exposition ; famille A (action_log) + famille B (shot_records) ; 26 tests |
| 2026-08-17 | Proxy count `hit_reroll_exposure` | `max(existant, count > 0)` miroir `oath_wound_bonus` ; 2 tests rouge→vert |
| 2026-08-17 | `damage_exceeds_hp` retiré | Irréalisable par construction ; remplacé par test moteur |
| 2026-08-17 | PSYCHIC statut N/A | `_INTERACTION_ONLY_WEAPON_RULES` ; exclu table §1.8 et résumé ; 3 sites |
| 2026-08-17 | Corpus contrôle §1.2–§2.8 | `rules_corpus.json` étendu ; scalaire `#` pour `state_resync` ; 188 tests |
| 2026-08-17 | Marqueur SHOOT 10.02 | `is_shoot_activation_start` dans `is_activation_marker` ; reset début de tour ; 2 tests |
| 2026-08-12 | Portée jugée AVANT les pertes | `[TARGET_MODELS:]` → liste survivants post-pertes ; gel au Select Targets step ; 31 verdicts → 0 |
| 2026-08-12 | Engagement jugé AVANT les pertes | Gel état au Select Targets step ; jumeau mêlée 12.04 corrigé |
| 2026-08-12 | Journal nomme figurine allouée | `LOG_GRAMMAR_VERSION` ; 496 lignes non vérifiables → 0 ; → `Documentation/Implémentation/Implémenté/figurine_allouee_nommee_au_journal_2026-08-12.md` |
| 2026-08-12 | Non-allouée contrôle retiré | Faux positifs par construction ; invariant en test moteur |
| 2026-08-12 | Deux familles move soldées 03.01+09.05 | `update_units_cache_position` écrasait `occupied_hexes` sur mort ancre ; fix déjà en place depuis 08-12 |
| 2026-08-11 | Mesure cesse de mentir | 370 → 53 erreurs ; 4 fichiers de test créés |
| 2026-08-11 | CC_NB : 24 → 0 (CLEAVE trouvé) | `[CLEAVE:X]` token absent ; `[BLAST]` jumeau traité |
