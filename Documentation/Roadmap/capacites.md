# Capacités — Chantier 06

**Chantiers 01→05 livrés** (vérifié code, 2026-08-10) — conceptions 01→04 absorbées dans `Documentation/Reference/moteur/capacites.md` (consolidation 2026-08-28, sources en `Archives/docs/`), journal 05 dans `Documentation/Archives/chantiers/`, et [archives/capacites.md](archives/capacites.md).

---

## 06 — Armageddon abilities {#armageddon-06}

**1/6 passes.** Tous prérequis (01→05) livrés et vérifiés. Jalon J4 — hors du chemin de la mesure de référence.

✅ **Passe 1 — Primitive A `roll_modifiers` (2026-08-30).** Might Is Right (Warboss), Litany of Hate (ChaplainJumpPack), Somethin' to Prove (Bigboss) et le malus de suppression sont vifs, tir et mêlée, avec `clamp(base − bonus + malus, 2, 6)`. Journalisés en tags de ligne (`[MIGHT IS RIGHT]`, `[SUPPRESSED]`, `[LITANY OF HATE]`, `[SOMETHIN' TO PROVE]`), observés (obs_size inchangé), contrôlés par l'analyzer (`fight_hit_threshold_mismatch`, `charge_roll_out_of_range`, plus le seuil de blessure qui connaît désormais Litany). Le statut `suppressed` existe et est purgé au bon moment ; **aucune datasheet ne le POSE avant la passe 6**.

**Ordre** : passes 1-2 d'abord (12 capacités sans nouvelle structure d'état) ; FNP déjà câblé côté moteur.

✅ Recalculé le 2026-08-30 : max 6 capacités simultanées sur une entité (contrainte 19.01 : 1 leader + 1 support max), marge 2 slots. `UNIT_ABILITY_SLOTS = 8` tient pour l'intégralité du chantier 06.

**Prérequis posé (2026-08-25, hors passe) :** Deadly Demise câblé sur WeirdBoy — `unit_rules.json` + `WeirdBoy.ts` + `build_units_cache` + 3 tests. Le mécanisme moteur était déjà livré (moteur.md §24.08) ; ce commit ferme la chaîne roster → engine.

→ `Documentation/Reference/moteur/capacites.md`
