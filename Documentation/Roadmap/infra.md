# Infra / Perf / DB — Tâches ouvertes

---

## Perf `generate_compact_formation` {#perf-formation}

½-1 j. **MESURER avant d'implémenter** — gain non acquis.

→ `Documentation/Implémentation/A_faire/perf_generate_compact_formation.md`

---

## ✅ gzip + Brotli livrés (2026-08-18) {#gzip}

**gzip** ✅ `frontend/nginx.conf` : `gzip on`, niveau 6, seuil 1 Ko, `gzip_vary on`, types JSON/JS/CSS/SVG/fonts.

**Brotli** ✅ `frontend/Dockerfile` : stage `brotli-builder` (nginx:1.27-alpine, git/cmake/build-base, clone `ngx_brotli`, source nginx exacte via `${NGINX_VERSION}`, `--with-compat`) ; `.so` copiés dans `/usr/lib/nginx/modules/` ; `load_module` injecté en tête de `/etc/nginx/nginx.conf` (contexte main) ; directives `brotli on/static/level 6/min 1 Ko` dans le bloc server. `test -f` explicite : pas de fallback silencieux si les `.so` manquent.

---

## Noyau natif BFS move/empreintes {#noyau-natif}

**Lourd, EN PAUSE** (décision 2026-08-16 : non lancé). Le pool de déplacement (`build_squad_move_cell_map` → `erode_move_pool_by_squad_block` → `geodesic_move_reach`) pèse **29 % d'une partie d'évaluation** — calcul dérivé, optimisable sous verrou d'empreinte `step.log`.

→ `Documentation/Implémentation/A_faire/perf_noyau_natif_et_gzip.md` §2

---

## Migration PostgreSQL {#postgresql}

**Lourd, re-cadrer avant reprise.** Plusieurs semaines. Spec de mars 2026 visant des modules `ai/` réécrits par V11 depuis — re-confronter au code avant.

→ `Documentation/Implémentation/A_faire/Database/DB_migration.md` ; prompt d'exécution : `Documentation/Implémentation/A_faire/Database/DB_migration_prompt.md`

---

## MCTS adversaire d'entraînement {#mcts}

**Lourd.** Plusieurs semaines (P0+P1 ≈ 1-2 sem.). Après stabilité obs/masques.

Distinct du MCTS à l'inférence ([bot.md#mcts-inference](bot.md#mcts-inference)).

→ `Documentation/Implémentation/A_faire/MCTS/MCTS_bot_final.md`
