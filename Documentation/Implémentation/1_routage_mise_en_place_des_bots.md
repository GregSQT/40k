# Router la mise en place des bots par `_get_bot_action`

Proposé le 2026-08-04 par la revue d'altitude du chantier 04c. **Non fait — amélioration de
conception, aucun bug actif.** Le garde-fou actuel fonctionne et est verrouillé par des tests.

> **Périmètre** : `ai/env_wrappers.py` (`BotControlledEnv._get_bot_action`) et
> `ai/evaluation_bots.py` (les 7 bots). Ne touche ni le moteur, ni le masque, ni le PvP.
>
> **Principe** : nettoyer le pool d'actions UNE fois, au point de traduction masque → décision,
> au lieu de le faire dans chaque bot.
>
> **Statut (2026-08-04)** : proposition argumentée, non implémentée, non arbitrée.

---

## Le contexte

Le masque de déploiement ouvre `SQUAD_ACTION_WAIT` dès qu'une unité tient sous le plafond de 50 %
(`engine/action_decoder.py`, règle 20.01). En phase de déploiement, ce slot **n'est pas une
attente** : le jouer place l'unité **en réserves stratégiques**.

Cette surcharge d'id est **justifiée et à conserver** — elle évite d'ajouter une dimension à
l'action space, et `TOTAL_ACTION_SIZE` est gelé depuis le chantier 01. L'invariant ne peut donc
pas descendre dans le décodeur.

Conséquence : chaque bot doit écarter ce coup lui-même. Sept bots, sept occasions d'oublier.

## Ce que ça a déjà coûté

L'oubli s'est produit, et il a été **MESURÉ** au chantier 04c :

| Bot | `randomness` | Unités mises en réserves |
|---|---|---|
| TacticalBot | (repli sans branche `deployment`) | **400 / 400** |
| AdaptiveBot | 0.15 | 114 / 4000 (2,85 %) |
| ControlBot | 0.15 | 98 / 4000 (2,45 %) |
| GreedyBot | 0.15 | 93 / 4000 (2,33 %) |
| ValueTradeBot | 0.15 | 91 / 4000 (2,27 %) |
| TacticalBot | 0.05 | 39 / 4000 (0,97 %) |

TacticalBot est le **holdout**, le mètre étalon dont la valeur est gelée
(`config/bot_movement_weights.json`, entrée `tactical`). Il a donc faussé la mesure de référence
depuis le merge du chantier 04.

Deux causes distinctes, toutes deux corrigées en 04c : l'absence de branche `deployment`
(TacticalBot), et la clause d'exploration évaluée **avant** cette branche chez 5 bots sur 7.

## La proposition

`BotControlledEnv._get_bot_action` est déjà le point qui traduit le masque en pool jouable, et il
le fait **déjà correctement pour la phase move** : la branche `if current_phase == "move"` route
vers `_select_bot_move_action`, qui pour l'ingress isole lui-même les slots, tranche le pool vide
(`return mi.ACTION_WAIT`) et ne transmet au bot **que** des slots de pose.

Le déploiement est le **seul** site de mise en place qui n'est pas routé là : les bots y reçoivent
le masque brut, WAIT compris.

Ajouter la branche jumelle :

```python
if current_phase == "deployment":
    return actor.select_placement_action(
        [a for a in valid_actions if a in mi.DEPLOY_SLOTS], game_state
    )
```

## Ce que ça gagne

1. **Aucun bot ne peut plus voir WAIT au déploiement**, quel qu'il soit. La protection actuelle
   repose sur une liste maintenue à la main — `ALL_BOTS` dans
   `tests/unit/ai/test_bot_ingress_reserves.py`. Un 8ᵉ bot oublié dans cette liste rouvre le
   défaut ci-dessus, en silence.
2. **`select_placement_action` retrouve UN seul contrat.** Elle en a deux aujourd'hui : pool
   pré-filtré à l'ingress, masque brut au déploiement. Ça se voit dans le message d'erreur de
   `_open_placement_actions`, obligé de décrire les deux mondes en une phrase.
3. **`_random_escape_action` n'a plus besoin du paramètre `phase`**, et le filtre disparaît de
   `_open_placement_actions` côté bots.

## Ce que ça coûte, et pourquoi ce n'est pas fait

- Ça change le chemin de déploiement de **tous les bots** pendant l'entraînement. Le win-rate de
  référence ne bouge pas en théorie (le comportement résultant est identique), mais ce n'est pas
  vérifié par une mesure.
- Le `raise ValueError` de `_open_placement_actions` deviendrait **inatteignable** sur les deux
  chemins (à l'ingress le wrapper sort sur `ACTION_WAIT` quand le pool est vide ; au déploiement
  le décodeur lève « Deployment deadlock » avant). Le test
  `test_placement_refuses_a_pool_without_any_open_slot` verrouille alors une exigence sans objet
  et devrait sauter.
- Aucun bug actif : le garde-fou de 04c est en place et **verrouillé** (défaut remis → les 5 bots
  attendus passent au rouge).

C'est une assurance contre une erreur future, pas une correction. À faire dans une tâche dédiée,
pas en marge d'un autre chantier.
