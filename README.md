wh40k-tactics/
├── backend/
│   ├── game/
│   │   ├── core.py              # Board/unit logic (positions as (x, y))
│   │   ├── rules.py             # Move/attack/range functions
│   │   └── utils.py             # Grid/hex/continuous distance helpers
│   ├── rl/
│   │   ├── env_gym.py           # Gymnasium env (for RL, API)
│   │   └── agent.py             # RL agent loader/trainer
│   ├── api/
│   │   └── main.py              # FastAPI app (serves game state, step, reset)
│   ├── models/                  # (optional) Pydantic schemas
│   └── requirements.txt         # All backend deps
├── frontend/
│   ├── src/
│   │   ├── App.jsx              # Main React App
│   │   ├── api.js               # REST API helpers (calls FastAPI)
│   │   ├── components/
│   │   │   ├── Board.jsx        # PixiJS or react-pixi game board
│   │   │   └── UnitToken.jsx    # Unit visual representation
│   │   └── utils.js             # Coord conversion, math, etc.
│   ├── package.json
│   └── public/
│       └── index.html
└── README.md
