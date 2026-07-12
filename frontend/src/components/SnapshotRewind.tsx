// frontend/src/components/SnapshotRewind.tsx
// Rewind / playback temporel par phase (mode PvP / PvP test).
// - Clic sur un numéro de round dans TurnPhaseTracker -> menu des phases jouées ce round.
// - Clic sur une phase -> popup : Reprendre (le jeu repart de ce point) ou Visionner (lecture seule).
// - En visionnage : bandeau avec navigation ◀ ▶ entre phases et retour à la partie.
import type React from "react";
import { useCallback, useEffect, useState } from "react";

export interface SnapshotMeta {
  turn: number;
  player: number;
  phase: string;
  score: Record<string, number>;
}

interface SnapshotRewindProps {
  /** Round dont on a demandé le menu (clic sur le numéro dans le tracker), ou null. */
  menuTurn: number | null;
  onCloseMenu: () => void;
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
}

function formatPhase(phase: string): string {
  return phase.charAt(0).toUpperCase() + phase.slice(1);
}

function scoreLabel(score: Record<string, number>): string {
  const p1 = score["1"] ?? 0;
  const p2 = score["2"] ?? 0;
  return `${p1}–${p2}`;
}

const overlayStyle: React.CSSProperties = {
  position: "fixed",
  inset: 0,
  background: "rgba(0,0,0,0.55)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  zIndex: 4000,
};

const panelStyle: React.CSSProperties = {
  background: "#1f2937",
  border: "1px solid #555",
  borderRadius: "8px",
  padding: "16px",
  minWidth: "320px",
  maxWidth: "480px",
  color: "#fff",
  boxShadow: "0 10px 30px rgba(0,0,0,0.5)",
};

const btnBase: React.CSSProperties = {
  padding: "8px 12px",
  borderRadius: "6px",
  border: "1px solid",
  cursor: "pointer",
  fontSize: "14px",
  fontWeight: 600,
  color: "#fff",
};

