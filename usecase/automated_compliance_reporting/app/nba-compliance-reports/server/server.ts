import { createApp, analytics, jobs, lakebase, server } from '@databricks/appkit';
import { z } from 'zod';
import { setupStateRoutes } from './routes/lakebase/state-routes';
import { setupWorkflowRoutes, type WorkflowAppKit } from './routes/workflow-routes';

// Lock the jobs plugin's generic HTTP route to job-level string parameters only.
const jobParams = z.object({ job_parameters: z.record(z.string(), z.string().max(200)) }).strict();

// Bind only the jobs that are configured, so a missing optional job does not stop the app starting.
const jobConfig = Object.fromEntries(
  (
    [
      ['report', process.env.DATABRICKS_JOB_REPORT],
      ['verify', process.env.DATABRICKS_JOB_VERIFY],
    ] as const
  )
    .filter(([, id]) => Boolean(id))
    .map(([key]) => [key, { params: jobParams }])
);

createApp({
  plugins: [analytics(), jobs({ jobs: jobConfig }), lakebase(), server()],
  async onPluginsReady(appkit) {
    setupWorkflowRoutes(appkit as unknown as WorkflowAppKit);
    await setupStateRoutes(appkit);
  },
}).catch((error) => {
  console.error('Application failed to start', error);
  process.exit(1);
});
