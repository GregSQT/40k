"""Verrou des trois hooks de .claude/hooks/.

Ces hooks portent des règles qui vivaient auparavant dans CLAUDE.md sous forme de texte, donc
sans exécution : présence des sections du rapport de clôture, disposition du bloc RELIRE, refus
de la vérification large, liste des fichiers restant à relire. Un hook muet est indistinguable
d'un hook conforme — d'où ce fichier.

Les cas PASSANTS comptent autant que les cas bloquants : un hook qui réclame sur tout est ignoré
aussi vite qu'un hook qui ne réclame rien laisse passer les défauts. Le cas central est celui du
2026-08-12 : un tour conforme dont le rapport était précédé de textes intermédiaires, que la
première version du contrôle prenait pour le rapport lui-même.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[3]
CLAUDE_MD = RACINE / "CLAUDE.md"
HOOKS = RACINE / ".claude" / "hooks"
H_RAPPORT = HOOKS / "rapport-cloture.sh"
H_DENY = HOOKS / "deny-verif-large.sh"
H_ATTENTE = HOOKS / "relire-en-attente.sh"

# Les listes sont nommées par le session_id, dont la FORME est contrôlée : un identifiant
# fantaisiste est refusé, donc les tests emploient de vrais UUID.
S1 = "11111111-1111-1111-1111-111111111111"
S2 = "22222222-2222-2222-2222-222222222222"

RAPPORT_CONFORME = """Fait.

LU : engine/x.py en entier, ses 3 appelants
JUMEAU : grep -rn "foo" engine/ -> 2 hits, 2 traites
COUVERTURE : tests/unit/engine/test_x.py::test_foo etendu ; aucun trou vu
RELIRE :
/code-review /home/greg/40k/engine/x.py
/simplify /home/greg/40k/engine/x.py
"""

WORKTREE_FILE = "/home/greg/40k/.claude/worktrees/sujet/engine/x.py"


# --------------------------------------------------------------------------- outils de transcript


def _user(text: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": text}}


def _tool_result() -> dict:
    """Un retour d'outil s'écrit `type: user` — il ne doit PAS découper le tour."""
    return {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]},
    }


def _edit(path: str, *, sidechain: bool = False) -> dict:
    entry = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": path}}],
        },
    }
    if sidechain:
        entry["isSidechain"] = True
    return entry


def _say(text: str) -> dict:
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def _rapport(tmp_path: Path, *entries: dict, hook: Path = H_RAPPORT) -> str | None:
    """Contexte injecté par le hook au prompt suivant, ou None s'il se tait."""
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    proc = subprocess.run(
        [str(hook)],
        input=json.dumps(
            {
                "transcript_path": str(transcript),
                "hook_event_name": "UserPromptSubmit",
                "prompt": "suite",
            }
        ),
        capture_output=True,
        text=True,
        check=True,
    )
    if not proc.stdout.strip():
        return None
    return json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]


