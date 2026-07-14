// frontend/src/components/SnapshotRewind.tsx
// Rewind / playback temporel par phase (mode PvP / PvP test).
// - Container de contrôle (mêmes controls que le mode replay) affiché sous le tracker quand la caméra est active.
// - Clic sur un tour / une phase dans le TurnPhaseTracker -> rollback NON destructif (mode view) sur ce point.
// - Navigation avec les boutons du container (⏮ ⏪ ▶ ⏸ ⏹ ⏭ + vitesse) ; « Reprendre ici » bascule en reprise.
import type React from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

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
  /** Type de row : "game_start" | "turn" | "phase" | "action" | "manual". */
  kind?: string;
  /** Score (VP) par joueur au moment de la row (pour le tracker). */
  score?: Record<string, number>;
}

/** Nom affiché d'une save (1 ligne) : "Game start", ou tag "T{tour} P{joueur} {Phase} · #{event}",
 *  note manuelle ajoutée en fin. */
function saveDisplayName(s: SaveMeta): string {
  if (s.kind === "game_start") return "Game start";
  const phase = s.phase ? s.phase[0].toUpperCase() + s.phase.slice(1) : "";
  const base = `T${s.turn} P${s.player} ${phase}`;
  // Le "#" (n° d'activation) n'est utile que pour distinguer plusieurs saves manuelles dans une phase.
  if (s.kind === "manual") {
    return `${base} · #${s.episode_steps}${s.note ? ` — ${s.note}` : ""}`;
  }
  return base;
}

/** Couleur de fond par type : game start = noir, manuel = blanc, auto/tour = gris,
 *  auto/phase = couleur de la phase (mêmes variables que les boutons du TurnPhaseTracker). */
