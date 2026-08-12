#!/usr/bin/env python3
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
# check_ai_rules). Elles n'étaient protégées que par du texte, donc pas protégées du tout.
#
# AUCUNE PORTE DE SORTIE (2026-08-13). Une délégation ponctuelle a existé un jour : un marqueur
# `VERIF-LARGE-AUTORISEE` en fin de ligne faisait passer n'importe quelle commande. Retirée à la
# demande de l'utilisateur, qui a constaté qu'un agent l'écrivait de lui-même. Le motif est
# structurel, pas disciplinaire : un hook ne voit pas le prompt, donc il ne peut pas distinguer
# l'autorisation réelle de l'autorisation supposée — une interdiction dont une chaîne de
# caractères ouvre la porte n'est pas une interdiction. Un agent vérifie CE QU'IL A TOUCHÉ, point.
# Ne pas réintroduire de condition d'échappement (marqueur, variable d'environnement, fichier
# jeton) : un agent peut produire chacune d'elles lui-même.
#
# ANALYSE PAR SEGMENT, en Python depuis le 2026-08-13 (comme `rapport-cloture.sh`, python sous un
# nom en .sh). La version en `grep` jugeait la LIGNE ENTIÈRE d'un seul tenant : une brique ciblée
# quelque part sur la ligne dispensait tout le reste d'examen, donc
# `pytest tests/x.py ; pyright ; npx biome check frontend/src` passait en entier — la commande de
# référence de l'utilisateur, sans marqueur. Ici, la ligne est DÉCOUPÉE sur `;`, `&&`, `||`, `|`
# et retours à la ligne, et chaque segment est jugé pour lui-même. `shlex` gère en prime les
# guillemets (`pytest "tests/x.py"`) et les `--ignore=tests/x.py`, que les regex confondaient
# avec une cible.
import json
import re
import shlex
import sys

# Un fichier de test NOMMÉ est une cible ; un répertoire de tests est une suite.
REPERTOIRE_DE_TESTS = re.compile(r"^\.?/?tests(/[A-Za-z0-9_-]+)*/?$")

# Options qui MANGENT le token suivant : sans ça `-n 8` ferait de `8` une cible, et `-k tests`
# ferait passer un run complet pour un run ciblé.
OPTIONS_A_VALEUR = {"-n", "-k", "-m", "-p", "-c", "-o", "-r", "--dist", "--rootdir", "--deselect",
                    "--ignore", "--ignore-glob", "--maxfail", "--junitxml", "-W",
                    "--project", "--outDir", "--config-file"}
# `--cov` et `--tb` n'y sont PAS : leur valeur s'écrit collée (`--cov=engine`), donc les compter
# comme mangeurs faisait disparaître la cible de `pytest --cov tests/unit/engine/test_x.py`.

# Premiers mots qui LISENT une ligne de commande sans l'exécuter : `grep -rn pytest .claude/hooks/`
# n'est pas un run de pytest. La liste est délibérément COURTE et fermée — tout premier mot inconnu
# (`stdbuf`, `xargs`, `sh -c`…) compte comme une EXÉCUTION, donc se fait juger. Un oubli ici refuse
# une commande de trop ; l'inverse rouvrirait la porte que ce hook existe pour fermer. `find` et
# `git` n'y figurent PAS, et ce n'est pas un oubli : `find -exec` et `git bisect run` LANCENT.
LECTEURS = {"grep", "rg", "ag", "cat", "bat", "head", "tail", "less", "more", "echo", "printf",
            "wc", "sed", "awk", "diff", "ls", "stat", "md5sum", "sha1sum"}

# Une cible n'est PRÉCISE que si elle nomme un fichier : un glob (`tests/**/*.py`) rend la main
# au shell, qui rouvre la suite entière. Un guillemet résiduel signe un découpage dégradé.
GLOBS = ("*", "?", "[", '"', "'")

# Mots derrière lesquels le mot suivant est l'EXÉCUTABLE. Sans ça, `pip install pytest` — qui
# installe pytest sans le lancer — serait refusé ; avec seulement la tête de segment,
# `git bisect run pytest` ou `find . -exec pytest {} +` passeraient.
LANCEURS = {"-m", "run", "exec", "-exec", "p", "python", "python3", "node"}

# Mots qui PRÉFIXENT une commande sans être la commande : ils ont leurs propres options et parfois
# un argument à eux (`timeout 1200 pytest`, `nice -n 10 pytest`). L'exécutable est le premier mot
# qui n'est ni l'un d'eux, ni une option, ni une valeur numérique — sans quoi n'importe lequel
# d'entre eux servirait de laissez-passer (mesuré : `timeout 1200 pytest tests/unit/` passait).
PREFIXES = {"npx", "npm", "pnpm", "yarn", "uv", "uvx", "poetry", "pipenv", "sudo", "env", "command",
            "timeout", "nohup", "nice", "stdbuf", "watch", "time", "xargs", "python", "python3",
            "p", "node", "bunx", "pdm", "rye", "hatch"}

# Shells : eux seuls prennent une COMMANDE en argument cité. Un `git commit -m "run pytest"` porte
# du texte, pas une commande — le distinguer évite de refuser les messages de commit du dépôt.
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "busybox"}


