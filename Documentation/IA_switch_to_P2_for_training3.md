# IA switch seat training/eval - correctifs critiques v3

## Objectif

Completer le plan v2 avec 4 verrous indispensables pour eviter les regressions silencieuses:

1. source de verite unique pour `agent_player`
2. versionnement observation/checkpoints
3. audit random sur episodes **et** timesteps
4. definition testable de l'invariance action-mask

---

## 1) Source de verite unique `agent_player` (bloquant)

## Regle

- `engine.config["controlled_player"]` est la **seule source de verite** runtime.
- En mode seat-aware, elle est resolue au `reset` d'episode puis consideree immutable pendant l'episode.
- Toute logique training/eval/reward/metrics lit cette valeur unique.

## Regle d'ecriture

- Ecriture autorisee uniquement a l'initialisation d'episode (resolver de seat).
- Ecriture interdite ailleurs (wrappers, callbacks, analyzer, eval workers).
- En debug: assert si une ecriture hors reset est detectee.

## Critere Go/No-Go

- Go si aucun module critique ne derive un `agent_player` local divergent.
- No-Go si au moins une branche compare `winner` a une constante (`1`/`2`) au lieu de `controlled_player`.

---

## 2) Observation: versionnement explicite (compat checkpoints)

## Regle

- Toute modification semantique des features (ex: `P1-P2` -> `ally-enemy`) impose un bump de schema.
- Ajouter `obs_schema_version` (ex: `v1`, `v2_seat_aware`) expose dans metadata train/eval.

## Politique checkpoints

- Checkpoint entraine avec `obs_schema_version=X` ne doit etre evalue qu'avec `X`.
- Si mismatch schema:
  - erreur explicite en chargement/eval
  - pas de fallback silencieux

## Critere Go/No-Go

- Go si eval refuse explicitement les mismatchs de schema.
- No-Go si un ancien checkpoint peut tourner avec nouveau schema sans garde-fou explicite.

---

## 3) Mode random: audit de distribution PPO robuste

## Regle

Sur fenetre significative, auditer:

- `%episodes_agent_p1` vs `%episodes_agent_p2`
- `%timesteps_agent_p1` vs `%timesteps_agent_p2`

Pourquoi:

- 50/50 en episodes peut rester biaise en gradient si la longueur moyenne d'episode differe par side.

## Seuils minimaux

- Ecart absolu episodes <= 5%
- Ecart absolu timesteps <= 10%

## Critere Go/No-Go

- Go si les 2 seuils passent.
- No-Go si episodes OK mais timesteps hors tolerance.

---

## 4) Invariance action-mask: definition testable

## Regle

L'invariance ne doit pas rester conceptuelle; elle doit etre testee sur etats de reference miroir P1/P2.

## Checks minimum

1. cardinalite identique:
   - `count_valid_actions(P1_state_mirror) == count_valid_actions(P2_state_mirror)`
2. semantique des actions critiques stable:
   - WAIT, SHOOT slots, CHARGE/FIGHT selection gardent le meme sens cote agent
3. mapping explicite des indices:
   - table de correspondance documentee si un remapping est necessaire
4. guardrails debug:
   - assertions explicites en cas de mismatch mask/semantique

## Critere Go/No-Go

- Go si checks miroir passent sur un set d'etats representative.
- No-Go si une action valide change de signification entre P1 et P2.

---

## Additions recommandees au plan PR

## PR1 (infra seat)

- Ajouter test d'integrite "single source of truth controlled_player".

## PR2 (reward/metrics/eval)

- Interdire explicitement toute comparaison `winner == 1`/`winner == 2` hors contexte legacy versionne.

## PR3 (obs/mask)

- Introduire `obs_schema_version` + garde-fou checkpoint.
- Ajouter batterie de tests miroir action-mask.

## PR4 (assets role-based)

- Pas de merge si PR3 n'a pas valide l'invariance.

---

## Resume

Ces 4 verrous rendent le switch `p1|p2|random` exploitable en PPO sans faux positifs:

- un seul `controlled_player` autorite
- schema observation versionne
- random audite en episodes **et** timesteps
- invariance action-mask prouvee par tests
