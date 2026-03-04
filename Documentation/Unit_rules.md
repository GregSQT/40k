# Unit Rules - Guide d'implementation

Ce document explique la structure des regles d'unite, comment les declarer, et comment activer les choix contextuels (`choice_timing`) dans le moteur.

## 1) Vue d'ensemble

Le systeme se base sur 2 niveaux:

- `config/unit_rules.json` : registre global des regles (techniques et d'affichage).
- `static UNIT_RULES` dans chaque unite TS : declaration des regles portees par l'unite.

Le moteur resolt ensuite les effets via:

- `ruleId` (regle source portee par l'unite),
- `grants_rule_ids` (sous-regles eventuelles),
- `alias` dans `unit_rules.json` (mapping regle d'affichage -> regle technique).

## 2) Structure de `config/unit_rules.json`

Le fichier est un objet `rule_id -> rule_config`.

Format minimal d'une regle technique:

```json
{
  "reroll_1_tohit_fight": {
    "id": "reroll_1_tohit_fight",
    "description": "During the fight phase, ..."
  }
}
```

Format d'une regle d'affichage (avec alias):

```json
{
  "aggression_imperative": {
    "id": "aggression_imperative",
    "name": "Aggression Imperative",
    "alias": "reroll_1_tohit_fight",
    "description": "During the fight phase, ..."
  }
}
```

Contraintes importantes:

- `id` requis et doit etre identique a la cle JSON.
- `description` requise et non vide.
- `alias` optionnel, mais s'il existe:
  - doit pointer vers une regle existante,
  - ne peut pas pointer vers elle-meme.
- `name` est requis en pratique pour toute regle utilisee comme option de choix (label UI).

## 3) Structure de `UNIT_RULES` dans une unite

Exemple:

```ts
static UNIT_RULES = [
  {
    ruleId: "adrenalised_onslaught",
    displayName: "Adrenalised Onslaught",
    grants_rule_ids: ["aggression_imperative", "preservation_imperative"],
    usage: "or",
    choice_timing: {
      trigger: "phase_start",
      phase: "fight",
      active_player_scope: "both",
    },
  },
];
```

Champs:

- `ruleId` (requis): id de regle present dans `config/unit_rules.json`.
- `displayName` (requis): nom affiche cote unite.
- `grants_rule_ids` (optionnel): liste d'ids de sous-regles (doivent exister dans `unit_rules.json`).
- `usage` (optionnel): mode d'application des sous-regles.
- `choice_timing` (optionnel): quand demander un choix joueur.

## 4) `usage`: modes possibles

- `and`:
  - toutes les `grants_rule_ids` sont actives en meme temps.
  - pas de popup de choix.
- `or`:
  - une seule sous-regle active a la fois.
  - popup de choix.
  - le choix est remis a zero au debut de chaque phase `command`.
- `unique`:
  - une seule sous-regle choisie une fois.
  - le choix reste verrouille pour la suite de la partie.
- `always`:
  - comportement toujours actif (pas de popup), equivalent "toujours applique".

Note:

- Si `grants_rule_ids` contient moins de 2 elements, aucun popup n'est emis.

## 5) `choice_timing`: declencheurs et parametres

`choice_timing.trigger` autorise:

- `on_deploy`
- `turn_start`
- `player_turn_start`
- `phase_start`
- `activation_start`

`choice_timing.phase` autorise:

- `command`, `move`, `shoot`, `charge`, `fight`

`choice_timing.active_player_scope` autorise:

- `owner`: seulement quand le joueur actif est le proprietaire de l'unite.
- `opponent`: seulement pendant le tour/phases de l'adversaire.
- `both`: pour les deux joueurs actifs.

Regles de validation:

- `phase` est requis pour `phase_start` et `activation_start`.
- `active_player_scope` est requis pour `phase_start`.

## 6) Cycle runtime (moteur)

Le moteur:

1. Construit un index `choice_timing_index` a partir des unites vivantes/deployees.
2. Enqueue les prompts au bon moment (`on_deploy`, debut de tour, debut de phase, debut d'activation).
3. Emet `waiting_for_rule_choice` pour un joueur humain.
4. Recoit `select_rule_choice` et stocke `_selected_granted_rule_id` sur la regle source.

Comportement IA:

- cote IA, la premiere option est selectionnee automatiquement.

## 7) Procedure "ajouter une nouvelle regle"

1. Ajouter/mettre a jour la regle technique dans `config/unit_rules.json`.
2. Si besoin de choix joueur, ajouter une (ou plusieurs) regles d'affichage avec:
   - `name`
   - `alias` vers la regle technique
   - `description`
3. Dans l'unite TS (`UNIT_RULES`):
   - declarer la regle source (`ruleId`, `displayName`)
   - renseigner `grants_rule_ids`
   - choisir `usage`
   - ajouter `choice_timing` si un prompt est attendu.
4. Verifier que tous les ids references existent dans `unit_rules.json`.

## 8) Erreurs frequentes

- "Unknown granted unit rule id ...":
  - un id dans `grants_rule_ids` n'existe pas dans `unit_rules.json`.
- Pas de popup:
  - `usage` vaut `and`/`always`, ou `grants_rule_ids` < 2.
- Prompt au mauvais moment:
  - `trigger`/`phase`/`active_player_scope` mal configures.
- Label vide dans popup:
  - la regle de sous-choix n'a pas `name`.

## 9) Exemple complet: Adrenalised Onslaught

`unit_rules.json`:

- `adrenalised_onslaught` (source)
- `aggression_imperative` -> alias `reroll_1_tohit_fight`
- `preservation_imperative` -> alias `reroll_1_save_fight`

`UNIT_RULES` unite melee:

- `usage: "or"`
- `trigger: "phase_start"`
- `phase: "fight"`
- `active_player_scope: "both"`

Effet:

- Au debut de chaque phase fight (joueur actif owner ou opponent), le popup propose 1 choix entre les 2 imperatives.
