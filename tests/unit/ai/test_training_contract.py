"""Le garde-fou d'ouverture de run : un modèle ne reprend pas sur un contrat qui a bougé.

CE QUE CE FICHIER VERROUILLE, et ce que personne d'autre ne voit.

Trois contrôles existaient déjà à l'ouverture d'un run, et aucun n'attrape ce cas :
`check_model_lifecycle` regarde la COMMANDE (`--new` / `--append`), pas le modèle ; le verrou de
parité de pool (`test_pool_parity_lock.py`) attrape une reprise désappariée mais APRÈS la première
sonde, donc après des épisodes joués ; Stable-Baselines3 compare les espaces d'observation et
d'action au chargement — et ne voit donc que les changements de DIMENSION.

Reste la dérive à taille constante : un canal de grille permuté, une clé de récompense retirée. Les
tenseurs gardent leur forme, rien ne lève, et le modèle repris apprend sur des grandeurs qui ont
changé de sens. À l'échelle de ce dépôt, c'est un run de plusieurs dizaines d'heures rendu faux
sans une ligne rouge.

Le test le plus important du fichier est `test_une_valeur_de_recompense_modifiee_ne_bloque_rien` :
un garde-fou qui crie sur un réglage délibéré est un garde-fou qu'on désactive.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import pytest

from ai.training_contract import (
    CONTRACT_SUFFIX,
    build_contract,
    contract_mismatch,
    contract_path,
    diff_contracts,
    enforce_training_contract,
    read_contract,
    write_contract,
)

AGENT = "TestAgent"


def _rewards(**bloc: Any) -> Dict[str, Any]:
    """Une table de récompense d'agent, dans la forme réelle `{agent_key: {...}}`.

    La sous-table porte TOUJOURS `base_actions` : c'est la seule section que `RewardCalculator`
    exige nommément à chaque épisode (engine/reward_calculator.py:820), donc une table de test qui
    s'en passe n'est pas une table que la production accepterait.
    """
    sous_table: Dict[str, Any] = {"base_actions": {"charge_fail": -1.0}}
    sous_table.update(bloc or {"win": 10.0, "kill": {"ranged": 1.0}})
    return {"description": "table de test", AGENT: sous_table}


def _model(tmp_path: Path, *, existant: bool) -> str:
    model_path = tmp_path / AGENT / f"model_{AGENT}.zip"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    if existant:
        model_path.write_bytes(b"PK\x03\x04 modele entraine")
    return str(model_path)


# --------------------------------------------------------------------- contenu du contrat


def test_le_contrat_porte_les_registres_reels_du_moteur() -> None:
    """VERT VACANT évité : un contrat vide comparerait deux fois rien, et passerait toujours."""
    contrat = build_contract(_rewards(), AGENT)

    assert contrat["grid_channels"], "les canaux de grille sont vides"
    assert contrat["action_families"], "les familles d'actions sont vides"
    assert contrat["observation_fields"], "aucun registre d'observation découvert"
    # Les registres sont découverts par introspection : ceux-ci existent et doivent y être.
    assert "GLOBAL_CONT_FIELDS" in contrat["observation_fields"]
    assert "UNIT_BIN_FIELDS" in contrat["observation_fields"]
    assert "wall" in contrat["grid_channels"], "le canal `wall` a disparu du contrat"


def test_le_contrat_ne_porte_aucune_valeur_de_recompense() -> None:
    """Ce sont les CLÉS qui font le sens, les valeurs sont des réglages."""
    contrat = build_contract(_rewards(win=10.0), AGENT)
    serialise = json.dumps(contrat)

    assert "win" in contrat["reward_keys"]
    assert "10.0" not in serialise, "une valeur de récompense a fui dans le contrat"


def test_les_cles_de_recompense_sont_relatives_a_l_agent() -> None:
    """L'empreinte est prise SOUS la clé de l'agent.

    `load_agent_rewards_config` ajoute une clé alias à la racine en mode inter-faction : une
    empreinte prise à la racine changerait avec le MODE, sans qu'aucune récompense n'ait bougé.
    """
    contrat = build_contract(_rewards(win=1.0), AGENT)

    assert "win" in contrat["reward_keys"]
    assert AGENT not in contrat["reward_keys"], "la clé de l'agent est un préfixe, pas un contenu"
    assert "description" not in contrat["reward_keys"], "la racine du fichier a fui"


def test_une_table_sans_entree_pour_l_agent_est_refusee() -> None:
    """Même règle que `RewardCalculator` en production : on ne devine pas la sous-table."""
    with pytest.raises(ValueError, match="AutreAgent"):
        build_contract(_rewards(), "AutreAgent")


@pytest.mark.parametrize("sous_table", [{}, [], 3.0, "base_actions", None])
def test_une_sous_table_vide_est_refusee_a_l_ECRITURE(sous_table: Any) -> None:
    """L'écriture refuse ce que la relecture refuse : le contrat ne s'écrit pas sans empreinte.

    Une sous-table vide donnait `reward_keys: []`, écrit sans un mot. Le run suivant, lui, tombait
    dans `_exige_sections` — « section `reward_keys` vide » — en accusant le fichier de contrat
    alors que le coupable est la table de récompense. Le défaut se voit donc là où il naît, et non
    un run plus tard.
    """
    with pytest.raises(ValueError, match="base_actions"):
        build_contract({AGENT: sous_table}, AGENT)


def test_une_sous_table_sans_base_actions_est_refusee_a_l_ECRITURE() -> None:
    """Le cas FRÉQUENT, et non la table vide : une clé retirée d'un fichier de récompense.

    `RewardCalculator._get_unit_reward_config` lève dès la première action d'unité si la section
    `base_actions` manque (engine/reward_calculator.py:820). Sans ce refus, le prologue écrivait
    un contrat sur une table que la production ne sait pas lire, et le run mourait en cours
    d'épisode — des minutes plus tard, avec un message qui ne parle plus de la table.
    """
    with pytest.raises(ValueError, match="base_actions"):
        build_contract({AGENT: {"description": "note de roster", "win": 10.0}}, AGENT)


@pytest.mark.parametrize("section", [{}, [], "wait", 3.0, None])
def test_une_section_base_actions_vide_est_refusee_a_l_ECRITURE(section: Any) -> None:
    """Présente mais creuse, la section ne vaut pas mieux qu'absente — et le contrat, lui, passait.

    `_chemins_de_cles({"base_actions": {}})` rend un chemin : l'empreinte n'est pas vide, donc rien
    n'arrêtait l'écriture. La production, elle, lit `base_actions["ranged_attack"]` au premier tir
    (ai/reward_mapper.py:80) et lève. Même asymétrie que pour la section absente, un cran plus bas.
    """
    with pytest.raises(ValueError, match="base_actions"):
        build_contract({AGENT: {"base_actions": section, "win": 10.0}}, AGENT)


def test_l_ecriture_du_contrat_ne_produit_jamais_ce_que_la_relecture_refuse(tmp_path) -> None:
    """Bout en bout, sur les deux appels réels : `--new` écrit, la reprise relit.

    C'est la séquence exacte du prologue d'entraînement (`prepare_run_artifacts`), et c'est elle
    qui rendait l'asymétrie visible : le premier appel passait, le second levait.
    """
    model_path = _model(tmp_path, existant=False)
    enforce_training_contract(
        model_path, AGENT, _rewards(), new_model=False, log_fn=lambda _m: None
    )
    open(model_path, "wb").close()

    action, ecarts = enforce_training_contract(
        model_path, AGENT, _rewards(), new_model=False, log_fn=lambda _m: None
    )

    assert (action, ecarts) == ("verified", [])
    contrat = read_contract(model_path)
    assert contrat is not None and contrat["reward_keys"], "empreinte vide écrite sur disque"


# --------------------------------------------------------------------- comparaison


def test_un_contrat_identique_ne_produit_aucun_ecart() -> None:
    contrat = build_contract(_rewards(), AGENT)
    assert diff_contracts(contrat, contrat) == []


def test_une_cle_de_recompense_retiree_est_nommee() -> None:
    """LE cas d'origine : un événement qui ne rapporte plus rien, en silence."""
    avant = build_contract(_rewards(win=10.0, kill=1.0), AGENT)
    apres = build_contract(_rewards(win=10.0), AGENT)

    ecarts = diff_contracts(avant, apres)

    assert ecarts, "la disparition d'une clé de récompense doit être vue"
    assert any("kill" in e for e in ecarts), f"la clé retirée n'est pas nommée : {ecarts}"


