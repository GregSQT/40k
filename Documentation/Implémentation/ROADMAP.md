# ROADMAP — source unique de l'ordre du travail

> **Rôle.** Ce fichier est la SEULE source de vérité sur « qu'est-ce qu'on fait ensuite ».
>
> **Trois dossiers, trois rôles distincts** (`2_Various/` dissous le 2026-08-10) :
>
> | Dossier | Contient | Ce qu'on y cherche |
> |---|---|---|
> | [`1_Agent/`](1_Agent/) | la spec et l'état du programme V11 (4 docs) | le **détail** d'une tranche, un piège de méthode |
> | [`A_faire/`](A_faire/) | le backlog des chantiers ouverts | le **contenu** d'un chantier à faire |
> | [`Implémenté/`](Implémenté/) | les chantiers livrés | la **référence** de conception d'un truc déjà fait |
> | **racine** (2 docs) | les **références transverses vivantes** : [`Replay.md`](Replay.md) (contrat `step.log`, pipeline, registre replay) et [`analyzer_couverture.md`](analyzer_couverture.md) (matrice règle → contrôle → champs de log) | ce que le journal **porte**, et ce qu'il **ne porte pas encore** |
>
> Aucun des quatre ne donne l'ordre du travail — il est **ici, et nulle part ailleurs**.
> ⚠️ Les deux docs racine ne sont ni des chantiers à faire, ni des chantiers livrés : ce sont des
> **contrats permanents**, relus à chaque livraison qui touche le journal. Ils portent en revanche
> du travail ouvert, et **ce travail a sa ligne en §4** — ajoutée le 2026-08-10, quand on a constaté
> qu'ils n'étaient cités nulle part ici alors que ce fichier se déclare source unique de l'ordre.
> ⚠️ **Une troisième chose traîne à la racine et n'y a pas sa place** : [`Security.md`](Security.md)
> est un **chantier ouvert** (étapes 4→8, §4), donc du ressort d'`A_faire/` selon la 2ᵉ ligne de ce
> tableau. Son déplacement à la racine a d'ailleurs cassé le lien relatif que
> `A_faire/perf_noyau_natif_et_gzip.md` pointait vers lui (réparé le 2026-08-10, seul lien mort du
> corpus). Le remettre en `A_faire/` est un `git mv` + 2 liens : à faire, ou assumer la 3ᵉ exception.
>
> **Règles d'arbitrage entre docs** (établies le 2026-08-10) :
> 1. **Le code fait foi** sur fait/pas fait. Un doc contredit par le code est périmé, pas le code.
> 2. **La décision datée la plus récente tranche l'approche.** Les décisions sont recensées dans
>    `V11_agent_rework.md` §0 (tableau récapitulatif) et dans les amendements des chantiers.
> 3. **Sur les priorités, ce fichier l'emporte** sur tout autre doc, y compris `V11_agent_rework.md`
>    §0 et sa colonne « Ordre ». Sur le détail et l'état de V11, c'est l'inverse.
> 4. Conflit résiduel → section « Arbitrages ouverts » ci-dessous, tranchée par l'utilisateur.
>
> **Discipline.** Tout nouveau chantier prend une ligne ici AVANT d'ouvrir un doc de détail.
> Un chantier livré passe son doc en `Implémenté/` et sa ligne ici à jour DANS la même livraison.
>
> État vérifié contre le code le **2026-08-10** (tous dossiers balayés, exécutions à l'appui).

---

## 0. En cours — ne rien casser

- ✅ **Run `--new` ArmageddonAgent x1 — TERMINÉ** (PID 842478 absent, dernier checkpoint 15 h 18,
  `run_20260810-111734`). C'était une **base de développement, PAS la mesure** (décision
  2026-08-10) : modèle chargeable + sortie d'`analyzer.py` pour les tranches P3, rien de plus. Son
  modèle deviendra inchargeable dès P3-4. `x1` = **10 000 épisodes** (`total_episodes`, et non
  50 000 qui est la clé de commentaire `total_episodes_normal`).
  → [`1_Agent/V11_agent_rework.md`](1_Agent/V11_agent_rework.md) §0.70
- **Conséquence immédiate : plus rien n'est gelé.** La consigne « ne rien lancer de cassant, aucun
  JSON de `config/` » tombe avec le run. Ce qui était différé à ce titre redevient faisable —
  notamment la `justification` d'`obs_size` (§5) et l'ajout d'un profil de validation P5 (§1 pt 6).
