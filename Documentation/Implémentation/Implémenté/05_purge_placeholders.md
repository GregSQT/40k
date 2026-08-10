# Chantier 05 — Purge des capacités placeholder
> ✅ **LIVRÉ le 2026-08-10** (commits `47ed073f`, `05d830fe`). Périmètre **élargi en cours de route** au-delà de ce qu'autorisait la section EXÉCUTION (6 datasheets SM hors rosters Armageddon) — la justification est en CONCEPTION, le prompt d'EXÉCUTION la contredit littéralement : c'est la CONCEPTION qui fait foi.
>
> Conséquence : les orks perdent la relance de charge ⇒ **toute mesure de win-rate antérieure est invalide**.
>
> **Série « chantiers capacités » (ex-`2_Various/`, dossier dissous le 2026-08-10).** Les chantiers **01 à 05 sont LIVRÉS** et rangés dans `Implémenté/` ; seul le **06** reste ouvert, dans `A_faire/`. Les renvois « chantier 0X » du texte désignent ces fichiers, qui ont gardé leur nom.
> Ordre du travail : [`../ROADMAP.md`](../ROADMAP.md) — ce fichier n'est pas une roadmap.

> **Deux cycles de vie.** **CONCEPTION** fait foi après livraison. **EXÉCUTION** est un
> prompt consommé une fois.

---

# CONCEPTION — à maintenir

## Le constat

Les neuf unités orkes des rosters Armageddon déclarent toutes :

```ts
static UNIT_RULES = [{ ruleId: "reroll_charge", displayName: "Unstoppable Valour" }];
static RULES_STATUS = { reroll_charge: 2 };
```

**Aucune des datasheets ne contient cette capacité.** Vérification faite sur
`Documentation/40k_rules/Armageddon/Datasheets - Orks.pdf`, les neuf pages : Warboss, Bigboss,
Bannernob, Painboy, Weirdboy, Boyz, Gretchin, Wartrakk, Big Mek Dakkarig. « Unstoppable
Valour » n'y figure pas une seule fois.

C'est un placeholder générique qui donne aujourd'hui une **relance de charge** à toute
l'armée orke. Ce n'est pas une capacité manquante : c'est une capacité **inventée**, active
dans le moteur, qui fausse tout entraînement et toute mesure de win-rate.

Le même placeholder existe côté Space Marines sur les personnages
(`CaptainRelicShield`, `ChaplainJumpPack`, `Ancient`, `Librarian` via `RULES_STATUS`) — à
vérifier unité par unité contre `Datasheets - Space Marines.pdf` avant de purger : certaines
capacités SM légitimes pourraient s'y cacher.

## Ce qui a réellement été livré (2026-08-10)

Périmètre élargi sur arbitrage, au-delà de ce que la section EXÉCUTION autorisait : les 6
datasheets SM **hors** rosters Armageddon portaient le même placeholder et sont purgées aussi
(les 4 Captain Terminator, `LeaderCaptainTerminator`, `LibrarianTerminator`) — invérifiables
contre un PDF, mais `CaptainTerminatorRelicWeaponBolter` est joué par
`config/armies/v10_space_marines.json`, donc le laisser aurait maintenu la relance de charge
fantôme en PvP.

**Aucune exception, aucune dette.** `CaptainPowerWeaponBolter` a été purgé en dernier, quelques
heures après les autres : les 8 tests de la règle 19.04 s'ancraient sur son `reroll_charge` et
n'avaient pas d'autre porteur. Ils reposent désormais sur un couple de vraies datasheets —
`ChaplainJumpPack` (`deep_strike`) mené sur `AssaultIntercessorJumpPack` (`charge_impact`),
discriminant dans les deux sens, légal au titre de 19.01.

Le report avait d'abord été envisagé jusqu'à la passe 1 du chantier 06. Il a été écarté sur une
mesure : cette datasheet est jouée par deux rosters de **benchmark KPI** de CoreAgent
(`agent_training_roster_balanced_balanced_kpis_v21.json`, 150 et 500 pts) et par quatre scénarios
PvP. Une dette sans échéance dans un roster de mesure, c'est exactement le défaut que ce chantier
existe pour supprimer.

