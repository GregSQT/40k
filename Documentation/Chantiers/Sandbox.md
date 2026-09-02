# Mode Sandbox

## Objectif

Permettre au joueur de faire des démonstrations libres : repositionner des figurines sans contraintes, et sauter directement à une phase quelconque sans rejouer le tour depuis le début.

Deux fonctionnalités distinctes :
- **Free move** : désactive les contraintes de déplacement pour la phase en cours.
- **Sélecteur de phase** : avance la partie jusqu'à une phase cible en appelant `end_phase` en boucle (équivalent à cliquer "End Phase" N fois).

---

## 1. Sélecteur de phase

### Mécanique retenue

Le backend possède déjà `_execute_end_phase_action` (`services/api_server.py`), qui vide le pool d'activation de la phase courante par une boucle de `skip`, puis appelle `advance_phase`. Le sélecteur de phase appelle simplement cette action en boucle jusqu'à atteindre la phase voulue.

La séquence canonique est dans `config/game_config.json:phase_order` :
```
deployment → command → move → shoot → charge → fight
```
puis retour à `command` (joueur 2), puis `command` (joueur 1) avec `turn += 1`.

### Effets de bord par transition

| Transition | Effet de bord notable |
|---|---|
| command → move | `apply_secure_objective_on_control` (scoring objectifs) |
| shoot → charge | Vide `shoot_activation_pool`, purge cache LoS |
| charge → fight | Vide `charge_activation_pool`, purge rolls de charge |
| fight (P2) → command | `turn += 1` — **seule** source d'incrément de round |
| toutes | `enter_phase` empile la phase dans `PHASES_TRAVERSED_KEY` → scoring frontières |

En mode sandbox, ces effets se produiront normalement puisqu'on passe par `end_phase` standard. C'est acceptable pour une démo.

### Guards à lever côté backend (`_execute_end_phase_action`)

```python
if game_state["current_player"] != requested_player:
    return error("wrong_player_end_phase")
```

En sandbox, il faut accepter la requête quel que soit le joueur courant.

### Guards à lever côté frontend (`handleEndPhase`)

```typescript
if (gameState.current_player !== player) throw ...
if (!["move","shoot","charge","fight"].includes(phase)) throw ...
```

Le frontend doit appeler `end_phase` sans vérifier le joueur courant, et accepter la phase `command`.

### Flags remis à zéro à chaque début de tour

`command_step_start_of_phase` remet à zéro au début de chaque phase de commandement :
- `units_moved`, `units_shot`, `units_charged`, `units_fought`, `units_fled`, `units_advanced`
- `moved_distance_by_model`, `advance_rolls`
- `units_shot_previous_turn` ← copie de `units_shot`

Quand on saute plusieurs phases d'un coup, ces resets se produisent normalement via la cascade `command_step_start_of_phase`.

### Gestion du round

`_fight_v11_end_progression` : `turn += 1` se déclenche uniquement à la fin du Fight du joueur 2. Si on saute en sandbox depuis le milieu d'un tour sans passer par ce point, le compteur de tour ne bouge pas — comportement attendu.

Si le round maximum est atteint lors d'un saut, la partie se déclare terminée normalement. En sandbox il faudra soit ignorer `max_turns`, soit le rendre configurable.

---

## 2. Free Move

### Contraintes de mouvement actuelles

Toutes vérifiées dans `validate_move_plan` → `explain_move_plan_rejection` (`shared_utils.py`) :

| Contrainte | Guard |
|---|---|
| Budget de distance par figurine | BFS géodésique + `get_squad_move_budget` |
| Zone d'engagement ennemie (EZ) | `build_move_blocked_cells_by_level` |
| Murs | `wall_blocked_anchors` |
| Collisions alliées | doublons `(level, col, row)` |
| Cohérence d'escouade (03.03) | `coherency_violation_flags` |
| Bounds du plateau | `nc < 0 or nr < 0 ...` |
| Terrain / étages | `unit_can_occupy_upper_floor` |

### Ce que "free move" doit désactiver

En mode sandbox, on désactive **toutes** les contraintes sauf les bounds du plateau (on ne peut pas sortir du plateau). La cohérence d'escouade reste optionnellement activable.

Le flag `sandbox_free_move: bool` est à passer dans le `game_state` ou en paramètre de la requête. `validate_move_plan` retourne `True` immédiatement si le flag est actif (sauf bounds).

### Éligibilité au pool de mouvement (`get_eligible_units`)

En mode free move, les unités déjà dans `units_moved` doivent rester sélectionnables (pour les repositionner plusieurs fois). Il faut soit vider `units_moved` après chaque move sandbox, soit ignorer ce filtre quand le flag est actif.

