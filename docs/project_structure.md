# Project Structure

## Overview
This is a Warhammer 40k tactical game with AI opponents, built with React/TypeScript frontend and Python AI backend.

## Directory Structure

```
wh40k-tactics/
├── frontend/                    # React/TypeScript frontend
│   ├── src/
│   │   ├── components/          # React components
│   │   ├── pages/              # Page components
│   │   ├── data/               # Game data & factories
│   │   ├── roster/             # Unit definitions
│   │   │   └── spaceMarine/    # Space Marine units
│   │   └── ai/                 # Frontend AI integration
│   ├── dist/                   # Frontend build output
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
├── ai/                         # Python AI backend
│   ├── agent.py               # AI agent implementation
│   ├── api.py                 # API endpoints
│   ├── gym40k.py             # Gymnasium environment
│   ├── model.py              # Neural network models
│   └── ...
├── tools/                      # Development tools
│   ├── backup_script.py       # Project backup utility
│   └── generate_scenario.py   # Scenario generation
├── docs/                       # Documentation
└── README.md
```

## Key Components

### Frontend (`/frontend/src/`)
- **components/**: Reusable React components (Board, UnitSelector, etc.)
- **pages/**: Main application pages (HomePage, GamePage, ReplayPage)
- **data/**: Game logic and data management
- **roster/**: Unit definitions and stats
- **ai/**: Frontend integration with AI backend

### AI Backend (`/ai/`)
- **agent.py**: Main AI agent logic
- **gym40k.py**: Gymnasium environment for training
- **api.py**: FastAPI endpoints for frontend communication
- **model.py**: Neural network architectures

### Development Tools (`/tools/`)
- **backup_script.py**: Project versioning and backup
- **generate_scenario.py**: Scenario generation utilities

## Build Commands

```bash
# Frontend development
cd frontend
npm run dev

# Frontend build
cd frontend
npm run build

# AI backend
cd ai
python api.py
```

## Path Aliases

TypeScript path aliases are configured for cleaner imports:

- `@/` → `frontend/src/`
- `@components/` → `frontend/src/components/`
- `@data/` → `frontend/src/data/`
- `@roster/` → `frontend/src/roster/`
- `@pages/` → `frontend/src/pages/`
- `@ai/` → `ai/`
