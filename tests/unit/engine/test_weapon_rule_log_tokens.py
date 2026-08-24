"""Tokens `[REGLE]` des regles d armes dans le Game Log PvP — chemin VIF, tir et melee.

Avant ce chantier, seuls [HEAVY] 24.16 et le couvert 13.08 etaient nommes dans la ligne de
tir : [MELTA], [BLAST], [RAPID FIRE], [ANTI-X], [TORRENT], [SUSTAINED HITS], [LETHAL HITS],
[TWIN-LINKED] et [DEVASTATING WOUNDS] agissaient sans laisser la moindre trace lisible. Le
joueur voyait un nombre de des ou un seuil changer sans cause affichee, et une sauvegarde
disparaitre purement et simplement sur une blessure DEVASTATING.

Ce que ces tests verrouillent, et qui est la vraie exigence :
  - le token n apparait que si la regle a REELLEMENT joue sur ce groupe (une arme [MELTA] hors
    demi-portee, une [BLAST] sur une cible de 4 figurines, une [ANTI-INFANTRY] sur un vehicule
    n affichent rien) — sans cette discrimination, le token dirait « declaree », pas « appliquee » ;
  - chaque token est accole au SEGMENT qu il modifie (des sur `Shots:`, seuil de touche sur
    `Hit:`, seuil de blessure sur `Wound:`, sauvegarde sur `Save:`, degats sur `HP lost:`) ;
  - les drapeaux par tir ([TORRENT], [SUSTAINED HITS], [LETHAL HITS], [DEVASTATING WOUNDS])
    arrivent bien dans `shootDetails`, ou le navigateur les rend.

Tout passe par `build_manual_shoot_allocation` / `build_manual_fight_allocation`, c est-a-dire
le chemin de production : un token construit mais jamais atteint par la vraie resolution
n afficherait rien.
"""
import random

import pytest

from engine.phase_handlers import shared_utils, shooting_handlers
from engine.phase_handlers.attack_sequence import ANTI_RULE_IDS
from engine.phase_handlers.fight_handlers import build_manual_fight_allocation
from engine.phase_handlers.shared_utils import build_manual_shoot_allocation
from tests._state_invariants import turn_state_invariants
from tests.unit.engine._state_builders import units_cache_entry as _uc


def _seq(monkeypatch, rolls):
    """RNG deterministe + LoS/couvert neutralises (le couvert a son propre test).

    Retourne `seq` pour que l appelant puisse verifier l epuisement complet apres resolution
    (assert not seq), ce qui detecte tout codepath qui sauterait silencieusement un jet."""
    seq = list(rolls)

    def fake(a, b):
        assert seq, "sequence RNG epuisee"
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})
    monkeypatch.setattr(
        shooting_handlers, "_ranged_distance_metric", lambda *args, **kwargs: "euclidean"
    )
    return seq



