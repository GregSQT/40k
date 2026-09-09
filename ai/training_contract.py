"""Le CONTRAT d'un modele : les noms qui donnent leur sens aux nombres qu'il echange.

POURQUOI CE FICHIER EXISTE
--------------------------
Un run d'entrainement de ce depot coute des dizaines d'heures. Deux garde-fous existaient deja a
son ouverture, et aucun ne voit ce que celui-ci attrape :

- `check_model_lifecycle` (ai/train.py) verifie que la COMMANDE dit quoi faire du modele en place
  (`--new` / `--append`). Il ne regarde pas le contenu du modele ;
- le verrou de parite de pool (tests/unit/ai/test_pool_parity_lock.py) attrape une reprise
  desapparee, mais APRES la premiere sonde — donc apres des episodes deja joues ;
- Stable-Baselines3 lui-meme compare `observation_space` et `action_space` au chargement
  (`check_for_correct_spaces`, base_class.py:717) et leve si une DIMENSION a bouge.

Reste le cas que personne ne voit : la SEMANTIQUE change a taille CONSTANTE. Un canal de grille
renomme ou permute, un champ d'observation dont le sens change, une cle de recompense retiree.
Les tenseurs gardent leur forme, SB3 ne dit rien, et le modele repris continue de lire a l'indice
17 une grandeur qui n'est plus celle sur laquelle il a appris. Le run ne casse pas : il derive.

CE QUE CE GARDE-FOU APPORTE VRAIMENT, PAR FAMILLE
-------------------------------------------------
Mesure du 2026-09-09 sur l'historique git, a REFAIRE plutot qu'a recopier de memoire. Les deux
familles ne valent pas la meme chose, et le message d'arret ne doit pas les confondre (cf.
`FAMILLES_INVISIBLES_AILLEURS`) :

- TABLE DE RECOMPENSE — 7 commits sur 90 jours retirent au moins une cle d'un
  `config/agents/*/*_rewards_config.json`. Personne d'autre ne regarde les recompenses : ni SB3,
  ni le verrou de parite. Ce fichier est SEUL ;
- VOCABULAIRES D'IDS (`*_IDS`) — 21 commits sur 90 jours. `SQUAD_OBS_SIZE_TARGET` ne les compte
  pas (6 des 17 registres empreintes n'entrent pas dans son calcul, verifie le 2026-09-09) :
  « le vocabulaire s'allonge pour zero scalaire » (observation_builder.py:135). Une insertion y
  decale le sens de tous les ids suivants a dimension CONSTANTE. Ce fichier est SEUL, la aussi ;
- CHAMPS D'OBSERVATION / ACTIONS — 13 commits sur 30 jours touchent une entree de registre, mais
  12 changent la DIMENSION, donc `check_for_correct_spaces` les attrape deja au chargement.
  L'apport n'y est pas la detection : c'est de s'arreter AVANT d'engager le run, et de couvrir le
  renommage a taille constante — reel, mais rare (aucun cas sur ces 30 jours).

CE QUI EST COMPARE, ET CE QUI NE L'EST PAS
------------------------------------------
Comparé : les NOMS, dans leur ORDRE — registres d'observation (`*_FIELDS` de
`engine.observation_entities`), canaux de grille (`GRID_CHANNEL_NAMES`), familles d'actions
(`ACTION_FAMILIES`), et les CHEMINS DE CLES de la table de recompense.

PAS comparé : les VALEURS de la table de recompense. Changer un poids est un reglage delibere, et
c'en est meme le mode d'emploi normal ; bloquer un run pour un `+2.0` devenu `+2.5` rendrait ce
garde-fou insupportable, donc contourné. Ce qui se surveille est la STRUCTURE : une cle disparue
est un evenement qui ne rapporte plus rien, en silence.

L'ordre compte autant que l'appartenance : deux canaux permutes forment le meme ensemble de noms
et un vecteur d'observation different. La comparaison porte donc sur des LISTES, jamais sur des
ensembles.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Mapping, Optional, Tuple

from engine import macro_intents, observation_entities, spatial_grid

#: Nom du fichier voisin du modele. Volontairement pas un `.zip` : `ai/models/**/*.zip` ne se
#: modifie jamais automatiquement (CLAUDE.md), et le contrat doit pouvoir s'ecrire et se relire
#: sans jamais toucher aux poids.
CONTRACT_FILENAME = "training_contract.json"

#: Version du FORMAT du contrat. Un ancien fichier n'est pas « different », il est illisible par
#: ce code : c'est un cas distinct d'une divergence de contenu, et il se dit autrement.
CONTRACT_VERSION = 1


def _registres_nommes(module: Any) -> Dict[str, List[str]]:
    """Tous les registres de noms exposes par ce module, decouverts par INTROSPECTION.

    Une liste ecrite en dur ici se perimerait au premier registre ajoute — et un registre absent
    de l'empreinte est exactement le trou que ce fichier existe pour fermer. Le critere est donc
    structurel : un attribut public, tuple non vide de chaines.
    """
    trouves: Dict[str, List[str]] = {}
    for nom in dir(module):
        if nom.startswith("_"):
            continue
        valeur = getattr(module, nom)
        if isinstance(valeur, tuple) and valeur and all(isinstance(v, str) for v in valeur):
            trouves[nom] = list(valeur)
    return trouves


def _chemins_de_cles(valeur: Any, prefixe: str = "") -> List[str]:
    """Les chemins de cles d'une structure JSON, tries — sans aucune de ses valeurs.

    Une liste est notee par son chemin suivi de `[]` et n'est pas parcourue element par element :
    la table de recompense n'y range que des nombres, et en descendre ferait dependre l'empreinte
    du NOMBRE d'entrees, donc d'un reglage.
    """
    if isinstance(valeur, Mapping):
        chemins: List[str] = []
        for cle in sorted(valeur):
            enfant = f"{prefixe}.{cle}" if prefixe else str(cle)
            chemins.append(enfant)
            chemins.extend(_chemins_de_cles(valeur[cle], enfant))
        return chemins
    if isinstance(valeur, list):
        return [f"{prefixe}[]"]
    return []


def agent_reward_table(rewards_config: Mapping[str, Any], agent_key: str) -> Mapping[str, Any]:
    """La sous-table de recompense de CET agent, jamais la racine du fichier.

    Deux raisons, et la seconde est un faux positif evite :

    1. c'est ce que lit la production — `RewardCalculator` leve si `agent_key` manque
       (engine/reward_calculator.py:820), au lieu de deviner ;
    2. `load_agent_rewards_config` AJOUTE une cle alias a la racine en mode inter-faction
       (config_loader.py:645). Une empreinte prise a la racine changerait donc avec le MODE, sans
       qu'aucune recompense n'ait bouge — et un garde-fou qui crie a tort finit contourne.
    """
    if agent_key not in rewards_config:
        raise ValueError(
            f"Table de recompense sans entree pour l'agent '{agent_key}' : "
            f"cles disponibles {sorted(rewards_config)}. Le contrat ne peut pas etre etabli."
        )
    return rewards_config[agent_key]


def build_contract(rewards_config: Mapping[str, Any], agent_key: str) -> Dict[str, Any]:
    """Le contrat COURANT, lu du code et de la table de recompense de cet agent."""
    return {
        "version": CONTRACT_VERSION,
        "observation_fields": _registres_nommes(observation_entities),
        "grid_channels": list(spatial_grid.GRID_CHANNEL_NAMES),
        "action_families": list(macro_intents.ACTION_FAMILIES),
        "reward_keys": _chemins_de_cles(agent_reward_table(rewards_config, agent_key)),
    }


def contract_path(model_path: str) -> str:
    """Le chemin du contrat voisin d'un modele donne."""
    return os.path.join(os.path.dirname(model_path), CONTRACT_FILENAME)


