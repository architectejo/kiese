import React, { useEffect, useState } from 'react';
import { FiCalendar } from 'react-icons/fi';
import { productionApi, BreadStock, BreadStockByDate } from '@/api/services';
import { getErrorDetail } from '@/api/errors';
import { Modal } from '@/components/shared/Modal';
import { CalendarPicker } from '@/components/shared/CalendarPicker';
import { useWorkDate } from '@/store/workDateStore';

// BUG-145 (docs/qa/REGISTRE_BUGS.md, demande client remarque.md l.397) : « Stock Pains
// Actuel » devient « Stock Pains du Jour » et peut être consulté pour n'importe quel jour
// passé, et plus seulement « maintenant ». Composant extrait de Production.tsx (CLAUDE.md
// §4 : extraction obligatoire des sous-composants ajoutés à une page de plus de ~1000 lignes).
// Contrat API : docs/qa/rapports/dev-backend-2026-11-10-bug144-stock-pains-par-jour.md.

const formatFC = (n: number) => n.toLocaleString('fr-FR') + ' FC';

const formatDateLong = (iso: string): string => {
  const [y, m, d] = iso.split('-').map(Number);
  const date = new Date(y, (m || 1) - 1, d || 1);
  return date.toLocaleDateString('fr-FR', { day: '2-digit', month: 'long', year: 'numeric' });
};

export interface StockDuJourSectionProps {
  /** Date sélectionnée (AAAA-MM-JJ), contrôlée par le parent — la même date pilote
   *  aussi « Historique des Fournées » dans Production.tsx (un seul sélecteur pour les deux). */
  selectedDate: string;
  onSelectDate: (iso: string) => void;
  /** Solde courant complet (avec détail produit/reçu/sorti/disposé), déjà chargé par
   *  Production.tsx — réutilisé tel quel quand `selectedDate` est aujourd'hui, pour ne pas
   *  dupliquer un appel réseau et conserver le clic « voir détail » existant. */
  liveBreadStocks: BreadStock[];
  /** Code ou identifiant de la boulangerie actuellement affichée (même valeur que les
   *  autres appels scopés de Production.tsx), utilisé pour l'endpoint `by-date` sur un jour passé. */
  nodeFilter?: string;
  currentNodeLabel?: string;
  onSelectBreadStock: (bs: BreadStock) => void;
}

