"""Le socle et le mur se mesurent avec UNE géométrie : l'hexagone, jamais son centre.

Défaut corrigé (2026-08-11). Le PLACEMENT (pool de déploiement, filtre de destination du move,
voile rouge, commit) mesurait un hex de mur par son CENTRE — c'est l'empreinte hex,
``_footprint_round`` retenant les cases dont le centre est dans le disque. La TRAVERSÉE
(``geodesic_field`` → ``_segment_hits_hex``) mesure le même mur comme un HEXAGONE, donc à
``circumradius`` près. Les deux critères divergent exactement sur la bande
``r < d <= r + circumradius`` : une figurine posée là est légale au placement et n'a AUCUN premier
pas possible dans les six directions, parce que tout segment partant de son ancre passe dans la
clairance du mur. Mesuré sur ``terrain-mc1`` (socle 8 sous-hex à ×5, rayon 6,0) : 664 ancres
légales au pool de mouvement VIDE, dont 198 dans les zones de déploiement.

Second volet (pièce B) : un obstacle MOBILE ne peut pas, lui, être interdit par le placement — le
contact socle à socle avec un ennemi est l'issue normale d'une charge. ``geodesic_field`` reçoit
donc ces obstacles séparément : ils gardent leurs cases bloquantes (règle 09.07 — seul Desperate
Escape traverse les figurines ennemies) mais ne dilatent plus. Sans ça, une unité au contact ne
peut pas faire son Fall Back du tout.

VERROU : chaque test ci-dessous a été vu ROUGE en remettant l'ancien critère (cf. docstring de
chaque test pour la mutation exacte).
"""

import pathlib
from typing import Set, Tuple

import pytest

from engine.hex_utils import (
    _hex_center,
    geodesic_field,
    obstacles_touching_disc,
    precompute_footprint_offsets,
    round_base_radius_norm,
    socle_blocked_anchor_cells,
)

BOARD_COLS, BOARD_ROWS = 60, 60
BASE = 8  # Terminator : BASE_SIZE 16 (unités ×10) → 8 sous-hex à inches_to_subhex = 5
RADIUS = round_base_radius_norm(BASE)  # 6.0


def _footprint(col: int, row: int) -> Set[Tuple[int, int]]:
    """Empreinte hex du socle — l'ANCIEN critère de placement (mur mesuré comme un point)."""
    off_even, off_odd = precompute_footprint_offsets("round", BASE, 0)
    offs = off_even if (col & 1) == 0 else off_odd
    return {(col + dc, row + dr) for dc, dr in offs}


def _wall_column(col: int) -> Set[Tuple[int, int]]:
    return {(col, r) for r in range(0, BOARD_ROWS)}


def _wall_diagonal() -> Set[Tuple[int, int]]:
    """Mur OBLIQUE — la géométrie où le défaut vit réellement.

    Mesuré : un mur en colonne droite ne produit AUCUN désaccord (les pas de colonne valent 1,5
    unité-norme, la bande ``]6,0 ; 7,0]`` tombe alors entre deux colonnes et reste vide). Sur une
    diagonale, 40 ancres du plateau d'essai sont légales au critère d'empreinte et immobiles ;
    sur un coin, 25. Les ruines de ``terrain-mc1`` sont obliques, d'où les 664 de la vraie carte.
    Un fixture axé aurait donc affiché un test vert sans rien regarder.
    """
    return {(20 + k, 10 + k) for k in range(40)}


def _can_take_a_step(anchor: Tuple[int, int], obstacles: Set[Tuple[int, int]]) -> bool:
    """Le socle peut-il quitter ``anchor`` ? Budget d'un pas : seul le premier saut est en jeu."""
    obs = set(obstacles)
    obs.discard(anchor)
    return len(geodesic_field(anchor, BOARD_COLS, BOARD_ROWS, obs, 2.0, RADIUS)) > 1