def _game_state(
    weapon_rules,
    *,
    target_row=1,
    target_keywords=("INFANTRY",),
    melee=False,
    declared_target_size=1,
    carriers=1,
    split_first_carrier=False,
    target_is_character=False,
    target_save=7,
    attacker_is_vehicle=False,
):
    """Escouade attaquante '1' en (0,0) — arme RNG 24 (demi-portee 12), ATK 3, DMG 1. Cible '2'
    HP 12, sans sauvegarde (Sv 7) pour que la resolution aille toujours au bout.

    `carriers` : nombre de figurines portant LA MEME arme. Elles tombent donc dans le meme
    groupe (04.03), ce qui est la seule facon d observer ce qui est agrege par groupe et ce qui
    ne l est pas.
    `split_first_carrier` : la 1re figurine repartit ses attaques sur une SECONDE cible ('3').
    Elle perd alors la clause « une seule cible » de [CLEAVE] 24.06, la 2e la garde.
    """
    weapon = {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
              "WEAPON_RULES": list(weapon_rules), "code": "test_weapon", "display_name": "Test Weapon"}
    weapons_key = "CC_WEAPONS" if melee else "RNG_WEAPONS"
    models_cache = {}
    intents = []
    for index in range(carriers):
        mid = f"A{index + 1}"
        attacker = {"id": mid, "squad_id": "1", "player": 0, "T": 4, "SHOOT_LEFT": 1,
                    "ATTACK_LEFT": 1, "col": 0, "row": 0,
                    # 10.06 volet MONSTER/VEHICLE : le test se lit sur les keywords PROPRES de
                    # la figurine (`_model_is_monster_or_vehicle`), pas sur l'union 19.03.
                    "UNIT_KEYWORDS": ["VEHICLE"] if attacker_is_vehicle else [],
                    "RNG_WEAPONS": [], "CC_WEAPONS": []}
        attacker[weapons_key] = [weapon]
        models_cache[mid] = attacker
        intents.append({"model_id": mid, "target_unit_id": "2", "weapon_index": 0,
                        "n_attacks_resolved": 1,
                        "target_squad_size_at_declaration": declared_target_size})
        # La PREMIERE figurine est celle qui repartit : le groupe est ainsi cree a partir d un
        # intent SANS des additionnels, ce qui rend le test sensible a l ordre de declaration
        # (c est exactement ce que la copie du premier intent laissait passer).
        if split_first_carrier and index == 0:
            intents.append({"model_id": mid, "target_unit_id": "3", "weapon_index": 0,
                            "n_attacks_resolved": 1,
                            "target_squad_size_at_declaration": declared_target_size})

    def _target_model(mid, sid, row):
        # `role="leader"` = CHARACTER au sens de l allocation (`_is_character_role`), donc un
        # groupe d allocation que [PRECISION] 24.28 peut imposer.
        return {"id": mid, "squad_id": sid, "player": 1, "T": 4, "HP_CUR": 12, "HP_MAX": 12,
                "ARMOR_SAVE": target_save, "INVUL_SAVE": 7,
                "role": "leader" if target_is_character else None, "unitType": "Grunt",
                "points_per_hp": 5.0, "VALUE": 10.0, "col": 0, "row": row,
                "RNG_WEAPONS": [], "CC_WEAPONS": []}

    models_cache["T1"] = _target_model("T1", "2", target_row)
    squad_models = {"1": [mid for mid in models_cache if mid.startswith("A")], "2": ["T1"]}
    units_cache = {"1": _uc(0, 0, player=0), "2": _uc(0, target_row, player=1)}
    units = [{"id": "1", "player": 0}, {"id": "2", "player": 1}]
    unit_by_id = {
        # `player` est exige par le decideur d allocation du combat
        # (`_is_ai_controlled_fight_unit`) : sans lui, le chemin melee leve avant tout log.
        "1": {"id": "1", "UNIT_RULES": [], "player": 0},
        "2": {"id": "2", "UNIT_RULES": [], "player": 1, "unit_keywords": list(target_keywords)},
    }
    squad_cache = {"1": {"model_count_at_start": carriers}, "2": {"model_count_at_start": 1}}
    if split_first_carrier:
        models_cache["T2"] = _target_model("T2", "3", target_row)
        squad_models["3"] = ["T2"]
        units_cache["3"] = _uc(1, target_row, player=1)
        units.append({"id": "3", "player": 1})
        unit_by_id["3"] = {"id": "3", "UNIT_RULES": [], "player": 1,
                           "unit_keywords": list(target_keywords)}
        squad_cache["3"] = {"model_count_at_start": 1}
    intents_key = "pending_squad_fight_intents" if melee else "pending_squad_shoot_intents"
    return {**turn_state_invariants(),
        "gym_training_mode": True,
        "turn": 1, "phase": "fight" if melee else "shoot",
        "action_logs": [], "action_log_seq": 0,
        "models_cache": models_cache,
        "squad_models": squad_models,
        "squad_cache": squad_cache,
        "units_cache": units_cache,
        "units": units,
        "unit_by_id": unit_by_id,
        "objectives": [], "units_moved": set(), "units_advanced": set(),
        intents_key: {"1": intents},
    }


