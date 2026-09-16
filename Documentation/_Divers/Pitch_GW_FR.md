# L'esprit de la machine chez Games Workshop ?

*Document de présentation — Games Workshop*

---

## La question qu'on pose mal

"Quand Games Workshop franchira-t-il le cap de l'IA ?"

Ce document répond à une question plus précise : que pourrait apporter à Games Workshop une IA sachant jouer à Warhammer 40,000 ?

---

## 1. Le premier gain : en interne

### L'expertise humaine est inestimable, pas le temps

Les développeurs et testeurs de Warhammer 40,000 sont une ressource précieuse. Leur expérience, leur expertise, leur intuition du jeu sont inestimables — elles ont mis des années à se construire et ne peuvent pas s'automatiser.

Mais leur temps est limité. Et le rythme des sorties — codex, équilibrages, nouvelles éditions — est soutenu.

C'est là qu'une IA sachant jouer à 40K devient un **facilitateur**.

### De l'intuition à la mesure, en quelques minutes

Mise en situation : un testeur expérimenté repère une combinaison qui semble trop forte, une valeur d'unité difficile à calibrer, une "force composition" dont l'équilibrage lui paraît perfectible.

Vérifier cette intuition demande de jouer des parties. Et jouer des parties introduit deux problèmes structurels que, aujourd'hui, personne ne sait éliminer :

- **L'objectivation.** Même après plusieurs parties, il demeure très délicat de statuer sur des points très sensibles pouvant impacter tout un pan du jeu.
- **L'angle mort.** Une interaction non testée reste invisible jusqu'à ce que dix mille joueurs la trouvent après publication.
- **Le niveau des joueurs.** Un résultat dépend d'eux autant que des règles. Deux testeurs inégaux, et la conclusion est faussée — sans qu'on puisse démêler la cause.

Ce que leur apporte une IA :
Des milliers de parties et autant de statistiques par heure. Des datas, objectives, concrètes, sur lesquelles ils pourront s'appuyer pour statuer sur le point testé de manière objective.

A ceci il faut ajouter une nuance que la plupart des approches ratent : **une IA parfaite n'est pas un joueur humain.** Une unité difficile à manier paraîtra excellente à une machine et décevra vos joueurs. On rejoue donc les mêmes affrontements avec une IA volontairement dégradée. Si l'unité s'effondre, elle n'est pas mal évaluée — elle est **technique**. Ce n'est pas le même remède, et c'est exactement la distinction qu'un designer a besoin de faire.

### Le danger écarté

On pourrait objecter : l'IA ne va-t-elle pas "terminer" le jeu en définissant la liste optimale pour chaque codex ? Trouver la liste optimale demanderait une fonctionnalité distincte — une boucle d'optimisation sur les compositions d'armée, qui n'existe pas dans ce moteur. Ce n'est pas un oubli : c'est un choix d'architecture. Et une fois cet outil entre vos mains, c'est vous qui décidez si cette fonctionnalité voit jamais le jour.

---

## 2. La virtualisation : Un saut dans l'inconnu ?

### Le précédent — comment Magic a répondu à la même question

La première objection que soulève ce projet est prévisible : une plateforme numérique officielle ne va-t-elle pas réduire les achats de figurines ?

Magic: The Gathering a dû répondre à cette même question en 2017-2018. Son économie reposait sur la vente d'un produit physique qu'on achète, qu'on collectionne et dont on a besoin pour jouer — exactement comme Games Workshop. La crainte de cannibalisation y était encore plus directe : une carte numérique remplace explicitement la carte physique correspondante.

Wizards a lancé MTG Arena en bêta ouverte en septembre 2018. Ce qui s'est passé ensuite répond à la question.

