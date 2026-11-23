# Rapport dev-frontend (Dev B) — lot I-4 frontend (BUG-1113), 2026-11-23

## Fait
- `frontend/src/api/services.ts` : `productionApi.intrantsExport.download({date, month?, node?})` -> `{blob, filename}` (GET `responseType: 'blob'` via `apiClient`, nom lu dans Content-Disposition, repli `statistiques-intrants-AAAA-MM-JJ.xlsx`). En erreur, le corps blob JSON est lu et `detail` est relancé en `Error` lisible.
- `frontend/src/utils/downloadFile.ts` : `saveBlob(blob, filename)` (aucun utilitaire existant réutilisable : `clotureReportExport.ts` n'en contient pas ; Commissions/Finance/BassinsSection ont chacun leur code inline, non touchés).
- `frontend/src/components/production/useIntrantsExport.ts` : hook `{ exporting, error, exportIntrants }`.
- `FlourMonthStats.tsx` : bouton « Exporter Excel » (« Export… » et désactivé pendant le téléchargement, erreur sous la barre). `date` = aujourd'hui (mois courant) ou dernier jour du mois affiché, via `localIsoDate` ; `month` = mois affiché ; `node` = boulangerie choisie (rôles siège). Barre en `flex-wrap`.

## Usage du hook pour dev-a (onglet Statistiques I-2)
```tsx
import { useIntrantsExport } from '@/components/production/useIntrantsExport';
const { exporting, error, exportIntrants } = useIntrantsExport();
<button disabled={exporting} onClick={() => void exportIntrants({ date, month, node })}>{exporting ? 'Export…' : 'Exporter Excel'}</button>
{error && <div role="alert">{error}</div>}
```
`date` en AAAA-MM-JJ locale (`localIsoDate`), `month` et `node` facultatifs.

## Vérifications
- `npx tsc --noEmit` et `npm run build` : voir résultat communiqué au coordinateur (lancés dans frontend/).
- Non touchés : IntrantsTab.tsx, App.tsx, DashboardLayout.tsx, Nodes.tsx, Clients.tsx, backend.

## Non vérifié visuellement
- Rendu à 360 / 768 / 1440 px et téléchargement réel du .xlsx avec un serveur (aucun serveur lancé).
- Lecture du `detail` d'un blob 400/403 en conditions réelles (logique écrite, non exercée).
- Le nom du fichier avec `filename*=` n'a pas été testé (le backend envoie `filename="..."`).
