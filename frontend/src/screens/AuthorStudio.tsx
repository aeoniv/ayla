import { useCallback, useEffect, useRef, useState } from "react";
import SkeletonOverlay from "../components/authoring/SkeletonOverlay";
import TimelineEditor from "../components/authoring/TimelineEditor";
import { detect, initPose } from "../lib/pose";
import { measureFps, seekTo, seekToFrame, stepFrame } from "../lib/video";
import {
  AUDIT_PASS, AuditedCheckpoint, LM, cloneLM, correctionMagnitude,
  fromLM, toLM, validatePose,
} from "../lib/audit";
import { CatMovement, getCatalog, getFullVideo, saveAuditedReference } from "../api/client";

const GUIDE_STEPS = [
  "1. Pick a movement (or upload a video file) to load it.",
  "2. Play or scrub to a key pose — a moment students must hold.",
  "3. Hit \"＋ Pose marker\" to capture the pose at that exact frame.",
  "4. Drag any joint on the skeleton to fix MediaPipe errors, then \"Mark audited\".",
  "5. Repeat for every checkpoint, then \"Save reference\".",
];

interface Props {
  movementId?: string;
  styleId?: string;
  src?: string;            // direct video URL (else the picker/selector is used)
  onExit?: () => void;
}

/**
 * Timeline authoring & auditing studio. The whole point is precision: frames are
 * stepped on the fps grid via requestVideoFrameCallback, MediaPipe runs on the
 * exact painted frame, the overlay maps non-mirrored onto the source video, and
 * every landmark is hand-correctable before a checkpoint is marked 'Audited'.
 */