- ⚠️ **Rien n'est en cours. Cette section doit être VIDE ou décrire un run vivant** — un 🟢 périmé
  gèle du travail pour rien, ce qu'il a fait entre 15 h 18 et sa correction.

## 1. Chemin critique vers la mesure de référence

Ordre imposé par les décisions du 2026-08-07 et 2026-08-10 : la mesure de référence (`x1_long`,
600 parties/bot) est **différée** jusqu'à livraison de tout ce bloc. D'ici là le projet est SANS
mesure, et c'est assumé (§0.14).

1. **P3-4 — Allocation des pertes défenseur** (= L3) → [`1_Agent/V11_phaseA.md`](1_Agent/V11_phaseA.md) §9.4 pt 4
2. **P3-5 — Pile-in / consolidation** (= L4) — **bloqué en amont** par la migration par-figurine
   du pile-in auto V11 → [`A_faire/pile_in_overrun_par_figurine.md`](A_faire/pile_in_overrun_par_figurine.md).
   Décision spatiale ⇒ top-K d'hex interdit (§9.0bis).
   🔴 **Le périmètre décrit en §9.4 pt 5 était FAUX et a été corrigé le 2026-08-10 (lecture de
   `12 Fights pahse.pdf`) : le MODE de consolidation n'est pas un choix de joueur** (12.08 l'impose
   par la situation) ; les décisions réelles sont consolider ou non, quelles unités ennemies
   sélectionner, et la destination. S'y ajoute un **écart aux règles**, pas seulement au PvP : le
   gym ne sait pas consolider vers un objectif. → [`1_Agent/V11_phaseA.md`](1_Agent/V11_phaseA.md) §9.4 pt 5
3. **P3-6 — Move-after-shooting + reactive move** (= L5) → [`1_Agent/V11_phaseA.md`](1_Agent/V11_phaseA.md) §9.4 pt 6
4. **P3-8 — Optionnels à statuer** (= L7→L11) — le choix d'arme en mêlée (§0.69) est déjà acté
   en ordre 3 ; le reste (split-fire, multi-cibles charge, placement final, stratégies de
   déploiement) exige de **mesurer le regret** avant de trancher (§9.0bis).
   🟢 **Décision 2026-08-10 (3) — la circularité est tranchée : le regret se mesure sur la BASE DE
   DÉVELOPPEMENT en cours** (§0.70), pas après la mesure de référence. Le regret est un écart
   *relatif* (choix branché vs heuristique auto) : il supporte l'imprécision d'un run de 10 000
   épisodes, et l'alternative — statuer après la mesure — rachèterait un `x1_long` complet (~20 h)
   au premier optionnel retenu. → [`1_Agent/V11_phaseA.md`](1_Agent/V11_phaseA.md) §9.4 pt 8
5. **P4 — Observation de support** (= L12, ne se livre pas seule) → [`1_Agent/V11_phaseA.md`](1_Agent/V11_phaseA.md) §9.5
   ⚠️ **Ordre à ne pas prendre au pied de la lettre** : les features de §9.5 (LoS/couvert par slot
   ennemi, portée effective, flags advanced/fell_back) sont ce qui rend P3-4 et P3-6 apprenables.
   Livrées APRÈS, elles font échouer le critère P5 de ces tranches pour une raison connue d'avance.
   Chaque feature part **avec** la tranche qui en dépend ; ce point 5 ne garde que le reliquat.
6. **P5 — Validation par tranche** (protocole jamais appliqué depuis sa rédaction).
   🔴 **AUCUN PROFIL EXISTANT NE CONVIENT — à trancher avant d'ouvrir P3-4.**
   - Ce qui est **acquis** : le « ne PAS utiliser `x1_debug`, il porte 48 envs » de §9.6 est
     périmé. `n_steps` est un TOTAL divisé par `n_envs` en un point de passage unique depuis
     §0.33 ⇒ le buffer ne dépend plus de `n_envs`, et les **7** profils sont à 48 envs de toute
     façon, `x5_debug` compris. La mémoire n'écarte plus aucun profil.
   - Ce qui **casse** : `x1_debug.total_episodes` vaut **10** (et non 480 — la valeur a changé en
     commit après la rédaction de cette ligne le 2026-08-10 ; recompté depuis la config). Et
     `total_episodes` est un total **GLOBAL** tous environnements confondus
     (`self.episode_count += episodes_finished`, `ai/training_callbacks.py:201`), pas un par-env.
     Reste `x5_debug` = **96**. Comparer deux win-rates par tranche sur 10 ou 96 parties, c'est
     mesurer du bruit : à 96, l'erreur-type autour de 0,5 vaut ~5 points (IC95 ≈ ±10).
   - **Le protocole §9.6 conditionne l'ouverture de CHAQUE tranche P3 à ce chiffre.** Le mesurer
     avec un instrument trop court revient à ne pas le mesurer, et P3-4 serait validée sur du bruit.
   - **À faire** : ajouter un profil de validation dédié (~500-1000 épisodes) à
     `ArmageddonAgent_training_config.json`. Plus rien ne l'interdit depuis la fin du run (§0).
     → [`1_Agent/V11_phaseA.md`](1_Agent/V11_phaseA.md) §9.6
