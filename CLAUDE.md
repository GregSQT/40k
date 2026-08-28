CONTEXTE PROJET

PROJET : Warhammer 40K Game Engine avec IA (Reinforcement Learning)

Backend Python : Flask API (services/api_server.py)

Frontend : React + TypeScript + Vite

IA : Stable-Baselines3 PPO + MaskablePPO

Structure : engine/ moteur, ai/ entraînement, config/ configurations

Modèles IA : ai/models/<agent_key>/model_<agent_key>.zip

Configs agents : config/agents/<agent_name>/

Python : type hints, docstrings, respect Documentation/Reference/moteur/tour_de_jeu.md

Aucun fallback/workaround/default anti-erreur → T1

SOURCES DE VÉRITÉ / ROADMAP

Avant toute question de priorité, état d'un chantier ou « qu'est-ce qui reste » :
1. Lire Documentation/Roadmap/ROADMAP_INDEX.md (direction + ordre global)
2. Si détail d'un chantier spécifique → lire le fichier sujet correspondant
3. Pour l'historique d'un sujet → Documentation/Roadmap/archives/<sujet>.md

Fichiers par sujet (tâches ouvertes uniquement) :
- Documentation/Roadmap/v11_chemin_critique.md — pipeline V11 (cross-sujets)
- Documentation/Roadmap/training.md — entraînement IA
- Documentation/Roadmap/bot.md — panel de bots
- Documentation/Roadmap/analyzer.md — analyzer / couverture
- Documentation/Roadmap/front.md — frontend
- Documentation/Roadmap/moteur.md — moteur de jeu
- Documentation/Roadmap/infra.md — infra / perf / DB
- Documentation/Roadmap/capacites.md — chantier 06 capacités
- Documentation/Roadmap/doc.md — hygiène documentaire

Rôle des sources :

CODE : tranche ce qui est réellement implémenté ou non.

ROADMAP_INDEX.md : tranche l'ordre/priorité des chantiers, y compris contre V11_agent_rework.md §0.

Décision datée la plus récente : tranche l'approche retenue.

Chantiers/v11/ : détail/spec du programme V11.

Chantiers/backlog/ : contenu des chantiers ouverts (détail).

Reference/ : références vivantes par domaine ; Archives/chantiers/ : journaux des chantiers livrés.

Si aucune règle ci-dessus ne tranche : demander à l'utilisateur.

Cycle chantier : voir blocs **Discipline** et **Exceptions actées** de ROADMAP_INDEX.md (source unique).

RÈGLES 40K OFFICIELLES

SOURCE UNIQUE : Documentation/40k_rules/.
Ne jamais assumer une règle. Toute réponse/modification dépendant d'une règle 40K exige la lecture préalable du PDF pertinent avec Read.
En cas de contradiction code/règle, le PDF tranche la règle attendue.
PDFs : 01 Core concepts, 02 Datasheets, 03 Moving, 04 Making attacks, 05 Attack sequence, 06 Other concepts, 07 The battle round, 08 Command phase, 09 Movement phase, 10 Shooting phase, 11 Charge phase, 12 Fights pahse (typo dans le nom du fichier), 13 Terrain, 13-5 gone to ground (.jpg), 14 Objectives, 15 Stratagems, 16 Actions, 17 Monsters and vehicles, 18 Transports, 19 Attached units, 20 Strategic reserves, 21 Flying and surging, 22 Other rules and abilities, 23 Aircraft, 24 Core abilities, 25 Rules appendix.

ENVIRONNEMENT / COMMANDES

Toujours activer le venv avant Python :
source /home/greg/40k/.venv/bin/activate

Services :

backend : cd /home/greg/40k && python3 services/api_server.py (api, port 5001)

frontend : cd /home/greg/40k/frontend && npm run dev (app, port 5175)

redémarrer : ap

arrêter : stop

REDÉMARRAGE — ACQUIS : l'utilisateur relance toujours backend + frontend lui-même avant chaque essai PvP.
Donc l'agent ne demande/propose/rappelle jamais de redémarrer, ne lance jamais ap/api/app/stop, et ne diagnostique jamais un échec par « ancien code encore chargé ».
Si un changement nécessite redémarrage : écrire seulement actif au prochain ap à la fin.

ENTRAÎNEMENT IA

<X> = résolution 1 ou 5.
Entraîner :
python3 ai/train.py --agent ArmageddonAgent --training-config x<X> --scenario bot --resolution <X> --new

