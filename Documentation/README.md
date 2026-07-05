# Documentation — Index

Index des documents `Documentation/`. Statut de chaque doc : voir **[Documentation_audit.md](Documentation_audit.md)** (audit croisé code, 2026-07-05).

Les plans d'implémentation sont classés dans `Implémentation/Implémenté/` (livrés) et `Implémentation/A_faire/` (backlog).

---

## Architecture moteur et règles de tour

| Document | Rôle |
|----------|------|
| **[AI_TURN.md](AI_TURN.md)** | Règles de tour, phases, séquence d’activation, tracking, contrat de codage (V11). **Référence pour toute logique de jeu.** |
| **[AI_IMPLEMENTATION.md](AI_IMPLEMENTATION.md)** | Architecture du moteur : modules (`w40k_core`, phase_handlers, observation, reward, action_decoder), flux, caches. |

**Voir aussi** : Weapon_rules.md, Unit_rules.md, CONFIG_FILES.md, KNOWN_ANOMALIES.md.

---

## Entraînement et tuning

| Document | Rôle |
|----------|------|
| **[AI_TRAINING.md](AI_TRAINING.md)** | Référence unique training/tuning : pipeline (train.py, env, wrappers), configs, monitoring, bots, anti-overfitting. |
| **[AI_METRICS.md](AI_METRICS.md)** | Métriques et tuning : guide rapide (0_critical, matrice → paramètres) + analyse experte. |
| **[AI_OBSERVATION.md](AI_OBSERVATION.md)** | Système d’observation (vecteur 357 floats, asymétrie, intégration training). |
| **[self-play_organization32.md](self-play_organization32.md)** | Organisation self-play (ratio progressif, snapshots). |

---

## Systèmes de jeu et référence métier

| Document | Rôle |
|----------|------|
| **[FRONTEND_UI.md](FRONTEND_UI.md)** | UI frontend : LoS hex-native, couvert, tooltips, preview de tir. |
| **[Weapon_rules.md](Weapon_rules.md)** | Système d’armes : armurerie TS, règles, sélection IA, backend/frontend. |
| **[Unit_rules.md](Unit_rules.md)** | Règles d’unités : `unit_rules.json`, résolution, choix contextuels (dont reactive_move). |
| **[Distance management.md](Distance%20management.md)** | Audit des calculs de distance (hex vs euclidien). |
| **[compute_footprint_placement_mask.md](compute_footprint_placement_mask.md)** | Référence de la fonction de masque d'empreinte. |
| **[Endless_duty.md](Endless_duty.md)** | Spec du mode Endless Duty. |
| **[Tutorial.md](Tutorial.md)** | Spec du tutoriel (scénarios étapes 1-3). |

---

## Configuration et outillage

| Document | Rôle |
|----------|------|
| **[CONFIG_FILES.md](CONFIG_FILES.md)** | Référence des fichiers de config : weapon_rules, game_config, training/rewards, scénarios, armurerie. |
| **[LOS_TOPOLOGY.md](LOS_TOPOLOGY.md)** | Topologie LoS précalculée (legacy boards). |
| **[TESTING.md](TESTING.md)** | Architecture des tests (`tests/unit/engine`, `tests/unit/services`). |
| **[KNOWN_ANOMALIES.md](KNOWN_ANOMALIES.md)** | Registre des anomalies connues et de leur suivi. |
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

| Dossier | Contenu |
|---------|---------|
| **[Implémentation/Implémenté/](Impl%C3%A9mentation/Impl%C3%A9ment%C3%A9/)** | Plans/specs de features livrées (fight V11, board ×10, rosters, command phase, déploiement…). |
| **[Implémentation/A_faire/](Impl%C3%A9mentation/A_faire/)** | Backlog : MCTS, migration PostgreSQL, squad PR4, accélérations 10x restantes. |

---

## Divers

- **[Memoire/](Memoire/)** : mémoire académique RNCP/CDA (livrables de certification, hors périmètre technique).
- **_Pitch_GW.md**, **GITHUB_PROFILE_README.md** : marketing / vision.
- **40k_rules/** : PDF des règles officielles 40K — **source de vérité**.

---

**Entrée recommandée** : moteur → AI_TURN.md + AI_IMPLEMENTATION.md ; training → AI_TRAINING.md ; armes → Weapon_rules.md.
