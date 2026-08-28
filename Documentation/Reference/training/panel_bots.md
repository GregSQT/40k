# Panel de bots

Six styles de doctrine (alpha, attrition, decapitation, endgame, racer, scorer) remplaçant
l'ancien panel (control, value_trade, adaptive, greedy, defensive, tactical).

> Journal détaillé du chantier de refonte (§1→§12, runs de réglage, deltas appariés) :
> `Documentation/Archives/docs/bots_refonte_panel.md`.

---

## Structure du panel

Le panel compte six bots de doctrine, plus les bots de référence (dont `tactical`) qui varient
selon le profil d'évaluation. Les six styles forment une **échelle de difficulté graduée**, pas
une base multi-dimensionnelle : sur un format où seuls les objectifs marquent, la mesure bot-contre-bot
a montré qu'ils se déplacent en bloc d'un modèle à l'autre — ordre strictement identique, +3 à +7
points selon le modèle.

**Profils d'évaluation :**

- `x1_panel` — les six styles seuls, plateau `board/44x60x1` ;
- `x1_long` — évaluation longue (150 ep/tâche) sur l'ancien panel.

**Modèle canonique :** `ai/models/ArmageddonAgent/model_ArmageddonAgent.zip` — partagé et
volatil. Toute évaluation comparable doit vérifier le md5 du checkpoint et copier le `.zip`
**et** son `_vec_normalize.pkl` apparié dans un répertoire privé au worktree. Cf. §10.2 du
journal pour le protocole complet.

---

## Styles de doctrine

| style | doctrine | erreur punie |
|---|---|---|
| Racer | prend tous les objectifs au plus vite, refuse le combat | l'agent qui campe et ne conteste jamais |
| Endgame | tient le minimum tôt, prend le maximum à partir du tour 3 | l'agent qui marque tôt et se croit gagnant |
| Alpha | cherche le contact au plus tôt sur la pièce clé | l'agent qui expose ses unités de tir |
| Attrition | joue le départage VALUE : préserve ses pièces chères, tue le rentable | l'agent qui trade mal |
| Decapitation | concentre tout sur une escouade par tour pour la retirer entièrement | l'agent qui étale ses forces |
| Scorer | joue pour marquer, ne se bat que pour ça | l'agent qui gagne des combats et perd la partie |

Racer/Endgame sont les deux bornes du **tempo**, Attrition/Décapitation les deux façons
opposées de dépenser ses dégâts, Alpha la distance nulle, Scorer l'axe du score lui-même.

Les poids par style sont dans `config/bot_movement_weights.json`. Source unique pour les
scripts du panel : `scripts/bot_panel_reference.py` (via `print_panel_reference()`).

---

## Architecture des bots

**Fichiers :**

- `ai/bot_doctrines.py` — les six styles ;
- `ai/bot_registry.py` — source unique clé→classe ;
- `ai/evaluation_bots.py` — anciens bots (gelés, non supprimés) ;
- `scripts/bot_zone_direct.py` — mesure d'étalement par bot et par tour ;
- `scripts/bot_panel_reference.py` — source unique des chiffres de référence ;
- `scripts/bot_compare_weights.py` — comparaison appariée de deux runs.

**Modèle de dégâts :** `engine/weapon_damage_cache.py` + `squad_expected_damage()`.
La table donne un dégât **par figurine** ; `squad_expected_damage` agrège sur les figurines
**vivantes** lues dans `models_cache`. Aucun repli : cache absent ou escouade inconnue lèvent.

**Accès moteur :** les bots reçoivent `game_state` et `enemies`. Le cache de contributions OC
(`_contributions_cache_key` / `_contributions_cache_val`) évite de recalculer
`objective_control_contributions` à chaque candidat de mouvement au sein de la même activation.

---

## Référence de mesure

### Protocole

```bash
cd /home/greg/40k && source .venv/bin/activate
python3 ai/train.py --agent ArmageddonAgent --training-config x1 \
  --test-only --test-episodes 100 --resolution 1
```

- Plateau : `board/44x60x1` (x1), sans `--resolution 1` le classement change.
- Pool : holdout (`scenario_bot-01..04`), `base_seed = 42`.
- 100 épisodes par bot, 600 au total.
- Vérifier le md5 du modèle avant et après (cf. §10.2 du journal).

**Mesure d'étalement (instrument de réglage) :**

```bash
W40K_BOARD_PATH=board/44x60x1 python3 scripts/bot_zone_direct.py --episodes 60
```

Résultat déterministe au bit à graines identiques. Deux exécutions consécutives sans changement
de modèle ni de poids produisent un `diff` vide. Gardes : `W40K_BOARD_PATH` exigé, md5 du
checkpoint vérifié (`REFERENCE_MD5`).

**Mesure de correspondance bot-contre-bot :**

```bash
W40K_BOARD_PATH=board/44x60x1 python3 scripts/bot_ranking.py --training-config x1
```

Pas de drapeau de résolution : sans `W40K_BOARD_PATH` mesure sur x5, autre jeu que la
référence.

**Ressources partagées — ne pas mesurer en parallèle :**

- modèle canonique (écrasé par tout `--new`) ;
- `step.log` (un seul fichier) ;
- JSON de `config/` (relus à chaud par les évaluations) ;
- la ligne de base elle-même et la numérotation du journal.

---

### §12.5 — Référence historique (pre-§12.6)