**En février 2018, avant le lancement de la bêta ouverte d'Arena, Wizards estimait à environ 30 millions le nombre de personnes ayant joué à Magic sur les 25 années précédentes.** Dès décembre 2018, ce chiffre dépassait déjà les 35 millions. **Aujourd'hui, il dépasse 50 millions** — dont plus de 17 millions de comptes numériques enregistrés sur Arena seul. Dans le même temps, le réseau de boutiques physiques WPN est passé d'environ **6 000 boutiques en 2019** à plus de **10 000 boutiques actives fin 2025** (+20 % sur la seule dernière année), avec plus d'un million de joueurs uniques ayant participé au jeu organisé physique en 2025 (+22 % sur un an).

Le numérique n'a pas remplacé le physique. Les deux ont progressé ensemble.

### Le chiffre qui répond à la crainte

Dans son rapport annuel 2022, Hasbro identifie les joueurs **hybrides** — ceux qui pratiquent à la fois le Magic de table et le digital — comme sa **catégorie de joueurs Magic à la croissance la plus rapide**, avec "le niveau de dépense le plus élevé, à 40 % au-dessus du revenu moyen par joueur Magic toutes pratiques confondues". Hasbro ne publie pas la taille exacte de ce segment, mais le juge suffisamment stratégique pour le mettre en avant dans son rapport aux investisseurs.

Pour Games Workshop, avec un chiffre d'affaires core de £626,8 M en 2025/26 : même une progression modeste du panier d'une fraction des hobbyists hybrides représente plusieurs dizaines de millions de livres de valeur annuelle potentielle — sans compter les revenus numériques directs.

Ce chiffre de +40 % répond directement à la crainte de cannibalisation. Les données de Hasbro suggèrent précisément l'inverse chez les joueurs hybrides.

### Ce que GW ajouterait que Magic ne fait pas

Arena fournit à Wizards des données massives *après* publication. GW obtiendrait cela aussi — mais avec un avantage supplémentaire décisif : grâce à l'IA, la simulation est disponible **avant** publication.

Le cycle deviendrait :

> conception → **simulation IA** → playtest humain → **simulation IA** → publication → données réelles → analyse → dataslate

Wizards n'a accès qu'à la moitié droite de ce cycle. GW aurait les deux.

### Ce que GW possède déjà

Games Workshop n'aurait pas à partir de zéro. À fin mai 2026 :

- **890 000 utilisateurs actifs My Warhammer** (interactions au cours des six derniers mois), contre 735 000 l'année précédente (**+21 %**)
- **269 000 abonnés Warhammer+**, contre 232 000 un an auparavant (**+16 %**)
- Plus de **1,5 million de spectateurs uniques** pour le dernier World Championships

La plateforme, la facturation, la base de clients : il n'y a rien à construire autour. Il manque une raison de revenir chaque semaine.

### La structure qui protège le physique

Wizards a séparé deux environnements. **Standard Arena** reproduit exactement le Standard physique — même cartes, mêmes règles, mêmes bannissements. Un joueur s'entraîne sur Arena et joue physiquement le lendemain sans déphasage. **Alchemy** est un espace exclusivement numérique : cartes propres au digital, mécaniques impossibles sur table, rééquilibrages fréquents — et il n'interfère jamais avec le Standard physique.

Pour GW, une architecture analogue :

| WARHAMMER OFFICIEL | WARHAMMER LAB |
|---|---|
| Règles tabletop exactes | Futurs équilibrages en test |
| Parties humaines et IA | Nouvelles unités avant publication |
| Tournois et matchmaking | Missions expérimentales |
| Données de tournoi en ligne | Simulation IA avant sortie |

Le premier environnement est entièrement aligné avec le tabletop. Le second permet à GW de faire ce qu'il est impossible de faire avec des figurines déjà imprimées et des codex déjà vendus.

---

## 3. Les gains commerciaux

### Un besoin sans réponse

