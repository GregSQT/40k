"""Tests unitaires — mécanique de morale/battleshock.

État actuel : la mécanique morale/battleshock N'EST PAS implémentée.
LD est uniquement un champ de stat sur les unités ; aucune phase
battleshock ni résolution de tests de leadership n'existe dans le moteur.

Ces tests documentent explicitement l'absence de cette mécanique
et vérifieront une régression si elle est ajoutée sans mise à jour des tests.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


class TestMoraleNotImplemented:

    def test_morale_not_implemented(self) -> None:
        """morale_absent : aucun handler battleshock/morale n'existe dans phase_handlers/."""
        import engine.phase_handlers as _ph
        handlers_dir = Path(_ph.__file__).parent
        morale_files = [
            f for f in os.listdir(handlers_dir)
            if any(kw in f.lower() for kw in ("morale", "battleshock", "leadership"))
        ]
        assert morale_files == [], (
            f"Des fichiers de morale ont été trouvés : {morale_files}. "
            "Mettre à jour test_morale.py pour couvrir la nouvelle mécanique."
        )

    def test_no_battleshock_phase_in_engine(self) -> None:
        """morale_no_phase : aucune phase 'battleshock' ou 'morale' dans le moteur."""
        from engine.w40k_core import W40KEngine
        # Les phases légales connues du moteur ne contiennent pas de phase morale
        known_phases = {
            "deployment", "command", "move", "shoot", "charge", "fight"
        }
        # Vérification que battleshock n'est pas référencé comme phase dans le code
        import inspect
        source = inspect.getsource(W40KEngine)
        # Cherche une affectation de phase à "battleshock" ou "morale"
        for forbidden in ("battleshock", "morale_phase"):
            assert f'"{forbidden}"' not in source and f"'{forbidden}'" not in source, (
                f"Phase '{forbidden}' détectée dans W40KEngine. "
                "Mettre à jour test_morale.py."
            )

    def test_ld_field_exists_on_units_as_stat_only(self) -> None:
        """morale_ld_stat : LD est bien un champ de stat sans logique de résolution."""
        from engine.game_state import GameStateManager
        config = {"board": {"default": {"inches_to_subhex": 1}}}
        sm = GameStateManager(config)
        unit_cfg = {
            "id": 99, "player": 1, "col": 0, "row": 0,
            "unitType": "T", "DISPLAY_NAME": "TestUnit",
            "HP_CUR": 3, "HP_MAX": 3, "MOVE": 6, "T": 4,
            "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
            "RNG_WEAPONS": [], "CC_WEAPONS": [],
            "UNIT_RULES": [], "UNIT_KEYWORDS": [],
            "LD": 7, "OC": 1, "VALUE": 100, "ICON": "t",
            "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
            "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        }
        unit = sm.create_unit(unit_cfg)
        # LD est bien stocké comme valeur entière, pas consommé par une logique
        assert unit["LD"] == 7

    def test_no_morale_roll_function_in_combat_utils(self) -> None:
        """morale_no_fn : combat_utils n'expose pas de fonction de résolution de morale."""
        import engine.combat_utils as cu
        morale_fns = [
            name for name in dir(cu)
            if any(kw in name.lower() for kw in ("morale", "battleshock", "leadership_test"))
        ]
        assert morale_fns == [], (
            f"Fonctions de morale trouvées : {morale_fns}. "
            "Mettre à jour test_morale.py."
        )

    def test_command_phase_does_not_run_morale(self) -> None:
        """morale_cmd : command_phase_start() ne déclenche pas de résolution de morale."""
        from engine.phase_handlers import command_handlers
        from engine.phase_handlers.shared_utils import build_units_cache
        import inspect
        source = inspect.getsource(command_handlers.command_phase_start)
        for forbidden in ("morale", "battleshock", "ld_test", "leadership_test"):
            assert forbidden not in source.lower(), (
                f"'{forbidden}' détecté dans command_phase_start. "
                "Mettre à jour test_morale.py."
            )
