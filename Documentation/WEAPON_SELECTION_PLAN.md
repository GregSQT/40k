# Plan d'implémentation : Système de sélection d'arme

## Vue d'ensemble

Implémenter un système de sélection d'arme flexible permettant :
- **Mode automatique** : Sélection automatique de la meilleure arme (par défaut)
- **Mode manuel** : Le joueur choisit son arme via une interface
- **Filtrage ASSAULT** : Après advance, seules les armes ASSAULT sont disponibles
- **Option de paramétrage** : Toggle dans le menu Settings

---

## Phase 1 : Menu Settings (Frontend)

### Fichier : `frontend/src/components/SettingsMenu.tsx`

**Modification nécessaire :**

Ajouter une nouvelle option dans le tableau `settings` :

```typescript
{
  id: 'autoSelectWeapon',
  label: 'Auto-select weapon',
  description: 'Automatically select the best weapon for each target',
  type: 'boolean',
  defaultValue: true,
  category: 'gameplay'
}
```

**State management :**
- Stocker dans `localStorage` sous la clé `"gameSettings.autoSelectWeapon"`
- Accessible via `useGameSettings()` hook ou context

---

## Phase 2 : Types TypeScript (Frontend)

### Fichier : `frontend/src/types/game.ts`

**Ajouter nouveaux types :**

```typescript
export interface WeaponOption {
  index: number;
  weapon: Weapon;
  canUse: boolean;          // False si pas ASSAULT après advance
  reason?: string;           // "No ASSAULT rule" si disabled
}

export interface WeaponSelectionState {
  isActive: boolean;
  unitId: UnitId;
  weapons: WeaponOption[];
  hasAdvanced: boolean;
}
```

**Modifier GameState :**

```typescript
export interface GameState {
  // ... existing fields
  weaponSelection?: WeaponSelectionState;
}
```

---

## Phase 3 : Backend - Filtrage et gestion (Python)

### Fichier : `engine/phase_handlers/shooting_handlers.py`

**MODIFICATION 1 : Nouvelle fonction `_get_available_weapons_after_advance()`**

```python
def _get_available_weapons_after_advance(
    unit: Dict[str, Any], 
    has_advanced: bool
) -> List[Dict[str, Any]]:
    """
    Get list of available weapons, filtered by ASSAULT rule if unit advanced.
    
    Returns:
        List of dicts with keys: index, weapon, can_use, reason
    """
    available_weapons = []
    rng_weapons = unit.get("RNG_WEAPONS", [])
    
    for idx, weapon in enumerate(rng_weapons):
        can_use = True
        reason = None
        
        if has_advanced:
            # Check ASSAULT rule
            if not _weapon_has_assault_rule(weapon):
                can_use = False
                reason = "No ASSAULT rule (cannot shoot after advancing)"
        
        available_weapons.append({
            "index": idx,
            "weapon": weapon,
            "can_use": can_use,
            "reason": reason
        })
    
    return available_weapons
```

**MODIFICATION 2 : Adapter `_handle_advance_action()`**

Dans la section où on vérifie `can_shoot_after_advance` :

```python
# Check if unit can shoot after advance (ASSAULT weapon rule)
from engine.utils.weapon_helpers import get_selected_ranged_weapon
selected_weapon = get_selected_ranged_weapon(unit)

# Get auto-select setting from config
auto_select = config.get("game_settings", {}).get("autoSelectWeapon", True)

if auto_select:
    # AUTO MODE: Select best ASSAULT weapon automatically
    can_shoot_after_advance = _weapon_has_assault_rule(selected_weapon)
    
    if can_shoot_after_advance:
        # Continue to shooting phase with ASSAULT weapon
        return _shooting_unit_execution_loop(game_state, unit_id, config)
    else:
        # No ASSAULT weapon - end activation
        result = _shooting_activation_end(game_state, unit, "ACTION", 1, "PASS", "SHOOTING")
        return result
else:
    # MANUAL MODE: Return weapon selection list
    available_weapons = _get_available_weapons_after_advance(unit, has_advanced=True)
    
    # Filter to only weapons that can be used
    usable_weapons = [w for w in available_weapons if w["can_use"]]
    
    if not usable_weapons:
        # No usable weapons - end activation
        result = _shooting_activation_end(game_state, unit, "ACTION", 1, "PASS", "SHOOTING")
        return result
    
    # Return weapon selection prompt
    return True, {
        "waiting_for_weapon_selection": True,
        "unitId": unit_id,
        "available_weapons": available_weapons,
        "has_advanced": True
    }
```

