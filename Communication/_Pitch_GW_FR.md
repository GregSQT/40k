# Warhammer 40,000 Battle Simulator — Présentation du projet

*Préparé à l'attention de Games Workshop Ltd.*

## 1. Concept

Une application PC qui simule une partie complète de Warhammer 40,000, contre un autre joueur humain ou contre une IA entraînée par renforcement. Le moteur applique les règles officielles et prend en charge toute la gestion mécanique — portées de mouvement, ligne de vue, résolution des jets de dés — tandis que chaque décision tactique reste entre les mains du joueur.

**Ce que c'est :**
- Une reproduction fidèle des règles de base de l'édition en cours
- Un moyen de jouer des parties complètes rapidement, en local ou contre une IA
- Un complément à la pratique physique du hobby

**Ce que ce n'est pas :**
- Pas une réinterprétation action/STR (pas de combat en temps réel, pas de réécriture du lore)
- Pas un substitut aux figurines, à la peinture ou au produit physique
- Pas un remplacement de l'expérience plateau — l'outil supprime la friction, pas le jeu

L'application cible les moments *autour* de la table : tester une liste, apprendre une faction, s'entraîner avant un tournoi, ou jouer quand aucune session physique n'est possible.

## 2. Fonctionnalités de jeu

L'application guide le joueur à travers chaque phase, en gérant les mesures, la vérification des règles et les jets de dés, pour que le joueur puisse se concentrer sur la tactique. L'ensemble de la séquence de tour — Commandement, Mouvement, Tir, Charge, Combat — se déroule dans l'ordre officiel.

**Fiches de données en un clic.** Le profil complet de chaque unité, ses armes et ses capacités sont accessibles instantanément. Plus besoin de livre de règles ni de feuilles de référence.

