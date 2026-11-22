import type { Invoice, BreadPrice } from '@/api/services';
import type { PendingDeliveryLine } from './PendingDeliveryActions';

// ── Delivery queue item ───────────────────────────────────────────────────────
export interface QueueItem {
  _apiId: string;
  id: string;
  clientName: string;
  clientCode: string;
  clientPhoto?: string;
  nodeDisplay: string;
  facturierDisplay: string;
  livreurDisplay?: string;
  lines: PendingDeliveryLine[];
  totalValue: number;
  /** BUG-318 : valeur commandée avant réduction (null si jamais réduite). */
  initialTotal: number | null;
  /** BUG-318 : statut serveur NOT_SERVED (distinct d'« Annulé » et du code spécial NS). */
  isNotServed: boolean;
  notServedReason: string;
  versement: number;
  paymentType: 'CASH' | 'CREDIT';
  debtBefore: number;
  debtAfter: number;
  commissionRate: number;
  isSoldee: boolean;
  /** BUG-092/BUG-096 : perte (prix catalogue − prix facturé) × quantité, nulle hors vente soldée. */
  totalLoss: number;
  isRepayment: boolean;
  specialCode: string;
  /** BUG-177 : facture « Non Servi » (NS) — reste PENDING indéfiniment, jamais livrable. */
  isNonServi: boolean;
  status: 'En attente' | 'Livré' | 'Non servi';
  invoiceDate: string;
  timeAdded: string;
  createdAt: string;
  // BUG-109 : trace d'ajustement (correction/annulation d'une commande déjà
  // enregistrée via une facture liée — jamais de mutation de l'originale).
  isAdjustment: boolean;
  adjustmentSign: 1 | -1 | null;
  adjustsId: string | null;
  adjustmentsCount: number;
}

export const mapInvoice = (inv: Invoice, bpMap: Record<number, BreadPrice>): QueueItem => ({
  _apiId: inv.id,
  id: inv.receipt_number,
  clientName: inv.client_display || inv.client,
  clientCode: inv.client_code || '',
  clientPhoto: inv.client_photo || undefined,
  nodeDisplay: inv.node_display || inv.node || '—',
  facturierDisplay: inv.facturier_display || '—',
  livreurDisplay: inv.livreur_display || undefined,
  lines: (inv.lines || []).map(l => ({
    id: l.id,
    label: bpMap[Number(l.bread_price)]?.label || l.bread_price_display || l.bread_price,
    qty: l.quantity,
    unitPrice: l.unit_price != null ? parseFloat(l.unit_price) || 0 : (bpMap[Number(l.bread_price)]?.unit_price || 0),
  })),
  totalValue: parseFloat(inv.order_total) || 0,
  initialTotal: inv.initial_order_total != null ? parseFloat(inv.initial_order_total) || 0 : null,
  isNotServed: inv.status === 'NOT_SERVED',
  notServedReason: inv.not_served_reason || '',
  versement: parseFloat(inv.payment_amount) || 0,
  paymentType: inv.payment_type,
  debtBefore: parseFloat(inv.debt_before) || 0,
  debtAfter: parseFloat(inv.debt_after) || 0,
  commissionRate: parseFloat(inv.commission_rate) || 0,
  isSoldee: inv.is_soldee === true,
  totalLoss: parseFloat(inv.total_loss || '0') || 0,
  isRepayment: inv.is_debt_repayment === true,
  specialCode: inv.special_code || '',
  isNonServi: inv.special_code === 'NS' && inv.is_debt_repayment !== true,
  status: inv.status === 'NOT_SERVED' ? 'Non servi' : inv.status === 'DELIVERED' || inv.status === 'CANCELLED' ? 'Livré' : 'En attente',
  invoiceDate: inv.invoice_date || inv.created_at?.split('T')[0] || '',
  timeAdded: new Date(inv.created_at).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }),
  createdAt: inv.created_at,
  isAdjustment: inv.is_adjustment === true,
  adjustmentSign: inv.adjustment_sign ?? null,
  adjustsId: inv.adjusts || null,
  adjustmentsCount: inv.adjustments_count || 0,
});

export const TEAM_NOT_ASSIGNED_MESSAGE =
  "Désignez l'équipe de service du jour avant de facturer. La boîte de désignation vient de s'ouvrir.";

/** Code HTTP d'une erreur axios (sans `any`), undefined hors réponse serveur. */
export const axiosStatus = (err: unknown): number | undefined =>
  (err as { response?: { status?: number } } | null)?.response?.status;
