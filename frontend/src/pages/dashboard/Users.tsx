import React, { useEffect, useState } from 'react';
import { 
  FiUserCheck, FiPlus, FiEdit2, FiTrash2, FiRefreshCw, 
  FiKey, FiShield, FiCheckCircle, FiXCircle
} from 'react-icons/fi';
import { apiClient } from '@/api/client';
import { BakeryNode } from './Nodes';
import { Modal } from '@/components/shared/Modal';

interface User {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  email: string;
  role: string;
  role_display: string;
  team: string;
  team_display: string;
  node: string | null;
  node_display: string | null;
  phone: string;
  is_active: boolean;
}

export const Users: React.FC = () => {
  const [users, setUsers] = useState<User[]>([]);
  const [nodes, setNodes] = useState<BakeryNode[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  
  // Modals state
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isSavingUser, setIsSavingUser] = useState(false);
  const [isPasswordModalOpen, setIsPasswordModalOpen] = useState(false);
  
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [passwordResetUser, setPasswordResetUser] = useState<User | null>(null);
  
  // Form state
  const [formData, setFormData] = useState({
    username: '',
    first_name: '',
    last_name: '',
    email: '',
    phone: '',
    role: 'GERANT',
    team: 'A',
    node: '',
    password: '' // Only for creation
  });

  const fetchData = async () => {
    setIsLoading(true);
    try {
      const [usersRes, nodesRes] = await Promise.all([
        apiClient.get('/api/core/users/'),
        apiClient.get('/api/core/nodes/')
      ]);
      const usersData = Array.isArray(usersRes.data) ? usersRes.data : (usersRes.data.results || []);
      const nodesData = Array.isArray(nodesRes.data) ? nodesRes.data : (nodesRes.data.results || []);
      setUsers(usersData);
      setNodes(nodesData);
    } catch (error) {
      console.error('Failed to fetch data', error);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleOpenModal = (user?: User) => {
    if (user) {
      setEditingUser(user);
      setFormData({
        username: user.username,
        first_name: user.first_name || '',
        last_name: user.last_name || '',
        email: user.email || '',
        phone: user.phone || '',
        role: user.role || 'GERANT',
        team: user.team || 'A',
        node: user.node || '',
        password: ''
      });
    } else {
      setEditingUser(null);
      setFormData({
        username: '',
        first_name: '',
        last_name: '',
        email: '',
        phone: '',
        role: 'GERANT',
        team: 'A',
        node: '',
        password: ''
      });
    }
    setIsModalOpen(true);
  };

  const handleCloseModal = () => {
    setIsModalOpen(false);
    setEditingUser(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isSavingUser) return;
    setIsSavingUser(true);
    try {
      const payload: Record<string, any> = { ...formData };
      if (!payload.node) delete payload.node; // Don't send empty node if not selected

      if (editingUser) {
        // Remove password from payload when editing
        delete payload.password;
        await apiClient.put(`/api/core/users/${editingUser.id}/`, payload);
      } else {
        await apiClient.post('/api/core/users/', payload);
      }
      handleCloseModal();
      fetchData();
    } catch (error: any) {
      console.error('Error saving user', error);
      alert('Erreur lors de l\'enregistrement. Veuillez vérifier les données (le nom d\'utilisateur doit être unique).');
    } finally {
      setIsSavingUser(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm("Voulez-vous vraiment désactiver ou supprimer cet utilisateur ?")) {
      return;
    }
    try {
      await apiClient.delete(`/api/core/users/${id}/`);
      fetchData();
    } catch (error) {
      console.error('Error deleting user', error);
      alert('Impossible de supprimer cet utilisateur.');
    }
  };

  const handleOpenPasswordModal = (user: User) => {
    setPasswordResetUser(user);
    setIsPasswordModalOpen(true);
  };

  const handleResetPassword = async () => {
    if (!passwordResetUser) return;
    try {
      await apiClient.post(`/api/core/users/${passwordResetUser.id}/reset_password/`, {});
      setIsPasswordModalOpen(false);
      alert(`Mot de passe réinitialisé — nouveau mot de passe : ${passwordResetUser.username}`);
      setPasswordResetUser(null);
    } catch (error) {
      console.error('Error resetting password', error);
      alert("Erreur lors de la réinitialisation du mot de passe.");
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
              Gestion du Personnel & Comptes
            </h1>
            <p style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.75rem' }}>
              Administration centrale des accès, rôles et équipes des employés sur l'ensemble du réseau KIESE.
            </p>
          </div>
          <FiUserCheck style={{ fontSize: '2rem', color: 'hsl(var(--accent-color))', opacity: 0.8 }} />
        </div>
      </div>

      {/* Main Content */}
      <div className="glass-card" style={{ padding: '16px 20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h2 style={{ fontSize: '0.95rem', fontWeight: 800, color: 'hsl(var(--text-primary))' }}>
            Annuaire des Utilisateurs
          </h2>
          <div style={{ display: 'flex', gap: '10px' }}>
            <button onClick={fetchData} className="btn btn-secondary" style={{ padding: '6px 10px', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.78rem' }}>
              <FiRefreshCw className={isLoading ? 'animate-spin' : ''} />
              <span>Actualiser</span>
            </button>
            <button onClick={() => handleOpenModal()} className="btn btn-primary" style={{ padding: '6px 12px', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.78rem' }}>
              <FiPlus />
              <span>Nouvel Employé</span>
            </button>
          </div>
        </div>

        <div style={{ overflowX: 'auto' }}>
          <table className="premium-table">
            <thead>
              <tr style={{ fontSize: '0.68rem', textTransform: 'uppercase' }}>
                <th style={{ padding: '8px 10px' }}>Identifiant</th>
                <th style={{ padding: '8px 10px' }}>Nom Complet</th>
                <th style={{ padding: '8px 10px' }}>Rôle</th>
                <th style={{ padding: '8px 10px' }}>Succursale / Équipe</th>
                <th style={{ padding: '8px 10px' }}>Statut</th>
                <th style={{ padding: '8px 10px', textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody style={{ fontSize: '0.75rem' }}>
              {isLoading ? (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', padding: '20px', color: 'hsl(var(--text-secondary))' }}>
                    Chargement des utilisateurs...
                  </td>
                </tr>
              ) : users.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', padding: '20px', color: 'hsl(var(--text-secondary))' }}>
                    Aucun utilisateur trouvé.
                  </td>
                </tr>
              ) : (
                users.map(u => (
                  <tr key={u.id}>
                    <td style={{ padding: '8px 10px', fontWeight: 800, color: 'hsl(var(--accent-color))' }}>
                      {u.username}
                    </td>
                    <td style={{ padding: '8px 10px', fontWeight: 700, color: 'hsl(var(--text-primary))' }}>
                      {u.first_name} {u.last_name}
                      {u.phone && <div style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))', fontWeight: 'normal' }}>📞 {u.phone}</div>}
                    </td>
                    <td style={{ padding: '8px 10px' }}>
                      <span className="badge" style={{ backgroundColor: 'hsl(var(--bg-tertiary))', color: 'hsl(var(--text-primary))', border: '1px solid hsl(var(--border-color))' }}>
                        {u.role_display || u.role}
                      </span>
                    </td>
                    <td style={{ padding: '8px 10px' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                        <span style={{ fontWeight: 600 }}>{u.node_display || 'Direction Centrale'}</span>
                        <span style={{ fontSize: '0.65rem', color: 'hsl(var(--text-muted))' }}>Équipe : {u.team_display || u.team}</span>
                      </div>
                    </td>
                    <td style={{ padding: '8px 10px' }}>
                      {u.is_active ? (
                        <span className="badge badge-success" style={{ fontSize: '0.6rem', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                          <FiCheckCircle /> Actif
                        </span>
                      ) : (
                        <span className="badge badge-danger" style={{ fontSize: '0.6rem', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                          <FiXCircle /> Suspendu
                        </span>
                      )}
                    </td>
                    <td style={{ padding: '8px 10px', textAlign: 'right' }}>
                      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '6px' }}>
                        <button 
                          onClick={() => handleOpenPasswordModal(u)}
                          className="theme-picker-btn" 
                          style={{ padding: '4px 6px', color: 'hsl(var(--color-warning))', borderRadius: '4px' }}
                          title="Réinitialiser le mot de passe"
                        >
                          <FiKey />
                        </button>
                        <button 
                          onClick={() => handleOpenModal(u)}
                          className="theme-picker-btn" 
                          style={{ padding: '4px 6px', color: 'hsl(var(--color-info))', borderRadius: '4px' }}
                          title="Modifier le compte"
                        >
                          <FiEdit2 />
                        </button>
                        <button 
                          onClick={() => handleDelete(u.id)}
                          className="theme-picker-btn" 
                          style={{ padding: '4px 6px', color: 'hsl(var(--color-danger))', borderRadius: '4px' }}
                          title="Supprimer le compte"
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
        title={editingUser ? 'Modifier le Profil Utilisateur' : 'Créer un Nouvel Employé'}
        subtitle="Remplissez les informations de base et configurez les droits d'accès."
        maxWidth="600px"
      >
            <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Nom d'utilisateur (Login) *</label>
                  <input 
                    type="text" required value={formData.username} 
                    onChange={(e) => setFormData({...formData, username: e.target.value.toLowerCase()})}
                    className="form-input" style={{ fontSize: '0.8rem', height: '36px', padding: '0 10px' }}
                  />
                </div>
                {!editingUser && (
                  <div>
                    <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Mot de passe *</label>
                    <input 
                      type="password" required minLength={6} value={formData.password} 
                      onChange={(e) => setFormData({...formData, password: e.target.value})}
                      className="form-input" style={{ fontSize: '0.8rem', height: '36px', padding: '0 10px' }}
                    />
                  </div>
                )}
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Prénom</label>
                  <input 
                    type="text" value={formData.first_name} 
                    onChange={(e) => setFormData({...formData, first_name: e.target.value})}
                    className="form-input" style={{ fontSize: '0.8rem', height: '36px', padding: '0 10px' }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Nom de famille</label>
                  <input 
                    type="text" value={formData.last_name} 
                    onChange={(e) => setFormData({...formData, last_name: e.target.value})}
                    className="form-input" style={{ fontSize: '0.8rem', height: '36px', padding: '0 10px' }}
                  />
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Téléphone</label>
                  <input 
                    type="text" value={formData.phone} 
                    onChange={(e) => setFormData({...formData, phone: e.target.value})}
                    className="form-input" style={{ fontSize: '0.8rem', height: '36px', padding: '0 10px' }}
                    placeholder="+243..."
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Email</label>
                  <input 
                    type="email" value={formData.email} 
                    onChange={(e) => setFormData({...formData, email: e.target.value})}
                    className="form-input" style={{ fontSize: '0.8rem', height: '36px', padding: '0 10px' }}
                  />
                </div>
              </div>

              <div style={{ backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', borderRadius: '8px', padding: '16px', marginTop: '8px' }}>
                <h4 style={{ fontSize: '0.8rem', fontWeight: 800, marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <FiShield color="hsl(var(--accent-color))" /> Autorisations & Affectation
                </h4>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Rôle Système</label>
                    <select 
                      value={formData.role} 
                      onChange={(e) => setFormData({...formData, role: e.target.value})}
                      className="form-input" style={{ fontSize: '0.8rem', height: '36px' }}
                    >
                      <option value="ADMIN">Administrateur</option>
                      <option value="DIRECTION">Direction / Gérant Principal</option>
                      <option value="COMPTABLE">Comptable / Caisse Centrale</option>
                      <option value="GERANT">Gérant de Succursale</option>
                      <option value="FACTURIER">Facturier / Caisse POS</option>
                      <option value="BOULANGER">Chef Boulanger / Magasinier</option>
                      <option value="LIVREUR">Livreur / Distributeur</option>
                    </select>
                  </div>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Équipe (Rotation)</label>
                    <select 
                      value={formData.team} 
                      onChange={(e) => setFormData({...formData, team: e.target.value})}
                      className="form-input" style={{ fontSize: '0.8rem', height: '36px' }}
                    >
                      <option value="A">Équipe A</option>
                      <option value="B">Équipe B</option>
                    </select>
                  </div>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Succursale Affectée</label>
                    <select 
                      value={formData.node || ''} 
                      onChange={(e) => setFormData({...formData, node: e.target.value})}
                      className="form-input" style={{ fontSize: '0.8rem', height: '36px' }}
                    >
                      <option value="">(Direction Centrale - Siège)</option>
                      {nodes.map(n => (
                        <option key={n.id} value={n.id}>{n.code} - {n.name}</option>
                      ))}
                    </select>
                  </div>
                </div>
              </div>
              
              <div style={{ display: 'flex', gap: '10px', marginTop: '12px' }}>
                <button type="button" onClick={handleCloseModal} className="btn btn-secondary" style={{ flex: 1, padding: '8px 12px', fontSize: '0.82rem' }}>
                  Annuler
                </button>
                <button type="submit" disabled={isSavingUser} className="btn btn-primary" style={{ flex: 1, padding: '8px 12px', fontSize: '0.82rem', opacity: isSavingUser ? 0.6 : 1 }}>
                  {isSavingUser ? 'Enregistrement...' : editingUser ? 'Mettre à jour le profil' : 'Créer l\'accès'}
                </button>
              </div>
            </form>
      </Modal>

      {/* Reset Password Modal */}
      {passwordResetUser && (
        <Modal
          isOpen={isPasswordModalOpen}
          onClose={() => setIsPasswordModalOpen(false)}
          maxWidth="400px"
        >
            <h3 style={{ fontSize: '1.2rem', fontWeight: 800, marginBottom: '6px', color: 'hsl(var(--color-warning))', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <FiKey /> Réinitialiser le Mot de Passe
            </h3>
            <p style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.75rem', marginBottom: '18px' }}>
              Le mot de passe de <strong>@{passwordResetUser.username}</strong> sera réinitialisé et redeviendra identique à son identifiant (<strong>{passwordResetUser.username}</strong>).
            </p>

            <div style={{ display: 'flex', gap: '10px', marginTop: '6px' }}>
              <button type="button" onClick={() => setIsPasswordModalOpen(false)} className="btn btn-secondary" style={{ flex: 1, padding: '8px 12px', fontSize: '0.82rem' }}>
                Annuler
              </button>
              <button type="button" onClick={handleResetPassword} className="btn btn-primary" style={{ flex: 1, padding: '8px 12px', fontSize: '0.82rem', backgroundColor: 'hsl(var(--color-warning))', color: '#000', border: 'none' }}>
                Confirmer la réinitialisation
              </button>
            </div>
        </Modal>
      )}

    </div>
  );
};