def test_une_valeur_de_recompense_modifiee_ne_bloque_rien() -> None:
    """Le faux positif à ne PAS produire.

    Régler un poids est le mode d'emploi normal de cette table (un « conf » d'une ligne est un
    réglage délibéré, pas une dérive). Un garde-fou qui s'y déclenche est contourné le jour même,
    et ne protège donc plus de rien.
    """
    avant = build_contract(_rewards(win=10.0), AGENT)
    apres = build_contract(_rewards(win=42.5), AGENT)

    assert diff_contracts(avant, apres) == []


def test_deux_canaux_permutes_sont_une_divergence() -> None:
    """L'ordre EST le sens : même ensemble de noms, autre vecteur d'observation."""
    avant = build_contract(_rewards(), AGENT)
    apres = json.loads(json.dumps(avant))
    apres["grid_channels"][0], apres["grid_channels"][1] = (
        apres["grid_channels"][1], apres["grid_channels"][0],
    )

    ecarts = diff_contracts(avant, apres)

    assert any("ORDRE" in e for e in ecarts), (
        f"une permutation doit être vue comme telle, pas ignorée : {ecarts}"
    )


def test_un_champ_d_observation_ajoute_est_vu() -> None:
    avant = build_contract(_rewards(), AGENT)
    apres = json.loads(json.dumps(avant))
    apres["observation_fields"]["GLOBAL_CONT_FIELDS"].append("nouveau_champ")

    ecarts = diff_contracts(avant, apres)

    assert any("nouveau_champ" in e for e in ecarts), ecarts