def deshabille(ligne):
    """La ligne sans ses commentaires, retours à la ligne devenus séparateurs de commandes.

    Les deux règles sont celles du shell, et aucune n'est celle de `shlex` : un `#` n'ouvre un
    commentaire qu'en DÉBUT DE MOT et hors guillemets (`--grep=#42` n'en est pas un), et un
    retour à la ligne SÉPARE deux commandes au lieu d'être un simple blanc.
    """
    sortie, quote, commentaire, debut_de_mot = [], "", False, True
    for car in ligne:
        if commentaire:
            if car == "\n":
                commentaire, debut_de_mot = False, True
                sortie.append(";")
            continue
        if quote:
            sortie.append(car)
            if car == quote:
                quote = ""
            continue
        if car in "\"'":
            quote, debut_de_mot = car, False
            sortie.append(car)
            continue
        if car == "#" and debut_de_mot:
            commentaire = True
            continue
        if car == "\n":
            sortie.append(";")
            debut_de_mot = True
            continue
        sortie.append(car)
        # Un mot commence aussi après un opérateur : `git status ;# npx biome check frontend/src`
        # est un commentaire pour le shell, pas une commande.
        debut_de_mot = car.isspace() or car in ";|&()"
    return "".join(sortie)


def segments(ligne):
    """La ligne découpée en commandes élémentaires, chacune rendue comme liste de mots.

    Le découpage se fait APRÈS l'analyse lexicale, pas avant : un `;` ou un `&&` à l'intérieur de
    guillemets appartient à une sous-commande, pas à la ligne. Découper la chaîne d'abord (ce que
    faisait la version en regex) hachait `bash -c "pytest tests/unit/; pyright"` en morceaux dont
    aucun ne ressemblait plus à un run — la commande passait entière.

    Les commentaires et les retours à la ligne sont traités AVANT, par `deshabille()` : `shlex`
    coupe sur un `#` au milieu d'un mot (`git log --grep=#42 ; pytest tests/unit/` y perdait sa
    seconde commande, donc passait) et ne voit dans `\n` qu'un blanc, pas un séparateur.

    Sur syntaxe incomplète (guillemet non fermé), découpage naïf : les guillemets restent collés
    aux mots, et `precise()` refuse toute cible qui en porte — le mode dégradé refuse.
    """
    ligne = deshabille(ligne)
    try:
        lex = shlex.shlex(ligne, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        lex.commenters = ""
        mots = list(lex)
    except ValueError:
        return [s.split() for s in re.split(r"\|\||&&|[;|&\n]", ligne) if s.strip()]

    commandes, courante = [], []
    for mot in mots:
        if mot and all(c in ";|&()<>\n" for c in mot):
            if courante:
                commandes.append(courante)
            courante = []
        else:
            courante.append(mot)
    if courante:
        commandes.append(courante)
    return commandes




def lecture_seule(mots):
    """Vrai si le segment ne fait que LIRE : son premier mot est un afficheur de texte.

    Le premier mot seul décide, et la liste est fermée : un `find -exec pytest` ou un
    `git bisect run pytest` LANCE l'outil, donc ni l'un ni l'autre n'est un lecteur ici.
    """
    for mot in mots:
        if "=" in mot and not mot.startswith("-") and mot.split("=", 1)[0].isidentifier():
            continue  # affectation d'environnement en tête : VAR=1 pytest …
        return mot.split("/")[-1] in LECTEURS
    return False


def precise(cible, suffixes):
    """Vrai si cette cible nomme UN fichier — pas un glob, pas un répertoire.

    Le node id (`fichier.py::test_x[param]`) est la cible la PLUS fine du dépôt : seul le chemin
    qui précède `::` est jugé, sinon le `[` de la paramétrisation le ferait passer pour un glob.
    """
    chemin = cible.split("::", 1)[0]
    if any(g in chemin for g in GLOBS):
        return False
    return chemin.endswith(suffixes)


def cibles(mots, outil, depart):
    """Les arguments POSITIONNELS passés à l'occurrence de `outil` située en `depart`.

    Une occurrence à la fois : `pytest tests/unit/ ; pytest test_x.py` en compte deux, et la
    première est une suite entière. Ne lire que la dernière blanchissait la ligne.
    """
    positionnels, saute = [], False
    for mot in mots[depart + 1:]:
        if saute:
            saute = False
            continue
        if mot.startswith("-"):
            saute = mot in OPTIONS_A_VALEUR
            continue
        positionnels.append(mot)
    return positionnels


def affectation(mot):
    """Vrai si le mot est une affectation d'environnement en tête (`VAR=1 pytest …`)."""
    return "=" in mot and not mot.startswith("-") and mot.split("=", 1)[0].isidentifier()


def occurrences(mots, outil):
    """Les positions où ce segment EXÉCUTE `outil`.

    Deux façons de l'être : en POSITION D'EXÉCUTABLE — le premier mot qui n'est ni un préfixe
    (`timeout`, `env`, `npx`…), ni une de leurs options, ni une valeur — ou juste derrière un
    LANCEUR (`-m`, `run`, `-exec`), qui prend l'exécutable en argument. Nommer l'outil ailleurs ne
    compte pas : `pip install pytest` l'installe, `git add check_ai_rules.py` l'indexe.
    """
    trouvees, en_tete = [], True
    for i, mot in enumerate(mots):
        est_outil = mot.split("/")[-1] == outil
        if est_outil and (en_tete or mots[i - 1] in LANCEURS):
            trouvees.append(i)
            en_tete = False
            continue
        if not en_tete:
            continue
        if affectation(mot) or mot.startswith("-") or mot.split("/")[-1] in PREFIXES:
            continue
        if re.fullmatch(r"[0-9]+(\.[0-9]+)?[smhd]?", mot):
            continue  # argument propre d'un préfixe : `timeout 1200`, `nice -n 10`
        en_tete = False  # ce mot-ci est l'exécutable, et ce n'est pas l'outil cherché
    return trouvees


def raisons(mots, profondeur=0):
    """Ce que cette commande lance de trop large — vide si elle est ciblée."""
    if not mots or lecture_seule(mots):
        return []
    trouve = []

    # CHAQUE occurrence se juge : un run ciblé ne couvre pas celui d'à côté.
    for i in occurrences(mots, "pytest"):
        vises = cibles(mots, "pytest", i)
        if any(REPERTOIRE_DE_TESTS.match(c) for c in vises):
            trouve.append("lance un RÉPERTOIRE de tests entier")
        elif not any(precise(c, (".py",)) for c in vises):
            trouve.append("ne cible aucun fichier de test précis (collecte tout le projet)")

    # pyright n'a pas de mode "ciblé" utile ici — sans fichier nommé il type-check tout le projet.
    for i in occurrences(mots, "pyright"):
        if not any(precise(c, (".py", ".pyi")) for c in cibles(mots, "pyright", i)):
            trouve.append("lance pyright sur tout le projet")

    # biome sur une ARBORESCENCE (frontend/src, ., src) plutôt que sur des fichiers nommés.
    for i in occurrences(mots, "biome"):
        exts = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json")
        if not any(precise(c, exts) for c in cibles(mots, "biome", i)):
            trouve.append("lance biome sur une arborescence entière")

    # tsc : `-p tsconfig.json` comme `tsc` nu compilent tout le frontend. Seuls des .ts NOMMÉS
    # restent ciblés — `--noEmit` n'y change rien, ce n'est pas lui qui décide de l'ampleur.
    for i in occurrences(mots, "tsc"):
        if not any(precise(c, (".ts", ".tsx")) for c in cibles(mots, "tsc", i)):
            trouve.append("type-check tout le frontend (tsc sur un projet entier)")

    # Scripts de conformité : ils balayent le dépôt entier par construction. Même règle de
    # position que les autres outils — `git add scripts/check_ai_rules.py` ou
    # `pytest tests/unit/ai/test_hidden_action_finder.py` ne LANCENT ni l'un ni l'autre.
    if occurrences(mots, "hidden_action_finder.py") or occurrences(mots, "check_ai_rules.py"):
        trouve.append("lance un script de conformité qui balaye tout le dépôt")

    # Sous-commande CITÉE (`bash -c "python3 -m pytest tests/"`) : shlex en fait un seul token,
    # donc elle échapperait à tout. Elle se juge comme une ligne à part entière — mais SEULEMENT
    # derrière un shell : partout ailleurs un argument cité est du texte (message de commit,
    # `python3 -c`, `--body`), et le juger refuserait des commandes qui ne lancent rien.
    if profondeur < 3 and any(m.split("/")[-1] in SHELLS for m in mots):
        for i, mot in enumerate(mots[1:], start=1):
            # Argument du `-c` (ou `-lc`, `-ic`…), ou tout argument qui porte une espace : dans
            # les deux cas c'est une ligne de commande, pas une donnée.
            porte_commande = any(c.isspace() for c in mot) or re.fullmatch(r"-[a-z]*c", mots[i - 1])
            if porte_commande and not mot.startswith("-"):
                for sous in segments(mot):
                    trouve.extend(m for m in raisons(sous, profondeur + 1) if m not in trouve)

    return trouve


def main():
    try:
        cmd = json.load(sys.stdin).get("tool_input", {}).get("command", "")
    except Exception:
        return
    if not cmd:
        return

    motifs = []
    for segment in segments(cmd):
        for motif in raisons(segment):
            if motif not in motifs:
                motifs.append(motif)
    if not motifs:
        return

    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason":
            "REFUSÉ : cette commande " + ", puis ".join(motifs) + ". La vérification large prend "
            "~20 min et c'est l'utilisateur qui la lance, avec sa propre commande. Tu ne vérifies "
            "QUE ce que tu as touché : pytest tests/unit/engine/test_xxx.py, pyright fichier.py, "
            "biome sur un fichier. Aucun marqueur, aucune variable, aucune reformulation ne rouvre "
            "cette porte : elle est fermée. Si une validation large te semble nécessaire, DIS-LE à "
            "l'utilisateur au lieu de la lancer.",
    }}, ensure_ascii=False))


main()
