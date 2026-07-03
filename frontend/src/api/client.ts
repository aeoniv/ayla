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

// Multipart form POST (file uploads). Let the browser set the multipart
// Content-Type boundary; only attach the auth header.
async function form<T>(base: string, path: string, data: FormData): Promise<T> {
  const headers: Record<string, string> = {};
  if (sessionToken) headers.Authorization = `Bearer ${sessionToken}`;
  const resp = await fetch(base + path, { method: "POST", body: data, headers });
  if (!resp.ok) throw new ApiError(resp.status, await resp.text());
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
  movement_id: string; name: string; description: string | null; style_id: string;
  price_stars: number; teaser_url: string | null; created_at: string | null;
  like_count: number; liked: boolean; entitled: boolean;
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

export interface Purchase {
  scope: string; movement_id: string | null; variant_id: string | null;
  granted_at: string | null; movement_name?: string | null;
}
export const getMyPurchases = () =>
  req<{ count: number; purchases: Purchase[] }>(DELIVERY, "/me/purchases");

export interface RevenueTx { id: string; stars: number; direction: "in" | "out"; date: number }
export interface Revenue {
  balance_stars: number | null; recent_income_stars: number;
  transaction_count: number; transactions: RevenueTx[]; note: string;
}
export const getRevenue = () => req<Revenue>(DELIVERY, "/admin/revenue");

// ---- admin (Phase 7) -----------------------------------------------------
export interface CatVariant {
  variant_id: string; avatar_name: string; style_name: string;
  price_stars: number; unlocks: number; est_stars: number;
}
export interface CatMovement {
  movement_id: string; name: string; style_name: string; price_stars: number;
  reference_status: string;   // "pending" = not practicable until authored
  unlocks: number; views: number; attempts: number; est_stars: number; variants: CatVariant[];
}
export interface Catalog {
  styles: { style_id: string; name: string }[];
  avatars: { avatar_id: string; name: string }[];
  movements: CatMovement[];
  total_est_stars: number;
}
export const getCatalog = () => req<Catalog>(DELIVERY, "/admin/catalog");

export const createStyle = (name: string) => {
  const f = new FormData(); f.append("name", name);
  return form<{ style_id: string }>(DELIVERY, "/admin/style", f);
};
export const createAvatar = (name: string, styleId: string) => {
  const f = new FormData(); f.append("name", name); f.append("style_id", styleId);
  return form<{ avatar_id: string }>(DELIVERY, "/admin/avatar", f);
};
export const createMovement = (d: {
  name: string; description: string; styleId: string; priceStars: number;
  checkpoints?: number[];   // omit → studio flow; backend skips auto-authoring
  teaser: File; full: File;
}) => {
  const f = new FormData();
  f.append("name", d.name); f.append("description", d.description);
  f.append("style_id", d.styleId);
  f.append("price_stars", String(d.priceStars));
  if (d.checkpoints !== undefined)
    f.append("checkpoint_seconds", JSON.stringify(d.checkpoints));
  f.append("teaser_video", d.teaser); f.append("full_video", d.full);
  return form<{ movement_id: string; checkpoint_count: number; reference_status: string }>(
    DELIVERY, "/admin/movement", f,
  );
};
export const createVariant = (d: {
  movementId: string; styleId: string; avatarId: string; priceStars: number;
  teaser: File; full: File;
}) => {
  const f = new FormData();
  f.append("movement_id", d.movementId); f.append("style_id", d.styleId);
  f.append("avatar_id", d.avatarId); f.append("price_stars", String(d.priceStars));
  f.append("teaser_video", d.teaser); f.append("full_video", d.full);
  return form<{ variant_id: string }>(DELIVERY, "/admin/movement-variant", f);
};

export const getFullVideo = (movementId: string) =>
  req<{ movement_id: string; style_id: string; full_url: string | null }>(
    DELIVERY, `/movement/${movementId}/full`,
  );

export const likeMovement = (movementId: string) =>
  req<{ liked: boolean; like_count: number }>(
    DELIVERY, `/movement/${movementId}/like`, { method: "POST" },
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

export interface ReferenceResponse {
  movement_id: string; style_id: string;
  checkpoints: {
    index: number; landmarks: number[][];
    timestamp_seconds: number | null; tolerance: number;
    original_landmarks: number[][] | null; audit_score: number | null;
  }[];
}
export const getReference = (movementId: string, styleId: string) =>
  req<ReferenceResponse>(POSE, `/score/reference/${movementId}/${styleId}`);

export interface AuditedCheckpointPayload {
  index: number;
  timestamp_seconds: number;
  landmarks: number[][];
  original_landmarks: number[][];
  audit_score: number;
  correction_magnitude: number;
  tolerance: number;   // per-checkpoint match gate (30-95)
}
// Persist an author-audited reference (owner-gated). Sends the exact, corrected
// landmarks per checkpoint plus their frame timestamps and audit metadata.
export const saveAuditedReference = (
  movementId: string, styleId: string, checkpoints: AuditedCheckpointPayload[],
) =>
  req<{ ok: boolean; checkpoint_count: number }>(POSE, "/score/authoring-audited", {
    method: "POST",
    body: JSON.stringify({ movement_id: movementId, style_id: styleId, checkpoints }),
  });

export const matchCheckpoint = (
  movementId: string, styleId: string, checkpointIndex: number, landmarks: number[][],
  threshold?: number,
) =>
  req<MatchResult>(POSE, "/score/checkpoint", {
    method: "POST",
    body: JSON.stringify({
      movement_id: movementId, style_id: styleId,
      checkpoint_index: checkpointIndex, landmarks, threshold,
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