def _resolve(monkeypatch, weapon_rules, *, rolls, melee=False, **state_kwargs):
    """Resout une activation et rend (message du log, records par tir)."""
    seq = _seq(monkeypatch, rolls)
    gs = _game_state(weapon_rules, melee=melee, **state_kwargs)
    if melee:
        build_manual_fight_allocation(gs, "1")
    else:
        build_manual_shoot_allocation(gs, "1")
    assert not seq, f"sequence RNG non epuisee : {seq} — un jet a ete saute"
    logs = [entry for entry in gs["action_logs"] if "shootDetails" in entry]
    assert len(logs) == 1, f"attendu 1 log d attaque, obtenu {len(logs)}"
    return logs[0]["message"], logs[0]["shootDetails"]


# --------------------------------------------------------------------------------------
# Regles appliquees conditionnellement : le token suit l APPLICATION, pas la declaration
# --------------------------------------------------------------------------------------

def test_melta_dans_demi_portee_nomme_le_bonus_de_degats(monkeypatch):
    msg, _ = _resolve(monkeypatch, ["MELTA:2"], rolls=[4, 5, 1], target_row=1)
    assert "[MELTA:2]" in msg
    # Segment des degats : le bonus porte sur la caracteristique D, pas sur un seuil.
    assert msg.index("[MELTA:2]") > msg.index("HP lost:")


def test_melta_hors_demi_portee_ne_dit_rien(monkeypatch):
    """Contre-epreuve : l arme DECLARE [MELTA] mais la regle n a pas joue."""
    msg, _ = _resolve(monkeypatch, ["MELTA:2"], rolls=[4, 5, 1], target_row=100)
    assert "MELTA" not in msg


def test_rapid_fire_dans_demi_portee_est_nomme_sur_les_des(monkeypatch):
    msg, _ = _resolve(monkeypatch, ["RAPID_FIRE:1"], rolls=[4, 5, 1, 4, 5, 1], target_row=1)
    assert "[RAPID FIRE:1]" in msg
    assert msg.index("[RAPID FIRE:1]") < msg.index("Hit:")


def test_rapid_fire_affiche_le_X_declare_pas_les_des_ajoutes(monkeypatch):
    """[RAPID FIRE] porte le X de la DATASHEET, quel que soit le nombre de porteuses.

    Deux porteuses de [RAPID FIRE:1] a demi-portee ajoutent bien 2 des (`Shots:4`), mais le
    token dit `1` — la valeur que le joueur lit sur son profil d arme. Regle UNIFORME depuis le
    2026-08-10 : [BLAST] et [CLEAVE] suivent la meme (cf. leurs jumeaux ci-dessous).

    Verrou de non-regression : `2` etait l ancienne valeur, elle ne doit plus apparaitre.
    """
    msg, _ = _resolve(
        monkeypatch, ["RAPID_FIRE:1"], rolls=[4, 5, 1] * 4, target_row=1, carriers=2
    )
    assert "Shots:4" in msg, msg
    assert "[RAPID FIRE:1]" in msg, msg
    assert "[RAPID FIRE:2]" not in msg, msg


def test_rapid_fire_porte_un_X_superieur_a_un(monkeypatch):
    """Discrimination : le token suit le PARAMETRE, il ne dit pas `1` par accident.

    Une seule porteuse de [RAPID FIRE:2] ajoute 2 des — meme total que le cas precedent, mais
    un token different. Sans ce cas, un token cable en dur sur `1` passerait le test ci-dessus.
    """
    msg, _ = _resolve(
        monkeypatch, ["RAPID_FIRE:2"], rolls=[4, 5, 1] * 3, target_row=1
    )
    assert "[RAPID FIRE:2]" in msg, msg


def test_rapid_fire_hors_demi_portee_ne_dit_rien(monkeypatch):
    msg, _ = _resolve(monkeypatch, ["RAPID_FIRE:1"], rolls=[4, 5, 1], target_row=100)
    assert "RAPID FIRE" not in msg


def test_blast_nu_affiche_le_defaut_de_la_regle(monkeypatch):
    """[BLAST] 24.05 sous sa forme NUE vaut « 1 de par tranche de 5 » : le token dit donc `1`.

    Ce `1` est le PARAMETRE par defaut de la regle (valeur metier du PDF), pas un compte de des
    — le test suivant le prouve en changeant le nombre de porteuses sans changer le token.
    """
    msg, _ = _resolve(
        monkeypatch, ["BLAST"], rolls=[4, 5, 1, 4, 5, 1], declared_target_size=5
    )
    assert "[BLAST:1]" in msg


