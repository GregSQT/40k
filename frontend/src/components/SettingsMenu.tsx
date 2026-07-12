// frontend/src/components/SettingsMenu.tsx
import type React from "react";
import { useEffect, useRef, useState } from "react";
import type { BoardDisplayMode } from "./BoardPvp";

interface SettingsMenuProps {
  isOpen: boolean;
  onClose: () => void;
  onLogout: () => void;
  showAdvanceWarning: boolean;
  canToggleAdvanceWarning: boolean;
  onToggleAdvanceWarning: (value: boolean) => void;
  showDebug: boolean;
  onToggleDebug: (value: boolean) => void;
  showDebugLoS: boolean;
  onToggleDebugLoS: (value: boolean) => void;
  shootPoolFastMode?: boolean;
  onToggleShootPoolFastMode?: (value: boolean) => void;
  autoSelectWeapon: boolean;
  canToggleAutoSelectWeapon: boolean;
  onToggleAutoSelectWeapon: (value: boolean) => void;
  hpBarPerModel?: boolean;
  onToggleHpBarPerModel?: (value: boolean) => void;
  hpBarBlinkEnlarged?: boolean;
  onToggleHpBarBlinkEnlarged?: (value: boolean) => void;
  showWoundProbability?: boolean;
  onToggleShowWoundProbability?: (value: boolean) => void;
  boardDisplayMode?: BoardDisplayMode;
  onSetBoardDisplayMode?: (value: BoardDisplayMode) => void;
  statusBadgePerModel?: boolean;
  onToggleStatusBadgePerModel?: (value: boolean) => void;
  retreatAlertEnabled?: boolean;
  onToggleRetreatAlert?: (value: boolean) => void;
  modeGuidesActivated?: boolean;
  onToggleModeGuidesActivated?: (value: boolean) => void;
  battleShockTestEnabled?: boolean;
  onToggleBattleShockTest?: (value: boolean) => void;
  deployIconBaseSizeBounded?: boolean;
  onToggleDeployIconBaseSizeBounded?: (value: boolean) => void;
  logShowCoords?: boolean;
  onToggleLogShowCoords?: (value: boolean) => void;
  logShowType?: boolean;
  onToggleLogShowType?: (value: boolean) => void;
  dynamicCoverStatus?: boolean;
  onToggleDynamicCoverStatus?: (value: boolean) => void;
  snapshotPersistEnabled?: boolean;
  snapshotPersistDir?: string;
  onToggleSnapshotPersist?: (value: boolean, directory?: string) => void;
  /** Ouvre un explorateur natif (Windows via WSL) et renvoie le chemin choisi, ou null si annulé. */
  onPickDirectory?: () => Promise<string | null>;
  replayContainerEnabled?: boolean;
  onToggleReplayContainer?: (value: boolean) => void;
  autoSaveEnabled?: boolean;
  onToggleAutoSave?: (value: boolean) => void;
  autoSaveGranularity?: "phase" | "turn";
  onSetAutoSaveGranularity?: (value: "phase" | "turn") => void;
  onDeleteSaves?: () => Promise<void> | void;
}

/**
 * Catégorie repliable/dépliable (défini hors du composant pour ne pas remonter).
 * Repliée par défaut ; l'état ouvert/fermé est mémorisé en localStorage pour
 * être conservé au fil de la partie (réouverture du menu, navigation).
 */
const CollapsibleSection: React.FC<{ title: string; children: React.ReactNode }> = ({
  title,
  children,
}) => {
  const storageKey = `settingsSectionOpen:${title}`;
  const [open, setOpen] = useState(() => localStorage.getItem(storageKey) === "true");
  const toggle = () => {
    setOpen((v) => {
      const next = !v;
      localStorage.setItem(storageKey, JSON.stringify(next));
      return next;
    });
  };
  return (
    <div style={{ marginBottom: "12px", border: "1px solid #4caf50", borderRadius: "6px" }}>
      <button
        type="button"
        onClick={toggle}
        className="settings-category-header"
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          gap: "10px",
          backgroundColor: "var(--settings-category-bg)",
          color: "var(--tooltip-text-color)",
          border: "none",
          borderRadius: "6px",
          padding: "10px 12px",
          cursor: "pointer",
          fontSize: "18px",
          fontWeight: 600,
        }}
      >
        <span style={{ width: "14px", textAlign: "center" }}>{open ? "−" : "+"}</span>
        <span>{title}</span>
      </button>
      {open && <div style={{ padding: "12px 12px 0 12px" }}>{children}</div>}
    </div>
  );
};

