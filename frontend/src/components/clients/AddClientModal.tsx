import React from 'react';
import { Modal } from '@/components/shared/Modal';
import type { BakeryNode } from '@/api/services';
import type { NewClientType } from './clientItem';

interface AddClientModalProps {
  isAddModalOpen: boolean;
  closeAddClientModal: () => void;
  handleAddClient: (e: React.FormEvent) => void | Promise<void>;
  needsNodeSelector: boolean;
  nodesList: BakeryNode[];
  selectedNode: string;
  setSelectedNode: (v: string) => void;
  newName: string;
  setNewName: (v: string) => void;
  newBusiness: string;
  setNewBusiness: (v: string) => void;
  newType: NewClientType;
  setNewType: (v: NewClientType) => void;
  newCreditLimit: number;
  setNewCreditLimit: (v: number) => void;
  newCommissionRate: number;
  setNewCommissionRate: (v: number) => void;
  newCotisationSociale: string;
  setNewCotisationSociale: (v: string) => void;
  newPhone: string;
  setNewPhone: (v: string) => void;
  newAddress: string;
  setNewAddress: (v: string) => void;
  newPhoto: File | null;
  setNewPhoto: (f: File | null) => void;
  newPhotoPreview: string | null;
  setNewPhotoPreview: (v: string | null) => void;
  addError: string | null;
  isAddingClient: boolean;
}

