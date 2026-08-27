# Refonte du panel de bots (§12)

Six styles de doctrine (alpha, attrition, decapitation, endgame, racer, scorer) remplaçant
l'ancien panel (control, value_trade, adaptive, greedy, defensive, tactical).

## §12.5 — Référence historique (pre-§12.6)

Référence panel (§12.5, pre-§12.6, JAMAIS REJOUÉE après les correctifs) :
`combined = 0,837`. Pire bot `attrition = 0,837`.
— mesure sur l'ancien panel (control/value_trade/adaptive/greedy/defensive), avant toute
correction du modèle de dégâts par figurine.

## §12.14 — Référence courante (remesurée le 2026-08-21 sur robust_0.8463)

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
