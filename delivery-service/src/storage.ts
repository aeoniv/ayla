/**
 * GCS V4 signed-URL minting for HLS manifests.
 *
 * DEFERRED ("video logic"): per the scaffold instructions, the actual signing
 * is not implemented until the skeleton passes a dry run. The interface and the
 * IAM-SignBlob wiring are stubbed so callers and tests have a stable contract.
 */

import type { Config } from "./config.js";

export interface ManifestSigner {
  /**
   * Mint a time-limited V4 signed URL for `<videoId>/manifest.m3u8` in the one
   * permitted bucket. Lifetime is fixed at config.signedUrlTtlSeconds (600s).
   */
  signManifestUrl(videoId: string): Promise<string>;
}

class StubSigner implements ManifestSigner {
  constructor(private readonly config: Config) {}
  async signManifestUrl(_videoId: string): Promise<string> {
    // TODO(video-logic): implement V4 signed URL via @google-cloud/storage,
    // signing through the SIGNER_SERVICE_ACCOUNT (IAM SignBlob, no key file).
    throw new Error("signManifestUrl not implemented (deferred video logic)");
  }
}

export function createManifestSigner(config: Config): ManifestSigner {
  return new StubSigner(config);
}
