# Spécification exécutable V1 - Déploiement autonome agent RL

## 1) Objectif

Définir un contrat d'implémentation **non ambigu** pour que l'agent RL place ses unités en phase `deployment`, sans random placement, avec `MaskablePPO`, en respectant `AI_TURN.md` et `AI_IMPLEMENTATION.md`.

---

## 2) Contraintes non négociables

1. **Single source of truth**
   - Un seul `game_state`.
   - Aucune copie locale de `game_state`.

2. **Activation séquentielle**
   - Une unité active à la fois.
   - Une action de déploiement par `step()`.

3. **Validation stricte**
   - Aucune correction implicite des coordonnées.
   - Aucune action illégale exécutée.
   - Toute donnée requise manquante doit lever une erreur explicite.

4. **Fin de phase par éligibilité**
   - La phase `deployment` se termine uniquement quand aucune unité n'est encore éligible.

5. **Pas de fallback / workaround**
   - Pas de placement automatique de secours.
   - Pas de valeur inventée pour "continuer quand même".

---

## 3) Contrat d'état `game_state`

### 3.1 Champs requis

Quand `deployment_type == "active"`, les champs suivants sont obligatoires:

- `phase == "deployment"` au démarrage de match
- `deployment_state` (objet)
  - `current_deployer` (int joueur actif)
  - `deployable_units_by_player` (dict `player_id -> list[unit_id]`)
  - `deployed_units` (set/list d'IDs déjà placés)
  - `deployment_pools_by_player` (dict `player_id -> set/list[(col,row)]`)
  - `deployment_complete` (bool)
  - `active_unit_id` (unit_id sélectionné pour l'action courante, ou `None`)

### 3.2 Invariants obligatoires

1. Une unité est **placée** si et seulement si son ID est dans `deployed_units`.
2. Une unité non placée doit avoir des coordonnées sentinelles invalides (`col=-1`, `row=-1`) tant qu'elle n'est pas déployée.
3. Une unité ne peut pas être à la fois:
   - dans `deployed_units`, et
   - dans la liste des unités encore déployables.
4. `deployment_complete == True` si et seulement si toutes les unités des deux joueurs sont placées.
5. Si `deployment_complete == True`, `phase != "deployment"` après transition.

### 3.3 Politique de tour de déploiement (fixée V1)

Politique V1 figée pour éviter toute ambiguïté:

- **Ordre par joueur**: le joueur courant place toutes ses unités éligibles, puis passe à l'autre joueur.
- Le passage de joueur se fait uniquement quand la liste deployable du joueur courant est vide.

---

## 4) Contrat d'action

## 4.1 Action sémantique unique (V1)

`deploy_unit { unitId, col, row }`

## 4.2 Validation d'une action `deploy_unit`

L'action est valide uniquement si toutes les conditions sont vraies:

1. `phase == "deployment"`
2. `unitId` appartient à `current_deployer`
3. `unitId` n'est pas déjà dans `deployed_units`
4. `(col,row)` est dans les bornes du board
5. `(col,row)` n'est pas un wall
6. `(col,row)` appartient à `deployment_pools_by_player[current_deployer]`
7. `(col,row)` est libre (aucune unité déjà placée)
8. les restrictions scenario additionnelles sont respectées

Si une condition échoue:

- retourner une erreur explicite actionnable;
- ne modifier aucun champ de state;
- ne pas passer automatiquement à une autre unité.

## 4.3 Effets atomiques d'une action valide

Sur succès, l'engine doit faire atomiquement:

1. écrire la position unité (`col,row`);
2. ajouter `unitId` à `deployed_units`;
3. retirer `unitId` de `deployable_units_by_player[current_deployer]`;
4. mettre à jour l'occupation interne utilisée par les validations;
5. recalculer l'éligibilité de fin de sous-phase / fin globale.

---

## 5) Contrat action-space RL + mask

## 5.1 Mapping canonique V1

Action space discret unique pour toutes les phases, avec branche `deployment`.

Pour la phase `deployment`, le mapping est **canonique et déterministe**:

- index action -> tuple `(unit_slot, hex_slot)`
- `unit_slot` et `hex_slot` sont indexés sur des listes ordonnées de manière stable

Ordres imposés:

1. `deployable_unit_slots`: tri stable par `unit_id` (ordre lexicographique strict)
2. `deployment_hex_slots`: tri stable par `(col,row)` (ordre col puis row)

Règle de stabilité:

- pour une même observation de state, le même index doit pointer vers le même tuple.

## 5.2 Dimension fixe du masque

La dimension du masque doit être **fixe** et définie par configuration explicite.

Clés de config requises:

- `deployment_max_unit_slots`
- `deployment_max_hex_slots`

Dimension branch `deployment`:

- `deployment_action_dim = deployment_max_unit_slots * deployment_max_hex_slots + 1`

Le `+1` correspond à `pass_deployment` (voir 5.3).

## 5.3 Cas masque vide / dead-end local

Action supplémentaire obligatoire:

- `pass_deployment`

Règle:

1. `pass_deployment` est **autorisée uniquement** si aucune action `deploy_unit` n'est légale pour l'unité active (ou pour le joueur actif selon le design retenu).
2. Si au moins un `deploy_unit` légal existe, `pass_deployment` est masquée.
3. `pass_deployment` ne doit jamais terminer silencieusement la phase; elle doit déclencher la logique explicite de résolution (section 7).

Cela garantit qu'un masque entièrement faux n'arrive jamais côté PPO.

---

## 6) Contrat d'observation (minimal V1)

Les informations suivantes doivent être observables pendant `deployment`:

1. joueur actif de déploiement;
2. unité active (identité/slot) ou liste des unités encore déployables;
3. occupation courante du board (au moins sur la zone utile);
4. zone autorisée du joueur actif;
5. indicateur binaire "au moins un placement légal existe".

Contraintes:

- pas de duplication incohérente;
- même source de vérité que les validations action;
- encodage stable entre épisodes.

---

## 7) Contrat de transition et anti-deadlock

## 7.1 Fin de sous-phase joueur

Passage au joueur suivant si et seulement si:

- `deployable_units_by_player[current_deployer]` est vide.

## 7.2 Fin globale `deployment`

Fin de phase si et seulement si:

- toutes les unités des deux joueurs sont dans `deployed_units`.

Alors:

1. `deployment_complete = True`
2. transition vers phase suivante **déterministe** (clé de config requise: `post_deployment_start_phase`)

## 7.3 Deadlock global (obligatoire)

Condition de deadlock:

- il existe des unités non déployées, mais aucune action légale de déploiement n'est possible pour la suite.

Comportement imposé:

- lever une erreur explicite de type `DeploymentDeadlockError` (ou équivalent explicite),
- inclure dans le message: joueur actif, unités restantes, taille des pools, occupation.

Interdit:

- auto-placement,
- suppression silencieuse d'unité,
- fin de phase forcée sans signal d'erreur.

---

## 8) Contrat reward (V1)

1. Reward principal: issue globale épisode (win/loss + performance) inchangé.
2. Shaping déploiement: optionnel, léger, explicite, piloté config.
3. Toute constante de reward doit provenir des fichiers de config.
4. Aucun reward "pansement" pour masquer une validation incorrecte.

---

## 9) Contrat métriques (obligatoire en training)

Métriques minimales par run:

- `deployment_valid_action_rate`
- `deployment_invalid_action_attempt_rate` (doit tendre vers 0 avec mask correct)
- `deployment_steps_mean`
- `deployment_deadlock_count`
- `deployment_pass_count`
- `winrate_with_active_deployment`

Métriques de diagnostic:

- distribution des `hex_slot` choisis
- distribution des `unit_slot` choisis
- corrélation placement initial -> survie / dégâts

---

## 10) Plan de tests exécutable

## 10.1 Tests unitaires (engine)

1. construction des pools par joueur;
2. acceptation placement valide;
3. rejet explicite des placements invalides (hors zone, wall, occupé, hors board, unité déjà placée);
4. passage joueur correct;
5. fin de phase correcte.

## 10.2 Tests unitaires (action decoder / mask)

1. mapping index -> `(unit_slot, hex_slot)` stable;
2. masque vrai uniquement pour actions légales;
3. `pass_deployment` activée seulement en absence d'actions légales.

## 10.3 Tests d'intégration env RL

1. `reset()` démarre en `deployment` si `deployment_type=active`;
2. séquence complète `deployment -> post_deployment_start_phase`;
3. aucun masque vide transmis à PPO.

## 10.4 Tests anti-deadlock

1. scénario avec zones insuffisantes -> erreur explicite attendue;
2. scénario bloqué par walls/occupation -> erreur explicite attendue;
3. vérifier qu'aucun fallback ne masque l'échec.

---

## 11) Critères d'acceptation V1 (Definition of Done)

- [ ] Contrat `deployment_state` respecté et invariant testé
- [ ] Mapping action/mask déterministe et stable
- [ ] Jamais de masque entièrement faux pour PPO
- [ ] Transitions de phase déterministes et testées
- [ ] Deadlock détecté et remonté explicitement
- [ ] Aucun fallback/workaround ajouté
- [ ] Métriques deployment disponibles dans les logs training

---

## 12) Décisions figées V1 (pour éviter les ambiguïtés)

1. Ordre de déploiement: joueur par joueur (complet) en V1.
2. Coordonnées unité non placée: `(-1,-1)` tant que non déployée.
3. Action-space: discret indexé + masque strict.
4. Action de sécurité PPO: `pass_deployment` conditionnelle.
5. Transition post-déploiement contrôlée par `post_deployment_start_phase` (config requise, pas de valeur implicite).

