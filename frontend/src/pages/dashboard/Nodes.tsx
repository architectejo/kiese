import React, { useEffect, useState } from 'react';
import axios from 'axios';
import {
  FiMapPin, FiPlus, FiEdit2, FiTrash2, FiRefreshCw,
  FiCheckCircle, FiXCircle, FiClock, FiShield
} from 'react-icons/fi';
import { apiClient } from '@/api/client';
import { Modal } from '@/components/shared/Modal';

export interface BakeryNode {
  id: string;
  code: string;
  name: string;
  address: string;
  sac_value_fc: string | null;
  is_active: boolean;
  last_sync: string | null;
  created_at: string;
}

interface NodeAgent {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  full_name: string;
  email: string;
  role: string;
  role_display: string;
  is_active: boolean;
}

export const Nodes: React.FC = () => {
  const [nodes, setNodes] = useState<BakeryNode[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  
  // Modal state
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingNode, setEditingNode] = useState<BakeryNode | null>(null);
  const [isSavingNode, setIsSavingNode] = useState(false);

  // Agents modal state
  const [agentsModalNode, setAgentsModalNode] = useState<BakeryNode | null>(null);
  const [agents, setAgents] = useState<NodeAgent[]>([]);
  const [isLoadingAgents, setIsLoadingAgents] = useState(false);
  
  // Form state
  const [formData, setFormData] = useState({
    code: '',
    name: '',
    address: '',
    sac_value_fc: '',
    is_active: true
  });
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});

  const fetchNodes = async () => {
    setIsLoading(true);
    try {
      const res = await apiClient.get('/api/core/nodes/');
      const nodesData = Array.isArray(res.data) ? res.data : (res.data.results || []);
      setNodes(nodesData);
    } catch (error) {
      console.error('Failed to fetch nodes', error);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchNodes();
  }, []);

  const handleOpenModal = (node?: BakeryNode) => {
    if (node) {
      setEditingNode(node);
      setFormData({
        code: node.code,
        name: node.name,
        address: node.address || '',
        sac_value_fc: node.sac_value_fc ?? '',
        is_active: node.is_active
      });
    } else {
      setEditingNode(null);
      setFormData({
        code: '',
        name: '',
        address: '',
        sac_value_fc: '',
        is_active: true
      });
    }
    setFormErrors({});
    setIsModalOpen(true);
  };

  const handleCloseModal = () => {
    setIsModalOpen(false);
    setEditingNode(null);
    setFormErrors({});
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isSavingNode) return;
    if (formData.code.trim().length > 5) {
      setFormErrors(p => ({ ...p, code: 'Le code ne doit pas dépasser 5 caractères (ex: K1, B2).' }));
      return;
    }
    const payload = {
      ...formData,
      sac_value_fc: formData.sac_value_fc !== '' ? formData.sac_value_fc : null,
    };
    setIsSavingNode(true);
    try {
      if (editingNode) {
        await apiClient.put(`/api/core/nodes/${editingNode.id}/`, payload);
      } else {
        await apiClient.post('/api/core/nodes/', payload);
      }
      handleCloseModal();
      fetchNodes();
    } catch (error: unknown) {
      console.error('Error saving node', error);
      const data = axios.isAxiosError(error) ? error.response?.data : undefined;
      if (data && typeof data === 'object') {
        const parsed: Record<string, string> = {};
        for (const [key, val] of Object.entries(data)) {
          parsed[key] = Array.isArray(val) ? (val as string[]).join(' ') : String(val);
        }
        setFormErrors(parsed);
      } else {
        setFormErrors({ non_field_errors: 'Une erreur est survenue lors de l\'enregistrement.' });
      }
    } finally {
      setIsSavingNode(false);
    }
  };

  const handleViewAgents = async (node: BakeryNode) => {
    setAgentsModalNode(node);
    setIsLoadingAgents(true);
    try {
      const res = await apiClient.get('/api/core/users/', { params: { node: node.id } });
      const data = Array.isArray(res.data) ? res.data : (res.data.results || []);
      setAgents(data);
    } catch (error) {
      console.error('Failed to fetch node agents', error);
      setAgents([]);
    } finally {
      setIsLoadingAgents(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm("Voulez-vous vraiment supprimer cette succursale ? Cette action est irréversible et pourrait affecter les données qui y sont liées.")) {
      return;
    }
    try {
      await apiClient.delete(`/api/core/nodes/${id}/`);
      fetchNodes();
    } catch (error) {
      console.error('Error deleting node', error);
      alert('Impossible de supprimer cette succursale. Elle contient peut-être des données liées (utilisateurs, transactions). Vous devriez plutôt la désactiver.');
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', fontSize: '0.85rem' }}>
      
      {/* Header Banner */}
      <div className="glass-card animate-fade-in" style={{
        background: 'linear-gradient(135deg, hsl(var(--bg-tertiary)) 0%, hsl(var(--bg-secondary)) 100%)',
        borderLeft: '4px solid hsl(var(--accent-color))',
        padding: '16px 20px'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h1 style={{ fontSize: '1.4rem', fontWeight: 800, marginBottom: '2px' }}>
              Gestion des Succursales (Nœuds)
            </h1>
            <p style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.75rem' }}>
              Interface réservée à la Direction Générale pour l'ajout et l'administration des points de production et de vente.
            </p>
          </div>
          <FiMapPin style={{ fontSize: '2rem', color: 'hsl(var(--accent-color))', opacity: 0.8 }} />
        </div>
      </div>

      {/* Main Content */}
      <div className="glass-card" style={{ padding: '16px 20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h2 style={{ fontSize: '0.95rem', fontWeight: 800, color: 'hsl(var(--text-primary))' }}>
            Liste des Boulangeries (Réseau KIESE)
          </h2>
          <div style={{ display: 'flex', gap: '10px' }}>
            <button onClick={fetchNodes} className="btn btn-secondary" style={{ padding: '6px 10px', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.78rem' }}>
              <FiRefreshCw className={isLoading ? 'animate-spin' : ''} />
              <span>Actualiser</span>
            </button>
            <button onClick={() => handleOpenModal()} className="btn btn-primary" style={{ padding: '6px 12px', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.78rem' }}>
              <FiPlus />
              <span>Nouvelle Succursale</span>
            </button>
          </div>
        </div>

        <div style={{ overflowX: 'auto' }}>
          <table className="premium-table">
            <thead>
              <tr style={{ fontSize: '0.68rem', textTransform: 'uppercase' }}>
                <th style={{ padding: '8px 10px' }}>Code</th>
                <th style={{ padding: '8px 10px' }}>Nom</th>
                <th style={{ padding: '8px 10px' }}>Adresse Locale</th>
                <th style={{ padding: '8px 10px' }}>Dernière Synchronisation</th>
                <th style={{ padding: '8px 10px' }}>Statut</th>
                <th style={{ padding: '8px 10px', textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody style={{ fontSize: '0.75rem' }}>
              {isLoading ? (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', padding: '20px', color: 'hsl(var(--text-secondary))' }}>
                    Chargement des succursales...
                  </td>
                </tr>
              ) : nodes.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', padding: '20px', color: 'hsl(var(--text-secondary))' }}>
                    Aucune succursale trouvée. Veuillez en ajouter une.
                  </td>
                </tr>
              ) : (
                nodes.map(node => (
                  <tr key={node.id} onClick={() => handleViewAgents(node)} style={{ cursor: 'pointer' }} title="Voir les agents de cette succursale">
                    <td style={{ padding: '8px 10px', fontWeight: 800, color: 'hsl(var(--accent-color))' }}>
                      {node.code}
                    </td>
                    <td style={{ padding: '8px 10px', fontWeight: 700, color: 'hsl(var(--text-primary))' }}>
                      {node.name}
                    </td>
                    <td style={{ padding: '8px 10px', color: 'hsl(var(--text-secondary))' }}>
                      {node.address || 'Non spécifiée'}
                    </td>
                    <td style={{ padding: '8px 10px', color: 'hsl(var(--text-muted))', fontSize: '0.7rem' }}>
                      {node.last_sync ? (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <FiClock />
                          <span>{new Date(node.last_sync).toLocaleString('fr-FR')}</span>
                        </div>
                      ) : (
                        <span style={{ color: 'hsl(var(--color-warning))' }}>Jamais synchronisée</span>
                      )}
                    </td>
                    <td style={{ padding: '8px 10px' }}>
                      {node.is_active ? (
                        <span className="badge badge-success" style={{ fontSize: '0.6rem', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                          <FiCheckCircle /> Actif
                        </span>
                      ) : (
                        <span className="badge badge-danger" style={{ fontSize: '0.6rem', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                          <FiXCircle /> Inactif
                        </span>
                      )}
                    </td>
                    <td style={{ padding: '8px 10px', textAlign: 'right' }} onClick={(e) => e.stopPropagation()}>
                      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '6px' }}>
                        <button
                          onClick={() => handleOpenModal(node)}
                          className="theme-picker-btn"
                          style={{ padding: '4px 6px', color: 'hsl(var(--color-info))', borderRadius: '4px' }}
                          title="Modifier la succursale"
                        >
                          <FiEdit2 />
                        </button>
                        <button
                          onClick={() => handleDelete(node.id)}
                          className="theme-picker-btn"
                          style={{ padding: '4px 6px', color: 'hsl(var(--color-danger))', borderRadius: '4px' }}
                          title="Supprimer la succursale"
                        >
                          <FiTrash2 />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Add/Edit Modal */}
      <Modal
        isOpen={isModalOpen}
        onClose={handleCloseModal}
        title={editingNode ? 'Modifier la Succursale' : 'Ajouter une Succursale'}
        subtitle="Veuillez saisir les informations de la boulangerie (ou nœud)."
        maxWidth="500px"
      >
            <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Code (ex: K1) *</label>
                  <input
                    type="text"
                    required
                    maxLength={5}
                    value={formData.code}
                    onChange={(e) => {
                      const nextCode = e.target.value.toUpperCase().slice(0, 5);
                      setFormData({...formData, code: nextCode});
                      setFormErrors(p => ({...p, code: ''}));
                    }}
                    className="form-input"
                    style={{ fontSize: '0.8rem', height: '36px', padding: '0 10px', borderColor: formErrors.code ? 'hsl(var(--color-danger))' : '' }}
                    placeholder="K1, B2..."
                  />
                  {formErrors.code && <span style={{ fontSize: '0.68rem', color: 'hsl(var(--color-danger))', marginTop: '3px', display: 'block' }}>{formErrors.code}</span>}
                  {!formErrors.code && <span style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))', marginTop: '3px', display: 'block' }}>5 caractères maximum (ex : K1, B2).</span>}
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Nom / Emplacement *</label>
                  <input
                    type="text"
                    required
                    value={formData.name}
                    onChange={(e) => { setFormData({...formData, name: e.target.value}); setFormErrors(p => ({...p, name: ''})); }}
                    className="form-input"
                    style={{ fontSize: '0.8rem', height: '36px', padding: '0 10px', borderColor: formErrors.name ? 'hsl(var(--color-danger))' : '' }}
                    placeholder="Boulangerie Gombe..."
                  />
                  {formErrors.name && <span style={{ fontSize: '0.68rem', color: 'hsl(var(--color-danger))', marginTop: '3px', display: 'block' }}>{formErrors.name}</span>}
                </div>
              </div>
              
              <div>
                <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Adresse Physique</label>
                <textarea 
                  value={formData.address} 
                  onChange={(e) => setFormData({...formData, address: e.target.value})}
                  className="form-input" 
                  style={{ fontSize: '0.8rem', minHeight: '60px', padding: '8px 10px', resize: 'vertical' }}
                  placeholder="Adresse complète du bâtiment..."
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Valeur Théorique par Sac de Farine (FC)</label>
                <input
                  type="number"
                  min="0"
                  value={formData.sac_value_fc}
                  onChange={(e) => setFormData({...formData, sac_value_fc: e.target.value})}
                  className="form-input"
                  style={{ fontSize: '0.8rem', height: '36px', padding: '0 10px' }}
                  placeholder="Ex: 200000"
                />
                <span style={{ fontSize: '0.68rem', color: 'hsl(var(--text-muted))', marginTop: '4px', display: 'block' }}>
                  Laisser vide pour utiliser la valeur globale de la Configuration.
                </span>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '4px' }}>
                <input
                  type="checkbox"
                  id="isActiveToggle"
                  checked={formData.is_active}
                  onChange={(e) => setFormData({...formData, is_active: e.target.checked})}
                  style={{ width: '16px', height: '16px', accentColor: 'hsl(var(--accent-color))' }}
                />
                <label htmlFor="isActiveToggle" style={{ fontSize: '0.78rem', fontWeight: 700, color: 'hsl(var(--text-primary))', cursor: 'pointer' }}>
                  Succursale Active (Autoriser les synchronisations)
                </label>
              </div>
              
              {formErrors.non_field_errors && (
                <div style={{ fontSize: '0.75rem', color: 'hsl(var(--color-danger))', padding: '8px 10px', background: 'hsl(var(--color-danger) / 0.08)', borderRadius: '6px', borderLeft: '3px solid hsl(var(--color-danger))' }}>
                  {formErrors.non_field_errors}
                </div>
              )}
              <div style={{ display: 'flex', gap: '10px', marginTop: '12px' }}>
                <button type="button" onClick={handleCloseModal} className="btn btn-secondary" style={{ flex: 1, padding: '8px 12px', fontSize: '0.82rem' }}>
                  Annuler
                </button>
                <button type="submit" disabled={isSavingNode} className="btn btn-primary" style={{ flex: 1, padding: '8px 12px', fontSize: '0.82rem', opacity: isSavingNode ? 0.6 : 1 }}>
                  {isSavingNode ? 'Enregistrement...' : editingNode ? 'Enregistrer les modifications' : 'Créer la succursale'}
                </button>
              </div>
            </form>
      </Modal>

      {/* Agents Modal */}
      {agentsModalNode && (
        <Modal
          isOpen={true}
          onClose={() => setAgentsModalNode(null)}
          title={`Agents — ${agentsModalNode.code} ${agentsModalNode.name}`}
          subtitle="Liste des utilisateurs assignés à cette succursale et leurs rôles."
          maxWidth="480px"
        >
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {isLoadingAgents ? (
                <p style={{ textAlign: 'center', color: 'hsl(var(--text-secondary))', padding: '16px 0' }}>Chargement des agents...</p>
              ) : agents.length === 0 ? (
                <p style={{ textAlign: 'center', color: 'hsl(var(--text-muted))', padding: '16px 0' }}>Aucun agent assigné à cette succursale.</p>
              ) : agents.map(agent => (
                <div key={agent.id} style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '8px 10px', borderRadius: 'var(--radius-sm)',
                  backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <div style={{
                      width: '28px', height: '28px', borderRadius: '50%',
                      backgroundColor: 'hsl(var(--accent-color) / 0.15)', color: 'hsl(var(--accent-color))',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontWeight: 800, fontSize: '0.7rem', flexShrink: 0
                    }}>
                      {(agent.full_name || agent.username).substring(0, 2).toUpperCase()}
                    </div>
                    <div>
                      <div style={{ fontWeight: 700, fontSize: '0.78rem' }}>{agent.full_name || agent.username}</div>
                      <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-secondary))' }}>{agent.email || agent.username}</div>
                    </div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span className="badge badge-info" style={{ fontSize: '0.6rem', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                      <FiShield /> {agent.role_display || agent.role}
                    </span>
                    {!agent.is_active && (
                      <span className="badge badge-danger" style={{ fontSize: '0.58rem' }}>Inactif</span>
                    )}
                  </div>
                </div>
              ))}
            </div>

            <button onClick={() => setAgentsModalNode(null)} className="btn btn-secondary" style={{ marginTop: '16px', padding: '8px 12px', fontSize: '0.8rem' }}>
              Fermer
            </button>
        </Modal>
      )}
    </div>
  );
};
