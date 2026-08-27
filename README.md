# Trazyn's Trials

<p align="center">
  <strong>Warhammer 40K Tactical Simulator with Reinforcement Learning AI</strong><br/>
  <em>Frontend React/TypeScript • Flask API • Phase-based game engine • MaskablePPO</em>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white" />
  <img alt="Flask" src="https://img.shields.io/badge/Flask-API-000000?logo=flask&logoColor=white" />
  <img alt="React" src="https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black" />
  <img alt="TypeScript" src="https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white" />
  <img alt="Vite" src="https://img.shields.io/badge/Vite-7-646CFF?logo=vite&logoColor=white" />
  <img alt="RL" src="https://img.shields.io/badge/RL-MaskablePPO-8A2BE2" />
</p>

<p align="center">
  <a href="#fran%C3%A7ais">Français</a> •
  <a href="#english">English</a>
</p>

---

## Français

### Pourquoi ce projet ?
Trazyn's Trials transforme une partie de Warhammer 40K en expérience numérique jouable en solo ou à deux :
- **PvE** contre des agents IA entraînés,
- **PvP** local/web via l'interface,
- conformité stricte aux règles métier (phases, activation, LoS, couvert),
- traçabilité complète via logs et replay.

### Ce que l'application fait

| Domaine | Capacité |
|---|---|
| 🎮 Simulation | Déploiement, mouvement, tir, charge, combat (ordre strict) |
| 🔐 Sécurité | Authentification, profils, permissions, contrôle backend (403) |
| 🌐 API REST | `auth`, `game`, `replay`, `health`, `debug` |
| 🤖 IA | Entraînement MaskablePPO, évaluation bots, modèles par agent |
| 📊 Qualité | `step.log`, analyzer, check de conformité, replay parser |
| 🚀 Déploiement | Docker Compose + reverse proxy HTTPS (Synology) |

### Illustration — Architecture logique

```mermaid
flowchart LR
    U["Utilisateur"] --> FE["Frontend React TS PIXI"]
    FE --> API["API Flask"]
    API --> ENG["Moteur W40KEngine"]
    ENG --> AI["IA RL MaskablePPO"]

    API --> AUTH["Auth et permissions"]
    API --> REPLAY["Replay et logs"]

    AUTH --> DB[("SQLite users.db")]
    ENG --> CFG["Config regles scenarios agents"]
    AI --> MODELS[("Modeles IA")]
    ENG --> LOGS[("step.log et replay")]
    AI --> LOGS
```

### Illustration — Parcours utilisateur

```mermaid
flowchart TB
    A["Auth"] --> G["Game"] --> R["Replay"]
    A --> API["API Flask"]
    G --> API
    R --> API
```

### Démarrage rapide (local)

```bash
# 1) Dépendances
pip install -r requirements.txt
npm --prefix frontend install

# 2) API Flask
python services/api_server.py

# 3) Frontend
npm --prefix frontend run dev
```

> `requirements.txt` = environnement de développement complet.
> `requirements.runtime.txt` = **verrou généré** de l'image Docker de production ; il ne s'édite
> pas à la main, sa source est `requirements.runtime.in`.
> `requirements-dev.txt` = outillage d'analyse de sécurité (`bandit`, `pip-audit`).
> `requirements-test.txt` = ce qu'il faut **en plus** du verrou pour exécuter la suite de tests
> (pytest et `tensorboard`, requis par `ai/metrics_tracker.py`). C'est ce que la CI installe.

### Analyse de sécurité

```bash
pip install -r requirements-dev.txt
./scripts/security_check.sh    # bandit + pip-audit + npm audit ; sortie non nulle si finding haut
```

Seuils, exceptions justifiées et findings connus : [Documentation/Reference/infra/Security.md](Documentation/Reference/infra/Security.md).

### Entraînement IA (exemple)

```bash
python ai/train.py --agent CoreAgent --scenario bot --new
```

### Arborescence (vue synthétique)

```text
/home/greg/40k
├── frontend/       # UI React + TypeScript + PIXI
├── services/       # API Flask
├── engine/         # Moteur (W40KEngine + phase_handlers)
├── ai/             # Training, eval, analyzer
├── config/         # Scenarios/rules/agents + users.db
├── scripts/        # Qualité, audit, déploiement
└── Documentation/  # Docs techniques et mémoire
```

### Documentation utile
- `Documentation/Reference/moteur/architecture_moteur.md`
- `Documentation/Reference/training/AI_TRAINING.md`
- `Documentation/FRONTEND_UI.md`
- `Documentation/Reference/infra/USER_ACCESS_CONTROL.md`
- `Documentation/Reference/infra/Deployment_Synology.md`

---

## English

### What is it?
Trazyn's Trials is a tactical Warhammer 40K web simulator built for:
- **PvE** against trained RL agents,
- **PvP** sessions,
- strict rule compliance (phase flow, activation, line of sight, cover),
- full traceability with logs and replay tooling.

### Key capabilities

| Area | Capability |
|---|---|
| 🎮 Simulation | Deployment, movement, shooting, charge, fight (strict order) |
| 🔐 Security | Authentication, profiles, permissions, backend 403 enforcement |
| 🌐 REST API | `auth`, `game`, `replay`, `health`, `debug` |
| 🤖 AI | MaskablePPO training, bot evaluation, per-agent model management |
| 📊 Quality | `step.log`, analyzer, compliance checks, replay parser |
| 🚀 Deployment | Docker Compose + HTTPS reverse proxy (Synology target) |

### Quick start (local)

```bash
# 1) Dependencies
pip install -r requirements.txt
npm --prefix frontend install

# 2) Flask API
python services/api_server.py

# 3) Frontend
npm --prefix frontend run dev
```

> `requirements.txt` = full development environment.
> `requirements.runtime.txt` = **generated lock** for the production Docker image; never edit it
> by hand, its source is `requirements.runtime.in`.
> `requirements-dev.txt` = security analysis tooling (`bandit`, `pip-audit`).
> `requirements-test.txt` = what the test suite needs **on top of** the lock (pytest and
> `tensorboard`, required by `ai/metrics_tracker.py`). This is what CI installs.

### Security scan

```bash
pip install -r requirements-dev.txt
./scripts/security_check.sh    # bandit + pip-audit + npm audit; non-zero exit on any high finding
```

Thresholds, written exceptions and known findings: [Documentation/Reference/infra/Security.md](Documentation/Reference/infra/Security.md).

### AI training example

```bash
python ai/train.py --agent CoreAgent --scenario bot --new
```

### Docs
- `Documentation/Reference/moteur/architecture_moteur.md`
- `Documentation/Reference/training/AI_TRAINING.md`
- `Documentation/FRONTEND_UI.md`
- `Documentation/Reference/infra/USER_ACCESS_CONTROL.md`
- `Documentation/Reference/infra/Deployment_Synology.md`

