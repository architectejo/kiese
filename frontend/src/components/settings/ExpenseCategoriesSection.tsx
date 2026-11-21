import React, { useState } from 'react';
import axios from 'axios';
import { FiEdit2, FiPackage, FiPlus, FiSave, FiTrash2, FiX } from 'react-icons/fi';
import { coreApi, ExpenseCategory } from '@/api/services';
import { getErrorDetail } from '@/api/errors';

interface ExpenseCategoriesSectionProps {
  initial: ExpenseCategory[];
}

export const ExpenseCategoriesSection: React.FC<ExpenseCategoriesSectionProps> = ({ initial }) => {
  const [expenseCategories, setExpenseCategories] = useState<ExpenseCategory[]>(initial);
  const [ecLoading, setEcLoading] = useState(false);
  // Add form
  const [showEcAdd, setShowEcAdd] = useState(false);
  const [ecNewCode, setEcNewCode] = useState('');
  const [ecNewLabel, setEcNewLabel] = useState('');
  const [ecAddError, setEcAddError] = useState<string | null>(null);
  // Edit state
  const [editingEcId, setEditingEcId] = useState<number | null>(null);
  const [ecEditCode, setEcEditCode] = useState('');
  const [ecEditLabel, setEcEditLabel] = useState('');
  const [ecEditActive, setEcEditActive] = useState(true);
  const [ecEditError, setEcEditError] = useState<string | null>(null);

  const handleEcCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!ecNewCode || !ecNewLabel) { setEcAddError('Code et libellé requis.'); return; }
    setEcAddError(null);
    setEcLoading(true);
    try {
      const res = await coreApi.expenseCategories.create({ code: ecNewCode.toUpperCase(), label: ecNewLabel, is_active: true });
      setExpenseCategories(prev => [...prev, res.data]);
      setEcNewCode(''); setEcNewLabel(''); setShowEcAdd(false);
    } catch (err: unknown) {
      const d = axios.isAxiosError(err)
        ? (err.response?.data as { detail?: string; code?: string[] } | undefined)
        : undefined;
      setEcAddError(d?.detail || d?.code?.[0] || 'Erreur de création.');
    }
    setEcLoading(false);
  };

  const startEditEc = (ec: ExpenseCategory) => {
    setEditingEcId(ec.id);
    setEcEditCode(ec.code);
    setEcEditLabel(ec.label);
    setEcEditActive(ec.is_active);
    setEcEditError(null);
  };

  const handleEcSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingEcId) return;
    setEcEditError(null);
    try {
      const res = await coreApi.expenseCategories.update(editingEcId, { code: ecEditCode.toUpperCase(), label: ecEditLabel, is_active: ecEditActive });
      setExpenseCategories(prev => prev.map(ec => ec.id === editingEcId ? res.data : ec));
      setEditingEcId(null);
    } catch (err: unknown) {
      setEcEditError(getErrorDetail(err, 'Erreur de mise à jour.'));
    }
  };

  const handleEcDelete = async (id: number) => {
    if (!window.confirm('Supprimer cette catégorie ? Les dépenses existantes qui l\'utilisent empêcheront la suppression.')) return;
    try {
      await coreApi.expenseCategories.delete(id);
      setExpenseCategories(prev => prev.filter(ec => ec.id !== id));
    } catch (err: unknown) {
      alert(getErrorDetail(err, 'Suppression impossible — cette catégorie est utilisée par des dépenses existantes.'));
    }
  };

  return (
      <div className="glass-card" style={{ padding: '18px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
          <h3 style={{ fontSize: '0.88rem', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '6px' }}>
            <FiPackage style={{ color: 'hsl(var(--accent-color))' }} />
            Catégories de Dépenses Locales
          </h3>
          {!showEcAdd && (
            <button onClick={() => setShowEcAdd(true)} className="btn btn-secondary" style={{ padding: '5px 10px', fontSize: '0.72rem', display: 'flex', alignItems: 'center', gap: '4px' }}>
              <FiPlus /> Ajouter une catégorie
            </button>
          )}
        </div>

        {/* Add form */}
        {showEcAdd && (
          <form onSubmit={handleEcCreate} style={{ backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', borderRadius: 'var(--radius-sm)', padding: '12px', marginBottom: '12px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '10px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', textTransform: 'uppercase' }}>Code *</label>
                <input type="text" value={ecNewCode} onChange={e => setEcNewCode(e.target.value)} placeholder="Ex: SALAIRES" className="form-input" style={{ height: '32px', fontSize: '0.78rem', padding: '0 8px' }} required />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', textTransform: 'uppercase' }}>Libellé *</label>
                <input type="text" value={ecNewLabel} onChange={e => setEcNewLabel(e.target.value)} placeholder="Ex: Salaires Temporaires" className="form-input" style={{ height: '32px', fontSize: '0.78rem', padding: '0 8px' }} required />
              </div>
            </div>
            {ecAddError && <div style={{ fontSize: '0.68rem', color: 'hsl(var(--color-danger))' }}>{ecAddError}</div>}
            <div style={{ display: 'flex', gap: '8px' }}>
              <button type="submit" disabled={ecLoading} className="btn btn-primary" style={{ padding: '6px 14px', fontSize: '0.75rem' }}>Créer</button>
              <button type="button" onClick={() => { setShowEcAdd(false); setEcAddError(null); setEcNewCode(''); setEcNewLabel(''); }} className="btn btn-secondary" style={{ padding: '6px 14px', fontSize: '0.75rem' }}>Annuler</button>
            </div>
          </form>
        )}

        {/* Categories list */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {expenseCategories.length === 0 && <p style={{ fontSize: '0.75rem', color: 'hsl(var(--text-muted))', textAlign: 'center', padding: '16px 0' }}>Aucune catégorie enregistrée.</p>}
          {expenseCategories.map(ec => (
            <div key={ec.id} style={{ padding: '8px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid hsl(var(--border-color))', backgroundColor: 'hsl(var(--bg-tertiary))' }}>
              {editingEcId === ec.id ? (
                <form onSubmit={handleEcSave} style={{ display: 'flex', gap: '8px', alignItems: 'flex-end', flexWrap: 'wrap' }}>
                  <div>
                    <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, marginBottom: '2px', textTransform: 'uppercase' }}>Code</div>
                    <input type="text" value={ecEditCode} onChange={e => setEcEditCode(e.target.value)} className="form-input" style={{ height: '28px', fontSize: '0.75rem', padding: '0 6px', width: '120px' }} required />
                  </div>
                  <div>
                    <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, marginBottom: '2px', textTransform: 'uppercase' }}>Libellé</div>
                    <input type="text" value={ecEditLabel} onChange={e => setEcEditLabel(e.target.value)} className="form-input" style={{ height: '28px', fontSize: '0.75rem', padding: '0 6px', width: '180px' }} required />
                  </div>
                  <div>
                    <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, marginBottom: '2px', textTransform: 'uppercase' }}>Statut</div>
                    <select value={ecEditActive ? 'true' : 'false'} onChange={e => setEcEditActive(e.target.value === 'true')} className="form-input" style={{ height: '28px', fontSize: '0.73rem', padding: '0 4px' }}>
                      <option value="true">Actif</option>
                      <option value="false">Inactif</option>
                    </select>
                  </div>
                  <div style={{ display: 'flex', gap: '4px' }}>
                    <button type="submit" className="btn btn-primary" style={{ padding: '4px 10px', fontSize: '0.72rem' }}><FiSave size={11} /> OK</button>
                    <button type="button" onClick={() => setEditingEcId(null)} className="btn btn-secondary" style={{ padding: '4px 8px', fontSize: '0.72rem' }}><FiX size={11} /></button>
                  </div>
                  {ecEditError && <div style={{ fontSize: '0.65rem', color: 'hsl(var(--color-danger))', width: '100%' }}>{ecEditError}</div>}
                </form>
              ) : (
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span className="badge badge-info" style={{ fontSize: '0.55rem', padding: '1px 5px', fontFamily: 'monospace' }}>{ec.code}</span>
                    <span style={{ fontWeight: 800, fontSize: '0.82rem' }}>{ec.label}</span>
                    <span className={`badge ${ec.is_active ? 'badge-success' : 'badge-danger'}`} style={{ fontSize: '0.55rem', padding: '1px 5px' }}>{ec.is_active ? 'ACTIF' : 'INACTIF'}</span>
                  </div>
                  <div style={{ display: 'flex', gap: '4px' }}>
                    <button onClick={() => startEditEc(ec)} className="theme-picker-btn" style={{ padding: '4px 5px', color: 'hsl(var(--accent-color))' }} title="Modifier">
                      <FiEdit2 style={{ fontSize: '0.75rem' }} />
                    </button>
                    <button onClick={() => handleEcDelete(ec.id)} className="theme-picker-btn" style={{ padding: '4px 5px', color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.07)', border: '1px solid hsl(var(--color-danger) / 0.2)' }} title="Supprimer">
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
