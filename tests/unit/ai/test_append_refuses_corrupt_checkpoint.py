"""Un checkpoint illisible ARRETE le run — il ne se transforme pas en modele neuf.

Les trois sites de chargement de `ai/train.py` entouraient `MaskablePPO.load` d'un
`except Exception` qui construisait un modele NEUF et poursuivait l'entrainement. Consequence
sur un `--append` dont le .zip est corrompu, tronque ou absent : des heures d'entrainement depuis
des poids aleatoires, un code de sortie 0, et pour seul signal deux lignes « Failed to load
model / Creating new model instead » noyees dans le log. Le desastre ne se voyait qu'au win-rate
du run suivant.
"""

import ast
import re
import zipfile
from functools import lru_cache
from pathlib import Path

import pytest

import ai.train as train

from .test_train_helpers import _function_code

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TRAIN_PY = PROJECT_ROOT / "ai" / "train.py"
#: Dossiers de `Documentation/` qui ARCHIVENT au lieu d'instruire : archives (chantiers livres,
#: docs morts, prompts consommes), spec V11, backlog, PDF de regles. Les commandes qu'ils citent
#: sont des relevés d'execution passes — les reecrire falsifierait l'archive, donc les controler
#: n'aurait pas de sens. Arborescence refonte 2026-08-27 : Reference/, Chantiers/ (racine) et
#: Roadmap/ restent scannes, ce sont les docs vivantes.
_DOSSIERS_ARCHIVES = {"Archives", "v11", "backlog", "40k_rules"}


def _docs_vivantes() -> list:
    """Les docs qu'on EXECUTE : `CLAUDE.md` et tout `Documentation/` hors archives.

    Nommer deux fichiers en dur ne suffisait pas — la meme commande fausse vivait aussi dans
    `Documentation/Prompts/` et `Documentation/Code_Compliance/`, que rien ne regardait.
    """
    docs = [PROJECT_ROOT / "CLAUDE.md"]
    docs += [
        p for p in (PROJECT_ROOT / "Documentation").rglob("*.md")
        if not (_DOSSIERS_ARCHIVES & set(p.relative_to(PROJECT_ROOT).parts))
    ]
    return docs


def _lignes_de_commande_train():
    """(fichier, numero, ligne) pour chaque ligne de doc vivante qui appelle `ai/train.py`."""
    for fichier in _docs_vivantes():
        for numero, ligne in enumerate(fichier.read_text(encoding="utf-8").splitlines(), 1):
            if "ai/train.py" in ligne:
                yield fichier, numero, ligne


@lru_cache(maxsize=1)
def _source_train() -> str:
    """`ai/train.py` lu UNE fois par process. 237 Ko : le relire par test coutait ~2 ms chacun, et
    le re-parser 0,17 s — 70 % du temps de ce fichier de test."""
    return TRAIN_PY.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _arbre_train() -> ast.Module:
    return ast.parse(_source_train())


@lru_cache(maxsize=1)
def _flags_declares() -> frozenset:
    """Les `--flags` que l'argparse de `ai/train.py` declare REELLEMENT."""
    flags = set()
    for node in ast.walk(_arbre_train()):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "add_argument":
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.startswith("--"):
                flags.add(arg.value)
    return frozenset(flags)


def test_load_checkpoint_raises_on_a_corrupt_zip(tmp_path: Path) -> None:
    """Le cas vecu : le .zip existe, donc `os.path.exists` est vrai et la branche de reprise est
    prise, mais son contenu n'est pas un checkpoint.

    La cause d'origine reste CHAINEE : sans elle, la traceback ne dit plus POURQUOI le zip est
    illisible (tronque ? mauvais pickle ? droits ?) et le diagnostic repart de zero.
    """
    corrupt = tmp_path / "model_CoreAgent.zip"
    corrupt.write_bytes(b"ce n'est pas une archive zip")

    with pytest.raises(RuntimeError) as excinfo:
        train._load_checkpoint(str(corrupt), env=None, device="cpu")

    message = str(excinfo.value)
    assert str(corrupt) in message, "le message doit NOMMER le chemin du modele illisible"
    assert "--new" in message, "le message doit rappeler l'option pour repartir de zero"
    assert excinfo.value.__cause__ is not None, "la cause d'origine doit rester chainee"