Évaluer le modèle existant sur HOLDOUT :
python3 ai/train.py --agent ArmageddonAgent --training-config x<X> --resolution <X> --test-only --step

--test-only n'entraîne RIEN et laisse le modèle intact.

--step écrit step.log.

--new écarte le modèle existant.

--append exige un modèle existant et le remplace par le résultat du run.

pour entraîner lorsqu'un modèle existe, ne jamais choisir implicitement entre --new et --append.

Analyser : python3 ai/analyzer.py <fichier_de_résultats>.
Qualité/performance PPO : validation par HOLDOUT + --step + analyzer.py + replay ; cela ne remplace jamais pytest/vitest pour les invariants logiciels.

TESTS — QUI LANCE QUOI

VÉRIFICATION LARGE = utilisateur uniquement :
python3 -m pytest tests/unit/ -q -n 16 --dist worksteal ; python3 -m pytest tests/integration/pvp/ -q -n 6 --dist load ; pyright ; p ai/hidden_action_finder.py ; p scripts/check_ai_rules.py ; npx biome check frontend/src ; (cd frontend && npx tsc --noEmit -p tsconfig.app.json)

L'agent ne la lance JAMAIS, ni en totalité, ni par recomposition/contournement. .claude/hooks/deny-verif-large.sh juge chaque segment séparé par ;, &&, |; le contourner ou le désactiver est interdit.
L'agent vérifie CE QU'IL A TOUCHÉ, rien d'autre, et DOIT lancer les fichiers de test ciblés qu'il vient d'écrire/toucher :

Python : pytest tests/unit/engine/test_xxx.py

Front : cd frontend && npx vitest run src/.../xxx.test.ts
Si une validation large semble nécessaire : le dire et s'arrêter ; ne jamais annoncer « suite verte » sans l'avoir réellement obtenue.
scripts/check_ai_rules.py et ai/hidden_action_finder.py appartiennent à la vérification utilisateur.

WORKTREES

Avant la PREMIÈRE écriture de code : vérifier git status --short.
Tree propre → EnterWorktree directement, nom décrivant le sujet.
Tree sale → signaler (les modifications locales ne suivent pas le worktree) et attendre.
Lecture/analyse/doc seule → pas de worktree.
Glissement analyse → écriture : dès que l'intention d'écrire un fichier code apparaît, re-vérifier git status + ouvrir le worktree AVANT ce write, même si la tâche a commencé en lecture pure. Le hook check-worktree-before-write.sh bloque tout write de fichier code dans main ; un refus du hook = ouvrir le worktree, pas contourner le hook.
Fin : à la clôture de chaque chantier, sans attendre de demande : commit → ExitWorktree "keep" → merge dans main → supprimer worktree + branche → mettre à jour ROADMAP_INDEX.md + fichier sujet → déplacer le doc du chantier dans Archives/chantiers/.
Jamais remove avant merge. discard_changes: true interdit.
Training en cours → ne toucher aucun JSON de config/ (relu à chaud par les évaluations).

WORKFLOW IA

Ne jamais modifier automatiquement :

config/users.db

ai/models/**/*.zip

MODE UNIQUE : AUTO

AUTO est permanent ; aucun marqueur [MODE ...].
L'agent travaille jusqu'à résolution complète, décision utilisateur réellement nécessaire ou STOP imposé ci-dessous.
T1–T4 ne sont JAMAIS relâchées.
Avant modification : établir cause/hypothèse, plan et périmètre.
Autorisé : commandes prévues par le prompt, relance automatique après fix, plusieurs modifications liées, lectures nécessaires, recherche ciblée de motifs/jumeaux/appelants.
Toujours respecter l'ordre, les checkpoints de validation et les listes de fichiers explicitement imposés par le prompt ; vérifier après chaque modification avant de poursuivre.
Interdit : exploration par curiosité ; refactor non demandé sauf nécessité causale pour fermer T2.
Prompt ambigu ou contradictoire → présenter la contradiction, demander de trancher, ne pas choisir.

UNE SEULE RÉPONSE, À LA FIN

Ne rien adresser à l'utilisateur pendant le travail.
Exceptions : question bloquante, worktree (tree sale au premier tour), STOP imposé par ce fichier, checkpoint T3 (cause établie → stop avant écriture). Dans ces cas, répondre puis s'arrêter.
Sinon, tout ce que l'utilisateur doit lire est dans le message final.

