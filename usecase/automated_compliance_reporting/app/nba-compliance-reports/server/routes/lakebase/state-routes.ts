import type { Application, Request, Response } from 'express';
import { z } from 'zod';

/**
 * App-owned user state in Lakebase (`compliance_app` schema): per-user preferences such as the
 * filters last used on each screen. This is convenience state only. Compliance decisions never
 * live here; they go to the append-only Delta tables (see workflow-routes.ts).
 */

interface AppKitWithLakebase {
  lakebase: { query(text: string, params?: unknown[]): Promise<{ rows: Record<string, unknown>[] }> };
  server: { extend(fn: (app: Application) => void): void };
}

const Preference = z.object({
  key: z
    .string()
    .min(1)
    .max(80)
    .regex(/^[a-z0-9_.:-]+$/i),
  value: z.unknown(),
});

function userId(req: Request) {
  return req.header('x-forwarded-email') ?? req.header('x-forwarded-user') ?? 'local-user';
}

export async function setupStateRoutes(appkit: AppKitWithLakebase) {
  let available = true;
  try {
    await appkit.lakebase.query('CREATE SCHEMA IF NOT EXISTS compliance_app');
    await appkit.lakebase.query(`
      CREATE TABLE IF NOT EXISTS compliance_app.preferences (
        user_id TEXT NOT NULL, preference_key TEXT NOT NULL, preference_value JSONB NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), PRIMARY KEY (user_id, preference_key)
      );
    `);
  } catch (error) {
    // Lakebase state is optional. Without it the app still works; preferences just are not remembered.
    available = false;
    console.warn('[state] Lakebase preferences unavailable:', error instanceof Error ? error.message : error);
  }

  const guard = (fn: (req: Request, res: Response) => Promise<void>) => async (req: Request, res: Response) => {
    if (!available) return void res.status(503).json({ error: 'Preferences are unavailable.' });
    try {
      await fn(req, res);
    } catch (error) {
      console.error('[state]', error);
      res.status(500).json({ error: 'Preferences could not be read or saved.' });
    }
  };

  appkit.server.extend((app) => {
    app.get(
      '/api/preferences',
      guard(async (req, res) => {
        const result = await appkit.lakebase.query(
          'SELECT preference_key AS key, preference_value AS value FROM compliance_app.preferences WHERE user_id = $1',
          [userId(req)]
        );
        const preferences: Record<string, unknown> = {};
        for (const row of result.rows) preferences[String(row.key)] = row.value;
        res.json({ preferences });
      })
    );

    app.put(
      '/api/preferences',
      guard(async (req, res) => {
        const parsed = Preference.safeParse(req.body);
        if (!parsed.success) return void res.status(400).json({ error: 'Invalid preference' });
        await appkit.lakebase.query(
          `INSERT INTO compliance_app.preferences(user_id, preference_key, preference_value)
           VALUES ($1, $2, $3::jsonb)
           ON CONFLICT (user_id, preference_key) DO UPDATE
           SET preference_value = EXCLUDED.preference_value, updated_at = NOW()`,
          [userId(req), parsed.data.key, JSON.stringify(parsed.data.value ?? null)]
        );
        res.status(204).send();
      })
    );
  });
}