7. **Mesure de référence** `x1_long` — solde §0.14, §0.67, critère T6 (via §10.6) d'un coup.
8. **§0.59 — Phase 2 self-play** (`--append x1_selfplay`) — livré, JAMAIS exécuté ; le premier
   run est aussi son premier test d'intégration. → [`1_Agent/V11_agent_rework.md`](1_Agent/V11_agent_rework.md) §0.59

## 2. Capacités — seul chantier restant de la série « chantiers capacités »

- **06 — Capacités Armageddon** : 0/6 passes, tous prérequis (01→05) livrés et vérifiés.
  Passes 1-2 d'abord (12 capacités sans nouvelle structure d'état) ; FNP déjà câblé côté moteur.
  ⚠️ Risque concret : `UNIT_ABILITY_SLOTS = 8` ([`engine/observation_entities.py:274`](file:///home/greg/40k/engine/observation_entities.py))
  est une projection — si une entité dépasse 8 capacités en vigueur, le moteur lève.
  → [`A_faire/06_armageddon_abilities.md`](A_faire/06_armageddon_abilities.md)
- Les chantiers **01→05 sont livrés** (vérifié code, 2026-08-10) et rangés en `Implémenté/` :
  [01 embedding](Implémenté/01_ability_embedding.md) · [02 CP/battle-shock](Implémenté/02_command_points.md) ·
  [03 capacités de faction](Implémenté/03_faction_abilities.md) · [04 réserves](Implémenté/04_strategic_reserves.md) ·
  [05 purge placeholders](Implémenté/05_purge_placeholders.md). Leur section CONCEPTION reste la
  référence vivante ; leur EXÉCUTION n'a plus que valeur d'historique.

## 3. Suspendus à un jalon explicite — ne pas commencer avant

- **T7 — Unification validation de déploiement** — déclencheur : « le training tourne ».
  🔴 Le fix décrit est FAUX en l'état (mesuré 2026-07-20) ; c'est une décision de design
  (plan contraint par l'ancre), pas un bug. → [`1_Agent/V11_tranches.md`](1_Agent/V11_tranches.md) §5 T7
- **Phase B — Observation des niveaux** (= L13) — après Phase A' validée ET vérification du
  chantier LoS 3D (`combat_utils`/WASM, câblage incomplet). → [`1_Agent/V11_tranches.md`](1_Agent/V11_tranches.md)
- **É9 — Second siège + second scénario** — après entraînement bot satisfaisant ; second
  scénario écrit par l'utilisateur (décision 2026-08-02). → [`1_Agent/V11_agent_rework.md`](1_Agent/V11_agent_rework.md) §0.47
- **§10.6 volet 2 — Validation qualitative par un joueur externe** — requis pour la démo, au
  même titre que le quantitatif. → [`1_Agent/V11_eval_strategy.md`](1_Agent/V11_eval_strategy.md) §10.6
- **§10.7 — MCTS à l'inférence** — plan B anti-coups-absurdes, « à ne PAS anticiper » avant la
  mesure ; risque = latence en démo. → [`1_Agent/V11_eval_strategy.md`](1_Agent/V11_eval_strategy.md) §10.7
- **Dette d'ancre G1/G2/G4** — recensement en fiabilité dégradée ; interdiction d'ouvrir un
  chantier depuis une ligne non ✅. → [`1_Agent/V11_tranches.md`](1_Agent/V11_tranches.md) §1bis

## 4. Backlog hors chemin critique (`A_faire/`)

Prêts à démarrer sans décision produit :
- **Security étapes 4→8** (~4-5 j ; étapes 1-3 livrées, suivi à jour ; étape 5 = durcir la stack Docker existante, pas la créer) → [`Security.md`](Security.md)
- **Tests front — reste T2b/T3a/T7 (couche A) + couches B (vitest) et C (Playwright)**
  (~10 j au total, sécable) → [`A_faire/front_test_auto.md`](A_faire/front_test_auto.md)
- **Perf `generate_compact_formation`** (½-1 j) — MESURER avant d'implémenter, gain non acquis
  → [`A_faire/perf_generate_compact_formation.md`](A_faire/perf_generate_compact_formation.md)
- **gzip/Brotli** (½ j) — à faire AVEC l'étape 5 de Security (même proxy)
  → [`A_faire/perf_noyau_natif_et_gzip.md`](A_faire/perf_noyau_natif_et_gzip.md) §1
- ~~**Résidu front V10 des sous-phases fight**~~ — **LIVRÉ le 2026-08-10.** Les deux cascades de
  `useEngineAPI.ts` et les 3 champs morts de son interface sont supprimés ; le pool CC vient de
  `getFightActivationPoolUnitIds` (`fight_eligible_units`), source unique partagée avec le clic
  manuel. `grep` des 5 sous-phases V10 et des 3 champs : **0 hit** front comme backend.
  ⚠️ Ce n'était PAS un nettoyage neutre — voir le changement de comportement de l'auto-play PvP
  décrit en [`Replay.md`](Replay.md) §4.B, **à confirmer en session PvP fight réelle**.
- **Champs manquants du `step.log`** (sécable, **27** entrées ordonnées par nombre de règles
  débloquées : `L1`, puis `L3`→`L28` — **`L2` a été retirée**, S/T sur les jets étant livrée).
  Ce n'est pas un chantier d'un bloc : chaque champ se livre seul et fait passer des règles de
  « non vérifiable » à « vérifiable » par l'analyzer. À piocher quand un contrôle analyzer manque
  de données. *(Cette ligne a annoncé « 15 entrées, L1…L15 » jusqu'au 2026-08-10 : le tableau
  avait été lu jusqu'à `L15` seulement, sans en chercher la fin. Recompter, ne pas extrapoler.)*
  → [`analyzer_couverture.md`](analyzer_couverture.md) §7

Bloqués par une décision utilisateur :
- **Replis `unit_by_id`** — T0 (signature de `require_unit_by_id`) appartient à l'utilisateur ;
  ~4-5 sessions ensuite. ⚠️ Chiffres du doc périmés 3× : **5** implémentations du lookup
  désormais, pas 4. → [`A_faire/replis_unit_by_id_2026-08-05.md`](A_faire/replis_unit_by_id_2026-08-05.md)
- **Endless Duty** (8-13 j) — décisions produit sur les obstacles 3 (format objectifs) et
  7 (double sens de `VALUE`). → [`A_faire/Endless_duty_etat_mesure.md`](A_faire/Endless_duty_etat_mesure.md)

Lourds, à re-cadrer avant toute reprise :
- **Preview de tir sans deepcopy** (4-8 j) — meilleure spec du lot, mais touche
  `compute_unit_los` = source unique (obs RL, reward, déploiement).
  → [`A_faire/preview_tir_position_virtuelle.md`](A_faire/preview_tir_position_virtuelle.md)
- **Pile-in / Overrun 12.06 par-figurine** (3-5 j après prérequis « le gym emprunte la machine
  V11 ») — **prérequis de P3-5** (§1), donc pas vraiment optionnel.
  → [`A_faire/pile_in_overrun_par_figurine.md`](A_faire/pile_in_overrun_par_figurine.md)
- **Migration PostgreSQL** (plusieurs semaines) — spec de mars 2026 visant des modules `ai/`
  réécrits par V11 depuis : re-confronter au code avant. → [`A_faire/Database/DB_migration.md`](A_faire/Database/DB_migration.md)
- **MCTS adversaire d'entraînement** (plusieurs semaines ; P0+P1 ≈ 1-2 sem.) — après stabilité
  obs/masques. → [`A_faire/MCTS/MCTS_bot_final.md`](A_faire/MCTS/MCTS_bot_final.md)

## 5. Hygiène documentaire

> **Le compte rendu du chantier du 2026-08-10 est sorti d'ici** (dissolution de `2_Various/`,
> réparation des 497 liens, recadrage de `1_Agent/`, fusions et suppressions) →
> [`Implémenté/hygiene_doc_2026-08-10.md`](Implémenté/hygiene_doc_2026-08-10.md). Il occupait
> 90 lignes sur 249 d'un fichier qui se déclare source unique de l'ordre du travail, sans jamais
> dire par quoi commencer. Extrait le 2026-08-10, en application de la règle de discipline en tête
> de ce fichier — un chantier livré passe son doc en `Implémenté/`.
>
> Ne reste ici que ce qui **sert à la prochaine passe** : le contrôle des liens, et les
> incohérences non soldées.

### Contrôle réutilisable des liens

**Contrôle réutilisable — et ses trois exclusions, sans lesquelles il ne sert à rien.** Parcourir
les liens markdown de `Documentation/Implémentation/` et vérifier que chaque cible existe, en
écartant : (1) les `http(s)://` et **`file:///`** — les liens vers le code sont ABSOLUS par
convention CLAUDE.md et ne sont pas des chemins relatifs ; (2) l'encodage URL (`%20` dans
`03%20Moving.pdf`) qu'il faut décoder avant le test ; (3) les faux positifs de regex — du texte
entre parenthèses pris pour une cible, dans `V11_tranches.md` et `V11_refactor_plan.md`.
Un contrôle naïf rend **152 hits** dont **aucun n'est un lien mort** (143 dans `Implémenté/stage.md`,
5 dans `Boardx10-audit.md`, tous des `file:///`) : mesuré le 2026-08-10, ne pas le reprendre pour
une régression. À relancer après tout déplacement de doc.

### Incohérences factuelles restantes (non traitées, aucune ne bloque)

- **`obs_size`** — la valeur vraie à HEAD est **16659**, portée par les **7** profils de la config
  ArmageddonAgent (un `"obs_size": 16659` chacun ; ce fichier a annoncé « 3 occurrences » jusqu'au
  2026-08-10, sans les compter). Vérifiée par exécution le 2026-08-08, recomptée le 2026-08-10.
  ✅ `Implémenté/01_ability_embedding.md`, qui annonçait 14609/14615, est corrigé. Reste la
  `justification` du champ dans la config, qui raconte encore la lignée 20780 → 20727 : **aucun
  JSON de `config/` n'est touché pendant un training** (§0), à reprendre après le run.
- ~~`justification` de `bot_eval_final_normal` dit « x1 (10 000 episodes) » alors que
  `x1.total_episodes` = **50 000**.~~ → **L'INCOHÉRENCE ÉTAIT DANS CE FICHIER, pas dans la config**
  (corrigé le 2026-08-10) : `x1.total_episodes` vaut bien **10 000** ; le 50 000 est
  `total_episodes_normal`, une clé de **commentaire** que `train.py` ne lit pas (il lit
  `total_episodes`). La `justification` avait raison. Même erreur propagée depuis
  `V11_agent_rework.md` §0.70, corrigée là aussi.
- ~~`A_faire/Endless_duty_etat_mesure.md` affirme que `config/agents/CoreAgent/` n'existe plus —
  **il existe**.~~ ✅ corrigé dans le doc le 2026-08-10.
- Bandeaux et chiffres périmés listés en `1_Agent/V11_agent_rework.md` §0bis (l.3713-3735),
  signalés et volontairement non corrigés depuis le 2026-07-20.
- `UNIT_ABILITY_SLOTS = 8` est une projection non mesurée ; le chantier 06 la rendra mesurable (§2).
- **Ancres de ligne des docs V11 : périmées en masse** (relevé le 2026-08-10). Les symboles cités
  existent tous, mais les numéros de ligne ont dérivé de 400 à 3 500 lignes — `_select_allocation_model`
  ~5643 → **7980**, `fight_pile_in_plan` ~6708 → **10240**, `squad_consolidate_plan` ~7038 →
  **10627**, `charge_build_valid_plan` ~3955 → **5720**, `_auto_select_cc_weapon_for_fig` L7370 →
  **10463**, `_auto_declared_order` L6462 → **9133**, `compute_candidate_footprint` L416 → **496**.
  Les lignes du **chemin critique** (§9.4, §9.0bis, §1bis) sont corrigées en **nom de symbole** ;
  le reste des docs n'a pas été balayé.
  🟢 **DÉCISION 2026-08-10 — traitement AU FIL DE L'EAU, pas de balayage global.** Motif : le
  porteur de risque est un doc qu'on **rouvre** (c'est ainsi qu'est né le plan T7 faux, cf.
  `V11_tranches.md` §1bis) ; un balayage complet dépenserait une journée sur `Implémenté/`, qui
  n'a plus que valeur d'historique. **Règle : tout doc modifié voit ses ancres de ligne corrigées
  dans la même livraison** — cela entre dans le périmètre de clôture T2, sans validation
  supplémentaire.
  **Convention d'écriture : citer `def <symbole>` ou un `grep` reproductible, jamais un numéro de
  ligne** — c'est la seule forme qui survit à une livraison.
