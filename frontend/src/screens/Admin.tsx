import { useEffect, useMemo, useState } from "react";
import {
  AdminUser, AdminUserDetail, Catalog, CourseMember, createAvatar, createMovement,
  createStyle, createVariant, getAdminUserDetail, getAdminUsers, getCatalog,
  getCourseMembers, getRevenue, Revenue, uploadVideo,
} from "../api/client";
import {
  BackIcon, EyeIcon, TargetIcon, UnlockIcon, UsersIcon,
} from "../components/icons";

type Tab = "overview" | "studio" | "users";

// Owner dashboard: Overview (KPIs + earnings) / Studio (content) / Users.
export default function Admin(
  { onExit, onOpenAuthor }: {
    onExit: () => void;
    onOpenAuthor?: (movementId?: string) => void;
  },
) {
  const [tab, setTab] = useState<Tab>("overview");
  const [cat, setCat] = useState<Catalog | null>(null);
  const [rev, setRev] = useState<Revenue | null>(null);
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const refresh = () => {
    getCatalog().then(setCat).catch((e) => setMsg("catalog: " + e));
    getRevenue().then(setRev).catch(() => {});
    getAdminUsers().then((r) => setUsers(r.users)).catch(() => {});
  };
  useEffect(refresh, []);

  async function run(label: string, fn: () => Promise<unknown>) {
    setBusy(true); setMsg(null);
    try { await fn(); setMsg(label + " ✓"); refresh(); }
    catch (e) { setMsg(label + " failed: " + e); }
    finally { setBusy(false); }
  }

  return (
    <div className="admin pro">
      <div className="admin-top">
        <button className="exit" onClick={onExit}><BackIcon /></button>
        <h2>Dashboard</h2>
      </div>

      <nav className="admin-tabs">
        {(["overview", "studio", "users"] as Tab[]).map((t) => (
          <button key={t} className={tab === t ? "atab on" : "atab"} onClick={() => setTab(t)}>
            {t === "overview" ? "Overview" : t === "studio" ? "Studio" : "Users"}
          </button>
        ))}
      </nav>

      {msg && <p className="admin-msg">{msg}</p>}

      {tab === "overview" && <OverviewTab cat={cat} rev={rev} users={users} onOpenAuthor={onOpenAuthor} />}
      {tab === "studio" && (
        <StudioTab
          cat={cat} busy={busy} onOpenAuthor={onOpenAuthor} run={run}
          setBusy={setBusy} setMsg={setMsg} refresh={refresh}
        />
      )}
      {tab === "users" && <UsersTab users={users} />}
    </div>
  );
}

// --- Overview ---------------------------------------------------------------

function OverviewTab(
  { cat, rev, users, onOpenAuthor }: {
    cat: Catalog | null; rev: Revenue | null; users: AdminUser[] | null;
    onOpenAuthor?: (movementId?: string) => void;
  },
) {
  const k = useMemo(() => {
    const mvs = cat?.movements ?? [];
    return {
      courses: mvs.length,
      views: mvs.reduce((s, m) => s + m.views, 0),
      attempts: mvs.reduce((s, m) => s + m.attempts, 0),
      unlocks: mvs.reduce((s, m) => s + m.unlocks, 0),
      pending: mvs.filter((m) => m.reference_status === "pending"),
      activeUsers: (users ?? []).filter((u) => u.attempts > 0).length,
    };
  }, [cat, users]);

  return (
    <>
      <section className="earn card-panel">
        <h4>Earnings</h4>
        <p className="big">⭐ {rev?.balance_stars ?? 0}<span className="sub"> withdrawable balance</span></p>
        <p className="sub">Est. from sales: ⭐{cat?.total_est_stars ?? 0} · withdraw via Fragment (TON)</p>
      </section>

      <section className="kpi-grid">
        <Kpi label="Courses" value={k.courses} />
        <Kpi label="Learners" value={users?.length ?? "—"} />
        <Kpi label="Active" value={k.activeUsers} />
        <Kpi label="Views" value={k.views} />
        <Kpi label="Attempts" value={k.attempts} />
        <Kpi label="Unlocks" value={k.unlocks} />
      </section>

      {k.pending.length > 0 && (
        <section className="card-panel warn">
          <h4>Needs authoring</h4>
          {k.pending.map((m) => (
            <div className="row" key={m.movement_id}>
              <span>{m.name}</span>
              {onOpenAuthor && (
                <button className="mini" onClick={() => onOpenAuthor(m.movement_id)}>Open Studio</button>
              )}
            </div>
          ))}
        </section>
      )}
    </>
  );
}

function Kpi({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="kpi">
      <span className="kpi-v">{value}</span>
      <span className="kpi-l">{label}</span>
    </div>
  );
}

// --- Studio (content management) ---------------------------------------------

