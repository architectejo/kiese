import React from 'react';
import { FiEye, FiShoppingBag } from 'react-icons/fi';
import { ClientItem, CLIENTS_PAGE_SIZE } from './clientItem';

interface ClientsTableProps {
  isLoading: boolean;
  loadError: string | null;
  clientsBackgroundLoading: boolean;
  clientsLoadedCount: number;
  clientsTotalCount: number | null;
  selectedType: string;
  selectedRisk: string;
  searchTerm: string;
  canAccessAllNodes: boolean;
  canReadSocial: boolean;
  visibleClients: ClientItem[];
  sortedClients: ClientItem[];
  clientsVisibleCount: number;
  setClientsVisibleCount: React.Dispatch<React.SetStateAction<number>>;
  selectedClientIds: Set<string>;
  toggleSelectClient: (id: string) => void;
  toggleSelectAllVisible: () => void;
  setHistoryClient: (c: { id: string; name: string } | null) => void;
  onStartSale: (client: ClientItem) => void;
  onOpenDetail: (client: ClientItem) => void;
}

/** Tableau des clients : états chargement / erreur / vide, pagination « Voir plus ». */
export const ClientsTable: React.FC<ClientsTableProps> = ({
  isLoading, loadError, clientsBackgroundLoading, clientsLoadedCount, clientsTotalCount, selectedType, selectedRisk,
  searchTerm, canAccessAllNodes, canReadSocial, visibleClients, sortedClients, clientsVisibleCount,
  setClientsVisibleCount, selectedClientIds, toggleSelectClient, toggleSelectAllVisible, setHistoryClient,
  onStartSale, onOpenDetail,
}) => {
  return (
      <div className="glass-card" style={{ padding: '12px 16px' }}>
        {isLoading && (
          <div style={{ textAlign: 'center', padding: '24px', color: 'hsl(var(--text-secondary))' }}>
            Chargement des clients...
          </div>
        )}
        {!isLoading && loadError && (
          <div style={{ textAlign: 'center', padding: '16px', color: 'hsl(var(--color-danger))', fontSize: '0.78rem' }}>
            {loadError}
          </div>
        )}
        {/* BUG-132 : indicateur discret pendant le chargement arrière-plan des pages suivantes
            (le tableau ci-dessous affiche déjà ce qui est arrivé, sans attendre). */}
        {!isLoading && clientsBackgroundLoading && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 10px', marginBottom: '8px',
            fontSize: '0.72rem', color: 'hsl(var(--text-secondary))',
            background: 'hsl(var(--accent-color) / 0.08)', borderRadius: '6px',
          }}>
            <span className="spinner" style={{
              width: '12px', height: '12px', border: '2px solid hsl(var(--accent-color) / 0.3)',
              borderTopColor: 'hsl(var(--accent-color))', borderRadius: '50%',
              animation: 'spin 0.8s linear infinite', flexShrink: 0,
            }} />
            Chargement du reste de la liste… {clientsLoadedCount}
            {clientsTotalCount !== null ? ` / ${clientsTotalCount}` : ''} clients chargés.
            {(selectedType !== 'All' || selectedRisk !== 'All') && (
              <span> Les filtres Type/Risque peuvent être incomplets tant que ce chargement n'est pas terminé.</span>
            )}
          </div>
        )}
        {!isLoading && !clientsBackgroundLoading && clientsTotalCount !== null && clientsLoadedCount === clientsTotalCount && clientsTotalCount > CLIENTS_PAGE_SIZE && (
          <div style={{ padding: '4px 10px', marginBottom: '8px', fontSize: '0.7rem', color: 'hsl(var(--color-success))' }}>
            Liste complète chargée ({clientsTotalCount} client(s)).
          </div>
        )}
        <div style={{ overflowX: 'auto' }}>
          <table className="premium-table">
            <thead>
              <tr style={{ fontSize: '0.68rem', textTransform: 'uppercase', letterSpacing: '0.03em' }}>
                {canAccessAllNodes && (
                  <th style={{ padding: '8px 10px', width: '32px' }}>
                    <input
                      type="checkbox"
                      checked={visibleClients.length > 0 && visibleClients.every(c => c._apiId && selectedClientIds.has(c._apiId))}
                      onChange={toggleSelectAllVisible}
                    />
                  </th>
                )}
                <th style={{ padding: '8px 10px' }}>ID</th>
                <th style={{ padding: '8px 10px' }}>Client</th>
                <th style={{ padding: '8px 10px' }}>BP</th>
                <th style={{ padding: '8px 10px' }}>Risque</th>
                <th style={{ padding: '8px 10px' }}>Statut</th>
                <th style={{ textAlign: 'center', padding: '8px 10px', width: '100px' }}>Actions</th>
              </tr>
            </thead>
            <tbody style={{ fontSize: '0.72rem' }}>
              {visibleClients.map((client) => {
                const isOverLimit = client.outstandingDebt > client.creditLimit;
                return (
                  <tr key={client.id} style={{ transition: 'background-color 0.2s ease' }}>
                    {canAccessAllNodes && (
                      <td style={{ padding: '8px 10px' }}>
                        <input
                          type="checkbox"
                          checked={!!client._apiId && selectedClientIds.has(client._apiId)}
                          onChange={() => client._apiId && toggleSelectClient(client._apiId)}
                        />
                      </td>
                    )}
                    <td style={{ fontWeight: 800, color: 'hsl(var(--accent-color))', padding: '8px 10px' }}>{client.id}</td>
                    <td style={{ padding: '8px 10px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <div style={{
                          width: '26px',
                          height: '26px',
                          borderRadius: '50%',
                          backgroundColor: client.avatarColor,
                          color: '#fff',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontWeight: 800,
                          fontSize: '0.7rem',
                          flexShrink: 0
                        }}>
                          {client.name.substring(0, 2).toUpperCase()}
                        </div>
                        <div>
                          <div style={{ fontWeight: 800, fontSize: '0.76rem' }}>
                            {canReadSocial && client._apiId ? (
                              <button type="button" title="Voir l'historique des achats et dépôts"
                                onClick={() => setHistoryClient({ id: client._apiId as string, name: client.name })}
                                style={{ background: 'none', border: 0, padding: 0, font: 'inherit', color: 'hsl(var(--accent-color))', cursor: 'pointer', textDecoration: 'underline', textAlign: 'left' }}>
                                {client.name}
                              </button>
                            ) : client.name}
                          </div>
                          <div style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))' }}>{client.businessName}</div>
                        </div>
                      </div>
                    </td>
                    <td style={{ padding: '8px 10px' }}>
                      <div style={{ display: 'flex', flexDirection: 'column' }}>
                        {client.outstandingDebt < 0 ? (
                          <>
                            <span style={{ fontWeight: 800, color: 'hsl(var(--color-success))', fontSize: '0.78rem' }}>
                              CRÉDIT : {Math.abs(client.outstandingDebt).toLocaleString('fr-FR')} FC
                            </span>
                            <span style={{ fontSize: '0.55rem', color: 'hsl(var(--color-success))', fontWeight: 700 }}>Trop-payé</span>
                          </>
                        ) : (
                          <>
                            <span style={{
                              fontWeight: 800,
                              color: isOverLimit ? 'hsl(var(--color-danger))' : 'hsl(var(--text-primary))',
                              fontSize: '0.78rem'
                            }}>
                              {client.outstandingDebt.toLocaleString('fr-FR')} FC
                            </span>
                            {isOverLimit && (
                              <span style={{ fontSize: '0.55rem', color: 'hsl(var(--color-danger))', fontWeight: 700 }}>
                                +{(client.outstandingDebt - client.creditLimit).toLocaleString('fr-FR')} FC
                              </span>
                            )}
                          </>
                        )}
                      </div>
                    </td>
                    <td style={{ padding: '8px 10px' }}>
                      <span className={`badge ${client.riskScore === 'High' ? 'badge-danger' :
                          client.riskScore === 'Medium' ? 'badge-warning' : 'badge-success'
                        }`} style={{ fontSize: '0.55rem', padding: '1px 3px' }}>
                        {client.riskScore === 'High' ? 'CRITIQUE' : client.riskScore === 'Medium' ? 'MOYEN' : 'MINIME'}
                      </span>
                    </td>
                    <td style={{ padding: '8px 10px' }}>
                      <span className={`badge ${client.active ? 'badge-success' : 'badge-danger'}`} style={{ padding: '1px 4px', fontSize: '0.55rem' }}>
                        {client.active ? 'ACTIF' : 'SUSPENDU'}
                      </span>
                    </td>
                    <td style={{ padding: '8px 10px' }}>
                      <div style={{ display: 'flex', justifyContent: 'center', gap: '4px' }}>
                        {/* Nouvelle action : Enregistrer un achat pour cet ancien client */}
                        <button
                          onClick={() => onStartSale(client)}
                          className="theme-picker-btn"
                          style={{
                            padding: '4px 5px',
                            color: 'hsl(var(--color-success))',
                            backgroundColor: 'hsl(var(--color-success) / 0.1)',
                            border: '1px solid hsl(var(--color-success) / 0.2)'
                          }}
                          title="Enregistrer un Achat / Vente"
                        >
                          <FiShoppingBag style={{ fontSize: '0.78rem' }} />
                        </button>

                        {/* Fiche détaillée */}
                        <button
                          onClick={() => onOpenDetail(client)}
                          className="theme-picker-btn"
                          style={{ padding: '4px 5px' }}
                          title="Voir la fiche détaillée"
                        >
                          <FiEye style={{ fontSize: '0.78rem' }} />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {!isLoading && sortedClients.length === 0 && (
          <div style={{ textAlign: 'center', padding: '24px', color: 'hsl(var(--text-secondary))', fontSize: '0.78rem' }}>
            {searchTerm || selectedType !== 'All' || selectedRisk !== 'All'
              ? 'Aucun client ne correspond à cette recherche/ces filtres.'
              : 'Aucun client enregistré pour le moment.'}
            {/* BUG-132 : filtres Type/Risque appliqués en mémoire sur les pages déjà reçues —
                tant que le reste de la liste charge encore, « aucun résultat » peut juste
                signifier « pas encore trouvé » plutôt qu'une absence réelle. */}
            {clientsBackgroundLoading && (selectedType !== 'All' || selectedRisk !== 'All') && (
              <div style={{ marginTop: '6px', fontWeight: 700 }}>
                Chargement du reste de la liste toujours en cours — ce résultat peut être incomplet.
              </div>
            )}
          </div>
        )}
        {!isLoading && sortedClients.length > 0 && (() => {
          // BUG-132 : le bouton reste visible tant qu'il reste des clients déjà chargés à
          // révéler OU que le chargement arrière-plan n'est pas terminé (dans ce dernier cas, un
          // clic ne révèle encore rien de neuf mais fait avancer `clientsVisibleCount` : la ligne
          // suivante apparaîtra seule, sans second clic, dès que la page suivante arrivera).
          const hasMoreLoaded = sortedClients.length > clientsVisibleCount;
          const showButton = hasMoreLoaded || clientsBackgroundLoading;
          const isWaiting = clientsBackgroundLoading && !hasMoreLoaded;
          return (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px', padding: '14px 0 4px' }}>
              <span style={{ fontSize: '0.7rem', color: 'hsl(var(--text-secondary))' }}>
                {visibleClients.length} sur {sortedClients.length} client(s) affiché(s)
                {clientsTotalCount !== null && clientsTotalCount > clientsLoadedCount
                  ? ` (${clientsTotalCount} au total, chargement en cours)`
                  : ''}
              </span>
              {showButton && (
                <button
                  onClick={() => setClientsVisibleCount(c => c + 20)}
                  className="btn btn-secondary"
                  disabled={isWaiting}
                  style={{ padding: '6px 16px', fontSize: '0.75rem', opacity: isWaiting ? 0.7 : 1 }}
                >
                  {isWaiting ? 'En attente de la page suivante…' : 'Voir plus'}
                </button>
              )}
            </div>
          );
        })()}
      </div>
  );
};
