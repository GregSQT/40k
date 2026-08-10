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
    une couverture qui n'existe pas — c'est le mode d'échec du VERT VACANT ;
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

import json
import pathlib
import re
import subprocess
import sys
import urllib.parse
from typing import Callable, Iterable

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "Documentation" / "Implémentation"

DEFAULT_DOCS = [
    "Documentation/Implémentation/analyzer_couverture.md",
    "Documentation/Implémentation/ROADMAP.md",
]

AGENT_CONFIG = ROOT / "config" / "agents" / "ArmageddonAgent" / "ArmageddonAgent_training_config.json"
COUVERTURE = DOCS / "analyzer_couverture.md"

#: Répertoires où un nom de fichier NU est cherché. `scripts/` en fait partie : son absence a
#: produit une fausse alerte sur `check_ai_rules.py` au premier passage.
SEARCH_DIRS = [
    "", "ai", "ai/analyzer_phases", "engine", "engine/phase_handlers", "engine/utils",
    "shared", "scripts", "services", "config", "tests/unit/ai", "tests/unit/engine",
]

#: Un chemin peut être relatif AU DOCUMENT (`../../engine/x.py`), absolu, ou nu. La classe de
#: caractères doit donc accepter le point : sans lui, `../../engine/x.py` était capturé comme
#: `/engine/x.py`, que `ROOT / name` transformait en chemin absolu inexistant — 18 fausses
#: alertes sur `V11_phaseA.md` le 2026-08-11, sur un document dont les 9 cibles existaient toutes.
FILE_REF = re.compile(r"((?:\.{1,2}/)+[\w./-]+\.(?:py|json|md)|[\w/-]+\.(?:py|json|md))")
BACKTICKED = re.compile(r"`([^`]+)`")
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
MD_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
LINE_ANCHOR = re.compile(r"\b([A-Za-z0-9_]+\.py):(\d+)")

#: Un renvoi générique (`*_handler.py`, `analyzer_phases/*`) ne désigne aucun fichier précis : il
#: n'y a rien à résoudre, et le compter en échec ferait du bruit là où le document est correct.
WILDCARD = re.compile(r"[*]")

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

    En PROSE, seule l'EXISTENCE des fichiers est vérifiée — elle n'est jamais ambiguë. AUCUN
    appariement, même quand la phrase ne cite qu'un fichier : mesuré le 2026-08-11, les quatre
    tentatives d'appariement en prose d'`analyzer_couverture.md` étaient toutes fausses (une
    phrase cite `check_ai_rules.py` et, plus loin, `pyright` et `biome`, qui n'ont rien à y
    faire). Un contrôle qui crie à tort finit désactivé ; ces cas sont comptés comme non vérifiés.
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


def symbols_in(cell: str) -> list[str]:
    symbols: list[str] = []
    for raw in BACKTICKED.findall(cell):
        # Un fragment qui porte un chemin ou un joker (`analyzer_phases/*`) désigne un ENSEMBLE
        # de fichiers, pas un symbole : en tirer des identifiants fabriquait des paires que le
        # document n'a jamais affirmées.
        if "/" in raw or "*" in raw or FILE_REF.fullmatch(raw.strip()):
            continue
        symbols += IDENTIFIER.findall(raw)
    return [s for s in dict.fromkeys(symbols) if not s.endswith("py")]


def check_references(doc_path: pathlib.Path) -> tuple[int, int, list[str]]:
    """Passe 1 — les fichiers cités existent, les symboles cités y vivent."""
    doc_dir = doc_path.parent
    resolved = unverifiable = 0
    broken: list[str] = []
    for lineno, line in enumerate(doc_path.read_text(encoding="utf-8").split("\n"), 1):
        cells, pairing_allowed = fragments(line)
        for cell in cells:
            names = names_in(cell)
            if not names:
                continue
            missing = [n for n in names if resolve(n, doc_dir) is None]
            for name in missing:
                broken.append(f"{doc_path.name}:{lineno}  FICHIER INTROUVABLE  {name}")
            present = [n for n in names if n not in missing]
            if not present:
                continue
            if not pairing_allowed:
                unverifiable += len(present)
                continue
            symbols = symbols_in(cell)
            if not symbols:
                unverifiable += len(present)
                continue
            # UN renvoi est confirmé dès qu'UN des fichiers de la cellule porte UN des symboles
            # de la cellule. Exiger que CHAQUE fichier les porte tous serait une affirmation que
            # le document ne fait pas : une cellule cite couramment le producteur ET le lecteur
            # d'une donnée, dont les symboles ne vivent que d'un côté.
            bodies = [
                path.read_text(encoding="utf-8", errors="replace")
                for path in (resolve(n, doc_dir) for n in present) if path is not None
            ]
            if any(symbol_is_present(s, b) for s in symbols for b in bodies):
                resolved += len(present)
            else:
                broken.append(
                    f"{doc_path.name}:{lineno}  AUCUN SYMBOLE dans {', '.join(present)} — "
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


def claim_profile_count(text: str) -> list[tuple[str, object]]:
    return [(m.group(0).strip(), int(m.group(1)))
            for m in re.finditer(r"\*\*(\d+)\*\*\s*profils", text)]


def claim_n_envs(text: str) -> list[tuple[str, object]]:
    return [(m.group(0).strip(), int(m.group(1))) for m in re.finditer(r"(\d+)\s+envs\b", text)]


def claim_obs_size(text: str) -> list[tuple[str, object]]:
    found = [(m.group(0).strip(), int(m.group(1)))
             for m in re.finditer(r"`obs_size`[^\n]*?\*\*(\d{4,})\*\*", text)]
    found += [(m.group(0).strip(), int(m.group(1)))
              for m in re.finditer(r'`"obs_size":\s*(\d+)`', text)]
    return found


def claim_profile_table(text: str) -> list[tuple[str, object]]:
    """Les cases du tableau `profil | total_episodes | bot_eval_final` de §1.

    Ancré sur le NOM du profil, seul repère qui survive à une reformulation : la ligne peut
    porter du gras, une parenthèse d'historique ou un séparateur de milliers sans se dérober.
    """
    known = set(agent_profiles())
    claims: list[tuple[str, object]] = []
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


def claim_step_log(text: str) -> list[tuple[str, object]]:
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
ValueCheck = tuple[Callable[[str], list[tuple[str, object]]], Callable[[object], object]]

TABLE_LABEL = "tableau des profils"

VALUE_CHECKS: dict[str, dict[str, ValueCheck]] = {
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
    if doc_path.name not in VALUE_CHECKS and doc_path != COUVERTURE:
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
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
        if not last:
            return f"   ℹ️  {doc_path.name} n'a aucun commit — rappel des livraisons impossible"
        merges = subprocess.run(
            ["git", "log", "--merges", "--oneline", f"{last}..HEAD"],
            cwd=ROOT, capture_output=True, text=True, check=True,
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
