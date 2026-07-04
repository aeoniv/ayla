import { useEffect, useState } from "react";
import {
  Catalog, CourseMember, createAvatar, createMovement, createStyle, createVariant,
  getCatalog, getCourseMembers, getRevenue, Revenue,
} from "../api/client";
import { BackIcon, EyeIcon, TargetIcon, UnlockIcon, UsersIcon } from "../components/icons";

// Phase 7 — owner-only content + earnings management.
export default function Admin(
  { onExit, onOpenAuthor }: {
    onExit: () => void;
    onOpenAuthor?: (movementId?: string) => void;
  },
) {
  const [cat, setCat] = useState<Catalog | null>(null);
  const [rev, setRev] = useState<Revenue | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const refresh = () => {
    getCatalog().then(setCat).catch((e) => setMsg("catalog: " + e));
    getRevenue().then(setRev).catch(() => {});
  };
  useEffect(refresh, []);

  async function run(label: string, fn: () => Promise<unknown>) {
    setBusy(true); setMsg(null);
    try { await fn(); setMsg(label + " ✓"); refresh(); }
    catch (e) { setMsg(label + " failed: " + e); }
    finally { setBusy(false); }
  }

  return (
    <div className="admin">
      <div className="admin-top">
        <button className="exit" onClick={onExit}><BackIcon /></button>
        <h2>Courses</h2>
        {onOpenAuthor && (
          <button className="admin-author-btn" onClick={() => onOpenAuthor()}>Studio</button>
        )}
      </div>

      {/* Earnings */}
      <section className="earn">
        <h4>Earnings (Telegram Stars) ✦</h4>
        <p className="big">⭐ {rev?.balance_stars ?? 0}<span className="sub"> balance</span></p>
        <p className="sub">
          Est. from sales: ⭐{cat?.total_est_stars ?? 0} · Withdraw via Fragment (TON).
        </p>
        <p className="sub" style={{ color: "#ffd23f", fontSize: 11 }}>
          Last refreshed: {new Date().toLocaleTimeString()}
        </p>
      </section>

      {msg && <p className="admin-msg">{msg}</p>}

      {/* Courses: per course — Studio (authoring) + Members (learner progress) */}
      <section>
        <h4>Courses ({cat?.movements.length ?? 0})</h4>
        {cat?.movements.map((m) => (
          <div className="mv" key={m.movement_id}>
            <div className="mv-head">
              <b>{m.name}</b><span className="tag">{m.style_name} · ⭐{m.price_stars}</span>
            </div>
            <div className="stat">
              <span className="stat-i"><EyeIcon /> {m.views}</span>
              <span className="stat-i"><TargetIcon /> {m.attempts}</span>
              <span className="stat-i"><UnlockIcon /> {m.unlocks}</span>
              <span className="stat-i">⭐{m.est_stars}</span>
            </div>
            {m.variants.map((v) => (
              <div className="var" key={v.variant_id}>
                ↳ {v.avatar_name} · ⭐{v.price_stars} · 🔓{v.unlocks} · ⭐{v.est_stars}
              </div>
            ))}
            <div className="mv-actions">
              {onOpenAuthor && (
                <button className="mini" onClick={() => onOpenAuthor(m.movement_id)}>
                  Studio
                </button>
              )}
              <MembersPanel movementId={m.movement_id} />
              <AddVariant movementId={m.movement_id} cat={cat!} busy={busy}
                onAdd={(d) => run("variant", () => createVariant(d))} primary />
            </div>
          </div>
        ))}
      </section>

      {/* Create style */}
      <NewStyle busy={busy} onAdd={(name) => run("style", () => createStyle(name))} />
      {/* Create avatar */}
      {cat && <NewAvatar cat={cat} busy={busy}
        onAdd={(name, styleId) => run("avatar", () => createAvatar(name, styleId))} />}
      {/* Create movement — supports both manual timestamps and studio authoring */}
      {cat && (
        <NewMovement
          cat={cat}
          busy={busy}
          onAdd={async (d) => {
            setBusy(true); setMsg(null);
            try {
              const result = await createMovement(d);
              setMsg(`movement created ✓ (${result.reference_status === "pending"
                ? "open Studio to author checkpoints"
                : `${result.checkpoint_count} checkpoints auto-extracted`})`);
              refresh();
              if (result.reference_status === "pending" && onOpenAuthor)
                onOpenAuthor(result.movement_id);
            } catch (e) { setMsg("movement failed: " + e); }
            finally { setBusy(false); }
          }}
        />
      )}
    </div>
  );
}

