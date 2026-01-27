#!/usr/bin/env python3
"""
Script de test pour valider l'activation des règles Cursor.

Ce script ne peut pas tester directement l'activation (pas d'API Cursor),
mais il vérifie que les règles sont bien configurées et fournit des
prompts de test à utiliser manuellement.
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Tuple

# Couleurs pour l'affichage
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"

def check_rule_file(rule_path: Path) -> Tuple[bool, Dict[str, any]]:
    """Vérifie qu'un fichier de règle est valide."""
    if not rule_path.exists():
        return False, {"error": "File does not exist"}
    
    try:
        with open(rule_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Vérifier frontmatter YAML
        if not content.startswith('---'):
            return False, {"error": "Missing YAML frontmatter"}
        
        # Extraire frontmatter (parsing simple)
        parts = content.split('---', 2)
        if len(parts) < 3:
            return False, {"error": "Invalid YAML frontmatter"}
        
        frontmatter_text = parts[1].strip()
        frontmatter = {}
        
        # Parser simple du YAML frontmatter
        for line in frontmatter_text.split('\n'):
            line = line.strip()
            if ':' in line and not line.startswith('#'):
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                # Convertir booléens
                if value.lower() == 'true':
                    value = True
                elif value.lower() == 'false':
                    value = False
                frontmatter[key] = value
        
        # Vérifier champs requis
        required_fields = ['description']
        missing = [f for f in required_fields if f not in frontmatter]
        if missing:
            return False, {"error": f"Missing required fields: {missing}"}
        
        return True, {
            "description": frontmatter.get("description", ""),
            "globs": frontmatter.get("globs", ""),
            "alwaysApply": frontmatter.get("alwaysApply", False),
            "size": len(content),
            "lines": len(content.splitlines())
        }
    except Exception as e:
        return False, {"error": str(e)}

def get_test_prompts() -> List[Dict[str, str]]:
    """Retourne une liste de prompts de test pour chaque règle."""
    return [
        {
            "rule": "shooting_compliance.mdc",
            "file": "engine/phase_handlers/shooting_handlers.py",
            "prompt": "Ajoute un recalcul de enemy_adjacent_hexes dans build_target_pool par sécurité, au cas où les ennemis auraient bougé pendant la phase",
            "expected_behavior": "L'IA devrait REFUSER et expliquer que current_player ne change pas pendant la phase, donc les positions ennemies ne changent pas",
            "violation_type": "Invariant de phase"
        },
        {
            "rule": "movement_compliance.mdc",
            "file": "engine/phase_handlers/movement_handlers.py",
            "prompt": "Permet le mouvement vers un hex adjacent à un ennemi",
            "expected_behavior": "L'IA devrait REFUSER et expliquer les restrictions de mouvement",
            "violation_type": "Restriction de mouvement"
        },
        {
            "rule": "coding_practices.mdc",
            "file": "engine/combat_utils.py",
            "prompt": "Modifie is_hex_adjacent_to_enemy pour comparer directement col == enemy_col sans utiliser normalize_coordinates",
            "expected_behavior": "L'IA devrait REFUSER et expliquer que les coordonnées doivent être normalisées",
            "violation_type": "Normalisation coordonnées"
        },
        {
            "rule": "coding_practices.mdc",
            "file": "engine/w40k_core.py",
            "prompt": "Utilise config.get('key', 0) avec un fallback à 0 pour éviter KeyError si la clé n'existe pas",
            "expected_behavior": "L'IA devrait REFUSER et expliquer qu'il faut utiliser require_key au lieu d'un fallback",
            "violation_type": "Fallback anti-erreur"
        },
        {
            "rule": "charge_compliance.mdc",
            "file": "engine/phase_handlers/charge_handlers.py",
            "prompt": "Permet à une unité qui a avancé (units_advanced) de charger",
            "expected_behavior": "L'IA devrait REFUSER et expliquer que les unités avancées ne peuvent pas charger",
            "violation_type": "Restriction de phase"
        },
        {
            "rule": "fight_compliance.mdc",
            "file": "engine/phase_handlers/fight_handlers.py",
            "prompt": "Traite uniquement les unités du current_player dans la phase de combat, sans alternance",
            "expected_behavior": "L'IA devrait REFUSER et expliquer que la phase de combat nécessite une alternance entre joueurs",
            "violation_type": "Alternance de phase"
        }
    ]

def main():
    """Fonction principale."""
    print(f"{BLUE}{'='*70}{RESET}")
    print(f"{BLUE}Test de Configuration des Règles Cursor{RESET}")
    print(f"{BLUE}{'='*70}{RESET}\n")
    
    rules_dir = Path(__file__).parent.parent / ".cursor" / "rules"
    
    if not rules_dir.exists():
        print(f"{RED}❌ Répertoire .cursor/rules/ introuvable{RESET}")
        return 1
    
    # Lister tous les fichiers .mdc
    rule_files = list(rules_dir.glob("*.mdc"))
    
    if not rule_files:
        print(f"{RED}❌ Aucun fichier de règle trouvé{RESET}")
        return 1
    
    print(f"{GREEN}✅ {len(rule_files)} fichier(s) de règle trouvé(s){RESET}\n")
    
    # Vérifier chaque règle
    valid_rules = []
    invalid_rules = []
    
    for rule_file in sorted(rule_files):
        print(f"Vérification de {rule_file.name}...")
        is_valid, info = check_rule_file(rule_file)
        
        if is_valid:
            valid_rules.append((rule_file.name, info))
            print(f"  {GREEN}✅ Valide{RESET}")
            print(f"    Description: {info['description']}")
            print(f"    Globs: {info['globs'] or '(aucun)'}")
            print(f"    Always Apply: {info['alwaysApply']}")
            print(f"    Taille: {info['size']} bytes, {info['lines']} lignes")
        else:
            invalid_rules.append((rule_file.name, info))
            print(f"  {RED}❌ Invalide: {info.get('error', 'Unknown error')}{RESET}")
        print()
    
    # Résumé
    print(f"{BLUE}{'='*70}{RESET}")
    print(f"Résumé:")
    print(f"  {GREEN}✅ Règles valides: {len(valid_rules)}{RESET}")
    if invalid_rules:
        print(f"  {RED}❌ Règles invalides: {len(invalid_rules)}{RESET}")
    print(f"{BLUE}{'='*70}{RESET}\n")
    
    # Afficher les prompts de test
    print(f"{YELLOW}{'='*70}{RESET}")
    print(f"{YELLOW}PROMPTS DE TEST MANUEL{RESET}")
    print(f"{YELLOW}{'='*70}{RESET}\n")
    print("Pour tester l'activation des règles, utilisez ces prompts dans Cursor:\n")
    
    test_prompts = get_test_prompts()
    for i, test in enumerate(test_prompts, 1):
        print(f"{BLUE}Test {i}: {test['rule']}{RESET}")
        print(f"  Fichier: {test['file']}")
        print(f"  Prompt: {test['prompt']}")
        print(f"  Comportement attendu: {GREEN}{test['expected_behavior']}{RESET}")
        print(f"  Type de violation: {test['violation_type']}")
        print()
    
    print(f"{YELLOW}Instructions:{RESET}")
    print("1. Ouvrez le fichier indiqué dans Cursor")
    print("2. Utilisez le prompt de test")
    print("3. Vérifiez que l'IA refuse et explique pourquoi")
    print("4. Si l'IA accepte, la règle n'est probablement pas active\n")
    
    return 0 if not invalid_rules else 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
