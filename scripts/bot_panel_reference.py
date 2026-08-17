#!/usr/bin/env python3
"""Source UNIQUE de la référence chiffrée du panel de bots (§12.14 de `bots_refonte_panel.md`).

POURQUOI CE MODULE EXISTE. La ligne était recopiée à la main dans `bot_zone_check.py` et
`bot_zone_direct.py` : mêmes chiffres, étiquettes CONTRAIRES (« pre-§12.6 » d'un côté,
« post-§12.6 » de l'autre). L'un des deux mentait à qui lisait la sortie, et rien ne pouvait le
signaler — deux littéraux n'ont aucun moyen de se contredire bruyamment. C'est le motif JUMEAU
du dépôt : la copie corrigée d'un seul côté. Un troisième script aurait recopié une troisième
étiquette.

Tout script du panel qui affiche cette référence appelle `print_panel_reference()`. Aucun ne
réécrit les chiffres : `tests/unit/scripts/test_bot_panel_reference.py` échoue si un littéral
`combined=0.788` reparaît ailleurs dans `scripts/`.

CE QUE DIT L'ÉTIQUETTE, et pourquoi elle a changé le 2026-08-13. Ce module portait les chiffres
du §12.5 avec la mention « JAMAIS REJOUÉE », qui était juste quand il a été écrit et fausse
quelques heures plus tard : le §12.8, le §12.9 et le §12.14 les ont rejoués le même jour, sur le
même modèle et le même plateau. La référence est donc celle du §12.14, la seule postérieure à
TOUS les correctifs du chantier (§12.6 sur la pénalité d'encombrement, §12.11 sur le déplacement
de `decapitation`) et au réglage de `scorer` (§12.9).

⚠️ La moyenne de panel en zones n'a presque pas bougé entre le §12.5 (1.61/1.90) et le §12.14
(1.60/1.89), et ça ne veut PAS dire que rien n'a changé : c'est une moyenne sur six bots dont la
distribution s'est fortement déplacée (`scorer` 1.93 → 2.33, `decapitation` 1.08 → 1.68, la
pénalité d'encombrement ayant par ailleurs redistribué les escouades). Ne jamais conclure de
cette ligne seule — le tableau PAR BOT du §12.14 est ce qui se compare.

CE QUE DIT LA CONDITION EXPÉRIMENTALE. Ce n'est PAS « bot=P2 », comme les deux copies l'ont
longtemps écrit : la référence est mesurée sur `x1_long`, dont `agent_seat_mode` vaut
« random » — le bot occupe donc les deux sièges. Annoncer un siège fixe faisait décrire une
condition que personne n'a imposée, et un lecteur qui aurait voulu la reproduire à siège fixe
aurait comparé deux protocoles.
"""
from __future__ import annotations

#: Les quatre grandeurs de la ligne de base du §12.14. `combined`, `pire bot` et `pire scénario`
#: viennent de la mesure contre l'agent (100 ép./bot) ; la moyenne de zones vient du relevé
#: d'étalement (60 ép./bot). Les deux runs sont du même jour, sur `robust_0.8721`.
PANEL_REFERENCE_FIGURES = "combined=0.7433  pire bot racer=0.630  pire scenario=0.6867  zones T2/T5=1.60/1.89"

#: La ligne telle qu'elle s'affiche. L'avertissement fait partie de la référence, pas du décor :
#: une moyenne de panel masque la redistribution qui est l'objet même du chantier.
PANEL_REFERENCE_LINE = (
    f"Référence panel §12.14 (x1_long, siège aléatoire, robust_0.8721) : {PANEL_REFERENCE_FIGURES}\n"
    "   post-§12.6, post-§12.9 (`scorer` réglé) et post-§12.11 (déplacement de `decapitation`).\n"
    "⚠️ la moyenne de zones est presque identique à celle du §12.5 alors que la distribution par\n"
    "   bot a fortement bougé : comparer le tableau PAR BOT du §12.14, jamais cette moyenne seule."
)


def print_panel_reference() -> None:
    """Affiche la référence du panel. Seul point d'émission de ces chiffres dans `scripts/`."""
    print(PANEL_REFERENCE_LINE)
