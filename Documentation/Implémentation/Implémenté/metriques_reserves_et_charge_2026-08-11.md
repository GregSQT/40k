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

## 8. Distances de charge — la mesure prise à l'instant où la règle la regarde

Le §6 ci-dessus a été obtenu en **re-dérivant à la main** les distances depuis les coordonnées du
step.log. Elles sont désormais mesurées par le moteur, aux deux instants que l'alignement 11.02 a
rendus distincts et réels : la **déclaration** (11.02.1, l'activation) et le **choix de la cible**
(11.04).

**Quelle distance.** Celle du gate 11.04 lui-même — « within the maximum distance of your unit » —
via `charge_target_edge_distance_subhex`, qui n'est que la VALEUR de `charge_target_within_max_distance`.
Donc bord-à-bord, **par figurine** (le socle est construit sur `model_centers`), dans la métrique
que le moteur résout déjà. C'est la seule grandeur directement comparable à un 2D6.

**Ce qu'elle ne dit pas** : le trajet réel. 11.04 exige aussi un plan légal dans le budget, et un
mur peut rendre une cible proche inatteignable. La distance de trajet n'existe ici que **bornée par
le jet** (`_compute_plan_context`, donc tronquée exactement sur les déclarations trop lointaines
qu'on veut compter) ou **par ancre** (pool BFS, donc divergente de l'oracle par-figurine — 9 cas
sur 37 mesurés). La mesurer autrement demanderait un **troisième** oracle d'atteignabilité dans un
fichier qui en porte déjà deux ; le motif d'échec n°1 du dépôt.

**Sept sites, pas cinq.** Le décompte annoncé dans « Ce qui reste » ne comptait que
`charge_handlers` (2 succès, 3 échecs). Le chemin **gym** journalise à part, dans `w40k_core` —
et c'est lui qui produit le step.log d'entraînement. S'en tenir à cinq aurait rendu la mesure
muette là où elle sert.

**Cinq pièges, cinq verrous** (`test_charge_declaration_distances.py` et
`test_charge_manual_surface.py`, chacun vérifié ROUGE en réintroduisant son défaut ; les deux
derniers viennent de la relecture) :

| piège | ce qui se serait passé |
|---|---|
| mesure prise au site de succès | `commit_move` a déplacé les figurines → toutes les charges réussies à l'ER, moyenne effondrée, aucun `require_key` levé |
| activation close sur WAIT comptée | 11.02.3 permet de renoncer ; le dénominateur enflerait de non-charges et la part à ≥ 9" baisserait avec le nombre de renoncements |
| un site oublié | la moitié des issues sans mesure, donc aucune des deux questions posées ne trouve réponse |
| mesure posée avant la validation de la cible | une cible **détruite** depuis l'offre fait lever `require_key` là où le handler prend délibérément la branche `charge_fail` → requête PvP en 500 ; et la distance d'une cible **refusée** par 11.04 (bascule 21.03) partait quand même dans les stats des ratées |
| part à ≥ 9" rapportée à toutes les déclarations | une charge sans cible ne peut jamais entrer au numérateur ; au dénominateur, elle fait baisser la part **quand ces cas se multiplient** — la courbe décrirait l'inverse de ce qui se passe |

La distance est calculée avec un **élagage** à `charge_max_distance` (11.02 « within 12" »),
au-delà duquel elle vaut `None` : sans lui, le contour complet des socles était parcouru par
couple (chargeur, ennemi) à chaque activation, sur le chemin chaud de l'entraînement, pour une
courbe de télémétrie. Le gate jumeau passe un cap exactement pour cette raison.

Un quatrième verrou tient le **jumeau log/analyzer** : le segment `[Dist: … | Nearest: …]` est posé
en fin de ligne, après `[Roll: N]`, là où aucun des trois parseurs de step.log n'ancre. Vérifié non
vacant — le même segment glissé avant `from (c,r)` casse bien la regex.

Dix courbes `charge_distance/*`, deux camps × cinq mesures : `a_nearest_enemy_inches`,
`b_target_inches`, `c_target_inches_success`, `d_target_inches_fail`, `e_declarations_ge9_share`.
Chacune est un **rapport de moyennes sur la fenêtre glissante** (`_emit_ratio_of_means`), comme
`n_charge_success_rate` juste à côté et pour la raison que documente cette fonction : le
dénominateur est un **résultat d'épisode**, donc un épisode sans charge n'a pas de moyenne, et
toute façon de le traiter isolément biaise la courbe. Aucun point tant que la fenêtre n'a rien
mesuré : un 0.0 se lirait « il charge au contact ».

Pas de courbe de volume ici : `02_combat/m_charge_attempts` et `o_charge_attempts_bot` la
portent déjà, **dérivées des mêmes lignes de journal**. C'est le fond du câblage — la ligne de
charge est le SEUL porteur de la mesure, et la statistique d'épisode se dérive d'`action_logs`
dans la même passe et sur le même couple de types que `charge_attempts` / `charge_successes`.
Une liste d'enregistrements tenue en parallèle dans `game_state` aurait été un second compteur
du même événement, capable de diverger du premier sans qu'aucune courbe ne le montre — et il
aurait suffi d'un futur chemin de fin de charge émettant la ligne sans passer par lui.

Corollaire : `charge_record_outcome` ne prend **pas** de paramètre d'issue. Réussite ou échec est
déjà le `type` de la ligne ; un booléen à côté aurait été une seconde source pour la même
information, à sept sites, sans rien pour vérifier qu'elles s'accordent.

---

## Ce qui reste

- ~~**Distances de charge au `step.log` et en métriques**~~ — **livré le 2026-08-11**, cf. §8
  ci-dessous.
- **Compteurs `abilities/`** : un compteur par règle d'unité réellement appliquée, par joueur, plus
  une courbe d'exposition (sans elle, un zéro ne distingue pas « jamais déclenchée » de « jamais
  dans le roster »). Deux familles à couvrir : celles qui produisent une ligne d'`action_log`
  (`reactive_move`, `charge_impact`, `charge_after_advance/flee`, `move_after_shooting`) et celles
  qui ne modifient qu'un jet (rerolls, bonus Oath, sur les `shot_records`).
- **Déséquilibre de siège** : `winrate_agent_p1` 0,783 contre `p2` 0,655 — 13 points. Constaté,
  jugé normal (jouer en premier est un avantage), non traité.
- **`h_clip_fraction` 0,032** sous le seuil bas de 0,10 : fin de schedule, les 20 000 derniers
  épisodes n'apprennent presque plus. Levier = `decay_fraction`, pas le clip.