**MODIFICATION 3 : Nouvelle action `select_weapon` dans `execute_action()`**

```python
elif action_type == "select_weapon":
    # Handle weapon selection action
    weapon_index = action.get("weaponIndex")
    if weapon_index is None:
        return False, {"error": "missing_weapon_index"}
    
    # Validate weapon index
    rng_weapons = unit.get("RNG_WEAPONS", [])
    if weapon_index < 0 or weapon_index >= len(rng_weapons):
        return False, {"error": "invalid_weapon_index", "weaponIndex": weapon_index}
    
    # Set selected weapon
    unit["selectedRngWeaponIndex"] = weapon_index
    
    # Continue to shooting execution loop
    return _shooting_unit_execution_loop(game_state, unit_id, config)
```

**MODIFICATION 4 : Adapter `shooting_unit_activation_start()`**

Ajouter support pour mode manuel :

```python
def shooting_unit_activation_start(game_state: Dict[str, Any], unit_id: str) -> Dict[str, Any]:
    # ... existing code ...
    
    # Check if we need weapon selection (manual mode)
    auto_select = game_state.get("config", {}).get("game_settings", {}).get("autoSelectWeapon", True)
    
    if not auto_select:
        # Manual mode - check if unit has multiple weapons
        rng_weapons = unit.get("RNG_WEAPONS", [])
        if len(rng_weapons) > 1:
            # Return weapon selection prompt
            available_weapons = _get_available_weapons_after_advance(unit, has_advanced=False)
            return {
                "success": True,
                "waiting_for_weapon_selection": True,
                "unitId": unit_id,
                "available_weapons": available_weapons
            }
    
    # Auto mode or single weapon - continue as before
    return {
        "success": True,
        "unitId": unit_id,
        "shootLeft": unit["SHOOT_LEFT"],
        "position": {"col": unit["col"], "row": unit["row"]}
    }
```

---

## Phase 4 : Frontend - Hook useEngineAPI (Frontend)

### Fichier : `frontend/src/hooks/useEngineAPI.ts`

**MODIFICATION 1 : Ajouter state pour weapon selection**

```typescript
const [weaponSelection, setWeaponSelection] = useState<WeaponSelectionState | null>(null);
```

**MODIFICATION 2 : Handler pour sélection d'arme**

```typescript
const handleWeaponSelect = useCallback(async (weaponIndex: number) => {
  if (!weaponSelection) return;
  
  try {
    const response = await fetch('/api/game/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action: 'select_weapon',
        unitId: weaponSelection.unitId,
        weaponIndex: weaponIndex
      })
    });
    
    const result = await response.json();
    
    // Clear weapon selection
    setWeaponSelection(null);
    
    // Process result (targets display, etc.)
    handleActionResult(result);
    
  } catch (error) {
    console.error('Weapon selection failed:', error);
  }
}, [weaponSelection]);
```

**MODIFICATION 3 : Détecter weapon selection dans handleActionResult**

```typescript
// Dans handleActionResult(), ajouter :
if (result.waiting_for_weapon_selection) {
  setWeaponSelection({
    isActive: true,
    unitId: result.unitId,
    weapons: result.available_weapons,
    hasAdvanced: result.has_advanced || false
  });
  return;
}
```

**Exporter :**

```typescript
return {
  // ... existing exports
  weaponSelection,
  handleWeaponSelect
};
```

---

## Phase 5 : Frontend - UI Components (Frontend)

### 5.1 - Icône d'arme sur l'unité active

**Fichier : `frontend/src/components/UnitRenderer.tsx`**

Ajouter une icône pistolet en haut à droite de l'unité quand elle est activée pour tirer :

