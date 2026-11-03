import { apiClient } from './client';

// Unwrap DRF paginated ({count, next, results}) or plain array responses,
// following "next" until exhausted so callers always get the FULL matching
// list (DRF's default PAGE_SIZE is 25 — without this, any list past page 1
// was silently dropped, e.g. "Gestion Clientèle" showing only 25/600+ clients).
// Returns an Axios-like {data: T[]} so callers can use res.data unchanged.
async function getList<T>(url: string, params?: Record<string, string>): Promise<{ data: T[] }> {
  const res = await apiClient.get<T[] | { count: number; next: string | null; results: T[] }>(url, { params });
  const raw = res.data;
  if (Array.isArray(raw)) return { data: raw };
  let results = raw.results ?? [];
  let next = raw.next;
  while (next) {
    const nextRes = await apiClient.get<{ count: number; next: string | null; results: T[] }>(next);
    results = results.concat(nextRes.data.results ?? []);
    next = nextRes.data.next;
  }
  return { data: results };
}

// ── Types ────────────────────────────────────────────────────────────────────

export interface BakeryNode {
  id: string;
  code: string;
  name: string;
  address: string;
  sac_value_fc: string | null;
  is_active: boolean;
  last_sync: string | null;
  created_at: string;
}

export interface BreadPrice {
  id: number;          // integer PK — not UUID
  category: 'MINI' | 'MOYEN' | 'GRAND' | 'PREMIUM';
  label: string;
  unit_price: number;
  is_active: boolean;
}

export interface Client {
  id: string;
  code: string;
  first_name: string;
  last_name: string;
  full_name: string;
  phone: string;
  address: string;
  node: string;
  node_display: string;
  cotisation_sociale: string;
  commission_rate: string;
  credit_limit: string;
  current_debt: string;
  total_breads_received: number;
  category: 'NORMAL' | 'BEST' | 'RISK';
  client_type: 'DETAILLANT' | 'GROSSISTE' | 'REVENDEUR';
  is_active: boolean;
  notes: string;
  photo?: string | null;
  created_at: string;
}

export interface ClientImportReportRow {
  node: string;
  node_name: string;
  total_in_file: number;
  to_import: number;
  already_existing: number;
}

export interface ClientImportResult {
  dry_run: boolean;
  created: number;
  report: ClientImportReportRow[];
  skipped_sheets: string[];
  unknown_nodes: string[];
}

export interface InvoiceLine {
  id?: string;
  bread_price: string;
  bread_price_display?: string;
  quantity: number;
  unit_price?: string;
  line_total?: string;
  /**
   * BUG-092/BUG-096 : perte = (prix catalogue − unit_price facturé) × quantity, calculée côté
   * serveur (`InvoiceLine.loss`, property). Toujours « 0 » hors vente soldée (`Invoice.is_soldee`).
   */
  loss?: string;
}

// Ligne agrégée renvoyée par `/api/sales/invoices/daily_summary/` (groupée par
// boulangerie `node__code` et `payment_type`, CLAUDE.md §5.5 niveau 1).
export interface DailySummaryRow {
  node__code?: string;
  payment_type: 'CASH' | 'CREDIT';
  total: string | number;
}

export interface Invoice {
  id: string;
  receipt_number: string;
  client: string;
  client_display?: string;
  facturier: string;
  facturier_display?: string;
  livreur?: string;
  livreur_display?: string;
  team?: string;
  node: string;
  node_display?: string;
  client_code?: string;
  client_photo?: string | null;
  client_current_debt?: string;
  invoice_date: string;
  delivered_at?: string | null;
  status: 'PENDING' | 'DELIVERED' | 'CANCELLED';
  payment_type: 'CASH' | 'CREDIT';
  debt_before: string;
  order_total: string;
  payment_amount: string;
  debt_after: string;
  commission_rate: string;
  is_soldee?: boolean;
  /**
   * BUG-052 : exonération de commission (CM=0) sur une facture normale, INDÉPENDANTE de
   * `is_soldee` — ne change ni le prix (toujours catalogue plein) ni le traitement de la BP
   * (suit `order_total` normalement, jamais gelée). Combinable avec `is_soldee` sans
   * incohérence : les deux chemins mènent alors à CM=0, prix à 75 % et BP gelée restant
   * portés uniquement par `is_soldee`.
   */
  commission_exempt?: boolean;
  /**
   * BUG-092/BUG-096 : somme de `InvoiceLine.loss` sur la facture (property serveur, jamais
   * stockée). Nul sur une vente non soldée. Prix catalogue appliqué à 75 % quand `is_soldee`.
   */
  total_loss?: string;
  is_debt_repayment?: boolean;
  special_code?: '' | 'NV' | 'RG' | 'NS';
  lines: InvoiceLine[];
  created_at: string;
  // BUG-097/BUG-109 : trace d'ajustement (correction/annulation d'une commande déjà
  // enregistrée via une nouvelle facture liée, jamais de mutation de l'originale).
  // `adjusts` : id de la facture d'origine, uniquement si `is_adjustment=true`.
  // `adjustments_count` : nombre d'ajustements déjà appliqués, uniquement sur une
  // facture d'origine (jamais sur un ajustement lui-même).
  adjusts?: string | null;
  is_adjustment?: boolean;
  adjustment_sign?: 1 | -1 | null;
  adjustments_count?: number;
}

