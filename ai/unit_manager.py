# ai/unit_manager.py
"""
Python equivalent of useGameState.ts unit management functions
Focused on death management to match PvP mode behavior exactly
"""

from typing import List, Dict, Any, Optional

class UnitManager:
    """
    Python equivalent of useGameState.ts for centralized unit management.
    Mirrors PvP mode behavior exactly, starting with death management.
    """
    
    def __init__(self, initial_units: List[Dict[str, Any]]):
        """Initialize with units list like PvP mode."""
        self.units = initial_units.copy()
        self.ai_units = [u for u in self.units if u["player"] == 1]
        self.enemy_units = [u for u in self.units if u["player"] == 0]
    
    def remove_unit(self, unit_id: int) -> None:
        """
        EXACT equivalent of PvP removeUnit function:
        units: prev.units.filter(unit => unit.id !== unitId)
        """
        # Apply EXACT PvP logic: filter out the dead unit
        self.units = [u for u in self.units if u["id"] != unit_id]
        
        # Update derived lists to stay in sync
        self.ai_units = [u for u in self.units if u["player"] == 1]
        self.enemy_units = [u for u in self.units if u["player"] == 0]
    
    def update_unit(self, unit_id: int, updates: Dict[str, Any]) -> None:
        """
        EXACT equivalent of PvP updateUnit function:
        units: prev.units.map(unit => unit.id === unitId ? { ...unit, ...updates } : unit)
        """
        for unit in self.units:
            if unit["id"] == unit_id:
                unit.update(updates)
                break
        
        # Update derived lists to stay in sync
        self.ai_units = [u for u in self.units if u["player"] == 1]
        self.enemy_units = [u for u in self.units if u["player"] == 0]
    
    def find_unit(self, unit_id: int) -> Optional[Dict[str, Any]]:
        """
        EXACT equivalent of PvP findUnit function:
        return units.find(u => u.id === unitId);
        """
        return next((u for u in self.units if u["id"] == unit_id), None)
    
    def get_alive_units(self) -> List[Dict[str, Any]]:
        """Get all alive units (units with cur_hp > 0)."""
        return [u for u in self.units if u.get("cur_hp", 0) > 0]
    
    def get_alive_ai_units(self) -> List[Dict[str, Any]]:
        """Get alive AI units only."""
        return [u for u in self.ai_units if u.get("cur_hp", 0) > 0]
    
    def get_alive_enemy_units(self) -> List[Dict[str, Any]]:
        """Get alive enemy units only."""
        return [u for u in self.enemy_units if u.get("cur_hp", 0) > 0]
    
    def handle_unit_death(self, unit: Dict[str, Any]) -> bool:
        """
        Handle unit death exactly like PvP mode:
        if (newHP <= 0) { actions.removeUnit(targetId); }
        
        Returns True if unit died and was removed.
        """
        if unit.get("cur_hp", 0) <= 0:
            # Mark as dead immediately
            unit["alive"] = False
            unit["cur_hp"] = 0
            self.remove_unit(unit["id"])
            return True
        return False
    
    def apply_damage_and_check_death(self, unit: Dict[str, Any], damage: int) -> bool:
        """
        Apply damage and handle death atomically like PvP mode.
        Returns True if unit died and was removed.
        """
        old_hp = unit.get("cur_hp", 0)
        new_hp = max(0, old_hp - damage)
        unit["cur_hp"] = new_hp
        
        if new_hp <= 0:
            # Mark as dead immediately
            unit["alive"] = False
            unit["cur_hp"] = 0
            self.remove_unit(unit["id"])
            return True
        return False
    
    def apply_shooting_damage(self, shooter: Dict[str, Any], target: Dict[str, Any], shooting_result: Dict[str, Any]) -> bool:
        """
        Apply shooting damage atomically like PvP mode.
        Returns True if target died and was removed.
        """
        total_damage = shooting_result["totalDamage"]
        return self.apply_damage_and_check_death(target, total_damage)
    
    def apply_combat_damage(self, attacker: Dict[str, Any], target: Dict[str, Any], combat_result: Dict[str, Any]) -> bool:
        """
        Apply combat damage atomically like PvP mode.
        Returns True if target died and was removed.
        """
        total_damage = combat_result["totalDamage"]
        return self.apply_damage_and_check_death(target, total_damage)
    
    def apply_direct_damage(self, attacker: Dict[str, Any], target: Dict[str, Any]) -> bool:
        """
        Apply direct damage (like cc_dmg) atomically like PvP mode.
        Returns True if target died and was removed.
        """
        damage = attacker["cc_dmg"]
        return self.apply_damage_and_check_death(target, damage)