"""Verrou : tout scenario ECRIT par un script declare `uses_codex_detachment`.

Ce champ est OBLIGATOIRE des qu'une armee ADEPTUS ASTARTES est en jeu — `game_state.
uses_codex_detachment` leve sinon, et il leve TARD : au premier jet de blessure d'un marine
contre la cible d'Oath, donc en plein episode, apres des minutes de generation et de run. Les
scenarios commites, eux, portent tous la cle ; ce sont les GENERATEURS qui l'avaient perdue, et
une regeneration l'effacait des fichiers commites sans qu'aucun test ne bouge.

Deux verrous complementaires :
  - un STATIQUE, qui couvre les trois sites d'ecriture a la fois (le payload rule-checker n'est
    pas extractible sans lancer la generation, qui ecrit sous `config/`) ;
  - un FONCTIONNEL, qui fait relire la valeur emise par le LECTEUR du moteur — un test de
    presence de cle laisserait passer une forme que le moteur refuse.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from engine.game_state import uses_codex_detachment
from tests._chargeur_script import charger_script

PROJECT_ROOT = Path(__file__).resolve().parents[3]

#: Les scripts qui ECRIVENT des scenarios. `primary_objectives` est le marqueur d'un payload de
#: scenario : il est present dans les trois, et absent de tout autre dict de ces fichiers.
SCENARIO_WRITERS = (
    "scripts/roster_matchup_stats.py",
    "shared/rule_checker_scenarios.py",
    "scripts/build_holdout_benchmark.py",
    "scripts/smoke_t5_bare.py",
)


def _scenario_payload_literals(path: Path) -> list[ast.Dict]:
    """Les dict litteraux de `path` qui sont des payloads de scenario."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
        if "primary_objectives" in keys:
            found.append(node)
    return found


@pytest.mark.parametrize("relative", SCENARIO_WRITERS)
def test_every_generated_scenario_declares_codex_detachment(relative: str) -> None:
    payloads = _scenario_payload_literals(PROJECT_ROOT / relative)
    # VERT VACANT : un fichier dont on n'extrait AUCUN payload passerait le test sans rien
    # regarder. L'echantillon doit exister avant d'etre juge.
    assert payloads, f"aucun payload de scenario trouve dans {relative}"
    for payload in payloads:
        emitted = {
            k.value: v for k, v in zip(payload.keys, payload.values)
            if isinstance(k, ast.Constant)
        }
        assert "uses_codex_detachment" in emitted, (
            f"{relative}:{payload.lineno} ecrit un scenario sans `uses_codex_detachment` — "
            "il levera au premier jet de blessure d'un marine sous Oath of Moment"
        )
        # La VALEUR, pas seulement la cle : `True` nu, `{"1": True}` seul ou des cles entieres
        # passeraient une verification de presence et leveraient quand meme (TypeError/KeyError)
        # en plein episode — exactement la panne tardive que ce fichier existe pour empecher.
        # Le litteral est deja dans le noeud AST : c'est le LECTEUR du moteur qui le juge.
        value = ast.literal_eval(emitted["uses_codex_detachment"])
        for player in (1, 2):
            assert uses_codex_detachment({"config": {"uses_codex_detachment": value}}, player), (
                f"{relative}:{payload.lineno} : valeur illisible ou fausse pour le joueur "
                f"{player} ({value!r})"
            )


def test_the_emitted_value_is_the_one_the_engine_reads() -> None:
    """La valeur emise traverse le LECTEUR du moteur, pour les DEUX joueurs.

    `_build_scenario_template` est le seul des trois generateurs dont le payload s'obtient sans
    ecrire sous `config/` ; c'est donc lui qui porte la preuve de FORME, commune aux trois
    (meme litteral `{"1": True, "2": True}`).
    """
    template = charger_script("scripts/roster_matchup_stats.py")._build_scenario_template(
        "100pts", "44x60x5", "terrain-mc1.json"
    )
    for player in (1, 2):
        assert uses_codex_detachment({"config": template}, player) is True


