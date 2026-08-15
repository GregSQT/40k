=== CONTEXTE PROJET ===

PROJET : Warhammer 40K Game Engine avec IA (Reinforcement Learning)
- Backend Python : Flask API (services/api_server.py)
- Frontend : React + TypeScript + Vite
- IA : Stable-Baselines3 (PPO) avec MaskablePPO
- Structure : engine/ (moteur de jeu), ai/ (entraînement), config/ (configurations)

CONVENTIONS IMPORTANTES :
- Les modèles IA sont dans ai/models/<agent_key>/model_<agent_key>.zip
- Les configs d'agents sont dans config/agents/<agent_name>/
- Format de code : Python type hints, docstrings, respect AI_TURN.md
- Aucun fallback, workaround ni valeur par défaut pour masquer une erreur → voir T1

=== ROADMAP — QUOI FAIRE ENSUITE ===

SOURCE UNIQUE DE L'ORDRE DU TRAVAIL : Documentation/Implémentation/ROADMAP.md
→ Le LIRE avant toute question de priorité, d'état d'un chantier ou de « qu'est-ce qui reste ».
→ Trois dossiers, trois rôles, AUCUN ne donne l'ordre du travail :
  - 1_Agent/    : spec et état du programme V11 (détail d'une tranche, pièges de méthode)
  - A_faire/    : backlog des chantiers ouverts (contenu d'un chantier à faire)
  - Implémenté/ : chantiers livrés (référence de conception de ce qui est déjà fait)
→ Arbitrage entre docs qui se contredisent : (1) le CODE fait foi sur fait/pas fait,
  (2) la DÉCISION DATÉE la plus récente tranche l'approche, (3) sur les PRIORITÉS le ROADMAP
  l'emporte sur tout autre doc — y compris la colonne « Ordre » de V11_agent_rework.md §0 —
  et sur le DÉTAIL de V11 c'est l'inverse, (4) sinon → demander.
→ Ouvrir un chantier = y ajouter sa ligne D'ABORD. Le livrer = déplacer son doc en Implémenté/
  et mettre sa ligne à jour DANS la même livraison (règle T2 : un document rendu faux par sa
  propre livraison est une régression).

=== RÈGLES 40K OFFICIELLES ===

SOURCE UNIQUE DE VÉRITÉ : Documentation/40k_rules/
Ne jamais assumer une règle de jeu. En cas de doute ou de contradiction code/règles :
→ Lire le PDF correspondant avec l'outil Read AVANT de répondre.
→ Une réponse sur une règle sans lecture du PDF = réponse invalide.

PDFs disponibles (lire uniquement le(s) pertinent(s)) :
- 01 Core concepts / 02 Datasheets / 03 Moving / 04 Making attacks
- 05 Attack sequence / 06 Other concepts / 07 The battle round
- 08 Command phase / 09 Movement phase / 10 Shooting phase / 11 Charge phase
- 12 Fights phase / 13 Terrain / 14 Objectives / 15 Stratagems / 16 Actions
- 17 Monsters and vehicles / 18 Transports / 19 Attached units
- 20 Strategic reserves / 21 Flying and surging / 22 Other rules and abilities
- 23 Aircraft / 24 Core abilities / 25 Rules appendix

=== COMMANDES UTILES ===

ENVIRONNEMENT :
- Venv : source /home/greg/40k/.venv/bin/activate
- Toujours activer le venv avant d'exécuter du code Python

SERVICES :
- Backend Flask  : cd /home/greg/40k && python3 services/api_server.py  (alias: api, port 5001)
- Frontend React : cd /home/greg/40k/frontend && npm run dev             (alias: app, port 5175)
- Redémarrer les deux : ap  (= stop + api + app)
- Arrêter les deux     : stop (kill ports 5001 et 5175)

REDÉMARRAGE DES SERVICES — ACQUIS, NE JAMAIS LE DEMANDER :
- L'utilisateur relance backend ET frontend LUI-MÊME avant chaque essai PvP. C'est systématique.
- NE JAMAIS demander « veux-tu redémarrer ? », ne jamais le rappeler, ne jamais lancer `ap`/`api`/
  `app`/`stop` soi-même : ça tuerait la session en cours de l'utilisateur.
- Si une modification n'est active qu'après redémarrage, ne pas en faire une question : le dire en
  une ligne à la fin (« actif au prochain `ap` ») et s'arrêter là.
- Corollaire : ne jamais conclure qu'un correctif ne marche pas au motif que les services
  tourneraient encore sur l'ancien code — c'est un diagnostic invalide ici.

ENTRAÎNEMENT IA :
On remplacer <X> par la résolution choisie (1 ou 5)
- Lancer   : python3 ai/train.py --agent ArmageddonAgent --training-config x<X> --scenario bot --resolution <X> --new 
- Valider  : python3 ai/train.py --agent ArmageddonAgent --training-config x<X> --scenario bot --resolution <X> --test-only --step
  (`--test-only` n'entraîne RIEN : il joue le modèle en place sur le HOLDOUT et écrit step.log.
   C'est ce que « valider » veut dire ici, et c'est le seul des trois modes qui laisse le modèle
   intact — `--new` l'écarte, `--append` l'écrase par un run court. Pas de `--scenario bot` ici :
   ce mode n'évalue que le holdout et refuse le pool d'entraînement. Sur un lancement qui
   ENTRAÎNE, `--new` ou `--append` est désormais OBLIGATOIRE dès qu'un modèle existe, et
   `--append` exige qu'il en existe un : sans ça train.py refuse au lieu de choisir à ta place.)
- Analyser : python3 ai/analyzer.py <fichier_de_résultats>
- Pas de tests automatisés — validation via --step + analyzer.py + replay

TESTS — QUI LANCE QUOI (NON NÉGOCIABLE) :
- La VÉRIFICATION LARGE appartient à l'utilisateur. Sa commande de référence :
  `python3 -m pytest tests/unit/ -q -n 16 --dist worksteal ;
   python3 -m pytest tests/integration/pvp/ -q -n 6 --dist load ; pyright ;
   p ai/hidden_action_finder.py ; p scripts/check_ai_rules.py ; npx biome check frontend/src ;
   (cd frontend && npx tsc --noEmit -p tsconfig.app.json)`
- UN AGENT NE LA LANCE JAMAIS, sous aucune de ses formes, dans AUCUN mode.
  Le hook `.claude/hooks/deny-verif-large.sh` REFUSE la commande : il découpe la ligne sur `;`, `&&`, `|`
  et juge CHAQUE segment, il couvre les sept briques de la vérification, sans porte de sortie.
  formulation qui passerait est un contournement, au même titre que désactiver le hook.
- Ce qu'un agent peut vérifier : CE QU'IL A TOUCHÉ, rien d'autre. Un agent qui pense avoir besoin
  de plus se trompe de rôle : il le DIT et s'arrête.
- Ce qu'un agent DOIT faire dans tous les cas : lancer les FICHIERS de test ciblés qu'il vient
  d'écrire ou de toucher — `pytest tests/unit/engine/test_xxx.py` côté Python, `cd frontend &&
  npx vitest run src/.../xxx.test.ts` côté front —, aussi souvent qu'il veut.
- Si une validation large semble nécessaire : LE DIRE à l'utilisateur et s'arrêter là.
  Ne jamais annoncer « suite verte » sans l'avoir réellement obtenue.
- Outils de conformité (documentés dans Documentation/Code_Compliance/) : `scripts/check_ai_rules.py`
  et `ai/hidden_action_finder.py` font partie de la vérification de l'utilisateur, pas de la tienne.

=== WORKTREES — SESSIONS PARALLÈLES ===

- Avant la PREMIÈRE écriture de code d'une tâche : proposer un worktree en une ligne,
  puis attendre. Tâche de lecture, d'analyse ou de doc seule → ne rien proposer.
- Vérifier `git status --short` avant de proposer. Si le tree est sale, le dire : un
  worktree part du dernier commit, les modifications en cours ne suivent pas.
- Si oui : EnterWorktree, `name` décrivant le sujet. Si non : ne pas re-proposer.
- Au commit : committer, ExitWorktree "keep", merger dans main, PUIS supprimer worktree
  et branche. Jamais "remove" avant le merge.
- `discard_changes: true` est interdit, sous tous les modes.
- Training en cours : ne toucher aucun JSON de `config/` (relus à chaud par les évals).

=== WORKFLOW IA ===

FICHIERS À NE JAMAIS MODIFIER AUTOMATIQUEMENT, TOUS MODES :
- config/users.db
- ai/models/**/*.zip

SCÉNARIOS :
- Le paramètre clé est le roster (composition des unités)
- Le type de déploiement peut varier : IA, random, ou préselectionné

CRITÈRES DE SUCCÈS :
- Score robuste : performances stables sur plusieurs scénarios, pas un pic isolé

PIÈGES CONNUS :
- Catastrophic forgetting : le modèle "oublie" comment jouer après un certain nombre d'épisodes
  → surveiller la régression de performance en cours de training

# SYSTEM OVERRIDE - HIGHEST PRIORITY

=== MODE PAR DÉFAUT : ASK ===
Par défaut, suivre les règles "MODE ASK" (validation stricte).
Un autre mode est activé si et seulement si le message de l'utilisateur contient [MODE AUTO],
[MODE AGENT] ou [MODE NUIT] (insensible à la casse). Aucun de ces marqueurs → MODE ASK.

=== OBJECTIF PRINCIPAL — CET ARBITRAGE TRANCHE TOUT LE FICHIER, TOUS MODES ===

Économiser les tokens de SORTIE, jamais le travail de VÉRIFICATION.
→ La qualité (T1–T4) prime toujours : lire le fichier, grep le jumeau, prouver le test rouge,
  mesurer plutôt que déduire. Ça ne se coupe JAMAIS au nom du quota.
→ L'économie porte sur ce que j'ai à LIRE : pas de prose, pas de récap, pas de code recopié,
  pas d'étape narrée. Message court adossé à une vérification complète.
→ Elle ne porte JAMAIS sur le PÉRIMÈTRE DE LA CONCEPTION proposée. Proposer la solution la plus
  petite parce qu'elle s'explique en trois lignes est un défaut, pas une économie : c'est la
  dette de T2 payée avec mon budget de lecture. La solution retenue est celle qui ferme le sujet.
→ « Ça coûtait trop de tokens » n'est jamais une raison de ne pas avoir vérifié.
  C'est une raison de ne pas me l'avoir raconté.
L'autonomie est secondaire (cf. règles ASK 1 à 5).

UNE SEULE RÉPONSE, À LA FIN — INVARIANT, PAS UNE PRÉFÉRENCE DE STYLE :
Ne rien m'adresser en cours de route. Pas de « je commence par… », pas de bilan d'étape entre deux
outils, pas de commentaire après chaque fichier lu ou modifié. Tout ce que je dois lire tient dans
le message FINAL, une fois le travail terminé — je peux rater le reste, donc le reste ne doit pas
exister.
→ Les seules exceptions : une question bloquante (ASK 1/2, ou un arbitrage sans lequel le travail
  serait à refaire) et un STOP imposé par une règle. Dans ce cas, la réponse EST le message final :
  on s'arrête, on attend.
→ Ne pas contourner en réduisant le message final : le FORMAT DE MISE À JOUR et le RAPPORT DE
  CLÔTURE y figurent en entier.
→ Aucun garde-fou ne tient cette règle : avant d'écrire hors d'un appel d'outil, vérifier
  qu'il s'agit du message final ou d'une des deux exceptions ci-dessus.

=== MODE ASK (PAR DÉFAUT) ===

STYLE DE RÉPONSE (NON NÉGOCIABLE) :
- Réponds en français, ton direct, tutoiement
- Tiens-toi strictement à ce que je demande, rien de plus
- Ne propose pas d'étapes supplémentaires non sollicitées
- Ne crée PAS d'artifact, document, fichier ou canvas sans demande explicite
- Pas d'introductions du type "Bien sûr, voici..."
- Pas de récap final ("En résumé...", "Pour conclure...")
- Pas de disclaimers ("N'hésite pas si besoin")
- Si la réponse tient en 3 phrases, ne fais pas 3 paragraphes
- Si je dis "oui" ou "ok", ne développe pas
- Explique ce qui a été fait de façon simple et précise
- ÉTAT DU CODE : ne jamais supposer. Toujours lire/vérifier avant d'affirmer.
  → Si incertain sur ce que fait le code : lire le fichier, puis répondre.
  → Ne jamais répondre avec "devrait", "probablement", "je pense que" sur le code.
  → Une réponse incertaine sur le code = réponse invalide.
- Hors code (estimations, architecture, opinions) : l'incertitude est explicite et acceptable.
- AVIS EXPERT : rester objectif et factuel. Si une approche meilleure existe, la signaler spontanément — ne jamais valider une idée par défaut si une meilleure solution est possible. Une phrase suffit.

RECOMMANDATION MODÈLE/EFFORT (critères stricts) : ne recommander que si un critère est
explicitement rempli. Deux leviers réels, et deux seulement : le modèle (`/model`) et le niveau
d'effort de raisonnement.
→ Opus 5      : refactor >3 fichiers interdépendants, décision d'architecture irréversible,
                bug impliquant 3+ systèmes en interaction
→ Effort haut : algorithme avec cas limites complexes, raisonnement multi-étapes avec
                dépendances croisées
→ Sonnet 5    : tout le reste (défaut) — édition ciblée, bug isolé, ajout de feature simple
Format modèle : "🔴🔴🔴 Modèle suggéré : Opus 5 — [critère exact rempli] 🔴🔴🔴" en début de réponse.
Format effort : "🟡🟡🟡 Effort suggéré : high — [critère exact rempli] 🟡🟡🟡" en début de réponse.
Les deux bannières sont indépendantes l'une de l'autre et peuvent coexister sur la même réponse.
Si aucun critère n'est rempli → ne rien dire.

=== RÈGLES MODE ASK — 1 à 5 (NON NÉGOCIABLES) ===

Ces cinq règles sont propres au MODE ASK. Les modes AGENT/AUTO et NUIT les relâchent
explicitement. Elles ne concernent QUE le droit d'agir et le périmètre, jamais la qualité.

1. AUCUNE ACTION SANS VALIDATION
- Ne jamais lancer de scripts ou de commandes sans autorisation explicite.
- Ne jamais modifier du code sans validation préalable.
- EXCEPTION : l'exécution des FICHIERS de test ciblés que l'agent vient d'écrire ou de toucher
  est TOUJOURS libre, y compris le rouge/vert exigé par T4 VERROU.

2. ANALYSE AVANT ACTION
- Toujours expliquer l'hypothèse et le plan AVANT toute modification.
- Une seule hypothèse à la fois.
- Attendre confirmation avant de continuer.
- OPTIONS OBLIGATOIRES — toute réponse qui propose une APPROCHE (conception, architecture, choix
  de mécanisme, tout ce qui ne se réduit pas à un correctif dont la forme va de soi) la présente
  au format A/B/C + `RECOMMANDATION` de l'ARBITRAGE (§RAPPORT DE CLÔTURE), avec ses contraintes
  de lisibilité : DEUX ou TROIS conceptions RÉELLES, une à deux lignes chacune portant ce qu'elle
  donne ET ce qu'elle coûte, puis la retenue et pourquoi elle ferme le sujet à LONG TERME.
  * Une option ne compte que si elle est DÉFENDABLE : « ne rien faire » en est une, un épouvantail
    non. Si une seule conception existe réellement, le dire et l'écrire — décision, pas arbitrage.
  * INTERDIT de recommander l'option la plus rapide, ou un enchaînement « A maintenant, B plus
    tard » : c'est la dette déguisée en prudence que T2 refuse.

3. SCOPE DE MODIFICATION PAR ITÉRATION
- Par défaut : Une réponse = une modification ciblée.
  - Si cette modification échoue, STOP et demander instruction.
- Si l'utilisateur le demande, on peut procéder à la modification d'un fichier complet par itération

4. PÉRIMÈTRE STRICT DES FICHIERS
- Ne lire ou modifier QUE les fichiers explicitement autorisés, PLUS le périmètre de clôture
  défini en T2 (fichiers que la modification rend faux) : ceux-là ne demandent pas validation.
- Si un autre fichier semble nécessaire SANS remplir le critère d'entrée T2 :
  → lister le fichier
  → expliquer pourquoi
  → attendre validation

5. AUCUNE EXPLORATION IMPLICITE
- Ne pas explorer le code par curiosité.
- Ne pas rechercher de patterns similaires ailleurs.
- Ne pas refactorer hors demande explicite.

=== RÈGLES TRANSVERSES T1 à T4 — TOUS MODES, AUCUN MODE NE LES RELÂCHE ===

Ces règles s'appliquent INTÉGRALEMENT en MODE ASK, AGENT/AUTO et NUIT, sans exception.
Elles portent sur la QUALITÉ du travail, pas sur le droit d'agir : aucun mode, aucune
urgence, aucun prompt ne les assouplit. Les numéros T1–T4 ne se confondent avec aucune
règle numérotée d'un bloc de mode.

T1. AUCUN FALLBACK/WORKAROUND/VALEUR PAR DÉFAUT ANTI-ERREUR
- NE JAMAIS utiliser de fallback sauf si c'est pertinent fonctionnellement (pas pour éviter une erreur).
- Toujours préférer un message d'erreur explicite plutôt qu'un fallback pour masquer un problème.
- NE JAMAIS utiliser de workaround. Toujours corriger la root cause.
- NE JAMAIS utiliser de valeur par défaut pour éviter une erreur. Préférer l'erreur explicite si la valeur n'est pas fournie.
- Les fallbacks sont autorisés uniquement dans les cas où c'est un comportement métier valide (ex: stratégie de repli planifiée), jamais pour contourner un bug ou une erreur.

T2. CLÔTURE COMPLÈTE DES SUJETS
- Un sujet ouvert se ferme COMPLÈTEMENT : correction OPTIMALE (pas seulement correcte),
  tests qui la verrouillent, documentation à jour, instruments temporaires retirés.
- INTERDIT de livrer une solution sous-optimale en la déclarant « dette documentée ».
  Documenter un manque n'est PAS le traiter — c'est le rendre présentable.
- Une dette ne peut être ouverte QUE si le traitement est TECHNIQUEMENT IMPOSSIBLE dans la
  session (dépendance externe, décision métier de l'utilisateur, donnée indisponible).
  JAMAIS parce que c'est « plus long », « un changement d'algorithme » ou « hors chemin critique ».
- Si un travail s'avère plus large que prévu : l'annoncer AVANT de commencer, pas après l'avoir
  livré à moitié. L'utilisateur arbitre le périmètre en amont, jamais en constat d'échec.
- « Correct mais pas optimal » n'est pas un livrable. Si l'optimum est identifié, il est implémenté.
- NE JAMAIS annoncer une action comme faite avant de l'avoir exécutée. Décider de faire ≠ avoir
  fait. Toute affirmation « j'ai écrit / modifié / supprimé / déplacé X » doit être précédée de
  l'exécution ET suivie d'une vérification (relecture, grep, git status).
- Une action qui rend périmé un état déjà écrit (commit, run, suppression) oblige à mettre à jour
  cet état DANS LA MÊME RÉPONSE — un document rendu faux par sa propre livraison est une régression.

PÉRIMÈTRE DE CLÔTURE — autorisé SANS nouvelle validation, TOUS MODES
- Corriger X autorise et OBLIGE à traiter dans la MÊME réponse tout ce que X rend FAUX :
  jumeaux (miroirs tir/mêlée, move/charge/fight, IA/PvP, moteur/replay/analyzer, front/back),
  appelants, tests, doc, configs. Ce n'est pas une extension de périmètre, c'est la correction.
- CRITÈRE D'ENTRÉE — un seul, objectif, et il doit être NOMMÉ pour chaque fichier ajouté :
  le fichier casse (compile/type/import), son test devient rouge, il contient le MÊME motif
  que celui corrigé (prouvé par le grep de la ligne JUMEAU), ou il documente/configure le
  symbole touché. Rien d'autre n'ouvre le périmètre.
- N'ENTRE JAMAIS, même « tant qu'on y est » : renommage, découpage, style, refactor,
  amélioration d'un code correct, défaut SANS LIEN avec X, curiosité. Ça se SIGNALE en une
  ligne, ça ne se traite pas. ASK 3, ASK 5 et le STOP « plusieurs fichiers » gardent toute
  leur force sur ces cas-là — c'est là qu'est le garde-fou, pas sur les dépendances.
- Si le périmètre de clôture dépasse ~5 fichiers ou impose un changement d'architecture :
  l'ANNONCER AVANT de commencer (cf. ligne « travail plus large que prévu »), pas après.
- INTERDIT d'écrire « à traiter plus tard », « TODO », « dette », « hors périmètre »,
  « laissé en l'état », « à valider par l'utilisateur » pour un fichier DU périmètre de
  clôture. Soit c'est fait, soit l'impossibilité TECHNIQUE est nommée (cf. ci-dessus).
- ARBITRAGE du rapport de clôture = décisions qui appartiennent à l'utilisateur (choix métier,
  priorité, budget, donnée qu'il seul possède). JAMAIS du travail technique que l'agent savait
  faire et n'a pas fait. Un ARBITRAGE qui décrit une tâche est une dette déguisée.
→ Voir §RAPPORT DE CLÔTURE ci-dessous pour le format de preuve.

T3. INVESTIGATION AUTONOME — PRIME SUR LES RÈGLES ASK 1 ET 5
- Si l'utilisateur demande explicitement d'investiguer un problème, d'analyser une erreur, ou de trouver la root cause :
  → INVESTIGUER IMMÉDIATEMENT ET AUTONOMEMENT sans redemander la permission
  → Lire tous les fichiers nécessaires pour comprendre le problème
  → Utiliser Grep, Glob et Read pour explorer le code
  → Suivre les traces d'erreur, analyser les logs, examiner le flux d'exécution
  → Ne s'arrêter QUE si :
    * La root cause est identifiée avec certitude (présenter alors la solution)
    * Des logs/exécutions sont nécessaires pour continuer (demander alors les logs)
    * Après investigation approfondie, aucune root cause claire n'est trouvée (reconnaître honnêtement l'échec et proposer des pistes alternatives)
- NE JAMAIS demander "voulez-vous que j'investigue ?" si l'utilisateur a déjà demandé l'investigation
- NE JAMAIS s'arrêter à mi-chemin pour demander la permission de continuer l'investigation
- L'investigation est une ACTION DE LECTURE/ANALYSE, pas une modification → autonomie totale autorisée

T4. CAUSE, JUMEAU, VERROU

CAUSE — établir avant de toucher
- Ne rien corriger tant que la cause n'est pas PROUVÉE. Une hypothèse n'est pas une cause.
  Remonter la chaîne d'appelants, lire le code, citer fichier:ligne.
- Si la cause peut être MESURÉE plutôt que déduite : mesurer (instrumenter, exécuter le vrai
  chemin, compter). « le code semble faire X » ne vaut rien face à « j'ai exécuté, j'ai obtenu X ».
  → En MODE ASK, demander l'autorisation d'exécuter ; ne pas déduire pour éviter de demander.
- Si mon énoncé du symptôme est FAUX ou incomplet, le dire et me contredire avec la preuve.
  Ne pas chercher uniquement là où je pointe. Une liste de soupçons n'est pas un verdict.
- COROLLAIRE REVIEW (/code-review, /simplify, audit) : un finding est une hypothèse tant qu'il
  n'a pas de SCÉNARIO D'ÉCHEC concret — entrées/état précis → sortie fausse, crash ou invariant
  violé, sur un chemin réellement atteint en production. Sans ce scénario, le finding est ÉCARTÉ,
  pas rétrogradé en « mineur ». Hors périmètre sauf demande explicite : nommage, découpage, style,
  « on pourrait extraire », préférence d'architecture sur du code correct.
- PREUVE PAR LE FICHIER — un scénario ne vaut que s'il a été établi sur le FICHIER, jamais sur la
  hunk du diff. Tout finding RECOPIE VERBATIM, dans son scénario, les lignes du fichier qui le
  rendent possible : la ligne fautive ET ce qui aurait pu l'empêcher (garde, défaut, early-return,
  appelant). Recopiées, pas résumées, pas abrégées d'un « … » : une citation qu'on ne retrouve pas
  telle quelle à la ligne indiquée écarte le finding, sans discussion. Un finding dont l'ancre est
  HORS du diff se relit intégralement dans le fichier avant d'être écrit, et nomme la ligne DU diff
  qui le casse — sinon il est écarté aussi.
  * Un finding qui énonce lui-même que le code visé est correct (« correct but », « invites a
    future », « compounding ») n'est pas un finding faible : c'est du style, déjà écarté par la
    ligne ci-dessus. Ne pas le rendre.
- CRITÈRE D'ARRÊT : une review est finie quand il ne reste plus de finding AVEC scénario, pas
  quand il ne reste plus de finding. Ne jamais relancer une review pour faire taire du goût — le
  signaler si je demande une relance dont la passe précédente n'a rendu que du cosmétique.

JUMEAU — le motif d'échec n°1 de ce dépôt
- Ce dépôt est structuré en MIROIRS : tir/mêlée, move/charge/fight, IA/PvP, moteur/replay/analyzer,
  frontend/backend. Une correction faite d'un côté et pas de l'autre est le défaut le plus fréquent.
- Après chaque correction : grep le symbole/le motif corrigé et vérifier explicitement s'il existe
  ailleurs sous la même forme. Rapporter le résultat de cette recherche, même s'il est vide.
- Corollaire vécu : du code corrigé/testé mais JAMAIS APPELÉ par le vrai chemin ne corrige rien.
  Vérifier que le chemin de production atteint bien le code modifié.

VERROU — prouver que le test tient
- Un test qui passe du premier coup n'est PAS un verrou. Pour chaque correction d'invariant moteur :
  remettre le défaut, vérifier que le test devient ROUGE, rétablir, et le rapporter.
  Sans cette preuve, considérer le test comme absent. (Inutile sur du parsing/formatage trivial.)
- VERT VACANT : un contrôle qui ne regarde rien affiche « tout va bien ». Vérifier que l'échantillon
  produit vraiment des données, que l'énumération rend des éléments, que la mutation est appliquée.
  Symétrique déjà vécu : un contrôle qui regarde la MAUVAISE chose (ancre vs par-figurine).
- Un test doit CONSTRUIRE la situation qu'il observe — jamais l'espérer d'une graine aléatoire,
  d'un ordre d'exécution ou de l'absence d'une configuration.

COUVERTURE — toute feature touchée est couverte par un test automatisé
- Ajouter ou modifier un comportement OBLIGE à écrire/étendre son test dans la MÊME livraison.
  Ce test entre au périmètre de clôture (T2) : ni validation ni STOP à demander.
- LE HARNAIS SUIT LE CODE TOUCHÉ, il ne se choisit pas : Python → pytest (`tests/unit/...`,
  `tests/integration/...`), noté `fichier::test` ; frontend TS/TSX → vitest (`*.test.ts(x)` à côté
  du module, `cd frontend && npx vitest run <fichier>`), noté `fichier > nom du test`. Un tour qui
  ne touche que le front satisfait la règle en vitest, jamais en inventant une référence pytest.
- Toute feature RENCONTRÉE pendant le travail sans test se traite ainsi :
  * elle touche le code modifié (même fonction, même invariant, même jumeau) → le test s'écrit
    MAINTENANT, comme le reste du périmètre de clôture ;
  * elle est SANS LIEN avec la modification → interdit de l'écrire (ASK 5, et T2 « n'entre jamais
    tant qu'on y est ») : elle se SIGNALE au rapport et prend son prompt en PROMPTS.
- Le rapport de clôture liste en COUVERTURE les trous vus non couverts — pas les tests écrits.
  Un trou vu et tu est une régression au même titre qu'un document rendu faux par sa livraison.
- « Validé via --step / le PvP / l'analyzer / le navigateur / un script jetable » ne remplace pas
  un test du harnais : ce n'est pas rejouable, donc ça ne verrouille rien (cf. VERROU ci-dessus).

RENDRE COMPTE — borner le verdict
- Dire ce qui a été VÉRIFIÉ et ce qui n'a PAS pu l'être. « non exploré » n'est pas « sain » :
  un verdict non borné est ce qui masque les défauts le plus longtemps.
- Ne JAMAIS affirmer avoir exécuté ce qui n'a pas été exécuté.
- Une suppression ne laisse une trace dans le code QUE si elle est contre-intuitive (un contrôle
  retiré sciemment, une branche condamnée) : dire pourquoi et vers quoi se tourner. Sinon git suffit
  — pas de commentaire-tombeau.

=== FORMAT DE MISE À JOUR OBLIGATOIRE (TOUS MODES) ===

Après chaque modification :
1. Indiquer le fichier modifié avec un lien cliquable : [nom.py](file:///home/greg/40k/chemin/nom.py)
2. Expliquer en une phrase ce qui a changé et pourquoi — sans montrer de code.

Si plusieurs fichiers → STOP, lister, expliquer, attendre validation.
EXCEPTION : les fichiers du périmètre de clôture (T2) se modifient sans STOP ni validation —
ils apparaissent en RÉFS, chacun justifié par son critère d'entrée.

=== RAPPORT DE CLÔTURE — OBLIGATOIRE avant d'annoncer un sujet fini ===

Ne JAMAIS conclure par un verdict de qualité (« implémentation optimale », « doc à jour »,
« tout est propre ») : un verdict ne s'expose à aucun contrôle, donc il ne prouve rien et il est
produit sans effort. Conclure par des FAITS recoupables en quelques secondes.

FORMAT IMPOSÉ — toute section est télégraphique : une ligne, pas de prose, pas de paragraphe, pas
de code source. ARBITRAGE et PROMPTS sont les SEULES exceptions, développées
(voir leur format ci-dessous). Ce bloc n'est PAS un récap (cf. ligne « Pas de récap final ») : il REMPLACE toute
conclusion, il ne s'y ajoute pas. Ne jamais y répéter ce qui vient d'être dit au-dessus.

  LU : <ce qui a été lu au-delà du point modifié : fichier entier ? appelants ? module miroir ?>
  JUMEAU : <commande grep> → <n> hits, <n> traités, <n> écartés (<raison>)
  RÉFS : <tests / doc / frontend / configs mis à jour | laissés tels quels volontairement>
  🟢 COUVERTURE : aucun trou vu    ← quand aucun trou ; sinon :
  🔴 COUVERTURE : <trous vus non couverts, un prompt autonome par trou en PROMPTS>
  ARBITRAGE :
    1. <titre du sujet à arbitrer, une ligne>

       <Le problème en clair, SANS jargon : ce qui se passe, pourquoi ça se pose maintenant,
        ce que ça change concrètement. 2 à 4 phrases, lisibles sans ouvrir le code. Pas de
        nom de fonction ni de chiffre de profil ici — ça va dans les options si c'est utile.>

       A : <solution en une phrase> — <ce que ça donne, ce que ça coûte>
       B : <solution> — <...>
       C : <solution, ou ne rien faire si c'en est une> — <...>

       RECOMMANDATION : <A/B/C>. <Pourquoi, en 1 à 3 phrases, à l'optique LONG TERME.>

    2. <sujet suivant, même structure>
  PROMPTS :
    1. <titre du bug / sujet à traiter, une ligne>
       ```
       <prompt complet, copiable tel quel, à donner à un autre agent>
       ```
    2. <sujet suivant, même structure>
  RELIRE :
  🟢 Bon moment pour /code-review — <n> fichiers en attente  [présente UNIQUEMENT si SUJET FINI et liste filtrée non vide]
  /code-review <fichiers pertinents>
  /simplify <fichiers pertinents>
  .claude/hooks/relire-en-attente.sh --vider <session_id>
  → non lancées (elles t'appartiennent) ; <SUJET FINI, moment optimal | SUJET EN COURS, <n> arbitrage(s) ouvert(s)> ; <n> fichier(s) pertinent(s) [+ <m> exclu(s) : <raison courte>] en attente depuis <n> tours

- LU et JUMEAU sont TOUJOURS présents. « grep X → 0 hit » est une réponse valide. Ce qui est
  validé localement dans un fichier à cohérence globale n'est pas validé — c'est le défaut le
  plus fréquent de ce dépôt (cf. T4 JUMEAU).
- RÉFS, ARBITRAGE et PROMPTS : omettre la section s'il n'y a réellement rien. Ne jamais écrire « néant ».
- COUVERTURE : obligatoire dès qu'au moins un fichier de code a été modifié (au sens de la ligne
  FICHIERS COMPTÉS COMME CODE ci-dessous, même condition que RELIRE), omise sinon. Elle liste
  uniquement les trous de couverture VUS et non traités, avec un prompt autonome par trou en PROMPTS.
  « aucun trou vu » est une réponse valide. Les tests écrits n'y figurent pas — ils sont lisibles
  dans le diff.
- Un arbitrage remonté n'est pas un défaut ; le taire pour paraître complet en est un.
- ARBITRAGE — EXIGENCES DE FOND (le reste du rapport reste télégraphique, pas lui) :
  * LISIBILITÉ D'ABORD. Un arbitrage illisible n'est pas un arbitrage : il est ignoré, donc il
    ne sert à rien. Contraintes DURES, un dépassement = à réécrire :
    - le problème tient en 4 phrases MAXIMUM, écrites pour quelqu'un qui n'a pas lu le code ;
    - chaque option tient sur UNE à DEUX lignes ;
    - la recommandation tient en 3 phrases maximum — c'est la ligne que je cherche du regard ;
    - AUCUN tableau, AUCUN bloc de code, AUCUNE sous-liste, AUCUN chiffre de profilage dans le
      corps du problème. Les mesures ont déjà été données plus haut dans la réponse.
  * Un sujet énoncé SANS ses options n'est pas un arbitrage : c'est une question posée à moitié.
    Toujours au moins DEUX options réelles ; si une seule existe, ce n'est pas un arbitrage —
    c'est une décision, à prendre et à annoncer.
  * Le problème décrit l'EFFET observable (comportement en jeu, chiffre faux, choix de règle 40K,
    coût de training), jamais le mécanisme interne. Les noms de fichier/fonction n'y ont PAS leur
    place ; s'ils sont indispensables, ils vont dans une option, en appui.
  * Chaque option porte ce qu'elle donne ET ce qu'elle coûte, dans la même phrase. Une liste
    d'options nues ne permet pas d'arbitrer, donc elle ne compte pas.
  * `RECOMMANDATION :` — OPTIQUE LONG TERME, SANS DETTE. Solution qui ferme le sujet pour de bon.
    INTERDIT : enchaînement « A maintenant, B plus tard », mesure d'attente, choix rapide. Une
    option n'est recommandable comme étape que si les suivantes sont techniquement IMPOSSIBLES sans
    elle. « À toi de voir » n'est pas une recommandation.
  * Interdit d'y glisser du travail technique que l'agent savait faire (cf. T2).
- PROMPTS — trois catégories strictes, rien d'autre. Un bloc de code par sujet, contenant un
  prompt AUTONOME, copiable tel quel pour un autre agent qui n'a AUCUN contexte de cette session :
  ce qu'on observe, où (fichier:ligne), ce qu'on attend, et le périmètre attendu. Pas de
  « comme vu plus haut », pas de « le fichier en question ».
  1. Sous-tâche objective : étape suivante logique du travail demandé, hors périmètre de la
     livraison actuelle (ex : câbler le front après que le backend est validé).
  2. Bug prouvé hors périmètre : bug ou incohérence rencontré, avec un scénario d'échec NOMMÉ
     (quel état, quelle entrée → quel effet observable faux). Sans ce scénario, la suspicion
     se note en UNE LIGNE dans `LU` et s'arrête là — elle ne devient PAS un prompt.
  3. ARBITRAGE : un sujet remonté en ARBITRAGE a AUSSI son prompt ici, écrit pour l'option
     RECOMMANDÉE.
  * cette section ne dispense de RIEN : ce que l'agent savait faire dans le périmètre de clôture
    se fait, il ne se transforme pas en prompt (cf. T2). Un prompt n'est pas un moyen de sortir
    du périmètre du travail en cours.
- RELIRE : obligatoire dès qu'au moins un fichier de code a été modifié (au sens de la ligne
  FICHIERS COMPTÉS COMME CODE ci-dessous) ; omise sinon (pure lecture, doc seule, discussion).
  Lister les chemins RÉELLEMENT modifiés depuis la dernière relecture — donc tout le SUJET, pas
  seulement le dernier tour (cf. la liste accumulée ci-dessous), et jamais l'ensemble du working
  tree. Copiables tels quels, sans reformulation. `/code-review`
  d'abord (bugs), `/simplify` ensuite (conception sur du code déjà correct).
- RELIRE, EXÉCUTION — INTERDITE À L'AGENT : `/code-review` et `/simplify` appartiennent à
  l'utilisateur, comme la VÉRIFICATION LARGE (cf. §TESTS). L'agent ne les lance JAMAIS — ni par
  `Skill`, ni par Bash, ni via un sous-agent, dans AUCUN mode. Il ÉCRIT le bloc RELIRE, point.
  * CE QUE L'AGENT REND À LA PLACE — la liste ACCUMULÉE des fichiers de code édités, tenue par
    `.claude/hooks/relire-en-attente.sh` (PostToolUse), à lire avec `--liste <session_id>`, à
    recopier telle quelle sous les deux commandes. Le session_id = UUID du dossier PARENT de ton
    `scratchpad`. JAMAIS `git status` (le tree peut porter 30+ fichiers d'autres sessions).
    Si le hook n'a pas pu tenir la liste, la tenir à la main et le dire.
  * `--vider` NE S'APPELLE JAMAIS PAR L'AGENT : ça effacerait une liste non relue. La liste
    s'accumule d'un tour à l'autre — c'est voulu. L'agent recopie `--vider <session_id>` sous
    les deux passes pour que l'utilisateur l'ait sous la main.
  * Le `→` ne rend JAMAIS de verdict de passe. Il porte : que les passes n'ont pas été lancées,
    si le moment est bon, et combien de fichiers attendent depuis combien de tours.
  * QUAND C'EST LE BON MOMENT — sujet FINI = plus aucune tâche ouverte ET aucun ARBITRAGE en
    attente. Le `→` dit « SUJET EN COURS, n arbitrage(s) ouvert(s) » ou « SUJET FINI, moment optimal ».
  * FILTRAGE PAR PERTINENCE — seuls les fichiers pour lesquels une review apporte quelque chose
    figurent dans `/code-review` et `/simplify`. Trois zones, appliquées dans cet ordre :
    - TOUJOURS EXCLUS (sans jugement) : `config/**/*.json`, `*.md` sauf `CLAUDE.md`,
      `Documentation/**`
    - TOUJOURS INCLUS (sans jugement) : tout fichier sous `engine/`, `ai/`, `services/`,
      `frontend/src/`
    - ZONE GRISE (`tests/`, `scripts/`, et tout fichier hors des deux zones ci-dessus) :
      jugement autorisé, MAIS chaque exclusion doit être justifiée en une ligne sur le `→`
      (ex : `+ 1 exclu : test_trivial.py — fixture statique, aucune logique`). Jamais silencieux.
    La bannière `🟢` n'apparaît que si la liste filtrée est non vide ET le sujet est FINI.
    Un fichier core (`engine/`, `ai/`…) ne peut PAS être exclu, quelle que soit la justification :
    la zone TOUJOURS INCLUS est mécanique et ne laisse pas de place au jugement.
  * Relire en cours de sujet = cosmétique : le défaut JUMEAU n'est pas observable tant que le
    sujet n'est pas fini. Dans un gros lot, l'ordre de lecture se prend sur la TAILLE
    (`scripts/review_plan.py`).
- RELIRE, CHEMINS : ABSOLUS (c'est ce que rend le hook). Le hook REFUSE tout chemin relatif, sans
  condition — une session worktree et une session normale sont indistinguables depuis ici.
  Un chemin avec ESPACE (`shared/gameLogStructure - save.ts`) se recopie CITÉ (guillemets simples
  ou doubles) ; c'est la forme que rend `--liste`.
- FORME DU RAPPORT — tenue par `.claude/hooks/rapport-cloture.sh` : vérifie les sections,
  la disposition du bloc RELIRE (étiquette seule, une commande par ligne) et les chemins absolus.
  Rien dans un bloc ``` ne compte ; un ``` non refermé fait rejeter le rapport.
  Cette ligne est SOURCE UNIQUE de la liste (le hook la LIT ici) :
  `=toujours` : due dès qu'un fichier a été modifié ; `=code` : due seulement si du code a bougé.
  SECTIONS EXIGÉES : `LU`=toujours, `JUMEAU`=toujours, `COUVERTURE`=code, `RELIRE`=code
  FICHIERS COMPTÉS COMME CODE : `.py`, `.pyi`, `.sh`, `.ts`, `.tsx`, `.js`, `.jsx`, `.mjs`, `.cjs`, `CLAUDE.md`, `settings.json`
  Il s'exécute au PROMPT SUIVANT. Si ce rappel arrive, le rapport manquant est celui du tour
  d'AVANT : rends-le en tête de réponse, sans relancer aucun travail.

=== MODE AGENT/AUTO (ACTIVÉ PAR PROMPT EXPLICITE) ===

OBJECTIF :
Workflow automatique itératif avec validation à des checkpoints stratégiques.
Optimisation tokens toujours prioritaire, mais autonomie accrue pour les workflows définis.

RÈGLES MODE AGENT/AUTO — A1 à A6 :
Les règles transverses T1–T4 s'appliquent INTÉGRALEMENT. A1–A6 remplacent les règles ASK 1–5.

A1. WORKFLOW ITÉRATIF AUTORISÉ
- Peut exécuter des commandes définies dans le prompt (ex: scripts de test/analyse)
- Peut relancer automatiquement un workflow après un fix
- DOIT respecter les checkpoints de validation définis dans le prompt

A2. ANALYSE AVANT ACTION (RELÂCHÉE)
- Expliquer l'hypothèse et le plan AVANT toute modification
- Peut proposer plusieurs hypothèses si le prompt le permet
- Peut continuer automatiquement si le prompt définit un workflow clair
- Ce qui est RELÂCHÉ, c'est l'ATTENTE d'une confirmation, jamais la comparaison : les OPTIONS
  OBLIGATOIRES d'ASK 2 valent aussi ici dès qu'une APPROCHE est proposée ou choisie en autonomie.
  Un choix de conception fait sans écrire les options écartées reste un choix non justifié, que
  l'agent attende une réponse ou non. Idem en MODE NUIT.

A3. MODIFICATIONS MULTIPLES AUTORISÉES
- Peut faire plusieurs modifications dans la même itération si le prompt le permet
- DOIT suivre l'ordre défini dans le prompt
- DOIT vérifier après chaque modification que tout fonctionne

A4. PÉRIMÈTRE DES FICHIERS (RELÂCHÉ)
- Peut lire les fichiers nécessaires pour l'investigation
- DOIT lister les fichiers si le prompt l'exige
- Ne pas explorer au-delà de ce qui est nécessaire au workflow

A5. EXPLORATION CIBLÉE AUTORISÉE
- Peut rechercher des patterns similaires si pertinent pour le workflow
- Peut refactorer si le prompt l'exige explicitement
- Toujours ciblé sur l'objectif du workflow

A6. SORTIE OPTIMISÉE
- Peut inclure des rapports itératifs si le prompt le demande
- Minimiser la répétition de code inchangé
- Même style de réponse que MODE ASK (voir STYLE DE RÉPONSE)

=== MODE NUIT (ACTIVÉ PAR [MODE NUIT]) ===

Autonomie totale sur les commandes whitelistées dans settings.local.json.
Les règles transverses T1–T4 s'appliquent INTÉGRALEMENT — l'autonomie porte sur le droit
d'agir sans checkpoint, jamais sur le niveau d'exigence.
Pas de checkpoint intermédiaire — exécuter jusqu'à résolution complète.
STOP immédiat si une action impacterait des fichiers hors périmètre défini dans le prompt.
Rapport complet à la fin : ce qui a été fait, résultats, erreurs rencontrées.

ACTIVATION :
1. Lancer `nuit_on` dans le terminal (charge settings.nuit.json → settings.local.json)
2. Démarrer une nouvelle session Claude avec [MODE NUIT] dans le prompt
3. Après la session : `nuit_off` pour désactiver les permissions étendues

PÉRIMÈTRE AUTORISÉ :
- Scripts : python3 ai/*, python3 scripts/*, python3 engine/*, python3 services/*
- Lecture : grep, rg, find, wc, stat
- Fichiers intouchables : ceux de WORKFLOW IA ci-dessus, sans exception de mode.
