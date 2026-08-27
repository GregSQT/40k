# Documentation — Index

**Un document = un rôle, lisible dans son chemin** (architecture actée le 2026-08-27,
détail : [Chantiers/backlog/refonte_documentation.md](Chantiers/backlog/refonte_documentation.md)) :

| Zone | Rôle | Règle |
|---|---|---|
| [Reference/](Reference/) | Décrit l'état ACTUEL du système | Doit rester vrai — toute livraison qui le rend faux le corrige dans la même livraison |
| [Roadmap/](Roadmap/) | Priorités ET état des chantiers | **Source unique** — commencer par [ROADMAP_INDEX.md](Roadmap/ROADMAP_INDEX.md) |
| [Chantiers/](Chantiers/) | Specs et conceptions vivantes | Contrats permanents, specs V11, backlog |
| [Archives/](Archives/) | Historique clos | Jamais maintenu — bandeaux datés, renvois non garantis |
| [40k_rules/](40k_rules/) | Règles officielles 40K (PDF) | **Source de vérité** des règles — jamais assumer, lire le PDF |

Hors documentation technique : `Review/` (état de l'outil `scripts/review_plan.py`),
`sql/` (scripts d'amorçage), et à la racine du dépôt `Memoire_RNCP/` (certification) et
`Communication/` (pitchs).

---

## Reference/ — les références par domaine

### moteur/ — architecture du moteur de jeu

| Document | Rôle |
|---|---|
| [AI_TURN.md](Reference/moteur/AI_TURN.md) | Séquence de tour, phases, activation, matrices de conformité V11. **Contrat pour toute logique de jeu** (cité par CLAUDE.md). |
| [AI_IMPLEMENTATION.md](Reference/moteur/AI_IMPLEMENTATION.md) | Architecture des modules `engine/` : w40k_core, phase_handlers, flux, caches. |
| [stage.md](Reference/moteur/stage.md) | Système d'étages / niveaux verticaux (3D). |
| [squad.md](Reference/moteur/squad.md) | Spec fondatrice du pipeline squad multi-figurines. |
| [Distance management.md](Reference/moteur/Distance%20management.md) | Cartographie des métriques de distance backend + frontend. |
| [LoS_unique_source_of_truth.md](Reference/moteur/LoS_unique_source_of_truth.md) | Point de passage unique d'invalidation des caches LoS/positions. |
| [refactor_attack_shoot_fight1.md](Reference/moteur/refactor_attack_shoot_fight1.md) | Moteur d'allocation manuelle mutualisé tir/mêlée. |
| [Boardx10-final.md](Reference/moteur/Boardx10-final.md) | Géométrie ×10 (odd-q, primitives hex) — source de vérité de `hex_utils`. |
| [V11_board_44x60x1.md](Reference/moteur/V11_board_44x60x1.md) | Banc d'itération x1 (1 hex = 1 pouce). |
| [1_unites_hors_table_chemins_geometriques.md](Reference/moteur/1_unites_hors_table_chemins_geometriques.md) | Contrat « unités hors table filtrées de toute mesure géométrique ». |
| [V11_entity_encoder_pointer.md](Reference/moteur/V11_entity_encoder_pointer.md) | Encodeur d'entités partagé + tête pointeur (conception). |
| [move_action_space_spatial_rework.md](Reference/moteur/move_action_space_spatial_rework.md) | Action space spatial de move (grille égocentrique + tête spatiale). |
| [compute_footprint_placement_mask.md](Reference/moteur/compute_footprint_placement_mask.md) | Primitives de placement multi-hex de `hex_utils`. |
| [V11_move_build_acceleration.md](Reference/moteur/V11_move_build_acceleration.md) | Perf du noyau de pool de move : périmètre de validité, filet de validation. |
| [01_ability_embedding.md](Reference/moteur/01_ability_embedding.md) → [04_strategic_reserves.md](Reference/moteur/04_strategic_reserves.md) | Conceptions du socle capacités (embedding, CP/battle-shock, capacités de faction, réserves) — le chantier 06 s'appuie dessus. |

### training/ — entraînement et évaluation IA

| Document | Rôle |
|---|---|
| [AI_TRAINING.md](Reference/training/AI_TRAINING.md) | Référence training/tuning : pipeline `train.py`, configs, monitoring, curriculum. |
| [AI_OBSERVATION.md](Reference/training/AI_OBSERVATION.md) | Ce que l'agent observe : tenseurs d'entités + grille égocentrique (bloc de tailles verrouillé par test). |
| [AI_METRICS.md](Reference/training/AI_METRICS.md) | Interprétation des métriques TensorBoard et tuning correctif. |
| [bots_refonte_panel.md](Reference/training/bots_refonte_panel.md) | Panel de bots 6 styles : conception, protocole de mesure (§12) — la ligne de référence courante vit dans [Chantiers/backlog/panel_reference.md](Chantiers/backlog/panel_reference.md). |

Le chantier perf training (mesures + Phase 3 à lancer) est un chantier OUVERT :
[Chantiers/backlog/perf_entrainement.md](Chantiers/backlog/perf_entrainement.md).

### jeu/ — systèmes de jeu et conformité règles

| Document | Rôle |
|---|---|
| [Weapon_rules.md](Reference/jeu/Weapon_rules.md) | Système d'armes : registre des règles, effets moteur, armureries, sélection IA. |
| [Unit_rules.md](Reference/jeu/Unit_rules.md) | Règles d'unités : `unit_rules.json`, résolution, choix contextuels. |
| [Rules_Coverage.md](Reference/jeu/Rules_Coverage.md) | Audit règles officielles ↔ code (ancré sur les PDF de `40k_rules/`). |

### outils/ — configuration, tests, conformité

| Document | Rôle |
|---|---|
| [CONFIG_FILES.md](Reference/outils/CONFIG_FILES.md) | Référence des fichiers de config : weapon_rules, game_config, training, scénarios. |
| [TESTING.md](Reference/outils/TESTING.md) | Architecture des tests, conventions (dont anomalies ANOM-XXX), DoD. |
| [front_test_auto.md](Reference/outils/front_test_auto.md) | Plan des tests automatiques du front PvP (couches A/B/C). |
| [GAME_Analyzer.md](Reference/outils/GAME_Analyzer.md) | Guide d'`ai/analyzer.py` (contrôles, pièges de lecture). |
| [AI_RULES_checker.md](Reference/outils/AI_RULES_checker.md) | Guide de `scripts/check_ai_rules.py`. |
| [Hidden_action_finder.md](Reference/outils/Hidden_action_finder.md) | Guide d'`ai/hidden_action_finder.py`. |
| [Obs_channel_audit.md](Reference/outils/Obs_channel_audit.md) | Guide de `scripts/obs_channel_audit.py` (canaux d'observation). |
| [Fix_violations_guideline.md](Reference/outils/Fix_violations_guideline.md) | Workflow de correction des violations de règles détectées. |

### infra/ — déploiement, sécurité, accès

| Document | Rôle |
|---|---|
| [Deployment_Synology.md](Reference/infra/Deployment_Synology.md) | Déploiement NAS : Docker, volumes, HTTPS/DDNS, durcissement. |
| [Security.md](Reference/infra/Security.md) | Référence sécurité : failles F1–F15 (chantier clos), seuils de `security_check.sh`. |
| [USER_ACCESS_CONTROL.md](Reference/infra/USER_ACCESS_CONTROL.md) | Auth, profils, droits d'accès, protection des modes de jeu. |

---

## Roadmap/ — par quoi commencer

[ROADMAP_INDEX.md](Roadmap/ROADMAP_INDEX.md) est la **source unique de priorité et d'état** ;
un fichier par sujet (moteur, training, bot, analyzer, front, infra, capacites, doc,
v11_chemin_critique) ; historique par sujet dans [Roadmap/archives/](Roadmap/archives/).
Discipline, exceptions actées et outillage (checker + porte de fusion) : préface de l'index.

## Chantiers/ — specs vivantes

- **Contrats permanents** (jamais archivés) : [Replay.md](Chantiers/Replay.md) (contrat
  `step.log`, pipeline replay) et [analyzer_couverture.md](Chantiers/analyzer_couverture.md)
  (matrice règle → contrôle → champs de log) — relus à chaque livraison touchant le journal.
- [Bot_refactor.md](Chantiers/Bot_refactor.md) — conception du chantier bots (exception actée :
  vit à la racine).
- [v11/](Chantiers/v11/) — les 4 specs du programme V11 (agent_rework, tranches, phaseA,
  eval_strategy). **L'état fait foi dans Roadmap/, pas ici.**
- [backlog/](Chantiers/backlog/) — chantiers ouverts jamais commencés, tous atteignables depuis
  l'index roadmap (vérifié par le checker, passe 6).

## Archives/ — historique clos, jamais maintenu

- [chantiers/](Archives/chantiers/) — journaux des chantiers livrés (~45 fichiers).
- [docs/](Archives/docs/) — documents qui ne décrivent plus le code courant
  (FRONTEND_UI, Tutorial, AI_OBSERVATION_Legacy, KNOWN_ANOMALIES…).
- [prompts/](Archives/prompts/) — prompts consommés (ère Cursor comprise).

---

**Entrée recommandée** : priorités → Roadmap/ROADMAP_INDEX.md · moteur → Reference/moteur/AI_TURN.md
+ AI_IMPLEMENTATION.md · training → Reference/training/AI_TRAINING.md · armes →
Reference/jeu/Weapon_rules.md · règles officielles → 40k_rules/.
