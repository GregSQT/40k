# Audit de la documentation

Date : 2026-07-05
Méthode : chaque document croisé avec le code réel (`engine/`, `ai/`, `services/`, `config/`, `frontend/`). Aucune supposition.
Les PDF `40k_rules/` (source de vérité officielle) ne sont pas audités : gardés d'office.

---

## 1. À supprimer / archiver (obsolète, remplacé, ou intégré)

| Fichier | Raison |
|---|---|
| AI_TURN_V10.md | Remplacé par AI_TURN.md (V11). Jamais référencé par le code. |
| DOCUMENTATION_STATUS.md | Snapshot mars 2026 périmé, liste des docs supprimés. |
| Old/Observation_fix21.md | Fix déjà appliqué (`_build_los_cache_for_observation`). |
| temp/HANDOFF_allocation_pertes_tir.md | Handoff intégré en prod, scripts jetables disparus. |
| Prompts/SHOOTING_PHASE_FIX_PROMPT.md | Cible du code désormais DEPRECATED. |
| TODO/ENGINE_PROFILING_OPTIMIZATION.md | Guide de méthode py-spy, l'outillage existe déjà. |
| TODO/Macro_agent.md | Fichiers d'implémentation cités absents, cible MCTS-macro non faite. |
| Endless_duty.pdf | Doublon plus ancien du .md. |

## 2. À rafraîchir (base utile mais infos fausses/périmées)

| Fichier | Correction nécessaire |
|---|---|
| README.md | Liens morts vers docs supprimés + omet des docs présents. |
| CONFIG_FILES.md | Chemin `config/scenarios/` inexistant, ancien nom d'agent. |
| AI_OBSERVATION.md | Rédigé autour de 355 floats, le code impose 357. |
| LOS_TOPOLOGY.md | Builder `los_topology_builder.py` disparu, cover refondu. |
| phase_fight_v11.md / x1.md | Header « non implémenté » périmé — en fait codés. |
| Distance management.md, macro_intent.md, AI_METRICS.md, self-play_organization32.md | Justes mais léger décalage (roster bots élargi, 357, snapshot unique). |

## 3. Implémentés — le doc reflète le code (référence vivante à garder)

- **Refactor combat (terminé côté code)** : phase_fight_v11.md, refactor_attack_shoot_fight1.md, consolidation_plan.md, desperate_escape.md, cover11.md
- **FIGHT_RESOLVER_CONVERGENCE.md** : convergence code faite, **reste ouvert §6** (re-validation training).
- **Board ×10 / spatial** : x1.md, Boardx10-final.md, Boardx10-audit.md, Distance_functions.md
- **Pipeline IA** : AI_TRAINING.md, ANALYZER_REFACTORING.md, macro_intent.md, AI_IMPLEMENTATION.md
- **Features moteur** : COMMAND_PHASE_IMPLEMENTATION.md, DEPLOYMENT_MODE_IMPLEMENTATION1.md, ROSTER_REFACTOR_* (3 fichiers), 10x_move_preview_form.md, 10x_shoot_LoS_shape.md
- **Infra** : FRONTEND_UI.md, USER_ACCESS_CONTROL.md, Deployment_Synology.md, TESTING.md

## 4. TODO encore ouverts (non faits — à garder comme backlog)

- **MCTS** : MCTS_agent_implementation.md + MCTS_bot_final.md → **aucune trace code**, ni agent d'inférence ni adversaire.
- **PostgreSQL** : DB_migration_prompt.md + DB_migration33.md → jamais amorcé, SQLite toujours en place.
- **squad.md** : PR1-4 livrées, PR4 (configs/wiring/retrain) en pause.
- **10x_acceleration.md / 10x_Move_init.md** : partiels — JSON/payload faits, noyau natif + compression HTTP non faits.
- **Various/Roadmap.md** : doc de pilotage daté d'aujourd'hui, points ouverts confirmés (`end_of_turn_coherency_removal` défini jamais appelé, décision IA par-figurine absente).

## 5. Références pures à garder telles quelles

- Règles/spec : Unit_rules.md, Weapon_rules.md, KNOWN_ANOMALIES.md, compute_footprint_placement_mask.md, Tutorial.md, Endless_duty.md
- **Various/conformite_regles.md** : audit daté d'aujourd'hui, fiable (signale bug `[PILEIN-DBG]` toujours présent dans fight_handlers.py).
- Outillage actif : tout `Code_Compliance/`, `Prompts/CURSOR_SUB_AGENTS.md` + `fix_game_rules_violations.md`, `sql/create_first_admin.sql`

## 6. Hors périmètre technique (ne pas toucher)

- `Memoire/` : mémoire académique RNCP/CDA (livrables de certification).
- `_Pitch_GW.md`, `GITHUB_PROFILE_README.md` : marketing/vision.

## Points d'attention

1. `Prompts/fix_game_rules_violations.md` et `Code_Compliance/Fix_violations_guideline.md` sont quasi-doublons → consolidables.
2. `Old/ARCHITECTURE_TRAINING_TANKING_MATRIX.md` : proposition multi-agent jamais implémentée (code mono-agent CoreAgent) — à trancher (garder comme piste R&D ou archiver).
