import type { QueryRegistry } from '@databricks/appkit-ui/react';

/** One row of an analytics query. Values arrive as strings; read them through lib/format helpers. */
export type QueryRow<K extends keyof QueryRegistry> = QueryRegistry[K]['result'] extends Array<infer R> ? R : never;
