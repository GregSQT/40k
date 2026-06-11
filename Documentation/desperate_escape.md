# Desperate Escape — Hazard rolls & attribution manuelle des mortal wounds

> Spec d'implémentation. Objectif : rendre l'attribution des mortal wounds du hazard roll
> (Desperate Escape) conforme aux règles 40k, avec choix du joueur quand il existe, et
> déplacer le hazard roll à l'**activation** de l'unité (avant le move preview).

---

## 1. Contexte & objectif

En phase de move, une unité **engagée** (dans l'Engagement Range ennemie) qui se déplace fait
un **Fall Back** (09.07). Deux modes :

- **Ordered Retreat** : unité **non** battle-shocked → aucun hazard.
- **Desperate Escape** : unité **battle-shocked** → **hazard roll par figurine** (06.03).

Aujourd'hui le hazard roll fonctionne (Part B), mais :

1. **Bug** : les mortal wounds sont appliqués via `update_units_cache_hp` = HP **agrégé** de
   l'unité. Sur une unité multi-figurines, ça baisse le total **sans retirer de figurine
   précise** (`models_cache` / `squad_models` intacts). Le bon chemin est `destroy_model`.
2. **Pas d'attribution joueur** : le joueur qui contrôle l'unité doit pouvoir attribuer les
   mortal wounds aux figurines, selon la séquence 06.02 (avec choix là où la règle en laisse).
3. **Timing** : le hazard est aujourd'hui appliqué au **commit** du move. On veut le faire à
   l'**activation** (avant le preview), conformément à 09.07 (« BEFORE MOVING »).

---

## 2. Règles officielles (source : `Documentation/40k_rules/`)

### 09.07 — Fall Back move
- ELIGIBLE IF : l'unité est engagée. MAX DISTANCE : caractéristique M.
- BEFORE MOVING : choisir le mode. Desperate Escape (si battle-shocked) → **hazard roll par
  figurine** (06.03).
- WHILE MOVING : Desperate Escape → chaque figurine peut traverser les figurines ennemies.
- AFTER MOVING : l'unité doit être désengagée ; ne peut ni tirer, ni charger, ni faire une
  action ; (Desperate Escape) si l'unité n'est **pas** battle-shocked → battle-shock roll
  (no-op chez nous puisque Desperate Escape ⟺ battle-shocked).

### 06.03 — Hazard rolls
> To make a hazard roll for a unit, roll one D6: on a 1-2, that roll fails and that unit
> suffers 1 mortal wound, or **3 mortal wounds** instead **if each model in that unit is a
> MONSTER/VEHICLE** model. If more than one hazard roll is required, make all rolls
> simultaneously.

Desperate Escape : **1 hazard roll par figurine vivante**.

### 06.02 — Mortal wounds (séquence d'attribution)
Pour chaque mortal wound, jusqu'à ce que toutes soient infligées ou l'unité détruite :
1. **Select Model** — première instruction applicable :
   - une figurine **non-CHARACTER** ayant déjà perdu ≥1 wound → on **doit** la choisir ;
   - sinon, s'il existe des figurines non-CHARACTER → on **doit** en choisir une ;
   - sinon, si des CHARACTER ont perdu des wounds → on **doit** en choisir un ;
   - sinon → choisir un CHARACTER.
2. **Resolve Damage** — la figurine choisie perd 1 wound ; à 0 → détruite.

**Conséquence (clé pour l'UI)** : le **choix** du joueur n'existe qu'entre figurines
**également éligibles** à l'étape courante (ex. plusieurs non-CHARACTER au plein PV, ou — cas
demandé — **2 CHARACTERs** également au plein PV). Dès qu'une figurine multi-wound est entamée,
les wounds suivantes **doivent** aller dessus (elle est « wounded ») jusqu'à sa mort, puis le
choix réapparaît sur les figurines restantes.

### 01.07 / 01.06 — Battle-shock / leadership (déjà implémentés)
2D6 ≥ Ld → succès. Le bouton de test `force_battle_shock` existe déjà.

---

## 3. État actuel du code

### Backend
- `engine/phase_handlers/shared_utils.py`
  - `roll_hazard_for_unit(unit_id, game_state)` (~2816) : roule 1D6/fig, applique les MW via
    `update_units_cache_hp` (**agrégé — à remplacer par `destroy_model`**), loggue `[HAZARD]`.
  - `roll_battle_shock(unit_id, game_state)` (~2878).
  - `desperate_escape_pre_move(squad_id, game_state, was_engaged)` (~2915) →
    `(is_desperate, is_alive, hazard_wounds)`. Appelé par les deux commit-paths.
  - `desperate_escape_post_move(squad_id, game_state)` (~2935) : no-op fonctionnel.
  - `destroy_model(game_state, model_id, reason)` (~2537) : **retrait propre d'une figurine**
    (reasons : `combat`, `coherency_removal`, …). C'est la primitive cible.
  - `_build_alloc_groups(game_state, target_sid)` (~4568) : groupes 05.03 (non-CHARACTER
    d'abord, puis 1 groupe/CHARACTER). Réutilisable pour grouper l'éligibilité 06.02.
  - `_is_character_role(role)` (~4543), `_group_alive` (~4611).
- `engine/phase_handlers/movement_handlers.py`
  - `movement_destination_selection_handler` (~2784) : commit **rigide** (action `move`).
    Contient aujourd'hui le bloc Desperate Escape (`desperate_escape_pre_move` avant
    `_attempt_movement_to_destination`, `desperate_escape_post_move` après). **À retirer**
    (déplacé à l'activation).
  - `movement_commit_move_plan_handler` (~2481) : commit **per-figurine** (action
    `commit_move_plan`). Même bloc Desperate Escape (~2530). **À retirer.**
  - `movement_unit_execution_loop` (~825) / `_handle_unit_activation` (~776) : renvoient
    `would_flee` = `_squad_is_in_enemy_er(...)` au moment de l'activation. **Point d'injection
    du nouveau flux.**
- `engine/w40k_core.py`
  - `_process_semantic_action` (~2609) : early-return `force_battle_shock` (~2623). Blocage des
    actions tant que `pending_shoot_allocation` n'est pas résolu (~2653) → **pattern à copier
    pour `pending_hazard_allocation`.**

### Système d'allocation manuelle du TIR (référence — NE PAS réutiliser tel quel)
- Couplé aux armes : weapon groups, jets de save par blessure (`pending_wounds.save_roll`),
  `declare_order` des groupes d'armes. Les mortal wounds n'ont **ni arme ni save**.
- `pending_shoot_allocation` (state), `apply_manual_shoot_allocate_model`,
  `_manual_allocation_step`, `manual_allocation_waiting_payload` (~5122).
- Frontend : `ManualAllocation` interface (`useEngineAPI.ts` ~385), `manualAllocation` state,
  `onAllocateModel` → action `squad_shoot_allocate_model` (~4088), réponse `data.result.allocation`
  (~1545). **Pattern UI réutilisable** : `choices: [{model_id, col, row, HP_CUR, HP_MAX}]`,
  `wounds_remaining`, clic sur une figurine.

**À réutiliser** : `destroy_model`, la logique d'ordre 06.02, le **pattern UI** (clic figurine +
`wounds_remaining`). **À NE PAS réutiliser** : le pipeline weapon-groups/saves du tir.

---

## 4. Workflow cible (validé)

1. Le joueur **active** une unité en phase de move.
2. Si l'unité est **engagée ET battle-shocked** → **popup d'avertissement** : « Déplacer cette
   unité = Fall Back en Desperate Escape : jets de hazardous (1 MW par figurine sur 1-2) avant
   de bouger. Continuer ? » (Une unité engagée **non** shockée → pas de popup, Ordered Retreat.)
3. Si le joueur **valide** :
   - on **suspend le move** (pas de preview, pas de pool de destinations) ;
   - l'unité **reste sélectionnée** ;
   - on **roule le hazard** (06.03) et on entre en **attribution** des mortal wounds (06.02) :
     - cas sans choix (fig forcée, ou unité mono-fig) → **auto-résolution** silencieuse ;
     - cas avec choix (≥2 figs également éligibles, **y compris 2 CHARACTERs**) → **prompt**
       de sélection de figurine (clic), une MW à la fois.
   - application via `destroy_model`.
4. Quand l'attribution est terminée :
   - si l'unité est **détruite** → fin d'activation, **pas de move** (log `desperate_escape_died`) ;
   - sinon → on **repart sur le move preview** normal (Fall Back), budget M.
5. Si le joueur **annule** le popup → l'unité reste sélectionnée mais **non déplacée** (revenir
   au choix d'action ; pas de hazard tant qu'elle ne s'engage pas dans le move).

> Note : popup distinct du « retreat alert » existant (`fleeWarningPopup` / `shouldShowRetreatAlert`,
> `useEngineAPI.ts`). Voir si on mutualise ou si on ajoute un popup dédié hazard.

---

## 5. Architecture backend

### 5.1 Nouvel état : `pending_hazard_allocation`
Calqué sur `pending_shoot_allocation`. Posé quand un hazard inflige des MW nécessitant un choix.
Structure proposée :
```
game_state["pending_hazard_allocation"] = {
    "squad_id": str,
    "controlling_player": int,          # = player de l'unité (≠ tir : c'est l'actif)
    "wounds_remaining": int,            # MW restant à attribuer
    "wounds_per_fail": int,             # 1 ou 3 (MONSTER/VEHICLE)
    "resume": "move_activation",        # quoi faire une fois fini
}
```
- Bloquer les autres actions tant que présent (copier le garde-fou `_process_semantic_action`
  ~2653, n'autoriser que l'action d'allocation hazard).
- `manual_allocation_waiting_payload`-équivalent pour le front.

### 5.2 Découplage hazard → activation
- **Retirer** `desperate_escape_pre_move` / `desperate_escape_post_move` des deux commit-paths
  (Part B) — voir §3.
- À l'activation (`_handle_unit_activation` / `movement_unit_execution_loop`) : si
  `would_flee && battle_shocked` → ne PAS construire le pool tout de suite ; renvoyer un signal
  `requires_hazard = True` (popup côté front).
- Nouvelle action `hazard_confirm` (le joueur valide le popup) :
  1. roule le hazard (réutiliser/raffiner `roll_hazard_for_unit` → version qui **n'applique pas**
     l'agrégat mais délègue à l'allocation) ;
  2. boucle d'attribution 06.02 (auto + prompt) ;
  3. si détruite → `desperate_escape_died` ; sinon → construire le pool de move (Fall Back) et
     repasser en `waiting_for_player`.

### 5.3 Logique d'attribution 06.02 (cœur)
Fonction `allocate_mortal_wounds(game_state, squad_id, n_wounds)` :
```
répéter n_wounds fois (ou jusqu'à unité détruite) :
    eligibles = select_eligible_models(squad_id)   # applique la séquence 06.02
    si len(eligibles) == 1 → cible = eligibles[0]   # forcé → auto
    sinon → si controlling_player humain : prompt (pending_hazard_allocation) ; sinon (IA) :
             choix par défaut déterministe (ex. plus petit index)
    appliquer 1 wound à cible (update HP modèle) ; si 0 → destroy_model(reason="hazard"?)
```
`select_eligible_models` (séquence 06.02) :
1. non-CHARACTER **blessés** (HP_CUR < HP_MAX) → si ≥1, ce sont les seuls éligibles ;
2. sinon non-CHARACTER (tous) ;
3. sinon CHARACTER **blessés** ;
4. sinon CHARACTER (tous).
→ Réutiliser `_build_alloc_groups` / `_is_character_role` pour le découpage CHARACTER vs non.
→ **Cas 2 CHARACTERs** : couvert par les étapes 3-4 (choix entre les 2 si également éligibles).

⚠️ `destroy_model` attend une `reason` dans une liste validée — **ajouter `"hazard"`** (ou
réutiliser une reason existante adaptée) à la validation (`shared_utils.py` ~2558).

---

## 6. Frontend

- Nouveau popup hazard à l'activation (ou réutiliser le mécanisme `fleeWarningPopup`).
- Nouvel état type `HazardAllocation` (calqué sur `ManualAllocation` : `choices`,
  `wounds_remaining`, `controlling_player`).
- Handler `onAllocateHazardModel(modelId)` → action backend d'allocation hazard (clic figurine).
- Réutiliser le rendu de sélection de figurine du tir (blink/halo + clic).
- À la fin : reprise du move preview (le backend renvoie le pool Fall Back).
- Le log `[HAZARD]` existe déjà (type `hazard`, icône ☢️, hover règle 06.03).

---

## 7. Découpage d'implémentation proposé

1. **Backend — allocation 06.02 pure** : `select_eligible_models` + `allocate_mortal_wounds`
   (auto only, choix par défaut déterministe), via `destroy_model`. Corrige le bug agrégat.
   Testable seul (unité multi-fig, vérifier retrait fig correct).
2. **Backend — déplacement hazard → activation** : retirer des commit-paths ; brancher à
   l'activation + action `hazard_confirm` ; `desperate_escape_died` si détruite.
3. **Backend — état `pending_hazard_allocation`** + garde-fou actions + payload front.
4. **Frontend — popup** à l'activation (engaged + battle_shocked).
5. **Frontend — UI d'attribution** (clic figurine) branchée sur le pending.
6. **Reprise move preview** après attribution ; **fin d'activation** si détruite.
7. Validation manuelle (PvP test) : mono-fig, multi-fig avec choix, 2 CHARACTERs, unité tuée
   par le hazard.

---

## 8. Points de vigilance

- **Desperate Escape ⟺ battle-shocked** : pas de hazard pour une unité engagée saine (Ordered
  Retreat). Le moteur ne gère pas le Desperate Escape volontaire (non-shocked qui choisit de
  traverser les ennemis) — hors scope.
- **MW simultanées vs séquence** : 06.03 dit « rolls simultanés », mais 06.02 résout les MW
  **une par une** (le statut « blessé » d'une fig influence l'attribution de la suivante).
- **MONSTER/VEHICLE** : 3 MW par échec (déjà géré dans `roll_hazard_for_unit` via `keywordId`).
- **Cohésion** : `destroy_model` maintient `squad_cache.is_coherent` ; vérifier l'état post-retrait.
- **Mort en cours d'attribution** : si l'unité meurt avant d'avoir attribué toutes les MW,
  arrêter (06.02 : « until … that unit is destroyed »).
- **IA / gym** : pas de prompt — choix par défaut déterministe (ne pas bloquer l'entraînement).
  Le path RL `execute_squad_move` (action `squad_fall_back`) ne gère toujours pas le Desperate
  Escape ; décider si on l'aligne ici ou plus tard.
- **Mono-figurine** : `update_units_cache_hp` reste OK comme effet net, mais passer par
  `destroy_model` pour l'uniformité.
