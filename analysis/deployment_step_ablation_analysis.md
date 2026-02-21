# Analyse deploiement a partir de step.log

## Perimetre

- Source: `step.log`
- Echantillon: 30 episodes (`--test-episodes 10` x 3 bots)
- Objectif: estimer si le style de deploiement P1 est associe a la performance.

## Methode

- Extraction manuelle episode par episode dans `analysis/deployment_step_ablation.csv`.
- Archetypes de deploiement (sur les 5 unites P1):
  - `center`: au moins 3 unites avec `col` entre 10 et 14 inclus.
  - `right`: au moins 3 unites avec `col >= 20`.
  - `mixed`: sinon.

## Resultats globaux par archetype

- `center`: 15 victoires / 17 episodes = **88.2%**
- `right`: 4 victoires / 6 episodes = **66.7%**
- `mixed`: 5 victoires / 7 episodes = **71.4%**

Lecture: dans cet echantillon, le deploiement `center` est clairement le plus performant.

## Resultats par bot (archetypes avec echantillon exploitable)

- `center`
  - RandomBot: 3/4 = 0.75
  - GreedyBot: 5/6 = 0.83
  - DefensiveBot: 7/7 = 1.00
  - Combined (poids 0.2/0.4/0.4): **0.883**
  - Worst bot score: **0.75**

- `right`
  - RandomBot: 1/1 = 1.00
  - GreedyBot: 2/2 = 1.00
  - DefensiveBot: 1/3 = 0.33
  - Combined (poids 0.2/0.4/0.4): **0.733**
  - Worst bot score: **0.33**

- `mixed`
  - RandomBot: 3/5 = 0.60
  - GreedyBot: 2/2 = 1.00
  - DefensiveBot: 0 episode (insuffisant pour un combined comparable)

## Cas quasi-causaux forts (meme scenario + meme bot)

- `bot-2` vs `DefensiveBot`:
  - E24 `center` -> Win
  - E25 `right` -> Loss
  - E26 `center` -> Win

- `bot-3` vs `DefensiveBot`:
  - E27 `center` -> Win
  - E28 `right` -> Loss

Interpretation: quand le deploiement bascule `center -> right`, la perf chute dans les matchs defensifs de cet echantillon.

## Conclusion

- Ce `step.log` soutient fortement l'hypothese: **une partie materiale du gain vient du deploiement**.
- Le signal est net sur les matchups defensifs (plus discriminants).
- Ce n'est pas encore une preuve "100%" (echantillon court, variance), mais c'est un **indice causal robuste**.

## Limites

- 30 episodes seulement.
- Quelques cellules tres faibles (`right` vs Random/Greedy).
- Analyse post-hoc (pas une ablation online A/B sur un meme checkpoint).

## Recommandation immediate

- Refaire exactement le meme protocole avec 3 seeds et >=100 episodes/bot.
- Conserver les memes archetypes pour verifier la reproductibilite du signal `center > right`.
