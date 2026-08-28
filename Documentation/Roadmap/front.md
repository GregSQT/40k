# Front — Tâches ouvertes

---

## Tests front {#tests}

✅ CHANTIER LIVRÉ 2026-08-19 — T7-T13 complets (82 tests vitest verts, Playwright config+E2E, orchestration).

→ `Documentation/Reference/outils/tests_front.md`

---

## Validations navigateur en attente {#validations-nav}

Plusieurs chantiers récents ont été livrés sans passage navigateur. À valider en PvP/replay :

| Chantier | Quoi valider |
|---|---|
| Socle vs mur 2026-08-11 | Vérification large utilisateur (suite complète, pyright, conformité, PvE navigateur) |
| Contrôle objectif 2026-08-12 | Vérification large utilisateur |
| Objectif → couleur 2026-08-12 | Validation navigateur (capture d'objectif doit recolorer la zone) |
| Clé contrôle objectif 2026-08-12 | Validation navigateur (capture d'objectif doit toujours recolorer) |
| Aplatissements chemin rendu 2026-08-12 | Navigateur : glisser déploiement rangée du bas ; murs et couleurs objectif inchangés |
| Config plateau BoardPvp 2026-08-12 | Navigateur replay (changement épisode, décor/échelle corrects) + glisser déploiement objectif |

---

## ~~Scission `bcKey` géométrie/contrôle~~

**Livré 2026-08-19** — `bcKey` scindé en `geomKey` (dims + zones + murs + dep) et `controlKey` (oc) dans `BoardPvp` ; `buildBoardGeomKey`, `buildBoardControlKey`, `computeStaticLayerReusable` exportés depuis `boardRedrawDecision.ts` ; 13 tests vitest verts (rouge/vert vérifié par mutation).
