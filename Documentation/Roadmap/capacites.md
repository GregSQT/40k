# Capacités — Chantier 06

**Chantiers 01→05 livrés** (vérifié code, 2026-08-10) — conceptions 01→04 absorbées dans `Documentation/Reference/moteur/capacites.md` (consolidation 2026-08-28, sources en `Archives/docs/`), journal 05 dans `Documentation/Archives/chantiers/`, et [archives/capacites.md](archives/capacites.md).

---

## 06 — Armageddon abilities {#armageddon-06}

**0/6 passes.** Tous prérequis (01→05) livrés et vérifiés. Jalon J4 — hors du chemin de la mesure de référence.

**Ordre** : passes 1-2 d'abord (12 capacités sans nouvelle structure d'état) ; FNP déjà câblé côté moteur.

✅ Recalculé le 2026-08-30 : max 6 capacités simultanées sur une entité (contrainte 19.01 : 1 leader + 1 support max), marge 2 slots. `UNIT_ABILITY_SLOTS = 8` tient pour l'intégralité du chantier 06.

**Prérequis posé (2026-08-25, hors passe) :** Deadly Demise câblé sur WeirdBoy — `unit_rules.json` + `WeirdBoy.ts` + `build_units_cache` + 3 tests. Le mécanisme moteur était déjà livré (moteur.md §24.08) ; ce commit ferme la chaîne roster → engine.

→ `Documentation/Reference/moteur/capacites.md`
