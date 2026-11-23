import React from 'react';
import type { Client, BreadPrice } from '@/api/services';
import { FiPlusCircle, FiCheckCircle, FiAlertCircle, FiSearch, FiX, FiCreditCard } from 'react-icons/fi';
import type { InvoiceMotif } from './MotifSelect';
import { MotifSelect } from './MotifSelect';
import { useSalesBlocked } from '@/store/closureStatusStore';

export interface InvoiceFormProps {
  breadPrices: BreadPrice[];
  formError: string | null;
  isSubmitting: boolean;
  clientSearch: string;
  setClientSearch: React.Dispatch<React.SetStateAction<string>>;
  isSearchingClients: boolean;
  clientSearchError: string | null;
  selectedClient: Client | null;
  setSelectedClient: React.Dispatch<React.SetStateAction<Client | null>>;
  showSuggestions: boolean;
  setShowSuggestions: React.Dispatch<React.SetStateAction<boolean>>;
  isOccasional: boolean;
  setIsOccasional: React.Dispatch<React.SetStateAction<boolean>>;
  quantities: Record<number, number>;
  setQuantities: React.Dispatch<React.SetStateAction<Record<number, number>>>;
  versement: number;
  setVersement: React.Dispatch<React.SetStateAction<number>>;
  versementText: string;
  setVersementText: React.Dispatch<React.SetStateAction<string>>;
  motif: InvoiceMotif;
  setMotif: React.Dispatch<React.SetStateAction<InvoiceMotif>>;
  setRepaymentMotif: React.Dispatch<React.SetStateAction<InvoiceMotif>>;
  venteSoldee: boolean;
  setVenteSoldee: React.Dispatch<React.SetStateAction<boolean>>;
  commissionExempt: boolean;
  setCommissionExempt: React.Dispatch<React.SetStateAction<boolean>>;
  specialCode: '' | 'NV' | 'RG' | 'NS';
  setSpecialCode: React.Dispatch<React.SetStateAction<'' | 'NV' | 'RG' | 'NS'>>;
  showSpecialCode: boolean;
  setShowSpecialCode: React.Dispatch<React.SetStateAction<boolean>>;
  nsPaymentType: 'CASH' | 'CREDIT';
  setNsPaymentType: React.Dispatch<React.SetStateAction<'CASH' | 'CREDIT'>>;
  allowBackdatedSales: boolean;
  invoiceDate: string;
  setInvoiceDate: React.Dispatch<React.SetStateAction<string>>;
  setIsRepaymentModalOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setRepaymentAmount: React.Dispatch<React.SetStateAction<string>>;
  setRepaymentDate: React.Dispatch<React.SetStateAction<string>>;
  setRepaymentError: React.Dispatch<React.SetStateAction<string | null>>;
  workDate: string;
  searchRef: React.RefObject<HTMLInputElement | null>;
  suggestions: Client[];
  selectClient: (c: Client) => void;
  clearClient: () => void;
  effectiveUnitPrice: (bp: BreadPrice) => number;
  orderTotal: number;
  isNonServiForm: boolean;
  isRegularisationForm: boolean;
  isCashOnlySale: boolean;
  paymentType: 'CASH' | 'CREDIT';
  handleSubmit: (e: React.FormEvent<HTMLFormElement>) => Promise<void>;
}

