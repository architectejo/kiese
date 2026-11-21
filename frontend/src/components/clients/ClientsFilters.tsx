import React from 'react';
import { FiSearch } from 'react-icons/fi';
import type { BakeryNode } from '@/api/services';

interface ClientsFiltersProps {
  searchTerm: string;
  setSearchTerm: (v: string) => void;
  canFilterByNode: boolean;
  clientNodeFilter: string;
  setClientNodeFilter: (v: string) => void;
  nodesList: BakeryNode[];
  selectedType: string;
  setSelectedType: (v: string) => void;
  selectedRisk: string;
  setSelectedRisk: (v: string) => void;
}

/** Recherche et filtres (boulangerie, type, statut de plafond) de la liste clients. */
export const ClientsFilters: React.FC<ClientsFiltersProps> = ({
  searchTerm, setSearchTerm, canFilterByNode, clientNodeFilter, setClientNodeFilter, nodesList,
  selectedType, setSelectedType, selectedRisk, setSelectedRisk,
}) => {
  return (
      <div className="glass-card" style={{ padding: '14px' }}>
        <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'center' }}>
          {/* Search bar */}
          <div style={{ flex: 2, minWidth: '240px', position: 'relative' }}>
            <FiSearch style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'hsl(var(--text-muted))' }} />
            <input
              type="text"
              placeholder="Rechercher par nom, commerce ou ID..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="form-input"
              style={{ paddingLeft: '36px', height: '36px', fontSize: '0.8rem' }}
            />
          </div>

          {/* Boulangerie filter */}
          {canFilterByNode && (
            <div style={{ flex: 1, minWidth: '170px' }}>
              <select
                value={clientNodeFilter}
                onChange={(e) => setClientNodeFilter(e.target.value)}
                className="form-input"
                style={{ cursor: 'pointer', height: '36px', fontSize: '0.8rem' }}
              >
                <option value="">Toutes les boulangeries</option>
                {nodesList.map(n => (
                  <option key={n.id} value={n.id}>{n.code} — {n.name}</option>
                ))}
              </select>
            </div>
          )}

          {/* Type filter */}
          <div style={{ flex: 1, minWidth: '150px' }}>
            <select
              value={selectedType}
              onChange={(e) => setSelectedType(e.target.value)}
              className="form-input"
              style={{ cursor: 'pointer', height: '36px', fontSize: '0.8rem' }}
            >
              <option value="All">Tous les types</option>
              <option value="Grossiste">Grossistes</option>
              <option value="Détaillant">Détaillants</option>
              <option value="Revendeur">Revendeurs</option>
            </select>
          </div>

          {/* Plafond limit status filter */}
          <div style={{ flex: 1, minWidth: '150px' }}>
            <select
              value={selectedRisk}
              onChange={(e) => setSelectedRisk(e.target.value)}
              className="form-input"
              style={{ cursor: 'pointer', height: '36px', fontSize: '0.8rem' }}
            >
              <option value="All">Tous les statuts de limite</option>
              <option value="Exceeded">Limite dépassée ⚠️</option>
              <option value="Normal">En règle ✅</option>
            </select>
          </div>
        </div>
      </div>
  );
};
