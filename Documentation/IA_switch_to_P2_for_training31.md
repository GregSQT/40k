# IA switch seat training/eval (P1, P2, random) - v31 master

## Objectif

Permettre un pipeline RL fiable avec seat agent configurable:

- `p1`: agent toujours joueur 1
- `p2`: agent toujours joueur 2
- `random`: agent alterne P1/P2 par episode

Sans biais de perspective (reward, metrics, eval, observation, action-mask), avec validation reproductible.

---

## Decision de reference

Cette version est la base d'implementation recommandee:

- structure d'execution orientee PR (comme v1)
- verrous critiques anti-regressions silencieuses (v3)

---

## Contrat cible (strict)

## 1) Seat explicite

Champ obligatoire:

- `agent_seat_mode`: `"p1" | "p2" | "random"`

Resolution a chaque reset d'episode:

- `controlled_player` in `{1,2}`
- `opponent_player` = autre joueur
- persister `controlled_player` et `opponent_player` dans `info/state episode`

## 2) Single source of truth (bloquant)

- `engine.config["controlled_player"]` est la **seule** source de verite runtime.
- Ecriture autorisee uniquement a l'initialisation d'episode.
- Lecture obligatoire dans wrappers, reward, metrics, eval.
- Interdit: derivation locale divergente de `controlled_player`.

## 3) Interdits (chemins critiques)

- fallback implicite (`get(..., 1)`) pour seat/controlled player
- valeur absente/invalide silencieuse
- comparaison hardcodee `winner == 1` ou `winner == 2`

---

## Random mode robuste PPO

Regles:

- assignment par episode (jamais par step)
- tirage independant par sous-env vectorise
- seed deterministe par `(global_seed, env_rank, episode_index)`

Audit obligatoire:

- `%episodes_agent_p1`, `%episodes_agent_p2`
- `%timesteps_agent_p1`, `%timesteps_agent_p2`

Seuils minimaux:

- ecart episodes <= 5%
- ecart timesteps <= 10%
- fenetre d'audit >= 2000 episodes

---

## Observation + checkpoint compatibility

## Regle schema

- Toute modif semantique de feature impose bump `obs_schema_version`
  - ex: `v1` -> `v2_seat_aware`

## Regle checkpoint

- Un checkpoint n'est eval/train-compatible qu'avec le meme `obs_schema_version`.
- Mismatch schema => erreur explicite.
- Aucun fallback silencieux.

---

## Invariance action-mask (testable)

Doit etre validee sur etats miroir P1/P2:

1. meme cardinalite des actions valides
2. meme sens des actions critiques (WAIT, SHOOT slots, CHARGE/FIGHT)
3. mapping d'indices documente si remapping requis
4. assertions debug explicites en cas de mismatch

---

## Plan d'implementation (PR par PR)

## PR1 - Seat infra + wrappers (bloquant)

Perimetre:

- `ai/train.py`
- `ai/bot_evaluation.py`
- `ai/env_wrappers.py`
- `engine/w40k_core.py` (points lies a `controlled_player`)

Contenu:

- ajouter `agent_seat_mode` + validation stricte
- resoudre `controlled_player/opponent_player` par episode
- ecrire `controlled_player` uniquement au reset
- remplacer hardcodes wrapper `current_player == 2` par `current_player == bot_player`
- logger side episode (`controlled_player`)

DoD PR1:

- smoke train OK en `p1`, `p2`, `random` (200-500 episodes par mode, sans crash)
- pas de boucle infinie wrapper
- distribution random visible (episodes + timesteps)
- integrite "single source of truth" verifiee

No-Go PR1:

- hardcode bot=P2 residuel
- ecriture `controlled_player` hors reset

## PR2 - Reward + metrics + eval (integrite des signaux)

Perimetre:

- `engine/reward_calculator.py`
- `ai/metrics_tracker.py`
- `ai/training_callbacks.py`
- `ai/bot_evaluation.py`
- scripts d'analyse critiques (`ai/analyzer.py` si necessaire)

Contenu:

- remplacer `winner == 1` par `winner == controlled_player`
- aligner rewards terminales win/lose/draw sur `controlled_player`
- ajouter metriques:
  - `seat_aware/winrate_agent_p1`
  - `seat_aware/winrate_agent_p2`
  - `seat_aware/winrate_global`