def _config(hook: Path = H_RAPPORT) -> dict:
    """Config lue PAR le hook, pas reparsée ici : reparser recréerait le doublon qu'on supprime."""
    proc = subprocess.run([str(hook), "--config"], capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


def _config_refusee(hook: Path) -> bool:
    """Le hook refuse-t-il de lire une config qu'il ne comprend pas entièrement ?"""
    return subprocess.run([str(hook), "--config"], capture_output=True).returncode != 0


def _labels_du_format_impose() -> list[str]:
    """Étiquettes du gabarit `FORMAT IMPOSÉ` de CLAUDE.md, dans l'ordre où elles y figurent.

    Le gabarit indente ses étiquettes de DEUX espaces ; les sous-parties de l'ARBITRAGE
    (`RECOMMANDATION :`) le sont davantage et ne sont donc pas des sections du rapport.
    """
    texte = CLAUDE_MD.read_text(encoding="utf-8")
    debut = texte.index("FORMAT IMPOSÉ")
    fin = texte.index("/simplify <fichiers modifiés>", debut)
    return re.findall(r"^ {2}([A-ZÉÈÀÂÎÔÛÇ]+)\s*:", texte[debut:fin], re.MULTILINE)


def _sections_declarees_facultatives() -> set[str]:
    """Sections que CLAUDE.md autorise explicitement à omettre (« omettre la section »)."""
    texte = CLAUDE_MD.read_text(encoding="utf-8")
    puce = re.search(r"^- ([A-ZÉÈÀÂÎÔÛÇ, et]+) : omettre la section", texte, re.MULTILINE)
    assert puce is not None, "la puce qui déclare les sections omissibles a disparu de CLAUDE.md"
    return set(re.findall(r"[A-ZÉÈÀÂÎÔÛÇ]{2,}", puce.group(1)))


def _run_deny(command: str) -> dict | None:
    """Verdict du hook PreToolUse : le dict de refus, ou None si la commande passe."""
    proc = subprocess.run(
        [str(H_DENY)],
        input=json.dumps({"tool_input": {"command": command}}),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout) if proc.stdout.strip() else None


# -------------------------------------------------------- source unique de la liste des sections


def _hook_isole(tmp_path: Path, claude_md: str) -> Path:
    """Copie du hook au-dessus d'un CLAUDE.md fabriqué, pour éprouver sa lecture de la config.

    La ligne des fichiers-code est complétée si le cas sous test ne la fournit pas : chaque test
    n'énonce ainsi que la ligne qu'il éprouve.
    """
    hooks = tmp_path / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    shutil.copy(H_RAPPORT, hooks / H_RAPPORT.name)
    if "FICHIERS COMPTÉS COMME CODE" not in claude_md:
        claude_md += "\nFICHIERS COMPTÉS COMME CODE : `.py`, `CLAUDE.md`\n"
    (tmp_path / "CLAUDE.md").write_text(claude_md, encoding="utf-8")
    return hooks / H_RAPPORT.name


def test_la_liste_vient_bien_de_claude_md(tmp_path: Path) -> None:
    """VERROU de la source unique : la liste est LUE, pas codée en dur dans le hook.

    On rejoue le hook sur une copie du dépôt dont le CLAUDE.md exige une section inventée : si
    elle est réclamée, c'est bien le fichier qui commande. Sans ce test, un hook redevenu
    autonome passerait tous les autres.
    """
    hook = _hook_isole(tmp_path, "SECTIONS EXIGÉES : `LU`=toujours, `TOTO`=toujours\n")
    assert _config(hook)["sections"] == [["LU", "toujours"], ["TOTO", "toujours"]]

    contexte = _rapport(tmp_path, _user("corrige"), _edit("engine/x.py"),
                        _say(RAPPORT_CONFORME), hook=hook)
    assert contexte is not None
    assert "TOTO" in contexte and "RELIRE" not in contexte


def test_liste_illisible_est_signalee_et_non_ignoree(tmp_path: Path) -> None:
    """Un garde-fou qui ne peut plus lire sa liste le DIT — se taire le rendrait muet (T1)."""
    hook = _hook_isole(tmp_path, "plus aucune liste ici\n")
    contexte = _rapport(tmp_path, _user("q"), _say("r"), hook=hook)
    assert contexte is not None and "SECTIONS EXIGÉES" in contexte


@pytest.mark.parametrize(
    "ligne",
    [
        # Une entrée qui perd ses backticks : le parse la sauterait et RELIRE disparaîtrait.
        "SECTIONS EXIGÉES : `LU`=toujours, JUMEAU=toujours, `RELIRE`=code",
        # Liste repliée sur deux lignes : la seconde n'est jamais lue. Les trois ponctuations de
        # continuation comptent — deviner laquelle laisse toujours une forme passer, et le cas
        # SANS ponctuation est le seul que la ligne elle-même ne trahit pas.
        "SECTIONS EXIGÉES : `LU`=toujours, `JUMEAU`=toujours,\n  `RELIRE`=code",
        "SECTIONS EXIGÉES : `LU`=toujours `JUMEAU`=toujours\n  `RELIRE`=code",
        "SECTIONS EXIGÉES : `LU`=toujours\n  `RELIRE`=code",
        # Repli dont la VIRGULE part à la ligne : l'amorce n'est alors pas un backtick.
        "SECTIONS EXIGÉES : `LU`=toujours\n  , `RELIRE`=code",
        # Portée inventée : ni `toujours` ni `code`.
        "SECTIONS EXIGÉES : `LU`=parfois, `RELIRE`=code",
        # Entrée reconnaissable MAIS noyée dans du texte : la nuance ne serait appliquée par
        # personne, donc la ligne ne dit plus ce que le hook fait.
        "SECTIONS EXIGÉES : `LU`=toujours sauf en doc, `RELIRE`=code",
        # Source dédoublée : la seconde ligne ne commanderait rien, sans que rien ne le dise.
        "SECTIONS EXIGÉES : `LU`=toujours\n\ntexte\n\nSECTIONS EXIGÉES : `RELIRE`=code",
    ],
)
def test_liste_partiellement_illisible_est_refusee(tmp_path: Path, ligne: str) -> None:
    """Un parse PARTIEL éteindrait RELIRE en silence — donc le contrôle des chemins en worktree."""
    assert _config_refusee(_hook_isole(tmp_path, ligne + "\n")), (
        "liste partiellement illisible acceptée sans bruit"
    )


def test_une_mention_illustrative_ailleurs_ne_tue_pas_le_hook(tmp_path: Path) -> None:
    """Le contrôle du repli est borné à la ligne suivante, et doit le rester.

    Compté sur tout le fichier, il ferait lever la lecture de la config dès qu'une puce cite une
    entrée en exemple — et une exception éteint TOUT le contrôle de forme, pas seulement le
    repli, sur un CLAUDE.md pourtant conforme.
    """
    hook = _hook_isole(
        tmp_path,
        "SECTIONS EXIGÉES : `LU`=toujours, `RELIRE`=code\n\n"
        "- exemple documentaire : écrire `LU`=toujours signifie que la section est due partout.\n",
    )
    assert _config(hook)["sections"] == [["LU", "toujours"], ["RELIRE", "code"]]


@pytest.mark.parametrize(
    "voisine",
    [
        # L'AUTRE ligne déclarative : elles sont adjacentes dans CLAUDE.md, dans un ordre ou
        # dans l'autre. Chercher un item n'importe où sur la ligne suivante rendait cet ordre
        # mortel — les deux garde-fous éteints sur un fichier conforme.
        "SECTIONS EXIGÉES : `LU`=toujours, `RELIRE`=code",
        # La glose qui suit la ligne, dès qu'elle cite un item entre backticks.
        "  (un suffixe comme `.py`, ou un nom entier comme `CLAUDE.md`)",
        "- puce voisine citant `.sh` en exemple",
    ],
)
def test_ligne_voisine_citant_un_item_n_est_pas_un_repli(tmp_path: Path, voisine: str) -> None:
    """Un repli COMMENCE par l'item ; une ligne qui en cite un ailleurs n'en est pas un."""
    claude_md = "FICHIERS COMPTÉS COMME CODE : `.py`, `CLAUDE.md`\n" + voisine + "\n"
    if "SECTIONS EXIGÉES" not in voisine:
        claude_md += "SECTIONS EXIGÉES : `LU`=toujours, `RELIRE`=code\n"
    assert _config(_hook_isole(tmp_path, claude_md))["code_suffixes"] == [".py"]


def test_modifier_claude_md_engage_couverture_et_relire(tmp_path: Path) -> None:
    """CLAUDE.md pilote le hook : le tour qui peut l'éteindre ne peut pas être le seul exempté."""
    contexte = _rapport(tmp_path, _user("change la liste"), _edit("CLAUDE.md"),
                        _say("Fait.\n\nLU : CLAUDE.md\nJUMEAU : grep -c foo -> 0 hit\n"))
    assert contexte is not None
    assert "COUVERTURE" in contexte and "RELIRE" in contexte


def test_portee_code_vient_aussi_de_claude_md(tmp_path: Path) -> None:
    """La portée « qu'est-ce que du code » est déclarée au même endroit que les sections.

    Elle vivait en dur dans le hook pendant que les puces COUVERTURE/RELIRE la décrivaient en
    prose : deux exemplaires, donc la divergence du 2026-08-12 à l'endroit voisin. Ici on prouve
    que c'est bien CLAUDE.md qui commande, suffixes comme noms entiers.
    """
    reel = _config()
    assert "CLAUDE.md" in reel["code_basenames"] and ".py" in reel["code_suffixes"]

    hook = _hook_isole(
        tmp_path,
        "SECTIONS EXIGÉES : `COUVERTURE`=code\nFICHIERS COMPTÉS COMME CODE : `.zzz`, `INVENTE.md`\n",
    )
    assert _config(hook)["code_suffixes"] == [".zzz"]
    for fichier in ("a.zzz", "INVENTE.md"):
        contexte = _rapport(tmp_path, _user("corrige"), _edit(fichier), _say("fait."), hook=hook)
        assert contexte is not None and "COUVERTURE" in contexte
    assert _rapport(tmp_path, _user("corrige"), _edit("a.py"), _say("fait."), hook=hook) is None


def test_sections_du_hook_et_gabarit_de_claude_md_ne_divergent_pas() -> None:
    """Le défaut du 2026-08-12 : le hook réclamait COUVERTURE, la puce ne la listait pas."""
    exigees = [nom for nom, _ in _config()["sections"]]
    labels = _labels_du_format_impose()
    assert set(exigees) <= set(labels), "section exigée par le hook mais absente du FORMAT IMPOSÉ"
    facultatives = _sections_declarees_facultatives()
    assert set(labels) == set(exigees) | facultatives, (
        "toute section du FORMAT IMPOSÉ doit être soit exigée par le hook, soit déclarée omissible"
    )


def test_portee_des_sections_est_celle_annoncee() -> None:
    """La liste reste lisible : rien d'autre que `toujours` / `code`, et RELIRE reste gaté code."""
    sections = dict(_config()["sections"])
    assert set(sections.values()) <= {"toujours", "code"}
    assert sections["LU"] == sections["JUMEAU"] == "toujours"
    assert sections["COUVERTURE"] == sections["RELIRE"] == "code"


# ------------------------------------------------------------------- contrôle du rapport de clôture


def test_tour_sans_modification_ne_reclame_rien(tmp_path: Path) -> None:
    assert _rapport(tmp_path, _user("explique-moi ça"), _say("voilà.")) is None


def test_rapport_conforme_ne_reclame_rien(tmp_path: Path) -> None:
    assert (
        _rapport(tmp_path, _user("corrige"), _edit("engine/x.py"), _tool_result(),
                 _say(RAPPORT_CONFORME))
        is None
    )


def test_textes_intermediaires_ne_passent_pas_pour_le_rapport(tmp_path: Path) -> None:
    """LE cas du 2026-08-12, mesuré en production.

    Un tour conforme narre souvent son avancement (« je commence par les hooks »). Ces textes
    sont écrits au transcript AVANT le message final. Le contrôle, branché sur Stop, prenait le
    dernier texte disponible — donc une phrase de narration — et réclamait trois sections que le
    message final contenait. Ici le rapport est bien reconnu, malgré la narration qui le précède.
    """
    assert (
        _rapport(tmp_path, _user("corrige"), _say("Je commence par les hooks."),
                 _edit("engine/x.py"), _tool_result(), _say("Points factuels :"),
                 _edit("engine/y.py"), _tool_result(), _say(RAPPORT_CONFORME))
        is None
    )


def test_narration_sans_rapport_final_est_bien_reclamee(tmp_path: Path) -> None:
    """Le symétrique du test précédent : la narration ne doit pas non plus TENIR LIEU de rapport."""
    contexte = _rapport(tmp_path, _user("corrige"), _say("Je commence par les hooks."),
                        _edit("engine/x.py"), _tool_result(), _say("Voilà, c'est corrigé."))
    assert contexte is not None
    for section in ("LU", "JUMEAU", "RELIRE"):
        assert section in contexte


def test_rapport_absent_reclame_chaque_section(tmp_path: Path) -> None:
    contexte = _rapport(tmp_path, _user("corrige"), _edit("engine/x.py"), _tool_result(),
                        _say("c'est corrigé."))
    assert contexte is not None and "PRÉCÉDENT" in contexte
    for section in ("LU", "JUMEAU", "COUVERTURE", "RELIRE"):
        assert section in contexte


def test_couverture_est_exigee_des_qu_un_fichier_de_code_bouge(tmp_path: Path) -> None:
    """T4 COUVERTURE : un comportement modifié sans son test pytest ne passe pas en silence."""
    ampute = "\n".join(
        ln for ln in RAPPORT_CONFORME.splitlines() if not ln.startswith("COUVERTURE")
    )
    contexte = _rapport(tmp_path, _user("corrige"), _edit("engine/x.py"), _say(ampute))
    assert contexte is not None and "COUVERTURE" in contexte


def test_couverture_n_est_pas_exigee_sur_une_modification_de_doc(tmp_path: Path) -> None:
    """Même condition que RELIRE : aucun code n'a bougé, donc aucun test n'est dû.

    Sur une doc ORDINAIRE : CLAUDE.md, lui, pilote le hook et compte comme du code (voir
    `test_modifier_claude_md_engage_couverture_et_relire`).
    """
    doc = "Fait.\n\nLU : le doc en entier\nJUMEAU : grep -c COUVERTURE -> 1 hit\n"
    assert _rapport(tmp_path, _user("corrige la doc"), _edit("Documentation/x.md"),
                    _say(doc)) is None


@pytest.mark.parametrize(
    "fichier",
    [
        ".claude/hooks/rapport-cloture.sh",
        # Il n'ENREGISTRE pas moins les hooks que CLAUDE.md ne les configure : l'y retirer les
        # éteint aussi sûrement, donc ce tour-là doit son rapport complet.
        ".claude/settings.json",
    ],
)
def test_un_fichier_qui_pilote_les_hooks_compte_comme_du_code(
    tmp_path: Path, fichier: str
) -> None:
    """Sinon le tour qui modifie un garde-fou serait le seul à n'en réclamer aucun."""
    ampute = "\n".join(
        ln for ln in RAPPORT_CONFORME.splitlines() if not ln.startswith("COUVERTURE")
    )
    contexte = _rapport(tmp_path, _user("corrige le hook"), _edit(fichier), _say(ampute))
    assert contexte is not None and "COUVERTURE" in contexte


def test_etiquette_relire_doit_etre_seule_sur_sa_ligne(tmp_path: Path) -> None:
    colle = RAPPORT_CONFORME.replace("RELIRE :\n/code-review", "RELIRE : /code-review")
    contexte = _rapport(tmp_path, _user("corrige"), _edit("engine/x.py"), _say(colle))
    assert contexte is not None and "SEULE sur sa ligne" in contexte


@pytest.mark.parametrize("manquante", ["/code-review", "/simplify"])
def test_les_deux_commandes_de_relecture_sont_exigees(tmp_path: Path, manquante: str) -> None:
    ampute = "\n".join(
        ln for ln in RAPPORT_CONFORME.splitlines() if not ln.startswith(manquante)
    )
    contexte = _rapport(tmp_path, _user("corrige"), _edit("engine/x.py"), _say(ampute))
    assert contexte is not None and manquante in contexte


@pytest.mark.parametrize("edite", ["engine/x.py", WORKTREE_FILE])
def test_un_chemin_relatif_est_refuse_ou_que_l_on_travaille(tmp_path: Path, edite: str) -> None:
    """Défaut mesuré le 2026-08-08 : une review entière rendue sur le dépôt principal.

    Le paramètre `WORKTREE_FILE` n'est pas le cas intéressant — c'est `engine/x.py` : une session
    worktree qui ne touche QUE le dépôt principal n'est pas distinguable d'une session normale
    depuis les fichiers édités. L'exigence ne peut donc pas être conditionnelle.
    """
    relatif = RAPPORT_CONFORME.replace("/home/greg/40k/engine/x.py", "engine/x.py")
    contexte = _rapport(tmp_path, _user("corrige"), _edit(edite), _say(relatif))
    assert contexte is not None and "ABSOLUS" in contexte


@pytest.mark.parametrize("argument", ["high", "--fix", "1234"])
def test_un_argument_qui_n_est_pas_un_chemin_ne_declenche_rien(
    tmp_path: Path, argument: str
) -> None:
    """Niveau d'effort, option, numéro de PR : ce que ces commandes acceptent en plus des chemins."""
    avec = RAPPORT_CONFORME.replace("/code-review ", f"/code-review {argument} ")
    assert _rapport(tmp_path, _user("corrige"), _edit("engine/x.py"), _say(avec)) is None


def test_un_prompt_copiable_n_est_pas_pris_pour_le_bloc_relire(tmp_path: Path) -> None:
    """PROMPTS contient des prompts COPIABLES, donc souvent une commande en début de ligne.

    Balayer tout le message reprochait au rapport des chemins relatifs qui n'étaient pas les siens.
    """
    prompt_copiable = (
        "PROMPTS :\n  1. relire le module\n     ```\n     RELIRE :\n"
        "     /code-review engine/y.py\n     /simplify engine/y.py\n     ```\n"
    )
    # PROMPTS précède RELIRE dans le gabarit : le bloc du prompt est rencontré EN PREMIER, donc
    # « prendre la première étiquette » ne suffit pas — ce sont les ``` qui tranchent.
    assert _rapport(
        tmp_path, _user("corrige"), _edit("engine/x.py"),
        _say(prompt_copiable + RAPPORT_CONFORME),
    ) is None


PROMPT_TRONQUE = "PROMPTS :\n  1. corriger le module\n     ```\n     lire engine/y.py\n"


@pytest.mark.parametrize("avant", [True, False])
def test_un_bloc_de_code_non_referme_est_signale_et_non_avale(tmp_path: Path, avant: bool) -> None:
    """Une fence ``` jamais refermée faisait disparaître TOUT ce qui la suit, RELIRE comprise.

    Le hook répondait alors « la section RELIRE est absente » sur un rapport qui la contenait :
    diagnostic faux sur un défaut réel, donc l'agent corrigeait la mauvaise chose. Le paramètre
    `avant=False` est le cas qui le prouve : RELIRE y est complète AVANT le bloc ouvert, et rien
    dans le message ne manque — seule la fence est en trop.
    """
    message = PROMPT_TRONQUE + RAPPORT_CONFORME if avant else RAPPORT_CONFORME + PROMPT_TRONQUE
    contexte = _rapport(tmp_path, _user("corrige"), _edit("engine/x.py"), _say(message))
    assert contexte is not None and "jamais refermé" in contexte
    assert "RELIRE est absente" not in contexte


def test_un_bloc_non_referme_est_signale_meme_sans_fichier_de_code(tmp_path: Path) -> None:
    """Le cas où le hook se TAISAIT : tour doc-only, donc RELIRE hors de portée.

    Un message doc-only dont la fence orpheline enferme `LU :` et `JUMEAU :` n'a AUCUNE section
    visible hors des blocs, et le contrôle de RELIRE — seul endroit qui disait la malformation —
    n'est pas exécuté. Le hook ne sortait alors rien du tout : garde-fou muet, indistinguable d'un
    rapport conforme.
    """
    message = "Fait.\n\nPROMPTS :\n  1. sujet\n     ```\n     LU : x\n     JUMEAU : grep -> 0\n"
    contexte = _rapport(tmp_path, _user("corrige la doc"), _edit("Documentation/x.md"),
                        _say(message))
    assert contexte is not None and "jamais refermé" in contexte


A_ESPACE = "/home/greg/40k/shared/gameLogStructure - save.ts"


@pytest.mark.parametrize("forme", [f"'{A_ESPACE}'", f'"{A_ESPACE}"'])
def test_un_chemin_absolu_contenant_une_espace_est_acceptable_s_il_est_cite(
    tmp_path: Path, forme: str
) -> None:
    """`shared/gameLogStructure - save.ts` existe dans ce dépôt : il doit avoir une forme écrivable.

    Cité, il gardait ses guillemets et passait pour relatif — donc le hook réclamait sans fin sur
    un rapport correct. Les DEUX guillemets comptent : `relire-en-attente.sh --liste` rend du
    `shlex.quote`, qui produit des guillemets SIMPLES, et l'agent recopie cette sortie telle quelle ;
    un agent qui écrit le chemin à la main met plutôt des doubles.
    """
    espace = RAPPORT_CONFORME.replace("/home/greg/40k/engine/x.py", forme)
    assert _rapport(tmp_path, _user("corrige"), _edit("engine/x.py"), _say(espace)) is None


def test_un_chemin_a_espace_ECRIT_NU_est_refuse_avec_le_moyen_de_le_corriger(
    tmp_path: Path,
) -> None:
    """DÉCISION : le nu reste refusé, et le refus DIT qu'il faut citer.

    Le rattraper — recoller au chemin précédent tout fragment sans `/` — ferait passer
    `/code-review /abs/x.py engine`, c'est-à-dire le chemin relatif du 2026-08-08 exactement.
    Rien ne distingue les deux lectures, donc on garde celle qui protège. Reste que le diagnostic
    nu (« ABSOLUS — vu : -, save.ts ») n'indiquait pas la forme à écrire : c'est ce que verrouille
    la seconde assertion.
    """
    nu = RAPPORT_CONFORME.replace("/home/greg/40k/engine/x.py", A_ESPACE)
    contexte = _rapport(tmp_path, _user("corrige"), _edit("engine/x.py"), _say(nu))
    assert contexte is not None and "ABSOLUS" in contexte
    # Le libellé EXACT du hook : `"CITE" in contexte.upper()` était satisfait par le mot
    # « explicite » de n'importe quel autre diagnostic, donc l'assertion ne regardait rien.
    assert "ESPACE se CITE" in contexte


def test_un_repertoire_relatif_est_refuse_comme_un_fichier(tmp_path: Path) -> None:
    """`engine` n'a ni point ni slash : trié par ressemblance, il passait pour un mot ordinaire."""
    dossier = RAPPORT_CONFORME.replace("/home/greg/40k/engine/x.py", "engine")
    contexte = _rapport(tmp_path, _user("corrige"), _edit("engine/x.py"), _say(dossier))
    assert contexte is not None and "ABSOLUS" in contexte


def test_modification_de_doc_seule_n_exige_pas_relire(tmp_path: Path) -> None:
    doc = "Fait.\n\nLU : CLAUDE.md en entier\nJUMEAU : grep -c foo -> 0 hit\n"
    assert _rapport(tmp_path, _user("corrige la doc"), _edit("Documentation/x.md"),
                    _say(doc)) is None


def test_modification_de_doc_exige_quand_meme_lu_et_jumeau(tmp_path: Path) -> None:
    assert _rapport(tmp_path, _user("corrige la doc"), _edit("Documentation/x.md"),
                    _say("fait.")) is not None


def test_un_tour_qui_n_edite_qu_un_notebook_doit_quand_meme_son_rapport(tmp_path: Path) -> None:
    """`NotebookEdit` nomme son argument `notebook_path` : lu nulle part, le tour passait pour vide.

    Un tour vu comme sans modification ne se fait réclamer AUCUNE section — ni LU, ni JUMEAU.
    """
    carnet = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "name": "NotebookEdit",
                    "input": {"notebook_path": "ai/explore.ipynb"},
                }
            ],
        },
    }
    contexte = _rapport(tmp_path, _user("corrige le carnet"), carnet, _say("c'est corrigé."))
    assert contexte is not None and "LU" in contexte