def test_blast_parametre_affiche_son_X(monkeypatch):
    """Discrimination : la forme [BLAST 2] dit `2`, le token suit bien le parametre declare."""
    msg, _ = _resolve(
        monkeypatch, ["BLAST:2"], rolls=[4, 5, 1] * 3, declared_target_size=5
    )
    assert "[BLAST:2]" in msg, msg


def test_blast_sous_cinq_figurines_ne_dit_rien(monkeypatch):
    msg, _ = _resolve(monkeypatch, ["BLAST"], rolls=[4, 5, 1], declared_target_size=4)
    assert "BLAST" not in msg


def test_blast_ne_compte_pas_les_porteuses(monkeypatch):
    """JUMEAU du cas [RAPID FIRE] : le token ne bouge pas quand le nombre de porteuses change.

    Deux porteuses, cible declaree a 5 -> 1 de chacune, donc `Shots:4`. Le token reste `[BLAST:1]`,
    le parametre de la regle. `2` etait l ancienne valeur (le cumul des des ajoutes), elle ne doit
    plus apparaitre : c est ce qui rendait le log incoherent avec la datasheet."""
    msg, _ = _resolve(
        monkeypatch, ["BLAST"], rolls=[4, 5, 1] * 4, declared_target_size=5, carriers=2
    )
    assert "Shots:4" in msg, msg
    assert "[BLAST:1]" in msg, msg
    assert "[BLAST:2]" not in msg, msg


def test_anti_nomme_le_keyword_qui_s_applique(monkeypatch):
    msg, _ = _resolve(
        monkeypatch, ["ANTI_INFANTRY:4"], rolls=[4, 5, 1], target_keywords=("INFANTRY",)
    )
    assert "[ANTI-INFANTRY:4+]" in msg
    assert msg.index("[ANTI-INFANTRY:4+]") > msg.index("Wound:")


def test_anti_ecrit_le_seuil_declare_et_non_le_clamp_du_moteur(monkeypatch):
    """MEME grammaire que [RAPID FIRE:X] / [BLAST:X] : le `n` de `[REGLE:n]` est TOUJOURS le
    parametre que l ARME DECLARE, jamais ce que le moteur en a tire.

    Le token affichait `crit_wound_on`, c est-a-dire le seuil DEJA borne a 6 par 05.02 — la
    seule exception a la regle enoncee par le docstring du socle, et elle n y etait pas listee.
    Un `7+` declare ressortait en `6+`, si bien que le log confirmait le moteur avec le chiffre
    du moteur au lieu de se recouper avec la datasheet. `7+` est une armurerie fautive, et c est
    le point : c est le seul cas ou les deux valeurs se separent, donc le seul qui DISCRIMINE.

    Meme grammaire des deux cotes : `step.log` porte le meme seuil declare
    (`tests/unit/ai/test_step_log_weapon_rule_tokens.py`), pour qu une regle ne puisse pas etre
    nommee d une facon d un cote et d une autre en face.
    """
    msg, _ = _resolve(
        monkeypatch, ["ANTI_INFANTRY:7"], rolls=[4, 5, 1], target_keywords=("INFANTRY",)
    )
    assert "[ANTI-INFANTRY:7+]" in msg, msg
    assert "[ANTI-INFANTRY:6+]" not in msg, msg


def test_anti_sur_cible_sans_le_keyword_ne_dit_rien(monkeypatch):
    """24.03 : la regle est indexee sur les keywords de la CIBLE — sur un vehicule,
    [ANTI-INFANTRY] n abaisse aucun seuil, donc ne s affiche pas."""
    msg, _ = _resolve(
        monkeypatch, ["ANTI_INFANTRY:4"], rolls=[4, 5, 1], target_keywords=("VEHICLE",)
    )
    assert "ANTI" not in msg


# --------------------------------------------------------------------------------------
# Regles de la boucle touche/blessure : token de groupe + drapeau par tir
# --------------------------------------------------------------------------------------

