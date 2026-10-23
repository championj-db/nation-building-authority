import { createApp, analytics, genie, server } from '@databricks/appkit';

createApp({
  plugins: [
    analytics(),
    genie({
      spaces: {
        default: process.env.DATABRICKS_GENIE_SPACE_ID ?? '',
      },
    }),
    server(),
  ],
  onPluginsReady(appkit) {
    appkit.server.extend((app) => {
      app.get('/api/whoami', (request, response) => {
        response.json({
          email: request.header('x-forwarded-email') ?? null,
          user: request.header('x-forwarded-user') ?? null,
        });
      });
    });
  },
}).catch(console.error);
