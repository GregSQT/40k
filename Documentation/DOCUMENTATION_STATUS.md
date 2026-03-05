# État de la documentation (racine Documentation/)

> Dernière revue : mars 2025. Ce fichier résume les corrections effectuées et les points d’attention.
>
> **Index des docs** : [README.md](README.md) — liste des documents regroupés par thème (architecture, training, systèmes de jeu, config, déploiement) pour éviter les docs orphelins.

## Corrections effectuées (alignement code ↔ doc)

- **CONFIG_FILES.md**  
  - Parser armurerie : `engine/armory_parser.py` → `engine/weapons/parser.py` (ArmoryParser).  
  - Références à des fichiers inexistants retirées ou redirigées : `WEAPON_RULES_DESIGN.md`, `ARMORY_REFACTOR.md` → voir Weapon_rules.md.  
  - Related docs : liens mis à jour.

- **AI_IMPLEMENTATION.md**  
  - Module de validation : `shared/validation.py` → `shared/data_validation.py` (exemples d’import corrigés).  
  - Référence à `Documentation/unit_cache21.md` (fichier supprimé) remplacée par renvoi à la section « Units cache & HP_CUR » dans ce document et AI_TURN.md.

- **AI_TURN.md**  
  - Référence à `unit_cache21.md` retirée ; renvoi uniquement à AI_IMPLEMENTATION.md.

- **AI_OBSERVATION.md**  
  - Référence à `AI_GAME_OVERVIEW.md` (inexistant) retirée des Related Documents.

- **AI_TRAINING.md**  
  - Quick Start : `--config default` remplacé par `--agent`, `--training-config`, `--rewards-config`, `--scenario`.  
  - Récompenses : `rewards_master.json` → `config/agents/<agent>/<agent>_rewards_config.json` (partout).  
  - Step log : `train_step.log` → `step.log` (fichier réel généré avec `--step`).  
  - Continue model : exemple avec `--append` et chemin modèle dérivé de l’agent.