function StudioTab(
  { cat, busy, onOpenAuthor, run, setBusy, setMsg, refresh }: {
    cat: Catalog | null; busy: boolean;
    onOpenAuthor?: (movementId?: string) => void;
    run: (label: string, fn: () => Promise<unknown>) => Promise<void>;
    setBusy: (b: boolean) => void; setMsg: (m: string | null) => void; refresh: () => void;
  },
) {
  const [creating, setCreating] = useState(false);

  return (
    <>
      <div className="studio-head">
        <h4>Courses ({cat?.movements.length ?? 0})</h4>
        <button className="mini accent" onClick={() => setCreating((c) => !c)}>
          {creating ? "Close" : "＋ New course"}
        </button>
      </div>

      {creating && cat && (
        <div className="create-stack">
          <NewMovement
            cat={cat}
            busy={busy}
            onAdd={async (d) => {
              setBusy(true); setMsg("uploading videos…");
              try {
                // Videos go straight to GCS (see uploadVideo) — the create call
                // then carries only the object paths, so it can't hit Cloud Run's
                // 32 MiB request cap that broke the old multipart upload.
                const [teaserPath, fullPath] = await Promise.all([
                  uploadVideo("teaser", d.teaser),
                  uploadVideo("full", d.full),
                ]);
                setMsg("creating course…");
                const result = await createMovement({
                  name: d.name, description: d.description, styleId: d.styleId,
                  priceStars: d.priceStars, checkpoints: d.checkpoints,
                  teaserPath, fullPath,
                });
                setMsg(`movement created ✓ (${result.reference_status === "pending"
                  ? "open Studio to author checkpoints"
                  : `${result.checkpoint_count} checkpoints auto-extracted`})`);
                refresh(); setCreating(false);
                if (result.reference_status === "pending" && onOpenAuthor)
                  onOpenAuthor(result.movement_id);
              } catch (e) { setMsg("movement failed: " + e); }
              finally { setBusy(false); }
            }}
          />
          <NewStyle busy={busy} onAdd={(name) => run("style", () => createStyle(name))} />
          <NewAvatar cat={cat} busy={busy}
            onAdd={(name, styleId) => run("avatar", () => createAvatar(name, styleId))} />
        </div>
      )}

      {cat?.movements.map((m) => (
        <div className="mv card-panel" key={m.movement_id}>
          <div className="mv-head">
            <b>{m.name}</b>
            <span className="tag">{m.style_name} · ⭐{m.price_stars}</span>
            {m.reference_status === "pending" && <span className="tag pending">unauthored</span>}
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
              <button className="mini" onClick={() => onOpenAuthor(m.movement_id)}>Studio</button>
            )}
            <MembersPanel movementId={m.movement_id} />
            <AddVariant movementId={m.movement_id} cat={cat!} busy={busy}
              onAdd={(d) => run("variant", async () => {
                const [teaserPath, fullPath] = await Promise.all([
                  uploadVideo("teaser", d.teaser),
                  uploadVideo("full", d.full),
                ]);
                return createVariant({
                  movementId: d.movementId, styleId: d.styleId, avatarId: d.avatarId,
                  priceStars: d.priceStars, teaserPath, fullPath,
                });
              })} primary />
          </div>
        </div>
      ))}
    </>
  );
}

// --- Users -------------------------------------------------------------------

function UsersTab({ users }: { users: AdminUser[] | null }) {
  const [q, setQ] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);

  const filtered = useMemo(() => {
    if (!users) return null;
    const needle = q.trim().toLowerCase();
    if (!needle) return users;
    return users.filter((u) =>
      String(u.telegram_id ?? "").includes(needle) ||
      u.user_id.toLowerCase().includes(needle) ||
      u.role.includes(needle));
  }, [users, q]);

  return (
    <>
      <input
        className="user-search"
        placeholder="Search by telegram id, user id, role…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      {!filtered && <p className="sub">Loading users…</p>}
      {filtered?.length === 0 && <p className="sub">No users match.</p>}
      {filtered?.map((u) => (
        <UserRow key={u.user_id} u={u}
          open={openId === u.user_id}
          onToggle={() => setOpenId(openId === u.user_id ? null : u.user_id)} />
      ))}
    </>
  );
}

function UserRow({ u, open, onToggle }: { u: AdminUser; open: boolean; onToggle: () => void }) {
  const [detail, setDetail] = useState<AdminUserDetail | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    if (open && !detail && !err) {
      getAdminUserDetail(u.user_id).then(setDetail).catch(() => setErr(true));
    }
  }, [open, detail, err, u.user_id]);

  return (
    <div className={open ? "user-card open" : "user-card"}>
      <button className="user-summary" onClick={onToggle}>
        <span className="user-ident">
          <UsersIcon />
          <b>tg:{u.telegram_id ?? "?"}</b>
          {u.role !== "student" && <span className="tag">{u.role}</span>}
          {u.referred_by && <span className="tag ref">referred</span>}
        </span>
        <span className="user-nums">
          <span title="unlocks"><UnlockIcon /> {u.unlocks}</span>
          <span title="attempts"><TargetIcon /> {u.attempts}</span>
          {u.referral_stars > 0 && <span title="earned by sharing">⭐{u.referral_stars}</span>}
        </span>
      </button>
      <div className="user-meta">
        {u.joined && <span>joined {new Date(u.joined).toLocaleDateString()}</span>}
        {u.last_active && <span>· active {new Date(u.last_active).toLocaleDateString()}</span>}
        {u.best_score !== null && <span>· best {u.best_score}</span>}
      </div>

      {open && (
        <div className="user-detail">
          {err && <p className="sub">Couldn’t load detail.</p>}
          {!detail && !err && <p className="sub">Loading…</p>}
          {detail && (
            <>
              <h5>Progress</h5>
              {detail.progress.length === 0 && <p className="sub">No practice yet.</p>}
              {detail.progress.map((p) => (
                <div className="row" key={p.movement_id}>
                  <span>{p.movement_name}</span>
                  <span className="sub">
                    {p.attempts}× · best {p.best_score}
                    {p.last && ` · ${new Date(p.last).toLocaleDateString()}`}
                  </span>
                </div>
              ))}
              <h5>Unlocks</h5>
              {detail.unlocks.length === 0 && <p className="sub">Nothing purchased.</p>}
              {detail.unlocks.map((e, i) => (
                <div className="row" key={i}>
                  <span>{e.movement_name ?? e.variant_id ?? e.movement_id ?? "—"}</span>
                  <span className="tag">{e.scope}</span>
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// --- shared course sub-components ---------------------------------------------

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
      <h4>New course</h4>
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
