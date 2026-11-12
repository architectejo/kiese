// BUG-153 : export Excel (.xlsx) et impression du rapport « Clôture Journalière »
// (remarque.md, après l.410 : « possibilité d'exporter (format Excel) et d'imprimer
// les différentes sections »). Utilitaire isolé (CLAUDE.md §4 — pages volumineuses)
// pour ne pas alourdir frontend/src/pages/dashboard/ClotureJournaliere.tsx.
//
// IMPORTANT : ce fichier ne recalcule rien. Il met uniquement en forme les données
// déjà calculées par le backend (DailyClosureReport) pour l'export et l'impression.
import * as XLSX from 'xlsx';
import type {
  DailyClosureReport,
  DailyClosureRepartitionRow,
} from '@/api/services';
import { formatFC, formatQty, REGULARISATION_HELP, NON_SERVI_HELP } from '@/pages/dashboard/ClotureJournaliere';

type RepartitionMode = 'QUANTITE' | 'VALEUR';

/** Transforme une chaîne Decimal (ou nombre) en nombre JS natif, null si absent/invalide. */
const toNum = (v: string | number | null | undefined): number | null => {
  if (v === null || v === undefined || v === '') return null;
  const n = typeof v === 'string' ? parseFloat(v) : v;
  return Number.isNaN(n) ? null : n;
};

const FC_FMT = '#,##0" FC"';
const QTY_FMT = '#,##0';
const PCT_FMT = '0.00"%"';

const dateLabel = (iso: string): string =>
  new Date(iso).toLocaleDateString('fr-FR', { day: '2-digit', month: 'long', year: 'numeric' });

/** Nom de fichier normalisé : cloture-journaliere-K1-2026-11-10.xlsx */
export const buildClotureFilename = (nodeCode: string, date: string, ext: string): string =>
  `cloture-journaliere-${nodeCode || 'NA'}-${date}.${ext}`;

/** Applique un format numérique de cellule (sans modifier la valeur stockée). */
function setFmt(ws: XLSX.WorkSheet, ref: string, fmt: string) {
  const cell = ws[ref];
  if (cell && cell.t === 'n') cell.z = fmt;
}

/**
 * Construit et télécharge le classeur Excel du rapport de clôture.
 * Choix retenu (documenté dans le rapport de ticket) : 3 feuilles distinctes
 * (Résumé KPI / Répartition / Décomposition) plutôt qu'une seule feuille à
 * sections empilées — plus simple à lire et à manipuler pour le client dans Excel
 * (tri, filtres, recalcul par feuille). Les montants et quantités sont des
 * nombres natifs avec un format d'affichage de cellule (pas des chaînes
 * formatées), conformément à CLAUDE.md §4.
 */
