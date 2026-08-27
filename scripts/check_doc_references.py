#!/usr/bin/env python3
"""Les documents d'entrée disent-ils encore la vérité sur le dépôt ?

POURQUOI CE SCRIPT EXISTE. Les documents d'ENTRÉE sont la roadmap (`Documentation/Roadmap/` :
`ROADMAP_INDEX.md` qui dit par quoi commencer, plus un fichier par sujet) et les deux contrats
permanents (`analyzer_couverture.md`, `Security.md`). Ils sont tenus à la main, et rien ne les
confrontait au dépôt. Le 2026-08-10, un contrôle ponctuel a mesuré l'état
des renvois d'`analyzer_couverture.md` **après une seule journée de livraisons** :

    147 citations `fichier.py:ligne` — 31 saines, 76 PROUVÉES FAUSSES, 40 invérifiables.

Les numéros de ligne ont donc été supprimés au profit du couple `fichier.py` + nom de symbole, qui
ne rouille pas. Ce script est la seconde moitié de cette décision.

CE QU'IL ÉTABLIT, en six passes :
  1. RENVOIS  — tout fichier cité existe, et tout symbole cité vit dans le fichier cité.
  2. LIENS    — toute cible de lien markdown existe, ET l'ancre `#fragment` qu'elle porte est
                offerte par le document visé. Mesuré le 2026-08-18 : 45 des 48 liens du corpus
                portent un fragment, tous vers un titre d'un fichier sujet — le fragment était
                coupé et jeté, si bien qu'un titre renommé gardait son lien vert.
  3. VALEURS  — les nombres recopiés d'une source mécanique (config d'agent, tableau d'un autre
                document, constante d'un script) valent encore ce que le document annonce.
  4. ANCRES   — aucun renvoi de la forme `fichier.py:123`, convention posée par la roadmap
                (aujourd'hui portée par `Documentation/Roadmap/doc.md`, section ancres).
                La convention vaut pour TOUTE extension citée par ces documents, pas seulement le
                `.py` : mesuré le 2026-08-12, les deux seules ancres survivantes de `ROADMAP.md`
                étaient des `.tsx`, invisibles au contrôle et déjà décalées de plusieurs milliers
                de lignes. Une convention qui ne tient que sur un suffixe n'en est pas une.
  5. SORTES   — un symbole cité `def X` est bien un `def`, un `class X` bien un `class`. Motif :
                `ROADMAP.md` écrivait « `def EpisodeTerminationCallback` », en promettant
                explicitement un grep reproductible — or ce sont des `class`, et le grep promis
                rendait 0 hit. Le document se présentait comme vérifiable et ne l'était pas.
  6. ATTEIGN. — tout chantier ouvert (`Documentation/Chantiers/backlog/`, sous-dossiers
                compris) se rejoint depuis `ROADMAP_INDEX.md` en suivant les renvois. Les cinq
                premières passes vérifient ce que les documents DISENT ; celle-ci voit ce qu'ils
                ne disent PLUS. Mesuré au premier passage, 2026-08-18 : 2 chantiers ouverts sur
                13 n'étaient cités par aucun fichier sujet — aucune phrase fausse à attraper,
                donc aucune des cinq autres passes ne pouvait le voir.

CE QU'IL N'ÉTABLIT PAS, et qui est COMPTÉ ET AFFICHÉ plutôt que passé sous silence :
  - un renvoi sans symbole à confronter : il n'y a rien à vérifier, et le taire ferait croire à
    une couverture qui n'existe pas — c'est le mode d'échec du VERT VACANT. En font partie le
    jeton backtiqué qui n'a pas la FORME d'un symbole (`directory`, `CORS`, `debug=False` — un mot
    de prose se retrouve dans n'importe quel fichier et confirmerait n'importe quoi), le
    symbole noyé dans une phrase et démenti par le code (la phrase n'affirmait peut-être pas
    qu'il vivait là) et le nom de fichier NU cité à plusieurs exemplaires dans le dépôt
    (`conftest.py`) : le document ne dit pas duquel il parle, donc rien n'y est confrontable ;
  - une cible de lien qui n'a pas la forme d'un chemin (texte entre parenthèses, motif de regex
    cité en prose) : écartée sur un critère de FORME, jamais par une liste d'exceptions nommées,
    qui masquerait le jour où l'une d'elles deviendrait un vrai lien mort ;
  - le nombre de « contrôles analyzer vivants » : il n'existe AUCUNE énumération de ces contrôles
    dans le code (27 compteurs incrémentés dans les handlers, 45 appels du helper de somme du
    rapport — ni l'un ni l'autre ne vaut le nombre annoncé). Compter les lignes d'un tableau de
    document et grepper les noms mesurerait autre chose sous le même nom. Déclaré non vérifiable.

UNE ASSERTION QUI NE RETROUVE PLUS SA CIBLE EST UNE ERREUR, pas un silence. Sans cette règle, une
simple reformulation de la phrase désarme le contrôle sans que personne ne le voie — le script
rejouerait alors très exactement le défaut qu'il est censé fermer.

Usage : python3 scripts/check_doc_references.py [doc.md ...]
Sortie : 0 si rien n'est cassé, 1 sinon.
"""
from __future__ import annotations

import ast
import collections
import functools
import importlib.util
import json
import pathlib
import re
import subprocess
import sys
import urllib.parse
from typing import Any, Callable, Iterable, TypeVar


class SourceUnavailable(RuntimeError):
    """Une SOURCE du contrôle a disparu ou ne se lit plus.

    Type dédié, et pas un `LookupError` générique : attraper `LookupError` en sortie de `main`
    avalait aussi le `KeyError` d'un profil mal formé, et annonçait « les sources du contrôle ont
    disparu » en désignant le mauvais fichier. Ce qui est bloquant-mais-lisible doit se distinguer
    de ce qui est un défaut interne, lequel garde sa trace.
    """


def _check_filesystem_encoding() -> None:
    """Vérifie avant toute ouverture de fichier que le codec filesystem encode les chemins accentués.

    L'arborescence Documentation/ est ASCII depuis la refonte 2026-08-27, mais le dépôt porte
    encore des chemins accentués (Memoire_RNCP/, ex. « Méthodologie de la rédaction... »), que
    `git ls-files` rend et que ce script décode. Sous LC_ALL=C PYTHONUTF8=0,
    sys.getfilesystemencoding() vaut 'ascii' et os.fsencode() échoue à mi-parcours avec une
    UnicodeEncodeError qui ne nomme ni la locale ni le remède.
    Le script choisit de refuser plutôt que de convertir tout son parcours de fichiers en chemins
    bytes : le coût de lisibilité est réel pour un scénario qui exige PYTHONUTF8=0 explicite,
    que Python 3.12 n'active pas de lui-même sous locale C (PEP 538/540 active le mode UTF-8).
    """
    codec = sys.getfilesystemencoding()
    try:
        "é".encode(codec)
    except (UnicodeEncodeError, LookupError):
        import locale as _locale
        loc = _locale.getlocale()[0] or "C"
        raise SourceUnavailable(
            f"L'encodage filesystem '{codec}' (locale détectée : {loc}) ne peut pas encoder "
            f"les chemins accentués de ce dépôt (ex. : Memoire_RNCP/). "
            f"Relancer avec PYTHONUTF8=1 ou sous une locale UTF-8."
        )


ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "Documentation" / "Chantiers"
CLAUDE_MD = ROOT / "CLAUDE.md"

DEFAULT_DOCS = [
    "Documentation/Roadmap/ROADMAP_INDEX.md",
    "Documentation/Roadmap/v11_chemin_critique.md",
    "Documentation/Roadmap/moteur.md",
    "Documentation/Roadmap/training.md",
    "Documentation/Roadmap/bot.md",
    "Documentation/Roadmap/analyzer.md",
    "Documentation/Roadmap/front.md",
    "Documentation/Roadmap/infra.md",
    "Documentation/Roadmap/capacites.md",
    "Documentation/Roadmap/doc.md",
    "Documentation/Chantiers/analyzer_couverture.md",
    "Documentation/Reference/infra/Security.md",
]

#: Documents soumis à la SEULE passe 3 (valeurs). Ce ne sont pas des documents d'entrée : ils ne
#: disent pas par quoi commencer, on ne leur demande donc ni la convention d'ancres ni la
#: vérification de leurs renvois — `AI_TRAINING.md` cite des dizaines de `fichier.py:ligne` et
#: passerait au rouge le jour où on l'ajouterait à DEFAULT_DOCS, ce qui rendrait le contrôle
#: entier ignorable. Mais il PORTE des valeurs recopiées d'une source mécanique, et une valeur
#: recopiée rouille où qu'elle vive : `obs_size` y est resté à 16 659 face à une source à 16703.
VALUE_ONLY_DOCS = [
    "Documentation/Reference/training/AI_TRAINING.md",
    "Documentation/Reference/training/AI_OBSERVATION.md",
]

@functools.lru_cache(maxsize=1)
def _git_raw_listing() -> str:
    """Sortie brute de `git ls-files -z` — une seule invocation par run."""
    try:
        return subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout
    except subprocess.CalledProcessError as exc:
        raise SourceUnavailable(
            f"git ls-files a échoué (code {exc.returncode}) : {exc.stderr.strip()}"
        ) from exc


#: Arbres du corpus chantiers soumis à la convention d'ancres (passe 4) : les chantiers vivants
#: (`Chantiers/`) et l'archive des chantiers livrés (`Archives/chantiers/`) — exactement la
#: population de l'ex-`Documentation/Implémentation/`, relocalisée par la refonte 2026-08-27.
#: `Reference/` est inclus depuis P2 (2026-08-27) après nettoyage des ancres historiques
#: d'`AI_TRAINING.md` (renvois `fichier:ligne` supprimés).
ANCHOR_TREES = (
    "Documentation/Chantiers/",
    "Documentation/Archives/chantiers/",
    "Documentation/Reference/",
)

#: Documents tenus à la convention « le symbole, jamais la ligne » : les documents d'entrée
#: (DEFAULT_DOCS) et tous les .md des arbres ANCHOR_TREES, par basename. Les documents
#: d'historique comme `archives/ROADMAP.md` restent exclus — un contrôle durablement rouge
#: finit par être ignoré.
def _impl_doc_basenames() -> frozenset[str]:
    """Basenames de tous les .md des arbres ANCHOR_TREES — pour la passe 4.

    Utilise git ls-files plutôt que pathlib.rglob, et sans passer de chemin accentué en
    argument : sous locale C (PYTHONUTF8=0), le codec filesystem est ASCII (le dépôt garde des
    chemins accentués dans Memoire_RNCP/). os.fsencode('é') échoue à la fois dans pathlib
    (is_dir / rglob) et dans subprocess (encodage des argv). git ls-files sans filtre de chemin,
    puis filtrage Python sur la sortie UTF-8 décodée explicitement, contourne les deux pièges
    quelle que soit la locale.
    """
    paths = [
        f for f in _git_raw_listing().split("\0")
        if f.endswith(".md") and any(f.startswith(prefix) for prefix in ANCHOR_TREES)
    ]
    if not paths:
        raise SourceUnavailable(
            f"Aucun fichier .md suivi par git sous {' ni '.join(ANCHOR_TREES)}"
        )
    return frozenset(f.rsplit("/", 1)[-1] for f in paths)

DEFAULT_DOC_NAMES: frozenset[str] = frozenset(
    pathlib.PurePosixPath(doc).name for doc in DEFAULT_DOCS
)


class _Unset:
    pass


_ANCHOR_UNSET = _Unset()


@functools.lru_cache(maxsize=1)
def _get_anchor_enforced() -> frozenset[str]:
    """Calcul paresseux de l'ensemble des basenames soumis à la passe 4."""
    return DEFAULT_DOC_NAMES | _impl_doc_basenames()

AGENT_CONFIG = ROOT / "config" / "agents" / "ArmageddonAgent" / "ArmageddonAgent_training_config.json"
COUVERTURE = DOCS / "analyzer_couverture.md"

