"""Fragments de GRAMMAIRE du step.log partagés par plusieurs lecteurs.

Ce module ne dépend d'AUCUN autre module de l'analyzer : c'est sa raison d'être. Les fragments
qui décrivent la forme d'une ligne sont consommés aussi bien par les feuilles (`analyzer_hit`,
`analyzer_wound`) que par la boucle principale (`analyzer_core`), et les héberger dans cette
dernière inversait la hiérarchie — `analyzer_hit` importait les 3 000 lignes de la boucle pour
une constante de vingt caractères, refermant le cycle
`analyzer_hit → analyzer_core → analyzer_suppression → analyzer_hit`. Le cycle ne se manifestait
que lorsque `ai.analyzer_hit` était le PREMIER module de la chaîne importé, c'est-à-dire en
lançant seul le fichier de tests qui le vise.
"""
from __future__ import annotations

#: Token(s) de capacité OPTIONNELS entre un verbe et son complément (`[WAAAGH!]`, `[FLY]`, …).
#: MÊME fragment pour les verbes de mouvement (`move_line_re`) et d'attaque : c'est la grammaire
#: du journal, pas celle d'un site.
ACTION_ABILITY_TOKENS = r'(?:\s+\[[^\]]+\])*'
