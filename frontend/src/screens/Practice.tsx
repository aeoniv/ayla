import { useCallback, useEffect, useRef, useState } from "react";
import {
  CheckpointMeta, CoachResult, coachNext, getCheckpoints, getFullVideo,
  getReference, matchCheckpoint, submitAttempt,
} from "../api/client";
import { Anchor, detect, drawSkeleton, initPose, mirrorPose, skeletonAnchor } from "../lib/pose";

interface Props {
  movementId: string;
  styleId: string;
  onExit: () => void;
}

type Phase = "loading" | "ready" | "playing" | "gating" | "scoring" | "done" | "error";

export default function Practice({ movementId, styleId, onExit }: Props) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [checkpoints, setCheckpoints] = useState<CheckpointMeta[]>([]);
  const [current, setCurrent] = useState(0);
  const [score, setScore] = useState<number | null>(null);
  const [coach, setCoach] = useState<CoachResult | null>(null);
  const [error, setError] = useState("");
  const [align, setAlign] = useState(true);
  const [difficulty, setDifficulty] = useState(70);
  const [debug, setDebug] = useState("");

  const alignRef = useRef(true);
  const thresholdRef = useRef(70);
  const refVideo = useRef<HTMLVideoElement>(null);
  const camVideo = useRef<HTMLVideoElement>(null);
  const overlay = useRef<HTMLCanvasElement>(null);
  const raf = useRef<number | null>(null);
  const latestLm = useRef<number[][] | null>(null);
  const targetLm = useRef<number[][][]>([]);      // reference pose per checkpoint
  const regionScores = useRef<Record<string, number> | undefined>(undefined);
  const phaseRef = useRef<Phase>("loading");
  const currentRef = useRef(0);
  const lastScoreT = useRef(0);
  const lastDbgT = useRef(0);
  const scoring = useRef(false);
  const poseReady = useRef(false);
  const camOk = useRef(false);
  const collected = useRef<{ index: number; landmarks: number[][] }[]>([]);

  useEffect(() => { phaseRef.current = phase; }, [phase]);
  useEffect(() => { currentRef.current = current; }, [current]);
  useEffect(() => { alignRef.current = align; }, [align]);
  useEffect(() => { thresholdRef.current = difficulty; }, [difficulty]);

  const advance = useCallback(() => {
    phaseRef.current = "playing";
    regionScores.current = undefined;
    if (currentRef.current + 1 < checkpoints.length) {
      setCurrent((c) => c + 1); setPhase("playing"); setScore(null);
      refVideo.current?.play().catch(() => {});
    } else { finish(); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [checkpoints.length]);

  async function finish() {
    setPhase("scoring");
    try {
      await submitAttempt(movementId, styleId, collected.current);
      setCoach(await coachNext());
      setPhase("done");
    } catch (e) { setError(String(e)); setPhase("error"); }
  }

  // --- preload (no gesture needed): video src, checkpoints, reference, model -
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [full, cps] = await Promise.all([
          getFullVideo(movementId), getCheckpoints(movementId, styleId),
        ]);
        if (cancelled) return;
        setCheckpoints(cps.checkpoints);
        if (refVideo.current && full.full_url) {
          refVideo.current.src = full.full_url; refVideo.current.load();
        }
        // Target/avatar skeleton is optional — never let it block practice.
        getReference(movementId, styleId)
          .then((ref) => { targetLm.current = ref.checkpoints.map((c) => c.landmarks); })
          .catch(() => {});
        initPose().then(() => { poseReady.current = true; }).catch(() => {});
        setPhase("ready");
        loop(performance.now());
      } catch (e) { setError(String(e)); setPhase("error"); }
    })();

    function loop(t: number) {
      if (cancelled) return;
      const cv = overlay.current, cam = camVideo.current, av = refVideo.current;
      if (cv) {
        if (cv.width !== cv.clientWidth) cv.width = cv.clientWidth;
        if (cv.height !== cv.clientHeight) cv.height = cv.clientHeight;
        cv.getContext("2d")?.clearRect(0, 0, cv.width, cv.height);

        const gating = phaseRef.current === "gating";

        // 1) AVATAR ghost — locked onto the avatar video exactly as it is shown
        // (object-fit:cover, NOT mirrored, NOT re-centered). This overlays the
        // avatar's real body so the authoring can be audited. Shown when paused.
        let anchor: Anchor | null = null;
        const tgt = targetLm.current[currentRef.current];
        const avA = av && av.videoWidth ? av.videoWidth / av.videoHeight : undefined;
        if (gating && tgt && tgt.length >= 33) {
          drawSkeleton(cv, tgt, { fit: "cover", srcAspect: avA, ghost: true, clear: false });
          anchor = skeletonAnchor(cv, tgt, { fit: "cover", srcAspect: avA });
        }

        // 2) The student's live skeleton, snapped onto the avatar's body anchor.
        let lmCount = 0;
        if (poseReady.current && camOk.current && cam && cam.videoWidth > 0) {
          let lm: number[][] | null = null;
          try { lm = detect(cam, t); } catch { /* detector hiccup */ }
          if (lm) {
            // Selfie mirror applied ONCE: same vector drives the drawing, the
            // real-time gate, and the final attempt — so what the user sees and
            // what we score can never disagree.
            const view = mirrorPose(lm);
            latestLm.current = view; lmCount = view.length;
            const camA = cam.videoWidth ? cam.videoWidth / cam.videoHeight : undefined;
            drawSkeleton(cv, view, {
              regionScores: gating ? regionScores.current : undefined, srcAspect: camA,
              alignTo: alignRef.current && anchor ? anchor : undefined,
              matchThreshold: gating ? thresholdRef.current : undefined, clear: false,
            });
          }
        }

        // 3) debug readout (throttled)
        if (t - lastDbgT.current > 400) {
          lastDbgT.current = t;
          setDebug(
            `phase:${phaseRef.current} cam:${camOk.current ? "on" : "off"} ` +
            `camRes:${cam ? cam.videoWidth + "x" + cam.videoHeight : "-"} rs:${cam?.readyState} ` +
            `pose:${poseReady.current} lm:${lmCount} tgt:${(targetLm.current[currentRef.current]?.length ?? 0)} score:${score ?? "-"}`,
          );
        }
      }

      if (phaseRef.current === "gating" && latestLm.current && !scoring.current && t - lastScoreT.current > 350) {
        lastScoreT.current = t; scoring.current = true;
        const idx = currentRef.current, lm = latestLm.current;
        matchCheckpoint(movementId, styleId, idx, lm, thresholdRef.current)
          .then((r) => {
            if (cancelled || phaseRef.current !== "gating") return;
            setScore(r.score); regionScores.current = r.region_scores;
            if (r.matched) { collected.current.push({ index: idx, landmarks: lm }); advance(); }
          })
          .catch(() => {})
          .finally(() => { scoring.current = false; });
      }
      raf.current = requestAnimationFrame(loop);
    }

    return () => {
      cancelled = true;
      if (raf.current) cancelAnimationFrame(raf.current);
      (camVideo.current?.srcObject as MediaStream | null)?.getTracks().forEach((tr) => tr.stop());
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [movementId, styleId]);

  // Begin requires a user gesture (Telegram webview blocks autoplay + camera).
  async function begin() {
    try { await refVideo.current?.play(); } catch { /* keep going */ }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" } });
      if (camVideo.current) { camVideo.current.srcObject = stream; await camVideo.current.play().catch(() => {}); }
      camOk.current = true;
    } catch (e) { camOk.current = false; setDebug("camera denied: " + e); }
    setPhase("playing");
  }

  const onTimeUpdate = useCallback(() => {
    const v = refVideo.current;
    if (!v || phase !== "playing") return;
    const cp = checkpoints[current];
    if (cp && v.currentTime >= cp.timestamp_seconds) {
      v.pause();
      if (camOk.current) setPhase("gating"); // no camera → just keep playing
      else v.play().catch(() => {});
    }
  }, [phase, checkpoints, current]);

  return (
    <div className="practice immersive">
      <button className="exit" onClick={onExit}>✕</button>

      <video ref={refVideo} className="avatar-fs" playsInline muted onTimeUpdate={onTimeUpdate} />
      <canvas ref={overlay} className="pose-overlay" />
      <video ref={camVideo} className="cam-src" playsInline muted />

      {phase === "loading" && <div className="center">Loading avatar & form…</div>}

      {phase === "ready" && (
        <div className="begin-gate">
          <p>The blue skeleton is the avatar's pose — mirror it.<br />Stand back so your whole body fits.</p>
          <button onClick={begin}>▶ Begin practice</button>
          <span className="tiny">Grant camera access when asked</span>
        </div>
      )}

      {(phase === "playing" || phase === "gating") && (
        <>
          <div className="practice-controls">
            <button className={align ? "ctl on" : "ctl"} onClick={() => setAlign((a) => !a)}>
              {align ? "◉ Aligned" : "○ Free"}
            </button>
            <label className="difficulty">
              <span>Easy</span>
              <input type="range" min={45} max={92} value={difficulty} onChange={(e) => setDifficulty(+e.target.value)} />
              <span>Hard</span>
            </label>
          </div>
          <div className="checkpoint-pill">◍ {current + 1} / {checkpoints.length}</div>
        </>
      )}

      {phase === "gating" && (
        <div className="match-meter">
          <div className="mm-track">
            <div className="mm-fill" style={{
              height: `${Math.max(0, Math.min(100, score ?? 0))}%`,
              background: (score ?? 0) >= difficulty ? "#2ecc71" : "#ff4d4d",
            }} />
            <div className="mm-threshold" style={{ bottom: `${difficulty}%` }} />
          </div>
          <div className="mm-num">{score !== null ? Math.round(score) : "—"}</div>
        </div>
      )}

      {debug && <div className="debug-hud">{debug}</div>}

      {phase === "scoring" && <div className="center">Scoring your run…</div>}

      {phase === "done" && coach && (
        <div className="coach">
          <h3>Your coach</h3>
          <p>{coach.note}</p>
          {coach.suggested_next.movement_id && <p className="next">Try next: {coach.suggested_next.movement_id}</p>}
          <button onClick={onExit}>Back to feed</button>
        </div>
      )}

      {phase === "error" && (
        <div className="center">Something went wrong.<br />{error}<button onClick={onExit}>Back</button></div>
      )}
    </div>
  );
}
