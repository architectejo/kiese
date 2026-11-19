import React, { useState } from 'react';
import type { DailyClosureReport } from '@/api/services';
import { Modal } from '@/components/shared/Modal';

// BUG-302 (remarque.md l.429) : les cartes de totaux de la Clôture Journalière ouvrent une
// boîte modale de détails au clic. Aucun calcul métier : les détails sont lus dans le
// rapport déjà chargé (`DailyClosureReport`), par catégorie de pain. Chaque carte est un
// <button> natif (Entrée / Espace, focus visible) ; le tableau de la modale défile
// horizontalement à 360 px au lieu de déborder.

const fc = (value: string | number | null | undefined): string => {
  if (value === null || value === undefined || value === '') return '—';
  const n = typeof value === 'string' ? parseFloat(value) : value;
  if (Number.isNaN(n)) return '—';
  return Math.round(n).toLocaleString('fr-FR') + ' FC';
};

const qty = (n: number | null | undefined): string =>
  n === null || n === undefined ? '—' : n.toLocaleString('fr-FR');

type KpiKey =
  | 'total' | 'net' | 'ecartFacture' | 'sacs' | 'moyenne' | 'tarif' | 'ecartProd' | 'pains';

interface DetailTable {
  headers: string[];
  rows: string[][];
  footer?: string[];
}

interface KpiDetail {
  title: string;
  explanation: string;
  table?: DetailTable;
}

const buildDetail = (key: KpiKey, report: DailyClosureReport): KpiDetail => {
  const { totals, categories } = report;
  switch (key) {
    case 'total':
      return {
        title: 'Total du Jour',
        explanation: "Montant facturé du jour toutes catégories (facture mouvements internes, non servi retranché).",
        table: {
          headers: ['Catégorie', 'Facture Mvm Interne', 'Non servi retranché'],
          rows: categories.map(c => [c.label, fc(c.facture_mvm_interne.fc), fc(c.non_servi.fc_signe)]),
          footer: ['Total du jour', fc(totals.total_du_jour_fc), ''],
        },
      };
    case 'net':
      return {
        title: 'Net Produit',
        explanation: 'Valeur nette produite du jour, par catégorie de pain.',
        table: {
          headers: ['Catégorie', 'Pains produits', 'Valeur produite'],
          rows: categories.map(c => [c.label, qty(c.produit.quantity), fc(c.produit.fc)]),
          footer: ['Net produit', qty(totals.total_breads_produced), fc(totals.net_produit_fc)],
        },
      };
    case 'ecartFacture':
      return {
        title: 'Écart / Facture',
        explanation: 'Écart entre le total du jour et la valeur facturée, avec le détail facturé par catégorie.',
        table: {
          headers: ['Catégorie', 'Pains facturés', 'Valeur facturée'],
          rows: categories.map(c => [c.label, qty(c.facture_jr.quantity), fc(c.facture_jr.fc)]),
          footer: ['Écart / Facture', qty(totals.total_breads_billed), fc(totals.ecart_facture_fc)],
        },
      };
    case 'sacs':
      return {
        title: 'Nombre de Sacs Produits',
        explanation: 'Nombre de sacs de farine utilisés par les fournées du jour.',
        table: {
          headers: ['Indicateur', 'Valeur'],
          rows: [
            ['Sacs produits', String(totals.nombre_sacs_produits)],
            ['Net produit', fc(totals.net_produit_fc)],
            ['Moyenne produit / sac', fc(totals.moyenne_produit_par_sac_fc)],
          ],
        },
      };
    case 'moyenne':
      return {
        title: 'Moyenne Produit / Sac',
        explanation: 'Valeur produite moyenne par sac de farine (net produit ÷ nombre de sacs).',
        table: {
          headers: ['Indicateur', 'Valeur'],
          rows: [
            ['Net produit', fc(totals.net_produit_fc)],
            ['Nombre de sacs', String(totals.nombre_sacs_produits)],
            ['Moyenne produit / sac', fc(totals.moyenne_produit_par_sac_fc)],
            ['Tarif vente (fixe)', fc(totals.tarif_vente_fc)],
          ],
        },
      };
    case 'tarif':
      return {
        title: 'Tarif Vente (fixe)',
        explanation: 'Valeur théorique de vente d\'un sac et prix de chaque catégorie de pain.',
        table: {
          headers: ['Catégorie', 'Prix unitaire'],
          rows: categories.map(c => [c.label, fc(c.unit_price)]),
          footer: ['Tarif vente (fixe)', fc(totals.tarif_vente_fc)],
        },
      };
    case 'ecartProd': {
      const n = parseFloat(totals.ecart_production_fc);
      const verdict = Number.isNaN(n) || n === 0 ? 'Aucun écart' : n < 0 ? 'Manquant' : 'Excédent';
      return {
        title: 'Écart / Production',
        explanation: `Écart entre la valeur théorique (sacs × tarif) et la valeur produite : ${verdict.toLowerCase()}.`,
        table: {
          headers: ['Indicateur', 'Valeur'],
          rows: [
            ['Nombre de sacs', String(totals.nombre_sacs_produits)],
            ['Tarif vente (fixe)', fc(totals.tarif_vente_fc)],
            ['Net produit', fc(totals.net_produit_fc)],
            [`Écart (${verdict})`, fc(totals.ecart_production_fc)],
          ],
        },
      };
    }
    case 'pains':
      return {
        title: 'Pains Produits / Facturés',
        explanation: 'Pains produits et pains facturés du jour, par catégorie.',
        table: {
          headers: ['Catégorie', 'Produits', 'Facturés'],
          rows: categories.map(c => [c.label, qty(c.produit.quantity), qty(c.facture_jr.quantity)]),
          footer: ['Total', qty(totals.total_breads_produced), qty(totals.total_breads_billed)],
        },
      };
  }
};