def test_torrent_ligne_et_detail(monkeypatch):
    """[TORRENT] 24.37 : aucun de de touche n est jete — la premiere valeur du RNG est donc
    deja le jet de BLESSURE."""
    msg, shots = _resolve(monkeypatch, ["TORRENT"], rolls=[5, 1])
    assert "[TORRENT]" in msg
    assert msg.index("[TORRENT]") > msg.index("Hit:")
    assert shots[0]["autoHit"] is True
    assert shots[0]["attackRoll"] is None


def test_sustained_hits_ligne_et_touche_additionnelle(monkeypatch):
    """Touche critique (6) -> 2 touches additionnelles, sans jet de touche."""
    msg, shots = _resolve(
        monkeypatch, ["SUSTAINED_HITS:2"], rolls=[6, 5, 1, 5, 1, 5, 1]
    )
    assert "[SUSTAINED HITS:2]" in msg
    assert shots[0]["criticalHit"] is True
    assert [s.get("sustainedHit") for s in shots] == [None, True, True]


def test_lethal_hits_ligne_et_detail(monkeypatch):
    """[LETHAL HITS] 24.23 sur touche critique : blessure automatique, aucun de de blessure."""
    msg, shots = _resolve(monkeypatch, ["LETHAL_HITS"], rolls=[6, 1])
    assert "[LETHAL HITS]" in msg
    assert shots[0]["lethalHit"] is True
    assert shots[0]["strengthRoll"] is None


def test_lethal_hits_decline_par_le_moteur_ne_dit_rien(monkeypatch):
    """24.23 dit « you CAN choose » : le moteur tranche par esperance de degats et DECLINE
    l auto-blessure quand elle est perdante — ici [LETHAL HITS] + [DEVASTATING WOUNDS] contre
    une sauvegarde 2+, ou l auto-blessure interdirait la blessure critique (donc les mortelles)
    pour un gain nul. La regle ne joue sur AUCUNE attaque du groupe : la ligne ne doit pas la
    nommer, sans quoi elle annonce un effet qu aucun detail par tir ne confirme jamais.

    Le choix ne depend que du profil et des deux seuils, tous constants sur le groupe : il est
    donc le meme pour toutes les attaques, et decidable a l affichage."""
    msg, shots = _resolve(
        monkeypatch, ["LETHAL_HITS", "DEVASTATING_WOUNDS"], rolls=[6, 5, 2], target_save=2
    )
    assert "LETHAL HITS" not in msg, msg
    # Contre-preuve par la resolution elle-meme : la touche critique (6) n a PAS produit
    # d auto-blessure, un de de blessure a bien ete jete.
    assert shots[0]["criticalHit"] is True
    assert shots[0].get("lethalHit") is None
    assert shots[0]["strengthRoll"] == 5
    # La blessure est NORMALE (5 ne franchit pas le seuil critique de blessure) : DEVASTATING
    # ne s applique pas, la sauvegarde est jetee et le resultat est presente.
    assert "[DEVASTATING WOUNDS]" not in msg, msg
    assert "saveRoll" in shots[0], "sauvegarde attendue car blessure non critique"


def test_devastating_wounds_ligne_detail_et_absence_de_sauvegarde(monkeypatch):
    """24.10 : blessure critique -> mortelle, AUCUNE sauvegarde n est jetee (donc pas de
    `saveRoll` au record : c est ce qui rendait la ligne muette cote navigateur)."""
    msg, shots = _resolve(monkeypatch, ["DEVASTATING_WOUNDS"], rolls=[4, 6])
    assert "[DEVASTATING WOUNDS]" in msg
    assert msg.index("[DEVASTATING WOUNDS]") > msg.index("Save:")
    assert shots[0]["devastating"] is True
    assert shots[0]["criticalWound"] is True
    assert "saveRoll" not in shots[0]


def test_twin_linked_ligne_et_cause_de_relance(monkeypatch):
    """[TWIN-LINKED] 24.38 : la relance vient de l ARME. Sans `woundRerollRule`, le detail
    affichait « 1->5 » sans dire ce qui l avait ouverte."""
    msg, shots = _resolve(monkeypatch, ["TWIN_LINKED"], rolls=[4, 1, 5, 1])
    assert "[TWIN-LINKED]" in msg
    assert shots[0]["woundRerollRule"] == "TWIN-LINKED"
    assert shots[0]["strengthRollInitial"] == 1