def test_the_rule_checker_run_key_follows_its_payload() -> None:
    """La cle de dossier rule-checker doit BOUGER quand le payload emis change.

    LA PANNE, mesuree le 2026-08-06. `generate` rend un jeu deja present sans le reecrire, et il
    le reconnait par `_run_key` + le NOMBRE de fichiers. La cle ne hachait que les ENTREES
    (unites, echelle, plateau, terrain) : le jour ou `build_scenario_payload` a gagne
    `army_faction`, les 2401 fichiers deja ecrits ont garde la meme cle et le meme nombre, donc
    ils ont ete rendus tels quels. L'entrainement rule-checker levait
    « config['army_faction'] est absent » a l'ouverture de la phase de commandement, juste apres
    le deploiement — soit apres la generation ET apres tout le deploiement d'un episode.

    Ce test tient l'invariant qui l'empeche, sans dependre d'AUCUNE cle en particulier : il fait
    varier le payload et exige que la cle suive. Un champ ajoute demain sera couvert sans que
    personne ait a y penser.

    DEUX mutations, et la seconde est celle qui compte. Elle ne touche QUE les matchups CROISES
    (`p1 != p2`) : tout repli partiel qui a servi de tentation ici — un payload TEMOIN miroir
    `units[0]` vs `units[0]`, ou la seule diagonale `(u, u)` — n'en voit rien et laisse la cle
    immobile pendant que presque tous les fichiers changent. Seule l'enumeration COMPLETE des
    couples, celle que `generate` ecrit, deplace la cle.
    """
    from shared import rule_checker_scenarios as rcs

    params = rcs.GenerationParams()
    units = ["Intercessor", "Boyz"]

    def key() -> str:
        """La cle telle que `generate` la calcule : sur les payloads qu'il s'apprete a ecrire."""
        return rcs._run_key(units, params, rcs._payloads(units, params))

    before = key()

    # 1. Le payload gagne un champ, partout. C'est la panne d'origine, a l'identique.
    real_payload = rcs.build_scenario_payload
    try:
        rcs.build_scenario_payload = lambda *a, **k: {
            **real_payload(*a, **k), "_un_champ_de_plus": True,
        }
        after_shape = key()
    finally:
        rcs.build_scenario_payload = real_payload

    assert after_shape != before, (
        "`_run_key` ignore le payload : un jeu de scenarios deja ecrit sera reutilise apres un "
        "changement de `build_scenario_payload`, et le training levera en plein episode sur le "
        "champ manquant. Hacher les payloads, pas seulement les entrees."
    )

    # 2. Seuls les matchups CROISES bougent. Ni un temoin miroir, ni la diagonale complete n'en
    #    voient quoi que ce soit : il faut TOUS les couples.
    try:
        rcs.build_scenario_payload = lambda p1, p2, *a, **k: (
            {**real_payload(p1, p2, *a, **k), "_croise": True}
            if p1 != p2
            else real_payload(p1, p2, *a, **k)
        )
        # VERT VACANT : si la mutation n'atteignait aucun payload, la cle resterait identique pour
        # une bonne raison et l'assertion suivante ne prouverait rien.
        assert "_croise" in rcs.build_scenario_payload(
            units[0], units[1], params.scale, params.board_ref, params.terrain_ref
        ), "la mutation n'atteint pas le payload croise : ce test ne mesure plus rien"
        assert "_croise" not in rcs.build_scenario_payload(
            units[0], units[0], params.scale, params.board_ref, params.terrain_ref
        ), "la mutation atteint la diagonale : elle ne discrimine plus le repli partiel"
        after_cross = key()
    finally:
        rcs.build_scenario_payload = real_payload

    assert after_cross != before, (
        "`_run_key` ne hache pas TOUS les matchups : un changement qui n'affecte que les couples "
        "croises reecrit presque tous les scenarios sans deplacer la cle, donc `generate` rend le "
        "jeu PERIME. Replier sur l'enumeration complete, pas sur un temoin ni sur la diagonale."
    )

    # Contre-epreuve integree : la cle doit rester STABLE a payload inchange, sinon elle
    # regenererait 2401 fichiers a chaque appel et ne serait plus un cache du tout.
    assert key() == before, "`_run_key` n'est pas deterministe"


# ─────────────────────────────────────────────────────────────────────────────
# Le trou que ces deux verrous ne couvraient pas : les scenarios A ROSTERS
# ─────────────────────────────────────────────────────────────────────────────

def test_un_scenario_a_rosters_astartes_sans_la_cle_leve_AU_CHARGEMENT() -> None:
    """Les deux donnees n'ont pas la meme source, et c'est la faille.

    `army_faction` vient du ROSTER tire (un scenario `training_random` en change a chaque
    episode) ; `uses_codex_detachment` ne vient QUE du scenario. Les rosters de
    `config/agents/**` declarent tous leur faction sans porter la clause : un scenario a rosters
    qui l'oublierait n'etait trahi qu'au PREMIER APPEL — depuis le 2026-08-06, la construction de
    l'observation, donc apres le demarrage du run.

    Le controle de chargement nomme le fichier fautif, seule information qui permette de corriger.
    """
    from engine.game_state import _require_codex_detachment_when_astartes

    with pytest.raises(KeyError, match="uses_codex_detachment"):
        _require_codex_detachment_when_astartes(
            {"1": "ADEPTUS ASTARTES", "2": "ORKS"}, None, "scenario_demo.json",
            roster_sourced=True,
        )


def test_le_controle_de_chargement_ne_gene_aucune_partie_sans_astartes() -> None:
    """DISCRIMINATION : sans armee ADEPTUS ASTARTES, l'absence de la cle est LEGITIME.

    Sans ce cas, le controle precedent serait satisfait par une exigence posee sur tout le monde
    — ce qui bloquerait les scenarios ORKS/TYRANIDS qui n'ont aucune raison de la porter.
    """
    from engine.game_state import _require_codex_detachment_when_astartes

    _require_codex_detachment_when_astartes(
        {"1": "ORKS", "2": "TYRANIDS"}, None, "scenario_demo.json", roster_sourced=False,
    )
    # Et une armee ASTARTES QUI declare la cle passe, evidemment.
    _require_codex_detachment_when_astartes(
        {"1": "ADEPTUS ASTARTES", "2": "ORKS"}, {"1": True, "2": True}, "scenario_demo.json",
        roster_sourced=False,
    )
