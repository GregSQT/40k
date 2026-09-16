# Équilibrer Warhammer 40,000 par la mesure

*Document de présentation — Games Workshop*

---

## ⚡ Pourquoi maintenant

Jusqu'à récemment, les joueurs qui voulaient jouer à Warhammer 40,000 à distance passaient par une
plateforme de simulation physique généraliste : des figurines modélisées, des décors, un mètre, des
dés. Et rien d'autre. Aucune règle n'y est connue du logiciel. Le joueur mesure lui-même, se
souvient lui-même, arbitre lui-même les désaccords, et fait confiance à l'autre.

Cette solution n'est plus disponible. Le besoin, lui, demeure — et il est aujourd'hui sans réponse.

Ce document ne propose pas de la remplacer. Il propose autre chose : **un moteur qui connaît les
règles, les applique, et rend les erreurs impossibles au lieu de les laisser s'arbitrer entre
joueurs.** L'écart entre les deux est celui qui sépare un parking d'un circuit.

Et c'est une offre que vous contrôlez : elle joue vos règles, dans votre univers, avec vos
validations — au lieu d'un bricolage sur lequel vous n'avez aucune prise.

Ce qui suit décrit ce même système et l'usage qu'il permet en interne : mesurer l'équilibrage du
jeu.

## 1. Un problème qui n'a jamais été résolu — parce qu'il est insoluble à la main

Depuis quarante ans, la critique la plus constante adressée à Warhammer 40,000 n'est ni son
univers, ni ses figurines, ni ses règles : c'est son **équilibrage**.

Je veux commencer par écarter un malentendu. Ce n'est pas un défaut de soin, ni de compétence.
C'est un **mur mathématique**.

Avec plusieurs centaines d'unités disponibles et un budget de 2000 points, le nombre de listes
d'armée légales se compte en milliards. Le nombre d'affrontements possibles est ce nombre au
carré. Et chaque affrontement dépend encore du terrain, de la mission, du déploiement et des
décisions prises tour après tour.

Aucun programme de playtest humain ne peut couvrir cet espace. Pas avec dix testeurs, pas avec
mille. Ce n'est pas une question d'effort : c'est une question d'ordre de grandeur. Le
déséquilibre n'est pas une erreur ponctuelle qu'on pourrait éviter en travaillant mieux — c'est
la conséquence inévitable d'un espace de possibilités qu'aucune équipe humaine ne peut explorer.

**Un tel problème ne se résout pas par plus de rigueur. Il se résout par un changement
d'instrument.**

## 2. Pourquoi les outils actuels ne peuvent pas y arriver

Vous équilibrez déjà en continu — mises à jour de points, dataslates d'équilibrage. Le principe
est le bon. Ce sont les **données** qui sont structurellement insuffisantes :

- **Elles arrivent trop tard.** Le retour de tournoi arrive des mois après la publication. Le
  déséquilibre a déjà été vécu par les joueurs — la réputation, elle, est déjà faite.
- **Elles sont biaisées.** Seuls les joueurs compétitifs remontent des résultats. Et on ne mesure
  que les listes déjà populaires : une unité que personne ne joue ne génère aucune donnée, donc
  reste invisible — alors que son absence *est* précisément le symptôme.
- **Elles ne sont pas contrefactuelles.** Les données de tournoi disent ce qui s'est passé. Elles
  ne disent jamais ce qui se serait passé si cette unité avait coûté 15 points de moins. Or c'est
  la seule question qui compte pour décider.
- **Elles ne couvrent presque rien.** Quelques milliers de parties par saison, sur un espace de
  milliards de combinaisons.

Le playtest et les données de tournoi ne sont pas mauvais. Ils sont simplement **trop lents, trop
étroits et trop rétrospectifs** pour la taille du problème.

## 3. Ce que j'apporte : une IA qui joue déjà à Warhammer 40,000

Ce n'est pas un concept ni une étude de faisabilité. C'est un système qui fonctionne aujourd'hui :

- Un **moteur de jeu complet** : mouvement, tir, charge, corps-à-corps, terrain, objectifs, ligne
  de vue en trois dimensions, règles d'armes spéciales, phases et tour de bataille.
- **Deux modes jouables** : entre joueurs, ou contre l'IA — avec rejeu et analyse des parties.
- Une **intelligence artificielle par apprentissage par renforcement** qui joue le jeu — elle
  déploie, manœuvre, tire, charge, combat et dispute les objectifs.