// Learners enrolled in a course and how far they've come.
function MembersPanel({ movementId }: { movementId: string }) {
  const [open, setOpen] = useState(false);
  const [members, setMembers] = useState<CourseMember[] | null>(null);
  const [err, setErr] = useState(false);

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && members === null) {
      getCourseMembers(movementId)
        .then((r) => setMembers(r.members))
        .catch(() => setErr(true));
    }
  }

  return (
    <>
      <button className="mini" onClick={toggle}>
        <UsersIcon /> Members{members ? ` (${members.length})` : ""}
      </button>
      {open && (
        <div className="members">
          {err && <p className="sub">Couldn’t load members.</p>}
          {members?.length === 0 && <p className="sub">No one has unlocked this course yet.</p>}
          {members?.map((u) => (
            <div className="member-row" key={u.user_id}>
              <span className="member-id">tg:{u.telegram_id ?? "?"}</span>
              <span className="member-progress">
                {u.attempts} attempt{u.attempts === 1 ? "" : "s"}
                {u.best_score !== null && ` · best ${u.best_score}`}
                {u.last_practiced && ` · ${new Date(u.last_practiced).toLocaleDateString()}`}
              </span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function NewStyle({ busy, onAdd }: { busy: boolean; onAdd: (n: string) => void }) {
  const [name, setName] = useState("");
  return (
    <section className="form">
      <h4>New style</h4>
      <input placeholder="e.g. Taichi" value={name} onChange={(e) => setName(e.target.value)} />
      <button disabled={busy || !name} onClick={() => { onAdd(name); setName(""); }}>Add style</button>
    </section>
  );
}

function NewAvatar(
  { cat, busy, onAdd }: { cat: Catalog; busy: boolean; onAdd: (n: string, s: string) => void },
) {
  const [name, setName] = useState("");
  const [style, setStyle] = useState("");
  return (
    <section className="form">
      <h4>New avatar</h4>
      <input placeholder="e.g. Blue Robe" value={name} onChange={(e) => setName(e.target.value)} />
      <select value={style} onChange={(e) => setStyle(e.target.value)}>
        <option value="">Select style…</option>
        {cat.styles.map((s) => <option key={s.style_id} value={s.style_id}>{s.name}</option>)}
      </select>
      <button disabled={busy || !name || !style}
        onClick={() => { onAdd(name, style); setName(""); }}>Add avatar</button>
    </section>
  );
}

type AuthorMode = "manual" | "studio";

function NewMovement(
  { cat, busy, onAdd }: {
    cat: Catalog; busy: boolean;
    onAdd: (d: { name: string; description: string; styleId: string; priceStars: number; checkpoints?: number[]; teaser: File; full: File }) => void;
  },
) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [style, setStyle] = useState("");
  const [price, setPrice] = useState(50);
  const [mode, setMode] = useState<AuthorMode>("studio");
  const [checkpoints, setCheckpoints] = useState("2,5,9,13");
  const [teaser, setTeaser] = useState<File | null>(null);
  const [full, setFull] = useState<File | null>(null);
  const ready = name && style && teaser && full;

  const submit = () => {
    const base = { name, description, styleId: style, priceStars: price, teaser: teaser!, full: full! };
    if (mode === "manual") {
      const parsed = checkpoints.split(",").map((x) => parseFloat(x.trim())).filter((x) => !isNaN(x));
      onAdd({ ...base, checkpoints: parsed });
    } else {
      onAdd(base); // no checkpoints → backend skips auto-authoring → Studio opens
    }
  };

  return (
    <section className="form">
      <h4>New movement</h4>
      <input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
      <input placeholder="Short description" value={description} onChange={(e) => setDescription(e.target.value)} />
      <select value={style} onChange={(e) => setStyle(e.target.value)}>
        <option value="">Select style…</option>
        {cat.styles.map((s) => <option key={s.style_id} value={s.style_id}>{s.name}</option>)}
      </select>
      <label>Price ⭐<input type="number" value={price} onChange={(e) => setPrice(+e.target.value)} /></label>

      <label>Teaser (≤12s)<input type="file" accept="video/*" onChange={(e) => setTeaser(e.target.files?.[0] ?? null)} /></label>
      <label>Full video<input type="file" accept="video/*" onChange={(e) => setFull(e.target.files?.[0] ?? null)} /></label>

      {/* Authoring mode toggle */}
      <div className="mode-toggle">
        <button
          className={`mode-btn${mode === "studio" ? " active" : ""}`}
          onClick={() => setMode("studio")}
          type="button"
        >
          Studio authoring
        </button>
        <button
          className={`mode-btn${mode === "manual" ? " active" : ""}`}
          onClick={() => setMode("manual")}
          type="button"
        >
          Manual timestamps
        </button>
      </div>

      {mode === "manual" ? (
        <div className="mode-detail">
          <p className="mode-hint">Enter checkpoint times in seconds, comma-separated. MediaPipe will extract the pose at each timestamp automatically.</p>
          <label>Checkpoints (s)<input value={checkpoints} onChange={(e) => setCheckpoints(e.target.value)} placeholder="2,5,9,13" /></label>
        </div>
      ) : (
        <div className="mode-detail">
          <p className="mode-hint">After upload the Studio will open so you can mark checkpoints frame-by-frame and audit every pose before saving.</p>
        </div>
      )}

      <button className="publish-btn" disabled={busy || !ready} onClick={submit}>
        {busy ? "Uploading…" : mode === "studio" ? "Upload & open Studio" : "Upload & auto-extract"}
      </button>
    </section>
  );
}

function AddVariant(
  { movementId, cat, busy, onAdd, primary }: {
    movementId: string; cat: Catalog; busy: boolean; primary?: boolean;
    onAdd: (d: { movementId: string; styleId: string; avatarId: string; priceStars: number; teaser: File; full: File }) => void;
  },
) {
  const [open, setOpen] = useState(false);
  const [style, setStyle] = useState("");
  const [avatar, setAvatar] = useState("");
  const [price, setPrice] = useState(20);
  const [teaser, setTeaser] = useState<File | null>(null);
  const [full, setFull] = useState<File | null>(null);
  if (!primary) return null; // only render the add-form once per movement
  if (!open) return <button className="mini" onClick={() => setOpen(true)}>+ variant</button>;
  const ready = style && avatar && teaser && full;
  return (
    <div className="form inline">
      <select value={style} onChange={(e) => setStyle(e.target.value)}>
        <option value="">Style…</option>
        {cat.styles.map((s) => <option key={s.style_id} value={s.style_id}>{s.name}</option>)}
      </select>
      <select value={avatar} onChange={(e) => setAvatar(e.target.value)}>
        <option value="">Avatar…</option>
        {cat.avatars.map((a) => <option key={a.avatar_id} value={a.avatar_id}>{a.name}</option>)}
      </select>
      <label>Price ⭐<input type="number" value={price} onChange={(e) => setPrice(+e.target.value)} /></label>
      <label>Teaser<input type="file" accept="video/*" onChange={(e) => setTeaser(e.target.files?.[0] ?? null)} /></label>
      <label>Full<input type="file" accept="video/*" onChange={(e) => setFull(e.target.files?.[0] ?? null)} /></label>
      <button disabled={busy || !ready} onClick={() => {
        onAdd({ movementId, styleId: style, avatarId: avatar, priceStars: price, teaser: teaser!, full: full! });
        setOpen(false);
      }}>{busy ? "Uploading…" : "Add variant"}</button>
    </div>
  );
}
