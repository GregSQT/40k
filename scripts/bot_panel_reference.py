#!/usr/bin/env python3
"""Source UNIQUE de la référence chiffrée du panel de bots (§12.5 de `bots_refonte_panel.md`).

POURQUOI CE MODULE EXISTE. La ligne était recopiée à la main dans `bot_zone_check.py` et
`bot_zone_direct.py` : mêmes chiffres, étiquettes CONTRAIRES (« pre-§12.6 » d'un côté,
« post-§12.6 » de l'autre). L'un des deux mentait à qui lisait la sortie, et rien ne pouvait le
signaler — deux littéraux n'ont aucun moyen de se contredire bruyamment. C'est le motif JUMEAU
du dépôt : la copie corrigée d'un seul côté. Un troisième script aurait recopié une troisième
étiquette.

Tout script du panel qui affiche cette référence appelle `print_panel_reference()`. Aucun ne
réécrit les chiffres : `tests/unit/scripts/test_bot_panel_reference.py` échoue si un littéral
`combined=0.788` reparaît ailleurs dans `scripts/`.

CE QUE DIT L'ÉTIQUETTE, et pourquoi elle est celle-là. Les chiffres du §12.5 sont ANTÉRIEURS au
§12.6, qui le dit deux fois : « CES CHIFFRES SONT ANTÉRIEURS AU §12.6 et n'ont pas été rejoués
depuis » et « À REJOUER : la mesure du §12.5 sur 600 parties ». Ils ont donc été obtenus avec
les deux défauts que le §12.6 corrige (poids fractionnaires purement annulés, surplus d'OC
compté autrement que le contrôle du moteur), et depuis le §12.7 `alpha` et `decapitation` n'ont
plus les mêmes poids. Le SENS du résultat tient, son AMPLITUDE non : la ligne le dit, sinon
corriger l'étiquette ne ferait que remplacer un mensonge sur la date par une comparaison
invalide silencieuse.

CE QUE DIT LA CONDITION EXPÉRIMENTALE. Ce n'est PAS « bot=P2 », comme les deux copies l'ont
longtemps écrit : la référence est mesurée sur `x1_panel`, dont `agent_seat_mode` vaut
« random » — le bot occupe donc les deux sièges. Annoncer un siège fixe faisait décrire une
condition que personne n'a imposée, et un lecteur qui aurait voulu la reproduire à siège fixe
aurait comparé deux protocoles.
"""
from __future__ import annotations

#: Les quatre grandeurs du tableau §12.5 « après », 100 épisodes par bot.
PANEL_REFERENCE_FIGURES = "T2=1.61  T5=1.90  VP=31.0  combined=0.788"

#: La ligne telle qu'elle s'affiche. L'avertissement fait partie de la référence, pas du décor :
#: sans lui, le lecteur compare son run du jour à une mesure qui ne mesurait pas la même chose.
PANEL_REFERENCE_LINE = (
    f"Référence panel §12.5 (x1_panel, siège aléatoire, 100 ép./bot) : {PANEL_REFERENCE_FIGURES}\n"
    "⚠️ pre-§12.6, JAMAIS REJOUÉE : mesurée avec les deux défauts corrigés au §12.6 (poids\n"
    "   fractionnaires annulés, surplus d'OC mal compté), et les poids d'`alpha`/`decapitation`\n"
    "   ont changé au §12.7. Le sens tient, l'amplitude non — ne pas comparer un run du jour à\n"
    "   ces chiffres tant que le §12.5 n'a pas été rejoué (600 parties)."
)


def print_panel_reference() -> None:
    """Affiche la référence du panel. Seul point d'émission de ces chiffres dans `scripts/`."""
    print(PANEL_REFERENCE_LINE)
