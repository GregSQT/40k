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
| **[AI_OBSERVATION_Legacy.md](AI_OBSERVATION_Legacy.md)** | Archive : pipeline mono-figurine (vecteur plat d’offsets fixes). Ne décrit PAS le code actuel. |
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

### Chantiers V11 EN COURS (racine `Implémentation/`)

⚠️ **Ces documents n'étaient référencés nulle part dans cet index** (ajoutés le 2026-07-28) : seuls
les deux dossiers `Implémenté/` et `A_faire/` l'étaient, alors que les chantiers **vivants** sont à
la racine de `Implémentation/`.

| Document | Rôle | État |
|----------|------|------|
| **[Implémentation/V11_agent_rework.md](Impl%C3%A9mentation/V11_agent_rework.md)** | **Document de pilotage du chantier V11.** État ouvert (§0), pièges et leçons de méthode canoniques (§0bis), concept d'ancre (§1bis), tranches T1→T7 (§5), Phase A' (§9), stratégie d'entraînement/évaluation (§10), historique résolu intégral (§0hist, en fin de document). | 🟠 actif — 4 entrées ouvertes |
| **[Implémentation/V11_entity_encoder_pointer.md](Impl%C3%A9mentation/V11_entity_encoder_pointer.md)** | Encodeur d'entités partagé + tête pointeur (source de vérité de `§0.30`). | ✅ livré |
| **[Implémentation/V11_move_build_acceleration.md](Impl%C3%A9mentation/V11_move_build_acceleration.md)** | Perf du noyau de pool de move (`§0.22`) : ce qui est livré, impasses mesurées, tâches ouvertes. | ✅ clos, 3 tâches résiduelles |
| **[Implémentation/V11_refactor_plan.md](Impl%C3%A9mentation/V11_refactor_plan.md)** | Plan d'extraction de `V11_agent_rework.md` en sous-documents. | ⏸️ **plan non exécuté** ; ses numéros de ligne datent du 2026-07-21 et ne correspondent plus |
| **[Implémentation/Replay.md](Impl%C3%A9mentation/Replay.md)** | Spec du replay. | — |
| **[Implémentation/Implémenté/observation_deploiement.md](Impl%C3%A9mentation/Impl%C3%A9ment%C3%A9/observation_deploiement.md)** | Observation de la phase de déploiement : les 5 défauts et leurs correctifs (clos le 2026-07-29). | — |
| **[Implémentation/replis_units_cache_2026-08-05.md](Impl%C3%A9mentation/replis_units_cache_2026-08-05.md)** | **42 replis silencieux sur `units_cache`** dans move/fight/shoot : inventaire par site (formes A/B/C/D), méthode imposée et découpage en 3 tranches. Issu du lot charge clos le 2026-08-05 — un site sur trois n'est PAS à corriger, le tri fait partie du travail. | 🔴 **ouvert, rien de livré** — T1 (forme A, 9 sites) recommandée en premier |
| **[Implémentation/Implémenté/campagne_typage_et_replis_2026-07-29.md](Impl%C3%A9mentation/Impl%C3%A9ment%C3%A9/campagne_typage_et_replis_2026-07-29.md)** | Campagne « typage & replis silencieux » (57 commits) : replis silencieux, code mort, socle scindé, compteurs de combat, journal de tir + **leçons de méthode réutilisables (§4)**, qui sont sa valeur résiduelle. Le typage n'y était presque jamais le défaut, seulement son symptôme. | ✅ clos le 2026-08-05 ; reste §3.2 (arrêt décidé) et §3.7 (relevé `pytest --collect-only`, vérification utilisateur) |

### Archives et backlog

| Dossier | Contenu |
|---------|---------|
| **[Implémentation/Implémenté/](Impl%C3%A9mentation/Impl%C3%A9ment%C3%A9/)** | Plans/specs de features livrées (fight V11, board ×10, rosters, command phase, déploiement…). |
| **[Implémentation/A_faire/](Impl%C3%A9mentation/A_faire/)** | Backlog : MCTS, migration PostgreSQL, squad PR4, accélérations 10x restantes. |
| **[Old/](Old/)** | Documents archivés (FRONTEND_UI, Tutorial, KNOWN_ANOMALIES…) — ne décrivent plus le code courant. |

---

## Divers

- **[Memoire/](Memoire/)** : mémoire académique RNCP/CDA (livrables de certification, hors périmètre technique).
- **_Pitch_GW.md**, **GITHUB_PROFILE_README.md** : marketing / vision.
- **40k_rules/** : PDF des règles officielles 40K — **source de vérité**.

---

**Entrée recommandée** : moteur → AI_TURN.md + AI_IMPLEMENTATION.md ; training → AI_TRAINING.md ; armes → Weapon_rules.md.
