# Prompt implementation - Refactor rosters P1/P2

Tu travailles dans le repository Warhammer 40K (`/home/greg/40k`).

## Objectif

Refactorer la gestion des scenarios d'entrainement pour:

1) centraliser les rosters P2 partages,
2) gerer des pools P1 par agent,
3) eviter la duplication massive des `units` dans les scenarios,
4) rester strict (pas de fallback silencieux).

## Contraintes non negociables

- Ne jamais inventer de valeur.
- Erreurs explicites si une donnee requise manque.
- Pas de fallback silencieux.
- Pas de workaround.
- Garder la compatibilite avec la logique de deploiement (`deployment_zone`, `deployment_type`) deja presente dans les scenarios.
- Les IDs ne sont plus stockes dans les rosters; ils doivent etre generes de maniere deterministe au build runtime.

## Cible de structure

### P2 centralise

- `config/agents/_p2_rosters/100pts/training/p2_roster-XX.json`
- `config/agents/_p2_rosters/100pts/holdout/p2_roster-XX.json`

### P1 par agent

- `config/agents/<agent_key>/rosters/100pts/training/p1_roster-XX.json`
- `config/agents/<agent_key>/rosters/100pts/holdout/p1_roster-XX.json`

### Scenarios minces

Les scenarios agent ne doivent plus embarquer les listes `units` completes.
Ils doivent contenir:
- map / objectifs / deployment,
- references roster P1 et P2,
- echelle (`100pts`).

Exemple attendu (schema indicatif, ajuste si necessaire mais reste coherent partout):

```json
{
  "deployment_zone": "hammer",
  "deployment_type": "active",
  "scale": "100pts",
  "p1_roster_ref": "training/p1_roster-01",
  "p2_roster_ref": "training/p2_roster-01",
  "wall_hexes": [...],
  "primary_objectives": [...],
  "objectives": [...]
}
```

## Format roster cible (compact)

Utiliser ce format pour P1 et P2:

```json
{
  "roster_id": "p2_roster-01",
  "composition": [
    { "unit_type": "Intercessor", "count": 4 },
    { "unit_type": "IntercessorGrenadeLauncher", "count": 1 },
    { "unit_type": "TyranidWarriorRanged", "count": 1 }
  ]
}
```

Pas de `id`, `col`, `row` dans les rosters.

## Travaux a faire (ordre impose)

1. **Analyser le chargement scenario actuel**
   - `config_loader.py`
   - `engine/game_state.py` (`load_units_from_scenario`)
   - `ai/train.py` / `ai/training_utils.py`

2. **Implementer la resolution roster**
   - Charger refs P1/P2 depuis scenario mince.
   - Resoudre les chemins selon:
     - P1: `config/agents/<agent_key>/rosters/100pts/...`
     - P2: `config/agents/_p2_rosters/100pts/...`
   - Lever erreur explicite si ref invalide/manquante.

3. **Implementer l'expansion composition -> units runtime**
   - Expand `count` en unite runtime.
   - Generer IDs deterministes et uniques.
     - Convention recommandee:
       - P1: `1..N`
       - P2: `101..(100+N2)`
   - Ne pas assigner de coordonnees dans les rosters.
   - Laisser la logique de deploiement gerer le placement via `deployment_zone`/`deployment_type`.

4. **Migration des donnees**
   - Convertir les rosters P2 existants vers format compact.
   - Creer les rosters P1 pour les agents cibles (au moins 2-3 compos training + 2 holdout).
   - Migrer les scenarios existants vers format mince (refs rosters).

5. **Randomisation P1**
   - En mode training, selectionner aleatoirement un roster P1 parmi le pool.
   - En holdout/test, mode deterministe (ref explicite par scenario).
   - Logger le roster choisi (P1/P2) dans `step.log` et infos episode.

6. **Documentation**
   - Mettre a jour `Documentation/AI_TRAINING.md` avec:
     - nouveaux chemins canoniques,
     - format scenario mince,
     - format roster compact,
     - regles de generation IDs.

## Validation obligatoire

- Verifier qu'aucun fallback silencieux n'a ete introduit.
- Verifier que les scenarios fonctionnent sans champ `units` complet.
- Verifier IDs uniques en runtime.
- Verifier que la rotation scenario training fonctionne toujours.
- Verifier logs roster (`p1_roster_id`, `p2_roster_id`) dans `step.log`.
- Lancer la verification regles:
  - `python scripts/check_ai_rules.py`

## Sortie attendue

A la fin, fournir:
- la liste des fichiers modifies,
- les decisions de schema retenues,
- les cas d'erreur explicite couverts,
- un mini plan de rollback si besoin.