export const InvoiceForm: React.FC<InvoiceFormProps> = ({ breadPrices, formError, isSubmitting, clientSearch, setClientSearch, isSearchingClients, clientSearchError, selectedClient, setSelectedClient, showSuggestions, setShowSuggestions, isOccasional, setIsOccasional, quantities, setQuantities, versement, setVersement, versementText, setVersementText, motif, setMotif, setRepaymentMotif, venteSoldee, setVenteSoldee, commissionExempt, setCommissionExempt, specialCode, setSpecialCode, showSpecialCode, setShowSpecialCode, nsPaymentType, setNsPaymentType, allowBackdatedSales, invoiceDate, setInvoiceDate, setIsRepaymentModalOpen, setRepaymentAmount, setRepaymentDate, setRepaymentError, workDate, searchRef, suggestions, selectClient, clearClient, effectiveUnitPrice, orderTotal, isNonServiForm, isRegularisationForm, isCashOnlySale, paymentType, handleSubmit }) => {
  // BUG-973 : clôture du jour en attente de validation -> création de facture désactivée.
  const { blocked: closureBlocked } = useSalesBlocked();
  return (
        <div className="glass-card" style={{ padding: '16px' }}>
          <h2 style={{ fontSize: '0.9rem', fontWeight: 800, marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <FiPlusCircle style={{ color: 'hsl(var(--accent-color))' }} />
            Nouvelle Facture POS
          </h2>

          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>

            {/* Vente occasionnelle toggle */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '7px 10px', borderRadius: 'var(--radius-sm)', backgroundColor: isOccasional ? 'hsl(var(--color-info) / 0.08)' : 'hsl(var(--bg-tertiary))', border: `1px solid ${isOccasional ? 'hsl(var(--color-info) / 0.3)' : 'hsl(var(--border-color))'}`, cursor: 'pointer' }}
              onClick={() => { setIsOccasional(v => !v); if (!isOccasional) { setSelectedClient(null); setClientSearch(''); } }}
            >
              <input type="checkbox" checked={isOccasional} onChange={() => {}} style={{ cursor: 'pointer', accentColor: 'hsl(var(--color-info))' }} />
              <span style={{ fontSize: '0.72rem', fontWeight: 700, color: isOccasional ? 'hsl(var(--color-info))' : 'hsl(var(--text-secondary))' }}>
                Vente occasionnelle (sans client enregistré)
              </span>
            </div>

            {/* BUG-090 : un remboursement/dépôt exige un client enregistré — rappel visible
                dès que la vente occasionnelle est cochée, pour ne pas induire en erreur le
                facturier qui chercherait ce bouton sans l'avoir trouvé. */}
            {isOccasional && (
              <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', padding: '0 2px' }}>
                Un remboursement de dette ou un dépôt épargne nécessite un client enregistré — décochez « Vente occasionnelle » et recherchez le client.
              </div>
            )}

            {/* Vente soldée */}
            <div
              style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '7px 10px', borderRadius: 'var(--radius-sm)', backgroundColor: venteSoldee ? 'hsl(var(--color-warning) / 0.08)' : 'hsl(var(--bg-tertiary))', border: `1px solid ${venteSoldee ? 'hsl(var(--color-warning) / 0.4)' : 'hsl(var(--border-color))'}`, cursor: 'pointer' }}
              onClick={() => setVenteSoldee(v => !v)}
            >
              <input type="checkbox" checked={venteSoldee} onChange={() => {}} style={{ cursor: 'pointer', accentColor: 'hsl(var(--color-warning))' }} />
              <span style={{ fontSize: '0.72rem', fontWeight: 700, color: venteSoldee ? 'hsl(var(--color-warning))' : 'hsl(var(--text-secondary))' }}>
                Vente Soldée / Vente Cash — -25% sur le prix catalogue, 0% commission, manquant non imputé en BP
                {/* BUG-096 : distinct de « Vente occasionnelle » (client non enregistré) — les deux sont combinables. */}
              </span>
            </div>
            {venteSoldee && (
              <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', padding: '0 2px' }}>
                Remise automatique de 25 % appliquée par le serveur sur le prix catalogue de chaque pain ;
                distinct de « Vente occasionnelle » (client non enregistré) — les deux cases sont combinables.
              </div>
            )}

            {/* BUG-052 : Vente sans commission (25%) — distincte et combinable avec « Vente
                Soldée » ci-dessus. Ne change ni le prix ni le traitement de la BP : seule la
                commission (CM) est annulée (remarque.md l.190). */}
            <div
              style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '7px 10px', borderRadius: 'var(--radius-sm)', backgroundColor: commissionExempt ? 'hsl(var(--color-info) / 0.08)' : 'hsl(var(--bg-tertiary))', border: `1px solid ${commissionExempt ? 'hsl(var(--color-info) / 0.4)' : 'hsl(var(--border-color))'}`, cursor: 'pointer' }}
              onClick={() => setCommissionExempt(v => !v)}
            >
              <input type="checkbox" checked={commissionExempt} onChange={() => {}} style={{ cursor: 'pointer', accentColor: 'hsl(var(--color-info))' }} />
              <span style={{ fontSize: '0.72rem', fontWeight: 700, color: commissionExempt ? 'hsl(var(--color-info))' : 'hsl(var(--text-secondary))' }}>
                Vente sans commission (25%) — geste commercial ponctuel, prix et BP inchangés
              </span>
            </div>
            {commissionExempt && (
              <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', padding: '0 2px' }}>
                {venteSoldee
                  ? 'Facture à la fois SOLDÉE (prix à 75%, BP gelée) ET sans commission — les deux cases restent combinables, CM=0 dans tous les cas.'
                  : 'Distinct de « Vente Soldée » (ci-dessus) : ici le prix reste plein et la BP suit la commande normalement, seule la commission (CM) est annulée.'}
              </div>
            )}

            {/* Code spécial optionnel */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <button
                type="button"
                onClick={() => { setShowSpecialCode(v => !v); if (showSpecialCode) setSpecialCode(''); }}
                style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '0.68rem', color: 'hsl(var(--text-muted))', padding: 0, textDecoration: 'underline' }}
              >
                {showSpecialCode ? '− Code spécial' : '+ Code spécial (NV/RG/NS)'}
              </button>
              {showSpecialCode && (
                <select
                  value={specialCode}
                  onChange={e => setSpecialCode(e.target.value as '' | 'NV' | 'RG' | 'NS')}
                  className="form-input"
                  style={{ height: '28px', fontSize: '0.75rem', flex: 1 }}
                >
                  <option value="">— Aucun</option>
                  <option value="NV">NV — Nouveau client</option>
                  <option value="RG">RG — Régularisation</option>
                  <option value="NS">NS — Non Servi</option>
                </select>
              )}
            </div>

            {/* BUG-083 : date de commande rétroactive — visible seulement si activé en Configuration */}
            {allowBackdatedSales && (
              <div>
                <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--color-warning))', marginBottom: '2px', textTransform: 'uppercase' }}>
                  Date de la commande (optionnel)
                </label>
                <span style={{ display: 'block', fontSize: '0.6rem', color: 'hsl(var(--text-muted))', marginBottom: '4px' }}>
                  Laisser vide = aujourd'hui. Jamais une date future.
                </span>
                <input
                  type="date"
                  max={workDate}
                  value={invoiceDate}
                  onChange={e => setInvoiceDate(e.target.value)}
                  className="form-input"
                  style={{ fontSize: '0.78rem', height: '30px', padding: '0 8px' }}
                />
              </div>
            )}

            {/* Predictive client search */}
            {!isOccasional && <div style={{ position: 'relative' }}>
              <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px', textTransform: 'uppercase' }}>
                Client — code ou nom *
              </label>
              <div style={{ position: 'relative' }}>
                <FiSearch style={{ position: 'absolute', left: '9px', top: '50%', transform: 'translateY(-50%)', color: 'hsl(var(--text-muted))', fontSize: '0.85rem', pointerEvents: 'none' }} />
                <input
                  ref={searchRef}
                  type="text"
                  placeholder="Ex: K1-0045 ou KANZA Albert..."
                  value={clientSearch}
                  onChange={e => { setClientSearch(e.target.value); setSelectedClient(null); setShowSuggestions(true); }}
                  onFocus={() => setShowSuggestions(true)}
                  onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
                  className="form-input"
                  style={{ paddingLeft: '28px', paddingRight: selectedClient ? '28px' : '8px', fontSize: '0.78rem', height: '32px', borderColor: selectedClient ? 'hsl(var(--color-success) / 0.5)' : undefined }}
                  autoComplete="off"
                />
                {selectedClient && (
                  <button type="button" onClick={clearClient} style={{ position: 'absolute', right: '6px', top: '50%', transform: 'translateY(-50%)', border: 'none', background: 'none', cursor: 'pointer', color: 'hsl(var(--text-muted))', padding: 0 }}>
                    <FiX style={{ fontSize: '0.8rem' }} />
                  </button>
                )}
              </div>

              {/* État de la recherche serveur — BUG-065 : la saisie reste réactive, l'attente
                  réseau (debounce 350 ms) est visible plutôt que silencieuse */}
              {showSuggestions && !selectedClient && clientSearch.length >= 1 && isSearchingClients && (
                <div style={{
                  position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 50,
                  backgroundColor: 'hsl(var(--bg-secondary))', border: '1px solid hsl(var(--border-color))',
                  borderRadius: 'var(--radius-sm)', boxShadow: 'var(--shadow-md)', marginTop: '2px',
                  padding: '8px 12px', fontSize: '0.72rem', color: 'hsl(var(--text-muted))'
                }}>
                  Recherche en cours…
                </div>
              )}
              {showSuggestions && !selectedClient && !isSearchingClients && clientSearchError && (
                <div style={{
                  position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 50,
                  backgroundColor: 'hsl(var(--bg-secondary))', border: '1px solid hsl(var(--color-danger) / 0.4)',
                  borderRadius: 'var(--radius-sm)', boxShadow: 'var(--shadow-md)', marginTop: '2px',
                  padding: '8px 12px', fontSize: '0.72rem', color: 'hsl(var(--color-danger))'
                }}>
                  {clientSearchError}
                </div>
              )}
              {showSuggestions && !selectedClient && !isSearchingClients && !clientSearchError
                && clientSearch.length >= 1 && suggestions.length === 0 && (
                <div style={{
                  position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 50,
                  backgroundColor: 'hsl(var(--bg-secondary))', border: '1px solid hsl(var(--border-color))',
                  borderRadius: 'var(--radius-sm)', boxShadow: 'var(--shadow-md)', marginTop: '2px',
                  padding: '8px 12px', fontSize: '0.72rem', color: 'hsl(var(--text-muted))'
                }}>
                  Aucun client ne correspond à « {clientSearch} ».
                </div>
              )}
              {showSuggestions && suggestions.length > 0 && !selectedClient && !isSearchingClients && (
                <div style={{
                  position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 50,
                  backgroundColor: 'hsl(var(--bg-secondary))', border: '1px solid hsl(var(--border-color))',
                  borderRadius: 'var(--radius-sm)', boxShadow: 'var(--shadow-md)', marginTop: '2px', overflow: 'hidden'
                }}>
                  {suggestions.map(c => (
                    <div
                      key={c.id}
                      onMouseDown={() => selectClient(c)}
                      style={{ padding: '8px 12px', cursor: 'pointer', borderBottom: '1px solid hsl(var(--border-color) / 0.5)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
                      className="theme-picker-btn"
                    >
                      <div>
                        <span style={{ fontWeight: 800, fontSize: '0.72rem', color: 'hsl(var(--accent-color))' }}>{c.code}</span>
                        <span style={{ fontSize: '0.78rem', marginLeft: '8px', fontWeight: 700 }}>{c.full_name}</span>
                        {c.category === 'RISK' && (
                          <span style={{ marginLeft: '6px', fontSize: '0.6rem', fontWeight: 800, padding: '1px 6px', borderRadius: '999px', backgroundColor: 'hsl(var(--color-danger) / 0.15)', color: 'hsl(var(--color-danger))' }}>À risque</span>
                        )}
                      </div>
                      <span style={{ fontSize: '0.65rem', color: parseFloat(c.current_debt) > 0 ? 'hsl(var(--color-warning))' : 'hsl(var(--text-muted))', fontWeight: 700 }}>
                        {parseFloat(c.current_debt) > 0 ? `BP: ${parseFloat(c.current_debt).toLocaleString('fr-FR')} FC` : 'Solde OK'}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>}

            {/* Selected client info */}
            {!isOccasional && selectedClient && (
              <div style={{ backgroundColor: 'hsl(var(--color-success) / 0.08)', border: '1px solid hsl(var(--color-success) / 0.25)', borderRadius: 'var(--radius-sm)', padding: '8px 10px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.7rem' }}>
                <div>
                  <div style={{ fontWeight: 800, color: 'hsl(var(--accent-color))' }}>{selectedClient.code} — {selectedClient.full_name}</div>
                  <div style={{ color: 'hsl(var(--text-secondary))', marginTop: '1px' }}>Taux CM : {(parseFloat(selectedClient.commission_rate) * 100).toFixed(0)}%</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontWeight: 800, color: parseFloat(selectedClient.current_debt) > 0 ? 'hsl(var(--color-warning))' : 'hsl(var(--color-success))' }}>
                    BP : {parseFloat(selectedClient.current_debt).toLocaleString('fr-FR')} FC
                  </div>
                  <div style={{ color: 'hsl(var(--text-muted))' }}>Balance antérieure</div>
                </div>
              </div>
            )}

            {/* BUG-229 : client à risque servi quand même ; le serveur décide du blocage (403). */}
            {!isOccasional && selectedClient && selectedClient.category === 'RISK' && (
              <div role="alert" style={{ backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.4)', borderRadius: 'var(--radius-sm)', padding: '8px 10px', fontSize: '0.7rem', color: 'hsl(var(--color-danger))', fontWeight: 700 }}>
                Client à risque — BP {parseFloat(selectedClient.current_debt).toLocaleString('fr-FR')} FC
                {parseFloat(selectedClient.credit_limit) > 0 && ` / plafond ${parseFloat(selectedClient.credit_limit).toLocaleString('fr-FR')} FC`}.
                <div style={{ fontWeight: 500, marginTop: '2px' }}>
                  Si la BP atteint le plafond, la facture n'est acceptée que si le versement couvre au moins la valeur de la commande ; sinon le serveur la refuse.
                </div>
              </div>
            )}

            {/* BUG-090 : remboursement de dette / dépôt épargne — paiement seul, sans
                commande de pain. Nécessite un client enregistré (pas une vente occasionnelle). */}
            {!isOccasional && selectedClient && (
              <button
                type="button"
                onClick={() => { setRepaymentAmount(''); setRepaymentMotif(''); setRepaymentDate(''); setRepaymentError(null); setIsRepaymentModalOpen(true); }}
                className="btn btn-secondary"
                style={{ padding: '7px 10px', fontSize: '0.72rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', color: 'hsl(var(--color-info))', borderColor: 'hsl(var(--color-info) / 0.4)' }}
                title="Enregistrer un versement sans commande de pain : remboursement de dette ou dépôt épargne"
              >
                <FiCreditCard />
                <span>Remboursement / Dépôt sans commande</span>
              </button>
            )}

            {/* Bread quantities — line-by-line with running total */}
            <div>
              <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '6px', textTransform: 'uppercase' }}>
                Commande (Qté × Catégorie)
              </label>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                {/* Header row */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 60px 80px', gap: '4px', fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, textTransform: 'uppercase', paddingBottom: '2px' }}>
                  <span>Catégorie</span><span style={{ textAlign: 'right' }}>Qté</span><span style={{ textAlign: 'right' }}>Sous-total</span>
                </div>
                {breadPrices.map(bp => {
                  const qty = quantities[bp.id] || 0;
                  // BUG-107 : sous-total à l'écran avec remise de 75% appliquée (Vente Soldée)
                  const lineTotal = qty * effectiveUnitPrice(bp);
                  return (
                    <div key={bp.id} style={{ display: 'grid', gridTemplateColumns: '1fr 60px 80px', gap: '4px', alignItems: 'center' }}>
                      <span style={{ fontSize: '0.73rem', color: qty > 0 ? 'hsl(var(--text-primary))' : 'hsl(var(--text-secondary))', fontWeight: qty > 0 ? 700 : 400 }}>
                        {bp.label}
                      </span>
                      <input
                        type="number" min={0}
                        value={qty || ''}
                        placeholder="0"
                        onChange={e => setQuantities(prev => ({ ...prev, [bp.id]: Math.max(0, Number(e.target.value)) }))}
                        className="form-input"
                        style={{ fontSize: '0.78rem', height: '28px', padding: '0 6px', textAlign: 'right', fontWeight: 700 }}
                      />
                      <span style={{ fontSize: '0.73rem', textAlign: 'right', fontWeight: lineTotal > 0 ? 800 : 400, color: lineTotal > 0 ? 'hsl(var(--accent-color))' : 'hsl(var(--text-muted))' }}>
                        {lineTotal > 0 ? `${lineTotal.toLocaleString('fr-FR')} FC` : '—'}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Order total */}
            <div style={{ backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px dashed hsl(var(--border-color))', padding: '8px 10px', borderRadius: 'var(--radius-sm)', display: 'flex', flexDirection: 'column', gap: '2px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '0.72rem', color: 'hsl(var(--text-secondary))' }}>Total commande :</span>
                <strong style={{ color: 'hsl(var(--accent-color))', fontSize: '0.88rem' }}>{orderTotal.toLocaleString('fr-FR')} FC</strong>
              </div>
              {/* BUG-107 : rend explicite que le total ci-dessus intègre déjà la remise à 75 %
                  (prix catalogue plein affiché à titre de comparaison, jamais ce qui sera facturé) */}
              {venteSoldee && (
                <div style={{ fontSize: '0.6rem', color: 'hsl(var(--color-warning))', textAlign: 'right' }}>
                  Remise de 25% déjà appliquée (prix catalogue plein : {breadPrices.reduce((s, b) => s + (quantities[b.id] || 0) * b.unit_price, 0).toLocaleString('fr-FR')} FC)
                </div>
              )}
            </div>

            {/* BUG-177 : Non Servi — le type de paiement exprime le choix du client, sans versement */}
            {isNonServiForm && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--color-warning))', textTransform: 'uppercase' }}>
                  Client non servi — dette
                </label>
                <select
                  value={nsPaymentType}
                  onChange={e => setNsPaymentType(e.target.value as 'CASH' | 'CREDIT')}
                  className="form-input"
                  style={{ height: '34px', fontSize: '0.78rem' }}
                  aria-label="Choix du client non servi"
                >
                  <option value="CREDIT">Le client garde la dette</option>
                  <option value="CASH">Payé comptant</option>
                </select>
                <span style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))' }}>
                  Aucun pain n'est retiré du stock ; la dette n'est enregistrée que si le client la garde.
                </span>
              </div>
            )}
            {isRegularisationForm && (
              <div style={{ fontSize: '0.64rem', color: 'hsl(var(--text-muted))', padding: '0 2px' }}>
                Régularisation : aucune dette n'est créée (aucun versement à saisir).
              </div>
            )}

            {/* Versement + auto payment type */}
            {!isNonServiForm && !isRegularisationForm && <div>
              <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--color-success))', marginBottom: '2px', textTransform: 'uppercase' }}>
                Versement du Jour (FC)
              </label>
              <span style={{ display: 'block', fontSize: '0.6rem', color: 'hsl(var(--text-muted))', marginBottom: '4px' }}>Acompte en espèces versé ce jour</span>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: '6px', alignItems: 'center' }}>
                <input
                  type="text" inputMode="text" autoComplete="off" pattern="-?[0-9]*"
                  aria-label="Versement du jour en francs congolais (le signe moins est accepté)"
                  value={isCashOnlySale ? String(orderTotal) : versementText}
                  placeholder="0 (ex. -5000)"
                  disabled={isCashOnlySale}
                  onChange={e => {
                    // Entier signé : « − » typographique et espaces tolérés, tout le reste ignoré.
                    const raw = e.target.value.replace(/[−–—]/g, '-').replace(/[\s  ]/g, '');
                    if (!/^-?\d*$/.test(raw)) return;
                    setVersementText(raw);
                    setVersement(raw === '' || raw === '-' ? 0 : parseInt(raw, 10));
                  }}
                  className="form-input"
                  style={{ fontSize: '0.78rem', height: '30px', padding: '0 8px', borderColor: 'hsl(var(--color-success) / 0.4)', fontWeight: 800 }}
                />
                <span className={`badge ${venteSoldee ? 'badge-warning' : paymentType === 'CASH' ? 'badge-success' : 'badge-warning'}`} style={{ fontSize: '0.6rem', whiteSpace: 'nowrap' }}>
                  {venteSoldee ? 'SOLDÉ ✓' : paymentType === 'CASH' ? 'CASH ✓' : 'CRÉDIT'}
                </span>
              </div>
              {isCashOnlySale && (
                <div style={{ fontSize: '0.62rem', color: 'hsl(var(--color-info))', marginTop: '3px', fontWeight: 700 }}>
                  Vente sans client enregistré : paiement comptant obligatoire, le versement est égal à la valeur de la commande (pas de crédit).
                </div>
              )}
              {selectedClient && orderTotal > 0 && (
                <div style={{ fontSize: '0.62rem', color: venteSoldee ? 'hsl(var(--color-warning))' : 'hsl(var(--text-muted))', marginTop: '3px', fontWeight: venteSoldee ? 700 : 400 }}>
                  {venteSoldee
                    ? 'Vente soldée — aucune dette ajoutée au BP'
                    : `Nouvelle BP ≈ ${(parseFloat(selectedClient.current_debt) + orderTotal - versement).toLocaleString('fr-FR')} FC`}
                </div>
              )}
              {versement < 0 && !isCashOnlySale && (
                <div style={{ fontSize: '0.62rem', color: 'hsl(var(--color-warning))', marginTop: '3px', fontWeight: 700 }}>
                  Versement négatif : sortie de caisse ({versement.toLocaleString('fr-FR')} FC), la BP augmente. Le blocage de crédit reste appliqué par le serveur.
                </div>
              )}
              {!isCashOnlySale && !isNonServiForm && !isRegularisationForm && (
                <div style={{ marginTop: '8px' }}><MotifSelect value={motif} onChange={setMotif} /></div>
              )}
            </div>}

            {formError && (
              <div style={{ backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.3)', borderRadius: 'var(--radius-sm)', padding: '7px 10px', fontSize: '0.7rem', color: 'hsl(var(--color-danger))', display: 'flex', alignItems: 'flex-start', gap: '6px' }}>
                <FiAlertCircle style={{ flexShrink: 0, marginTop: '1px' }} />
                <span>{formError}</span>
              </div>
            )}

            <button type="submit" disabled={isSubmitting || closureBlocked} className="btn btn-primary" style={{ padding: '8px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', opacity: (isSubmitting || closureBlocked) ? 0.55 : 1 }}>
              <FiCheckCircle />
              <span>{closureBlocked ? 'Ventes bloquées — clôture en attente' : isSubmitting ? 'Enregistrement...' : isNonServiForm ? 'Enregistrer le non servi' : 'Facturer & Mettre en Attente'}</span>
            </button>
          </form>
        </div>
  );
};