def test_load_checkpoint_raises_on_a_valid_zip_that_is_not_a_checkpoint(tmp_path: Path) -> None:
    """VERT VACANT : un fichier non-zip echoue des le premier octet lu. Une archive VALIDE mais
    sans les entrees attendues par SB3 fait echouer `load` plus loin (KeyError / pickle), et c'est
    ce chemin-la que l'`except Exception` supprime aussi."""
    archive = tmp_path / "model_CoreAgent.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("readme.txt", "archive valide, checkpoint absent")
    assert zipfile.is_zipfile(archive), "l'echantillon doit vraiment etre une archive lisible"

    with pytest.raises(RuntimeError, match="Checkpoint illisible"):
        train._load_checkpoint(str(archive), env=None, device="cpu")


def test_load_checkpoint_ne_court_circuite_jamais_sur_un_fichier_absent(tmp_path: Path) -> None:
    """CONTRAT DU HELPER, pas du flux : la production ne l'atteint plus (`--append` sans modele est
    refuse en amont, la branche de chargement teste `os.path.exists`). Le verrou reste utile parce
    que la tentation, le jour ou ce chemin redevient atteignable, est d'y remettre un
    `if not os.path.exists(...): return <modele neuf>` — un repli qu'aucune sentinelle `except` ne
    verrait, puisqu'il n'y a pas d'`except`."""
    absent = tmp_path / "jamais_ecrit.zip"
    with pytest.raises(RuntimeError, match="Checkpoint illisible"):
        train._load_checkpoint(str(absent), env=None, device="cpu")


def test_load_checkpoint_diagnoses_an_observation_space_mismatch(monkeypatch) -> None:
    """Mode d'echec DOMINANT apres un changement d'obs_size (199 -> 1011, GRID_CHANNELS 7 -> 9) :
    le .zip est intact, c'est l'environnement qui a change. Un message unique « verifier
    l'integrite du .zip » envoie chercher un probleme de fichier qui n'existe pas.
    """
    def _refuse(*_args, **_kwargs):
        raise ValueError(
            "Observation spaces do not match: Box(-1.0, 1.0, (199,), float32) "
            "!= Box(-1.0, 1.0, (1011,), float32)"
        )

    monkeypatch.setattr(train.MaskablePPO, "load", staticmethod(_refuse))

    with pytest.raises(RuntimeError) as excinfo:
        train._load_checkpoint("ai/models/CoreAgent/model_CoreAgent.zip", env=None, device="cpu")

    message = str(excinfo.value)
    assert "incompatible" in message, "le desaccord d'espace doit avoir son propre diagnostic"
    assert "integrite du .zip" not in message, (
        "un fichier intact ne doit pas etre presente comme corrompu"
    )
    assert "--new" in message


def test_les_deux_diagnostics_partagent_le_meme_conseil_de_reprise() -> None:
    """Ce qu'on fait APRES l'arret ne depend pas de la raison de l'arret : une constante, pas deux
    queues de message recopiees. C'est la divergence des copies — trois exemplaires, deux `print`,
    un `chunk_log`, un emoji casse — qui a laisse le repli survivre a la suppression de ses
    jumeaux ; le refaire a l'echelle de deux branches rejouerait la meme histoire."""
    code = _function_code(train._load_checkpoint)
    assert code.count("_CONSEIL_DE_REPRISE") == 2, (
        "les deux branches de diagnostic doivent citer la constante, pas recopier le conseil"
    )
    assert "relancer avec --new" not in code, "conseil recopie dans une branche"