Et surtout, un choix d'architecture qui est le cœur de tout ce document : **l'IA lit les
caractéristiques des unités avant de décider.** Elle ne mémorise pas « comment jouer les
Intercessors ». Elle lit une fiche technique — profil, armes, règles spéciales — exactement comme
un joueur, puis décide. Elle peut donc manier une unité qu'elle n'a **jamais** rencontrée.

C'est la partie difficile, et elle est faite. La conséquence est décisive : **ajouter une unité
ou une règle ne demande pas de reconstruire l'IA.** Le système absorbe le contenu nouveau.

Ce qui reste devant est du travail volumineux mais connu : compléter le catalogue des règles et
des unités, et fournir du temps d'entraînement. Pas de verrou de recherche. Du temps et des
moyens.

**Et la fiabilité du moteur n'est pas un détail technique.** Une mesure d'équilibrage ne vaut que
ce que vaut le moteur qui la produit : si les règles sont mal appliquées, tout ce qui suit dans ce
document ne vaut rien. C'est pourquoi la vérification est traitée ici comme dans un système où une
erreur coûte cher :

- **7 113 tests automatisés, nommés d'après les règles officielles qu'ils vérifient.** Choisissez
  une règle, je vous montre le test qui la verrouille — c'est lisible sans savoir coder.
- **Chaque test est validé en réintroduisant volontairement le défaut** qu'il doit attraper. Un
  test qui passe du premier coup ne prouve rien ; on vérifie qu'il échoue quand il doit échouer.
- **Des parties entières jouées au hasard, en continu**, pour débusquer les incohérences que
  personne n'a pensé à tester — y compris des enchaînements d'actions qu'aucun joueur ne tenterait.
  Ces tests ne cherchent pas un résultat, ils cherchent une contradiction.
- **Aucun test désactivé.** Rien n'est mis de côté en attendant d'avoir le temps.

## 4. De « elle joue » à « elle équilibre » — quatre étapes

**Étape 1 — La machine compose des armées.**
Des milliers de listes légales, toutes au même budget, y compris celles que personne n'a jamais
essayées. C'est déjà une couverture hors de portée d'un playtest.

**Étape 2 — Elle joue.**
Des centaines de milliers de parties, en parallèle, sans affichage ni humain. Une partie qui
prend trois heures sur une table prend ici une fraction de seconde.

**Étape 3 — Elle mesure ce qui survit à la compétition.**
Pas « qui a gagné » : le taux de victoire moyen dépend entièrement des adversaires choisis, il
est donc manipulable et trompeur. La bonne question est : **quelles armées restent debout quand
tout le monde optimise ?** Une unité présente dans 98 % des listes survivantes est sous-évaluée.
Une unité qui n'apparaît jamais est surévaluée. Et deux unités anodines dont l'association gagne
davantage que la somme de leurs apports : c'est une combinaison abusive, détectée avant qu'un
joueur ne la trouve.

**Étape 4 — Elle cherche le prix juste.**
C'est l'étape qui rend l'outil utile plutôt qu'intéressant. La machine modifie le prix, refait
tourner la simulation, et recommence jusqu'à ce que l'unité redevienne **un choix parmi
d'autres** — ni obligatoire, ni ridicule. Elle ne vous dit pas « cette unité est trop forte ».
Elle vous dit **combien elle devrait coûter**.

## 5. Ce que reçoit un game designer

Un rapport lisible en cinq minutes, pas un fichier d'ingénieur *(chiffres illustratifs)* :

| Unité | Prix actuel | Prix recommandé | Présence dans les armées optimales |
|---|---|---|---|
| Intercessor | 20 | **17** | 98 % — auto-inclusion, clairement sous-évaluée |
| Dreadnought | 135 | 135 | 41 % — sain, aucun changement |
| Terminator | 180 | **150** | 2 % — quasiment jamais joué, gamme dormante |

> ⚠️ **Combinaison détectée** : *Apothicaire + Terminators*. Chacun est correctement évalué seul.
> Ensemble, ils gagnent 23 points de pourcentage de plus que la somme de leurs apports. Cause
> probable : la règle de soin annule le point faible prévu de l'unité.

