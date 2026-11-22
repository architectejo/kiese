import React, { useState, useEffect, useCallback, useRef } from 'react';
import { FiRefreshCw, FiFileText, FiPlus } from 'react-icons/fi';
import { treasuryApi } from '@/api/services';
import type { JournalEntry, SuggestedCa } from '@/api/services';
import { treasuryErrorMessage } from '@/components/treasury/treasuryRules';
import { PAGE_SIZE, progressLabel, fmt } from '@/components/treasury/treasuryShared';
import { useAuthStore } from '@/store/authStore';
import { useProgressiveList } from '@/hooks/useProgressiveList';

const JOURNAL_IMPUT = [
  { value: 'CA',        label: 'Recettes du jour (CA)' },
  { value: 'PAY_BLG',  label: 'Paye boulangers' },
  { value: 'RATION',   label: 'Ration boulangers' },
  { value: 'LIVRAISON',label: 'Livraison inter-site' },
  { value: 'EAU',      label: 'Eau' },
  { value: 'APPRO',    label: "Frais d'appro" },
  { value: 'DEPOT',    label: 'Dépôt rapport direction' },
  { value: 'TRANSPORT',label: 'Transport' },
  { value: 'CREDIT',   label: 'Crédit personnel' },
  { value: 'PRIME',    label: 'Prime personnel' },
  { value: 'CARBURANT',label: 'Essence / Mazout' },
  { value: 'ACHAT',    label: 'Achat matériel / fourniture' },
  { value: 'AUTRE',    label: 'Autre' },
];

interface Props {
  today: string;
  nodeFilter: string;
  isHq: boolean;
  canWriteTreasury: boolean;
}

