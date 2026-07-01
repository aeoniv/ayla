// Typed API client for the three Ayla backends. One session token (issued by
// delivery-service) is accepted by all three (shared SESSION_SECRET).

const DELIVERY = import.meta.env.VITE_DELIVERY_URL ?? "";
const POSE = import.meta.env.VITE_POSE_URL ?? "";
const COACH = import.meta.env.VITE_COACH_URL ?? "";

let sessionToken = "";
export function setSessionToken(t: string) {
  sessionToken = t;
}

async function req<T>(base: string, path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string>),
  };
  if (sessionToken) headers.Authorization = `Bearer ${sessionToken}`;
  const resp = await fetch(base + path, { ...init, headers });
  if (!resp.ok) {
    const body = await resp.text();
    throw new ApiError(resp.status, body);
  }
  return (await resp.json()) as T;
}

export class ApiError extends Error {
  constructor(public status: number, public body: string) {
    super(`API ${status}: ${body}`);
  }
}

// ---- types ---------------------------------------------------------------
export interface AuthResponse { session_token: string; user_id: string; role: string }
export interface FeedItem {
  movement_id: string; name: string; style_id: string;
  price_stars: number; teaser_url: string | null; created_at: string | null;
}
export interface VariantItem {
  variant_id: string; movement_id: string; style_id: string; avatar_id: string;
  price_stars: number; entitled: boolean; teaser_url: string | null;
  locked: boolean; blurred: boolean;
}
export interface ProgressResponse {
  seconds_watched: number; locked: boolean; free_preview_seconds: number;
}
export interface CheckpointMeta { index: number; timestamp_seconds: number; tolerance: number }
export interface CheckpointsResponse {
  movement_id: string; style_id: string; checkpoints: CheckpointMeta[];
}
export interface MatchResult {
  matched: boolean; score: number; worst_region: string;
  region_scores: Record<string, number>;
}
export interface AttemptResult {
  attempt_id: string; score: number; worst_region: string; checkpoints_scored: number;
}
export interface CoachResult {
  note: string;
  suggested_next: { movement_id: string | null; variant_id: string | null };
  coaching_note_id: string;
  requested_custom_skin: string | null;
}

// ---- delivery-service ----------------------------------------------------
export const authTelegram = (initData: string) =>
  req<AuthResponse>(DELIVERY, "/auth/telegram", {
    method: "POST", body: JSON.stringify({ init_data: initData }),
  });

export const getFeed = () => req<FeedItem[]>(DELIVERY, "/feed");

export const getFullVideo = (movementId: string) =>
  req<{ movement_id: string; style_id: string; full_url: string | null }>(
    DELIVERY, `/movement/${movementId}/full`,
  );

export const getVariants = (movementId: string) =>
  req<VariantItem[]>(DELIVERY, `/movement/${movementId}/variants`);

export const postProgress = (movementId: string, variantId: string | null, seconds: number) =>
  req<ProgressResponse>(DELIVERY, "/playback/progress", {
    method: "POST",
    body: JSON.stringify({ movement_id: movementId, variant_id: variantId, seconds }),
  });

export const createInvoice = (target: { movement_id?: string; variant_id?: string }) =>
  req<{ invoice_link: string }>(DELIVERY, "/payment/create-invoice", {
    method: "POST", body: JSON.stringify(target),
  });

// ---- pose-scoring-service ------------------------------------------------
export const getCheckpoints = (movementId: string, styleId: string) =>
  req<CheckpointsResponse>(POSE, `/score/checkpoints/${movementId}/${styleId}`);

export const matchCheckpoint = (
  movementId: string, styleId: string, checkpointIndex: number, landmarks: number[][],
) =>
  req<MatchResult>(POSE, "/score/checkpoint", {
    method: "POST",
    body: JSON.stringify({
      movement_id: movementId, style_id: styleId,
      checkpoint_index: checkpointIndex, landmarks,
    }),
  });

export const submitAttempt = (
  movementId: string, styleId: string, poses: { index: number; landmarks: number[][] }[],
) =>
  req<AttemptResult>(POSE, "/score/attempt", {
    method: "POST",
    body: JSON.stringify({ movement_id: movementId, style_id: styleId, poses }),
  });

// ---- coaching-agent-service ----------------------------------------------
export const coachNext = (requestedCustomSkin: string | null = null) =>
  req<CoachResult>(COACH, "/coach/next", {
    method: "POST", body: JSON.stringify({ requested_custom_skin: requestedCustomSkin }),
  });
