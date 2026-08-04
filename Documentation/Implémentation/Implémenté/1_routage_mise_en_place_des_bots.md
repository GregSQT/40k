# Router la mise en place des bots par `_get_bot_action`

Proposé le 2026-08-04 par la revue d'altitude du chantier 04c. **IMPLÉMENTÉ le 2026-08-05.**

> **Périmètre** : `ai/env_wrappers.py` (`BotControlledEnv._get_bot_action`) et
> `ai/evaluation_bots.py` (les 7 bots). Ne touche ni le moteur, ni le masque, ni le PvP.
>
> **Principe** : nettoyer le pool d'actions UNE fois, au point de traduction masque → décision,
> au lieu de le faire dans chaque bot.
>
> **Statut (2026-08-05)** : fait. `BotControlledEnv._select_bot_deploy_action` route le
> déploiement ; `_open_placement_slots` porte la règle « seuls les slots 4-8 sont des poses »
> pour les deux sites de mise en place (déploiement 03.02 et ingress move 20.04) et
> `_ask_bot_placement` est leur point d'interrogation commun ; `_open_placement_actions` a
> disparu côté bots. Cf. « Ce qui a été fait » en fin de document pour les écarts avec la
> proposition.

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

## Ce que ça coûte

- Ça change le chemin de déploiement de **tous les bots** pendant l'entraînement.
- Le `raise ValueError` de `_open_placement_actions` deviendrait **inatteignable** sur les deux
  chemins (à l'ingress le wrapper sort sur `ACTION_WAIT` quand le pool est vide ; au déploiement
  le décodeur lève « Deployment deadlock » avant).
- Aucun bug actif : le garde-fou de 04c est en place et **verrouillé** (défaut remis → les 5 bots
  attendus passent au rouge).

C'est une assurance contre une erreur future, pas une correction.

---

## Ce qui a été fait (2026-08-05)

### Trois écarts avec la proposition

**1. « Le comportement résultant est identique » était FAUX.** La proposition ne voyait pas la
clause d'exploration `randomness`, qui chez 5 bots est évaluée **avant** la branche `deployment` :
elle tirait alors un slot **uniforme**, court-circuitant la table de poids du bot. Router la mise
en place au wrapper supprime donc l'exploration au déploiement :

| Bot | avant | après |
|---|---|---|
| Greedy / Adaptive / Control / ValueTrade | 15 % uniforme, 85 % pondéré | 100 % pondéré |
| **TacticalBot (holdout)** | **5 % uniforme, 95 % premier slot** | **100 % premier slot** |
| Defensive (branche avant la clause) | 100 % pondéré | inchangé |
| Random | uniforme | inchangé |

Symétriquement, l'ingress n'avait **jamais** eu d'exploration : il appelait déjà
`select_placement_action` en direct. Les deux sites étant des jumeaux, il fallait trancher lequel
bougeait. **Arbitré : doctrine pure des deux côtés.** Conséquence à retenir : le holdout est
désormais strictement déterministe à la pose, ses win-rates antérieurs ne sont plus bit-à-bit
comparables.

**2. `_open_placement_actions` a bien disparu côté bots, comme prévu — mais en deux temps.**
Elle a d'abord été retournée en vérification de contrat (`_require_placement_pool`), pour ne pas
perdre la garde. La passe `/simplify` a montré que cette garde ne pouvait plus rien voir : le
filtre étant remonté chez l'appelant, un contrôle placé **après** lui est un vert vacant, et il
restait à trois sites consommateurs qu'un 8ᵉ bot pouvait ignorer. Elle a donc été supprimée, et
le contrat est documenté une fois en tête de `ai/evaluation_bots.py`. La règle elle-même vit dans
`BotControlledEnv._open_placement_slots`, **écrite une seule fois** pour les deux sites — le
premier jet la dupliquait dans les deux branches du wrapper, soit le défaut de 04c un cran plus
haut. `test_placement_refuses_a_pool_without_any_open_slot` a bien sauté, comme la proposition
l'avait prévu ; `test_the_placement_pool_rule_is_written_once` le remplace et verrouille
l'unicité de la règle (défaut remis → rouge).

**3. Le pool vide au déploiement ne peut pas se replier sur `ACTION_WAIT`** comme le fait
l'ingress — WAIT y **est** la mise en réserves. `_select_bot_deploy_action` lève donc une
`RuntimeError` explicite, là où l'ingress rend `ACTION_WAIT` (état de jeu normal).

### Ce qui a été mesuré

La proposition disait « aucun bug actif ». C'est vrai des bots pris un par un, et faux du chemin
complet : `_get_bot_action` **est** appelé en phase de déploiement, et la protection de 04c y
tenait à la seule branche `deployment` de chaque bot. Branche du wrapper retirée, sur
`scenario_training_armageddon.json`, 5 épisodes, TacticalBot `randomness=0.05` :

| | WAIT ouvert dans le masque | WAIT **joué** (mise en réserves) |
|---|---|---|
| sans le routage | 9 / 27 déploiements | **8** |
| avec le routage | 25 / 28 déploiements | **0** |

Deux conditions doivent être réunies pour que le défaut soit visible, et elles expliquent
pourquoi les tests existants ne le voyaient pas : le déploiement doit être **actif** (le
scheduler par-épisode rend « fixed » en début de training — pas de phase de déploiement du
tout), et `WAIT` doit être **ouvert** (fermé dès que la liste sature le plafond 20.01, ce qui
est le cas de la fixture d'ingress). Ces deux conditions sont assertées dans
`test_bot_deployment_never_reserves_on_the_real_path`, sans quoi ce serait un vert vacant.

### Verrous

- `test_bot_deployment_never_reserves_on_the_real_path` (intégration) : défaut remis → **rouge**
  (`le bot a mis ['102', '103'] en réserves stratégiques`). C'est le seul test qui prouve que le
  code est ATTEINT par le vrai chemin.
- `test_wrapper_never_offers_wait_at_deployment` : vérifie ce que le wrapper **transmet**, donc
  ne dépend plus de la liste `ALL_BOTS` tenue à la main — c'est le gain n°1 de la proposition.
- `test_no_bot_ever_puts_a_unit_in_strategic_reserves` passe désormais par
  `_select_bot_deploy_action` et non plus par `select_action_with_state`.
- `test_the_placement_pool_rule_is_written_once` : filtre réécrit à la main dans une des deux
  branches → **rouge**. Verrouille l'unicité de la règle, pas seulement son comportement.
