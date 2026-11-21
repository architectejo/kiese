import React from 'react';
import {
  FiPhone, FiMapPin, FiShield, FiX, FiGrid, FiAlertTriangle, FiEdit2, FiSave, FiCreditCard, FiArrowRight,
} from 'react-icons/fi';
import { salesApi } from '@/api/services';
import type { Invoice } from '@/api/services';
import { Modal } from '@/components/shared/Modal';
import { ClientItem, ClientDetailTab } from './clientItem';
import { ClientInvoiceHistoryTab } from './ClientInvoiceHistoryTab';
import { ClientRepaymentsTab } from './ClientRepaymentsTab';

interface ClientDetailModalProps {
  selectedClient: ClientItem;
  setSelectedClient: (c: ClientItem | null) => void;
  userRole: string | undefined;
  isEditingLimit: boolean;
  setIsEditingLimit: (v: boolean) => void;
  limitInput: string;
  setLimitInput: (v: string) => void;
  handleSaveCreditLimit: () => void | Promise<void>;
  clientDetailTab: ClientDetailTab;
  setClientDetailTab: (t: ClientDetailTab) => void;
  clientInvoices: Invoice[];
  setClientInvoices: (inv: Invoice[]) => void;
  invoicesLoading: boolean;
  setInvoicesLoading: (v: boolean) => void;
  historyYear: number;
  historyMonth: number;
  setHistoryYear: React.Dispatch<React.SetStateAction<number>>;
  setHistoryMonth: React.Dispatch<React.SetStateAction<number>>;
  canAdjustInvoice: boolean;
  openAdjustModal: (invoice: Invoice) => void;
  /** Ouvre le formulaire de remboursement / dépôt pour ce client (la page ferme la fiche). */
  onStartRepayment: (client: ClientItem) => void;
  /** Ouvre le formulaire de commande pour ce client. */
  onStartSale: (client: ClientItem) => void;
}

