# REFACTORING - Système de Sélection d'Armes en Phase de Tir

## Date : [Date actuelle]
## Objectif : Corriger et améliorer le système de sélection d'armes en mode manuel

---

## 1. PROBLÈMES IDENTIFIÉS

### 1.1 Pas de tracking des armes utilisées
- **Problème** : Aucun mécanisme pour marquer les armes déjà complètement utilisées pendant l'activation
- **Impact** : Impossible de griser les armes dans le menu après utilisation
- **Localisation** : `engine/phase_handlers/shooting_handlers.py`, `frontend/src/components/BoardPvp.tsx`

### 1.2 Logique dupliquée
- **Problème** : Le filtrage PISTOL/non-PISTOL est répété 3 fois dans `shooting_target_selection_handler`
- **Impact** : Maintenance difficile, risque d'incohérence
- **Localisation** : `engine/phase_handlers/shooting_handlers.py` lignes 1374-1417, 1431-1481, 1497-1540

### 1.3 Filtrage des armes incomplet
- **Problème** : `_get_available_weapons_after_advance` ne vérifie que la règle ASSAULT
- **Manque** : Vérification de portée, LoS, et armes déjà utilisées
- **Localisation** : `engine/phase_handlers/shooting_handlers.py` ligne 26

### 1.4 Séparation des responsabilités
- **Problème** : Le frontend construit `weaponOptions` avec `canUse: true` pour toutes les armes
- **Impact** : Le backend devrait fournir les armes filtrées avec leur statut `can_use`
- **Localisation** : `frontend/src/components/BoardPvp.tsx` ligne 1564

### 1.5 SHOOT_LEFT ambigu
- **Problème** : `SHOOT_LEFT == 0` peut signifier "non initialisé" ou "épuisé"
- **Impact** : Difficile de distinguer les deux cas
- **Localisation** : `engine/phase_handlers/shooting_handlers.py` (multiple)

---

## 2. FLUX ATTENDU EN MODE MANUEL

### 2.1 Activation de l'unité
1. Utilisateur clique sur unité dans `shoot_activation_pool`
2. Action `activate_unit` → `shooting_unit_activation_start()`
3. Initialise `SHOOT_LEFT = weapon["NB"]` avec l'arme sélectionnée (index 0 par défaut)
4. Initialise `_used_weapon_indices = []` (NOUVEAU)
5. Si `autoSelectWeapon = false` et plusieurs armes → retourne `waiting_for_weapon_selection: true` avec `available_weapons` filtrées

### 2.2 Sélection d'arme (quand le joueur clique sur l'icône du menu d'armes)
1. Icône visible si `autoSelectWeapon = false` et plusieurs armes
2. Clic ouvre le menu de sélection d'arme
3. Armes filtrées par le backend :
   - Seules les armes avec au moins une cible en LoS et à portée sont sélectionnables
   - Les armes déjà utilisées sont grisées (NOUVEAU)
   - Les autres sont grisées et non sélectionnables
4. Action `select_weapon` :
   - Met à jour `selectedRngWeaponIndex` et `SHOOT_LEFT = weapon["NB"]`
   - Met à jour le shooting preview (et le HP blink)
   - Construit `valid_targets` selon la portée de l'arme sélectionnée
5. Appelle `_shooting_unit_execution_loop()`

### 2.3 Boucle d'exécution (`_shooting_unit_execution_loop`)
- Si `SHOOT_LEFT <= 0` :
  - Vérifie si l'arme actuelle est PISTOL
  - Cherche d'autres armes de la même catégorie (PISTOL ou non-PISTOL) sélectionnables (non grisées, avec cibles valides)
  - Si trouvées et cibles disponibles → retourne `weapon_selection_required: true`
  - Sinon → termine l'activation
