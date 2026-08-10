"""Le cache de scoring mis à jour INCRÉMENTALEMENT est-il égal à un cache reconstruit ?

C'EST LE TEST QUI REND LA CORRECTION SÛRE (V11 §0.46, suite). La mise à jour incrémentale a
été généralisée à N poses de delta parce que les joueurs déploient en ALTERNANCE : quand un
joueur revient, il a manqué sa propre pose et celle de l'adversaire. Auparavant elle exigeait
exactement une pose et rendait donc la main dans tous les cas réels — c'est-à-dire qu'elle
n'a jamais tourné en production, et qu'aucun test ne pouvait attester qu'elle était juste.

Plutôt que de raisonner cas par cas sur les mises à jour (retrait des hexes occupés, comptage
des alliés par colonne, recalcul des lignes de vue par ennemi apparu), on COMPARE : à chaque
pose, le cache vivant doit être égal, champ par champ, à ce qu'aurait produit une
reconstruction complète du même état. Une divergence, même d'une unité sur un seul hexe,
serait une observation faussée pour l'agent (§0.40).
"""

import pytest

#: `ally_deployed_hexes` et `enemy_deployed_units` sont construits par APPEND dans la mise à
#: jour incrémentale, et le premier alimente `nearest_ally` dans `_deployment_score_columns`,
#: donc directement l'observation. Les omettre laissait hors du verrou un ingrédient de score
#: que ce chemin fabrique lui-même.
_CHAMPS_COMPARES = (
    "los_exposure_by_hex",
    "potential_los_exposure_by_hex",
    "ally_col_counts",
    "ally_deployed_hexes",
    "enemy_deployed_units",
)


def _avance_deploiement(eng) -> bool:
    """Joue UN pas de déploiement (premier slot légal). Rend False quand il n'y a plus à jouer.

    La politique (« premier légal »), le nom du drapeau de phase et le contrôle de masque vide
    étaient recopiés à chaque boucle de ce fichier — neuf fois. Ce qui compte dans ces tests est ce
    qu'ils OBSERVENT entre deux poses, pas la façon d'avancer : changer le pilotage (jouer un slot
    au hasard, par exemple) se payait donc neuf fois, et une copie qui oublie la garde `if not
    legal` lève un `IndexError` opaque au lieu de s'arrêter.
    """
    if eng.game_state["phase"] != "deployment":
        return False
    mask = eng.get_action_mask()
    legal = [i for i, ok in enumerate(mask) if ok]
    if not legal:
        return False
    eng.step(legal[0])
    return True


def _rebuild_reference(decoder, game_state, deployer):
    """Cache reconstruit de zéro pour l'état courant — la référence."""
    return decoder._build_deployment_scoring_cache(
        game_state, deployer, decoder.deployment_scoring_hexes(game_state, deployer)
    )


def _compare(vivant, reference, contexte):
    ecarts = []
    for champ in _CHAMPS_COMPARES:
        a, b = vivant[champ], reference[champ]
        if a != b:
            if isinstance(a, list) and isinstance(b, list):
                detail = f"{champ}: {len(a)} elements vivant contre {len(b)} reconstruits"
            elif isinstance(a, dict) and isinstance(b, dict):
                differents = [k for k in set(a) & set(b) if a[k] != b[k]]
                detail = (
                    f"{champ}: {len(set(a) ^ set(b))} cles divergentes, "
                    f"{len(differents)} valeurs differentes (ex: {differents[:3]})"
                )
            else:
                detail = f"{champ}: {len(set(a) ^ set(b))} elements divergents"
            ecarts.append(detail)
    assert not ecarts, f"{contexte} — le cache incremental diverge de la reconstruction :\n" + "\n".join(ecarts)