- versionner tags metriques (coexistence old/new sur 1 cycle)
- retirer fallback implicite critique seat

Regle de nommage metriques:

- toutes les nouvelles metriques seat-aware utilisent le prefixe unique `seat_aware/`
- pas de variante parallele (`seataware/`, `seatAware/`, etc.)

Convention de versionnage metriques (obligatoire):

- nouveaux tags sous prefixe `seat_aware/`
- conserver les tags historiques pendant 1 cycle de release
- ajouter dans la PR une table de mapping `old_tag -> new_tag`

Plan de retrait:

- release N: old + new
- release N+1: old tags marques deprecated
- release N+2: suppression des old tags

DoD PR2:

- benchmark fixe: compteurs resultats corrects en `p1` et `p2`
- TensorBoard side-aware coherent
- zero fallback implicite critique

No-Go PR2:

- courbes qui changent de sens selon seat
- mismatch winner engine vs compteur eval

## PR2.5 - Gate mini obs/mask (obligatoire)

But: eviter un bug semantique cache avant PR3.

Checks minimum:

- au moins 50 etats miroir (dataset fixe) valident cardinalite + sens actions critiques
- verifier une feature globale critique en agent-relatif (ou confirmer inchangee)

Si echec: corriger avant PR3.

## PR3 - Observation/action-mask invariance (conditionnel)

Condition d'entree:

- si apres PR2, `WR(P2)` reste inferieur a la baseline cible de > 10 points
  **ou** si PR2.5 detecte un mismatch semantique.

Contenu:

- convertir features absolues en agent-relatives (`ally - enemy`)
- introduire `obs_schema_version`
- garde-fou checkpoint sur mismatch schema
- batterie de checks miroir action-mask

DoD PR3:

- tests miroir sans inversion semantique
- compatibilite checkpoint protegee par version
- pas de regression throughput > 10% vs PR2

No-Go PR3:

- une action valide change de signification entre P1 et P2
- action-mask invalide sur un des seats
- checkpoint evaluable avec `obs_schema_version` mismatch sans erreur explicite

## PR4 - Assets role-based (optionnel)

Contenu:

- introduire `side: "agent" | "opponent"` dans scenarios/rosters
- mapping role -> player au reset selon seat
- compat transitoire ancien format + nouveau format

DoD PR4:

- un meme asset tourne en `p1`, `p2`, `random`
- pas de regression sur benchmark PR2/PR3

No-Go PR4:

- rupture backward compatibility non assumee
- assets role-based non resolus de maniere deterministe au reset

---

## Benchmark de reference (obligatoire)

Fixer une matrice stable pour toutes les PR:

- 5 seeds fixes (versionnees)
- set scenarios fixe (holdout + subset training)
- `episodes_eval >= 500` par condition
- inference deterministe fixe pour comparaisons primaires

Reporting minimum:

- `WR(P1)`, `WR(P2)`, `WR(global)`
- `N_episodes` par condition
- `%episodes` et `%timesteps` par side en mode random
- diff absolue vs baseline
- version des tags metriques utilisee (`legacy`, `seat_aware`, ou mix)

---

## Go / No-Go final

Go si:

- `WR(P2)` progresse d'au moins +5 points vs baseline PR0 figee
- `WR(P1)` ne baisse pas de plus de 5 points vs baseline PR0 figee
- aucun No-Go actif
- metriques side-aware lisibles et coherentes
- version obs/checkpoint correctement enforcee

Sinon:

- stop, corriger, revalider sur benchmark fixe.

---

## Strategie merge/release

Ordre strict:

1. PR1
2. PR2
3. PR3 (si gate)
4. PR4 (optionnel)

Regles:

- ne pas merge PR(n+1) tant que DoD/No-Go PR(n) ne sont pas valides
- conserver les artefacts benchmark par PR (json + logs)
- garder la meme matrice benchmark entre PR pour comparaisons fiables

---

## Scope control

- API PvE/UI PvE: pas de refonte dans ce ticket
- gameplay hors sujet: non modifie
- priorite: fiabiliser training/eval multi-seat avec risques maitrises

---

## Conclusion

Le minimum robuste est:

- PR1 + PR2 + PR2.5

PR3 est data-driven mais souvent necessaire si la semantique observation/action-mask reste orientee P1.
PR4 est une dette assets utile mais optionnelle a court terme.
