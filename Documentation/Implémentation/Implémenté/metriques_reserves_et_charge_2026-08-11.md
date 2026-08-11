# Métriques (réserves, abilities), barème et alignement de la charge — 2026-08-11

> **Livré.** Sept tranches, issues de la lecture des métriques du run `x1_long` du 2026-08-11
> (50 000 épisodes, combined 96,9 %). Chacune part d'une **mesure**, pas d'une intuition : le
> chiffre qui l'a déclenchée est cité à chaque fois, et les commentaires du code le portent.
>
> ⚠️ **Le modèle de ce run est caduc.** La tranche 7 change l'espace de décision de la phase de
> charge. Les poids restent chargeables, mais `02_combat/n_charge_success_rate` saute vers 100 %
> pour une raison mécanique, pas par progrès.

---

## Ce que le run du 2026-08-11 a montré

L'écart avec le run précédent (200 000 épisodes, combined 0,72) ne vient **pas** de l'obs seule.
La cause principale est mesurée et documentée dans `engine/episode_schedule.py` : la rampe de
déploiement était **figée** (compteur d'épisodes local à un env rapporté à un budget global,
`n_envs=48`). `00_critical/s_deploy_active_share` valait 0,29 plat sur tout le run de 200 k, contre
0,31 → 0,80 sur celui de 50 k — alors que l'évaluation, elle, **impose toujours** un déploiement
actif (`deployment_type: "active"` dans les 4 scénarios holdout). L'agent était donc noté sur un
comportement présent dans 29 % de son entraînement. Signature interne cohérente : le run de 200 k
finissait à 0,966 de win-rate d'entraînement pour 0,72 en holdout ; celui de 50 k fait 0,858 pour
0,969.

Comparaison **non iso** par ailleurs : `obs_size` 20828 → 16659, ~24 000 lignes changées dans
`engine/`, 8 400 dans `ai/`, et les bots eux-mêmes ont évolué (arrivée des réserves, CP,
battle-shock). La part revenant à l'agent seul n'est pas isolable.

---

## 1. Cadence d'évaluation — le score robuste ne sélectionnait rien