def test_incremental_matches_a_full_rebuild_at_every_deployment_step(make_active_deployment_engine):
    """À chaque pose, pour CHAQUE joueur, l'incrémental doit égaler la reconstruction."""
    eng = make_active_deployment_engine(seed=1)
    dec = eng.action_decoder
    assert eng.game_state["phase"] == "deployment"

    poses = 0
    for _ in range(400):
        gs = eng.game_state
        if gs["phase"] != "deployment":
            break
        deployer = int(gs["deployment_state"]["current_deployer"])
        # Consultation réelle : c'est elle qui déclenche l'incrémental ou la reconstruction.
        vivant = dec._get_or_build_deployment_scoring_cache(gs, deployer)
        _compare(vivant, _rebuild_reference(dec, gs, deployer), f"pose {poses}, joueur {deployer}")

        if not _avance_deploiement(eng):
            break
        poses += 1

    assert poses >= 4, f"trop peu de poses jouees ({poses}) : le test ne verrouille rien"


def test_the_incremental_path_is_actually_taken(make_active_deployment_engine):
    """CONTRE LE VERT VACANT : sans réutilisation, le test précédent ne compare que des rebuilds.

    C'est exactement l'état d'AVANT la correction — `incremental` valait 0 et la comparaison
    aurait été verte sans rien prouver.
    """
    eng = make_active_deployment_engine(seed=1)
    for _ in range(400):
        if not _avance_deploiement(eng):
            break

    counts = eng.action_decoder.deployment_cache_counts()
    assert counts["incremental"] > 0, (
        f"le chemin incremental n'est jamais pris : {counts} — la correction ne sert a rien"
    )


def test_each_player_keeps_its_own_cache(make_active_deployment_engine):
    """Un cache par joueur : les pools diffèrent, un cache unique se ferait invalider à chaque pose."""
    from engine.action_decoder import ActionDecoder

    eng = make_active_deployment_engine(seed=1)
    for _ in range(6):
        if not _avance_deploiement(eng):
            break

    caches = eng.game_state[ActionDecoder.DEPLOYMENT_SCORING_CACHE_KEY]
    assert set(caches) == {1, 2}, f"un cache par joueur attendu, obtenu : {sorted(caches)}"
    assert set(caches[1]["scoring_hexes"]) != set(caches[2]["scoring_hexes"]), (
        "les deux joueurs auraient le meme ensemble d'hexes : le pool n'est pas propre au joueur"
    )


