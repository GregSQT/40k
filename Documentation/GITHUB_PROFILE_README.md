# Hi, I'm Grégory (GregSQT) 👋

<p>
  Concepteur développeur d'applications (RNCP 6) orienté <strong>Python</strong>, <strong>React/TypeScript</strong> et <strong>IA appliquée</strong>.<br/>
  I build tactical simulation software, full-stack APIs, and reinforcement learning pipelines.
</p>

<p>
  <a href="https://github.com/GregSQT">
    <img src="https://img.shields.io/badge/GitHub-GregSQT-181717?logo=github&logoColor=white" alt="GitHub" />
  </a>
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/Flask-API-000000?logo=flask&logoColor=white" alt="Flask" />
  <img src="https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black" alt="React" />
  <img src="https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white" alt="TypeScript" />
  <img src="https://img.shields.io/badge/RL-MaskablePPO-8A2BE2" alt="RL" />
</p>

---

## 🚀 Featured Project — Trazyn's Trials

**Trazyn's Trials** is a tactical Warhammer 40K web simulator with reinforcement learning AI.

### Project overview
- **Game engine** with strict phase logic: deployment, movement, shooting, charge, fight
- **Flask REST API** for auth, game control, replay, and health checks
- **React + TypeScript + PIXI** frontend for interactive hex-board gameplay
- **MaskablePPO training pipeline** with per-agent configs and model management
- **Replay and audit tooling** (`step.log`, analyzer, hidden action finder)

### Tech stack
- Backend: Python, Flask
- Frontend: React, TypeScript, Vite, PIXI
- AI: Stable-Baselines3 + sb3-contrib (MaskablePPO)
- Data/config: SQLite (`users.db`), JSON-based rules/scenarios/configs
- Deployment: Docker Compose + Synology HTTPS reverse proxy

### Repository
👉 [`GregSQT/40k`](https://github.com/GregSQT/40k)

---

## 🧩 What I focus on

- Designing robust backends with explicit validation and clear contracts
- Building simulation engines with deterministic rules and traceability
- Shipping usable frontends for complex domain logic
- Training and evaluating RL agents in constrained action spaces

---

## 📚 Current documentation highlights

- `AI_IMPLEMENTATION.md` — engine architecture and compliance rules
- `AI_TRAINING.md` — training pipeline, seat-aware setup, tuning
- `FRONTEND_UI.md` — LoS, cover, tooltips, shooting previews
- `USER_ACCESS_CONTROL.md` — auth, profiles, permissions
- `Deployment_Synology.md` — container deployment and HTTPS setup

---

## 📫 Contact

- GitHub: [@GregSQT](https://github.com/GregSQT)

<!--
How to use this as your GitHub profile README:
1) Create a public repository named exactly: GregSQT
2) Copy this content into GregSQT/README.md
3) Commit and push
-->