# --------------------------------------------------------------------------------------
# Regles sans effet mesurable a posteriori : token inconditionnel, et c est assume
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "rule,token",
    [("IGNORES_COVER", "[IGNORES COVER]"), ("EXTRA_ATTACKS", "[EXTRA ATTACKS]")],
)
def test_regles_sans_condition_mesurable(monkeypatch, rule, token):
    msg, _ = _resolve(monkeypatch, [rule], rolls=[4, 5, 1])
    assert token in msg


def test_precision_sans_character_visible_ne_dit_rien(monkeypatch):
    """[PRECISION] 24.28 n a qu UN effet : imposer un groupe CHARACTER comme groupe
    d allocation courant. Sans CHARACTER dans la cible, elle n a impose aucun groupe — l arme
    la declare, la regle n a pas joue, la ligne ne doit pas la nommer."""
    msg, _ = _resolve(monkeypatch, ["PRECISION"], rolls=[4, 5, 1])
    assert "PRECISION" not in msg


def test_precision_avec_character_visible_est_nommee(monkeypatch):
    """Contre-epreuve : cible contenant un CHARACTER visible -> l override d allocation joue
    (`_apply_precision_allocation_override`), et c est CE fait, pose sur le groupe, que la
    ligne affiche."""
    seq = _seq(monkeypatch, [4, 5, 1])
    # La VISIBILITE de la figurine CHARACTER passe par la primitive de LoS complete (terrain,
    # obscuring, footprint), qui exige un plateau configure et a ses propres tests. Elle est
    # neutralisee ici comme `compute_unit_los` l est pour tout ce fichier : ce test verrouille
    # le contrat du LOG, pas la LoS. Tout le reste du chemin est reel — le groupe CHARACTER
    # existe, l override s execute et reordonne effectivement l allocation.
    monkeypatch.setattr(
        shared_utils, "_attacker_model_can_reach_squad", lambda *a, **k: True
    )
    gs = _game_state(["PRECISION"], target_is_character=True)

    build_manual_shoot_allocation(gs, "1")

    assert not seq, f"sequence RNG non epuisee : {seq} — un jet a ete saute"
    logs = [e for e in gs["action_logs"] if "shootDetails" in e]
    assert len(logs) == 1, f"attendu 1 log d attaque, obtenu {len(logs)}"
    msg = logs[0]["message"]
    assert "[PRECISION]" in msg, msg


def test_le_malus_10_06_est_nomme_sur_le_seuil_de_touche(monkeypatch):
    """10.06 volet MONSTER/VEHICLE : « subtract 1 from the hit roll ». C'etait le DERNIER
    modificateur du seuil affiche sans cause visible, alors que [HEAVY] et [COVER] avaient la
    leur — le drapeau existait dans le moteur et n etait lu nulle part.

    Ce n est pas une regle d ARME (aucune entree dans weapon_rules.json) : elle est posee sur le
    segment `Hit:` par l emission, comme [COVER], et non par le socle de regles d armes."""
    # Le TYPE de tir (10.05/10.06) et l engagement se calculent sur la geometrie du plateau et
    # ont leurs propres tests ; ils sont fixes ici comme `compute_unit_los` l est pour tout ce
    # fichier. La DECISION du malus (« sauf arme CLOSE-QUARTERS ET cible engagee »), le drapeau
    # et sa remontee jusqu au log restent le code reel.
    monkeypatch.setattr(
        shared_utils, "resolve_squad_shooting_type",
        lambda gs, sid: shared_utils.SHOOTING_TYPE_CLOSE_QUARTERS,
    )
    monkeypatch.setattr(shared_utils, "_squads_are_engaged", lambda gs, a, b: False)
    monkeypatch.setattr(shared_utils, "_squad_is_in_enemy_er", lambda gs, sid: False)
    msg, _ = _resolve(
        monkeypatch, ["CLOSE_QUARTERS"], rolls=[4, 5, 1], attacker_is_vehicle=True
    )
    # ATK 3 degrade a 4+ par le malus : le seuil ET sa cause sont lisibles.
    assert "Hit:4+" in msg, msg
    assert "[POINT-BLANK]" in msg, msg


