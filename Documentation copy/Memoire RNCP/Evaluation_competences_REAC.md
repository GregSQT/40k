# Évaluation des compétences REAC CDA – Projet Trazyn's Trials

**Objectif :** Vérifier pour chaque compétence professionnelle (CP) du référentiel RNCP 6 CDA si le mémoire et le projet apportent des éléments de preuve suffisants pour une **validation** par le jury.

**Légende des statuts :**
- **Validée** : Preuves claires et suffisantes dans le mémoire (section(s) dédiée(s), livrables, démonstration).
- **Partiellement validée** : Preuves présentes mais à expliciter, à renforcer ou partiellement couvertes (ex. un sous-point manquant).
- **À renforcer** : Peu de traces dans le mémoire ou éléments manquants pour le niveau attendu.

---

## Activité 1 – Développer une application sécurisée

### CP1 – Installer et configurer son environnement de travail en fonction du projet

| Critère | Évaluation |
|---------|------------|
| **Statut** | **Validée** |
| **Preuves dans le mémoire** | Gestion du projet → Environnement technique (p. 10–11) : stack (Python, Flask, SQLite, React, TypeScript, Vite, PIXI), Git, Docker Compose ; configuration par projet (config/agents, configs d'entraînement). |
| **Éléments manquants / remarques** | Aucun. Environnement décrit, outillage (IDE implicite, Git, Docker) et configuration projet explicites. |

---

### CP2 – Développer des interfaces utilisateur

| Critère | Évaluation |
|---------|------------|
| **Statut** | **Validée** |
| **Preuves dans le mémoire** | Réalisations front-end (p. 18–27) : SPA React/TypeScript, composants (auth, plateau PIXI, log), parcours utilisateur (auth → jeu → replay), organisation du code et de l'interface, plan du site. |
| **Éléments manquants / remarques** | À confirmer en soutenance : maquettes / wireframes si demandés ; accessibilité (section prévue dans la structure). Compléter si des sous-parties sont encore « [À intégrer] ». |

---

### CP3 – Développer des composants métier

| Critère | Évaluation |
|---------|------------|
| **Statut** | **Validée** |
| **Preuves dans le mémoire** | Réalisation back-end (p. 38–42) : W40KEngine, phase_handlers (movement, shooting, charge, fight, deployment), observation_builder, action_decoder, reward_calculator. Réalisations IA (p. 44–45) : pipeline d'entraînement, observation, récompenses. |
| **Éléments manquants / remarques** | Aucun. Cœur métier (moteur, règles, IA) bien identifié et documenté. |

---

### CP4 – Contribuer à la gestion d'un projet informatique

| Critère | Évaluation |
|---------|------------|
| **Statut** | **Partiellement validée** |
| **Preuves dans le mémoire** | Gestion du projet (p. 10–11, 16) : démarche itérative, planning en 5 étapes, état d'avancement (*Roadmap.md*), objectifs de qualité. Besoins → Contraintes et livrables (p. 9 et suiv.). |
| **Éléments manquants / remarques** | Projet en autonomie (formation) : pas d'équipe ni de tuteur entreprise détaillé. Pour renforcer : expliciter le suivi (points d'étape, choix d'architecture, priorisation), et compléter « [A compléter : environnement humain] » si possible (encadrement pédagogique, livrables). |

---

## Activité 2 – Concevoir et développer une application sécurisée organisée en couches

### CP5 – Analyser les besoins et maquetter une application

| Critère | Évaluation |
|---------|------------|
| **Statut** | **Validée** |
| **Preuves dans le mémoire** | Besoins du projet (p. 9 et suiv.) : cahier des charges (besoins initiaux, fonctionnels, non fonctionnels). Réalisations front-end → Organisation de l'interface et maquettes (p. 18–27), parcours, plan du site / sitemap. |
| **Éléments manquants / remarques** | Si maquettes visuelles (wireframes) ne sont pas dans le mémoire, les mentionner ou les ajouter (ou indiquer « maquettes fonctionnelles / parcours »). Sinon suffisant. |

---

### CP6 – Définir l'architecture logicielle d'une application

| Critère | Évaluation |
|---------|------------|
| **Statut** | **Validée** |
| **Preuves dans le mémoire** | Résumé / Introduction (p. 6–7) : architecture en modules (engine/, ai/, services/, frontend/, config/). Réalisation back-end (p. 38–39) : description des blocs (Moteur, IA, API, Frontend, Config), structure du code, single source of truth. |
| **Éléments manquants / remarques** | Aucun. Architecture claire et cohérente avec le code. |

---

### CP7 – Concevoir et mettre en place une base de données relationnelle

| Critère | Évaluation |
|---------|------------|
| **Statut** | **Validée** |
| **Preuves dans le mémoire** | Réalisation back-end → 2. Base de données (p. 42) : SQLite *config/users.db*, schéma (profiles, users, game_modes, options, tables d'association, sessions), script *initialize_auth_db*, spécification *USER_ACCESS_CONTROL.md*. Annexes : schéma MEA / physique, script BDD auth. |
| **Éléments manquants / remarques** | Aucun. BDD relationnelle conçue, documentée et mise en place (auth). |

---

### CP8 – Développer des composants d'accès aux données SQL et NoSQL

| Critère | Évaluation |
|---------|------------|
| **Statut** | **Partiellement validée** |
| **Preuves dans le mémoire** | Réalisation back-end (p. 42) : accès BDD auth (requêtes paramétrées, pas d'injection). API RESTful (*services/api_server.py*) : routes auth/game/replay qui s'appuient sur les données. |
| **Éléments manquants / remarques** | **NoSQL** : non utilisé dans le projet. Le référentiel mentionne « SQL et NoSQL ». À anticiper en soutenance : préciser que le projet utilise uniquement SQL (SQLite) ; les composants d'accès aux données (couche auth, API) sont bien présents. Si le jury exige une preuve NoSQL, indiquer que c'est hors périmètre du projet actuel mais maîtrisable (formation ou autre contexte). |

---

## Activité 3 – Préparer le déploiement d'une application sécurisée

### CP9 – Préparer et exécuter les plans de tests d'une application

| Critère | Évaluation |
|---------|------------|
| **Statut** | **Validée** |
| **Preuves dans le mémoire** | Gestion du projet → Objectifs qualité (p. 16) : traçabilité, conformité. Jeux d'essai (p. 49) : plan de tests (test moteur, check_ai_rules, audit_shooting_phase, analyzer, hidden_action_finder, bot_evaluation, métriques). Réalisations IA → Conformité et analyse des logs. Jeu d'essai représentatif : Analyzer.py + vérification visuelle. |
| **Éléments manquants / remarques** | Tests unitaires frontend / tests de charge non réalisés : déjà mentionné dans le mémoire (phrase recommandée dans *Emplacements_modifications_memoire.pdf.md*). Les scripts de conformité et l’analyzer constituent une preuve solide pour les tests fonctionnels et de règles métier. |

---

### CP10 – Préparer et documenter le déploiement d'une application

| Critère | Évaluation |
|---------|------------|
| **Statut** | **Validée** |
| **Preuves dans le mémoire** | Déploiement (p. 51–52) : procédure sur NAS Synology, Docker Compose, configuration (ports, reverse proxy, volumes, variables d'environnement), schéma de déploiement. Documentation : *Deployment_Synology.md*. |
| **Éléments manquants / remarques** | Aucun. Déploiement réel, documenté et reproductible. |

---

### CP11 – Contribuer à la mise en production dans une démarche DevOps

| Critère | Évaluation |
|---------|------------|
| **Statut** | **Validée** |
| **Preuves dans le mémoire** | Déploiement (p. 51–52) : conteneurisation (Docker Compose), déploiement sur NAS Synology, healthcheck (*/api/health*), variables d'environnement, flux applicatif. Besoins : application conteneurisable et déployable. |
| **Éléments manquants / remarques** | CI/CD non décrit (ex. pipeline Git). Pour une validation pleine, une phrase sur les évolutions possibles (CI avec check_ai_rules, analyzer) ou sur la reproductibilité du déploiement suffit. |

---

## Compétences transversales

| Compétence | Statut | Preuves / remarques |
|------------|--------|----------------------|
| **Communiquer en français et en anglais** | **Validée** | Mémoire en français ; documentation technique et code en anglais (fichiers, variables, *Documentation/*). |
| **Mettre en œuvre une démarche de résolution de problème** | **Validée** | Besoins et contraintes ; gestion de projet itérative ; conformité (check_ai_rules, analyzer, action masking) ; résolution de problèmes techniques décrite dans le mémoire. |
| **Apprendre en continu** | **Validée** | Veille (RL, action masking, métriques PPO, sécurisation, documentation) ; références *AI_TRAINING.md*, *AI_METRICS.md*, *AI_TURN.md*. |

---

## Synthèse

| Statut | Nombre de CP |
|--------|----------------|
| **Validée** | 9 |
| **Partiellement validée** | 2 (CP4, CP8) |
| **À renforcer** | 0 |

**Points de vigilance pour la soutenance :**
1. **CP4** : Expliciter la gestion de projet (planning, suivi, priorisation) et compléter la partie « environnement humain » si possible.
2. **CP8** : Préparer une réponse sur l’absence de NoSQL (choix du projet, SQL seul ; NoSQL maîtrisable dans un autre contexte).
3. **CP9** : Rappeler que les tests reposent sur scripts de conformité + analyzer + vérification visuelle ; tests unitaires frontend et de charge prévus en évolution.

---

*Document à utiliser en préparation de la soutenance et pour vérifier la couverture du référentiel avant remise du mémoire.*