Et une nuance que la plupart des approches ratent : **une IA parfaite n'est pas un joueur
humain.** Une unité difficile à manier paraîtra excellente à une machine et décevra vos joueurs.
Nous rejouons donc les mêmes affrontements avec une IA volontairement dégradée. Si l'unité
s'effondre, elle n'est pas mal évaluée — elle est **technique**. Le remède n'est pas le même, et
cette distinction est exactement celle qu'un designer a besoin de faire.

## 6. Ce que cela change pour Games Workshop

- **Équilibrer avant publication, plus après.** Le déséquilibre est corrigé pendant la conception,
  pas dans un dataslate d'urgence trois mois plus tard. Ce qui change, ce n'est pas seulement le
  jeu — c'est **le moment** où vous apprenez le problème.
- **Tester une règle avant qu'elle existe.** Toute règle nouvelle peut être simulée avant d'être
  écrite, illustrée, imprimée. Le coût d'un revirement tardif est le vôtre ; ici il devient une
  ligne de calcul.
- **Réveiller la gamme dormante.** Une unité que personne ne joue est une figurine que personne
  n'achète. L'outil identifie ces unités — y compris celles qui ne génèrent aujourd'hui aucune
  donnée de tournoi, précisément parce que personne ne les joue.
- **Un besoin permanent, pas un achat unique.** Chaque codex, chaque édition, chaque saison
  recrée le problème. L'instrument sert indéfiniment.
- **Transposable à vos autres systèmes** — Age of Sigmar, Kill Team, Necromunda. Le moteur change ;
  la méthode, non.

## 7. Le même moteur répond à un second problème : faire entrer les nouveaux joueurs

Les deux armées sur lesquelles mon IA s'entraîne ne sont pas choisies au hasard : **ce sont celles
de la boîte de base de la V11.**

Considérez la situation d'un nouveau joueur. Il est intéressé, il est seul, personne autour de lui
ne connaît le jeu, et il a 200 € devant lui. Sa barrière n'est pas le prix : c'est d'apprendre
seul un jeu de cette complexité, sans partenaire et sans personne pour corriger ses erreurs.
Beaucoup renoncent exactement là — non par manque d'envie, mais par manque d'un adversaire.

Ce que l'IA met dans la bouche d'un vendeur :

> *« Tenez, voilà une adresse. C'est gratuit. Vous jouez avec les figurines de la boîte, et vous
> apprenez les règles en jouant. »*

- Un adversaire **disponible immédiatement**, sans avoir à trouver quelqu'un.
- Les règles apprises **en jouant**, pas en lisant — la seule méthode qui fonctionne réellement.
- Il joue **exactement les unités qu'il s'apprête à acheter**, pas une démonstration abstraite.
- Et une IA encore imparfaite est un adversaire **idéal** pour un débutant : ici, ce n'est pas une
  limite, c'est la bonne difficulté.

C'est mesurable, et rapidement : taux de conversion sur la boîte de base, avec et sans l'outil.

Le point décisif est celui-ci : **cette application n'attend rien.** Elle ne demande ni le
catalogue complet, ni des mois d'entraînement supplémentaire — elle repose exactement sur ce qui
existe déjà, ces deux armées et cette IA. L'équilibrage est un chantier ; l'onboarding est
disponible.

## 8. Un abonnement qu'on ne résilie pas

Ce même produit a déjà un canal chez vous : un service par abonnement, une base de clients qui
paie, une distribution en place. Il n'y a rien à construire autour — ni canal, ni facturation, ni
acquisition de clients.

Ce qu'il propose aujourd'hui est du contenu qui se **consomme** : on le regarde, puis on attend la
suite. Un jeu, lui, se **pratique** — chaque semaine, indéfiniment.

Cette distinction décide de la vie d'un abonnement. **Un service ne se juge pas sur ce qui fait
souscrire, mais sur ce qui empêche de résilier.** Un catalogue qu'on a fini de regarder ne retient
personne ; une partie en cours ramène le joueur. Vous n'auriez pas un contenu de plus à proposer :
vous auriez une raison de rester.

Ce que j'ai observé chez les joueurs à qui je l'ai montré : ils n'ont pas demandé si le jeu
sortirait un jour. Ils ont demandé comment y accéder, et combien ça coûterait. Ce n'est pas une
étude de marché — c'est ce que j'ai constaté, spontanément, à chaque fois.

