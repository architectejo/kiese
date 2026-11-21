import type { Client as ApiClient, BreadPrice } from '@/api/services';

export interface ClientItem {
  id: string;
  _apiId?: string;
  name: string;
  businessName: string;
  type: 'Grossiste' | 'Détaillant' | 'Revendeur' | 'Occasionnel';
  phone: string;
  address: string;
  creditLimit: number;
  outstandingDebt: number;
  commissionRate: number;
  /** BUG-289 : cotisation sociale effective (lecture seule). */
  effectiveCotisation: number;
  riskScore: 'Low' | 'Medium' | 'High';
  active: boolean;
  avatarColor: string;
  lastPaymentDate: string;
  createdAt: string;
}

/** Taille de page de chargement progressif de la liste clients (BUG-132). */
export const CLIENTS_PAGE_SIZE = 50;

export type StatModalKind = 'plafonds' | 'encours' | 'solvabilite' | 'deficit';
export type ClientDetailTab = 'info' | 'history' | 'repayments';
export type NewClientType = 'Grossiste' | 'Détaillant' | 'Revendeur';

export interface DeficitRow {
  client_code: string; client_name: string; order_value: string;
  commission_gross: string; current_debt: string; deficit: string; period: string;
}

export const mapApiClient = (c: ApiClient): ClientItem => ({
  id: c.code,
  _apiId: c.id,
  name: c.full_name,
  businessName: c.notes || c.full_name,
  type: c.client_type === 'GROSSISTE' ? 'Grossiste' : c.client_type === 'REVENDEUR' ? 'Revendeur' : 'Détaillant',
  phone: c.phone,
  address: c.address,
  creditLimit: parseFloat(c.credit_limit) || 50000,
  outstandingDebt: parseFloat(c.current_debt) || 0,
  commissionRate: parseFloat(c.commission_rate) || 0.25,
  effectiveCotisation: parseFloat(c.effective_cotisation_sociale ?? c.cotisation_sociale ?? '0') || 0,
  riskScore: c.category === 'RISK' ? 'High' : c.category === 'BEST' ? 'Low' : 'Medium',
  active: c.is_active,
  avatarColor: `hsl(${(c.code.charCodeAt(0) * 37 + c.code.charCodeAt(2) * 13) % 360}, 65%, 42%)`,
  lastPaymentDate: c.created_at.split('T')[0],
  createdAt: c.created_at,
});

  // BUG-107 : prix effectif affiché (aperçu ET reçu si la livraison serveur n'a pas pu être
  // confirmée) — remise de 75 % appliquée PAR LIGNE puis arrondie au franc le plus proche
  // (ROUND_HALF_UP), même formule que `backend/sales/models.py::InvoiceLine.save()` /
  // `SOLDEE_PRICE_RATIO = Decimal('0.75')`. `Math.round` arrondit déjà au demi supérieur pour
  // un nombre positif, équivalent à ROUND_HALF_UP ici.
  export const effectiveUnitPrice = (bp: BreadPrice, soldee: boolean) => (soldee ? Math.round(bp.unit_price * 0.75) : bp.unit_price);
