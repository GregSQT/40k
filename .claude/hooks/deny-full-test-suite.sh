#!/usr/bin/env bash
# PreToolUse/Bash — exige une confirmation AVANT tout lancement de la suite de tests complète.
#
# Motif : une suite complète coûte ~20 min sur ce projet. Un agent qui la relance "pour valider"
# fait attendre l'utilisateur, qui préfère faire ses checks lui-même. Les runs CIBLÉS (un ou
# plusieurs fichiers de test nommés) restent libres : ils sont rapides et servent le travail.
#
# Sortie : rien (exit 0) si la commande est autorisée telle quelle ; sinon un JSON
# `permissionDecision: "deny"` — la commande est REFUSÉE, sans prompt pour l'utilisateur.
# Choix assumé (2026-07-26) : l'utilisateur fait ses vérifications larges lui-même, avec sa
# propre commande (pytest -n 8 + pyright + biome + tsc + scripts de conformité). Un agent n'a
# donc aucune raison de lancer la suite : il doit se rabattre sur des tests CIBLÉS.
# `permissions.deny` ne conviendrait pas : les règles de permission matchent par préfixe, donc
# `source .venv/bin/activate && python3 -m pytest tests/` y échapperait. Le hook, lui, voit la
# ligne de commande entière.
set -uo pipefail

# jq n'est PAS installé sur cette machine (`jq: command not found`) : la charge JSON du hook
# est lue avec python3, toujours présent.
cmd=$(python3 -c 'import json,sys
try:
    print(json.load(sys.stdin).get("tool_input", {}).get("command", ""))
except Exception:
    pass' 2>/dev/null || printf '')

# Pas de pytest dans la commande -> rien à faire.
printf '%s' "$cmd" | grep -q 'pytest' || exit 0

# PORTE DE SORTIE — délégation ponctuelle (CLAUDE.md, « TESTS — QUI LANCE QUOI »).
#
# L'utilisateur peut confier SA vérification large à l'agent pour un prompt donné. CLAUDE.md
# décrit depuis toujours le marqueur ci-dessous comme le moyen de le signaler au hook... et le
# hook ne l'a jamais implémenté (constaté le 2026-08-12 : autorisation donnée, commande refusée
# quand même). Une règle écrite que le code contredit ne protège rien — elle fait perdre un
# aller-retour à chaque délégation, et pousse à contourner par des appels fichier par fichier,
# c'est-à-dire exactement ce que ce hook existe pour empêcher.
#
# Ce n'est PAS un affaiblissement : le marqueur n'est légitime que si le PROMPT COURANT porte
# l'autorisation explicite, il ne vaut que pour ce prompt et ne se déduit d'aucun contexte
# (cf. CLAUDE.md). L'ajouter sans autorisation reste une faute grave — simplement, elle se juge
# à la lecture du transcript, pas ici : un hook ne voit pas le prompt.
if printf '%s' "$cmd" | grep -q 'VERIF-LARGE-AUTORISEE'; then
  exit 0
fi

reason=""

# Cas 1 : un RÉPERTOIRE de tests est passé en cible (tests, tests/, tests/unit, tests/integration…).
# C'est une suite, quel que soit le reste de la ligne.
if printf '%s' "$cmd" | grep -Eq 'pytest[^|;&]*(^|[[:space:]])(\./)?tests(/[A-Za-z0-9_-]+)*/?([[:space:]]|$)'; then
  reason="lance un RÉPERTOIRE de tests entier"
# Cas 2 : pytest sans aucun fichier .py explicite -> collecte tout (rootdir), donc suite complète.
elif ! printf '%s' "$cmd" | grep -Eq 'pytest[^|;&]*[A-Za-z0-9_/.:-]+\.py'; then
  reason="ne cible aucun fichier de test précis (collecte tout le projet)"
fi

[ -z "$reason" ] && exit 0

printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"REFUSÉ : cette commande %s. La suite complète prend ~20 min et c'"'"'est l'"'"'utilisateur qui la lance, avec sa propre commande de vérification. Lance uniquement des fichiers de test ciblés (pytest tests/unit/engine/test_xxx.py). Si une validation large te semble nécessaire, DIS-LE à l'"'"'utilisateur au lieu de la lancer."}}' "$reason"
exit 0
