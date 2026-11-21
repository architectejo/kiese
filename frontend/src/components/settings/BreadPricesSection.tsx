import React, { useState } from 'react';
import { FiEdit2, FiPackage, FiPlus, FiSave, FiTrash2, FiX } from 'react-icons/fi';
import { coreApi, BreadPrice } from '@/api/services';
import { getErrorDetail } from '@/api/errors';

interface BreadPricesSectionProps {
  initial: BreadPrice[];
}

export const BreadPricesSection: React.FC<BreadPricesSectionProps> = ({ initial }) => {
  const [breadPrices, setBreadPrices] = useState<BreadPrice[]>(initial);
  const [bpLoading, setBpLoading] = useState(false);
  // Add form
  const [showBpAdd, setShowBpAdd] = useState(false);
  const [bpNewLabel, setBpNewLabel] = useState('');
  const [bpNewPrice, setBpNewPrice] = useState('');
  // BUG-049 : `category` est un texte libre côté backend depuis BUG-039 (plus de choix fermé à 4 valeurs).
  // Les 4 valeurs historiques restent proposées via <datalist> pour le confort de saisie, sans bloquer une 5ᵉ catégorie.
  const BP_CATEGORY_SUGGESTIONS = ['MINI', 'MOYEN', 'GRAND', 'PREMIUM'];
  const [bpNewCategory, setBpNewCategory] = useState<string>('MOYEN');
  const [bpAddError, setBpAddError] = useState<string | null>(null);
  // Edit state
  const [editingBpId, setEditingBpId] = useState<number | null>(null);
  const [bpEditLabel, setBpEditLabel] = useState('');
  const [bpEditPrice, setBpEditPrice] = useState('');
  const [bpEditCategory, setBpEditCategory] = useState<string>('MOYEN');
  const [bpEditActive, setBpEditActive] = useState(true);
  const [bpEditError, setBpEditError] = useState<string | null>(null);

  const handleBpCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!bpNewLabel || !bpNewPrice) { setBpAddError('Libellé et prix requis.'); return; }
    if (!bpNewCategory.trim()) { setBpAddError('Catégorie requise.'); return; }
    setBpAddError(null);
    setBpLoading(true);
    try {
      // `category` est un champ texte libre côté backend (BUG-039) : le type `BreadPrice['category']`
      // partagé dans src/api/services.ts n'a pas encore été élargi, cast nécessaire ici.
      const res = await coreApi.breadPrices.create({ label: bpNewLabel, unit_price: parseFloat(bpNewPrice), category: bpNewCategory.trim().toUpperCase() as BreadPrice['category'], is_active: true });
      setBreadPrices(prev => [...prev, res.data]);
      setBpNewLabel(''); setBpNewPrice(''); setShowBpAdd(false);
    } catch (err: unknown) {
      setBpAddError(getErrorDetail(err, 'Erreur de création.'));
    }
    setBpLoading(false);
  };

  const startEditBp = (bp: BreadPrice) => {
    setEditingBpId(bp.id);
    setBpEditLabel(bp.label);
    setBpEditPrice(bp.unit_price.toString());
    setBpEditCategory(bp.category);
    setBpEditActive(bp.is_active);
    setBpEditError(null);
  };

  const handleBpSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingBpId) return;
    if (!bpEditCategory.trim()) { setBpEditError('Catégorie requise.'); return; }
    setBpEditError(null);
    try {
      const res = await coreApi.breadPrices.update(editingBpId, { label: bpEditLabel, unit_price: parseFloat(bpEditPrice), category: bpEditCategory.trim().toUpperCase() as BreadPrice['category'], is_active: bpEditActive });
      setBreadPrices(prev => prev.map(bp => bp.id === editingBpId ? res.data : bp));
      setEditingBpId(null);
    } catch (err: unknown) {
      setBpEditError(getErrorDetail(err, 'Erreur de mise à jour.'));
    }
  };

  const handleBpDelete = async (id: number) => {
    if (!window.confirm('Supprimer ce tarif ? Les tarifs déjà utilisés dans des factures ou productions ne pourront pas être supprimés.')) return;
    try {
      await coreApi.breadPrices.delete(id);
      setBreadPrices(prev => prev.filter(bp => bp.id !== id));
    } catch (err: unknown) {
      alert(getErrorDetail(err, 'Suppression impossible — ce tarif est peut-être déjà utilisé.'));
    }
  };

  return (
      <div className="glass-card" style={{ padding: '18px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
          <h3 style={{ fontSize: '0.88rem', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '6px' }}>
            <FiPackage style={{ color: 'hsl(var(--accent-color))' }} />
            Grille Tarifaire — Prix des Pains
          </h3>
          {!showBpAdd && (
            <button onClick={() => setShowBpAdd(true)} className="btn btn-secondary" style={{ padding: '5px 10px', fontSize: '0.72rem', display: 'flex', alignItems: 'center', gap: '4px' }}>
              <FiPlus /> Ajouter un tarif
            </button>
          )}
        </div>

        {/* Suggestions des catégories historiques — champ libre, ne bloque pas une 5ᵉ valeur (BUG-049) */}
        <datalist id="bp-category-suggestions">
          {BP_CATEGORY_SUGGESTIONS.map(c => <option key={c} value={c} />)}
        </datalist>

        {/* Add form */}
        {showBpAdd && (
          <form onSubmit={handleBpCreate} style={{ backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', borderRadius: 'var(--radius-sm)', padding: '12px', marginBottom: '12px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: '10px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', textTransform: 'uppercase' }}>Libellé *</label>
                <input type="text" value={bpNewLabel} onChange={e => setBpNewLabel(e.target.value)} placeholder="Ex: Pain 400 FC" className="form-input" style={{ height: '32px', fontSize: '0.78rem', padding: '0 8px' }} required />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', textTransform: 'uppercase' }}>Prix FC *</label>
                <input type="number" min={1} value={bpNewPrice} onChange={e => setBpNewPrice(e.target.value)} placeholder="400" className="form-input" style={{ height: '32px', fontSize: '0.78rem', padding: '0 8px' }} required />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', textTransform: 'uppercase' }}>Catégorie</label>
                <input
                  type="text"
                  list="bp-category-suggestions"
                  value={bpNewCategory}
                  onChange={e => setBpNewCategory(e.target.value)}
                  placeholder="Ex: MICRO_200"
                  className="form-input"
                  style={{ height: '32px', fontSize: '0.78rem', padding: '0 8px' }}
                  required
                />
              </div>
            </div>
            {bpAddError && <div style={{ fontSize: '0.68rem', color: 'hsl(var(--color-danger))' }}>{bpAddError}</div>}
            <div style={{ display: 'flex', gap: '8px' }}>
              <button type="submit" disabled={bpLoading} className="btn btn-primary" style={{ padding: '6px 14px', fontSize: '0.75rem' }}>Créer</button>
              <button type="button" onClick={() => { setShowBpAdd(false); setBpAddError(null); setBpNewLabel(''); setBpNewPrice(''); }} className="btn btn-secondary" style={{ padding: '6px 14px', fontSize: '0.75rem' }}>Annuler</button>
            </div>
          </form>
        )}

        {/* Bread prices list */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {breadPrices.length === 0 && <p style={{ fontSize: '0.75rem', color: 'hsl(var(--text-muted))', textAlign: 'center', padding: '16px 0' }}>Aucun tarif enregistré.</p>}
          {breadPrices.map(bp => (
            <div key={bp.id} style={{ padding: '8px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid hsl(var(--border-color))', backgroundColor: 'hsl(var(--bg-tertiary))' }}>
              {editingBpId === bp.id ? (
                <form onSubmit={handleBpSave} style={{ display: 'flex', gap: '8px', alignItems: 'flex-end', flexWrap: 'wrap' }}>
                  <div>
                    <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, marginBottom: '2px', textTransform: 'uppercase' }}>Libellé</div>
                    <input type="text" value={bpEditLabel} onChange={e => setBpEditLabel(e.target.value)} className="form-input" style={{ height: '28px', fontSize: '0.75rem', padding: '0 6px', width: '120px' }} required />
                  </div>
                  <div>
                    <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, marginBottom: '2px', textTransform: 'uppercase' }}>Prix FC</div>
                    <input type="number" min={1} value={bpEditPrice} onChange={e => setBpEditPrice(e.target.value)} className="form-input" style={{ height: '28px', fontSize: '0.75rem', padding: '0 6px', width: '80px' }} required />
                  </div>
                  <div>
                    <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, marginBottom: '2px', textTransform: 'uppercase' }}>Catégorie</div>
                    <input
                      type="text"
                      list="bp-category-suggestions"
                      value={bpEditCategory}
                      onChange={e => setBpEditCategory(e.target.value)}
                      className="form-input"
                      style={{ height: '28px', fontSize: '0.73rem', padding: '0 6px', width: '110px' }}
                      required
                    />
                  </div>
                  <div>
                    <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, marginBottom: '2px', textTransform: 'uppercase' }}>Statut</div>
                    <select value={bpEditActive ? 'true' : 'false'} onChange={e => setBpEditActive(e.target.value === 'true')} className="form-input" style={{ height: '28px', fontSize: '0.73rem', padding: '0 4px' }}>
                      <option value="true">Actif</option>
                      <option value="false">Inactif</option>
                    </select>
                  </div>
                  <div style={{ display: 'flex', gap: '4px' }}>
                    <button type="submit" className="btn btn-primary" style={{ padding: '4px 10px', fontSize: '0.72rem' }}><FiSave size={11} /> OK</button>
                    <button type="button" onClick={() => setEditingBpId(null)} className="btn btn-secondary" style={{ padding: '4px 8px', fontSize: '0.72rem' }}><FiX size={11} /></button>
                  </div>
                  {bpEditError && <div style={{ fontSize: '0.65rem', color: 'hsl(var(--color-danger))', width: '100%' }}>{bpEditError}</div>}
                </form>
              ) : (
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span style={{ fontWeight: 800, fontSize: '0.82rem' }}>{bp.label}</span>
                    <span style={{ fontWeight: 700, fontSize: '0.85rem', color: 'hsl(var(--accent-color))' }}>{bp.unit_price.toLocaleString('fr-FR')} FC</span>
                    <span className="badge badge-info" style={{ fontSize: '0.55rem', padding: '1px 5px' }}>{bp.category}</span>
                    <span className={`badge ${bp.is_active ? 'badge-success' : 'badge-danger'}`} style={{ fontSize: '0.55rem', padding: '1px 5px' }}>{bp.is_active ? 'ACTIF' : 'INACTIF'}</span>
                  </div>
                  <div style={{ display: 'flex', gap: '4px' }}>
                    <button onClick={() => startEditBp(bp)} className="theme-picker-btn" style={{ padding: '4px 5px', color: 'hsl(var(--accent-color))' }} title="Modifier">
                      <FiEdit2 style={{ fontSize: '0.75rem' }} />
                    </button>
                    <button onClick={() => handleBpDelete(bp.id)} className="theme-picker-btn" style={{ padding: '4px 5px', color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.07)', border: '1px solid hsl(var(--color-danger) / 0.2)' }} title="Supprimer">
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
