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
    """`../../engine/…` depuis un doc de `Chantiers/v11/` désigne bien le fichier du dépôt."""
    doc_dir = ROOT / "Documentation" / "Chantiers" / "v11"
    assert cdr.resolve("../../../engine/w40k_core.py", doc_dir) == ROOT / "engine" / "w40k_core.py"


def test_parent_relative_path_is_captured_whole() -> None:
    """La regex capture le préfixe `../`, sinon la résolution reçoit un fragment absolu."""
    assert cdr.names_in("voir [x](../../../engine/w40k_core.py)") == ["../../../engine/w40k_core.py"]


def test_doc_relative_and_root_relative_both_resolve() -> None:
    """Les deux conventions du corpus coexistent et doivent être servies toutes les deux."""
    docs = ROOT / "Documentation" / "Chantiers"
    assert cdr.resolve("v11/V11_phaseA.md", docs) is not None
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
    write(tmp_path, "bot.md", "# cible {#etape8}\n")
    doc = write(tmp_path, "note.md", "voir [bot.md#etape8](bot.md#etape8) et [bot.md](bot.md)\n")
    assert cdr.resolve("bot.md", tmp_path) == tmp_path / "bot.md"
    _checked, _skipped, _fragments, broken = cdr.check_links(doc)
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
    _checked, _skipped, _fragments, broken = cdr.check_links(doc)
    assert len(broken) == 1 and "LIEN MORT" in broken[0]


@pytest.mark.parametrize("target", ["fichier", '[^"\\\']+'])
def test_regex_noise_is_not_taken_for_a_link(tmp_path: pathlib.Path, target: str) -> None:
    """Écartés sur la FORME. Une liste d'exceptions nommées masquerait un vrai lien mort."""
    doc = write(tmp_path, "note.md", f"texte [x]({target}#L1)\n")
    checked, skipped, _fragments, broken = cdr.check_links(doc)
    assert (checked, skipped, broken) == (0, 1, [])


def test_live_link_is_verified(tmp_path: pathlib.Path) -> None:
    doc = write(tmp_path, "note.md", "voir [le moteur](engine/w40k_core.py)\n")
    checked, _skipped, _fragments, broken = cdr.check_links(doc)
    assert checked == 1 and not broken


# --------------------------------------------------------------------------- fragments d'ancre


def test_dead_fragment_is_reported(tmp_path: pathlib.Path) -> None:
    """Un fragment `#ancre` absent de la cible génère ANCRE MORTE."""
    write(tmp_path, "cible.md", "# Titre existant\n\ndu contenu\n")
    doc = write(tmp_path, "note.md", "[texte](cible.md#ancre-inexistante)\n")
    _checked, _skipped, _fragments, broken = cdr.check_links(doc)
    assert len(broken) == 1 and "ANCRE MORTE" in broken[0] and "ancre-inexistante" in broken[0]


def test_live_fragment_slug_is_not_reported(tmp_path: pathlib.Path) -> None:
    """Un fragment qui correspond au slug GFM d'un titre ne génère pas d'erreur."""
    write(tmp_path, "cible.md", "# Titre existant\n\ndu contenu\n")
    doc = write(tmp_path, "note.md", "[texte](cible.md#titre-existant)\n")
    checked, _skipped, _fragments, broken = cdr.check_links(doc)
    assert checked == 1 and not broken


def test_explicit_anchor_id_is_recognized(tmp_path: pathlib.Path) -> None:
    """`{#mon-id}` sur un titre est une ancre valide, indépendamment du slug du titre."""
    write(tmp_path, "cible.md", "# Titre quelconque {#mon-id}\n\ndu contenu\n")
    doc = write(tmp_path, "note.md", "[texte](cible.md#mon-id)\n")
    _checked, _skipped, _fragments, broken = cdr.check_links(doc)
    assert not broken


def test_explicit_anchor_id_wrong_slug_is_dead(tmp_path: pathlib.Path) -> None:
    """Quand `{#mon-id}` est présent, le slug du titre de surface n'est PAS une ancre valide.

    Mutation : changer l'id explicite sans mettre à jour le lien → ANCRE MORTE.
    """
    write(tmp_path, "cible.md", "# Titre quelconque {#autre-id}\n\ndu contenu\n")
    doc = write(tmp_path, "note.md", "[texte](cible.md#titre-quelconque)\n")
    _checked, _skipped, _fragments, broken = cdr.check_links(doc)
    assert len(broken) == 1 and "ANCRE MORTE" in broken[0]


