# Meta-Controller Multi-Agents (PvE)

## Objectif
Permettre à **un seul joueur** (PvE) d’être piloté par **plusieurs modèles** selon le **type d’unité**.

## Variante : Super-agent (sélection d’unité dans le pool)
Le super-agent **choisit l’unité à activer parmi le pool** (activation non séquentielle).
Cela **modifie la règle AI_TURN** : l’ordre d’activation n’est plus imposé par le moteur.

Conséquences :
- l’action doit inclure **un choix d’unité**
- le masking doit exposer **les unités éligibles**
- le moteur doit accepter **l’unité choisie** (si dans le pool)

## Contraintes AI_TURN
- Activation **séquentielle** (une unité active à la fois)
- Pool = source de vérité (pas de modification IA)
- **Aucune action** sans activation préalable
- **Un seul game_state** (pas de copies)
- **Erreurs explicites** si config manquante

## Configuration
Créer `config/agents/pve_meta_controller.json` :
```json
{
  "controlled_player": 2,
  "model_by_unit_type": {
    "Hormagaunt": "Tyranid_Infantry_Swarm_MeleeSwarm",
    "TyranidWarriorRanged": "Tyranid_Infantry_Troop_RangedTroop"
  },
  "default_model": "Tyranid_Infantry_Swarm_MeleeSwarm"
}
```

Règles :
- `model_by_unit_type` : map unitType → agent_key
- `default_model` : fallback **explicite** (erreur si absent)

## Observation (macro → micro)
### Infos globales (validées)
- `turn`, `phase`, `current_player`
- objectifs contrôlés (par joueur)
- diff de valeur d’armée vivante (sum VALUE P1 − P2)

### Infos par unité (validées)
- `unitType` (ex: `IntercessorGrenadeLauncher`, `Hormagaunt`)
- position (col/row)
- HP / HP_MAX
- `VALUE` (importance relative)
- distance aux objectifs

### Pool éligible
- masque des unités activables (obligatoire)

### Intention stratégique (extension)
- champ `macro_intent` (id entier ou one‑hot)
- prévu, **non utilisé** dans la version initiale
- mise à jour de `obs_size` quand activé

### Exemple d’observation (format suggéré)
```
macro_obs = {
  "global": {
    "turn": 2,
    "phase": "shoot",
    "current_player": 2,
    "objectives_controlled": {"p1": 1, "p2": 2},
    "army_value_diff": -40
  },
  "units": [
    {"id": "7", "unitType": "Hormagaunt", "col": 6, "row": 8, "hp": 1, "hp_max": 1, "value": 5, "dist_obj": 3},
    {"id": "5", "unitType": "TyranidWarriorRanged", "col": 10, "row": 5, "hp": 3, "hp_max": 3, "value": 25, "dist_obj": 5}
  ],
  "eligible_mask": [1, 0, 1, 0, 0]
}
```

## Mode strict recommandé
Pour éviter un routage silencieux via `default_model`, activer un mode strict en production :
- pas de `default_model`, ou flag `strict_mapping=true` (ou `no_default`)
- si `unitType` non mappé → **erreur explicite** + log clair

## Points d’injection
1) `engine/w40k_core.py`  
   - `execute_ai_turn()` : sélectionner **le modèle** selon `unitType`
2) `engine/pve_controller.py` (si utilisé)
   - Charger **plusieurs modèles** au démarrage
   - Router les prédictions par type d’unité

## Implémentation détaillée

### 1) Nouveau module `engine/ai/meta_controller.py`
Fonctions :
- `select_model_for_unit(unit, model_by_unit_type, default_model) -> str`
- `get_action_for_unit(game_state, unit, models_registry) -> int`

Règles :
- `unit["unitType"]` obligatoire
- modèle introuvable → **erreur explicite**
- `default_model` absent → **erreur explicite**

### 2) Chargement des modèles (PvE)
Au démarrage PvE, charger **tous** les modèles requis :
- `models_registry[agent_key] = MaskablePPO.load(...)`
- Aucun chargement dynamique en cours de partie

### 3) Routage par type d’unité
- L’unité active est déterminée par le moteur (pool / active unit)
- Le meta‑controller **ne choisit pas l’unité**, il choisit **le modèle**
- Utiliser le modèle correspondant au `unitType`

### 4) Appel du modèle
- Construire l’observation normalement
- Appeler `model.predict(obs, action_masks=...)`
- Convertir l’action via `action_decoder` (inchangé)

### 5) Invariants AI_TURN à respecter
- Pas de modification des pools
- Pas de multi‑activation simultanée
- Toujours une action par step
- Aucune “fallback” silencieuse

## Super-agent : changements techniques minimaux
### A) Action space
- Ajouter un **sélecteur d’unité** (index dans le pool)
- Le mask doit exposer uniquement les unités éligibles

### B) Step pipeline
- La step devient : `select_unit` → `action`
- Le moteur doit **valider** que l’unité choisie est dans le pool