Jusqu'à récemment, les joueurs voulant jouer à Warhammer 40,000 à distance n'avaient aucune solution officielle : des figurines modélisées par des tiers, un mètre virtuel, des dés — et aucune règle connue du logiciel. Le joueur mesurait lui-même, appliquait les règles lui-même, arbitrait lui-même les désaccords. Cette demande existe, elle n'a pas de réponse officielle aujourd'hui.

Ce que j'apporte n'est pas un substitut : c'est un moteur qui connaît les règles et les applique, rendant les erreurs et les tricheries impossibles. Il offre aux joueurs une expérience et un confort qu'aucune plateforme tierce, officielle ou non, ne leur avait encore proposé.

### Faire entrer les nouveaux joueurs

Les deux armées sur lesquelles mon IA s'entraîne ne sont pas choisies au hasard : **ce sont celles de la boîte de base de la V11.**

Un nouveau joueur, seul, avec 200 € de budget : sa barrière n'est pas le prix — c'est la crainte de devoir apprendre seul un jeu de cette complexité, sans partenaire, sans personne pour corriger ses erreurs. Beaucoup renoncent exactement là, non par manque d'envie, mais par manque d'accès à une initiation.

Ce que l'IA met dans la bouche d'un vendeur :

> *"Voilà une URL, c'est gratuit. Jouez avec les figurines de la boîte, apprenez les règles en jouant."*

- Un adversaire **disponible immédiatement**, sans avoir à en trouver un.
- Les règles apprises **en jouant**, pas en lisant — la seule méthode qui fonctionne vraiment.
- Il joue **exactement les unités qu'il s'apprête à acheter**, pas une démonstration abstraite.

C'est mesurable, et rapidement : taux de conversion sur la boîte de base, avec et sans l'outil. Et cette application n'attend rien : elle repose sur ce qui existe déjà, ces deux armées et cette IA.

Le numérique ne devient pas le concurrent de la figurine. Il en devient l'accélérateur.

### Un abonnement qu'on ne résilie pas

Vous avez déjà le service, la facturation, les clients : il n'y a rien à construire autour.

Ce que ce service propose aujourd'hui est du contenu qui se **consomme** — on le regarde, puis on attend la suite. Un jeu, lui, se **pratique** : chaque semaine, indéfiniment.

Cette distinction décide de la vie d'un abonnement. **Un service ne se juge pas sur ce qui fait souscrire, mais sur ce qui empêche de résilier.** Un catalogue qu'on a fini de regarder ne retient personne. Une partie en cours ramène le joueur, et surtout **entretient son lien avec le jeu**. Vous n'ajouteriez pas un contenu de plus à proposer : vous ajouteriez une **raison de rester**.

Les joueurs à qui le jeu a été montré n'ont pas demandé s'il sortirait un jour. Ils ont demandé comment y accéder, et combien ça coûterait. Ce n'est pas une étude de marché — c'est ce que j'ai constaté, spontanément, à chaque fois.

Et c'est la seule des applications dont le revenu se calcule directement : un abonnement est un revenu récurrent, attribuable, projetable.

---

## 4. L'image — faire d'une difficulté une force

L'équilibrage de Warhammer 40,000 est un mur mathématique. Avec plusieurs centaines d'unités et un budget de 2000 points, le nombre d'affrontements possibles est astronomique. Aucun programme de playtest humain ne peut couvrir cet espace — ce n'est pas une question d'effort, c'est une question d'ordre de grandeur.

Avec cet outil, cette critique ne disparaît pas — elle **se retourne**.

Une décision d'équilibrage cesse d'être une opinion d'éditeur opposée à l'opinion d'un joueur. Elle repose sur une mesure, faite à niveau de jeu égal, sur un volume de parties qu'aucune communauté ne pourra jamais atteindre. La controverse permanente sur l'équilibrage use la réputation du jeu autant que le déséquilibre lui-même — c'est le premier levier qui l'attaque à la racine.

Et pour les joueurs à distance : le besoin de jouer en ligne — sur vos règles, dans votre univers, sans arbitrage manuel — est aujourd'hui sans réponse. Le premier à y répondre récupère un segment que le retrait des outils tiers a laissé vacant.