Et c'est la seule des trois applications dont le revenu se calcule directement. L'équilibrage
produit une économie diffuse, l'onboarding une conversion difficile à isoler ; un abonnement est un
revenu récurrent, attribuable, projetable.

Un même moteur qui équilibre le jeu, y fait entrer les nouveaux joueurs et donne à votre offre en
ligne une raison d'être reconduite n'est pas un outil : c'est une infrastructure.

## 9. Ce que la simulation retire du travail — et ce qu'elle vous laisse

Aujourd'hui, éprouver un changement d'équilibrage suppose de jouer des parties. Et jouer une
partie introduit deux problèmes que personne ne sait éliminer :

- **Le niveau des joueurs.** Un résultat dépend d'eux autant que des règles. Deux testeurs
  inégaux, et l'unité testée paraît forte ou faible sans qu'on puisse démêler la cause.
- **L'angle mort.** Une interaction qu'on n'a pas pensé à essayer reste invisible — jusqu'à ce
  que dix mille joueurs la trouvent après publication.

**En simulation, l'IA joue au même niveau des deux côtés de la table. Le niveau du joueur cesse
d'être une variable.** Ce qui subsiste dans l'écart de résultats, ce sont les règles et les
points : exactement ce que vous cherchez à mesurer, et rien d'autre. Ce n'est pas un argument
d'autorité, c'est un contrôle expérimental.

Et une partie prend une seconde. Ce changement d'échelle change la nature du travail : au lieu de
vérifier quelques hypothèses choisies à l'avance, on balaie l'espace — y compris les
combinaisons auxquelles personne n'aurait pensé, qui sont précisément celles qui font mal.

**Ce qui ne change pas : vous gardez la main.** Vos designers définissent les listes de référence,
choisissent les affrontements à explorer, arbitrent les ajustements. L'outil ne décide rien et ne
remplace aucun jugement — il n'a pas d'intention, pas de vision du jeu, pas de goût. Ce qu'il vous
retire est le travail que personne ne veut faire : jouer des centaines de parties pour éprouver
une intuition, et la crainte permanente d'être passé à côté d'une combinaison que la communauté
trouvera à votre place.

Et il en découle quelque chose qui pèse au-delà du studio : une décision d'équilibrage cesse
d'être une opinion d'éditeur opposée à l'opinion d'un joueur. Elle s'appuie sur une mesure, faite
à niveau de jeu égal, sur un volume de parties qu'aucune communauté ne pourra jamais atteindre.
La controverse permanente sur l'équilibrage use la réputation du jeu autant que le déséquilibre
lui-même ; c'est le premier levier qui l'attaque à la racine.

Enfin, **la même IA peut être rendue aux joueurs** — partenaire d'entraînement, adversaire de
préparation aux tournois, outil d'analyse de liste. C'est aussi, accessoirement, un produit.

## 10. Où en est le projet, sans enjoliver

**Fait :** le moteur de jeu, l'interface jouable, la chaîne de rejeu et d'analyse automatisée, et
l'architecture d'IA qui lit les caractéristiques des unités — la fondation dont dépend tout ce
document.

**Ce qui manque :** l'IA joue, mais elle ne joue pas encore assez bien pour que ses verdicts
fassent autorité. La qualité de la mesure est plafonnée par la force du joueur — je le dis
franchement plutôt que de le laisser découvrir. Il manque aussi le générateur d'armées, la
couche d'analyse, et la complétion du catalogue d'unités et de règles.

**Pourquoi ce manque n'est pas un doute technique :** rien de ce qui reste ne demande une
découverte. Il faut du contenu à saisir, et du temps de calcul pour l'entraînement. Ce sont des
ressources, pas des inconnues. C'est précisément là que je viens vous chercher : j'ai construit
seul la partie qu'on ne peut pas acheter, et il me manque celle qu'on peut.

## 11. Ce que je propose

Je ne viens pas négocier de droits aujourd'hui. Votre univers est le vôtre, et le prototype ne
prendrait son sens qu'entre vos mains.

Ce que j'apporte est **l'instrument** : un moteur de simulation et une IA capables de mesurer ce
que quarante ans de playtest n'ont pas pu atteindre — et le potentiel de retourner votre critique
la plus ancienne en argument de vente.

Je suis disponible pour une démonstration en direct : l'IA joue, vous regardez.