// BUG-109 : payload de POST /api/sales/invoices/{id}/adjust/ (réservé GERANT+,
// voir backend/sales/serializers.py::InvoiceAdjustSerializer).
export interface InvoiceAdjustPayload {
  adjustment_sign: 1 | -1;
  payment_amount: string;
  lines: Array<{ bread_price: number; quantity: number }>;
  invoice_date?: string;
}

// BUG-107/BUG-052 (dev-frontend, 2026-10-30) : payload de POST /api/sales/invoices/ —
// `client` doit pouvoir être `null` (vente occasionnelle) sans recourir à `Partial<Invoice>`
// (où `client` est une chaîne non nullable dans la réponse serveur), ce qui évitait un
// cast `as any` dans les deux appelants (`Sales.tsx`, `Clients.tsx`).
export interface InvoiceCreatePayload {
  client?: string | null;
  payment_type: 'CASH' | 'CREDIT';
  payment_amount: string;
  commission_rate?: string | number;
  is_soldee?: boolean;
  commission_exempt?: boolean;
  special_code?: '' | 'NV' | 'RG' | 'NS';
  invoice_date?: string;
  lines: Array<{ bread_price: number; quantity: number }>;
}

export interface ProductionSessionLine {
  bread_price: number;
  bread_price_display?: string;
  unit_price?: number;
  quantity: number;
  line_fc?: number;
}

export interface ProductionSession {
  id: string;
  node: string;
  node_display?: string;
  team: string;
  date: string;
  flour_sacks_used: string;
  lines: ProductionSessionLine[];
  consumables_used?: Array<{ consumable_type: string; quantity: number }>;
  // legacy per-price fields (synced from lines, kept for backward compat)
  breads_300: number;
  breads_400: number;
  breads_500: number;
  breads_1000: number;
  total_breads: number;
  total_fc_produced: number;
  theoretical_yield: number;  // now in FC
  yield_gap: number;           // now in FC
  created_at: string;
  notes?: string;
  // BUG-093/BUG-108 : clôture automatisée de la fournée (recoupement ventes/dispositions).
  is_closed?: boolean;
  closed_at?: string | null;
  closure_summary?: ProductionClosureSummary | null;
}

// BUG-051 : réponse de GET /api/production/sessions/reconciliation/
// (production déclarée vs ventes livrées + retours, en pains et en FC).
export interface ProductionReconciliationAmount {
  breads: number;
  fc: string; // Decimal sérialisé en chaîne côté backend
}

export interface ProductionReconciliation {
  node: string | null;
  date: string | null;
  date_from: string | null;
  date_to: string | null;
  production_declared: ProductionReconciliationAmount;
  sales: ProductionReconciliationAmount;
  returns: ProductionReconciliationAmount;
  gap: ProductionReconciliationAmount;
}

// BUG-093/BUG-108 : détail figé (`closure_summary`) renvoyé par
// POST /api/production/sessions/{id}/close/ — même clés que
// ProductionReconciliation, plus le reliquat NV et le marqueur d'anomalie
// (ventes/dispositions dépassant la production déclarée, non bloquant).
export interface ProductionClosureSummary extends ProductionReconciliation {
  nv: { breads: number };
  anomaly: boolean;
}

// BUG-120 : rapport de clôture journalier consolidé, par catégorie de pain
// (CLAUDE.md §5.4) — GET /api/production/daily-closure/?node=<code>&date=<AAAA-MM-JJ>.
// Contrat exact : docs/qa/rapports/dev-backend-2026-11-02-bug120-corrections-client.md
export interface DailyClosureQuantityFc {
  quantity: number;
  fc: string; // Decimal sérialisé en chaîne côté backend
}

export interface DailyClosureFcOnly {
  fc: string;
}

export interface DailyClosureCategory {
  bread_price: number;
  label: string;
  unit_price: number;
  produit: DailyClosureQuantityFc;
  facture_jr: DailyClosureQuantityFc;
  commission_jr: DailyClosureFcOnly;
  // Clé = équipe ('A' | 'B'), valeur = quantité (peut être négative ou nulle, CLAUDE.md §5.2).
  reste_du_jour: Record<string, number | null>;
  reste_du_hier: Record<string, number | null>;
  appro_effectue: DailyClosureQuantityFc;
  appro_recu: DailyClosureQuantityFc;
  non_servi: DailyClosureQuantityFc;
  regularisation: DailyClosureQuantityFc;
  vente_cash_soldee: DailyClosureQuantityFc & { perte_fc: string };
  facture_mvm_interne: DailyClosureFcOnly;
  non_vendu_nv: DailyClosureQuantityFc;
  declasses: DailyClosureQuantityFc;
  sorties_gratuites: DailyClosureQuantityFc;
}

export interface DailyClosureRepartitionRow {
  bread_price: number;
  label: string;
  pct: string;
}

export interface DailyClosureTotals {
  total_du_jour_fc: string;
  net_produit_fc: string;
  ecart_facture_fc: string;
  nombre_sacs_produits: string;
  moyenne_produit_par_sac_fc: string | null;
  tarif_vente_fc: string;
  ecart_production_fc: string;
  total_breads_produced: number;
  total_breads_billed: number;
  repartition_pct_par_quantite: DailyClosureRepartitionRow[];
  repartition_pct_par_valeur: DailyClosureRepartitionRow[];
}

export interface DailyClosureReport {
  node: string;
  date: string;
  categories: DailyClosureCategory[];
  totals: DailyClosureTotals;
}

