// BUG-387 : types du contrat BUG-386 (vue globale consommables direction + inventaire physique).
// Les quantités sont des chaînes décimales à 3 décimales (« 12.500 »).

export interface GlobalConsumableType {
  code: string;
  label: string;
  unit: string;
}

export interface GlobalLastInventory {
  id: string;
  date: string;
  has_comment: boolean;
}

export interface GlobalNodeRow {
  node: number;
  code: string;
  name: string;
  stocks: Record<string, string>;
  last_inventory: GlobalLastInventory | null;
}

export interface GlobalConsumables {
  types: GlobalConsumableType[];
  direction: { node: number; code: string; stocks: Record<string, string> };
  nodes: GlobalNodeRow[];
  totals_bakeries: Record<string, string>;
  totals_group: Record<string, string>;
}

export interface ConsumableDispatchPayload {
  consumable_type: string;
  note?: string;
  allocations: Array<{ node: number | string; quantity: string }>;
}

export interface ConsumableDispatchResult {
  consumable_type: string;
  unit: string;
  total_sent: string;
  direction_remaining: string;
  sent: Array<{ node: number; code: string; quantity: string }>;
}

export interface InventoryLine {
  id: number;
  consumable_type: string;
  consumable_type_display: string;
  unit: string;
  system_quantity: string;
  physical_quantity: string;
  gap: string;
  notes: string;
}

export interface ConsumableInventory {
  id: string;
  node: number;
  node_code: string;
  node_name: string;
  inventory_date: string;
  comment: string;
  recorded_by: number | string | null;
  recorded_by_display: string;
  created_at: string;
  updated_at: string;
  lines_editable: boolean;
  lines?: InventoryLine[];
}

export interface InventoryToday {
  date: string;
  done: boolean;
  inventory: ConsumableInventory | null;
}

export interface InventoryCreatePayload {
  comment?: string;
  lines: Array<{ consumable_type: string; physical_quantity: string; notes?: string }>;
}

export interface NodeInventoryDetail {
  node: number;
  code: string;
  name: string;
  inventory: ConsumableInventory | null;
  history_dates: string[];
}
