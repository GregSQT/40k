# Analyzer — Tâches ouvertes

Découpage en 6 lots des trois sujets ci-dessous (ordre séquentiel imposé : tous éditent `ai/analyzer*.py`) → `Documentation/Implémentation/Implémenté/analyzer_conformite_lots.md` ✅ TOUS LIVRÉS

---

## Champs manquants `step.log` {#champs-step-log}

**15** entrées restantes (L6–L28, hors L1/L13/L14/L18/L19/L22/L25/L27/L28 résolues — voir ci-dessous). L1–L5 et L18 livrées. Chaque champ se livre seul et fait passer des règles de « non vérifiable » à « vérifiable ».

Livré (2026-08-19) : `[TARGET_DECL:N]` — effectif cible au SelectTargets step — corrige §1.2 portée (garde `len < alive → unverifiable`) et §1.4 CLEAVE (alive_override → cc_nb exact ; anciens logs → fight_over_cc_nb_unverifiable).

À piocher quand un contrôle analyzer manque de données.

→ `Documentation/Implémentation/analyzer_couverture.md` §7

---

## Corpus de règles vérifiable {#corpus-regles}

**✅ LIVRÉ Lot 5 (2026-08-20)** — 267 entrées dans `config/rules_corpus.json` (60 existantes + 207 migrées). Matrices §3/§4/§5-bis supprimées du Markdown. VERROU : `test_aucun_compteur_en_double_dans_le_corpus` + `test_tous_les_chemins_de_controle_sont_lisibles` (64 verts).

**✅ LIVRÉ Lot 6 (2026-08-20)** — V4/V8/V13 fermés ; 10.02/12.07 câblés ; `wait_with_shootable_target` ; `analyzer_couverture.md` vrai : 0 vert vacant ouvert, COUVERT 65/267. Verrous : 64 verts.

→ `Documentation/Implémentation/Implémenté/analyzer_conformite_lots.md`
