"""Verrous du contrôle documentaire.

Ce que ces tests protègent, et pourquoi chacun existe :

- la RÉSOLUTION des chemins relatifs. Le 2026-08-11, le contrôle rendait 18 renvois cassés sur
  `V11_phaseA.md` alors que les 9 cibles distinctes existaient toutes : la classe de caractères
  de la regex excluait le point, `../../engine/x.py` devenait `/engine/x.py`, et `ROOT / name`
  transformait ce fragment en chemin absolu inexistant.
- la DÉTECTION d'une valeur périmée. Un contrôle qui ne sait que confirmer ne prouve rien : il
  faut montrer qu'il vire au rouge quand le document ment.
- l'ASSERTION ORPHELINE. C'est la garde anti-vert-vacant : sans elle, reformuler la phrase suffit
  à désarmer le contrôle en silence, et on retrouve le défaut qu'il devait fermer.
- l'ABSENCE d'appariement en prose, et le rejet des faux positifs par la FORME. Un contrôle qui
  crie à tort finit désactivé ; ces deux cas sont ceux qui le faisaient crier.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

from tests._chargeur_script import charger_script

ROOT = pathlib.Path(__file__).resolve().parents[3]
cdr = charger_script("scripts/check_doc_references.py")


def write(tmp_path: pathlib.Path, name: str, body: str) -> pathlib.Path:
    doc = tmp_path / name
    doc.write_text(body, encoding="utf-8")
    return doc


# --------------------------------------------------------------------------- résolution


def test_parent_relative_path_resolves() -> None:
    """`../../engine/…` depuis un doc de `1_Agent/` désigne bien le fichier du dépôt."""
    doc_dir = ROOT / "Documentation" / "Implémentation" / "1_Agent"
    assert cdr.resolve("../../../engine/w40k_core.py", doc_dir) == ROOT / "engine" / "w40k_core.py"


def test_parent_relative_path_is_captured_whole() -> None:
    """La regex capture le préfixe `../`, sinon la résolution reçoit un fragment absolu."""
    assert cdr.names_in("voir [x](../../../engine/w40k_core.py)") == ["../../../engine/w40k_core.py"]


def test_doc_relative_and_root_relative_both_resolve() -> None:
    """Les deux conventions du corpus coexistent et doivent être servies toutes les deux."""
    docs = ROOT / "Documentation" / "Implémentation"
    assert cdr.resolve("1_Agent/V11_phaseA.md", docs) is not None
    assert cdr.resolve("engine/w40k_core.py", docs) is not None


def test_absolute_path_that_does_not_exist_is_broken() -> None:
    """Un absolu faux reste faux : le réessayer depuis la racine masquerait un renvoi cassé."""
    assert cdr.resolve("/engine/w40k_core.py", ROOT) is None


def test_a_bare_neighbour_resolves_to_the_document_directory(tmp_path: pathlib.Path) -> None:
    """Un nom NU adjacent au document résout chez lui — la sémantique des liens markdown.

    Les fichiers sujets de `Documentation/Roadmap/` se lient entre eux par nom nu
    (`[bot.md#etape8](bot.md#etape8)`) : cherché seulement depuis la racine et les arbres de
    documentation, chaque lien interne sortait FICHIER INTROUVABLE + LIEN MORT (41 fois sur
    l'index au premier passage du corpus partitionné, 2026-08-18).
    """
    write(tmp_path, "bot.md", "# cible\n")
    doc = write(tmp_path, "note.md", "voir [bot.md#etape8](bot.md#etape8) et [bot.md](bot.md)\n")
    assert cdr.resolve("bot.md", tmp_path) == tmp_path / "bot.md"
    _checked, _skipped, broken = cdr.check_links(doc)
    assert not broken


# --------------------------------------------------------------------------- valeurs


def test_stale_value_is_detected(tmp_path: pathlib.Path) -> None:
    doc = write(tmp_path, "v11_chemin_critique.md", "les **99** profils sont à 48 envs\n")
    _verified, broken = cdr.check_values(doc)
    assert any("VALEUR PÉRIMÉE" in entry and "99" in entry for entry in broken)


def test_true_value_is_confirmed(tmp_path: pathlib.Path) -> None:
    count = len(cdr.agent_profiles())
    doc = write(tmp_path, "v11_chemin_critique.md", f"les **{count}** profils\n")
    verified, broken = cdr.check_values(doc)
    assert verified == 1
    assert not any("VALEUR PÉRIMÉE" in entry for entry in broken)


def test_orphan_assertion_is_reported(tmp_path: pathlib.Path) -> None:
    """Une phrase reformulée doit faire ROUGIR le contrôle, pas le rendre muet."""
    doc = write(tmp_path, "v11_chemin_critique.md", "plus aucune des phrases surveillees ici\n")
    _verified, broken = cdr.check_values(doc)
    assert len(broken) == len(cdr.VALUE_CHECKS["v11_chemin_critique.md"])
    assert all("ASSERTION ORPHELINE" in entry for entry in broken)


def test_the_gate_ceiling_is_read_from_the_gate(tmp_path: pathlib.Path) -> None:
    """Le plafond annoncé par §5 se confronte à `MAX_UNDECLARED`, pas à une relecture du texte."""
    ceiling = cdr.expected_gate_ceiling(None)
    doc = write(tmp_path, "ROADMAP_INDEX.md", f"est refusée quand **{ceiling}** chantiers ont été livrés\n")
    verified, broken = cdr.check_values(doc)
    assert verified == 1
    assert not any("plafond" in entry for entry in broken)


def test_a_stale_gate_ceiling_is_detected(tmp_path: pathlib.Path) -> None:
    """Le cas vécu : le document a annoncé 3 pendant que la porte refusait à 2."""
    ceiling = cdr.expected_gate_ceiling(None)
    doc = write(
        tmp_path, "ROADMAP_INDEX.md", f"est refusée quand **{ceiling + 1}** chantiers ont été livrés\n"
    )
    _verified, broken = cdr.check_values(doc)
    assert any("VALEUR PÉRIMÉE" in entry and f"la source dit {ceiling}" in entry for entry in broken)


def test_the_gate_ceiling_matches_the_real_roadmap() -> None:
    """Bout en bout, sur le document réel : la phrase existe et dit la valeur de la porte."""
    text = (ROOT / "Documentation" / "Roadmap" / "ROADMAP_INDEX.md").read_text(encoding="utf-8")
    claims = cdr.claim_gate_ceiling(text)
    assert claims, "ROADMAP_INDEX.md n'annonce plus le plafond de la porte — assertion orpheline"
    assert all(value == cdr.expected_gate_ceiling(None) for _where, value in claims)


def test_profile_table_reads_thousands_separator(tmp_path: pathlib.Path) -> None:
    """« 10 000 » vaut dix mille : le lire comme 10 inventerait une valeur périmée."""
    episodes = cdr.agent_profiles()["x1"]["total_episodes"]
    final = cdr.agent_profiles()["x1"]["callback_params"]["bot_eval_final"]
    doc = write(
        tmp_path, "v11_chemin_critique.md", f"| `x1` | {episodes:,} | {final} |\n".replace(",", " ")
    )
    claims = dict(cdr.claim_profile_table(doc.read_text(encoding="utf-8")))
    assert claims["x1.total_episodes"] == episodes


# --------------------------------------------------------------------------- liens


def test_dead_link_is_detected(tmp_path: pathlib.Path) -> None:
    doc = write(tmp_path, "note.md", "voir [ça](A_faire/ce_fichier_n_existe_pas.md)\n")
    _checked, _skipped, broken = cdr.check_links(doc)
    assert len(broken) == 1 and "LIEN MORT" in broken[0]


@pytest.mark.parametrize("target", ["fichier", '[^"\\\']+'])
def test_regex_noise_is_not_taken_for_a_link(tmp_path: pathlib.Path, target: str) -> None:
    """Écartés sur la FORME. Une liste d'exceptions nommées masquerait un vrai lien mort."""
    doc = write(tmp_path, "note.md", f"texte [x]({target}#L1)\n")
    checked, skipped, broken = cdr.check_links(doc)
    assert (checked, skipped, broken) == (0, 1, [])


def test_live_link_is_verified(tmp_path: pathlib.Path) -> None:
    doc = write(tmp_path, "note.md", "voir [le moteur](engine/w40k_core.py)\n")
    checked, _skipped, broken = cdr.check_links(doc)
    assert checked == 1 and not broken


# --------------------------------------------------------------------------- renvois


def test_prose_never_pairs_symbols(tmp_path: pathlib.Path) -> None:
    """Une phrase cite un fichier et, plus loin, des symboles étrangers : pas une erreur."""
    doc = write(tmp_path, "note.md", "la suite large (`pyright`, `check_ai_rules.py`, `biome`)\n")
    resolved, unverifiable, broken = cdr.check_references(doc)
    assert (resolved, unverifiable, broken) == (0, 1, [])


def test_table_cell_still_pairs_symbols(tmp_path: pathlib.Path) -> None:
    """Le tableau reste le lieu du renvoi PORTEUR : l'appariement doit y rester actif."""
    doc = write(tmp_path, "note.md", "| x | `engine/w40k_core.py` → `_get_unit_by_id` | y |\n")
    resolved, _unverifiable, broken = cdr.check_references(doc)
    assert resolved == 1 and not broken


def test_table_cell_with_absent_symbol_is_broken(tmp_path: pathlib.Path) -> None:
    doc = write(tmp_path, "note.md", "| x | `engine/w40k_core.py` → `zzz_symbole_absent` | y |\n")
    _resolved, _unverifiable, broken = cdr.check_references(doc)
    assert len(broken) == 1 and "AUCUN SYMBOLE" in broken[0]


def test_a_table_word_no_longer_confirms_anything(tmp_path: pathlib.Path) -> None:
    """Le tableau applique le MÊME critère de symbole que la prose.

    Mesuré : 8 renvois du corpus étaient « confirmés » par un mot ordinaire retrouvé dans le code
    (`leader`, `CORS`, `Objectives`, `False`). La prose refusait déjà ces jetons ; une cellule ne
    peut pas être un endroit où la même phrase devient vraie.
    """
    doc = write(tmp_path, "note.md", "| x | `engine/w40k_core.py` → `leader` | y |\n")
    resolved, unverifiable, broken = cdr.check_references(doc)
    assert (resolved, unverifiable, broken) == (0, 1, [])


@pytest.mark.parametrize("word", ["False", "Objectives", "CORS"])
def test_a_capitalised_word_is_not_a_symbol(tmp_path: pathlib.Path, word: str) -> None:
    """Un mot CAPITALISÉ n'est pas plus un symbole qu'un mot minuscule.

    `token != token.lower()` tenait `False` pour du code : présent dans n'importe quel fichier
    Python, il confirmait tout ce qu'on lui présentait. Un symbole composé se reconnaît à sa
    BOSSE de casse (`GameClient`), pas à sa première lettre.
    """
    doc = write(tmp_path, "note.md", f"| x | `engine/w40k_core.py` → `{word}` | y |\n")
    assert cdr.check_references(doc) == (0, 1, [])
    assert cdr.is_symbol_token("GameClient") and cdr.is_symbol_token("W40K_PERSIST_DIR")


def test_the_colon_list_refuses_a_path_in_any_position(tmp_path: pathlib.Path) -> None:
    """Le chemin avalé n'arrive pas qu'en tête de liste.

    Gardée sur le seul PREMIER jeton, la liste `a`, `b/c.py` (`sym`) consommait le renvoi suivant
    et son affirmation ferme : la ligne sortait entièrement invérifiable.
    """
    doc = write(
        tmp_path, "note.md",
        "voir `ai/train.py` : `_zzz_absent_du_train`, `engine/w40k_core.py` (`zzz_supprime`)\n",
    )
    _resolved, _unverifiable, broken = cdr.check_references(doc)
    assert len(broken) == 2
    assert any("zzz_supprime" in entry and "w40k_core" in entry for entry in broken)


def test_a_table_adjacent_claim_is_firm(tmp_path: pathlib.Path) -> None:
    """`x.py` (`a`, `b`) affirme autant entre deux barres verticales que dans une phrase.

    17 cellules du corpus portent cette forme et passaient au régime mou de la co-occurrence : un
    seul symbole vivant suffisait à valider la ligne, la mort de l'autre restait invisible.
    """
    doc = write(
        tmp_path, "note.md",
        "| x | `engine/w40k_core.py` (`_get_unit_by_id`, `zzz_supprimee`) | y |\n",
    )
    resolved, _unverifiable, broken = cdr.check_references(doc)
    assert resolved == 0 and len(broken) == 1
    assert "SYMBOLE ABSENT" in broken[0] and "zzz_supprimee" in broken[0]


def test_a_symbol_attributed_to_one_file_is_not_opposed_to_its_neighbours(
    tmp_path: pathlib.Path,
) -> None:
    """Une cellule qui attribue ses symboles à UN fichier n'affirme rien sur les autres.

    Cas réel (`analyzer_couverture.md` §7) : trois fichiers cités, les symboles entre parenthèses
    n'appartiennent qu'au deuxième. Les opposer aux deux autres les rendait rouges pour des
    symboles que la cellule attribue explicitement ailleurs.
    """
    doc = write(
        tmp_path, "note.md",
        "| `ai/train.py` (1186 l.), `engine/w40k_core.py` (`_get_unit_by_id`), "
        "`ai/bot_evaluation.py` | commentaire |\n",
    )
    resolved, unverifiable, broken = cdr.check_references(doc)
    assert (resolved, unverifiable, broken) == (1, 2, [])


def test_an_attribution_holds_even_when_its_file_cannot_be_confronted(
    tmp_path: pathlib.Path,
) -> None:
    """L'attribution est un fait du DOCUMENT, pas une conséquence de ce que la machine sait lire.

    `conftest.py` est ambigu, donc son symbole n'est confronté à rien — mais la cellule le lui
    attribue quand même, et l'opposer au fichier voisin rendait rouge un document correct.
    """
    doc = write(tmp_path, "note.md", "| `conftest.py` (`GameClient`), `engine/w40k_core.py` | x |\n")
    assert cdr.check_references(doc) == (0, 2, [])


def test_brace_enumeration_is_not_a_file(tmp_path: pathlib.Path) -> None:
    """`{move,charge}_handler.py` désigne un ensemble ; `_handler.py` n'existe pas."""
    doc = write(tmp_path, "note.md", "`ai/analyzer_phases/{move,charge}_handler.py` et le reste\n")
    _resolved, _unverifiable, broken = cdr.check_references(doc)
    assert not broken


def test_missing_file_in_table_is_broken(tmp_path: pathlib.Path) -> None:
    doc = write(tmp_path, "note.md", "| x | `engine/ce_module_n_existe_pas.py` | `truc` |\n")
    _resolved, _unverifiable, broken = cdr.check_references(doc)
    assert len(broken) == 1 and "FICHIER INTROUVABLE" in broken[0]


# --------------------------------------------------------------------------- ancres


def test_line_anchor_is_reported(tmp_path: pathlib.Path) -> None:
    doc = write(tmp_path, "ROADMAP_INDEX.md", "voir `engine/observation_entities.py:274`\n")
    assert len(cdr.check_anchors(doc)) == 1


def test_symbol_reference_is_not_an_anchor(tmp_path: pathlib.Path) -> None:
    doc = write(tmp_path, "ROADMAP_INDEX.md", "voir `def compute_candidate_footprint` dans le moteur\n")
    assert cdr.check_anchors(doc) == []


@pytest.mark.parametrize("ref", [
    "BoardPvp.tsx:9290",
    "useBoardHexMemos.ts:117",
    "settings.json:17",
    "V11_agent_rework.md:3713",
    "docker-compose.yml:18",
    "pytest.ini:12",
    "useBoardHexMemos.test.ts:117",
    "engine/ce_module_a_ete_supprime.py:412",
    "Annexe_script_BDD_auth.sql:42",
    ".env.example:7",
    "frontend.code-workspace:3",
])
def test_a_line_anchor_of_any_extension_is_reported(tmp_path: pathlib.Path, ref: str) -> None:
    """La convention §5 porte sur la LIGNE, pas sur le langage.

    Mesuré le 2026-08-12 : les seules ancres survivantes de `ROADMAP.md` étaient deux `.tsx`,
    décalées de plusieurs milliers de lignes et invisibles au contrôle, qui affichait pourtant
    « 0 renvoi ». Une liste de suffixes aurait reconduit le trou sur `.yml` et `.ini` — ces deux
    cas-là sont dans l'échantillon pour cette raison, et `docker-compose.yml:18` était bel et bien
    présent dans `Security.md`.
    """
    doc = write(tmp_path, "ROADMAP_INDEX.md", f"le composant `{ref}` recopie les hexes\n")
    entries = cdr.check_anchors(doc)
    assert len(entries) == 1
    # Le renvoi est cité ENTIER, chemin compris. Capturé sans ses points internes,
    # `useBoardHexMemos.test.ts:117` sortait comme `test.ts:117` ; capturé sans son dossier,
    # `engine/…/move_handler.py:99` sortait comme `move_handler.py:99`, qui désigne cinq fichiers
    # du dépôt au lieu d'un. Dans les deux cas le message n'envoie nulle part.
    assert ref in entries[0]


@pytest.mark.parametrize("line", [
    "`_auto_declared_order` L6462 → **9133**\n",
    "listés en `1_Agent/V11_agent_rework.md` §0bis (l.3713-3735)\n",
])
def test_the_other_two_spellings_of_an_anchor_are_reported(
    tmp_path: pathlib.Path, line: str
) -> None:
    """§5 interdit le NUMÉRO DE LIGNE, pas une graphie particulière.

    Ces deux écritures vivaient dans `ROADMAP.md` au 2026-08-12 pendant que le contrôle affichait
    « 0 renvoi » : il n'en surveillait qu'une sur trois.
    """
    doc = write(tmp_path, "ROADMAP_INDEX.md", line)
    assert len(cdr.check_anchors(doc)) >= 1


def test_a_step_log_entry_is_not_an_anchor(tmp_path: pathlib.Path) -> None:
    """`Ln` NOMME une entrée du `step.log` : le corpus en porte 34, dont 28 NUES dans le §7.

    Le seuil n'est pas écrit en dur — il est lu dans le tableau §7 et grandit avec lui. Ce test
    construit donc son échantillon depuis la MÊME source : figer `L28` ici le rendrait faux à la
    prochaine entrée, ce qui est exactement le défaut qu'on ferme.
    """
    largest = cdr.step_log_entries()[1]
    doc = write(tmp_path, "ROADMAP_INDEX.md", f"| L1 | `L3` → `L{largest}` |\n")
    assert cdr.check_anchors(doc) == []


def test_a_line_number_beyond_the_step_log_is_an_anchor(tmp_path: pathlib.Path) -> None:
    """Au-delà du plus grand index existant, `Ln` ne peut plus être un nom d'entrée."""
    largest = cdr.step_log_entries()[1]
    doc = write(tmp_path, "ROADMAP_INDEX.md", f"`_auto_declared_order` L{largest + 1} → **9133**\n")
    assert len(cdr.check_anchors(doc)) == 1


def test_a_citation_cannot_be_framed_by_two_files(tmp_path: pathlib.Path) -> None:
    """Encadrer une citation de deux fichiers n'affirme plus rien, et c'est voulu.

    Une citation encadrée affirmait deux choses contradictoires, et le fichier ACCUSÉ dépendait du
    seul ordre des mots. Depuis que le deux-points doit terminer la ligne et la parenthèse se
    refermer, l'encadrement n'est plus exprimable : la ligne ci-dessous ne porte qu'une affirmation,
    celle qui se clôt, et le reste est compté non vérifié plutôt que deviné.
    """
    porteur = tmp_path / "porteur.py"
    porteur.write_text("def agit():\n    return 1\n", encoding="utf-8")
    absent = tmp_path / "absent.py"
    absent.write_text("VALEUR = 1\n", encoding="utf-8")
    doc = write(tmp_path, "ROADMAP_INDEX.md", f"`{absent}` : `def agit` : `{porteur}`\n")
    checked, unverifiable, broken, _notes = cdr.check_symbol_kinds(doc)
    assert (checked, unverifiable, broken) == (1, 0, [])


@pytest.mark.parametrize("line", [
    "mesuré sur torch 2.13, git 2.43, à 15 h 18\n",
    "le rapport de charge tient à `3.7:1` après la bascule\n",
    "voir `Makefile.local:12`, hors dépôt\n",
    "le modèle `ViT-L336` et la variante `SM-L1000`\n",
])
def test_what_is_not_a_repo_reference_is_not_an_anchor(
    tmp_path: pathlib.Path, line: str
) -> None:
    """Ce qui a la FORME d'une ancre sans désigner de fichier du dépôt n'en est pas une.

    `3.7:1` et `Makefile.local:12` ont bien la forme `nom.ext:chiffres` et traversent donc
    `LINE_ANCHOR` : c'est `is_a_line_anchor` qui les écarte, sur une extension qu'aucun fichier
    suivi n'emploie. Sans eux, ce test resterait vert avec le filtre remplacé par `return True`.
    `ViT-L336`, lui, est écarté plus tôt, par le voisinage gauche de `BARE_ANCHOR`.
    """
    doc = write(tmp_path, "ROADMAP_INDEX.md", line)
    assert cdr.check_anchors(doc) == []


# --------------------------------------------------------------------------- sortes


def test_a_def_claimed_for_a_class_is_reported(tmp_path: pathlib.Path) -> None:
    """Le défaut réel : `ROADMAP.md` promettait un grep `def` sur deux `class`, qui rend 0 hit."""
    doc = write(
        tmp_path, "ROADMAP_INDEX.md",
        "c'est `def EpisodeTerminationCallback` (`ai/training_callbacks.py`) qui porte le budget\n",
    )
    _checked, _unverifiable, broken, _notes = cdr.check_symbol_kinds(doc)
    assert len(broken) == 1
    assert "SORTE FAUSSE" in broken[0] and "`class`" in broken[0]


def test_the_right_kind_is_confirmed(tmp_path: pathlib.Path) -> None:
    doc = write(
        tmp_path, "ROADMAP_INDEX.md",
        "c'est `class EpisodeTerminationCallback` (`ai/training_callbacks.py`) qui compte\n",
    )
    checked, _unverifiable, broken, _notes = cdr.check_symbol_kinds(doc)
    assert checked == 1 and not broken


def test_a_symbol_that_is_not_defined_at_all_is_reported(tmp_path: pathlib.Path) -> None:
    doc = write(
        tmp_path, "ROADMAP_INDEX.md",
        "voir `def _ce_symbole_na_jamais_existe` (`ai/training_callbacks.py`)\n",
    )
    _checked, _unverifiable, broken, _notes = cdr.check_symbol_kinds(doc)
    assert len(broken) == 1 and "SYMBOLE NON DÉFINI" in broken[0]


@pytest.mark.parametrize("body", [
    'def porteur():\n    """Le lecteur cherchera `def write`, qui vit ailleurs."""\n'
    "    return write(1)\n",
    'PROSE = """\n    def write(source):\n        exemple recopié, pas une définition\n"""\n',
])
def test_a_mention_is_not_a_definition(tmp_path: pathlib.Path, body: str) -> None:
    """Une MENTION ne vaut pas définition, y compris recopiée indentée dans une docstring.

    Les deux corps citent `def write` sans le définir. Un motif textuel — même ancré en début de
    ligne, l'indentation étant tolérée — les prend l'un et l'autre pour des définitions et
    confirme la sorte qu'on lui souffle : c'est le vert vacant, côté sortes. La lecture par AST
    ferme les deux d'un coup.
    """
    module = tmp_path / "faux_module.py"
    module.write_text(body, encoding="utf-8")
    doc = write(tmp_path, "ROADMAP_INDEX.md", f"voir `def write` (`{module}`)\n")
    _checked, _unverifiable, broken, _notes = cdr.check_symbol_kinds(doc)
    assert len(broken) == 1 and "SYMBOLE NON DÉFINI" in broken[0]


@pytest.mark.parametrize("citation", ["`def sert`", "`async def sert`"])
def test_an_async_def_is_a_def(tmp_path: pathlib.Path, citation: str) -> None:
    """`async def X` est un `def` des deux côtés : dans le code, et dans la CITATION.

    Traiter `AsyncFunctionDef` côté AST sans accepter `async def` côté citation, c'était écrire un
    traitement inatteignable : la ligne sortait « 0 fausse, 0 non vérifiée », le silence même que
    la passe existe pour refuser.
    """
    module = tmp_path / "faux_module.py"
    module.write_text("async def sert(requete):\n    return requete\n", encoding="utf-8")
    doc = write(tmp_path, "ROADMAP_INDEX.md", f"voir {citation} (`{module}`)\n")
    checked, _unverifiable, broken, _notes = cdr.check_symbol_kinds(doc)
    assert checked == 1 and not broken


def test_a_nested_definition_counts(tmp_path: pathlib.Path) -> None:
    """Une méthode citée par son nom est bien définie dans le fichier cité."""
    module = tmp_path / "faux_module.py"
    module.write_text("class Porteur:\n    def methode(self):\n        return 1\n", encoding="utf-8")
    doc = write(tmp_path, "ROADMAP_INDEX.md", f"voir `def methode` (`{module}`)\n")
    checked, _unverifiable, broken, _notes = cdr.check_symbol_kinds(doc)
    assert checked == 1 and not broken


@pytest.mark.parametrize("citation", [
    "`def EpisodeTerminationCallback()`",
    "`def EpisodeTerminationCallback(model, verbose=0) -> None`",
    "`def EpisodeTerminationCallback:`",
])
def test_a_signature_does_not_disarm_the_pass(tmp_path: pathlib.Path, citation: str) -> None:
    """Citer la signature est la forme la plus courante : elle doit être CONFRONTÉE, pas ignorée.

    Ignorée, elle ne comptait même pas comme non vérifiée — la passe rendait « 0 fausse, 0 non
    vérifiée » sur une ligne fausse.
    """
    doc = write(tmp_path, "ROADMAP_INDEX.md", f"c'est {citation} (`ai/training_callbacks.py`) qui compte\n")
    _checked, _unverifiable, broken, _notes = cdr.check_symbol_kinds(doc)
    assert len(broken) == 1 and "SORTE FAUSSE" in broken[0]


def test_an_ambiguous_file_makes_the_cell_unconfrontable(tmp_path: pathlib.Path) -> None:
    """`conftest.py` existe cinq fois : le document ne dit pas duquel il parle.

    L'adjacence donne un fichier, pas une identité : ouvrir le premier trouvé, c'est interroger un
    fichier dont le document ne parle peut-être pas — même doctrine qu'en passe 1.
    """
    doc = write(tmp_path, "ROADMAP_INDEX.md", "voir `class GameClient` (`conftest.py`)\n")
    checked, unverifiable, broken, _notes = cdr.check_symbol_kinds(doc)
    assert (checked, unverifiable, broken) == (0, 1, [])


def test_an_unparsable_file_is_not_blamed_on_the_document(tmp_path: pathlib.Path) -> None:
    """Un `.py` du dépôt qui ne compile pas n'est pas un défaut du DOCUMENT.

    Scénario vécu le 2026-08-12 : `ai/train.py` ne compilait pas à HEAD. Imputer sa syntaxe au
    document aurait rendu la porte documentaire rouge — et invérifiable — pour un défaut de code.
    Compté non vérifié, jamais « symbole absent », qui aurait accusé le document à tort.
    """
    module = tmp_path / "faux_module.py"
    module.write_text("def casse(:\n", encoding="utf-8")
    doc = write(tmp_path, "ROADMAP_INDEX.md", f"voir `def casse` (`{module}`)\n")
    checked, unverifiable, broken, _notes = cdr.check_symbol_kinds(doc)
    assert (checked, unverifiable, broken) == (0, 1, [])


def test_a_table_never_pairs_across_cells(tmp_path: pathlib.Path) -> None:
    """Une cellule cite le symbole, une AUTRE cite un fichier étranger : rien n'est affirmé.

    `analyzer_couverture.md` est presque entièrement tabulaire ; apparier la ligne entière le
    rendrait rouge à la première ligne de cette forme, et un contrôle qui crie à tort finit
    désactivé.
    """
    doc = write(
        tmp_path, "ROADMAP_INDEX.md",
        "| `class EpisodeTerminationCallback` | oui | `ai/train.py` |\n",
    )
    checked, unverifiable, broken, _notes = cdr.check_symbol_kinds(doc)
    assert (checked, unverifiable, broken) == (0, 1, [])


def test_prose_never_pairs_a_distant_file(tmp_path: pathlib.Path) -> None:
    """Le seul `.py` de la phrase n'est PAS le fichier du symbole cité.

    Scénario mesuré : la phrase parle d'un fichier du dépôt puis cite une classe de SB3, qui n'y
    vit évidemment pas. Apparier les deux sortait un SYMBOLE NON DÉFINI, donc un code 1, sur une
    phrase juste — et un contrôle qui crie à tort finit désactivé.
    """
    doc = write(
        tmp_path, "ROADMAP_INDEX.md",
        "les rampes vivent dans `ai/training_callbacks.py` ; on y branche `class VecNormalize` "
        "de SB3\n",
    )
    checked, unverifiable, broken, _notes = cdr.check_symbol_kinds(doc)
    assert (checked, unverifiable, broken) == (0, 1, [])


def test_a_parenthesis_that_keeps_talking_is_not_a_claim(tmp_path: pathlib.Path) -> None:
    """`class X` (`a/b.py` l'importe de SB3) n'affirme pas que `X` vit dans `a/b.py`.

    C'est la distinction ferme/molle de la passe 1 : sans elle, cette ligne sortait CASSÉE ici
    (donc code 1) et « non vérifiée » là, sur exactement la même phrase.
    """
    doc = write(
        tmp_path, "ROADMAP_INDEX.md",
        "on branche `class VecNormalize` (`ai/training_callbacks.py` l'importe de SB3)\n",
    )
    checked, unverifiable, broken, _notes = cdr.check_symbol_kinds(doc)
    assert (checked, unverifiable, broken) == (0, 1, [])


@pytest.mark.parametrize("line", [
    "le budget vit dans `ai/training_callbacks.py` (`def EpisodeTerminationCallback`)\n",
    "le budget vit dans `ai/training_callbacks.py` : `def EpisodeTerminationCallback`\n",
])
def test_the_file_may_come_first(tmp_path: pathlib.Path, line: str) -> None:
    """L'ordre `fichier.py` (`def X`) est celui de la passe 1 : le défaut y passait entier.

    Ni la passe 5 (qui n'appariait que symbole-puis-fichier) ni la passe 1 (dont
    `is_symbol_token` refuse l'espace de « def Foo ») ne voyaient cette écriture. Le motif même
    qui a ouvert ce chantier, écrit à l'envers, sortait vert.
    """
    doc = write(tmp_path, "ROADMAP_INDEX.md", line)
    _checked, unverifiable, broken, _notes = cdr.check_symbol_kinds(doc)
    assert len(broken) == 1 and "SORTE FAUSSE" in broken[0]
    # La citation est APPARIÉE : la compter EN PLUS comme « non vérifiée » ferait dire au rapport
    # qu'un renvoi confronté ne l'a pas été.
    assert unverifiable == 0


@pytest.mark.parametrize("line", [
    "on branche `class VecNormalize` `ai/training_callbacks.py` l'importe de SB3\n",
    "`ai/training_callbacks.py` `def EpisodeTerminationCallback` porte le budget\n",
])
def test_a_bare_juxtaposition_is_not_a_firm_claim(tmp_path: pathlib.Path, line: str) -> None:
    """Deux jetons collés ne se distinguent pas d'une phrase qui continue — dans les DEUX sens.

    Tenue pour ferme, la première ligne sortait un SYMBOLE NON DÉFINI (donc un code 1) sur une
    phrase juste ; et l'accepter dans un sens sans l'accepter dans l'autre faisait dépendre le
    verdict de l'ordre des mots. Le lien fermé — parenthèse ou deux-points — est exigé partout.
    """
    doc = write(tmp_path, "ROADMAP_INDEX.md", line)
    checked, unverifiable, broken, _notes = cdr.check_symbol_kinds(doc)
    assert (checked, unverifiable, broken) == (0, 1, [])


def test_a_qualified_citation_is_confronted(tmp_path: pathlib.Path) -> None:
    """`def Classe.methode` est une citation : la rejeter la faisait disparaître de TOUS les compteurs.

    Ni vérifiée, ni non vérifiée : le rapport annonçait « 0 fausse » sur une ligne jamais regardée.
    Le nom QUALIFIÉ est confronté tel quel — `definitions` indexe chaque définition sous ses deux
    noms —, et le test suivant prouve qu'un homonyme de module ne suffit pas à le satisfaire.
    """
    module = tmp_path / "faux_module.py"
    module.write_text("class Moteur:\n    def agit(self):\n        return 1\n", encoding="utf-8")
    doc = write(tmp_path, "ROADMAP_INDEX.md", f"voir `class Moteur.agit` (`{module}`)\n")
    _checked, _unverifiable, broken, _notes = cdr.check_symbol_kinds(doc)
    assert len(broken) == 1 and "SORTE FAUSSE" in broken[0]


def test_a_qualified_citation_is_not_satisfied_by_a_module_level_twin(
    tmp_path: pathlib.Path
) -> None:
    """`def Moteur.agit` n'est pas confirmé par un `def agit` de module, sans `Moteur` nulle part.

    Confronter le seul dernier segment rendait vert un document dont le grep promis rend 0 hit —
    le défaut même que cette passe existe pour attraper.
    """
    module = tmp_path / "faux_module.py"
    module.write_text("def agit():\n    return 1\n", encoding="utf-8")
    doc = write(tmp_path, "ROADMAP_INDEX.md", f"voir `def Moteur.agit` (`{module}`)\n")
    checked, _unverifiable, broken, _notes = cdr.check_symbol_kinds(doc)
    assert checked == 0
    assert len(broken) == 1 and "SYMBOLE NON DÉFINI" in broken[0]


def test_an_extensionless_tracked_file_is_an_anchor(tmp_path: pathlib.Path) -> None:
    """`Dockerfile:14` est un renvoi de ligne — et `Security.md` cite justement ce fichier."""
    doc = write(tmp_path, "ROADMAP_INDEX.md", "le montage est décrit en `Dockerfile:14`\n")
    assert len(cdr.check_anchors(doc)) == 1


def test_the_same_anchor_written_twice_is_reported_once(tmp_path: pathlib.Path) -> None:
    """`[a.py:629](…/a.py#L629)` porte UN renvoi, écrit dans le texte et dans l'URL.

    Compté deux fois, le rapport annonçait « 2 ancres » et envoyait chercher une seconde qui
    n'existe pas.
    """
    doc = write(
        tmp_path, "ROADMAP_INDEX.md",
        "voir [shared_utils.py:629](../../engine/phase_handlers/shared_utils.py#L629)\n",
    )
    assert len(cdr.check_anchors(doc)) == 1


def test_two_distinct_anchors_sharing_a_number_are_both_reported(
    tmp_path: pathlib.Path
) -> None:
    """Hors lien, deux renvois qui portent le même nombre restent DEUX renvois.

    Dédoublonner sur le seul numéro perdait le second en silence — pire que le doublon qu'on
    voulait éviter.
    """
    doc = write(tmp_path, "ROADMAP_INDEX.md", "les deux sites `shared_utils.py:629` et L629 de BoardPvp\n")
    assert len(cdr.check_anchors(doc)) == 2


def test_two_files_at_the_same_line_inside_one_link_are_both_reported(
    tmp_path: pathlib.Path
) -> None:
    """Deux FICHIERS différents au même numéro, dans un même lien, sont deux renvois."""
    doc = write(tmp_path, "ROADMAP_INDEX.md", "voir [train.py:12 et w40k_core.py:12](x.md)\n")
    assert len(cdr.check_anchors(doc)) == 2


def test_a_file_url_link_repeating_its_anchor_is_reported_once(tmp_path: pathlib.Path) -> None:
    """La forme `file:///` imposée par CLAUDE.md répète le renvoi sans passer par un `#L`.

    Le dédoublonnage doit donc valoir des DEUX côtés du lien, pas seulement pour la graphie `Ln` :
    autrement cette forme-là, la plus courante du corpus, était comptée deux fois.
    """
    doc = write(
        tmp_path, "ROADMAP_INDEX.md",
        "voir [shared_utils.py:629](file:///home/greg/40k/engine/phase_handlers/"
        "shared_utils.py:629)\n",
    )
    assert len(cdr.check_anchors(doc)) == 1


def test_an_unloadable_source_blocks_without_a_traceback(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Une porte de fusion qui ne s'importe plus bloque en une ligne, pas en trace Python."""
    doc = write(tmp_path, "ROADMAP_INDEX.md", "est refusée quand **2** chantiers ont été livrés\n")
    monkeypatch.setattr(
        cdr, "gate_module",
        lambda: (_ for _ in ()).throw(cdr.SourceUnavailable("import cassé")),
    )
    assert cdr.main(["prog", str(doc)]) == 1


def test_a_gate_that_no_longer_imports_is_a_source_failure(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La porte de fusion qui ne s'exécute plus est une SOURCE indisponible, pas une trace brute.

    Un import cassé dans `check_roadmap_declared.py` sortait en `ImportError` nu — hors du filet,
    donc en trace Python, sur un document qui n'y est pour rien.
    """
    faux = tmp_path / "scripts"
    faux.mkdir()
    (faux / "check_roadmap_declared.py").write_text(
        "import ce_module_nexiste_pas\n", encoding="utf-8"
    )
    monkeypatch.setattr(cdr, "ROOT", tmp_path)
    cdr.gate_module.cache_clear()
    try:
        with pytest.raises(cdr.SourceUnavailable):
            cdr.gate_module()
    finally:
        cdr.gate_module.cache_clear()


def test_an_internal_defect_keeps_its_traceback(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un `KeyError` de profil mal formé n'est PAS « une source disparue ».

    Le confondre avec elle annonçait la mauvaise panne et désignait le mauvais fichier : ce qui
    est un défaut interne garde sa trace.
    """
    doc = write(tmp_path, "v11_chemin_critique.md", "les **9** profils\n")
    monkeypatch.setattr(
        cdr, "expected_profile_count",
        lambda: (_ for _ in ()).throw(KeyError("callback_params")),
    )
    with pytest.raises(KeyError):
        cdr.main(["prog", str(doc)])


def test_a_source_that_disappears_blocks_without_a_traceback(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Une SOURCE du contrôle qui s'évapore bloque — mais en une ligne, pas en trace Python.

    Le §7 d'`analyzer_couverture.md` renommé faisait mourir la passe 4 de n'importe quel document,
    y compris ceux qui n'ont aucun rapport avec le `step.log` : une trace envoie alors corriger le
    mauvais fichier, et le script promet 0 ou 1.
    """
    doc = write(tmp_path, "ROADMAP_INDEX.md", "`_auto_declared_order` L6462 → **9133**\n")
    monkeypatch.setattr(
        cdr, "step_log_entries",
        lambda: (_ for _ in ()).throw(cdr.SourceUnavailable("§7 introuvable")),
    )
    assert cdr.main(["prog", str(doc)]) == 1


def test_backticked_prose_with_a_colon_is_not_a_citation(tmp_path: pathlib.Path) -> None:
    """`class Objectives : la liste des objectifs` est une phrase, pas une signature.

    Laisser le deux-points ouvrir n'importe quoi sortait un SYMBOLE NON DÉFINI, donc un code 1,
    sur une ligne juste. Le deux-points de signature est COLLÉ au nom.
    """
    doc = write(
        tmp_path, "ROADMAP_INDEX.md",
        "`class Objectives : la liste des objectifs` (`engine/w40k_core.py`)\n",
    )
    checked, unverifiable, broken, _notes = cdr.check_symbol_kinds(doc)
    assert (checked, unverifiable, broken) == (0, 0, [])


def test_an_unparsable_file_is_named_not_just_counted(tmp_path: pathlib.Path) -> None:
    """Le silence est compté ET sa raison NOMMÉE, sinon la passe s'éteint sans témoin.

    Absorbée dans « pas de fichier adjacent », la panne donnait une raison fausse d'un silence
    réel — et c'est exactement ainsi qu'un contrôle meurt sans que personne ne le voie.
    """
    module = tmp_path / "faux_module.py"
    module.write_text("def casse(:\n", encoding="utf-8")
    doc = write(tmp_path, "ROADMAP_INDEX.md", f"voir `def casse` (`{module}`)\n")
    _checked, unverifiable, broken, notes = cdr.check_symbol_kinds(doc)
    assert (unverifiable, broken) == (1, [])
    assert len(notes) == 1 and "faux_module.py" in notes[0]


@pytest.mark.parametrize("line", [
    "`ai/training_callbacks.py` : `class VecNormalize` est importé de SB3, pas défini ici\n",
    "`class VecNormalize` : `ai/training_callbacks.py` l'importe de SB3\n",
])
def test_a_colon_that_opens_a_sentence_is_not_a_claim(
    tmp_path: pathlib.Path, line: str
) -> None:
    """Le deux-points n'a pas de clôture : il n'affirme que s'il TERMINE la ligne.

    Sans cette garde, la phrase ci-dessus sortait un SYMBOLE NON DÉFINI — donc un code 1 — quand
    la même phrase écrite entre parenthèses était correctement comptée non vérifiée. Le verdict ne
    peut pas dépendre de la ponctuation.
    """
    doc = write(tmp_path, "ROADMAP_INDEX.md", line)
    checked, unverifiable, broken, _notes = cdr.check_symbol_kinds(doc)
    assert (checked, unverifiable, broken) == (0, 1, [])


def test_the_colon_form_claims_in_both_orders(tmp_path: pathlib.Path) -> None:
    """Le deux-points affirme, quel que soit le côté où se trouve le fichier."""
    doc = write(
        tmp_path, "ROADMAP_INDEX.md",
        "`def EpisodeTerminationCallback` : `ai/training_callbacks.py`\n",
    )
    _checked, _unverifiable, broken, _notes = cdr.check_symbol_kinds(doc)
    assert len(broken) == 1 and "SORTE FAUSSE" in broken[0]


def test_the_message_names_the_adjacent_file(tmp_path: pathlib.Path) -> None:
    """Le message accuse le fichier ADJACENT, seul que le contrôle ait ouvert.

    Le fichier cité plus loin dans la phrase n'existe même pas : le nommer enverrait corriger le
    mauvais endroit.
    """
    doc = write(
        tmp_path, "ROADMAP_INDEX.md",
        "`def EpisodeTerminationCallback` (`ai/training_callbacks.py`) a remplacé "
        "`ai/disparu.py`\n",
    )
    _checked, _unverifiable, broken, _notes = cdr.check_symbol_kinds(doc)
    assert len(broken) == 1
    assert "training_callbacks.py" in broken[0] and "disparu" not in broken[0]


@pytest.mark.parametrize("line", [
    "⚠️ ne pas confondre avec `def _EpisodeRampCallback`, du même fichier\n",
    "`def enter_phase` vit entre `engine/game_utils.py` et `ai/train.py`\n",
])
def test_a_kind_without_a_single_file_is_counted_not_guessed(
    tmp_path: pathlib.Path, line: str
) -> None:
    """Zéro ou deux fichiers sur la ligne : rien n'est confrontable, rien n'est inventé.

    « du même fichier » ne se résout pas, et rattacher la ligne au fichier de la précédente
    fabriquerait une affirmation que le document ne fait pas.
    """
    doc = write(tmp_path, "ROADMAP_INDEX.md", line)
    checked, unverifiable, broken, _notes = cdr.check_symbol_kinds(doc)
    assert (checked, unverifiable, broken) == (0, 1, [])


# --------------------------------------------------------------------------- corpus réel


def test_prose_pairs_an_adjacent_symbol(tmp_path: pathlib.Path) -> None:
    """`fichier.py` (`symbole`) est une affirmation du document : elle doit être vérifiée."""
    doc = write(tmp_path, "note.md", "le moteur `engine/w40k_core.py` (`_get_unit_by_id`) le lit\n")
    resolved, _unverifiable, broken = cdr.check_references(doc)
    assert resolved == 1 and not broken


def test_prose_adjacent_symbol_that_is_absent_is_broken(tmp_path: pathlib.Path) -> None:
    doc = write(tmp_path, "note.md", "le moteur `engine/w40k_core.py` (`zzz_absent`) le lit\n")
    _resolved, _unverifiable, broken = cdr.check_references(doc)
    assert len(broken) == 1 and "SYMBOLE ABSENT" in broken[0]


def test_prose_colon_form_is_also_a_claim(tmp_path: pathlib.Path) -> None:
    doc = write(tmp_path, "note.md", "voir `engine/w40k_core.py` : `_get_unit_by_id`\n")
    resolved, _unverifiable, broken = cdr.check_references(doc)
    assert resolved == 1 and not broken


def test_a_filename_between_parentheses_is_not_a_symbol(tmp_path: pathlib.Path) -> None:
    """`moteur.py` (`autre/fichier.py`) cite DEUX fichiers, pas un fichier et son symbole."""
    doc = write(
        tmp_path, "note.md",
        "voir `engine/w40k_core.py` (`ai/hidden_action_finder.py`) pour le détail\n",
    )
    _resolved, _unverifiable, broken = cdr.check_references(doc)
    assert not broken


def test_a_deep_relative_claim_is_confirmed(tmp_path: pathlib.Path) -> None:
    """Un renvoi qui remonte PLUSIEURS niveaux doit être confirmé, pas tronqué.

    Tronqué, il ne se résolvait plus et disparaissait des trois compteurs à la fois. Le test
    exige donc la CONFIRMATION : se contenter de « il sort quelque part » le laisserait passer
    dès que le renvoi cassé est simplement signalé ailleurs.
    """
    (tmp_path / "engine").mkdir()
    (tmp_path / "engine" / "moteur.py").write_text("def _get_unit_by_id():\n    ...\n", "utf-8")
    profond = tmp_path / "a" / "b" / "c"
    profond.mkdir(parents=True)
    doc = profond / "note.md"
    doc.write_text("`../../../engine/moteur.py` (`_get_unit_by_id`) le lit\n", encoding="utf-8")
    resolved, _unverifiable, broken = cdr.check_references(doc)
    assert (resolved, broken) == (1, [])


def test_a_missing_file_claimed_in_prose_is_reported(tmp_path: pathlib.Path) -> None:
    doc = write(tmp_path, "note.md", "`engine/pas_ici.py` (`un_symbole`) ferait foi\n")
    _resolved, _unverifiable, broken = cdr.check_references(doc)
    assert len(broken) == 1 and "FICHIER INTROUVABLE" in broken[0]


def test_a_broken_path_is_not_rescued_by_a_namesake(tmp_path: pathlib.Path) -> None:
    """Deux chemins, un seul nom de fichier : l'appariement ne doit PAS les confondre.

    Une phrase cite couramment un chemin faux depuis ce document (`../engine/x.py`) et, plus
    loin, le bon (`engine/x.py`). Apparié par basename, le premier héritait du fichier du second :
    la paire portait alors un chemin irrésolvable et le contrôle partait en exception, perdant les
    renvois déjà collectés et les documents suivants du run.
    """
    line = "le `../engine/w40k_core.py` (`_get_unit_by_id`) et `engine/w40k_core.py` le lisent\n"
    doc = write(tmp_path, "note.md", line)
    resolved, unverifiable, broken = cdr.check_references(doc)
    assert len(broken) == 1 and "FICHIER INTROUVABLE" in broken[0]
    assert (resolved, unverifiable) == (0, 1)


def test_a_file_cited_twice_is_one_reference(tmp_path: pathlib.Path) -> None:
    """Un fichier cité deux fois vaut UN renvoi, et son voisin sans symbole reste compté.

    En soustrayant des PAIRES au nombre de fichiers, le décompte des invérifiables tombait à zéro :
    `ai/train.py`, confronté à aucun symbole, disparaissait des trois compteurs pendant que
    `resolved` annonçait deux confirmations pour un seul fichier — le vert vacant que ce module
    existe pour fermer.
    """
    doc = write(
        tmp_path, "note.md",
        "`engine/w40k_core.py` (`_get_unit_by_id`) puis `engine/w40k_core.py` "
        "(`_get_unit_by_id`) et `ai/train.py` aussi\n",
    )
    resolved, unverifiable, broken = cdr.check_references(doc)
    assert (resolved, unverifiable, broken) == (1, 1, [])


@pytest.mark.parametrize("line", [
    "`../../../engine/moteur.py` (`_un_symbole`)",
    "`../engine/moteur.py` (`_un_symbole`)",
    "`engine/moteur.py` (`_un_symbole`)",
    "`moteur.py` (`_un_symbole`)",
    "voir `engine/moteur.py` : `_un_symbole`",
    "`a/b/c-d_e.py` (`_un_symbole`)",
    "`config/agents/x.json` (`_un_symbole`)",
    "`Documentation/x.md` (`_un_symbole`)",
    "`*_handler.py` (`_un_symbole`)",
    "`{move,charge,fight}_handler.py` (`_un_symbole`)",
    "`analyzer_phases/*` (`_un_symbole`)",
    "on dépose un `hashlib.md5` (`_un_symbole`) quelque part",
])
def test_adjacent_is_a_subset(line: str) -> None:
    """L'invariant dont dépend l'appariement des symboles en prose.

    Tout fichier que l'appariement adjacent reconnaît doit AUSSI être reconnu par l'extracteur
    général, à l'identique — l'appariement se faisant sur le chemin ENTIER, un fichier que `names_in`
    ignore (joker, énumération `{a,b}`, appel pointé) et que `ADJACENT` retient se verrait apparier
    des symboles sans être jamais résolu. Le sens est un SOUS-ENSEMBLE : ne rien affirmer sur un
    fichier bien vu est licite (la phrase peut ne porter aucun symbole), l'inverse ne l'est pas.
    Les extensions y sont toutes présentes : le motif limité au `.py` laissait une affirmation
    portée par un `.json` ou un `.md` sortir en « sans symbole à confronter » (mesuré).
    """
    names = cdr.names_in(line)
    assert [p[0] for p in cdr.adjacent_pairs(line) if p[0] not in names] == []


def test_a_json_claim_is_verified(tmp_path: pathlib.Path) -> None:
    """Le sous-ensemble ne suffit pas : les extensions non-`.py` doivent VRAIMENT être appariées."""
    doc = write(tmp_path, "note.md", "le profil `config/agents/ArmageddonAgent/"
                                     "ArmageddonAgent_training_config.json` (`total_episodes`)\n")
    resolved, _unverifiable, broken = cdr.check_references(doc)
    assert (resolved, broken) == (1, [])


def test_a_prose_word_in_backticks_is_not_a_symbol(tmp_path: pathlib.Path) -> None:
    """`directory` est un mot, pas un symbole : le confronter confirme n'importe quoi.

    Mesuré sur `Security.md` : `directory`, `debug`/`False` et `os.system` suffisaient à faire
    passer une citation pour vérifiée. Le vrai symbole pouvait disparaître du code sans un mot.
    """
    doc = write(tmp_path, "note.md", "voir `ai/train.py` (rejet du `directory`, `os.system`)\n")
    resolved, unverifiable, broken = cdr.check_references(doc)
    assert (resolved, unverifiable, broken) == (0, 1, [])


def test_a_symbol_drowned_in_prose_never_cries(tmp_path: pathlib.Path) -> None:
    """« (par exemple quand `x` survient) » n'affirme pas que `x` vit dans le fichier.

    L'affirmation molle se CONFIRME si le symbole est là, mais son absence ne prouve rien : la
    rendre rouge ferait crier le contrôle sur une phrase correcte, et un contrôle qui crie à tort
    finit désactivé — c'est très exactement pourquoi la prose n'était pas appariée à l'origine.
    """
    absent = "`ai/train.py` (par exemple quand `zzz_jamais_defini` survient)\n"
    assert cdr.check_references(write(tmp_path, "note.md", absent)) == (0, 1, [])
    present = "`engine/w40k_core.py` (`_get_unit_by_id` en aval) le lit\n"
    assert cdr.check_references(write(tmp_path, "note2.md", present)) == (1, 0, [])


def test_a_pure_list_claims_every_symbol(tmp_path: pathlib.Path) -> None:
    """`x.py` (`a`, `b`) affirme les DEUX : un `any` laissait `a` couvrir la mort de `b`."""
    doc = write(tmp_path, "note.md", "`engine/w40k_core.py` (`_get_unit_by_id`, `zzz_supprimee`)\n")
    resolved, _unverifiable, broken = cdr.check_references(doc)
    assert resolved == 0 and len(broken) == 1
    assert "zzz_supprimee" in broken[0] and "_get_unit_by_id" not in broken[0]


def test_the_colon_form_reads_the_whole_list(tmp_path: pathlib.Path) -> None:
    """`x.py` : `a`, `b` — le second symbole n'était jamais confronté."""
    doc = write(tmp_path, "note.md", "voir `engine/w40k_core.py` : `_get_unit_by_id`, `zzz_absent`\n")
    _resolved, _unverifiable, broken = cdr.check_references(doc)
    assert len(broken) == 1 and "zzz_absent" in broken[0]


def test_the_colon_form_does_not_swallow_the_next_reference(tmp_path: pathlib.Path) -> None:
    """`a.py` : `b/c.py` (`sym`) n'affirme rien sur `a.py`, et l'affirmation réelle est celle de `c.py`.

    En avalant le renvoi voisin, le motif consommait la seule affirmation vérifiable de la ligne :
    elle sortait « invérifiable » alors que le document dit précisément quoi confronter.
    """
    doc = write(tmp_path, "note.md", "voir `ai/train.py` : `engine/w40k_core.py` (`_get_unit_by_id`)\n")
    resolved, unverifiable, broken = cdr.check_references(doc)
    assert (resolved, unverifiable, broken) == (1, 1, [])


def test_accented_paths_are_counted_under_their_real_name() -> None:
    """Les fichiers de `Documentation/Implémentation/` doivent EXISTER pour le compteur.

    Sans `-z`, git entoure de guillemets et échappe les 73 chemins non-ASCII du dépôt : le
    basename sortait comme `ROADMAP.md"` et tout le dossier accentué devenait invisible à la
    détection d'ambiguïté — un contrôle qui ne regarde rien affiche « tout va bien ».
    """
    counts = cdr.tracked_basenames()
    assert not [name for name in counts if '"' in name or "\\" in name]
    assert counts["ROADMAP.md"] >= 1 and counts["V11_phaseA.md"] >= 1


def test_git_output_is_decoded_regardless_of_the_locale() -> None:
    """La sortie de git est de l'UTF-8, quelle que soit la locale de la machine.

    Les chemins de `Documentation/Implémentation/` sont non-ASCII : décodés avec l'encodage du
    système, ils lèvent `UnicodeDecodeError` sous locale C et emportent tout le contrôle, qui
    appelle `tracked_basenames` sur son chemin principal. Sur la machine d'un CI, pas sur celle
    où le script a été écrit.

    `PYTHONCOERCECLOCALE=0` et `PYTHONUTF8=0` sont indispensables : sans eux, Python bascule de
    lui-même en mode UTF-8 sous locale C (PEP 538/540) et le test resterait vert quoi qu'il
    arrive — le vert vacant appliqué à son propre verrou.

    BORNE : ce test couvre le DÉCODAGE de git. Sous une locale strictement ASCII, l'ouverture des
    documents accentués échoue de toute façon, faute d'encodage de système de fichiers — c'est
    une limite de l'environnement, pas du script, et aucun `encoding=` ne la lève.
    """
    env = {
        **os.environ, "LC_ALL": "C", "LANG": "C", "PYTHONIOENCODING": "utf-8",
        "PYTHONCOERCECLOCALE": "0", "PYTHONUTF8": "0",
    }
    program = (
        "import importlib.util;"
        f"s=importlib.util.spec_from_file_location('cdr', r'{ROOT}/scripts/check_doc_references.py');"
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
        "print(m.tracked_basenames()['ROADMAP.md'])"
    )
    done = subprocess.run(
        [sys.executable, "-c", program],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
    )
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip() == "1"


def test_an_ambiguous_bare_name_is_not_confronted(tmp_path: pathlib.Path) -> None:
    """`conftest.py` existe cinq fois : le document ne dit pas duquel il parle.

    `resolve` en rend un — le premier de son ordre de recherche — et confronter les symboles à
    CELUI-LÀ produisait un faux « AUCUN SYMBOLE » sur un document juste (mesuré sur
    `A_faire/front_test_auto.md`, où `GameClient` vit dans l'autre `conftest.py`).
    """
    doc = write(tmp_path, "note.md", "`conftest.py` : `GameClient` porte les fixtures\n")
    resolved, unverifiable, broken = cdr.check_references(doc)
    assert (resolved, unverifiable, broken) == (0, 1, [])


def test_a_dotted_call_is_not_a_file(tmp_path: pathlib.Path) -> None:
    """`hashlib.md5` n'est pas un fichier `hashlib.md` — mesuré comme fausse alerte réelle."""
    doc = write(tmp_path, "note.md", "| x | on dépose un `hashlib.md5` dans `config/` | y |\n")
    _resolved, _unverifiable, broken = cdr.check_references(doc)
    assert not broken


def test_reference_documents_are_clean() -> None:
    """Les documents d'entrée EXISTENT et passent le contrôle — la ligne de base à tenir.

    L'existence est affirmée en premier : le déménagement de la roadmap (2026-08-17) a laissé
    `DEFAULT_DOCS` pointer un fichier supprimé, et le contrôle est resté rouge en permanence
    jusqu'au prompt suivant. Un chemin mort dans la liste d'entrée doit rougir ICI, nommément.
    """
    for rel in cdr.DEFAULT_DOCS:
        path = ROOT / rel
        assert path.exists(), f"DEFAULT_DOCS pointe un fichier absent : {rel}"
        _resolved, _unverifiable, broken_refs = cdr.check_references(path)
        _checked, _skipped, broken_links = cdr.check_links(path)
        _verified, broken_values = cdr.check_values(path)
        _kinds, _kinds_unverifiable, broken_kinds, _notes = cdr.check_symbol_kinds(path)
        broken = (
            broken_refs + broken_links + broken_values + cdr.check_anchors(path) + broken_kinds
        )
        assert not broken, f"{rel} : " + " | ".join(broken)


def test_the_corpus_really_confronts_some_kinds() -> None:
    """VERT VACANT : « 0 sorte fausse » ne vaut rien si aucune sorte n'a été confrontée.

    Le corpus en porte au moins trois (les `def` de la convention d'ancres dans `doc.md`, une
    dans `Security.md`). Le jour où la dernière disparaît, ce test doit le dire plutôt que
    laisser la passe s'éteindre en silence.
    """
    total = 0
    for rel in cdr.DEFAULT_DOCS:
        checked, _unverifiable, _broken, _notes = cdr.check_symbol_kinds(ROOT / rel)
        total += checked
    assert total >= 3
