import { useCallback, useEffect, useRef } from "react";
import {
  ContentRect, POSE_CONNECTIONS, contentRect, normToPx, pxToNorm,
} from "../../lib/pose";
import { LM } from "../../lib/audit";

interface Props {
  /** The source <video> this overlay sits on top of (for aspect + size). */
  video: HTMLVideoElement | null;
  landmarks: LM[] | null;
  editable: boolean;
  /** Called with a NEW landmark array whenever the author drags a joint. */
  onChange?: (next: LM[]) => void;
  selected?: number | null;
  onSelect?: (index: number | null) => void;
}

const HANDLE_HIT_PX = 16;

/**
 * Renders the MediaPipe skeleton precisely over the source video. Mapping is
 * strictly non-mirrored (contentRect + normToPx) and uses `contain` so the whole
 * frame — hence every landmark — is visible and auditable. Landmarks are
 * draggable; drag positions round-trip through pxToNorm (exact inverse of the
 * draw mapping), so what the author drops is exactly what gets stored.
 */
export default function SkeletonOverlay({
  video, landmarks, editable, onChange, selected, onSelect,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const lmRef = useRef<LM[] | null>(landmarks);
  const rectRef = useRef<ContentRect | null>(null);
  const dragging = useRef<number | null>(null);
  lmRef.current = landmarks;

  const srcAspect = useCallback(
    () => (video && video.videoWidth ? video.videoWidth / video.videoHeight : 0),
    [video],
  );

  const draw = useCallback(() => {
    const cv = canvasRef.current;
    if (!cv) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    // Keep the canvas bitmap matched to its CSS box (1 CSS px = 1 bitmap px).
    if (cv.width !== cv.clientWidth) cv.width = cv.clientWidth;
    if (cv.height !== cv.clientHeight) cv.height = cv.clientHeight;
    ctx.clearRect(0, 0, cv.width, cv.height);

    const lms = lmRef.current;
    const asp = srcAspect();
    if (!lms || lms.length < 33 || !asp) return;
    const rect = contentRect(cv.width, cv.height, asp, "contain");
    rectRef.current = rect;
    const px = lms.map((p) => normToPx(p.x, p.y, rect));

    // bones
    ctx.lineWidth = Math.max(2, cv.width * 0.005);
    ctx.lineCap = "round";
    ctx.strokeStyle = "rgba(90,200,255,0.95)";
    ctx.shadowColor = "#5ac8ff";
    ctx.shadowBlur = 6;
    for (const [a, b] of POSE_CONNECTIONS) {
      ctx.beginPath();
      ctx.moveTo(px[a][0], px[a][1]);
      ctx.lineTo(px[b][0], px[b][1]);
      ctx.stroke();
    }
    ctx.shadowBlur = 0;

    // joints (draggable handles when editable)
    const r = Math.max(3, cv.width * 0.008);
    for (let i = 0; i < px.length; i++) {
      const isSel = selected === i;
      ctx.beginPath();
      ctx.arc(px[i][0], px[i][1], isSel ? r * 1.7 : r, 0, Math.PI * 2);
      ctx.fillStyle = isSel ? "#ffd23f" : editable ? "#2ecc71" : "rgba(120,220,255,0.9)";
      ctx.fill();
      if (isSel) {
        ctx.lineWidth = 2; ctx.strokeStyle = "#000"; ctx.stroke();
      }
    }
  }, [srcAspect, editable, selected]);

  // Redraw when inputs change, and keep synced to element resizes.
  useEffect(() => { draw(); }, [draw, landmarks]);
  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv) return;
    const ro = new ResizeObserver(() => draw());
    ro.observe(cv);
    return () => ro.disconnect();
  }, [draw]);

  // --- pointer editing ------------------------------------------------------
  const localPx = (e: React.PointerEvent): [number, number] => {
    const cv = canvasRef.current!;
    const b = cv.getBoundingClientRect();
    return [e.clientX - b.left, e.clientY - b.top];
  };

  const hitTest = (mx: number, my: number): number | null => {
    const lms = lmRef.current, rect = rectRef.current;
    if (!lms || !rect) return null;
    let best = -1, bestD = HANDLE_HIT_PX;
    for (let i = 0; i < lms.length; i++) {
      const [x, y] = normToPx(lms[i].x, lms[i].y, rect);
      const d = Math.hypot(x - mx, y - my);
      if (d < bestD) { bestD = d; best = i; }
    }
    return best >= 0 ? best : null;
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (!editable) return;
    const [mx, my] = localPx(e);
    const hit = hitTest(mx, my);
    onSelect?.(hit);
    if (hit !== null) {
      dragging.current = hit;
      canvasRef.current?.setPointerCapture(e.pointerId);
    }
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!editable || dragging.current === null) return;
    const lms = lmRef.current, rect = rectRef.current;
    if (!lms || !rect) return;
    const [mx, my] = localPx(e);
    const [nx, ny] = pxToNorm(mx, my, rect);
    const next = lms.map((p, i) =>
      i === dragging.current ? { ...p, x: nx, y: ny, visibility: 1 } : p);
    onChange?.(next);
  };

  const endDrag = (e: React.PointerEvent) => {
    if (dragging.current !== null) {
      canvasRef.current?.releasePointerCapture(e.pointerId);
      dragging.current = null;
    }
  };

  return (
    <canvas
      ref={canvasRef}
      className="author-overlay"
      style={{ touchAction: "none", cursor: editable ? "crosshair" : "default" }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
    />
  );
}