def test_sans_monster_vehicle_aucun_malus_affiche(monkeypatch):
    """Contre-epreuve : meme arme, tireur d infanterie -> le volet MONSTER/VEHICLE de 10.06 ne
    s applique pas, le seuil reste net et rien ne s affiche."""
    monkeypatch.setattr(shared_utils, "_squad_is_in_enemy_er", lambda gs, sid: False)
    msg, _ = _resolve(monkeypatch, ["CLOSE_QUARTERS"], rolls=[4, 5, 1])
    assert "Hit:3+" in msg, msg
    assert "POINT-BLANK" not in msg, msg


def test_psychic_sans_couvert_ne_dit_rien(monkeypatch):
    """[PSYCHIC] 24.29 ne neutralise que des MODIFICATEURS : sans couvert, elle n a rien
    neutralise. Le couvert est force a False par le harnais."""
    msg, _ = _resolve(monkeypatch, ["PSYCHIC"], rolls=[4, 5, 1])
    assert "PSYCHIC" not in msg


# --------------------------------------------------------------------------------------
# JUMEAU melee : le socle est partage, une regle nommee au tir doit l etre en melee
# --------------------------------------------------------------------------------------

def test_melee_nomme_les_memes_regles(monkeypatch):
    """Deux attaquants du meme groupe (carriers=2) : l un declenche LETHAL HITS (touche critique),
    l autre DEVASTATING WOUNDS (blessure critique sur une touche normale). Les deux tokens
    apparaissent dans la meme ligne de synthese — c est la propriete qu on verrouille ici (le
    chemin melee passe bien par le meme socle que le tir). Avec LETHAL HITS + DEVASTATING sur
    Sv 7+, le moteur ACCEPTE l auto-blessure (EV_auto=1.0 > EV_roll=0.5), donc un hit critique
    prend le chemin lethal-hit (is_critical_wound=False, devastating ne s applique pas) : les
    deux effets ne peuvent pas coexister sur UNE seule attaque."""
    # A1 : hit=6 (critique) -> LETHAL HITS -> auto-blessure -> save=1 (7+ -> echoue) -> degat
    # A2 : hit=4 (normale) -> jet blessure=6 (critique) -> DEVASTATING -> pas de save
    msg, shots = _resolve(
        monkeypatch, ["DEVASTATING_WOUNDS", "LETHAL_HITS"], rolls=[6, 1, 4, 6],
        melee=True, carriers=2,
    )
    assert "[DEVASTATING WOUNDS]" in msg
    assert "[LETHAL HITS]" in msg
    assert any(s.get("lethalHit") for s in shots)


def test_melee_cleave_affiche_son_X_declare(monkeypatch):
    """[CLEAVE] 24.06 est le jumeau melee de [BLAST] : meme comptage par tranche de 5, et meme
    token — le X que l arme declare."""
    msg, _ = _resolve(
        monkeypatch, ["CLEAVE:2"], rolls=[4, 5, 1, 4, 5, 1, 4, 5, 1],
        melee=True, declared_target_size=5,
    )
    assert "[CLEAVE:2]" in msg


