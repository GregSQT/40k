/**
 * Lecture du résultat d'`executeAction` (hook `useEngineAPI`).
 *
 * `executeAction` a TROIS issues, et deux d'entre elles se ressemblent :
 *
 * - un objet avec `success !== false` : le moteur a agi ;
 * - un objet `success === false` : le moteur a REFUSÉ, `error` porte la raison ;
 * - `undefined` : rien n'a été envoyé, ou l'envoi a échoué. C'est le cas piégeux. Il couvre les
 *   NON-ACTIONS délibérées (aperçu d'un point de sauvegarde actif — `executeAction` ouvre alors
 *   lui-même son popup de confirmation —, partie non démarrée, `game_over`) ET l'échec réseau,
 *   où `executeAction` a DÉJÀ posé le vrai diagnostic via `setError`.
 *
 * Les deux fautes symétriques, toutes deux commises dans ce dépôt :
 * - `data?.success === false` seul : `undefined` passe pour un SUCCÈS, et l'appelant applique les
 *   effets de bord d'une action qui n'a pas eu lieu (purge du plan de déploiement provisoire) ;
 * - `!data || data.success === false` : `undefined` passe pour un REFUS, et l'appelant appelle
 *   `setError` — qui remplace tout le plateau par le panneau d'erreur fatal (seule issue :
 *   recharger la page) et écrase le diagnostic réseau déjà affiché par un « unknown ».
 *
 * D'où trois cas nommés, et jamais un booléen.
 */

/** Enveloppe rendue par `executeAction` : seul `success` est lu ici. */
interface EngineActionResult {
  success?: boolean;
  error?: unknown;
}

export type EngineActionOutcome =
  /** Le moteur a agi : appliquer les effets de bord. */
  | { kind: "ok" }
  /** Le moteur a refusé : afficher `message`, ne rien appliquer. */
  | { kind: "refused"; message: string }
  /** Rien ne s'est passé : ne rien afficher (c'est déjà fait en amont), ne rien appliquer. */
  | { kind: "noop" };

export function readEngineActionOutcome(
  data: EngineActionResult | undefined | null
): EngineActionOutcome {
  if (!data) return { kind: "noop" };
  if (data.success === false) {
    return { kind: "refused", message: String(data.error ?? "unknown") };
  }
  return { kind: "ok" };
}
