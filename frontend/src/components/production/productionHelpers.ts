import { productionApi, BreadTransfer, BreadDisposal } from '@/api/services';
import { localIsoDate } from '@/store/workDateStore';

export const STOCK_ICONS: Record<string, string> = { FLOUR: '🌾', YEAST: '💥', SALT: '🧂', OIL: '💧' };

export const displayStock = (s: string) => (s || '').replace(/\s*\(Sac \d+\s*kg\)/i, '').trim() || s;
// BUG-161 (F3) : plus de date UTC. Un horodatage `created_at` (UTC) est converti en date LOCALE
// avant comparaison à la date du jour ; en rotation de 24 h c'est exact : le jour
// calendaire fait foi (les sorties n'ont pas de `work_date` côté API).
export const isOnDay = (iso: string | undefined, day: string): boolean =>
  !!iso && localIsoDate(new Date(iso)) === day;

// BUG-164 : au lieu de lire TOUTES les sorties puis de garder les 20 premières, on demande
// 20 lignes au serveur (tri -created_at). Le KPI « Pains non valorisés » (sorties du jour)
// reste exact : si la dernière ligne lue est encore d'aujourd'hui, on lit la page suivante
// (les sorties du jour forment un préfixe de la liste triée), jamais de total partiel.
export async function fetchDisposalsPage(scoped: Record<string, string>, day: string): Promise<{ shown: BreadDisposal[]; todayQty: number }> {
  let page = 1;
  const first = await productionApi.disposals.page({ ...scoped, page: '1', page_size: '20' });
  const shown = (first.data.results ?? []).slice(0, 20);
  let all: BreadDisposal[] = first.data.results ?? [];
  let next = first.data.next;
  while (next && isOnDay(all[all.length - 1]?.created_at, day)) {
    page += 1;
    const r = await productionApi.disposals.page({ ...scoped, page: String(page), page_size: '20' });
    all = all.concat(r.data.results ?? []);
    next = r.data.next;
  }
  // BUG-245 : le stock restant (REMAINING) n'est ni une perte ni un pain « non valorisé ».
  const todayQty = all
    .filter(d => d.disposal_type !== 'REMAINING' && isOnDay(d.created_at, day))
    .reduce((a, d) => a + (d.quantity || 0), 0);
  return { shown, todayQty };
}

// BUG-244 : KPI « Fournées » / « Valeur FC produite » = totaux complets (toutes les pages),
// jamais la somme des 15 fournées affichées. `null` tant que non chargé / en cas d'échec.
export async function fetchSessionTotals(scoped: Record<string, string>): Promise<{ count: number; totalFc: number }> {
  let page = 1;
  let count = 0;
  let totalFc = 0;
  for (;;) {
    const r = await productionApi.sessions.page({ ...scoped, page: String(page), page_size: '500' });
    count = r.data.count ?? 0;
    totalFc += (r.data.results ?? []).reduce((a, s) => a + (Number(s.total_fc_produced) || 0), 0);
    if (!r.data.next) break;
    page += 1;
  }
  return { count, totalFc };
}

// BUG-164 : l'API des transferts n'a pas de filtre « boulangerie impliquée » (from_node OU
// to_node) ; on s'appuie sur le filtre `transfer_status` existant : les transferts actifs
// (en attente, à confirmer, en litige — peu nombreux) sont lus en entier, et pour l'historique
// on ne demande que les 3 derniers CONFIRMED (par boulangerie : from_node puis to_node).
export async function fetchTransfersScoped(node: string | undefined): Promise<BreadTransfer[]> {
  const [pend, resp, disp] = await Promise.all([
    productionApi.transfers.list({ transfer_status: 'PENDING' }),
    productionApi.transfers.list({ transfer_status: 'RESPONDED' }),
    productionApi.transfers.list({ transfer_status: 'DISPUTED' }),
  ]);
  const confirmedParams: Array<Record<string, string>> = node
    ? [{ from_node: node }, { to_node: node }]
    : [{}];
  const confirmedPages = await Promise.all(confirmedParams.map(extra =>
    productionApi.transfers.page({ transfer_status: 'CONFIRMED', ...extra, page: '1', page_size: '3' })));
  const seen = new Set<string>();
  const confirmed = confirmedPages
    .flatMap(r => r.data.results ?? [])
    .filter(t => (seen.has(t.id) ? false : (seen.add(t.id), true)))
    .sort((a, b) => String(b.created_at ?? '').localeCompare(String(a.created_at ?? '')))
    .slice(0, 3);
  return [...pend.data, ...resp.data, ...disp.data, ...confirmed];
}

export const DISPOSAL_LABELS: Record<string, string> = {
  SOLD_DISCOUNT: 'Pains Soldés',
  DECLASSED:     'Pains Déclassés (non conformes)',
  UNSOLD:        'Pains Invendus (perte sèche)',
  FREE_DIST:     'Sorties gratuite (NV)',
  REMAINING:     'Stock Restant',
};
// BUG-092/BUG-096 (volet frontend) : le backend refuse désormais la création d'un nouveau
// BreadDisposal de type SOLD_DISCOUNT (la vente soldée se fait dans Facturation/Gestion
// Clientèle via `Invoice.is_soldee`, avec calcul de la perte). On ne retire SOLD_DISCOUNT que
// de la liste proposée pour une NOUVELLE saisie — les entrées historiques déjà créées avec ce
// type restent affichées normalement via DISPOSAL_LABELS/DISPOSAL_COLORS (non filtrées).
export const DISPOSAL_CREATE_LABELS: Record<string, string> = Object.fromEntries(
  Object.entries(DISPOSAL_LABELS).filter(([k]) => k !== 'SOLD_DISCOUNT')
);
// BUG-050 : POST /api/production/sessions/ et /api/production/movements/ renvoient
// désormais ce message distinct (BUG-041) quand une sortie de consommable dépasserait
// le stock disponible — affiché avec une icône dédiée plutôt que comme une erreur générique.
export const isStockInsufficientError = (msg: string | null) => !!msg && /stock insuffisant/i.test(msg);

export const DISPOSAL_COLORS: Record<string, string> = {
  SOLD_DISCOUNT: 'var(--color-info)',
  DECLASSED:     'var(--color-warning)',
  UNSOLD:        'var(--color-danger)',
  FREE_DIST:     'var(--color-success)',
  REMAINING:     'var(--accent-color)',
};
