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

## 🔴 Couche C — exécutée pour la première fois le 2026-09-09, **aucun test vert** {#couche-c}

Playwright installé (paquet + Chromium), la couche C a enfin tourné : **6 min 42, 13 échecs et
1 test skippé sur 14 — aucun ne passe**. Elle **n'entre pas** dans la vérification large. Le mur
mesuré est presque entièrement du timeout (13 × 30 s d'attente d'un canvas qui n'arrive jamais) : il
ne dit rien du coût réel de la couche, à re-mesurer sur des tests verts.

Quatre défauts, dont **trois corrigés** dans `worktree-playwright-couche-c-et-hook` : `__dirname`
indéfini en module ES dans `global-setup.ts` (le setup mourait avant le premier test) ; le proxy
`/api` de `vite.config.ts` figé sur `localhost:5001` quand le script sert le backend sur 5098 (tous
les tests tombaient sur `ECONNREFUSED` — `PW_BASE_URL` ne gouverne que les requêtes de Playwright,
pas celles de la page) ; et `playwright-report/`, `test-results/`, `.auth/` non ignorés, ce dernier
portant le **cookie de session** d'un vrai compte.

**Le `HTTP 500` sur la liste des terrains était un serveur FANTÔME, pas un défaut de l'API.**
`npx vite` n'est qu'un lanceur : le `node …/vite` qu'il crée survivait au script, et le run suivant
— voyant son port pris — laissait Playwright piloter le serveur du run précédent, avec son ancien
proxy. Corrigé (`setsid`, kill de groupe, refus explicite sur port occupé) et verrouillé par
`tests/unit/scripts/test_front_test_all_garde_fous.py`. Reproduit à la main :
`/api/config/terrain-list` rend **200** avec le cookie et l'en-tête `X-W40K-Client`.

**Reste à traiter** : la couche C n'a pas été re-jouée après ce correctif, donc son bilan réel
(13 rouges / 1 skippé) est celui de runs faussés par le fantôme — **il est à refaire**. Elle exige
par ailleurs une **session valide** dans `config/users.db`, non versionné : elle ne tourne ni dans
un worktree neuf, ni sur une machine où personne ne s'est connecté au front.

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
