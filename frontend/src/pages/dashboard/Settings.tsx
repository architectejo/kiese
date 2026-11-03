import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import {
  FiSettings, FiSave, FiRefreshCw, FiGlobe, FiLock,
  FiAlertTriangle, FiCheckCircle, FiSliders, FiPercent,
  FiDollarSign, FiPackage, FiEdit2, FiTrash2,
  FiPlus, FiX
} from 'react-icons/fi';
import { coreApi, productionApi, SiteConfig, BreadPrice, ExpenseCategory, ConsumableType, BakeryNode, ColisDistribution } from '@/api/services';
import { getErrorDetail } from '@/api/errors';
import { useAuthStore } from '@/store/authStore';
export const Settings: React.FC = () => {
  const { user } = useAuthStore();

  // ── Config state ──────────────────────────────────────────────────
  const [config, setConfig] = useState<SiteConfig | null>(null);
  const [form, setForm] = useState<Partial<SiteConfig>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [saveMsg, setSaveMsg] = useState('');

  // ── BreadPrice CRUD state ─────────────────────────────────────────
  const [breadPrices, setBreadPrices] = useState<BreadPrice[]>([]);
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

  // ── ExpenseCategory CRUD state ──────────────────────────────────────
  const [expenseCategories, setExpenseCategories] = useState<ExpenseCategory[]>([]);
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

  // ── ConsumableType CRUD state (Production & Stocks — Stocks Consommables) ──
  const [consumableTypes, setConsumableTypes] = useState<ConsumableType[]>([]);
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

  // ── COLIS Personnel state ─────────────────────────────────────────
  const [colisNode, setColisNode]     = useState('');
  const [colisYear, setColisYear]     = useState(() => new Date().getFullYear());
  const [colisList, setColisList]     = useState<ColisDistribution[]>([]);
  const [colisLoading, setColisLoading] = useState(false);
  const [colisNodes, setColisNodes]   = useState<BakeryNode[]>([]);
  const [colisLabel, setColisLabel]   = useState('');
  const [colisRiceSacks, setColisRiceSacks] = useState('');
  const [colisRiceValue, setColisRiceValue] = useState('');
  const [colisMeatKg, setColisMeatKg] = useState('');
  const [colisMeatValue, setColisMeatValue] = useState('');
  const [colisCash, setColisCash]     = useState('');
  const [colisNotes, setColisNotes]   = useState('');
  const [colisError, setColisError]   = useState<string | null>(null);
  const [colisSubmitting, setColisSubmitting] = useState(false);
  const [showColisForm, setShowColisForm] = useState(false);

  const loadColis = useCallback(async () => {
    if (!colisNode) return;
    setColisLoading(true);
    try {
      const res = await coreApi.colis.list({ node: colisNode, year: String(colisYear) });
      setColisList(Array.isArray(res.data) ? res.data : []);
    } catch { setColisList([]); }
    finally { setColisLoading(false); }
  }, [colisNode, colisYear]);

  useEffect(() => { loadColis(); }, [loadColis]);

  const handleColisSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!colisLabel) { setColisError('Indiquez le bénéficiaire.'); return; }
    setColisSubmitting(true); setColisError(null);
    try {
      await coreApi.colis.create({
        node: colisNode, year: colisYear, beneficiary_label: colisLabel,
        rice_sacks: colisRiceSacks || '0', rice_value: colisRiceValue || '0',
        meat_kg: colisMeatKg || '0', meat_value: colisMeatValue || '0',
        cash_amount: colisCash || '0', notes: colisNotes,
      });
      setColisLabel(''); setColisRiceSacks(''); setColisRiceValue('');
      setColisMeatKg(''); setColisMeatValue(''); setColisCash(''); setColisNotes('');
      setShowColisForm(false);
      await loadColis();
    } catch (err: unknown) { setColisError(getErrorDetail(err, 'Erreur.')); }
    finally { setColisSubmitting(false); }
  };

  const handleColisDelete = async (id: number) => {
    if (!window.confirm('Supprimer cette ligne COLIS ?')) return;
    try { await coreApi.colis.delete(id); await loadColis(); } catch { /* ignore */ }
  };

  useEffect(() => {
    Promise.all([
      coreApi.config.get(),
      coreApi.breadPrices.list(),
      coreApi.nodes.list(),
      coreApi.expenseCategories.list(),
      productionApi.consumableTypes.list(),
    ]).then(([configRes, bpRes, nodesRes, ecRes, ctRes]) => {
      setConfig(configRes.data);
      setForm(configRes.data);
      setBreadPrices(bpRes.data);
      setColisNodes(nodesRes.data);
      setExpenseCategories(ecRes.data);
      setConsumableTypes(ctRes.data);
      if (nodesRes.data.length > 0 && !colisNode) setColisNode(nodesRes.data[0].id);
    }).catch(() => {}).finally(() => setIsLoading(false));
    if (user?.node && !colisNode) setColisNode(user.node);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const set = (key: keyof SiteConfig, value: string | number | boolean) =>
    setForm(prev => ({ ...prev, [key]: value }));

  const handleSave = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setIsSaving(true);
    setSaveStatus('idle');
    try {
      const res = await coreApi.config.update(form);
      setConfig(res.data);
      setForm(res.data);
      setSaveStatus('success');
      setSaveMsg('Configuration enregistrée avec succès.');
    } catch (err: unknown) {
      setSaveStatus('error');
      setSaveMsg(getErrorDetail(err, 'Erreur lors de la sauvegarde.'));
    } finally {
      setIsSaving(false);
      setTimeout(() => setSaveStatus('idle'), 4000);
    }
  };

  const handleToggleOnline = async () => {
    const newVal = !form.on_line;
    setForm(prev => ({ ...prev, on_line: newVal }));
    try {
      await coreApi.config.update({ on_line: newVal });
      setConfig(prev => prev ? { ...prev, on_line: newVal } : prev);
      setSaveStatus('success');
      setSaveMsg(`Site web ${newVal ? 'ACTIVÉ (vitrine visible)' : 'DÉSACTIVÉ (dashboard uniquement)'}`);
      setTimeout(() => setSaveStatus('idle'), 4000);
    } catch {
      setForm(prev => ({ ...prev, on_line: !newVal })); // rollback
      setSaveStatus('error');
      setSaveMsg('Impossible de changer le mode. Vérifiez les permissions.');
      setTimeout(() => setSaveStatus('idle'), 4000);
    }
  };

  // ── Handlers: BreadPrice CRUD ─────────────────────────────────────
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

  // ── Handlers: ExpenseCategory CRUD ─────────────────────────────────
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

  // ── Handlers: ConsumableType CRUD ──────────────────────────────────
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

  if (isLoading) {
    return (
      <div style={{ textAlign: 'center', padding: '48px', color: 'hsl(var(--text-muted))' }}>
        Chargement de la configuration...
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', fontSize: '0.85rem' }}>

      {/* Header */}
      <div className="glass-card animate-fade-in" style={{ background: 'linear-gradient(135deg, hsl(var(--bg-tertiary)) 0%, hsl(var(--bg-secondary)) 100%)', borderLeft: '4px solid hsl(var(--accent-color))', padding: '14px 20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h1 style={{ fontSize: '1.3rem', fontWeight: 800, marginBottom: '2px' }}>Configuration Système</h1>
            <p style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.72rem' }}>
              §6.2 Toggle on_line · Paramètres algorithmiques · Grilles de commission et de rendement
            </p>
          </div>
          <FiSettings style={{ fontSize: '2rem', color: 'hsl(var(--accent-color))', opacity: 0.8 }} />
        </div>
      </div>

      {/* Save status */}
      {saveStatus !== 'idle' && (
        <div className="animate-fade-in" style={{
          padding: '10px 16px', borderRadius: 'var(--radius-sm)', fontSize: '0.78rem', fontWeight: 700,
          backgroundColor: saveStatus === 'success' ? 'hsl(var(--color-success) / 0.1)' : 'hsl(var(--color-danger) / 0.1)',
          border: `1px solid hsl(var(--${saveStatus === 'success' ? 'color-success' : 'color-danger'}) / 0.4)`,
          color: saveStatus === 'success' ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))',
          display: 'flex', alignItems: 'center', gap: '8px'
        }}>
          {saveStatus === 'success' ? <FiCheckCircle /> : <FiAlertTriangle />}
          {saveMsg}
        </div>
      )}

      {/* §6.2 ON_LINE TOGGLE — carte principale */}
      <div className="glass-card" style={{
        padding: '20px 24px',
        borderLeft: `4px solid hsl(var(--${form.on_line ? 'color-success' : 'color-danger'}))`,
        backgroundColor: `hsl(var(--${form.on_line ? 'color-success' : 'color-danger'}) / 0.04)`,
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
            <div style={{
              width: '48px', height: '48px', borderRadius: '50%',
              backgroundColor: `hsl(var(--${form.on_line ? 'color-success' : 'color-danger'}) / 0.15)`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: `hsl(var(--${form.on_line ? 'color-success' : 'color-danger'}))`,
              fontSize: '1.4rem'
            }}>
              {form.on_line ? <FiGlobe /> : <FiLock />}
            </div>
            <div>
              <h2 style={{ fontSize: '1rem', fontWeight: 800, marginBottom: '4px' }}>
                Mode d'Affichage Public — §6.2
              </h2>
              <p style={{ fontSize: '0.72rem', color: 'hsl(var(--text-secondary))', maxWidth: '500px' }}>
                {form.on_line
                  ? 'Site web vitrine VISIBLE au public. Les agents accèdent au dashboard via le bouton "Connexion".'
                  : 'Site vitrine MASQUÉ. Tout visiteur est automatiquement redirigé vers la page de login du dashboard.'}
              </p>
              <p style={{ fontSize: '0.65rem', color: 'hsl(var(--text-muted))', marginTop: '2px' }}>
                Dernière modification : {config?.updated_at ? new Date(config.updated_at).toLocaleString('fr-FR') : '—'}
              </p>
            </div>
          </div>

          {/* Toggle switch */}
          <button
            type="button"
            onClick={handleToggleOnline}
            style={{
              position: 'relative', width: '72px', height: '36px',
              borderRadius: '18px', border: 'none', cursor: 'pointer',
              backgroundColor: form.on_line ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))',
              transition: 'background-color 0.3s ease',
              flexShrink: 0,
            }}
            title={form.on_line ? 'Cliquer pour désactiver la vitrine' : 'Cliquer pour activer la vitrine'}
          >
            <span style={{
              position: 'absolute', top: '4px',
              left: form.on_line ? '38px' : '4px',
              width: '28px', height: '28px', borderRadius: '50%',
              backgroundColor: '#fff',
              transition: 'left 0.3s ease',
              boxShadow: '0 2px 6px rgba(0,0,0,0.3)',
            }} />
            <span style={{
              position: 'absolute', top: '50%', transform: 'translateY(-50%)',
              left: form.on_line ? '6px' : 'auto', right: form.on_line ? 'auto' : '6px',
              fontSize: '0.55rem', fontWeight: 800, color: '#fff',
              transition: 'all 0.3s ease',
            }}>
              {form.on_line ? 'ON' : 'OFF'}
            </span>
          </button>
        </div>

        {/* Status badges */}
        <div style={{ display: 'flex', gap: '8px', marginTop: '12px', flexWrap: 'wrap' }}>
          <span className={`badge ${form.on_line ? 'badge-success' : 'badge-danger'}`} style={{ fontSize: '0.6rem' }}>
            {form.on_line ? '🌐 VITRINE EN LIGNE' : '🔒 DASHBOARD UNIQUEMENT'}
          </span>
          <span className="badge badge-info" style={{ fontSize: '0.6rem' }}>
            Route "/" → {form.on_line ? '<Vitrine />' : '<Navigate to="/login" />'}
          </span>
        </div>
      </div>

      {/* Configuration form */}
      <form onSubmit={handleSave}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>

          {/* §2 Paramètres des commissions */}
          <div className="glass-card" style={{ padding: '16px' }}>
            <h3 style={{ fontSize: '0.88rem', fontWeight: 800, marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <FiPercent style={{ color: 'hsl(var(--accent-color))' }} />
              §2.3 — Algorithme des Commissions (CM)
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.68rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px', textTransform: 'uppercase' }}>
                  Taux de Commission par Défaut (%)
                </label>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <input
                    type="number" step="1" min="0" max="100"
                    value={form.default_commission_rate != null ? Math.round(parseFloat(String(form.default_commission_rate)) * 100) : ''}
                    onChange={e => set('default_commission_rate', (parseFloat(e.target.value) / 100).toFixed(2))}
                    className="form-input"
                    style={{ height: '34px', fontSize: '0.8rem', padding: '0 10px' }}
                  />
                  <span style={{ fontSize: '0.8rem', color: 'hsl(var(--text-secondary))', fontWeight: 700 }}>%</span>
                </div>
                <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', marginTop: '3px' }}>Défaut : 25 — applicable à tous les clients sans taux personnalisé</div>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.68rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px', textTransform: 'uppercase' }}>
                  Taux Cotisation Sociale (%)
                </label>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <input
                    type="number" step="0.01"
                    value={form.social_deduction_rate ?? ''}
                    onChange={e => set('social_deduction_rate', e.target.value)}
                    className="form-input"
                    style={{ height: '34px', fontSize: '0.8rem', padding: '0 10px' }}
                  />
                  <span style={{ fontSize: '0.72rem', color: 'hsl(var(--text-secondary))', whiteSpace: 'nowrap' }}>
                    = {((parseFloat(String(form.social_deduction_rate)) || 0) * 100).toFixed(0)}%
                  </span>
                </div>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.68rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px', textTransform: 'uppercase' }}>
                  Taux Remise Annuelle (§2.3.3)
                </label>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <input
                    type="number" step="0.001"
                    value={form.annual_bonus_rate ?? ''}
                    onChange={e => set('annual_bonus_rate', e.target.value)}
                    className="form-input"
                    style={{ height: '34px', fontSize: '0.8rem', padding: '0 10px' }}
                  />
                  <span style={{ fontSize: '0.72rem', color: 'hsl(var(--text-secondary))', whiteSpace: 'nowrap' }}>
                    = {((parseFloat(String(form.annual_bonus_rate)) || 0) * 100).toFixed(1)}%
                  </span>
                </div>
                <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', marginTop: '3px' }}>Remise Annuelle = 0.025 × Volume Total Pains</div>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.68rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px', textTransform: 'uppercase' }}>
                  Frais d'Imprimés (FC)
                </label>
                <input
                  type="number"
                  value={form.print_fee ?? ''}
                  onChange={e => set('print_fee', e.target.value)}
                  className="form-input"
                  style={{ height: '34px', fontSize: '0.8rem', padding: '0 10px' }}
                />
              </div>
            </div>
          </div>

          {/* §2.2 + §3.1 Seuils et rendements */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div className="glass-card" style={{ padding: '16px' }}>
              <h3 style={{ fontSize: '0.88rem', fontWeight: 800, marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <FiDollarSign style={{ color: 'hsl(var(--accent-color))' }} />
                §2.2 — Seuils de Segmentation Clients
              </h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.68rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px', textTransform: 'uppercase' }}>
                    Plafond de Dette — Client à Risque (FC)
                  </label>
                  <input
                    type="number"
                    value={form.debt_ceiling ?? ''}
                    onChange={e => set('debt_ceiling', e.target.value)}
                    className="form-input"
                    style={{ height: '34px', fontSize: '0.8rem', padding: '0 10px' }}
                  />
                  <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', marginTop: '3px' }}>
                    Au-delà → catégorie RISK + alerte rouge
                  </div>
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.68rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px', textTransform: 'uppercase' }}>
                    Seuil "Meilleur Client" (nb pains)
                  </label>
                  <input
                    type="number"
                    value={form.best_client_threshold ?? ''}
                    onChange={e => set('best_client_threshold', Number(e.target.value))}
                    className="form-input"
                    style={{ height: '34px', fontSize: '0.8rem', padding: '0 10px' }}
                  />
                  <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', marginTop: '3px' }}>
                    Volume cumulé ≥ seuil → catégorie BEST
                  </div>
                </div>
              </div>
            </div>

            <div className="glass-card" style={{ padding: '16px' }}>
              <h3 style={{ fontSize: '0.88rem', fontWeight: 800, marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <FiPackage style={{ color: 'hsl(var(--accent-color))' }} />
                §3.1 — Valeur Théorique par Sac de Farine
              </h3>
              <div>
                <label style={{ display: 'block', fontSize: '0.68rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px', textTransform: 'uppercase' }}>
                  Valeur FC théorique / sac de farine
                </label>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <input
                    type="number"
                    value={form.sac_value_fc ?? ''}
                    onChange={e => set('sac_value_fc', Number(e.target.value))}
                    className="form-input"
                    style={{ height: '34px', fontSize: '0.8rem', padding: '0 10px' }}
                  />
                  <span style={{ fontSize: '0.72rem', color: 'hsl(var(--text-secondary))', whiteSpace: 'nowrap' }}>FC</span>
                </div>
                <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', marginTop: '4px', lineHeight: 1.5 }}>
                  Défaut : <strong>200 000 FC</strong> / sac.
                  <br />Équivalences : {(form.sac_value_fc || 200000).toLocaleString('fr-FR')} FC =
                  {' '}<strong>{Math.round((form.sac_value_fc || 200000) / 1000)}</strong> pains 1000 FC
                  {' '}= <strong>{Math.round((form.sac_value_fc || 200000) / 500)}</strong> pains 500 FC
                  {' '}= <strong>{Math.round((form.sac_value_fc || 200000) / 300)}</strong> pains 300 FC
                </div>
              </div>
            </div>

            <div className="glass-card" style={{ padding: '16px' }}>
              <h3 style={{ fontSize: '0.88rem', fontWeight: 800, marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <FiAlertTriangle style={{ color: 'hsl(var(--accent-color))' }} />
                Ventes Passées (saisie rétroactive)
              </h3>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: '0.78rem', fontWeight: 700 }}>
                    Autoriser la saisie de ventes datées (passées)
                  </div>
                  <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', marginTop: '3px', lineHeight: 1.5 }}>
                    Permet aux facturiers de choisir une date antérieure lors de l'enregistrement d'une
                    commande ou d'une livraison. Désactivé par défaut.
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => set('allow_backdated_sales', !form.allow_backdated_sales)}
                  style={{
                    position: 'relative', width: '48px', height: '26px',
                    borderRadius: '13px', border: 'none', cursor: 'pointer',
                    backgroundColor: form.allow_backdated_sales ? 'hsl(var(--color-success))' : 'hsl(var(--text-muted))',
                    transition: 'background-color 0.3s ease',
                    flexShrink: 0,
                  }}
                  title={form.allow_backdated_sales ? 'Cliquer pour désactiver' : 'Cliquer pour activer'}
                >
                  <span style={{
                    position: 'absolute', top: '3px',
                    left: form.allow_backdated_sales ? '25px' : '3px',
                    width: '20px', height: '20px', borderRadius: '50%',
                    backgroundColor: '#fff',
                    transition: 'left 0.3s ease',
                    boxShadow: '0 1px 4px rgba(0,0,0,0.3)',
                  }} />
                </button>
              </div>
              <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', marginTop: '10px' }}>
                N'oubliez pas d'enregistrer la configuration pour appliquer ce changement.
              </div>
            </div>
          </div>
        </div>

        {/* Save button */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '16px' }}>
          <button
            type="submit"
            disabled={isSaving}
            className="btn btn-primary"
            style={{ padding: '10px 28px', fontSize: '0.82rem', display: 'flex', alignItems: 'center', gap: '8px', opacity: isSaving ? 0.7 : 1 }}
          >
            {isSaving ? <FiRefreshCw style={{ animation: 'spin 1s linear infinite' }} /> : <FiSave />}
            {isSaving ? 'Enregistrement...' : 'Enregistrer la Configuration'}
          </button>
        </div>
      </form>

      {/* ── Grille Tarifaire — Prix des Pains ── */}
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

      {/* ── Catégories de Dépenses (§5.1.2) ── */}
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

      {/* ── Consommables (Production & Stocks — Stocks Consommables) ── */}
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

      {/* §6.4 COLIS Personnel */}
      <div className="glass-card" style={{ padding: '16px' }}>
        <h3 style={{ fontSize: '0.85rem', fontWeight: 800, marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <FiPackage style={{ color: 'hsl(var(--accent-color))' }} />
          §6.4 — Distribution COLIS Personnel
        </h3>

        {/* Filters */}
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14, alignItems: 'flex-end' }}>
          {colisNodes.length > 0 && (
            <div>
              <label style={{ fontSize: '0.7rem', color: 'hsl(var(--text-secondary))', display: 'block', marginBottom: 3 }}>Succursale</label>
              <select value={colisNode} onChange={e => setColisNode(e.target.value)}
                className="form-input" style={{ fontSize: '0.8rem', height: 32, padding: '0 8px' }}>
                {colisNodes.map(n => <option key={n.id} value={n.id}>{n.code} — {n.name}</option>)}
              </select>
            </div>
          )}
          <div>
            <label style={{ fontSize: '0.7rem', color: 'hsl(var(--text-secondary))', display: 'block', marginBottom: 3 }}>Année</label>
            <select value={colisYear} onChange={e => setColisYear(Number(e.target.value))}
              className="form-input" style={{ fontSize: '0.8rem', height: 32, padding: '0 8px' }}>
              {[2024, 2025, 2026, 2027].map(y => <option key={y} value={y}>{y}</option>)}
            </select>
          </div>
          <button onClick={() => setShowColisForm(v => !v)}
            className="btn btn-primary" style={{ padding: '5px 12px', fontSize: '0.78rem', height: 32, display: 'flex', alignItems: 'center', gap: 5 }}>
            <FiPlus />{showColisForm ? 'Annuler' : 'Ajouter'}
          </button>
        </div>

        {/* Add form */}
        {showColisForm && (
          <form onSubmit={handleColisSubmit} style={{ background: 'hsl(var(--bg-tertiary))', borderRadius: 8, padding: 14, marginBottom: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              <div style={{ flex: '2 1 200px' }}>
                <label style={{ fontSize: '0.7rem', color: 'hsl(var(--text-secondary))', display: 'block', marginBottom: 3 }}>Bénéficiaire *</label>
                <input value={colisLabel} onChange={e => setColisLabel(e.target.value)} placeholder="ex: Boulanger 1" required
                  className="form-input" style={{ fontSize: '0.82rem', height: 32, width: '100%', padding: '0 8px' }} />
              </div>
              {[
                { label: 'Sacs riz', val: colisRiceSacks, set: setColisRiceSacks },
                { label: 'Valeur riz (FC)', val: colisRiceValue, set: setColisRiceValue },
                { label: 'Viande (kg)', val: colisMeatKg, set: setColisMeatKg },
                { label: 'Valeur viande (FC)', val: colisMeatValue, set: setColisMeatValue },
                { label: 'Espèces (FC)', val: colisCash, set: setColisCash },
              ].map(f => (
                <div key={f.label} style={{ flex: '1 1 110px' }}>
                  <label style={{ fontSize: '0.7rem', color: 'hsl(var(--text-secondary))', display: 'block', marginBottom: 3 }}>{f.label}</label>
                  <input type="number" step="0.01" min="0" value={f.val} onChange={e => f.set(e.target.value)} placeholder="0"
                    className="form-input" style={{ fontSize: '0.82rem', height: 32, width: '100%', padding: '0 8px' }} />
                </div>
              ))}
            </div>
            <div>
              <label style={{ fontSize: '0.7rem', color: 'hsl(var(--text-secondary))', display: 'block', marginBottom: 3 }}>Notes</label>
              <input value={colisNotes} onChange={e => setColisNotes(e.target.value)} placeholder="optionnel"
                className="form-input" style={{ fontSize: '0.82rem', height: 32, width: '100%', padding: '0 8px' }} />
            </div>
            {colisError && <div style={{ color: 'hsl(var(--color-danger))', fontSize: '0.78rem' }}>{colisError}</div>}
            <div style={{ display: 'flex', gap: 8 }}>
              <button type="submit" disabled={colisSubmitting} className="btn btn-primary" style={{ padding: '5px 16px', fontSize: '0.8rem' }}>
                {colisSubmitting ? 'Enregistrement…' : 'Enregistrer'}
              </button>
              <button type="button" onClick={() => setShowColisForm(false)} className="btn btn-secondary" style={{ padding: '5px 12px', fontSize: '0.8rem' }}>
                Annuler
              </button>
            </div>
          </form>
        )}

        {/* Table */}
        {colisLoading ? (
          <div style={{ textAlign: 'center', padding: 16, color: 'hsl(var(--text-secondary))', fontSize: '0.82rem' }}>Chargement…</div>
        ) : colisList.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 16, color: 'hsl(var(--text-muted))', fontSize: '0.82rem' }}>
            Aucune distribution COLIS pour {colisYear}.
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' }}>
              <thead>
                <tr style={{ background: 'hsl(var(--bg-tertiary))', borderBottom: '2px solid hsl(var(--border-color))' }}>
                  {['Bénéficiaire', 'Riz (sacs)', 'Valeur riz', 'Viande (kg)', 'Valeur viande', 'Espèces', 'TOTAL', ''].map(h => (
                    <th key={h} style={{ padding: '6px 8px', textAlign: h === 'Bénéficiaire' || h === '' ? 'left' : 'right', fontWeight: 600, color: 'hsl(var(--text-secondary))', fontSize: '0.68rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {colisList.map(row => (
                  <tr key={row.id} style={{ borderBottom: '1px solid hsl(var(--border-color))' }}>
                    <td style={{ padding: '6px 8px', fontWeight: 600 }}>{row.beneficiary_label}</td>
                    <td style={{ padding: '6px 8px', textAlign: 'right' }}>{parseFloat(row.rice_sacks).toLocaleString('fr-FR')}</td>
                    <td style={{ padding: '6px 8px', textAlign: 'right' }}>{parseFloat(row.rice_value).toLocaleString('fr-FR')}</td>
                    <td style={{ padding: '6px 8px', textAlign: 'right' }}>{parseFloat(row.meat_kg).toLocaleString('fr-FR')}</td>
                    <td style={{ padding: '6px 8px', textAlign: 'right' }}>{parseFloat(row.meat_value).toLocaleString('fr-FR')}</td>
                    <td style={{ padding: '6px 8px', textAlign: 'right' }}>{parseFloat(row.cash_amount).toLocaleString('fr-FR')}</td>
                    <td style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 800, color: 'hsl(var(--accent-color))' }}>{parseFloat(row.total_value).toLocaleString('fr-FR')} FC</td>
                    <td style={{ padding: '6px 8px' }}>
                      <button onClick={() => handleColisDelete(row.id)} style={{ padding: '2px 6px', borderRadius: 4, border: '1px solid hsl(var(--color-danger)/0.3)', background: 'hsl(var(--color-danger)/0.06)', color: 'hsl(var(--color-danger))', cursor: 'pointer', fontSize: '0.7rem' }}>
                        <FiTrash2 />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr style={{ background: 'hsl(var(--bg-tertiary))', borderTop: '2px solid hsl(var(--border-color))', fontWeight: 800 }}>
                  <td style={{ padding: '6px 8px' }}>{colisList.length} bénéficiaire(s)</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right' }}>{colisList.reduce((s, r) => s + parseFloat(r.rice_sacks), 0).toLocaleString('fr-FR')}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right' }}>{colisList.reduce((s, r) => s + parseFloat(r.rice_value), 0).toLocaleString('fr-FR')}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right' }}>{colisList.reduce((s, r) => s + parseFloat(r.meat_kg), 0).toLocaleString('fr-FR')}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right' }}>{colisList.reduce((s, r) => s + parseFloat(r.meat_value), 0).toLocaleString('fr-FR')}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right' }}>{colisList.reduce((s, r) => s + parseFloat(r.cash_amount), 0).toLocaleString('fr-FR')}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', color: 'hsl(var(--accent-color))' }}>{colisList.reduce((s, r) => s + parseFloat(r.total_value), 0).toLocaleString('fr-FR')} FC</td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </div>

      {/* §6.3 Info readonly */}
      <div className="glass-card" style={{ padding: '16px' }}>
        <h3 style={{ fontSize: '0.85rem', fontWeight: 800, marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <FiSliders style={{ color: 'hsl(var(--accent-color))' }} />
          §6.3 — Architecture Décentralisée (Lecture seule)
        </h3>
        <div className="kpi-grid" style={{ gap: '12px', fontSize: '0.72rem' }}>
          {[
            { label: 'Stratégie IDs', value: 'UUIDv4 + node_origin', desc: 'Évite les collisions en mode offline' },
            { label: 'Protocol Sync', value: 'is_synced = True/False', desc: 'Poussé vers Cloud dès connexion détectée' },
            { label: 'Sécurité Cashbook', value: 'SHA-256 Chain', desc: 'Blockchain immuable — Blockchain.tsx' },
          ].map(item => (
            <div key={item.label} style={{ padding: '10px 12px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)' }}>
              <div style={{ fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '2px', textTransform: 'uppercase', fontSize: '0.6rem' }}>{item.label}</div>
              <div style={{ fontWeight: 800, color: 'hsl(var(--accent-color))', fontFamily: 'monospace', marginBottom: '2px' }}>{item.value}</div>
              <div style={{ color: 'hsl(var(--text-muted))', fontSize: '0.62rem' }}>{item.desc}</div>
            </div>
          ))}
        </div>
      </div>

    </div>
  );
};