#: La RACINE de l'atteignabilité (passe 6). `ROADMAP_INDEX.md` se déclare source unique de l'ordre
#: du travail : un chantier ouvert dont le document ne se rejoint pas depuis lui n'est pas priorisé,
#: il est seulement stocké.
ROADMAP_INDEX = ROOT / "Documentation" / "Roadmap" / "ROADMAP_INDEX.md"

#: Les documents dont l'atteignabilité est EXIGÉE : les chantiers ouverts, à toute profondeur —
#: `backlog/` porte des sous-dossiers (`Database/`, `MCTS/`) et un chantier n'est pas moins ouvert
#: parce qu'il est rangé.
A_FAIRE = DOCS / "backlog"

#: Les arbres par lesquels un renvoi PROPAGE l'atteignabilité : la roadmap et les chantiers
#: ouverts. `Roadmap/archives/` et `Archives/chantiers/` en sont exclus, et c'est le fond de la
#: passe — être cité par l'historique d'un chantier clos prouve exactement le contraire d'être sur
#: la feuille de route. Sans cette borne, un document orphelin redeviendrait vert le jour où une
#: archive le mentionne au passé, et `archives/ROADMAP.md` — cité par l'index lui-même — rendrait
#: à lui seul atteignable tout ce que la roadmap a jamais porté.
LIVE_TREES = (ROOT / "Documentation" / "Roadmap", A_FAIRE)
ARCHIVES = ROOT / "Documentation" / "Roadmap" / "archives"

#: Répertoires où un nom de fichier NU est cherché. `scripts/` en fait partie : son absence a
#: produit une fausse alerte sur `check_ai_rules.py` au premier passage.
SEARCH_DIRS = [
    "", "ai", "ai/analyzer_phases", "engine", "engine/phase_handlers", "engine/utils",
    "shared", "scripts", "services", "config", "tests/unit/ai", "tests/unit/engine",
    "frontend",
]

#: Un chemin peut être relatif AU DOCUMENT (`../../engine/x.py`), absolu, ou nu. La classe de
#: caractères doit donc accepter le point : sans lui, `../../engine/x.py` était capturé comme
#: `/engine/x.py`, que `ROOT / name` transformait en chemin absolu inexistant — 18 fausses
#: alertes sur `V11_phaseA.md` le 2026-08-11, sur un document dont les 9 cibles existaient toutes.
#: `(?!\w)` en queue : sans lui, `hashlib.md5` était capturé comme un fichier `hashlib.md`
#: (mesuré sur `Security.md` le 2026-08-11).
#: Les extensions vivent ici SEULES : `FILE_REF` et `ADJACENT` doivent les reconnaître à
#: l'identique, faute de quoi une affirmation portée par un `.json` est vue par l'un et pas par
#: l'autre — c'est arrivé, l'appariement était resté limité au `.py`.
CODE_SUFFIX = r"(?:py|json|md)"
FILE_REF = re.compile(rf"((?:\.{{1,2}}/)+[\w./-]+\.{CODE_SUFFIX}|[\w/-]+\.{CODE_SUFFIX})(?!\w)")
BACKTICKED = re.compile(r"`([^`]+)`")
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
MD_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

#: `{#id}` explicite — dans un titre ou seul dans la ligne.
_EXPLICIT_ANCHOR = re.compile(r"\{#([^}]+)\}")

#: Ancre HTML `<a id="...">` — employée par le corpus V11 en alternative à `{#id}` GFM.
_HTML_ANCHOR = re.compile(r'<a\s+id="([^"]+)"')

#: Ligne de titre ATX (# à ######), texte jusqu'en fin de ligne.
_MD_HEADING = re.compile(r"^#{1,6} +(.+)$", re.MULTILINE)

#: Bloc code fencé (``` ou ~~~) — son contenu ne doit pas être scanné pour les ancres.
#: Deux alternatives distinctes : un bloc backtick ne peut être fermé que par des backticks,
#: un bloc tilde que par des tildes (CommonMark §4.5 — fence characters must match).
_FENCED_CODE_BLOCK = re.compile(
    r"^`{3,}[^\n]*\n.*?^`{3,}[^\n]*$\n?"
    r"|^~{3,}[^\n]*\n.*?^~{3,}[^\n]*$\n?",
    re.MULTILINE | re.DOTALL,
)

#: Remplace chaque caractère d'un bloc fencé par un espace, en préservant les sauts de ligne
#: pour que la numérotation des lignes reste correcte dans les messages d'erreur.
def _mask_fenced(m: re.Match) -> str:  # type: ignore[type-arg]
    return re.sub(r"[^\n]", " ", m.group(0))


def _read_masked(path: pathlib.Path) -> str:
    """Lit le fichier et masque les blocs fencés."""
    return _FENCED_CODE_BLOCK.sub(_mask_fenced, path.read_text(encoding="utf-8"))


#: Span de code inline — `code` — présent dans les titres comme dans le corps du document.
_INLINE_CODE = re.compile(r"`[^`\n]*`")

#: Une ancre de ligne, quelle que soit l'extension : la convention §5 porte sur la LIGNE, pas sur le
#: langage. Le basename accepte les points internes, sans quoi `useBoardHexMemos.test.ts:117` se
#: réduit à `test.ts` — 25 fichiers `*.test.ts(x)` et 3 `*.d.ts` échappaient à la convention. Et
#: l'extension n'est bornée ni en longueur ni au seul alphanumérique : `.example`, `.errors` et
#: `.code-workspace` sont des extensions RÉELLES de ce dépôt, qu'une borne à 5 caractères écartait
#: en silence alors que la docstring promettait « toute extension ». Le tri, lui, se fait après.
#: `(?<![\w.])` plutôt que `\b`, avec un point initial optionnel : `.env.example:7` était rapporté
#: comme `env.example:7`, qui envoie chercher un fichier que le dépôt ne porte pas sous ce nom.
#: Le CHEMIN est capturé quand il est écrit : `engine/phase_handlers/move_handler.py:99` rapporté
#: comme `move_handler.py:99` désigne cinq fichiers du dépôt au lieu d'un, et n'envoie donc nulle
#: part. Le tri, lui, ne regarde que le basename (cf. `is_a_line_anchor`).
#: LIMITE ASSUMÉE : le chemin ne traverse pas l'espace, donc un renvoi vers un fichier dont le nom
#: en porte (`Documentation/40k_rules/09 Movement phase.pdf:12`) est bien DÉTECTÉ, mais rapporté
#: sous son dernier segment. Autoriser l'espace ferait avaler la phrase autour du chemin dans tous
#: les autres cas — un message tronqué vaut mieux qu'un message inventé.
#: L'extension est OPTIONNELLE : `Dockerfile:14` est un renvoi de ligne comme un autre, et
#: `Security.md` — document sous convention — cite justement les deux `Dockerfile` du dépôt. Sans
#: extension, seul le critère de dépôt s'applique (cf. `is_a_line_anchor`), ce qui écarte les
#: `Note:12` et autres deux-points de prose.
LINE_ANCHOR = re.compile(
    r"(?<![\w.])((?:[\w.-]+/)*\.?[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*):(\d+)"
)

#: Les DEUX autres graphies du même renvoi, employées par ce corpus : `L7370` et `(l.3713-3735)`.
#: Ne contrôler que `fichier.ext:123`, c'était appliquer la convention à une graphie sur trois — et
#: les deux autres étaient vivantes dans `ROADMAP.md` au 2026-08-12.
#:
#: La graphie `Ln` est AMBIGUË, et irréductiblement : `L1`, `L11`, `L28` NOMMENT les entrées du
#: `step.log`, backtiquées en prose mais NUES dans les cellules du tableau §7 — 34 occurrences
#: mesurées. Ni le backtick ni un seuil de chiffres écrit en dur ne les séparent d'un numéro de
#: ligne : la suite GRANDIT, et un seuil devenu faux rendrait le contrôle rouge sur un document
#: juste. Le départage est donc DONNÉ PAR LE CORPUS — `step_log_entries` connaît le plus grand
#: index existant, et il grandit avec lui (cf. `is_a_bare_anchor`).
#: Le `-` est exclu du voisinage gauche pour les noms de modèle (`ViT-L336`).
BARE_ANCHOR = re.compile(r"(?<![\w.-])(?:L(\d+)|l\.(\d+))\b")

