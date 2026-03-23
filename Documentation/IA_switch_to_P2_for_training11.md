# IA switch seat training/eval (P1, P2, random) - version unifiee recommandee

## Objectif

Permettre un pipeline RL fiable avec siege agent configurable:

- `p1`: agent toujours joueur 1
- `p2`: agent toujours joueur 2
- `random`: agent alterne P1/P2 par episode

Sans biais de perspective (reward, metrics, eval, observation, action-mask), avec validation reproductible.

---

## Resume executif

Le switch de siege n'est fiable que si on traite toute la pipeline:

- seat explicite par episode
- wrappers seat-aware
- reward/metrics/eval agent-relatifs
- observation + action-mask invariants

La migration assets role-based (`agent`/`opponent`) est utile, mais separee et optionnelle.

---

## Etat actuel (facts)

### Coherent cote PvE runtime

- `engine/w40k_core.py`: IA runtime PvE executee en P2.
- `services/api_server.py`: `player_types` coherent avec PvE.
- `engine/pve_controller.py`: inference deterministic en place.

### Encore oriente P1 cote training/eval

- Hypotheses `winner == 1` dans training/eval/metrics.
- `controlled_player` encore biaise P1 dans certaines branches.
- `BotControlledEnv` structure autour agent=P1 / bot=P2.
- Certaines features observation restent absolues (P1-P2) et non agent-relatives.

---

## Contrat cible (strict)

## 1) Seat explicite

Champ obligatoire:

- `agent_seat_mode`: `"p1" | "p2" | "random"`

A chaque reset episode:

- `agent_player` in `{1,2}`
- `opponent_player` = autre joueur
- persistance dans `info`/state episode

Interdit sur chemins critiques:

- fallback implicite (`get(..., 1)`)
- valeur absente/invalide silencieuse

## 2) Random mode reproductible (vec env)

Regles:

- assignment par episode, jamais par step
- tirage independant par sous-env
- seed deterministic par `(global_seed, env_rank, episode_index)`
- en `--append`: `episode_index` reprend a partir du compteur global

Formule de reference (exemple):

- `seat_rng_seed = hash32(f"{global_seed}:{env_rank}:{episode_index}")`
- `agent_player = 1` si `seat_rng_seed % 2 == 0`, sinon `2`

Audit obligatoire:

- `%episodes_P1`, `%episodes_P2`
- `%timesteps_P1`, `%timesteps_P2`

Seuils minimaux:

- episodes: ecart absolu `<= 5%` sur fenetre >= `2000` episodes
- timesteps: ecart absolu `<= 10%` sur fenetre >= `2000` episodes

## 3) Logique agent-relative partout

Tout calcul sensible au camp doit utiliser `agent_player`:

- reward terminale/actionnelle
- win/loss/draw metrics
- eval bots
- features globales d'observation

## 4) Invariance observation + action-mask

- semantique action-space identique pour l'agent quel que soit seat
- action-mask valide/coherent en P1 et P2
- pas d'inversion de sens des indices d'action

---

## Verrous critiques (obligatoires)

## A) Source de verite unique `agent_player`

- `engine.config["controlled_player"]` est la seule source runtime.
- ecriture autorisee uniquement au reset episode.
- ecriture hors reset interdite (assert debug).

No-Go:

- toute branche critique qui rederive un `agent_player` local divergent.

## B) Versionnement observation/checkpoint

- toute modification semantique observation => bump `obs_schema_version`.
- checkpoint `obs_schema_version=X` evaluable uniquement avec `X`.
- mismatch schema => erreur explicite, pas de fallback.

No-Go:

- ancien checkpoint evaluable silencieusement avec schema different.

## C) Invariance action-mask testable

Sur etats miroirs P1/P2:

- cardinalite des actions valides equivalente
- actions critiques (WAIT/SHOOT/CHARGE/FIGHT) gardent le meme sens cote agent
- checks debug explicites en cas de mismatch

No-Go:

- une action valide change de signification selon le seat.

---

## Plan d'implementation (PR par PR)

## PR1 - Seat infrastructure + wrappers (bloquant)

Perimetre:

- `ai/train.py`
- `ai/bot_evaluation.py`
- `ai/env_wrappers.py`
- `engine/w40k_core.py` (points train/eval lies a `controlled_player`)

Contenu:

