# Capacités — Chantier 06

**Chantiers 01→05 livrés** (vérifié code, 2026-08-10) — conceptions 01→04 absorbées dans `Documentation/Reference/moteur/capacites.md` (consolidation 2026-08-28, sources en `Archives/docs/`), journal 05 dans `Documentation/Archives/chantiers/`, et [archives/capacites.md](archives/capacites.md).

---

## 06 — Armageddon abilities {#armageddon-06}

**3/6 passes.** Tous prérequis (01→05) livrés et vérifiés. Jalon J4 — hors du chemin de la mesure de référence.

✅ **Passe 1 — Primitive A `roll_modifiers` (2026-08-30).** Might Is Right (Warboss), Litany of Hate (ChaplainJumpPack), Somethin' to Prove (Bigboss) et le malus de suppression sont vifs, tir et mêlée, avec `clamp(base − bonus + malus, 2, 6)`. Journalisés en tags de ligne (`[MIGHT IS RIGHT]`, `[SUPPRESSED]`, `[LITANY OF HATE]`, `[SOMETHIN' TO PROVE]`), observés (obs_size inchangé), contrôlés par l'analyzer (`fight_hit_threshold_mismatch`, `charge_roll_out_of_range`, plus le seuil de blessure qui connaît désormais Litany). Le statut `suppressed` existe et est purgé au bon moment ; **aucune datasheet ne le POSE avant la passe 6**.

✅ **Passe 2 — Primitive B `granted_weapon_effects` (2026-08-30).** 8 capacités : Breakin' Heads (SUSTAINED HITS 1 mêlée), Vanguard Assault (LETHAL HITS après charge), Overlapping Detonations (BLAST vs non-MV), Dakkablitz (+6 A blitzcannon), Hail of Bolts (+2 A bolt rifle), Waaagh! Energy (+1S +1D/5 figs, HAZARDOUS conditionnel), Da Biggest and da Best (+4 A tant que Waaagh! actif, sur le modèle), Finest Hour (+3 A + DEVASTATING WOUNDS 1×/partie). Point d'intégration : `build_weapon_attack_profile` étendu avec contexte attaquant ; logique split Bloc A (STR avant `wth`) / Bloc B (A/D/BLAST après résolution cible). 27 tests rouge→vert. `rules_corpus.json` §1.5 à jour.

✅ **Passe 3 — Primitive C `feel_no_pain` conditionnel (2026-08-30).** 3 capacités : Dok's Toolz (PainBoy, FNP 5+ générique), Psychic Hood (Librarian, FNP 4+ vs arme PSYCHIC uniquement), Unbreakable Resolve (Ancient, FNP 4+ à ≤3" d'un objectif ou ≤6" du centre). Deux nouveaux types registrés (`feel_no_pain_vs_psychic` obs_id 29, `feel_no_pain_near_objective` obs_id 30). Jets FNP journalisés dans step.log (`fnpSaves`, `fnpThreshold`, `fnp_saves_mortal`, `[FNP:N]`). Multi-FNP séquentiels via `_collect_fnp_thresholds` / `_collect_fnp_thresholds_mortal` / `_roll_fnp_sequential`. 41 tests verts (rouge→vert prouvé).

**Ordre** : passes 1-3 livrées ; FNP déjà câblé côté moteur.

✅ Recalculé le 2026-08-30 : max 6 capacités simultanées sur une entité (contrainte 19.01 : 1 leader + 1 support max), marge 2 slots. `UNIT_ABILITY_SLOTS = 8` tient pour l'intégralité du chantier 06.

**Prérequis posé (2026-08-25, hors passe) :** Deadly Demise câblé sur WeirdBoy — `unit_rules.json` + `WeirdBoy.ts` + `build_units_cache` + 3 tests. Le mécanisme moteur était déjà livré (moteur.md §24.08) ; ce commit ferme la chaîne roster → engine.

→ `Documentation/Reference/moteur/capacites.md`