def test_explicit_anchor_id_accepted_when_slug_is_dead(tmp_path: pathlib.Path) -> None:
    """`{#autre-id}` est une ancre valide ; le slug du titre ne l'est pas.

    Vérifie les DEUX invariants sur le même heading : le lien vers l'id explicite est vert,
    le lien vers le slug de surface est rouge — une régression qui supprimerait l'id explicite
    ferait passer les deux au rouge, ce que test_explicit_anchor_id_wrong_slug_is_dead
    ne détecterait pas seul.
    """
    write(tmp_path, "cible.md", "# Titre quelconque {#autre-id}\n\ndu contenu\n")
    doc_ok = write(tmp_path, "note_ok.md", "[texte](cible.md#autre-id)\n")
    doc_ko = write(tmp_path, "note_ko.md", "[texte](cible.md#titre-quelconque)\n")
    cdr.md_anchors.cache_clear()
    _, _, _, broken_ok = cdr.check_links(doc_ok)
    _, _, _, broken_ko = cdr.check_links(doc_ko)
    assert not broken_ok, f"id explicite rejeté : {broken_ok}"
    assert len(broken_ko) == 1 and "ANCRE MORTE" in broken_ko[0]


def test_url_encoded_fragment_is_decoded(tmp_path: pathlib.Path) -> None:
    """Un fragment URL-encodé (`%C3%A9tape`) est confronté à l'ancre décodée (`étape`)."""
    write(tmp_path, "cible.md", "# Étape 1\n")
    doc = write(tmp_path, "note.md", "[texte](cible.md#%C3%A9tape-1)\n")
    cdr.md_anchors.cache_clear()
    _checked, _skipped, _fragments, broken = cdr.check_links(doc)
    assert not broken, f"fragment URL-encodé rejeté à tort : {broken}"


def test_explicit_anchor_inside_backtick_span_is_not_treated_as_explicit(
    tmp_path: pathlib.Path,
) -> None:
    """`{#id}` dans un span inline d'un titre n'est PAS un id explicite ; le slug fait foi.

    Heading : ## Use `{#wrong-id}` here
    - le slug est `use-here` (le span est vidé, {#wrong-id} supprimé par _heading_slug)
    - `#wrong-id` est mort : le span était dans l'inline code, pas un id déclaré
    """
    write(tmp_path, "cible.md", "## Use `{#wrong-id}` here\n")
    # slug réel = "use-here" (_heading_slug supprime {#wrong-id} puis strip les backticks)
    doc_slug = write(tmp_path, "note_slug.md", "[texte](cible.md#use-here)\n")
    doc_bad = write(tmp_path, "note_bad.md", "[texte](cible.md#wrong-id)\n")
    cdr.md_anchors.cache_clear()
    _, _, _, broken_slug = cdr.check_links(doc_slug)
    _, _, _, broken_bad = cdr.check_links(doc_bad)
    assert not broken_slug, f"slug légitime rejeté : {broken_slug}"
    assert len(broken_bad) == 1 and "ANCRE MORTE" in broken_bad[0]


def test_explicit_anchor_inside_fenced_code_block_is_ignored(tmp_path: pathlib.Path) -> None:
    """`{#id}` dans un bloc code fencé n'est PAS une ancre valide du document."""
    content = "# Titre réel\n\n```json\n{\"#config-key\": 1}\n```\n"
    write(tmp_path, "cible.md", content)
    doc_real = write(tmp_path, "note_real.md", "[texte](cible.md#titre-réel)\n")
    doc_fake = write(tmp_path, "note_fake.md", "[texte](cible.md#config-key)\n")
    cdr.md_anchors.cache_clear()
    _, _, _, broken_real = cdr.check_links(doc_real)
    _, _, _, broken_fake = cdr.check_links(doc_fake)
    assert not broken_real, f"ancre réelle rejetée : {broken_real}"
    assert len(broken_fake) == 1 and "ANCRE MORTE" in broken_fake[0]


def test_fragment_on_non_md_file_is_not_checked(tmp_path: pathlib.Path) -> None:
    """Un fragment sur un `.py` suit la convention `#L<n>` de GitHub — pas de validation."""
    doc = write(tmp_path, "note.md", "voir [texte](engine/w40k_core.py#L629)\n")
    _checked, _skipped, _fragments, broken = cdr.check_links(doc)
    assert not broken


def test_link_without_fragment_is_unaffected(tmp_path: pathlib.Path) -> None:
    """Un lien sans fragment n'est pas touché par la validation d'ancre."""
    write(tmp_path, "cible.md", "# Titre\n")
    doc = write(tmp_path, "note.md", "[texte](cible.md)\n")
    checked, _skipped, _fragments, broken = cdr.check_links(doc)
    assert checked == 1 and not broken