export const StockDuJourSection: React.FC<StockDuJourSectionProps> = ({
  selectedDate, onSelectDate, liveBreadStocks, nodeFilter, currentNodeLabel, onSelectBreadStock,
}) => {
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [snapshot, setSnapshot] = useState<BreadStockByDate | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // BUG-161 (F3) : « jour courant » = journée de travail du serveur (repli : date locale).
  const workDate = useWorkDate();
  const isToday = selectedDate === workDate;

  useEffect(() => {
    if (isToday) {
      // Jour courant : la liste complète (avec détail) vient déjà du chargement principal
      // de Production.tsx — aucun appel réseau supplémentaire nécessaire.
      setSnapshot(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    productionApi.breadStocks.byDate({ node: nodeFilter, date: selectedDate })
      .then(res => { if (!cancelled) setSnapshot(res.data); })
      .catch(err => {
        if (!cancelled) {
          setSnapshot(null);
          setError(getErrorDetail(err, 'Erreur lors du chargement du stock pains de ce jour.'));
        }
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDate, nodeFilter, isToday]);

  return (
    <div className="glass-card" style={{ padding: '12px 14px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px', marginBottom: '8px' }}>
        <h3 style={{ fontSize: '0.8rem', fontWeight: 800 }}>
          Stock Pains du Jour
          <span style={{ fontWeight: 400, color: 'hsl(var(--text-secondary))', marginLeft: '6px', fontSize: '0.68rem' }}>
            — {formatDateLong(selectedDate)}
          </span>
          {currentNodeLabel && <span className="badge badge-info" style={{ fontSize: '0.6rem', marginLeft: '8px' }}>{currentNodeLabel}</span>}
          {!isToday && snapshot?.source === 'snapshot' && (
            <span className="badge badge-warning" style={{ fontSize: '0.56rem', marginLeft: '6px' }} title="Reconstitué à partir des clôtures d'équipe de ce jour-là, pas le solde en temps réel.">
              Historique (reconstitué)
            </span>
          )}
        </h3>
        <button
          type="button"
          onClick={() => setCalendarOpen(true)}
          className="btn btn-secondary"
          style={{ height: '28px', fontSize: '0.68rem', display: 'flex', alignItems: 'center', gap: '5px', padding: '4px 9px' }}
        >
          <FiCalendar size={12} />
          <span>Choisir un jour</span>
        </button>
      </div>

      {isToday ? (
        liveBreadStocks.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '12px', color: 'hsl(var(--text-muted))', fontSize: '0.7rem' }}>
            Aucun stock de pains suivi pour l'instant.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {liveBreadStocks.map(bs => (
              <div
                key={bs.id}
                onClick={() => onSelectBreadStock(bs)}
                style={{ display: 'grid', gridTemplateColumns: '1fr auto', alignItems: 'center', padding: '5px 8px', borderRadius: 'var(--radius-sm)', border: '1px solid hsl(var(--border-color))', fontSize: '0.68rem', cursor: 'pointer', transition: 'background 0.15s' }}
                onMouseEnter={e => (e.currentTarget.style.background = 'hsl(var(--bg-tertiary))')}
                onMouseLeave={e => (e.currentTarget.style.background = '')}
              >
                <div>
                  <span style={{ fontWeight: 800 }}>{bs.bread_price_display}</span>
                  <span style={{ color: 'hsl(var(--text-muted))', marginLeft: '6px', fontSize: '0.6rem' }}>
                    produits: {bs.qty_produced} · reçus: <span style={{ color: 'hsl(var(--color-info))' }}>{bs.qty_received}</span> · sortis: {bs.qty_sent} · disposés: {bs.qty_disposed}
                  </span>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <span style={{ fontWeight: 800, fontSize: '0.75rem', color: bs.qty_available > 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>
                    {bs.qty_available} dispo
                  </span>
                  <span style={{ display: 'block', fontSize: '0.55rem', color: 'hsl(var(--text-muted))' }}>voir détail</span>
                </div>
              </div>
            ))}
          </div>
        )
      ) : loading ? (
        <div style={{ textAlign: 'center', padding: '12px', color: 'hsl(var(--text-secondary))', fontSize: '0.7rem' }}>Chargement...</div>
      ) : error ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.68rem', color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.08)', padding: '8px 10px', borderRadius: 'var(--radius-sm)' }}>
          {error}
        </div>
      ) : !snapshot || snapshot.categories.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '12px', color: 'hsl(var(--text-muted))', fontSize: '0.7rem' }}>
          Aucun stock de pains enregistré ce jour-là.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          {snapshot.categories.map(cat => (
            <div
              key={cat.bread_price}
              style={{ display: 'grid', gridTemplateColumns: '1fr auto', alignItems: 'center', padding: '5px 8px', borderRadius: 'var(--radius-sm)', border: '1px solid hsl(var(--border-color))', fontSize: '0.68rem' }}
            >
              <span style={{ fontWeight: 800 }}>{cat.bread_price_display}</span>
              <div style={{ textAlign: 'right' }}>
                <span style={{ fontWeight: 800, fontSize: '0.75rem', color: cat.qty_available > 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>
                  {cat.qty_available} dispo
                </span>
                <span style={{ display: 'block', fontSize: '0.55rem', color: 'hsl(var(--text-muted))' }}>
                  {formatFC(cat.qty_available * cat.unit_price)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      <Modal
        isOpen={calendarOpen}
        onClose={() => setCalendarOpen(false)}
        title="Choisir une date"
        subtitle="Consultez le stock de pains et les fournées d'un jour passé."
        maxWidth="360px"
        contentPadding="12px 16px 16px"
      >
        <CalendarPicker
          value={selectedDate}
          onSelect={(iso) => {
            onSelectDate(iso);
            setCalendarOpen(false);
          }}
        />
      </Modal>
    </div>
  );
};
