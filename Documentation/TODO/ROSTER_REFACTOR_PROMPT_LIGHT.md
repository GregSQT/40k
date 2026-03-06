# Prompt (version courte) - Refactor rosters P1/P2

Contexte: repo `/home/greg/40k`.

## But

Refactorer les scenarios pour:
- centraliser P2,
- gerer des pools P1 par agent,
- supprimer la duplication des `units`,
- rester strict (fail-fast, zero fallback).

## Cible

- P2 partage:
  - `config/agents/_p2_rosters/100pts/training/p2_roster-XX.json`
  - `config/agents/_p2_rosters/100pts/holdout/p2_roster-XX.json`
- P1 par agent:
  - `config/agents/<agent_key>/rosters/100pts/training/p1_roster-XX.json`
  - `config/agents/<agent_key>/rosters/100pts/holdout/p1_roster-XX.json`
- Scenarios minces: map/objectifs/deployment + refs rosters (pas de `units` complet).

## Format roster

Utiliser un format compact (pas de `id/col/row`):

```json
{
  "roster_id": "p2_roster-01",
  "composition": [
    { "unit_type": "Intercessor", "count": 4 },
    { "unit_type": "IntercessorGrenadeLauncher", "count": 1 }
  ]
}
```

## Regles strictes

- Pas de fallback silencieux.
- Erreur explicite si:
  - ref roster manquante/invalide,
  - schema invalide,
  - `unit_type` inconnu,
  - IDs dupliques.
- IDs generes deterministes au runtime:
  - P1: `1..N`
  - P2: `101..(100+N2)`
- Le deploiement continue d'utiliser `deployment_zone`/`deployment_type`.

## Travaux

1. Adapter le chargement scenario/rosters:
   - `config_loader.py`
   - `engine/game_state.py`
   - `ai/train.py` (+ utilitaires relies si necessaire)
2. Implementer expansion `composition -> units runtime`.
3. Migrer:
   - rosters P2 existants -> format compact,
   - pools P1 (training/holdout) pour agents cibles,
   - scenarios -> refs rosters.
4. Randomisation P1:
   - training: pick aleatoire dans pool,
   - holdout/test: selection deterministe.
5. Logging:
   - ajouter `p1_roster_id` et `p2_roster_id` dans `step.log`.
6. Mettre a jour `Documentation/AI_TRAINING.md`.

## Validation

- Lancement train/test OK avec scenarios minces.
- Rotation scenario toujours OK.
- IDs uniques et stables.
- Aucun fallback introduit.
- Verif regles:
  - `python scripts/check_ai_rules.py`

## Sortie attendue

- liste des fichiers modifies,
- schema final retenu (scenario + roster),
- erreurs explicites couvertes,
- points de vigilance restants.