def test_heading_with_backtick_slugs_correctly(tmp_path: pathlib.Path) -> None:
    """Les backticks sont retirés du titre avant slugification."""
    write(tmp_path, "cible.md", "## `obs_size` justification\n")
    doc = write(tmp_path, "note.md", "[texte](cible.md#obs_size-justification)\n")
    _checked, _skipped, _fragments, broken = cdr.check_links(doc)
    assert not broken


def test_dead_anchor_is_dead_after_mutation(tmp_path: pathlib.Path) -> None:
    """Rouge/vert par mutation : renommer le titre casse le fragment.

    État VERT : lien vers `#ancien-titre`.
    Mutation (renommer le titre) → état ROUGE.
    """
    cible = write(tmp_path, "cible.md", "## Ancien titre\n")
    doc = write(tmp_path, "note.md", "[texte](cible.md#ancien-titre)\n")
    # VERT : ancre valide
    _checked, _skipped, _fragments, broken = cdr.check_links(doc)
    assert not broken, f"attendu vert, obtenu : {broken}"
    # Mutation : on renomme le titre
    cdr.md_anchors.cache_clear()
    cible.write_text("## Nouveau titre\n", encoding="utf-8")
    cdr.md_anchors.cache_clear()
    _checked, _skipped, _fragments, broken = cdr.check_links(doc)
    assert len(broken) == 1 and "ANCRE MORTE" in broken[0], f"attendu rouge, obtenu : {broken}"


def test_a_line_fragment_is_left_to_the_anchor_pass(tmp_path: pathlib.Path) -> None:
    """`#L629` cite une LIGNE, y compris vers un `.md` : la passe 4 la rapporte déjà.

    Confrontée aux titres, elle sortirait ANCRE MORTE et enverrait chercher un titre là où le
    document cite une ligne — deux messages pour un seul défaut, dont un qui égare.
    """
    write(tmp_path, "cible.md", "# Doc\n")
    doc = write(tmp_path, "ROADMAP_INDEX.md", "voir [là](cible.md#L99999)\n")
    _checked, _skipped, fragments, broken = cdr.check_links(doc)
    assert (fragments, broken) == (0, [])
    assert len(cdr.check_anchors(doc)) == 1


def test_a_line_range_fragment_is_not_counted_as_dead_anchor(tmp_path: pathlib.Path) -> None:
    """`#L10-L20` (plage GitHub) ne nomme pas un titre : ne pas le compter comme ancre morte."""
    write(tmp_path, "cible.md", "# Doc\n")
    doc = write(tmp_path, "note.md", "voir [là](cible.md#L10-L20)\n")
    _checked, _skipped, fragments, broken = cdr.check_links(doc)
    assert (fragments, broken) == (0, [])


def test_a_percent_encoded_fragment_matches_anchor(tmp_path: pathlib.Path) -> None:
    """`#%C3%A9l%C3%A9ment` doit être décodé avant comparaison avec `md_anchors`."""
    write(tmp_path, "cible.md", "# Élément\n")
    doc = write(tmp_path, "note.md", "[voir](cible.md#%C3%A9l%C3%A9ment)\n")
    _checked, _skipped, fragments, broken = cdr.check_links(doc)
    assert (fragments, broken) == (1, [])


def test_a_fragment_on_a_non_markdown_target_is_not_confronted(tmp_path: pathlib.Path) -> None:
    """Hors `.md`, aucun fragment ne nomme un titre — pas seulement la graphie `#L<n>`."""
    doc = write(tmp_path, "note.md", "voir [le moteur](engine/w40k_core.py#execute_action)\n")
    checked, _skipped, fragments, broken = cdr.check_links(doc)
    assert (checked, fragments, broken) == (1, 0, [])


def test_a_dead_link_is_not_counted_twice(tmp_path: pathlib.Path) -> None:
    """Le fichier disparu se rapporte UNE fois : son ancre n'a plus de document où être cherchée."""
    doc = write(tmp_path, "note.md", "voir [là](A_faire/disparu.md#une-ancre)\n")
    _checked, _skipped, fragments, broken = cdr.check_links(doc)
    assert fragments == 0
    assert len(broken) == 1 and cdr.DEAD_LINK in broken[0]


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


# --------------------------------------------------------------------------- passe 4 étendue au corpus chantiers (ANCHOR_TREES)