def test_un_changement_de_version_de_format_se_dit_a_part() -> None:
    """Un format différent n'est pas « un contenu différent » : il n'est pas comparable."""
    avant = build_contract(_rewards(), AGENT)
    apres = dict(avant, version=avant["version"] + 1)

    ecarts = diff_contracts(avant, apres)

    assert len(ecarts) == 1 and "format" in ecarts[0], ecarts


# --------------------------------------------------------------------- garde-fou d'ouverture


def test_new_ecrit_le_contrat(tmp_path) -> None:
    model_path = _model(tmp_path, existant=False)

    action, ecarts = enforce_training_contract(
        model_path, AGENT, _rewards(), new_model=True, log_fn=lambda _m: None
    )

    assert (action, ecarts) == ("written", [])
    assert os.path.exists(contract_path(model_path))
    assert read_contract(model_path) == build_contract(_rewards(), AGENT)


def test_une_reprise_conforme_passe(tmp_path) -> None:
    model_path = _model(tmp_path, existant=True)
    write_contract(model_path, build_contract(_rewards(), AGENT))

    action, ecarts = enforce_training_contract(
        model_path, AGENT, _rewards(), new_model=False, log_fn=lambda _m: None
    )

    assert (action, ecarts) == ("verified", [])


def test_une_reprise_sans_contrat_s_arrete_et_dit_comment_initialiser(tmp_path) -> None:
    """Ne PAS écrire le contrat courant à la volée : ce serait déclarer conforme ce qu'on n'a pas
    comparé, et rendre le garde-fou muet exactement le jour où il servirait."""
    model_path = _model(tmp_path, existant=True)

    with pytest.raises(ValueError) as excinfo:
        enforce_training_contract(
            model_path, AGENT, _rewards(), new_model=False, log_fn=lambda _m: None
        )

    message = str(excinfo.value)
    assert "--init" in message and AGENT in message, message
    assert not os.path.exists(contract_path(model_path)), (
        "le refus a quand même écrit un contrat : la prochaine reprise passerait sans contrôle"
    )


def test_une_reprise_divergente_s_arrete_en_nommant_l_ecart(tmp_path) -> None:
    """Le scénario complet : la table a changé, le run ne démarre pas."""
    model_path = _model(tmp_path, existant=True)
    write_contract(model_path, build_contract(_rewards(win=10.0, kill=1.0), AGENT))

    with pytest.raises(ValueError) as excinfo:
        enforce_training_contract(
            model_path, AGENT, _rewards(win=10.0), new_model=False, log_fn=lambda _m: None
        )

    message = str(excinfo.value)
    assert "kill" in message, f"l'écart doit être nommé, pas résumé : {message}"
    assert "--new" in message, "le message doit dire par quoi sortir de l'impasse"
    assert "AUCUN autre controle" in message, (
        "un écart de récompense est le seul que rien d'autre ne voit — le message doit le dire, "
        "c'est ce qui justifie l'arrêt"
    )