export interface BreadStock {
  id: number;
  node: string;
  node_display?: string;
  bread_price: number;
  bread_price_display?: string;
  unit_price: number;
  qty_produced: number;
  qty_received: number;
  qty_sent: number;
  qty_disposed: number;
  qty_available: number;
}

export interface ConsumableType {
  id: number;
  code: string;
  label: string;
  unit: string;
  is_active: boolean;
}

export interface ConsumableStock {
  id: string;
  node: string;
  node_display?: string;
  consumable_type: string;
  consumable_type_display?: string;
  quantity: string;
  unit: string;
  /** BUG-125 : Coût Unitaire Moyen Pondéré, recalculé à chaque entrée de stock. */
  average_unit_cost?: string;
}

export interface BreadTransferLine {
  id: number;
  bread_price: number;
  bread_price_display?: string;
  unit_price?: number;
  quantity_sent: number;
  quantity_received?: number;
  quantity_gap?: number;
}

export interface BreadTransfer {
  id: string;
  from_node: string;
  from_node_display?: string;
  to_node: string;
  to_node_display?: string;
  lines: BreadTransferLine[];
  total_sent?: number;
  quantity_received?: number;
  transfer_status: 'PENDING' | 'RESPONDED' | 'CONFIRMED' | 'DISPUTED' | 'CANCELLED';
  transfer_date: string;
  quantity_gap?: number;
  notes?: string;
  created_at: string;
}

export interface ConsumableMovement {
  id: string;
  node: string;
  stock: string;
  session?: string;
  movement_type: 'ENTRY' | 'EXIT';
  quantity: string;
  unit_price?: string;
  supplier?: string;
  description: string;
  created_at: string;
}

export interface ConsumableCount {
  id: number;
  node: string;
  node_display?: string;
  consumable_type: string;
  consumable_type_display?: string;
  count_date: string;
  system_quantity: string;
  physical_quantity: string;
  gap: string;
  counted_by?: number;
  counted_by_display?: string;
  notes: string;
  created_at: string;
}

export interface FlourHistoryEntry {
  id: number;
  date: string;
  node: string;
  supplier: string;
  quantity: string;
  unit_price: string;
  total_cost: string;
  description: string;
}

export interface BreadDisposal {
  id: string;
  node: string;
  session?: string;
  bread_price: number;
  bread_price_display?: string;
  disposal_type: 'SOLD_DISCOUNT' | 'DECLASSED' | 'UNSOLD' | 'FREE_DIST' | 'REMAINING';
  quantity: number;
  unit_price_sold: string;
  total_value: string;
  notes: string;
  created_at: string;
}

export interface CommissionPeriod {
  id: string;
  node: string;
  node_display?: string;
  month: number;
  year: number;
  is_closed: boolean;
  created_at: string;
}

export interface ClientCommission {
  id: string;
  period: string;
  period_display?: string;
  node?: string;
  node_display?: string;
  client: string;
  client_display?: string;
  total_breads: number;
  order_value: string;
  commission_rate: string;
  commission_gross: string;
  deduction_debt: string;
  deduction_social: string;
  deduction_prints: string;
  deduction_other: string;
  deduction_carte: string;
  deduction_remise: string;
  /** BUG-124 : report automatique du net à payer négatif de la période précédente (jamais remis à zéro), lecture seule. */
  carried_debt_in: string;
  total_deductions: string;
  net_ordi: string;
  net_carte: string;
  annual_bonus: string;
  annual_bonus_incorporated: boolean;
  net_payable: string;
  manuel_adjustment?: string | null;
  manuel_notes?: string;
  is_paid: boolean;
  paid_at?: string;
  paid_by?: string;
  notes?: string;
}

export interface CashbookEntry {
  id: string;
  node: string;
  node_display?: string;
  date: string;
  piece_number: string;
  imputation: string;
  label: string;
  entry_amount: string;
  exit_amount: string;
  running_balance: string;
  is_tampered: boolean;
  block_hash: string;
  // BUG-083 : traçabilité des écritures de correction (« ventes passées »
  // sur une clôture déjà validée) — toujours visibles, jamais une
  // modification d'une écriture existante.
  is_correction: boolean;
  correction_reason?: string;
  corrected_by?: string | null;
  corrected_by_display?: string | null;
  correction_source_invoice?: string | null;
}

export interface DisbursementVoucher {
  id: string;
  date: string;
  created_by?: string;
  created_by_display?: string;
  motif: string;
  beneficiary?: string;
  bills_20000: number;
  bills_10000: number;
  bills_5000: number;
  bills_1000: number;
  bills_500: number;
  bills_200: number;
  bills_100: number;
  bills_50: number;
  physical_cash_total: string;
  piece_number: string;
  created_at: string;
}

// BUG-119 — Comptage physique Livre de Caisse Direction (Niveau 3, CLAUDE.md §5.5).
// Contrôle annexe, séparé du chaînage SHA-256 des CashbookEntry (voir
// backend/treasury/models.py::DirectionCashCount).
export interface DirectionCashCount {
  id: string;
  date: string;
  counted_by?: string | null;
  counted_by_display?: string | null;
  bills_20000: number;
  bills_10000: number;
  bills_5000: number;
  bills_1000: number;
  bills_500: number;
  bills_200: number;
  bills_100: number;
  bills_50: number;
  physical_cash_total: string;
  reference_entry?: string | null;
  theoretical_balance: string;
  cash_gap: string;
  notes: string;
  created_at: string;
}

