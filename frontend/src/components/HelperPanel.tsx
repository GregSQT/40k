// frontend/src/components/HelperPanel.tsx
import helperTexts from "../../../config/helper_texts.json";
import type { FightSubPhase, GamePhase } from "../types/game";

interface HelperPanelProps {
  /** Phase courante du moteur. */
  phase: GamePhase | undefined;
  /** Mode UI courant (union de `useEngineAPI`). Sert de second segment de clé. */
  mode: string | undefined;
  /** Sous-phase de combat : segment intermédiaire de clé quand `phase === "fight"`. */
  fightSubphase?: FightSubPhase;
  /** false pendant la phase de déploiement tant que « Start Deployment » n'a pas été cliqué. */
  deploymentStarted?: boolean;
  /** true quand l'unité en cours de déploiement a déjà été posée sur le plateau (1er clic fait). */
  deploymentPlaced?: boolean;
}

const TEXTS = helperTexts as Record<string, string | string[]>;

/** Clés déjà signalées : un seul warn par combinaison manquante. */
const warned = new Set<string>();

/**
 * Clé du message : `<phase>.<mode>`, sauf en phase fight où la sous-phase
 * s'intercale : `fight.<fight_subphase>.<mode>`.
 */
function buildKey(
  phase: GamePhase,
  mode: string,
  fightSubphase: FightSubPhase | undefined,
  deploymentStarted: boolean,
  deploymentPlaced: boolean,
): string | null {
  if (phase === "deployment") {
    if (!deploymentStarted) return "deployment.not_started";
    // Unité sélectionnée mais pas encore posée : 1er clic attendu sur le plateau.
    if (mode === "deploymentMove" && !deploymentPlaced) return "deployment.placing";
  }
  if (phase === "fight") {
    if (!fightSubphase) return null;
    return `fight.${fightSubphase}.${mode}`;
  }
  return `${phase}.${mode}`;
}

export function HelperPanel({
  phase,
  mode,
  fightSubphase,
  deploymentStarted = true,
  deploymentPlaced = false,
}: HelperPanelProps) {
  if (!phase || !mode) return null;

  const key = buildKey(phase, mode, fightSubphase, deploymentStarted, deploymentPlaced);
  const entry = key === null ? undefined : TEXTS[key];

  if (entry === undefined) {
    if (key !== null && !warned.has(key)) {
      warned.add(key);
      console.warn(`[HelperPanel] aucun texte pour la clé "${key}" (config/helper_texts.json)`);
    }
    return null;
  }

  const lines = Array.isArray(entry) ? entry : [entry];

  return (
    <div className="helper-panel">
      {lines.map((line) => (
        <div key={line}>{line}</div>
      ))}
    </div>
  );
}

export default HelperPanel;