Référence panel (§12.5, pre-§12.6, JAMAIS REJOUÉE après les correctifs) :
`combined = 0,837`. Pire bot `attrition = 0,837`.
— mesure sur l'ancien panel (control/value_trade/adaptive/greedy/defensive), avant toute
correction du modèle de dégâts par figurine.

---

### §12.14 — Référence courante (remesurée le 2026-08-21 sur robust_0.8463)

Remesure après §12.15 (rupture charge_pair_net) sur le nouveau checkpoint `robust_0.8463`
(100 ép./bot, siège aléatoire, panel 10 bots dont 3 bots de référence, board/44x60x1, x1_long) :

`Combined = 0,8567`. Pire bot `attrition = 0,810`.

Mesure historique sur robust_0.8721 (robust_0.8721 ne charge plus depuis le 2026-08-20) :
— `Combined = 0,7433`. Pire bot `racer = 0,630`.

Source unique : `scripts/bot_panel_reference.py` — ne pas recopier ces chiffres dans les scripts
du panel (`bot_zone_check.py`, `bot_zone_direct.py`), ils lisent via `print_panel_reference()`.

## §12.15 — Rupture de comparabilité (2026-08-21)

Le commit `d5ddffb5` (charge multi-cibles, P3 L9, 2026-08-20) a ajouté la tête dense
`charge_pair_net` à `PointerMaskablePolicy`. **Tout checkpoint antérieur lève au chargement** :
`Missing key(s) in state_dict: "charge_pair_net.weight", "charge_pair_net.bias"`. Sur les 28
archives de `ai/models/ArmageddonAgent/`, 6 chargent et 22 lèvent (vérifié le 2026-08-21).

L'étalon épinglé du §12 (`ArmageddonAgent_NEW_BOTS_12345_robust_0.8692`) en fait partie :
l'instrument `bot_zone_direct.py` était donc inutilisable, quel que soit le modèle visé — la
garde md5 s'applique aussi au chemin passé par `--model`, qui est un alias de chemin vers le
même checkpoint et non un sélecteur de modèle.

**Décision (2026-08-21) : re-épinglage sur `ArmageddonAgent_12345_robust_0.8463`**
(md5 `794335b6979b9532f7ce7c83c59c950e`), seule archive nommée `_robust_` postérieure à la
rupture. Les deux autres options ont été écartées : greffer la tête manquante sur l'ancien
checkpoint mesurerait une politique qui n'a jamais existé (poids non entraînés sur des actions
légales), et abandonner l'épinglage retirerait la garde qui a coûté la campagne du §12.7.

**Conséquence sur les chiffres.** La ligne de base du §12.14 (`Combined = 0,7433`, pire bot
`racer = 0,630`) a été prise sur un checkpoint qui ne charge plus : aucun relevé pris sur
`robust_0.8463` ne s'y compare. Elle reste affichée par `print_panel_reference()` avec un
avertissement `⛔ PRÉ-RUPTURE`, verrouillé par
`tests/unit/scripts/test_bot_panel_reference.py::test_la_ligne_signale_la_rupture_tant_que_les_chiffres_ne_sont_pas_rejoues`.
Ce test exige aussi le retrait de l'avertissement le jour où la ligne est rejouée sur l'étalon
courant. **Remesure à faire** (100 ép./bot, `W40K_BOARD_PATH=board/44x60x1`, `x1_long`) avant
toute nouvelle comparaison de panel.

---

## Ligne de base §12.14 (post-réglage décapitation, 2026-08-13)

Mesure sur `robust_0.8721` (avant rupture §12.15), 100 ép./bot, profil `x1_panel` :

| bot | zones T2 | zones T5 | win-rate agent |
|---|---|---|---|
| racer | 1,77 | 2,07 | **0,63** |
| scorer | **1,87** | **2,33** | 0,66 |
| attrition | 1,67 | 2,08 | 0,71 |
| decapitation | 1,63 | 1,68 | 0,73 |
| endgame | 1,57 | 2,08 | 0,80 |
| alpha | 1,12 | 1,10 | 0,93 |

`Combined = 0,7433`. Pire bot `racer = 0,630`. Pire scénario `holdout_regular_bot-01 = 0,6867`.
Écart Space Marine − Ork : −4,7 pt.

---

## Pièges et décisions actées

- **`--model` ne redirige rien** dans `ai/train.py --test-only` : le modèle chargé est toujours
  le chemin canonique. Pour évaluer un checkpoint nommé, l'installer au chemin canonique **avec**
  son `.pkl` apparié.
- **`--scenario bot` est refusé en `--test-only`** : omettre `--scenario`.
- **La résolution se fixe AVANT de mesurer.** Sans `--resolution 1` le plateau par défaut est x5,
  classement des bots différent.
- **Le nom du bot n'est posé qu'en mode sérial** : le `step_logger` n'est pas picklable.
- **`w_crowd` et le seuil `hold_bonus`** : poser un poids au nom de ce que le style est censé
  faire a échoué trois fois de suite (§12.8, §12.9, §12.11) — régler par mesure appariée uniquement.
- **Biais de survie de `dist_by_turn`** : ne se lit jamais seule au dernier tour ; toujours
  accompagner du taux de pertes (`squads_by_turn`) ou utiliser une cohorte fixe (§12.12.2).
- **Ressource partagée — la ligne de base** : une session qui reprend un chantier de mesure écrase
  la référence des sessions parallèles. Geler le document et les JSON de `config/` avant de mesurer.