def _impl_enforced_name() -> str:
    """Retourne un basename réel des arbres ANCHOR_TREES présent dans ANCHOR_ENFORCED.

    Utiliser un nom découvert dynamiquement évite de coder en dur un fichier qui pourrait être
    renommé — ce qui rendrait le test vert mais vacueux (la mutation ne serait jamais atteinte).
    """
    enforced_impl = cdr._get_anchor_enforced() - cdr.DEFAULT_DOC_NAMES
    assert enforced_impl, (
        "Aucun doc des arbres ANCHOR_TREES dans _get_anchor_enforced() — _impl_doc_basenames() est silencieux"
    )
    return sorted(enforced_impl)[0]


def test_impl_doc_line_anchor_is_detected(tmp_path: pathlib.Path) -> None:
    """ROUGE : une ancre de ligne dans le corpus chantiers (ANCHOR_TREES) est détectée.

    Avant cette livraison, check_anchors() ne regardait que DEFAULT_DOCS ; un renvoi de ligne
    dans un doc chantier passait en vert sans aucune alerte. ANCHOR_ENFORCED inclut
    désormais tous les .md des arbres ANCHOR_TREES via _impl_doc_basenames().
    """
    chosen = _impl_enforced_name()
    # ROUGE : numéro de ligne présent → violation
    doc = write(tmp_path, chosen, "voir `engine/w40k_core.py:705`\n")
    entries = cdr.check_anchors(doc)
    assert len(entries) == 1, f"attendu 1 violation, obtenu {entries}"

    # VERT après correction : symbole à la place de la ligne
    doc.write_text("voir `def _get_unit_by_id` dans `engine/w40k_core.py`\n", encoding="utf-8")
    assert cdr.check_anchors(doc) == []


def test_impl_doc_line_anchor_inside_fenced_block_is_ignored(tmp_path: pathlib.Path) -> None:
    """Un renvoi de ligne dans un bloc fencé n'est PAS une ancre de document.

    `# shooting_handlers.py:1538` dans un extrait de code Python est une attribution de
    source, pas un renvoi de doc. Le masquage des blocs fencés dans check_anchors() ferme
    ce faux positif.
    """
    chosen = _impl_enforced_name()
    content = (
        "Du texte avant.\n"
        "```python\n"
        "gs = copy.deepcopy(gs)   # shooting_handlers.py:1538\n"
        "```\n"
        "Du texte après.\n"
    )
    doc = write(tmp_path, chosen, content)
    assert cdr.check_anchors(doc) == []


def test_impl_real_corpus_has_no_line_anchor() -> None:
    """VERT VACANT fermé : le corpus chantiers (ANCHOR_TREES) passe entièrement la passe 4.

    Verrou sur le dépôt réel : report_impl_anchors() doit rendre 0 violation. Si ce test
    rougit, un doc de Chantiers/ ou d'Archives/chantiers/ a reçu un numéro de ligne lors
    d'une livraison sans que ce tour ne le corrige.
    """
    has_broken, lines = cdr.report_impl_anchors()
    assert not has_broken, "\n".join(lines)


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
    """Les fichiers des chemins non-ASCII du dépôt doivent EXISTER pour le compteur.

    Sans `-z`, git entoure de guillemets et échappe les chemins non-ASCII (`Memoire_RNCP/`,
    et à l'époque de la mesure tout `Documentation/Implémentation/`) : le basename sortait
    comme `ROADMAP.md"` et tout le dossier accentué devenait invisible à la détection
    d'ambiguïté — un contrôle qui ne regarde rien affiche « tout va bien ».
    """
    counts = cdr.tracked_basenames()
    assert not [name for name in counts if '"' in name or "\\" in name]
    assert counts["ROADMAP.md"] >= 1 and counts["V11_phaseA.md"] >= 1


