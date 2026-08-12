#!/usr/bin/env bash
# PreToolUse/Bash — refuse la VÉRIFICATION LARGE, qui appartient à l'utilisateur.
#
# Motif : la vérification large de ce projet coûte ~20 min. Un agent qui la relance "pour valider"
# fait attendre l'utilisateur, qui préfère faire ses checks lui-même. Les runs CIBLÉS (un ou
# plusieurs fichiers de test nommés) restent libres : ils sont rapides et servent le travail.
#
# Sortie : rien (exit 0) si la commande est autorisée telle quelle ; sinon un JSON
# `permissionDecision: "deny"` — la commande est REFUSÉE, sans prompt pour l'utilisateur.
# Choix assumé (2026-07-26) : l'utilisateur fait ses vérifications larges lui-même, avec sa
# propre commande (pytest -n 8 + pyright + biome + tsc + scripts de conformité). Un agent n'a
# donc aucune raison de la lancer : il doit se rabattre sur des vérifications CIBLÉES.
# `permissions.deny` ne conviendrait pas : les règles de permission matchent par préfixe, donc
# `source .venv/bin/activate && python3 -m pytest tests/` y échapperait. Le hook, lui, voit la
# ligne de commande entière.
#
# Périmètre élargi le 2026-08-12 : ce hook ne gardait que `pytest`, alors que CLAUDE.md confie à
# l'utilisateur SIX autres briques de la même commande (pyright, biome, tsc, hidden_action_finder,
# check_ai_rules). Elles n'étaient protégées que par du texte, donc pas protégées du tout — même
# défaut que le marqueur VERIF-LARGE-AUTORISEE documenté pendant des mois sans exister ici.
set -uo pipefail

# jq n'est PAS installé sur cette machine (`jq: command not found`) : la charge JSON du hook
# est lue avec python3, toujours présent.
cmd=$(python3 -c 'import json,sys
try:
    print(json.load(sys.stdin).get("tool_input", {}).get("command", ""))
except Exception:
    pass' 2>/dev/null || printf '')

[ -z "$cmd" ] && exit 0

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

if printf '%s' "$cmd" | grep -q 'pytest'; then
  # Cas 1 : un RÉPERTOIRE de tests est passé en cible (tests, tests/, tests/unit, tests/integration…).
  # C'est une suite, quel que soit le reste de la ligne.
  if printf '%s' "$cmd" | grep -Eq 'pytest[^|;&]*(^|[[:space:]])(\./)?tests(/[A-Za-z0-9_-]+)*/?([[:space:]]|$)'; then
    reason="lance un RÉPERTOIRE de tests entier"
  # Cas 2 : pytest sans aucun fichier .py explicite -> collecte tout (rootdir), donc suite complète.
  elif ! printf '%s' "$cmd" | grep -Eq 'pytest[^|;&]*[A-Za-z0-9_/.:-]+\.py'; then
    reason="ne cible aucun fichier de test précis (collecte tout le projet)"
  fi

# Cas 3 : pyright. Il n'a pas de mode "ciblé" utile ici — sans fichier nommé il type-check tout
# le projet. Avec un fichier nommé, il reste rapide : on laisse passer.
elif printf '%s' "$cmd" | grep -Eq '(^|[[:space:]/])pyright([[:space:]]|$)'; then
  if ! printf '%s' "$cmd" | grep -Eq 'pyright[^|;&]*[A-Za-z0-9_/.-]+\.(py|pyi)([[:space:]]|$)'; then
    reason="lance pyright sur tout le projet"
  fi

# Cas 4 : biome sur une ARBORESCENCE (frontend/src, ., src) plutôt que sur des fichiers nommés.
elif printf '%s' "$cmd" | grep -q 'biome'; then
  if ! printf '%s' "$cmd" | grep -Eq 'biome[^|;&]*[A-Za-z0-9_/.-]+\.(ts|tsx|js|jsx|mjs|cjs|json)([[:space:]]|$)'; then
    reason="lance biome sur une arborescence entière"
  fi

# Cas 5 : tsc --noEmit sur un tsconfig = compilation de tout le frontend. Aucune forme ciblée.
elif printf '%s' "$cmd" | grep -Eq 'tsc([[:space:]]|$)' && printf '%s' "$cmd" | grep -q -- '--noEmit'; then
  reason="type-check tout le frontend (tsc --noEmit)"

# Cas 6 : scripts de conformité. Ils balayent le dépôt entier par construction : pas de forme ciblée.
elif printf '%s' "$cmd" | grep -Eq 'hidden_action_finder\.py|check_ai_rules\.py'; then
  reason="lance un script de conformité qui balaye tout le dépôt"
fi

[ -z "$reason" ] && exit 0

printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"REFUSÉ : cette commande %s. La vérification large prend ~20 min et c'"'"'est l'"'"'utilisateur qui la lance, avec sa propre commande. Reste sur du CIBLÉ (pytest tests/unit/engine/test_xxx.py, pyright fichier.py, biome sur un fichier). Si une validation large te semble nécessaire, DIS-LE à l'"'"'utilisateur au lieu de la lancer."}}' "$reason"
exit 0