def test_le_motif_de_l_arret_depend_de_la_famille_de_l_ecart() -> None:
    """Le message ne doit pas promettre une détection unique là où SB3 lève déjà.

    Mesuré le 2026-09-09 : sur 30 jours, 13 commits touchent une entrée de registre
    d'observation, dont 12 changent la DIMENSION — `check_for_correct_spaces` (SB3
    base_class.py:717) les attrape au chargement. Le message d'origine affirmait pour TOUS les
    écarts que « ni Stable-Baselines3 ni le verrou de parité ne l'auraient dit » : faux douze fois
    sur treize. Un motif d'arrêt qui sonne faux est un motif qu'on apprend à ignorer.
    """
    obs_seul = str(contract_mismatch("/m/model_A.zip", ["observation.GLOBAL_CONT_FIELDS : ajoute(s) ['x']"]))
    recompense_seule = str(contract_mismatch("/m/model_A.zip", ["reward_keys : retire(s) ['kill']"]))

    assert "AUCUN autre controle" not in obs_seul, (
        f"un écart d'observation ne doit pas se prétendre invisible ailleurs : {obs_seul}"
    )
    assert "Stable-Baselines3" in obs_seul and "avant le moindre effet de bord" in obs_seul, (
        f"il doit dire ce qu'il apporte VRAIMENT — s'arrêter plus tôt : {obs_seul}"
    )
    assert "AUCUN autre controle" in recompense_seule, recompense_seule


def test_un_vocabulaire_d_ids_est_invisible_partout_ailleurs() -> None:
    """Un registre `*_IDS` porte le SENS des valeurs, pas des cases : sa taille ne bouge jamais.

    « Le vocabulaire s'allonge pour zéro scalaire » (engine/observation_builder.py:135, verbatim).
    Vérifié le 2026-09-09 : 6 des 17 registres empreintés n'entrent pas dans le calcul de
    `SQUAD_OBS_SIZE_TARGET`, dont les quatre `*_IDS`. Une insertion y décale le sens de tous les
    ids suivants **sans changer une seule dimension** : ni `check_for_correct_spaces` ni le verrou
    de parité ne peuvent le voir. 21 commits sur 90 jours touchent un de ces registres.
    """
    vocabulaire = str(contract_mismatch(
        "/m/model_A.zip", ["observation.UNIT_RULE_EFFECT_IDS : ajoute(s) ['fnp_6']"]
    ))
    champs = str(contract_mismatch(
        "/m/model_A.zip", ["observation.GLOBAL_CONT_FIELDS : ajoute(s) ['fog']"]
    ))

    assert "AUCUN autre controle" in vocabulaire, (
        f"un vocabulaire d'ids est le cas où ce contrat est seul — le message doit le dire : "
        f"{vocabulaire}"
    )
    assert "AUCUN autre controle" not in champs, (
        "un champ d'observation, lui, change la dimension et fait lever SB3 : ne pas confondre "
        "les deux familles"
    )


def test_un_ecart_mixte_dit_les_deux_motifs() -> None:
    """Les deux familles à la fois : chacune garde son motif, aucune n'écrase l'autre."""
    message = str(contract_mismatch(
        "/m/model_A.zip",
        ["reward_keys : retire(s) ['kill']", "grid_channels : ajoute(s) ['fog']"],
    ))

    assert "AUCUN autre controle" in message and "Stable-Baselines3" in message, message


def test_un_contrat_present_mais_corrompu_leve(tmp_path) -> None:
    """Distinct de l'absence : les deux appellent des réponses opposées."""
    model_path = _model(tmp_path, existant=True)
    Path(contract_path(model_path)).write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="illisible"):
        read_contract(model_path)


def test_un_contrat_ampute_d_une_section_leve_au_lieu_de_la_lire_vide(tmp_path) -> None:
    """Un fichier tronqué n'est pas un écart de contrat : c'est un fichier à réparer.

    Section lue comme vide, la comparaison ne levait pas et produisait un diff FAUX — tous les
    registres du code annoncés « nouveaux » alors que rien n'avait bougé dans le code. Le message
    disait « le contrat a changé », et la sortie affichée pour ce message est `--new` : un modèle
    de plusieurs dizaines d'heures jeté sur un fichier abîmé.
    """
    model_path = _model(tmp_path, existant=True)
    ampute = build_contract(_rewards(), AGENT)
    del ampute["reward_keys"]
    Path(contract_path(model_path)).write_text(json.dumps(ampute), encoding="utf-8")

    with pytest.raises(ValueError, match="reward_keys"):
        read_contract(model_path)