export function exportClotureToExcel(
  report: DailyClosureReport,
  nodeLabel: string,
  repartitionMode: RepartitionMode,
) {
  const wb = XLSX.utils.book_new();
  const totals = report.totals;
  const label = dateLabel(report.date);

  // --- Feuille 1 : Résumé KPI -------------------------------------------------
  const kpiRows: (string | number | null)[][] = [
    [`Clôture Journalière — ${nodeLabel}`],
    [`Date : ${label}`],
    [],
    ['Indicateur', 'Valeur'],
    ['Total du Jour (FC)', toNum(totals.total_du_jour_fc)],
    ['Net Produit (FC)', toNum(totals.net_produit_fc)],
    ['Écart / Facture (FC)', toNum(totals.ecart_facture_fc)],
    ['Nombre de Sacs Produits', toNum(totals.nombre_sacs_produits)],
    ['Moyenne Produit / Sac (FC)', toNum(totals.moyenne_produit_par_sac_fc)],
    ['Tarif Vente fixe (FC)', toNum(totals.tarif_vente_fc)],
    ['Écart / Production (FC)', toNum(totals.ecart_production_fc)],
    ['Pains Produits', totals.total_breads_produced],
    ['Pains Facturés', totals.total_breads_billed],
  ];
  const wsKpi = XLSX.utils.aoa_to_sheet(kpiRows);
  wsKpi['!cols'] = [{ wch: 32 }, { wch: 18 }];
  wsKpi['!merges'] = [{ s: { r: 0, c: 0 }, e: { r: 0, c: 1 } }, { s: { r: 1, c: 0 }, e: { r: 1, c: 1 } }];
  // Lignes de valeurs FC/quantités : index 4..10 → FC, 7/11/12 → quantités entières
  [4, 5, 6, 8, 9, 10].forEach(r => setFmt(wsKpi, `B${r + 1}`, FC_FMT));
  [7, 11, 12].forEach(r => setFmt(wsKpi, `B${r + 1}`, QTY_FMT));
  XLSX.utils.book_append_sheet(wb, wsKpi, 'Résumé KPI');

  // --- Feuille 2 : Répartition par catégorie ---------------------------------
  const repartitionRows: (string | number)[][] = [
    [`Clôture Journalière — ${nodeLabel} — ${label}`],
    [],
  ];
  const pctCellRefs: string[] = []; // lignes contenant un pourcentage, colonne B
  const appendRepartitionBlock = (title: string, rows: DailyClosureRepartitionRow[]) => {
    repartitionRows.push([title]);
    repartitionRows.push(['Catégorie', 'Part (%)']);
    rows.forEach(r => {
      repartitionRows.push([r.label, toNum(r.pct) ?? 0]);
      pctCellRefs.push(`B${repartitionRows.length}`); // 1-indexé = ligne courante
    });
    repartitionRows.push([]);
  };
  appendRepartitionBlock('Répartition par quantité', totals.repartition_pct_par_quantite);
  appendRepartitionBlock('Répartition par valeur (FC)', totals.repartition_pct_par_valeur);

  const wsRep = XLSX.utils.aoa_to_sheet(repartitionRows);
  wsRep['!cols'] = [{ wch: 26 }, { wch: 14 }];
  pctCellRefs.forEach(ref => setFmt(wsRep, ref, PCT_FMT));
  XLSX.utils.book_append_sheet(wb, wsRep, 'Répartition par catégorie');
  // Note : le mode actuellement choisi à l'écran (repartitionMode) est repris en commentaire
  // ci-dessous pour information, les deux répartitions (quantité / valeur) étant exportées
  // intégralement pour ne perdre aucune information par rapport à l'écran.
  void repartitionMode;

  // --- Feuille 3 : Décomposition par catégorie de pain ------------------------
  const header = [
    'Catégorie', 'Produit (qté)', 'Produit (FC)', 'Facture/Jr (qté)', 'Facture/Jr (FC)',
    'CM/Jr (FC)', 'Reste Jour (A)', 'Reste Jour (B)', 'Reste Hier (A)', 'Reste Hier (B)',
    'Appro Effectué (qté)', 'Appro Effectué (FC)', 'Appro Reçu (qté)', 'Appro Reçu (FC)',
    'Non Servi (qté)', 'Non Servi (FC)', 'Régularisation (qté)', 'Régularisation (FC)',
    'Vente Cash/Soldée (qté)', 'Vente Cash/Soldée (FC)', 'Perte (Soldée) (FC)',
    'Facture Mvm Interne (FC)', 'Non Vendu NV (qté)', 'Non Vendu NV (FC)',
    'Déclassés (qté)', 'Déclassés (FC)', 'Sorties Gratuites (qté)', 'Sorties Gratuites (FC)',
    'Non Servi retranché du total (FC)',
  ];
  const decompRows: (string | number | null)[][] = [
    [`Décomposition par Catégorie de Pain — ${nodeLabel} — ${label}`],
    [],
    header,
  ];
  report.categories.forEach(cat => {
    decompRows.push([
      cat.label,
      cat.produit.quantity, toNum(cat.produit.fc),
      cat.facture_jr.quantity, toNum(cat.facture_jr.fc),
      toNum(cat.commission_jr.fc),
      cat.reste_du_jour.A ?? null, cat.reste_du_jour.B ?? null,
      cat.reste_du_hier.A ?? null, cat.reste_du_hier.B ?? null,
      cat.appro_effectue.quantity, toNum(cat.appro_effectue.fc),
      cat.appro_recu.quantity, toNum(cat.appro_recu.fc),
      cat.non_servi.quantity, toNum(cat.non_servi.fc),
      cat.regularisation.quantity, toNum(cat.regularisation.fc),
      cat.vente_cash_soldee.quantity, toNum(cat.vente_cash_soldee.fc), toNum(cat.vente_cash_soldee.perte_fc),
      toNum(cat.facture_mvm_interne.fc),
      cat.non_vendu_nv.quantity, toNum(cat.non_vendu_nv.fc),
      cat.declasses.quantity, toNum(cat.declasses.fc),
      cat.sorties_gratuites.quantity, toNum(cat.sorties_gratuites.fc),
      toNum(cat.non_servi.fc_signe),
    ]);
  });
  const dataEnd = decompRows.length;
  decompRows.push([], [REGULARISATION_HELP], [NON_SERVI_HELP]);
  const wsDecomp = XLSX.utils.aoa_to_sheet(decompRows);
  wsDecomp['!cols'] = header.map((_, i) => ({ wch: i === 0 ? 16 : 14 }));
  const fcCols = [2, 4, 5, 11, 13, 15, 17, 19, 20, 21, 23, 25, 27, 28]; // colonnes « (FC) », 0-indexées
  const qtyCols = [1, 3, 6, 7, 8, 9, 10, 12, 14, 16, 18, 22, 24, 26];
  for (let r = 3; r < dataEnd; r++) {
    fcCols.forEach(c => setFmt(wsDecomp, `${XLSX.utils.encode_col(c)}${r + 1}`, FC_FMT));
    qtyCols.forEach(c => setFmt(wsDecomp, `${XLSX.utils.encode_col(c)}${r + 1}`, QTY_FMT));
  }
  XLSX.utils.book_append_sheet(wb, wsDecomp, 'Décomposition par catégorie');

  XLSX.writeFile(wb, buildClotureFilename(report.node, report.date, 'xlsx'));
}

