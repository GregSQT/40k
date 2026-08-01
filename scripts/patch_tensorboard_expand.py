#!/usr/bin/env python3
"""Ouvre les N premiers groupes de tags du dashboard TensorBoard au chargement.

TensorBoard code en dur le nombre de groupes deplies par defaut dans son bundle
JS (`webfiles.zip` -> `index.js`) :

    if (0 === n.tagGroupExpanded.size) { ... for (let _ of m.slice(0, 2)) a.set(_.groupName, !0) }

Seuls les DEUX premiers groupes sont donc ouverts, quel que soit leur nom. Aucun
reglage cote event files, cote URL ou cote CLI ne change ce nombre, et l'etat
n'est pas persiste entre deux rechargements de page. Ce script reecrit la
constante dans le bundle installe dans le venv courant.

`index.html` reference `index.js?_file_hash=<hash>` avec un hash fige dans le
bundle, et le JS est servi avec un cache navigateur d'un an
(`core_plugin.py`, JS_CACHE_EXPIRATION_IN_SECS). Le patch recalcule donc ce hash
a partir du bundle modifie : l'URL change, le cache navigateur est invalide et
aucun rechargement force n'est necessaire.

TensorBoard lit `webfiles.zip` une seule fois au demarrage et sert son contenu
depuis la memoire : REDEMARRER TensorBoard apres le patch.

A relancer apres chaque `pip install`/`pip install -U tensorboard` : la
reinstallation restaure le `webfiles.zip` d'origine.

Usage :
    python3 scripts/patch_tensorboard_expand.py            # 3 groupes
    python3 scripts/patch_tensorboard_expand.py --groups 4
    python3 scripts/patch_tensorboard_expand.py --check    # verifie sans ecrire
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
import zipfile
from pathlib import Path

# Le `2` capture est le nombre de groupes deplies. L'ancre exige le `.set(x.groupName, !0)`
# qui suit pour ne pas toucher un autre `.slice(0, 2)` si le bundle evolue.
_PATTERN = re.compile(
    r"(\.slice\(0,)(\d+)(\)\)[A-Za-z_$]+\.set\([A-Za-z_$]+\.groupName,!0\))"
)

_BUNDLE_ENTRY = "index.js"
_INDEX_ENTRY = "index.html"
# `index.js?_file_hash=8d1eb1fd` — le hash pilote le cache navigateur d'un an du bundle.
_CACHE_BUST = re.compile(rf"({re.escape(_BUNDLE_ENTRY)}\?_file_hash=)([0-9a-f]+)")


def _locate_webfiles() -> Path:
    import tensorboard

    package_dir = Path(tensorboard.__file__).resolve().parent
    webfiles = package_dir / "webfiles.zip"
    if not webfiles.is_file():
        raise FileNotFoundError(
            f"webfiles.zip introuvable dans {package_dir} — installation TensorBoard inattendue"
        )
    return webfiles


def _read_entry(webfiles: Path, entry: str) -> str:
    with zipfile.ZipFile(webfiles) as archive:
        if entry not in archive.namelist():
            raise KeyError(f"{entry} absent de {webfiles}")
        return archive.read(entry).decode("utf-8")


def _current_groups(bundle: str) -> int:
    matches = _PATTERN.findall(bundle)
    if len(matches) != 1:
        raise RuntimeError(
            f"motif d'expansion des groupes trouve {len(matches)} fois dans {_BUNDLE_ENTRY} "
            "(attendu : 1) — le bundle TensorBoard a change, le patch doit etre revu"
        )
    return int(matches[0][1])


def _cache_bust(index_html: str, bundle: str) -> str:
    """Aligne le `_file_hash` d'index.html sur le contenu reel du bundle patche."""
    digest = hashlib.sha256(bundle.encode("utf-8")).hexdigest()[:8]
    patched, count = _CACHE_BUST.subn(rf"\g<1>{digest}", index_html)
    if count != 1:
        raise RuntimeError(
            f"reference '{_BUNDLE_ENTRY}?_file_hash=' trouvee {count} fois dans {_INDEX_ENTRY} "
            "(attendu : 1) — le bundle TensorBoard a change, le patch doit etre revu"
        )
    return patched


def _rewrite_archive(webfiles: Path, replacements: dict[str, bytes]) -> None:
    backup = webfiles.with_suffix(".zip.orig")
    if not backup.exists():
        shutil.copy2(webfiles, backup)

    temp = webfiles.with_suffix(".zip.tmp")
    with zipfile.ZipFile(backup) as source, zipfile.ZipFile(temp, "w") as target:
        for info in source.infolist():
            payload = replacements.get(info.filename, None)
            if payload is None:
                payload = source.read(info)
            target.writestr(info, payload, compress_type=info.compress_type)
    temp.replace(webfiles)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--groups", type=int, default=3, help="nombre de groupes deplies au chargement (defaut : 3)"
    )
    parser.add_argument(
        "--check", action="store_true", help="rapporte l'etat courant sans modifier le bundle"
    )
    args = parser.parse_args()

    if args.groups < 1:
        raise ValueError(f"--groups doit valoir au moins 1 (recu : {args.groups})")

    webfiles = _locate_webfiles()
    bundle = _read_entry(webfiles, _BUNDLE_ENTRY)
    index_html = _read_entry(webfiles, _INDEX_ENTRY)
    current = _current_groups(bundle)

    patched_bundle = _PATTERN.sub(rf"\g<1>{args.groups}\g<3>", bundle, count=1)
    patched_index = _cache_bust(index_html, patched_bundle)
    up_to_date = patched_bundle == bundle and patched_index == index_html

    if args.check:
        state = "a jour" if up_to_date else "a patcher"
        print(f"{webfiles} : {current} groupe(s) deplie(s) au chargement — {state}")
        return 0 if up_to_date else 1

    if up_to_date:
        print(f"deja patche : {current} groupe(s) deplie(s) — {webfiles}")
        return 0

    _rewrite_archive(
        webfiles,
        {
            _BUNDLE_ENTRY: patched_bundle.encode("utf-8"),
            _INDEX_ENTRY: patched_index.encode("utf-8"),
        },
    )
    print(f"{webfiles} : {current} -> {args.groups} groupe(s) deplie(s) au chargement")
    print("redemarrer TensorBoard (le bundle est lu une seule fois au demarrage)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
