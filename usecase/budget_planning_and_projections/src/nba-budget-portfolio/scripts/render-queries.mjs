// Renders config/query-templates/*.sql into config/queries/ (what AppKit's analytics plugin reads),
// replacing {{schema}} with the deployment's `catalog`.`schema`. Runs before `dev`, `start` and
// type generation, so no catalog or schema name is ever committed to the repository.
//
// The schema comes from, in order:
//   PORTFOLIO_SCHEMA  explicit "catalog.schema" (e.g. in a local, git-ignored .env)
//   PORTFOLIO_TABLE   full name of any portfolio table, as injected by an app resource binding
//                     (app.yaml `valueFrom`); the table part is dropped
import { mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const templatesDir = join(root, 'config', 'query-templates');
const outputDir = join(root, 'config', 'queries');

export function resolveSchema(env = process.env) {
  const parts = env.PORTFOLIO_SCHEMA
    ? env.PORTFOLIO_SCHEMA.split('.')
    : env.PORTFOLIO_TABLE
      ? env.PORTFOLIO_TABLE.split('.').slice(0, -1)
      : [];
  const clean = parts.map((p) => p.trim().replace(/^`|`$/g, ''));
  if (clean.length !== 2 || clean.some((p) => !/^[A-Za-z0-9_-]+$/.test(p))) {
    throw new Error(
      'Set PORTFOLIO_SCHEMA=<catalog>.<schema> (local .env) or bind a table resource to PORTFOLIO_TABLE (app.yaml).',
    );
  }
  return clean.map((p) => `\`${p}\``).join('.');
}

const schema = resolveSchema();
rmSync(outputDir, { recursive: true, force: true });
mkdirSync(outputDir, { recursive: true });
const templates = readdirSync(templatesDir).filter((f) => f.endsWith('.sql'));
for (const file of templates) {
  const sql = readFileSync(join(templatesDir, file), 'utf8');
  writeFileSync(join(outputDir, file), sql.replaceAll('{{schema}}', schema));
}
console.log(`Rendered ${templates.length} queries for ${schema}`);
