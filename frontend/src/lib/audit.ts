// Authoring/audit data model + validity checks.
//
// Design note on scoring (a deliberate correction to the "compare adjusted vs
// raw" idea): the delta between the author's correction and MediaPipe's raw
// estimate does NOT measure pose quality — a perfect raw estimate would need
// zero correction yet is the best possible case. So we keep two SEPARATE
// numbers:
//   • auditScore          — pose VALIDITY/confidence from sanity checks (0..1)
//   • correctionMagnitude — how far the author moved joints from raw (info only)
// A checkpoint is 'Audited' only when it passes validity AND the author confirms.

export interface LM { x: number; y: number; z: number; visibility: number }

export interface AuditedCheckpoint {
  index: number;
  mediaTime: number;              // exact presented-frame time (from rVFC)
  originalCoordinates: LM[];      // raw MediaPipe estimate
  auditedCoordinates: LM[];       // after manual nudges (starts === original)
  auditScore: number;             // 0..1 validity/confidence
  correctionMagnitude: number;    // mean torso-normalized drag from raw
  audited: boolean;               // passed validity AND author-confirmed
}

export const AUDIT_PASS = 0.6;    // validity threshold to allow 'Audited'

// MediaPipe body indices we reason about.
const SHO_L = 11, SHO_R = 12, ELB_L = 13, ELB_R = 14, WRI_L = 15, WRI_R = 16;
const HIP_L = 23, HIP_R = 24, KNE_L = 25, KNE_R = 26, ANK_L = 27, ANK_R = 28;
const CORE = [SHO_L, SHO_R, HIP_L, HIP_R];

const dist = (a: LM, b: LM) => Math.hypot(a.x - b.x, a.y - b.y);
const mid = (a: LM, b: LM): LM => ({
  x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, z: (a.z + b.z) / 2,
  visibility: Math.min(a.visibility, b.visibility),
});

export const toLM = (arr: number[][]): LM[] =>
  arr.map(([x, y, z = 0, v = 1]) => ({ x, y, z, visibility: v }));
export const fromLM = (lms: LM[]): number[][] =>
  lms.map((p) => [p.x, p.y, p.z, p.visibility]);
export const cloneLM = (lms: LM[]): LM[] => lms.map((p) => ({ ...p }));

export const torsoLength = (lms: LM[]): number =>
  dist(mid(lms[SHO_L], lms[SHO_R]), mid(lms[HIP_L], lms[HIP_R]));

export interface Check { name: string; ok: boolean; detail: string }
export interface Validation { auditScore: number; checks: Check[] }

// Key bones and the fraction-of-torso band each should plausibly fall in. Bands
// are lenient on the low end (2D foreshortening legitimately shortens a limb
// pointing at the camera) and mainly catch the HIGH end — a landmark flung far
// away is the signature of a misdetection.
const BONES: { a: number; b: number; lo: number; hi: number; label: string }[] = [
  { a: SHO_L, b: ELB_L, lo: 0.1, hi: 1.4, label: "L upper arm" },
  { a: SHO_R, b: ELB_R, lo: 0.1, hi: 1.4, label: "R upper arm" },
  { a: ELB_L, b: WRI_L, lo: 0.1, hi: 1.4, label: "L forearm" },
  { a: ELB_R, b: WRI_R, lo: 0.1, hi: 1.4, label: "R forearm" },
  { a: HIP_L, b: KNE_L, lo: 0.15, hi: 1.6, label: "L thigh" },
  { a: HIP_R, b: KNE_R, lo: 0.15, hi: 1.6, label: "R thigh" },
  { a: KNE_L, b: ANK_L, lo: 0.15, hi: 1.6, label: "L shin" },
  { a: KNE_R, b: ANK_R, lo: 0.15, hi: 1.6, label: "R shin" },
];

