"""`[TARGET_MODELS:]` ne doit JAMAIS servir à rendre un verdict — liste blanche des lecteurs.

DEUX FOIS le même défaut, et c'est pour ça que ce garde existe :

- 2026-07-24, mêlée : « fight from non-adjacent » mesurait l'adjacence sur ce segment. Contrôle
  RETIRÉ, vérification déplacée en test moteur.
- 2026-08-12, tir : `shoot_handler` mesurait la portée dessus. 31 faux « hors portée » sur
  600 épisodes, zéro tir réellement illégal.

La cause est structurelle, pas accidentelle. Ce segment liste les survivants **post-pertes** et
n'est émis que sur le DERNIER jet visant la cible (`w40k_core`) : la figurine visée — celle sur
laquelle le moteur a décidé — en disparaît dès qu'elle meurt de l'action qu'on juge. Toute mesure
géométrique prise dessus décrit un état postérieur à la décision qu'elle prétend contrôler.

`step_logger` l'écrit d'ailleurs à la source : segment « consommé UNIQUEMENT par le replay », tenu
distinct de `[MODELS:]` « pour ne pas perturber l'analyzer ». Ce test rend cette phrase opposable.

SEUL USAGE LÉGITIME : recaler l'état per-figurine APRÈS l'action (`analyzer_core`), c'est-à-dire
exactement ce que le segment décrit. Tout autre lecteur doit ajouter sa ligne ici ET expliquer
pourquoi il ne juge rien avec.
"""
from __future__ import annotations

import pathlib
import re

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[3]
AI = RACINE / "ai"

#: Fichier -> raison. `analyzer_core` recale `positions_by_model` après l'action : le segment
#: décrit précisément cet état-là, et le décalage d'une ligne qu'il maintient est ce qui permet
#: aux contrôles de mesurer, eux, la position de DÉPART.
LECTEURS_AUTORISES = {
    "analyzer_perfig.py": "définit le parseur lui-même",
    "analyzer_core.py": "recale l'état per-figurine APRÈS l'action (usage décrit par le segment)",
}


def _fichiers_python():
    return sorted(p for p in AI.rglob("*.py") if "__pycache__" not in p.parts)


def test_le_parseur_du_segment_n_est_appele_que_par_les_lecteurs_autorises():
    """VERROU : rebrancher `parse_target_models_segment` dans un handler de phase rend ce test ROUGE."""
    appels = re.compile(r"\bparse_target_models_segment\s*\(")
    coupables = {}
    for chemin in _fichiers_python():
        texte = chemin.read_text(encoding="utf-8")
        # On ne compte que les APPELS, pas les mentions en commentaire ou en import.
        for ligne in texte.splitlines():
            nue = ligne.strip()
            if nue.startswith("#") or nue.startswith("from ") or nue.startswith("import "):
                continue
            if appels.search(ligne):
                coupables.setdefault(chemin.name, []).append(nue[:90])
    inattendus = {f: l for f, l in coupables.items() if f not in LECTEURS_AUTORISES}
    assert inattendus == {}, (
        f"`[TARGET_MODELS:]` lu hors de la liste blanche : {inattendus}. Ce segment liste les "
        f"survivants POST-pertes — en juger une distance a déjà produit 31 faux positifs de "
        f"portée (2026-08-12) et fait retirer un contrôle de mêlée (2026-07-24). Pour un verdict, "
        f"lire `state.positions_by_model`, qui porte l'état d'AVANT l'action."
    )


def test_la_liste_blanche_n_est_pas_vide_de_sens():
    """Un garde dont la liste blanche ne correspond à aucun fichier réel ne garde rien."""
    presents = {p.name for p in _fichiers_python()}
    manquants = sorted(set(LECTEURS_AUTORISES) - presents)
    assert manquants == [], f"liste blanche périmée, fichiers absents : {manquants}"


def test_le_controle_de_portee_lit_bien_l_etat_d_avant():
    """Le tir, corrigé le 2026-08-12, doit lire la géométrie gelée — et rien d'autre.

    D'abord `positions_by_model` (état jusqu'à la ligne N-1), puis `engagement_models` : cette carte
    EST `positions_by_model`, figée à la première ligne de l'activation. Le passage au gel répare
    une extinction silencieuse — la carte vive est purgée dès la première figurine tuée, et le
    contrôle ne rendait plus aucun verdict pour le reste de l'activation.
    """
    source = (AI / "analyzer_phases" / "shoot_handler.py").read_text(encoding="utf-8")
    bloc = source[source.index("if weapon_range is not None:"):]
    bloc = bloc[: bloc.index("# Track shots after advance")]
    assert "engagement_models" in bloc, "le contrôle de portée doit lire l'état d'AVANT l'action"
    assert "parse_target_models_segment" not in bloc, (
        "le contrôle de portée relit le segment post-pertes — régression du 2026-08-12"
    )