def test_edition_d_un_sous_agent_n_engage_pas_le_rapport(tmp_path: Path) -> None:
    assert _rapport(tmp_path, _user("cherche"), _edit("engine/x.py", sidechain=True),
                    _say("rien trouvé.")) is None


def test_un_tour_de_lecture_ne_reveille_pas_le_tour_d_avant(tmp_path: Path) -> None:
    """Le rapport rendu au tour N ne doit pas être re-réclamé au tour N+2."""
    assert (
        _rapport(tmp_path, _user("q1"), _edit("engine/x.py"), _say(RAPPORT_CONFORME),
                 _user("q2"), _say("juste une réponse"))
        is None
    )


def test_un_retour_d_outil_ne_decoupe_pas_le_tour(tmp_path: Path) -> None:
    """Sinon le dernier morceau — qui porte le rapport — masquerait les éditions d'avant."""
    contexte = _rapport(tmp_path, _user("corrige"), _edit("engine/x.py"), _tool_result(),
                        _edit("engine/y.py"), _tool_result(), _say("fait."))
    assert contexte is not None


def test_tour_vide_du_prompt_qui_vient_d_arriver_est_ecarte(tmp_path: Path) -> None:
    """Le prompt soumis peut déjà figurer au transcript : le tour à juger est le dernier NON vide."""
    contexte = _rapport(
        tmp_path, _user("corrige"), _edit("engine/x.py"), _say("c'est fait."),
        _user("et ensuite ?")
    )
    assert contexte is not None and "PRÉCÉDENT" in contexte