```typescript
// Dans renderActiveShootingIndicator() ou nouvelle fonction :
private renderWeaponIcon(): PIXI.Container | null {
  const { unit, isActiveShooter, onWeaponIconClick } = this.props;
  
  if (!isActiveShooter) return null;
  
  // Check if unit has multiple weapons (manual mode only)
  const hasMultipleWeapons = unit.RNG_WEAPONS && unit.RNG_WEAPONS.length > 1;
  if (!hasMultipleWeapons) return null;
  
  const iconContainer = new PIXI.Container();
  
  // Position en haut à droite de l'unité
  const iconSize = 24;
  iconContainer.position.set(
    this.hexRadius * 0.7,  // Top right
    -this.hexRadius * 0.7
  );
  
  // Background circle
  const bg = new PIXI.Graphics();
  bg.beginFill(0x333333, 0.9);
  bg.drawCircle(0, 0, iconSize / 2);
  bg.endFill();
  iconContainer.addChild(bg);
  
  // Pistol icon (simple graphic or sprite)
  const icon = new PIXI.Text('🔫', {
    fontSize: 18,
    align: 'center'
  });
  icon.anchor.set(0.5);
  iconContainer.addChild(icon);
  
  // Make interactive
  iconContainer.interactive = true;
  iconContainer.cursor = 'pointer';
  iconContainer.on('pointerdown', (event) => {
    event.stopPropagation();
    onWeaponIconClick?.(unit.id);
  });
  
  // Hover effect
  iconContainer.on('pointerover', () => {
    bg.clear();
    bg.beginFill(0xFFD700, 0.9);
    bg.drawCircle(0, 0, iconSize / 2);
    bg.endFill();
  });
  
  iconContainer.on('pointerout', () => {
    bg.clear();
    bg.beginFill(0x333333, 0.9);
    bg.drawCircle(0, 0, iconSize / 2);
    bg.endFill();
  });
  
  return iconContainer;
}
```

### 5.2 - Menu déroulant compact

**Nouveau fichier : `frontend/src/components/WeaponDropdown.tsx`**

Menu compact qui apparaît près de l'icône :

```typescript
import React, { useRef, useEffect } from 'react';
import type { WeaponOption } from '../types/game';

interface WeaponDropdownProps {
  weapons: WeaponOption[];
  position: { x: number; y: number };  // Position de l'icône
  onSelectWeapon: (index: number) => void;
  onClose: () => void;
  hasAdvanced?: boolean;
}

export const WeaponDropdown: React.FC<WeaponDropdownProps> = ({
  weapons,
  position,
  onSelectWeapon,
  onClose,
  hasAdvanced
}) => {
  const dropdownRef = useRef<HTMLDivElement>(null);
  
  // Close on click outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        onClose();
      }
    };
    
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [onClose]);
  
  return (
    <div 
      ref={dropdownRef}
      className="weapon-dropdown"
      style={{
        position: 'absolute',
        left: `${position.x}px`,
        top: `${position.y}px`,
      }}
    >
      {hasAdvanced && (
        <div className="dropdown-warning">⚠️ Only ASSAULT</div>
      )}
      
      <div className="weapon-list">
        {weapons.map((weaponOption) => {
          const weapon = weaponOption.weapon;
          const isDisabled = !weaponOption.canUse;
          
          return (
            <button
              key={weaponOption.index}
              className={`weapon-item ${isDisabled ? 'disabled' : ''}`}
              onClick={() => !isDisabled && onSelectWeapon(weaponOption.index)}
              disabled={isDisabled}
              title={weaponOption.reason}
            >
              <div className="weapon-name">
                {weapon.display_name}
                {weapon.WEAPON_RULES?.includes('ASSAULT') && (
                  <span className="assault">⚡</span>
                )}
              </div>
              <div className="weapon-stats-compact">
                {weapon.RNG && `${weapon.RNG}"`} • {weapon.NB}A • {weapon.DMG}D
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
};
```

**CSS associé (compact et près de l'icône) :**

```css
.weapon-dropdown {
  background: rgba(20, 20, 20, 0.98);
  border: 2px solid #ffd700;
  border-radius: 6px;
  padding: 8px;
  min-width: 200px;
  max-width: 250px;
  z-index: 1000;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);
}

.dropdown-warning {
  color: #ff6b6b;
  font-size: 0.85em;
  padding: 4px 8px;
  margin-bottom: 6px;
  background: rgba(255, 107, 107, 0.1);
  border-radius: 3px;
  text-align: center;
}

.weapon-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.weapon-item {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid #444;
  border-radius: 4px;
  padding: 8px 10px;
  cursor: pointer;
  text-align: left;
  transition: all 0.15s;
}

.weapon-item:hover:not(.disabled) {
  background: rgba(255, 215, 0, 0.15);
  border-color: #ffd700;
}