export interface JournalEntry {
  id: number;
  node: string;
  node_display?: string;
  recorded_by?: number;
  recorded_by_display?: string;
  date: string;
  imput: string;
  imput_display?: string;
  label: string;
  entry_amount: string;
  exit_amount: string;
  running_balance: string;
  month_carried: string;
  created_at: string;
  // BUG-091/BUG-105 — rapprochement de l'imputation CA avec la Clôture (Niveau 2)
  is_reconciled?: boolean;
  reconciliation_gap?: string;
  reconciled_closure?: string | null;
}

export interface SuggestedCa {
  available: boolean;
  amount: string | null;
  closure_id: string | null;
  message: string | null;
}

export interface CashClosure {
  id: string;
  node: string;
  node_display?: string;
  gerant?: string | null;
  gerant_display?: string | null;
  date: string;
  total_entries: string;
  total_expenses: string;
  net_cash: string;
  // §5.2 — Bill denomination counts (computed to physical_cash_total)
  bills_20000: number;
  bills_10000: number;
  bills_5000: number;
  bills_1000: number;
  bills_500: number;
  bills_200: number;
  bills_100: number;
  bills_50: number;
  physical_cash_total: string;
  cash_gap: string;
  is_validated: boolean;
  is_rejected: boolean;
  rejection_reason: string;
  notes: string;
  created_at: string;
  has_cashbook_entry: boolean;
}

export interface FacturierReport {
  id: string;
  node: string;
  node_display?: string;
  node_origin?: string;
  team: string;
  date: string;
  total_cash_sales: string;
  total_credit_sales: string;
  theoretical_cash: string;
  is_validated: boolean;
  validated_at?: string;
  created_at: string;
  // BUG-033/BUG-045 — détail par catégorie de pain et écart valeur sacs/ventes, ajoutés par la vacation.
  sacks_consumed?: string;
  breads_produced_by_category?: Record<string, number>;
  breads_sold_by_category?: Record<string, number>;
  sacks_value_gap?: string;
}

export interface LocalExpense {
  id: string;
  node: string;
  node_display?: string;
  description: string;
  category: number;
  category_display?: string;
  amount: string;
  date: string;
}

export interface ExpenseCategory {
  id: number;
  code: string;
  label: string;
  is_active: boolean;
  updated_at?: string;
}

export interface FinancialYear {
  id: string;
  year: number;
  is_current: boolean;
  is_closed: boolean;
  notes: string;
}

export interface FinanceSummaryRow {
  node: string;
  node_code: string;
  node_name: string;
  month: number;
  year: number;
  period_id: string;
  is_closed: boolean;
  client_count: number;
  total_orders: string;
  total_cm: string;
  total_net: string;
  total_debt: string;
}

export interface Doc1Row {
  client_code: string;
  client_name: string;
  qty_200: number;
  qty_300: number;
  qty_500: number;
  qty_1000: number;
  invoice_total: string;
  payment_amount: string;
  debt_after: string;
  commission_rate: string;
  cm_amount: string;
}

export interface BassinRow {
  client_code: string;
  client_name: string;
  order_value: string;
  bp: string;
  cm: string;
  net_payable: string;
  category: string;
  rank: number;
}

export interface ColisDistribution {
  id: number;
  node: string;
  node_display?: string;
  year: number;
  beneficiary_label: string;
  rice_sacks: string;
  rice_value: string;
  meat_kg: string;
  meat_value: string;
  cash_amount: string;
  total_value: string;
  notes: string;
  created_at: string;
}

export interface CmHistoryRow {
  id: string;
  node: string;
  node_code: string;
  node_name: string;
  month: number;
  year: number;
  is_closed: boolean;
  client_count: number;
  total_orders: string;
  total_cm: string;
  total_net: string;
  total_paid: string;
  total_payments: string;
}

export interface IncomeStatement {
  year: number;
  revenue_300: string;
  revenue_400: string;
  revenue_500: string;
  revenue_1000: string;
  total_revenue: string;
  cost_flour: string;
  cost_yeast: string;
  cost_salt: string;
  cost_oil: string;
  gross_profit: string;
  commissions_paid: string;
  operational_expenses: string;
  net_result: string;
  previous_year?: IncomeStatement;
  revenue_growth_pct?: number | null;
}

export interface Cashflow {
  year: number;
  total_entries: string;
  total_exits: string;
  net_cashflow: string;
  closing_balance: string;
  previous_year?: Cashflow;
}

export interface BalanceSheet {
  year: number;
  receivables: string;
  cash_position: string;
  total_assets: string;
  previous_year?: BalanceSheet;
}

export interface TamperAlert {
  id: string;
  node: string;
  node_name: string;
  detected_at: string;
  affected_model: string;
  severity: 'HIGH' | 'MEDIUM' | 'LOW';
  description: string;
  is_resolved: boolean;
}

export interface BlockchainSnapshot {
  id: string;
  node: string;
  node_name: string;
  snapshot_date: string;
  total_entries: number;
  tampered_entries: number;
  is_intact: boolean;
}

// ── Types ─────────────────────────────────────────────────────────────────────

export interface DailySavings {
  id: number;
  node: string;
  node_display?: string;
  recorded_by?: number;
  date: string;
  flour_sacks: string;
  daily_revenue: string;
  savings_rate: string;
  savings_amount: string;
  created_at: string;
}