def write_contract(model_path: str, contrat: Mapping[str, Any]) -> str:
    """Ecrit le contrat a cote du modele et rend son chemin."""
    chemin = contract_path(model_path)
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as flux:
        json.dump(contrat, flux, indent=2, ensure_ascii=False, sort_keys=True)
        flux.write("\n")
    return chemin


def read_contract(model_path: str) -> Optional[Dict[str, Any]]:
    """Le contrat enregistre, ou `None` s'il n'y en a pas.

    Un fichier PRESENT mais illisible n'est pas rendu comme absent : il leve. Les deux situations
    appellent des reponses opposees — initialiser d'un cote, reparer de l'autre — et les confondre
    ferait ecraser en silence un contrat corrompu.
    """
    chemin = contract_path(model_path)
    if not os.path.exists(chemin):
        return None
    with open(chemin, "r", encoding="utf-8") as flux:
        contenu = json.load(flux)
    if not isinstance(contenu, dict):
        raise ValueError(f"Contrat d'entrainement illisible ({chemin}) : un objet JSON est attendu.")
    return contenu


def _compare_listes(nom: str, ancienne: List[str], courante: List[str]) -> List[str]:
    """Ce qui a change entre deux listes de noms, dit en clair — ordre compris."""
    if ancienne == courante:
        return []
    retires = [v for v in ancienne if v not in courante]
    ajoutes = [v for v in courante if v not in ancienne]
    if not retires and not ajoutes:
        return [f"{nom} : meme contenu, ORDRE different ({ancienne} -> {courante})"]
    ecarts = []
    if retires:
        ecarts.append(f"{nom} : retire(s) {retires}")
    if ajoutes:
        ecarts.append(f"{nom} : ajoute(s) {ajoutes}")
    return ecarts


