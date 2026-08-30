# Capacités — Chantier 06

**Chantiers 01→05 livrés** (vérifié code, 2026-08-10) — conceptions 01→04 absorbées dans `Documentation/Reference/moteur/capacites.md` (consolidation 2026-08-28, sources en `Archives/docs/`), journal 05 dans `Documentation/Archives/chantiers/`, et [archives/capacites.md](archives/capacites.md).

---

## 06 — Armageddon abilities {#armageddon-06}

**5/6 passes.** Tous prérequis (01→05) livrés et vérifiés. Jalon J4 — hors du chemin de la mesure de référence.

✅ **Passe 1 — Primitive A `roll_modifiers` (2026-08-30).** Might Is Right (Warboss), Litany of Hate (ChaplainJumpPack), Somethin' to Prove (Bigboss) et le malus de suppression sont vifs, tir et mêlée, avec `clamp(base − bonus + malus, 2, 6)`. Journalisés en tags de ligne (`[MIGHT IS RIGHT]`, `[SUPPRESSED]`, `[LITANY OF HATE]`, `[SOMETHIN' TO PROVE]`), observés (obs_size inchangé), contrôlés par l'analyzer (`fight_hit_threshold_mismatch`, `charge_roll_out_of_range`, plus le seuil de blessure qui connaît désormais Litany). Le statut `suppressed` existe et est purgé au bon moment ; **aucune datasheet ne le POSE avant la passe 6**.

✅ **Passe 2 — Primitive B `granted_weapon_effects` (2026-08-30).** 8 capacités : Breakin' Heads (SUSTAINED HITS 1 mêlée), Vanguard Assault (LETHAL HITS après charge), Overlapping Detonations (BLAST vs non-MV), Dakkablitz (+6 A blitzcannon), Hail of Bolts (+2 A bolt rifle), Waaagh! Energy (+1S +1D/5 figs, HAZARDOUS conditionnel), Da Biggest and da Best (+4 A tant que Waaagh! actif, sur le modèle), Finest Hour (+3 A + DEVASTATING WOUNDS 1×/partie). Point d'intégration : `build_weapon_attack_profile` étendu avec contexte attaquant ; logique split Bloc A (STR avant `wth`) / Bloc B (A/D/BLAST après résolution cible). 27 tests rouge→vert. `rules_corpus.json` §1.5 à jour.

✅ **Passe 3 — Primitive C `feel_no_pain` conditionnel (2026-08-30).** 3 capacités : Dok's Toolz (PainBoy, FNP 5+ générique), Psychic Hood (Librarian, FNP 4+ vs arme PSYCHIC uniquement), Unbreakable Resolve (Ancient, FNP 4+ à ≤3" d'un objectif ou ≤6" du centre). Deux nouveaux types registrés (`feel_no_pain_vs_psychic` obs_id 29, `feel_no_pain_near_objective` obs_id 30). Jets FNP journalisés dans step.log (`fnpSaves`, `fnpThreshold`, `fnp_saves_mortal`, `[FNP:N]`). Multi-FNP séquentiels via `_collect_fnp_thresholds` / `_collect_fnp_thresholds_mortal` / `_roll_fnp_sequential`. 41 tests verts (rouge→vert prouvé).

✅ **Passe 4 — Primitive D `mortal_wounds` (2026-08-30).** 3 capacités : Hold Still and Say Aargh (PainBoy/'urty Syringe, crit wound → D6 BM sur cible non-VEHICLE, séquence d'attaque terminée), Exhortation de Rage (ChaplainJumpPack, sélection combat → D6 : 4-5=D3 BM, 6=3 BM sur ennemi engagé au choix, décision agent `mortal_wounds_target`). Charge impact unifié via `allocate_mortal_wounds` (suppression du décrément HP direct). Deadly Demise WeirdBoy vérifié (chemin déjà câblé). Da Jump failure bloqué Type C (action non implémentée). Nouveau type agent `mortal_wounds_target` (slot 6/8, obs_size inchangé). Deux nouveaux types registrés (`mortal_wounds_on_critical_wound` obs_id 31, `mortal_wounds_on_fight_activation` obs_id 32). 14 tests rouge→vert. `rules_corpus.json` à jour.

✅ **Passe 5 — Primitive E `objective_effects` (2026-08-30).** 3 capacités : Get da Good Bitz (Boyz/Orks) et Objective Secured (Intercessor/SM) — une seule règle générique `secure_objective_on_control` ; en fin de phase de commandement, si l'unité contrôle l'objectif, celui-ci est sécurisé dans `secured_objectives` : l'adversaire doit avoir STRICTEMENT plus d'OC pour le reprendre (14.03). Relic Banner (Ancient) — `oc_bonus` (+1 OC par figurine via `unit_effective_oc`). `calculate_objective_control` et `_calculate_primary_objective_control_counts` honorent les deux mécanismes ; `apply_secure_objective_on_control` appelée en `command_phase_end` après rafraîchissement explicite des contrôleurs. Deux nouveaux types registrés (`secure_objective_on_control` obs_id 33, `oc_bonus` obs_id 34). 12 tests rouge→vert.

**Ordre** : passes 1-5 livrées ; FNP déjà câblé côté moteur.

✅ Recalculé le 2026-08-30 : max 6 capacités simultanées sur une entité (contrainte 19.01 : 1 leader + 1 support max), marge 2 slots. `UNIT_ABILITY_SLOTS = 8` tient pour l'intégralité du chantier 06.

**Prérequis posé (2026-08-25, hors passe) :** Deadly Demise câblé sur WeirdBoy — `unit_rules.json` + `WeirdBoy.ts` + `build_units_cache` + 3 tests. Le mécanisme moteur était déjà livré (moteur.md §24.08) ; ce commit ferme la chaîne roster → engine.

→ `Documentation/Reference/moteur/capacites.md`