export interface SocialContribution {
  id: number;
  client: string;
  client_display?: string;
  node: string;
  month: number;
  year: number;
  amount: string;
  is_paid: boolean;
  paid_at?: string | null;
}

export interface SocialDistributionLine {
  id: number;
  client: string;
  client_display?: string;
  indice: number;
  total_social: string;
  remise: string;
  merite: string;
  total_payer: string;
  position: 'present' | 'absent';
  form: 'especes' | 'colis';
}

export interface SocialDistribution {
  id: number;
  node: string;
  node_display?: string;
  year: number;
  tarif: string;
  is_closed: boolean;
  lines: SocialDistributionLine[];
  created_at: string;
}

export interface SiteConfig {
  on_line: boolean;
  default_commission_rate: string;
  debt_ceiling: string;
  best_client_threshold: number;
  social_deduction_rate: string;
  print_fee: string;
  annual_bonus_rate: string;
  sac_value_fc: number;
  savings_rate: string;
  bassin_grand: string;
  bassin_inter_gm: string;
  bassin_inter_mpt: string;
  bassin_moyen: string;
  allow_backdated_sales: boolean;
  updated_at: string;
}

// ── Core API ─────────────────────────────────────────────────────────────────

export const coreApi = {
  config: {
    get: () => apiClient.get<SiteConfig>('/api/core/config/'),
    update: (data: Partial<SiteConfig>) => apiClient.patch<SiteConfig>('/api/core/config/', data),
  },
  me: {
    get: () => apiClient.get('/api/core/auth/me/'),
    update: (data: Record<string, string>) => apiClient.patch('/api/core/auth/me/', data),
  },
  breadPrices: {
    list: () => getList<BreadPrice>('/api/core/bread-prices/'),
    create: (data: Partial<BreadPrice>) => apiClient.post<BreadPrice>('/api/core/bread-prices/', data),
    update: (id: number, data: Partial<BreadPrice>) => apiClient.patch<BreadPrice>(`/api/core/bread-prices/${id}/`, data),
    delete: (id: number) => apiClient.delete(`/api/core/bread-prices/${id}/`),
  },
  expenseCategories: {
    list: () => getList<ExpenseCategory>('/api/core/expense-categories/'),
    create: (data: Partial<ExpenseCategory>) => apiClient.post<ExpenseCategory>('/api/core/expense-categories/', data),
    update: (id: number, data: Partial<ExpenseCategory>) => apiClient.patch<ExpenseCategory>(`/api/core/expense-categories/${id}/`, data),
    delete: (id: number) => apiClient.delete(`/api/core/expense-categories/${id}/`),
  },
  nodes: {
    list: () => getList<BakeryNode>('/api/core/nodes/'),
  },
  colis: {
    list: (params?: Record<string, string>) =>
      getList<ColisDistribution>('/api/core/colis/', params),
    create: (data: Partial<ColisDistribution> & { node?: string }) =>
      apiClient.post<ColisDistribution>('/api/core/colis/', data),
    update: (id: number, data: Partial<ColisDistribution>) =>
      apiClient.patch<ColisDistribution>(`/api/core/colis/${id}/`, data),
    delete: (id: number) =>
      apiClient.delete(`/api/core/colis/${id}/`),
  },
};

// ── Client API ───────────────────────────────────────────────────────────────