# -------------------------------------------------------------------------------- hook PreToolUse


@pytest.mark.parametrize(
    "command",
    [
        "python3 -m pytest tests/unit/ -q -n 8 --dist worksteal",
        "source .venv/bin/activate && python3 -m pytest tests/",
        "pytest",
        "pyright",
        "npx biome check frontend/src",
        "(cd frontend && npx tsc --noEmit -p tsconfig.app.json)",
        "p ai/hidden_action_finder.py",
        "python3 scripts/check_ai_rules.py",
    ],
)
def test_verification_large_refusee(command: str) -> None:
    verdict = _run_deny(command)
    assert verdict is not None
    assert verdict["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.parametrize(
    "command",
    [
        "pytest tests/unit/engine/test_x.py",
        "source .venv/bin/activate && pytest tests/unit/ai/test_y.py -q",
        "pyright engine/x.py",
        "npx biome check frontend/src/utils/replayParser.ts",
        "python3 ai/train.py --agent CoreAgent --scenario bot --step",
        "grep -rn foo engine/",
        "git status --short",
        # Délégation ponctuelle : le marqueur ouvre la porte, et lui seul.
        "python3 -m pytest tests/unit/ -q -n 8  # VERIF-LARGE-AUTORISEE",
        "pyright  # VERIF-LARGE-AUTORISEE",
    ],
)
def test_verification_ciblee_et_delegation_passent(command: str) -> None:
    assert _run_deny(command) is None