- ajouter `agent_seat_mode` + validation stricte
- resoudre `agent_player/opponent_player` par episode
- propager au wrapper train/eval
- remplacer hardcodes wrapper `current_player == 2` par `current_player == bot_player`
- logger `agent_player` par episode

DoD PR1:

- smoke train OK en `p1`, `p2`, `random` (>= 500 episodes par mode)
- pas de crash/infinite loop wrappers
- distribution random episodes/timesteps dans la tolerance

No-Go PR1:

- hardcode bot=P2 residuel dans wrappers critiques

## PR2 - Reward + metrics + eval (integrite des signaux)

Perimetre:

- `engine/reward_calculator.py`
- `ai/metrics_tracker.py`
- `ai/training_callbacks.py`
- `ai/bot_evaluation.py`
- scripts d'analyse critiques (`ai/analyzer.py` si necessaire)

Contenu:

- remplacer `winner == 1` par `winner == agent_player`
- aligner rewards terminales win/lose/draw sur `controlled_player` effectif
- interdire `winner == 1/2` hors legacy explicitement versionne
- ajouter metriques par side:
  - `winrate_agent_p1`
  - `winrate_agent_p2`
  - `winrate_global`
- versionner les tags metriques (`_seataware_v2`)

DoD PR2:

- benchmark fixe: compteurs wins/losses corrects en `p1` et `p2`
- TensorBoard: metriques side-aware presentes
- zero fallback implicite critique seat

No-Go PR2:

- courbes qui changent de sens selon seat
- mismatch winner engine vs compteur eval

## PR3 - Observation + action-mask invariance (conditionnel)

Condition d'entree:

- PR3 ne demarre que si, apres PR2, `WR(P2)` reste sous baseline cible de > `10 points`.

Perimetre:

- builders observation
- action decoder / masque / checks debug

Contenu:

- convertir features absolues en agent-relatives (`ally - enemy`)
- introduire `obs_schema_version`
- hard fail sur mismatch checkpoint/schema
- tests miroirs P1/P2 pour action-mask

DoD PR3:

- tests miroir sans inversion semantique
- pas de regression throughput training > `10%` vs PR2

No-Go PR3:

- feature cle change de sens entre P1/P2
- action-mask invalide sur un seat

## PR4 - Assets role-based (optionnel)

Perimetre:

- scenarios/rosters + resolver de roles

Contenu:

- introduire `side: "agent" | "opponent"`
- mapping role -> player au reset selon seat
- compat transitoire ancien + nouveau format

DoD PR4:

- un meme asset tourne en `p1`, `p2`, `random`
- aucune regression sur benchmark PR2/PR3

No-Go PR4:

- rupture backward compatibility non assumee

---

## Benchmark de reference (fige, obligatoire)

Utiliser le meme benchmark pour toutes les PR:

- `seed_set`: 5 seeds fixes (versionnees)
- `scenario_set`: liste fixe holdout + subset training
- `episodes_eval`: minimum 500 par condition
- `deterministic`: fixe `true` pour comparaisons primaires

Reporting minimal:

- `WR(P1)`, `WR(P2)`, `WR(global)`
- `N_episodes` exact
- `N_timesteps` exact
- diff absolue vs baseline

Regle de promotion:

- `WR(P2)` +>= `5 points` vs baseline PR0
- `WR(P1)` ne baisse pas de plus de `5 points`
- aucun No-Go actif

---

## Ordre de merge et release

Ordre strict:

1. PR1
2. PR2
3. PR3 (si gate)
4. PR4 (optionnel)

Regles:

- pas de merge PR(n+1) tant que DoD/No-Go PR(n) non valides
- conserver artefacts benchmark par PR (json + logs)

---

## Checklist finale (post-PR2 minimum)

- `agent_seat_mode` supporte `p1|p2|random` en train + eval
- aucune hypothese critique `winner == 1` residuelle
- metriques side-aware versionnees et visibles
- random mode reproductible + distribution episodes/timesteps conforme
- eval cross-seat reproductible sur benchmark fixe

---

## Conclusion

Le minimum robuste est PR1+PR2.
PR3 est conditionnel (data-driven).
PR4 est optionnel (qualite assets long terme).

Cette sequence minimise les regressions et permet de valider factuellement l'impact sur `WR(P2)`.