class TestBandeDeDesaccord:
    """La bande ``r < d <= r + circumradius`` — le cœur du défaut."""

    def test_ancre_de_la_bande_est_desormais_interdite(self):
        """VERROU : remettre ``_footprint(*anchor) & walls`` comme critère rend ce test ROUGE
        (l'empreinte n'y touche aucun mur, donc l'ancien critère l'acceptait)."""
        walls = _wall_diagonal()
        pieges = [
            (c, r)
            for c in range(6, BOARD_COLS - 6)
            for r in range(6, BOARD_ROWS - 6)
            if not (_footprint(c, r) & walls) and not _can_take_a_step((c, r), walls)
        ]
        # Le fixture DOIT produire le défaut, sinon le test ne regarde rien.
        assert pieges, "aucune ancre piège : le fixture ne reproduit pas le défaut"
        blocked = socle_blocked_anchor_cells(walls, "round", BASE, 0, BOARD_COLS, BOARD_ROWS)
        restantes = [a for a in pieges if a not in blocked]
        assert restantes == [], f"ancres pièges encore licites : {restantes}"

    def test_toute_ancre_permise_peut_faire_un_premier_pas(self):
        """L'invariant que la primitive rétablit, et que ``geodesic_field`` suppose déjà : toute
        ancre licite laisse au moins une direction de fuite.

        VERROU : remplacer ``socle_blocked_anchor_cells`` par ``set(walls)`` rend ce test ROUGE.
        """
        walls = _wall_diagonal()
        blocked = socle_blocked_anchor_cells(walls, "round", BASE, 0, BOARD_COLS, BOARD_ROWS)
        testees = [
            (c, r)
            for c in range(6, BOARD_COLS - 6)
            for r in range(6, BOARD_ROWS - 6)
            if (c, r) not in blocked
        ]
        assert len(testees) > 500, "l'échantillon doit être peuplé (pas de vert vacant)"
        immobiles = [a for a in testees if not _can_take_a_step(a, walls)]
        assert immobiles == [], f"ancres licites mais immobiles : {immobiles[:5]}"

    def test_le_critere_ne_retire_que_la_bande(self):
        """Une ancre à plus de ``r + circumradius`` du mur reste licite — le correctif ne mange
        pas le plateau. VERROU : dilater d'un hex de plus rend ce test ROUGE."""
        walls = {(30, 30)}
        blocked = socle_blocked_anchor_cells(walls, "round", BASE, 0, BOARD_COLS, BOARD_ROWS)
        sx, sy = _hex_center(30, 30)
        loin = 0
        for col in range(10, 51):
            for row in range(10, 51):
                cx, cy = _hex_center(col, row)
                distance = ((cx - sx) ** 2 + (cy - sy) ** 2) ** 0.5
                if distance > RADIUS + 1.0 + 1e-9:
                    assert (col, row) not in blocked, (
                        f"({col},{row}) à {distance:.2f} d'un mur isolé, doit rester licite"
                    )
                    loin += 1
        assert loin > 100, "l'échantillon doit contenir des ancres réellement éloignées"


class TestPocheIsolee:
    """Une ancre dont les six voisines sont interdites : le socle y tient mais n'en sort jamais."""

    def test_ancre_sans_voisine_licite_est_interdite(self):
        """Résidu mesuré sur ``terrain-mc1`` : la dilatation par le disque couvrait 663 des 664
        ancres immobiles ; la 664ᵉ, ``(167,125)``, tenait le socle mais avait ses SIX voisines
        trop étroites. « Aucune voisine licite » EST la définition de « aucun premier pas ».

        VERROU : retirer ``blocked |= _isolated_anchor_cells(...)`` rend ce test ROUGE.
        """
        from engine.hex_utils import _isolated_anchor_cells, get_neighbors

        poche = (25, 30)
        entoure = set(get_neighbors(*poche))
        isolees = _isolated_anchor_cells(entoure, BOARD_COLS, BOARD_ROWS)
        assert poche in isolees, "une ancre dont les 6 voisines sont interdites doit l'être aussi"

    def test_bord_de_plateau_referme_la_poche(self):
        """Hors plateau compte comme interdit : une poche adossée au bord se referme par le bord.

        VERROU : ignorer les voisines hors-bornes au lieu de les compter interdites rend ce
        test ROUGE (l'ancre du coin resterait licite alors qu'elle est murée).
        """
        from engine.hex_utils import _isolated_anchor_cells, get_neighbors

        coin = (0, 0)
        entoure = {
            nb for nb in get_neighbors(*coin)
            if 0 <= nb[0] < BOARD_COLS and 0 <= nb[1] < BOARD_ROWS
        }
        assert len(entoure) < 6, "le coin doit avoir des voisines hors plateau"
        isolees = _isolated_anchor_cells(entoure, BOARD_COLS, BOARD_ROWS)
        assert coin in isolees


