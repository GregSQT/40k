import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

# Définition des semaines et tâches
weeks = list(range(1, 11))
tasks = [
    'IA minimale – adaptation agent',
    'IA apprentissage incrémental',
    'Unités multi-figurines / cohésion',
    'Modes jeu 1v1 et survie',
    'UX léger / polish',
    'Subdivision hex (optionnel)'
]

# Durée approximative en semaines pour chaque tâche
start_weeks = [1, 3, 5, 7, 9, 10]
end_weeks = [2, 4, 6, 8, 9, 10]
colors = ['#1f77b4', '#1f77b4', '#d62728', '#d62728', '#2ca02c', '#9467bd']  # rouge = 60% critique

# Tâches clés, livrables et critères de tests par palier
task_details = [
    'Adapter state encoding pour toutes les unités, renforcer meta-agent, implémenter RL, tests simples',
    'Tester apprentissage 1 type → 2 types, ajuster reward shaping et horizon, valider convergence',
    'Définir structure unité/figurines, implémenter cohésion, gérer occupation hex, adapter meta-agent',
    'Mode 1v1 boîte de base, mode survie, replay system, leaderboard simple',
    'Tooltips / highlights, stabilisation logs et performance, préparer démo/vidéos',
    'Découper hex ×10, adapter occupation/collisions, vérifier line-of-sight'
]

# Critères et tests supplémentaires pour chaque palier
task_tests = [
    '- Winrate >50% contre IA basique\n- Logs stables\n- Partie jouable sans crash',
    '- Convergence apprentissage confirmée\n- 10k+ épisodes testés\n- Décisions cohérentes multi-unités',
    '- Cohésion respectée\n- IA capable de gérer toutes les figurines de l’unité\n- Occupation hex correcte',
    '- Mode 1v1 jouable\n- Survie avec vagues successives\n- Leaderboard mis à jour correctement\n- Replays valides',
    '- Affichage clair des règles spéciales\n- Logs et performance stables\n- Démo prête pour présentation',
    '- Subdivision visuelle correcte\n- Occupation et collisions précises\n- Ligne de vue calculée correctement'
]

# Création PDF
with PdfPages('Planning_Warhammer_Complete.pdf') as pdf:
    fig, ax = plt.subplots(figsize=(14,10))
    
    for i, task in enumerate(tasks):
        ax.barh(task, end_weeks[i]-start_weeks[i]+1, left=start_weeks[i]-1, color=colors[i], edgecolor='black')
        # Ajouter tâches clés, livrables et tests à droite
        detail_text = f'{task_details[i]}\nTests:\n{task_tests[i]} (Semaine {start_weeks[i]}–{end_weeks[i]})'
        ax.text(end_weeks[i]+0.1, i, detail_text, va='center', fontsize=8)

    ax.set_xlabel('Semaines')
    ax.set_title('Planning 10 semaines – Démo jouable boîte de base (complet)')
    ax.set_xlim(0, 11)
    ax.set_yticks(range(len(tasks)))
    ax.set_yticklabels(tasks)
    ax.grid(axis='x', linestyle='--', alpha=0.5)

    # Ajouter indicateur 60% critique
    ax.axvline(x=6, color='red', linestyle='--', linewidth=2, label='60% critique')
    ax.legend()

    pdf.savefig(fig)
    plt.close()
