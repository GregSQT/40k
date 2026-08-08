# Documentation — Index

Index des documents `Documentation/`. Statut de chaque doc : voir **[Documentation_audit.md](Documentation_audit.md)** (audit croisé code, 2026-07-05).

Les plans d'implémentation sont classés dans `Implémentation/Implémenté/` (livrés) et `Implémentation/A_faire/` (backlog).

---

## Architecture moteur et règles de tour

| Document | Rôle |
|----------|------|
| **[AI_TURN.md](AI_TURN.md)** | Règles de tour, phases, séquence d’activation, tracking, contrat de codage (V11). **Référence pour toute logique de jeu.** |
| **[AI_IMPLEMENTATION.md](AI_IMPLEMENTATION.md)** | Architecture du moteur : modules (`w40k_core`, phase_handlers, observation, reward, action_decoder), flux, caches. |

**Voir aussi** : Weapon_rules.md, Unit_rules.md, CONFIG_FILES.md, [Old/KNOWN_ANOMALIES.md](Old/KNOWN_ANOMALIES.md) (archivé).

---

## Entraînement et tuning

| Document | Rôle |
|----------|------|
| **[AI_TRAINING.md](AI_TRAINING.md)** | Référence unique training/tuning : pipeline (train.py, env, wrappers), configs, monitoring, bots, anti-overfitting. |
| **[AI_METRICS.md](AI_METRICS.md)** | Métriques et tuning : guide rapide (00_critical, matrice → paramètres) + analyse experte. |
| **[AI_OBSERVATION.md](AI_OBSERVATION.md)** | Ce que l’agent observe : tenseurs d’entités (clés, formes, normalisation, caches) + grille égocentrique. |
| **[AI_OBSERVATION_Legacy.md](Old/AI_OBSERVATION_Legacy.md)** | Archive : pipeline mono-figurine (vecteur plat d’offsets fixes). Ne décrit PAS le code actuel. |
| **[self-play_organization32.md](self-play_organization32.md)** | Organisation self-play (ratio progressif, snapshots). |

---

## Systèmes de jeu et référence métier

| Document | Rôle |
|----------|------|
| **[Old/FRONTEND_UI.md](Old/FRONTEND_UI.md)** | ⚠️ **Archivé dans `Old/`** — UI frontend : LoS hex-native, couvert, tooltips, preview de tir. |
| **[Weapon_rules.md](Weapon_rules.md)** | Système d’armes : armurerie TS, règles, sélection IA, backend/frontend. |
| **[Unit_rules.md](Unit_rules.md)** | Règles d’unités : `unit_rules.json`, résolution, choix contextuels (dont reactive_move). |
| **[Implémentation/Implémenté/Distance management.md](Impl%C3%A9mentation/Impl%C3%A9ment%C3%A9/Distance%20management.md)** | Audit des calculs de distance (hex vs euclidien). |
| **[Implémentation/Implémenté/compute_footprint_placement_mask.md](Impl%C3%A9mentation/Impl%C3%A9ment%C3%A9/compute_footprint_placement_mask.md)** | Référence de la fonction de masque d'empreinte. |
| **[Implémentation/Implémenté/V11_pathfinding_exact.md](Impl%C3%A9mentation/Impl%C3%A9ment%C3%A9/V11_pathfinding_exact.md)** | ⚠️ **Code SUPPRIMÉ le 2026-07-28** — distance BFS exacte (troncature silencieuse, champ par source). Conservé pour la leçon de méthode et comme spec de reconstruction ; état en `§0.39`. |
| **[Endless_duty.md](Endless_duty.md)** | Spec du mode Endless Duty. |
| **[Old/Tutorial.md](Old/Tutorial.md)** | ⚠️ **Archivé dans `Old/`** — spec du tutoriel (scénarios étapes 1-3). |

---

## Configuration et outillage

| Document | Rôle |
|----------|------|
| **[CONFIG_FILES.md](CONFIG_FILES.md)** | Référence des fichiers de config : weapon_rules, game_config, training/rewards, scénarios, armurerie. |
| **[TESTING.md](TESTING.md)** | Architecture des tests (`tests/unit/engine`, `tests/unit/services`). |
| **[Old/KNOWN_ANOMALIES.md](Old/KNOWN_ANOMALIES.md)** | ⚠️ **Archivé dans `Old/`** — registre des anomalies connues et de leur suivi. |
| **[Code_Compliance/](Code_Compliance/)** | Docs des outils de conformité (analyzer, check_ai_rules, hidden_action_finder). |
| **[Prompts/](Prompts/)** | Prompts outillage réutilisables (CURSOR_SUB_AGENTS, fix_game_rules_violations). |