export const clientsApi = {
  list: (params?: Record<string, string>) =>
    getList<Client>('/api/clients/clients/', params),
  // `data` peut être un `FormData` (photo jointe : upload multipart) ou un objet JSON classique.
  // Avec FormData, on retire l'en-tête `Content-Type: application/json` par défaut pour laisser
  // le navigateur générer `multipart/form-data; boundary=...`.
  create: (data: Partial<Client> | FormData) =>
    apiClient.post<Client>('/api/clients/clients/', data,
      data instanceof FormData ? { headers: { 'Content-Type': undefined } } : undefined),
  update: (id: string, data: Partial<Client>) =>
    apiClient.patch<Client>(`/api/clients/clients/${id}/`, data),
  riskAlerts: () =>
    getList<Client>('/api/clients/clients/risk_alerts/'),
  bestClients: () =>
    getList<Client>('/api/clients/clients/best_clients/'),
  activeLastMonth: () =>
    apiClient.get<{ count: number }>('/api/clients/clients/active_last_month/'),
  recalculateCategory: (id: string) =>
    apiClient.post(`/api/clients/clients/${id}/recalculate_category/`),
  bassins: (params: { node: string; month: string; year: string }) =>
    apiClient.get<{ categories: string[]; thresholds: Record<string, number>; rows: BassinRow[] }>(
      '/api/clients/clients/bassins/', { params }
    ),
  deficitReport: (params?: { node?: string }) =>
    getList<{
      client_code: string;
      client_name: string;
      order_value: string;
      commission_gross: string;
      current_debt: string;
      deficit: string;
      period: string;
    }>('/api/clients/clients/deficit_report/', params as Record<string, string>),
  contributions: {
    list: (params?: Record<string, string>) =>
      getList<SocialContribution>('/api/clients/contributions/', params),
    create: (data: Partial<SocialContribution> & { node?: string }) =>
      apiClient.post<SocialContribution>('/api/clients/contributions/', data),
    togglePaid: (id: number) =>
      apiClient.post<SocialContribution>(`/api/clients/contributions/${id}/toggle_paid/`),
    bulkCreateMonth: (data: { node: string; month: number; year: number; amount?: string }) =>
      apiClient.post<{ created: number; skipped: number }>('/api/clients/contributions/bulk_create_month/', data),
  },
  distributions: {
    list: (params?: Record<string, string>) =>
      getList<SocialDistribution>('/api/clients/distributions/', params),
    create: (data: Partial<SocialDistribution> & { node?: string }) =>
      apiClient.post<SocialDistribution>('/api/clients/distributions/', data),
    autoPopulate: (id: number) =>
      apiClient.post<{ created: number; skipped: number; distribution: SocialDistribution }>(
        `/api/clients/distributions/${id}/auto_populate_lines/`
      ),
  },
  distributionLines: {
    list: (params?: Record<string, string>) =>
      getList<SocialDistributionLine>('/api/clients/distribution-lines/', params),
    update: (id: number, data: Partial<SocialDistributionLine>) =>
      apiClient.patch<SocialDistributionLine>(`/api/clients/distribution-lines/${id}/`, data),
  },
  bulkMove: (ids: string[], node: string) =>
    apiClient.post<{ moved: number; requested: number }>('/api/clients/clients/bulk_move/', { ids, node }),
  bulkDelete: (ids: string[]) =>
    apiClient.post<{ deleted: number; blocked: string[]; requested: number }>('/api/clients/clients/bulk_delete/', { ids }),
  importExcel: (file: File, dryRun: boolean) => {
    const form = new FormData();
    form.append('file', file);
    form.append('dry_run', dryRun ? 'true' : 'false');
    return apiClient.post<ClientImportResult>('/api/clients/clients/import_excel/', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
};

// ── Sales API ────────────────────────────────────────────────────────────────

export const salesApi = {
  list: (params?: Record<string, string>) =>
    getList<Invoice>('/api/sales/invoices/', params),
  create: (data: InvoiceCreatePayload) =>
    apiClient.post<Invoice>('/api/sales/invoices/', data),
  // BUG-090 : `invoiceDate` optionnel (`AAAA-MM-JJ`) — même règle que BUG-083 sur les
  // commandes normales (réservé aux cas où `Config.allow_backdated_sales=True`,
  // validation réelle côté serveur). Couvre à la fois un remboursement de dette et un
  // dépôt « client épargne » (le serveur autorise un BP négatif, CLAUDE.md §5.1).
  createRepayment: (clientId: string, paymentAmount: number, invoiceDate?: string) =>
    apiClient.post<Invoice>('/api/sales/invoices/', {
      client: clientId,
      payment_type: 'CASH',
      payment_amount: paymentAmount.toString(),
      is_debt_repayment: true,
      lines: [],
      ...(invoiceDate ? { invoice_date: invoiceDate } : {}),
    }),
  // BUG-083 : `deliveredAt` optionnel (`AAAA-MM-JJ`) — livraison datée rétroactivement, réservé aux
  // cas où `Config.allow_backdated_sales=True` (validation réelle côté serveur).
  deliver: (id: string, deliveredAt?: string) =>
    apiClient.post(`/api/sales/invoices/${id}/deliver/`, deliveredAt ? { delivered_at: deliveredAt } : undefined),
  cancel: (id: string) =>
    apiClient.post(`/api/sales/invoices/${id}/cancel/`),
  // BUG-109 : correction/annulation d'une commande déjà enregistrée via une nouvelle
  // facture d'ajustement liée (jamais de mutation de l'originale) — réservé GERANT+
  // (403 pour FACTURIER/LIVREUR, contrôlé côté serveur).
  adjust: (id: string, data: InvoiceAdjustPayload) =>
    apiClient.post<Invoice>(`/api/sales/invoices/${id}/adjust/`, data),
  pendingDeliveries: () =>
    getList<Invoice>('/api/sales/invoices/pending_deliveries/'),
  cleanupExpired: () =>
    apiClient.post('/api/sales/invoices/cleanup_expired/'),
  dailySummary: () =>
    apiClient.get<DailySummaryRow[]>('/api/sales/invoices/daily_summary/'),
  breadSummary: (params?: Record<string, string>) =>
    apiClient.get<{
      by_category: Array<{ unit_price: number; total_qty: number; total_fc: number }>;
      grand_total_qty: number;
      grand_total_fc: number;
    }>('/api/sales/invoices/bread_summary/', { params }),
};

// ── Production API ───────────────────────────────────────────────────────────

export const productionApi = {
  sessions: {
    list: (params?: Record<string, string>) =>
      getList<ProductionSession>('/api/production/sessions/', params),
    create: (data: Partial<ProductionSession>) =>
      apiClient.post<ProductionSession>('/api/production/sessions/', data),
    update: (id: string, data: Partial<ProductionSession>) =>
      apiClient.patch<ProductionSession>(`/api/production/sessions/${id}/`, data),
    // BUG-051 : écart production déclarée vs ventes livrées + retours (CLAUDE.md §5.4)
    reconciliation: (params?: { node?: string; date?: string; date_from?: string; date_to?: string }) =>
      apiClient.get<ProductionReconciliation>('/api/production/sessions/reconciliation/', { params }),
    // BUG-093/BUG-108 : clôture automatisée de la fournée (recoupement ventes/dispositions,
    // reliquat NV, écart). Fige is_closed/closed_at/closure_summary ; action irréversible.
    close: (id: string) =>
      apiClient.post<ProductionSession>(`/api/production/sessions/${id}/close/`),
  },
  breadStocks: {
    list: (params?: Record<string, string>) =>
      getList<BreadStock>('/api/production/bread-stocks/', params),
  },
  consumableTypes: {
    list: (params?: Record<string, string>) =>
      getList<ConsumableType>('/api/production/consumable-types/', params),
    create: (data: Partial<ConsumableType>) =>
      apiClient.post<ConsumableType>('/api/production/consumable-types/', data),
    update: (id: number, data: Partial<ConsumableType>) =>
      apiClient.patch<ConsumableType>(`/api/production/consumable-types/${id}/`, data),
    delete: (id: number) =>
      apiClient.delete(`/api/production/consumable-types/${id}/`),
  },
  stocks: {
    list: (params?: Record<string, string>) =>
      getList<ConsumableStock>('/api/production/stocks/', params),
  },
  transfers: {
    list: (params?: Record<string, string>) =>
      getList<BreadTransfer>('/api/production/transfers/', params),
    create: (data: Partial<Omit<BreadTransfer, 'lines'>> & { lines?: Array<{ bread_price: number; quantity_sent: number }> }) =>
      apiClient.post<BreadTransfer>('/api/production/transfers/', data),
    respond: (id: string, approved: boolean, lines?: Array<{ bread_price: number; quantity_sent: number }>) =>
      apiClient.post(`/api/production/transfers/${id}/respond_to_request/`, { approved, lines }),
    confirm: (id: string, lines: Array<{ bread_price: number; quantity_received: number }>) =>
      apiClient.post(`/api/production/transfers/${id}/confirm_reception/`, { lines }),
  },
  movements: {
    list: (params?: Record<string, string>) =>
      getList<ConsumableMovement>('/api/production/movements/', params),
    create: (data: Partial<ConsumableMovement>) =>
      apiClient.post<ConsumableMovement>('/api/production/movements/', data),
    flourHistory: (params?: Record<string, string>) =>
      getList<FlourHistoryEntry>('/api/production/movements/flour_history/', params),
  },
  counts: {
    list: (params?: Record<string, string>) =>
      getList<ConsumableCount>('/api/production/counts/', params),
    create: (data: Partial<ConsumableCount> & { node?: string }) =>
      apiClient.post<ConsumableCount>('/api/production/counts/', data),
  },
  disposals: {
    list: (params?: Record<string, string>) =>
      getList<BreadDisposal>('/api/production/disposals/', params),
    create: (data: Partial<BreadDisposal>) =>
      apiClient.post<BreadDisposal>('/api/production/disposals/', data),
  },
  // BUG-120 : rapport de clôture journalier consolidé (lecture seule).
  dailyClosure: {
    get: (node: string, date: string) =>
      apiClient.get<DailyClosureReport>('/api/production/daily-closure/', { params: { node, date } }),
  },
};

// ── Commissions API ──────────────────────────────────────────────────────────

export const commissionsApi = {
  periods: {
    list: () => getList<CommissionPeriod>('/api/commissions/periods/'),
    create: (data: Partial<CommissionPeriod>) =>
      apiClient.post<CommissionPeriod>('/api/commissions/periods/', data),
    close: (id: string) =>
      apiClient.post(`/api/commissions/periods/${id}/close_period/`),
    generate: (data: { node: string; month: number; year: number }) =>
      apiClient.post<{ period: CommissionPeriod; generated: number }>('/api/commissions/periods/generate/', data),
    history: (params?: Record<string, string>) =>
      getList<CmHistoryRow>('/api/commissions/periods/history/', params),
  },
  commissions: {
    list: (params?: Record<string, string>) =>
      getList<ClientCommission>('/api/commissions/commissions/', params),
    markPaid: (id: string) =>
      apiClient.post(`/api/commissions/commissions/${id}/mark_paid/`),
    setManuel: (id: string, data: { manuel_adjustment: string | null; manuel_notes?: string }) =>
      apiClient.patch<ClientCommission>(`/api/commissions/commissions/${id}/set_manuel/`, data),
    payrollListing: (periodId: string) =>
      apiClient.get(`/api/commissions/commissions/payroll_listing/?period=${periodId}`),
  },
};

// ── Treasury API ─────────────────────────────────────────────────────────────

export const treasuryApi = {
  reports: {
    list: (params?: Record<string, string>) =>
      getList<FacturierReport>('/api/treasury/reports/', params),
    create: (data: Partial<FacturierReport>) =>
      apiClient.post<FacturierReport>('/api/treasury/reports/', data),
    validate: (id: string) =>
      apiClient.post(`/api/treasury/reports/${id}/validate/`),
    generate: (data?: { date?: string; node?: string }) =>
      apiClient.post<FacturierReport[]>('/api/treasury/reports/generate/', data || {}),
  },
  expenses: {
    list: (params?: Record<string, string>) =>
      getList<LocalExpense>('/api/treasury/expenses/', params),
    create: (data: Partial<LocalExpense>) =>
      apiClient.post<LocalExpense>('/api/treasury/expenses/', data),
  },
  closures: {
    list: (params?: Record<string, string>) =>
      getList<CashClosure>('/api/treasury/closures/', params),
    create: (data: Partial<CashClosure>) =>
      apiClient.post<CashClosure>('/api/treasury/closures/', data),
    update: (id: string, data: Partial<CashClosure>) =>
      apiClient.patch<CashClosure>(`/api/treasury/closures/${id}/`, data),
    validate: (id: string, notes?: string) =>
      apiClient.post<CashClosure>(`/api/treasury/closures/${id}/validate/`, { notes: notes || '' }),
    reject: (id: string, reason?: string) =>
      apiClient.post<CashClosure>(`/api/treasury/closures/${id}/reject/`, { reason: reason || '' }),
    pushToCashbook: (id: string) =>
      apiClient.post(`/api/treasury/closures/${id}/push_to_cashbook/`),
  },
  cashbook: {
    list: (params?: Record<string, string>) =>
      getList<CashbookEntry>('/api/treasury/cashbook/', params),
    integrityCheck: () =>
      apiClient.get<{ chain_valid: boolean; tampered_count: number }>(
        '/api/treasury/cashbook/integrity_check/'
      ),
    periodSummary: (params?: Record<string, string>) =>
      apiClient.get('/api/treasury/cashbook/period_summary/', { params }),
  },
  vouchers: {
    list: (params?: Record<string, string>) =>
      getList<DisbursementVoucher>('/api/treasury/vouchers/', params),
    create: (data: Partial<DisbursementVoucher>) =>
      apiClient.post<DisbursementVoucher>('/api/treasury/vouchers/', data),
    finalReport: (params?: Record<string, string>) =>
      apiClient.get<{ vouchers: DisbursementVoucher[]; total_disbursed: string; remaining_balance: string }>(
        '/api/treasury/vouchers/final_report/', { params }
      ),
  },
  journal: {
    list: (params?: Record<string, string>) =>
      getList<JournalEntry>('/api/treasury/journal/', params),
    create: (data: Partial<JournalEntry> & { node?: string }) =>
      apiClient.post<JournalEntry>('/api/treasury/journal/', data),
    suggestedCa: (params: { node: string; date: string }) =>
      apiClient.get<SuggestedCa>('/api/treasury/journal/suggested_ca/', { params }),
    monthlyReport: (params: Record<string, string>) =>
      apiClient.get<{
        month: string; year: string;
        month_carried: string; total_entries: string;
        total_exits: string; final_balance: string;
      }>('/api/treasury/journal/monthly_report/', { params }),
  },
  savings: {
    list: (params?: Record<string, string>) =>
      getList<DailySavings>('/api/treasury/savings/', params),
    create: (data: Partial<DailySavings> & { node?: string }) =>
      apiClient.post<DailySavings>('/api/treasury/savings/', data),
    update: (id: number, data: Partial<DailySavings>) =>
      apiClient.patch<DailySavings>(`/api/treasury/savings/${id}/`, data),
    monthlyTotal: (params: Record<string, string>) =>
      apiClient.get<{
        month: string; year: string;
        total_flour_sacks: string; total_revenue: string; total_savings: string;
        entries: DailySavings[];
      }>('/api/treasury/savings/monthly_total/', { params }),
  },
  // BUG-119 — comptage physique Livre de Caisse Direction (IsHeadquarters
  // uniquement, pas de update/delete : voir DirectionCashCountViewSet).
  directionCashCounts: {
    list: (params?: Record<string, string>) =>
      getList<DirectionCashCount>('/api/treasury/direction-cash-counts/', params),
    create: (data: Partial<DirectionCashCount>) =>
      apiClient.post<DirectionCashCount>('/api/treasury/direction-cash-counts/', data),
  },
};

// ── Finance API ──────────────────────────────────────────────────────────────

export const financeApi = {
  years: {
    list: () => getList<FinancialYear>('/api/finance/years/'),
    create: (data: Partial<FinancialYear>) =>
      apiClient.post<FinancialYear>('/api/finance/years/', data),
  },
  incomeStatement: (yearId: string) =>
    apiClient.get<IncomeStatement>(`/api/finance/years/${yearId}/income_statement/`),
  cashflow: (yearId: string) =>
    apiClient.get<Cashflow>(`/api/finance/years/${yearId}/cashflow/`),
  balanceSheet: (yearId: string) =>
    apiClient.get<BalanceSheet>(`/api/finance/years/${yearId}/balance_sheet/`),
  comparative: (yearId: string) =>
    apiClient.get(`/api/finance/years/${yearId}/comparative/`),
  summary: (params: Record<string, string>) =>
    getList<FinanceSummaryRow>('/api/finance/years/summary/', params),
  doc1Report: (params: Record<string, string>) =>
    getList<Doc1Row>('/api/finance/years/doc1_report/', params),
  doc1Export: (params: { node: string; month: string; year: string }) =>
    apiClient.get('/api/finance/years/doc1_export/', { params, responseType: 'blob' }),
};

// ── Blockchain API ────────────────────────────────────────────────────────────

export const blockchainApi = {
  alerts: {
    list: (params?: Record<string, string>) =>
      getList<TamperAlert>('/api/blockchain/alerts/', params),
    resolve: (id: string) =>
      apiClient.post(`/api/blockchain/alerts/${id}/resolve/`),
  },
  snapshots: {
    list: () => getList<BlockchainSnapshot>('/api/blockchain/snapshots/'),
    globalStatus: () =>
      apiClient.get('/api/blockchain/snapshots/global_status/'),
    runCheck: (nodeId?: string) =>
      apiClient.post('/api/blockchain/snapshots/run_check/', nodeId ? { node: nodeId } : {}),
  },
};