STYLE

Français, tutoiement, direct, strictement la demande ; pas d'étapes supplémentaires non sollicitées ; pas d'artifact/document/fichier/canvas sans demande explicite ; pas d'intro/conclusion générique ni « n'hésite pas » ; si 3 phrases suffisent, pas 3 paragraphes ; oui/ok → ne pas développer ; expliquer simplement et précisément ce qui a été fait. Être concis dans la réponse, pas dans le travail : pas de narration d'outils/étapes, pas de code recopié sauf preuve verbatim exigée par T4 REVIEW. Lecture, appelants, mesure, grep jumeau, tests, rouge/vert, vrai chemin ne se coupent jamais pour économiser.
La concision ne réduit jamais le périmètre de conception ; une solution choisie seulement parce qu'elle est plus courte à expliquer est un défaut.
Réponse analytique (investigation, arbitrage) : conclusion en une phrase d'abord, puis ce qui est attendu de l'utilisateur si nécessaire, puis détail. Jamais un mur de texte non structuré avant les sections de rapport.
ÉTAT DU CODE : ne jamais supposer ; lire/vérifier avant d'affirmer ; pas de devrait, probablement, je pense que sur le code.
Estimations/architecture/opinions : incertitude explicite autorisée.
AVIS EXPERT : signaler une meilleure approche lorsqu'elle existe ; ne pas valider par défaut.
Suppression de code → commentaire seulement si contre-intuitive (contrôle retiré sciemment, branche condamnée) ; sinon git suffit, pas de commentaire-tombeau.

MODÈLE / EFFORT

Recommander Opus 5 uniquement si : refactor >3 fichiers interdépendants, architecture irréversible, ou bug impliquant 3+ systèmes.
Format : 🔴🔴🔴 Modèle suggéré : Opus 5 — [critère exact rempli] 🔴🔴🔴
Recommander effort high uniquement si : algorithme à cas limites complexes ou raisonnement multi-étapes à dépendances croisées.
Format : 🟡🟡🟡 Effort suggéré : high — [critère exact rempli] 🟡🟡🟡
Sinon Sonnet 5 ; ne rien afficher. Les deux bannières peuvent coexister.

T1 — AUCUN FALLBACK / WORKAROUND ANTI-ERREUR

Jamais de fallback, workaround ou default destiné à masquer/éviter une erreur.
Corriger la root cause. Donnée obligatoire absente → erreur explicite.
Fallback autorisé seulement comme comportement métier réellement valide.

T2 — CLÔTURE COMPLÈTE

Périmètre — trois états :
A. APPARTIENT AU SUJET : demandé explicitement, nécessaire au workflow, ou critère T2 rempli → traiter MAINTENANT ; interdit de le transformer en TODO/dette/prompt/« plus tard ».
B. HORS SUJET : aucun critère T2 → ne pas modifier ; bug prouvé = PROMPTS ; simple suspicion = une ligne dans LU.
C. APPARTIENT AU SUJET MAIS IMPOSSIBLE : uniquement dépendance externe, donnée indisponible ou décision utilisateur → STOP avec raison précise. Trop long, changement d'algorithme, hors chemin critique ne sont jamais des impossibilités.

Un sujet se ferme complètement : root cause + correction + impacts + jumeaux + appelants + tests + doc/config + suppression des instruments temporaires.
Ne pas livrer une solution inférieure si une meilleure solution a été identifiée et vérifiée. Documenter un manque ≠ le traiter.
Ne jamais annoncer une action avant exécution + vérification (relecture/grep/git selon le cas).
Une livraison qui rend un état/document faux doit le mettre à jour dans la même livraison.

Périmètre de clôture

Corriger X autorise ET oblige à traiter tout ce que X rend faux : jumeaux, appelants, tests, docs, configs ; miroirs fréquents : tir/mêlée, move/charge/fight, IA/PvP, moteur/replay/analyzer, front/back.
Un fichier entre automatiquement si AU MOINS UN critère objectif est prouvé :

compile/type/import cassé ;

test rouge ;

même motif prouvé par grep ;

