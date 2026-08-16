# Refonte du panel de bots (§12)

Six styles de doctrine (alpha, attrition, decapitation, endgame, racer, scorer) remplaçant
l'ancien panel (control, value_trade, adaptive, greedy, defensive, tactical).

## §12.5 — Référence historique (pre-§12.6)

Référence panel (§12.5, pre-§12.6, JAMAIS REJOUÉE après les correctifs) :
`combined = 0,837`. Pire bot `attrition = 0,837`.
— mesure sur l'ancien panel (control/value_trade/adaptive/greedy/defensive), avant toute
correction du modèle de dégâts par figurine.

## §12.14 — Référence courante (post-correctifs)

Mesure de référence après §12.6, §12.9 et §12.11 (100 ép./bot, robust_0.8721, siège aléatoire) :

`Combined = 0,7433`. Pire bot `racer = 0,630`.

Source unique : `scripts/bot_panel_reference.py` — ne pas recopier ces chiffres dans les scripts
du panel (`bot_zone_check.py`, `bot_zone_direct.py`), ils lisent via `print_panel_reference()`.
