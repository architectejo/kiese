import React, { useState } from 'react';
import axios from 'axios';
import { FiEdit2, FiPackage, FiPlus, FiSave, FiTrash2, FiX } from 'react-icons/fi';
import { productionApi, ConsumableType } from '@/api/services';
import { getErrorDetail } from '@/api/errors';

interface ConsumableTypesSectionProps {
  initial: ConsumableType[];
}

export const ConsumableTypesSection: React.FC<ConsumableTypesSectionProps> = ({ initial }) => {
  const [consumableTypes, setConsumableTypes] = useState<ConsumableType[]>(initial);
  const [ctLoading, setCtLoading] = useState(false);
  // Add form
  const [showCtAdd, setShowCtAdd] = useState(false);
  const [ctNewCode, setCtNewCode] = useState('');
  const [ctNewLabel, setCtNewLabel] = useState('');
  const [ctNewUnit, setCtNewUnit] = useState('');
  const [ctAddError, setCtAddError] = useState<string | null>(null);
  // Edit state
  const [editingCtId, setEditingCtId] = useState<number | null>(null);
  const [ctEditCode, setCtEditCode] = useState('');
  const [ctEditLabel, setCtEditLabel] = useState('');
  const [ctEditUnit, setCtEditUnit] = useState('');
  const [ctEditActive, setCtEditActive] = useState(true);
  const [ctEditError, setCtEditError] = useState<string | null>(null);

  const handleCtCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!ctNewCode || !ctNewLabel) { setCtAddError('Code et libellé requis.'); return; }
    setCtAddError(null);
    setCtLoading(true);
    try {
      const res = await productionApi.consumableTypes.create({ code: ctNewCode.toUpperCase(), label: ctNewLabel, unit: ctNewUnit, is_active: true });
      setConsumableTypes(prev => [...prev, res.data]);
      setCtNewCode(''); setCtNewLabel(''); setCtNewUnit(''); setShowCtAdd(false);
    } catch (err: unknown) {
      const d = axios.isAxiosError(err)
        ? (err.response?.data as { detail?: string; code?: string[] } | undefined)
        : undefined;
      setCtAddError(d?.detail || d?.code?.[0] || 'Erreur de création.');
    }
    setCtLoading(false);
  };

  const startEditCt = (ct: ConsumableType) => {
    setEditingCtId(ct.id);
    setCtEditCode(ct.code);
    setCtEditLabel(ct.label);
    setCtEditUnit(ct.unit);
    setCtEditActive(ct.is_active);
    setCtEditError(null);
  };

  const handleCtSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingCtId) return;
    setCtEditError(null);
    try {
      const res = await productionApi.consumableTypes.update(editingCtId, { code: ctEditCode.toUpperCase(), label: ctEditLabel, unit: ctEditUnit, is_active: ctEditActive });
      setConsumableTypes(prev => prev.map(ct => ct.id === editingCtId ? res.data : ct));
      setEditingCtId(null);
    } catch (err: unknown) {
      setCtEditError(getErrorDetail(err, 'Erreur de mise à jour.'));
    }
  };

  const handleCtDelete = async (id: number) => {
    if (!window.confirm('Supprimer ce consommable ?')) return;
    try {
      await productionApi.consumableTypes.delete(id);
      setConsumableTypes(prev => prev.filter(ct => ct.id !== id));
    } catch (err: unknown) {
      alert(getErrorDetail(err, 'Suppression impossible — des stocks non nuls existent encore pour ce consommable.'));
    }
  };

  return (
      <div className="glass-card" style={{ padding: '18px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
          <h3 style={{ fontSize: '0.88rem', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '6px' }}>
            <FiPackage style={{ color: 'hsl(var(--accent-color))' }} />
            Consommables (Stocks Production)
          </h3>
          {!showCtAdd && (
            <button onClick={() => setShowCtAdd(true)} className="btn btn-secondary" style={{ padding: '5px 10px', fontSize: '0.72rem', display: 'flex', alignItems: 'center', gap: '4px' }}>
              <FiPlus /> Ajouter un consommable
            </button>
          )}
        </div>
        <p style={{ fontSize: '0.7rem', color: 'hsl(var(--text-muted))', marginTop: '-8px', marginBottom: '12px' }}>
          Un compte de stock est créé automatiquement pour chaque boulangerie au prochain accès à "Production &amp; Stocks".
        </p>

        {/* Add form */}
        {showCtAdd && (
          <form onSubmit={handleCtCreate} style={{ backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', borderRadius: 'var(--radius-sm)', padding: '12px', marginBottom: '12px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr 1fr', gap: '10px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', textTransform: 'uppercase' }}>Code *</label>
                <input type="text" value={ctNewCode} onChange={e => setCtNewCode(e.target.value)} placeholder="Ex: SUCRE" className="form-input" style={{ height: '32px', fontSize: '0.78rem', padding: '0 8px' }} required />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', textTransform: 'uppercase' }}>Libellé *</label>
                <input type="text" value={ctNewLabel} onChange={e => setCtNewLabel(e.target.value)} placeholder="Ex: Sucre (kg)" className="form-input" style={{ height: '32px', fontSize: '0.78rem', padding: '0 8px' }} required />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', textTransform: 'uppercase' }}>Unité</label>
                <input type="text" value={ctNewUnit} onChange={e => setCtNewUnit(e.target.value)} placeholder="Ex: kg" className="form-input" style={{ height: '32px', fontSize: '0.78rem', padding: '0 8px' }} />
              </div>
            </div>
            {ctAddError && <div style={{ fontSize: '0.68rem', color: 'hsl(var(--color-danger))' }}>{ctAddError}</div>}
            <div style={{ display: 'flex', gap: '8px' }}>
              <button type="submit" disabled={ctLoading} className="btn btn-primary" style={{ padding: '6px 14px', fontSize: '0.75rem' }}>Créer</button>
              <button type="button" onClick={() => { setShowCtAdd(false); setCtAddError(null); setCtNewCode(''); setCtNewLabel(''); setCtNewUnit(''); }} className="btn btn-secondary" style={{ padding: '6px 14px', fontSize: '0.75rem' }}>Annuler</button>
            </div>
          </form>
        )}

        {/* List */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {consumableTypes.length === 0 && <p style={{ fontSize: '0.75rem', color: 'hsl(var(--text-muted))', textAlign: 'center', padding: '16px 0' }}>Aucun consommable enregistré.</p>}
          {consumableTypes.map(ct => (
            <div key={ct.id} style={{ padding: '8px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid hsl(var(--border-color))', backgroundColor: 'hsl(var(--bg-tertiary))' }}>
              {editingCtId === ct.id ? (
                <form onSubmit={handleCtSave} style={{ display: 'flex', gap: '8px', alignItems: 'flex-end', flexWrap: 'wrap' }}>
                  <div>
                    <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, marginBottom: '2px', textTransform: 'uppercase' }}>Code</div>
                    <input type="text" value={ctEditCode} onChange={e => setCtEditCode(e.target.value)} className="form-input" style={{ height: '28px', fontSize: '0.75rem', padding: '0 6px', width: '110px' }} required />
                  </div>
                  <div>
                    <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, marginBottom: '2px', textTransform: 'uppercase' }}>Libellé</div>
                    <input type="text" value={ctEditLabel} onChange={e => setCtEditLabel(e.target.value)} className="form-input" style={{ height: '28px', fontSize: '0.75rem', padding: '0 6px', width: '170px' }} required />
                  </div>
                  <div>
                    <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, marginBottom: '2px', textTransform: 'uppercase' }}>Unité</div>
                    <input type="text" value={ctEditUnit} onChange={e => setCtEditUnit(e.target.value)} className="form-input" style={{ height: '28px', fontSize: '0.75rem', padding: '0 6px', width: '80px' }} />
                  </div>
                  <div>
                    <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, marginBottom: '2px', textTransform: 'uppercase' }}>Statut</div>
                    <select value={ctEditActive ? 'true' : 'false'} onChange={e => setCtEditActive(e.target.value === 'true')} className="form-input" style={{ height: '28px', fontSize: '0.73rem', padding: '0 4px' }}>
                      <option value="true">Actif</option>
                      <option value="false">Inactif</option>
                    </select>
                  </div>
                  <div style={{ display: 'flex', gap: '4px' }}>
                    <button type="submit" className="btn btn-primary" style={{ padding: '4px 10px', fontSize: '0.72rem' }}><FiSave size={11} /> OK</button>
                    <button type="button" onClick={() => setEditingCtId(null)} className="btn btn-secondary" style={{ padding: '4px 8px', fontSize: '0.72rem' }}><FiX size={11} /></button>
                  </div>
                  {ctEditError && <div style={{ fontSize: '0.65rem', color: 'hsl(var(--color-danger))', width: '100%' }}>{ctEditError}</div>}
                </form>
              ) : (
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span className="badge badge-info" style={{ fontSize: '0.55rem', padding: '1px 5px', fontFamily: 'monospace' }}>{ct.code}</span>
                    <span style={{ fontWeight: 800, fontSize: '0.82rem' }}>{ct.label}</span>
                    {ct.unit && <span style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))' }}>({ct.unit})</span>}
                    <span className={`badge ${ct.is_active ? 'badge-success' : 'badge-danger'}`} style={{ fontSize: '0.55rem', padding: '1px 5px' }}>{ct.is_active ? 'ACTIF' : 'INACTIF'}</span>
                  </div>
                  <div style={{ display: 'flex', gap: '4px' }}>
                    <button onClick={() => startEditCt(ct)} className="theme-picker-btn" style={{ padding: '4px 5px', color: 'hsl(var(--accent-color))' }} title="Modifier">
                      <FiEdit2 style={{ fontSize: '0.75rem' }} />
                    </button>
                    <button onClick={() => handleCtDelete(ct.id)} className="theme-picker-btn" style={{ padding: '4px 5px', color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.07)', border: '1px solid hsl(var(--color-danger) / 0.2)' }} title="Supprimer">
                      <FiTrash2 style={{ fontSize: '0.75rem' }} />
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
  );
};