class TestSortieDeContact:
    """Pièce B — obstacle MOBILE déjà chevauché par le socle au départ."""

    @staticmethod
    def _enemy_cells(anchor: Tuple[int, int]) -> Set[Tuple[int, int]]:
        return _footprint(*anchor)

    def test_au_contact_le_socle_peut_encore_partir(self):
        """VERROU : passer ``contact_obstacles=None`` rend ce test ROUGE (champ réduit au départ).

        Distance 8 colonnes = tangence exacte pour deux socles de rayon 6,0 — l'état où une
        charge laisse les deux unités.
        """
        enemy = self._enemy_cells((38, 30))
        start = (30, 30)
        sans_exception = geodesic_field(start, BOARD_COLS, BOARD_ROWS, enemy, 40.0, RADIUS)
        assert len(sans_exception) == 1, "sans l'exception, le contact fige les 6 directions"

        contact = obstacles_touching_disc(enemy, start, RADIUS)
        assert contact, "l'ennemi tangent doit être reconnu au contact"
        avec_exception = geodesic_field(
            start, BOARD_COLS, BOARD_ROWS, enemy, 40.0, RADIUS, contact_obstacles=contact
        )
        assert len(avec_exception) > 1, "l'unité au contact doit pouvoir se dégager (09.07)"

    def test_la_case_au_contact_reste_infranchissable(self):
        """09.07 : seul Desperate Escape traverse les figurines ennemies. L'exception supprime la
        DILATATION, pas le blocage des cases.

        L'obstacle est réduit à UNE cellule, et c'est indispensable : avec une empreinte ennemie
        entière, les cellules du fond restent dilatées et masquent celles du contact — le test
        passerait quoi qu'il arrive (vérifié : la mutation ne le faisait pas rougir).

        VERROU : ignorer complètement ``contact`` au lieu de le réindexer à clairance nulle rend
        ce test ROUGE — la case devient atteignable.
        """
        start = (30, 30)
        # Une seule cellule, posée assez près pour que le disque du socle la chevauche.
        obstacle = {(34, 30)}
        contact = obstacles_touching_disc(obstacle, start, RADIUS)
        assert contact == obstacle, "la cellule doit être reconnue au contact"
        field = geodesic_field(
            start, BOARD_COLS, BOARD_ROWS, obstacle, 40.0, RADIUS, contact_obstacles=contact
        )
        assert len(field) > 1, "le socle doit pouvoir se dégager"
        assert set(field) & obstacle == set(), "la case au contact reste infranchissable"

    def test_l_exception_ne_vaut_que_pour_le_premier_pas(self):
        """L'exception dit « ce sur quoi je suis posé ne m'empêche pas de PARTIR », pas « cet
        obstacle ne me gêne plus de la partie ». Une cellule qui n'est atteignable qu'en LONGEANT
        l'obstacle de contact, loin du départ, doit rester hors du champ.

        Fixture choisie par mesure, pas au jugé : une simple paire d'obstacles encadrant un
        couloir ne discrimine pas (le couloir est fermé des deux façons). Ici l'obstacle de
        contact borde lui-même le passage, ce qui rend la borne observable — 8 cellules d'écart.

        VERROU : retirer ``par == start`` / ``cur == start`` rend ce test ROUGE.
        """
        start = (30, 30)
        obstacles = {(34, 30), (34, 34), (36, 34), (38, 34)}
        contact = obstacles_touching_disc(obstacles, start, RADIUS)
        assert contact == {(34, 30)}, "un seul obstacle doit être au contact"
        field = geodesic_field(
            start, BOARD_COLS, BOARD_ROWS, obstacles, 60.0, RADIUS, contact_obstacles=contact
        )
        assert len(field) > 1, "le socle doit pouvoir se dégager du contact"
        # Cellules dont l'accès demande de longer l'obstacle de contact ailleurs qu'au départ.
        en_longeant = {(35, 29), (36, 30), (37, 29)}
        atteintes = set(field) & en_longeant
        assert atteintes == set(), (
            f"cellules atteintes en longeant l'obstacle de contact : {sorted(atteintes)}"
        )

    def test_sans_contact_le_champ_est_inchange(self):
        """L'exception ne doit RIEN changer quand personne n'est au contact — sinon elle élargit
        le champ partout au lieu de traiter le seul cas qui la justifie."""
        enemy = self._enemy_cells((45, 30))  # hors de portée du socle
        start = (30, 30)
        contact = obstacles_touching_disc(enemy, start, RADIUS)
        assert contact == set(), "aucun obstacle ne touche le socle à cette distance"
        temoin = geodesic_field(start, BOARD_COLS, BOARD_ROWS, enemy, 20.0, RADIUS)
        avec = geodesic_field(
            start, BOARD_COLS, BOARD_ROWS, enemy, 20.0, RADIUS, contact_obstacles=contact
        )
        assert avec == temoin


