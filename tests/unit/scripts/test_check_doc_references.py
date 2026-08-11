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

import importlib.util
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "check_doc_references", ROOT / "scripts" / "check_doc_references.py"
)
assert _SPEC is not None and _SPEC.loader is not None
cdr = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cdr)


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


# --------------------------------------------------------------------------- valeurs


def test_stale_value_is_detected(tmp_path: pathlib.Path) -> None:
    doc = write(tmp_path, "ROADMAP.md", "les **99** profils sont à 48 envs\n")
    _verified, broken = cdr.check_values(doc)
    assert any("VALEUR PÉRIMÉE" in entry and "99" in entry for entry in broken)


def test_true_value_is_confirmed(tmp_path: pathlib.Path) -> None:
    count = len(cdr.agent_profiles())
    doc = write(tmp_path, "ROADMAP.md", f"les **{count}** profils\n")
    verified, broken = cdr.check_values(doc)
    assert verified == 1
    assert not any("VALEUR PÉRIMÉE" in entry for entry in broken)


def test_orphan_assertion_is_reported(tmp_path: pathlib.Path) -> None:
    """Une phrase reformulée doit faire ROUGIR le contrôle, pas le rendre muet."""
    doc = write(tmp_path, "ROADMAP.md", "plus aucune des phrases surveillees ici\n")
    _verified, broken = cdr.check_values(doc)
    assert len(broken) == len(cdr.VALUE_CHECKS["ROADMAP.md"])
    assert all("ASSERTION ORPHELINE" in entry for entry in broken)


def test_profile_table_reads_thousands_separator(tmp_path: pathlib.Path) -> None:
    """« 10 000 » vaut dix mille : le lire comme 10 inventerait une valeur périmée."""
    episodes = cdr.agent_profiles()["x1"]["total_episodes"]
    final = cdr.agent_profiles()["x1"]["callback_params"]["bot_eval_final"]
    doc = write(tmp_path, "ROADMAP.md", f"| `x1` | {episodes:,} | {final} |\n".replace(",", " "))
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
    doc = write(tmp_path, "ROADMAP.md", "voir `engine/observation_entities.py:274`\n")
    assert len(cdr.check_anchors(doc)) == 1


def test_symbol_reference_is_not_an_anchor(tmp_path: pathlib.Path) -> None:
    doc = write(tmp_path, "ROADMAP.md", "voir `def compute_candidate_footprint` dans le moteur\n")
    assert cdr.check_anchors(doc) == []


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
    """Les trois documents d'entrée passent le contrôle — c'est la ligne de base à tenir."""
    for name in ("analyzer_couverture.md", "ROADMAP.md", "Security.md"):
        path = ROOT / "Documentation" / "Implémentation" / name
        _resolved, _unverifiable, broken_refs = cdr.check_references(path)
        _checked, _skipped, broken_links = cdr.check_links(path)
        _verified, broken_values = cdr.check_values(path)
        broken = broken_refs + broken_links + broken_values + cdr.check_anchors(path)
        assert not broken, f"{name} : " + " | ".join(broken)