doc/config directe du symbole/comportement touché.
Chaque fichier ajouté via T2 doit avoir son critère identifiable.
N'entrent jamais « tant qu'on y est » : renommage, découpage, style, refactor non nécessaire, amélioration d'un code correct, défaut indépendant, curiosité.
Si l'investigation AVANT écriture révèle >~5 fichiers hors tests/docs mécaniquement liés, ou un changement d'architecture significatif → STOP, annoncer le périmètre avant modification.
Pour un fichier réellement T2, interdit : TODO, dette, plus tard, hors périmètre, laissé en l'état, à valider par l'utilisateur ; soit traité, soit impossibilité C ci-dessus.
ARBITRAGE/PROMPTS ne servent jamais à externaliser du travail T2 faisable.

T3 — INVESTIGATION AUTONOME

Toute demande d'analyse/bug/root cause autorise immédiatement toutes les LECTURES nécessaires : Read, Grep, Glob, appelants, logs, flux d'exécution, fichiers non nommés initialement.
Ne jamais demander « veux-tu que j'investigue ? » ni interrompre l'investigation pour demander de continuer.
Checkpoint dès que la cause est établie avec preuves suffisantes pour exclure les hypothèses concurrentes raisonnables : répondre avec cause (fichier:ligne), plan de correction, périmètre T2 prévu → s'arrêter et attendre. L'écriture démarre au tour suivant.
Autres arrêts :

donnée/log/exécution inaccessible indispensable → demander précisément ;

investigation approfondie sans cause claire → reconnaître l'échec et donner les pistes restantes.

T4 — DIAGNOSTIC

Ne rien corriger tant que la cause n'est pas suffisamment prouvée. Hypothèse ≠ cause.
Avant correction : remonter les appelants, lire le code, identifier fichier:ligne, vérifier le chemin réel.
Si mesurable, mesurer plutôt que déduire : instrumenter/exécuter/compter. semble faire X ne vaut pas exécuté, obtenu X.
Si le symptôme utilisateur est faux/incomplet : le dire avec preuve ; ne pas chercher uniquement là où il pointe.
Toujours distinguer vérifié / non vérifié ; non exploré ≠ sain ; ne jamais affirmer avoir exécuté ce qui ne l'a pas été.

Après CHAQUE correction : grep symbole/motif, rechercher les miroirs, examiner chaque occurrence, traiter celles appartenant à T2, rapporter hits traités/écartés + raison ; même 0 hit doit être rapporté.
Toujours vérifier que le vrai chemin de production atteint le code corrigé. Code testé mais jamais appelé = correction non prouvée.

T4 — TESTS

Pour chaque correction d'invariant moteur : écrire/adapter le test → remettre le défaut → constater ROUGE → rétablir le fix → constater VERT → rapporter.
Test vert du premier coup ≠ verrou. Exception : parsing/formatage trivial où cette réintroduction n'apporte aucune preuve utile.
VERT VACANT : vérifier données présentes, énumération non vide, mutation appliquée, bonne valeur observée.
Le test construit son scénario ; jamais dépendre d'une graine, d'un ordre implicite ou d'une configuration absente.

Tout comportement modifié doit avoir un test automatisé dans la même livraison ; ce test entre automatiquement dans T2.
Harnais : Python → pytest (tests/unit/... ou tests/integration/..., référence fichier::test) ; TS/TSX → vitest *.test.ts(x) à côté du module, référence fichier > test.
Front uniquement → vitest, jamais pytest artificiel.
Feature sans test rencontrée : liée au code touché (même fonction/invariant/jumeau) → écrire le test MAINTENANT ; indépendante → ne pas toucher, signaler en COUVERTURE + PROMPTS.
--step, PvP, analyzer, navigateur ou script jetable ne remplacent jamais un test automatisé rejouable.

T4 — REVIEW

Finding valide = scénario concret (état/entrée → sortie fausse/crash/invariant violé sur chemin réellement atteint). Sans scénario : écarté, pas « mineur ».
PREUVE PAR LE FICHIER : recopier VERBATIM la ligne fautive ; citation incorrecte → finding écarté. Style/nommage/préférence architecturale sur code correct = pas des findings. Finding qui reconnaît le code correct mais projette un risque futur hypothétique (correct but, futur, compounding sans panne) = style → écarter.
Ancre hors diff → relire la zone du fichier ET nommer la ligne du diff qui la casse ; sinon écarter.
Review finie quand aucun finding AVEC scénario ne reste.

RAPPORT FINAL

Structure obligatoire, dans cet ordre exact :

1. EN-TÊTE (seulement si Bloqué ou Arbitrage requis) :
STATUT : Bloqué — <raison en 5 mots> | Arbitrage requis — <sujet en 5 mots>
À TOI : <action concrète attendue de l'utilisateur>

