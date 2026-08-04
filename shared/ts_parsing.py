"""Motifs communs de lecture des sources TypeScript (rosters, armurerie).

Les datasheets et l'armurerie sont ecrites en TS et lues par DEUX parseurs Python distincts
(`ai/unit_registry.py` pour les unites, `engine/weapons/parser.py` pour les armes). Toute regle
de lecture qu'ils partagent vit ICI : elles ont deja diverge une fois sur ce point precis, et
c'est le motif du jumeau divergent.
"""

#: Chaine TS entre guillemets, fermee sur le MEME guillemet que l'ouverture.
#:
#: Groupe 1 = le guillemet, groupe 2 = la VALEUR. Un appelant qui lisait `group(1)` avec l'ancien
#: motif doit passer a `group(2)`.
#:
#: POURQUOI LA BACKREFERENCE. Le motif naif `["\']([^"\']+)["\']` s'arrete au premier guillemet
#: RENCONTRE, quel qu'il soit — donc a l'apostrophe interne d'un nom anglais :
#:   displayName: "Thievin' Scavengers"  -> capturait "Thievin"  (TRONQUE, sans erreur)
#:   display_name: "Dok's Tools"         -> capturait "Dok"
#:   display_name: "'eadbanger'"         -> aucun match, la cle n'etait JAMAIS posee, et
#:                                          l'absence explosait bien plus loin, ailleurs
#: La troncature est SILENCIEUSE : aucune exception, une valeur simplement fausse qui traverse
#: l'API et s'affiche telle quelle dans l'UI. Avec `\1`, la fermeture doit etre le meme guillemet
#: que l'ouverture — comportement strictement identique pour toute valeur sans apostrophe.
TS_QUOTED_STRING = r'(["\'])((?:(?!\1).)*)\1'
