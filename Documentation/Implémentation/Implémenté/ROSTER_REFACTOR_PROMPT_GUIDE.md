# Guide Prompt - Refactor rosters P1/P2

## Objectif

Documenter un plan clair pour refactorer la gestion des rosters afin de:
- centraliser les rosters P2 partages,
- gerer des pools P1 par agent (2-3 compos mini),
- reduire la duplication des scenarios,
- conserver un comportement strict (pas de fallback silencieux).

Ce guide sert de base a un prompt d'implementation.

---

## Etat actuel (important)

- Les scenarios agent sont encore au format classique avec `units` complets (`id`, `unit_type`, `player`, `col`, `row`).
- Les rosters P2 partages existent deja ici:
  - `config/agents/_p2_rosters/100pts/training/p2_roster-XX.json`
  - `config/agents/_p2_rosters/100pts/holdout/p2_roster-XX.json`
- Les rosters P2 actuels contiennent encore `id/col/row` (format transitoire).
- Le cablage n'est pas encore fait (les scenarios ne pointent pas encore vers ces rosters).

---

## Cible fonctionnelle

### 1) P2 centralise par echelle

Structure:
- `config/agents/_p2_rosters/<scale>/training/p2_roster-XX.json`
- `config/agents/_p2_rosters/<scale>/holdout/p2_roster-XX.json`

Exemple echelle actuelle:
- `100pts`

### 2) P1 par agent, par split

Structure:
- `config/agents/<agent_key>/rosters/<scale>/training/p1_roster-XX.json`
- `config/agents/<agent_key>/rosters/<scale>/holdout/p1_roster-XX.json`

### 3) Scenarios "minces" (thin scenarios)

Un scenario ne porte plus les deux rosters complets.
Il garde:
- map/deployment/objectifs,
- references vers rosters P1/P2.

Exemple d'intention (a definir precisement dans le prompt):
- `p1_roster_ref`
- `p2_roster_ref`
- `scale`

### 4) Generation runtime stricte

Le loader construit la liste `units` finale a partir des rosters references.

Regles:
- IDs generes de maniere deterministe.
- Positionnement gere par la logique de deploiement existante.
- Erreur explicite si reference roster invalide/manquante.
- Aucun fallback implicite.

---

## Decision sur le format roster (a trancher dans le prompt)

Deux formats possibles:

1. **Format transitoire** (actuel, facile a brancher)
   - `units` avec `id/col/row`.
   - Avantage: impact technique plus faible.
   - Inconvenient: verbeux, duplication inutile.

2. **Format compact cible** (recommande)
   - `composition`: `unit_type + count`.
   - Pas de `id/col/row` dans les fichiers rosters.
   - Avantage: propre, concis, scalable.
   - Inconvenient: necessite un builder runtime.

Recommandation: implémenter directement le format compact si possible.

---

## Fichiers impactes (minimum)

- `config_loader.py`
  - resolution des refs roster,
  - validations strictes des chemins/refs.
- `engine/game_state.py`
  - adaptation du chargement scenario si `units` est derive de rosters,
  - generation IDs si format compact,
  - erreurs explicites si structure invalide.
- `ai/train.py`
  - scenario rotation: compatibilite avec scenarios minces,
  - logs explicites du couple roster choisi (P1/P2).
- Eventuellement `ai/training_utils.py` / `ai/scenario_manager.py`
  - selon le point d'integration choisi pour assembler les scenarios.
- Documentation:
  - `Documentation/AI_TRAINING.md` (format scenario + chemins canoniques),
  - eventuelle note dans `Documentation/AI_IMPLEMENTATION.md` si architecture modifiee.

---

## Contraintes non negociables

- Pas de fallback silencieux.
- Pas de valeurs inventees.
- Erreurs explicites si:
  - roster introuvable,
  - roster mal forme,
  - refs scenario invalides,
  - IDs dupliques apres expansion,
  - unit_type inconnu.
- Comportement deterministe sous seed fixe.

---

## Checklist implementation (copier dans le prompt)

- [ ] Definir schema JSON final pour `p1_roster` et `p2_roster`.
- [ ] Definir schema JSON final pour scenario mince (refs P1/P2 + map/objectifs).
- [ ] Ajouter validation schema stricte (load-time).
- [ ] Implementer assembly runtime des `units`.
- [ ] Implementer generation IDs deterministe (P1 et P2).
- [ ] Logger `p1_roster_id` et `p2_roster_id` dans `step.log`.
- [ ] Migrer au moins 1 agent pilote de bout en bout.
- [ ] Generaliser a tous les agents cibles.
- [ ] Mettre a jour la doc (`AI_TRAINING.md`).
- [ ] Verifier qu'aucun script ne lit encore l'ancien format sans adaptation.

---

## Plan de migration recommande (risque reduit)

1. **Phase A (safe)**
   - cabler rosters P2 centralises sans changer le format (`units` completes).
2. **Phase B**
   - ajouter pools P1 par agent (toujours format complet).
3. **Phase C**
   - migrer vers format compact (`unit_type + count`) avec builder runtime.
4. **Phase D**
   - nettoyer ancien format scenarios/rosters.

---

## Prompt type (mode implementation)

Utiliser ce cadrage:

1. "Implémente le cablage roster en mode strict, sans fallback."
2. "Commence par un agent pilote puis généralise."
3. "Ajoute logs explicites du roster choisi."
4. "Mets a jour la documentation."
5. "Fournis une checklist finale de verification."

---

## Criteres d'acceptation

- Entrainement/test se lance avec scenarios minces references rosters.
- Rotation scenario fonctionne encore.
- IDs uniques et stables.
- Aucune regression sur le deploiement.
- Le chemin canonique `_p2_rosters/<scale>/{training,holdout}` est utilise.
- Documentation coherente avec le code.

