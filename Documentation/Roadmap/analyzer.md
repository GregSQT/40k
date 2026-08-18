# Analyzer — Tâches ouvertes

Découpage en 6 lots des trois sujets ci-dessous (ordre séquentiel imposé : tous éditent `ai/analyzer*.py`) → `Documentation/Implémentation/A_faire/analyzer_conformite_lots.md`

---

## Champs manquants `step.log` {#champs-step-log}

**17** entrées restantes (L6–L28, hors L14/L19/L22/L25/L27/L28 résolues — voir ci-dessous). L1–L5 livrées. Chaque champ se livre seul et fait passer des règles de « non vérifiable » à « vérifiable ».

À piocher quand un contrôle analyzer manque de données.

→ `Documentation/Implémentation/analyzer_couverture.md` §7

---

## Corpus de règles vérifiable {#corpus-regles}

Sortir les 214 règles du tableau Markdown et en faire une DONNÉE, sur le modèle de `weapon_rules.json` / `unit_rules.json` : une entrée par règle portant son applicabilité, le ou les contrôles qui la mesurent, et son état de vérifiabilité.

L'analyzer rend alors une section de couverture — applicable, utilisée N fois, N erreurs, vérifiable ou non — avec trois interdits par construction : règle applicable et JAMAIS utilisée → ⚠️ ; règle non vérifiable → hors des ✅ ; règle hors roster → ne pèse sur rien.

§1.7 et §1.8 font déjà ça pour les 58 règles d'unité et d'armes — ce chantier généralise aux 156 lignes des PDF.

Ordre de découpe : les entrées PROUVABLES d'abord (les contrôles vivants de l'inventaire §2 d'`analyzer_couverture.md` — source unique du compte — + règles dérivables du journal).

→ `Documentation/Implémentation/analyzer_couverture.md` §3, §4, §5-bis ; découpage en lots : `Documentation/Implémentation/A_faire/analyzer_conformite_lots.md`
