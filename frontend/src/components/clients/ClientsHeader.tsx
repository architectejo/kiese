import React from 'react';
import { FiPlus, FiChevronDown, FiShoppingBag, FiCreditCard, FiDownload } from 'react-icons/fi';

interface ClientsHeaderProps {
  canAccessAllNodes: boolean;
  openImportModal: () => void;
  isActionMenuOpen: boolean;
  setIsActionMenuOpen: (open: boolean) => void;
  triggerCasualSale: () => void;
  openAddModal: () => void | Promise<void>;
}

/** En-tête de la page Gestion Clientèle et menu « Nouvelle vente ». */
export const ClientsHeader: React.FC<ClientsHeaderProps> = ({
  canAccessAllNodes, openImportModal, isActionMenuOpen, setIsActionMenuOpen, triggerCasualSale, openAddModal,
}) => {
  return (
      <div className="glass-card animate-fade-in" style={{
        background: 'linear-gradient(135deg, hsl(var(--bg-tertiary)) 0%, hsl(var(--bg-secondary)) 100%)',
        borderLeft: '4px solid hsl(var(--accent-color))',
        padding: '20px 24px',
        overflow: 'visible'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
          <div>
            <h1 style={{ fontSize: '1.6rem', fontWeight: 800, marginBottom: '4px', letterSpacing: '-0.02em' }}>
              Gestion Clientèle
            </h1>
            <p style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.8rem', maxWidth: '800px' }}>
              Fichier centralisé des revendeurs, calcul automatique du score de risque crédit et alertes de dépassement de plafond.
            </p>
          </div>

          {/* Nouvelle Vente interactive Action Button with Horizontal rollout Drawer */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', zIndex: 100 }}>
            {canAccessAllNodes && (
              <button
                onClick={openImportModal}
                className="btn btn-secondary"
                style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 16px', fontSize: '0.8rem', height: '38px' }}
              >
                <FiDownload style={{ transform: 'rotate(180deg)' }} />
                <span>Importer (Excel)</span>
              </button>
            )}
            {isActionMenuOpen && (
              <div
                className="animate-fade-in"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  backgroundColor: 'hsl(var(--bg-tertiary))',
                  border: '1px solid hsl(var(--border-color))',
                  padding: '4px 8px',
                  borderRadius: 'var(--radius-sm)',
                  boxShadow: 'var(--shadow-sm)'
                }}
              >
                <button
                  onClick={triggerCasualSale}
                  className="btn btn-secondary"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    padding: '6px 12px',
                    fontSize: '0.78rem',
                    whiteSpace: 'nowrap',
                    height: '34px',
                    borderColor: 'hsl(var(--color-info) / 0.3)',
                    backgroundColor: 'hsl(var(--color-info) / 0.05)',
                    color: 'hsl(var(--text-primary))'
                  }}
                >
                  <FiCreditCard style={{ color: 'hsl(var(--color-info))' }} />
                  <span>Vente occasionnelle</span>
                </button>
                <button
                  onClick={() => { setIsActionMenuOpen(false); openAddModal(); }}
                  className="btn btn-secondary"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    padding: '6px 12px',
                    fontSize: '0.78rem',
                    whiteSpace: 'nowrap',
                    height: '34px',
                    borderColor: 'hsl(var(--accent-color) / 0.3)',
                    backgroundColor: 'hsl(var(--accent-glow))',
                    color: 'hsl(var(--accent-color))'
                  }}
                >
                  <FiPlus />
                  <span>Nouveau client</span>
                </button>
              </div>
            )}

            <button
              onClick={() => setIsActionMenuOpen(!isActionMenuOpen)}
              className="btn btn-primary"
              style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 20px', fontSize: '0.85rem', height: '38px' }}
            >
              <FiShoppingBag />
              <span>Nouvelle vente</span>
              <FiChevronDown style={{ transform: isActionMenuOpen ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 0.2s ease' }} />
            </button>
          </div>
        </div>
      </div>
  );
};