// §5.1.4 — Journal de caisse par boulangerie (écritures du mois, rapport mensuel, saisie gérant+).
export const JournalSection: React.FC<Props> = ({ today, nodeFilter, isHq, canWriteTreasury }) => {
  const { user } = useAuthStore();
  const nodeParam: Record<string, string> = nodeFilter ? { node: nodeFilter } : {};
  const [journalMonth, setJournalMonth] = useState(() => new Date().getMonth() + 1);
  const [journalYear, setJournalYear]   = useState(() => new Date().getFullYear());
  const [journalReport, setJournalReport] = useState<{
    month_carried: string; total_entries: string; total_exits: string; final_balance: string;
  } | null>(null);
  const [jImput, setJImput]       = useState('CA');
  const [jLabel, setJLabel]       = useState('');
  const [jEntry, setJEntry]       = useState('');
  const [jExit, setJExit]         = useState('');
  const [jDate, setJDate]         = useState(today);
  const [jError, setJError]       = useState<string | null>(null);
  const [jSubmitting, setJSubmitting] = useState(false);
  // BUG-105 — pré-remplissage/confrontation « Recettes du jour (CA) » avec la Clôture (Niveau 2)
  const [jSuggestedCa, setJSuggestedCa] = useState<SuggestedCa | null>(null);
  const [jSuggestedCaLoading, setJSuggestedCaLoading] = useState(false);
  const [jLastResult, setJLastResult] = useState<JournalEntry | null>(null);

  const journalQ = useProgressiveList<JournalEntry>({
    fetchPage: p => treasuryApi.journal.page({ month: String(journalMonth), year: String(journalYear), ...nodeParam, page: String(p), page_size: PAGE_SIZE }),
    resetKey: `jrn|${journalMonth}|${journalYear}|${nodeFilter}`,
  });
  const journalEntries = journalQ.items;
  const journalLoading = journalQ.isLoading;

  // BUG-161 (F3) : à la relève (passage de minuit), le sélecteur de jour suit la nouvelle journée.
  const prevTodayRef = useRef(today);
  useEffect(() => {
    const previous = prevTodayRef.current;
    if (previous === today) return;
    prevTodayRef.current = today;
    setJDate(d => (d === previous ? today : d));
  }, [today]);

  // §5.1.4 — Journal de Caisse load
  // Les écritures sont lues par `journalQ` (progressif) ; le rapport mensuel (totaux
  // calculés par le serveur) est lu à part.
  const reloadJournalEntries = journalQ.reload;
  const loadJournalReport = useCallback(async () => {
    const params: Record<string, string> = { month: String(journalMonth), year: String(journalYear) };
    if (nodeFilter) params.node = nodeFilter;
    try {
      const reportRes = await treasuryApi.journal.monthlyReport(params);
      setJournalReport(reportRes.data ?? null);
    } catch { /* ignore */ }
  }, [journalMonth, journalYear, nodeFilter]);
  const loadJournal = useCallback(async () => {
    reloadJournalEntries();
    await loadJournalReport();
  }, [reloadJournalEntries, loadJournalReport]);

  useEffect(() => { loadJournalReport(); }, [loadJournalReport]);

  // BUG-105 — pré-remplissage/confrontation du montant « Recettes du jour (CA) »
  // avec la Clôture (Niveau 2) du même (nœud, date) — ne bloque jamais la saisie :
  // la valeur suggérée ne fait que remplir le champ, qui reste librement modifiable.
  useEffect(() => {
    const effectiveNode = user?.node || nodeFilter;
    if (jImput !== 'CA' || !effectiveNode || !jDate) {
      setJSuggestedCa(null);
      return;
    }
    let cancelled = false;
    setJSuggestedCaLoading(true);
    treasuryApi.journal.suggestedCa({ node: effectiveNode, date: jDate })
      .then(res => {
        if (cancelled) return;
        setJSuggestedCa(res.data);
        if (res.data.available && res.data.amount) {
          setJEntry(String(Math.round(parseFloat(res.data.amount))));
        }
      })
      .catch(() => { if (!cancelled) setJSuggestedCa(null); })
      .finally(() => { if (!cancelled) setJSuggestedCaLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jImput, jDate, user?.node, nodeFilter]);

  const handleJournalSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setJError(null);
    const ea = parseFloat(jEntry) || 0;
    const xa = parseFloat(jExit)  || 0;
    if (!canWriteTreasury) { setJError("Écriture réservée au gérant et aux rôles supérieurs."); return; }
    if (ea < 0 || xa < 0) { setJError('Les montants ne peuvent pas être négatifs.'); return; }
    if (ea === 0 && xa === 0) { setJError('Indiquez une entrée ou une sortie.'); return; }
    setJSubmitting(true);
    try {
      const payload: Partial<JournalEntry> & { node?: string } = {
        imput: jImput, label: jLabel, date: jDate,
        entry_amount: ea ? String(ea) : '0',
        exit_amount:  xa ? String(xa) : '0',
      };
      if (isHq && nodeFilter) payload.node = nodeFilter;
      const res = await treasuryApi.journal.create(payload);
      // BUG-105 — confrontation à la Clôture renvoyée par le serveur pour
      // l'imputation CA (jamais calculée/forcée côté client).
      setJLastResult(jImput === 'CA' ? res.data : null);
      setJLabel(''); setJEntry(''); setJExit('');
      setJSuggestedCa(null);
      await loadJournal();
    } catch (err: unknown) {
      setJError(treasuryErrorMessage(err, "Erreur lors de l'enregistrement."));
    } finally {
      setJSubmitting(false);
    }
  };

  return (
      <div className="glass-card" style={{ padding: '16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px', flexWrap: 'wrap', gap: '10px' }}>
          <h2 style={{ fontSize: '0.9rem', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '6px' }}>
            <FiFileText style={{ color: 'hsl(var(--accent-color))' }} />
            §5.1.4 — Journal de Caisse par Boulangerie
          </h2>
          {/* Month/Year navigation */}
          <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
            <label style={{ fontSize: '0.7rem', color: 'hsl(var(--text-secondary))', fontWeight: 600 }}>Mois</label>
            <select
              value={journalMonth}
              onChange={e => setJournalMonth(Number(e.target.value))}
              className="form-input"
              style={{ height: '28px', fontSize: '0.72rem', padding: '0 6px', width: '110px' }}
            >
              {['Janvier','Février','Mars','Avril','Mai','Juin','Juillet','Août','Septembre','Octobre','Novembre','Décembre'].map((m, i) => (
                <option key={i + 1} value={i + 1}>{m}</option>
              ))}
            </select>
            <input
              type="number"
              value={journalYear}
              onChange={e => setJournalYear(Math.min(2035, Math.max(2024, Number(e.target.value) || 2024)))}
              className="form-input"
              style={{ height: '28px', fontSize: '0.72rem', padding: '0 6px', width: '72px' }}
              min={2024} max={2035}
            />
            <button onClick={loadJournal} className="btn btn-secondary" style={{ padding: '4px 10px', fontSize: '0.68rem', display: 'flex', alignItems: 'center', gap: '4px' }}>
              <FiRefreshCw size={11} /> Actualiser
            </button>
          </div>
        </div>

        {/* Report mois précédent */}
        {journalReport && (
          <div style={{ marginBottom: '12px', padding: '8px 14px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', display: 'flex', gap: '24px', flexWrap: 'wrap', fontSize: '0.72rem' }}>
            <span>
              <span style={{ color: 'hsl(var(--text-secondary))', fontWeight: 600 }}>Report mois précédent : </span>
              <span style={{ fontWeight: 800, color: parseFloat(journalReport.month_carried) < 0 ? 'hsl(var(--color-danger))' : 'hsl(var(--accent-color))' }}>
                {fmt(journalReport.month_carried)} FC
              </span>
            </span>
            <span>
              <span style={{ color: 'hsl(var(--text-secondary))', fontWeight: 600 }}>Total Entrées : </span>
              <span style={{ fontWeight: 700, color: 'hsl(var(--color-success))' }}>{fmt(journalReport.total_entries)} FC</span>
            </span>
            <span>
              <span style={{ color: 'hsl(var(--text-secondary))', fontWeight: 600 }}>Total Sorties : </span>
              <span style={{ fontWeight: 700, color: 'hsl(var(--color-danger))' }}>{fmt(journalReport.total_exits)} FC</span>
            </span>
            <span>
              <span style={{ color: 'hsl(var(--text-secondary))', fontWeight: 600 }}>Solde Final : </span>
              <span style={{ fontWeight: 800, color: parseFloat(journalReport.final_balance) < 0 ? 'hsl(var(--color-danger))' : 'hsl(var(--color-success))' }}>
                {fmt(journalReport.final_balance)} FC
              </span>
            </span>
          </div>
        )}

        {/* Form — new entry (BUG-231 : ajout seul, gérant et au-dessus ; aucune édition/suppression de ligne, le serveur répond 405) */}
        {canWriteTreasury ? (
        <form onSubmit={handleJournalSubmit} style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'flex-end', marginBottom: '14px', padding: '12px 14px', backgroundColor: 'hsl(var(--bg-secondary))', borderRadius: 'var(--radius-sm)', border: '1px solid hsl(var(--border-color))' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
            <label style={{ fontSize: '0.62rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', textTransform: 'uppercase' }}>Date</label>
            <input type="date" value={jDate} onChange={e => setJDate(e.target.value)} className="form-input" style={{ height: '30px', fontSize: '0.72rem', padding: '0 6px', width: '130px' }} required />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
            <label style={{ fontSize: '0.62rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', textTransform: 'uppercase' }}>Imputation</label>
            <select value={jImput} onChange={e => setJImput(e.target.value)} className="form-input" style={{ height: '30px', fontSize: '0.72rem', padding: '0 6px', width: '180px' }} required>
              {JOURNAL_IMPUT.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '3px', flex: 1, minWidth: '120px' }}>
            <label style={{ fontSize: '0.62rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', textTransform: 'uppercase' }}>Libellé</label>
            <input type="text" value={jLabel} onChange={e => setJLabel(e.target.value)} className="form-input" style={{ height: '30px', fontSize: '0.72rem', padding: '0 8px' }} placeholder="Description (optionnel)" maxLength={200} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
            <label style={{ fontSize: '0.62rem', fontWeight: 700, color: 'hsl(var(--color-success))', textTransform: 'uppercase' }}>Entrée (FC)</label>
            <input type="number" value={jEntry} onChange={e => setJEntry(e.target.value)} className="form-input" style={{ height: '30px', fontSize: '0.72rem', padding: '0 6px', width: '120px' }} placeholder="0" min={0} step={1} />
            {/* BUG-105 — pré-remplissage/confrontation CA avec la Clôture (Niveau 2) */}
            {jImput === 'CA' && (
              <div style={{ fontSize: '0.6rem', fontWeight: 600, whiteSpace: 'nowrap' }}>
                {jSuggestedCaLoading ? (
                  <span style={{ color: 'hsl(var(--text-secondary))' }}>Vérification de la Clôture...</span>
                ) : jSuggestedCa?.available ? (
                  <>
                    <span style={{ color: 'hsl(var(--color-success))' }}>✓ Rapproché à la Clôture ({fmt(jSuggestedCa.amount || '0')} FC)</span>
                    {(() => {
                      const liveGap = parseFloat(jEntry || '0') - parseFloat(jSuggestedCa!.amount || '0');
                      return liveGap !== 0 ? (
                        <div style={{ color: 'hsl(var(--color-warning))' }}>
                          Écart avec la Clôture : {liveGap >= 0 ? '+' : ''}{fmt(String(liveGap))} FC
                        </div>
                      ) : null;
                    })()}
                  </>
                ) : (
                  <span style={{ color: 'hsl(var(--text-secondary))' }}>{jSuggestedCa?.message || 'Aucune Clôture (Niveau 2) pour ce jour — écriture non rapprochée.'}</span>
                )}
              </div>
            )}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
            <label style={{ fontSize: '0.62rem', fontWeight: 700, color: 'hsl(var(--color-danger))', textTransform: 'uppercase' }}>Sortie (FC)</label>
            <input type="number" value={jExit} onChange={e => setJExit(e.target.value)} className="form-input" style={{ height: '30px', fontSize: '0.72rem', padding: '0 6px', width: '120px' }} placeholder="0" min={0} step={1} />
          </div>
          <button type="submit" disabled={jSubmitting} className="btn btn-primary" style={{ height: '30px', padding: '0 14px', fontSize: '0.72rem', display: 'flex', alignItems: 'center', gap: '5px' }}>
            <FiPlus size={13} />{jSubmitting ? 'Enregistrement...' : 'Enregistrer'}
          </button>
          {jError && (
            <div style={{ width: '100%', padding: '6px 10px', backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.4)', borderRadius: 'var(--radius-sm)', color: 'hsl(var(--color-danger))', fontSize: '0.7rem', fontWeight: 600 }}>
              {jError}
            </div>
          )}
          {jLastResult && (
            <div style={{
              width: '100%', padding: '6px 10px', borderRadius: 'var(--radius-sm)', fontSize: '0.7rem', fontWeight: 600,
              backgroundColor: jLastResult.is_reconciled
                ? (parseFloat(jLastResult.reconciliation_gap || '0') === 0 ? 'hsl(var(--color-success) / 0.1)' : 'hsl(var(--color-warning) / 0.1)')
                : 'hsl(var(--bg-tertiary))',
              border: `1px solid hsl(var(--${jLastResult.is_reconciled ? (parseFloat(jLastResult.reconciliation_gap || '0') === 0 ? 'color-success' : 'color-warning') : 'border-color'}) / 0.4)`,
              color: jLastResult.is_reconciled
                ? (parseFloat(jLastResult.reconciliation_gap || '0') === 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-warning))')
                : 'hsl(var(--text-secondary))',
            }}>
              {jLastResult.is_reconciled
                ? (parseFloat(jLastResult.reconciliation_gap || '0') === 0
                    ? 'Écriture enregistrée — rapprochée à la Clôture, aucun écart.'
                    : `Écriture enregistrée — écart de ${parseFloat(jLastResult.reconciliation_gap || '0') >= 0 ? '+' : ''}${fmt(jLastResult.reconciliation_gap || '0')} FC avec la Clôture (notification envoyée).`)
                : 'Écriture enregistrée — non rapprochée (aucune Clôture pour ce jour).'}
            </div>
          )}
        </form>
        ) : (
          <div style={{ fontSize: '0.68rem', color: 'hsl(var(--text-muted))', marginBottom: '14px', padding: '8px 12px', backgroundColor: 'hsl(var(--bg-secondary))', borderRadius: 'var(--radius-sm)' }}>
            Le journal est en lecture seule pour votre rôle : la saisie est réservée au gérant et aux rôles supérieurs.
          </div>
        )}

        {/* Entries table */}
        {journalQ.error && (
          <p role="alert" style={{ textAlign: 'center', padding: '8px', color: 'hsl(var(--color-danger))', fontSize: '0.75rem' }}>
            {journalQ.error}{' '}
            <button onClick={reloadJournalEntries} className="btn btn-secondary" style={{ padding: '2px 8px', fontSize: '0.62rem' }}>Réessayer</button>
          </p>
        )}
        {journalLoading ? (
          <p style={{ textAlign: 'center', padding: '20px', color: 'hsl(var(--text-secondary))', fontSize: '0.8rem' }}>Chargement...</p>
        ) : journalEntries.length === 0 ? (
          <p style={{ textAlign: 'center', padding: '20px', color: 'hsl(var(--text-secondary))', fontSize: '0.8rem' }}>
            Aucune écriture pour ce mois.
          </p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="premium-table">
              <thead>
                <tr style={{ fontSize: '0.62rem', textTransform: 'uppercase' }}>
                  <th style={{ width: '90px', textAlign: 'center' }}>Date</th>
                  <th style={{ width: '140px' }}>Imputation</th>
                  <th>Libellé</th>
                  <th style={{ textAlign: 'right', width: '110px', color: 'hsl(var(--color-success))' }}>Entrée (FC)</th>
                  <th style={{ textAlign: 'right', width: '110px', color: 'hsl(var(--color-danger))' }}>Sortie (FC)</th>
                  <th style={{ textAlign: 'right', width: '120px' }}>Solde Courant</th>
                  <th style={{ textAlign: 'center', width: '150px' }}>Rapprochement</th>
                </tr>
              </thead>
              <tbody>
                {journalEntries.map(entry => {
                  const balance = parseFloat(entry.running_balance || '0');
                  const gap = parseFloat(entry.reconciliation_gap || '0');
                  return (
                    <tr key={entry.id} style={{ fontSize: '0.72rem' }}>
                      <td style={{ textAlign: 'center', fontWeight: 600 }}>
                        {new Date(entry.date).toLocaleDateString('fr-FR', { day: '2-digit', month: 'short' })}
                      </td>
                      <td>
                        <span style={{ fontWeight: 700, color: 'hsl(var(--accent-color))', fontSize: '0.68rem' }}>
                          {entry.imput_display || entry.imput}
                        </span>
                      </td>
                      <td style={{ color: 'hsl(var(--text-secondary))' }}>
                        {entry.label || <span style={{ fontStyle: 'italic', opacity: 0.5 }}>—</span>}
                      </td>
                      <td style={{ textAlign: 'right', color: parseFloat(entry.entry_amount) > 0 ? 'hsl(var(--color-success))' : 'hsl(var(--text-secondary))', fontWeight: parseFloat(entry.entry_amount) > 0 ? 700 : 400 }}>
                        {parseFloat(entry.entry_amount) > 0 ? fmt(entry.entry_amount) : '—'}
                      </td>
                      <td style={{ textAlign: 'right', color: parseFloat(entry.exit_amount) > 0 ? 'hsl(var(--color-danger))' : 'hsl(var(--text-secondary))', fontWeight: parseFloat(entry.exit_amount) > 0 ? 700 : 400 }}>
                        {parseFloat(entry.exit_amount) > 0 ? fmt(entry.exit_amount) : '—'}
                      </td>
                      <td style={{ textAlign: 'right', fontWeight: 800, color: balance < 0 ? 'hsl(var(--color-danger))' : 'hsl(var(--text-primary))' }}>
                        {fmt(entry.running_balance)} FC
                      </td>
                      <td style={{ textAlign: 'center' }}>
                        {/* BUG-105 — rapprochement CA ↔ Clôture (Niveau 2), autres imputations non concernées */}
                        {entry.imput === 'CA' ? (
                          entry.is_reconciled ? (
                            <span style={{
                              fontSize: '0.62rem', fontWeight: 700, padding: '2px 6px', borderRadius: 'var(--radius-sm)',
                              backgroundColor: gap === 0 ? 'hsl(var(--color-success) / 0.12)' : 'hsl(var(--color-warning) / 0.12)',
                              color: gap === 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-warning))',
                            }}>
                              Rapproché{gap !== 0 ? ` (écart ${gap >= 0 ? '+' : ''}${fmt(entry.reconciliation_gap || '0')} FC)` : ''}
                            </span>
                          ) : (
                            <span style={{ fontSize: '0.62rem', fontWeight: 600, color: 'hsl(var(--text-muted))' }}>Non rapproché</span>
                          )
                        ) : (
                          <span style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))' }}>—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr style={{ fontSize: '0.68rem', fontWeight: 800, backgroundColor: 'hsl(var(--bg-tertiary))' }}>
                  <td colSpan={3} style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--text-secondary))' }}>
                    {journalQ.total ?? journalEntries.length} écriture(s)
                  </td>
                  {journalQ.isComplete ? (
                    <>
                      <td style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--color-success))' }}>
                        {fmt(journalEntries.reduce((a, e) => a + parseFloat(e.entry_amount || '0'), 0))} FC
                      </td>
                      <td style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--color-danger))' }}>
                        {fmt(journalEntries.reduce((a, e) => a + parseFloat(e.exit_amount || '0'), 0))} FC
                      </td>
                    </>
                  ) : (
                    <td colSpan={2} style={{ textAlign: 'right', padding: '8px 10px', fontWeight: 600, color: 'hsl(var(--text-muted))' }}>{progressLabel(journalQ)}</td>
                  )}
                  <td style={{ textAlign: 'right', padding: '8px 10px', color: journalReport && parseFloat(journalReport.final_balance) < 0 ? 'hsl(var(--color-danger))' : 'hsl(var(--color-success))' }}>
                    {journalReport ? `${fmt(journalReport.final_balance)} FC` : '—'}
                  </td>
                  <td></td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </div>
  );
};
