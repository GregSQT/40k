#!/usr/bin/env python3
"""Les documents d'entrée disent-ils encore la vérité sur le dépôt ?

POURQUOI CE SCRIPT EXISTE. `analyzer_couverture.md` et `ROADMAP.md` sont les documents d'ENTRÉE :
l'un dit ce qui est vérifié et ce qui ne l'est pas, l'autre dit par quoi commencer. Ils sont tenus
à la main, et rien ne les confrontait au dépôt. Le 2026-08-10, un contrôle ponctuel a mesuré l'état
des renvois d'`analyzer_couverture.md` **après une seule journée de livraisons** :

    147 citations `fichier.py:ligne` — 31 saines, 76 PROUVÉES FAUSSES, 40 invérifiables.

Les numéros de ligne ont donc été supprimés au profit du couple `fichier.py` + nom de symbole, qui
ne rouille pas. Ce script est la seconde moitié de cette décision.

CE QU'IL ÉTABLIT, en quatre passes :
  1. RENVOIS  — tout fichier cité existe, et tout symbole cité vit dans le fichier cité.
  2. LIENS    — toute cible de lien markdown existe.
  3. VALEURS  — les nombres recopiés d'une source mécanique (config d'agent, tableau d'un autre
                document) valent encore ce que le document annonce.
  4. ANCRES   — aucun renvoi de la forme `fichier.py:123`, convention posée par `ROADMAP.md` §5.

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

import collections
import functools
import json
import pathlib
import re
import subprocess
import sys
import urllib.parse
from typing import Any, Callable, Iterable, TypeVar

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "Documentation" / "Implémentation"

DEFAULT_DOCS = [
    "Documentation/Implémentation/analyzer_couverture.md",
    "Documentation/Implémentation/ROADMAP.md",
    "Documentation/Implémentation/Security.md",
]

#: Documents tenus à la convention « le symbole, jamais la ligne » (`ROADMAP.md` §5). La liste est
#: explicite : l'imposer à tout `.md` du dépôt rendrait rouges des documents d'historique que
#: personne ne rouvre, et un contrôle durablement rouge finit par être ignoré.
ANCHOR_ENFORCED = {"analyzer_couverture.md", "ROADMAP.md", "Security.md"}

AGENT_CONFIG = ROOT / "config" / "agents" / "ArmageddonAgent" / "ArmageddonAgent_training_config.json"
COUVERTURE = DOCS / "analyzer_couverture.md"

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
LINE_ANCHOR = re.compile(r"\b([A-Za-z0-9_]+\.py):(\d+)")

#: Un renvoi générique (`*_handler.py`, `analyzer_phases/*`) ne désigne aucun fichier précis : il
#: n'y a rien à résoudre, et le compter en échec ferait du bruit là où le document est correct.
WILDCARD = re.compile(r"[*]")

#: La bosse de casse d'un identifiant composé (`SummaryWriter`, `GameClient`, `XMLHttpRequest`).
#: `token != token.lower()` ne suffisait pas : il tenait `False` et `Objectives` pour des symboles.
CASE_HUMP = re.compile(r"[a-z][A-Z]")

#: Suffixes qu'une cible de lien doit porter pour être tenue pour un chemin. Un lien vers un
#: répertoire (`1_Agent/`) est reconnu par sa barre finale.
LINK_SUFFIXES = (".md", ".py", ".json", ".pdf", ".txt", ".sh", ".ts", ".tsx", ".png")

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
    # documents est relatif AU DOCUMENT (`1_Agent/V11_phaseA.md`), un renvoi vers le code est
    # relatif à la RACINE (`engine/w40k_core.py`). Essayer les deux n'est pas un repli qui
    # masquerait une erreur : c'est résoudre dans les deux systèmes que le dépôt emploie.
    if "/" in name:
        for candidate in (doc_dir / name, ROOT / name):
            if candidate.exists():
                return candidate
        return None
    for directory in SEARCH_DIRS:
        candidate = ROOT / directory / name if directory else ROOT / name
        if candidate.exists():
            return candidate
    # Un nom NU renvoie couramment à un document rangé dans un sous-dossier (`V11_tranches.md`)
    # ou à une configuration d'agent (`ArmageddonAgent_training_config.json`). Ces deux arbres
    # sont petits : on les parcourt plutôt que d'énumérer à la main des chemins qui bougeront.
    for tree in (DOCS, ROOT / "config"):
        found = next(tree.rglob(name), None)
        if found is not None:
            return found
    return None


@functools.lru_cache(maxsize=1)
def tracked_basenames() -> collections.Counter[str]:
    """Combien de fichiers SUIVIS portent chaque nom. Une seule invocation de git par run.

    `-z` n'est pas un détail : sans lui, git échappe les octets non-ASCII et ENTOURE le chemin de
    guillemets (73 chemins de ce dépôt, tout `Documentation/Implémentation/` en tête). Le basename
    en sortait avec son guillemet collé, sous une clé que personne n'interroge — l'ambiguïté de ces
    fichiers-là n'aurait jamais été vue. Même piège que `core.quotePath` dans
    `scripts/check_roadmap_declared.py`, qui l'a payé le 2026-08-11.
    """
    listing = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True,
        text=True, encoding="utf-8", check=True,
    ).stdout
    return collections.Counter(f.rsplit("/", 1)[-1] for f in listing.split("\0") if f)


def is_ambiguous(name: str) -> bool:
    """Ce nom NU désigne-t-il plusieurs fichiers du dépôt ?

    `conftest.py` existe cinq fois. L'ordre de recherche de `resolve` est une convention
    d'EXISTENCE — il rend le premier trouvé — et ne vaut pas identification : confronter des
    symboles au fichier qu'il désigne, c'est interroger un fichier dont le document ne parle pas.
    Mesuré : `conftest.py` : `GameClient` sortait en AUCUN SYMBOLE, le symbole étant défini dans
    l'autre `conftest.py`. Le renvoi est donc compté INVÉRIFIABLE, jamais cassé.
    """
    return "/" not in name and tracked_basenames()[name] > 1


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
    for lineno, line in enumerate(doc_path.read_text(encoding="utf-8").split("\n"), 1):
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


def check_links(doc_path: pathlib.Path) -> tuple[int, int, list[str]]:
    """Passe 2 — les cibles des liens markdown existent.

    Les liens `file:///` sont ABSOLUS par convention CLAUDE.md : ils sont vérifiés comme tels,
    et non écartés — c'est ce que faisait le contrôle manuel, qui ne les regardait donc jamais.
    """
    doc_dir = doc_path.parent
    checked = skipped = 0
    broken: list[str] = []
    for lineno, line in enumerate(doc_path.read_text(encoding="utf-8").split("\n"), 1):
        for raw in MD_LINK.findall(line):
            target = urllib.parse.unquote(raw.split("#", 1)[0]).strip()
            if target.startswith("file://"):
                target = target[len("file://"):]
            if not looks_like_path(target):
                skipped += 1
                continue
            checked += 1
            if resolve(target.rstrip("/") if target.endswith("/") else target, doc_dir) is None:
                broken.append(f"{doc_path.name}:{lineno}  LIEN MORT  {target}")
    return checked, skipped, broken


def agent_profiles() -> dict[str, dict]:
    """Les profils d'entraînement de l'agent, source de vérité des nombres recopiés."""
    data = json.loads(AGENT_CONFIG.read_text(encoding="utf-8"))
    return {key: value for key, value in data.items() if isinstance(value, dict)}


def step_log_entries() -> tuple[int, int, bool]:
    """(nombre d'entrées, plus grand index, L2 absente) du tableau §7 d'`analyzer_couverture`."""
    text = COUVERTURE.read_text(encoding="utf-8")
    section = re.search(r"^## 7\..*?(?=^## 8\.)", text, re.S | re.M)
    if section is None:
        raise LookupError("analyzer_couverture.md : §7 introuvable")
    indexes = sorted({int(m) for m in re.findall(r"^\|\s*`?L(\d+)`?\s*\|", section.group(0), re.M)})
    if not indexes:
        raise LookupError("analyzer_couverture.md : §7 ne porte aucune entrée `Ln`")
    return len(indexes), max(indexes), 2 not in indexes


def integers_in(cell: str) -> list[int]:
    """Les entiers d'une cellule, séparateur de milliers compris (« 10 000 » vaut 10000)."""
    return [int(m.group(0).replace(" ", "").replace(" ", "").replace("\xa0", ""))
            for m in re.finditer(r"\d[\d  \xa0]*\d|\d", cell)]


def claim_profile_count(text: str) -> list[tuple[str, int]]:
    return [(m.group(0).strip(), int(m.group(1)))
            for m in re.finditer(r"\*\*(\d+)\*\*\s*profils", text)]


def claim_n_envs(text: str) -> list[tuple[str, int]]:
    return [(m.group(0).strip(), int(m.group(1))) for m in re.finditer(r"(\d+)\s+envs\b", text)]


def claim_obs_size(text: str) -> list[tuple[str, int]]:
    found = [(m.group(0).strip(), int(m.group(1)))
             for m in re.finditer(r"`obs_size`[^\n]*?\*\*(\d{4,})\*\*", text)]
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
    count, largest, _ = step_log_entries()
    return ("count", count) if key[0] == "count" else ("max", largest)


def expected_from_table_key(claim: object) -> object:
    """Le tableau des profils porte sa clé DANS le `où` du couple, pas dans la valeur annoncée."""
    raise AssertionError("le tableau des profils se compare par clé, pas par valeur annoncée")


#: label -> (extracteur des valeurs ANNONCÉES par le document, valeur ATTENDUE de la source).
#: L'extracteur qui ne trouve rien fait ÉCHOUER le contrôle : voir la docstring du module.
#: La valeur ANNONCÉE change de nature d'un contrôle à l'autre (un entier ici, un couple
#: `(sorte, entier)` là) : le couple est donc générique en cette valeur, et chaque paire
#: extracteur/attendu reste typée ensemble. Le registre, lui, est hétérogène par nature —
#: `Any` y est l'aveu exact de ce qui s'y range, pas un relâchement du typage des contrôles.
_Claim = TypeVar("_Claim")
ValueCheck = tuple[Callable[[str], list[tuple[str, _Claim]]], Callable[[_Claim], object]]

TABLE_LABEL = "tableau des profils"

VALUE_CHECKS: dict[str, dict[str, ValueCheck[Any]]] = {
    "ROADMAP.md": {
        "nombre de profils": (claim_profile_count, lambda _claim: expected_profile_count()),
        "n_envs des profils": (claim_n_envs, lambda _claim: expected_n_envs()),
        "obs_size": (claim_obs_size, lambda _claim: expected_obs_size()),
        TABLE_LABEL: (claim_profile_table, expected_from_table_key),
        "entrées manquantes du step.log": (claim_step_log, expected_step_log),
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


def check_anchors(doc_path: pathlib.Path) -> list[str]:
    """Passe 4 — aucun renvoi `fichier.py:123`.

    Convention `ROADMAP.md` §5 : un numéro de ligne ne survit pas à une livraison. Mesuré sur ce
    dépôt : `UNIT_ABILITY_SLOTS` a changé deux fois de ligne en vingt-quatre heures.
    """
    if doc_path.name not in ANCHOR_ENFORCED:
        return []
    found: list[str] = []
    for lineno, line in enumerate(doc_path.read_text(encoding="utf-8").split("\n"), 1):
        for match in LINE_ANCHOR.finditer(line):
            found.append(
                f"{doc_path.name}:{lineno}  ANCRE DE LIGNE  {match.group(0)} — "
                f"citer le symbole, pas la ligne (§5)"
            )
    return found


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
    checked, skipped, broken_links = check_links(path)
    verified, broken_values = check_values(path)
    broken_anchors = check_anchors(path)
    broken = broken_refs + broken_links + broken_values + broken_anchors
    lines = [
        f"{'❌' if broken else '✅'} {doc}",
        f"   renvois  : {resolved} confirmés, {len(broken_refs)} cassés, "
        f"{unverifiable} sans symbole à confronter (non vérifiés)",
        f"   liens    : {checked} vérifiés, {len(broken_links)} morts, "
        f"{skipped} écartés (pas une forme de chemin)",
        f"   valeurs  : {verified} confirmées, {len(broken_values)} périmées ou orphelines",
        f"   ancres   : {len(broken_anchors)} renvois `fichier.py:ligne`",
    ]
    lines += [f"   {entry}" for entry in broken]
    reminder = merges_since(path)
    if reminder:
        lines.append(reminder)
    return bool(broken), lines


def main(argv: list[str]) -> int:
    docs: Iterable[str] = argv[1:] or DEFAULT_DOCS
    failed = False
    for doc in docs:
        path = pathlib.Path(doc) if pathlib.Path(doc).is_absolute() else ROOT / doc
        if not path.exists():
            print(f"❌ document introuvable : {doc}")
            failed = True
            continue
        has_broken, lines = report(doc, path)
        print("\n".join(lines))
        failed = failed or has_broken
    print(
        "\nNON VÉRIFIABLE, et assumé : le nombre de « contrôles analyzer vivants ». Le code n'en "
        "porte aucune énumération ; le compter depuis un tableau de document mesurerait autre "
        "chose sous le même nom."
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
