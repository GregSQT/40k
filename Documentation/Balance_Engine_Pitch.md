# Équilibrer Warhammer 40,000 par la mesure / Balancing Warhammer 40,000 by Measurement

*Document de présentation — Games Workshop*
*Presentation document — Games Workshop*

---

# 🇫🇷 VERSION FRANÇAISE

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
- Une **interface jouable** par des humains, avec rejeu et analyse des parties.
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

Un même moteur qui sert à la fois à équilibrer le jeu et à y faire entrer des joueurs n'est pas un
outil : c'est une infrastructure.

## 8. Ce que la simulation retire du travail — et ce qu'elle vous laisse

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

## 9. Où en est le projet, sans enjoliver

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

## 10. Ce que je propose

Je ne viens pas négocier de droits aujourd'hui. Votre univers est le vôtre, et le prototype ne
prendrait son sens qu'entre vos mains.

Ce que j'apporte est **l'instrument** : un moteur de simulation et une IA capables de mesurer ce
que quarante ans de playtest n'ont pas pu atteindre — et le potentiel de retourner votre critique
la plus ancienne en argument de vente.

Je suis disponible pour une démonstration en direct : l'IA joue, vous regardez.

---
---

# 🇬🇧 ENGLISH VERSION

## ⚡ Why now

Until recently, players who wanted to play Warhammer 40,000 remotely went through a general-purpose
physics sandbox: modelled miniatures, terrain, a tape measure, dice. And nothing else. The software
knows no rules. Players measure themselves, remember themselves, settle their own disagreements,
and trust each other.

That solution is no longer available. The need remains — and today it has no answer.

This document does not propose to replace it. It proposes something else: **an engine that knows
the rules, applies them, and makes mistakes impossible rather than leaving them to be argued out
between players.** The gap between the two is the gap between a car park and a racing circuit.

And it is an offering you control: it plays your rules, in your setting, with your approvals —
instead of a workaround you have no hold over.

What follows describes that same system and the internal use it makes possible: measuring the
game's balance.

## 1. A problem that was never solved — because it cannot be solved by hand

For forty years, the most persistent criticism levelled at Warhammer 40,000 has been neither its
setting, nor its miniatures, nor its rules: it is **balance**.

Let me clear up a misunderstanding first. This is not a failure of care, nor of competence. It is
a **mathematical wall**.

With several hundred available units and a 2000-point budget, the number of legal army lists runs
into the billions. The number of possible matchups is that number squared. And each matchup still
depends on terrain, mission, deployment, and decisions taken turn after turn.

No human playtest programme can cover that space. Not with ten testers, not with a thousand. It
is not a matter of effort — it is a matter of order of magnitude. Imbalance is not an isolated
mistake that harder work would have avoided: it is the inevitable consequence of a possibility
space no human team can explore.

**A problem of this kind is not solved by more rigour. It is solved by changing instrument.**

## 2. Why the current tools cannot get there

You already balance continuously — points updates, balance dataslates. The principle is right. It
is the **data** that is structurally insufficient:

- **It arrives too late.** Tournament feedback comes months after publication. Players have
  already lived through the imbalance — and the reputation is already made.
- **It is biased.** Only competitive players report results. And only already-popular lists get
  measured: a unit nobody plays generates no data, and therefore stays invisible — when its
  absence *is* precisely the symptom.
- **It is not counterfactual.** Tournament data tells you what happened. It never tells you what
  would have happened had that unit cost fifteen points less. Yet that is the only question that
  matters when deciding.
- **It covers almost nothing.** A few thousand games a season, across billions of combinations.

Playtesting and tournament data are not bad. They are simply **too slow, too narrow and too
retrospective** for the size of the problem.

## 3. What I bring: an AI that already plays Warhammer 40,000

This is not a concept or a feasibility study. It is a working system today:

- A **complete game engine**: movement, shooting, charging, close combat, terrain, objectives,
  three-dimensional line of sight, special weapon rules, phases and battle round.
- A **playable interface** for human players, with replay and game analysis.
- A **reinforcement-learning artificial intelligence** that plays the game — it deploys,
  manoeuvres, shoots, charges, fights and contests objectives.

And above all, one architectural choice that is the heart of this entire document: **the AI reads
unit characteristics before deciding.** It does not memorise "how to play Intercessors". It reads
a stat block — profile, weapons, special rules — exactly as a player would, then decides. It can
therefore handle a unit it has **never** encountered.

That is the hard part, and it is done. The consequence is decisive: **adding a unit or a rule
does not require rebuilding the AI.** The system absorbs new content.

What remains ahead is substantial but understood work: completing the catalogue of rules and
units, and providing training time. No research blocker. Time and resources.

## 4. From "it plays" to "it balances" — four steps

**Step 1 — The machine composes armies.**
Thousands of legal lists, all at the same budget, including ones nobody has ever tried. That
alone is coverage beyond the reach of any playtest.

**Step 2 — It plays.**
Hundreds of thousands of games, in parallel, with no display and no human. A game that takes
three hours on a table takes a fraction of a second here.

**Step 3 — It measures what survives competition.**
Not "who won": average win rate depends entirely on which opponents were selected, so it is both
manipulable and misleading. The right question is: **which armies are left standing once everyone
optimises?** A unit appearing in 98% of surviving lists is underpriced. A unit that never appears
is overpriced. And two unremarkable units whose pairing wins more than the sum of their
contributions: that is an abusive combination, detected before a player finds it.

**Step 4 — It searches for the right price.**
This is the step that makes the tool useful rather than merely interesting. The machine changes
the price, re-runs the simulation, and repeats until the unit becomes **one option among
several** — neither compulsory nor pointless. It does not tell you "this unit is too strong". It
tells you **what it should cost**.

