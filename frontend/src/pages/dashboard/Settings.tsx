import React, { useState, useEffect } from 'react';
import { FiSettings, FiAlertTriangle, FiCheckCircle, FiSliders, FiTrash2, FiShield } from 'react-icons/fi';
import { coreApi, productionApi, SiteConfig, BreadPrice, ExpenseCategory, ConsumableType, BakeryNode } from '@/api/services';
import { getErrorDetail } from '@/api/errors';
import { useAuthStore } from '@/store/authStore';
import { ResetDataModal } from '@/components/settings/ResetDataModal';
import { BreadPricesSection } from '@/components/settings/BreadPricesSection';
import { ExpenseCategoriesSection } from '@/components/settings/ExpenseCategoriesSection';
import { ConsumableTypesSection } from '@/components/settings/ConsumableTypesSection';
import { ColisSection } from '@/components/settings/ColisSection';
import { OnlineToggleCard } from '@/components/settings/OnlineToggleCard';
import { ConfigForm } from '@/components/settings/ConfigForm';

export const Settings: React.FC = () => {
  const { user } = useAuthStore();

  const [config, setConfig] = useState<SiteConfig | null>(null);
  const [form, setForm] = useState<Partial<SiteConfig>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [saveMsg, setSaveMsg] = useState('');

  // Listes chargées une fois puis gérées par les sous-composants
  const [breadPrices, setBreadPrices] = useState<BreadPrice[]>([]);
  const [expenseCategories, setExpenseCategories] = useState<ExpenseCategory[]>([]);
  const [consumableTypes, setConsumableTypes] = useState<ConsumableType[]>([]);
  const [nodes, setNodes] = useState<BakeryNode[]>([]);

  // BUG-150 : réinitialisation globale des données (Superuser)
  const [showResetModal, setShowResetModal] = useState(false);

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
      setNodes(nodesRes.data);
      setExpenseCategories(ecRes.data);
      setConsumableTypes(ctRes.data);
    }).catch(() => {}).finally(() => setIsLoading(false));
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

      <OnlineToggleCard form={form} updatedAt={config?.updated_at} onToggle={handleToggleOnline} />

      {/* Configuration form */}
      <ConfigForm form={form} set={set} isSaving={isSaving} onSubmit={handleSave} />

      <BreadPricesSection initial={breadPrices} />

      <ExpenseCategoriesSection initial={expenseCategories} />

      <ConsumableTypesSection initial={consumableTypes} />

      <ColisSection nodes={nodes} defaultNode={nodes[0]?.id ?? user?.node ?? ''} />

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

      {/* BUG-150 : Réinitialisation globale des données — Superuser uniquement */}
      {user?.is_superuser && (
        <div className="glass-card" style={{ padding: '16px', borderLeft: '4px solid hsl(var(--color-danger))' }}>
          <h3 style={{ fontSize: '0.85rem', fontWeight: 800, marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px', color: 'hsl(var(--color-danger))' }}>
            <FiShield /> Zone dangereuse — Superuser
          </h3>
          <p style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))', marginBottom: '12px', maxWidth: '640px' }}>
            Supprime définitivement toutes les données transactionnelles (ventes, production,
            trésorerie, commissions, finance, blockchain…). La configuration, les boulangeries, les
            utilisateurs et la liste des clients sont conservés (soldes clients remis à zéro).
          </p>
          <button
            type="button"
            onClick={() => setShowResetModal(true)}
            className="btn"
            style={{
              padding: '8px 16px', fontSize: '0.78rem', fontWeight: 800,
              display: 'flex', alignItems: 'center', gap: '6px',
              backgroundColor: 'hsl(var(--color-danger))', color: '#fff', border: 'none', cursor: 'pointer',
            }}
          >
            <FiTrash2 /> Réinitialiser les données
          </button>
        </div>
      )}

      <ResetDataModal isOpen={showResetModal} onClose={() => setShowResetModal(false)} />

    </div>
  );
};