---

## Déploiement, infra, projet

| Document | Rôle |
|----------|------|
| **[Deployment_Synology.md](Deployment_Synology.md)** | Déploiement Synology : Docker, réseau, HTTPS, DDNS. |
| **[USER_ACCESS_CONTROL.md](USER_ACCESS_CONTROL.md)** | Auth, profils, droits d’accès. |
| **[Various/Roadmap.md](Various/Roadmap.md)** | Paliers démo, état d’avancement (doc de pilotage courant). |
| **[Various/conformite_regles.md](Various/conformite_regles.md)** | Audit règles ↔ code (courant). |

---

## Plans d'implémentation

**Règle de classement — trois emplacements, un seul critère : l'ÉTAT du chantier.**
`Implémentation/` (racine) = chantier **vivant**, on y travaille · `Implémentation/Implémenté/` =
**livré**, y compris avec des résidus nommés · `Implémentation/A_faire/` = **backlog**, rien
n'est commencé. Un document qui n'est plus dans le bon dossier ment sur l'état du projet à qui
lit l'arborescence : le déplacer fait partie de la clôture du chantier.
*(Rangement du 2026-08-08 : 6 documents étaient au mauvais endroit — 4 chantiers livrés traînaient
en racine ou en backlog, 1 backlog jamais commencé occupait la racine.)*

### Chantiers V11 VIVANTS (racine `Implémentation/`)

