def extract_episode(file_path, episode_number):
    """
    Extrait un épisode spécifique du fichier log.
    
    Args:
        file_path: Chemin vers le fichier log (step.log ou debug.log)
        episode_number: Numéro de l'épisode à extraire (1, 2, 3, ...)
    
    Returns:
        Contenu de l'épisode (avec le marqueur de début, sans le marqueur de fin)
    """
    start_marker = f" === EPISODE {episode_number} START ==="
    end_marker = f" === EPISODE {episode_number + 1} START ==="
    
    captured_lines = []
    in_episode = False
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                # Démarrer la capture quand on trouve le marqueur de début
                if start_marker in line:
                    in_episode = True
                    captured_lines.append(line)
                    continue
                
                # Arrêter la capture quand on trouve le marqueur de fin
                if in_episode and end_marker in line:
                    break
                
                # Capturer les lignes de l'épisode
                if in_episode:
                    captured_lines.append(line)
    except FileNotFoundError:
        return None
    
    return ''.join(captured_lines) if captured_lines else None


if __name__ == "__main__":
    import sys
    
    # Vérifier les arguments
    if len(sys.argv) < 2:
        print("Usage: python check/episode.py <episode_number>")
        print("Example: python check/episode.py 4")
        sys.exit(1)
    
    try:
        episode_number = int(sys.argv[1])
    except ValueError:
        print(f"Erreur: '{sys.argv[1]}' n'est pas un numéro d'épisode valide")
        sys.exit(1)
    
    # Extraire l'épisode de step.log
    step_content = extract_episode("step.log", episode_number)
    if not step_content:
        print(f"⚠️  Épisode {episode_number} non trouvé dans step.log")
        step_content = ""
    
    # Extraire l'épisode de debug.log
    debug_content = extract_episode("debug.log", episode_number)
    if not debug_content:
        print(f"⚠️  Épisode {episode_number} non trouvé dans debug.log")
        debug_content = ""
    
    # Combiner les deux contenus
    combined_content = ""
    if step_content:
        combined_content += "=== STEP.LOG ===\n"
        combined_content += step_content
        combined_content += "\n"
    if debug_content:
        combined_content += "=== DEBUG.LOG ===\n"
        combined_content += debug_content
    
    if not combined_content:
        print(f"❌ Épisode {episode_number} non trouvé dans step.log ni debug.log")
        sys.exit(1)
    
    # Écrire dans episode<numéro>.log
    output_file = f"episode{episode_number}.log"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(combined_content)
    
    print(f"✅ Épisode {episode_number} extrait et écrit dans {output_file}")
    if step_content:
        print(f"   - step.log: {len(step_content.splitlines())} lignes")
    if debug_content:
        print(f"   - debug.log: {len(debug_content.splitlines())} lignes")