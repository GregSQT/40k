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
- Ne jamais utiliser de fallbacks ou de workaround ou de valeur par défaut pour masquer des erreurs potentielles

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
- Lancer   : python3 ai/train.py --agent CoreAgent --scenario bot --new
- Valider  : python3 ai/train.py --agent CoreAgent --scenario bot --step
- Analyser : python3 ai/analyzer.py <fichier_de_résultats>
- Pas de tests automatisés — validation via --step + analyzer.py + replay

TESTS — QUI LANCE QUOI (NON NÉGOCIABLE) :
- La VÉRIFICATION LARGE appartient à l'utilisateur. Il la lance lui-même, avec SA commande :
  `python3 -m pytest tests/unit/ -q -n 8 --dist worksteal ; pyright ; p ai/hidden_action_finder.py ;
   p scripts/check_ai_rules.py ; npx biome check frontend/src ;
   (cd frontend && npx tsc --noEmit -p tsconfig.app.json)`
- UN AGENT NE LANCE JAMAIS LA SUITE COMPLÈTE. Ni `pytest tests/unit/`, ni `pytest tests/`,
  ni `pytest` nu, sous aucune forme (y compris derrière un `source .venv/... &&`).
  Un hook la REFUSE (.claude/hooks/deny-full-test-suite.sh) — inutile de contourner.
- Ce qu'un agent DOIT faire : lancer les FICHIERS de test ciblés qu'il vient d'écrire ou de
  toucher (`pytest tests/unit/engine/test_xxx.py`), aussi souvent qu'il veut.
- Si une validation large semble nécessaire, LE DIRE à l'utilisateur et s'arrêter là. Ne jamais
  annoncer « suite verte » sans l'avoir réellement obtenue de lui.
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

FICHIERS À NE JAMAIS MODIFIER AUTOMATIQUEMENT :
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
Le mode est activé si et seulement si le message de l'utilisateur contient [MODE AUTO] ou [MODE AGENT] (insensible à la casse).

=== MODE ASK (PAR DÉFAUT) ===

MODE ÉCONOME STRICT — PRIORITÉ ABSOLUE AU QUOTA

OBJECTIF PRINCIPAL :
Minimiser la consommation de tokens.
L'autonomie est secondaire.

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

RECOMMANDATION MODÈLE/EFFORT (critères stricts) :Ne recommander que si un critère est explicitement rempli.
→ Opus      : refactor >3 fichiers interdépendants, décision d'architecture irréversible, bug impliquant 3+ systèmes en interaction
→ /think    : algorithme avec cas limites complexes, raisonnement multi-étapes avec dépendances croisées
→ Sonnet    : tout le reste (défaut) — édition ciblée, bug isolé, ajout de feature simple
Format      : "🔴🔴🔴 Modèle suggéré : Opus — [critère exact rempli] 🔴🔴🔴" en début de réponse.
Si aucun critère n'est rempli → ne rien dire.

=== RÈGLES MODE ASK — 1 à 5 (NON NÉGOCIABLES) ===

Ces cinq règles sont propres au MODE ASK. Les modes AGENT/AUTO et NUIT les relâchent
explicitement. Elles ne concernent QUE le droit d'agir et le périmètre, jamais la qualité.

1. AUCUNE ACTION SANS VALIDATION
- Ne jamais lancer de tests, scripts ou commandes sans autorisation explicite.
- Ne jamais modifier du code sans validation préalable.

2. ANALYSE AVANT ACTION
- Toujours expliquer l'hypothèse et le plan AVANT toute modification.
- Une seule hypothèse à la fois.
- Attendre confirmation avant de continuer.

3. SCOPE DE MODIFICATION PAR ITÉRATION
- Par défaut : Une réponse = une modification ciblée.
  - Si cette modification échoue, STOP et demander instruction.
- Si l'utilisateur le demande, on peut procéder à la modification d'un fichier complet par itération

4. PÉRIMÈTRE STRICT DES FICHIERS
- Ne lire ou modifier QUE les fichiers explicitement autorisés.
- Si un autre fichier semble nécessaire :
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

RAPPORT DE CLÔTURE — OBLIGATOIRE avant d'annoncer un sujet fini
Ne JAMAIS conclure par un verdict de qualité (« implémentation optimale », « doc à jour »,
« tout est propre ») : un verdict ne s'expose à aucun contrôle, donc il ne prouve rien et il est
produit sans effort. Conclure par des FAITS recoupables en quelques secondes.

FORMAT IMPOSÉ — 5 lignes télégraphiques MAXIMUM, pas de prose, pas de paragraphe, pas de code
source. Ce bloc n'est PAS un récap (cf. ligne « Pas de récap final ») : il REMPLACE toute
conclusion, il ne s'y ajoute pas. Ne jamais y répéter ce qui vient d'être dit au-dessus.

  LU : <ce qui a été lu au-delà du point modifié : fichier entier ? appelants ? module miroir ?>
  JUMEAU : <commande grep> → <n> hits, <n> traités, <n> écartés (<raison>)
  RÉFS : <tests / doc / frontend / configs mis à jour | laissés tels quels volontairement>
  ARBITRAGE : <ce qui attend une décision utilisateur>
  RELIRE : /code-review <fichiers modifiés>
           /simplify <fichiers modifiés>

- LU et JUMEAU sont TOUJOURS présents. « grep X → 0 hit » est une réponse valide ; omettre la
  ligne n'en est pas une. Ce qui est validé localement dans un fichier à cohérence globale n'est
  pas validé — c'est le défaut le plus fréquent de ce dépôt (cf. T4 JUMEAU).
- RÉFS et ARBITRAGE : omettre la ligne s'il n'y a réellement rien. Ne jamais écrire « néant ».
- Un arbitrage remonté n'est pas un défaut ; le taire pour paraître complet en est un.
- RELIRE : obligatoire dès qu'au moins un fichier de code a été modifié ; omise sinon (réponse
  pure lecture, doc seule, discussion). Lister les chemins RÉELLEMENT modifiés dans CETTE tâche,
  jamais l'ensemble du working tree — copiables tels quels, sans reformulation. `/code-review`
  d'abord (bugs), `/simplify` ensuite (conception sur du code déjà correct). Ces deux commandes
  appartiennent à l'utilisateur : ne JAMAIS les lancer soi-même, seulement les écrire.

T3. INVESTIGATION AUTONOME — PRIME SUR LES RÈGLES ASK 1 ET 5
- Si l'utilisateur demande explicitement d'investiguer un problème, d'analyser une erreur, ou de trouver la root cause :
  → INVESTIGUER IMMÉDIATEMENT ET AUTONOMEMENT sans redemander la permission
  → Lire tous les fichiers nécessaires pour comprendre le problème
  → Utiliser codebase_search, grep, read_file pour explorer le code
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
- NE JAMAIS modifier : config/users.db, ai/models/**/*.zip