def diff_contracts(ancien: Mapping[str, Any], courant: Mapping[str, Any]) -> List[str]:
    """Les divergences entre le contrat du modele et celui du code, une phrase chacune."""
    ecarts: List[str] = []
    if ancien.get("version") != courant.get("version"):
        return [
            f"version de contrat {ancien.get('version')} != {courant.get('version')} : le format "
            "a change, le contenu n'est pas comparable."
        ]

    anciens_champs = ancien.get("observation_fields", {})
    courants_champs = courant.get("observation_fields", {})
    if not isinstance(anciens_champs, dict):
        return [f"observation_fields illisible dans le contrat enregistre ({type(anciens_champs)})"]
    for registre in sorted(set(anciens_champs) | set(courants_champs)):
        if registre not in anciens_champs:
            ecarts.append(f"observation : nouveau registre `{registre}`")
            continue
        if registre not in courants_champs:
            ecarts.append(f"observation : registre `{registre}` disparu du code")
            continue
        ecarts.extend(
            _compare_listes(f"observation.{registre}", anciens_champs[registre], courants_champs[registre])
        )

    for cle in ("grid_channels", "action_families", "reward_keys"):
        ecarts.extend(_compare_listes(cle, list(ancien.get(cle, [])), list(courant.get(cle, []))))
    return ecarts


def contract_missing(model_path: str, agent_key: str) -> ValueError:
    """L'erreur de « ce modele existe, mais on ne sait pas sur quel contrat il a appris ».

    Le run s'ARRETE au lieu d'ecrire le contrat courant et de continuer : ecrire maintenant
    reviendrait a declarer conforme ce qu'on n'a pas pu comparer, et a rendre le garde-fou muet
    exactement le jour ou il servirait. Un modele anterieur a l'introduction du contrat est dans
    ce cas — d'ou une commande d'initialisation explicite, qui est une decision, pas un defaut.
    """
    return ValueError(
        f"Aucun contrat d'entrainement a cote du modele ({contract_path(model_path)}). Impossible "
        "de verifier que l'observation, les familles d'actions et la table de recompense sont "
        "restees celles sur lesquelles ce modele a appris.\n"
        "  - modele anterieur a ce garde-fou, et le contrat courant est le bon :\n"
        f"      python3 -m ai.training_contract --init --agent {agent_key}\n"
        "  - modele dont on ne sait plus sur quoi il a appris : le reentrainer avec --new."
    )


