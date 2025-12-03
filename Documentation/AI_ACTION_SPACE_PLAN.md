## AI Action Space Plan

Ce document décrit le plan d'évolution de l'espace d'actions de l'agent RL pour le projet 40k, en respectant `AI_IMPLEMENTATION.md` (architecture) et en appliquant `AI_TURN.md` uniquement pour la logique de tour / de phase.

L'objectif est d'aller, par étapes contrôlées, d'un agent qui pilote surtout **l'ordre d'activation des unités** vers un agent qui contrôle **l'unité, la cible, puis la destination**.

---

## Étape 1 – Choix d’unité par l’agent (shoot / charge / fight)

### Objectif

Donner à l’agent le contrôle de **quelle unité agit** dans chaque phase de combat, sans exploser l’espace d’action ni casser les scripts d’entraînement existants.

À ce stade :
- Le moteur / les handlers restent responsables des **détails d’action** (cible exacte, jets, résolution).
- L’agent choisit **l’ordre des unités** : qui tire, qui charge, qui fight en premier.

### Phases concernées

- **Shoot**
- **Charge**
- **Fight**
- **Move** : inchangé dans cette étape (le moteur choisit encore la destination).

### Action space global

L’espace d’actions Gym reste :

- `action_space = gym.spaces.Discrete(12)`

On change **l’interprétation** des actions par phase, pas la taille globale.

#### Mouvement (phase move) – inchangé à cette étape

Comportement actuel conservé :

- `0..3` : différents **styles / heuristiques** de mouvement (agressif, défensif, etc. – déjà implémentés).
- `11` : **wait** (ne pas bouger).
- Les autres indices sont masqués en phase move.

> Remarque : le mouvement reste piloté par le moteur (choix de la destination exacte). La libération complète du mouvement (choix d’hex) est prévue en Étape 2.

#### Tir (phase shoot) – modifié

Pool d’unités : `shoot_activation_pool` (handlers de tir).

- **Slots d’unité** :
  - `0..9` : slot d’unité dans la pool de tir, après tri et tronquage.
  - `action = i` → "tirer avec l’unité `eligible_units[i]`".
- **Wait** :
  - `10` : **wait** (ne tirer avec **aucune** unité sur ce step).
- Autres :
  - `11` : masqué en phase de tir.

La **cible exacte** reste choisie par :
- `shooting_handlers.shooting_build_valid_target_pool(...)`,
- et la logique de priorité (RewardMapper / turns-to-kill / menace) existante.

##### Masque d’actions (`get_action_mask`) en shoot

1. Construire `eligible_units` depuis `shoot_activation_pool` via `_get_eligible_units_for_current_phase`.
2. Appliquer la limite :
   - `MAX_SHOOT_UNITS = 10`.
   - Si plus de 10 unités éligibles, trier puis tronquer (voir section **Tronquage** ci‑dessous).
3. Pour une pool finale de taille `k` (0 ≤ k ≤ 10) :
   - `mask[0..k-1] = True` (slots d’unité valides).
   - `mask[k..9] = False`.
   - `mask[10] = True` (wait est toujours possible).
   - `mask[11] = False`.

#### Charge (phase charge) – modifié

Pool d’unités : `charge_activation_pool`.

Interprétation identique au tir mais appliquée à la phase de charge :

- `0..9` : slot d’unité dans la pool de charge (max 10 unités).  
  - `action = i` → "cet unité tente une charge / effectue sa phase de charge".
  - Les handlers de charge décident de la destination et de la cible (si plusieurs).
- `10` : wait (aucune unité ne charge ce step).
- `11` : masqué en phase de charge.

Limite :

- `MAX_CHARGE_UNITS = 10` (tronquage éventuel via la stratégie commune décrite plus bas).

#### Fight (phase fight) – modifié

Pools d’unités :  
- `charging_activation_pool`,  
- `active_alternating_activation_pool`,  
- `non_active_alternating_activation_pool`,  
en fonction de `fight_subphase` (`"charging"`, `"alternating_active"`, `"alternating_non_active"`, etc.).

- **Slots d’unité** :
  - `0..5` : slot d’unité dans la pool active de fight (max 6 unités).  
    - `action = i` → "cette unité‑là résout son fight (tous ses attaques CC_NB, comme dans AI_TURN.md)".
- **Wait** :
  - **Pas de wait en fight** (conforme à `AI_TURN.md`) :
    - `10` et `11` sont toujours masqués en phase de fight.

Limite :

- `MAX_FIGHT_UNITS = 6` (géométrie : 6 hex adjacents max).

##### Masque d’actions (`get_action_mask`) en fight

1. Déterminer le sous‑pool actif à partir de `fight_subphase` (ou fallback: concaténation de toutes les pools de fight).
2. Appliquer la limite :
   - Tronquer la liste d’unités éligibles à `MAX_FIGHT_UNITS = 6` (cf. tronquage).
3. Pour une pool finale de taille `k` (0 ≤ k ≤ 6) :
   - `mask[0..k-1] = True`.
   - `mask[k..9] = False`.
   - `mask[10] = False` (pas de wait).
   - `mask[11] = False`.

### Stratégie de tronquage (MAX_*) – Étape 1

Quand il y a plus de candidats que `MAX_*` dans une phase, on doit choisir **quels** sont exposés à l’agent via les slots 0..N‑1.

Pour toutes les phases qui utilisent `MAX_*` (shoot / charge / fight) :

1. **Score de qualité** (via RewardMapper ou équivalent) :
   - Exemple : "valeur / turns to kill", menace, priorité de cible, etc.
2. **Distance croissante** (plus proche d’abord) :
   - Cela favorise naturellement les cibles / unités pertinentes sur le plan spatial.