# ------------------------------------------------- liste des fichiers restant à relire (PostToolUse)


CLAUDE_MD_MINIMAL = (
    "SECTIONS EXIGÉES : `LU`=toujours, `RELIRE`=code\n"
    "FICHIERS COMPTÉS COMME CODE : `.py`, `.sh`, `CLAUDE.md`\n"
)


def _bac(tmp_path: Path, claude_md: str = CLAUDE_MD_MINIMAL) -> Path:
    """Copie des deux hooks dans un faux dépôt : la vraie liste de session ne doit pas bouger.

    `relire-en-attente.sh` lit ce qui compte comme du code DANS son voisin, qui le lit dans
    CLAUDE.md : le bac reproduit donc les trois pièces, sinon on ne teste pas le vrai chemin.
    """
    hooks = tmp_path / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    shutil.copy(H_ATTENTE, hooks / H_ATTENTE.name)
    shutil.copy(H_RAPPORT, hooks / H_RAPPORT.name)
    (tmp_path / "CLAUDE.md").write_text(claude_md, encoding="utf-8")
    return hooks / H_ATTENTE.name


def _edite(hook: Path, chemin: str, session: str = S1, cwd: Path | None = None) -> str:
    """Rejoue un PostToolUse d'édition. Rend ce que le hook a écrit sur stdout.

    `cwd` compte : un chemin RELATIF dans le payload ne se résout que par rapport à lui.
    """
    proc = subprocess.run(
        [str(hook)],
        input=json.dumps({"session_id": session, "tool_input": {"file_path": chemin}}),
        capture_output=True,
        text=True,
        check=True,
        cwd=str(cwd) if cwd else None,
    )
    return proc.stdout


def _cmd(hook: Path, *args: str) -> subprocess.CompletedProcess:
    """Appel en ligne de commande, SANS check : l'échec fait partie de ce qu'on vérifie."""
    return subprocess.run([str(hook), *args], capture_output=True, text=True)


def _en_attente(hook: Path, session: str = S1) -> list[str]:
    """Ce que `--liste` rend. Échec = liste absente, distinct d'une liste vide (il n'en existe pas).

    `--liste` prend aussi un INSTANTANÉ de ce qu'il rend : c'est ce que `--vider` aura le droit
    d'effacer. Les tests qui vérifient une liste passent donc par le même chemin que la production.
    """
    proc = _cmd(hook, "--liste", session)
    assert proc.returncode == 0, proc.stderr
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


def _fichier_liste(tmp_path: Path, session: str = S1) -> Path:
    """Le fichier de liste, tel que le hook le nomme. Sa disposition ne se recopie pas de test en
    test : elle vient de `relire-en-attente.sh` (`DOSSIER` + `fichier_de_session`).

    Normalisé, parce que le session_id peut porter des `..` : le chemin rendu est alors celui où
    l'écriture atterrit RÉELLEMENT, hors du bac, et pas une forme qui le laisse croire dedans.
    """
    return Path(os.path.normpath(tmp_path / ".claude" / "relire-en-attente" / f"{session}.txt"))


def _lignes_brutes(tmp_path: Path, session: str = S1) -> list[str]:
    """Le CONTENU du fichier de liste, sans passer par `--liste`, `[]` s'il n'existe pas.

    La lecture du hook refiltre ce qu'elle rend : un contrôle qui s'en tient à `--liste` ne voit
    donc pas ce que l'ÉCRITURE a laissé entrer (prouvé par mutation le 2026-08-12).
    """
    fichier = _fichier_liste(tmp_path, session)
    if not fichier.exists():
        return []
    return fichier.read_text(encoding="utf-8").splitlines()


def test_un_fichier_de_code_entre_dans_la_liste(tmp_path: Path) -> None:
    hook = _bac(tmp_path)
    assert _edite(hook, str(tmp_path / "engine" / "x.py")) == ""  # aucun bruit sur stdout
    assert _en_attente(hook) == [str(tmp_path / "engine" / "x.py")]


