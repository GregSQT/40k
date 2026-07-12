// frontend/src/components/SnapshotRewind.tsx
// Rewind / playback temporel par phase (mode PvP / PvP test).
// - Container de contrôle (mêmes controls que le mode replay) affiché sous le tracker quand la caméra est active.
// - Clic sur un tour / une phase dans le TurnPhaseTracker -> rollback NON destructif (mode view) sur ce point.
// - Navigation avec les boutons du container (⏮ ⏪ ▶ ⏸ ⏹ ⏭ + vitesse) ; « Reprendre ici » bascule en reprise.
import type React from "react";
import { useCallback, useEffect, useMemo, useState } from "react";

export interface SnapshotMeta {
  turn: number;
  player: number;
  phase: string;
  score: Record<string, number>;
}

/** Métadonnées d'une save manuelle (renvoyées par le backend, dérivées du nom de fichier). */
export interface SaveMeta {
  id: string;
  turn: number;
  player: number;
  phase: string;
  episode_steps: number;
  ts: string;
  label: string;
  /** Note optionnelle saisie par le joueur pour retrouver la save. */
  note?: string;
  /** Type de save : "manual" | "auto_phase" | "auto_turn" | "game_start". */
  kind?: string;
}

/** Nom affiché d'une save (1 ligne) : "Game start", ou tag T·Phase·#·P, note manuelle en fin. */
function saveDisplayName(s: SaveMeta): string {
  if (s.kind === "game_start") return "Game start";
  const base = `${s.label} · P${s.player}`;
  return s.kind === "manual" && s.note ? `${base} — ${s.note}` : base;
}

/** Couleur de fond par type : manuel = vert, auto/tour = gris, auto/phase (et game start) = blanc. */
function saveColors(kind?: string): { bg: string; fg: string } {
  if (kind === "manual") return { bg: "#16a34a", fg: "#ffffff" };
  if (kind === "auto_turn") return { bg: "#6b7280", fg: "#ffffff" };
  return { bg: "#ffffff", fg: "#1f2937" };
}

/** Requête de saut vers un tour/phase (nonce : permet de re-cliquer le même point). */
export interface SnapshotJump {
  turn: number;
  phase: string | null;
  nonce: number;
}

interface SnapshotRewindProps {
  /** Saut demandé (clic sur un tour/phase du tracker), ou null. */
  jump: SnapshotJump | null;
  fetchList: () => Promise<{ snapshots: SnapshotMeta[]; persist_enabled: boolean }>;
  restore: (
    turn: number,
    player: number,
    phase: string,
    mode: "resume" | "view"
  ) => Promise<unknown>;
  reloadLive: () => Promise<void>;
  /** Notifie le parent de l'entrée/sortie du mode visionnage (pour bloquer les clics du board). */
  onViewModeChange: (active: boolean) => void;
  /** true → affiche le container de contrôle du replay sous le tracker. */
  replayOpen: boolean;
  /** Notifie le point visionné (liste + index) pour tronquer le Game Log jusqu'à ce moment, ou null en live. */
  onViewChange: (viewed: { snapshots: SnapshotMeta[]; index: number } | null) => void;
  /** Clés `turn|phase|player` des phases où au moins une action a eu lieu (pour sauter les phases vides). */
  actionKeys: Set<string>;
  /** Enregistre l'état vivant courant dans une save (fichier plat), avec note optionnelle. */
  createSave: (note: string) => Promise<SaveMeta>;
  /** Liste les saves existantes (métadonnées). */
  fetchSaveList: () => Promise<SaveMeta[]>;
  /** Charge une save (remplace l'état vivant et repart de ce point). */
  loadSave: (id: string) => Promise<unknown>;
  /** false → Save bloqué tant que le répertoire de sauvegarde n'a pas été choisi. */
  canSave: boolean;
}

const iconSvgProps = {
  width: 18,
  height: 18,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
  style: { display: "block" as const },
};