3. **ID croissant** en dernier ressort :
   - Pour garantir un ordre déterministe et stable.

On sélectionne les `MAX_*` meilleurs, puis on les mappe sur les slots 0..MAX_*-1.

### Ce que l’agent contrôle à l’Étape 1

**Contrôlé par l’agent** :
- L’ordre d’activation des unités en :
  - tir (shoot),
  - charge,
  - fight (y compris les alternances actif / non‑actif).

**Toujours contrôlé par le moteur / handlers** :
- Cible exacte de tir / mêlée / charge (RewardMapper + handlers).
- Destination précise du mouvement (move).

Cette étape donne déjà un comportement beaucoup plus “humain” :
- L’agent peut décider **quelle arme tire d’abord**, **qui finit une cible**, **qui charge en premier**, etc.

---

## Étape 2 – Choix d’unité + cible (et, plus tard, destination de move)

Cette étape est un **chantier séparé**, plus lourd, à planifier après stabilisation de l’Étape 1.

### Objectif

Supprimer progressivement la dépendance à RewardMapper pour le **choix de cible**, de manière à ce que l’agent RL choisisse :
- **l’unité qui agit**, et
- **la cible** (ou la destination) de cette action.

RewardMapper ne devient plus qu’un **producteur de features** (valeur, turns‑to‑kill, menace, etc.) pour l’observation et les rewards, pas un décideur.

### 2.a – Unité + cible en Shoot / Charge / Fight

#### Idée de base

Au lieu d’une action = "slot d’unité" + logique interne pour la cible, on passe à :

```text
action = f(phase, slot_unité, slot_cible)
```

Concrètement :

- Pour chaque unité candidate `u_i`, construire une petite liste de **cibles candidates** `t_{i,0..K}` (tronquée à `MAX_TARGETS_PER_UNIT_*`).
- L’espace d’action se structure comme :

```text
Shoot :  (slot_unité ∈ [0..MAX_SHOOT_UNITS-1], slot_cible ∈ [0..MAX_TARGETS_PER_UNIT_SHOOT-1])
Charge : (slot_unité ∈ [0..MAX_CHARGE_UNITS-1], slot_cible ∈ [0..MAX_TARGETS_PER_UNIT_CHARGE-1])
Fight :  (slot_unité ∈ [0..MAX_FIGHT_UNITS-1], slot_cible ∈ [0..MAX_TARGETS_PER_UNIT_FIGHT-1])
```

Avec par exemple :
- `MAX_TARGETS_PER_UNIT_SHOOT = 5`,
- `MAX_TARGETS_PER_UNIT_CHARGE` petit (souvent 1 ou 2),
- `MAX_TARGETS_PER_UNIT_FIGHT = 3`.

#### Conséquences sur l’implémentation

- **ActionDecoder.get_action_mask** :
  - doit évaluer la validité de chaque couple *(unité i, cible j)*,
  - ne mettre à `True` que les actions correspondant à des couples valides.
- **ActionDecoder.convert_gym_action** :
  - doit décoder `action_int` en `(slot_unité, slot_cible)`,
  - reconstruire l’ID d’unité et l’ID de cible correspondants à partir des listes tronquées,
  - passer explicitement `unitId` et `targetId` aux handlers.

#### Rôle de RewardMapper après Étape 2

RewardMapper ne choisit plus de cible, mais :
- calcule des scores par cible (pour l’obs et les rewards),
- peut être utilisé pour construire / trier les listes de cibles candidates,
- reste la couche de “sens du jeu” (valeur, menaces, turns‑to‑kill), mais **pas la couche de décision**.

### 2.b – Mouvement : choix d’unité + destination

Cette sous‑étape est encore plus ambitieuse et peut venir après 2.a.

#### Idée de base

Pour la phase move :

- Construire, pour chaque unité, un petit **pool de destinations candidates** (par BFS, LoS, objectifs, couvert, etc.).
- Étendre l’espace d’actions pour inclure des actions du type :

```text
action = f(phase = move, slot_unité_move, slot_destination_move)
```

#### Conséquences

- `get_action_mask` doit vérifier la validité de chaque couple *(unité, destination)* :
  - pas de murs, pas d’occupation illégale, distances respectées, etc.
- `convert_gym_action` doit décoder `(slot_unité_move, slot_destination_move)` et passer les coordonnées explicites aux handlers de move.

Cette étape donnerait à l’agent un contrôle **total** sur le positionnement (pas seulement sur l’ordre des activations).

---

## Résumé des étapes

- **Étape 1 (à implémenter maintenant)** :
  - Garder `Discrete(12)`.
  - Donner à l’agent le **choix de l’unité** en shoot / charge / fight via des slots d’unités (`0..9` ou `0..5`).
  - Conserver le choix de cible et de destination dans les handlers (RewardMapper, BFS, etc.).
  - Introduire `MAX_SHOOT_UNITS = 10`, `MAX_CHARGE_UNITS = 10`, `MAX_FIGHT_UNITS = 6` avec tronquage déterministe (Reward score → distance → id).

- **Étape 2 (chantier futur)** :
  - Étendre l’espace d’actions pour coder **unité + cible** en shoot / charge / fight.
  - Repenser ensuite le move pour inclure **unité + destination**.
  - Transformer RewardMapper en **source d’info** (features) plutôt qu’en décideur final.

Ce plan permet :
- de rester aligné avec `AI_IMPLEMENTATION.md` (séquentiel, un seul int d’action),
- de tester rapidement un agent qui commence à jouer “comme un humain raisonnable” (Étape 1),
- tout en préparant une extension naturelle vers un agent **full‑contrôle** (Étape 2) lorsque l’architecture sera stabilisée.