/** Formulaire de création d'une fiche client. */
export const AddClientModal: React.FC<AddClientModalProps> = ({
  isAddModalOpen, closeAddClientModal, handleAddClient, needsNodeSelector, nodesList, selectedNode, setSelectedNode,
  newName, setNewName, newBusiness, setNewBusiness, newType, setNewType, newCreditLimit, setNewCreditLimit,
  newCommissionRate, setNewCommissionRate, newCotisationSociale, setNewCotisationSociale,
  newPhone, setNewPhone, newAddress, setNewAddress, newPhoto, setNewPhoto, newPhotoPreview, setNewPhotoPreview,
  addError, isAddingClient,
}) => {
  return (
      <Modal
        isOpen={isAddModalOpen}
        onClose={closeAddClientModal}
        title="Créer une Fiche Client"
        maxWidth="500px"
      >
            <form onSubmit={handleAddClient} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              {needsNodeSelector && (
                <div>
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--accent-color))', marginBottom: '6px', textTransform: 'uppercase' }}>Boulangerie de Rattachement *</label>
                  <select
                    value={selectedNode}
                    onChange={e => setSelectedNode(e.target.value)}
                    className="form-input"
                    style={{ height: '36px', fontSize: '0.8rem' }}
                  >
                    <option value="">— Sélectionner une boulangerie —</option>
                    {nodesList.map(n => (
                      <option key={n.id} value={n.id}>{n.code} — {n.name}</option>
                    ))}
                  </select>
                </div>
              )}
              <div>
                <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '6px', textTransform: 'uppercase' }}>Nom Complet de l'Abonné *</label>
                <input
                  type="text"
                  required
                  placeholder="Ex: Dieudonné Kabeya"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  className="form-input"
                  style={{ height: '36px', fontSize: '0.8rem', padding: '0 12px' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '6px', textTransform: 'uppercase' }}>Nom du Commerce / Maison</label>
                <input
                  type="text"
                  placeholder="Ex: Boulangerie Kabeya"
                  value={newBusiness}
                  onChange={(e) => setNewBusiness(e.target.value)}
                  className="form-input"
                  style={{ height: '36px', fontSize: '0.8rem', padding: '0 12px' }}
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '6px', textTransform: 'uppercase' }}>Type de Client</label>
                  <select
                    value={newType}
                    onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setNewType(e.target.value as NewClientType)}
                    className="form-input"
                    style={{ height: '36px', fontSize: '0.8rem' }}
                  >
                    <option value="Détaillant">Détaillant</option>
                    <option value="Grossiste">Grossiste</option>
                    <option value="Revendeur">Revendeur</option>
                  </select>
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '6px', textTransform: 'uppercase' }}>Plafond Crédit (FC)</label>
                  <input
                    type="number"
                    value={newCreditLimit}
                    onChange={(e) => setNewCreditLimit(Number(e.target.value))}
                    className="form-input"
                    style={{ height: '36px', fontSize: '0.8rem', padding: '0 12px' }}
                  />
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--accent-color))', marginBottom: '6px', textTransform: 'uppercase' }}>Taux de Commission (%)</label>
                  <input
                    type="number"
                    min="0"
                    max="100"
                    step="1"
                    value={newCommissionRate}
                    onChange={(e) => setNewCommissionRate(Number(e.target.value))}
                    className="form-input"
                    style={{ height: '36px', fontSize: '0.8rem', padding: '0 12px' }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--accent-color))', marginBottom: '6px', textTransform: 'uppercase' }}>Cotisation Sociale (FC, facultatif)</label>
                  <input
                    type="number"
                    min="0"
                    placeholder="Boulangerie"
                    title="Laisser vide : la valeur de la boulangerie s'applique"
                    value={newCotisationSociale}
                    onChange={(e) => setNewCotisationSociale(e.target.value)}
                    className="form-input"
                    style={{ height: '36px', fontSize: '0.8rem', padding: '0 12px' }}
                  />
                </div>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '6px', textTransform: 'uppercase' }}>Téléphone</label>
                <input
                  type="text"
                  placeholder="Ex: +243 899 876 543"
                  value={newPhone}
                  onChange={(e) => setNewPhone(e.target.value)}
                  className="form-input"
                  style={{ height: '36px', fontSize: '0.8rem', padding: '0 12px' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '6px', textTransform: 'uppercase' }}>Adresse Commerciale</label>
                <input
                  type="text"
                  placeholder="Ex: Route de Matadi 145, Kasa-Vubu"
                  value={newAddress}
                  onChange={(e) => setNewAddress(e.target.value)}
                  className="form-input"
                  style={{ height: '36px', fontSize: '0.8rem', padding: '0 12px' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '6px', textTransform: 'uppercase' }}>Photo d'identité</label>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  {newPhotoPreview && (
                    <img
                      src={newPhotoPreview}
                      alt="Aperçu photo client"
                      style={{ width: '48px', height: '48px', borderRadius: '50%', objectFit: 'cover', border: '1px solid hsl(var(--border-color))' }}
                    />
                  )}
                  <input
                    type="file"
                    accept="image/*"
                    onChange={(e) => {
                      const file = e.target.files?.[0] || null;
                      if (newPhotoPreview) URL.revokeObjectURL(newPhotoPreview);
                      setNewPhoto(file);
                      setNewPhotoPreview(file ? URL.createObjectURL(file) : null);
                    }}
                    className="form-input"
                    style={{ flex: 1, height: '36px', fontSize: '0.75rem', padding: '6px 8px' }}
                  />
                  {newPhoto && (
                    <button
                      type="button"
                      onClick={() => {
                        if (newPhotoPreview) URL.revokeObjectURL(newPhotoPreview);
                        setNewPhoto(null); setNewPhotoPreview(null);
                      }}
                      className="btn btn-secondary"
                      style={{ padding: '6px 10px', fontSize: '0.7rem' }}
                    >
                      Retirer
                    </button>
                  )}
                </div>
              </div>

              {addError && (
                <div style={{ backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.3)', borderRadius: 'var(--radius-sm)', padding: '8px 12px', fontSize: '0.72rem', color: 'hsl(var(--color-danger))' }}>
                  {addError}
                </div>
              )}
              <div style={{ display: 'flex', gap: '12px', marginTop: '8px' }}>
                <button type="button" onClick={closeAddClientModal} className="btn btn-secondary" style={{ flex: 1, padding: '8px 16px', fontSize: '0.8rem' }}>
                  Annuler
                </button>
                <button type="submit" disabled={isAddingClient} className="btn btn-primary" style={{ flex: 2, padding: '8px 16px', fontSize: '0.8rem', opacity: isAddingClient ? 0.6 : 1 }}>
                  {isAddingClient ? 'Enregistrement...' : "Enregistrer l'Abonné"}
                </button>
              </div>
            </form>
      </Modal>
  );
};