class TestCacheDesAncres:
    """Le cache d'ancres interdites est mémoïsé : il DOIT mourir quand les murs changent."""

    def test_le_cache_est_purge_a_la_rotation_de_scenario(self):
        """Les murs sont statiques PENDANT une partie, mais changent à la rotation de scénario —
        que le training enchaîne. Un cache survivant servirait les murs de la carte précédente à
        toute géométrie déjà vue, pendant que les autres reçoivent la nouvelle : masque et commit
        décriraient alors deux terrains différents.

        VERROU : retirer ``pop("_socle_wall_blocked_cache")`` de ``w40k_core`` rend ce test ROUGE.
        Le test lit la SOURCE (les deux sites de purge), parce qu'aucune assertion sur un
        game_state ne peut prouver qu'un site d'écriture n'a pas été oublié.
        """
        import re

        source = (
            pathlib.Path(__file__).resolve().parents[3] / "engine" / "w40k_core.py"
        ).read_text()
        purges_wall_set = len(re.findall(r'pop\("_wall_set_cache", None\)', source))
        purges_socle = len(re.findall(r'pop\("_socle_wall_blocked_cache", None\)', source))
        assert purges_wall_set > 0, "le jumeau _wall_set_cache doit exister (sinon ce test dérive)"
        assert purges_socle == purges_wall_set, (
            f"_socle_wall_blocked_cache purgé {purges_socle} fois pour "
            f"{purges_wall_set} purges de son jumeau _wall_set_cache"
        )


class TestSocleNonRond:
    """Sur socle non rond, placement et traversée coïncidaient déjà — rien ne doit bouger."""

    def test_non_rond_garde_la_dilatation_par_empreinte(self):
        """La traversée dilate un socle non rond par son empreinte hex ORIENTÉE (clairance 0) :
        le critère de placement doit rester exactement celui-là.

        VERROU : faire passer le non-rond par la géométrie de disque rend ce test ROUGE.
        """
        from engine.hex_utils import inflate_obstacles_by_footprint

        walls = _wall_column(30)
        off_even, off_odd = precompute_footprint_offsets("oval", [8, 4], 0)
        attendu = inflate_obstacles_by_footprint(walls, off_even, off_odd)
        obtenu = socle_blocked_anchor_cells(walls, "oval", [8, 4], 0, BOARD_COLS, BOARD_ROWS)
        # Les poches isolées s'ajoutent aussi au non-rond : on vérifie l'inclusion + l'absence
        # de géométrie continue (aucune ancre retenue hors de la dilatation par empreinte + poches).
        assert attendu <= obtenu
        from engine.hex_utils import _isolated_anchor_cells
        assert obtenu == attendu | _isolated_anchor_cells(attendu, BOARD_COLS, BOARD_ROWS)


class TestCarteReelle:
    """Le défaut tel qu'il s'est produit en partie, sur le terrain réellement joué."""

    def test_terrain_mc1_aucune_ancre_licite_immobile(self):
        """Balayage de la vraie carte : plus une seule ancre licite d'où le socle ne peut partir.

        VERROU : remettre le critère d'empreinte rend ce test ROUGE avec 664 ancres.
        """
        import json

        from engine.hex_utils import expand_wall_group_to_hex_list

        cols, rows = 220, 300
        terrain = json.load(open("config/board/44x60x5/terrain/terrain-mc1.json"))
        walls: Set[Tuple[int, int]] = set()
        for gi, group in enumerate(terrain["walls"]):
            walls.update(
                (int(col), int(row))
                for col, row in expand_wall_group_to_hex_list(group, path_hint=f"walls[{gi}]")
            )
        assert len(walls) > 900, "le fixture doit vraiment porter des murs (pas de vert vacant)"

        blocked = socle_blocked_anchor_cells(walls, "round", BASE, 0, cols, rows)
        # Échantillon : la couronne de 10 hexes autour de chaque mur, là où vit le défaut.
        candidates = {
            (c + dc, r + dr)
            for c, r in walls
            for dc in range(-10, 11)
            for dr in range(-10, 11)
            if 0 <= c + dc < cols and 0 <= r + dr < rows
        }
        testees = [a for a in candidates if a not in blocked]
        assert len(testees) > 10_000, "l'échantillon doit être peuplé"

        immobiles = []
        for anchor in testees:
            fp = _footprint(*anchor)
            if any(not (0 <= x < cols and 0 <= y < rows) for x, y in fp):
                continue  # hors plateau : rejeté par les bornes, pas par ce critère
            obs = set(walls)
            obs.discard(anchor)
            if len(geodesic_field(anchor, cols, rows, obs, 2.0, RADIUS)) <= 1:
                immobiles.append(anchor)
                if len(immobiles) > 5:
                    break
        assert immobiles == [], f"ancres licites mais immobiles : {immobiles[:5]}"