export const SnapshotRewind: React.FC<SnapshotRewindProps> = ({
  menuTurn,
  onCloseMenu,
  fetchList,
  restore,
  reloadLive,
  onViewModeChange,
}) => {
  const [list, setList] = useState<SnapshotMeta[]>([]);
  const [choice, setChoice] = useState<SnapshotMeta | null>(null);
  const [viewIndex, setViewIndex] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Charge la liste à l'ouverture du menu.
  useEffect(() => {
    if (menuTurn == null) return;
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
  }, [menuTurn, fetchList]);

  const enterView = useCallback(
    async (index: number) => {
      const m = list[index];
      if (!m) return;
      setBusy(true);
      setError(null);
      try {
        await restore(m.turn, m.player, m.phase, "view");
        setViewIndex(index);
        setChoice(null);
        onCloseMenu();
        onViewModeChange(true);
      } catch (e) {
        setError(String((e as Error)?.message ?? e));
      } finally {
        setBusy(false);
      }
    },
    [list, restore, onCloseMenu, onViewModeChange]
  );

  const stepView = useCallback(
    async (dir: -1 | 1) => {
      if (viewIndex == null) return;
      const next = viewIndex + dir;
      if (next < 0 || next >= list.length) return;
      const m = list[next];
      setBusy(true);
      try {
        await restore(m.turn, m.player, m.phase, "view");
        setViewIndex(next);
      } catch (e) {
        setError(String((e as Error)?.message ?? e));
      } finally {
        setBusy(false);
      }
    },
    [viewIndex, list, restore]
  );

  const exitView = useCallback(async () => {
    setBusy(true);
    try {
      await reloadLive();
      setViewIndex(null);
      onViewModeChange(false);
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setBusy(false);
    }
  }, [reloadLive, onViewModeChange]);

  const doResume = useCallback(async () => {
    if (!choice) return;
    setBusy(true);
    setError(null);
    try {
      await restore(choice.turn, choice.player, choice.phase, "resume");
      setChoice(null);
      onCloseMenu();
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setBusy(false);
    }
  }, [choice, restore, onCloseMenu]);

  // --- Bandeau de visionnage (lecture seule) ---
  if (viewIndex != null) {
    const m = list[viewIndex];
    return (
      <div
        style={{
          position: "fixed",
          bottom: 0,
          left: 0,
          right: 0,
          background: "#111827",
          borderTop: "2px solid #f59e0b",
          padding: "10px 16px",
          display: "flex",
          alignItems: "center",
          gap: "12px",
          justifyContent: "center",
          color: "#fff",
          zIndex: 4001,
        }}
      >
        <span style={{ color: "#f59e0b", fontWeight: 700 }}>👁 Visionnage</span>
        {m && (
          <span>
            Round {m.turn} · P{m.player} · {formatPhase(m.phase)} · Score {scoreLabel(m.score)}
          </span>
        )}
        <button
          type="button"
          style={{ ...btnBase, background: "#374151", borderColor: "#4b5563" }}
          disabled={busy || viewIndex <= 0}
          onClick={() => stepView(-1)}
        >
          ◀ Précédente
        </button>
        <button
          type="button"
          style={{ ...btnBase, background: "#374151", borderColor: "#4b5563" }}
          disabled={busy || viewIndex >= list.length - 1}
          onClick={() => stepView(1)}
        >
          Suivante ▶
        </button>
        <button
          type="button"
          style={{ ...btnBase, background: "#059669", borderColor: "#047857" }}
          disabled={busy}
          onClick={exitView}
        >
          Retour à la partie
        </button>
        {error && <span style={{ color: "#f87171" }}>{error}</span>}
      </div>
    );
  }

  // --- Popup de choix Reprendre / Visionner ---
  if (choice) {
    return (
      // biome-ignore lint/a11y/noStaticElementInteractions: backdrop modal — clic fond = fermeture
      <div
        role="presentation"
        style={overlayStyle}
        onClick={() => setChoice(null)}
        onKeyDown={(e) => e.key === "Escape" && setChoice(null)}
      >
        {/* biome-ignore lint/a11y/noStaticElementInteractions: panneau — stopPropagation intentionnel */}
        <div
          style={panelStyle}
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => e.stopPropagation()}
        >
          <h3 style={{ marginTop: 0 }}>
            Round {choice.turn} · P{choice.player} · {formatPhase(choice.phase)}
          </h3>
          <p style={{ color: "#9ca3af" }}>
            Reprendre la partie à ce point (l'historique postérieur sera effacé), ou visionner le
            déroulé à partir d'ici en lecture seule ?
          </p>
          {error && <p style={{ color: "#f87171" }}>{error}</p>}
          <div
            style={{ display: "flex", gap: "8px", justifyContent: "flex-end", marginTop: "12px" }}
          >
            <button
              type="button"
              style={{ ...btnBase, background: "#6b7280", borderColor: "#4b5563" }}
              disabled={busy}
              onClick={() => setChoice(null)}
            >
              Annuler
            </button>
            <button
              type="button"
              style={{ ...btnBase, background: "#2563eb", borderColor: "#1d4ed8" }}
              disabled={busy}
              onClick={() =>
                enterView(
                  list.findIndex(
                    (x) =>
                      x.turn === choice.turn &&
                      x.player === choice.player &&
                      x.phase === choice.phase
                  )
                )
              }
            >
              👁 Visionner
            </button>
            <button
              type="button"
              style={{ ...btnBase, background: "#dc2626", borderColor: "#991b1b" }}
              disabled={busy}
              onClick={doResume}
            >
              ↩ Reprendre ici
            </button>
          </div>
        </div>
      </div>
    );
  }

  // --- Menu des phases jouées dans le round sélectionné ---
  if (menuTurn == null) return null;
  const roundSnaps = list.filter((m) => m.turn === menuTurn);
  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: backdrop modal — clic fond = fermeture
    <div
      role="presentation"
      style={overlayStyle}
      onClick={onCloseMenu}
      onKeyDown={(e) => e.key === "Escape" && onCloseMenu()}
    >
      {/* biome-ignore lint/a11y/noStaticElementInteractions: panneau — stopPropagation intentionnel */}
      <div
        style={panelStyle}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
      >
        <h3 style={{ marginTop: 0 }}>Round {menuTurn} — phases jouées</h3>
        {error && <p style={{ color: "#f87171" }}>{error}</p>}
        {roundSnaps.length === 0 ? (
          <p style={{ color: "#9ca3af" }}>Aucune phase enregistrée pour ce round.</p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
            {roundSnaps.map((m) => (
              <button
                key={`${m.turn}-${m.player}-${m.phase}`}
                type="button"
                style={{
                  ...btnBase,
                  background: m.player === 1 ? "#1d4ed8" : "#b91c1c",
                  borderColor: m.player === 1 ? "#1e3a8a" : "#7f1d1d",
                  textAlign: "left",
                }}
                onClick={() => setChoice(m)}
              >
                P{m.player} — {formatPhase(m.phase)} · Score {scoreLabel(m.score)}
              </button>
            ))}
          </div>
        )}
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "12px" }}>
          <button
            type="button"
            style={{ ...btnBase, background: "#6b7280", borderColor: "#4b5563" }}
            onClick={onCloseMenu}
          >
            Fermer
          </button>
        </div>
      </div>
    </div>
  );
};

export default SnapshotRewind;
