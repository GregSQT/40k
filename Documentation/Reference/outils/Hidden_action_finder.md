# ai/hidden_action_finder.py — Détection des actions non loguées

> **Usage** : après une run avec `--step` (et éventuellement avec `debug.log`), exécuter `python ai/hidden_action_finder.py`
>
> **Entrées** : `step.log`, `debug.log` (optionnel pour certaines vérifications)  
> **Sortie** : `hidden_action_finder_output.log` + résumé en console

---

## Objectif

Comparer ce qui s’est réellement passé (mouvements, attaques) avec ce qui est enregistré dans `step.log`. Le script détecte :

1. **Mouvements faits mais non logués** dans step.log (position changes dans debug vs MOVE/FLED/CHARGE/ADVANCE dans step).
2. **Attaques faites mais non loguées** dans step.log (attack_executed dans debug vs SHOOT/FIGHT dans step).
3. **Attaques manquantes en phase fight** : unités avec cibles valides qui n’ont pas attaqué (aucune attaque loguée).
4. **Avertissements** issus de debug.log (ex. unité adjacente à l’ennemi mais n’ayant pas attaqué).

---

## Prérequis

- **step.log** : généré par `python ai/train.py ... --step --test-episodes N`.
- **debug.log** : généré si le moteur écrit des logs `[POSITION CHANGE]`, `[FIGHT DEBUG]`, `[SHOOT DEBUG]` (selon configuration / debug du jeu). Sans debug.log, le script signale son absence et ne peut pas faire les vérifications 1–4.

---

## Utilisation

```bash
# Depuis la racine du projet, après avoir produit step.log (et idéalement debug.log)
python ai/hidden_action_finder.py
```

Sortie principale : **hidden_action_finder_output.log**. Un résumé (succès ou nombre d’erreurs) est aussi affiché en console.

---

## Intégration au workflow

Ce script est typiquement enchaîné avec l’analyzer dans le workflow de validation des règles :

1. Générer les logs : `python ai/train.py ... --step --test-episodes N 2>&1 | tee movement_debug.log`
2. Analyser les violations de règles : `python ai/analyzer.py step.log`
3. Vérifier la cohérence des logs : `python ai/hidden_action_finder.py`

Voir **[Fix_violations_guideline.md](Fix_violations_guideline.md)** pour le workflow complet (consigne / prompt pour automatiser les correctifs) et **[GAME_Analyzer.md](GAME_Analyzer.md)** pour l’analyzer.
