/**
 * Centralised, validated runtime configuration.
 *
 * The service is stateless: every value comes from the environment so the same
 * image runs unchanged across Cloud Run revisions. Nothing here is persisted.
 */

export interface Config {
  /** Port Cloud Run injects via $PORT (defaults to 8080 locally). */
  port: number;
  /** Telegram bot token — used to derive the HMAC key for initData. Secret. */
  botToken: string;
  /**
   * Secret token configured on the Telegram webhook (setWebhook secret_token).
   * Telegram echoes it in the X-Telegram-Bot-Api-Secret-Token header so we can
   * reject forged webhook calls. Secret.
   */
  webhookSecret: string;
  /** GCP project hosting Firestore + the video bucket. */
  projectId: string;
  /** The single GCS bucket the service is allowed to mint signed URLs for. */
  videoBucket: string;
  /**
   * Service account email used for V4 signed-URL signing via IAM SignBlob.
   * When empty, the runtime ADC service account is used (Cloud Run default).
   */
  signerServiceAccount: string;
  /** Signed-URL lifetime. Spec fixes this at 10 minutes; kept here for tests. */
  signedUrlTtlSeconds: number;
  /** True only in local/dev dry-run mode — disables GCP client construction. */
  dryRun: boolean;
}

function required(name: string, fallbackForDryRun?: string): string {
  const value = process.env[name];
  if (value && value.length > 0) return value;
  if (process.env.DRY_RUN === "1" && fallbackForDryRun !== undefined) {
    return fallbackForDryRun;
  }
  throw new Error(`Missing required environment variable: ${name}`);
}

export function loadConfig(): Config {
  const dryRun = process.env.DRY_RUN === "1";
  return {
    port: Number(process.env.PORT ?? "8080"),
    botToken: required("TELEGRAM_BOT_TOKEN", "dry-run-bot-token"),
    webhookSecret: required("TELEGRAM_WEBHOOK_SECRET", "dry-run-webhook-secret"),
    projectId: required("GCP_PROJECT_ID", "dry-run-project"),
    videoBucket: required("VIDEO_BUCKET", "dry-run-bucket"),
    signerServiceAccount: process.env.SIGNER_SERVICE_ACCOUNT ?? "",
    signedUrlTtlSeconds: Number(process.env.SIGNED_URL_TTL_SECONDS ?? "600"),
    dryRun,
  };
}
