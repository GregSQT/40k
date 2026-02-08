## Deployment Active V1 (minimal)

### Objectif
Remplacer le deploiement random par un deploiement actif, compatible avec
l'architecture actuelle et les regles AI_TURN.md.

### Scope V1
- Ajout d'une phase `deployment` dans le game flow.
- Placement actif des unites via actions explicites.
- Reutilisation des configs existantes (pas de nouveau schema).

### Hors scope
- Nouveau systeme de config (board/teams/primary/templates).
- UI avancee (undo/redo, templates, saved setups).
- Multi-boards ou multi-scenarios dans un meme match.

### Sources de donnees (sans duplication)
- `config/board_config.json` (cols/rows, wall_hexes).
- `config/deployment/hammer.json` (zones p1/p2).
- `scenario.json` (units, deployment_zone, deployment_type).

### Nouveau comportement attendu
Si `deployment_type` vaut `active`:
- le jeu demarre en `phase="deployment"`;
- aucune unite n'a de position valide avant placement;
- une action `deploy_unit` est requise pour placer chaque unite;
- la phase se termine quand toutes les unites ont ete placees.

### Etat `game_state` (minimal)
Ajouts proposes:
- `phase: "deployment"` pendant le placement.
- `deployment_state`:
  - `current_deployer` (1 ou 2)
  - `deployable_units` (liste d'IDs par joueur)
  - `deployed_units` (set d'IDs)
  - `deployment_pools` (hex valides par joueur)
  - `deployment_complete` (bool)

### Ou sont stockees les unites avant deploiement
- Les unites sont creees dans `game_state["units"]` avec `col/row` provisoires.
- Leur statut "non place" est derive de `deployment_state["deployed_units"]`.
- Une unite est consideree "placee" si son ID est dans `deployed_units`.
 - Recommandation V1: utiliser `col = -1` et `row = -1` tant que l'unite n'est pas placee.

### Comment deployer (flux minimal)
1) Selectionner une unite dans `deployable_units[current_deployer]`.
2) Choisir un hex valide dans `deployment_pools[current_deployer]`.
3) Appeler `deploy_unit {unitId, col, row}`.
4) L'engine:
   - valide l'hex
   - met a jour `unit.col` et `unit.row`
   - ajoute l'ID a `deployed_units`
5) Quand toutes les unites d'un joueur sont placees:
   - `current_deployer` passe a l'autre joueur
6) Quand toutes les unites sont placees:
   - `deployment_complete = true`
   - passage a la phase suivante (`command` ou `move`).

### Regles de validation (strictes)
- hex dans `deployment_pools[player]`.
- hex non occupe et non wall.
- coords dans les bornes du board.
- hex interdits respectes (ex: ligne 20, colonnes impaires).
- erreurs explicites si invalide (pas de fallback).

### Actions (API/engine)
Actions minimales:
- `deploy_unit {unitId, col, row}`
- `undeploy_unit {unitId}` (optionnel V1)
- `confirm_deployment {player}`

Flux:
1) `deployment_start` construit les pools.
2) `deploy_unit` place une unite si valide.
3) quand toutes les unites sont placees:
   - `deployment_complete = true`
   - phase suivante: `command` (ou `move` selon le flow existant).

### Training et PvE (sans random)
Objectif: aucun placement random.
Options V1:
- **Training**: policy de deploiement deterministe (ex: tri par col,row).
- **PvE**: joueur humain place, IA place via policy deterministe.
- Toutes les actions passent par `deploy_unit` (meme chemin que PvP).

### Notes AI_TURN.md
- `game_state` reste source unique.
- pas de copie de state.
- pas de valeurs par defaut "silencieuses".
- erreurs explicites sur donnees manquantes.

### Resultat V1
Un mode de deploiement actif fonctionnel, sans refactor massif, qui:
- supprime le random;
- respecte AI_TURN.md;
- reutilise les configs actuelles.

### Risques & tests minimaux
Risques:
- pool de deploiement vide (zones trop petites ou overlap murs).
- conflit de placements (hex occupe).
- incoherence entre UI et game_state (state non synchronise).

Tests minimaux:
- deployer toutes les unites sans erreur (p1/p2).
- tenter un placement invalide (hors zone, wall, occupe) -> erreur explicite.
- verifier transition `deployment` -> `command`/`move` quand tout est place.

### Checklist d'acceptation (mini)
- chaque unite placee a une position valide (pas de hex interdit).
- aucun placement possible hors `deployment_pools` (erreur explicite).
- `deployment_complete = true` uniquement quand toutes les unites sont placees.
- phase suivante atteinte sans activation automatique non selectionnee.