**Aperçu du mouvement.** Quand une unité est sélectionnée, l'application affiche exactement où elle peut aller — toutes les cases accessibles en un coup d'œil en tenant compte du terrain, des unités amies et ennemies (et de leurs zones d'engagement) et des capacités de vol. Mouvements normaux, Avances, Replis et retraits désespérés ont chacun leur zone légale, avec les conséquences appliquées automatiquement (pas de tir après un Repli, etc.).

**Aperçu de la ligne de vue.** Avant de valider un mouvement, le joueur voit quels ennemis seront visibles et à portée depuis la position envisagée, mis à jour en temps réel. Les couverts sont affichés de la même façon, pour que les joueurs aient la même vision objective du jeu.

**Sélection des armes et des cibles.** Le joueur choisit l'ordre et la cible des armes dans un menu, tandis que l'adversaire définit l'ordre des pertes et procède au retrait des figurines lui-même.

**Résolution automatique des attaques.** Touches, blessures et sauvegardes sont tirés et comptabilisés instantanément. Les règles spéciales des armes (Tir Rapide, Melta, Explosion, Pistolet, Assaut, relances, etc.) sont appliquées automatiquement et notifiées dans l'historique de la partie afin que les joueurs sachent pourquoi et comment tel ou tel modificateur a été appliqué.

**Charge et combat.** Les phases de charge et de combat suivent la séquence officielle — le joueur déclare la charge et prend les décisions, l'application gère les distances et la séquence de déplacement et d'attaque selon les règles.

**Fidélité aux règles.** Plus de 100 fiches de données et leurs profils d'équipement, plus de 200 profils d'armes répartis sur six factions, terrain, couvert et objectifs sont tous modélisés sur l'édition en cours. Les distances à l'écran correspondent directement aux pouces du plateau. La précision et l'intégrité des règles est garantie par plus de 6 000 tests de régression automatisés, assurant qu'aucune mise à jour ne puisse silencieusement casser un comportement existant.

Le principe de conception est constant : **l'application fait les calculs ; le joueur prend toutes les décisions.**

> **Note sur le modèle de plateau.** Le champ de bataille utilise une grille hexagonale fine plutôt que la mesure libre — un choix d'ingénierie délibéré qui borne l'espace d'états pour l'entraînement par renforcement. La résolution est calibrée à **1 pouce = 5 hexagones**, maintenant la précision positionnelle bien en dessous d'un pouce pour que portées, charges et distances d'engagement restent fidèles au plateau physique tout en restant tractables pour l'IA.

## 3. État du projet

- **PvP — fonctionnel.** Des parties humain contre humain complètes sont jouables de bout en bout, avec la boucle de jeu complète.
- **IA — en développement.** Un adversaire par apprentissage par renforcement (MaskablePPO, avec masquage d'actions, entraînement en environnements parallèles et évaluation contre des bots scriptés) est en cours d'entraînement pour le jeu solo et l'entraînement tactique.
- **Replay et analytique.** Un système de replay action par action et des outils de métriques d'entraînement sont en place.
- **Alpha — testé en privé.** La version actuelle a été testée dans un cadre fermé.

Les stratagèmes et les force dispositions seront intégrés dans un second temps : leur implémentation est techniquement simple, mais leur intégration par l'agent exigerait un volume d'entraînement important sans pour autant améliorer la pertinence de la démonstration.

## 4. Le précédent industriel : MTG Arena

Wizards of the Coast a fait face au même dilemme apparent lors du lancement de MTG Arena en 2018 : comment numériser un produit dont le modèle économique repose sur un objet de collection physique sans cannibaliser ce dernier ?

**Ce que montrent les chiffres.** Quand Arena est entré en bêta ouverte en septembre 2018, Magic comptait environ 30 à 35 millions de joueurs cumulés dans le monde depuis 1993. Hasbro annonce aujourd'hui plus de **50 millions de joueurs** et plus de **17 millions de comptes enregistrés sur Arena**. Il serait inexact d'attribuer cette croissance à Arena seul. Commander, les collaborations Universes Beyond et l'expansion internationale ont joué un rôle simultané. Mais c'est précisément le point : l'arrivée d'Arena n'a pas freiné la croissance physique. Sur la même période, le réseau de jeu organisé physique est passé d'environ 6 000 boutiques à plus de **10 000 boutiques WPN actives**, avec plus d'**un million de participants uniques** au jeu organisé physique en une seule année. Les deux canaux ont progressé en parallèle.

**Le chiffre qui répond directement à la crainte de cannibalisation.** En 2022, Hasbro a indiqué que les joueurs pratiquant à la fois le Magic plateau et Arena constituaient le **segment à la croissance la plus rapide** de leur base de clients, et dépensaient environ **40 % de plus** que le joueur Magic moyen. Ce n'est pas le numérique qui a capté la dépense physique : c'est l'engagement hybride qui a augmenté la dépense totale. Les joueurs qui jouent plus — sous toutes ses formes — achètent plus.

**Warhammer part d'une base de friction encore plus élevée.** Organiser une partie de Magic exige deux decks et une table. Organiser une partie de Warhammer 40,000 exige une armée assemblée et peinte, un plateau, du décor, un adversaire disponible, et plusieurs heures libres. Chacune de ces barrières disparaît dans un environnement numérique. Si une réduction modérée de friction a produit +40 % de dépense hybride pour Magic, l'effet pour Warhammer — dont les joueurs subissent structurellement plus de friction — devrait être au moins équivalent.

## 5. Valeur pour Games Workshop

**Deux clients, pas un.** La plateforme sert les joueurs directement, et sert simultanément Games Workshop comme outil de développement du jeu.

*Pour les joueurs :*

**Test de liste avant achat.** Les joueurs construisent et testent une liste numériquement avant d'acheter et de peindre les figurines — validant leurs achats en jeu plutôt qu'en les abandonnant après une première partie décevante.

**Entraînement tournoi.** Les joueurs compétitifs répètent les matchups, déploiements et séquences bien plus souvent que le jeu physique ne le permet, approfondissant leur engagement dans l'écosystème du jeu organisé.

**Parties plus courtes.** Une partie complète dure environ **une heure** contre trois à quatre heures physiquement. Plus de parties jouées signifie une maîtrise des règles plus rapide et un attachement plus fort à une faction.

**Acquisition de nouveaux joueurs.** Le moteur applique les règles, donc les débutants apprennent en jouant plutôt qu'en lisant. Cela supprime la principale barrière à l'entrée et crée un entonnoir vers le produit physique.

*Pour Games Workshop :*

**Play design assisté par IA.** Le moteur par apprentissage par renforcement peut simuler des milliers de parties par heure contre lui-même, produisant des win-rates par matchup, des données d'avantage du premier joueur et les performances anormales des unités pour n'importe quelle combinaison de rosters — **avant** la publication d'une dataslate, pas après. C'est quelque chose que MTG Arena ne fournit pas à Wizards à cette échelle : des données de simulation en amont de la publication, et pas seulement des données de réaction en aval.

Le cycle résultant : conception → simulation IA → playtest humain ciblé → publication affinée → données réelles → dataslate informée. Chaque étape est plus rapide et mieux étayée que ce que le playtest physique seul peut atteindre.

*Cadrage financier :*

Le chiffre d'affaires core de Games Workshop pour l'exercice 2025/26 s'élève à **£626,8 millions**, avec 890 000 utilisateurs My Warhammer actifs déjà sur la plateforme. En appliquant le benchmark de dépense hybride Magic de façon conservatrice — 25 % des clients devenant des joueurs hybrides avec une hausse de dépense de +20 % — on obtient environ **£31 millions de chiffre d'affaires core additionnel annuel**. Même le scénario le plus prudent (10 % des clients, +10 % de dépense) implique +£6 millions. Ce sont des estimations de sensibilité, pas des prévisions ; l'enjeu est que le levier est large par rapport au coût de sa création.

L'effet net : plus de parties jouées par joueur, maîtrise des règles plus rapide, achats de figurines dérisqués, et une boucle de feedback continue assistée par IA pour le développement du jeu de GW — tout cela soutient les ventes physiques plutôt que de leur faire concurrence.

## 6. Proposition

Le cœur du projet est pleinement fonctionnel et en expansion active — des modes de jeu additionnels, une couverture de factions plus large et du contenu campagne sont déjà en cours de développement. Une collaboration officielle serait mutuellement bénéfique : Games Workshop obtient une plateforme numérique contrôlée et fidèle aux règles qui stimule l'acquisition de nouveaux joueurs et les ventes de figurines tout en fournissant des données de développement de jeu assistées par IA ; le projet obtient une sanction officielle, l'accès aux données de règles faisant autorité et la légitimité auprès de la communauté.

Nous sommes ouverts à la discussion d'un accord de licence couvrant l'utilisation de la propriété intellectuelle et du contenu de règles de Warhammer 40,000, et accueillerions volontiers une première conversation pour explorer les termes.
