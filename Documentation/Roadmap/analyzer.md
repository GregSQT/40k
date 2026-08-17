# Analyzer — Tâches ouvertes

---

## Conformité moteur {#conformite}

**10 erreurs restantes** (sur les 53 mesurées le 2026-08-11, après nettoyage de l'outil).

État sur le journal **2026-08-11 14h34** :

| Symptôme | P1 | P2 | Règle |
|---|---|---|---|
| Mort « fantôme » (état reconstruit ≠ moteur) | 1 (total) | | — |

Les autres familles soldées : CC_NB (CLEAVE), collisions 03.01, fall-back engagé 09.07, move au contact 09.05, tirs hors portée, tir engagé — toutes 0 ou artefacts de mesure.

⚠️ Piste suivante pour la mort fantôme : trois chemins de retrait n'écrivent aucune ligne (cohérence 03.03, blessures mortelles par socle, expiration de réserves) — rattrapés par l'instantané de fin de tour, mesurés à 1 fantôme sur 600 épisodes.

---

## Champs manquants `step.log` {#champs-step-log}

**21 entrées restantes** (L6→L28). L1–L5 livrées. Chaque champ se livre seul et fait passer des règles de « non vérifiable » à « vérifiable ».

À piocher quand un contrôle analyzer manque de données.

→ `Documentation/Implémentation/analyzer_couverture.md` §7

---

## Corpus de règles vérifiable {#corpus-regles}

Sortir les 214 règles du tableau Markdown et en faire une DONNÉE, sur le modèle de `weapon_rules.json` / `unit_rules.json` : une entrée par règle portant son applicabilité, le ou les contrôles qui la mesurent, et son état de vérifiabilité.

L'analyzer rend alors une section de couverture — applicable, utilisée N fois, N erreurs, vérifiable ou non — avec trois interdits par construction : règle applicable et JAMAIS utilisée → ⚠️ ; règle non vérifiable → hors des ✅ ; règle hors roster → ne pèse sur rien.

§1.7 et §1.8 font déjà ça pour les 58 règles d'unité et d'armes — ce chantier généralise aux 156 lignes des PDF.

Ordre de découpe : les entrées PROUVABLES d'abord (69 contrôles vivants + règles dérivables du journal).

→ `Documentation/Implémentation/analyzer_couverture.md` §3, §4, §5-bis
