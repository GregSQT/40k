# Stratagèmes réactifs — Fire Overwatch (15.08) et Heroic Intervention (15.11)

**Décision 2026-08-24 :** slots obs réservés avant le run R1, implémentation à J4.

---

## Règles PDF

### Fire Overwatch §15.08 — 1 CP

- **QUAND :** fin de la phase de mouvement adverse.
- **CIBLE :** une unité amie non engagée (sauf TITANIC).
- **EFFET :** l'unité tire en snap shooting (§15.09) :
  - une seule cible ennemie visible à ≤ 24" ;
  - touche uniquement sur 6 non modifié (peu importe BS ou modificateurs) ;
  - aucun re-roll de touche.

### Heroic Intervention §15.11 — 1 CP (+ 1 CP optionnel)

- **QUAND :** fin de la phase de charge adverse.
- **CIBLE :** une unité amie non engagée, à ≤ 12" d'une ou plusieurs unités ennemies. Un VEHICLE doit être CHARACTER/WALKER.
- **EFFET :** résoudre une charge (§11.02) avec cette unité. Avant le jet de charge, choisir un mode :
  - **Leap to Defend (inclus)** : cibles = unités ennemies qui ont fait une charge move ce tour et à portée maximale.
  - **Into the Fray (+1 CP)** : cibles = toutes unités ennemies à ≤ 6" et à portée maximale ; si le jet > 6 après modificateurs, le réduire à 6.

---

## Impact architectural

Les deux mécaniques sont des **interruptions réactives pendant le tour adverse** : le joueur passif prend une décision au milieu d'une phase qu'il ne contrôle pas. C'est le cas le plus complexe du gym.

### Flux d'exécution cible

```
Tour adverse :
  Phase Mouvement adverse (play_movement_phase)
    → fin phase : gym lève un decision point FIRE_OVERWATCH
    → agent répond : {unité cible, unité à utiliser} ou {décline}
    → si accepté : résoudre snap shooting
  Phase Charge adverse (play_charge_phase)
    → fin phase : gym lève un decision point HEROIC_INTERVENTION
    → agent répond : {mode, unité à utiliser, cible de charge} ou {décline}
    → si accepté : résoudre charge HI
```

Ce pattern utilise exactement le mécanisme `agent_decision` existant (§9.3 / `AGENT_DECISION_TYPE_IDS`). Le decision point est levé côté moteur ; la boucle gym reprend son step ; l'agent observe et agit.

**Différence avec `rule_choice`** : le décideur est le joueur PASSIF (is_my_turn = 0). Il faut que l'obs soit cohérente au moment de la décision — en particulier que les positions et statuts ennemis reflètent l'état après la phase qui vient de se terminer.

---

## Slots obs à réserver AVANT le prochain `--new` (R1)

### 1. `AGENT_DECISION_TYPE_IDS` — GRATUIT, pré-dimensionné

Ajouter dans `engine/observation_entities.py` :

```python
AGENT_DECISION_TYPE_IDS: Tuple[str, ...] = (
    "rule_choice", "waaagh_call", "fly_declaration",
    "allocation_model", "charge_placement",
    "fire_overwatch",          # ← nouveau §15.08
    "heroic_intervention",     # ← nouveau §15.11
)
```

Coût : **0 scalaire** (`AGENT_DECISION_TYPE_SLOTS = 8`, actuellement 5 utilisés → 7). Les slots 5 et 6 passent de colonnes réservées à zéro à colonnes réelles.

### 2. `UNIT_BIN_FIELDS` — +1 scalaire par entité

Ajouter `"charged"` dans `UNIT_BIN_FIELDS` (après `"fled"`, avant `"coherent"`) :

```python
UNIT_BIN_FIELDS: Tuple[str, ...] = (
    "is_ally", "is_active",
    "moved", "shot", "fought", "advanced", "fled",
    "charged",          # ← NOUVEAU : a fait une charge move ce tour
    "coherent", ...
)
```

**Pourquoi maintenant.** Heroic Intervention mode *Leap to Defend* ne peut cibler que les unités ennemies qui ont chargé ce tour. Sans ce bit, le mode est inopérant — l'agent ne peut pas distinguer une cible légale. Le réserver maintenant évite un 2e `--new` entre J3 et J4.

**Coût :** +1 × K_ENTITY_SLOTS scalaires. Acceptable dans le --new de R1 plutôt que dans un --new dédié post-J3.

**Remplissage moteur :** `is_ally=1` → flag `has_charged` du game_state allié ; `is_ally=0` → idem pour les ennemis. Le moteur le pose déjà dans le game_state pour résoudre `charge_succeeded`, il suffit de le lire.

### Ce qui N'est PAS nécessaire maintenant

- Pas de nouveau bit global `reactive_prompt_pending` : le champ `decision_pending` du bloc `DECISION_CTX_BIN_FIELDS` existant joue déjà ce rôle, avec `decision_type_fire_overwatch / decision_type_heroic_intervention` pour discriminer.
- Pas de canal "who just moved toward me" : l'`edge_distance` par entité + `moved` suffisent pour le snap shooting (une seule cible, le moteur liste les éligibles dans le masque).
- Pas de bit `used_overwatch_this_phase` par unité : une seule utilisation par phase est garantie par la règle (même stratagem = une fois par phase), le moteur l'impose en dehors de l'obs.

---

## Périmètre d'implémentation (J4)

| Composant | Travail |
|---|---|
| `observation_entities.py` | Ajouter `"charged"` à `UNIT_BIN_FIELDS` + 2 types dans `AGENT_DECISION_TYPE_IDS` (**fait avant R1**) |
| `observation_builder.py` | Écrire `charged` depuis le game_state |
| `macro_intents.py` / `action_decoder.py` | Nouveaux slots action fire_overwatch + HI (cible + mode) |
| `phase_handlers/movement_handlers.py` | Lever `fire_overwatch` decision point en fin de phase adverse |
| `phase_handlers/charge_handlers.py` | Lever `heroic_intervention` decision point en fin de phase adverse |
| `agent_decision.py` | Normaliser les candidats des deux nouveaux types |
| `w40k_core.py` / `pvp_controller.py` | Résoudre snap shooting + charge HI |
| `step_logger.py` | [OVERWATCH] et [HEROIC INTERVENTION] dans step.log |
| Tests | Verrous rouge/vert : décision acceptée / déclinée, snap shooting, charge HI |

**Note sur le coût CP.** Le gym ne gère pas encore les stratagèmes CP en général. L'implémentation devra d'abord confirmer que `my_command_points` et `enemy_command_points` (déjà dans l'obs) sont bien maintenus à jour par le moteur au moment des décisions réactives.

---

## Complexité relative

Overwatch < Heroic Intervention.

- Overwatch : snap shooting = tir simplifié avec masque restreint (une cible, BS ignoré). Pas de choix d'arme. Plus proche d'un tir normal que d'une phase complète.
- HI : charge complète (jet, placement, engagement) pendant le tour adverse, avec le choix de mode (2 options). La cascade post-charge (eligible to fight au tour suivant) découle des règles standards.

Recommandation : implémenter Overwatch en premier (plus simple, confirme le pattern réactif), puis HI.
