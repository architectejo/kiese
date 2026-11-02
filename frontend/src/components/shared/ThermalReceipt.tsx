import React, { useState } from 'react';
import { createPortal } from 'react-dom';
import { FiPrinter, FiLoader } from 'react-icons/fi';

// ── Receipt data ──────────────────────────────────────────────────────────────
export interface ReceiptLine { label: string; qty: number; unitPrice: number }
export interface ReceiptData {
  receiptNumber: string;
  boulangerie: string;
  agentName: string;
  team: string;
  clientCode: string;
  clientName: string;
  lines: ReceiptLine[];
  orderTotal: number;
  versement: number;
  commissionRate: number;
  debtBefore: number;
  newDebt: number;
  isSoldee?: boolean;
  /**
   * BUG-092/BUG-096 : perte = (prix catalogue − prix facturé) × quantité, agrégée sur la facture
   * (`Invoice.total_loss`, calculée côté serveur). Nulle/absente hors vente soldée — n'affiche
   * rien dans ce cas. Résulte du mécanisme attendu de la vente soldée (-25 % sur le catalogue),
   * donc présentée en alerte discrète, pas alarmante.
   */
  totalLoss?: number;
  /**
   * Date/heure réelle de la transaction (livraison si disponible, sinon
   * facturation), telle qu'enregistrée en base (`inv.delivered_at` ou
   * `inv.invoice_date`), au format ISO (date seule `AAAA-MM-JJ` ou
   * horodatage complet). BUG-099 : sans ce champ, le reçu affichait
   * l'horloge du navigateur au moment de l'IMPRESSION plutôt que la date
   * réelle de la vente — trompeur dès qu'une facture/livraison est
   * rétroactive (`Config.allow_backdated_sales`, BUG-083). Optionnel :
   * laissé vide, le comportement retombe sur « maintenant » (cas normal,
   * immense majorité des reçus, où la transaction a bien lieu aujourd'hui).
   */
  transactionDate?: string;
}

/**
 * Document HTML autonome envoyé à `window.kiese.printReceipt()` (impression
 * silencieuse Electron, `desktop/src/printing.ts`). Le reçu affiché à l'écran
 * utilise déjà des styles inline (`style={{...}}`) sur chaque élément : ils
 * sont donc conservés tels quels dans `innerHtml` (capturé via `outerHTML`
 * d'un clone du nœud #${domId}), seule une feuille de base minimale est
 * ajoutée ici pour la police et le fond de page.
 */
const buildPrintableHtml = (innerHtml: string, widthMm: 58 | 80): string => `<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8" />
<style>
  * { box-sizing: border-box; }
  html, body {
    margin: 0; padding: 0; background: #fff; color: #000;
    font-family: "Courier New", Courier, monospace;
  }
  body { width: ${widthMm}mm; }
</style>
</head>
<body>${innerHtml}</body>
</html>`;

