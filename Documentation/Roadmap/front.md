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

## 🟢 Couche C — remise en état le 2026-09-09 : **13 verts sur 14, en 37 s** {#couche-c}

Playwright installé (paquet + Chromium) et **huit défauts corrigés**, la couche C est verte :
**13 tests passent**, 1 est skippé par le spec, aucun n'échoue.

Les **invariants de parité front/back** — `greenCircleUnitIds ⊆ move_activation_pool` et
`movePreviewHexes ⊆ valid_move_destinations_pool` — vérifient enfin quelque chose. Ils **passaient
sans jamais comparer** : 401 silencieux faute d'en-tête CSRF, `return` sans assertion, pool lu hors
de l'enveloppe `game_state` (∅ ⊆ tout), et surtout aucun passage en phase move — la partie restait
en `command`, pool vide. Le test l'y amène désormais **par l'interface**, en répondant d'abord aux
deux modales que le jeu ouvre au démarrage (décision Waaagh! 08.04 et dialogue d'enregistrement du
replay), dont le fond interceptait tous les clics.

⚠️ Le bilan « 13 rouges, 6 min 42 » publié plus tôt le même jour était **faux** : il venait de runs
que polluait un Vite orphelin (défaut n° 4 ci-dessous).

**Son entrée dans la vérification large reste à trancher** : 34 s est un coût acceptable, mais la
couche exige deux serveurs, un navigateur, et une **session valide** dans `config/users.db`.

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

**Prérequis qui restent** : la couche exige une **session valide** dans `config/users.db`, non
versionné — elle ne tourne ni dans un worktree neuf sans qu'on y copie la base, ni sur une machine
où personne ne s'est connecté au front. Et les baselines de régression visuelle ne sont pas
versionnées : le test de screenshot écrit la sienne au premier run de chaque machine, en échouant
une fois.

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