---

## 5. Ce qui existe — l'état de l'art

Ce moteur a été conçu et développé seul, en dehors de toute structure.

**Fait :** le moteur de jeu complet (commandement, mouvement, tir, charge, corps-à-corps, terrain, ligne de vue en 3D, objectifs, règles d'armes, tour de bataille), l'interface jouable, la chaîne de rejeu et d'analyse automatisée, et l'architecture d'IA qui **lit les caractéristiques des unités avant de décider** — elle ne mémorise pas "comment jouer les Intercessors", elle lit une fiche technique exactement comme un joueur, puis décide. Ajouter une unité ou une règle ne demande pas de reconstruire l'IA : le système absorbe le contenu nouveau.

La fiabilité du moteur n'est pas un détail technique. Une mesure d'équilibrage ne vaut que ce que vaut le moteur qui la produit :

- **7 113 tests automatisés**, nommés d'après les règles officielles qu'ils vérifient — lisibles sans savoir coder.
- **Chaque test est validé en réintroduisant volontairement le défaut** qu'il doit attraper. Un test qui passe du premier coup ne prouve rien ; on vérifie qu'il échoue quand il doit échouer.
- **Des parties entières jouées au hasard, en continu**, pour débusquer les incohérences que personne n'a pensé à tester.

**Les limites et les choix :** La démonstration a été mise au point avec un matériel grand public, avec les limites évidentes que cela implique. Cependant, le moteur a été pensé pour être utilisable à plus grand format, et la qualité de jeu de l'agent n'est qu'une question de ressources pour l'entraîner.

Le moteur utilise une grille hexagonale — un prérequis pour que l'IA puisse s'entraîner : un espace continu rend la convergence du reinforcement learning prohibitivement longue. La granularité retenue (1 pouce = 5 hexagones) est un compromis entre précision et temps d'entraînement, pas une contrainte d'architecture. Le moteur gère déjà deux résolutions différentes, augmenter la granularité est une question de ressources de calcul et ne nécessiterait pas de refonte du moteur.

En termes de jeu, les compositions d'armée (force organisations), objectifs secondaires, stratagèmes et améliorations ne sont pas encore implémentés : les ajouter ne représente pas une difficulté technique, mais aurait complexifié / ralenti l'entraînement, pour des aspects qui ne sont pas significatifs dans le cadre de la démonstration.

L'interface s'inspire visuellement des rapports de bataille du White Dwarf. C'est un repère familier, pour un projet développé seul — l'enjeu de la démonstration est ce que le moteur calcule, pas l'habillage visuel.

---

## 6. Ce que je propose

Ce document a posé une question — que peut apporter une IA sachant jouer à 40K — et je viens de vous présenter ma réponse.

Ce que j'apporte est la fondation : un moteur de simulation intégrant les règles de Warhammer 40,000 et, dans un premier temps, une IA à double usage : un partenaire de jeu disponible à tout moment pour vos joueurs, un outil d'objectivation pour vos développeurs et testeurs.

La meilleure façon de juger d'un outil qui joue, c'est de le regarder jouer. Je suis prêt pour une démonstration en direct, quand vous le souhaitez.

---

*Sources chiffrées (disponibles sur demande) : rapport annuel Games Workshop 2025/26 (revenu, My Warhammer, Warhammer+, World Championships) ; Hasbro Investor Relations — page Magic: The Gathering (>50M joueurs, >17M comptes Arena) ; Hasbro Annual Report 2022 (joueurs hybrides, +40 %) ; Hasbro résultats T4/année 2025 (WPN stores, Organized Play) ; interview Chris Cocks, février 2018 (~30M joueurs avant Arena) ; communiqué Hasbro/Wizards, décembre 2018 (>35M joueurs) ; Wizards, mars 2019 (~6 000 WPN stores).*