/** Ligne d'option checkbox + description, factorisée. */
const ToggleRow: React.FC<{
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  description: string;
}> = ({ checked, onChange, label, description }) => (
  <div style={{ marginBottom: "16px" }}>
    <label
      style={{
        display: "flex",
        alignItems: "center",
        cursor: "pointer",
        color: "var(--tooltip-text-color)",
      }}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        style={{ marginRight: "12px", width: "18px", height: "18px", cursor: "pointer" }}
      />
      <span>{label}</span>
    </label>
    <p
      style={{
        color: "var(--tooltip-text-color)",
        fontSize: "14px",
        marginLeft: "30px",
        marginTop: "4px",
      }}
    >
      {description}
    </p>
  </div>
);

export const SettingsMenu: React.FC<SettingsMenuProps> = ({
  isOpen,
  onClose,
  onLogout,
  showAdvanceWarning,
  canToggleAdvanceWarning,
  onToggleAdvanceWarning,
  showDebug,
  onToggleDebug,
  showDebugLoS,
  onToggleDebugLoS,
  shootPoolFastMode = false,
  onToggleShootPoolFastMode,
  autoSelectWeapon,
  canToggleAutoSelectWeapon,
  onToggleAutoSelectWeapon,
  hpBarPerModel = false,
  onToggleHpBarPerModel,
  hpBarBlinkEnlarged = false,
  onToggleHpBarBlinkEnlarged,
  showWoundProbability = false,
  onToggleShowWoundProbability,
  boardDisplayMode = "full",
  onSetBoardDisplayMode,
  statusBadgePerModel = false,
  onToggleStatusBadgePerModel,
  retreatAlertEnabled = true,
  onToggleRetreatAlert,
  modeGuidesActivated = true,
  onToggleModeGuidesActivated,
  battleShockTestEnabled = false,
  onToggleBattleShockTest,
  deployIconBaseSizeBounded = true,
  onToggleDeployIconBaseSizeBounded,
  logShowCoords = false,
  onToggleLogShowCoords,
  logShowType = true,
  onToggleLogShowType,
  dynamicCoverStatus = true,
  onToggleDynamicCoverStatus,
  snapshotPersistEnabled = false,
  snapshotPersistDir = "logs",
  onToggleSnapshotPersist,
  onPickDirectory,
  replayContainerEnabled = true,
  onToggleReplayContainer,
  autoSaveEnabled = false,
  onToggleAutoSave,
  autoSaveGranularity = "phase",
  onSetAutoSaveGranularity,
  onDeleteSaves,
}) => {
  const [confirmingDeleteSaves, setConfirmingDeleteSaves] = useState(false);
  const [deletedSavesMsg, setDeletedSavesMsg] = useState<string | null>(null);
  const [persistDirPromptOpen, setPersistDirPromptOpen] = useState(false);
  const [persistDirInput, setPersistDirInput] = useState("");
  // Snapshot des réglages à l'ouverture du menu, pour pouvoir annuler les
  // changements (appliqués en live) en restaurant les valeurs initiales.
  type SettingsSnapshot = {
    showAdvanceWarning: boolean;
    showDebug: boolean;
    showDebugLoS: boolean;
    shootPoolFastMode: boolean;
    autoSelectWeapon: boolean;
    hpBarPerModel: boolean;
    hpBarBlinkEnlarged: boolean;
    showWoundProbability: boolean;
    boardDisplayMode: BoardDisplayMode;
    statusBadgePerModel: boolean;
    retreatAlertEnabled: boolean;
    modeGuidesActivated: boolean;
    battleShockTestEnabled: boolean;
    deployIconBaseSizeBounded: boolean;
    logShowCoords: boolean;
    logShowType: boolean;
    dynamicCoverStatus: boolean;
    replayContainerEnabled: boolean;
  };
  const latest: SettingsSnapshot = {
    showAdvanceWarning,
    showDebug,
    showDebugLoS,
    shootPoolFastMode,
    autoSelectWeapon,
    hpBarPerModel,
    hpBarBlinkEnlarged,
    showWoundProbability,
    boardDisplayMode,
    statusBadgePerModel,
    retreatAlertEnabled,
    modeGuidesActivated,
    battleShockTestEnabled,
    deployIconBaseSizeBounded,
    logShowCoords,
    logShowType,
    dynamicCoverStatus,
    replayContainerEnabled,
  };
  const latestRef = useRef(latest);
  latestRef.current = latest;
  const snapshotRef = useRef<SettingsSnapshot | null>(null);

  useEffect(() => {
    if (isOpen) {
      snapshotRef.current = { ...latestRef.current };
    }
  }, [isOpen]);

  const handleCancel = () => {
    const s = snapshotRef.current;
    if (s) {
      if (showAdvanceWarning !== s.showAdvanceWarning) onToggleAdvanceWarning(s.showAdvanceWarning);
      if (showDebug !== s.showDebug) onToggleDebug(s.showDebug);
      if (showDebugLoS !== s.showDebugLoS) onToggleDebugLoS(s.showDebugLoS);
      if (onToggleShootPoolFastMode && shootPoolFastMode !== s.shootPoolFastMode)
        onToggleShootPoolFastMode(s.shootPoolFastMode);
      if (autoSelectWeapon !== s.autoSelectWeapon) onToggleAutoSelectWeapon(s.autoSelectWeapon);
      if (onToggleHpBarPerModel && hpBarPerModel !== s.hpBarPerModel)
        onToggleHpBarPerModel(s.hpBarPerModel);
      if (onToggleHpBarBlinkEnlarged && hpBarBlinkEnlarged !== s.hpBarBlinkEnlarged)
        onToggleHpBarBlinkEnlarged(s.hpBarBlinkEnlarged);
      if (onToggleShowWoundProbability && showWoundProbability !== s.showWoundProbability)
        onToggleShowWoundProbability(s.showWoundProbability);
      if (onSetBoardDisplayMode && boardDisplayMode !== s.boardDisplayMode)
        onSetBoardDisplayMode(s.boardDisplayMode);
      if (onToggleStatusBadgePerModel && statusBadgePerModel !== s.statusBadgePerModel)
        onToggleStatusBadgePerModel(s.statusBadgePerModel);
      if (onToggleRetreatAlert && retreatAlertEnabled !== s.retreatAlertEnabled)
        onToggleRetreatAlert(s.retreatAlertEnabled);
      if (onToggleModeGuidesActivated && modeGuidesActivated !== s.modeGuidesActivated)
        onToggleModeGuidesActivated(s.modeGuidesActivated);
      if (onToggleBattleShockTest && battleShockTestEnabled !== s.battleShockTestEnabled)
        onToggleBattleShockTest(s.battleShockTestEnabled);
      if (
        onToggleDeployIconBaseSizeBounded &&
        deployIconBaseSizeBounded !== s.deployIconBaseSizeBounded
      )
        onToggleDeployIconBaseSizeBounded(s.deployIconBaseSizeBounded);
      if (onToggleLogShowCoords && logShowCoords !== s.logShowCoords)
        onToggleLogShowCoords(s.logShowCoords);
      if (onToggleLogShowType && logShowType !== s.logShowType) onToggleLogShowType(s.logShowType);
      if (onToggleDynamicCoverStatus && dynamicCoverStatus !== s.dynamicCoverStatus)
        onToggleDynamicCoverStatus(s.dynamicCoverStatus);
      if (onToggleReplayContainer && replayContainerEnabled !== s.replayContainerEnabled)
        onToggleReplayContainer(s.replayContainerEnabled);
    }
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 10000,
      }}
    >
      <button
        type="button"
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: "rgba(0, 0, 0, 0.7)",
          border: "none",
          padding: 0,
          cursor: "pointer",
        }}
        onClick={onClose}
        aria-label="Close settings"
      />
      <div
        role="dialog"
        aria-modal="true"
        style={{
          position: "relative",
          zIndex: 1,
          backgroundColor: "rgba(20, 20, 20, 0.98)",
          borderRadius: "6px",
          padding: "24px",
          width: "600px",
          maxWidth: "90vw",
          maxHeight: "85vh",
          display: "flex",
          flexDirection: "column",
          border: "2px solid #4caf50",
          boxShadow: "0 4px 12px rgba(0, 0, 0, 0.5)",
        }}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
      >
        <h2
          style={{
            color: "var(--tooltip-text-color)",
            marginTop: 0,
            marginBottom: "20px",
            fontSize: "24px",
            flexShrink: 0,
            backgroundColor: "var(--settings-title-bg)",
            textTransform: "uppercase",
            letterSpacing: "0.5px",
            padding: "6px 10px",
            borderRadius: "4px",
          }}
        >
          ⚙️ Paramètres
        </h2>

        <div style={{ overflowY: "auto", flex: 1, minHeight: 0, paddingRight: "8px" }}>
          {(canToggleAdvanceWarning || onToggleRetreatAlert) && (
            <CollapsibleSection title="Alertes">
              {canToggleAdvanceWarning && (
                <ToggleRow
                  checked={showAdvanceWarning}
                  onChange={onToggleAdvanceWarning}
                  label="Alerte d'advance"
                  description="Affiche une confirmation avant de valider une action Advance."
                />
              )}
              {onToggleRetreatAlert && (
                <ToggleRow
                  checked={retreatAlertEnabled}
                  onChange={onToggleRetreatAlert}
                  label="Alerte de retraite"
                  description="Affiche une confirmation avant de valider un mouvement de Retraite."
                />
              )}
            </CollapsibleSection>
          )}

          <CollapsibleSection title="Débug">
            <ToggleRow
              checked={showDebug}
              onChange={onToggleDebug}
              label="Debug mode"
              description="Affiche les coordonnées des hex, les ID des unités et les récompenses"
            />
            <ToggleRow
              checked={showDebugLoS}
              onChange={onToggleDebugLoS}
              label="Debug LoS"
              description="Affiche le ratio de visibilité LoS (%) en phase de tir."
            />
            {onToggleBattleShockTest && (
              <ToggleRow
                checked={battleShockTestEnabled}
                onChange={onToggleBattleShockTest}
                label="Bouton test Battle-shock"
                description="Affiche un bouton dans la barre de move pour forcer un battle-shock roll (01.07) sur l'unité active — sert à tester le Desperate Escape (09.07)."
              />
            )}
            {onToggleLogShowCoords && (
              <ToggleRow
                checked={logShowCoords}
                onChange={onToggleLogShowCoords}
                label="Coordonnées dans le Combat log"
                description="Affiche les coordonnées (col,row) des unités dans les lignes de tir/combat du Game Log."
              />
            )}
            {onToggleLogShowType && (
              <ToggleRow
                checked={logShowType}
                onChange={onToggleLogShowType}
                label="Type d'unité dans le Combat log"
                description="Affiche le type (ex. Intercessor) des unités dans les lignes de tir/combat du Game Log."
              />
            )}
          </CollapsibleSection>

          {canToggleAutoSelectWeapon && (
            <CollapsibleSection title="Gameplay">
              <ToggleRow
                checked={autoSelectWeapon}
                onChange={onToggleAutoSelectWeapon}
                label="Sélection automatique d'arme"
                description="Désactiver pour choisir manuellement l'arme à utiliser pour chaque tir."
              />
            </CollapsibleSection>
          )}

          {(onToggleAutoSave || onDeleteSaves || onToggleSnapshotPersist) && (
            <CollapsibleSection title="Sauvegarde">
              {onToggleSnapshotPersist && (
                <ToggleRow
                  checked={snapshotPersistEnabled}
                  onChange={(checked) => {
                    if (!checked) {
                      onToggleSnapshotPersist(false);
                      return;
                    }
                    if (onPickDirectory) {
                      onPickDirectory()
                        .then((path) => {
                          if (path) onToggleSnapshotPersist(true, path);
                        })
                        .catch(() => {
                          // Fallback : saisie manuelle si le sélecteur natif échoue.
                          setPersistDirInput(snapshotPersistDir);
                          setPersistDirPromptOpen(true);
                        });
                    } else {
                      setPersistDirInput(snapshotPersistDir);
                      setPersistDirPromptOpen(true);
                    }
                  }}
                  label="Sauvegarde des snapshots sur disque"
                  description="Conserve l'historique des phases (rewind / visionnage) et les saves sur disque pour qu'ils survivent à un rechargement. À l'activation, choisis le répertoire de destination."
                />
              )}
              {persistDirPromptOpen && onToggleSnapshotPersist && (
                // biome-ignore lint/a11y/noStaticElementInteractions: backdrop modal — clic fond = fermeture
                <div
                  role="presentation"
                  onClick={() => setPersistDirPromptOpen(false)}
                  onKeyDown={(e) => e.key === "Escape" && setPersistDirPromptOpen(false)}
                  style={{
                    position: "fixed",
                    inset: 0,
                    background: "rgba(0,0,0,0.55)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    zIndex: 5000,
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
                      minWidth: "360px",
                      color: "#fff",
                      boxShadow: "0 10px 30px rgba(0,0,0,0.5)",
                    }}
                  >
                    <h3 style={{ marginTop: 0 }}>Répertoire de sauvegarde</h3>
                    <p style={{ color: "#9ca3af", marginTop: 0 }}>
                      Chemin (serveur) où écrire snapshots et saves :
                    </p>
                    <input
                      type="text"
                      value={persistDirInput}
                      onChange={(e) => setPersistDirInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          onToggleSnapshotPersist(true, persistDirInput.trim() || "logs");
                          setPersistDirPromptOpen(false);
                        }
                      }}
                      placeholder="logs"
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
                    <div
                      style={{
                        display: "flex",
                        gap: "8px",
                        justifyContent: "flex-end",
                        marginTop: "14px",
                      }}
                    >
                      <button
                        type="button"
                        onClick={() => setPersistDirPromptOpen(false)}
                        style={{
                          background: "#374151",
                          border: "1px solid #4b5563",
                          borderRadius: "4px",
                          color: "#fff",
                          padding: "6px 12px",
                          cursor: "pointer",
                        }}
                      >
                        Annuler
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          onToggleSnapshotPersist(true, persistDirInput.trim() || "logs");
                          setPersistDirPromptOpen(false);
                        }}
                        style={{
                          background: "#059669",
                          border: "1px solid #047857",
                          borderRadius: "4px",
                          color: "#fff",
                          padding: "6px 12px",
                          cursor: "pointer",
                        }}
                      >
                        Activer
                      </button>
                    </div>
                  </div>
                </div>
              )}
              {onToggleAutoSave && (
                <ToggleRow
                  checked={autoSaveEnabled}
                  onChange={onToggleAutoSave}
                  label="Sauvegarde automatique"
                  description="Crée automatiquement une save (visible dans le menu Select du container de replay) au fil de la partie. NB : Relancez le jeu pour prendre en compte cette option."
                />
              )}
              {onSetAutoSaveGranularity && (
                <div style={{ marginBottom: "16px", opacity: autoSaveEnabled ? 1 : 0.5 }}>
                  <label
                    style={{
                      display: "block",
                      cursor: autoSaveEnabled ? "pointer" : "default",
                      color: "var(--tooltip-text-color)",
                      marginBottom: "6px",
                    }}
                  >
                    <span style={{ marginRight: "12px" }}>Fréquence</span>
                    <select
                      value={autoSaveGranularity}
                      disabled={!autoSaveEnabled}
                      onChange={(e) => onSetAutoSaveGranularity(e.target.value as "phase" | "turn")}
                      style={{
                        backgroundColor: "#111827",
                        color: "var(--tooltip-text-color)",
                        border: "1px solid #4b5563",
                        borderRadius: "4px",
                        padding: "4px 8px",
                      }}
                    >
                      <option value="phase">À chaque début de phase</option>
                      <option value="turn">À chaque début de tour</option>
                    </select>
                  </label>
                </div>
              )}
              {onDeleteSaves && (
                <div style={{ marginBottom: "8px" }}>
                  {confirmingDeleteSaves ? (
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                      <span style={{ color: "var(--tooltip-text-color)" }}>
                        Confirmer la suppression de toutes les sauvegardes ?
                      </span>
                      <button
                        type="button"
                        onClick={async () => {
                          await onDeleteSaves();
                          setConfirmingDeleteSaves(false);
                          setDeletedSavesMsg("Sauvegardes supprimées.");
                        }}
                        style={{
                          background: "#dc2626",
                          border: "1px solid #991b1b",
                          borderRadius: "4px",
                          color: "#fff",
                          padding: "4px 12px",
                          cursor: "pointer",
                        }}
                      >
                        Oui
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmingDeleteSaves(false)}
                        style={{
                          background: "#374151",
                          border: "1px solid #4b5563",
                          borderRadius: "4px",
                          color: "#fff",
                          padding: "4px 12px",
                          cursor: "pointer",
                        }}
                      >
                        Non
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => {
                        setDeletedSavesMsg(null);
                        setConfirmingDeleteSaves(true);
                      }}
                      style={{
                        background: "#dc2626",
                        border: "1px solid #991b1b",
                        borderRadius: "4px",
                        color: "#fff",
                        padding: "6px 12px",
                        cursor: "pointer",
                      }}
                    >
                      Supprimer les sauvegardes
                    </button>
                  )}
                  {deletedSavesMsg && (
                    <div style={{ color: "#9ca3af", marginTop: "6px" }}>{deletedSavesMsg}</div>
                  )}
                </div>
              )}
            </CollapsibleSection>
          )}

          {(onToggleHpBarPerModel ||
            onToggleHpBarBlinkEnlarged ||
            onToggleShowWoundProbability ||
            onToggleStatusBadgePerModel ||
            onSetBoardDisplayMode ||
            onToggleReplayContainer ||
            onToggleDeployIconBaseSizeBounded) && (
            <CollapsibleSection title="Display">
              {onToggleReplayContainer && (
                <ToggleRow
                  checked={replayContainerEnabled}
                  onChange={onToggleReplayContainer}
                  label="Container de replay"
                  description="Activé : affiche l'icône caméra et le container de contrôle du replay (rewind / saves) sous le tracker de phase, en mode PvP."
                />
              )}
              {onToggleHpBarPerModel && (
                <ToggleRow
                  checked={hpBarPerModel}
                  onChange={onToggleHpBarPerModel}
                  label="Barre HP par figurine"
                  description="Activé : une barre de vie sur chaque figurine. Désactivé : une seule barre par escouade (hors personnages). Les personnages affichent toujours leurs PV réels."
                />
              )}
              {onToggleHpBarBlinkEnlarged && (
                <ToggleRow
                  checked={hpBarBlinkEnlarged}
                  onChange={onToggleHpBarBlinkEnlarged}
                  label="Grossir barre HP des cibles"
                  description="Activé : la barre de vie des cibles blink / prévisualisées est agrandie (×1.5). Désactivé : taille normale."
                />
              )}
              {onToggleShowWoundProbability && (
                <ToggleRow
                  checked={showWoundProbability}
                  onChange={onToggleShowWoundProbability}
                  label="Probabilité de blessure"
                  description="Affiche au-dessus des cibles potentielles la probabilité qu'une attaque inflige une blessure non sauvegardée (touche × blesse × sauvegarde ratée). N'affecte pas le jet de charge affiché en phase de charge."
                />
              )}
              {onToggleStatusBadgePerModel && (
                <ToggleRow
                  checked={statusBadgePerModel}
                  onChange={onToggleStatusBadgePerModel}
                  label="Badges de statut par figurine"
                  description="Activé : un badge (caché, fui, choc) sur chaque figurine concernée. Désactivé : un seul badge sur l'escouade (uniquement si toutes les figurines ont le statut)."
                />
              )}
              {onSetBoardDisplayMode && (
                <div style={{ marginBottom: "16px" }}>
                  <label
                    style={{
                      display: "block",
                      cursor: "pointer",
                      color: "var(--tooltip-text-color)",
                      marginBottom: "6px",
                    }}
                  >
                    <span style={{ marginRight: "12px" }}>Affichage du plateau</span>
                    <select
                      value={boardDisplayMode}
                      onChange={(e) => onSetBoardDisplayMode(e.target.value as BoardDisplayMode)}
                      style={{
                        backgroundColor: "#111827",
                        color: "var(--tooltip-text-color)",
                        border: "1px solid #4b5563",
                        borderRadius: "4px",
                        padding: "4px 8px",
                        cursor: "pointer",
                      }}
                    >
                      <option value="full">Taille réelle (la page défile)</option>
                      <option value="fit">Adapté à l'écran</option>
                      <option value="window">Fenêtre navigable (molette/scroll)</option>
                    </select>
                  </label>
                  <p
                    style={{
                      color: "var(--tooltip-text-color)",
                      fontSize: "14px",
                      marginTop: "4px",
                    }}
                  >
                    Taille réelle : plateau à sa taille, la page défile. Adapté : plateau réduit
                    pour tenir entièrement dans l'écran. Fenêtre : plateau à sa taille dans une
                    fenêtre limitée à l'écran, navigable à la molette ou à la barre de défilement.
                  </p>
                </div>
              )}
              {onToggleDeployIconBaseSizeBounded && (
                <ToggleRow
                  checked={deployIconBaseSizeBounded}
                  onChange={onToggleDeployIconBaseSizeBounded}
                  label="Bornes taille icônes (déploiement)"
                  description="Activé : les icônes du panneau de déploiement sont bornées (24–60px) pour préserver la mise en page. Désactivé : affiche la taille réelle du socle de chaque figurine."
                />
              )}
            </CollapsibleSection>
          )}

          {(onToggleDynamicCoverStatus || onToggleShootPoolFastMode) && (
            <CollapsibleSection title="Performances">
              {onToggleDynamicCoverStatus && (
                <ToggleRow
                  checked={dynamicCoverStatus}
                  onChange={onToggleDynamicCoverStatus}
                  label="Statut couvert / caché dynamique"
                  description="Activé : pendant la prévisualisation de mouvement, les badges couvert, caché et portée de détection (15&quot; / 12&quot;) des ennemis sont recalculés à chaque case survolée, depuis la destination du fantôme. Désactivé : ils restent figés sur le statut de la position d'origine. ⚠️ Impact sur les performances : un calcul serveur par case nouvellement survolée."
                />
              )}
              {onToggleShootPoolFastMode && (
                <ToggleRow
                  checked={shootPoolFastMode}
                  onChange={onToggleShootPoolFastMode}
                  label="Pool tir : transition rapide"
                  description="Activé (défaut) : saute le test cible+LoS au démarrage de la phase de tir (transition move→tir rapide) ; la présence de cible est résolue à l'activation — une unité sans cible visible peut apparaître activable puis passer son tour. Désactivé : pool exact (vérifie cible à portée + LoS avant de rendre activable, pas de cercle vert inutile) mais coûte ~1,5 s par transition."
                />
              )}
            </CollapsibleSection>
          )}

          {onToggleModeGuidesActivated && (
            <CollapsibleSection title="Guides">
              <ToggleRow
                checked={modeGuidesActivated}
                onChange={onToggleModeGuidesActivated}
                label="Modes guides activated"
                description="Active les guides d'introduction PvE/PvP. Désactivé automatiquement après avoir vu un guide."
              />
            </CollapsibleSection>
          )}
        </div>

        <div
          style={{
            marginTop: "24px",
            display: "flex",
            justifyContent: "space-between",
            flexShrink: 0,
          }}
        >
          <button
            type="button"
            onClick={onLogout}
            style={{
              padding: "8px 16px",
              backgroundColor: "#991b1b",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor: "pointer",
              fontSize: "16px",
            }}
          >
            Se déconnecter
          </button>
          <div style={{ display: "flex", gap: "8px" }}>
            <button
              type="button"
              onClick={handleCancel}
              style={{
                padding: "8px 16px",
                backgroundColor: "var(--ui-gray-cancel)",
                color: "white",
                border: "none",
                borderRadius: "4px",
                cursor: "pointer",
                fontSize: "16px",
              }}
            >
              Annuler
            </button>
            <button
              type="button"
              onClick={onClose}
              style={{
                padding: "8px 16px",
                backgroundColor: "var(--ui-green-validate)",
                color: "white",
                border: "none",
                borderRadius: "4px",
                cursor: "pointer",
                fontSize: "16px",
              }}
            >
              Fermer
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
