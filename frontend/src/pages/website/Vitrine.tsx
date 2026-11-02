import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useThemeStore } from '@/store/themeStore';
import {
  FiPhone, FiMapPin, FiLogIn, FiAward, FiSun, FiMoon,
  FiCoffee, FiCpu, FiGrid, FiCheckCircle
} from 'react-icons/fi';
import { coreApi } from '@/api/services';

// Static per-category copy — official prices come from the Configuration price grid (BreadPrice)
const CATEGORY_META: Record<string, { desc: string; weight: string }> = {
  MINI:    { desc: 'Idéal pour le petit-déjeuner quotidien.', weight: '120g' },
  MOYEN:   { desc: 'Le format le plus populaire des familles.', weight: '180g' },
  GRAND:   { desc: 'Rendement et moelleux optimisés.', weight: '240g' },
  PREMIUM: { desc: 'Farine blanche de qualité supérieure.', weight: '500g' },
};
const CATEGORY_ORDER = ['MINI', 'MOYEN', 'GRAND', 'PREMIUM'];

export const Vitrine: React.FC = () => {
  const { theme, setTheme } = useThemeStore();
  const [activeTab, setActiveTab] = useState<'catalog' | 'nodes' | 'calculator'>('catalog');
  
  // Interactive nodes list
  const nodes = [
    { code: 'K1', name: 'TABORA', address: '49, Avenue Tabora, Mbanza-Ngungu', manager: 'Jean Mabanza', phone: '+243 851 992 001', status: 'Actif' },
    { code: 'K2', name: 'COQ', address: 'Avenue Coq, Mbanza-Ngungu', manager: 'Albert Nsilu', phone: '+243 851 992 002', status: 'Actif' },
    { code: 'K3', name: 'ATHENEE', address: 'Quartier Athénée, Mbanza-Ngungu', manager: 'Marie Luzolo', phone: '+243 851 992 003', status: 'Actif' },
    { code: 'K4', name: 'LOMA', address: 'Quartier Loma, Mbanza-Ngungu', manager: 'Simon Kimbangu', phone: '+243 851 992 004', status: 'Actif' },
    { code: 'K5', name: 'MPIANGU', address: 'Quartier Mpiangu, Mbanza-Ngungu', manager: 'Therese Kiese', phone: '+243 851 992 005', status: 'Actif' },
    { code: 'K6', name: 'ZADIM', address: 'Quartier Zadim, Mbanza-Ngungu', manager: 'Pierre Kanza', phone: '+243 851 992 006', status: 'Actif' },
    { code: 'B1', name: 'KUMBI', address: 'Quartier Kumbi, Mbanza-Ngungu', manager: 'Michel Nzuzi', phone: '+243 851 992 007', status: 'Actif' },
    { code: 'B2', name: 'MPETE', address: 'Quartier Mpete, Mbanza-Ngungu', manager: 'Florentin Nkusu', phone: '+243 851 992 008', status: 'Actif' },
  ];

  // Fallback shown until the official Configuration price grid has loaded
  const [breadCategories, setBreadCategories] = useState([
    { label: 'Pain Standard Mini', price: 300, weight: '120g', desc: 'Idéal pour le petit-déjeuner quotidien.', category: 'MINI' },
    { label: 'Pain Standard Moyen', price: 400, weight: '180g', desc: 'Le format le plus populaire des familles.', category: 'MOYEN' },
    { label: 'Pain Standard Grand', price: 500, weight: '240g', desc: 'Rendement et moelleux optimisés.', category: 'GRAND' },
    { label: 'Pain Premium / Spécial', price: 1000, weight: '500g', desc: 'Farine blanche de qualité supérieure.', category: 'PREMIUM' },
  ]);

  useEffect(() => {
    coreApi.breadPrices.list()
      .then(res => {
        const active = (res.data || []).filter(bp => bp.is_active);
        if (active.length === 0) return;
        const sorted = [...active].sort(
          (a, b) => CATEGORY_ORDER.indexOf(a.category) - CATEGORY_ORDER.indexOf(b.category)
        );
        setBreadCategories(sorted.map(bp => ({
          label: bp.label,
          price: bp.unit_price,
          weight: CATEGORY_META[bp.category]?.weight || '',
          desc: CATEGORY_META[bp.category]?.desc || '',
          category: bp.category,
        })));
      })
      .catch(() => { /* keep fallback grid on error */ });
  }, []);

  // Selected node for showcase
  const [selectedNodeCode, setSelectedNodeCode] = useState<string>('K1');
  const currentNode = nodes.find(n => n.code === selectedNodeCode) || nodes[0];

  // Interactive Calculator State
  const [calcMini, setCalcMini] = useState<number>(0);
  const [calcMoyen, setCalcMoyen] = useState<number>(0);
  const [calcGrand, setCalcGrand] = useState<number>(0);
  const [calcPremium, setCalcPremium] = useState<number>(0);

  // Business formulas for commissions (25% or 30% if cumulative quantities are large)
  const priceFor = (cat: string) => breadCategories.find(b => b.category === cat)?.price ?? 0;
  const totalQuantity = calcMini + calcMoyen + calcGrand + calcPremium;
  const rawSubtotal = (calcMini * priceFor('MINI')) + (calcMoyen * priceFor('MOYEN')) + (calcGrand * priceFor('GRAND')) + (calcPremium * priceFor('PREMIUM'));

  // Rule: If total quantity exceeds 100 pains, commission rate is 30%, else 25% (standard dealer commission)
  const commissionRate = totalQuantity >= 100 ? 0.30 : 0.25;
  const calculatedCommission = rawSubtotal * commissionRate;
  const netPayable = rawSubtotal - calculatedCommission;

  return (
    <div style={{
      minHeight: '100vh',
      backgroundColor: 'hsl(var(--bg-primary))',
      color: 'hsl(var(--text-primary))',
      display: 'flex',
      flexDirection: 'column',
      transition: 'background-color 0.3s ease'
    }}>
      {/* Header */}
      <header style={{
        height: '80px',
        borderBottom: '1px solid hsl(var(--border-color))',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 40px',
        backgroundColor: 'hsl(var(--bg-secondary) / 0.8)',
        backdropFilter: 'blur(8px)',
        position: 'sticky',
        top: 0,
        zIndex: 10
      }}>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <span style={{ fontSize: '1.6rem', fontWeight: 800, color: 'hsl(var(--accent-color))', letterSpacing: '0.05em', transition: 'color 0.3s ease' }}>
            ETS. KIESE
          </span>
          <span style={{ fontSize: '0.75rem', color: 'hsl(var(--text-muted))', fontWeight: 700, textTransform: 'uppercase' }}>
            Boulangeries Connectées
          </span>
        </div>

        {/* Navigation Tabs */}
        <div style={{ display: 'flex', gap: '8px', backgroundColor: 'hsl(var(--bg-tertiary))', padding: '4px', borderRadius: 'var(--radius-md)', border: '1px solid hsl(var(--border-color))' }}>
          <button 
            onClick={() => setActiveTab('catalog')}
            style={{
              background: activeTab === 'catalog' ? 'hsl(var(--accent-glow))' : 'transparent',
              color: activeTab === 'catalog' ? 'hsl(var(--accent-color))' : 'hsl(var(--text-secondary))',
              border: 'none',
              padding: '8px 16px',
              borderRadius: '6px',
              fontWeight: 700,
              fontSize: '0.85rem',
              cursor: 'pointer',
              transition: 'all 0.2s ease'
            }}
          >
            <FiAward style={{ marginRight: '6px', verticalAlign: 'middle' }} />
            Grille de Prix
          </button>
          <button 
            onClick={() => setActiveTab('nodes')}
            style={{
              background: activeTab === 'nodes' ? 'hsl(var(--accent-glow))' : 'transparent',
              color: activeTab === 'nodes' ? 'hsl(var(--accent-color))' : 'hsl(var(--text-secondary))',
              border: 'none',
              padding: '8px 16px',
              borderRadius: '6px',
              fontWeight: 700,
              fontSize: '0.85rem',
              cursor: 'pointer',
              transition: 'all 0.2s ease'
            }}
          >
            <FiGrid style={{ marginRight: '6px', verticalAlign: 'middle' }} />
            Boulangeries
          </button>
          <button 
            onClick={() => setActiveTab('calculator')}
            style={{
              background: activeTab === 'calculator' ? 'hsl(var(--accent-glow))' : 'transparent',
              color: activeTab === 'calculator' ? 'hsl(var(--accent-color))' : 'hsl(var(--text-secondary))',
              border: 'none',
              padding: '8px 16px',
              borderRadius: '6px',
              fontWeight: 700,
              fontSize: '0.85rem',
              cursor: 'pointer',
              transition: 'all 0.2s ease'
            }}
          >
            <FiCpu style={{ marginRight: '6px', verticalAlign: 'middle' }} />
            Simulateur CM
          </button>
        </div>
        
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          {/* Public Theme Switcher Widget */}
          <div style={{ 
            display: 'flex', 
            alignItems: 'center', 
            backgroundColor: 'hsl(var(--bg-tertiary))', 
            border: '1px solid hsl(var(--border-color))', 
            borderRadius: 'var(--radius-md)',
            padding: '2px'
          }}>
            <button 
              onClick={() => setTheme('dark')} 
              title="Thème Sombre"
              style={{
                border: 'none',
                background: theme === 'dark' ? 'hsl(var(--accent-glow))' : 'transparent',
                color: theme === 'dark' ? 'hsl(var(--accent-color))' : 'hsl(var(--text-secondary))',
                padding: '6px 8px',
                borderRadius: '6px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center'
              }}
            >
              <FiMoon />
            </button>
            <button 
              onClick={() => setTheme('light')} 
              title="Thème Clair"
              style={{
                border: 'none',
                background: theme === 'light' ? 'hsl(var(--accent-glow))' : 'transparent',
                color: theme === 'light' ? 'hsl(var(--accent-color))' : 'hsl(var(--text-secondary))',
                padding: '6px 8px',
                borderRadius: '6px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center'
              }}
            >
              <FiSun />
            </button>
            <button 
              onClick={() => setTheme('classic')} 
              title="Thème Classic (Boulangerie)"
              style={{
                border: 'none',
                background: theme === 'classic' ? 'hsl(var(--accent-glow))' : 'transparent',
                color: theme === 'classic' ? 'hsl(var(--accent-color))' : 'hsl(var(--text-secondary))',
                padding: '6px 8px',
                borderRadius: '6px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center'
              }}
            >
              <FiCoffee />
            </button>
          </div>

          <Link to="/login" className="btn btn-primary" style={{ padding: '10px 20px', fontSize: '0.85rem' }}>
            <FiLogIn />
            <span>Portail Agents</span>
          </Link>
        </div>
      </header>

      {/* Hero Showcase banner */}
      <main style={{ flex: 1, padding: '60px 40px', maxWidth: '1200px', margin: '0 auto', width: '100%' }}>
        <div style={{ textAlign: 'center', marginBottom: '60px' }} className="animate-fade-in">
          <h1 style={{ fontSize: '3.2rem', fontWeight: 800, marginBottom: '16px', lineHeight: 1.15, letterSpacing: '-0.03em' }}>
            Qualité, Moelleux et <span style={{ color: 'hsl(var(--accent-color))', transition: 'color 0.3s ease' }}>Régularité Irréprochable</span>
          </h1>
          <p style={{ color: 'hsl(var(--text-secondary))', fontSize: '1.2rem', maxWidth: '750px', margin: '0 auto' }}>
            Un réseau distribué unique de 8 boulangeries modernes interconnectées au Kongo-Central, engagé pour la sécurité alimentaire et l'approvisionnement des populations.
          </p>
        </div>

        {/* Tab Content 1: Catalog showcase */}
        {activeTab === 'catalog' && (
          <div className="animate-fade-in">
            <h2 style={{ fontSize: '1.8rem', fontWeight: 800, marginBottom: '24px', textAlign: 'center', letterSpacing: '-0.02em' }}>
              Tarification Consolidée Officielle (Toutes Zones)
            </h2>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '24px', marginBottom: '60px' }}>
              {breadCategories.map((bread, index) => (
                <div key={index} className="glass-card" style={{
                  display: 'flex',
                  flexDirection: 'column',
                  padding: '32px 24px',
                  borderTop: '4px solid stroke',
                  borderColor: 'hsl(var(--accent-color))'
                }}>
                  <FiAward style={{ fontSize: '2.2rem', color: 'hsl(var(--accent-color))', marginBottom: '16px', transition: 'color 0.3s ease' }} />
                  <h3 style={{ fontSize: '1.25rem', fontWeight: 800, marginBottom: '8px' }}>{bread.label}</h3>
                  <p style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.85rem', marginBottom: '16px', flex: 1 }}>{bread.desc}</p>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
                    <span style={{ fontSize: '2rem', fontWeight: 800, color: 'hsl(var(--text-primary))' }}>{bread.price} FC</span>
                    <span style={{ color: 'hsl(var(--text-muted))', fontSize: '0.85rem', fontWeight: 600 }}>/ format {bread.weight}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Tab Content 2: Active Nodes Showcase */}
        {activeTab === 'nodes' && (
          <div className="animate-fade-in" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '32px', marginBottom: '60px' }}>
            {/* Grid Selectors */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <h3 style={{ fontSize: '1.2rem', fontWeight: 800, marginBottom: '12px' }}>
                Sélectionnez une Boulangerie
              </h3>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '10px' }}>
                {nodes.map((node) => (
                  <button
                    key={node.code}
                    onClick={() => setSelectedNodeCode(node.code)}
                    style={{
                      padding: '12px',
                      borderRadius: 'var(--radius-md)',
                      fontWeight: 800,
                      border: '1px solid',
                      borderColor: selectedNodeCode === node.code ? 'hsl(var(--accent-color))' : 'hsl(var(--border-color))',
                      backgroundColor: selectedNodeCode === node.code ? 'hsl(var(--accent-glow))' : 'hsl(var(--bg-tertiary))',
                      color: selectedNodeCode === node.code ? 'hsl(var(--accent-color))' : 'hsl(var(--text-primary))',
                      cursor: 'pointer',
                      transition: 'all 0.2s ease',
                      fontSize: '0.9rem'
                    }}
                  >
                    {node.code}
                  </button>
                ))}
              </div>
            </div>

            {/* Display Node Glass card */}
            <div className="glass-card" style={{ borderLeft: '4px solid hsl(var(--accent-color))' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
                <span className="badge badge-success">{currentNode.status}</span>
                <span style={{ fontWeight: 800, color: 'hsl(var(--accent-color))', fontSize: '1.2rem' }}>{currentNode.code}</span>
              </div>
              
              <h2 style={{ fontSize: '1.6rem', fontWeight: 800, marginBottom: '16px', letterSpacing: '-0.02em' }}>
                Boulangerie KIESE {currentNode.name}
              </h2>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', color: 'hsl(var(--text-secondary))', fontSize: '0.95rem' }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px' }}>
                  <FiMapPin style={{ flexShrink: 0, marginTop: '4px', color: 'hsl(var(--accent-color))' }} />
                  <span>{currentNode.address}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <FiCheckCircle style={{ color: 'hsl(var(--accent-color))' }} />
                  <span>Gérant : <strong>{currentNode.manager}</strong></span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <FiPhone style={{ color: 'hsl(var(--accent-color))' }} />
                  <span>Contact : <strong>{currentNode.phone}</strong></span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Tab Content 3: Commission Calculator */}
        {activeTab === 'calculator' && (
          <div className="animate-fade-in" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '32px', marginBottom: '60px' }}>
            {/* Inputs Panel */}
            <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <h3 style={{ fontSize: '1.2rem', fontWeight: 800, marginBottom: '8px' }}>
                Saisissez les Volumes de Vente
              </h3>
              
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {breadCategories.map((bread, index) => (
                  <div key={index} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '16px' }}>
                    <div style={{ display: 'flex', flexDirection: 'column' }}>
                      <span style={{ fontWeight: 700, fontSize: '0.9rem' }}>{bread.label}</span>
                      <span style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))' }}>Tarif: {bread.price} FC</span>
                    </div>
                    <input
                      type="number"
                      min="0"
                      className="form-input"
                      style={{ width: '100px', padding: '8px 12px', textAlign: 'center' }}
                      value={
                        index === 0 ? calcMini :
                        index === 1 ? calcMoyen :
                        index === 2 ? calcGrand :
                        calcPremium
                      }
                      onChange={(e) => {
                        const val = Math.max(0, parseInt(e.target.value) || 0);
                        if (index === 0) setCalcMini(val);
                        else if (index === 1) setCalcMoyen(val);
                        else if (index === 2) setCalcGrand(val);
                        else setCalcPremium(val);
                      }}
                    />
                  </div>
                ))}
              </div>
            </div>

            {/* Calculations Result Glass Card */}
            <div className="glass-card" style={{ borderLeft: '4px solid hsl(var(--accent-color))', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
              <div>
                <h3 style={{ fontSize: '1.2rem', fontWeight: 800, marginBottom: '20px' }}>
                  Synthèse Commission Client CM
                </h3>
                
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', fontSize: '0.95rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: 'hsl(var(--text-secondary))' }}>Quantité Totale :</span>
                    <strong style={{ color: 'hsl(var(--text-primary))' }}>{totalQuantity} pains</strong>
                  </div>
                  
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: 'hsl(var(--text-secondary))' }}>Montant Brut :</span>
                    <strong style={{ color: 'hsl(var(--text-primary))' }}>{rawSubtotal.toLocaleString('fr-CD')} FC</strong>
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ color: 'hsl(var(--text-secondary))' }}>Taux de Commission :</span>
                    <span className={`badge ${totalQuantity >= 100 ? 'badge-success' : 'badge-warning'}`} style={{ fontWeight: 800 }}>
                      {(commissionRate * 100).toFixed(0)}% {totalQuantity >= 100 ? 'Super-Détaillant' : 'Détaillant'}
                    </span>
                  </div>

                  <hr style={{ border: 'none', borderBottom: '1px solid hsl(var(--border-color))', margin: '8px 0' }} />

                  <div style={{ display: 'flex', justifyContent: 'space-between', color: 'hsl(var(--color-success))', fontWeight: 700 }}>
                    <span>Gain Commission Client :</span>
                    <span>+{calculatedCommission.toLocaleString('fr-CD')} FC</span>
                  </div>
                </div>
              </div>

              <div style={{ marginTop: '24px', padding: '16px', borderRadius: 'var(--radius-md)', backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', textAlign: 'center' }}>
                <span style={{ display: 'block', fontSize: '0.8rem', color: 'hsl(var(--text-secondary))', textTransform: 'uppercase', fontWeight: 700, marginBottom: '4px' }}>
                  Net à Payer en Caisse
                </span>
                <strong style={{ fontSize: '1.8rem', color: 'hsl(var(--accent-color))' }}>
                  {netPayable.toLocaleString('fr-CD')} FC
                </strong>
              </div>
            </div>
          </div>
        )}

        {/* Quick Contacts Footer Widget */}
        <div className="glass-card" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '32px', marginTop: '32px' }}>
          <div>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 800, marginBottom: '12px', color: 'hsl(var(--accent-color))' }}>
              Siège Administratif Consolidé
            </h3>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px', color: 'hsl(var(--text-secondary))', fontSize: '0.9rem' }}>
              <FiMapPin style={{ flexShrink: 0, marginTop: '3px' }} />
              <span>Numéro 49 de l'Avenue Tabora, Commune de Mbanza-Ngungu, Kongo-Central, RDC</span>
            </div>
          </div>
          <div>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 800, marginBottom: '12px', color: 'hsl(var(--accent-color))' }}>
              Secrétariat & Direction
            </h3>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', color: 'hsl(var(--text-secondary))', fontSize: '0.9rem' }}>
              <FiPhone style={{ flexShrink: 0 }} />
              <span>+243 851 992 947 (Secrétaire de Direction)</span>
            </div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer style={{
        padding: '32px 40px',
        borderTop: '1px solid hsl(var(--border-color))',
        backgroundColor: 'hsl(var(--bg-secondary))',
        textAlign: 'center',
        fontSize: '0.85rem',
        color: 'hsl(var(--text-muted))',
        fontWeight: 600
      }}>
        <span>© 2026 ETS. KIESE — Système Central de Gestion en Réseau. RCCM: 021 – A-650 | Id. Nat: 10 – F4300 -N85947U | N° Impôt: A1902266K.</span>
      </footer>
    </div>
  );
};