- **Code compliance** : ANALYZER.md, CHECK_AI_RULES.md, fix_game_rules_violations.md déplacés dans **Documentation/Code_Compliance/** et renommés (GAME_Analyzer.md, AI_RULES_checker.md, Fix_violations_guideline.md) ; ajout de Hidden_action_finder.md pour `ai/hidden_action_finder.py`.

- **Weapon_rules.md**  
  - Référence à `ARMORY_REFACTOR.md` remplacée par un renvoi aux sections du présent document.

## Fichiers ou références inexistants (déjà traités dans les mises à jour ci‑dessus)

- `Documentation/unit_cache21.md` — supprimé ou jamais committé ; contenu couvert par AI_IMPLEMENTATION.md et AI_TURN.md.  
- `WEAPON_RULES_DESIGN.md` — jamais créé ; design décrit dans CONFIG_FILES.md et Weapon_rules.md.  
- `ARMORY_REFACTOR.md` — jamais créé ; architecture décrite dans Weapon_rules.md.  
- `AI_GAME_OVERVIEW.md` — référencé dans AI_OBSERVATION.md ; référence retirée.

## Mises à jour supplémentaires (mars 2025)

- **Déploiement** : Contenu des trois docs (deploiement_agent.md, DEPLOYMENT_ACTIVE_V1.md, DEPLOYMENT_AGENT_SPEC_EXECUTABLE_V1.md) intégré dans **AI_IMPLEMENTATION.md** (section phase_handlers + deployment_handlers). Les trois fichiers ont été supprimés. Le déploiement actif est implémenté (phase deployment, deploy_unit, deployment_handlers.py).

- **Métriques / tuning** : **PPO_METRICS_TUNING_GUIDE.md** fusionné dans **AI_METRICS.md** (section « Quick Tuning Guide ») ; PPO_METRICS_TUNING_GUIDE.md supprimé. AI_METRICS.md est la référence unique (tuning rapide + analyse experte).
- **League / curriculum** : **LEAGUE_CURRICULUM_TRAINING_PLAN.md** intégré dans **AI_TRAINING.md** (section « Évolutions prévues : League / curriculum training ») ; LEAGUE_CURRICULUM_TRAINING_PLAN.md supprimé.

- **Règles Cursor** : `.cursor/rules/coding_practices.mdc` et `ai_turn_compliance.mdc` mis à jour : `shared/validation.py` → `shared/data_validation.py`.

- **Roadmap.md** : Pourcentages de complétion révisés (Palier 0 ~70–75 %, Palier 1 ~60–65 %) et mention du déploiement actif implémenté.

- **train.py** : Référence « AI_GAME_OVERVIEW.md » remplacée par « AI_TURN.md / AI_IMPLEMENTATION.md ».

## Documents à la racine : statut rapide

| Document | Statut | Note |
|----------|--------|------|
| AI_IMPLEMENTATION.md | À jour | Inclut section déploiement (deployment_handlers). |
| AI_METRICS.md | OK | Référence unique métriques + tuning (inclut ex-PPO_METRICS_TUNING_GUIDE). |
| AI_OBSERVATION.md | OK | Réf. AI_GAME_OVERVIEW retirée. |
| AI_TRAINING.md | À jour | Référence unique training/tuning ; section « Training pipeline (architecture) » ; section « Évolutions prévues : League / curriculum » (ex-LEAGUE_CURRICULUM_TRAINING_PLAN) ; CLI et commandes alignées. |
| AI_TURN.md | OK | Réf. unit_cache21 retirée. |
| Code_Compliance/ | OK | GAME_Analyzer, AI_RULES_checker, Hidden_action_finder, Fix_violations_guideline. |
| CONFIG_FILES.md | À jour | Parser et liens corrigés. |
| CURSOR_SUB_AGENTS.md | OK | Règles sub-agents. |
| DOCUMENTATION_STATUS.md | OK | Ce fichier (état + historique). |
| README.md | OK | Index des docs par thème (éviter docs orphelins). |
| ENGINE_PROFILING_OPTIMIZATION.md | OK | Profilage moteur. |
| Macro_agent.md | OK | Macro agent (remplace meta_controller / macro_micro_load). |
| Deployment_Synology.md | OK | Fusion containerisation + Network (Docker, réseau, HTTPS Synology). |
| Roadmap.md | À jour | Pourcentages révisés, déploiement actif mentionné. |
| Unit_rules.md | OK | Règles d’unités. |
| USER_ACCESS_CONTROL.md | Spéc | Auth / profils. |
| Weapon_rules.md | OK | Armurerie. |
| reactive_move.md | — | Contenu intégré dans Unit_rules.md (section 10 — reactive_move) ; fichier supprimé. |

## Fusions réalisées

- **Déploiement** : Les trois docs déploiement ont été supprimés ; le résumé opérationnel est dans AI_IMPLEMENTATION.md (deployment_handlers, game_state deployment_state, deploy_unit, flow).
- **Métriques** : PPO_METRICS_TUNING_GUIDE.md supprimé ; contenu fusionné dans AI_METRICS.md (section « Quick Tuning Guide »).
- **League / curriculum** : LEAGUE_CURRICULUM_TRAINING_PLAN.md supprimé ; contenu intégré dans AI_TRAINING.md (section « Évolutions prévues : League / curriculum training »).
- **Reactive move** : reactive_move.md supprimé ; spécification intégrée dans **Unit_rules.md** (section « 10) Specification : reactive_move »), car reactive_move est une unit rule.
- **Déploiement Synology** : containerisation.md et Network.md supprimés ; contenu fusionné dans **Deployment_Synology.md** (containerisation Docker + réseau, NAT, reverse proxy, HTTPS).

## Code hors Documentation (corrigé)

- **train.py** : Référence AI_GAME_OVERVIEW.md remplacée par AI_TURN.md / AI_IMPLEMENTATION.md.
- **.cursor/rules** : shared/validation.py → shared/data_validation.py (corrigé).