### Portée de "free move"

Le flag s'applique à la phase de mouvement uniquement. Pour un sandbox plus complet, le même principe peut s'étendre au pile-in (`fight_handlers.py`) et à la consolidation, qui partagent `validate_move_plan`.

---

## 3. Contraintes des autres phases (pour référence future)

### Tir

- **Portée** : `_is_valid_shooting_target` — `distance > max_range → False`
- **LoS** : `_has_line_of_sight` (`shooting_handlers.py`) — tracé de ligne hex + murs
- **Engagement** : exclut les unités en CC et celles adjacentes à un ennemi
- **Pool de cibles** : memoïsé par `(uid, col, row, ...)` — à invalider si on repositionne des figurines

En sandbox : désactiver portée + LoS suffit pour la plupart des démos. Le cache LoS (`shooter["los_cache"]`, `game_state["hex_los_cache"]`) devra être purgé après chaque repositionnement.

### Charge

- **Pool de cibles** : `charge_build_valid_targets` (`charge_handlers.py`) — BFS ≤ 12"
- **Distance de charge** : résultat 2D6 × `inches_to_subhex`
- **EZ ennemie** : la destination doit entrer dans l'EZ de la cible

En sandbox : autoriser toute charge vers n'importe quelle unité ennemie, sans jet de dés, avec placement libre.

### Combat

- **Éligibilité** : engagé OU ayant chargé (`fight_v11_is_normal_fight_eligible`, `fight_handlers.py`)
- **Pile-in / consolidation** : budget 3" + doit se rapprocher d'un ennemi ou d'un objectif

En sandbox : si free move actif, le pile-in/consolidation peuvent suivre les mêmes règles allégées.

---

## 4. Frontend — composants concernés

| Composant | Rôle | Modification |
|---|---|---|
| `TurnPhaseTracker.tsx` | Affiche les phases et le bouton "End Phase" | Ajouter boutons de phase cliquables + toggle sandbox |
| `useEngineAPI.ts:handleEndPhase` | Appelle POST `/api/action` `end_phase` | Lever guards joueur/phase en mode sandbox |
| `useGameActions.ts:isUnitEligible` | Filtre d'éligibilité local (mouvement, tir…) | Retourner `true` pour toutes les unités en mode sandbox |
| `BoardWithAPI.tsx` | Orchestre le tout, affiche le plateau | Passer le flag `sandboxMode` en contexte |

Le flag `sandboxMode` peut vivre dans le `game_state` (backend) ou uniquement dans le state React (frontend). Si le but est purement cosmétique/démo sans persistance de partie, le frontend seul suffit pour la plupart des guards — les guards moteur restent à lever côté backend pour les moves réels.

---

## 5. Périmètre d'implémentation estimé

### Phase 1 — Free Move (½ journée)
- Ajouter flag `sandbox_free_move` dans le contexte de la requête move
- `shared_utils.py:validate_move_plan` : bypass si flag actif (sauf bounds)
- `movement_handlers.py:get_eligible_units` : ignorer `units_moved` si flag actif
- Frontend : toggle "Free" dans l'UI + transmission du flag à chaque requête move

### Phase 2 — Sélecteur de phase (½ journée)
- Backend `api_server.py` : nouvelle action `sandbox_jump_to_phase` (ou paramètre sur `end_phase`) qui appelle `_execute_end_phase_action` en boucle jusqu'à la cible, en ignorant la guard de joueur
- Frontend `TurnPhaseTracker.tsx` : rendre les labels de phase cliquables en mode sandbox
- Frontend `useEngineAPI.ts` : lever la guard de joueur et accepter `command` dans `handleEndPhase`

### Phase 3 — Extensions optionnelles
- Désactiver portée/LoS tir en sandbox
- Autoriser charges sans jets
- Ignorer `max_turns`
- Reset manuel des flags d'unités (bouton "Reset turn state")

---

## 6. Risques

| Risque | Mitigation |
|---|---|
| Cache LoS périmé après repositionnement | Purger `los_cache` et `hex_los_cache` à chaque move sandbox |
| `turn += 1` déclenché inopinément | Vérifier que le saut ne passe pas par la fin du Fight P2 sans le vouloir |
| Pool d'activation vide → cascade automatique | La cascade loop de `_process_semantic_action` peut enchaîner plusieurs phases si le pool est vide ; en sandbox, limiter à une phase à la fois |
| `faction_decision_is_pending` bloque la phase command | Décisions Waaagh!/Oath en attente → à auto-résoudre ou skip en sandbox |