// ── Receipt component ─────────────────────────────────────────────────────────
export const ThermalReceipt: React.FC<{
  receipt: ReceiptData;
  onClose: () => void;
  printId?: string;
  /**
   * Largeur du rouleau thermique réellement configurée sur le poste
   * (58 ou 80 mm). BUG-076 : à ce jour, `window.kiese` (desktop/src/preload.ts)
   * n'expose PAS la valeur choisie à l'installation (`DesktopConfig.printerWidthMm`,
   * voir desktop/src/config.ts) — aucun endpoint IPC ne la lit. Tant que ce
   * n'est pas ajouté côté `desktop/` (ticket à ouvrir pour packaging-desktop),
   * ce composant ne peut pas la détecter lui-même : la valeur par défaut
   * (80 mm, identique au défaut de `firstRun.ts`) est utilisée si l'appelant
   * ne la précise pas explicitement.
   */
  printerWidthMm?: 58 | 80;
}> = ({ receipt, onClose, printId = 'receipt', printerWidthMm = 80 }) => {
  // BUG-099 : priorité à la date réelle de la transaction transmise par l'appelant
  // (`transactionDate`, issue de `inv.delivered_at`/`inv.invoice_date`) ; repli sur
  // l'horloge courante uniquement si elle est absente ou invalide (ex. ancien
  // appelant pas encore migré, ou `new Date(...)` ne sait pas la parser).
  const now = new Date();
  const parsedTxDate = receipt.transactionDate ? new Date(receipt.transactionDate) : null;
  const effectiveDate = parsedTxDate && !isNaN(parsedTxDate.getTime()) ? parsedTxDate : now;
  const dateStr = effectiveDate.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  const timeStr = effectiveDate.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
  const domId = `thermal-receipt-${printId}`;
  const [isPrinting, setIsPrinting] = useState(false);
  const [printError, setPrintError] = useState<string | null>(null);

  // Rouleau 58 mm : surface utile plus étroite qu'à 80 mm → on réduit
  // proportionnellement les tailles de police pour éviter un texte tronqué
  // ou illisible après réduction automatique par le pilote d'imprimante
  // (BUG-076).
  const scale = printerWidthMm === 58 ? 0.82 : 1;
  const rem = (n: number): string => `${+(n * scale).toFixed(3)}rem`;
  const previewMaxWidth = printerWidthMm === 58 ? '240px' : '320px';

  const cell: React.CSSProperties = { border: '1px solid #000', padding: '2px 4px' };
  const cellR: React.CSSProperties = { ...cell, textAlign: 'right' };
  const cellC: React.CSSProperties = { ...cell, textAlign: 'center' };
  const tbl: React.CSSProperties = { width: '100%', borderCollapse: 'collapse', fontSize: rem(0.6) };
  // client_display from the API already carries "[code] Nom" — strip it so
  // the "[code] Nom" line below doesn't show the code twice.
  const clientDisplayName = receipt.clientName.replace(/^\[[^\]]*\]\s*/, '');

  const handlePrint = async (): Promise<void> => {
    const bridge = typeof window !== 'undefined' ? window.kiese : undefined;
    if (!bridge?.printReceipt) {
      // Navigateur classique (ou POS Android) : pas de pont Electron,
      // comportement standard du navigateur (CLAUDE.md §8 ne s'applique
      // qu'au desktop).
      window.print();
      return;
    }
    const el = document.getElementById(domId);
    if (!el) return;
    setPrintError(null);
    setIsPrinting(true);
    try {
      // On imprime un clone débarrassé des contraintes propres à l'aperçu
      // écran (largeur plafonnée, ombre, coins arrondis) : la largeur
      // physique réelle (58/80 mm) est imposée par Electron via `widthMm`.
      const clone = el.cloneNode(true) as HTMLElement;
      clone.style.width = '100%';
      clone.style.maxWidth = 'none';
      clone.style.boxShadow = 'none';
      clone.style.borderRadius = '0';
      const html = buildPrintableHtml(clone.outerHTML, printerWidthMm);
      const result = await bridge.printReceipt(html, { widthMm: printerWidthMm });
      if (!result.ok) {
        setPrintError(result.error || "Échec de l'impression silencieuse (voir journaux).");
      }
    } catch (err) {
      setPrintError(err instanceof Error ? err.message : "Échec de l'impression silencieuse.");
    } finally {
      setIsPrinting(false);
    }
  };

  return createPortal(
    <div style={{
      position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.75)',
      backdropFilter: 'blur(8px)', display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'flex-start', zIndex: 2000, padding: '40px 20px', overflowY: 'auto'
    }}>
      <style>{`
        @media print {
          body * { visibility: hidden !important; }
          #${domId}, #${domId} * { visibility: visible !important; }
          #${domId} {
            position: absolute !important; left: 50% !important; top: 0 !important;
            transform: translateX(-50%) !important; width: ${printerWidthMm}mm !important;
            margin: 0 !important; padding: 8px !important;
            box-shadow: none !important; border: none !important;
            background: #fff !important; color: #000 !important;
          }
        }
      `}</style>

      <div id={domId} style={{
        width: '100%', maxWidth: previewMaxWidth, backgroundColor: '#fff', color: '#000',
        fontFamily: '"Courier New", Courier, monospace', padding: '10px', borderRadius: '2px',
        boxShadow: '0 8px 30px rgba(0,0,0,0.3)', fontSize: rem(0.68), lineHeight: '1.25',
      }}>
        {/* ── En-tête ── */}
        <div style={{ textAlign: 'center', marginBottom: '4px' }}>
          <div style={{ fontSize: rem(0.82), fontWeight: 'bold', letterSpacing: '1px' }}>ETS. KIESE / BOULANGERIE</div>
          <div style={{ fontSize: rem(0.58), fontWeight: 'bold', marginTop: '1px' }}>{receipt.boulangerie}</div>
          <div style={{ fontSize: rem(0.5), marginTop: '2px' }}>
            ID.Nat: 10-F4300-N85947U | Impôt: A1902266K | RCCM: 021-A-650
          </div>
          <div style={{ fontSize: rem(0.52) }}>Siège : 49, Av. Tabora / Mbanza-Ngungu</div>
          <div style={{ fontSize: rem(0.52) }}>Tél: +243 851 992 947</div>
        </div>

        <div style={{ textAlign: 'center', fontWeight: 'bold', fontSize: rem(0.56), borderTop: '2px solid #000', borderBottom: '2px solid #000', padding: '2px 0', margin: '4px 0' }}>
          BON DE LIVRAISON N° {receipt.receiptNumber}{receipt.isSoldee ? ' — SOLDÉE' : ''}
        </div>

        {/* ── Infos facture ── */}
        <table style={{ ...tbl, marginBottom: '4px' }}>
          <tbody>
            <tr>
              <td style={{ fontSize: rem(0.54), padding: '1px 0', width: '20%' }}>Date :</td>
              <td style={{ fontSize: rem(0.54), padding: '1px 0', fontWeight: 'bold' }}>{dateStr}</td>
              <td style={{ fontSize: rem(0.54), padding: '1px 0', textAlign: 'right', width: '20%' }}>Heure :</td>
              <td style={{ fontSize: rem(0.54), padding: '1px 0', textAlign: 'right', fontWeight: 'bold' }}>{timeStr}</td>
            </tr>
            <tr>
              <td style={{ fontSize: rem(0.54), padding: '1px 0' }}>Caisse :</td>
              <td colSpan={3} style={{ fontSize: rem(0.54), padding: '1px 0' }}>{receipt.agentName.toUpperCase()} — Éq. {receipt.team}</td>
            </tr>
          </tbody>
        </table>

        <div style={{ fontSize: rem(0.56), fontWeight: 'bold', borderTop: '1px solid #000', borderBottom: '1px solid #000', padding: '2px 0', marginBottom: '4px' }}>
          CLIENT : [{receipt.clientCode}] {clientDisplayName.toUpperCase()}
        </div>

        {/* ── Tableau des articles ── */}
        {/*
          BUG-116 : un remboursement de dette ou un dépôt client épargne (sans
          commande, `createRepayment`) produit une facture sans aucune ligne
          (`lines: []`). Le tableau QTE/DESIGNATION/P.U/T.P n'a alors aucun
          sens (il afficherait un entête vide suivi directement des totaux à
          0) : on le remplace par une bannière explicite, sans toucher à la
          structure `ReceiptData` partagée avec le flux de vente normal.
        */}
        {receipt.lines.length === 0 && (
          <div style={{
            textAlign: 'center', fontWeight: 'bold', fontSize: rem(0.58),
            backgroundColor: '#e0e0e0', border: '1px solid #000', padding: '3px 0', marginBottom: '2px',
          }}>
            REMBOURSEMENT DE DETTE / DÉPÔT (sans commande)
          </div>
        )}
        <table style={tbl}>
          {receipt.lines.length > 0 && (
            <thead>
              <tr style={{ backgroundColor: '#e0e0e0' }}>
                <th style={{ ...cellC, width: '12%' }}>QTE</th>
                <th style={{ ...cell, textAlign: 'left', width: '44%' }}>DESIGNATION</th>
                <th style={{ ...cellR, width: '22%' }}>P.U</th>
                <th style={{ ...cellR, width: '22%' }}>T.P</th>
              </tr>
            </thead>
          )}
          <tbody>
            {receipt.lines.map((l, i) => (
              <tr key={i}>
                <td style={cellC}>{l.qty}</td>
                <td style={cell}>{l.label}</td>
                <td style={cellR}>{l.unitPrice.toLocaleString('fr-FR')}</td>
                <td style={cellR}>{(l.qty * l.unitPrice).toLocaleString('fr-FR')}</td>
              </tr>
            ))}
            {/* ── Sous-totaux ── */}
            <tr>
              <td colSpan={3} style={{ ...cellR, fontWeight: 'bold' }}>SOUS-TOTAL</td>
              <td style={{ ...cellR, fontWeight: 'bold' }}>{receipt.orderTotal.toLocaleString('fr-FR')}</td>
            </tr>
            <tr>
              <td colSpan={3} style={cellR}>VERSEMENT DU JOUR</td>
              <td style={cellR}>{receipt.versement.toLocaleString('fr-FR')}</td>
            </tr>
            <tr style={{ backgroundColor: '#e0e0e0' }}>
              <td colSpan={3} style={{ ...cellR, fontWeight: 'bold', fontSize: rem(0.64) }}>TOTAL (FC)</td>
              <td style={{ ...cellR, fontWeight: 'bold', fontSize: rem(0.64) }}>{receipt.orderTotal.toLocaleString('fr-FR')}</td>
            </tr>
            <tr>
              <td colSpan={3} style={cellR}>COMMISSION ({(receipt.commissionRate * 100).toFixed(0)}%){receipt.isSoldee ? ' [SOLDÉE]' : ''}</td>
              <td style={cellR}>{(receipt.orderTotal * receipt.commissionRate).toLocaleString('fr-FR')}</td>
            </tr>
            {/* BUG-092/BUG-096 : perte de la vente soldée (-25% sur le prix catalogue) —
                attendue par ce mécanisme, affichée en alerte discrète, pas alarmante. */}
            {receipt.isSoldee && !!receipt.totalLoss && receipt.totalLoss > 0 && (
              <tr>
                <td colSpan={3} style={{ ...cellR, color: '#8a6d00' }}>PERTE (VENTE SOLDÉE)</td>
                <td style={{ ...cellR, color: '#8a6d00', fontWeight: 'bold' }}>-{receipt.totalLoss.toLocaleString('fr-FR')}</td>
              </tr>
            )}
          </tbody>
        </table>

        {/* ── Situation comptable ── */}
        <table style={{ ...tbl, marginTop: '5px' }}>
          <tbody>
            <tr>
              <td style={cell}>BALANCE ANTÉRIEURE (BP)</td>
              <td style={{ ...cellR, fontWeight: 'bold' }}>{receipt.debtBefore.toLocaleString('fr-FR')} FC</td>
            </tr>
            <tr style={{ backgroundColor: '#e0e0e0' }}>
              <td style={{ ...cell, fontWeight: 'bold' }}>NOUVELLE DETTE</td>
              <td style={{ ...cellR, fontWeight: 'bold' }}>{receipt.newDebt.toLocaleString('fr-FR')} FC</td>
            </tr>
          </tbody>
        </table>

        {/* ── Pied ── */}
        <div style={{ textAlign: 'center', fontSize: rem(0.56), fontWeight: 'bold', marginTop: '6px', borderTop: '1px dashed #000', paddingTop: '4px' }}>
          Solde arrêté ce jour
        </div>
        <div style={{ textAlign: 'center', fontSize: rem(0.5), marginTop: '2px' }}>
          <div style={{ fontStyle: 'italic' }}>Merci pour votre fidélité !</div>
        </div>
      </div>

      {printError && (
        <div style={{
          width: '100%', maxWidth: previewMaxWidth, marginTop: '12px', padding: '8px 10px',
          backgroundColor: '#fdecea', color: '#611a15', border: '1px solid #f5c6cb',
          borderRadius: '4px', fontSize: '0.78rem',
        }}>
          {printError}
        </div>
      )}

      <div style={{ display: 'flex', gap: '12px', width: '100%', maxWidth: previewMaxWidth, marginTop: '16px' }}>
        <button onClick={onClose} className="btn btn-secondary" style={{ flex: 1, padding: '10px', fontSize: '0.85rem' }}>Fermer</button>
        <button
          onClick={handlePrint}
          disabled={isPrinting}
          className="btn btn-primary"
          style={{ flex: 2, padding: '10px', fontSize: '0.85rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', opacity: isPrinting ? 0.7 : 1 }}
        >
          {isPrinting ? <FiLoader /> : <FiPrinter />} {isPrinting ? 'Impression…' : 'Imprimer'}
        </button>
      </div>
    </div>,
    document.body
  );
};