/** Fiche client détaillée : informations, historique des commandes, remboursements. */
export const ClientDetailModal: React.FC<ClientDetailModalProps> = ({
  selectedClient, setSelectedClient, userRole, isEditingLimit, setIsEditingLimit, limitInput, setLimitInput,
  handleSaveCreditLimit, clientDetailTab, setClientDetailTab, clientInvoices, setClientInvoices,
  invoicesLoading, setInvoicesLoading, historyYear, historyMonth, setHistoryYear, setHistoryMonth,
  canAdjustInvoice, openAdjustModal, onStartRepayment, onStartSale,
}) => {
  return (
        <Modal
          isOpen={true}
          onClose={() => { setSelectedClient(null); setIsEditingLimit(false); }}
          maxWidth="580px"
          contentPadding="0"
          showCloseButton={false}
        >
            {/* Header */}
            <div style={{ padding: '20px 24px 0', borderBottom: '1px solid hsl(var(--border-color))' }}>
              <button
                onClick={() => { setSelectedClient(null); setIsEditingLimit(false); }}
                style={{ position: 'absolute', top: '14px', right: '14px', border: 'none', background: 'none', cursor: 'pointer', fontSize: '1.1rem', color: 'hsl(var(--text-secondary))' }}
              >
                <FiX />
              </button>

              {/* Profile summary */}
              <div style={{ display: 'flex', gap: '14px', alignItems: 'center', marginBottom: '16px' }}>
                <div style={{ width: '48px', height: '48px', borderRadius: '50%', backgroundColor: selectedClient.avatarColor, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: '1.3rem', boxShadow: '0 4px 12px rgba(0,0,0,0.15)', flexShrink: 0 }}>
                  {selectedClient.name.substring(0, 2).toUpperCase()}
                </div>
                <div>
                  <span className="badge badge-info" style={{ marginBottom: '3px', fontSize: '0.6rem', padding: '1px 6px' }}>{selectedClient.id} • {selectedClient.type}</span>
                  <h2 style={{ fontSize: '1.1rem', fontWeight: 800, marginBottom: '1px', color: 'hsl(var(--text-primary))' }}>{selectedClient.name}</h2>
                  <p style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.72rem', fontWeight: 600 }}>{selectedClient.businessName}</p>
                </div>
              </div>

              {/* Tab bar */}
              <div style={{ display: 'flex', gap: 0 }}>
                {(['info', 'history', 'repayments'] as const).map(tab => (
                  <button
                    key={tab}
                    onClick={async () => {
                      setClientDetailTab(tab);
                      if ((tab === 'history' || tab === 'repayments') && clientInvoices.length === 0 && selectedClient._apiId) {
                        setInvoicesLoading(true);
                        try {
                          const res = await salesApi.list({ client: selectedClient._apiId });
                          setClientInvoices(res.data);
                        } catch { /* ignore */ }
                        setInvoicesLoading(false);
                      }
                    }}
                    style={{
                      padding: '8px 14px', fontSize: '0.75rem', fontWeight: 700, cursor: 'pointer',
                      border: 'none', borderBottom: clientDetailTab === tab ? '2px solid hsl(var(--accent-color))' : '2px solid transparent',
                      background: 'none', color: clientDetailTab === tab ? 'hsl(var(--accent-color))' : 'hsl(var(--text-muted))',
                      transition: 'color 0.15s, border-color 0.15s'
                    }}
                  >
                    {tab === 'info' ? 'Informations' : tab === 'history' ? 'Historique' : 'Remboursements'}
                  </button>
                ))}
              </div>
            </div>

            {/* Tab content */}
            <div style={{ padding: '20px 24px', maxHeight: '55vh', overflowY: 'auto' }}>

              {/* ── Onglet Info ── */}
              {clientDetailTab === 'info' && (
                <>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', marginBottom: '16px' }}>
                    <div>
                      <h4 style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '0.65rem', fontWeight: 800, color: 'hsl(var(--text-muted))', textTransform: 'uppercase', marginBottom: '5px' }}>
                        <FiPhone /> Contact
                      </h4>
                      <p style={{ fontSize: '0.82rem', fontWeight: 700, color: 'hsl(var(--text-primary))' }}>{selectedClient.phone}</p>
                    </div>
                    <div>
                      <h4 style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '0.65rem', fontWeight: 800, color: 'hsl(var(--text-muted))', textTransform: 'uppercase', marginBottom: '5px' }}>
                        <FiMapPin /> Adresse
                      </h4>
                      <p style={{ fontSize: '0.78rem', color: 'hsl(var(--text-secondary))', lineHeight: 1.3 }}>{selectedClient.address}</p>
                    </div>
                    <div>
                      <h4 style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '0.65rem', fontWeight: 800, color: 'hsl(var(--text-muted))', textTransform: 'uppercase', marginBottom: '5px' }}>
                        <FiShield /> Limite Crédit
                        {['ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT'].includes(userRole || '') && !isEditingLimit && (
                          <button onClick={() => { setLimitInput(selectedClient.creditLimit.toString()); setIsEditingLimit(true); }} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'hsl(var(--accent-color))', padding: '0 2px', display: 'flex', alignItems: 'center' }} title="Modifier">
                            <FiEdit2 size={10} />
                          </button>
                        )}
                      </h4>
                      {isEditingLimit ? (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                          <input type="number" min={0} value={limitInput} onChange={e => setLimitInput(e.target.value)} className="form-input" style={{ height: '28px', fontSize: '0.78rem', padding: '0 6px', fontWeight: 700, width: '100px' }} autoFocus />
                          <span style={{ fontSize: '0.7rem', color: 'hsl(var(--text-secondary))' }}>FC</span>
                          <button onClick={handleSaveCreditLimit} className="btn btn-primary" style={{ padding: '3px 6px', fontSize: '0.65rem', display: 'flex', alignItems: 'center', gap: '3px' }}><FiSave size={10} /> OK</button>
                          <button onClick={() => setIsEditingLimit(false)} className="btn btn-secondary" style={{ padding: '3px 6px', fontSize: '0.65rem' }}><FiX size={10} /></button>
                        </div>
                      ) : (
                        <p style={{ fontSize: '0.9rem', fontWeight: 800, color: 'hsl(var(--accent-color))' }}>{selectedClient.creditLimit.toLocaleString('fr-FR')} FC</p>
                      )}
                      <p style={{ fontSize: '0.65rem', color: 'hsl(var(--text-muted))', marginTop: '4px' }}>
                        Cotisation sociale : {selectedClient.effectiveCotisation > 0 ? `${selectedClient.effectiveCotisation.toLocaleString('fr-FR')} FC/mois` : 'aucune'}
                      </p>
                    </div>
                    <div>
                      <h4 style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '0.65rem', fontWeight: 800, color: 'hsl(var(--text-muted))', textTransform: 'uppercase', marginBottom: '5px' }}>
                        <FiAlertTriangle /> Encours Actuel
                      </h4>
                      <div style={{ display: 'flex', alignItems: 'baseline', gap: '4px' }}>
                        {selectedClient.outstandingDebt < 0 ? (
                          <span style={{ fontSize: '0.9rem', fontWeight: 800, color: 'hsl(var(--color-success))' }}>
                            CRÉDIT : {Math.abs(selectedClient.outstandingDebt).toLocaleString('fr-FR')} FC
                          </span>
                        ) : (
                          <>
                            <span style={{ fontSize: '0.9rem', fontWeight: 800, color: selectedClient.outstandingDebt > selectedClient.creditLimit ? 'hsl(var(--color-danger))' : 'hsl(var(--text-primary))' }}>
                              {selectedClient.outstandingDebt.toLocaleString('fr-FR')} FC
                            </span>
                            {selectedClient.outstandingDebt > selectedClient.creditLimit && (
                              <span style={{ fontSize: '0.58rem', color: 'hsl(var(--color-danger))', fontWeight: 700 }}>(DÉPASSÉ)</span>
                            )}
                          </>
                        )}
                      </div>
                    </div>
                  </div>

                  <div style={{ backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', borderRadius: 'var(--radius-sm)', padding: '10px 12px' }}>
                    <h4 style={{ fontSize: '0.7rem', fontWeight: 800, color: 'hsl(var(--text-primary))', marginBottom: '7px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <FiGrid style={{ color: 'hsl(var(--accent-color))' }} /> Évaluation de Risque
                    </h4>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>
                      <span>Dernier enregistrement :</span>
                      <span style={{ fontWeight: 700, color: 'hsl(var(--color-success))' }}>{selectedClient.lastPaymentDate}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'hsl(var(--text-secondary))' }}>
                      <span>Score automatique :</span>
                      <span style={{ fontWeight: 700, color: selectedClient.riskScore === 'High' ? 'hsl(var(--color-danger))' : selectedClient.riskScore === 'Medium' ? 'hsl(var(--color-warning))' : 'hsl(var(--color-success))' }}>
                        {selectedClient.riskScore === 'High' ? 'Rouge — CRITIQUE' : selectedClient.riskScore === 'Medium' ? 'Orange — MOYEN' : 'Vert — FIABLE'}
                      </span>
                    </div>
                  </div>
                </>
              )}

              {/* ── Onglet Historique ── */}
              {clientDetailTab === 'history' && (
                <ClientInvoiceHistoryTab
                  clientInvoices={clientInvoices}
                  invoicesLoading={invoicesLoading}
                  historyYear={historyYear}
                  historyMonth={historyMonth}
                  setHistoryYear={setHistoryYear}
                  setHistoryMonth={setHistoryMonth}
                  canAdjustInvoice={canAdjustInvoice}
                  openAdjustModal={openAdjustModal}
                />
              )}

              {/* ── Onglet Remboursements ── */}
              {clientDetailTab === 'repayments' && (
                <ClientRepaymentsTab clientInvoices={clientInvoices} invoicesLoading={invoicesLoading} />
              )}

            </div>

            {/* Footer buttons */}
            <div style={{ padding: '14px 24px', borderTop: '1px solid hsl(var(--border-color))', display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
              <button
                onClick={() => { setSelectedClient(null); setIsEditingLimit(false); }}
                className="btn btn-secondary"
                style={{ flex: 1, minWidth: '80px', padding: '8px 16px', fontSize: '0.8rem' }}
              >
                Fermer
              </button>
              {selectedClient && (
                <button
                  onClick={() => onStartRepayment(selectedClient)}
                  className="btn btn-secondary"
                  style={{ flex: 1, minWidth: '120px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', padding: '8px 12px', fontSize: '0.78rem', color: 'hsl(var(--color-warning))', borderColor: 'hsl(var(--color-warning) / 0.4)' }}
                >
                  <FiCreditCard />
                  <span>Remboursement / Dépôt sans commande</span>
                </button>
              )}
              <button
                onClick={() => { setSelectedClient(null); onStartSale(selectedClient); }}
                className="btn btn-primary"
                style={{ flex: 2, minWidth: '140px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', padding: '8px 16px', fontSize: '0.8rem' }}
              >
                <span>Facturer une commande</span>
                <FiArrowRight />
              </button>
            </div>
        </Modal>
  );
};