def test_git_output_is_decoded_regardless_of_the_locale() -> None:
    """La sortie de git est de l'UTF-8, quelle que soit la locale de la machine.

    Le dépôt porte des chemins non-ASCII (`Memoire_RNCP/`) : décodés avec l'encodage du
    système, ils lèvent `UnicodeDecodeError` sous locale C et emportent tout le contrôle, qui
    appelle `tracked_basenames` sur son chemin principal. Sur la machine d'un CI, pas sur celle
    où le script a été écrit.

    `PYTHONCOERCECLOCALE=0` et `PYTHONUTF8=0` sont indispensables : sans eux, Python bascule de
    lui-même en mode UTF-8 sous locale C (PEP 538/540) et le test resterait vert quoi qu'il
    arrive — le vert vacant appliqué à son propre verrou.

    BORNE : ce test couvre le DÉCODAGE de git seul, en important le module (sans lancer le script).
    Le module peut s'importer sous fsencoding ascii — le check d'environnement (`_check_filesystem_
    encoding`) n'est appelé que depuis le bloc `__main__`, et non à l'import. Sous une locale
    strictement ASCII, l'ouverture des documents accentués échouerait à mi-parcours : le script
    CHOISIT de refuser au démarrage (voir `test_ascii_fsencoding_produces_explicit_error`) plutôt
    que de convertir tout son parcours de fichiers en chemins bytes. Ce choix est assumé : le coût
    de lisibilité du parcours bytes est réel pour un scénario qui exige `PYTHONUTF8=0` explicitement,
    que Python 3.12 n'active pas de lui-même sous locale C (PEP 538/540 active le mode UTF-8 seul).
    Aucun `encoding=` ne contourne `os.fsencode` — la seconde moitié de l'ancienne BORNE est juste.
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


def test_ascii_fsencoding_produces_explicit_error() -> None:
    """Sous fsencoding ascii, le script refuse au démarrage avec un message nommant PYTHONUTF8.

    `LC_ALL=C PYTHONUTF8=0 PYTHONCOERCECLOCALE=0` désactive le basculement automatique en mode
    UTF-8 de Python 3.12 (PEP 538/540) : sans ces variables, le test resterait vert quoi qu'il
    arrive — le vert vacant appliqué à son propre verrou.

    Ce que le test vérifie : le script sort avec un code non-nul ET la sortie d'erreur nomme
    PYTHONUTF8 explicitement — pas une `UnicodeEncodeError` brute dont la trace ne désigne
    ni la locale ni le remède.
    """
    env = {
        **os.environ, "LC_ALL": "C", "LANG": "C", "PYTHONIOENCODING": "utf-8",
        "PYTHONCOERCECLOCALE": "0", "PYTHONUTF8": "0",
    }
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_doc_references.py")],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
    )
    combined = done.stdout + done.stderr
    assert done.returncode != 0, "le script doit échouer sous fsencoding ascii"
    assert "PYTHONUTF8" in combined, f"message PYTHONUTF8 absent\nstderr={done.stderr[-2000:]}"
    assert "UnicodeEncodeError" not in combined, (
        f"UnicodeEncodeError brute exposée au lieu d'un refus explicite\n{done.stderr[-2000:]}"
    )


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
        _checked, _skipped, _fragments, broken_links = cdr.check_links(path)
        _verified, broken_values = cdr.check_values(path)
        _kinds, _kinds_unverifiable, broken_kinds, _notes = cdr.check_symbol_kinds(path)
        broken = (
            broken_refs + broken_links + broken_values + cdr.check_anchors(path) + broken_kinds
        )
        assert not broken, f"{rel} : " + " | ".join(broken)


def test_obs_size_is_read_through_its_thousands_separator() -> None:
    """`**16 703**` est une valeur annoncée autant que `**16703**`.

    Motif : borné à `\\d{4,}`, l'extracteur ne voyait pas la graphie à séparateur — et c'est
    exactement celle qu'employait `AI_TRAINING.md`. Sa valeur y est restée à 16 659 face à une
    source calculée à 16703, sous un contrôle qui se déclarait vert parce qu'il regardait
    ailleurs. Les trois séparateurs du corpus sont couverts.
    """
    for separator in (" ", " ", "\xa0"):
        text = f"| `obs_size` | **16{separator}703** (…) | source |"
        assert cdr.claim_obs_size(text) == [
            (f"`obs_size` | **16{separator}703**", 16703)
        ], f"séparateur {separator!r} non lu"


def test_a_short_bold_number_is_not_an_obs_size() -> None:
    """`**8** → **12**` sur la ligne d'`obs_size` désigne des slots, jamais une taille."""
    assert cdr.claim_obs_size("| `obs_size` | **8** slots | source |") == []


def test_value_only_documents_are_clean_and_stay_out_of_the_entry_corpus() -> None:
    """Les documents à valeurs seules EXISTENT, passent la passe 3, et n'entrent pas ailleurs.

    Ils portent des valeurs recopiées d'une source mécanique, donc la passe 3 les regarde ; ils
    citent en revanche des dizaines de `fichier.py:ligne`, donc les inscrire dans `DEFAULT_DOCS`
    les rendrait rouges en permanence par la convention d'ancres — et un contrôle durablement
    rouge finit ignoré. Cette exclusion est le contrat, pas un oubli.
    """
    assert cdr.VALUE_ONLY_DOCS, "l'énumération est vide : la passe ne regarde plus rien"
    for rel in cdr.VALUE_ONLY_DOCS:
        assert rel not in cdr.DEFAULT_DOCS, f"{rel} est aussi un document d'entrée"
        path = ROOT / rel
        assert path.exists(), f"VALUE_ONLY_DOCS pointe un fichier absent : {rel}"
        verified, broken = cdr.check_values(path)
        assert not broken, f"{rel} : " + " | ".join(broken)
        # VERT VACANT : « 0 valeur périmée » ne vaut rien si aucune valeur n'a été confrontée.
        assert verified, f"{rel} : aucune valeur confrontée"