def test_aucune_commande_documentee_ne_cite_un_flag_inexistant() -> None:
    """Les messages d'aide et les docs proposent des COMMANDES `ai/train.py` copiables. `--new-model`
    n'a jamais existe dans l'argparse : la commande copiee sortait en erreur d'argument, et le flag
    mort a survecu dans `Documentation/Reference/training/AI_TRAINING.md` a sa correction dans le code.

    Le controle porte sur la PROPRIETE, pas sur une chaine nommee en dur : tout `--flag` cite sur
    une ligne qui appelle `ai/train.py` doit etre declare par l'argparse. N'importe quel autre flag
    invente (`--from-scratch`, `--eval-only`) est couvert sans liste a tenir. Limite assumee : une
    commande etalee sur plusieurs lignes n'est lue que sur celle qui porte `ai/train.py`.
    """
    declares = _flags_declares()
    assert "--new" in declares and "--append" in declares, (
        "VERT VACANT : l'extraction des flags declares ne rend rien d'attendu"
    )

    lignes = list(_lignes_de_commande_train())
    lignes += [
        (TRAIN_PY, numero, ligne)
        for numero, ligne in enumerate(_source_train().splitlines(), 1)
        if "ai/train.py" in ligne
    ]
    assert len(lignes) > 20, (
        f"VERT VACANT : {len(lignes)} ligne(s) de commande trouvee(s), le controle ne lit rien"
    )

    inconnus = [
        f"{fichier.relative_to(PROJECT_ROOT)}:{numero} → {token}"
        for fichier, numero, ligne in lignes
        for token in re.findall(r"(?<![\w-])--[a-z][a-z0-9-]*", ligne)
        if token not in declares
    ]
    assert not inconnus, (
        f"commandes citant un flag que l'argparse ne declare pas : {inconnus}. "
        f"Flags declares : {sorted(declares)}"
    )


def test_aucune_commande_documentee_ne_combine_des_options_que_train_refuse() -> None:
    """Un flag qui EXISTE ne fait pas une commande qui MARCHE. `--test-only`/`--eval` n'evalue que
    le holdout et refuse explicitement `--scenario bot` (« --scenario bot is not allowed in
    --test-only mode ») : trois docs vivantes portaient cette combinaison, dont deux dont le
    pipeline enchaine `| tee … ; ai/analyzer.py step.log` — la commande sortait en ValueError et
    l'analyse tournait sur un step.log PERIME, sans que rien ne le signale.

    Le controle porte sur l'incompatibilite declaree par le code, pas sur une liste de fichiers :
    toute doc vivante qui la reintroduit devient rouge.
    """
    assert "--scenario bot is not allowed in --test-only mode" in _source_train(), (
        "VERT VACANT : le refus surveille n'existe plus dans ai/train.py, le test ne prouve rien"
    )

    fautives = [
        f"{fichier.relative_to(PROJECT_ROOT)}:{numero}"
        for fichier, numero, ligne in _lignes_de_commande_train()
        if "--scenario bot" in ligne and ("--test-only" in ligne or "--eval" in ligne)
    ]
    assert not fautives, (
        f"commandes qui sortiront en ValueError avant d'evaluer quoi que ce soit : {fautives}. "
        "En mode eval, retirer `--scenario bot` : le holdout est resolu tout seul."
    )


@pytest.mark.parametrize(
    "func_name", ["create_multi_agent_model", "train_with_scenario_rotation"]
)
def test_no_training_entry_point_rebuilds_a_model_when_the_load_fails(func_name: str) -> None:
    """JUMEAU — le motif du repli existait en TROIS exemplaires deja divergents (deux `print`,
    un `chunk_log`, un emoji casse) : c'est ainsi qu'un repli survit a la suppression de son
    jumeau. Les deux points d'entree d'entrainement doivent passer par `_load_checkpoint` et ne
    plus rattraper son echec.
    """
    code = _function_code(getattr(train, func_name))

    assert "_load_checkpoint(" in code, (
        f"{func_name} ne charge plus le checkpoint par le helper qui leve"
    )
    # Cible `model_path` et pas tout `MaskablePPO.load(` : `train_with_scenario_rotation` en garde
    # un usage LEGITIME, la relecture du snapshot de self-play qu'il vient d'ecrire lui-meme.
    assert "MaskablePPO.load(model_path" not in code, (
        f"{func_name} recharge le checkpoint en direct : le repli peut y etre revenu"
    )


