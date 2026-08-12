"""Le journal NOMME la figurine allouée, et l'analyzer la lit au lieu de la deviner.

Régression verrouillée (2026-08-12). Le journal disait qu'une escouade perdait des PV, jamais QUI
les perdait. L'analyzer devinait donc deux fois :

  - QUI ENCAISSE — déduit d'un tri CHARACTER/non-CHARACTER, quand le moteur applique la cascade
    `_select_allocation_model` (blessée d'abord, tier de rôle, proximité d'un ennemi, index).
    Mesuré : 200 PV par socle faux sur 173 129 comparés aux instantanés `T{n} STATE:`.
  - OÙ SONT LES AUTRES — à chaque perte, TOUS les socles de l'escouade étaient oubliés, faute de
    savoir lequel retirer. L'escouade retombait sur son ancre. Mesuré : 2 342 fenêtres, et 229
    lignes de seuil de blessure rendues NON VÉRIFIABLES sur un run de 60 épisodes, faute de
    composition connue (`analyzer_wound.target_bodyguard_toughness`).

⚠️ CE QUE CE CHANTIER NE CORRIGE PAS, et il faut le lire avant d'écrire un test ici. Sur un
journal RÉEL, `[TARGET_MODELS:]` — les survivants, émis par le moteur sur le dernier jet visant
la cible — recale déjà l'état à la FIN de chaque activation. La fenêtre d'ignorance ne s'étend
donc pas au-delà de l'activation qui tue, sauf pour les morts qui n'émettent aucun segment
(blessures mortelles, retrait de cohérence), hors périmètre ici. Un test qui fabrique une fenêtre
inter-activations doit omettre `[TARGET_MODELS:]` d'une ligne de tir — c'est-à-dire construire un
journal qu'aucun moteur ne produit, et prouver une correction qui ne sert jamais.

Les tests ci-dessous se tiennent donc à deux formes RÉELLES :
  1. l'intérieur d'une salve (la fenêtre existe, elle dure jusqu'au dernier jet) ;
  2. l'identité de la figurine touchée, que `[TARGET_MODELS:]` ne donne JAMAIS — il dit qui reste
     debout, pas qui a encaissé, ni avec combien de PV.
"""
from __future__ import annotations

import pytest

# Board x1 (inches_to_subhex=1) : 1 hex = 1 pouce.
TIREUR = (10, 20)
PROCHE = (30, 20)   # 1#0 — 20 hex : DANS les 24" de l'arme
LOIN = (36, 20)     # 1#1 — 26 hex : HORS des 24"
OBJECTIVES = ";".join(f"(60,{r})" for r in range(40, 46))

_ENTETE = f"""=== STEP-BY-STEP ACTION LOG ===
================================================================================

[10:00:00] === EPISODE 1 START ===
[10:00:00] Scenario: scenario_bot-01
[10:00:00] Opponent: SelfplayBot
[10:00:00] Walls:
[10:00:00] Objectives: rect b NW:{OBJECTIVES}
[10:00:00] Board: cols=44 rows=60 inches_to_subhex=1 hex_radius=13.9 margin=5
[10:00:00] Run rules: engagement_zone_subhex=2 engagement_zone_vertical_inches=5.0 metric.engagement=hex metric.ranged=hex move.thru_ez=True move.thru_enemy=False move.thru_friendly=True cohesion.model_subhex=2 cohesion.global_subhex=9 cohesion.min_neighbors=1
"""

_UNITES = f"""[10:00:00] Unit 1 (AssaultIntercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/1
[10:00:00] Unit 102 (SternguardVeteranBoltRifle) P2: Starting position (-1,-1), HP_MAX=2 base=round/1
[10:00:00] === ACTIONS START ===
[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1({PROCHE[0]},{PROCHE[1]}) DEPLOYED from (-1,-1) to ({PROCHE[0]},{PROCHE[1]}) [R:+0.0] [MODELS: 1#0@({PROCHE[0]},{PROCHE[1]},z0) 1#1@({LOIN[0]},{LOIN[1]},z0)] [SUCCESS]
[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 102({TIREUR[0]},{TIREUR[1]}) DEPLOYED from (-1,-1) to ({TIREUR[0]},{TIREUR[1]}) [R:+0.0] [MODELS: 102#0@({TIREUR[0]},{TIREUR[1]},z0)] [SUCCESS]
"""


def _jet(seconde: int, *, mid: str | None, degats: int = 2) -> str:
    """Un jet de la salve du tireur 102 sur l'escouade 1. `mid` None = grammaire 1.

    Pas de `[TARGET_MODELS:]` : le moteur ne l'écrit que sur le DERNIER jet visant la cible.
    Ces lignes sont donc des jets INTERMÉDIAIRES, la seule forme où la fenêtre existe.
    """
    token = f" [ALLOC_MODEL: {mid}]" if mid else ""
    return (
        f"[10:00:{seconde:02d}] E1 T1 P2 SHOOT : Unit 102({TIREUR[0]},{TIREUR[1]}) "
        f"SHOT Unit 1({PROCHE[0]},{PROCHE[1]}) with [Sternguard Bolt Rifle] "
        f"- Hit 4(3+) - Wound 5(4+) - Save 2(5+) - Dmg:{degats}HP [R:+0.0] "
        f"[MODELS: 102#0@({TIREUR[0]},{TIREUR[1]},z0)] [SHOOTER_MODELS: 102#0]{token} [SUCCESS]\n"
    )