def test_les_chemins_notes_sont_toujours_absolus(tmp_path: Path) -> None:
    """Un relatif s'interprète depuis le cwd de la review, pas depuis le dépôt édité (2026-08-08).

    Le cas qui a motivé la règle : une session worktree qui touche AUSSI le dépôt principal. Noté
    en relatif, `CLAUDE.md` désignerait la copie du worktree — et `rapport-cloture.sh` rejetterait
    le bloc RELIRE, les deux hooks se contredisant sur la liste que l'un produit pour l'autre.
    """
    hook = _bac(tmp_path)
    (tmp_path / "engine").mkdir()
    # Entrée RELATIVE, cwd = le dépôt : c'est le seul cas où la conversion peut échouer. L'alimenter
    # en chemins déjà absolus laissait `chemin_note` réduite à `return chemin` passer tous les tests.
    _edite(hook, "engine/x.py", cwd=tmp_path)
    _edite(hook, str(tmp_path / ".claude" / "worktrees" / "sujet" / "engine" / "y.py"))
    assert _en_attente(hook) == [
        str(tmp_path / "engine" / "x.py"),
        str(tmp_path / ".claude" / "worktrees" / "sujet" / "engine" / "y.py"),
    ]


@pytest.mark.parametrize("section", ["LU", "JUMEAU", "COUVERTURE"])
def test_une_section_citee_dans_un_prompt_ne_tient_pas_lieu_de_rapport(
    tmp_path: Path, section: str
) -> None:
    """Jumeau du filtrage des commandes : un prompt copiable cite volontiers `LU :` ou `JUMEAU :`.

    Cherchées dans le message brut, ces citations satisfaisaient l'exigence sans que le rapport
    porte la ligne — le contrôle disait alors « conforme » sur un rapport amputé.
    """
    ampute = "\n".join(
        ln for ln in RAPPORT_CONFORME.splitlines() if not ln.startswith(section)
    )
    avec_prompt = ampute + f"\nPROMPTS :\n  1. sujet\n     ```\n     {section} : ...\n     ```\n"
    contexte = _rapport(tmp_path, _user("corrige"), _edit("engine/x.py"), _say(avec_prompt))
    # Le diagnostic NOMMÉ, pas la simple présence du mot : `"LU" in contexte` est satisfait par
    # « ABSOLUS » d'un défaut voisin, donc un autre défaut sur la même entrée verdissait le test
    # sans que la section manquante ait jamais été réclamée.
    assert contexte is not None and f"la ligne {section} est absente" in contexte


def test_un_chemin_a_espace_sort_sous_une_forme_que_le_voisin_accepte(tmp_path: Path) -> None:
    """Les deux hooks doivent se boucler : ce que `--liste` produit, `rapport-cloture.sh` l'accepte.

    Sans échappement, `.../gameLogStructure - save.ts` sortait nu, se coupait en trois mots relatifs
    à la relecture du rapport, et l'agent n'avait aucune forme acceptable à écrire.
    """
    hook = _bac(tmp_path)
    _edite(hook, str(tmp_path / "shared" / "gameLogStructure - save.py"))
    ligne = _cmd(hook, "--liste", S1).stdout.strip()
    assert " " in ligne, "le cas testé exige un chemin à espace"
    rapport = RAPPORT_CONFORME.replace("/home/greg/40k/engine/x.py", ligne)
    # Le fichier ÉDITÉ est dans le dépôt réel : sans ça, RELIRE ne serait pas due et le test ne
    # regarderait rien (le contrôle des chemins n'est atteint que si un fichier de code a bougé).
    assert _rapport(tmp_path, _user("corrige"), _edit("engine/x.py"), _say(rapport)) is None


def test_un_fichier_hors_liste_de_code_n_engage_aucune_relecture(tmp_path: Path) -> None:
    hook = _bac(tmp_path)
    _edite(hook, str(tmp_path / "Documentation" / "x.md"))
    assert _cmd(hook, "--liste", S1).returncode != 0  # aucune liste n'a été créée


@pytest.mark.parametrize("deja_ouverte", [False, True])
def test_un_fichier_hors_depot_n_entre_pas(tmp_path: Path, deja_ouverte: bool) -> None:
    """Constaté le 2026-08-12 : trois scripts jetables du scratchpad attendaient d'être relus.

    DEUX états d'écriture, parce que `ajouter()` ne fait pas le même geste : liste absente (le
    fichier est créé) et liste déjà ouverte (le chemin est concaténé). Le contrôle porte sur le
    FICHIER, pas sur ce que `--liste` rend : la lecture refiltre, donc une version qui écrivait
    le scratchpad restait verte tant qu'on n'inspectait que `--liste` (vérifié par mutation).
    """
    hook = _bac(tmp_path)
    deja = [str(tmp_path / "engine" / "x.py")] if deja_ouverte else []
    for chemin in deja:
        _edite(hook, chemin)
    _edite(hook, str(tmp_path.parent / "scratchpad_migrate.py"))
    assert _lignes_brutes(tmp_path) == deja


def test_ce_qui_compte_comme_du_code_vient_de_claude_md(tmp_path: Path) -> None:
    """VERROU de la source unique : ce hook ne redéfinit pas sa propre liste de suffixes."""
    hook = _bac(
        tmp_path,
        "SECTIONS EXIGÉES : `LU`=toujours, `RELIRE`=code\n"
        "FICHIERS COMPTÉS COMME CODE : `.toto`\n",
    )
    _edite(hook, str(tmp_path / "engine" / "x.py"))
    _edite(hook, str(tmp_path / "engine" / "x.toto"))
    assert _en_attente(hook) == [str(tmp_path / "engine" / "x.toto")]


def test_un_fichier_edite_deux_fois_ne_figure_qu_une_fois(tmp_path: Path) -> None:
    """Le point de la demande : un sujet dure plusieurs tours, la liste ne doit pas gonfler."""
    hook = _bac(tmp_path)
    for _ in range(3):
        _edite(hook, str(tmp_path / "engine" / "x.py"))
    _edite(hook, str(tmp_path / "engine" / "y.py"))
    assert _en_attente(hook) == [
        str(tmp_path / "engine" / "x.py"),
        str(tmp_path / "engine" / "y.py"),
    ]


def test_deux_sessions_ne_se_melangent_pas(tmp_path: Path) -> None:
    """Sinon la review d'un sujet emporterait les fichiers d'une session parallèle."""
    hook = _bac(tmp_path)
    _edite(hook, str(tmp_path / "engine" / "x.py"), session=S1)
    _edite(hook, str(tmp_path / "engine" / "autre.py"), session=S2)
    assert _en_attente(hook, S1) == [str(tmp_path / "engine" / "x.py")]
    assert _en_attente(hook, S2) == [str(tmp_path / "engine" / "autre.py")]


def test_vider_efface_ce_qui_a_ete_relu(tmp_path: Path) -> None:
    hook = _bac(tmp_path)
    _edite(hook, str(tmp_path / "engine" / "x.py"))
    _en_attente(hook)
    assert _cmd(hook, "--vider", S1).returncode == 0
    assert _cmd(hook, "--liste", S1).returncode != 0


