# Front — Tâches ouvertes

---

## Tests front {#tests}

✅ CHANTIER LIVRÉ 2026-08-19 — T7-T13 complets (82 tests vitest verts, Playwright config+E2E, orchestration).

→ `Documentation/Implémentation/Implémenté/front_test_auto.md`

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

## Scission `bcKey` géométrie/contrôle {#bckey}

**Écartée le 2026-08-12, à arbitrer séparément** (relevé du chantier clé de contrôle d'objectif) : scinder `bcKey` en clé de géométrie et clé de contrôle pour ne plus reconstruire fond et murs à chaque capture d'objectif ; et sortir tout `bcKey` dans `frontend/src/utils/boardRedrawDecision.ts`, à côté de l'invariant qu'il alimente.
