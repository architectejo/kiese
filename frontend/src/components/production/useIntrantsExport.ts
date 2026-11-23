import { useCallback, useState } from 'react';
import { productionApi } from '@/api/services';
import { getErrorDetail } from '@/api/errors';
import { saveBlob } from '@/utils/downloadFile';

/**
 * Export Excel des statistiques d'intrants (BUG-1113, lot I-4).
 * Usage : const { exporting, error, exportIntrants } = useIntrantsExport();
 *         exportIntrants({ date: 'AAAA-MM-JJ', month?: 'AAAA-MM', node?: code });
 */
export function useIntrantsExport() {
  const [exporting, setExporting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const exportIntrants = useCallback(async (params: { date: string; month?: string; node?: string }) => {
    setExporting(true);
    setError(null);
    try {
      const { blob, filename } = await productionApi.intrantsExport.download(params);
      saveBlob(blob, filename);
    } catch (err: unknown) {
      setError(getErrorDetail(err, "Impossible d'exporter les statistiques."));
    } finally {
      setExporting(false);
    }
  }, []);

  return { exporting, error, exportIntrants };
}
