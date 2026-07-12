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
}) => {
  const [list, setList] = useState<SnapshotMeta[]>([]);
  const [viewIndex, setViewIndex] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState(1.0);

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

        {/* Reprendre la partie au point visionné */}
        {!atLive && (
          <button
            type="button"
            className="replay-btn replay-btn--nav"
            disabled={busy}
            onClick={resumeHere}
          >
            ↩ Reprendre ici
          </button>
        )}

        {/* État Live / retour au live — TOUT À DROITE */}
        <div className="replay-action-counter" style={{ marginLeft: "auto" }}>
          {atLive ? (
            <span style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
              Live
              <span
                style={{
                  width: "10px",
                  height: "10px",
                  borderRadius: "50%",
                  background: "#ef4444",
                  display: "inline-block",
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
    </div>
  );
};

export default SnapshotRewind;
