import { useRef } from 'react';
import { useAnalyticsQuery } from '@databricks/appkit-ui/react';

/** useAnalyticsQuery that keeps showing the previous result while a refresh (new data_version) is in flight. */
export const useQuery = ((key: never, params: never, options?: never) => {
  const result = useAnalyticsQuery(key, params, options);
  const last = useRef(result.data);
  if (result.data) last.current = result.data;
  return { ...result, data: result.data ?? last.current };
}) as unknown as typeof useAnalyticsQuery;
