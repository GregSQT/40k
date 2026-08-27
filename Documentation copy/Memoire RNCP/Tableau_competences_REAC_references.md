# Tableau des compétences du référentiel RNCP 6 CDA et références dans le mémoire

**Base :** tableau officiel REAC CDA (3 activités types, 11 compétences professionnelles).  
**Document :** mémoire Trazyn's Trials — **memoire.pdf** (édition mise à jour, ~66 pages). Référence pagination : *Emplacements_modifications_memoire.pdf.md* et structure du mémoire.

---

## Réponses rapides

- **Le tableau joint (AT + CP) est-il pertinent ?** Oui. Il est la formulation officielle du REAC CDA et doit servir de **référence unique** pour la section « Compétences du référentiel » du mémoire.
- **Peut-il servir de base ?** Oui. Il doit servir de base pour : (1) rédiger la liste des compétences dans le mémoire (libellés officiels) ; (2) établir la correspondance avec les parties du document qui les illustrent (tableau ci-dessous).

---

## Tableau : compétence → partie du document

| N° Fiche AT | Activités types | N° Fiche CP | Compétences professionnelles | Référence dans le mémoire (section, partie) |
|:-----------:|-----------------|:-----------:|------------------------------|--------------------------------------------|
| 1 | Développer une application sécurisée | 1 | Installer et configurer son environnement de travail en fonction du projet | **Gestion du projet** → 1. Environnement humain et technique → *Environnement technique* (p. 10–11) : stack (Python, Flask, SQLite, React, TypeScript, Vite, PIXI, Git), Contrôle de version, Déploiement (Docker Compose). |
| 1 | Développer une application sécurisée | 2 | Développer des interfaces utilisateur | **Réalisations front-end** (p. 18–27) : 1. Organisation du code ; 2. Organisation de l'interface et maquettes ; 3. Interface utilisateur – écrans et exemples (SPA React, plateau PIXI, log, parcours auth → jeu → replay). Plan du site : p. 27. |
| 1 | Développer une application sécurisée | 3 | Développer des composants métier | **Réalisation back-end** (p. 38–42) : 1. Structure du code (W40KEngine, phase_handlers, observation_builder, action_decoder, reward_calculator) ; 4. Composants métier. **Réalisations IA** (p. 44–45) : pipeline d'entraînement, observation, récompenses. |
| 1 | Développer une application sécurisée | 4 | Contribuer à la gestion d'un projet informatique | **Gestion du projet** (p. 10–11, 16) : 1. Environnement humain et technique (démarche itérative, planning, état d'avancement *Roadmap.md*) ; 2. Objectifs de qualité (p. 16). **Besoins du projet** → 3. Contraintes et livrables (p. 9 et suiv.). |
| 2 | Concevoir et développer une application sécurisée organisée en couches | 5 | Analyser les besoins et maquetter une application | **Besoins du projet** (p. 9 et suiv.) : 2. Cahier des charges (besoins initiaux, fonctionnels, non fonctionnels). **Réalisations front-end** → 2. Organisation de l'interface et maquettes (p. 18–27, parcours, plan du site / sitemap, maquettes). |
| 2 | Concevoir et développer une application sécurisée organisée en couches | 6 | Définir l'architecture logicielle d'une application | **Résumé / Introduction** (p. 6–7) : architecture en modules (engine/, ai/, services/, frontend/, config/). **Réalisation back-end** (p. 38–39) : *Architecture logicielle* (Moteur, IA, API, Frontend, Config) ; 1. Structure du code. |
| 2 | Concevoir et développer une application sécurisée organisée en couches | 7 | Concevoir et mettre en place une base de données relationnelle | **Réalisation back-end** → 2. Base de données (p. 42) : SQLite *config/users.db*, tables (profiles, users, game_modes, options, profile_game_modes, profile_options, sessions), script *initialize_auth_db*, spécification *USER_ACCESS_CONTROL.md*. Annexes : schéma MEA / physique, script BDD auth. |
| 2 | Concevoir et développer une application sécurisée organisée en couches | 8 | Développer des composants d'accès aux données SQL et NoSQL | **Réalisation back-end** → 2. Base de données (p. 42, accès auth, requêtes paramétrées) ; 3. API RESTful (*services/api_server.py*, routes auth/game/replay). Pas de NoSQL dans le projet ; accès données = SQLite + API. |
| 3 | Préparer le déploiement d'une application sécurisée | 9 | Préparer et exécuter les plans de tests d'une application | **Gestion du projet** → 2. Objectifs qualité (p. 16, traçabilité, conformité). **Jeux d'essai** (p. 49) : plan de tests (test moteur, check_ai_rules, audit_shooting_phase, analyzer, hidden_action_finder, bot_evaluation, métriques). **Réalisations IA** → Conformité et analyse des logs. Jeu d'essai représentatif : Analyzer.py + vérification visuelle (*Jeu_essai_complet.md*). |
| 3 | Préparer le déploiement d'une application sécurisée | 10 | Préparer et documenter le déploiement d'une application | **Déploiement** (p. 51–52) : procédure sur NAS Synology, Docker Compose, configuration (ports, reverse proxy, volumes, variables d'environnement), schéma de déploiement. **Documentation** : *Deployment_Synology.md*. |
| 3 | Préparer le déploiement d'une application sécurisée | 11 | Contribuer à la mise en production dans une démarche DevOps | **Déploiement** (p. 51–52) : Docker Compose (backend + frontend Nginx), déploiement sur NAS Synology, healthcheck (*/api/health*), variables d'environnement (*SYNO_CONFIG_PATH*, *SYNO_MODELS_PATH*, *SYNO_RUNTIME_PATH*), flux applicatif. **Besoins** : application conteneurisable et déployable. |
*Pagination memoire.pdf (~66 p.). Points d'ancrage : Besoins/Contexte p.9, Objectifs qualité p.16, Plan du site p.27, BDD p.42, Jeux d'essai p.49, Checklist p.66. Ajuster si ta TDM diffère.*

---

## Compétences transversales (REAC)

| Compétence transversale | Où dans le mémoire |
|-------------------------|--------------------|
| Communiquer en français et en anglais | Rédaction du mémoire (FR) ; documentation technique et code en anglais (noms de variables, fichiers, *Documentation/*). |
| Mettre en œuvre une démarche de résolution de problème | Besoins → contraintes techniques ; Gestion du projet (itération, objectifs qualité) ; Conformité (check_ai_rules, analyzer, action masking). |
| Apprendre en continu | Veille durant le projet (RL, action masking, évaluation agents, métriques PPO, sécurisation, documentation) ; références *AI_TRAINING.md*, *AI_METRICS.md*, *AI_TURN.md*. |

---

## Utilisation recommandée

1. **Dans le mémoire** : Remplacer l’actuelle liste « Compétences du référentiel » (reformulation front/back) par la **liste officielle** des 3 activités et 11 CP (libellés du tableau joint), éventuellement suivie d’un court paragraphe « Mise en œuvre dans ce projet » qui renvoie aux sections ci-dessus.
2. **Pour la soutenance** : Utiliser ce tableau pour préparer les réponses aux questions du type « Où montrez-vous la compétence X ? » (section + extrait à citer).
3. **Pour la checklist CDC** : La case « Liste des compétences » est cochée à condition que la liste du mémoire reprenne bien les 11 CP (et les 3 AT) du référentiel.