.weapon-item.disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.weapon-name {
  font-weight: 600;
  color: #fff;
  font-size: 0.9em;
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 3px;
}

.assault {
  color: #4caf50;
  font-size: 1.1em;
}

.weapon-stats-compact {
  color: #aaa;
  font-size: 0.75em;
}
```

---

## Phase 6 : Frontend - Intégration dans BoardPvp (Frontend)

### Fichier : `frontend/src/components/BoardPvp.tsx`

**MODIFICATION : Importer et afficher WeaponSelectionMenu**

```typescript
import { WeaponSelectionMenu } from './WeaponSelectionMenu';

// Dans le component :
const { 
  // ... existing
  weaponSelection,
  handleWeaponSelect
} = useEngineAPI();

// Dans le render :
return (
  <>
    {/* Existing board rendering */}
    
    {/* Weapon Selection Menu */}
    {weaponSelection && weaponSelection.isActive && (
      <WeaponSelectionMenu
        weaponSelection={weaponSelection}
        onSelectWeapon={handleWeaponSelect}
        onCancel={() => {
          // Handle cancel - maybe end unit activation or go back
          setWeaponSelection(null);
        }}
      />
    )}
  </>
);
```

---

## Phase 7 : Configuration et Settings (Backend)

### Fichier : `config/game_config.json` (ou similaire)

**Ajouter paramètre par défaut :**

```json
{
  "game_settings": {
    "autoSelectWeapon": true
  }
}
```

### Fichier : `services/api_server.py`

**Passer les settings du frontend au backend :**

Lors de l'action, récupérer les settings depuis le client :

```python
@app.route('/api/game/action', methods=['POST'])
def handle_action():
    data = request.json
    
    # Get game settings from request or use defaults
    game_settings = data.get('gameSettings', {
        'autoSelectWeapon': True
    })
    
    # Pass to config
    config = {
        # ... existing config
        'game_settings': game_settings
    }
    
    # Execute action with config
    result = game_engine.execute_action(action, config)
    # ...
```

---

## Résumé des fichiers à modifier

### Backend (Python)
1. ✅ `engine/phase_handlers/shooting_handlers.py` - 4 modifications
2. ✅ `services/api_server.py` - Passer game_settings
3. ✅ `config/game_config.json` - Paramètre par défaut

### Frontend (TypeScript/React)
4. ✅ `frontend/src/types/game.ts` - Nouveaux types
5. ✅ `frontend/src/components/SettingsMenu.tsx` - Option toggle
6. ✅ `frontend/src/hooks/useEngineAPI.ts` - State + handlers
7. ✅ `frontend/src/components/WeaponSelectionMenu.tsx` - **NOUVEAU composant**
8. ✅ `frontend/src/components/BoardPvp.tsx` - Intégration menu

### Optionnel
9. CSS pour WeaponSelectionMenu (peut être inline ou fichier séparé)

---

## Ordre d'implémentation recommandé

1. **Backend first** : Implémenter la logique de filtrage et les actions
2. **Types** : Ajouter les types TypeScript
3. **Settings** : Ajouter l'option dans le menu
4. **UI Component** : Créer WeaponSelectionMenu
5. **Hook** : Adapter useEngineAPI
6. **Integration** : Connecter dans BoardPvp
7. **Test** : Tester mode auto ET mode manuel

---

## Tests à effectuer

### Mode Auto (autoSelectWeapon = true)
- ✅ Unité avec 1 arme → sélection automatique
- ✅ Unité avec plusieurs armes → sélectionne la meilleure automatiquement
- ✅ Après advance sans ASSAULT → activation se termine
- ✅ Après advance avec ASSAULT → peut tirer

### Mode Manuel (autoSelectWeapon = false)
- ✅ Unité avec 1 arme → pas de menu, sélection auto
- ✅ Unité avec plusieurs armes → affiche menu
- ✅ Après advance → seules armes ASSAULT actives dans menu
- ✅ Clic sur arme → valide et continue vers tir
- ✅ Cancel → termine activation ou retour en arrière

---

## Estimation finale

- Backend : 3-4h
- Frontend (Types + Settings) : 1h
- Frontend (UI Component) : 2-3h
- Frontend (Integration) : 1-2h
- Tests + Debug : 2-3h

**Total : 9-13h**