def _analyse(tmp_path, corps: str, *, grammaire: int = 2) -> dict:
    entete = _ENTETE
    if grammaire >= 2:
        entete += f"[10:00:00] Log grammar: {grammaire}\n"
    log = tmp_path / "step.log"
    log.write_text(entete + _UNITES + corps)
    import ai.analyzer as an

    return an.parse_step_log(str(log))


def test_premisse_la_salve_encadre_la_portee_de_l_arme():
    """Sans cet écart, retirer le socle tôt ou tard donnerait le même verdict."""
    from engine.hex_utils import offset_to_cube

    def d(a, b):
        ax, ay, az = offset_to_cube(*a)
        bx, by, bz = offset_to_cube(*b)
        return max(abs(ax - bx), abs(ay - by), abs(az - bz))

    assert d(TIREUR, PROCHE) <= 24, "la figurine visée doit être À PORTÉE"
    assert d(TIREUR, LOIN) > 24, "la survivante doit être HORS portée"


def test_la_portee_n_est_pas_jugee_sur_les_survivants_de_la_meme_salve(tmp_path):
    """VERROU du retrait différé à la FIN DE L'ACTIVATION.

    La cible est choisie une fois, au Select Targets (10.02) : les pertes que la salve inflige ne
    peuvent pas rendre ses derniers jets illégaux. Retirer le socle dès sa mort le fait pourtant,
    et ça s'est produit — mesuré sur le run du 2026-08-12, E44 : un Onslaught Gatling Cannon vise
    une escouade à 22 hex, tue les six figurines les plus proches, et ses trois derniers jets
    ressortent « hors portée », les survivantes étant à 25-27 pour une arme de 24.

    Ce test rejoue cette forme en petit : jet 1 tue la figurine à portée, jet 2 vise la même
    escouade dont il ne reste qu'une figurine hors portée.

    Verrou prouvé : retrait rendu immédiat → ROUGE (1 hors portée) ; différé → vert.
    """
    stats = _analyse(tmp_path, _jet(2, mid="1#0") + _jet(3, mid="1#1"))
    assert stats["shoot_invalid"][2]["out_of_range"] == 0, (
        "les deux jets appartiennent à UNE salve : la cible était à 20 hex quand elle a été "
        "choisie, et la mort de sa figurine avancée ne peut pas rendre le jet suivant illégal"
    )
    assert stats["shoot_invalid"][2]["total"] == 2, (
        "les DEUX jets doivent avoir été mesurés — sans ça l'assertion ci-dessus ne prouve rien"
    )


def test_les_degats_vont_a_la_figurine_nommee(tmp_path):
    """VERROU d'IDENTITÉ — et c'est la seule chose que `[TARGET_MODELS:]` ne dira jamais.

    Deux jets de 1 PV nommant `1#1` la tuent (2 PV). Un troisième jet nommant `1#1` porte alors
    sur une figurine que l'analyzer ne connaît plus : le compteur 2.8 le dit.

    Le discriminant est là : si les dégâts allaient à la figurine déduite (`1#0`, première de
    l'ordre 06.02) au lieu de la nommée, ce serait `1#0` qui serait morte, `1#1` serait vivante,
    et le troisième jet la trouverait — compteur à 0. Le test distingue donc « retirer une
    figurine » de « retirer CELLE-LÀ ».
    """
    corps = _jet(2, mid="1#1", degats=1) + _jet(3, mid="1#1", degats=1) + _jet(4, mid="1#1")
    stats = _analyse(tmp_path, corps)
    assert stats["state_resync"]["alloc_model_unknown"] == 1, (
        "1#1 a encaissé ses 2 PV : elle doit être morte, et le jet suivant qui la nomme doit "
        "tomber sur une figurine inconnue. Un compteur à 0 signifie que les dégâts sont allés "
        "ailleurs — c'est-à-dire que la figurine nommée n'est pas celle qu'on frappe"
    )


def test_une_figurine_allouee_inconnue_ne_tue_personne(tmp_path):
    """Le moteur nomme un socle que l'état reconstruit ignore : divergence, donc section 2.8.

    L'alternative — appliquer les dégâts « à quelqu'un » — est exactement la devinette retirée.
    """
    stats = _analyse(tmp_path, _jet(2, mid="1#7"))
    assert stats["state_resync"]["alloc_model_unknown"] == 1
    assert stats["shoot_invalid"][2]["out_of_range"] == 0, (
        "aucune figurine n'a été retirée : la cible reste mesurée sur ses deux socles"
    )


def test_un_token_exige_et_absent_est_une_erreur_explicite(tmp_path):
    """T1 : sur un journal qui PROMET la donnée, son absence est une panne, jamais un repli.

    C'est ce que la ligne d'entête `Log grammar:` achète — sans elle, l'analyzer devrait retomber
    en silence sur la devinette que ce chantier vient de retirer.
    """
    with pytest.raises(ValueError, match=r"ALLOC_MODEL"):
        _analyse(tmp_path, _jet(2, mid=None), grammaire=2)


def test_un_journal_d_ancienne_grammaire_reste_lisible(tmp_path):
    """L'exigence ne vaut que pour les journaux qui la promettent : les archives se relisent."""
    stats = _analyse(tmp_path, _jet(2, mid=None), grammaire=1)
    assert stats["shoot_invalid"][2]["total"] == 1, "le journal doit avoir été analysé"
    assert stats["state_resync"]["alloc_model_unknown"] == 0