- Si `SHOOT_LEFT > 0` :
  - Si la cible est morte : Construit `valid_targets` (NOUVEAU)
  - Si pas de cibles → termine l'activation
  - Si cibles disponibles → retourne `waiting_for_player: true` avec `validTargets` et `blinking_units`

### 2.4 Clic sur une cible
1. Action `left_click` avec `targetId` et `clickTarget: "target"`
2. `shooting_click_handler()` → `shooting_target_selection_handler()`
3. Dès le premier tir, marquer l'arme comme utilisée si `SHOOT_LEFT` devient 0 (NOUVEAU)

### 2.5 Gestion de la sélection de cible (`shooting_target_selection_handler`)
1. Vérifie `SHOOT_LEFT` :
   - Si `SHOOT_LEFT <= 0` → définit `current_weapon_is_pistol`
2. Construit `valid_targets`
3. Si `target_id` est valide :
   - Mode auto (`autoSelectWeapon = true`) :
     - Filtre les armes selon la catégorie (PISTOL ou non-PISTOL)
     - Exclut les armes déjà utilisées (NOUVEAU)
     - Sélectionne automatiquement la meilleure arme
     - Met à jour `SHOOT_LEFT` si nécessaire
   - Mode manuel (`autoSelectWeapon = false`) :
     - Si `SHOOT_LEFT == 0` et unité déjà activée :
       - Filtre les armes de la même catégorie
       - Exclut les armes déjà utilisées (NOUVEAU)
       - Sélectionne automatiquement la meilleure arme (même en mode manuel)
       - Met à jour `SHOOT_LEFT`
     - Sinon → utilise l'arme déjà sélectionnée
4. Exécute le tir : `shooting_attack_controller()`
5. Décrémente `SHOOT_LEFT -= 1`
6. Si `SHOOT_LEFT == 0` après décrémentation → ajoute l'arme à `_used_weapon_indices` (NOUVEAU)
7. Appelle `_shooting_unit_execution_loop()` pour continuer

### 2.6 Après le tir
- `_shooting_unit_execution_loop()` vérifie `SHOOT_LEFT`
- Si `SHOOT_LEFT > 0` → retourne `waiting_for_player` pour permettre un autre tir
- Si `SHOOT_LEFT == 0` → vérifie s'il y a d'autres armes de la même catégorie (non utilisées, avec cibles valides)

---

## 3. CHANGEMENTS À IMPLÉMENTER

### 3.1 Backend - Tracking des armes utilisées

#### Fichier : `engine/phase_handlers/shooting_handlers.py`

**3.1.1 Dans `shooting_unit_activation_start` (ligne ~359)**
- Ajouter : `unit["_used_weapon_indices"] = []` pour initialiser la liste des armes utilisées

**3.1.2 Créer fonction centralisée de filtrage**
- Nouvelle fonction : `_get_available_weapons_for_selection(unit, game_state, current_weapon_is_pistol, exclude_used=True)`
- Vérifie :
  - Portée : au moins une cible à portée de l'arme
  - LoS : au moins une cible visible
  - Règle ASSAULT : si unité a avancé
  - Règle PISTOL : catégorie (PISTOL ou non-PISTOL)
  - Armes déjà utilisées : si `exclude_used=True`, exclut les indices dans `_used_weapon_indices`
- Retourne : Liste de dicts avec `index`, `weapon`, `can_use`, `reason`

**3.1.3 Dans `shooting_target_selection_handler` (ligne ~1325)**
- Après `unit["SHOOT_LEFT"] -= 1` (ligne ~1540)
- Si `SHOOT_LEFT == 0` → ajouter `current_weapon_index` à `unit["_used_weapon_indices"]`
- Remplacer les 3 blocs de filtrage dupliqués par des appels à `_get_available_weapons_for_selection`

**3.1.4 Dans `_get_available_weapons_after_advance` (ligne ~26)**
- Étendre pour vérifier portée et LoS
- Utiliser `_get_available_weapons_for_selection` si possible

### 3.2 Backend - Retourner les armes filtrées au frontend

