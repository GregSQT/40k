// frontend/src/components/SettingsMenu.tsx
import type React from "react";
import { useEffect, useRef, useState } from "react";

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
  autoSelectWeapon: boolean;
  canToggleAutoSelectWeapon: boolean;
  onToggleAutoSelectWeapon: (value: boolean) => void;
  hpBarPerModel?: boolean;
  onToggleHpBarPerModel?: (value: boolean) => void;
  fitBoardToScreen?: boolean;
  onToggleFitBoardToScreen?: (value: boolean) => void;
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
    <div style={{ marginBottom: "12px", border: "1px solid #374151", borderRadius: "6px" }}>
      <button
        type="button"
        onClick={toggle}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          gap: "10px",
          backgroundColor: "#111827",
          color: "#e5e7eb",
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
    <label style={{ display: "flex", alignItems: "center", cursor: "pointer", color: "#e5e7eb" }}>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        style={{ marginRight: "12px", width: "18px", height: "18px", cursor: "pointer" }}
      />
      <span>{label}</span>
    </label>
    <p style={{ color: "#9ca3af", fontSize: "14px", marginLeft: "30px", marginTop: "4px" }}>
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
  autoSelectWeapon,
  canToggleAutoSelectWeapon,
  onToggleAutoSelectWeapon,
  hpBarPerModel = false,
  onToggleHpBarPerModel,
  fitBoardToScreen = false,
  onToggleFitBoardToScreen,
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
}) => {
  // Snapshot des réglages à l'ouverture du menu, pour pouvoir annuler les
  // changements (appliqués en live) en restaurant les valeurs initiales.
  type SettingsSnapshot = {
    showAdvanceWarning: boolean;
    showDebug: boolean;
    showDebugLoS: boolean;
    autoSelectWeapon: boolean;
    hpBarPerModel: boolean;
    fitBoardToScreen: boolean;
    statusBadgePerModel: boolean;
    retreatAlertEnabled: boolean;
    modeGuidesActivated: boolean;
    battleShockTestEnabled: boolean;
    deployIconBaseSizeBounded: boolean;
  };
  const latest: SettingsSnapshot = {
    showAdvanceWarning,
    showDebug,
    showDebugLoS,
    autoSelectWeapon,
    hpBarPerModel,
    fitBoardToScreen,
    statusBadgePerModel,
    retreatAlertEnabled,
    modeGuidesActivated,
    battleShockTestEnabled,
    deployIconBaseSizeBounded,
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
      if (showAdvanceWarning !== s.showAdvanceWarning)
        onToggleAdvanceWarning(s.showAdvanceWarning);
      if (showDebug !== s.showDebug) onToggleDebug(s.showDebug);
      if (showDebugLoS !== s.showDebugLoS) onToggleDebugLoS(s.showDebugLoS);
      if (autoSelectWeapon !== s.autoSelectWeapon) onToggleAutoSelectWeapon(s.autoSelectWeapon);
      if (onToggleHpBarPerModel && hpBarPerModel !== s.hpBarPerModel)
        onToggleHpBarPerModel(s.hpBarPerModel);
      if (onToggleFitBoardToScreen && fitBoardToScreen !== s.fitBoardToScreen)
        onToggleFitBoardToScreen(s.fitBoardToScreen);
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
          backgroundColor: "#1f2937",
          borderRadius: "8px",
          padding: "24px",
          width: "600px",
          maxWidth: "90vw",
          maxHeight: "85vh",
          display: "flex",
          flexDirection: "column",
          border: "2px solid #4b5563",
        }}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
      >
        <h2
          style={{
            color: "white",
            marginTop: 0,
            marginBottom: "20px",
            fontSize: "24px",
            flexShrink: 0,
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

          {(onToggleHpBarPerModel ||
            onToggleStatusBadgePerModel ||
            onToggleFitBoardToScreen ||
            onToggleDeployIconBaseSizeBounded) && (
            <CollapsibleSection title="Display">
              {onToggleHpBarPerModel && (
                <ToggleRow
                  checked={hpBarPerModel}
                  onChange={onToggleHpBarPerModel}
                  label="Barre HP par figurine"
                  description="Activé : une barre de vie sur chaque figurine. Désactivé : une seule barre par escouade (hors personnages). Les personnages affichent toujours leurs PV réels."
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
              {onToggleFitBoardToScreen && (
                <ToggleRow
                  checked={fitBoardToScreen}
                  onChange={onToggleFitBoardToScreen}
                  label="Adapter le plateau à l'écran"
                  description="Activé : le plateau est réduit pour être affiché en entier dans la hauteur de l'écran. Désactivé : le plateau est affiché à sa taille réelle et la page défile."
                />
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
                backgroundColor: "#4b5563",
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
                backgroundColor: "#3b82f6",
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
