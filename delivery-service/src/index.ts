import express from "express";
import { loadConfig } from "./config.js";
import { createEntitlementStore } from "./firestore.js";
import { createManifestSigner } from "./storage.js";
import { authRouter } from "./routes/auth.js";
import { manifestRouter } from "./routes/manifest.js";
import { starsWebhookRouter } from "./routes/starsWebhook.js";

export function createApp() {
  const config = loadConfig();
  const store = createEntitlementStore(config);
  const signer = createManifestSigner(config);

  const app = express();
  app.use(express.json({ limit: "256kb" }));

  // Liveness/readiness probe — polled by the control-agent HEARTBEAT.
  app.get("/healthz", (_req, res) => {
    res.json({ ok: true, service: "delivery-service", dryRun: config.dryRun });
  });

  app.use("/auth", authRouter(config));
  app.use("/manifest", manifestRouter(config, store, signer));
  app.use("/webhook", starsWebhookRouter(config, store));

  // Catch-all 404.
  app.use((_req, res) => res.status(404).json({ ok: false, error: "not found" }));

  return { app, config };
}

// Only start listening when run directly (not when imported by tests).
if (require.main === module) {
  const { app, config } = createApp();
  app.listen(config.port, () => {
    // eslint-disable-next-line no-console
    console.log(
      `delivery-service listening on :${config.port} (dryRun=${config.dryRun})`,
    );
  });
}