#### Fichier : `engine/phase_handlers/shooting_handlers.py`

**3.2.1 Dans `shooting_unit_activation_start` (ligne ~405)**
- Quand `waiting_for_weapon_selection: true`, utiliser `_get_available_weapons_for_selection` pour construire `available_weapons`
- Inclure le statut `can_use` basé sur portée/LoS/usage

**3.2.2 Dans `_shooting_unit_execution_loop` (ligne ~989)**
- Quand `weapon_selection_required: true`, inclure `available_weapons` filtrées dans la réponse

### 3.3 Frontend - Utiliser les armes filtrées du backend

#### Fichier : `frontend/src/components/BoardPvp.tsx`

**3.3.1 Dans la construction de `weaponOptions` (ligne ~1557)**
- Utiliser `available_weapons` du backend si disponible
- Sinon, calculer `can_use` côté frontend en vérifiant portée/LoS
- Griser les armes avec `can_use: false` ou déjà utilisées

**3.3.2 Dans `WeaponDropdown`**
- Afficher les armes grisées selon `can_use` et `reason`

### 3.4 Backend - Reconstruction de valid_targets après mort de cible

#### Fichier : `engine/phase_handlers/shooting_handlers.py`

**3.4.1 Dans `_shooting_unit_execution_loop` (ligne ~1011)**
- Après vérification de `valid_targets`, si vide et qu'une cible est morte :
- Reconstruire `valid_targets` pour toutes les armes disponibles
- Vérifier si d'autres armes ont des cibles valides

---

## 4. ORDRE D'IMPLÉMENTATION RECOMMANDÉ

1. **Étape 1** : Ajouter `_used_weapon_indices` dans `shooting_unit_activation_start`
2. **Étape 2** : Créer `_get_available_weapons_for_selection` avec filtrage complet
3. **Étape 3** : Marquer les armes comme utilisées après `SHOOT_LEFT -= 1` quand `SHOOT_LEFT == 0`
4. **Étape 4** : Remplacer les 3 blocs dupliqués par des appels à la fonction centralisée
5. **Étape 5** : Modifier `_get_available_weapons_after_advance` pour utiliser la nouvelle fonction
6. **Étape 6** : Modifier le frontend pour utiliser les armes filtrées du backend
7. **Étape 7** : Ajouter la reconstruction de `valid_targets` après mort de cible

---

## 5. FICHIERS À MODIFIER

1. `/home/greg/projects/40k/engine/phase_handlers/shooting_handlers.py`
   - `shooting_unit_activation_start` (ligne ~359)
   - `_get_available_weapons_after_advance` (ligne ~26)
   - Nouvelle fonction `_get_available_weapons_for_selection`
   - `shooting_target_selection_handler` (ligne ~1325)
   - `_shooting_unit_execution_loop` (ligne ~952)

2. `/home/greg/projects/40k/frontend/src/components/BoardPvp.tsx`
   - Construction de `weaponOptions` (ligne ~1557)
   - Utilisation de `available_weapons` du backend

3. `/home/greg/projects/40k/frontend/src/components/WeaponDropdown.tsx`
   - Affichage des armes grisées selon `can_use`

---

## 6. TESTS À EFFECTUER

1. ✅ Après avoir tiré avec testor (NB: 3), pouvoir sélectionner bolt_rifle
2. ✅ Après avoir tiré avec bolt_rifle (NB: 2), pouvoir sélectionner testor
3. ✅ bolt_pistol (PISTOL) ne peut pas être sélectionné avec les armes non-PISTOL
4. ✅ Les armes sans cibles valides sont grisées dans le menu
5. ✅ Les armes déjà utilisées sont grisées dans le menu
6. ✅ Après avoir utilisé toutes les armes d'une catégorie, l'activation se termine
7. ✅ Si une cible meurt, les `valid_targets` sont reconstruits pour toutes les armes