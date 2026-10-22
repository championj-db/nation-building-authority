import type { Application, Request } from 'express';
import { z } from 'zod';

interface AppKitWithLakebase {
  lakebase: { query(text: string, params?: unknown[]): Promise<{ rows: Record<string, unknown>[] }> };
  server: { extend(fn: (app: Application) => void): void };
}

const Preference = z.object({
  key: z.string().min(1).max(80),
  value: z.unknown(),
});

const SavedView = z.object({
  name: z.string().min(1).max(100),
  route: z.string().min(1).max(80),
  filters: z.record(z.string(), z.unknown()).default({}),
});

function userId(req: Request) {
  return req.header('x-forwarded-email') ?? req.header('x-forwarded-user') ?? 'local-user';
}

export async function setupStateRoutes(appkit: AppKitWithLakebase) {
  await appkit.lakebase.query('CREATE SCHEMA IF NOT EXISTS compliance_app');
  await appkit.lakebase.query(`
    CREATE TABLE IF NOT EXISTS compliance_app.preferences (
      user_id TEXT NOT NULL, preference_key TEXT NOT NULL, preference_value JSONB NOT NULL,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), PRIMARY KEY (user_id, preference_key)
    );
    CREATE TABLE IF NOT EXISTS compliance_app.saved_views (
      id BIGSERIAL PRIMARY KEY, user_id TEXT NOT NULL, name TEXT NOT NULL, route TEXT NOT NULL,
      filters JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS saved_views_user_idx ON compliance_app.saved_views(user_id, created_at DESC);
  `);

  appkit.server.extend((app) => {
    app.get('/api/config', (req, res) => {
      res.json({
        catalog: process.env.DATABRICKS_CATALOG,
        schema: process.env.DATABRICKS_SCHEMA,
        user: userId(req),
      });
    });

    app.get('/api/state', async (req, res) => {
      const [preferences, savedViews] = await Promise.all([
        appkit.lakebase.query(
          'SELECT preference_key AS key, preference_value AS value FROM compliance_app.preferences WHERE user_id = $1',
          [userId(req)]
        ),
        appkit.lakebase.query(
          'SELECT id, name, route, filters, created_at FROM compliance_app.saved_views WHERE user_id = $1 ORDER BY created_at DESC',
          [userId(req)]
        ),
      ]);
      res.json({ preferences: preferences.rows, savedViews: savedViews.rows });
    });

    app.put('/api/preferences', async (req, res) => {
      const parsed = Preference.safeParse(req.body);
      if (!parsed.success) return void res.status(400).json({ error: 'Invalid preference' });
      const result = await appkit.lakebase.query(
        `INSERT INTO compliance_app.preferences(user_id, preference_key, preference_value)
         VALUES ($1, $2, $3::jsonb)
         ON CONFLICT (user_id, preference_key) DO UPDATE
         SET preference_value = EXCLUDED.preference_value, updated_at = NOW()
         RETURNING preference_key AS key, preference_value AS value, updated_at`,
        [userId(req), parsed.data.key, JSON.stringify(parsed.data.value)]
      );
      res.json(result.rows[0]);
    });

    app.post('/api/saved-views', async (req, res) => {
      const parsed = SavedView.safeParse(req.body);
      if (!parsed.success) return void res.status(400).json({ error: 'Invalid saved view' });
      const result = await appkit.lakebase.query(
        `INSERT INTO compliance_app.saved_views(user_id, name, route, filters)
         VALUES ($1, $2, $3, $4::jsonb) RETURNING id, name, route, filters, created_at`,
        [userId(req), parsed.data.name, parsed.data.route, JSON.stringify(parsed.data.filters)]
      );
      res.status(201).json(result.rows[0]);
    });

    app.delete('/api/saved-views/:id', async (req, res) => {
      await appkit.lakebase.query('DELETE FROM compliance_app.saved_views WHERE id = $1 AND user_id = $2', [
        req.params.id,
        userId(req),
      ]);
      res.status(204).send();
    });
  });
}