def test_un_premier_entrainement_sans_flag_ne_reclame_pas_de_stats_vecnormalize(tmp_path) -> None:
    """Scenario : `python3 ai/train.py --agent <nouvel_agent> --scenario bot`, dossier
    `ai/models/<agent>/` VIDE, profil avec `vec_normalize.enabled: true`.

    Aucun drapeau n'est exige (rien a ecraser), la branche de construction cree bien un modele
    neuf — mais `_apply_vec_normalize` ne recevait que `new_model`, donc il prenait la branche
    « reprise » et levait « stats absentes ». Un premier entrainement legal mourait sur un message
    qui accuse une reprise que personne n'a demandee.
    """
    model_path = str(tmp_path / "model_NouvelAgent.zip")
    assert not Path(model_path).exists(), "VERT VACANT : le modele doit vraiment manquer"

    # `object()` suffit : avec `starts_from_scratch`, la fonction ne doit toucher ni au disque ni
    # a l'env avant la construction des stats neuves — c'est le refus qu'on verifie ici.
    with pytest.raises(FileNotFoundError):
        train._apply_vec_normalize(object(), model_path, {}, False, 2, lambda _m: None)
    erreur_levee = None
    try:
        train._apply_vec_normalize(object(), model_path, {}, True, 2, lambda _m: None)
    except FileNotFoundError as exc:  # pragma: no cover - c'est precisement ce qui ne doit pas arriver
        erreur_levee = exc
    except Exception:
        pass  # la construction de VecNormalize sur un `object()` echoue, et c'est hors sujet
    assert erreur_levee is None, (
        "un run qui part de zero ne doit pas reclamer les stats d'une reprise"
    )


@pytest.mark.parametrize(
    "func_name", ["create_multi_agent_model", "train_with_scenario_rotation"]
)
def test_vecnormalize_lit_le_meme_predicat_que_la_branche_du_modele(func_name: str) -> None:
    """JUMEAU : la question « ce run part-il de zero ? » se decide UNE fois. Les deux points
    d'entree la posaient deux fois, sur deux entrees differentes — `new_model` pour VecNormalize,
    `new_model or not os.path.exists(model_path)` pour le modele — et ces deux reponses divergent
    exactement sur le premier entrainement d'un agent."""
    code = _function_code(getattr(train, func_name))
    appel = code[code.index("_apply_vec_normalize("):]
    assert "new_model or not os.path.exists(model_path)" in appel[:400], (
        f"{func_name} passe a _apply_vec_normalize un predicat different de celui de la branche"
    )


def test_no_load_site_at_all_rebuilds_a_model_on_failure() -> None:
    """Meme interdit, mais sur TOUT le module et sans liste de fonctions a tenir a jour.

    Le test ci-dessus nomme les deux points d'entree connus : un TROISIEME site de chargement,
    ajoute demain, y echapperait en silence — et c'est exactement l'histoire de ce repli, qui a
    survecu a la suppression de ses jumeaux. Celui-ci n'interroge plus des noms mais le MOTIF :
    un `except` qui enveloppe un chargement et y reconstruit un `MaskablePPO`.
    """
    essais_de_chargement = 0
    fautifs: list[str] = []
    for node in ast.walk(_arbre_train()):
        if not isinstance(node, ast.Try):
            continue
        # `MaskablePPO.load` / `VecNormalize.load`, jamais `json.load` : mesure du 2026-08-12, la
        # sentinelle comptait quatre `json.load` et restait donc verte apres suppression de TOUS
        # les chargements de modele — elle ne pouvait plus voir ce pour quoi elle existe.
        charge = any(
            isinstance(n, ast.Attribute) and n.attr == "load"
            and isinstance(n.value, ast.Name) and n.value.id in ("MaskablePPO", "PatchedMaskablePPO", "VecNormalize")
            for corps in node.body for n in ast.walk(corps)
        )
        # `and node.handlers` : un `try/finally` NU ne peut rien rattraper, donc il ne prouve rien.
        # Sans ce terme, le compte etait satisfait par le `try/finally` de nettoyage du tmpdir et
        # par le site d'eval — la sentinelle serait restee verte apres disparition du seul `try`
        # qu'elle surveille, c'est-a-dire en ne regardant plus rien.
        if not charge or not node.handlers:
            continue
        essais_de_chargement += 1
        for handler in node.handlers:
            if any(
                isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "MaskablePPO"
                for n in ast.walk(handler)
            ):
                fautifs.append(f"ai/train.py:{handler.lineno}")
    assert essais_de_chargement >= 1, "aucun chargement sous `try` trouve : le test regarde le vide"
    assert not fautifs, (
        f"un `except` autour d'un chargement reconstruit un MaskablePPO : {fautifs}. "
        "Un --append dont le checkpoint est illisible doit s'arreter, pas s'entrainer des heures "
        "depuis des poids aleatoires en sortant en code 0."
    )
