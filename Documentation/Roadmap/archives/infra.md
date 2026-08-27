# Archives Infra

| Date | Chantier | Détail |
|---|---|---|
| 2026-08-18 | gzip + Brotli | **gzip** : `frontend/nginx.conf` — `gzip on`, niveau 6, seuil 1 Ko, `gzip_vary on`, types JSON/JS/CSS/SVG/fonts. **Brotli** : `frontend/Dockerfile` — stage `brotli-builder` (nginx:1.27-alpine, git/cmake/build-base, clone `ngx_brotli`, source nginx exacte via `${NGINX_VERSION}`, `--with-compat`) ; `.so` copiés dans `/usr/lib/nginx/modules/` ; `load_module` injecté en tête de `/etc/nginx/nginx.conf` (contexte main) ; directives `brotli on/static/level 6/min 1 Ko` dans le bloc server. `test -f` explicite : pas de fallback silencieux si les `.so` manquent. |
| 2026-08-24 | ✅ fix type-errors tsc/pyright/check_ai_rules (2026-08-24) — 17 fichiers, 0 erreur après correction | infra · — |
| 2026-08-21 | ✅ gate roadmap exclut merges tests-only (2026-08-21) — `merge_only_touches_tests` dans `check_roadmap_declared.py` : un merge ne touchant que `tests/` n'est plus compté dans la dette ; 26 tests verts | infra · — |
| 2026-08-23 | ✅ mémoïsation `_deploy_pool_set` (2026-08-23) — zone mise en cache par joueur dans `game_state`, purgée aux deux chemins de re-publication ; −26 % par formation (10,79 → 7,94 ms) ; 5 verrous rouge/vert. Chantier CLOS, doc dans `Documentation/Archives/chantiers/perf_generate_compact_formation.md` | infra · — |
| 2026-08-23 | ✅ bench piste 1 érosion mesurée (2026-08-23) — non rentable ; goulot confirmé = marge inter-fig | infra · — |
| 2026-08-23 | ✅ Perf `generate_compact_formation` margin_blocked incrémental (2026-08-23) — O(N×fp×6) → O(fp) par cellule BFS ; suite verte, aucun verrou d'équivalence de plan (cf. SUITE du doc) | infra · — |
| 2026-08-23 | ✅ 13 exemptions check_ai_rules (2026-08-23) — fix-fallback-anti-error-exemptions : exemptions déclarées pour check_ai_rules, sans workaround anti-erreur | infra · — |
| 2026-08-18 | ✅ gzip + Brotli livrés (2026-08-18) — stage `brotli-builder`, `load_module` contexte main, directives server | infra · [archives/infra.md](archives/infra.md) |
| 2026-08-24 | ✅ fix pyright + terme interdit (2026-08-24) — erreurs pyright + terme interdit corrigés | infra · — |
| 2026-08-24 | ✅ fix pyright ai rules (2026-08-24) — corrections pyright + règles IA | infra · — |
| 2026-08-26 | ✅ item 1.7 buffers numpy observation (2026-08-26) — ~27 np.zeros/build supprimés : buffers pré-alloués réutilisés dans observation_builder | infra · [infra.md#perf-entrainement](infra.md#perf-entrainement) |
| 2026-08-26 | ✅ Phase 2 pipeline SB3 learner items 2.1–2.3 (2026-08-26) — GpuMaskableDictRolloutBuffer (upload H2D ×1/rollout), accumulation GPU des métriques PPO (~225 syncs éliminés), MaskableSubprocVecEnv+PatchedMaskablePPO (RPC masks inline) ; 11 tests rouge/vert | infra · [infra.md#perf-entrainement](infra.md#perf-entrainement) |
| 2026-08-26 | ✅ /code-review findings + /simplify (2026-08-26) — garde batch obsolète move cache supprimée (shared_utils), walrus models_cache obs (observation_builder), parser.error bot_zone_direct, pop _ez_fp redondant (fight_handlers), re-export gs_with_units (_fabriques) | infra+moteur · — |
| 2026-08-24 | ✅ fix pyright/biome/tsc — 6 erreurs corrigées (2026-08-24) — 6 erreurs de types corrigées après migration | infra · — |
| 2026-08-24 | ✅ fix pyright test_expected_damage (2026-08-24) — 12 erreurs pyright corrigées dans test_expected_damage ; signature expected_damage alignée | infra · — |