#: `def X` / `class X` backtiqués : la seule forme par laquelle ces documents PROMETTENT un grep.
#: La signature est tolérée (`def X(a, b) -> int`, `class X(Base)`, `class X:`) : exiger le backtick
#: collé au nom laissait la citation la plus courante DÉSARMER la passe en silence — ni vérifiée, ni
#: comptée non vérifiée, sous un rapport « 0 fausse, 0 non vérifiée ». Le tail est borné à ce qui
#: OUVRE une signature — une parenthèse, ou le deux-points COLLÉ au nom. Laisser le deux-points
#: ouvrir n'importe quoi tenait `class Objectives : la liste des objectifs` pour une citation ferme
#: et sortait un SYMBOLE NON DÉFINI sur une phrase juste. `async def X` est la même citation : la
#: refuser rendait le traitement d'`AsyncFunctionDef` par `definitions` inatteignable, donc
#: mensonger. Le nom accepte la QUALIFICATION (`def W40KEngine.execute_action`) : sans elle, la
#: citation ne tombait dans aucun compteur — ni vérifiée, ni non vérifiée.
SYMBOL_KIND = re.compile(
    r"`(?:async[ \t]+)?(def|class)[ \t]+"
    r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)(?:\([^`]*)?:?`"
)

#: La citation et son fichier, DANS LES DEUX ORDRES — `def X` (`a/b.py`) comme `a/b.py` (`def X`),
#: qui est celui de la passe 1 (cf. `ADJACENT`). N'en traiter qu'un, c'était laisser le défaut
#: d'origine passer intégralement dès qu'il était écrit dans l'autre sens ; la passe 1 ne le
#: rattrape pas non plus, `is_symbol_token` refusant l'espace de « def Foo ».
#:
#: UN SEUL LIEN les apparie, et il est FERMÉ : la parenthèse qui se referme, ou le deux-points. La
#: simple juxtaposition est écartée dans les deux sens, parce qu'elle ne se distingue pas d'une
#: phrase qui continue — `class X` `a/b.py` l'importe de SB3 — et la tenir pour ferme sortait un
#: SYMBOLE NON DÉFINI, donc un code 1, sur une phrase juste. C'est la distinction ferme/molle de la
#: passe 1, appliquée symétriquement : ce qui est molle d'un côté ne peut pas être ferme de l'autre.
#: La parenthèse se referme ; le deux-points, lui, n'a pas de fin — c'est le lecteur qui la met. Il
#: n'affirme donc que s'il TERMINE la ligne : `a.py` : `class X` est importé de SB3, pas défini ici
#: est une phrase, et la tenir pour ferme sortait un code 1 dessus, quand la même phrase entre
#: parenthèses était correctement comptée non vérifiée. Le verdict ne peut pas dépendre de la
#: ponctuation. C'est la garde de pureté de `claimed_symbols`, transposée à une forme sans clôture.
_END = r"(?=[ \t.,;)]*$)"
_PY_TOKEN = r"`((?:\.{1,2}/)*[\w/-]+\.py)`"
KIND_CLAIM = re.compile(
    SYMBOL_KIND.pattern
    + rf"[ \t]*(?:\([ \t]*{_PY_TOKEN}[ \t]*\)|:[ \t]*{_PY_TOKEN}{_END})"
)
KIND_CLAIM_REVERSED = re.compile(
    _PY_TOKEN
    + rf"[ \t]*(?:\([ \t]*{SYMBOL_KIND.pattern}[ \t]*\)|:[ \t]*{SYMBOL_KIND.pattern}{_END})"
)

#: Un renvoi générique (`*_handler.py`, `analyzer_phases/*`) ne désigne aucun fichier précis : il
#: n'y a rien à résoudre, et le compter en échec ferait du bruit là où le document est correct.
WILDCARD = re.compile(r"[*]")

#: La bosse de casse d'un identifiant composé (`SummaryWriter`, `GameClient`, `XMLHttpRequest`).
#: `token != token.lower()` ne suffisait pas : il tenait `False` et `Objectives` pour des symboles.
CASE_HUMP = re.compile(r"[a-z][A-Z]")

#: Suffixes qu'une cible de lien doit porter pour être tenue pour un chemin. Un lien vers un
#: répertoire (`v11/`) est reconnu par sa barre finale.
LINK_SUFFIXES = (".md", ".py", ".json", ".pdf", ".txt", ".sh", ".ts", ".tsx", ".png")

#: Un fragment `#L123` ne désigne pas un titre mais une LIGNE. La passe 4 le rapporte déjà sous son
#: propre message ; le confronter aux titres sortirait « ancre morte » et enverrait chercher un
#: titre là où le document cite une ligne.
FRAGMENT_LINE = re.compile(r"L\d+(?:-L\d+)?")

#: Les deux verdicts de la passe 2, NOMMÉS ici parce que le rapport les recompte : agréger l'ancre
#: morte sous « liens morts » annoncerait un fichier disparu là où seul un titre a bougé.
DEAD_LINK = "LIEN MORT"
DEAD_ANCHOR = "ANCRE MORTE"

#: Caractères qu'aucun chemin de ce dépôt ne porte. Leur présence signe un faux positif de regex
#: (`[^"\']+` cité en prose), écarté par la FORME et non par une liste de cas nommés.
NOT_A_PATH = set("\"'^\\<>*?|`{}$ ")


def resolve(name: str, doc_dir: pathlib.Path) -> pathlib.Path | None:
    """Le fichier cité, ou None. Trois formes, dans l'ordre où le dépôt les emploie."""
    if name.startswith("./") or name.startswith("../"):
        candidate = (doc_dir / name).resolve()
        return candidate if candidate.exists() else None
    if name.startswith("/"):
        # Convention CLAUDE.md : les liens vers le code sont ABSOLUS. Un absolu qui n'existe pas
        # est un renvoi cassé, pas un relatif à réessayer depuis la racine — réessayer serait un
        # repli qui rendrait vert un chemin faux.
        candidate = pathlib.Path(name)
        return candidate if candidate.exists() else None
    # Deux conventions COEXISTENT dans ce corpus, et les deux sont légitimes : un lien entre
    # documents est relatif AU DOCUMENT (`v11/V11_phaseA.md`), un renvoi vers le code est
    # relatif à la RACINE (`engine/w40k_core.py`). Essayer les deux n'est pas un repli qui
    # masquerait une erreur : c'est résoudre dans les deux systèmes que le dépôt emploie.
    if "/" in name:
        for candidate in (doc_dir / name, ROOT / name):
            if candidate.exists():
                return candidate
        return None
    # Un nom NU adjacent au document est le lien le plus courant du corpus roadmap
    # (`[bot.md#etape8](bot.md)` entre fichiers sujets) : la sémantique markdown le résout chez
    # le document, et l'adjacence IDENTIFIE — le voisin prime sur toute recherche par répertoire.
    # Sans cette branche, chaque lien interne de `ROADMAP_INDEX.md` sortait FICHIER INTROUVABLE
    # + LIEN MORT (41 fois au premier passage du corpus partitionné, 2026-08-18).
    adjacent = doc_dir / name
    if adjacent.exists():
        return adjacent
    for directory in SEARCH_DIRS:
        candidate = ROOT / directory / name if directory else ROOT / name
        if candidate.exists():
            return candidate
    # Un nom NU renvoie couramment à un document rangé dans un sous-dossier (`V11_tranches.md`),
    # à une référence vivante (`verticalite.md`) ou à une configuration d'agent
    # (`ArmageddonAgent_training_config.json`). Ces arbres sont petits : on les parcourt plutôt
    # que d'énumérer à la main des chemins qui bougeront.
    for tree in (DOCS, ROOT / "Documentation" / "Reference", ROOT / "config"):
        found = next(tree.rglob(name), None)
        if found is not None:
            return found
    return None


@functools.lru_cache(maxsize=1)
def tracked_basenames() -> collections.Counter[str]:
    """Combien de fichiers SUIVIS portent chaque nom. Une seule invocation de git par run.

    `-z` n'est pas un détail : sans lui, git échappe les octets non-ASCII et ENTOURE le chemin de
    guillemets (les chemins accentués de `Memoire_RNCP/`, et 73 chemins au moment de la mesure,
    tout l'ex-`Documentation/Implémentation/` en tête). Le basename
    en sortait avec son guillemet collé, sous une clé que personne n'interroge — l'ambiguïté de ces
    fichiers-là n'aurait jamais été vue. Même piège que `core.quotePath` dans
    `scripts/check_roadmap_declared.py`, qui l'a payé le 2026-08-11.
    """
    return collections.Counter(
        f.rsplit("/", 1)[-1] for f in _git_raw_listing().split("\0") if f
    )


def is_ambiguous(name: str) -> bool:
    """Ce nom NU désigne-t-il plusieurs fichiers du dépôt ?

    `conftest.py` existe cinq fois. L'ordre de recherche de `resolve` est une convention
    d'EXISTENCE — il rend le premier trouvé — et ne vaut pas identification : confronter des
    symboles au fichier qu'il désigne, c'est interroger un fichier dont le document ne parle pas.
    Mesuré : `conftest.py` : `GameClient` sortait en AUCUN SYMBOLE, le symbole étant défini dans
    l'autre `conftest.py`. Le renvoi est donc compté INVÉRIFIABLE, jamais cassé.
    """
    return "/" not in name and tracked_basenames()[name] > 1


@functools.lru_cache(maxsize=1)
def tracked_suffixes() -> frozenset[str]:
    """Les extensions que le dépôt emploie RÉELLEMENT, mesurées, jamais énumérées à la main.

    Une liste écrite à la main se périme : celle du 2026-08-12 ignorait `.rs`, `.sql`, `.html` et
    `.css`, tous porteurs d'ancres dans le corpus. Le dépôt sait ce qu'il contient ; lui demander
    coûte le `git ls-files` déjà fait pour les basenames.
    """
    return frozenset(
        "." + name.rsplit(".", 1)[-1] for name in tracked_basenames() if "." in name[1:]
    )


def is_a_bare_anchor(index: int) -> bool:
    """`L<index>` est-il un numéro de ligne, ou un NOM d'entrée du `step.log` ?

    Le seul repère non arbitraire est le corpus lui-même : le tableau §7 d'`analyzer_couverture.md`
    énumère les entrées existantes, donc tout ce qui dépasse son plus grand index est un numéro de
    ligne. Le seuil grandit avec la table, là où un seuil écrit en dur serait devenu faux le jour où
    la suite passe la centaine — et aurait alors rendu rouge un document juste.

    LIMITE ASSUMÉE, et elle vaut pour les trois documents : sous ce seuil, `L18` n'est pas
    opposable, même dans un document qui ne parle pas du `step.log`. Rien dans la FORME ne sépare
    un nom d'entrée d'un petit numéro de ligne, et il n'y a pas de troisième critère : refuser
    reviendrait à rendre rouge le §7 lui-même. Les renvois de cette taille restent attrapés par la
    graphie `fichier.ext:ligne`, qui, elle, nomme son fichier.
    """
    return index > step_log_entries()[1]


def is_a_line_anchor(basename: str) -> bool:
    """Ce `nom:123` est-il un renvoi de ligne à refuser ?

    DEUX critères, en OU, et chacun ferme ce que l'autre laisse ouvert :
      - le nom est celui d'un fichier SUIVI du dépôt. Seul moyen d'atteindre les extensions rares :
        `docker-compose.yml:18` vivait dans `Security.md`, invisible ;
      - son extension est employée quelque part dans le dépôt. Indispensable, parce que le motif
        n°1 de rouille d'une ancre est justement que son fichier ait été RENOMMÉ ou SUPPRIMÉ :
        `engine/ancien.py:412` n'est plus suivi, et le critère de dépôt seul le rendait muet — la
        passe aurait perdu sa cible principale.

    COÛT ASSUMÉ : une version écrite avec un deux-points (`Node.js:20`) porte exactement la forme
    d'une ancre et sera refusée. Le corriger tient dans une espace ; manquer l'ancre d'un fichier
    supprimé, non.
    """
    if tracked_basenames()[basename] > 0:
        return True
    if "." not in basename[1:]:
        # Sans extension, il ne reste RIEN à opposer : un jeton nu suivi de `:12` est le plus
        # souvent de la prose (`Note:12`). Seul le critère de dépôt, déjà tenté, pouvait trancher.
        return False
    return "." + basename.rsplit(".", 1)[-1] in tracked_suffixes()


def symbol_is_present(symbol: str, body: str) -> bool:
    """Le symbole vit-il dans ce fichier, littéralement ou COMPOSÉ ?

    Plusieurs compteurs ne sont jamais écrits en toutes lettres : `analyzer_hit` écrit
    ``stats[f"{key}_mismatch"]`` et `analyzer_wound` fait de même. Chercher le nom complet
    (`shoot_hit_result_mismatch`) rend alors 0 hit sur un document pourtant juste — première
    cause de fausse alerte du contrôle d'origine. On accepte donc aussi le suffixe composé, à
    partir d'une frontière `_` et d'une longueur qui exclut les fragments passe-partout.
    """
    if symbol in body:
        return True
    parts = symbol.split("_")
    for start in range(1, len(parts)):
        suffix = "_" + "_".join(parts[start:])
        if len(suffix) >= 8 and f'"{{key}}{suffix}"' in body:
            return True
        if len(suffix) >= 8 and f"'{{key}}{suffix}'" in body:
            return True
    return False


def fragments(line: str) -> tuple[list[str], bool]:
    """Morceaux de ligne à traiter INDÉPENDAMMENT, et si l'appariement est permis.

    Une ligne de tableau cite souvent plusieurs fichiers et plusieurs symboles qui ne vont pas
    ensemble ; les apparier tous avec tous fabrique des affirmations que le document n'a jamais
    faites. On découpe donc par cellule.

    Le booléen rendu n'autorise QUE cette CO-OCCURRENCE de cellule — « un fichier de la cellule
    porte un symbole de la cellule ». Les affirmations adjacentes (`fichier.py` (`sym`)), elles,
    valent partout : c'est le document qui les écrit, pas la mise en page qui les crée.
    En PROSE, rien d'autre n'est apparié, même quand la phrase ne cite qu'un fichier : mesuré le
    2026-08-11, les quatre tentatives d'appariement large en prose d'`analyzer_couverture.md`
    étaient toutes fausses (une phrase cite `check_ai_rules.py` et, plus loin, `pyright` et
    `biome`, qui n'ont rien à y faire). Un contrôle qui crie à tort finit désactivé ; ces cas
    sont comptés comme non vérifiés.
    """
    if line.lstrip().startswith("|"):
        return line.split("|"), True
    return [line], False


def names_in(cell: str) -> list[str]:
    # `{move,charge,fight}_handler.py` désigne un ENSEMBLE, comme le joker : le fragment capturé
    # (`_handler.py`) n'est le nom d'aucun fichier. Même famille que la garde sur `*`.
    found = [
        m.group(1) for m in FILE_REF.finditer(cell)
        if not (m.start() and cell[m.start() - 1] in "*,{}")
    ]
    return [n for n in dict.fromkeys(found) if not WILDCARD.search(n)]


def is_symbol_token(token: str) -> bool:
    """Ce jeton backtiqué a-t-il la FORME d'un symbole ?

    Un identifiant ENTIER (ni chemin, ni joker, ni appel pointé, ni `debug=False`) portant un `_`
    ou une BOSSE de casse — une majuscule précédée d'une minuscule, comme `SummaryWriter` ou
    `GameClient`. Le critère est de FORME, jamais une liste de mots exclus ; mesuré sur le corpus,
    il écarte `directory`, `leader`, `os.system`, et aussi les mots simplement CAPITALISÉS
    (`False`, `Objectives`, `CORS`), qui se retrouvent dans n'importe quel fichier et
    confirmeraient n'importe quoi. Il garde `_safe_loads`, `SummaryWriter`, `W40K_PERSIST_DIR`.
    Il COÛTE les symboles d'un seul mot sans bosse ni `_` (`reset`, `CORS`), comptés invérifiables :
    sous-affirmer et l'afficher est la doctrine de ce module, fabriquer une confirmation ne l'est
    pas.
    """
    return bool(IDENTIFIER.fullmatch(token)) and ("_" in token or bool(CASE_HUMP.search(token)))


def symbols_in(cell: str) -> list[str]:
    """Les symboles d'une CELLULE, qu'aucune forme n'attache à un fichier précis.

    Même critère qu'une affirmation adjacente : le tableau acceptait tout identifiant tiré d'un
    fragment backtiqué, et confirmait 8 renvois du corpus sur des MOTS (`False`, `CORS`, `leader`,
    `Objectives`) pendant que la prose, elle, les refusait déjà. Une même phrase ne peut pas
    changer de verdict selon qu'elle est écrite entre deux barres verticales.
    """
    tokens = [raw.strip() for raw in BACKTICKED.findall(cell)]
    return list(dict.fromkeys(t for t in tokens if is_symbol_token(t)))


#: `fichier.py` (`sym`, `sym2`) ou `fichier.py` : `sym`, `sym2` — la forme par laquelle ce corpus
#: DIT « ce symbole vit dans ce fichier ». C'est une affirmation adjacente, donc appariable même en
#: prose, là où apparier toute la ligne rendait 4 fausses alertes sur 4.
#: `(?:\.{1,2}/)*` et non `?` : un renvoi remonte couramment plusieurs niveaux
#: (`../../../engine/x.py`). Avec `?` le chemin était TRONQUÉ, ne se résolvait plus, et la
#: citation disparaissait de tous les compteurs à la fois — un vert vacant, mesuré le 2026-08-11.
#: Après `:`, la liste ENTIÈRE est captée (`a`, `b` — pas seulement `a`), et AUCUN de ses jetons
#: ne peut porter un `/` ou un `.` : `train.py` : `engine/x.py` (`sym`) n'affirme rien sur
#: `train.py`, et l'avaler consommait l'affirmation réelle qui suivait (mesuré). La contrainte
#: porte sur CHAQUE jeton, pas sur le premier : le chemin arrive aussi en deuxième position.
ADJACENT = re.compile(
    rf"`?((?:\.{{1,2}}/)*[\w/-]+\.{CODE_SUFFIX})`?\s*"
    r"(?:\((?P<par>[^)]*)\)"
    r"|:\s*(?P<col>`[^`/.]+`(?:\s*,\s*`[^`/.]+`)*))"
)


def claimed_symbols(blob: str) -> tuple[list[str], bool]:
    """(symboles affirmés, l'affirmation est-elle FERME ?).

    Une LISTE PURE — que des symboles et leurs séparateurs — est une affirmation ferme : le
    document dit que ce fichier porte ces symboles, leur absence est une erreur. Un symbole noyé
    dans une phrase (« (`_safe_loads` en aval) », « (par exemple quand `x` survient) ») affirme
    beaucoup moins : sa présence confirme le renvoi, son absence ne prouve rien. Rendre l'un et
    l'autre rouges ferait crier le contrôle sur des phrases correctes, et un contrôle qui crie à
    tort finit désactivé — c'est la raison pour laquelle la prose n'était pas appariée du tout.
    """
    tokens = [raw.strip() for raw in BACKTICKED.findall(blob)]
    kept = [t for t in tokens if is_symbol_token(t)]
    around = BACKTICKED.sub("", blob)
    firm = len(kept) == len(tokens) and not re.search(r"[^\W\d_]", around)
    return list(dict.fromkeys(kept)), firm


def adjacent_pairs(line: str) -> list[tuple[str, list[str], bool]]:
    """(fichier, symboles, affirmation ferme) que la ligne affirme, quelle que soit sa forme."""
    # Un fichier que l'extracteur général ne rend pas (`*_handler.py`, `{move,charge}_handler.py`)
    # ne peut pas porter d'affirmation : il ne sera jamais résolu. Filtrer sur `names_in` rend
    # l'inclusion STRUCTURELLE au lieu de recopier ici ses gardes, qui ont déjà divergé une fois.
    names = names_in(line)
    pairs: list[tuple[str, list[str], bool]] = []
    for match in ADJACENT.finditer(line):
        name = match.group(1)
        if name not in names:
            continue
        symbols, firm = claimed_symbols(match.group("par") or match.group("col") or "")
        if symbols:
            pairs.append((name, symbols, firm))
    return pairs


def check_references(doc_path: pathlib.Path) -> tuple[int, int, list[str]]:
    """Passe 1 — les fichiers cités existent, les symboles cités y vivent."""
    doc_dir = doc_path.parent
    resolved = unverifiable = 0
    broken: list[str] = []
    for lineno, line in enumerate(_read_masked(doc_path).split("\n"), 1):
        cells, cooccurrence_allowed = fragments(line)
        for cell in cells:
            names = names_in(cell)
            if not names:
                continue
            found: dict[str, pathlib.Path] = {}
            for name in names:
                path = resolve(name, doc_dir)
                if path is None:
                    broken.append(f"{doc_path.name}:{lineno}  FICHIER INTROUVABLE  {name}")
                else:
                    found[name] = path
            present = list(found)
            if not present:
                continue
            # 1. Les affirmations ADJACENTES — `fichier.py` (`a`, `b`) — valent dans les DEUX
            # formes de ligne : la même phrase dit la même chose entre deux barres verticales que
            # dans un paragraphe. C'est la preuve la plus forte du corpus, et la laisser au régime
            # mou des cellules revenait à la perdre là où elle est la plus dense.
            # L'appariement se fait sur le chemin ENTIER, jamais sur le nom de fichier nu : un
            # fragment cite couramment `../engine/x.py` (faux depuis ce doc) puis `engine/x.py`
            # (juste), et un rapprochement par basename attribuait au premier le fichier du second.
            # Un même fichier peut être cité deux fois : les symboles se cumulent sur UN renvoi,
            # ils n'en fabriquent pas deux. Fermes et molles restent séparées : une phrase ne doit
            # pas pouvoir amollir l'affirmation ferme du même fichier.
            claimed: dict[str, tuple[list[str], list[str]]] = {}
            # Un symbole que le fragment attribue à UN fichier n'est plus à la disposition des
            # autres, même quand ce fichier-là s'avère inconfrontable (nom ambigu, renvoi cassé) :
            # l'attribution est un fait du DOCUMENT, elle ne dépend pas de ce que la machine sait
            # en faire. Sans ça, `conftest.py` (`GameClient`), `w40k_core.py` rendait le second
            # rouge pour un symbole que la cellule donne explicitement au premier.
            pairs = adjacent_pairs(cell)
            attributed = {s for _name, syms, _firm in pairs for s in syms}
            for name, symbols, firm in pairs:
                if name in found and not is_ambiguous(name):
                    buckets = claimed.setdefault(name, ([], []))
                    bucket = buckets[0] if firm else buckets[1]
                    bucket += [s for s in symbols if s not in bucket]
            for name, (firm_symbols, soft_symbols) in claimed.items():
                body = found[name].read_text(encoding="utf-8", errors="replace")
                # `x.py` (`a`, `b`) affirme les DEUX symboles : il suffit qu'UN manque pour que le
                # document soit faux. Se contenter d'un `any`, c'était laisser un seul jeton encore
                # vivant confirmer la citation entière et masquer la suppression de l'autre — le
                # vert vacant, cette fois côté symboles. Le message nomme les ABSENTS, seuls à
                # corriger.
                absent = [s for s in firm_symbols if not symbol_is_present(s, body)]
                if absent:
                    broken.append(
                        f"{doc_path.name}:{lineno}  SYMBOLE ABSENT de {name} — "
                        f"introuvable(s) : {', '.join(absent[:4])}"
                    )
                elif firm_symbols or any(symbol_is_present(s, body) for s in soft_symbols):
                    resolved += 1
                else:
                    # Affirmation molle démentie : la phrase n'a peut-être jamais dit que ce
                    # symbole vivait là. Rien de prouvé, rien de faux — compté, pas crié.
                    unverifiable += 1
            # 2. Ce qui reste : les fichiers du fragment qu'aucune affirmation adjacente ne porte
            # — paire absente, nom ambigu, ou capture `ADJACENT` que `FILE_REF` ne rend pas
            # (divergence verrouillée par `test_adjacent_is_a_subset`). Jamais escamotés.
            rest = [n for n in present if n not in claimed]
            if not rest:
                continue
            if not cooccurrence_allowed:
                # En prose, seule l'ADJACENCE fait foi. Le reste de la phrase peut citer n'importe
                # quoi d'autre sans que le document l'affirme : mesuré le 2026-08-11, les quatre
                # tentatives d'appariement en prose d'`analyzer_couverture.md` étaient fausses.
                unverifiable += len(rest)
                continue
            # Un nom ambigu ne dit pas DE QUEL fichier la cellule parle : il ne peut porter
            # aucune confrontation, ici comme en prose. Il reste compté, jamais confronté.
            sure = [n for n in rest if not is_ambiguous(n)]
            unverifiable += len(rest) - len(sure)
            # `a.py` (1186 l.), `b.py` (`_sym`), `c.py` : la cellule affirme `_sym` de `b.py`, et
            # rien du tout de `a.py` ni de `c.py`. Opposer `_sym` à ces deux-là les rendait rouges
            # pour un symbole que le document attribue explicitement ailleurs.
            symbols = [s for s in symbols_in(cell) if s not in attributed]
            if not (sure and symbols):
                unverifiable += len(sure)
                continue
            # UN renvoi est confirmé dès qu'UN des fichiers de la cellule porte UN des symboles
            # de la cellule. Exiger que CHAQUE fichier les porte tous serait une affirmation que
            # le document ne fait pas : une cellule cite couramment le producteur ET le lecteur
            # d'une donnée, dont les symboles ne vivent que d'un côté.
            bodies = [found[n].read_text(encoding="utf-8", errors="replace") for n in sure]
            if any(symbol_is_present(s, b) for s in symbols for b in bodies):
                resolved += len(sure)
            else:
                broken.append(
                    f"{doc_path.name}:{lineno}  AUCUN SYMBOLE dans {', '.join(sure)} — "
                    f"cherchés : {', '.join(symbols[:4])}"
                )
    return resolved, unverifiable, broken


def looks_like_path(target: str) -> bool:
    if not target or target[0] == "#":
        return False
    if target.startswith(("http://", "https://", "mailto:")):
        return False
    if NOT_A_PATH & set(target):
        return False
    return target.endswith("/") or target.endswith(LINK_SUFFIXES)


def _heading_slug(text: str) -> str:
    r"""Titre markdown → fragment GFM (slug).

    Ordre : supprimer le `{#id}` explicite et les spans de code ; mettre en minuscules ;
    retirer tout ce qui n'est ni lettre/chiffre/underscore/tiret (`\w`), ni espace ; remplacer
    les espaces par des tirets. Les lettres accentuées sont des lettres (`\w` Unicode).
    """
    text = _EXPLICIT_ANCHOR.sub("", text)
    text = _INLINE_CODE.sub(lambda m: m.group(0)[1:-1], text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s+", "-", text.strip())


@functools.lru_cache(maxsize=128)
def md_anchors(path: pathlib.Path) -> frozenset[str]:
    """Ancres réelles d'un fichier `.md` : slugs des titres + `{#id}` explicites.

    Quand un titre porte un `{#id}` explicite, c'est cet id qui fait foi — le slug calculé
    depuis le texte du titre N'EST PAS ajouté (il n'est pas l'ancre rendue). Les `{#id}` hors
    titre (ancrages isolés dans le corps du document) sont également collectés.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    text_no_code = _FENCED_CODE_BLOCK.sub("", text)
    # Inline code spans masquent les {#id} qu'ils contiennent — idem pour le scan body.
    text_no_inline = _INLINE_CODE.sub("", text_no_code)
    result: set[str] = set()
    for m in _MD_HEADING.finditer(text_no_code):
        heading = m.group(1).strip()
        explicit = _EXPLICIT_ANCHOR.search(_INLINE_CODE.sub("", heading))
        if explicit:
            result.add(explicit.group(1))
        else:
            result.add(_heading_slug(heading))
    for m in _EXPLICIT_ANCHOR.finditer(text_no_inline):
        result.add(m.group(1))
    for m in _HTML_ANCHOR.finditer(text_no_inline):
        result.add(m.group(1))
    return frozenset(result)


def check_links(doc_path: pathlib.Path) -> tuple[int, int, int, list[str]]:
    """Passe 2 — les cibles des liens markdown existent et leurs fragments sont des ancres réelles.

    Le fragment n'est pas un ornement de ce corpus : 45 des 48 liens en portent un (mesuré le
    2026-08-18), et tous désignent un titre d'un fichier sujet. Coupé et jeté avant résolution, il
    laissait un titre renommé garder son lien vert — le fichier, lui, existait toujours, et c'était
    tout ce que la passe regardait. Le nombre de fragments CONFRONTÉS est donc rendu à part : sans
    lui, « 0 ancre morte » ne distingue pas un corpus sain d'une passe qui ne regarde plus rien.


    Les liens `file:///` sont ABSOLUS par convention CLAUDE.md : ils sont vérifiés comme tels,
    et non écartés — c'est ce que faisait le contrôle manuel, qui ne les regardait donc jamais.

    Les fragments (`#ancre`) sont confrontés aux ancres effectives du fichier cible lorsque
    celui-ci est un `.md` : titres ATX (slugifiés selon GFM) et `{#id}` explicites. Les fragments
    sur les autres types de fichiers (p. ex. `#L629` sur un `.py`) ne sont pas vérifiés — ils
    suivent une convention de ligne, pas une convention d'ancre de document. La graphie `#L123` est
    écartée MÊME sur un `.md` : c'est un renvoi de ligne, que la passe 4 rapporte déjà sous son
    propre message ; le confronter aux titres enverrait chercher un titre là où le document cite
    une ligne, et compterait deux fois un seul défaut.
    """
    doc_dir = doc_path.parent
    checked = skipped = fragments = 0
    broken: list[str] = []
    for lineno, line in enumerate(_read_masked(doc_path).split("\n"), 1):
        for raw in MD_LINK.findall(line):
            parts = raw.split("#", 1)
            target = urllib.parse.unquote(parts[0]).strip()
            fragment = urllib.parse.unquote(parts[1]) if len(parts) > 1 else ""
            if target.startswith("file://"):
                target = target[len("file://"):]
            if not looks_like_path(target):
                skipped += 1
                continue
            checked += 1
            resolved = resolve(target.rstrip("/"), doc_dir)
            if resolved is None:
                broken.append(f"{doc_path.name}:{lineno}  {DEAD_LINK}  {target}")
                continue
            if not fragment or FRAGMENT_LINE.fullmatch(fragment) or resolved.suffix != ".md":
                continue
            fragments += 1
            if fragment not in md_anchors(resolved):
                broken.append(f"{doc_path.name}:{lineno}  {DEAD_ANCHOR}  {target}#{fragment}")
    return checked, skipped, fragments, broken


def agent_profiles() -> dict[str, dict]:
    """Les profils d'entraînement de l'agent, source de vérité des nombres recopiés."""
    data = json.loads(AGENT_CONFIG.read_text(encoding="utf-8"))
    return {key: value for key, value in data.items() if isinstance(value, dict)}


@functools.lru_cache(maxsize=1)
def step_log_entries() -> tuple[int, int]:
    """(nombre d'entrées ACTIVES, plus grand index TOUS) du tableau §7 d'`analyzer_couverture`.

    count = entrées non barrées (encore ouvertes) — sert à vérifier les décomptes dans la roadmap.
    largest = index max toutes entrées confondues (y compris barrées) — sert à `is_a_bare_anchor`
    pour ne pas traiter un nom d'entrée livré comme un numéro de ligne.
    """
    text = COUVERTURE.read_text(encoding="utf-8")
    section = re.search(r"^## 7\..*?(?=^## 8\.)", text, re.S | re.M)
    if section is None:
        raise SourceUnavailable("analyzer_couverture.md : §7 introuvable")
    active = sorted({int(m) for m in re.findall(r"^\|\s*`?L(\d+)`?\s*\|", section.group(0), re.M)})
    all_idx = sorted({int(m) for m in re.findall(r"^\|\s*(?:~~)?`?L(\d+)`?(?:~~)?\s*\|", section.group(0), re.M)})
    if not all_idx:
        raise SourceUnavailable("analyzer_couverture.md : §7 ne porte aucune entrée `Ln`")
    return len(active), max(all_idx)


def integers_in(cell: str) -> list[int]:
    """Les entiers d'une cellule, séparateur de milliers compris (« 10 000 » vaut 10000)."""
    return [int(m.group(0).replace(" ", "").replace(" ", "").replace("\xa0", ""))
            for m in re.finditer(r"\d[\d  \xa0]*\d|\d", cell)]


def claim_profile_count(text: str) -> list[tuple[str, int]]:
    return [(m.group(0).strip(), int(m.group(1)))
            for m in re.finditer(r"\*\*(\d+)\*\*\s*profils", text)]


def claim_n_envs(text: str) -> list[tuple[str, int]]:
    return [(m.group(0).strip(), int(m.group(1))) for m in re.finditer(r"(\d+)\s+envs\b", text)]


#: Les séparateurs de milliers employés par ce corpus, en ESCAPES. Écrits en clair dans le
#: motif, trois d'entre eux sont des caractères invisibles indistinguables à la relecture — et
#: c'est ainsi que la fine insécable a été oubliée à la première rédaction de ce contrôle.
_THOUSANDS_SEPARATORS = "\u0020\u202f\u2009\u00a0"

#: Un entier en gras, séparateur de milliers compris : `**16703**` comme `**16 659**`. Le motif
#: refuse toujours un nombre court (`**8**`, `**12**`), qui sur ces lignes désigne un nombre de
#: slots et jamais une taille d'observation.
_BOLD_INTEGER = rf"(\d{{4,}}|\d{{1,3}}(?:[{_THOUSANDS_SEPARATORS}]\d{{3}})+)"


def claim_obs_size(text: str) -> list[tuple[str, int]]:
    """Les valeurs d'`obs_size` annoncées par un document.

    Le séparateur de milliers n'est pas un ornement : borné à `\\d{4,}`, ce motif ne voyait pas
    `**16 659**`, et c'est précisément la graphie qu'employait `AI_TRAINING.md`. Sa valeur y est
    restée à 16 659 pendant que la source calculée disait 16703 — le document le plus lu du
    dépôt sur ce sujet, faux, sous un contrôle vert qui regardait ailleurs.
    """
    found = [(m.group(0).strip(), integers_in(m.group(1))[0])
             for m in re.finditer(rf"`obs_size`[^\n]*?\*\*{_BOLD_INTEGER}\*\*", text)]
    found += [(m.group(0).strip(), int(m.group(1)))
              for m in re.finditer(r'`"obs_size":\s*(\d+)`', text)]
    return found


def claim_profile_table(text: str) -> list[tuple[str, int]]:
    """Les cases du tableau `profil | total_episodes | bot_eval_final` de §1.

    Ancré sur le NOM du profil, seul repère qui survive à une reformulation : la ligne peut
    porter du gras, une parenthèse d'historique ou un séparateur de milliers sans se dérober.
    """
    known = set(agent_profiles())
    claims: list[tuple[str, int]] = []
    for line in text.split("\n"):
        if not line.lstrip().startswith("|"):
            continue
        cells = line.split("|")
        if len(cells) < 4:
            continue
        name = cells[1].strip().strip("`*").strip()
        if name not in known:
            continue
        episodes = integers_in(cells[2])
        final = integers_in(cells[3])
        if episodes:
            claims.append((f"{name}.total_episodes", episodes[0]))
        if final:
            claims.append((f"{name}.bot_eval_final", final[0]))
    return claims


def claim_step_log(text: str) -> list[tuple[str, tuple[str, int]]]:
    found = [(m.group(0).strip(), ("count", int(m.group(1))))
             for m in re.finditer(r"\*\*(\d+)\*\*\s*entrées", text)]
    found += [(m.group(0).strip(), ("max", int(m.group(1))))
              for m in re.finditer(r"`L1`,\s*puis\s*`L3`\s*→\s*`L(\d+)`", text)]
    return found


def claim_gate_ceiling(text: str) -> list[tuple[str, int]]:
    return [(m.group(0).strip(), int(m.group(1)))
            for m in re.finditer(r"refusée quand \*\*(\d+)\*\* chantiers", text)]


@functools.lru_cache(maxsize=1)
def gate_module() -> Any:
    """La porte de fusion, chargée UNE fois. Sans le cache, elle l'était à chaque assertion."""
    path = ROOT / "scripts" / "check_roadmap_declared.py"
    spec = importlib.util.spec_from_file_location("check_roadmap_declared_for_docs", path)
    if spec is None or spec.loader is None:
        raise SourceUnavailable(f"{path} : module illisible, plafond de la porte invérifiable")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as error:  # import cassé, syntaxe cassée, constante calculée qui lève…
        raise SourceUnavailable(f"{path} ne se charge pas : {error}") from error
    return module


def expected_gate_ceiling(_claim: object) -> object:
    """`MAX_UNDECLARED`, lu dans la porte elle-même.

    La source est le MODULE, pas une relecture de son texte : `§5` du document annonce une valeur
    de réglage, et la seule chose qui la rende vraie est la constante que la porte évalue. Son
    absence est une erreur bruyante — un `getattr` avec repli rendrait le contrôle vert le jour où
    la constante serait renommée, c'est-à-dire précisément le jour où le document devient faux.
    """
    module = gate_module()
    if not hasattr(module, "MAX_UNDECLARED"):
        raise SourceUnavailable(
            "`MAX_UNDECLARED` a disparu de la porte — le plafond n'a plus de source"
        )
    return module.MAX_UNDECLARED


def expected_profile_count() -> object:
    return len(agent_profiles())


def expected_n_envs() -> object:
    values = {profile["n_envs"] for profile in agent_profiles().values()}
    if len(values) != 1:
        raise LookupError(f"les profils ne partagent pas un même n_envs : {sorted(values)}")
    return values.pop()


def expected_obs_size() -> object:
    values = {profile["observation_params"]["obs_size"] for profile in agent_profiles().values()}
    if len(values) != 1:
        raise LookupError(f"les profils ne partagent pas un même obs_size : {sorted(values)}")
    return values.pop()


def expected_profile_field(key: str) -> object:
    name, field = key.split(".")
    profile = agent_profiles()[name]
    if field == "total_episodes":
        return profile["total_episodes"]
    return profile["callback_params"]["bot_eval_final"]


def expected_step_log(key: tuple[str, int]) -> object:
    count, largest = step_log_entries()
    return ("count", count) if key[0] == "count" else ("max", largest)


def expected_from_table_key(claim: object) -> object:
    """Le tableau des profils porte sa clé DANS le `où` du couple, pas dans la valeur annoncée."""
    raise AssertionError("le tableau des profils se compare par clé, pas par valeur annoncée")


@functools.lru_cache(maxsize=1)
def obs_entities_module() -> Any:
    """engine/observation_entities.py chargé UNE fois — source des dimensions d'entité.

    Seuls `typing` et `__future__` sont importés par ce module : pas de manipulation de
    sys.path nécessaire, contrairement à `macro_intents.py`.
    """
    path = ROOT / "engine" / "observation_entities.py"
    spec = importlib.util.spec_from_file_location("obs_entities_for_docs", path)
    if spec is None or spec.loader is None:
        raise SourceUnavailable(f"{path} : module illisible")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception as error:
        raise SourceUnavailable(f"{path} ne se charge pas : {error}") from error
    return module


def claim_total_action_size(text: str) -> list[tuple[str, int]]:
    """TOTAL_ACTION_SIZE annoncé sur la ligne « espace d'action » d'AI_TRAINING.md."""
    return [
        (m.group(0).strip(), integers_in(m.group(1))[0])
        for m in re.finditer(rf"espace d'action[^\n]*\*\*{_BOLD_INTEGER}\*\*", text)
        if integers_in(m.group(1))
    ]


def expected_total_action_size(_claim: object) -> object:
    """TOTAL_ACTION_SIZE depuis engine/macro_intents.py, chargé avec ROOT dans sys.path.

    `macro_intents.py` importe depuis `engine.observation_entities` et `shared.data_validation` —
    ROOT doit être dans sys.path pour que ces imports aboutissent.
    """
    import sys as _sys

    root_str = str(ROOT)
    already = root_str in _sys.path
    if not already:
        _sys.path.insert(0, root_str)
    try:
        path = ROOT / "engine" / "macro_intents.py"
        spec = importlib.util.spec_from_file_location("_macro_intents_for_docs", path)
        if spec is None or spec.loader is None:
            raise SourceUnavailable(f"{path} : module illisible")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        if not hasattr(module, "TOTAL_ACTION_SIZE"):
            raise SourceUnavailable("TOTAL_ACTION_SIZE absent de engine/macro_intents.py")
        return int(module.TOTAL_ACTION_SIZE)
    except SourceUnavailable:
        raise
    except Exception as error:
        raise SourceUnavailable(
            f"engine/macro_intents.py ne se charge pas : {error}"
        ) from error
    finally:
        if not already and root_str in _sys.path:
            _sys.path.remove(root_str)


def claim_allies_dims(text: str) -> list[tuple[str, tuple[int, int, int, int]]]:
    r"""Dimensions (K_cont, W_cont, K_bin, W_bin) de la ligne allies_cont/allies_bin.

    Extrait le tuple depuis le tableau d'introduction d'AI_OBSERVATION.md :
    `| \`allies_cont\` / \`allies_bin\` | (K, W_cont) / (K, W_bin) | ... |`
    """
    m = re.search(
        r"`allies_cont`[^|]*\|\s*\((\d+),\s*(\d+)\)\s*/\s*\((\d+),\s*(\d+)\)\s*\|",
        text,
    )
    if m is None:
        return []
    return [
        (
            m.group(0).strip(),
            (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))),
        )
    ]


def expected_allies_dims(_claim: object) -> object:
    """Dimensions attendues depuis engine/observation_entities.py."""
    module = obs_entities_module()
    for attr in ("K_ALLY_SLOTS", "UNIT_CONT_SIZE", "UNIT_BIN_SIZE"):
        if not hasattr(module, attr):
            raise SourceUnavailable(f"{attr} absent de observation_entities.py")
    k = module.K_ALLY_SLOTS
    return (k, module.UNIT_CONT_SIZE, k, module.UNIT_BIN_SIZE)


#: label -> (extracteur des valeurs ANNONCÉES par le document, valeur ATTENDUE de la source).
#: L'extracteur qui ne trouve rien fait ÉCHOUER le contrôle : voir la docstring du module.
#: La valeur ANNONCÉE change de nature d'un contrôle à l'autre (un entier ici, un couple
#: `(sorte, entier)` là) : le couple est donc générique en cette valeur, et chaque paire
#: extracteur/attendu reste typée ensemble. Le registre, lui, est hétérogène par nature —
#: `Any` y est l'aveu exact de ce qui s'y range, pas un relâchement du typage des contrôles.
_Claim = TypeVar("_Claim")
ValueCheck = tuple[Callable[[str], list[tuple[str, _Claim]]], Callable[[_Claim], object]]

TABLE_LABEL = "tableau des profils"

#: Chaque affirmation chiffrée est contrôlée dans le document qui la PORTE depuis la partition de
#: la roadmap (2026-08-18) : le plafond de la porte vit dans la préface de l'index, le tableau des
#: profils dans le chemin critique (§P5), le décompte du `step.log` dans le sujet analyzer.
#: `obs_size` était surveillé sur `doc.md`, qui n'en portait la valeur que le temps d'un chantier
#: d'hygiène : le contrôle serait devenu ORPHELIN à sa clôture, et il ne voyait de toute façon pas
#: le document qui publie vraiment cette valeur. Il est passé sur `AI_TRAINING.md` le 2026-08-23.
VALUE_CHECKS: dict[str, dict[str, ValueCheck[Any]]] = {
    "ROADMAP_INDEX.md": {
        "plafond de la porte de fusion": (claim_gate_ceiling, expected_gate_ceiling),
    },
    "v11_chemin_critique.md": {
        "nombre de profils": (claim_profile_count, lambda _claim: expected_profile_count()),
        "n_envs des profils": (claim_n_envs, lambda _claim: expected_n_envs()),
        TABLE_LABEL: (claim_profile_table, expected_from_table_key),
    },
    "analyzer.md": {
        "entrées manquantes du step.log": (claim_step_log, expected_step_log),
    },
    "AI_TRAINING.md": {
        "obs_size": (claim_obs_size, lambda _claim: expected_obs_size()),
        "TOTAL_ACTION_SIZE": (claim_total_action_size, expected_total_action_size),
    },
    "AI_OBSERVATION.md": {
        "dimensions allies_cont/allies_bin": (claim_allies_dims, expected_allies_dims),
    },
}


def check_values(doc_path: pathlib.Path) -> tuple[int, list[str]]:
    """Passe 3 — les nombres recopiés valent encore ce que le document annonce."""
    checks = VALUE_CHECKS.get(doc_path.name)
    if not checks:
        return 0, []
    text = doc_path.read_text(encoding="utf-8")
    verified = 0
    broken: list[str] = []
    for label, (extract, expected_of) in checks.items():
        claims = extract(text)
        if not claims:
            broken.append(
                f"{doc_path.name}  ASSERTION ORPHELINE  « {label} » : le contrôle ne retrouve "
                f"plus la phrase qu'il vérifiait — reformulée, déplacée ou supprimée"
            )
            continue
        for where, claimed in claims:
            if label == TABLE_LABEL:
                key, value = where, claimed
                expected = expected_profile_field(key)
                shown = f"{key} = {value}"
            else:
                value = claimed
                expected = expected_of(claimed)
                shown = f"« {where} »"
            if value != expected:
                broken.append(
                    f"{doc_path.name}  VALEUR PÉRIMÉE  {shown} — la source dit {expected}"
                )
            else:
                verified += 1
    return verified, broken


def check_anchors(
    doc_path: pathlib.Path,
    *,
    enforcement_set: frozenset[str] | None | _Unset = _ANCHOR_UNSET,
) -> list[str]:
    """Passe 4 — aucun renvoi `fichier.py:123`.

    Convention d'ancres de la roadmap (`Documentation/Roadmap/doc.md`) : un numéro de ligne ne
    survit pas à une livraison. Mesuré sur ce dépôt : `UNIT_ABILITY_SLOTS` a changé deux fois de
    ligne en vingt-quatre heures.

    Toutes les extensions, pas seulement `.py` : la seule ligne de `ROADMAP.md` qui portait encore
    des ancres au 2026-08-12 citait deux `.tsx`, que le contrôle laissait passer. Le tri se fait sur
    le FAIT (le nom est-il un fichier du dépôt ?) et non sur une liste de suffixes, qui se serait
    périmée à son tour.
    """
    if enforcement_set is _ANCHOR_UNSET:
        enforcement_set = _get_anchor_enforced()
    if isinstance(enforcement_set, frozenset) and doc_path.name not in enforcement_set:
        return []
    found: list[str] = []
    for lineno, line in enumerate(_read_masked(doc_path).split("\n"), 1):
        # Un même renvoi s'écrit couramment DEUX FOIS sur une ligne — `[a.py:629](…/a.py#L629)`
        # porte le numéro dans le texte et dans l'URL. Compté deux fois, le rapport annonçait
        # « 2 ancres » là où il y en a une, et le lecteur cherchait la seconde.
        # Le dédoublonnage est borné AU MÊME LIEN : sur le seul numéro, « les deux sites a.py:629
        # et L629 de b.tsx » perdait le second en silence, ce qui est pire que le doublon. La clé
        # porte donc l'identité du lien — deux liens différents qui citent le même numéro sont deux
        # renvois, et un numéro hors lien (clé `None`) n'en dédoublonne aucun.
        links = [(match.span(0), match.span(1)) for match in MD_LINK.finditer(line)]

        def enclosing_link(position: int) -> int | None:
            for index, ((start, end), _target) in enumerate(links):
                if start <= position < end:
                    return index
            return None

        # La clé porte AUSSI le fichier : deux fichiers différents cités au même numéro dans le
        # texte d'un même lien sont deux renvois. La graphie `Ln`, qui ne nomme aucun fichier, se
        # dédoublonne alors sur le couple (lien, numéro) seul — c'est elle, et elle seule, qui
        # répète un renvoi déjà écrit en toutes lettres.
        seen: set[tuple[int | None, int, str]] = set()
        for match in LINE_ANCHOR.finditer(line):
            if not is_a_line_anchor(match.group(1).rsplit("/", 1)[-1]):
                continue
            link = enclosing_link(match.start())
            number = int(match.group(2))
            key = (link, number, match.group(1).rsplit("/", 1)[-1])
            if link is not None and key in seen:
                continue
            seen.add(key)
            found.append(
                f"{doc_path.name}:{lineno}  ANCRE DE LIGNE  {match.group(0)} — "
                f"citer le symbole, pas la ligne (§5)"
            )
        for match in BARE_ANCHOR.finditer(line):
            number = int(match.group(1) or match.group(2))
            if match.group(1) is not None and not is_a_bare_anchor(number):
                continue
            link = enclosing_link(match.start())
            if link is not None and any(
                seen_link == link and seen_number == number for seen_link, seen_number, _ in seen
            ):
                continue
            seen.add((link, number, ""))
            found.append(
                f"{doc_path.name}:{lineno}  ANCRE DE LIGNE  {match.group(0)} — "
                f"citer le symbole, pas la ligne (§5)"
            )
    return found


def definitions(source: str) -> dict[str, set[str]]:
    """Ce que ce fichier DÉFINIT vraiment : nom -> sortes (`def`, `class`).

    Lu par l'AST, jamais au motif textuel. Un motif ancré en début de ligne semblait suffire, mais
    il tient pour définition tout `def` INDENTÉ, y compris l'exemple recopié dans une docstring —
    le contrôle confirmait alors la sorte qu'on lui soufflait, très exactement le vert vacant qu'il
    existe pour refuser. L'AST ferme aussi `async def`, qui est un `def` pour qui lit le document
    et que le motif déclarait « introuvable » en accusant le grep de rendre 0 hit.

    Les définitions IMBRIQUÉES comptent : une méthode citée par son nom est bien définie dans le
    fichier cité, et exiger le niveau module rendrait rouges des renvois justes. Chacune est indexée
    SOUS SES DEUX NOMS, nu et QUALIFIÉ (`agit` et `Moteur.agit`) : confronter `def Moteur.agit` sur
    son seul dernier segment confirmait la citation contre un `def agit` de module, sans `Moteur`
    nulle part — le grep promis par le document rendait alors 0 hit, ce que cette passe existe
    précisément pour attraper.
    """
    kinds: dict[str, set[str]] = {}

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                kind = "class" if isinstance(child, ast.ClassDef) else "def"
                kinds.setdefault(child.name, set()).add(kind)
                qualified = f"{prefix}{child.name}"
                kinds.setdefault(qualified, set()).add(kind)
                walk(child, f"{qualified}.")
            else:
                walk(child, prefix)

    walk(ast.parse(source), "")
    return kinds


def kind_claims(line: str) -> tuple[list[tuple[str, str, str]], int]:
    """([(sorte, symbole, fichier) affirmés], nombre de CITATIONS distinctes), les deux ordres.

    Les groupes alternatifs non retenus sortent vides ; le `or` choisit celui qui a matché.

    Le COMPTE de citations est rendu à part, et il ne double pas : mal tenu, il faisait afficher
    « -1 non vérifiée » et pouvait satisfaire à lui seul le garde-fou de vert vacant. L'identité
    d'une citation est la POSITION de son symbole, pas son texte : la même ligne peut légitimement
    citer deux fois le même symbole.
    """
    claims: list[tuple[str, str, str]] = []
    spans: set[tuple[int, int]] = set()
    for match in KIND_CLAIM.finditer(line):
        kind, symbol, parenthesised, colon = match.groups()
        spans.add(match.span(2))
        claims.append((kind, symbol, parenthesised or colon))
    for match in KIND_CLAIM_REVERSED.finditer(line):
        name, kind_p, symbol_p, kind_c, symbol_c = match.groups()
        spans.add(match.span(3) if kind_p else match.span(5))
        claims.append((kind_p or kind_c, symbol_p or symbol_c, name))
    return claims, len(spans)


def check_symbol_kinds(doc_path: pathlib.Path) -> tuple[int, int, list[str], list[str]]:
    """Passe 5 — un symbole annoncé `def X` est un `def`, un `class X` est un `class`.

    L'appariement est ADJACENT, comme celui de la passe 1 : le fichier doit suivre immédiatement la
    citation, éventuellement entre parenthèses — `class X` (`ai/y.py`). Rien d'autre n'est apparié,
    pas même l'unique `.py` de la ligne : mesuré sur ce corpus, une phrase cite couramment un
    fichier ici et un symbole étranger là (« les rampes vivent dans `ai/training_callbacks.py` ; on
    y branche `class VecNormalize` de SB3 » sortait un SYMBOLE NON DÉFINI sur une phrase juste).
    C'est la même règle qui écarte les tableaux : entre deux barres verticales, la citation et le
    fichier ne sont plus adjacents, et `analyzer_couverture.md` est presque entièrement tabulaire.

    Une citation SANS fichier adjacent — « ne pas confondre avec `class _EpisodeRampCallback`, du
    même fichier » — est comptée NON VÉRIFIÉE : la rattacher au fichier de la phrase précédente
    fabriquerait une affirmation que le document ne fait pas.

    Un `.py` du dépôt que l'AST ne sait pas lire n'est PAS un défaut du document : au 2026-08-12,
    `ai/train.py` ne compilait pas à HEAD, et l'imputer au document aurait rendu la porte
    documentaire rouge pour un défaut de code. Il est donc compté non vérifié — mais NOMMÉ, en
    quatrième valeur de retour : un compteur qui absorbe cette panne sous l'étiquette « pas de
    fichier adjacent » donne une raison FAUSSE d'un silence réel, et c'est ainsi qu'une passe
    s'éteint sans que personne ne le voie.
    """
    checked = unverifiable = 0
    broken: list[str] = []
    notes: list[str] = []
    doc_dir = doc_path.parent
    for lineno, line in enumerate(_read_masked(doc_path).split("\n"), 1):
        cited = len(SYMBOL_KIND.findall(line))
        if not cited:
            continue
        claims, paired = kind_claims(line)
        unverifiable += cited - paired
        for kind, symbol, name in claims:
            path = resolve(name, doc_dir)
            if path is None or is_ambiguous(name):
                unverifiable += 1
                continue
            try:
                kinds = definitions(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError as error:
                unverifiable += 1
                note = f"{name} ne se lit pas ({error.msg}, ligne {error.lineno})"
                if note not in notes:
                    notes.append(note)
                continue
            # Un nom QUALIFIÉ se confronte TEL QUEL : `definitions` indexe sous les deux noms.
            actual = kinds.get(symbol, set())
            if kind in actual:
                checked += 1
            elif actual:
                broken.append(
                    f"{doc_path.name}:{lineno}  SORTE FAUSSE  `{kind} {symbol}` — "
                    f"{name} le définit en `{'`, `'.join(sorted(actual))}`"
                )
            else:
                broken.append(
                    f"{doc_path.name}:{lineno}  SYMBOLE NON DÉFINI  `{kind} {symbol}` — "
                    f"absent de {name}, le grep promis rend 0 hit"
                )
    return checked, unverifiable, broken, notes


def cited_documents(doc_path: pathlib.Path) -> list[pathlib.Path]:
    """Les documents que celui-ci DÉSIGNE, quelle que soit la graphie du renvoi.

    Pas seulement le lien markdown : le corpus roadmap renvoie à un chantier par son chemin
    backtiqué (`→ `Documentation/Chantiers/backlog/panel_reference.md``), et c'est même sa
    graphie majoritaire — mesuré le 2026-08-18, 11 des 11 renvois de fichier sujet vers un
    chantier ouvert. Ne suivre que les liens markdown aurait déclaré 11 orphelins sur 13.

    Un nom NU porté par plusieurs fichiers du dépôt et trouvé par RECHERCHE ne désigne rien
    (mesuré à l'époque où `bots_refonte_panel.md` vivait à la fois sous `A_faire/` et sous
    `Implémenté/`) : l'ordre de recherche de `resolve` n'est pas une identification (même
    doctrine que `is_ambiguous` en passe 1). L'ADJACENCE, elle, identifie : c'est la sémantique
    du lien markdown, et c'est par elle que l'index nomme ses fichiers sujets — refuser
    `moteur.md` parce qu'`archives/` en porte un homonyme coupait la marche au premier saut et
    déclarait orphelins 6 chantiers réellement cités (mesuré).
    """
    text = doc_path.read_text(encoding="utf-8")
    found: list[pathlib.Path] = []
    for name in names_in(text):
        if not name.endswith(".md"):
            continue
        target = resolve(name, doc_path.parent)
        if target is None or (is_ambiguous(name) and target != doc_path.parent / name):
            continue
        found.append(target.resolve())
    return found


def is_live(path: pathlib.Path) -> bool:
    """Ce document propage-t-il l'atteignabilité ? Cf. `LIVE_TREES` et `ARCHIVES`."""
    return any(path.is_relative_to(tree) for tree in LIVE_TREES) and not path.is_relative_to(
        ARCHIVES
    )


def reachable_documents() -> set[pathlib.Path]:
    """Tout ce qui se rejoint depuis `ROADMAP_INDEX.md` en suivant les renvois, de proche en proche.

    La marche est TRANSITIVE, et pas bornée aux deux sauts `index → fichier sujet → doc` : un
    fichier sujet qui renvoie à un autre fichier sujet, ou un chantier ouvert qui en découpe un
    second, sont des chemins réels de ce corpus. Les borner aurait rendu orphelin un document
    réellement priorisé, ce qui est le seul moyen sûr de faire ignorer cette passe.
    """
    if not ROADMAP_INDEX.exists():
        raise SourceUnavailable(f"la racine de l'atteignabilité a disparu : {ROADMAP_INDEX}")
    root = ROADMAP_INDEX.resolve()
    seen = {root}
    frontier = collections.deque([root])
    while frontier:
        current = frontier.popleft()
        for target in cited_documents(current):
            if target in seen or not is_live(target):
                continue
            seen.add(target)
            frontier.append(target)
    return seen


def check_reachability() -> tuple[list[str], int]:
    """Passe 6 — tout chantier ouvert se rejoint-il depuis la feuille de route ?

    POURQUOI. Les cinq premières passes vérifient ce que les documents d'entrée DISENT. Aucune ne
    voit ce qu'ils NE DISENT PAS. Un chantier ouvert dont plus aucun fichier sujet ne parle
    disparaît alors sans bruit : le document reste sur le disque, complet et juste, mais il n'est
    plus dans l'ordre du travail — et rien ne le signale, puisqu'il n'y a aucune phrase fausse à
    attraper. Mesuré au premier passage (2026-08-18) : 2 documents sur 13.

    C'est un contrôle de CORPUS, pas de document : il ne se prononce qu'une fois, sur l'ensemble,
    et n'a donc pas de place dans `report`.

    CE QU'IL N'ÉTABLIT PAS : que la ligne qui cite le chantier soit juste, ni qu'elle le range au
    bon endroit. Un renvoi suffit à l'atteignabilité — la pertinence de la priorité n'appartient
    qu'à l'utilisateur.

    Retourne (orphelins, total) pour que l'appelant n'ait pas à réénumérer A_FAIRE.
    """
    targets = sorted(A_FAIRE.rglob("*.md"))
    if not targets:
        # VERT VACANT : « 0 orphelin » ne vaut rien si l'énumération est vide. Le répertoire des
        # chantiers ouverts renommé rendrait la passe verte pour toujours.
        raise SourceUnavailable(f"aucun chantier ouvert énuméré sous {A_FAIRE}")
    reached = reachable_documents()
    orphan_entries = [
        f"{path.relative_to(DOCS).as_posix()}  CHANTIER ORPHELIN  aucun renvoi ne le rejoint "
        f"depuis {ROADMAP_INDEX.name}"
        for path in targets
        if path.resolve() not in reached
    ]
    return orphan_entries, len(targets)


def check_claude_roadmap_subjects() -> tuple[list[str], int, int]:
    """Passe 7 — la liste des fichiers sujets de CLAUDE.md correspond-elle à Documentation/Roadmap/*.md ?

    POURQUOI. CLAUDE.md porte une liste manuelle des fichiers sujets Roadmap ; elle diverge
    silencieusement du disque dès qu'un sujet est ajouté ou renommé sans mettre CLAUDE.md à jour.
    Aucune des six premières passes ne peut le voir : elles vérifient ce que les documents DISENT,
    pas si la liste de CLAUDE.md est exhaustive. Cette passe ferme ce trou en symétrie :
    - fichier listé dans CLAUDE.md mais absent du disque → renvoi mort dans CLAUDE.md ;
    - fichier présent sur le disque (hors ROADMAP_INDEX.md) mais absent de la liste → sujet fantôme,
      invisible pour l'agent qui lit la liste pour décider quoi ouvrir.

    Retourne (erreurs, nb_listés, nb_disque).
    """
    if not CLAUDE_MD.exists():
        raise SourceUnavailable(f"CLAUDE.md introuvable : {CLAUDE_MD}")

    roadmap_dir = ROOT / "Documentation" / "Roadmap"
    if not roadmap_dir.exists():
        raise SourceUnavailable(f"Répertoire Documentation/Roadmap/ introuvable : {roadmap_dir}")
    text = CLAUDE_MD.read_text(encoding="utf-8")

    # Lignes de la forme "- Documentation/Roadmap/X.md — …"
    listed: dict[str, str] = {}
    for m in re.finditer(r"^- Documentation/Roadmap/([\w.-]+\.md)", text, re.MULTILINE):
        listed[m.group(1)] = f"Documentation/Roadmap/{m.group(1)}"

    # Fichiers .md présents au premier niveau de Documentation/Roadmap/, hors index et fichiers
    # internes (convention : préfixe _)
    on_disk: set[str] = {
        f.name
        for f in roadmap_dir.glob("*.md")
        if f.name != "ROADMAP_INDEX.md" and not f.name.startswith("_")
    }

    errors: list[str] = []
    for name, rel in sorted(listed.items()):
        if name not in on_disk:
            errors.append(
                f"CLAUDE.md  SUJET INTROUVABLE  {rel} "
                f"— listé dans CLAUDE.md mais absent de Documentation/Roadmap/"
            )
    for name in sorted(on_disk):
        if name not in listed:
            errors.append(
                f"CLAUDE.md  SUJET NON LISTÉ  Documentation/Roadmap/{name} "
                f"— présent sur le disque mais absent de la liste CLAUDE.md"
            )
    return errors, len(listed), len(on_disk)


def report_claude_subjects() -> tuple[bool, list[str]]:
    errors, nb_listed, nb_disk = check_claude_roadmap_subjects()
    lines = [
        f"{'❌' if errors else '✅'} cohérence liste CLAUDE.md ↔ Documentation/Roadmap/*.md",
        f"   listés dans CLAUDE.md : {nb_listed}, présents sur le disque : {nb_disk}, "
        f"{len(errors)} écart(s)",
    ]
    lines += [f"   {e}" for e in errors]
    return bool(errors), lines


def merges_since(doc_path: pathlib.Path) -> str:
    """Rappel non bloquant : des chantiers ont-ils été livrés depuis la dernière mise à jour ?

    On ne peut pas vérifier qu'un chantier livré a pris sa ligne : il peut n'avoir aucun document,
    et un nom de branche ne se retrouve pas dans un texte écrit en français. Le seul fait que la
    machine possède est le NOMBRE de livraisons depuis la dernière édition du document. C'est un
    rappel, pas un verdict — il ne pèse pas sur le code de sortie.
    """
    try:
        relative = doc_path.relative_to(ROOT).as_posix()
    except ValueError:
        return f"   ℹ️  {doc_path.name} est hors du dépôt — rappel des livraisons sans objet"
    try:
        last = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", relative],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout.strip()
        if not last:
            return f"   ℹ️  {doc_path.name} n'a aucun commit — rappel des livraisons impossible"
        merges = subprocess.run(
            ["git", "log", "--merges", "--oneline", f"{last}..HEAD"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        return f"   ℹ️  rappel des livraisons indisponible : {error}"
    count = len(merges.split("\n")) if merges else 0
    if count == 0:
        return ""
    return (
        f"   ℹ️  {count} livraison(s) mergée(s) depuis la dernière écriture de {doc_path.name} — "
        f"chacune doit y avoir sa ligne (discipline non vérifiable par la machine)"
    )


def report(doc: str, path: pathlib.Path) -> tuple[bool, list[str]]:
    resolved, unverifiable, broken_refs = check_references(path)
    checked, skipped, fragments, broken_links = check_links(path)
    verified, broken_values = check_values(path)
    broken_anchors = check_anchors(path)
    kinds, kinds_unverifiable, broken_kinds, kind_notes = check_symbol_kinds(path)
    dead_links = sum(1 for entry in broken_links if f"  {DEAD_LINK}  " in entry)
    dead_anchors = sum(1 for entry in broken_links if f"  {DEAD_ANCHOR}  " in entry)
    broken = broken_refs + broken_links + broken_values + broken_anchors + broken_kinds
    lines = [
        f"{'❌' if broken else '✅'} {doc}",
        f"   renvois  : {resolved} confirmés, {len(broken_refs)} cassés, "
        f"{unverifiable} sans symbole à confronter (non vérifiés)",
        f"   liens    : {checked} vérifiés, "
        f"{dead_links} morts, "
        f"{skipped} écartés (pas une forme de chemin)",
        f"   fragments: {fragments} ancres de lien confrontées, "
        f"{dead_anchors} mortes",
        f"   valeurs  : {verified} confirmées, {len(broken_values)} périmées ou orphelines",
        f"   ancres   : {len(broken_anchors)} renvois `fichier.ext:ligne`",
        f"   sortes   : {kinds} confirmées, {len(broken_kinds)} fausses, "
        f"{kinds_unverifiable} non confrontées (pas de fichier adjacent, chemin irrésolu, "
        f"nom ambigu, ou `.py` illisible)",
    ]
    lines += [f"   ℹ️  {note}" for note in kind_notes]
    lines += [f"   {entry}" for entry in broken]
    reminder = merges_since(path)
    if reminder:
        lines.append(reminder)
    return bool(broken), lines


def report_reachability() -> tuple[bool, list[str]]:
    orphans, total = check_reachability()
    lines = [
        f"{'❌' if orphans else '✅'} atteignabilité des chantiers ouverts",
        f"   chantiers: {total} sous {A_FAIRE.relative_to(ROOT).as_posix()}, "
        f"{len(orphans)} orphelin(s)",
    ]
    lines += [f"   {entry}" for entry in orphans]
    return bool(orphans), lines


def report_values_only(doc: str, path: pathlib.Path) -> tuple[bool, list[str]]:
    """Passe 3 seule, pour un document qui porte des valeurs sans être un document d'entrée."""
    verified, broken = check_values(path)
    lines = [
        f"{'❌' if broken else '✅'} {doc}  (valeurs seules)",
        f"   valeurs  : {verified} confirmées, {len(broken)} périmées ou orphelines",
    ]
    lines += [f"   {entry}" for entry in broken]
    return bool(broken), lines


def report_impl_anchors() -> tuple[bool, list[str]]:
    """Passe 4 sur les arbres ANCHOR_TREES — découverte dynamique.

    Les documents déjà dans DEFAULT_DOCS passent le contrôle complet via report() ; ils sont
    écartés ici pour ne pas être comptés deux fois. Seule la passe 4 est appliquée : ces docs ne
    sont pas des documents d'entrée au sens de la roadmap, on ne leur demande ni la vérification
    de leurs renvois, ni la passe valeurs, ni la passe sortes.
    """
    trees = [ROOT / prefix.rstrip("/") for prefix in ANCHOR_TREES]
    for tree in trees:
        if not tree.is_dir():
            raise SourceUnavailable(f"Arbre de la passe 4 introuvable : {tree}")
    already = set(DEFAULT_DOCS)
    all_broken: list[str] = []
    count = 0
    for tree in trees:
        for path in sorted(tree.rglob("*.md")):
            rel = path.relative_to(ROOT).as_posix()
            if rel in already:
                continue
            count += 1
            all_broken.extend(check_anchors(path, enforcement_set=None))
    lines = [
        f"{'❌' if all_broken else '✅'} {' + '.join(ANCHOR_TREES)} (ancres) — "
        f"{count} fichier(s), {len(all_broken)} renvoi(s) de ligne",
    ]
    lines += [f"   {entry}" for entry in all_broken]
    return bool(all_broken), lines


#: Arbres et fichiers individuels du corpus VIVANT pour la passe LIENS (P2, 2026-08-27).
#: Roadmap/archives/ exclu : les archives ne sont pas maintenues, les liens qu'elles portaient
#: ont pu mourir sans que personne ait à les corriger.
_CORPUS_LINK_TREES = (
    "Documentation/Reference/",
    "Documentation/Chantiers/",
    "Documentation/Roadmap/",
)
_CORPUS_LINK_EXCLUDE = ("Documentation/Roadmap/archives/",)


def _corpus_link_paths() -> list[pathlib.Path]:
    """Chemins .md du corpus vivant : Reference + Chantiers + Roadmap hors archives + README."""
    paths: list[pathlib.Path] = []
    readme = ROOT / "README.md"
    if readme.exists():
        paths.append(readme)
    for item in _git_raw_listing().split("\0"):
        if not item or not item.endswith(".md"):
            continue
        if any(item.startswith(ex) for ex in _CORPUS_LINK_EXCLUDE):
            continue
        if any(item.startswith(tree) for tree in _CORPUS_LINK_TREES):
            paths.append(ROOT / item)
    return sorted(set(paths))


def report_corpus_links() -> tuple[bool, list[str]]:
    """Passe LIENS sur tout le corpus vivant — cibles markdown ET fragments.

    Extension de la passe 2 hors des seuls DEFAULT_DOCS : le corpus Reference/Chantiers/Roadmap
    portait ~85 liens morts au 2026-08-27, invisibles parce que la passe ne regardait que 12 docs.
    """
    all_broken: list[str] = []
    checked = skipped = fragments = 0
    paths = _corpus_link_paths()
    for path in paths:
        c, s, f, broken = check_links(path)
        checked += c
        skipped += s
        fragments += f
        all_broken.extend(broken)
    lines = [
        f"{'❌' if all_broken else '✅'} LIENS corpus vivant — {len(paths)} fichier(s), "
        f"{checked} lien(s) vérifiés, {skipped} écartés, {fragments} fragments confrontés, "
        f"{len(all_broken)} mort(s)",
    ]
    lines += [f"   {entry}" for entry in all_broken]
    return bool(all_broken), lines


#: Au-delà de ce seuil, ROADMAP_INDEX.md accumule des ✅ qui auraient dû descendre en archives.
MAX_ROADMAP_CHECKMARKS = 20


def check_accumulation_roadmap() -> tuple[int, int]:
    """Compte les lignes portant ✅ dans ROADMAP_INDEX.md."""
    text = ROADMAP_INDEX.read_text(encoding="utf-8")
    count = sum(1 for line in text.splitlines() if "✅" in line)
    return count, MAX_ROADMAP_CHECKMARKS


def report_accumulation() -> tuple[bool, list[str]]:
    """Passe accumulation : ROADMAP_INDEX.md ne dépasse pas MAX_ROADMAP_CHECKMARKS lignes ✅."""
    count, threshold = check_accumulation_roadmap()
    broken = count > threshold
    lines = [
        f"{'❌' if broken else '✅'} accumulation ROADMAP_INDEX.md — "
        f"{count} ligne(s) ✅ (seuil : {threshold})",
    ]
    if broken:
        lines.append(
            f"   {count} lignes ✅ dans ROADMAP_INDEX.md — archiver les chantiers clos "
            f"dans Documentation/Roadmap/archives/<sujet>.md"
        )
    return broken, lines


def main(argv: list[str]) -> int:
    docs: Iterable[str] = argv[1:] or [*DEFAULT_DOCS, *VALUE_ONLY_DOCS]
    failed = False
    for doc in docs:
        path = pathlib.Path(doc) if pathlib.Path(doc).is_absolute() else ROOT / doc
        if not path.exists():
            print(f"❌ document introuvable : {doc}")
            failed = True
            continue
        try:
            if doc in VALUE_ONLY_DOCS:
                has_broken, lines = report_values_only(doc, path)
            else:
                has_broken, lines = report(doc, path)
        except (SourceUnavailable, OSError) as error:
            # Les SOURCES du contrôle peuvent disparaître ou cesser de se lire : le §7
            # d'`analyzer_couverture.md` renommé, `MAX_UNDECLARED` supprimé, la porte de fusion
            # devenue illisible. C'est bloquant — jamais un vert —, mais ça n'a pas à sortir en
            # trace Python : le script promet 0 ou 1, et une trace sur un document SANS RAPPORT
            # avec la panne envoie corriger le mauvais fichier.
            print(f"❌ {doc}\n   CONTRÔLE IMPOSSIBLE — {type(error).__name__} : {error}")
            failed = True
            continue
        print("\n".join(lines))
        failed = failed or has_broken
    if not argv[1:]:
        # Les passes 6 et 7 portent sur le CORPUS : les rejouer quand l'utilisateur interroge un
        # document précis rapporterait des erreurs sans rapport avec ce qu'il regarde.
        try:
            has_orphans, lines = report_reachability()
        except (SourceUnavailable, OSError) as error:
            print(f"❌ atteignabilité\n   CONTRÔLE IMPOSSIBLE — {type(error).__name__} : {error}")
            failed = True
        else:
            print("\n".join(lines))
            failed = failed or has_orphans
        try:
            has_gaps, lines = report_claude_subjects()
        except (SourceUnavailable, OSError) as error:
            print(f"❌ cohérence CLAUDE.md\n   CONTRÔLE IMPOSSIBLE — {type(error).__name__} : {error}")
            failed = True
        else:
            print("\n".join(lines))
            failed = failed or has_gaps
        try:
            has_impl_broken, lines = report_impl_anchors()
        except (SourceUnavailable, OSError) as error:
            print(f"❌ corpus chantiers (ancres)\n   CONTRÔLE IMPOSSIBLE — {type(error).__name__} : {error}")
            failed = True
        else:
            print("\n".join(lines))
            failed = failed or has_impl_broken
        try:
            has_corpus_broken, lines = report_corpus_links()
        except (SourceUnavailable, OSError) as error:
            print(f"❌ LIENS corpus vivant\n   CONTRÔLE IMPOSSIBLE — {type(error).__name__} : {error}")
            failed = True
        else:
            print("\n".join(lines))
            failed = failed or has_corpus_broken
        try:
            has_accum, lines = report_accumulation()
        except (SourceUnavailable, OSError) as error:
            print(f"❌ accumulation ROADMAP_INDEX.md\n   CONTRÔLE IMPOSSIBLE — {type(error).__name__} : {error}")
            failed = True
        else:
            print("\n".join(lines))
            failed = failed or has_accum
    print(
        "\nNON VÉRIFIABLE, et assumé : le nombre de « contrôles analyzer vivants ». Le code n'en "
        "porte aucune énumération ; le compter depuis un tableau de document mesurerait autre "
        "chose sous le même nom."
    )
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        _check_filesystem_encoding()
    except SourceUnavailable as _env_error:
        print(f"❌ ERREUR D'ENVIRONNEMENT : {_env_error}", file=sys.stderr)
        sys.exit(1)
    sys.exit(main(sys.argv))
