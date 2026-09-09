"""La frontière de collecte entre les deux harnais front — vitest d'un côté, Playwright de l'autre.

CE QUE CE FICHIER VERROUILLE, et pourquoi il est en pytest.

Mesuré le 2026-09-09 : `npx vitest run` — la couche B de `scripts/front_test_all.sh:136` — rendait
``Test Files  1 failed | 36 passed (37)``. Le motif de collecte PAR DÉFAUT de Vitest ramasse tout
``**/*.{test,spec}.?(c|m)[jt]s?(x)``, donc aussi ``frontend/tests/e2e/smoke.spec.ts``, dont le
premier import est ``@playwright/test``. La couche B était rouge PAR CONSTRUCTION, indépendamment
du code testé, et le script qui l'orchestre ne pouvait donc jamais rendre PASS.

POURQUOI PAS UN TEST VITEST. Un test qui vérifie le périmètre de collecte ne peut pas vivre DANS ce
périmètre : le jour où la frontière se casse dans le sens « vitest ne ramasse plus rien de `src/` »,
un tel test ne serait pas exécuté du tout, et son silence se lirait comme un succès. Le contrôle
doit venir d'un harnais que la configuration contrôlée ne gouverne pas. C'est le même motif que
`test_hooks_garde_fous.py` (des hooks `.sh` vérifiés depuis pytest) et `test_pytest_config.py`.

CE QU'IL NE FAIT PAS : exécuter vitest. Il lit le motif déclaré et l'APPLIQUE AU DISQUE, ce qui
attrape les deux régressions réelles — la section retirée, et un fichier de test écrit hors du
périmètre déclaré, donc jamais exécuté par personne.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List

import pytest

RACINE = Path(__file__).resolve().parents[3]
VITE_CONFIG = RACINE / "frontend" / "vite.config.ts"
FRONT = RACINE / "frontend"


def _tableau(champ: str) -> List[str]:
    """Les chaînes du tableau `champ: [...]` de la section `test` de `vite.config.ts`.

    Lecture volontairement littérale : la section est écrite à la main et doit le rester lisible.
    Un champ absent lève — il n'y a pas de valeur par défaut acceptable ici, c'est précisément
    l'absence de la section qui a produit le défaut d'origine.
    """
    source = VITE_CONFIG.read_text(encoding="utf-8")
    section = re.search(r"\n  test:\s*\{(.*?)\n  \},", source, re.S)
    if section is None:
        pytest.fail(
            f"{VITE_CONFIG} n'a plus de section `test:` — sans elle, vitest applique son motif de "
            "collecte par défaut et ramasse les specs Playwright de frontend/tests/e2e/."
        )
    motif = re.search(rf"{champ}:\s*\[(.*?)\]", section.group(1), re.S)
    if motif is None:
        pytest.fail(f"la section `test:` de {VITE_CONFIG} ne déclare plus `{champ}`.")
    return [m.group(1) for m in re.finditer(r'"([^"]+)"', motif.group(1))]


def _fichiers(motif: str) -> List[Path]:
    """Les fichiers du disque que ce motif de collecte attrape, sous `frontend/`.

    Vitest accepte l'accolade `{ts,tsx}`, que `glob` ne connaît pas : elle est développée en
    autant de motifs. Tout le reste (`**`, `*`) a la même sémantique des deux côtés.
    """
    accolade = re.search(r"\{([^}]+)\}", motif)
    variantes = (
        [motif.replace(accolade.group(0), ext) for ext in accolade.group(1).split(",")]
        if accolade
        else [motif]
    )
    trouves: List[Path] = []
    for variante in variantes:
        trouves.extend(FRONT.glob(variante))
    return trouves


def test_le_perimetre_vitest_est_ancre_sur_src() -> None:
    """`include` doit nommer `src/`, pas hériter du défaut qui ratisse le dossier entier."""
    include = _tableau("include")
    assert include, "`include` vide : vitest retomberait sur son motif par défaut."
    hors_src = [m for m in include if not m.startswith("src/")]
    assert not hors_src, (
        f"motifs de collecte hors de `src/` : {hors_src}. La frontière entre les deux harnais est "
        "le RÉPERTOIRE — `src/` pour vitest, `tests/` pour Playwright."
    )


def test_le_domaine_de_playwright_est_exclu() -> None:
    exclude = _tableau("exclude")
    assert any(m.startswith("tests/") for m in exclude), (
        f"`exclude` ne nomme pas `tests/` : {exclude}. C'est le répertoire de Playwright ; "
        "l'`include` seul suffirait aujourd'hui, mais les deux ensemble disent l'intention."
    )


def test_aucun_spec_playwright_n_est_collecte_par_vitest() -> None:
    """Le contrôle qui aurait attrapé le défaut : appliquer le motif AU DISQUE.

    VERT VACANT évité : si plus aucun spec Playwright n'existe, ce test ne protège plus rien et
    doit le dire — il échoue au lieu de passer en silence.
    """
    specs = list((FRONT / "tests").rglob("*.spec.ts"))
    assert specs, (
        "aucun `*.spec.ts` sous frontend/tests/ : ce verrou ne protège plus rien. Si la couche "
        "Playwright a été retirée, retirer ce fichier ; sinon, retrouver les specs."
    )
    collectes = {p.resolve() for m in _tableau("include") for p in _fichiers(m)}
    captures = sorted(str(s.relative_to(FRONT)) for s in specs if s.resolve() in collectes)
    assert not captures, (
        f"vitest collecte des specs Playwright : {captures}. Ils importent `@playwright/test`, "
        "que le runner vitest ne fournit pas : la couche B échoue quel que soit l'état du code."
    )


def test_tous_les_tests_front_du_disque_sont_dans_le_perimetre() -> None:
    """L'autre sens de la frontière : un test écrit hors du motif n'est exécuté par PERSONNE.

    Un `include` trop étroit ne casse rien et ne se voit pas — la suite reste verte, elle regarde
    simplement moins de choses. C'est le mode de disparition que ce test ferme.
    """
    sur_disque = {p.resolve() for p in (FRONT / "src").rglob("*.test.ts")}
    sur_disque |= {p.resolve() for p in (FRONT / "src").rglob("*.test.tsx")}
    assert sur_disque, "aucun test vitest sous frontend/src/ — périmètre introuvable."
    collectes = {p.resolve() for m in _tableau("include") for p in _fichiers(m)}
    orphelins = sorted(str(p.relative_to(FRONT)) for p in sur_disque - collectes)
    assert not orphelins, (
        f"tests front hors du périmètre de collecte, donc jamais exécutés : {orphelins}."
    )


def test_la_couche_playwright_declare_sa_dependance() -> None:
    """`@playwright/test` doit rester une dépendance DÉCLARÉE du frontend.

    Mesuré le 2026-09-09 : le paquet est déclaré en `devDependencies` mais absent de
    `frontend/node_modules` sur cette machine — la couche C ne peut pas s'exécuter tant que
    `npm install` n'a pas été rejoué. Ce test verrouille la DÉCLARATION, seule chose qui vive dans
    le dépôt ; l'installation, elle, est une action d'environnement (cf. tests.md).
    """
    package = json.loads((FRONT / "package.json").read_text(encoding="utf-8"))
    dev = package.get("devDependencies", {})
    assert "@playwright/test" in dev, (
        "`@playwright/test` n'est plus déclaré : la couche C de scripts/front_test_all.sh ne peut "
        "plus être installée de façon reproductible."
    )
