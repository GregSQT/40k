# IA switch seat training/eval (P1, P2, random) - v4 unifiee

## Objectif

Permettre un pipeline RL fiable avec siege agent configurable:

- `p1`: agent toujours joueur 1
- `p2`: agent toujours joueur 2
- `random`: agent alterne P1/P2 par episode

Sans biais de perspective (reward, metrics, eval, observation, action-mask), avec validation reproductible.

---

## Etat actuel (facts)

### Deja coherent cote PvE runtime

- `engine/w40k_core.py`: IA runtime PvE executee en P2.
- `services/api_server.py`: `player_types` coherent avec PvE.
- `engine/pve_controller.py`: inference deterministic en place.

### Encore oriente P1 cote training/eval

- Hypotheses `winner == 1` dans training/eval/metrics.
- `controlled_player` biaise P1 dans certaines branches.
- `BotControlledEnv` structure autour agent=P1 / bot=P2.
- Certaines features observation sont absolues (`P1-P2`) et pas agent-relatives.

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

## 2) Source de verite unique

- `engine.config["controlled_player"]` est la seule source de verite runtime.
- En mode seat-aware, cette valeur est resolue au reset puis immuable pendant l'episode.
- Ecriture autorisee uniquement au resolver de seat (debut episode).
- Toute logique reward/metrics/eval/wrappers lit cette valeur unique.

## 3) Random mode reproductible (vec env)

Regles:

- assignment par episode, jamais par step
- tirage independant par sous-env
- seed deterministic basee sur `(global_seed, env_rank, episode_index)`

Audit obligatoire:

- `%episodes_agent_p1` vs `%episodes_agent_p2`
- `%timesteps_agent_p1` vs `%timesteps_agent_p2`

Seuils:

- ecart absolu episodes <= 5% (fenetre >= 2000 episodes)
- ecart absolu timesteps <= 10% (fenetre >= 2000 episodes)

## 4) Logique agent-relative partout

Tout calcul sensible au camp doit utiliser `agent_player`/`controlled_player`:

- reward terminale/actionnelle
- metrics win/loss/draw
- eval bots
- features globales d'observation

## 5) Invariance observation + action-mask

- semantique action-space identique cote agent quel que soit seat
- action-mask valide/coherent en P1 et P2
- pas d'inversion de sens des indices d'action

Checks minimum sur etats miroirs:

1. `count_valid_actions(P1_mirror) == count_valid_actions(P2_mirror)`
2. semantique stable pour WAIT / SHOOT slots / CHARGE / FIGHT
3. mapping d'indices documente si remapping necessaire

## 6) Versionnement observation/checkpoints

- toute modification semantique des features impose un bump `obs_schema_version`
- un checkpoint entraine avec schema `X` n'est evalue qu'avec schema `X`
- mismatch schema => erreur explicite (aucun fallback silencieux)

---

## Plan d'implementation (PR par PR)

## PR1 - Seat infra + wrappers (bloquant)

Perimetre:

- `ai/train.py`
- `ai/bot_evaluation.py`
- `ai/env_wrappers.py`
- `engine/w40k_core.py` (parties train/eval liees a `controlled_player`)

Contenu:

- ajouter `agent_seat_mode` + validation stricte
- resoudre `agent_player/opponent_player` par episode
- propager au wrapper train/eval
- remplacer hardcodes `current_player == 2` par `current_player == bot_player`
- logger `agent_player` par episode
- ajouter check d'integrite "single source of truth controlled_player"

DoD PR1:

- smoke train OK en `p1`, `p2`, `random` (200-500 episodes par mode, sans crash)
- aucune boucle infinie wrapper sur les 3 modes
- distribution random visible (`%episodes`, `%timesteps`)

No-Go PR1:

- hardcode bot=P2 residuel dans wrappers critiques
- ecriture de `controlled_player` hors reset

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
- ajouter metriques par side:
  - `seat_aware/winrate_agent_p1`
  - `seat_aware/winrate_agent_p2`
  - `seat_aware/winrate_global`
- versionner/coexister les tags historiques pendant un cycle release

DoD PR2:

- benchmark fixe: compteurs wins/losses corrects en `p1` et `p2`
- TensorBoard: metriques side-aware presentes et lisibles
- zero fallback implicite critique sur seat dans train/eval/reward

No-Go PR2:

- courbes qui changent de sens selon le seat
- mismatch winner engine vs compteur eval

## PR3 - Observation/action-mask invariance (conditionnel)

Perimetre:

- builders observation
- action decoder / masque / checks debug

Gate d'entree PR3:

- PR3 ne demarre que si, apres PR2, `WR(P2)` reste inferieur a la cible de plus de 10 points sur benchmark fixe

Contenu:

- convertir features absolues en agent-relatives (`ally - enemy`)
- introduire `obs_schema_version` + garde-fous checkpoint
- verifier semantique action-space + masque sur etats miroirs

DoD PR3:

- tests miroirs passent sans inversion semantique
- eval refuse explicitement les mismatchs `obs_schema_version`
- pas de regression throughput training > 10% vs PR2

No-Go PR3:

- action valide change de signification entre P1 et P2
- action-mask invalide sur un des seats

## PR4 - Assets role-based (optionnel)

Perimetre:

- scenarios/rosters + resolver roles

Contenu:

- introduire `side: "agent" | "opponent"`
- mapping role -> player au reset selon seat
- compat transitoire ancien format + nouveau format

DoD PR4:

- un meme asset tourne en `p1`, `p2`, `random`
- aucune regression sur benchmark PR2/PR3

No-Go PR4:

- rupture backward compatibility non assumee

---

## Benchmark de reference (fige)

Utiliser le meme benchmark pour toutes les PR:

- `seed_set`: 5 seeds fixes (versionnees dans repo)
- `scenario_set`: liste fixe holdout + subset training
- `episodes_eval`: minimum 500 par condition
- `deterministic`: `true` pour comparaisons primaires

Reporting minimal:

- `WR(P1)`, `WR(P2)`, `WR(global)`
- `N_episodes` exact par condition
- diff absolue vs baseline
- `%episodes_agent_p1/p2`, `%timesteps_agent_p1/p2`

Decision de promotion:

- `WR(P2)` +>= 5 points vs baseline PR0
- `WR(P1)` ne baisse pas de plus de 5 points
- aucun critere No-Go actif

---

## Strategie de merge/release

Ordre strict:

1. PR1
2. PR2
3. PR3 (si gate)
4. PR4 (optionnel)

Regles:

- ne pas merge PR(n+1) tant que DoD/No-Go PR(n) non valides
- conserver artefacts benchmark par PR (json + logs)

---

## Checklist finale (post-PR2 minimum)

- `agent_seat_mode` supporte `p1|p2|random` en train + eval
- aucune hypothese critique `winner == 1` residuelle
- source de verite unique `controlled_player` respectee
- random mode reproductible et distribue correctement (episodes + timesteps)
- metriques side-aware visibles
- eval cross-seat reproductible sur benchmark fixe
- versionnement `obs_schema_version` actif si schema modifie

---

## Conclusion

Le minimum robuste est PR1 + PR2.
PR3 est conditionnel (data-driven).
PR4 est optionnel (qualite assets long terme).

Ce plan minimise les faux positifs PPO et les regressions silencieuses lors du switch `p1|p2|random`.
