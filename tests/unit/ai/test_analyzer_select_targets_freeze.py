"""Le gel au Select Targets step doit être COHÉRENT : même instant partout, tout ou rien.

Le gel lui-même est verrouillé ailleurs (`test_analyzer_close_quarters_engagement`,
`test_analyzer_shoot_at_engaged_enemy`, `test_analyzer_fight_alternation_pre_loss`). Ce fichier
verrouille ses DEUX contrats internes, tous deux trouvés en relecture :

1. **Un seul instant.** Une cible sans socles connus est mesurée COMME UN POINT, donc entièrement
   sur son ancre. Si une mesure prend l'ancre gelée et sa jumelle l'ancre de la ligne, les deux
   décrivent deux instants différents dès que le moteur ré-ancre l'escouade sur un survivant.
2. **Tout ou rien.** Rendre l'ancre d'une cible sans lui rendre ses PV la fait ressortir « unité
   sans données » à chaque ligne, une erreur de parsing que les cartes vives ne produisaient pas.
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log

OBJECTIVES = ";".join(f"(60,{r})" for r in range(40, 46))

# Board x1 : 1 hex = 1 pouce, zone d'engagement = 2. Lecture directe des distances.
SHOOTER = (25, 20)      # tireur : engagé avec personne, et à portée de son arme de 24"
BRAWLER = (38, 20)      # allié du tireur, au contact de la cible
M0 = (39, 20)           # cible, figurine d'ancre au départ
M1 = (40, 20)           # devient l'ancre quand M0 tombe — À 2 hex du brawler : ENGAGÉE
M2 = (41, 20)           # devient l'ancre quand M1 tombe — à 3 hex : PLUS engagée

S = f"({SHOOTER[0]},{SHOOTER[1]})"
B = f"({BRAWLER[0]},{BRAWLER[1]})"
A0 = f"({M0[0]},{M0[1]})"

_HEADER = entete_step_log(
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1{S} DEPLOYED from (-1,-1) to {S} [R:+0.0] [MODELS: 1#0@({SHOOTER[0]},{SHOOTER[1]},z0)] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 2{B} DEPLOYED from (-1,-1) to {B} [R:+0.0] [MODELS: 2#0@({BRAWLER[0]},{BRAWLER[1]},z0)] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101{A0} DEPLOYED from (-1,-1) to {A0} [R:+0.0] [MODELS: 101#0@({M0[0]},{M0[1]},z0) 101#1@({M1[0]},{M1[1]},z0) 101#2@({M2[0]},{M2[1]},z0)] [SUCCESS]\n",
    units=(
        "[10:00:00] Unit 1 (SternguardVeteranBoltRifle) P1: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
        "[10:00:00] Unit 2 (AssaultIntercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
        "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
    ),
    inches_to_subhex=1,
    board="cols=60 rows=60",
    hex_radius="13.9",
    margin=5,
    objectives=OBJECTIVES,
    metric_ranged="hex",
)

# La mêlée de l'allié tue une figurine : les socles de la cible sont PURGÉS (le journal ne dit pas
# laquelle tombe) et ne seront réécrits qu'à sa prochaine action. La cible devient donc un POINT
# pour toute mesure ultérieure — c'est la situation où l'ancre décide de tout.
_MELEE_KILL = (
    f"[10:00:02] E1 T1 P1 FIGHT : Unit 2(38,20) FOUGHT Unit 101(39,20) with [Close Combat Weapon]"
    " - Hit 5(3+) - Wound 4(4+) - Save 2(3+) - Dmg:2HP [R:+0.0] [FIGHT_SUBPHASE:fight] [SUCCESS]\n"
)
# Activation de tir du tireur, DEUX lignes. La première tue encore une figurine : le moteur
# ré-ancre l'escouade sur la survivante, et la deuxième ligne porte donc une AUTRE ancre.
_SHOT_1 = (
    f"[10:00:03] E1 T2 P1 SHOOT : Unit 1(25,20) SHOT Unit 101(40,20) with [Sternguard Bolt Rifle]"
    " - Hit 4(5+) - Wound 5(4+) - Save 2(5+) - Dmg:2HP [R:+0.0] [SUCCESS]\n"
)
_SHOT_2 = (
    f"[10:00:03] E1 T2 P1 SHOOT : Unit 1(25,20) SHOT Unit 101(41,20) with [Sternguard Bolt Rifle]"
    " - Hit 4(5+) - Wound 5(4+) - Save 2(5+) - Dmg:1HP [R:+0.0] [SUCCESS]\n"
)
# Cible DÉTRUITE au tour 1, visée de nouveau au tour 2 : le gel n'a ni PV ni socles à rendre.
_KILL_SQUAD = (
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 1(25,20) SHOT Unit 102(50,20) with [Sternguard Bolt Rifle]"
    " - Hit 4(5+) - Wound 5(4+) - Save 2(5+) - Dmg:2HP [R:+0.0] [SUCCESS]\n"
)
_SHOT_AT_DEAD = (
    f"[10:00:03] E1 T2 P1 SHOOT : Unit 1(25,20) SHOT Unit 102(50,20) with [Sternguard Bolt Rifle]"
    " - Hit 4(5+) - Wound 5(4+) - Save 2(5+) - Dmg:1HP [R:+0.0] [SUCCESS]\n"
)
_DEAD_TARGET_HEADER = _HEADER.replace(
    "[10:00:00] === ACTIONS START ===",
    "[10:00:00] Unit 102 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/1\n"
    "[10:00:00] === ACTIONS START ===",
) + "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 102(50,20) DEPLOYED from (-1,-1) to (50,20) [R:+0.0] [MODELS: 102#0@(50,20,z0)] [SUCCESS]\n"


def _stats(tmp_path, log_text: str):
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(log_text)
    return an.parse_step_log(str(log))


def test_geometry_premise():
    """Les trois distances SANS lesquelles les tests ci-dessous ne prouvent rien."""
    from engine.hex_utils import offset_to_cube

    def d(a, b):
        ax, ay, az = offset_to_cube(*a)
        bx, by, bz = offset_to_cube(*b)
        return max(abs(ax - bx), abs(ay - by), abs(az - bz))

    assert d(BRAWLER, M1) <= 2, "l'ancre GELÉE doit être engagée avec l'allié du tireur"
    assert d(BRAWLER, M2) > 2, "l'ancre de la ligne suivante ne doit PLUS l'être"
    assert d(SHOOTER, M1) > 2, "le tireur ne doit pas être engagé : sinon c'est 10.06 qui parle"
    assert d(SHOOTER, M2) <= 24, "les deux tirs doivent rester à portée de l'arme"


def test_les_deux_lignes_d_une_activation_jugent_la_meme_ancre(tmp_path):
    """Contrat n°1 — un seul instant.

    Socles purgés par la mêlée : la cible est un POINT, son ancre décide seule. La première ligne
    de l'activation la tue encore une fois et le moteur ré-ancre sur la survivante, hors de
    l'engagement. Si la mesure 04.02 lit l'ancre de la LIGNE, la deuxième attaque de l'activation
    juge un état que le moteur n'a jamais eu à décider : la faute disparaît en cours d'activation.
    """
    stats = _stats(tmp_path, _HEADER + _MELEE_KILL + _SHOT_1 + _SHOT_2)
    assert stats["shoot_at_engaged_enemy"][1] == 2


def test_une_cible_deja_detruite_ne_produit_aucune_erreur_de_parsing(tmp_path):
    """Contrat n°2 — tout ou rien.

    Tirer sur une escouade que l'analyzer a déjà retirée est un cas RÉEL (il a son propre contrôle,
    `shoot_at_dead_unit`). Le gel ne doit pas lui rendre son ancre sans ses PV : elle ressortirait
    « unité sans données » à chaque ligne, une erreur de parsing inventée par le gel lui-même.
    """
    stats = _stats(tmp_path, _DEAD_TARGET_HEADER + _KILL_SQUAD + _SHOT_AT_DEAD)
    assert stats["shoot_at_dead_unit"][1] == 1, "prémisse : le tir sur cadavre doit être vu"
    fautifs = [e for e in stats["parse_errors"] if "102" in e["error"]]
    assert fautifs == [], f"erreurs de parsing inventées par le gel : {fautifs}"
