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
}

export const StockDuJourSection: React.FC<StockDuJourSectionProps> = ({
  selectedDate, onSelectDate, liveBreadStocks, nodeFilter, currentNodeLabel,
}) => {
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [snapshot, setSnapshot] = useState<BreadStockByDate | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // BUG-161 (F3) : « jour courant » = jour calendaire du serveur (repli : date locale).
  const workDate = useWorkDate();
  const isToday = selectedDate === workDate;

  // BUG-319 : colonnes affichées selon les données ; avant clôture seul « Vendu » (+ transferts).
  const hasReceived = liveBreadStocks.some(bs => bs.qty_received > 0);
  const hasSent = liveBreadStocks.some(bs => bs.qty_sent > 0);
  const anyClosed = liveBreadStocks.some(bs => bs.closed);
  const [ecartFc, setEcartFc] = useState<number | null>(null);
  const reportNode = nodeFilter || liveBreadStocks[0]?.node;

  // Écart sacs (manquant/excédent) lu dans le rapport de clôture, une fois la journée clôturée.
  useEffect(() => {
    if (!isToday || !anyClosed || !reportNode) { setEcartFc(null); return; }
    let cancelled = false;
    productionApi.dailyClosure.get(reportNode, selectedDate)
      .then(res => {
        if (cancelled) return;
        const n = parseFloat(res.data.totals.ecart_production_fc);
        setEcartFc(Number.isNaN(n) ? null : n);
      })
      .catch(() => { if (!cancelled) setEcartFc(null); });
    return () => { cancelled = true; };
  }, [isToday, anyClosed, reportNode, selectedDate]);

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

      <p style={{ fontSize: '0.64rem', color: 'hsl(var(--text-secondary))', margin: '0 0 8px' }}>
        Pendant la journée on compte les pains vendus ; à la clôture, les restes déclarés s'ajoutent pour donner le total produit.
      </p>

      {isToday ? (
        liveBreadStocks.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '12px', color: 'hsl(var(--text-muted))', fontSize: '0.7rem' }}>
            Aucun stock de pains suivi pour l'instant.
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="premium-table" style={{ width: '100%', fontSize: '0.68rem' }}>
              <thead>
                <tr style={{ fontSize: '0.58rem', textTransform: 'uppercase' }}>
                  <th>Catégorie</th>
                  <th style={{ textAlign: 'right' }}>Vendu</th>
                  {hasReceived && <th style={{ textAlign: 'right' }}>Reçus</th>}
                  {hasSent && <th style={{ textAlign: 'right' }}>Envoyés</th>}
                  {anyClosed && <th style={{ textAlign: 'right' }}>Restes déclarés</th>}
                  {anyClosed && <th style={{ textAlign: 'right' }}>Total produit</th>}
                </tr>
              </thead>
              <tbody>
                {liveBreadStocks.map(bs => {
                  const incoherent = bs.closed && bs.produced_total != null && bs.produced_total < 0;
                  return (
                    <tr key={bs.id}>
                      <td style={{ fontWeight: 800 }}>{bs.bread_price_display}</td>
                      <td style={{ textAlign: 'right', fontWeight: 800 }}>{(bs.sold_qty ?? 0).toLocaleString('fr-FR')}</td>
                      {hasReceived && <td style={{ textAlign: 'right', color: 'hsl(var(--color-info))' }}>{bs.qty_received}</td>}
                      {hasSent && <td style={{ textAlign: 'right' }}>{bs.qty_sent}</td>}
                      {anyClosed && (
                        <td style={{ textAlign: 'right' }}>
                          {bs.closed && bs.remaining_qty != null ? bs.remaining_qty.toLocaleString('fr-FR') : '—'}
                        </td>
                      )}
                      {anyClosed && (
                        <td style={{ textAlign: 'right', fontWeight: 800, color: incoherent ? 'hsl(var(--color-danger))' : undefined }}>
                          {bs.closed && bs.produced_total != null ? bs.produced_total.toLocaleString('fr-FR') : '—'}
                          {incoherent && (
                            <div style={{ fontSize: '0.56rem', fontWeight: 700 }} title="Les restes déclarés dépassent ce qui était disponible : vérifiez la déclaration.">
                              incohérence
                            </div>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {anyClosed && ecartFc !== null && (
              <div style={{ marginTop: '8px', fontSize: '0.7rem', fontWeight: 800, color: ecartFc < 0 ? 'hsl(var(--color-danger))' : ecartFc > 0 ? 'hsl(var(--color-success))' : undefined }}>
                Écart sacs : {ecartFc === 0 ? 'aucun écart' : `${ecartFc < 0 ? 'manquant' : 'excédent'} de ${formatFC(Math.abs(ecartFc))}`}
              </div>
            )}
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
