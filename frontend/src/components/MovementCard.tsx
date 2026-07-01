import { useCallback, useEffect, useRef, useState } from "react";
import {
  createInvoice, FeedItem, getVariants, postProgress, VariantItem,
} from "../api/client";
import { openInvoice } from "../lib/telegram";

interface Props {
  item: FeedItem;
  active: boolean;
  onPractice: (movementId: string, styleId: string) => void;
}

// index 0 = the main movement (its own teaser); 1..n = style variants.
export default function MovementCard({ item, active, onPractice }: Props) {
  const [variants, setVariants] = useState<VariantItem[]>([]);
  const [index, setIndex] = useState(0);
  const [locked, setLocked] = useState(false); // main-video 12s lock
  const [mainEntitled, setMainEntitled] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    getVariants(item.movement_id).then(setVariants).catch(() => setVariants([]));
  }, [item.movement_id]);

  const isMain = index === 0;
  const variant = isMain ? null : variants[index - 1];

  // Server-authoritative 12s enforcement for the MAIN video only.
  const tick = useCallback(async () => {
    const v = videoRef.current;
    if (!v) return;
    try {
      const p = await postProgress(item.movement_id, null, v.currentTime);
      if (p.locked && !mainEntitled) {
        v.pause();
        setLocked(true);
      }
    } catch {
      /* ignore transient errors; enforcement re-checks next tick */
    }
  }, [item.movement_id, mainEntitled]);

  useEffect(() => {
    if (!active || !isMain || locked) return;
    pollRef.current = window.setInterval(tick, 1000);
    return () => { if (pollRef.current) window.clearInterval(pollRef.current); };
  }, [active, isMain, locked, tick]);

  // Pause everything when this card scrolls out of view.
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    if (active && !locked && (isMain || variant?.entitled)) v.play().catch(() => {});
    else v.pause();
  }, [active, locked, isMain, variant]);

  async function buyMain() {
    const { invoice_link } = await createInvoice({ movement_id: item.movement_id });
    const status = await openInvoice(invoice_link);
    if (status === "paid") { setMainEntitled(true); setLocked(false); }
  }

  async function buyVariant(v: VariantItem) {
    const { invoice_link } = await createInvoice({ variant_id: v.variant_id });
    const status = await openInvoice(invoice_link);
    if (status === "paid") setVariants(await getVariants(item.movement_id));
  }

  const url = isMain ? item.teaser_url : variant?.teaser_url ?? null;
  // A variant with no entitlement is shown blurred with no playback.
  const blurred = !isMain && (variant?.blurred ?? true);

  return (
    <section className="card">
      <div className="video-wrap">
        {url ? (
          <video
            ref={videoRef}
            src={url}
            className={blurred ? "video blurred" : "video"}
            playsInline
            muted
            loop={!isMain}
          />
        ) : (
          <div className="video placeholder" />
        )}

        {/* Main video 12s paywall */}
        {isMain && locked && (
          <div className="overlay">
            <p>Free preview ended (12s).</p>
            <button onClick={buyMain}>Unlock full movement — ⭐{item.price_stars}</button>
          </div>
        )}

        {/* Variant paywall (blurred until bought) */}
        {!isMain && variant && !variant.entitled && (
          <div className="overlay">
            <p>{item.name} — alternate style</p>
            <button onClick={() => buyVariant(variant)}>
              Unlock this variant — ⭐{variant.price_stars}
            </button>
          </div>
        )}
      </div>

      <div className="card-meta">
        <h2>{item.name}</h2>
        <div className="carousel-nav">
          <button disabled={index === 0} onClick={() => setIndex((i) => i - 1)}>‹</button>
          <span>{isMain ? "Original" : `Variant ${index}/${variants.length}`}</span>
          <button
            disabled={index >= variants.length}
            onClick={() => setIndex((i) => i + 1)}
          >›</button>
        </div>
        {isMain && mainEntitled && (
          <button className="practice" onClick={() => onPractice(item.movement_id, item.style_id)}>
            Practice this movement →
          </button>
        )}
      </div>
    </section>
  );
}
