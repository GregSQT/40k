# Frontend UI — Ligne de vue, couvert, tooltips et preview de tir

> Dernière mise à jour : mars 2026. Ce document décrit les systèmes UI du frontend : LoS hex-native, gestion du couvert, tooltips des barres HP, et preview de tir unifié (phase move + shoot).

---

## 1. LoS hex-native (ligne de vue)

### Implémentation

Le frontend utilise un système LoS **hex-native** dans `frontend/src/utils/gameHelpers.ts` :

- **`hasLineOfSight(from, to, wallHexes, coverRatio, losVisibilityMinRatio)`**  
  Calcule la visibilité entre deux positions (centre + 6 sommets par hex) et retourne :
  - `canSee` : cible visible ou non
  - `inCover` : cible en couvert (ratio entre les seuils)
  - `visibilityRatio` : ratio de rayons non bloqués (0–1)

- **Seuils** (depuis `config/game_config.json` → `game_rules`) :
  - `los_visibility_min_ratio` : en dessous → bloqué
  - `cover_ratio` : entre les deux → en couvert ; au-dessus → visibilité claire
  - Contrainte : `los_visibility_min_ratio < cover_ratio`

- **Échantillonnage** : 7 points par hex (centre + 6 sommets), tous les rayons testés contre les murs.

### Référence backend

Le backend utilise une logique équivalente dans `engine/phase_handlers/shooting_handlers.py` (`_get_los_visibility_state`, `valid_target_pool_build`). Les seuils sont alignés avec `game_config.json`.

---

## 2. Gestion du couvert

### Affichage des hex

- **Hex bleu vif** (`attackCells`) : visibilité claire (`visibility_ratio >= cover_ratio`)
- **Hex bleu clair** (`coverCells`) : cible en couvert (`los_visibility_min_ratio <= ratio < cover_ratio`)
- **Pas d’hex** : bloqué (`ratio < los_visibility_min_ratio`)

### Impact sur les dégâts

- **En couvert** : bonus de sauvegarde (+1 à l’armure, sauf invul)
- **`IGNORES_COVER`** : l’arme ignore le bonus de couvert
- Le tooltip des barres HP et `blinkingHPBar.ts` utilisent `inCover` pour le calcul des probabilités.

### Source des données

- **Phase shoot** : `blinking_units` du backend (inclut les règles « adjacent à un allié », etc.)
- **Phase move (preview)** : API `preview_shoot_from_position` (même logique backend)

---

## 3. Refactor des tooltips (barres HP)

### Module `blinkingHPBar.ts`

Le module `frontend/src/utils/blinkingHPBar.ts` centralise :

- **`createBlinkingHPBar(config)`** : barre HP animée avec preview de dégâts
- **`onTooltip`** : callback pour afficher/masquer le tooltip (probabilités, dégâts attendus)
- **Probabilités** : hit, wound, save, overall (via `getPreferredRangedWeaponAgainstTarget`)
- **Icône couvert** : affichée quand `inCover === true` (phase shoot)

### Intégration

- `UnitRenderer` appelle `createBlinkingHPBar` pour les cibles valides (blink)
- Le tooltip affiche les probabilités et le dégât attendu par attaque
- Pas de fallback : les valeurs viennent de la config ou lèvent une erreur explicite

---

## 4. Preview de tir en phase de mouvement

### Principe

En phase **move**, au clic sur une destination (avant validation), le frontend affiche le **même preview de tir** qu’en phase shoot : hex bleus, blink des barres HP, ghost des unités non ciblables.

### Source de vérité : backend

Les deux phases utilisent la **même logique backend** :

- **Phase shoot** : `blinking_units` renvoyé à l’activation de l’unité
- **Phase move** : action `preview_shoot_from_position` avec `unitId`, `destCol`, `destRow`
- **Phase advance (advancePreview)** : même API avec `advancePosition: true` (simulation advance → armes ASSAULT ou règle shoot_after_advance)

### API `preview_shoot_from_position`

- **Endpoint** : `POST /api/game/action`
- **Payload** : `{ action: "preview_shoot_from_position", unitId, destCol, destRow, advancePosition?: boolean }`
- **Réponse** : `{ success, result: { blinking_units, start_blinking } }`
- **Comportement** : copie du `game_state`, déplacement virtuel de l’unité, si `advancePosition` → unité ajoutée à `units_advanced` (simulation), puis `shooting_build_valid_target_pool` → aucune modification de l’état réel

### Flux frontend

1. Clic sur une destination → `movePreview` mis à jour
2. `useEffect` appelle l’API `preview_shoot_from_position` (phase move ou advance avec `advancePosition: true`)
3. Réception de `blinking_units` → `movePreviewBlinkingUnits`
4. `blinkingUnitsIds` et `blinkingAttackerId` alimentés par ces données
5. `BoardPvp` et `UnitRenderer` utilisent les mêmes props que en phase shoot

### Unification du code

- **`effectiveBlinkingUnits`** : phase move = `movePreviewBlinkingUnits` (API) ; phase shoot = `blinking_units` (activation) ; advance preview = `movePreviewBlinkingUnits` (API avec `advancePosition`)
- **Preview advance actif uniquement** si l’unité peut tirer après advance : arme ASSAULT ou règle shoot_after_advance (ex. Cunning Hunters)
- **`effectiveShootTargetsSet`** : même ensemble pour blink et ghost (unités non ciblables grisées)
- **`UnitRenderer`** : même logique pour les deux phases (`hasShootingPreviewContext` inclut `mode === "movePreview"`)

---

## Références

- **AI_TURN.md** : règles LoS, couvert, `los_visibility_min_ratio`, `cover_ratio`
- **game_config.json** : `game_rules.los_visibility_min_ratio`, `game_rules.cover_ratio`
- **gameHelpers.ts** : `hasLineOfSight`, `getHexLine`
- **blinkingHPBar.ts** : `createBlinkingHPBar`, tooltips, probabilités
- **shooting_handlers.py** : `preview_shoot_valid_targets_from_position`, `shooting_build_valid_target_pool`
