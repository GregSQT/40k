// frontend/src/components/SettingsMenu.tsx
import React from 'react';

interface SettingsMenuProps {
    isOpen: boolean;
    onClose: () => void;
    showAdvanceWarning: boolean;
    onToggleAdvanceWarning: (value: boolean) => void;
    showDebug: boolean;
    onToggleDebug: (value: boolean) => void;
  }
  
  export const SettingsMenu: React.FC<SettingsMenuProps> = ({
    isOpen,
    onClose,
    showAdvanceWarning,
    onToggleAdvanceWarning,
    showDebug,
    onToggleDebug,
  }) => {
    if (!isOpen) return null;

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.7)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 10000,
      }}
      onClick={onClose}
    >
      <div
        style={{
          backgroundColor: '#1f2937',
          borderRadius: '8px',
          padding: '24px',
          minWidth: '400px',
          maxWidth: '600px',
          border: '2px solid #4b5563',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 style={{ color: 'white', marginTop: 0, marginBottom: '20px', fontSize: '24px' }}>
          ⚙️ Paramètres
        </h2>
        
        <div style={{ marginBottom: '16px' }}>
          <label style={{ display: 'flex', alignItems: 'center', cursor: 'pointer', color: '#e5e7eb' }}>
            <input
              type="checkbox"
              checked={showAdvanceWarning}
              onChange={(e) => onToggleAdvanceWarning(e.target.checked)}
              style={{ marginRight: '12px', width: '18px', height: '18px', cursor: 'pointer' }}
            />
            <span>Afficher l'avertissement lors du mode Advance</span>
          </label>
          <p style={{ color: '#9ca3af', fontSize: '14px', marginLeft: '30px', marginTop: '4px' }}>
            Désactiver cette option permet de passer en mode Advance sans confirmation.
          </p>
        </div>

        <div style={{ marginBottom: '16px' }}>
          <label style={{ display: 'flex', alignItems: 'center', cursor: 'pointer', color: '#e5e7eb' }}>
            <input
              type="checkbox"
              checked={showDebug}
              onChange={(e) => onToggleDebug(e.target.checked)}
              style={{ marginRight: '12px', width: '18px', height: '18px', cursor: 'pointer' }}
            />
            <span>Debug mode</span>
          </label>
          <p style={{ color: '#9ca3af', fontSize: '14px', marginLeft: '30px', marginTop: '4px' }}>
            Affiche les coordonnées des hex et les récompenses
          </p>
        </div>

        <div style={{ marginTop: '24px', display: 'flex', justifyContent: 'flex-end' }}>
          <button
            onClick={onClose}
            style={{
              padding: '8px 16px',
              backgroundColor: '#3b82f6',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '16px',
            }}
          >
            Fermer
          </button>
        </div>
      </div>
    </div>
  );
};