#: Familles d'ecarts qu'AUCUN autre controle du depot ne voit, jamais.
#:
#: MESURE du 2026-09-09, sur l'historique git — a refaire avant de modifier cette liste, pas a
#: recopier de memoire. Sur 90 jours, 7 commits retirent au moins une cle d'un
#: `config/agents/*/*_rewards_config.json` : ni Stable-Baselines3 (qui ne compare que les espaces
#: d'observation et d'action) ni le verrou de parite de pool ne regardent les recompenses.
#:
#: Les autres familles ne sont PAS dans ce cas, et le message ne doit pas le laisser croire. Sur
#: 30 jours, 13 commits modifient une entree d'un registre de `engine/observation_entities.py` :
#: 12 changent le NOMBRE d'entrees, donc la dimension, que `check_for_correct_spaces` attrape deja
#: au chargement ; le 13e (2b71ef00) ne touchait que des commentaires, donc ce contrat ne l'aurait
#: meme pas vu. Y prometre une detection unique serait faux douze fois sur treize.
FAMILLES_INVISIBLES_AILLEURS = ("reward_keys",)

#: Suffixe des registres de VOCABULAIRE : `UNIT_RULE_EFFECT_IDS`, `OBS_PHASE_IDS`,
#: `AGENT_DECISION_TYPE_IDS`, `DECISION_GRANTABLE_EFFECT_IDS`.
#:
#: Ces registres-la ne portent pas des CASES de l'observation, mais le sens des VALEURS qu'elle
#: transporte : l'indice d'une entree y est l'`obs_id` emis. « Le vocabulaire s'allonge pour zero
#: scalaire » — engine/observation_builder.py:135, verbatim. `SQUAD_OBS_SIZE_TARGET` ne les compte
#: donc pas (verifie le 2026-09-09 : 6 des 17 registres empreintes n'entrent pas dans son calcul),
#: et une INSERTION ou un REORDONNANCEMENT y decale le sens de tous les ids suivants sans changer
#: la moindre dimension. `check_for_correct_spaces` ne peut rien y voir, le verrou de parite non
#: plus : ce contrat est seul, exactement comme sur la table de recompense.
#:
#: FREQUENCE mesuree : 21 commits sur 90 jours touchent un de ces registres.
#:
#: Limite assumee : un ajout en FIN de vocabulaire ne decale aucun id existant et serait donc
#: inoffensif pour un modele deja entraine — la comparaison de listes ordonnees le signale quand
#: meme. Distinguer les deux demanderait de savoir si le prefixe commun est intact ; le cout d'un
#: arret de trop est une commande, celui d'un arret manquant des dizaines d'heures.
SUFFIXE_VOCABULAIRE = "_IDS"


def _est_invisible_ailleurs(ecart: str) -> bool:
    """Cet ecart-ci echappe-t-il a TOUS les autres controles du depot ?

    Deux cas, mesures : la table de recompense (que personne d'autre ne regarde) et les registres
    de vocabulaire (dont la taille ne bouge jamais, cf. `SUFFIXE_VOCABULAIRE`).
    """
    if ecart.startswith(FAMILLES_INVISIBLES_AILLEURS):
        return True
    if not ecart.startswith("observation."):
        return False
    registre = ecart.split(" ", 1)[0].split(".", 1)[1]
    return registre.endswith(SUFFIXE_VOCABULAIRE)


def _pourquoi_l_arret_vaut(ecarts: List[str]) -> str:
    """Ce que cet ecart-CI doit a ce garde-fou — pas une generalite sur tous les ecarts.

    Un motif d'arret qui sonne faux est un motif qu'on apprend a ignorer, puis a contourner. La
    phrase est donc construite sur les familles REELLEMENT presentes.
    """
    invisibles = [e for e in ecarts if _est_invisible_ailleurs(e)]
    autres = [e for e in ecarts if e not in invisibles]
    phrases = []
    if invisibles:
        quoi = (
            "la table de recompense ou un vocabulaire d'ids"
            if any(e.startswith("observation.") for e in invisibles)
            else "la table de recompense"
        )
        phrases.append(
            f"L'ecart sur {quoi} n'est vu par AUCUN autre controle : ni Stable-Baselines3, qui ne "
            "compare que les DIMENSIONS des espaces, ni le verrou de parite de pool. Un "
            "vocabulaire s'allonge pour zero scalaire, et une table de recompense n'entre dans "
            "aucun espace : sans cet arret, le run apprendrait sur des grandeurs qui ont change "
            "de sens, et rien ne le dirait."
        )
    if autres:
        phrases.append(
            "L'ecart sur l'observation ou les actions ferait AUSSI lever Stable-Baselines3 au "
            "chargement, MAIS seulement si la taille des tenseurs a change, et seulement une fois "
            "le run engage. Ici l'arret arrive avant le moindre effet de bord — et il couvre en "
            "plus le renommage ou la permutation a taille constante, que SB3 ne voit pas."
        )
    return " ".join(phrases)