| Document | Rôle | État |
|----------|------|------|
| **[Implémentation/V11_agent_rework.md](Impl%C3%A9mentation/V11_agent_rework.md)** | **Document de pilotage du chantier V11.** État ouvert (§0), pièges et leçons de méthode canoniques (§0bis), concept d'ancre (§1bis), tranches T1→T7 (§5), Phase A' (§9), stratégie d'entraînement/évaluation (§10), historique résolu intégral (§0hist, en fin de document). | 🟠 actif — **5 entrées ouvertes** au 2026-08-08 (§0.67, §0.59, §0.48, §0.47, §0.19) ; son §0 est à jour du code (`obs_size` 16659, `TOTAL_ACTION_SIZE` 1139, 7 têtes pointeur — revérifié par exécution) |
| **[Implémentation/V11_tranches.md](Impl%C3%A9mentation/V11_tranches.md)** | La **spec** V11 : objectif, concept d'ancre, ruptures R1→R8, tranches T1→T7 + Phase B, critères d'acceptation. | 🟠 T1→T5 faits ; **T6 partiel**, **T7 en attente**, **Phase B non commencée** (aucun `level` dans l'observation, vérifié le 2026-08-08) |
| **[Implémentation/V11_phaseA.md](Impl%C3%A9mentation/V11_phaseA.md)** | Phase A' — donner à l'agent chaque décision que les règles laissent au joueur (P1→P5). | 🟠 P1, P2, P3-0/1/2/3 livrés ; **P3-4→8, P4, P5 ouverts** (3 types de décision sur 8 slots, vérifié le 2026-08-08) |
| **[Implémentation/V11_eval_strategy.md](Impl%C3%A9mentation/V11_eval_strategy.md)** | Stratégie d'entraînement et d'évaluation (§10) : rosters, progression d'adversaires, holdout, critère de succès. | 🟢 décisions actées ; §10.4 et §10.5 **câblés et vérifiés dans le code** (2026-08-08) |
| **[Implémentation/Replay.md](Impl%C3%A9mentation/Replay.md)** | Replay : pipeline, contrat du `step.log`, registre des chantiers replay. | 🟠 A/C/D faits ; **résidu B ouvert** — `useEngineAPI.ts` porte encore les branches de sous-phase fight V10 (vérifié le 2026-08-08) |

### Livrés récemment (`Implémentation/Implémenté/`) — avec leurs résidus nommés

| Document | Rôle | État |
|----------|------|------|
| **[V11_entity_encoder_pointer.md](Impl%C3%A9mentation/Impl%C3%A9ment%C3%A9/V11_entity_encoder_pointer.md)** | Encodeur d'entités partagé + tête pointeur (conception et journal de `§0.30`). | ✅ livré, **archivé le 2026-08-08** — ⚠️ ses chiffres de dimensionnement sont datés, relire `obs_size` dans le code |
| **[replis_units_cache_2026-08-05.md](Impl%C3%A9mentation/Impl%C3%A9ment%C3%A9/replis_units_cache_2026-08-05.md)** | **42 replis silencieux sur `units_cache`** dans move/fight/shoot : inventaire par site et bilan par verdict. | ✅ clos, **archivé le 2026-08-08** ; reste les 26 lectures non auditées annoncées en §7 |
| **[V11_move_build_acceleration.md](Impl%C3%A9mentation/Impl%C3%A9ment%C3%A9/V11_move_build_acceleration.md)** | Perf du noyau de pool de move (`§0.22`) : livré, impasses mesurées, tâches résiduelles. | ✅ clos, **archivé le 2026-08-08** ; **T1 et T2 restent ouverts** (§5), T3 dépassé par §0.63/§0.64/§0.65 |
| **[move_action_space_spatial_rework.md](Impl%C3%A9mentation/Impl%C3%A9ment%C3%A9/move_action_space_spatial_rework.md)** | Refonte de l'action space de move : grille égocentrique + tête spatiale. | ✅ T1→T5 livrés (2026-07-18) — **sorti de `A_faire/` le 2026-08-08**, il y était classé à tort ; ⚠️ dimensions périmées |
| **[replay_per_figurine.md](Impl%C3%A9mentation/Impl%C3%A9ment%C3%A9/replay_per_figurine.md)** | Replay par figurine (segments `MODELS`/`TARGET_MODELS`). | ✅ livré — **sorti de `A_faire/` le 2026-08-08** ; réserve de validation navigateur suivie dans `Replay.md` |
| **[V11_refactor_plan.md](Impl%C3%A9mentation/Impl%C3%A9ment%C3%A9/V11_refactor_plan.md)** | Plan d'extraction de `V11_agent_rework.md` en sous-documents. | ✅ **TERMINÉ le 2026-07-28** — les 4 étapes sont exécutées (`db75417e`, `5e93fedd`, `cb77f6a6`, `5d1f1ab6`). L'ancienne mention « plan non exécuté » était fausse depuis ce jour-là |
| **[campagne_typage_et_replis_2026-07-29.md](Impl%C3%A9mentation/Impl%C3%A9ment%C3%A9/campagne_typage_et_replis_2026-07-29.md)** | Campagne « typage & replis silencieux » (57 commits) + **leçons de méthode réutilisables (§4)**, qui sont sa valeur résiduelle. | ✅ clos le 2026-08-05 ; reste §3.2 (arrêt décidé) et §3.7 |
| **[observation_deploiement.md](Impl%C3%A9mentation/Impl%C3%A9ment%C3%A9/observation_deploiement.md)** | Observation de la phase de déploiement : les 5 défauts et leurs correctifs. | ✅ clos le 2026-07-29 |

### Archives et backlog

| Dossier | Contenu |
|---------|---------|
| **[Implémentation/Implémenté/](Impl%C3%A9mentation/Impl%C3%A9ment%C3%A9/)** | Plans/specs de features livrées (fight V11, board ×10, rosters, command phase, déploiement…). |
| **[Implémentation/A_faire/](Impl%C3%A9mentation/A_faire/)** | Backlog : MCTS, migration PostgreSQL, sécurité, tests front auto, accélérations 10x, overrun 12.06. **Tête de file : [`replis_unit_by_id_2026-08-05.md`](Impl%C3%A9mentation/A_faire/replis_unit_by_id_2026-08-05.md)** — 56 replis silencieux sur le second index, rien de livré (`require_unit_by_id` a 0 hit, le lookup a **5** implémentations concurrentes, vérifié le 2026-08-08). |
| **[Old/](Old/)** | Documents archivés (FRONTEND_UI, Tutorial, KNOWN_ANOMALIES…) — ne décrivent plus le code courant. |

---

## Divers

- **[Memoire/](Memoire/)** : mémoire académique RNCP/CDA (livrables de certification, hors périmètre technique).
- **_Pitch_GW.md**, **GITHUB_PROFILE_README.md** : marketing / vision.
- **40k_rules/** : PDF des règles officielles 40K — **source de vérité**.

---

**Entrée recommandée** : moteur → AI_TURN.md + AI_IMPLEMENTATION.md ; training → AI_TRAINING.md ; armes → Weapon_rules.md.
