## Macro/Micro Load Simulation

Ce document décrit l'usage du script `scripts/macro_micro_load.py` pour simuler une charge
macro/micro et mesurer la consommation CPU/RAM/reseau.

### Ce que fait le script
- Lance des episodes W40K via `W40KEngine` avec un scenario donne.
- Simule une decision **macro** en reordonnant le pool d'activation.
- Simule des actions **micro** en choisissant une action valide depuis le masque.
- Arrete un episode sur `game_over`, ou quand `max_steps_per_turn` est atteint.
- Affiche un resume: steps par episode, total steps, steps/sec.
 - Capture les metrics CPU/RAM/reseau/disque en fin d'execution.

### Comment il fonctionne
1. Charge la config (`game_config.json`) pour `max_steps_per_turn` si l'option n'est pas fournie.
2. Instancie `UnitRegistry`, puis `W40KEngine` avec les configs et scenarios.
3. A chaque step:
   - **Macro**: toutes les `N` actions micro, choisit une unite du pool et la met en tete.
   - **Micro**: recupere le masque d'action et choisit une action valide (aleatoire).
4. Repete sur `--episodes`, puis imprime le debit global.
5. A la fin, calcule les deltas:
   - CPU (temps CPU du process)
   - RAM (ru_maxrss + pic Python)
   - IO disque (read/write bytes du process)
   - Reseau (RX/TX systeme, depuis `/proc/net/dev`)

### Parametres
- `--scenario-file` (repete): scenario JSON a utiliser.
- `--controlled-agent`: agent controle (ex. `MacroController`).
- `--training-config`: nom du training config (pas le chemin).
- `--rewards-config`: nom du rewards config (pas le chemin).
- `--episodes`: nombre d'episodes.
- `--macro-player`: joueur controle par le macro (1 ou 2).
- `--macro-every-steps`: appliquer la decision macro toutes les N actions micro.
- `--macro-both`: applique la decision macro aux deux joueurs.
- `--max-steps-per-turn`: override optionnel; sinon valeur par defaut dans `config/game_config.json`.
- `--metrics-out`: ecrit un JSON des metrics (resume).

### Notes sur les metrics
- **Reseau**: mesure systeme (RX/TX total), pas par process.
- **IO disque**: lecture/ecriture du process via `/proc/self/io`.

### Valeur par defaut `max_steps_per_turn`
Le script lit `game_rules.max_steps_per_turn` depuis `config/game_config.json` si
`--max-steps-per-turn` n'est pas fourni.

### Exemple (normal)
```
python scripts/macro_micro_load.py \
  --scenario-file config/agents/MacroController/scenarios/MacroController_scenario_default.json \
  --controlled-agent MacroController \
  --training-config MacroController_training_config \
  --rewards-config MacroController_rewards_config \
  --episodes 10 \
  --macro-player 1 \
  --macro-every-steps 5
```

### Exemple (stress)
```
python scripts/macro_micro_load.py \
  --scenario-file config/agents/MacroController/scenarios/MacroController_scenario_default.json \
  --controlled-agent MacroController \
  --training-config MacroController_training_config \
  --rewards-config MacroController_rewards_config \
  --episodes 50 \
  --macro-player 1 \
  --macro-every-steps 1
```
