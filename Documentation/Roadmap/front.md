# Front — Tâches ouvertes

---

## Tests front {#tests}

✅ CHANTIER LIVRÉ 2026-08-19 — T7-T13 complets (82 tests vitest verts, Playwright config+E2E, orchestration).

→ `Documentation/Reference/outils/tests_front.md`

**Rectification 2026-09-09.** L'orchestrateur livré ne pouvait pas passer : sa **couche B**
(`npx vitest run`) collectait aussi `frontend/tests/e2e/smoke.spec.ts` — un fichier Playwright dont
le premier import n'existe pas pour vitest — et rendait `1 failed | 36 passed` quel que soit l'état
du code. Frontière déclarée dans `frontend/vite.config.ts` et verrouillée par
`tests/unit/scripts/test_vitest_collect_scope.py`. La couche B (**4,0 s**, 36 fichiers, 430 tests)
entre dans la vérification large de CLAUDE.md.

⚠️ **La couche C n'a jamais pu s'exécuter sur cette machine** : `@playwright/test` est déclaré en
`devDependencies` mais absent de `frontend/node_modules`, et `~/.cache/ms-playwright` est vide. Son
mur reste **non mesuré**, donc son entrée dans la vérification large n'est pas tranchée. À jouer une
fois avant de décider : `npm --prefix frontend install` puis
`npx --prefix frontend playwright install chromium`, et `bash scripts/front_test_all.sh --skip-a --skip-b`.

---

## Validations navigateur en attente {#validations-nav}

Plusieurs chantiers récents ont été livrés sans passage navigateur. À valider en PvP/replay :

| Chantier | Quoi valider |
|---|---|
| Grot Orderly panneau 2026-08-31 | ✅ Validé via test intégration API (4 tests verts) : décision `returned_models_placement` postée + `player` correct + 3 option_index résolvent + partie continue en MOVE |
| Socle vs mur 2026-08-11 | Vérification large utilisateur (suite complète, pyright, conformité, PvE navigateur) |
| Contrôle objectif 2026-08-12 | Vérification large utilisateur |
| Objectif → couleur 2026-08-12 | Validation navigateur (capture d'objectif doit recolorer la zone) |
| Clé contrôle objectif 2026-08-12 | Validation navigateur (capture d'objectif doit toujours recolorer) |
| Aplatissements chemin rendu 2026-08-12 | Navigateur : glisser déploiement rangée du bas ; murs et couleurs objectif inchangés |
| Config plateau BoardPvp 2026-08-12 | Navigateur replay (changement épisode, décor/échelle corrects) + glisser déploiement objectif |
| Terrain transmis au démarrage 2026-09-03 | Navigateur PvP : choisir « Terrain 1 » (mc1) dans le popup, puis vérifier que les murs DESSINÉS bloquent bien le déploiement et qu'aucune zone visuellement vide ne le refuse. Avant le fix, le moteur jouait toujours le terrain par défaut du mode. Vérifier aussi le mode PvE (défaut mc1) et un `?terrain=` d'URL |

---

## ~~Scission `bcKey` géométrie/contrôle~~

**Livré 2026-08-19** — `bcKey` scindé en `geomKey` (dims + zones + murs + dep) et `controlKey` (oc) dans `BoardPvp` ; `buildBoardGeomKey`, `buildBoardControlKey`, `computeStaticLayerReusable` exportés depuis `boardRedrawDecision.ts` ; 13 tests vitest verts (rouge/vert vérifié par mutation).