def test_repositioning_an_already_deployed_unit_forces_a_rebuild(make_active_deployment_engine):
    """Un REPOSITIONNEMENT doit reconstruire, jamais être servi comme « cache à jour ».

    `deployment_recommit_plan` déplace une unité déjà posée : l'ensemble des ids ne change
    pas, seules les positions bougent. Un cache qui se déclare à jour sur ce seul critère sert
    des expositions calculées depuis l'ANCIENNE position — soit une observation fausse pour
    l'agent (§0.40), sur un handler atteignable par l'API.

    Ce cas était couvert par accident tant que l'incrémental exigeait exactement une pose ;
    généraliser à N ajouts a rouvert le trou, et ce test est ce qui le referme.
    """
    eng = make_active_deployment_engine(seed=1)
    dec = eng.action_decoder
    gs = eng.game_state

    for _ in range(3):
        if not _avance_deploiement(eng):
            break

    deployer = int(gs["deployment_state"]["current_deployer"])
    dec._get_or_build_deployment_scoring_cache(gs, deployer)

    posees = [u for u in gs["units"] if int(u["col"]) >= 0 and int(u["row"]) >= 0]
    assert posees, "aucune unite posee : le test ne construit pas la situation qu'il observe"
    cible = posees[0]
    ancienne = (int(cible["col"]), int(cible["row"]))
    libres = [
        h for h in dec.deployment_scoring_hexes(gs, int(cible["player"]))
        if h != ancienne
    ]
    cible["col"], cible["row"] = libres[len(libres) // 2]

    cache = dec._get_or_build_deployment_scoring_cache(gs, deployer)
    reference = _rebuild_reference(dec, gs, deployer)
    _compare(cache, reference, "apres repositionnement d'une unite deja posee")


def test_valid_hexes_are_always_inside_the_scoring_superset(make_active_deployment_engine):
    """L'INVARIANT qui rend le filtrage à la lecture sûr : `valid_hexes ⊆ scoring_hexes`.

    S'il tombe, le consommateur lève un `KeyError` sur un hexe absent du cache — c'est déjà sa
    garde. Ce test le vérifie AVANT, pour toutes les unités et à chaque étape du déploiement,
    y compris multi-hex (socle > 1) où la validité passe par une érosion morphologique.
    """
    eng = make_active_deployment_engine(seed=1)
    dec = eng.action_decoder

    verifications = 0
    for _ in range(400):
        gs = eng.game_state
        if gs["phase"] != "deployment":
            break
        deployer = int(gs["deployment_state"]["current_deployer"])
        superset = set(dec.deployment_scoring_hexes(gs, deployer))
        for unit_id in gs["deployment_state"]["deployable_units"][deployer]:
            valides = set(dec._get_valid_deployment_hexes(gs, deployer, str(unit_id)))
            hors = valides - superset
            assert not hors, (
                f"unite {unit_id} (joueur {deployer}) : {len(hors)} hexes valides HORS du "
                f"sur-ensemble, ex. {sorted(hors)[:3]}"
            )
            verifications += 1
        if not _avance_deploiement(eng):
            break

    assert verifications >= 8, f"trop peu de verifications ({verifications}) : test creux"


# ── Cache du POOL D'ANCRES VALIDES (`_get_valid_deployment_hexes`) ────────────────────────────
# Même exigence que le cache de scoring ci-dessus, sur l'autre poste du déploiement : mesuré
# 121 appels pour 12 états distincts (90,1 % de recalcul à l'identique) parce que le masque,
# l'observation et le commit d'un même step demandent tous le même pool. Un pool servi périmé
# ne lève rien : il rouvre le deadlock masque/commit (le masque ouvre un hexe que `deploy_unit`
# refuse), donc l'équivalence se PROUVE, elle ne se raisonne pas.


def _count_real_computations(dec, monkeypatch):
    """Compteur d'appels au calcul RÉEL du pool (les deux branches y passent).

    `_deployment_clearance_filter` est le point de passage obligé des branches mono-hex et
    multi-hex de `_get_valid_deployment_hexes`, et il est en aval du cache : le compter mesure
    donc les MISS, pas les consultations.
    """
    calls = []
    original = type(dec)._deployment_clearance_filter

    def _spy(self, game_state, unit_id, unit, candidates):
        calls.append(str(unit_id))
        return original(self, game_state, unit_id, unit, candidates)

    monkeypatch.setattr(type(dec), "_deployment_clearance_filter", _spy)
    return calls


def test_cached_valid_hexes_equal_a_cold_recomputation_at_every_step(make_active_deployment_engine):
    """À chaque pose et pour chaque unité déployable, le pool servi == le pool recalculé à froid."""
    eng = make_active_deployment_engine(seed=1)
    dec = eng.action_decoder

    verifications = 0
    for _ in range(400):
        gs = eng.game_state
        if gs["phase"] != "deployment":
            break
        deployer = int(gs["deployment_state"]["current_deployer"])
        for unit_id in gs["deployment_state"]["deployable_units"][deployer]:
            servi = dec._get_valid_deployment_hexes(gs, deployer, str(unit_id))
            # Recalcul à FROID : le cache vidé, le même état doit rendre le même pool.
            dec._deployment_valid_hexes_cache = None
            froid = dec._get_valid_deployment_hexes(gs, deployer, str(unit_id))
            assert servi == froid, (
                f"unite {unit_id} (joueur {deployer}) : le pool servi diverge du recalcul "
                f"({len(servi)} hexes contre {len(froid)})"
            )
            verifications += 1
        if not _avance_deploiement(eng):
            break

    assert verifications >= 8, f"trop peu de verifications ({verifications}) : test creux"


def test_the_valid_hexes_cache_is_actually_reused(make_active_deployment_engine, monkeypatch):
    """CONTRE LE VERT VACANT : sans réutilisation, le test d'équivalence compare deux rebuilds.

    C'est l'état d'AVANT la mémoïsation — chaque consultation recalculait, et l'équivalence
    aurait été verte sans rien prouver. On exige donc STRICTEMENT moins de calculs réels que de
    consultations.
    """
    eng = make_active_deployment_engine(seed=1)
    dec = eng.action_decoder
    calculs = _count_real_computations(dec, monkeypatch)

    consultations = 0
    for _ in range(400):
        gs = eng.game_state
        if gs["phase"] != "deployment":
            break
        deployer = int(gs["deployment_state"]["current_deployer"])
        for unit_id in gs["deployment_state"]["deployable_units"][deployer]:
            dec._get_valid_deployment_hexes(gs, deployer, str(unit_id))
            dec._get_valid_deployment_hexes(gs, deployer, str(unit_id))
            consultations += 2
        if not _avance_deploiement(eng):
            break

    assert consultations >= 8, f"trop peu de consultations ({consultations}) : test creux"
    assert len(calculs) < consultations, (
        f"{len(calculs)} calculs pour {consultations} consultations : le cache ne sert a rien"
    )


def _socle(entry):
    """Le triplet dont le pool dépend RÉELLEMENT côté unité candidate.

    `base_size_cache_key` est la source unique de la normalisation du socle en clé hachable, et
    c'est celle que le code sous test emploie : la recopier ici (`isinstance(..., list)` seul, sans
    les tuples) reproduirait la dérive que sa propre docstring documente comme déjà survenue — un
    test qui construit sa clé autrement que la production peut valider un partage qu'elle ne fait pas.
    """
    from engine.hex_utils import base_size_cache_key

    return (
        str(entry["BASE_SHAPE"]),
        base_size_cache_key(entry["BASE_SIZE"]),
        int(entry["orientation"]),
    )


def test_two_units_with_the_same_socle_share_the_cache_entry(make_active_deployment_engine):
    """Deux unités HORS TABLE de même socle ont le même pool : une seule entrée doit les servir.

    C'est ce que gagne l'absence d'`unit_id` dans la clé. Un roster porte plusieurs unités du même
    socle (trois `round 6` ici) : les distinguer coûtait un pool complet — ~14 000 hexes — recalculé
    par unité, pour un résultat identique hexe pour hexe.
    """
    eng = make_active_deployment_engine(seed=1)
    dec = eng.action_decoder
    gs = eng.game_state
    deployer = int(gs["deployment_state"]["current_deployer"])

    hors_table = [
        (str(uid), entry)
        for uid, entry in gs["units_cache"].items()
        if int(entry["col"]) < 0 and int(entry["player"]) == deployer
    ]
    par_socle = {}
    for uid, entry in hors_table:
        par_socle.setdefault(_socle(entry), []).append(uid)
    jumeaux = next((ids for ids in par_socle.values() if len(ids) >= 2), None)
    assert jumeaux, (
        f"aucune paire d'unites hors table de meme socle cote joueur {deployer} : "
        f"le test ne construit pas la situation qu'il observe ({sorted(par_socle)})"
    )

    a, b = jumeaux[0], jumeaux[1]
    unit_a = next(u for u in gs["units"] if str(u["id"]) == a)
    unit_b = next(u for u in gs["units"] if str(u["id"]) == b)
    fp_a = dec._deployment_valid_hexes_fingerprint(gs, deployer, a, unit_a)
    fp_b = dec._deployment_valid_hexes_fingerprint(gs, deployer, b, unit_b)
    assert fp_a == fp_b, (
        f"unites {a} et {b}, meme socle et toutes deux hors table, ont des empreintes de cache "
        f"differentes : le pool sera recalcule pour rien"
    )
    # Le partage n'est légitime que si les pools sont réellement identiques : on le vérifie, on ne
    # le postule pas.
    dec._deployment_valid_hexes_cache = None
    pool_a = dec._get_valid_deployment_hexes(gs, deployer, a)
    dec._deployment_valid_hexes_cache = None
    pool_b = dec._get_valid_deployment_hexes(gs, deployer, b)
    assert pool_a == pool_b, (
        f"cle partagee mais pools differents pour {a} et {b} ({len(pool_a)} vs {len(pool_b)} "
        f"hexes) : le partage servirait un pool faux"
    )


def test_a_deployed_unit_does_not_share_with_an_off_table_twin(make_active_deployment_engine):
    """L'exception qui rend l'absence d'`unit_id` sûre : une unité POSÉE ne partage avec personne.

    Le pool d'une unité déjà posée (repositionnement, `deployment_recommit_plan`) s'exclut
    elle-même du filtre de clairance ; celui de sa jumelle hors table, non. Ce qui les sépare est
    `neighbours` — énuméré avec `exclude_id=unit_id` — et RIEN d'autre. Si un jour cette
    énumération cessait d'exclure l'unité courante, ce test tombe : c'est son objet.
    """
    eng = make_active_deployment_engine(seed=1)
    dec = eng.action_decoder
    gs = eng.game_state

    # Situation CONSTRUITE : on joue jusqu'à ce qu'un socle existe en double dont UN est posé.
    cible = None
    for _ in range(400):
        gs = eng.game_state
        if gs["phase"] != "deployment":
            break
        deployer = int(gs["deployment_state"]["current_deployer"])
        posees = {
            _socle(e): str(u)
            for u, e in gs["units_cache"].items()
            if int(e["col"]) >= 0 and int(e["player"]) == deployer
        }
        for uid, entry in gs["units_cache"].items():
            if int(entry["col"]) >= 0 or int(entry["player"]) != deployer:
                continue
            posee = posees.get(_socle(entry))
            if posee is not None:
                cible = (deployer, posee, str(uid))
                break
        if cible is not None:
            break
        if not _avance_deploiement(eng):
            break

    assert cible is not None, (
        "aucun socle en double avec une unite posee et une hors table : le test ne construit pas "
        "la situation qu'il observe"
    )
    deployer, uid_posee, uid_hors_table = cible
    gs = eng.game_state
    unit_posee = next(u for u in gs["units"] if str(u["id"]) == uid_posee)
    unit_hors = next(u for u in gs["units"] if str(u["id"]) == uid_hors_table)
    fp_posee = dec._deployment_valid_hexes_fingerprint(gs, deployer, uid_posee, unit_posee)
    fp_hors = dec._deployment_valid_hexes_fingerprint(gs, deployer, uid_hors_table, unit_hors)
    assert fp_posee != fp_hors, (
        f"l'unite POSEE {uid_posee} partage l'empreinte de cache de sa jumelle hors table "
        f"{uid_hors_table} : elle lirait un pool qui la compte comme obstacle"
    )


def _play_until_a_non_round_ally_is_deployed(eng, limite=400):
    """Joue le déploiement jusqu'à ce que le DÉPLOYEUR COURANT ait une unité NON RONDE posée.

    Deux conditions, et chacune a une raison :
      - non ronde : `footprints_overlap` traite les paires ronde↔ronde en clearance euclidien
        continu, qui ne lit PAS `occupied_hexes`. Sur un voisin rond, muter l'empreinte ne
        changerait aucun pool et le test afficherait « tout va bien » sans rien observer.
      - du déployeur courant : la broad-phase de `_deployment_clearance_filter` ne convoque le
        test exact que pour les candidats dont le CENTRE est à portée du rayon englobant du
        voisin — un rayon qui ne dépend pas de l'empreinte. Un voisin planté dans la zone
        adverse est donc écarté avant que son empreinte ne soit lue, quelle qu'elle soit.
    Rend `(unit_id, entrée du cache, déployeur)`.
    """
    from engine.spatial_relations import entries_on_battlefield

    for _ in range(limite):
        gs = eng.game_state
        if gs["phase"] != "deployment":
            break
        deployer = int(gs["deployment_state"]["current_deployer"])
        for uid, entry in entries_on_battlefield(gs["units_cache"]):
            if str(entry["BASE_SHAPE"]) != "round" and int(entry["player"]) == deployer:
                return str(uid), entry, deployer
        if not _avance_deploiement(eng):
            break
    return None, None, None


def test_changing_only_a_neighbour_footprint_invalidates_the_cache(
    make_active_deployment_engine, board_x5
):
    """LE cas que `_build_deployed_snapshot_version` ne verrait pas : empreinte modifiée, ancre fixe.

    Le tampon du cache de scoring ne porte que `(player, col, row)` de l'ANCRE. Or le filtre de
    clairance lit l'EMPREINTE stockée du voisin (`entry_footprint` → `occupied_hexes`). Clefer ce
    cache-ci sur l'ancre servirait donc un pool calculé contre une autre empreinte, sans rien
    lever — la régression masque⊆exécutable §0.18. Ce test est ce qui interdit d'y revenir.
    """
    eng = make_active_deployment_engine(seed=1)
    dec = eng.action_decoder
    v_uid, v_entry, deployer = _play_until_a_non_round_ally_is_deployed(eng)
    assert v_entry is not None, (
        "aucune unite non ronde posee cote deployeur : le test ne construit pas la situation "
        "qu'il observe"
    )

    gs = eng.game_state
    deployables = [
        str(u) for u in gs["deployment_state"]["deployable_units"][deployer] if str(u) != v_uid
    ]
    assert deployables, f"aucune unite a deployer face au voisin {v_uid}"
    unit_id = deployables[0]

    servi_avant = dec._get_valid_deployment_hexes(gs, deployer, unit_id)
    assert servi_avant, f"pool vide pour {unit_id} : rien a observer"

    # Situation construite : l'empreinte du voisin AVALE les hexes du pool les plus proches de
    # son ancre — ceux-là passent la broad-phase, donc leur clairance est réellement testée
    # contre l'empreinte. Son ancre, elle, ne bouge pas : c'est tout l'objet du test.
    v_col, v_row = int(v_entry["col"]), int(v_entry["row"])
    empreinte_avant = set(v_entry["occupied_hexes"])
    proches = sorted(
        servi_avant, key=lambda h: (int(h[0]) - v_col) ** 2 + (int(h[1]) - v_row) ** 2
    )[:12]
    avalees = {(int(c), int(r)) for c, r in proches} - empreinte_avant
    assert avalees, (
        f"les hexes du pool les plus proches du voisin {v_uid} sont deja dans son empreinte : "
        "la mutation serait sans effet"
    )
    v_entry["occupied_hexes"] = empreinte_avant | avalees
    assert (int(v_entry["col"]), int(v_entry["row"])) == (v_col, v_row), (
        "l'ancre du voisin a bouge : le test ne prouve plus rien sur l'empreinte seule"
    )

    # Référence : ce que rend le calcul quand AUCUN cache ne peut mentir.
    dec._deployment_valid_hexes_cache = None
    froid = dec._get_valid_deployment_hexes(gs, deployer, unit_id)
    assert froid != servi_avant, (
        "la dilatation de l'empreinte ne change pas le pool recalcule : le test n'observe rien "
        "(voisin mal choisi, ou clearance qui ne lit pas l'empreinte)"
    )

    # Le vrai contrôle : le cache CHAUD, qui contient encore l'entrée d'avant la mutation.
    dec._deployment_valid_hexes_cache = None
    dec._get_valid_deployment_hexes(gs, deployer, unit_id)  # réchauffe sur l'etat MUTE
    v_entry["occupied_hexes"] = empreinte_avant
    revenu = dec._get_valid_deployment_hexes(gs, deployer, unit_id)
    assert revenu == servi_avant, (
        "empreinte revenue a son etat initial et pool different : le cache sert l'entree "
        "calculee contre l'empreinte dilatee (cle insensible a l'empreinte, §0.18)"
    )
