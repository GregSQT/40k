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

### moteur/ — architecture du moteur de jeu (9 documents, consolidés le 2026-08-28)

| Document | Rôle |
|---|---|
| [tour_de_jeu.md](Reference/moteur/tour_de_jeu.md) | Séquence du tour, arbres de décision par phase, matrices de conformité V11. **Contrat pour toute logique de jeu** (cité par CLAUDE.md). |
| [architecture_moteur.md](Reference/moteur/architecture_moteur.md) | Carte des modules `engine/`, flux d'un step et d'une action, patterns transverses et caches. |
| [geometrie_et_distances.md](Reference/moteur/geometrie_et_distances.md) | Plateau odd-q, résolutions x1/x5/x10, empreintes et socles, métriques de distance, unités hors table. |
| [verticalite.md](Reference/moteur/verticalite.md) | Étages et niveaux (3D) : occupation, mouvement vertical, engagement et LoS 3D. |
| [ligne_de_vue.md](Reference/moteur/ligne_de_vue.md) | Caches LoS et point d'invalidation unique. |
| [allocation_attaques.md](Reference/moteur/allocation_attaques.md) | Moteur d'allocation manuelle des attaques, mutualisé tir/mêlée. |
| [squad_multi_figurines.md](Reference/moteur/squad_multi_figurines.md) | Pipeline escouades multi-figurines (briques, caches, contrats par-figurine). |
| [capacites.md](Reference/moteur/capacites.md) | Socle capacités : embedding, CP/battle-shock, capacités de faction, réserves — **+ §À faire : chantier 06 Armageddon**. |
| [perf_move_pool.md](Reference/moteur/perf_move_pool.md) | Perf du noyau de pool de move : périmètre de validité, filet de validation. |

### training/ — entraînement et évaluation IA

| Document | Rôle |
|---|---|
| [entrainement.md](Reference/training/entrainement.md) | Référence training/tuning : pipeline `train.py`, configs, monitoring, curriculum. |
| [observation_et_actions.md](Reference/training/observation_et_actions.md) | Ce que l'agent observe et ce qu'il peut jouer : tenseurs d'entités, encodeur partagé + tête pointeur, grille égocentrique et tête spatiale (bloc de tailles verrouillé par test). |
| [metriques.md](Reference/training/metriques.md) | Interprétation des métriques TensorBoard et tuning correctif. |
| [V11_method_lessons.md](Reference/training/V11_method_lessons.md) | Pièges et leçons de méthode V11 (copie canonique, extraite de la spec). |
| [panel_bots.md](Reference/training/panel_bots.md) | Panel de bots 6 styles : conception, protocole de mesure (§12) et ligne de référence courante (§12.14). |

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
  l'index roadmap (vérifié par le checker, passe 6). Noms d'objet depuis la consolidation
  2026-08-28 : `endless_duty.md` (spec + état mesuré fusionnés), `migration_postgresql.md`,
  `mcts_adversaire.md`, `perf_entrainement.md`, `perf_noyau_natif_et_gzip.md`,
  `preview_tir_position_virtuelle.md`, `reactive_stratagems_overwatch_hi.md`,
  `curriculum_adversaires_etalons.md`, `panel_bots.md`, `refonte_documentation.md` ;
  le chantier 06 Armageddon vit en §À faire de
  [Reference/moteur/capacites.md](Reference/moteur/capacites.md).

## Archives/ — historique clos, jamais maintenu

- [chantiers/](Archives/chantiers/) — journaux des chantiers livrés (~45 fichiers).
- [docs/](Archives/docs/) — documents qui ne décrivent plus le code courant
  (FRONTEND_UI, Tutorial, AI_OBSERVATION_Legacy, KNOWN_ANOMALIES…).
- [prompts/](Archives/prompts/) — prompts consommés (ère Cursor comprise).

---

**Entrée recommandée** : priorités → Roadmap/ROADMAP_INDEX.md · moteur → Reference/moteur/tour_de_jeu.md
+ architecture_moteur.md · training → Reference/training/entrainement.md · armes →
Reference/jeu/Weapon_rules.md · règles officielles → 40k_rules/.