// Symmetric bone pairs (left, right) — weak signal (foreshortening breaks it),
// low weight, loose threshold.
const SYM: [number, number, number, number][] = [
  [SHO_L, ELB_L, SHO_R, ELB_R],
  [ELB_L, WRI_L, ELB_R, WRI_R],
  [HIP_L, KNE_L, HIP_R, KNE_R],
  [KNE_L, ANK_L, KNE_R, ANK_R],
];

/**
 * Sanity-check a pose and produce a 0..1 validity score plus human-readable
 * flags. Catches the real failure modes: missing joints, degenerate torso,
 * landmarks flung out of the body, invisible core joints.
 */
export function validatePose(lms: LM[]): Validation {
  const checks: Check[] = [];
  if (!lms || lms.length < 33) {
    return { auditScore: 0, checks: [{ name: "completeness", ok: false, detail: "missing landmarks" }] };
  }
  const torso = torsoLength(lms);

  // 1) finite + non-degenerate torso
  const finite = lms.every((p) => Number.isFinite(p.x) && Number.isFinite(p.y)) && torso > 1e-3;
  checks.push({ name: "geometry", ok: finite, detail: finite ? "torso ok" : "degenerate/NaN" });
  if (!finite) return { auditScore: 0, checks };

  // 2) proportion: bones within plausible fraction of torso. A bone LONGER than
  // its high band is a flung landmark — the signature of a misdetection — and is
  // treated as a hard failure that caps the whole score, forcing a correction.
  let flung = 0;
  const bad = BONES.filter((bn) => {
    const r = dist(lms[bn.a], lms[bn.b]) / torso;
    if (r > bn.hi) flung++;
    return r < bn.lo || r > bn.hi;
  });
  const proportion = 1 - bad.length / BONES.length;
  checks.push({
    name: "proportion", ok: bad.length === 0,
    detail: bad.length
      ? `out of range: ${bad.map((b) => b.label).join(", ")}${flung ? " (flung)" : ""}`
      : "limbs plausible",
  });

  // 3) visibility of core joints
  const vis = CORE.reduce((s, i) => s + (lms[i].visibility ?? 1), 0) / CORE.length;
  checks.push({ name: "visibility", ok: vis >= 0.5, detail: `core visibility ${vis.toFixed(2)}` });

  // 4) symmetry (weak): mean min/max ratio across symmetric pairs
  let symSum = 0;
  for (const [a, b, c, d] of SYM) {
    const l = dist(lms[a], lms[b]), r = dist(lms[c], lms[d]);
    symSum += Math.min(l, r) / (Math.max(l, r) || 1);
  }
  const symmetry = symSum / SYM.length;
  checks.push({ name: "symmetry", ok: symmetry >= 0.5, detail: `L/R ratio ${symmetry.toFixed(2)}` });

  let auditScore =
    0.15 /* finite base */ +
    0.40 * proportion +
    0.35 * Math.min(1, vis) +
    0.10 * symmetry;
  // A flung landmark must drop below the pass line so it can't be audited as-is.
  if (flung > 0) auditScore = Math.min(auditScore, AUDIT_PASS - 0.15);

  return { auditScore: Math.max(0, Math.min(1, auditScore)), checks };
}

/**
 * How far (mean, torso-normalized) the audited pose was moved from the raw
 * estimate. Informational only — never gates 'Audited'.
 */
export function correctionMagnitude(original: LM[], audited: LM[]): number {
  const torso = torsoLength(audited) || 1;
  let sum = 0;
  const n = Math.min(original.length, audited.length);
  for (let i = 0; i < n; i++) sum += dist(original[i], audited[i]);
  return sum / n / torso;
}

/** Recompute derived fields after an edit; returns a new checkpoint object. */
export function reaudit(cp: AuditedCheckpoint): AuditedCheckpoint {
  const { auditScore } = validatePose(cp.auditedCoordinates);
  const correctionMagnitude = correctionMagnitude_(cp);
  return { ...cp, auditScore, correctionMagnitude };
}
const correctionMagnitude_ = (cp: AuditedCheckpoint) =>
  correctionMagnitude(cp.originalCoordinates, cp.auditedCoordinates);