def test_vider_garde_ce_qui_est_arrive_apres_le_liste(tmp_path: Path) -> None:
    """Sinon les corrections appliquées PAR la review sortent de la liste sans avoir été relues."""
    hook = _bac(tmp_path)
    _edite(hook, str(tmp_path / "engine" / "x.py"))
    _en_attente(hook)
    _edite(hook, str(tmp_path / "engine" / "corrige_par_la_review.py"))
    assert _cmd(hook, "--vider", S1).returncode == 0
    assert _en_attente(hook) == [str(tmp_path / "engine" / "corrige_par_la_review.py")]


def test_le_message_de_liste_vide_ne_compte_pas_ses_propres_fichiers(tmp_path: Path) -> None:
    """Compter sa propre liste et l'annoncer « d'autres sessions » envoie chercher un mauvais id."""
    hook = _bac(tmp_path)
    _edite(hook, str(tmp_path / "engine" / "x.py"))
    _en_attente(hook)
    _cmd(hook, "--vider", S1)
    _edite(hook, str(tmp_path / "engine" / "y.py"), session=S2)
    (tmp_path / ".claude" / "relire-en-attente" / f"{S1}.txt").write_text("", encoding="utf-8")
    assert "1 autre(s) session(s)" in _cmd(hook, "--liste", S1).stderr


def test_vider_echappe_ce_qu_il_rend_comme_le_liste(tmp_path: Path) -> None:
    """`--vider` rend ce qui reste à relire : cette sortie ira dans le prochain bloc RELIRE.

    Jumeau de `commande_liste` : la sortir nue redonnait un chemin à espace que le hook voisin
    refuse, dans le fichier même dont le commentaire dit avoir fermé ce défaut.
    """
    hook = _bac(tmp_path)
    _edite(hook, str(tmp_path / "engine" / "x.py"))
    _en_attente(hook)
    _edite(hook, str(tmp_path / "shared" / "gameLogStructure - save.py"))
    reste = _cmd(hook, "--vider", S1).stdout.strip()
    assert reste == shlex.quote(str(tmp_path / "shared" / "gameLogStructure - save.py"))


def test_vider_garde_un_fichier_que_la_review_vient_de_corriger(tmp_path: Path) -> None:
    """Le cas FRÉQUENT, pas le cas limite : la review corrige ce qu'elle relit (`--fix`, /simplify).

    Le fichier est déjà dans l'instantané ; seule sa VERSION a changé. Retenir les noms seuls
    effaçait donc chaque correction d'une liste où elle venait de rentrer, sans relecture.
    """
    hook = _bac(tmp_path)
    fichier = tmp_path / "engine" / "x.py"
    fichier.parent.mkdir()
    fichier.write_text("avant\n", encoding="utf-8")
    _edite(hook, str(fichier))
    _en_attente(hook)
    os.utime(fichier, (0, 0))  # la review a réécrit le fichier : mtime différent
    assert _cmd(hook, "--vider", S1).returncode == 0
    assert _en_attente(hook) == [str(fichier)]


def test_un_script_jetable_hors_depot_n_engage_pas_de_rapport(tmp_path: Path) -> None:
    """Les deux hooks doivent s'accorder : l'un réclamait RELIRE pour un fichier que l'autre exclut.

    Un `.py` de sonde écrit dans le scratchpad n'est pas du travail livrable — RELIRE n'a alors
    aucune liste à donner, et l'agent se retrouvait devant une exigence insatisfiable.
    """
    contexte = _rapport(
        tmp_path, _user("instrumente"), _edit("/tmp/ailleurs/sonde.py"), _say("fait.")
    )
    assert contexte is not None and "COUVERTURE" not in contexte and "RELIRE" not in contexte


def test_un_voisin_casse_est_signale_et_non_avale(tmp_path: Path) -> None:
    """Panne atteignable précisément sur les tours qui ÉDITENT le voisin.

    Un traceback nu sortirait rc=1 sans `additionalContext` : l'édition disparaîtrait de la liste
    sans que rien ne le dise.
    """
    hook = _bac(tmp_path)
    (hook.parent / H_RAPPORT.name).write_text("def config(:\n", encoding="utf-8")
    contexte = json.loads(_edite(hook, str(tmp_path / "engine" / "x.py")))
    assert "SyntaxError" in contexte["hookSpecificOutput"]["additionalContext"]


def test_vider_sans_liste_prealable_refuse(tmp_path: Path) -> None:
    """`--vider` n'efface que du relu : sans `--liste`, rien n'a été relu, donc rien à effacer."""
    hook = _bac(tmp_path)
    _edite(hook, str(tmp_path / "engine" / "x.py"))
    assert _cmd(hook, "--vider", S1).returncode != 0
    assert _en_attente(hook) == [str(tmp_path / "engine" / "x.py")]


def test_session_id_inconnu_echoue_au_lieu_de_rendre_une_liste_vide(tmp_path: Path) -> None:
    """Une faute d'un caractère sautait la relecture en silence, ou relisait le sujet d'avant."""
    hook = _bac(tmp_path)
    _edite(hook, str(tmp_path / "engine" / "x.py"))
    for commande in ("--liste", "--vider"):
        proc = _cmd(hook, commande, S2)
        assert proc.returncode != 0, commande
    assert _en_attente(hook) == [str(tmp_path / "engine" / "x.py")]


def test_argument_sans_flag_echoue(tmp_path: Path) -> None:
    """`relire-en-attente.sh <uuid>`, flag oublié : sortait 0 et vide, donc « rien à relire »."""
    hook = _bac(tmp_path)
    _edite(hook, str(tmp_path / "engine" / "x.py"))
    proc = _cmd(hook, S1)
    assert proc.returncode != 0 and "flag inconnu" in proc.stderr


def test_une_liste_ecrite_par_une_version_anterieure_est_reparee_a_la_lecture(
    tmp_path: Path,
) -> None:
    """7 listes de production portaient des chemins relatifs et des scripts jetables (2026-08-12).

    Elles ne peuvent pas être réécrites — elles appartiennent à d'autres sessions — donc c'est la
    LECTURE qui répare : sans ça, ces sessions écrivent un RELIRE que le hook voisin refuse, et
    relisent des scripts du scratchpad.
    """
    hook = _bac(tmp_path)
    liste = _fichier_liste(tmp_path)
    liste.parent.mkdir(parents=True)
    liste.write_text(
        f"engine/legacy.py\n/tmp/ailleurs/scratch.py\n{tmp_path / 'engine' / 'x.py'}\n",
        encoding="utf-8",
    )
    assert _en_attente(hook) == [
        str(tmp_path / "engine" / "legacy.py"),
        str(tmp_path / "engine" / "x.py"),
    ]