def test_melee_cleave_separe_les_figurines_qui_y_ont_droit(monkeypatch):
    """04.03 IDENTICAL ATTACKS : [CLEAVE] qui joue pour une figurine et pas l autre SEPARE les
    lots. Les deux porteuses portent la MEME arme, mais 24.06 accorde ses des « if you only
    selected one target for ALL of that weapon's attacks » — la premiere repartit ses attaques
    sur '2' et '3' (pas de [CLEAVE]), la seconde ne vise que '2' (elle l a). Leurs attaques ne
    sont donc pas « affected by the same applicable abilities and rules » : les reunir dans un
    gather unique serait une faute de regle, et le `Shots:12` d un lot melange ne dirait a
    personne laquelle des deux a beneficie de quoi.

    Deux lots attendus sur la cible '2' :
      - 1 attaque, aucun token (la porteuse qui a reparti) ;
      - 1 attaque + 1 de [CLEAVE] (5 figurines declarees -> une tranche), token `[CLEAVE:1]`.

    JUMEAU du X applique de [RAPID FIRE], deja dans `gkey` pour exactement la meme raison
    (24.30, « within half range »). C est la symetrie que ce test verrouille : les deux seules
    regles additives dont l application depend de la FIGURINE separent les lots."""
    _seq(monkeypatch, [4, 5, 1] * 4)
    gs = _game_state(
        ["CLEAVE:1"], melee=True, declared_target_size=5, carriers=2,
        split_first_carrier=True,
    )

    build_manual_fight_allocation(gs, "1")

    logs = [e for e in gs["action_logs"] if "shootDetails" in e and e["targetId"] == "2"]
    assert len(logs) == 2, [e["message"] for e in gs["action_logs"]]
    messages = [e["message"] for e in logs]

    avec = [m for m in messages if "[CLEAVE:1]" in m]
    sans = [m for m in messages if "CLEAVE" not in m]
    assert len(avec) == 1 and len(sans) == 1, messages
    # La porteuse mono-cible : son attaque + le de de [CLEAVE].
    assert "Shots:2" in avec[0], avec[0]
    # Celle qui a reparti ses attaques : la sienne, et rien de plus.
    assert "Shots:1" in sans[0], sans[0]


def test_melee_ne_parle_jamais_de_rapid_fire_ni_de_melta(monkeypatch):
    """Ces deux regles sont indexees sur la demi-portee d une arme de TIR : la melee doit
    rester muette meme si l arme les declarait."""
    msg, _ = _resolve(monkeypatch, ["MELTA:2", "RAPID_FIRE:1"], rolls=[4, 5, 1], melee=True)
    assert "MELTA" not in msg
    assert "RAPID FIRE" not in msg


# --------------------------------------------------------------------------------------
# Contrat avec le registre : chaque libelle emis doit avoir sa bulle d aide
# --------------------------------------------------------------------------------------

def test_chaque_libelle_de_token_existe_dans_le_registre():
    """Le frontend resout la bulle d aide en normalisant le libelle du token contre le `name`
    de `config/weapon_rules.json` (`GameLog.tsx`, `normalizeRuleLookupKey`). Les libelles emis
    par le moteur sont donc un CONTRAT avec ce fichier — contrat qu aucun type ne verifie : un
    `name` renomme dans le JSON, ou un token mal orthographie ici, ferait perdre la bulle
    d aide en silence. Ce test est la seule chose qui le tienne.

    Les tokens PARAMETRES (`[MELTA:2]`) sont ramenes a leur libelle nu, comme le fait le
    repli parametre du frontend ; `[ANTI-<KEYWORD>:Y+]` porte le keyword dans son libelle,
    d ou la reconstruction du nom de regle `ANTI_<KEYWORD>`.
    """
    import json
    import re
    from pathlib import Path

    registry = json.loads(
        (Path(__file__).resolve().parents[3] / "config" / "weapon_rules.json").read_text(
            encoding="utf-8"
        )
    )
    # Meme normalisation que `normalizeRuleLookupKey` cote frontend : majuscules, `_`/`-`/`:`
    # ramenes a l espace. Les deux formes (cle et `name`) sont acceptees, comme la table du front.
    def _normalise(label):
        return re.sub(r"\s+", " ", re.sub(r"[:_-]+", " ", label.strip().upper())).strip()

    known = {_normalise(key) for key in registry}
    known |= {_normalise(entry["name"]) for entry in registry.values()}

    emitted = {
        "RAPID FIRE", "BLAST", "CLEAVE", "EXTRA ATTACKS", "HEAVY", "TORRENT",
        "SUSTAINED HITS", "IGNORES COVER", "PSYCHIC", "LETHAL HITS", "TWIN-LINKED",
        "DEVASTATING WOUNDS", "MELTA", "PRECISION",
    }
    emitted |= {f"ANTI-{rule_id[len('ANTI_'):]}" for rule_id in ANTI_RULE_IDS}

    inconnus = sorted(label for label in emitted if _normalise(label) not in known)
    assert not inconnus, (
        f"Libelles de tokens sans entree dans weapon_rules.json : {inconnus}. "
        f"Le frontend ne pourra pas afficher leur bulle d aide."
    )