/**
 * Ouvre une fenêtre d'impression reprenant les trois zones de l'écran (bandeau
 * KPI, répartition par catégorie, décomposition par catégorie de pain), sans
 * aucun bouton/navigation dans la sortie imprimée. Reprend le motif déjà en
 * place dans Treasury.tsx (window.open + <script>window.onload=()=>print()</script>).
 */
export function printClotureReport(
  report: DailyClosureReport,
  nodeLabel: string,
  repartitionRows: DailyClosureRepartitionRow[],
  repartitionModeLabel: string,
) {
  const totals = report.totals;
  const label = dateLabel(report.date);

  const kpiHtml = `
    <table class="kpi">
      <tr><td>Total du Jour</td><td>${formatFC(totals.total_du_jour_fc)}</td>
          <td>Net Produit</td><td>${formatFC(totals.net_produit_fc)}</td></tr>
      <tr><td>Écart / Facture</td><td>${formatFC(totals.ecart_facture_fc)}</td>
          <td>Nombre de Sacs Produits</td><td>${totals.nombre_sacs_produits}</td></tr>
      <tr><td>Moyenne Produit / Sac</td><td>${formatFC(totals.moyenne_produit_par_sac_fc)}</td>
          <td>Tarif Vente (fixe)</td><td>${formatFC(totals.tarif_vente_fc)}</td></tr>
      <tr><td>Écart / Production</td><td>${formatFC(totals.ecart_production_fc)}</td>
          <td>Pains Produits / Facturés</td><td>${formatQty(totals.total_breads_produced)} / ${formatQty(totals.total_breads_billed)}</td></tr>
    </table>`;

  const repRows = repartitionRows.map(r => `<tr><td>${r.label}</td><td style="text-align:right">${r.pct} %</td></tr>`).join('');

  const decompHeader = [
    'Catégorie', 'Produit', 'Facture/Jr', 'CM/Jr', 'Reste Jr(A)', 'Reste Jr(B)',
    'Reste Hr(A)', 'Reste Hr(B)', 'Appro Eff.', 'Appro Reçu', 'Non Servi', 'Régul.',
    'Vente Cash/Soldée', 'Perte (Soldée)', 'Fact. Mvm Int.', 'Non Vendu', 'Déclassés', 'Sorties Grat.',
  ].map(h => `<th>${h}</th>`).join('');

  const decompRows = report.categories.map(cat => `
    <tr>
      <td>${cat.label}</td>
      <td style="text-align:right">${formatQty(cat.produit.quantity)}<br/><small>${formatFC(cat.produit.fc)}</small></td>
      <td style="text-align:right">${formatQty(cat.facture_jr.quantity)}<br/><small>${formatFC(cat.facture_jr.fc)}</small></td>
      <td style="text-align:right">${formatFC(cat.commission_jr.fc)}</td>
      <td style="text-align:right">${formatQty(cat.reste_du_jour.A)}</td>
      <td style="text-align:right">${formatQty(cat.reste_du_jour.B)}</td>
      <td style="text-align:right">${formatQty(cat.reste_du_hier.A)}</td>
      <td style="text-align:right">${formatQty(cat.reste_du_hier.B)}</td>
      <td style="text-align:right">${formatQty(cat.appro_effectue.quantity)}<br/><small>${formatFC(cat.appro_effectue.fc)}</small></td>
      <td style="text-align:right">${formatQty(cat.appro_recu.quantity)}<br/><small>${formatFC(cat.appro_recu.fc)}</small></td>
      <td style="text-align:right">${formatFC(cat.non_servi.fc)}<br/><small>${formatQty(cat.non_servi.quantity)} pain(s)<br/>retranché : ${formatFC(cat.non_servi.fc_signe)}</small></td>
      <td style="text-align:right">${formatQty(cat.regularisation.quantity)}<br/><small>${formatFC(cat.regularisation.fc)}</small></td>
      <td style="text-align:right">${formatQty(cat.vente_cash_soldee.quantity)}<br/><small>${formatFC(cat.vente_cash_soldee.fc)}</small></td>
      <td style="text-align:right">${formatFC(cat.vente_cash_soldee.perte_fc)}</td>
      <td style="text-align:right">${formatFC(cat.facture_mvm_interne.fc)}</td>
      <td style="text-align:right">${formatQty(cat.non_vendu_nv.quantity)}<br/><small>${formatFC(cat.non_vendu_nv.fc)}</small></td>
      <td style="text-align:right">${formatQty(cat.declasses.quantity)}<br/><small>${formatFC(cat.declasses.fc)}</small></td>
      <td style="text-align:right">${formatQty(cat.sorties_gratuites.quantity)}<br/><small>${formatFC(cat.sorties_gratuites.fc)}</small></td>
    </tr>`).join('');

  const html = `
    <html><head><title>Clôture Journalière — ${nodeLabel} — ${label}</title>
    <style>
      body { font-family: Arial, sans-serif; padding: 20px; color: #111; }
      h1 { font-size: 18px; border-bottom: 2px solid #000; padding-bottom: 8px; margin-bottom: 2px; }
      h2 { font-size: 14px; margin: 18px 0 6px; }
      p.meta { font-size: 12px; color: #444; margin: 2px 0 10px; }
      table { width: 100%; border-collapse: collapse; margin-top: 6px; font-size: 11px; }
      table.kpi td { border: 1px solid #999; padding: 6px 8px; }
      table.kpi td:nth-child(odd) { font-weight: 700; background: #f3f4f6; width: 22%; }
      table.decomp th, table.decomp td { border: 1px solid #999; padding: 4px 5px; font-size: 9.5px; }
      table.decomp th { background: #eee; }
      table.repartition th, table.repartition td { border: 1px solid #999; padding: 5px 8px; }
      table.repartition th { background: #eee; text-align: left; }
      table, tr, td, th { page-break-inside: avoid; }
      @media print { @page { size: landscape; margin: 10mm; } }
    </style></head>
    <body>
      <h1>CLÔTURE JOURNALIÈRE — ETS. KIESE</h1>
      <p class="meta">Boulangerie : ${nodeLabel} — Date : ${label}</p>

      <h2>Indicateurs du jour</h2>
      ${kpiHtml}

      <h2>Répartition par Catégorie (${repartitionModeLabel})</h2>
      <table class="repartition">
        <thead><tr><th>Catégorie</th><th style="text-align:right">Part (%)</th></tr></thead>
        <tbody>${repRows || '<tr><td colspan="2" style="text-align:center">Aucune donnée.</td></tr>'}</tbody>
      </table>

      <h2>Décomposition par Catégorie de Pain</h2>
      <table class="decomp">
        <thead><tr>${decompHeader}</tr></thead>
        <tbody>${decompRows || `<tr><td colspan="18" style="text-align:center">Aucune donnée.</td></tr>`}</tbody>
      </table>

      <p style="font-size:10px;margin-top:8px">${REGULARISATION_HELP}<br/>${NON_SERVI_HELP}</p>

      <script>window.onload = () => { window.print(); window.onafterprint = () => window.close(); };</script>
    </body></html>`;

  const w = window.open('', '_blank', 'width=1100,height=800');
  if (w) { w.document.write(html); w.document.close(); }
}
