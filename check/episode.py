def extract_episode(file_path, episode_number):
    """
    Extrait un épisode spécifique du fichier log.
    
    Args:
        file_path: Chemin vers le fichier step.log
        episode_number: Numéro de l'épisode à extraire (1, 2, 3, ...)
    
    Returns:
        Contenu de l'épisode (avec le marqueur de début, sans le marqueur de fin)
    """
    start_marker = f" === EPISODE {episode_number} START ==="
    end_marker = f" === EPISODE {episode_number + 1} START ==="
    
    captured_lines = []
    in_episode = False
    
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
    
    return ''.join(captured_lines)


if __name__ == "__main__":
    import sys
    
    # Vérifier les arguments
    if len(sys.argv) < 2:
        print("Usage: python check/ep1.py <episode_number> [input_file]")
        print("Example: python check/ep1.py 4 step.log")
        sys.exit(1)
    
    try:
        episode_number = int(sys.argv[1])
    except ValueError:
        print(f"Erreur: '{sys.argv[1]}' n'est pas un numéro d'épisode valide")
        sys.exit(1)
    
    # Fichier source (step.log par défaut, ou deuxième argument)
    input_file = sys.argv[2] if len(sys.argv) > 2 else "step.log"
    
    # Extraire l'épisode
    content = extract_episode(input_file, episode_number)
    
    if not content:
        print(f"⚠️  Épisode {episode_number} non trouvé dans {input_file}")
        sys.exit(1)
    
    # Écrire dans episode<numéro>.log
    output_file = f"episode{episode_number}.log"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"✅ Épisode {episode_number} extrait et écrit dans {output_file}")