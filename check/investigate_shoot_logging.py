#!/usr/bin/env python3
"""
Script d'investigation : pourquoi certaines attaques shoot ne sont pas loguées
Focus sur E1 T3 Unit 4 -> Unit 8 : 2 attaques exécutées mais 1 seule loguée
"""

import re

def analyze_shoot_logging():
    """Analyze step.log and movement_debug.log to understand shoot logging behavior"""
    
    print("=" * 80)
    print("INVESTIGATION: Pourquoi certaines attaques shoot ne sont pas loguées")
    print("=" * 80)
    print()
    
    # Read movement_debug.log
    try:
        with open('movement_debug.log', 'rb') as f:
            debug_content = f.read().decode('utf-8', errors='ignore')
    except:
        print("❌ Cannot read movement_debug.log")
        return
    
    # Read step.log
    try:
        with open('step.log', 'r') as f:
            step_content = f.read()
    except:
        print("❌ Cannot read step.log")
        return
    
    print("1. ANALYSE DU CAS PROBLÉMATIQUE : E1 T3 Unit 4 -> Unit 8")
    print("-" * 80)
    
    # Extract all Unit 4 -> Unit 8 attacks in E1 T3 from debug
    debug_matches = re.findall(
        r'\[SHOOT DEBUG\] E1 T3 shoot attack_executed: Unit 4 -> Unit 8.*?',
        debug_content
    )
    print(f"   Attaques exécutées (debug): {len(debug_matches)}")
    for i, match in enumerate(debug_matches, 1):
        print(f"      {i}. {match}")
    
    # Extract context around first skipped attack
    print()
    print("2. CONTEXTE AUTOUR DE LA PREMIÈRE ATTAQUE SKIP")
    print("-" * 80)
    
    # Find the first occurrence
    first_match_pos = debug_content.find('[SHOOT DEBUG] E1 T3 shoot attack_executed: Unit 4 -> Unit 8')
    if first_match_pos != -1:
        context_start = max(0, first_match_pos - 500)
        context_end = min(len(debug_content), first_match_pos + 1000)
        context = debug_content[context_start:context_end]
        
        # Extract lines around the skip
        lines = context.split('\n')
        for i, line in enumerate(lines):
            if 'Unit 4 -> Unit 8' in line or 'SKIPPING' in line or 'waiting_for_player' in line:
                print(f"      {line}")
        
        # Check if last_attack_result is mentioned
        if 'last_attack_result' in context.lower():
            print()
            print("      ⚠️  'last_attack_result' mentionné dans le contexte")
        else:
            print()
            print("      ℹ️  'last_attack_result' non mentionné dans le contexte")
    
    # Extract logged attacks from step.log
    print()
    print("3. ATTAQUES LOGUÉES DANS STEP.LOG")
    print("-" * 80)
    
    step_matches = re.findall(
        r'\[.*?\] E1 T3 P\d+ SHOOT : Unit 4\(.*?\) SHOT at unit 8\(.*?\)',
        step_content
    )
    print(f"   Attaques loguées (step.log): {len(step_matches)}")
    for i, match in enumerate(step_matches, 1):
        print(f"      {i}. {match[:100]}...")
    
    # Extract all waiting_for_player=True skips for shoot actions
    print()
    print("4. TOUS LES SKIPS POUR ACTIONS SHOOT")
    print("-" * 80)
    
    skip_pattern = r'\[STEP LOGGER DEBUG\] E\d+ T\d+ shoot: SKIPPING logging - waiting_for_player=True.*?'
    skip_matches = re.findall(skip_pattern, debug_content)
    print(f"   Total de skips pour 'shoot': {len(skip_matches)}")
    
    # Group by episode/turn/unit
    skip_groups = {}
    for skip in skip_matches:
        unit_match = re.search(r'unit_id=(\d+)', skip)
        ep_turn_match = re.search(r'E(\d+) T(\d+)', skip)
        if unit_match and ep_turn_match:
            key = f"E{ep_turn_match.group(1)} T{ep_turn_match.group(2)} Unit {unit_match.group(1)}"
            skip_groups[key] = skip_groups.get(key, 0) + 1
    
    print()
    print("   Groupés par (episode, turn, unit):")
    for key, count in sorted(skip_groups.items()):
        print(f"      {key}: {count} skip(s)")
    
    # Check what happens AFTER a skip
    print()
    print("5. CE QUI SE PASSE APRÈS UN SKIP")
    print("-" * 80)
    
    # Find all skip positions
    skip_positions = []
    for match in re.finditer(r'\[STEP LOGGER DEBUG\].*?SKIPPING.*?unit_id=4', debug_content):
        skip_positions.append(match.start())
    
    for i, pos in enumerate(skip_positions[:3], 1):  # First 3 skips
        after_context = debug_content[pos:pos+800]
        lines = after_context.split('\n')[:15]
        print(f"   Skip #{i} - Unit 4:")
        for line in lines:
            if line.strip() and ('SHOOT DEBUG' in line or 'STEP LOGGER' in line or 'attack_executed' in line):
                print(f"      {line}")
        print()
    
    # Hypothesis
    print("6. HYPOTHÈSES")
    print("-" * 80)
    print("   HYPOTHÈSE 1: Une action 'shoot' peut exécuter plusieurs attaques (boucle)")
    print("   HYPOTHÈSE 2: Si waiting_for_player=True après une attaque, le logging est skip")
    print("   HYPOTHÈSE 3: Seule la DERNIÈRE attaque est loguée quand waiting_for_player=False")
    print("   HYPOTHÈSE 4: Les attaques intermédiaires sont perdues")
    print()
    print("   SOLUTION PROPOSÉE:")
    print("   - Pour 'shoot', vérifier si 'last_attack_result' est présent dans game_state")
    print("   - Si oui, logger même si waiting_for_player=True (comme pour 'combat')")
    print("   - MAIS: 'shoot' utilise 'last_attack_result' (1 attaque), pas 'all_attack_results' (plusieurs)")
    print("   - PROBLÈME: On ne peut logger qu'UNE attaque par appel à log_action()")
    print()
    print("   ⚠️  ROOT CAUSE PROBABLE:")
    print("   - Le shooting handler exécute plusieurs attaques dans une boucle")
    print("   - Chaque attaque met à jour 'last_attack_result' (écrase la précédente)")
    print("   - Seule la DERNIÈRE attaque est disponible dans 'last_attack_result'")
    print("   - Les attaques précédentes sont perdues si le logging est skip")
    print()
    print("   → SOLUTION RÉELLE:")
    print("   - Le shooting handler doit collecter TOUTES les attaques dans 'all_attack_results'")
    print("   - Comme le fait le fight handler pour 'combat'")
    print("   - Puis logger chaque attaque individuellement")

if __name__ == '__main__':
    analyze_shoot_logging()