def contract_mismatch(model_path: str, ecarts: List[str]) -> ValueError:
    """L'erreur de « le contrat a bouge depuis que ce modele a appris »."""
    detail = "\n".join(f"    - {e}" for e in ecarts)
    return ValueError(
        "Le contrat d'entrainement a change depuis que ce modele a appris.\n"
        f"{detail}\n"
        f"  contrat du modele : {contract_path(model_path)}\n"
        f"  {_pourquoi_l_arret_vaut(ecarts)}\n"
        "  Reprendre ce modele ferait apprendre sur des grandeurs qui ont change de sens. "
        "Soit repartir de zero (--new), soit — si le changement est neutre pour ce modele — "
        f"reecrire sciemment le contrat : python3 -m ai.training_contract --init --agent <agent>"
    )


def enforce_training_contract(
    model_path: str,
    agent_key: str,
    rewards_config: Mapping[str, Any],
    new_model: bool,
    log_fn=print,
) -> Tuple[str, List[str]]:
    """Garde-fou d'ouverture de run. Rend `(action, ecarts)`, ou leve.

    `--new` (re)ecrit le contrat : un modele neuf n'herite d'aucun passe, il DEFINIT le sien.
    Toute reprise le compare, et s'arrete au moindre ecart.
    """
    contrat_courant = build_contract(rewards_config, agent_key)
    if new_model or not os.path.exists(model_path):
        write_contract(model_path, contrat_courant)
        return "written", []

    enregistre = read_contract(model_path)
    if enregistre is None:
        raise contract_missing(model_path, agent_key)

    ecarts = diff_contracts(enregistre, contrat_courant)
    if ecarts:
        raise contract_mismatch(model_path, ecarts)
    log_fn("✅ Contrat d'entrainement inchange (observation, actions, cles de recompense)")
    return "verified", []


def _main(argv: Optional[List[str]] = None) -> int:
    """`python3 -m ai.training_contract --init --agent <agent_key>` : (re)ecrit le contrat.

    Seul chemin par lequel un contrat s'ecrit sans passer par `--new` — et il est MANUEL, parce
    que c'est une affirmation sur un modele existant que le code ne peut pas verifier a la place
    de qui la fait.
    """
    import argparse

    parseur = argparse.ArgumentParser(description="Contrat d'entrainement d'un agent.")
    parseur.add_argument("--init", action="store_true", help="ecrit le contrat courant")
    parseur.add_argument("--agent", required=True, help="cle d'agent (dossier ai/models/<agent>/)")
    parseur.add_argument("--models-root", default="ai/models")
    args = parseur.parse_args(argv)

    from ai.train import build_agent_model_path
    from config_loader import get_config_loader

    model_path = build_agent_model_path(args.models_root, args.agent)
    # `load_rewards_config()` est DEPRECIEE et leve : les tables sont par agent depuis leur
    # deplacement dans `config/agents/<agent>/`.
    rewards = get_config_loader().load_agent_rewards_config(args.agent)
    contrat = build_contract(rewards, args.agent)
    if not args.init:
        enregistre = read_contract(model_path)
        if enregistre is None:
            print(f"aucun contrat a {contract_path(model_path)}")
            return 1
        ecarts = diff_contracts(enregistre, contrat)
        print("\n".join(ecarts) if ecarts else "contrat inchange")
        return 1 if ecarts else 0
    print(f"contrat ecrit : {write_contract(model_path, contrat)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