2. ARBITRAGE (immédiatement après l'en-tête, seulement si présent) — voir section dédiée.

3. MODIFICATIONS — pour CHAQUE fichier modifié (chemin relatif, sans lien markdown) :
MODIFICATIONS :
chemin/relatif/nom.py — une phrase changement + raison, sans code.
UNE PHRASE = une proposition principale, sans sous-clauses enchaînées par virgules ou parenthèses. Plusieurs fichiers sont autorisés s'ils sont prévus par le prompt ou T2 ; sinon STOP avant d'ajouter le fichier, le nommer, expliquer pourquoi il est nécessaire et attendre.

4. SECTIONS TECHNIQUES (chacune précédée d'une ligne ---) :

---
LU : <fichiers/appelants/miroirs où quelque chose a été trouvé ou décidé> — toujours.

---
JUMEAU : <grep> → <n> hits — toujours ; 0 hit valide ; détail (traité/écarté + raison) seulement si hits > 0.

---
RÉFS : <tests/docs/front/configs mis à jour ou volontairement laissés inchangés> — seulement si pertinent.

---
🟢 COUVERTURE : aucun trou vu ou 🔴 COUVERTURE : <trous vus> — si code modifié ; uniquement trous VUS non traités, jamais tests écrits.

---
RELIRE — si code modifié.
Pas de verdict vague (optimal, tout propre, doc à jour) ; uniquement des faits contrôlables. Validation locale ≠ verdict global.

---
ÉTAT CHANTIER : Tests <s> · Commité <s> · Mergé <s> · ROADMAP <s> · Doc <s>
Tests : ✅ (N verts) ou 🔴 (N rouges). Doc : ✅ déplacé dans Archives/chantiers/ · 🟡 à faire · ⚪ pas de doc chantier associé.
Symboles communs : ✅ fait · 🟡 à faire · 🔴 erreur/bloqué · ⚪ sans objet. Omis si aucun code écrit.

SUITE : 🟢 Tout est terminé
— ou —
SUITE :
→ Ce prompt : <actions 🟡 restantes>
→ 🔴 Bug : `"<prompt complet — voir gabarit Bug>"`
→ 🕳 Trou : `"<prompt complet — voir gabarit Trou>"`
→ 💡 Amélioration : `"<prompt complet — voir gabarit Amélioration>"`
→ 📋 Sous-tâche : `"<prompt complet — voir gabarit Sous-tâche>"`

Catégories : Bug = invariant cassé prouvé hors périmètre ; Trou = cas non couvert par les tests ; Amélioration = code correct mais optimisable ; Sous-tâche = morceau hors livraison.
Suspicion non prouvée → une ligne dans LU, aucune entrée SUITE. SUITE ne remplace jamais T2.
Si analyse seule (aucun fichier modifié) : SUITE uniquement, avec une proposition d'action concrète.

Gabarits SUITE — seulement si des entrées SUITE sont présentes : chaque prompt doit être autonome, lisible sans le contexte de la conversation, copiable-collable directement comme prochain prompt. Jamais une phrase vague ; toujours les références exactes.

🔴 Bug — champs obligatoires :
  Observation : comportement constaté (valeur obtenue, crash, invariant violé) — verbatim si possible.
  Fichier:ligne : ancre exacte dans le code (ex. engine/combat.py:142).
  Attendu : comportement correct selon règle ou contrat.
  Reproduction : état minimal pour déclencher le bug (scénario, appel, fixture).
  Périmètre T2 prévu : fichiers/tests à toucher pour corriger + vérifier.

🕳 Trou — champs obligatoires :
  Cas manquant : quel scénario ou branche n'est pas couvert.
  Fichier:ligne : fonction ou bloc concerné.
  Test à écrire : ce que le test doit mettre en scène et vérifier (entrée → sortie attendue).
  Harnais : pytest tests/unit/... ou vitest src/...

💡 Amélioration — champs obligatoires :
  Comportement actuel : ce que le code fait (correct mais sous-optimal).
  Proposition : changement concret à apporter.
  Fichiers concernés : liste des fichiers à modifier.
  Gain attendu : perf, lisibilité, conformité règle — mesurable si possible.
  Risque : ce qui pourrait régresser et comment le vérifier.

📋 Sous-tâche — champs obligatoires :
  Objectif : ce qui doit être livré à la fin.
  Contexte : pourquoi ce morceau a été séparé (dépendance manquante, décision utilisateur, taille).
  Périmètre : fichiers/modules concernés.
  Critère de clôture : condition vérifiable indiquant que c'est terminé (test vert, endpoint fonctionnel, etc.).

ARBITRAGE

Tout vrai choix de conception/architecture/mécanisme se présente au format ARBITRAGE. Ne rien faire compte seulement si défendable ; épouvantail interdit. Interdit de recommander « le plus rapide », « petit diff » ou « A maintenant, B plus tard » pour reporter une dette. Un ARBITRAGE qui décrit du travail T2 faisable est une dette déguisée.
Seulement pour vraie décision utilisateur ou vrai choix de conception à expliciter.
Chaque sujet : titre ; problème observable en 2–4 phrases max, lisible sans code ; TOUJOURS 3 options réelles de 1–2 lignes chacune avec gain + coût ; RECOMMANDATION : A/B/C + raison long terme argumentée en ≤3 phrases.
Pas de tableau, bloc code, sous-liste, jargon/noms de fonction inutiles ni chiffres de profiling dans le problème.
Une seule option réelle = décision, pas arbitrage. Jamais d'arbitrage pour reporter du travail T2 faisable.


RELIRE

Obligatoire dès qu'un fichier compté comme code a bougé ; omis pour lecture/doc/discussion.
/code-review : lancer via le Skill tool quand pertinent — ≥ 1 fichier dans engine/**, ai/**, services/**, frontend/src/** avec un changement de logique ou de comportement (ajout/suppression de code, modification d'une condition, d'un calcul, d'un flux). Ne pas lancer pour commentaire seul, typo dans une chaîne doc, renommage pur, test isolé ou config pure. Findings = 0 → ne pas afficher la section CODE REVIEW FINDINGS.
L'agent ne lance JAMAIS /simplify.
Liste : .claude/hooks/relire-en-attente.sh --liste <session_id> (UUID du dossier PARENT du scratchpad). Ne jamais lancer --vider, seulement le fournir. Si hook défaillant : liste manuelle.
Filtrage — exclus : config/**/*.json, *.md sauf CLAUDE.md, Documentation/** ; inclus sans exception : engine/**, ai/**, services/**, frontend/src/** ; zone grise (tests/**, scripts/**) : exclusion seulement avec justification.
🟢 = sujet fini. 🟡 = arbitrage(s) ouvert(s). Gros lot → scripts/review_plan.py. Chemins ABSOLUS ; guillemets si espace.

Format si /code-review lancé — bloc RELIRE :
🟢 RELIRE : <n> fichiers — /code-review lancé, findings ci-dessous
Puis, à la toute fin du rapport (après SUITE), hors de tout bloc fencé :
🔍 CODE REVIEW FINDINGS :
Suivi du bloc copiable (délimité par ```) commençant par :
Assures toi que ces findings de /code-review soient pertinents et que ta solution soit optimale avant de coder :

[VERDICT · category] /chemin/absolu:ligne — summary
  Scénario : failure_scenario

/simplify <chemins absolus>
.claude/hooks/relire-en-attente.sh --vider <session_id>

Format si /code-review non lancé :
🟢 RELIRE : <n> fichiers — /code-review (bugs) + /simplify (cleanup)
/code-review <chemins absolus>
/simplify <chemins absolus>
.claude/hooks/relire-en-attente.sh --vider <session_id>

HOOK RAPPORT

.claude/hooks/rapport-cloture.sh vérifie sections, forme RELIRE, chemins absolus et blocs fermés ; rien dans un bloc ne compte comme section.
Source unique : =toujours dès qu'un fichier est modifié ; =code seulement si code modifié.
Ces deux lignes sont la CONFIGURATION du hook, qui les LIT ici : format strict, backticks compris.
SECTIONS EXIGÉES : `LU`=toujours, `JUMEAU`=toujours, `COUVERTURE`=code, `RELIRE`=code, `ÉTAT CHANTIER`=code, `SUITE`=toujours
FICHIERS COMPTÉS COMME CODE : `.py`, `.pyi`, `.sh`, `.ts`, `.tsx`, `.js`, `.jsx`, `.mjs`, `.cjs`, `CLAUDE.md`, `settings.json`
Le hook s'exécute au PROMPT SUIVANT ; s'il réclame un rapport, il concerne le tour précédent : le rendre EN TÊTE sans relancer de travail.