/** Save : flèche ↓ vers un trait horizontal en bas (enregistrer vers le disque). */
function SaveIcon() {
  return (
    <svg {...iconSvgProps}>
      <title>Save</title>
      <path d="M12 3 V14" />
      <path d="M7 9 L12 14 L17 9" />
      <path d="M5 20 H19" />
    </svg>
  );
}

/** Resume : flèche ↑ vers un trait horizontal en haut (inverse de Save). */
function ResumeIcon() {
  return (
    <svg {...iconSvgProps}>
      <title>Resume</title>
      <path d="M5 4 H19" />
      <path d="M7 13 L12 8 L17 13" />
      <path d="M12 8 V21" />
    </svg>
  );
}

/** Select : flèche → vers un trait vertical à droite. */
function SelectIcon() {
  return (
    <svg {...iconSvgProps}>
      <title>Select</title>
      <path d="M3 12 H15" />
      <path d="M10 7 L15 12 L10 17" />
      <path d="M20 4 V20" />
    </svg>
  );
}

export const SnapshotRewind: React.FC<SnapshotRewindProps> = ({
  jump,
  fetchList,
  restore,
  reloadLive,
  onViewModeChange,
  replayOpen,
  onViewChange,
  actionKeys,
  createSave,
  fetchSaveList,
  loadSave,
  canSave,
}) => {
  const [list, setList] = useState<SnapshotMeta[]>([]);
  const [viewIndex, setViewIndex] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState(1.0);
  const [saves, setSaves] = useState<SaveMeta[]>([]);
  const [saveMenuOpen, setSaveMenuOpen] = useState(false);
  const [savePromptOpen, setSavePromptOpen] = useState(false);
  const [saveNote, setSaveNote] = useState("");

  // Indices des snapshots dont la phase a eu au moins une action (sinon, tous : pas de filtre exploitable).
  const actionIndices = useMemo(() => {
    const arr: number[] = [];
    for (let i = 0; i < list.length; i++) {
      const s = list[i];
      if (s && actionKeys.has(`${s.turn}|${s.phase}|${s.player}`)) arr.push(i);
    }
    return arr.length > 0 ? arr : list.map((_, i) => i);
  }, [list, actionKeys]);

  const prevActionIndex = useCallback(
    (from: number) => {
      let best = -1;
      for (const i of actionIndices) {
        if (i < from) best = i;
        else break;
      }
      return best;
    },
    [actionIndices]
  );
  const nextActionIndex = useCallback(
    (from: number) => {
      for (const i of actionIndices) if (i > from) return i;
      return -1;
    },
    [actionIndices]
  );

  // Charge la liste à l'ouverture du container de replay.
  useEffect(() => {
    if (!replayOpen) return;
    let cancelled = false;
    setError(null);
    fetchList()
      .then((r) => {
        if (!cancelled) setList(r.snapshots);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e?.message ?? e));
      });
    return () => {
      cancelled = true;
    };
  }, [replayOpen, fetchList]);

  // Entre en visionnage (non destructif) sur un index de la liste.
  const enterView = useCallback(
    async (index: number) => {
      const m = list[index];
      if (!m) return;
      setBusy(true);
      setError(null);
      try {
        await restore(m.turn, m.player, m.phase, "view");
        setViewIndex(index);
        onViewModeChange(true);
      } catch (e) {
        setError(String((e as Error)?.message ?? e));
      } finally {
        setBusy(false);
      }
    },
    [list, restore, onViewModeChange]
  );

  const exitView = useCallback(async () => {
    setBusy(true);
    try {
      await reloadLive();
      setViewIndex(null);
      setIsPlaying(false);
      onViewModeChange(false);
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setBusy(false);
    }
  }, [reloadLive, onViewModeChange]);

  // Reprend la partie au snapshot actuellement visionné (bascule replay -> reprise destructive).
  const resumeHere = useCallback(async () => {
    if (viewIndex == null) return;
    const m = list[viewIndex];
    if (!m) return;
    setBusy(true);
    setError(null);
    try {
      await restore(m.turn, m.player, m.phase, "resume");
      setViewIndex(null);
      setIsPlaying(false);
      onViewModeChange(false);
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setBusy(false);
    }
  }, [viewIndex, list, restore, onViewModeChange]);

  // Enregistre l'état vivant courant dans une save, avec la note saisie (optionnelle).
  const doSave = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      await createSave(saveNote.trim());
      setSavePromptOpen(false);
      setSaveNote("");
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setBusy(false);
    }
  }, [createSave, saveNote]);

  // Ouvre/ferme le menu Select ; recharge la liste des saves à l'ouverture.
  const toggleSaveMenu = useCallback(async () => {
    if (saveMenuOpen) {
      setSaveMenuOpen(false);
      return;
    }
    setError(null);
    try {
      setSaves(await fetchSaveList());
      setSaveMenuOpen(true);
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    }
  }, [saveMenuOpen, fetchSaveList]);

  // Charge une save : remplace l'état vivant, sort du visionnage, repart de ce point.
  const pickSave = useCallback(
    async (id: string) => {
      setBusy(true);
      setError(null);
      try {
        await loadSave(id);
        setSaveMenuOpen(false);
        setViewIndex(null);
        setIsPlaying(false);
        onViewModeChange(false);
      } catch (e) {
        setError(String((e as Error)?.message ?? e));
      } finally {
        setBusy(false);
      }
    },
    [loadSave, onViewModeChange]
  );

  // Rapporte le point visionné (pour tronquer le Game Log jusqu'à ce moment).
  useEffect(() => {
    onViewChange(viewIndex != null ? { snapshots: list, index: viewIndex } : null);
  }, [viewIndex, list, onViewChange]);

  // Autoplay : enchaîne les phases avec action tant que la lecture est active.
  useEffect(() => {
    if (!isPlaying || viewIndex == null) return;
    const next = nextActionIndex(viewIndex);
    if (next < 0) {
      setIsPlaying(false);
      return;
    }
    const t = setTimeout(() => enterView(next), 1000 / playbackSpeed);
    return () => clearTimeout(t);
  }, [isPlaying, viewIndex, playbackSpeed, nextActionIndex, enterView]);

  // Saut vers un tour/phase (clic sur le tracker) : rollback view non destructif sur ce point.
  // biome-ignore lint/correctness/useExhaustiveDependencies: traiter chaque requête (nonce) une seule fois
  useEffect(() => {
    if (!jump) return;
    let cancelled = false;
    (async () => {
      setBusy(true);
      setError(null);
      try {
        let snaps = list;
        if (snaps.length === 0) {
          const r = await fetchList();
          if (cancelled) return;
          snaps = r.snapshots;
          setList(snaps);
        }
        let idx = -1;
        if (jump.phase) {
          idx = snaps.findIndex((s) => s.turn === jump.turn && s.phase === jump.phase);
        }
        if (idx < 0) idx = snaps.findIndex((s) => s.turn === jump.turn);
        if (idx < 0) {
          setError(
            `Aucun snapshot pour le tour ${jump.turn}${jump.phase ? ` / ${jump.phase}` : ""}`
          );
          return;
        }
        const m = snaps[idx];
        await restore(m.turn, m.player, m.phase, "view");
        if (cancelled) return;
        setViewIndex(idx);
        setIsPlaying(false);
        onViewModeChange(true);
      } catch (e) {
        if (!cancelled) setError(String((e as Error)?.message ?? e));
      } finally {
        if (!cancelled) setBusy(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [jump?.nonce]);

  // --- Container de contrôle du replay (mêmes controls que la barre replay, sous le tracker) ---
  if (!replayOpen && viewIndex == null) return null;

  const atLive = viewIndex == null;
  const progressPct = atLive || list.length === 0 ? 100 : ((viewIndex + 1) / list.length) * 100;
  const firstTarget = actionIndices.length ? actionIndices[0] : -1;
  const lastTarget = actionIndices.length ? actionIndices[actionIndices.length - 1] : -1;
  const prevTarget = atLive ? lastTarget : prevActionIndex(viewIndex);
  const nextTarget = atLive ? -1 : nextActionIndex(viewIndex);

  return (
    <div
      className="replay-playback-controls-container"
      style={{ position: "relative", zIndex: 4001 }}
    >
      <div className="replay-controls-row">
        {/* Lecture — CENTRE-GAUCHE */}
        <div className="replay-nav-buttons">
          <button
            type="button"
            className="replay-btn replay-btn--nav"
            title="Action précédente"
            disabled={busy || prevTarget < 0}
            onClick={() => enterView(prevTarget)}
          >
            <span className="replay-icon replay-icon--prev">⏮</span>
          </button>
          {!isPlaying ? (
            <button
              type="button"
              className="replay-btn replay-btn--play"
              disabled={busy || firstTarget < 0}
              onClick={() => {
                if (atLive) enterView(firstTarget);
                setIsPlaying(true);
              }}
            >
              ▶
            </button>
          ) : (
            <button
              type="button"
              className="replay-btn replay-btn--pause"
              onClick={() => setIsPlaying(false)}
            >
              ⏸
            </button>
          )}
          <button
            type="button"
            className="replay-btn replay-btn--nav"
            title="Action suivante"
            disabled={busy || nextTarget < 0}
            onClick={() => enterView(nextTarget)}
          >
            <span className="replay-icon replay-icon--next">⏭</span>
          </button>
        </div>

        {/* Vitesse — CENTRE */}
        <div className="replay-speed-controls">
          <span className="replay-speed-label">Speed:</span>
          {[0.25, 0.5, 1.0, 2.0, 4.0].map((speed) => (
            <button
              type="button"
              key={speed}
              onClick={() => setPlaybackSpeed(speed)}
              className={`replay-btn replay-btn--speed ${playbackSpeed === speed ? "active" : ""}`}
            >
              {speed}x
            </button>
          ))}
        </div>

        {/* Bloc saves — à égale distance entre les contrôles et le Live : [Save] · [Select] */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "10px",
            position: "relative",
            marginLeft: "auto",
          }}
        >
          <button
            type="button"
            className="replay-btn replay-btn--nav"
            title={
              canSave
                ? "Enregistrer l'état courant"
                : "Choisis d'abord le répertoire de sauvegarde (menu → Sauvegarde → Sauvegarde des snapshots sur disque)"
            }
            disabled={busy || !canSave}
            onClick={() => {
              setSaveNote("");
              setSavePromptOpen(true);
            }}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              background: "#16a34a",
              color: "#ffffff",
            }}
          >
            Save
            <SaveIcon />
          </button>
          <button
            type="button"
            className="replay-btn replay-btn--nav"
            title="Charger une save"
            disabled={busy}
            onClick={toggleSaveMenu}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              background: "#ca8a04",
              color: "#ffffff",
            }}
          >
            Select
            <SelectIcon />
          </button>
          {saveMenuOpen && (
            <div
              style={{
                position: "absolute",
                top: "calc(100% + 6px)",
                right: 0,
                minWidth: "220px",
                maxHeight: "260px",
                overflowY: "auto",
                background: "#1f2937",
                border: "1px solid #555",
                borderRadius: "8px",
                boxShadow: "0 10px 30px rgba(0,0,0,0.5)",
                zIndex: 4100,
                padding: "6px",
              }}
            >
              {saves.length === 0 ? (
                <div style={{ color: "#9ca3af", padding: "6px 8px" }}>Aucune save</div>
              ) : (
                saves.map((s) => {
                  const c = saveColors(s.kind);
                  return (
                    <button
                      key={s.id}
                      type="button"
                      className="replay-btn"
                      disabled={busy}
                      onClick={() => pickSave(s.id)}
                      title={saveDisplayName(s)}
                      style={{
                        display: "block",
                        width: "100%",
                        height: "auto",
                        textAlign: "left",
                        padding: "6px 8px",
                        marginBottom: "4px",
                        background: c.bg,
                        color: c.fg,
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {saveDisplayName(s)}
                    </button>
                  );
                })
              )}
            </div>
          )}
        </div>

        {/* Resume Here — entre le bloc saves et le Live, fond rouge */}
        <button
          type="button"
          className="replay-btn"
          title="Reprendre la partie au point visionné"
          disabled={busy || atLive}
          onClick={resumeHere}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "6px",
            background: "#ef4444",
            border: "1px solid #f87171",
            color: "#fff",
            fontWeight: 700,
            boxShadow: "0 0 10px 2px rgba(239, 68, 68, 0.75)",
          }}
        >
          Resume Here
          <ResumeIcon />
        </button>

        {/* État Live / retour au live — TOUT À DROITE */}
        <div className="replay-action-counter" style={{ marginLeft: "auto" }}>
          {atLive ? (
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "8px",
                fontSize: "18px",
              }}
            >
              Live
              <span
                style={{
                  width: "16px",
                  height: "16px",
                  borderRadius: "50%",
                  background: "#ff1a1a",
                  display: "inline-block",
                  boxShadow: "0 0 8px 2px rgba(255, 26, 26, 0.85)",
                }}
              />
            </span>
          ) : (
            <button
              type="button"
              className="replay-btn replay-btn--nav"
              title="Revenir au live"
              disabled={busy}
              onClick={exitView}
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: "18px",
                lineHeight: 1,
              }}
            >
              ⟳
            </button>
          )}
        </div>
      </div>

      {/* Barre de progression */}
      <div className="replay-progress-bar">
        <div className="replay-progress-fill" style={{ width: `${progressPct}%` }} />
      </div>
      {error && <div style={{ color: "#f87171", padding: "4px 8px" }}>{error}</div>}

      {/* Popup : note optionnelle pour la save */}
      {savePromptOpen && (
        // biome-ignore lint/a11y/noStaticElementInteractions: backdrop modal — clic fond = fermeture
        <div
          role="presentation"
          onClick={() => setSavePromptOpen(false)}
          onKeyDown={(e) => e.key === "Escape" && setSavePromptOpen(false)}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.55)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 4200,
          }}
        >
          {/* biome-ignore lint/a11y/noStaticElementInteractions: panneau — stopPropagation intentionnel */}
          <div
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
            style={{
              background: "#1f2937",
              border: "1px solid #555",
              borderRadius: "8px",
              padding: "16px",
              minWidth: "320px",
              color: "#fff",
              boxShadow: "0 10px 30px rgba(0,0,0,0.5)",
            }}
          >
            <h3 style={{ marginTop: 0 }}>Enregistrer la partie</h3>
            <p style={{ color: "#9ca3af", marginTop: 0 }}>
              Note (optionnelle) pour retrouver la save :
            </p>
            <input
              type="text"
              value={saveNote}
              onChange={(e) => setSaveNote(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !busy) doSave();
              }}
              placeholder="ex: avant l'assaut sur l'objectif"
              style={{
                width: "100%",
                boxSizing: "border-box",
                padding: "8px 10px",
                borderRadius: "6px",
                border: "1px solid #4b5563",
                background: "#111827",
                color: "#fff",
              }}
            />
            {error && <p style={{ color: "#f87171" }}>{error}</p>}
            <div
              style={{ display: "flex", gap: "8px", justifyContent: "flex-end", marginTop: "14px" }}
            >
              <button
                type="button"
                className="replay-btn replay-btn--nav"
                disabled={busy}
                onClick={() => setSavePromptOpen(false)}
              >
                Annuler
              </button>
              <button
                type="button"
                className="replay-btn"
                disabled={busy}
                onClick={doSave}
                style={{ background: "#059669", borderColor: "#047857", color: "#fff" }}
              >
                Enregistrer
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default SnapshotRewind;