## 5. What a game designer receives

A report readable in five minutes, not an engineering file *(illustrative figures)*:

| Unit | Current price | Recommended | Presence in optimal armies |
|---|---|---|---|
| Intercessor | 20 | **17** | 98% — auto-include, clearly underpriced |
| Dreadnought | 135 | 135 | 41% — healthy, no change |
| Terminator | 180 | **150** | 2% — effectively never played, dormant range |

> ⚠️ **Combination detected**: *Apothecary + Terminators*. Each is correctly priced on its own.
> Together they win 23 percentage points more than the sum of their contributions. Likely cause:
> the healing rule cancels the unit's intended weakness.

And one nuance most approaches miss: **a perfect AI is not a human player.** A unit that is hard
to handle will look excellent to a machine and disappoint your players. So we replay the same
matchups with a deliberately degraded AI. If the unit collapses, it is not mispriced — it is
**skill-intensive**. The remedy is not the same, and that distinction is exactly the one a
designer needs to make.

## 6. What this changes for Games Workshop

- **Balance before publication, not after.** Imbalance is corrected during design, not in an
  emergency dataslate three months later. What changes is not only the game — it is **when** you
  learn about the problem.
- **Test a rule before it exists.** Any new rule can be simulated before it is written,
  illustrated, printed. The cost of a late reversal is yours; here it becomes a compute line.
- **Wake the dormant range.** A unit nobody plays is a miniature nobody buys. The tool identifies
  those units — including the ones that generate no tournament data today, precisely because
  nobody plays them.
- **A permanent need, not a one-off purchase.** Every codex, every edition, every season recreates
  the problem. The instrument serves indefinitely.
- **Transferable to your other systems** — Age of Sigmar, Kill Team, Necromunda. The engine
  changes; the method does not.

## 7. The same engine answers a second problem: bringing new players in

The two armies my AI trains on are not chosen at random: **they are the ones from the 11th edition
starter set.**

Consider a new player. They are interested, they are on their own, nobody around them knows the
game, and there is £200 in front of them. Their barrier is not the price: it is learning a game of
this complexity alone, with no partner and nobody to correct their mistakes. Many give up at
exactly that point — not for lack of desire, but for lack of an opponent.

What the AI puts in a shop assistant's mouth:

> *"Here, take this address. It's free. You play with the miniatures from the box, and you learn
> the rules as you play."*

- An opponent **available immediately**, with no need to find one.
- Rules learned **by playing**, not by reading — the only method that actually works.
- They play **exactly the units they are about to buy**, not an abstract demo.
- And an AI that is still imperfect is an **ideal** opponent for a beginner: here it is not a
  limitation, it is the right difficulty.

It is measurable, and quickly: conversion rate on the starter set, with and without the tool.

The decisive point is this: **this application waits for nothing.** It requires neither the
complete catalogue nor months of additional training — it rests on exactly what already exists,
those two armies and this AI. Balancing is a programme of work; onboarding is available now.

A single engine that both balances the game and brings players into it is not a tool: it is
infrastructure.

## 8. What the simulation takes off your hands — and what it leaves you

Today, testing a balance change means playing games. And playing a game introduces two problems
nobody knows how to eliminate:

- **The players' skill.** A result depends on them as much as on the rules. Two unevenly matched
  testers, and the unit under test looks strong or weak with no way to tell which caused what.
- **The blind spot.** An interaction nobody thought to try stays invisible — until ten thousand
  players find it after publication.

**In simulation, the AI plays at the same level on both sides of the table. Player skill stops
being a variable.** What remains in the difference between results is the rules and the points:
exactly what you are trying to measure, and nothing else. This is not an argument from authority,
it is experimental control.

And a game takes one second. That change of scale changes the nature of the work: instead of
checking a handful of hypotheses picked in advance, you sweep the space — including the
combinations nobody would have thought of, which are precisely the ones that hurt.

**What does not change: you keep control.** Your designers define the reference lists, choose
which matchups to explore, and decide on the adjustments. The tool decides nothing and replaces no
judgement — it has no intent, no vision of the game, no taste. What it takes off your hands is the
work nobody wants: playing hundreds of games to test a hunch, and the standing fear of having
missed a combination the community will find on your behalf.

And something follows from that which matters beyond the studio: a balance decision stops being a
publisher's opinion set against a player's opinion. It rests on a measurement, made at equal skill
on both sides, across a volume of games no community could ever reach. The permanent controversy
over balance wears down the game's reputation as much as the imbalance itself; this is the first
lever that addresses it at the root.

Finally, **the same AI can be given back to the players** — as a training partner, a
tournament-preparation opponent, or a list-analysis tool. It is also, incidentally, a product.

## 9. Where the project stands, without embellishment

**Done:** the game engine, the playable interface, the automated replay and analysis pipeline, and
the AI architecture that reads unit characteristics — the foundation everything in this document
depends on.

**Missing:** the AI plays, but it does not yet play well enough for its verdicts to carry
authority. Measurement quality is capped by the strength of the player — I would rather state that
plainly than let you discover it. Also missing: the army generator, the analysis layer, and the
completion of the unit and rule catalogue.

**Why that gap is not a technical doubt:** nothing that remains requires a discovery. It requires
content to be entered, and compute time for training. Those are resources, not unknowns. That is
exactly why I am coming to you: I have built alone the part that cannot be bought, and I lack the
part that can.

## 10. What I am proposing

I am not here to negotiate rights today. The setting is yours, and the prototype would only make
sense in your hands.

What I bring is the **instrument**: a simulation engine and an AI able to measure what forty years
of playtesting could not reach — and the potential to turn your oldest criticism into a selling
point.

I am available for a live demonstration: the AI plays, you watch.