function saveColors(s: SaveMeta): { bg: string; fg: string } {
  if (s.kind === "game_start") return { bg: "#000000", fg: "#ffffff" };
  if (s.kind === "manual") return { bg: "#ffffff", fg: "#1f2937" };
  if (s.kind === "auto_turn") return { bg: "#6b7280", fg: "#ffffff" };
  const phase = (s.phase || "").toLowerCase();
  const known = ["command", "move", "shoot", "charge", "fight"];
  const bg = known.includes(phase) ? `var(--phase-${phase}-bg)` : "var(--phase-default-bg)";
  return { bg, fg: "#ffffff" };
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
  /** Timeline complète de la partie courante (toutes les rows) + état de l'enregistrement. */
  fetchTimeline: () => Promise<{ rows: SaveMeta[]; recording_enabled: boolean }>;
  /** Active l'enregistrement de la timeline (depuis le popup, sans passer par le menu). */
  /** Active l'enregistrement (sélection du répertoire incluse). Retourne false si l'utilisateur annule. */
  onEnableRecording: () => Promise<boolean>;
  reloadLive: () => Promise<void>;
  /** Notifie le parent de l'entrée/sortie du mode visionnage (pour bloquer les clics du board). */
  onViewModeChange: (active: boolean) => void;
  /** true → affiche le container de contrôle du replay sous le tracker. */
  replayOpen: boolean;
  /** Enregistre l'état vivant courant dans une save (fichier plat), avec note optionnelle. */
  createSave: (note: string) => Promise<SaveMeta>;
  /** Liste les saves existantes (métadonnées). */
  fetchSaveList: () => Promise<SaveMeta[]>;
  /** Charge une save : mode "view" = aperçu non destructif ; "resume" = commit (remplace le live). */
  loadSave: (
    id: string,
    mode?: "view" | "resume",
    divergence?: { fork: "fork" | "overwrite"; backup_name?: string }
  ) => Promise<unknown>;
  /** false → Save bloqué tant que le répertoire de sauvegarde n'a pas été choisi. */
  canSave: boolean;
  /** Liste les parties sauvegardées (pour Load). */
  fetchPartyList: () => Promise<Array<{ name: string }>>;
  /** Charge une partie : mode "view" = aperçu ; "resume" = commit à son game start. */
  loadParty: (
    name: string,
    mode?: "view" | "resume",
    divergence?: { fork: "fork" | "overwrite"; backup_name?: string }
  ) => Promise<unknown>;
  /** true → affiche le popup « tu vas modifier la partie » (clic board tenté pendant l'aperçu). */
  confirmModifyOpen: boolean;
  /** Ferme le popup de confirmation sans reprendre (Annuler ou après lancement du Resume). */
  onCancelConfirmModify: () => void;
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

/** Resume : barre puis flèche vers la droite ( |-> ) — reprendre depuis ce point. */
function ResumeBarIcon() {
  return (
    <svg {...iconSvgProps}>
      <title>Resume</title>
      <path d="M4 5 V19" />
      <path d="M9 12 H19" />
      <path d="M14 7 L19 12 L14 17" />
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
  fetchTimeline,
  onEnableRecording,
  reloadLive,
  onViewModeChange,
  replayOpen,
  createSave,
  fetchSaveList,
  loadSave,
  canSave,
  fetchPartyList,
  loadParty,
  confirmModifyOpen,
  onCancelConfirmModify,
}) => {
  const [list, setList] = useState<SaveMeta[]>([]);
  // Enregistrement de la timeline inactif à l'ouverture du replay → popup pour l'activer.
  const [recordingPromptOpen, setRecordingPromptOpen] = useState(false);
  const [viewIndex, setViewIndex] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState(1.0);
  const [saves, setSaves] = useState<SaveMeta[]>([]);
  const [saveMenuOpen, setSaveMenuOpen] = useState(false);
  const [savePromptOpen, setSavePromptOpen] = useState(false);
  // Popup « Enregistrer la partie » déplaçable : offset courant + drag en cours (poignée = le titre).
  const [savePos, setSavePos] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [saveDrag, setSaveDrag] = useState<{ sx: number; sy: number; bx: number; by: number } | null>(
    null
  );
  // Popup d'invite : Save / Select / Load cliqués sans répertoire de sauvegarde configuré.
  const [needsDirOpen, setNeedsDirOpen] = useState(false);
  const [saveNote, setSaveNote] = useState("");
  const [parties, setParties] = useState<Array<{ name: string }>>([]);
  const [loadMenuOpen, setLoadMenuOpen] = useState(false);
  // Popup de divergence (Resume alors que la partie a des save-points postérieurs au point repris).
  const [divergenceOpen, setDivergenceOpen] = useState(false);
  const [forkChoice, setForkChoice] = useState<"fork" | "overwrite">("fork");
  const [forkName, setForkName] = useState("");

  // Drag du popup « Enregistrer la partie » : pendant un drag, on suit la souris au niveau window
  // (bouger vite hors du panneau ne casse pas le suivi) et on relâche au mouseup.
  useEffect(() => {
    if (!saveDrag) return;
    const move = (e: MouseEvent) =>
      setSavePos({ x: saveDrag.bx + e.clientX - saveDrag.sx, y: saveDrag.by + e.clientY - saveDrag.sy });
    const up = () => setSaveDrag(null);
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    return () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
  }, [saveDrag]);

  // Playback ⏮⏭ : 1 flèche = 1 ACTION réelle. Les rows turn/phase/action correspondent toutes à une
  // action (celle qui a fait progresser tour/phase/activation) et portent leurs events de log → elles
  // sont TOUTES navigables. Sans "turn"/"phase", la 1ʳᵉ action d'un tour/d'une phase serait sautée et
  // son log n'apparaîtrait que fusionné avec l'action suivante. game_start/manual (début de partie,
  // saves explicites) ne sont pas des pas d'action → exclus (accessibles via Select).
  const actionIndices = useMemo(
    () =>
      list
        .map((_, i) => i)
        .filter((i) => {
          const k = list[i]?.kind;
          return k === "action" || k === "phase" || k === "turn";
        }),
    [list]
  );

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

  // Charge la timeline à l'ouverture du container de replay. Si l'enregistrement n'est pas actif,
  // pas de timeline exploitable → on propose de l'activer via un popup (sans passer par le menu).
  useEffect(() => {
    if (!replayOpen) return;
    let cancelled = false;
    setError(null);
    fetchTimeline()
      .then((r) => {
        if (cancelled) return;
        setList(r.rows);
        if (!r.recording_enabled) setRecordingPromptOpen(true);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(String((e as Error)?.message ?? e));
      });
    return () => {
      cancelled = true;
    };
  }, [replayOpen, fetchTimeline]);

  // Entre en visionnage (non destructif) sur un index de la liste.
  const enterView = useCallback(
    async (index: number) => {
      const m = list[index];
      if (!m) return;
      setBusy(true);
      setError(null);
      try {
        await loadSave(m.id, "view");
        setViewIndex(index);
        onViewModeChange(true);
      } catch (e) {
        setError(String((e as Error)?.message ?? e));
      } finally {
        setBusy(false);
      }
    },
    [list, loadSave, onViewModeChange]
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

  // Commit le moment affiché (aperçu snapshot OU save-point/partie) en partie live. `divergence`
  // (fork/écrasement) transmis au 2e appel après décision du joueur. Retourne la réponse API.
  const doResume = useCallback(
    async (divergence?: { fork: "fork" | "overwrite"; backup_name?: string }) => {
      if (viewIndex != null) {
        const m = list[viewIndex];
        if (!m) return null;
        return await loadSave(m.id, "resume", divergence);
      }
      return null;
    },
    [viewIndex, list, loadSave]
  );

  // Sortie du mode aperçu après un commit effectif.
  const finishResume = useCallback(() => {
    setViewIndex(null);
    setIsPlaying(false);
    onViewModeChange(false);
  }, [onViewModeChange]);

  // Resume : si divergence (saves postérieures dans le fichier) → popup ; sinon commit direct.
  const resumeHere = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const data = (await doResume()) as { needs_decision?: boolean } | null;
      if (data?.needs_decision) {
        setForkChoice("fork");
        setForkName("");
        setDivergenceOpen(true); // garde l'aperçu affiché : le joueur peut encore annuler
        return;
      }
      finishResume();
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setBusy(false);
    }
  }, [doResume, finishResume]);

  // Validation du popup : rejoue le resume avec la décision (fork+nom optionnel, ou écrasement).
  const confirmDivergence = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      await doResume(
        forkChoice === "fork"
          ? { fork: "fork", backup_name: forkName.trim() || undefined }
          : { fork: "overwrite" }
      );
      setDivergenceOpen(false);
      finishResume();
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setBusy(false);
    }
  }, [doResume, forkChoice, forkName, finishResume]);

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

  // Aperçu (view non destructif) d'une save (row de la partie courante) : positionne le curseur de
  // playback sur cette row (viewIndex) ; les ⏮⏭ naviguent ensuite normalement. Resume commit.
  const pickSave = useCallback(
    async (id: string) => {
      setBusy(true);
      setError(null);
      try {
        await loadSave(id, "view");
        setSaveMenuOpen(false);
        setViewIndex((prev) => {
          const idx = list.findIndex((m) => m.id === id);
          return idx >= 0 ? idx : prev;
        });
        setIsPlaying(false);
        onViewModeChange(true);
      } catch (e) {
        setError(String((e as Error)?.message ?? e));
      } finally {
        setBusy(false);
      }
    },
    [loadSave, list, onViewModeChange]
  );

  // Ouvre/ferme le menu Load ; recharge la liste des parties à l'ouverture.
  const toggleLoadMenu = useCallback(async () => {
    if (loadMenuOpen) {
      setLoadMenuOpen(false);
      return;
    }
    setError(null);
    try {
      setParties(await fetchPartyList());
      setLoadMenuOpen(true);
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    }
  }, [loadMenuOpen, fetchPartyList]);

  // Aperçu (view non destructif) d'une AUTRE partie : on charge son game_start, puis on recharge la
  // timeline (= rows de la partie chargée) et on place le curseur sur le game_start (index 0) → les
  // ⏮⏭ naviguent la partie chargée. Resume commit.
  const pickParty = useCallback(
    async (name: string) => {
      setBusy(true);
      setError(null);
      try {
        await loadParty(name, "view");
        setLoadMenuOpen(false);
        const r = await fetchTimeline();
        setList(r.rows);
        setViewIndex(r.rows.length > 0 ? 0 : null);
        setIsPlaying(false);
        onViewModeChange(true);
      } catch (e) {
        setError(String((e as Error)?.message ?? e));
      } finally {
        setBusy(false);
      }
    },
    [loadParty, fetchTimeline, onViewModeChange]
  );

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
        let rows = list;
        if (rows.length === 0) {
          const r = await fetchTimeline();
          if (cancelled) return;
          rows = r.rows;
          setList(rows);
        }
        // 1re row de la phase/tour visé (row de début de phase, kind phase/turn/game_start).
        let idx = -1;
        if (jump.phase) {
          idx = rows.findIndex((s) => s.turn === jump.turn && s.phase === jump.phase);
        }
        if (idx < 0) idx = rows.findIndex((s) => s.turn === jump.turn);
        if (idx < 0) {
          setError(
            `Aucun point de timeline pour le tour ${jump.turn}${jump.phase ? ` / ${jump.phase}` : ""}`
          );
          return;
        }
        const m = rows[idx];
        await loadSave(m.id, "view");
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
  const progressPct =
    viewIndex == null || list.length === 0 ? 100 : ((viewIndex + 1) / list.length) * 100;
  const firstTarget = actionIndices.length ? actionIndices[0] : -1;
  const lastTarget = actionIndices.length ? actionIndices[actionIndices.length - 1] : -1;
  // Navigation snapshot : ⏮/⏭ entrent en visionnage depuis le live OU depuis un aperçu save.
  const prevTarget = viewIndex == null ? lastTarget : prevActionIndex(viewIndex);
  const nextTarget = viewIndex == null ? -1 : nextActionIndex(viewIndex);

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
                if (viewIndex == null) enterView(firstTarget);
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
          {[0.5, 1.0, 2.0, 5.0].map((speed) => (
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
            title="Enregistrer l'état courant"
            disabled={busy}
            onClick={() => {
              if (!canSave) {
                setNeedsDirOpen(true);
                return;
              }
              setSaveNote("");
              setSavePos({ x: 0, y: 0 });
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
            onClick={() => {
              if (!canSave) {
                setNeedsDirOpen(true);
                return;
              }
              toggleSaveMenu();
            }}
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
          <button
            type="button"
            className="replay-btn replay-btn--nav"
            title="Charger une partie sauvegardée (à son début)"
            disabled={busy}
            onClick={() => {
              if (!canSave) {
                setNeedsDirOpen(true);
                return;
              }
              toggleLoadMenu();
            }}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              background: "#ea580c",
              color: "#ffffff",
            }}
          >
            Load
            <ResumeIcon />
          </button>
          {loadMenuOpen && (
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
              {parties.length === 0 ? (
                <div style={{ color: "#9ca3af", padding: "6px 8px" }}>Aucune partie</div>
              ) : (
                parties.map((p) => (
                  <button
                    key={p.name}
                    type="button"
                    className="replay-btn"
                    disabled={busy}
                    onClick={() => pickParty(p.name)}
                    style={{
                      display: "block",
                      width: "100%",
                      height: "auto",
                      textAlign: "left",
                      padding: "6px 8px",
                      marginBottom: "4px",
                      background: "#374151",
                      color: "#ffffff",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {p.name}
                  </button>
                ))
              )}
            </div>
          )}
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
                [...saves]
                  .sort((a, b) => b.ts.localeCompare(a.ts))
                  .map((s) => {
                    const c = saveColors(s);
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
          Resume
          <ResumeBarIcon />
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
      {savePromptOpen &&
        // Portal sur document.body : sort du stacking context du container replay pour que le
        // z-index passe AU-DESSUS des overlays HTML du board (boucliers cover, portalés à z 150000).
        createPortal(
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
            zIndex: 200000,
          }}
        >
          {/* biome-ignore lint/a11y/noStaticElementInteractions: panneau — stopPropagation intentionnel */}
          <div
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
            style={{
              background: "var(--tooltip-bg)",
              border: "1px solid var(--tooltip-border-color)",
              borderRadius: "8px",
              padding: "16px",
              minWidth: "320px",
              color: "var(--tooltip-text-color)",
              boxShadow: "0 10px 30px rgba(0,0,0,0.5)",
              transform: `translate(${savePos.x}px, ${savePos.y}px)`,
            }}
          >
            <h3
              style={{
                marginTop: 0,
                backgroundColor: "var(--settings-title-bg)",
                padding: "6px 10px",
                borderRadius: "4px",
                cursor: "move",
                userSelect: "none",
              }}
              onMouseDown={(e) =>
                setSaveDrag({ sx: e.clientX, sy: e.clientY, bx: savePos.x, by: savePos.y })
              }
            >
              Enregistrer la partie
            </h3>
            <p
              style={{
                color: "var(--tooltip-text-color)",
                marginTop: 0,
                marginBottom: "6px",
                fontStyle: "italic",
              }}
            >
              Note (optionnelle) pour retrouver la save :
            </p>
            <input
              type="text"
              className="replay-note-input"
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
                color: "#fff",
              }}
            />
            {error && <p style={{ color: "#f87171" }}>{error}</p>}
            <div
              style={{ display: "flex", gap: "8px", justifyContent: "flex-end", marginTop: "14px" }}
            >
              <button
                type="button"
                className="replay-btn"
                disabled={busy}
                onClick={() => setSavePromptOpen(false)}
                style={{ background: "var(--ui-gray-cancel)", borderColor: "transparent", color: "#fff" }}
              >
                Cancel
              </button>
              <button
                type="button"
                className="replay-btn"
                disabled={busy}
                onClick={doSave}
                style={{ background: "var(--ui-green-validate)", borderColor: "transparent", color: "#fff" }}
              >
                Save
              </button>
            </div>
          </div>
          </div>,
          document.body
        )}

      {needsDirOpen && (
        // biome-ignore lint/a11y/noStaticElementInteractions: backdrop modal — clic fond = fermeture
        <div
          role="presentation"
          onClick={() => setNeedsDirOpen(false)}
          onKeyDown={(e) => e.key === "Escape" && setNeedsDirOpen(false)}
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
              maxWidth: "420px",
              color: "#fff",
              boxShadow: "0 10px 30px rgba(0,0,0,0.5)",
            }}
          >
            <h3 style={{ marginTop: 0 }}>Répertoire de sauvegarde requis</h3>
            <p style={{ color: "#9ca3af", marginTop: 0 }}>
              Pour utiliser Save, Select et Load, configure d'abord un répertoire de sauvegarde :
              menu → Sauvegarde → « Sauvegarde des snapshots sur disque ». Fais-le{" "}
              <strong>avant de jouer</strong> pour que la partie soit enregistrée dès le début.
            </p>
            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "14px" }}>
              <button
                type="button"
                className="replay-btn replay-btn--nav"
                onClick={() => setNeedsDirOpen(false)}
              >
                Compris
              </button>
            </div>
          </div>
        </div>
      )}

      {divergenceOpen && (
        // biome-ignore lint/a11y/noStaticElementInteractions: backdrop modal — clic fond = fermeture
        <div
          role="presentation"
          onClick={() => !busy && setDivergenceOpen(false)}
          onKeyDown={(e) => e.key === "Escape" && !busy && setDivergenceOpen(false)}
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
              minWidth: "340px",
              color: "#fff",
              boxShadow: "0 10px 30px rgba(0,0,0,0.5)",
            }}
          >
            <h3 style={{ marginTop: 0 }}>Reprise de la partie</h3>
            <p style={{ color: "#9ca3af", marginTop: 0 }}>
              Cette partie contient des sauvegardes postérieures au point de reprise.
            </p>
            <label
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                marginBottom: 8,
                cursor: "pointer",
              }}
            >
              <input
                type="radio"
                name="fork-choice"
                checked={forkChoice === "overwrite"}
                onChange={() => setForkChoice("overwrite")}
              />
              <span>Écraser les sauvegardes postérieures</span>
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
              <input
                type="radio"
                name="fork-choice"
                checked={forkChoice === "fork"}
                onChange={() => setForkChoice("fork")}
              />
              <span>Conserver la partie actuelle dans une copie</span>
            </label>
            {forkChoice === "fork" && (
              <input
                type="text"
                value={forkName}
                onChange={(e) => setForkName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !busy) confirmDivergence();
                }}
                placeholder="Nom de la copie (optionnel)"
                style={{
                  width: "100%",
                  boxSizing: "border-box",
                  marginTop: 8,
                  padding: "8px 10px",
                  borderRadius: "6px",
                  border: "1px solid #4b5563",
                  background: "#111827",
                  color: "#fff",
                }}
              />
            )}
            {error && <p style={{ color: "#f87171" }}>{error}</p>}
            <div
              style={{ display: "flex", gap: "8px", justifyContent: "flex-end", marginTop: "14px" }}
            >
              <button
                type="button"
                className="replay-btn replay-btn--nav"
                disabled={busy}
                onClick={() => setDivergenceOpen(false)}
              >
                Annuler
              </button>
              <button
                type="button"
                className="replay-btn"
                disabled={busy}
                onClick={confirmDivergence}
                style={{ background: "#059669", borderColor: "#047857", color: "#fff" }}
              >
                Confirmer
              </button>
            </div>
          </div>
        </div>
      )}

      {confirmModifyOpen && (
        // biome-ignore lint/a11y/noStaticElementInteractions: backdrop modal — clic fond = fermeture
        <div
          role="presentation"
          onClick={() => !busy && onCancelConfirmModify()}
          onKeyDown={(e) => e.key === "Escape" && !busy && onCancelConfirmModify()}
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
              minWidth: "340px",
              color: "#fff",
              boxShadow: "0 10px 30px rgba(0,0,0,0.5)",
            }}
          >
            <h3 style={{ marginTop: 0 }}>Modifier la partie en cours ?</h3>
            <p style={{ color: "#9ca3af", marginTop: 0 }}>
              Tu es en visionnage (lecture seule). Pour jouer à partir de ce point, il faut reprendre
              la partie ici — elle deviendra la partie en cours. Tu pourras ensuite rejouer ton action.
            </p>
            {error && <p style={{ color: "#f87171" }}>{error}</p>}
            <div
              style={{ display: "flex", gap: "8px", justifyContent: "flex-end", marginTop: "14px" }}
            >
              <button
                type="button"
                className="replay-btn replay-btn--nav"
                disabled={busy}
                onClick={() => onCancelConfirmModify()}
              >
                Annuler
              </button>
              <button
                type="button"
                className="replay-btn"
                disabled={busy || atLive}
                onClick={() => {
                  onCancelConfirmModify();
                  resumeHere();
                }}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "6px",
                  background: "#ef4444",
                  border: "1px solid #f87171",
                  color: "#fff",
                  fontWeight: 700,
                }}
              >
                Reprendre ici
                <ResumeBarIcon />
              </button>
            </div>
          </div>
        </div>
      )}

      {recordingPromptOpen && (
        // biome-ignore lint/a11y/noStaticElementInteractions: backdrop modal — clic fond = fermeture
        <div
          role="presentation"
          onClick={() => !busy && setRecordingPromptOpen(false)}
          onKeyDown={(e) => e.key === "Escape" && !busy && setRecordingPromptOpen(false)}
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
              background: "var(--tooltip-bg)",
              border: "1px solid var(--tooltip-border-color)",
              borderRadius: "8px",
              padding: "16px",
              minWidth: "340px",
              color: "var(--tooltip-text-color)",
              boxShadow: "0 10px 30px rgba(0,0,0,0.5)",
            }}
          >
            <h3
              style={{
                marginTop: 0,
                backgroundColor: "var(--settings-title-bg)",
                padding: "6px 10px",
                borderRadius: "4px",
              }}
            >
              Replay indisponible
            </h3>
            <p style={{ color: "var(--tooltip-text-color)", marginTop: 0 }}>
              Le replay nécessite l'enregistrement de la partie, qui n'est pas activé.
              <br />
              L'activer enregistrera la timeline à partir de maintenant.
            </p>
            {error && <p style={{ color: "#f87171" }}>{error}</p>}
            <div
              style={{ display: "flex", gap: "8px", justifyContent: "flex-end", marginTop: "14px" }}
            >
              <button
                type="button"
                className="replay-btn"
                disabled={busy}
                onClick={() => setRecordingPromptOpen(false)}
                style={{ background: "var(--ui-gray-cancel)", borderColor: "transparent", color: "#fff" }}
              >
                Cancel
              </button>
              <button
                type="button"
                className="replay-btn"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  setError(null);
                  try {
                    const enabled = await onEnableRecording();
                    if (!enabled) return; // annulé au sélecteur de répertoire → on ne ferme pas
                    const r = await fetchTimeline();
                    setList(r.rows);
                    setRecordingPromptOpen(false);
                  } catch (e) {
                    setError(String((e as Error)?.message ?? e));
                  } finally {
                    setBusy(false);
                  }
                }}
                style={{ background: "var(--ui-green-validate)", borderColor: "transparent", color: "#fff" }}
              >
                Activate
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default SnapshotRewind;