export default function AuthorStudio({ movementId, styleId, src, onExit }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [ready, setReady] = useState(false);
  const [fps, setFps] = useState(30);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [checkpoints, setCheckpoints] = useState<AuditedCheckpoint[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [busy, setBusy] = useState("");
  const [saved, setSaved] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [showGuide, setShowGuide] = useState(true);
  const [movements, setMovements] = useState<CatMovement[]>([]);
  const [boundMovement, setBoundMovement] = useState(movementId ?? "");
  const [boundStyle, setBoundStyle] = useState(styleId ?? "");
  const nextId = useRef(0);

  const sel = checkpoints.find((c) => c.index === selected) ?? null;

  // Load the pose model once.
  useEffect(() => { initPose().then(() => setReady(true)).catch(() => setReady(true)); }, []);

  // If no movement was passed in, offer the owner's catalog to pick from.
  useEffect(() => {
    if (movementId || src) return;
    getCatalog().then((c) => setMovements(c.movements)).catch(() => {});
  }, [movementId, src]);

  // Bind a movement: its /full response carries both the style_id and the video.
  const bindMovement = useCallback(async (mid: string) => {
    if (!mid) return;
    setBusy("loading video…");
    try {
      const full = await getFullVideo(mid);
      setBoundMovement(mid);
      setBoundStyle(full.style_id);
      if (videoRef.current && full.full_url) videoRef.current.src = full.full_url;
      setCheckpoints([]); setSelected(null); setSaved(false); setBusy("");
    } catch (e) { setBusy("could not load movement: " + String(e)); }
  }, []);

  const onLoaded = useCallback(async () => {
    const v = videoRef.current;
    if (!v) return;
    setDuration(v.duration || 0);
    // measureFps briefly plays the video to sample two frames — give the buffer
    // a moment to arrive first, especially for long GCS-signed URLs.
    await new Promise((r) => setTimeout(r, 200));
    setFps(await measureFps(v));
  }, []);

  const togglePlay = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) { v.play().then(() => setPlaying(true)).catch(() => {}); }
    else { v.pause(); setPlaying(false); }
  }, []);

  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f || !videoRef.current) return;
    setPlaying(false);
    setCheckpoints([]); setSelected(null); setSaved(false); setBusy("");
    videoRef.current.src = URL.createObjectURL(f);
  };

  // --- timeline actions -----------------------------------------------------
  const onScrub = useCallback(async (t: number) => {
    const v = videoRef.current; if (!v) return;
    await seekTo(v, t);
    setCurrentTime(v.currentTime);
    setSelected(null); // scrubbing off a marker clears the editable overlay
  }, []);

  const onStepFrame = useCallback(async (dir: 1 | -1) => {
    const v = videoRef.current; if (!v) return;
    const fi = await stepFrame(v, dir, fps);
    setCurrentTime(fi.mediaTime);
  }, [fps]);

  const detectHere = useCallback((): LM[] | null => {
    const v = videoRef.current; if (!v) return null;
    const raw = detect(v, performance.now());
    return raw ? toLM(raw) : null;
  }, []);

  const onAddMarker = useCallback(async () => {
    const v = videoRef.current; if (!v) return;
    setBusy("detecting…");
    const fi = await seekToFrame(v, v.currentTime);  // guarantee frame is painted
    const lms = detectHere();
    setBusy("");
    if (!lms) { setBusy("no pose detected on this frame"); return; }
    const original = lms;
    const audited = cloneLM(lms);
    const cp: AuditedCheckpoint = {
      index: nextId.current++,
      mediaTime: fi.mediaTime,
      originalCoordinates: original,
      auditedCoordinates: audited,
      auditScore: validatePose(audited).auditScore,
      correctionMagnitude: 0,
      audited: false,
    };
    setCheckpoints((cs) => [...cs, cp]);
    setSelected(cp.index);
    setCurrentTime(fi.mediaTime);
    setSaved(false);
  }, [detectHere]);

  const onJumpMarker = useCallback(async (id: number) => {
    const v = videoRef.current; if (!v) return;
    const cp = checkpoints.find((c) => c.index === id);
    if (!cp) return;
    await seekTo(v, cp.mediaTime);
    setCurrentTime(v.currentTime);
    setSelected(id);
  }, [checkpoints]);

  const onRemoveMarker = useCallback((id: number) => {
    setCheckpoints((cs) => cs.filter((c) => c.index !== id));
    setSelected(null);
    setSaved(false);
  }, []);

  // Live edit from the overlay drag.
  const onOverlayChange = useCallback((next: LM[]) => {
    if (selected === null) return;
    setCheckpoints((cs) => cs.map((c) => {
      if (c.index !== selected) return c;
      return {
        ...c,
        auditedCoordinates: next,
        auditScore: validatePose(next).auditScore,
        correctionMagnitude: correctionMagnitude(c.originalCoordinates, next),
        audited: false, // any edit invalidates a prior audit stamp
      };
    }));
    setSaved(false);
  }, [selected]);

  const reDetect = useCallback(async () => {
    const v = videoRef.current; if (selected === null || !v) return;
    await seekToFrame(v, sel?.mediaTime ?? v.currentTime);
    const lms = detectHere();
    if (!lms) return;
    setCheckpoints((cs) => cs.map((c) => c.index === selected
      ? { ...c, originalCoordinates: lms, auditedCoordinates: cloneLM(lms),
          auditScore: validatePose(lms).auditScore, correctionMagnitude: 0, audited: false }
      : c));
  }, [selected, sel, detectHere]);

  const markAudited = useCallback(() => {
    if (selected === null) return;
    setCheckpoints((cs) => cs.map((c) =>
      c.index === selected && c.auditScore >= AUDIT_PASS ? { ...c, audited: true } : c));
  }, [selected]);

  const save = useCallback(async () => {
    if (!boundMovement || !boundStyle) { setBusy("pick a movement first — cannot save"); return; }
    const ordered = [...checkpoints].sort((a, b) => a.mediaTime - b.mediaTime);
    if (!ordered.length) { setBusy("add at least one checkpoint"); return; }
    if (!ordered.every((c) => c.audited)) { setBusy("audit every checkpoint before saving"); return; }
    setBusy("saving…");
    try {
      await saveAuditedReference(boundMovement, boundStyle, ordered.map((c, i) => ({
        index: i,
        timestamp_seconds: c.mediaTime,
        landmarks: fromLM(c.auditedCoordinates),
        original_landmarks: fromLM(c.originalCoordinates),
        audit_score: c.auditScore,
        correction_magnitude: c.correctionMagnitude,
      })));
      setBusy(""); setSaved(true);
    } catch (e) { setBusy("save failed: " + String(e)); }
  }, [boundMovement, boundStyle, checkpoints]);

  // Direct src (prop) or a movement passed in — load on mount.
  useEffect(() => { if (src && videoRef.current) videoRef.current.src = src; }, [src]);
  useEffect(() => { if (movementId && !src) bindMovement(movementId); }, [movementId, src, bindMovement]);

  const validation = sel ? validatePose(sel.auditedCoordinates) : null;
  const markers = checkpoints.map((c) => ({ index: c.index, mediaTime: c.mediaTime, audited: c.audited }));

  const orderedIdx = sel
    ? [...checkpoints].sort((a, b) => a.mediaTime - b.mediaTime).findIndex((c) => c.index === sel.index) + 1
    : 0;

  return (
    <div className="author-studio">

      {/* ── top bar ── */}
      <div className="author-top">
        {onExit && <button className="exit" onClick={onExit}>✕</button>}
        <div className="author-title">
          <span className="author-title-main">Authoring studio</span>
          <span className="author-title-sub">Mark pose checkpoints → audit → save reference</span>
        </div>
        <button
          className="author-guide-toggle"
          onClick={() => setShowGuide((v) => !v)}
          title="How to use"
        >?</button>
      </div>

      {/* ── how-to guide ── */}
      {showGuide && (
        <div className="author-guide">
          {GUIDE_STEPS.map((s) => <p key={s}>{s}</p>)}
          <button className="author-guide-close" onClick={() => setShowGuide(false)}>Got it</button>
        </div>
      )}

      {/* ── movement / file picker (only shown when not pre-bound) ── */}
      {(!src || !movementId) && (
        <div className="author-picker">
          {!src && !movementId && movements.length > 0 && (
            <label className="author-picker-label">
              Movement
              <select value={boundMovement} onChange={(e) => bindMovement(e.target.value)}>
                <option value="">— pick one —</option>
                {movements.map((m) => (
                  <option key={m.movement_id} value={m.movement_id}>{m.name}</option>
                ))}
              </select>
            </label>
          )}
          {!src && (
            <label className="author-picker-label author-file-label">
              Or upload video
              <input type="file" accept="video/*" onChange={onFile} />
            </label>
          )}
          {boundMovement && (
            <span className="author-bound-id">id: {boundMovement}</span>
          )}
        </div>
      )}

      {/* ── video + skeleton overlay ── */}
      <div className="author-stage">
        <video
          ref={videoRef}
          className="author-video"
          playsInline
          preload="metadata"
          onLoadedMetadata={onLoaded}
          onTimeUpdate={() => setCurrentTime(videoRef.current?.currentTime ?? 0)}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onEnded={() => setPlaying(false)}
        />
        <SkeletonOverlay
          video={videoRef.current}
          landmarks={sel ? sel.auditedCoordinates : null}
          editable={selected !== null}
          onChange={onOverlayChange}
          selected={null}
        />
        {!ready && (
          <div className="author-stage-overlay">Loading pose model…</div>
        )}
      </div>

      {/* ── timeline + playback controls ── */}
      <TimelineEditor
        duration={duration}
        currentTime={currentTime}
        fps={fps}
        markers={markers}
        selected={selected}
        playing={playing}
        onTogglePlay={togglePlay}
        onScrub={onScrub}
        onStepFrame={onStepFrame}
        onAddMarker={onAddMarker}
        onJumpMarker={onJumpMarker}
        onRemoveMarker={onRemoveMarker}
      />

      {/* ── bottom panel: status + audit card + save ── */}
      <div className="author-panel">
        {busy && <p className="author-busy">{busy}</p>}

        {sel && validation ? (
          <div className="audit-card">
            <div className="audit-head">
              <b>Checkpoint {orderedIdx} — audit skeleton</b>
              <span className={`audit-score ${sel.auditScore >= AUDIT_PASS ? "ok" : "bad"}`}>
                validity {(sel.auditScore * 100).toFixed(0)}%
              </span>
              <span className="audit-corr">Δ {(sel.correctionMagnitude * 100).toFixed(0)}%</span>
            </div>
            <p className="audit-hint" style={{ marginTop: 4 }}>
              Drag any joint on the skeleton above to correct MediaPipe. Editing reopens the audit.
            </p>
            <ul className="audit-checks">
              {validation.checks.map((c) => (
                <li key={c.name} className={c.ok ? "ok" : "bad"}>
                  {c.ok ? "✓" : "✕"} {c.name}: {c.detail}
                </li>
              ))}
            </ul>
            <div className="audit-actions">
              <button onClick={reDetect}>↺ Re-detect</button>
              <button
                className="audit-confirm"
                disabled={sel.auditScore < AUDIT_PASS}
                onClick={markAudited}
              >
                {sel.audited ? "✓ Audited" : "Mark audited"}
              </button>
            </div>
          </div>
        ) : (
          <p className="author-idle-hint">
            {checkpoints.length === 0
              ? "Play the video, pause on a key pose, then hit \"＋ Pose marker\"."
              : "Click a marker on the timeline to audit it."}
          </p>
        )}

        <div className="author-save">
          <span className="author-save-count">
            {checkpoints.filter((c) => c.audited).length}/{checkpoints.length} checkpoints audited
          </span>
          <button
            className="author-save-btn"
            onClick={save}
            disabled={!checkpoints.length || checkpoints.some((c) => !c.audited)}
          >
            Save reference
          </button>
          {saved && <span className="ok">Saved ✓</span>}
        </div>
      </div>
    </div>
  );
}