### C) Observation
- Ajouter le canal `macro_intent` à l’observation
- Mettre à jour `obs_size` dans les configs d’entraînement

### D) Logs & rewards
- Logger l’unité choisie par le super-agent
- Garantir que rewards/logs utilisent l’unité active réellement jouée

## Logs de validation
- `"[META] unitType=Hormagaunt -> model=Tyranid_Infantry_Swarm_MeleeSwarm"`
- `"[META] unitType=TyranidWarriorRanged -> model=Tyranid_Infantry_Troop_RangedTroop"`

## Cas d’erreur (fail‑fast)
- `unitType` absent → erreur explicite
- `default_model` absent → erreur explicite
- modèle introuvable sur disque → erreur explicite
- mismatch action space → erreur explicite

## Tests minimaux
1) PvE avec Hormagaunts + TyranidWarriors
2) Vérifier logs de routage (unité → modèle)
3) Vérifier qu’aucune action n’est générée pour une unité hors type

## Entraînement du macro (super‑agent)
### Observation macro
- État global (positions, PV, objectifs, tour/phase)
- Pool d’unités éligibles (indices)
- Optionnel : menaces / objectifs prioritaires

### Observation macro (spécification détaillée)
Pour chaque unité, on calcule un **profil offensif** séparé tir/mêlée, sans hypothèse
de “cible favorite” fixée dans le type d’unité.
Voir `Documentation/CONFIG_FILES.md` pour la définition de
`game_rules.macro_target_weights` et `game_rules.macro_max_unit_value`.
Les valeurs utilisées doivent provenir de `config/game_config.json` (section `game_rules`).

**1) Scores offensifs par mode (tir et mêlée)**
- Pour chaque arme de tir, calculer un score offensif contre **chaque type d’ennemi**
  (`Swarm`, `Troop`, `Elite`).
- Idem pour chaque arme de mêlée.
- Score = **dégâts attendus sur 1 tour** (meilleure arme uniquement).
- Pondérer ces scores par des **poids de type** définis en config
  (`game_rules.macro_target_weights`).

**2) Meilleur score pondéré par mode**
- `best_ranged_score` = meilleur score pondéré parmi les armes de tir
- `best_melee_score` = meilleur score pondéré parmi les armes de mêlée

**3) Ratio tir vs mêlée (0..1)**
- `attack_mode_ratio = best_melee_score / (best_melee_score + best_ranged_score)`
- Si `best_melee_score + best_ranged_score == 0` → **erreur explicite**

**4) Type de cible optimal (one‑hot)**
- `best_ranged_target_onehot` (3 positions : swarm/troop/elite)
- `best_melee_target_onehot` (3 positions : swarm/troop/elite)
- One‑hot basé sur le type d’ennemi qui produit le **meilleur score pondéré**

**5) Champs scalaires (par unité)**
- `hp_ratio = HP_CUR / HP_MAX`
- `value_norm = VALUE / game_rules.macro_max_unit_value`
- `pos_col_norm`, `pos_row_norm` (coordonnées normalisées)
- `dist_obj_norm = dist_min_objectif / max_range`

### Spécifications complètes (implémentation)
**Score offensif attendu (par arme, par type cible)**
- Utiliser les **mêmes règles que la résolution de combat** (hit/wound/save/AP/invuln).
- Calcul en **espérance** (pas de RNG) :
  - `nb_attacks = expected_dice_value(NB)`
  - `p_hit = P(hit | ATK)` avec `hit_target = ATK` et `p_hit = clamp((7 - hit_target) / 6)`
  - `p_wound = P(wound | STR, T_cible)` (table des blessures)
  - `p_unsaved = 1 - P(save | ARMOR_SAVE, INVUL_SAVE, AP)`
  - `expected_damage = nb_attacks * p_hit * p_wound * p_unsaved * expected_dice_value(DMG)`
- Les probabilites **doivent reproduire la logique moteur** (pas de formule divergente).

**Details exacts (moteur)**
- `expected_dice_value("D3") = 2.0`, `expected_dice_value("D6") = 3.5`.
- `wound_target = _calculate_wound_target(STR, T)` :
  - `STR >= 2*T` -> 2+, `STR > T` -> 3+, `STR == T` -> 4+, `STR*2 <= T` -> 6+, sinon 5+.
- `save_target = _calculate_save_target(target, AP)` :
  - `modified_armor_save = ARMOR_SAVE - AP` (AP negatif degrade la save)
  - `effective_invul = INVUL_SAVE` si > 0, sinon 7 (impossible)
  - `best_save = min(modified_armor_save, effective_invul)`
  - `save_target = clamp(best_save, min=2, max=6)`
- Probabilites d6 :
  - `p = clamp((7 - target) / 6)` avec `target in [2..6]`