const labelStyle: React.CSSProperties = {
  fontSize: '0.6rem', color: 'hsl(var(--text-secondary))', fontWeight: 700, textTransform: 'uppercase',
};

export const ClotureKpiCards: React.FC<{ report: DailyClosureReport }> = ({ report }) => {
  const [open, setOpen] = useState<KpiKey | null>(null);
  const { totals } = report;

  const cards: Array<{ key: KpiKey; label: string; value: React.ReactNode; color?: string }> = [
    { key: 'total', label: 'Total du Jour', value: fc(totals.total_du_jour_fc), color: 'hsl(var(--accent-color))' },
    { key: 'net', label: 'Net Produit', value: fc(totals.net_produit_fc), color: 'hsl(var(--color-success))' },
    {
      key: 'ecartFacture', label: 'Écart / Facture', value: fc(totals.ecart_facture_fc),
      color: parseFloat(totals.ecart_facture_fc) > 0 ? 'hsl(var(--color-warning))' : 'hsl(var(--text-primary))',
    },
    { key: 'sacs', label: 'Nombre de Sacs Produits', value: totals.nombre_sacs_produits },
    { key: 'moyenne', label: 'Moyenne Produit / Sac', value: fc(totals.moyenne_produit_par_sac_fc) },
    { key: 'tarif', label: 'Tarif Vente (fixe)', value: fc(totals.tarif_vente_fc) },
    {
      key: 'ecartProd', label: 'Écart / Production', value: fc(totals.ecart_production_fc),
      color: parseFloat(totals.ecart_production_fc) < 0 ? 'hsl(var(--color-danger))' : 'hsl(var(--color-success))',
    },
    { key: 'pains', label: 'Pains Produits / Facturés', value: `${qty(totals.total_breads_produced)} / ${qty(totals.total_breads_billed)}` },
  ];

  const detail = open ? buildDetail(open, report) : null;

  return (
    <>
      <div className="kpi-grid" style={{ gap: '12px' }}>
        {cards.map(card => (
          <button
            key={card.key}
            type="button"
            className="glass-card"
            onClick={() => setOpen(card.key)}
            aria-haspopup="dialog"
            aria-label={`${card.label} : voir le détail`}
            title="Cliquer pour voir le détail"
            style={{
              padding: '10px 12px', textAlign: 'left', cursor: 'pointer', font: 'inherit',
              color: 'inherit', width: '100%', minHeight: '44px',
            }}
          >
            <div style={labelStyle}>{card.label}</div>
            <div style={{ fontSize: '1rem', fontWeight: 800, color: card.color }}>{card.value}</div>
          </button>
        ))}
      </div>

      <Modal
        isOpen={detail !== null}
        onClose={() => setOpen(null)}
        title={detail?.title}
        subtitle={detail?.explanation}
        maxWidth="520px"
        footer={
          <button type="button" className="btn btn-secondary" onClick={() => setOpen(null)} style={{ minHeight: '40px' }}>
            Fermer
          </button>
        }
      >
        {detail?.table && (detail.table.rows.length === 0 ? (
          <p style={{ textAlign: 'center', color: 'hsl(var(--text-muted))', padding: '12px', fontSize: '0.78rem' }}>
            Aucune donnée pour ce jour.
          </p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="premium-table" style={{ minWidth: '300px' }}>
              <thead>
                <tr style={{ fontSize: '0.62rem', textTransform: 'uppercase' }}>
                  {detail.table.headers.map((h, i) => (
                    <th key={h} style={{ textAlign: i === 0 ? 'left' : 'right' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody style={{ fontSize: '0.78rem' }}>
                {detail.table.rows.map((row, r) => (
                  <tr key={r}>
                    {row.map((cell, i) => (
                      <td key={i} style={{ textAlign: i === 0 ? 'left' : 'right', fontWeight: i === 0 ? 700 : 600 }}>{cell}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
              {detail.table.footer && (
                <tfoot style={{ fontSize: '0.78rem' }}>
                  <tr>
                    {detail.table.footer.map((cell, i) => (
                      <td key={i} style={{ textAlign: i === 0 ? 'left' : 'right', fontWeight: 800 }}>{cell}</td>
                    ))}
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        ))}
      </Modal>
    </>
  );
};
