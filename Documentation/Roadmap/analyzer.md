# Analyzer — Tâches ouvertes

Découpage en 6 lots des trois sujets ci-dessous (ordre séquentiel imposé : tous éditent `ai/analyzer*.py`) → `Documentation/Implémentation/Implémenté/analyzer_conformite_lots.md` ✅ TOUS LIVRÉS

---

## Champs manquants `step.log` {#champs-step-log}

**6** entrées restantes (L6–L28, hors L1/L2/L3/L4/L9/L10/L11/L12/L13/L14/L15/L16/L17/L18/L19/L22/L24/L25/L26/L27/L28 résolues). Chaque champ se livre seul et fait passer des règles de « non vérifiable » à « vérifiable ».

Livré (2026-08-20) :
- L11 `[DESPERATE ESCAPE]/[ORDERED RETREAT]` + `Hazard:rolls` sur FLED (09.07/06.03) — 6 verrous.
- L12 `[FNP:saves/seuil+ ×tentatives]` sur Dmg: (24.12) — 4 verrous.
- L15 `[HAZARDOUS:n] Roll:dice` (24.15) — 5 verrous.
- L26 `[POINT-BLANK]` + `base+->eff+` généralisé pour tout `hit_rule_modifier` (10.06 M/V) — 5 verrous.

Bloqués sans implémentation moteur : L20 (terrain — 0 terrain dans scénarios), L21 (Aircraft — 0 hit engine), L23 (surge — 0 hit engine).

À piocher quand un contrôle analyzer manque de données.

→ `Documentation/Implémentation/analyzer_couverture.md` §7

---

## Corpus de règles vérifiable {#corpus-regles}

**✅ LIVRÉ Lot 5 (2026-08-20)** — 267 entrées dans `config/rules_corpus.json` (60 existantes + 207 migrées). Matrices §3/§4/§5-bis supprimées du Markdown. VERROU : `test_aucun_compteur_en_double_dans_le_corpus` + `test_tous_les_chemins_de_controle_sont_lisibles` (64 verts).

**✅ LIVRÉ Lot 6 (2026-08-20)** — V4/V8/V13 fermés ; 10.02/12.07 câblés ; `wait_with_shootable_target` ; `analyzer_couverture.md` vrai : 0 vert vacant ouvert, COUVERT 65/267. Verrous : 64 verts.

→ `Documentation/Implémentation/Implémenté/analyzer_conformite_lots.md`
