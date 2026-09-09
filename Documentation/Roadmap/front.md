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

## 🔴 Couche C — exécutée pour la première fois le 2026-09-09, **13 tests rouges sur 14** {#couche-c}

Playwright installé (paquet + Chromium), la couche C a enfin tourné : **~7 min, 13 échecs sur 14**.
Elle **n'entre pas** dans la vérification large tant qu'elle est rouge.

Quatre défauts, dont **trois corrigés** dans `worktree-playwright-couche-c-et-hook` : `__dirname`
indéfini en module ES dans `global-setup.ts` (le setup mourait avant le premier test) ; le proxy
`/api` de `vite.config.ts` figé sur `localhost:5001` quand le script sert le backend sur 5098 (tous
les tests tombaient sur `ECONNREFUSED` — `PW_BASE_URL` ne gouverne que les requêtes de Playwright,
pas celles de la page) ; et `playwright-report/`, `test-results/`, `.auth/` non ignorés, ce dernier
portant le **cookie de session** d'un vrai compte.

**Reste à traiter** : la page rend `Impossible de charger la liste des terrains : terrain-list: HTTP 500`,
donc le canvas PIXI n'apparaît jamais et les 13 tests expirent en l'attendant. La couche exige par
ailleurs une **session valide** dans `config/users.db`, non versionné : elle ne tourne ni dans un
worktree neuf, ni sur une machine où personne ne s'est connecté au front.

Détail et commandes : `Documentation/Reference/outils/tests.md`.

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