def test_the_corpus_really_confronts_its_fragments() -> None:
    """VERT VACANT : « 0 ancre introuvable » ne vaut rien si aucun fragment n'a été confronté.

    Le corpus en portait 45 au 2026-08-18, tous vers un titre d'un fichier sujet. Le seuil est bas
    à dessein — il dit que la passe REGARDE encore quelque chose, pas combien de liens la roadmap
    doit porter, qui n'appartient qu'à la roadmap.
    """
    total = sum(cdr.check_links(ROOT / rel)[2] for rel in cdr.DEFAULT_DOCS)
    assert total >= 10


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


# --------------------------------------------------------------------------- atteignabilité


def corpus(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """Un corpus JOUET : un index, un fichier sujet, des chantiers, une archive.

    Le contrôle d'atteignabilité se prononce sur des CONSTANTES de module (la racine, l'arbre des
    chantiers, les arbres vivants). Les déplacer sur `tmp_path` est le seul moyen de prouver le
    rouge : sur le corpus réel, écrire un orphelin pour le mesurer, c'est modifier la roadmap.
    """
    roadmap = tmp_path / "Roadmap"
    (roadmap / "archives").mkdir(parents=True)
    a_faire = tmp_path / "A_faire"
    (a_faire / "Database").mkdir(parents=True)
    monkeypatch.setattr(cdr, "DOCS", tmp_path)
    monkeypatch.setattr(cdr, "ROADMAP_INDEX", roadmap / "ROADMAP_INDEX.md")
    monkeypatch.setattr(cdr, "A_FAIRE", a_faire)
    monkeypatch.setattr(cdr, "LIVE_TREES", (roadmap, a_faire))
    monkeypatch.setattr(cdr, "ARCHIVES", roadmap / "archives")
    return tmp_path


def orphans() -> list[str]:
    """Les seuls noms des chantiers orphelins, sans le message."""
    return [entry.split("  ")[0] for entry in cdr.check_reachability()[0]]


def test_an_uncited_chantier_is_an_orphan(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ROUGE/VERT : le document que plus aucun fichier sujet ne cite doit sortir NOMMÉMENT.

    C'est le défaut que la passe existe pour fermer, et qu'aucune des cinq autres ne peut voir :
    le chantier orphelin ne porte aucune phrase fausse — il ne porte plus rien du tout.
    """
    root = corpus(tmp_path, monkeypatch)
    (root / "Roadmap" / "ROADMAP_INDEX.md").write_text("voir [moteur.md](moteur.md)\n", "utf-8")
    (root / "Roadmap" / "moteur.md").write_text("→ `../A_faire/cite.md`\n", "utf-8")
    (root / "A_faire" / "cite.md").write_text("# cité\n", "utf-8")
    (root / "A_faire" / "oublie.md").write_text("# oublié\n", "utf-8")
    assert orphans() == ["A_faire/oublie.md"]

    # VERT après correction : le fichier sujet le cite à son tour, plus aucun orphelin.
    (root / "Roadmap" / "moteur.md").write_text(
        "→ `../A_faire/cite.md` `../A_faire/oublie.md`\n", "utf-8"
    )
    assert orphans() == []


def test_a_markdown_link_reaches_as_well(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Les deux graphies du corpus valent renvoi : le chemin backtiqué ET le lien markdown."""
    root = corpus(tmp_path, monkeypatch)
    (root / "Roadmap" / "ROADMAP_INDEX.md").write_text("[s](sujet.md)\n", "utf-8")
    (root / "Roadmap" / "sujet.md").write_text("[c](../A_faire/cite.md)\n", "utf-8")
    (root / "A_faire" / "cite.md").write_text("# cité\n", "utf-8")
    assert orphans() == []


def test_a_chantier_in_a_subdirectory_is_enumerated(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`A_faire/Database/`, `A_faire/MCTS/` : un chantier n'est pas moins ouvert parce
    qu'il est rangé."""
    root = corpus(tmp_path, monkeypatch)
    (root / "Roadmap" / "ROADMAP_INDEX.md").write_text("rien\n", "utf-8")
    (root / "A_faire" / "Database" / "db.md").write_text("# db\n", "utf-8")
    assert orphans() == ["A_faire/Database/db.md"]


def test_reachability_is_transitive(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un chantier qui en découpe un second le rend atteignable : la marche ne se borne pas."""
    root = corpus(tmp_path, monkeypatch)
    (root / "Roadmap" / "ROADMAP_INDEX.md").write_text("[s](sujet.md)\n", "utf-8")
    (root / "Roadmap" / "sujet.md").write_text("→ `../A_faire/decoupage.md`\n", "utf-8")
    (root / "A_faire" / "decoupage.md").write_text("→ `Database/lot.md`\n", "utf-8")
    (root / "A_faire" / "Database" / "lot.md").write_text("# lot\n", "utf-8")
    assert orphans() == []


def test_a_chantier_cited_only_by_an_archive_stays_orphan(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Être cité par l'historique d'un chantier clos prouve le CONTRAIRE d'être sur la feuille.

    `ROADMAP_INDEX.md` cite `archives/ROADMAP.md` pour de vrai : sans cette borne, l'archive rendait
    atteignable tout ce que la roadmap a jamais porté, et la passe ne mesurait plus rien.
    """
    root = corpus(tmp_path, monkeypatch)
    (root / "Roadmap" / "ROADMAP_INDEX.md").write_text("[h](archives/ROADMAP.md)\n", "utf-8")
    archive = root / "Roadmap" / "archives" / "ROADMAP.md"
    archive.write_text("→ `../../A_faire/vieux.md`\n", "utf-8")
    (root / "A_faire" / "vieux.md").write_text("# vieux\n", "utf-8")
    assert orphans() == ["A_faire/vieux.md"]


def test_an_empty_chantier_tree_is_not_a_green(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VERT VACANT : « 0 orphelin » sur une énumération vide est un silence, pas un verdict."""
    root = corpus(tmp_path, monkeypatch)
    (root / "Roadmap" / "ROADMAP_INDEX.md").write_text("rien\n", "utf-8")
    with pytest.raises(cdr.SourceUnavailable):
        cdr.check_reachability()


def test_a_missing_index_is_not_a_green(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La racine disparue est BLOQUANTE : sans elle, tout chantier serait déclaré orphelin."""
    root = corpus(tmp_path, monkeypatch)
    (root / "A_faire" / "cite.md").write_text("# cité\n", "utf-8")
    with pytest.raises(cdr.SourceUnavailable):
        cdr.check_reachability()


def test_the_real_corpus_has_no_orphan() -> None:
    """Le verrou sur le dépôt : tout chantier ouvert se rejoint depuis la feuille de route.

    Mesuré au premier passage (2026-08-18) : 2 orphelins sur 13 — `analyzer_conformite_lots.md`
    (ouvert le 2026-08-16, cité par aucun fichier sujet) et `Database/DB_migration_prompt.md`.
    """
    assert cdr.check_reachability()[0] == []


# --------------------------------------------------------------------------- corpus vivant (LIENS)


def test_corpus_links_real_corpus_has_no_dead_links() -> None:
    """Bout en bout : le corpus livré ne contient aucun lien mort."""
    cdr.md_anchors.cache_clear()
    broken, lines = cdr.report_corpus_links()
    assert not broken, "\n".join(lines)


# --------------------------------------------------------------------------- TOTAL_ACTION_SIZE


def test_total_action_size_stale(tmp_path: pathlib.Path) -> None:
    """TOTAL_ACTION_SIZE faux dans AI_TRAINING.md → VALEUR PÉRIMÉE."""
    doc = write(tmp_path, "AI_TRAINING.md", "espace d'action | **1 000** (desc)\n")
    _verified, broken = cdr.check_values(doc)
    assert any("VALEUR PÉRIMÉE" in e for e in broken), f"attendu rouge, obtenu : {broken}"


def test_total_action_size_confirmed(tmp_path: pathlib.Path) -> None:
    """TOTAL_ACTION_SIZE exact dans AI_TRAINING.md → confirmé."""
    real = cdr.expected_total_action_size(None)
    formatted = f"{real:,}".replace(",", " ")
    doc = write(tmp_path, "AI_TRAINING.md", f"espace d'action | **{formatted}** (desc)\n")
    verified, broken = cdr.check_values(doc)
    assert verified >= 1
    assert not any("TOTAL_ACTION_SIZE" in e and "PÉRIMÉE" in e for e in broken)


def test_total_action_size_orphan(tmp_path: pathlib.Path) -> None:
    """Aucune phrase TOTAL_ACTION_SIZE dans AI_TRAINING.md → ASSERTION ORPHELINE."""
    doc = write(tmp_path, "AI_TRAINING.md", "rien à vérifier ici\n")
    _verified, broken = cdr.check_values(doc)
    assert any("ASSERTION ORPHELINE" in e and "TOTAL_ACTION_SIZE" in e for e in broken)


# --------------------------------------------------------------------------- dimensions allies


def test_allies_dims_stale(tmp_path: pathlib.Path) -> None:
    """Dimensions allies fausses dans AI_OBSERVATION.md → VALEUR PÉRIMÉE."""
    doc = write(
        tmp_path, "AI_OBSERVATION.md",
        "| `allies_cont` / `allies_bin` | (8, 19) / (8, 20) |\n",
    )
    _verified, broken = cdr.check_values(doc)
    assert any("VALEUR PÉRIMÉE" in e for e in broken), f"attendu rouge, obtenu : {broken}"


def test_allies_dims_confirmed(tmp_path: pathlib.Path) -> None:
    """Dimensions allies exactes dans AI_OBSERVATION.md → confirmé."""
    k, wc, _, wb = cdr.expected_allies_dims(None)
    doc = write(
        tmp_path, "AI_OBSERVATION.md",
        f"| `allies_cont` / `allies_bin` | ({k}, {wc}) / ({k}, {wb}) |\n",
    )
    verified, broken = cdr.check_values(doc)
    assert verified >= 1
    assert not any("PÉRIMÉE" in e for e in broken), f"attendu vert, obtenu : {broken}"


def test_allies_dims_orphan(tmp_path: pathlib.Path) -> None:
    """Aucune ligne allies_cont dans AI_OBSERVATION.md → ASSERTION ORPHELINE."""
    doc = write(tmp_path, "AI_OBSERVATION.md", "rien ici\n")
    _verified, broken = cdr.check_values(doc)
    assert any("ASSERTION ORPHELINE" in e for e in broken)


# --------------------------------------------------------------------------- accumulation ROADMAP


def test_accumulation_at_threshold_is_green(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Exactement MAX_ROADMAP_CHECKMARKS lignes ✅ → vert (seuil inclusif)."""
    lines = "\n".join(f"- item {i} ✅" for i in range(cdr.MAX_ROADMAP_CHECKMARKS))
    fake = tmp_path / "ROADMAP_INDEX.md"
    fake.write_text(lines, encoding="utf-8")
    monkeypatch.setattr(cdr, "ROADMAP_INDEX", fake)
    broken, _report = cdr.report_accumulation()
    assert not broken


def test_accumulation_above_threshold_is_red(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """> MAX_ROADMAP_CHECKMARKS lignes ✅ → rouge avec comptage exact."""
    n = cdr.MAX_ROADMAP_CHECKMARKS + 1
    lines = "\n".join(f"- item {i} ✅" for i in range(n))
    fake = tmp_path / "ROADMAP_INDEX.md"
    fake.write_text(lines, encoding="utf-8")
    monkeypatch.setattr(cdr, "ROADMAP_INDEX", fake)
    broken, report = cdr.report_accumulation()
    assert broken
    assert any(str(n) in line for line in report)


# --------------------------------------------------------------------------- blocs fencés — passe 1


def test_references_inside_fenced_code_block_are_ignored(tmp_path: pathlib.Path) -> None:
    """Un renvoi dans un bloc fencé ne déclenche pas de FICHIER INTROUVABLE.

    Un commentaire de code du type `# engine/w40k_core.py (_get_unit_by_id)` dans un bloc
    ````python` est une attribution, pas une affirmation documentaire : check_references ne doit
    pas la traiter comme un renvoi.
    """
    doc = write(
        tmp_path,
        "note.md",
        "Texte.\n"
        "```python\n"
        "`engine/fichier_inexistant_xyz.py` (`_get_unit_by_id`)\n"
        "```\n"
        "Suite.\n",
    )
    _resolved, _unverifiable, broken = cdr.check_references(doc)
    assert not broken, broken


# --------------------------------------------------------------------------- blocs fencés — passe 5


def test_symbol_kinds_inside_fenced_code_block_are_ignored(tmp_path: pathlib.Path) -> None:
    """Un renvoi de sorte dans un bloc fencé ne déclenche pas de SORTE FAUSSE.

    Un exemple de code contenant `def agit` adjacent à `fichier_xyz.py` est une illustration,
    pas une affirmation : check_symbol_kinds ne doit pas la vérifier.
    """
    module = tmp_path / "module.py"
    module.write_text("class agit:\n    pass\n", encoding="utf-8")
    doc = write(
        tmp_path,
        "ROADMAP_INDEX.md",
        "Texte.\n"
        "```python\n"
        f"`{module}` : `def agit`\n"
        "```\n"
        "Suite.\n",
    )
    _checked, _unverifiable, broken, _notes = cdr.check_symbol_kinds(doc)
    assert not broken, broken
