# Documentation — Index

Index des documents à la racine de `Documentation/`. Les sous-dossiers (TODO, Prompts, Memoire, etc.) ne sont pas listés ici.

---

## Architecture moteur et règles de tour

| Document | Rôle |
|----------|------|
| **[AI_TURN.md](AI_TURN.md)** | Règles de tour, phases, séquence d’activation, tracking, contrat de codage. **Référence pour toute logique de jeu.** |
| **[AI_IMPLEMENTATION.md](AI_IMPLEMENTATION.md)** | Architecture du moteur : modules (`w40k_core`, phase_handlers, observation, reward, action_decoder), flux, caches, déploiement. **Vue d’ensemble du code engine.** |

**Voir aussi** : Weapon_rules.md (système d’armes), Unit_rules.md (règles d’unités), CONFIG_FILES.md (configs).

---

## Entraînement et tuning

| Document | Rôle |
|----------|------|
| **[AI_TRAINING.md](AI_TRAINING.md)** | **Référence unique** training/tuning : pipeline (train.py, env, wrappers), configs, monitoring, bots, anti-overfitting, dépannage ; inclut la section « Évolutions prévues : League / curriculum training ». |
| **[AI_METRICS.md](AI_METRICS.md)** | Métriques et tuning : guide de tuning rapide (0_critical, problèmes courants, matrice → paramètres) + analyse experte (patterns, diagnostics, études de cas). |
| **[AI_OBSERVATION.md](AI_OBSERVATION.md)** | Système d’observation (vecteur, asymétrie, intégration training). |
| **[Macro_agent.md](Macro_agent.md)** | Agent macro : architecture macro/micro, scénarios, config, évaluation. |

---

## Systèmes de jeu et référence métier

| Document | Rôle |
|----------|------|
| **[Weapon_rules.md](Weapon_rules.md)** | Système d’armes : armurerie TypeScript, règles (RAPID_FIRE, etc.), sélection IA, backend/frontend. **Référence complète armes.** → Vue d’ensemble dans AI_IMPLEMENTATION (section weapons/). |
| **[Unit_rules.md](Unit_rules.md)** | Règles d’unités : `unit_rules.json`, `UNIT_RULES` dans les unités TS, résolution, choix contextuels. |
| **Reactive move** | Règle d’unité : spécification dans [Unit_rules.md](Unit_rules.md) (section « 10) Specification : reactive_move »). |

---

## Configuration et outillage

| Document | Rôle |
|----------|------|
| **[CONFIG_FILES.md](CONFIG_FILES.md)** | Référence des fichiers de config : weapon_rules, game_config, training/rewards par agent, scénarios, armurerie. |
| **[Code_Compliance/GAME_Analyzer.md](Code_Compliance/GAME_Analyzer.md)** | `ai/analyzer.py` : analyse de `step.log`, validation des règles de jeu. |
| **[Code_Compliance/AI_RULES_checker.md](Code_Compliance/AI_RULES_checker.md)** | `scripts/check_ai_rules.py` : vérification de conformité AI_TURN / coding_practices. |
| **[Code_Compliance/Hidden_action_finder.md](Code_Compliance/Hidden_action_finder.md)** | `ai/hidden_action_finder.py` : détection des mouvements/attaques non logués (step.log vs debug.log). |
| **[Code_Compliance/Fix_violations_guideline.md](Code_Compliance/Fix_violations_guideline.md)** | Guideline / prompt pour automatiser les correctifs. |

---

## Déploiement, infra, projet

| Document | Rôle |
|----------|------|
| **[Deployment_Synology.md](Deployment_Synology.md)** | Déploiement Synology : Docker (compose, volumes), réseau (NAT, reverse proxy, HTTPS, DDNS). |
| **[USER_ACCESS_CONTROL.md](USER_ACCESS_CONTROL.md)** | Auth, profils, droits d’accès (spécification). |
| **[Roadmap.md](Roadmap.md)** | Paliers démo, état d’avancement. |
| **[ENGINE_PROFILING_OPTIMIZATION.md](ENGINE_PROFILING_OPTIMIZATION.md)** | Profilage du moteur (py-spy, cProfile). |
| **[CURSOR_SUB_AGENTS.md](CURSOR_SUB_AGENTS.md)** | Règles Cursor par domaine (shooting, movement, charge, fight). |

---

## État et historique

| Document | Rôle |
|----------|------|
| **[DOCUMENTATION_STATUS.md](DOCUMENTATION_STATUS.md)** | Corrections récentes, fusions, statut des docs, références corrigées. |

---

**Entrée recommandée** : pour le moteur → AI_TURN.md + AI_IMPLEMENTATION.md ; pour l’entraînement → AI_TRAINING.md ; pour les armes → Weapon_rules.md (ou section weapons/ dans AI_IMPLEMENTATION pour la vue courte).
