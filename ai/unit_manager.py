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
            self.remove_unit(unit["id"])
            return True
        return False