def test_une_reprise_sur_contrat_ampute_s_arrete_sans_annoncer_un_faux_ecart(tmp_path) -> None:
    """Le chemin de production complet : le run s'arrête, et pas sur un motif inventé."""
    model_path = _model(tmp_path, existant=True)
    ampute = build_contract(_rewards(), AGENT)
    del ampute["observation_fields"]
    Path(contract_path(model_path)).write_text(json.dumps(ampute), encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        enforce_training_contract(
            model_path, AGENT, _rewards(), new_model=False, log_fn=lambda _m: None
        )

    message = str(excinfo.value)
    assert "illisible" in message and "observation_fields" in message, message
    assert "nouveau registre" not in message, (
        "un fichier tronqué s'est présenté comme une divergence du code : "
        f"{message}"
    )


def test_une_section_du_mauvais_type_leve(tmp_path) -> None:
    """Une liste de noms devenue autre chose se comparerait caractère par caractère."""
    model_path = _model(tmp_path, existant=True)
    tordu = build_contract(_rewards(), AGENT)
    tordu["grid_channels"] = "wall"
    Path(contract_path(model_path)).write_text(json.dumps(tordu), encoding="utf-8")

    with pytest.raises(ValueError, match="grid_channels"):
        read_contract(model_path)


def test_un_registre_d_observation_du_mauvais_type_leve(tmp_path) -> None:
    """Même règle un niveau plus bas : `observation_fields` est un dict de LISTES."""
    model_path = _model(tmp_path, existant=True)
    tordu = build_contract(_rewards(), AGENT)
    tordu["observation_fields"]["GLOBAL_CONT_FIELDS"] = "phase"
    Path(contract_path(model_path)).write_text(json.dumps(tordu), encoding="utf-8")

    with pytest.raises(ValueError, match="GLOBAL_CONT_FIELDS"):
        read_contract(model_path)


def test_un_contrat_sans_version_leve_au_lieu_de_se_dire_d_un_autre_format(tmp_path) -> None:
    """`None != 1` faisait passer un fichier sans version pour un format différent.

    Les deux se soignent autrement : un autre format se relit avec le code qui l'écrit, un
    fichier sans version se réécrit. Le confondre envoyait chercher une migration inexistante.
    """
    model_path = _model(tmp_path, existant=True)
    sans_version = build_contract(_rewards(), AGENT)
    del sans_version["version"]
    Path(contract_path(model_path)).write_text(json.dumps(sans_version), encoding="utf-8")

    with pytest.raises(ValueError, match="version"):
        read_contract(model_path)


def test_une_version_non_entiere_leve_au_lieu_de_sauter_le_controle_des_sections(tmp_path) -> None:
    """`"1"` textuel n'égale aucun entier : il faisait passer le fichier pour un autre format.

    Conséquence mesurée : le contrôle des sections était sauté, et un contrat amputé de
    `reward_keys` ressortait en « version de contrat 1 != 1 » — un message qui se contredit et
    qui cache la section manquante, avec `--new` pour sortie affichée.
    """
    model_path = _model(tmp_path, existant=True)
    tordu = build_contract(_rewards(), AGENT)
    tordu["version"] = str(tordu["version"])
    del tordu["reward_keys"]
    Path(contract_path(model_path)).write_text(json.dumps(tordu), encoding="utf-8")

    with pytest.raises(ValueError, match="version"):
        read_contract(model_path)


def test_une_section_vide_leve_comme_une_section_absente(tmp_path) -> None:
    """Vide ou absente, c'est le même faux diff — et `build_contract` n'écrit ni l'un ni l'autre.

    Les trois premières sections sont lues du code ; la quatrième d'une table de récompense dont
    `RewardCalculator` exige déjà `base_actions`. Une section vide est donc un fichier abîmé.
    """
    model_path = _model(tmp_path, existant=True)
    vide = build_contract(_rewards(), AGENT)
    vide["grid_channels"] = []
    Path(contract_path(model_path)).write_text(json.dumps(vide), encoding="utf-8")

    with pytest.raises(ValueError, match="grid_channels"):
        read_contract(model_path)


def test_un_registre_d_observation_vide_leve(tmp_path) -> None:
    """`_registres_nommes` n'empreinte que des tuples NON VIDES : un registre vide est abîmé."""
    model_path = _model(tmp_path, existant=True)
    vide = build_contract(_rewards(), AGENT)
    vide["observation_fields"]["GLOBAL_CONT_FIELDS"] = []
    Path(contract_path(model_path)).write_text(json.dumps(vide), encoding="utf-8")

    with pytest.raises(ValueError, match="GLOBAL_CONT_FIELDS"):
        read_contract(model_path)


def test_un_contrat_d_un_autre_format_ne_declenche_pas_le_controle_de_sections(tmp_path) -> None:
    """Le format futur définit ses propres sections : les exiger ici bloquerait sa lecture.

    C'est `diff_contracts` qui dit « format différent, contenu non comparable » — encore
    faut-il pouvoir lire le fichier pour le lui passer.
    """
    model_path = _model(tmp_path, existant=True)
    autre_format = {"version": 99, "ce_que_dira_le_format_suivant": []}
    Path(contract_path(model_path)).write_text(json.dumps(autre_format), encoding="utf-8")

    lu = read_contract(model_path)

    assert lu is not None and lu == autre_format
    ecarts = diff_contracts(lu, build_contract(_rewards(), AGENT))
    assert len(ecarts) == 1 and "format" in ecarts[0], ecarts


class _NonSerialisable:
    """Une valeur qui fait lever `json.dump` APRÈS qu'il a déjà écrit une partie du contrat."""


def test_une_ecriture_interrompue_laisse_le_contrat_precedent_intact(tmp_path) -> None:
    """Le contrat précédent survit à une écriture qui casse en cours de route.

    Le verrou de forme (`tests/unit/shared/test_json_atomic.py`) dit que ce site N'OUVRE PAS sa
    destination ; il ne dit pas ce qui reste sur le disque quand l'écriture casse. C'est
    précisément le moment qui compte : `json.dump` écrit EN FLUX, donc une valeur non
    sérialisable rencontrée au milieu du contrat laisse déjà des octets derrière elle. Avec une
    ouverture en "w", ces octets remplaçaient un contrat valide par un fragment, et la reprise
    suivante s'arrêtait sur « contrat illisible » au lieu de comparer.

    `sort_keys=True` fait passer `aaa` avant `zzz` : le début est écrit, la fin lève.
    """
    model_path = _model(tmp_path, existant=True)
    valide = build_contract(_rewards(), AGENT)
    write_contract(model_path, valide)

    with pytest.raises(TypeError):
        write_contract(model_path, {"aaa": "x" * 4096, "zzz": _NonSerialisable()})

    assert read_contract(model_path) == valide, (
        "l'écriture cassée a laissé un fragment à la place du contrat précédent"
    )
    nom_contrat = os.path.basename(contract_path(model_path))
    residus = [n for n in os.listdir(os.path.dirname(contract_path(model_path)))
               if n.startswith(nom_contrat) and n != nom_contrat]
    assert not residus, f"brouillon laissé derrière l'écriture cassée : {residus}"


# --------------------------------------------------------------------- câblage dans le prologue


def test_le_prologue_refuse_avant_tout_effet_de_bord(tmp_path, monkeypatch) -> None:
    """Un run qui doit s'arrêter ne doit pas avoir archivé le run précédent.

    C'est la raison du placement : le contrôle est AVANT `os.makedirs` et
    `archive_canonical_artifacts_for_new_run`, dont l'effet est irréversible sans intervention.
    """
    from ai import train

    class _Loader:
        def _resolve_agent_config_key(self, agent_key: str) -> str:
            return agent_key

    monkeypatch.setattr("ai.train.get_config_loader", lambda: _Loader())
    models_root = tmp_path / "models"
    (models_root / AGENT).mkdir(parents=True)
    model_path = models_root / AGENT / f"model_{AGENT}.zip"
    model_path.write_bytes(b"PK\x03\x04")
    write_contract(str(model_path), build_contract(_rewards(win=1.0, kill=1.0), AGENT))
    temoin = models_root / AGENT / "best_model.zip"
    temoin.write_bytes(b"best")

    with pytest.raises(ValueError, match="kill"):
        train.prepare_run_artifacts(
            str(models_root), AGENT, False, True, 1, _rewards(win=1.0), AGENT,
            log_fn=lambda _m: None,
        )

    assert temoin.exists(), "le refus a laissé le prologue archiver le run précédent"


def test_le_contrat_neuf_survit_a_l_archivage(tmp_path, monkeypatch) -> None:
    """`--new` écrit le contrat APRÈS l'archivage.

    Écrit avant, il partirait avec les artefacts du run précédent — l'agent neuf n'aurait alors
    aucun contrat, et sa première reprise s'arrêterait sur un « contrat absent » incompréhensible.
    """
    from ai import train

    class _Loader:
        def _resolve_agent_config_key(self, agent_key: str) -> str:
            return agent_key

    monkeypatch.setattr("ai.train.get_config_loader", lambda: _Loader())
    models_root = tmp_path / "models"
    (models_root / AGENT).mkdir(parents=True)
    (models_root / AGENT / f"model_{AGENT}.zip").write_bytes(b"PK\x03\x04")

    train.prepare_run_artifacts(
        str(models_root), AGENT, True, False, 1, _rewards(), AGENT, log_fn=lambda _m: None
    )

    contrat = models_root / AGENT / f"model_{AGENT}{CONTRACT_SUFFIX}"
    assert contrat.exists(), "le contrat neuf a été archivé avec le run précédent"
    assert json.loads(contrat.read_text(encoding="utf-8")) == build_contract(_rewards(), AGENT)


# --------------------------------------------------------------------- revue (2026-09-09)


def test_un_contrat_seul_n_est_pas_archive_sans_son_modele(tmp_path) -> None:
    """Deux `--new` dans la MÊME SECONDE ne doivent pas lever `FileExistsError`.

    Le premier `--new` écrit le contrat tout de suite, alors que le modèle n'arrivera qu'à la fin
    du run. Ce contrat-là n'accompagne donc aucun modèle : l'écarter faisait viser au second
    `--new` le nom d'archive que le premier venait de prendre — exactement la collision que la
    dérogation « sidecar vide » existe pour empêcher.
    """
    from ai.train import canonical_run_artifacts

    model_path = str(tmp_path / f"model_{AGENT}.zip")
    write_contract(model_path, build_contract(_rewards(), AGENT))

    noms = {os.path.basename(p) for p in canonical_run_artifacts(model_path)}

    assert f"model_{AGENT}{CONTRACT_SUFFIX}" not in noms, (
        "un contrat sans modèle n'a rien à accompagner"
    )


def test_deux_new_dans_la_meme_seconde_ne_levent_pas(tmp_path, monkeypatch) -> None:
    """Le scénario complet du cas ci-dessus, sur le vrai prologue."""
    from ai import train

    class _Loader:
        def _resolve_agent_config_key(self, agent_key: str) -> str:
            return agent_key

    monkeypatch.setattr("ai.train.get_config_loader", lambda: _Loader())
    models_root = tmp_path / "models"
    (models_root / AGENT).mkdir(parents=True)
    (models_root / AGENT / f"model_{AGENT}.zip").write_bytes(b"PK\x03\x04")

    for _ in range(2):
        train.prepare_run_artifacts(
            str(models_root), AGENT, True, False, 1, _rewards(), AGENT, log_fn=lambda _m: None
        )

    assert (models_root / AGENT / f"model_{AGENT}{CONTRACT_SUFFIX}").exists()


class _LoaderPromotion:
    """Ce que `_promote_checkpoint_for_resume` et `prepare_run_artifacts` consomment."""

    def __init__(self, tmp_path: Path) -> None:
        self._models_root = tmp_path / "models"

    def get_models_root(self) -> str:
        return str(self._models_root)

    def _resolve_agent_config_key(self, agent_key: str) -> str:
        return agent_key


def _canonique_et_checkpoint(tmp_path: Path, monkeypatch, *, contrat_checkpoint) -> tuple:
    """Un canonique sous le contrat `win=3.0`, un checkpoint sous `contrat_checkpoint` (ou sans).

    `build_agent_model_path` passe par le loader GLOBAL pour résoudre la clé d'agent, pas par
    celui qu'on donne à la promotion : sans ce patch, le test irait chercher un vrai dossier
    `config/agents/TestAgent/`.
    """
    from ai import train
    from ai.run_state import save_run_state
    from ai.vec_normalize_utils import get_vec_normalize_path

    loader = _LoaderPromotion(tmp_path)
    monkeypatch.setattr("ai.train.get_config_loader", lambda: loader)
    monkeypatch.setattr(train, "_pending_resume_promotion", None, raising=False)
    dossier = tmp_path / "models" / AGENT
    dossier.mkdir(parents=True)
    model_path = dossier / f"model_{AGENT}.zip"
    model_path.write_bytes(b"PK\x03\x04 canonique")
    write_contract(str(model_path), build_contract(_rewards(win=3.0), AGENT))

    checkpoint = dossier / "ppo_checkpoint_1000_steps.zip"
    checkpoint.write_bytes(b"PK\x03\x04 checkpoint")
    Path(get_vec_normalize_path(str(checkpoint))).write_bytes(b"stats")
    save_run_state(str(checkpoint), 7)
    if contrat_checkpoint is not None:
        write_contract(str(checkpoint), contrat_checkpoint)
    return train, loader, str(checkpoint)


def test_resume_from_installe_le_contrat_du_checkpoint_pas_celui_du_canonique(
    tmp_path, monkeypatch
) -> None:
    """Le modèle promu porte le contrat sous lequel LUI a appris.

    La promotion écarte les artefacts canoniques — contrat compris — et reposait ce contrat-là
    sur le checkpoint, en supposant qu'ils sortaient du même entraînement. Rien ne le garantit :
    les checkpoints des runs précédents restent dans le dossier. Le checkpoint emporte donc le
    sien, et c'est celui-là qui est installé.
    """
    contrat_checkpoint = build_contract(_rewards(win=3.0, kill=2.0), AGENT)
    train, loader, checkpoint = _canonique_et_checkpoint(
        tmp_path, monkeypatch, contrat_checkpoint=contrat_checkpoint
    )

    promu = train._promote_checkpoint_for_resume(checkpoint, AGENT, loader, log_fn=lambda _m: None)

    assert read_contract(promu) == contrat_checkpoint, (
        "le modèle promu porte le contrat du canonique écarté, pas le sien"
    )


def test_resume_from_refuse_un_checkpoint_sans_contrat(tmp_path, monkeypatch) -> None:
    """Sans contrat, on ne sait pas sur quoi le checkpoint a appris : on s'arrête, on ne suppose pas."""
    train, loader, checkpoint = _canonique_et_checkpoint(
        tmp_path, monkeypatch, contrat_checkpoint=None
    )

    with pytest.raises(FileNotFoundError, match="contrat d'entrainement absent"):
        train._promote_checkpoint_for_resume(checkpoint, AGENT, loader, log_fn=lambda _m: None)

    assert (tmp_path / "models" / AGENT / f"model_{AGENT}.zip").read_bytes() == b"PK\x03\x04 canonique", (
        "le refus a laissé la promotion toucher au modèle canonique"
    )


def test_un_checkpoint_d_un_autre_run_est_compare_sur_SON_contrat(tmp_path, monkeypatch) -> None:
    """Le scénario du bug, de bout en bout : promotion puis prologue.

    Le canonique a appris sous le contrat COURANT (`win` seul) ; le checkpoint vient d'un run
    antérieur où `kill` existait encore. Avec le contrat du canonique reposé sur le checkpoint, le
    prologue comparait ce contrat-là au code courant, disait « inchangé », et le run repartait sur
    des poids qui lisaient une clé disparue. Il doit s'arrêter en nommant `kill`.
    """
    contrat_ancien_run = build_contract(_rewards(win=3.0, kill=2.0), AGENT)
    train, loader, checkpoint = _canonique_et_checkpoint(
        tmp_path, monkeypatch, contrat_checkpoint=contrat_ancien_run
    )
    train._promote_checkpoint_for_resume(checkpoint, AGENT, loader, log_fn=lambda _m: None)

    with pytest.raises(ValueError, match="kill"):
        train.prepare_run_artifacts(
            loader.get_models_root(), AGENT, False, True, 1, _rewards(win=3.0), AGENT,
            log_fn=lambda _m: None,
        )


def test_la_cle_de_recompense_du_contrat_est_celle_du_run(tmp_path, monkeypatch) -> None:
    """`--agent A --rewards-config B` : c'est la table de B que le run optimise.

    Empreinter celle de A surveillerait une section que le run n'utilise pas, et laisserait
    passer une clé retirée de celle qu'il utilise. Même distinction que dans `test_trained_model`.
    """
    from ai import train

    class _Loader:
        def _resolve_agent_config_key(self, agent_key: str) -> str:
            return agent_key

    monkeypatch.setattr("ai.train.get_config_loader", lambda: _Loader())
    models_root = tmp_path / "models"
    (models_root / AGENT).mkdir(parents=True)
    socle = {"base_actions": {"charge_fail": -1.0}}
    table = {
        "description": "x",
        AGENT: {**socle, "win": 1.0},
        "PhaseB": {**socle, "win": 1.0, "kill": 2.0},
    }

    train.prepare_run_artifacts(
        str(models_root), AGENT, True, False, 1, table, "PhaseB", log_fn=lambda _m: None
    )

    ecrit = json.loads(
        (models_root / AGENT / f"model_{AGENT}{CONTRACT_SUFFIX}").read_text(encoding="utf-8")
    )
    assert "kill" in ecrit["reward_keys"], (
        "le contrat a empreinté la table de --agent au lieu de celle du run"
    )
