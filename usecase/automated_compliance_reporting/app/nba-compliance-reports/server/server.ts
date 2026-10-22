import { createApp, analytics, jobs, lakebase, server } from '@databricks/appkit';
import { setupStateRoutes } from './routes/lakebase/state-routes';

createApp({
  plugins: [analytics(), jobs(), lakebase(), server()],
  async onPluginsReady(appkit) {
    await setupStateRoutes(appkit);
  },
}).catch(console.error);