`bot_eval_freq` 10000 sur un run de 50 000 = 5 évaluations pour un `robust_window` de 5, donc **un
seul** score robuste : `save_best_robust` gardait le dernier modèle en le présentant comme le
meilleur (« Selected at episodes: 50001 », faute d'alternative).

La valeur avait été calée sur 200 000 épisodes et est devenue fausse **en silence** quand la durée
du run a changé. D'où une règle **dérivée** plutôt qu'une valeur en dur, tenue par
`test_profile_can_produce_the_best_model_it_promises` : `total_episodes / bot_eval_freq >= 2 ×
robust_window`. `x1_long` passe à 5000 (10 points de mesure, ~15 min d'éval en plus sur 5 h).

`test_long_profile_is_its_reference_recalibrated` ne fige plus `total_episodes == 200_000` — cette
assertion était **rouge sur `main`** depuis le passage à 50 000, sans rien protéger.

`x1` ne promet plus de best model (`save_best_robust: false`, comme `x5_new`) : sa contrainte
`save_best_min_episodes` vaut ses 10 000 épisodes, donc aucune sauvegarde n'y est possible avant le
tout dernier point de mesure. Sa sortie est son modèle **final**.

## 2. Affichage final — des agrégats affichés comme des win-rates

Les deux résumés publiés sélectionnaient par **liste noire**, donc toute clé numérique ajoutée aux
résultats s'affichait « vs `<clé>` : `<valeur×100>` % » : `roster_gap` (un écart de 0,012) en
« vs roster_gap : 1.2% », `total_episodes_played` (un compte) en « 360000.0% ». Source unique
`iter_bot_score_rows` (liste blanche `ALL_BOT_NAMES`), et les deux agrégats imprimés sous le
Combined Score, dans leur unité.

`game_tactical/action_efficiency` supprimée : elle valait exactement `1 − invalid_action_rate`.

## 3. Shaping zone-intent — débranché, pas supprimé

`combat/intent_shaping_aligned_ratio` 0,269 contre un `_baseline` de 0,355 — la référence étant ce
que la **même politique** obtiendrait en tirant son intent sans regarder le plateau. L'agent est
resté **sous** ce hasard dans 95 % des fenêtres des 10 000 derniers épisodes, tout en conditionnant
de mieux en mieux son intent sur l'état (`o_intent_control_dependency` 0,004 → 0,104).

Autrement dit : il a appris à lire le plateau **pour en tirer l'intention que le barème ne paie
pas**, et il gagne en encaissant la pénalité tour après tour. Un terme dense anti-corrélé au
comportement gagnant est du bruit dans le gradient.

`zone_intent_shaping.enabled: false` (lu par `require_key`, sans défaut). Les quatre montants, le
code et les courbes restent : un `true` rebranche tout.

## 4. Réserves — six mesures, deux camps, et la cause nommée

`destroyed_turn3` était documentée « tous joueurs » alors que son site d'écriture **filtrait sur
l'agent** : la perte de réserves du bot n'existait sur aucune courbe, et rien ne permettait de
vérifier ce que son code promet (il arrive dès qu'un slot s'ouvre, `env_wrappers`).

Les compteurs passent par **numéro de joueur** dans le `game_state` (le siège de l'agent est tiré
au sort), projetés sur `_agent` / `_opponent` à la terminaison — le seul endroit qui connaisse ce
siège. Douze courbes : `placed`, `deployed`, `destroyed_turn3`, `ingress_offers`,
`ingress_declined`, `ingress_no_destination`.

Les trois dernières séparent ce que « détruite en réserve » confondait :

| | mesure | ce qu'elle dit |
|---|---|---|
| `ingress_offers` | (unité, tour) où un slot d'arrivée était ouvert | le **dénominateur** — sans lui, un `declined` à 0 ne distingue pas « tout saisi » de « rien offert » |
| `ingress_declined` | offres non saisies | une **DÉCISION** (20.03 dit « can », jamais « must ») |
| `ingress_no_destination` | pool d'ingress vide | **aucune décision** — bande de 6" du bord, > 8" de tout ennemi, zone adverse fermée avant le 3e round |

Point de mesure : les **trois** sorties de `ActionDecoder.ingress_slot_candidates`, cache-hit
compris — le seul endroit qui connaisse la réponse sans rien recalculer.

## 5. Pénalité de réserve gaspillée — −25 par escouade

Motivée : la part des réserves de l'agent détruites sans être arrivées monte de **0 % à 14 %** en
fin d'entraînement, en hausse monotone, pendant qu'il en place de plus en plus (0,81 → 1,33 par
épisode, à mesure que la part d'épisodes en déploiement actif passe de 0,31 à 0,80). Rien dans le
barème ne s'y opposait.

Facturée **seulement** sur ce qui était une décision : croisement des unités détruites avec
`_ingress_offered`. Un compte transite du handler (qui n'a pas le barème) au calculateur (qui n'a
pas le moment), facturé au step suivant comme le shaping zone-intent, ventilé dans `penalties`.

Calibrage : un sixième du bonus de victoire (150) pour une escouade entière perdue sans avoir
combattu ; ~4,7 par épisode au taux mesuré, sur un retour moyen de ~485. **À surveiller au prochain
run** : `ingress_declined_agent` doit reculer *sans* que `placed_agent` s'effondre — l'agent qui
n'ose plus mettre en réserve serait pire que le gaspillage.

## 6. Charge — ce que le step.log a montré

En gym, le jet 2D6 avait lieu **après** le choix de la cible, et le masque ouvrait tout ennemi à
`charge_max_distance` (12"). Mesure sur le step.log du 2026-08-11, 494 charges de l'agent :

| distance à la cible déclarée | agent | adversaire |
|---|---|---|
| médiane des charges **réussies** | 5 | 5 |
| médiane des charges **ratées** | 9 | 9 |
| part des déclarations à ≥ 9" | **41 %** | 36 % |

Un 2D6 atteint 9 dans 27,8 % des cas : 41 % des déclarations étaient des paris à moins d'une chance
sur trois, et faisaient 58 % des échecs. Rien n'en dissuadait — `charge_fail` vaut −0,01 au barème.

## 7. Alignement de la charge sur 11.02

Séquence règle (PDF 11 lu) : **Declare Charge → Make Charge Roll → Attempt Charge**, et 11.04 borne
les cibles sélectionnables par le jet. Le chemin PvP/PvE l'appliquait déjà ; seul le gym divergeait.

Désormais : le jet tombe à l'**activation** de l'escouade — qui vaut déclaration (11.02.1) et est
déjà une décision explicite de l'agent — et le masque n'ouvre que les cibles que ce jet atteint.
`WAIT` reste ouvert : renoncer après le jet est légal (11.02.3).

**L'oracle est `charge_build_valid_plan`**, la fonction qu'exécute le commit. Une première version
dérivait l'atteignabilité du pool par-**ancre** alors que le commit raisonne par-**figurine** :
9 divergences sur 37 comparaisons, toutes « le commit accepte, le masque refuse », c'est-à-dire des
charges légales rendues injouables. Le masque, l'observation et le commit lisent maintenant la même
source — la parité est structurelle.

Effet mesuré, 8 épisodes en actions aléatoires :

| | déclarées | réussies | taux | durée |
|---|---|---|---|---|
| avant | 17 | 3 | 18 % | 130,6 s |
| après | 4 | 4 | 100 % | 119,9 s |

Les charges **réussies** ne baissent pas ; ce qui disparaît, ce sont les déclarations vouées à
l'échec. Aucun surcoût malgré un appel d'oracle par cible candidate.

Le jet est purgé à la fin de l'activation (`generic_handlers`) : le pipeline squad ne le stockait
pas auparavant, donc ne le purgeait nulle part — sans quoi il serait relu au tour suivant.

**Conséquence sur les tests** : en gym, une charge déclarée ne peut plus échouer. Trois tests
réparés — deux espéraient d'une graine une situation devenue rare et **construisent** désormais
leur journal, un troisième verrouillait un échec de charge en gym, motif qui reste testé sur le
chemin qui l'émet encore.

---

## Ce qui reste

- **Distances de charge au `step.log` et en métriques** : distance (pathfinding) à l'ennemi le plus
  proche **à la déclaration**, et distance à la cible **au choix**. Les deux moments existent
  maintenant réellement. Cinq sites de journalisation à couvrir dans `charge_handlers` (2 succès,
  3 échecs) — motif jumeau classique.
- **Compteurs `abilities/`** : un compteur par règle d'unité réellement appliquée, par joueur, plus
  une courbe d'exposition (sans elle, un zéro ne distingue pas « jamais déclenchée » de « jamais
  dans le roster »). Deux familles à couvrir : celles qui produisent une ligne d'`action_log`
  (`reactive_move`, `charge_impact`, `charge_after_advance/flee`, `move_after_shooting`) et celles
  qui ne modifient qu'un jet (rerolls, bonus Oath, sur les `shot_records`).
- **Déséquilibre de siège** : `winrate_agent_p1` 0,783 contre `p2` 0,655 — 13 points. Constaté,
  jugé normal (jouer en premier est un avantage), non traité.
- **`h_clip_fraction` 0,032** sous le seuil bas de 0,10 : fin de schedule, les 20 000 derniers
  épisodes n'apprennent presque plus. Levier = `decay_fraction`, pas le clip.
