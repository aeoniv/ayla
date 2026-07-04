import { useCallback, useEffect, useRef, useState } from "react";
import {
  createInvoice, FeedItem, getVariants, likeMovement,
  postProgress, VariantItem,
} from "../api/client";
import { openInvoice, shareMovement } from "../lib/telegram";
import { HeartIcon, LearnIcon, ShareIcon } from "./icons";

interface Props {
  item: FeedItem;
  active: boolean;
  userId: string;
  onPractice: (movementId: string, styleId: string) => void;
}

// Swipe past this fraction of the card width (or with enough velocity) to advance.
const SWIPE_RATIO = 0.22;

// index 0 = the main movement (its own teaser); 1..n = style variants.
export default function MovementCard({ item, active, userId, onPractice }: Props) {
  const [variants, setVariants] = useState<VariantItem[]>([]);
  const [index, setIndex] = useState(0);
  const [locked, setLocked] = useState(false);            // main-video 12s lock
  const [mainEntitled, setMainEntitled] = useState(item.entitled);
  const [liked, setLiked] = useState(item.liked);
  const [likeCount, setLikeCount] = useState(item.like_count);
  const [drag, setDrag] = useState(0);
  const [dragging, setDragging] = useState(false);
  const videoRefs = useRef<(HTMLVideoElement | null)[]>([]);
  const trackRef = useRef<HTMLDivElement>(null);
  const pollRef = useRef<number | null>(null);
  const startX = useRef(0);
  const startY = useRef(0);
  const startT = useRef(0);
  const axis = useRef<"" | "x" | "y">("");

  const slideCount = variants.length + 1;

  useEffect(() => {
    getVariants(item.movement_id).then(setVariants).catch(() => setVariants([]));
  }, [item.movement_id]);

  const isMain = index === 0;
  const clamp = useCallback(
    (i: number) => Math.max(0, Math.min(slideCount - 1, i)),
    [slideCount],
  );

  // Server-authoritative 12s enforcement — only while previewing the teaser.
  const tick = useCallback(async () => {
    const v = videoRefs.current[0];
    if (!v) return;
    try {
      const p = await postProgress(item.movement_id, null, v.currentTime);
      if (p.locked && !mainEntitled) { v.pause(); setLocked(true); }
    } catch { /* re-checks next tick */ }
  }, [item.movement_id, mainEntitled]);

  useEffect(() => {
    if (!active || !isMain || locked) return;
    pollRef.current = window.setInterval(tick, 1000);
    return () => { if (pollRef.current) window.clearInterval(pollRef.current); };
  }, [active, isMain, locked, tick]);

  // Only the visible slide's video plays; everything else pauses.
  useEffect(() => {
    videoRefs.current.forEach((v, i) => {
      if (!v) return;
      const isCurrent = i === index;
      const playable = i === 0 ? active && !locked : active && variants[i - 1]?.entitled;
      if (isCurrent && playable) v.play().catch(() => {});
      else v.pause();
    });
  }, [active, index, locked, variants]);

  // --- swipe handling -----------------------------------------------------
  function onPointerDown(e: React.PointerEvent) {
    setDragging(true);
    startX.current = e.clientX; startY.current = e.clientY;
    startT.current = Date.now(); axis.current = "";
  }
  function onPointerMove(e: React.PointerEvent) {
    if (!dragging) return;
    let dx = e.clientX - startX.current;
    const dy = e.clientY - startY.current;
    if (!axis.current && Math.hypot(dx, dy) > 8) {
      axis.current = Math.abs(dx) > Math.abs(dy) ? "x" : "y";
    }
    if (axis.current !== "x") return;
    if ((index === 0 && dx > 0) || (index === slideCount - 1 && dx < 0)) dx *= 0.35;
    setDrag(dx);
  }
  function onPointerUp() {
    if (!dragging) return;
    if (axis.current !== "x") { setDragging(false); setDrag(0); return; }
    const width = trackRef.current?.clientWidth ?? window.innerWidth;
    const dt = Date.now() - startT.current;
    const velocity = drag / Math.max(dt, 1);
    if (Math.abs(drag) > width * SWIPE_RATIO || Math.abs(velocity) > 0.5) {
      setIndex((i) => clamp(i + (drag < 0 ? 1 : -1)));
    }
    setDragging(false); setDrag(0);
  }

  async function buyMain(): Promise<boolean> {
    const { invoice_link } = await createInvoice({ movement_id: item.movement_id });
    const status = await openInvoice(invoice_link);
    if (status === "paid") { setMainEntitled(true); setLocked(false); return true; }
    return false;
  }
  async function buyVariant(v: VariantItem) {
    const { invoice_link } = await createInvoice({ variant_id: v.variant_id });
    const status = await openInvoice(invoice_link);
    if (status === "paid") setVariants(await getVariants(item.movement_id));
  }

  // "Learn": buy if needed, then go straight to the full-form screen (which
  // offers guided practice, or paid guidance-skip).
  async function learn() {
    if (!mainEntitled && !(await buyMain())) return;
    onPractice(item.movement_id, item.style_id);
  }

  async function toggleLike() {
    setLiked((l) => !l); setLikeCount((c) => c + (liked ? -1 : 1)); // optimistic
    try { const r = await likeMovement(item.movement_id); setLiked(r.liked); setLikeCount(r.like_count); }
    catch { setLiked(item.liked); setLikeCount(item.like_count); }
  }

  const trackStyle = {
    transform: `translateX(calc(${-index * 100}% + ${drag}px))`,
    transition: dragging ? "none" : "transform 260ms cubic-bezier(.22,.61,.36,1)",
  };
  const slides = [null as VariantItem | null, ...variants];

  return (
    <section className="card">
      <div
        className="swipe-viewport"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        <div className="swipe-track" ref={trackRef} style={trackStyle}>
          {slides.map((v, i) => {
            const main = i === 0;
            const url = main ? item.teaser_url : v?.teaser_url ?? null;
            const blurred = !main && (v?.blurred ?? true);
            const mountVideo = active && url;
            return (
              <div className="swipe-slide" key={main ? "main" : v!.variant_id}>
                <div className="video-wrap">
                  {mountVideo ? (
                    <video
                      ref={(el) => { videoRefs.current[i] = el; }}
                      src={url!}
                      className={blurred ? "video blurred" : "video"}
                      playsInline
                      muted
                      autoPlay={i === index}
                      loop
                      preload="metadata"
                    />
                  ) : (
                    <div className="video placeholder" />
                  )}

                  {main && locked && (
                    <div className="overlay">
                      <p>Free preview ended (12s).</p>
                      <button onClick={buyMain}>Unlock full movement — ⭐{item.price_stars}</button>
                    </div>
                  )}
                  {!main && v && !v.entitled && (
                    <div className="overlay">
                      <p>{item.name} — alternate style</p>
                      <button onClick={() => buyVariant(v)}>Unlock this variant — ⭐{v.price_stars}</button>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {slideCount > 1 && (
          <div className="swipe-dots">
            {Array.from({ length: slideCount }).map((_, i) => (
              <span key={i} className={i === index ? "dot on" : "dot"} />
            ))}
          </div>
        )}

        {/* TikTok-style action rail */}
        <div className="rail">
          <button className={liked ? "rail-btn liked" : "rail-btn"} onClick={toggleLike}>
            <span className="ico"><HeartIcon filled={liked} /></span>
            <span className="lbl">{likeCount}</span>
          </button>
          <button className="rail-btn" onClick={learn}>
            <span className="ico"><LearnIcon /></span>
            <span className="lbl">{mainEntitled ? "Learn" : `⭐${item.price_stars}`}</span>
          </button>
          <button className="rail-btn" onClick={() => shareMovement(item.name, userId)}>
            <span className="ico"><ShareIcon /></span>
            <span className="lbl">Share</span>
          </button>
        </div>

        {/* Title + description overlaid bottom-left */}
        <div className="card-info">
          <h2>{item.name}{!isMain && <span className="variant-tag"> · variant</span>}</h2>
          {item.description && <p className="desc">{item.description}</p>}
        </div>
      </div>
    </section>
  );
}
