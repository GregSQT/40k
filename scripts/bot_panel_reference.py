#!/usr/bin/env python3
"""Source UNIQUE de la référence chiffrée du panel de bots (§12.14 de `panel_bots.md`).

POURQUOI CE MODULE EXISTE. La ligne était recopiée à la main dans `bot_zone_check.py` et
`bot_zone_direct.py` : mêmes chiffres, étiquettes CONTRAIRES (« pre-§12.6 » d'un côté,
« post-§12.6 » de l'autre). L'un des deux mentait à qui lisait la sortie, et rien ne pouvait le
signaler — deux littéraux n'ont aucun moyen de se contredire bruyamment. C'est le motif JUMEAU
du dépôt : la copie corrigée d'un seul côté. Un troisième script aurait recopié une troisième
étiquette.

Tout script du panel qui affiche cette référence appelle `print_panel_reference()`. Aucun ne
réécrit les chiffres : `tests/unit/scripts/test_bot_panel_reference.py` échoue si un littéral
`combined=0.788` reparaît ailleurs dans `scripts/`.

CE QUE DIT L'ÉTIQUETTE, et pourquoi elle a changé le 2026-08-21. Le §12.15 (commit d5ddffb5,
charge multi-cibles) a ajouté `charge_pair_net` à `PointerMaskablePolicy`, rendant inchargeable
tout checkpoint antérieur. La référence du §12.14 (robust_0.8721) ne pouvait plus être produite
par aucun modèle chargeable. Le re-épinglage sur `robust_0.8463` (seule archive `_robust_` post-
rupture) a donc exigé de rejouer la ligne de base. Cette remesure est celle du 2026-08-21 : elle
incorpore aussi le nouveau panel à 10 bots (dont 3 bots de référence ajoutés le 2026-08-20).

⚠️ La moyenne de zones (T2/T5 = 1.81/1.76) n'est PAS comparable à l'ancienne (1.60/1.89) :
elle est calculée sur 10 bots, les 3 bots de référence (plus faibles) tirant la moyenne vers le
bas au T5. Comparer le tableau PAR BOT, jamais cette moyenne seule.

CE QUE DIT LA CONDITION EXPÉRIMENTALE. Ce n'est PAS « bot=P2 », comme les deux copies l'ont
longtemps écrit : la référence est mesurée sur `x1_long`, dont `agent_seat_mode` vaut
« random » — le bot occupe donc les deux sièges. Annoncer un siège fixe faisait décrire une
condition que personne n'a imposée, et un lecteur qui aurait voulu la reproduire à siège fixe
aurait comparé deux protocoles.
"""
from __future__ import annotations

#: Les quatre grandeurs de la ligne de base (remesurée le 2026-08-21). `combined`, `pire bot` et
#: `pire scénario` viennent de la mesure contre l'agent (100 ép./bot) ; la moyenne de zones vient
#: du relevé d'étalement (60 ép./bot). Les deux runs sont du même jour, sur `robust_0.8463`.
#: Panel à 10 bots (dont 3 bots de référence). La mesure précédente (robust_0.8721) ne charge plus.
PANEL_REFERENCE_FIGURES = "combined=0.8567  pire bot attrition=0.810  pire scenario=0.7800  zones T2/T5=1.81/1.76"

#: La ligne telle qu'elle s'affiche. L'avertissement fait partie de la référence, pas du décor :
#: une moyenne de panel masque la redistribution qui est l'objet même du chantier.
PANEL_REFERENCE_LINE = (
    f"Référence panel §12.14 (x1_long, siège aléatoire, robust_0.8463) : {PANEL_REFERENCE_FIGURES}\n"
    "   post-§12.6, post-§12.9 (`scorer` réglé), post-§12.11 (déplacement de `decapitation`),\n"
    "   post-§12.15 (charge_pair_net, re-épinglage robust_0.8463, panel 10 bots — 2026-08-21).\n"
    "⚠️ zones T2/T5 calculées sur 10 bots (dont 3 bots de référence) : ne pas comparer à la\n"
    "   ligne du §12.5 (6 bots) ; comparer le tableau PAR BOT du §12.14, jamais la moyenne seule."
)


def print_panel_reference() -> None:
    """Affiche la référence du panel. Seul point d'émission de ces chiffres dans `scripts/`."""
    print(PANEL_REFERENCE_LINE)