Ce que la bascule coûte : le test d'OBSERVATION suit maintenant la règle du BODYGUARD et non
celle du leader, parce que `deep_strike` n'a pas d'`obs_id`. Coût réel nul — l'observation lit
`unit["UNIT_RULES"]`, l'union déjà calculée, et ne distingue pas l'origine d'une règle ; quelle
source s'éteint quand reste verrouillé source par source par les 7 autres tests.

## Un second défaut, mineur

`RULES_STATUS = { leader: 0 }` (« non implémenté ») est **périmé** : le rattachement
leader/support est implémenté (règle 19.01/19.04, `engine/game_state.py:846`
`_fold_attached_characters`). Le statut ment sur l'état réel du moteur.

## Pourquoi un chantier séparé

Une suppression isolée dans l'historique git s'annule proprement. Fondue dans le chantier 06
— qui réécrit les `UNIT_RULES` des mêmes fichiers — elle deviendrait indiscernable de
l'ajout des vraies capacités.

Coût assumé : les neuf fichiers orks sont touchés deux fois (ici, puis en 06). C'est
négligeable.

**Aucun état intermédiaire cassé** : une unité sans `UNIT_RULES` est parfaitement valide.
`frontend/src/roster/spaceMarine/units/Intercessor.ts` n'en déclare aucune et fonctionne.

## Ordre

À lancer **juste avant le chantier 06**, pas plus tôt. Entre les deux, les unités orkes n'ont
aucune capacité — état légal mais sans intérêt, à ne pas laisser durer.

## Effet attendu sur le jeu

Les unités orkes **perdent** la relance de charge. C'est une régression de puissance
volontaire et conforme aux règles. Elle se verra sur le win-rate ; c'est normal, et c'est
précisément pourquoi la mesure d'avant est fausse.

---

# EXÉCUTION — prompt

## Périmètre

**Autorisé :**
- `frontend/src/roster/ork/units/*.ts` — les 9 unités des rosters Armageddon
- `frontend/src/roster/spaceMarine/units/*.ts` — **uniquement** celles dont la vérification
  PDF prouve le placeholder
- Tests ciblés impactés
- `Documentation/Unit_rules.md` si le retrait change un exemple documenté

**Interdit :** ajouter la moindre capacité (c'est le chantier 06), toucher aux unités hors
rosters Armageddon, refactorer les fichiers au passage.

## Étapes

1. **Vérifier avant de supprimer.** Pour **chaque** unité, relire la datasheet du PDF et
   confirmer que la capacité déclarée n'y figure pas. Ne pas purger sur la foi de ce
   document : c'est le PDF qui fait foi.
2. Retirer les entrées `reroll_charge` / « Unstoppable Valour » confirmées comme inventées.
3. Corriger les `RULES_STATUS` périmés : `leader` et `support` sont **implémentés**.
4. Vérifier qu'aucune unité ne se retrouve avec un `UNIT_RULES` mal formé (liste vide plutôt
   que champ absent, ou l'inverse selon la convention du chargeur — lire
   `engine/game_state.py:183` avant de trancher).

## Vérification exigée

- **Jumeau obligatoire** : `grep -rn "Unstoppable Valour" frontend/ config/ engine/` →
  rapporter le nombre de hits **avant** et **après**, et justifier chaque hit conservé.
- **Verrou de comportement** : test moteur montrant qu'une escouade de Boyz **ne relance
  plus** son jet de charge. Remettre la règle → le test devient **rouge**. Le prouver.
- `npx tsc --noEmit -p tsconfig.app.json` sur le frontend.
- Confirmer explicitement, unité par unité, que la datasheet a été relue.

## Pièges

- **Ne pas purger aveuglément.** Certaines unités SM ont de vraies capacités qui ressemblent
  à des placeholders. Le critère est la lecture du PDF, rien d'autre.
- Ne pas en profiter pour renommer, réordonner ou nettoyer les fichiers : hors périmètre.
- Le frontend et le backend lisent les mêmes définitions. Vérifier que le retrait se propage
  jusqu'à `game_state`, pas seulement à l'affichage.