def test_doublon_arrive_par_concurrence_est_gomme_a_la_lecture(tmp_path: Path) -> None:
    """Deux éditions du même fichier dans un message = deux processus qui lisent la même liste.

    Le dédoublonnage à l'écriture ne peut pas les voir ; celui à la lecture, si. La liste est écrite
    à la main ici parce que la course elle-même n'est pas reproductible à volonté.
    """
    hook = _bac(tmp_path)
    _edite(hook, str(tmp_path / "engine" / "x.py"))
    liste = _fichier_liste(tmp_path)
    liste.write_text(liste.read_text(encoding="utf-8") * 2, encoding="utf-8")
    assert _en_attente(hook) == [str(tmp_path / "engine" / "x.py")]


@pytest.mark.parametrize("hook_teste", ["attente", "rapport"])
def test_flag_inconnu_echoue(tmp_path: Path, hook_teste: str) -> None:
    """Sans ça, `--list` tombait dans le chemin de hook : rc=0, stdout vide, aucun signe.

    Les deux hooks, parce qu'ils ont tous deux une interface en ligne de commande pour les tests et
    pour l'agent : le défaut a été trouvé sur l'un puis retrouvé tel quel sur l'autre.
    """
    hook = _bac(tmp_path)
    if hook_teste == "rapport":
        hook = hook.parent / H_RAPPORT.name
    proc = _cmd(hook, "--list")
    assert proc.returncode != 0 and "flag inconnu" in proc.stderr


@pytest.mark.parametrize("commande", ["--liste", "--vider"])
def test_session_id_omis_refuse_au_lieu_de_deviner(tmp_path: Path, commande: str) -> None:
    """Une seule liste présente NE prouve PAS qu'elle est la nôtre.

    Mesuré le 2026-08-12 : une session qui n'avait rien édité récupérait puis EFFAÇAIT la liste de
    la session parallèle, seule à avoir touché du code. Deviner est donc destructeur, pas pratique.
    """
    hook = _bac(tmp_path)
    _edite(hook, str(tmp_path / "engine" / "x.py"), session=S2)
    proc = _cmd(hook, commande)
    assert proc.returncode != 0 and "session_id" in proc.stderr
    assert _en_attente(hook, S2) == [str(tmp_path / "engine" / "x.py")]


@pytest.mark.parametrize("mauvais_id", ["scratchpad", "../../../evil"])
def test_un_id_non_conforme_est_refuse_a_l_ecriture_aussi(tmp_path: Path, mauvais_id: str) -> None:
    """Le contrôle manquait sur le chemin PostToolUse, celui qui écrit.

    Conséquences mesurées : `scratchpad` (le mauvais composant du chemin) créait une liste que
    `--liste` refuse ensuite de lire — relecture perdue en silence — et `../../../evil` écrivait
    hors du dossier des listes.
    """
    hook = _bac(tmp_path)
    sortie = _edite(hook, str(tmp_path / "engine" / "x.py"), session=mauvais_id)
    assert "invalide" in json.loads(sortie)["hookSpecificOutput"]["additionalContext"]
    # Le chemin est CALCULÉ par paramètre, avec la formule du hook : `../../../evil` remonte de
    # trois crans depuis le dossier des listes et atterrit DEHORS, là où aucun balayage du bac ne
    # le voit. Un contrôle qui ne regarde que le bac reste vert sur le hook non corrigé pour
    # exactement le cas le plus grave — c'est le vert vacant que ce calcul supprime.
    ecrit = _fichier_liste(tmp_path, mauvais_id)
    assert not ecrit.exists(), f"liste écrite en {ecrit}"
    # Et nulle part ailleurs dans le bac, au cas où le nom retenu ne serait pas celui calculé.
    assert not list(tmp_path.rglob("*.txt"))


def test_session_id_qui_est_un_chemin_est_refuse(tmp_path: Path) -> None:
    """L'id nomme un fichier : un chemin le ferait sortir du dossier des listes."""
    hook = _bac(tmp_path)
    proc = _cmd(hook, "--liste", str(tmp_path / "ailleurs"))
    assert proc.returncode != 0 and "invalide" in proc.stderr


def test_une_edition_de_notebook_entre_aussi_dans_la_liste(tmp_path: Path) -> None:
    """`NotebookEdit` nomme son argument `notebook_path` : la brancher sur `file_path` la perdait."""
    hook = _bac(
        tmp_path,
        "SECTIONS EXIGÉES : `LU`=toujours, `RELIRE`=code\nFICHIERS COMPTÉS COMME CODE : `.ipynb`\n",
    )
    carnet = tmp_path / "ai" / "explore.ipynb"
    proc = subprocess.run(
        [str(hook)],
        input=json.dumps({"session_id": S1, "tool_input": {"notebook_path": str(carnet)}}),
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.stdout == ""
    assert _en_attente(hook) == [str(carnet)]


def test_session_id_absent_du_payload_est_signale_et_non_ignore(tmp_path: Path) -> None:
    """Se taire laisserait croire la relecture à jour avec une liste vide (T1)."""
    hook = _bac(tmp_path)
    proc = subprocess.run(
        [str(hook)],
        input=json.dumps({"tool_input": {"file_path": str(tmp_path / "engine" / "x.py")}}),
        capture_output=True,
        text=True,
        check=True,
    )
    contexte = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "ne peut pas être tenue" in contexte


def test_config_illisible_est_signalee_et_non_ignoree(tmp_path: Path) -> None:
    """Même exigence que son voisin : un garde-fou muet est indistinguable d'un tour conforme.

    Le message doit être DISTINCT de celui du session_id manquant : les deux pannes n'ont pas la
    même réparation, et un test qui ne les distingue pas laisse passer l'une pour l'autre.
    """
    hook = _bac(tmp_path, "plus aucune liste ici\n")
    contexte = json.loads(_edite(hook, str(tmp_path / "engine" / "x.py")))
    assert "n'a pas pu être mise à jour" in contexte["hookSpecificOutput"]["additionalContext"]


def test_ordre_des_deux_lignes_declaratives_est_indifferent(tmp_path: Path) -> None:
    """Elles sont VOISINES dans CLAUDE.md : leur ordre suffisait à tuer les deux garde-fous.

    Le garde anti-repli du voisin prenait la seconde déclaration pour la suite de la première, donc
    `config()` levait sur un fichier conforme — plus aucune section vérifiée, plus aucune liste
    tenue. Le test lit la config PAR le hook, sur les deux ordres.
    """
    hook = _bac(
        tmp_path,
        "FICHIERS COMPTÉS COMME CODE : `.py`, `CLAUDE.md`\n"
        "SECTIONS EXIGÉES : `LU`=toujours, `RELIRE`=code\n",
    )
    _edite(hook, str(tmp_path / "engine" / "x.py"))
    assert _en_attente(hook) == [str(tmp_path / "engine" / "x.py")]
    # Vérifié sur le CONTENU, pas sur un rc=0 : un `config()` entièrement cassé sortirait 0 aussi.
    voisin = hook.parent / H_RAPPORT.name
    cfg = json.loads(_cmd(voisin, "--config").stdout)
    assert cfg["sections"] == [["LU", "toujours"], ["RELIRE", "code"]]
    assert cfg["code_suffixes"] == [".py"] and cfg["code_basenames"] == ["CLAUDE.md"]