Sources moteur :
- `engine/phase_handlers/shooting_handlers.py`: `_calculate_wound_target`, `_calculate_save_target`
- `engine/phase_handlers/fight_handlers.py`: `_calculate_wound_target`, `_calculate_save_target`

**Exemple chiffre (ranged)**
- Arme : `NB=2`, `ATK=3+`, `STR=4`, `AP=-1`, `DMG=1`
- Cible : `T=4`, `ARMOR_SAVE=3+`, `INVUL_SAVE=0`
- `nb_attacks=2`, `p_hit=(7-3)/6=4/6`
- `wound_target=4+` (STR == T) donc `p_wound=3/6`
- `save_target`: `modified_armor_save=3-(-1)=4`, `effective_invul=7`, `best_save=4`
  -> `p_unsaved=1-(7-4)/6=1-3/6=3/6`
- `expected_damage = 2 * (4/6) * (3/6) * (3/6) * 1 = 2 * 36/216 = 0.333...`
La mêlée suit **exactement la même méthode** (NB/ATK/STR/AP/DMG identiques dans le calcul).

**Types cibles de reference**
- `Swarm`: `T=3`, `SV=6+`, `HP_MAX=1`, pas d’invuln
- `Troop`: `T=4`, `SV=3+`, `HP_MAX=2`, pas d’invuln
- `Elite`: `T=5`, `SV=2+`, `HP_MAX=3`, `INVUL_SAVE=4+`

**Ponderations**
- Pondérer par `game_rules.macro_target_weights`.
- Si la cle est absente → **erreur explicite**.

**Meilleur score et tie-break**
- Si plusieurs types ont le meme score pondéré, choisir l’ordre
  deterministe : `Swarm` > `Troop` > `Elite`.
- Si aucune arme pour un mode (tir ou melee) :
  - score = 0
  - one‑hot = `[0,0,0]`

**Ratio tir/melee**
- Si `best_melee_score + best_ranged_score == 0` → **erreur explicite**.
- Sinon calculer `attack_mode_ratio` comme defini plus haut.

**Definition de max_range**
- `max_range` est la **distance hex maximale** possible sur la carte courante,
  calculee une fois au chargement du scenario.
- Elle doit etre disponible dans le `game_state` (ou equivalente) ;
  sinon → **erreur explicite**.

**Format/ordre des features (par unite)**
- `best_ranged_target_onehot` (3)
- `best_melee_target_onehot` (3)
- `attack_mode_ratio` (1)
- `hp_ratio` (1)
- `value_norm` (1)
- `pos_col_norm`, `pos_row_norm` (2)
- `dist_obj_norm` (1)

**Performance**
- Calculer les scores une seule fois par activation si possible.
- Mettre en cache par unite/arme/type cible si l’etat n’a pas change
  (positions, PV, armes).

**Tests minimaux**
- Intercessor : `best_ranged_score > best_melee_score`.
- Hormagaunt : `best_melee_score > best_ranged_score`.
- TyranidWarriorRanged : ratio proche du tir (ranged > melee).

### Action macro
- Choisir **une unité du pool** (version initiale)
- Optionnel : choisir une **intention** (focus objectif, focus unité, tempo)

### Reward macro
- Reward global : victoire/défaite, objectifs capturés
- Bonus intermédiaire léger :
  - progression vers objectifs
  - dégâts nets (infligés − subis)

### Stratégie d’entraînement
1) **Séparé (recommandé)** : micro agents fixes, macro apprend à orchestrer
2) **Simultané** : macro + micro apprennent ensemble (plus instable)

## Évolutions possibles (propositions)
1) **Poids dynamiques** : dériver les poids de type via la valeur moyenne des unités
   ennemies du scénario (plus adaptatif, mais plus bruité).
2) **Top‑k armes** : utiliser la moyenne des 2 meilleures armes au lieu d’un seul max
   (robustesse accrue, mais ajoute un hyper‑paramètre `k`).
3) **Portée/LoS** : intégrer la portée réelle et la ligne de vue dans le score offensif.
4) **Règles d’armes** : inclure ASSAULT/PISTOL/RAPID/MELTA si besoin macro.
5) **Disponibilité d’arme** : ne scorer que les armes réellement sélectionnables
   selon l’état (adjacent, avancé, etc.).

### Micro agents (validé)
- modèles **pré‑entraînés et figés**

## Ordre d’implémentation
1) Ajouter config meta‑controller
2) Implémenter `engine/ai/meta_controller.py`
3) Brancher dans `pve_controller.py` / `w40k_core.execute_ai_turn`
4) Ajouter logs de debug
5) Tester en PvE avec deux types d’unités

## Ordre d’implémentation (super‑agent)
1) Ajouter action “select_unit” + mask unités éligibles
2) Ajouter canal `macro_intent` dans l’observation
3) Mettre à jour `obs_size` dans configs
4) Brancher super‑agent dans `execute_ai_turn`
5) Tests : validité pools + cohérence logs/rewards
