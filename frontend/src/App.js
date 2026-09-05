import { useCallback, useEffect, useMemo, useState } from "react";
import "@/App.css";
import "@/responsive.css";
import {
  BookOpen, CalendarDays, ChevronRight, CircleUserRound, Clock3, FileText, Grid2X2,
  LogIn, Menu, Search, ShieldCheck, Sparkles, Users, X, Trash2, Pencil, PlusCircle,
} from "lucide-react";
import api, { formatError } from "@/lib/api";

const CATEGORY_OPTIONS = ["Semua kategori", "Pendidikan", "Metodologi", "Teknologi", "Sains", "Literasi", "Sosial"];
const initials = (name = "") => name.split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase() || "AN";
const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString("id-ID", { day: "2-digit", month: "short", year: "numeric" }) : "-");

function App() {
  const [page, setPage] = useState("home");
  const [user, setUser] = useState(null);
  const [authChecking, setAuthChecking] = useState(true);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("Semua kategori");
  const [books, setBooks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [showAuth, setShowAuth] = useState(false);
  const [authMode, setAuthMode] = useState("login");
  const [mobileNav, setMobileNav] = useState(false);
  const [toast, setToast] = useState(null);

  const notify = useCallback((msg, kind = "info") => {
    setToast({ msg, kind });
    setTimeout(() => setToast(null), 3500);
  }, []);

  const refreshMe = useCallback(async () => {
    try {
      const u = await api.me();
      setUser(u);
    } catch {
      setUser(null);
    } finally {
      setAuthChecking(false);
    }
  }, []);

  const refreshBooks = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (query.trim()) params.q = query.trim();
      if (category && category !== "Semua kategori") params.category = category;
      const data = await api.listBooks(params);
      setBooks(data);
    } catch (e) {
      notify(formatError(e), "error");
    } finally {
      setLoading(false);
    }
  }, [query, category, notify]);

  useEffect(() => { refreshMe(); }, [refreshMe]);
  useEffect(() => {
    const t = setTimeout(refreshBooks, 250);
    return () => clearTimeout(t);
  }, [refreshBooks]);

  const navigate = (next) => {
    setPage(next);
    setMobileNav(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const handleAuthSuccess = async () => {
    setShowAuth(false);
    await refreshMe();
    notify("Selamat datang!", "success");
  };

  const handleLogout = async () => {
    try { await api.logout(); } catch {}
    setUser(null);
    navigate("home");
    notify("Anda telah keluar", "info");
  };

  const handleBorrow = async (book) => {
    if (!user) { setAuthMode("login"); setShowAuth(true); return; }
    try {
      const res = await api.borrow(book.id);
      if (res.type === "reservation") {
        notify(`Masuk antrean reservasi (posisi #${res.reservation.position})`, "success");
      } else {
        notify("Peminjaman berhasil. Jatuh tempo 14 hari.", "success");
      }
      setSelected(null);
      refreshBooks();
    } catch (e) {
      notify(formatError(e), "error");
    }
  };

  const featured = useMemo(() => books.filter((b) => b.featured).slice(0, 3), [books]);
  const isAdmin = user?.role === "admin";

  return (
    <div className="app-shell">
      <header className="topbar"><div className="topbar-inner">
        <button className="brand" data-testid="site-brand-button" onClick={() => navigate("home")}>
          <span className="brand-mark"><BookOpen size={20} /></span>
          <span><strong>DigiLib</strong><small>PERPUSTAKAAN DIGITAL</small></span>
        </button>
        <button className="mobile-menu" data-testid="mobile-menu-button" onClick={() => setMobileNav(!mobileNav)}>
          {mobileNav ? <X /> : <Menu />}
        </button>
        <nav className={mobileNav ? "main-nav open" : "main-nav"} data-testid="main-navigation">
          <button className={page === "home" ? "nav-active" : ""} data-testid="nav-home-button" onClick={() => navigate("home")}>Beranda</button>
          <button className={page === "catalog" ? "nav-active" : ""} data-testid="nav-catalog-button" onClick={() => navigate("catalog")}>Katalog</button>
          <button data-testid="nav-repository-button" onClick={() => navigate("catalog")}>Repositori</button>
          <button data-testid="nav-about-button" onClick={() => navigate("home")}>Tentang kami</button>
          {isAdmin && <button className={page === "admin" ? "nav-active" : ""} data-testid="nav-admin-button" onClick={() => navigate("admin")}>Admin</button>}
        </nav>
        <div className="header-actions">
          {authChecking ? null : user ? (
            <button className="profile-chip" data-testid="profile-menu-button" onClick={() => navigate("profile")}>
              <span className="avatar">{initials(user.name)}</span>
              <span>{user.name.split(" ")[0]}</span>
            </button>
          ) : (
            <button className="login-link" data-testid="header-login-button" onClick={() => { setAuthMode("login"); setShowAuth(true); }}>
              <LogIn size={17} /> Masuk
            </button>
          )}
        </div>
      </div></header>

      {page === "home" && <HomePage
        books={books} featured={featured} query={query} setQuery={setQuery}
        onOpen={setSelected} navigate={navigate} onJoin={() => { setAuthMode("register"); setShowAuth(true); }}
      />}

      {page === "catalog" && <CatalogPage
        books={books} loading={loading} query={query} setQuery={setQuery}
        category={category} setCategory={setCategory} onOpen={setSelected} isReal={!!user || true}
      />}

      {page === "profile" && user && <ProfilePage user={user} onLogout={handleLogout} navigate={navigate} notify={notify} />}
      {page === "profile" && !user && <RequireAuth onOpen={() => { setAuthMode("login"); setShowAuth(true); }} />}

      {page === "admin" && isAdmin && <AdminPanel notify={notify} />}

      <footer>
        <div className="footer-brand"><span className="brand-mark"><BookOpen size={18} /></span><strong>DigiLib</strong></div>
        <span>Perpustakaan digital modern — dibangun di atas Emergent</span>
        <span>© 2026 DigiLib</span>
      </footer>

      {selected && <BookDetail
        book={selected}
        onClose={() => setSelected(null)}
        onBorrow={() => handleBorrow(selected)}
        loggedIn={!!user}
      />}

      {showAuth && <AuthModal
        mode={authMode} setMode={setAuthMode}
        onClose={() => setShowAuth(false)}
        onSuccess={handleAuthSuccess}
        notify={notify}
      />}

      {toast && <div className={`toast toast-${toast.kind}`} data-testid="toast-notification">{toast.msg}</div>}
    </div>
  );
}

/* ------------------------------- HOME ------------------------------- */
function HomePage({ books, featured, query, setQuery, onOpen, navigate, onJoin }) {
  return (
    <main>
      <section className="hero">
        <div className="hero-content">
          <div className="eyebrow"><Sparkles size={15} /> RUANG BACA UNTUK SEMUA</div>
          <h1>Temukan ide.<br /><em>Bangun masa depan.</em></h1>
          <p>Jelajahi koleksi buku, skripsi, jurnal, dan karya ilmiah untuk menemani perjalanan belajarmu.</p>
          <div className="hero-search">
            <Search size={20} />
            <input
              data-testid="hero-search-input"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && navigate("catalog")}
              placeholder="Cari judul, penulis, atau topik..."
            />
            <button data-testid="hero-search-button" onClick={() => navigate("catalog")}>Cari koleksi</button>
          </div>
          <div className="search-hint">
            <span>Populer:</span>
            <button data-testid="popular-topic-pendidikan" onClick={() => { setQuery("pendidikan"); navigate("catalog"); }}>Pendidikan</button>
            <button data-testid="popular-topic-teknologi" onClick={() => { setQuery("teknologi"); navigate("catalog"); }}>Teknologi</button>
            <button data-testid="popular-topic-literasi" onClick={() => { setQuery("literasi"); navigate("catalog"); }}>Literasi</button>
          </div>
        </div>
        <div className="hero-art">
          <img src="https://images.unsplash.com/photo-1564910443496-5fd2d76b47fa?auto=format&fit=crop&w=1200&q=85" alt="Interior perpustakaan modern" />
          <div className="hero-stat"><strong>{books.length}</strong><span>koleksi digital tersedia</span></div>
        </div>
      </section>

      <section className="stats-strip">
        <div><strong>{books.length}</strong><span>Total koleksi</span></div>
        <div><strong>{books.reduce((s, b) => s + (b.stock || 0), 0)}</strong><span>Stok tersedia</span></div>
        <div><strong>{books.filter((b) => b.type === "E-Book").length}</strong><span>Judul e-book</span></div>
        <div><strong>98%</strong><span>Kepuasan anggota</span></div>
      </section>

      <section className="section featured-section">
        <div className="section-heading">
          <div><span className="section-kicker">PILIHAN PUSTAKAWAN</span><h2>Koleksi pilihan minggu ini</h2></div>
          <button className="text-link" data-testid="view-all-books-button" onClick={() => navigate("catalog")}>Lihat semua koleksi <ChevronRight size={17} /></button>
        </div>
        <div className="book-grid">
          {featured.map((b) => <BookCard key={b.id} book={b} onOpen={onOpen} />)}
        </div>
      </section>

      <section className="member-banner">
        <div>
          <span className="section-kicker">AKSES LEBIH BANYAK</span>
          <h2>Jadikan membaca<br /><em>sebuah kebiasaan.</em></h2>
          <p>Daftar sebagai anggota untuk meminjam koleksi, menyimpan buku favorit, dan melihat riwayat bacaanmu.</p>
        </div>
        <button data-testid="banner-register-button" onClick={onJoin}>Mulai jadi anggota <ChevronRight size={17} /></button>
      </section>
    </main>
  );
}

/* ----------------------------- CATALOG ----------------------------- */
function CatalogPage({ books, loading, query, setQuery, category, setCategory, onOpen }) {
  return (
    <main className="page-main">
      <div className="page-title">
        <div>
          <span className="section-kicker">KOLEKSI DIGITAL</span>
          <h1>Jelajahi pengetahuan</h1>
          <p>Temukan koleksi yang relevan dengan kebutuhanmu.</p>
        </div>
        <div className="sync-status" data-testid="sync-status"><span></span> Tersinkron dari database DigiLib</div>
      </div>
      <div className="catalog-toolbar">
        <div className="catalog-search">
          <Search size={18} />
          <input
            data-testid="catalog-search-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Cari koleksi..."
          />
        </div>
        <select data-testid="category-filter-select" value={category} onChange={(e) => setCategory(e.target.value)}>
          {CATEGORY_OPTIONS.map((c) => <option key={c}>{c}</option>)}
        </select>
      </div>
      <div className="results-row">
        <span data-testid="catalog-result-count">Menampilkan <strong>{books.length}</strong> koleksi</span>
        <button className="sort-button" data-testid="catalog-sort-button"><Grid2X2 size={16} /> Tampilan grid</button>
      </div>
      {loading ? (
        <div className="empty-state" data-testid="catalog-loading">Memuat koleksi...</div>
      ) : books.length === 0 ? (
        <div className="empty-state" data-testid="catalog-empty-state">Koleksi tidak ditemukan. Coba kata kunci lain.</div>
      ) : (
        <div className="book-grid catalog-grid">
          {books.map((b) => <BookCard key={b.id} book={b} onOpen={onOpen} />)}
        </div>
      )}
    </main>
  );
}

/* ----------------------------- PROFILE ----------------------------- */
function ProfilePage({ user, onLogout, navigate, notify }) {
  const [loans, setLoans] = useState([]);
  const [reservations, setReservations] = useState([]);
  const [tab, setTab] = useState("overview");

  const load = useCallback(async () => {
    try {
      const [l, r] = await Promise.all([api.myLoans(), api.myReservations()]);
      setLoans(l);
      setReservations(r);
    } catch (e) {
      notify(formatError(e), "error");
    }
  }, [notify]);

  useEffect(() => { load(); }, [load]);

  const active = loans.filter((l) => l.status === "active");
  const history = loans.filter((l) => l.status === "returned");

  const handleReturn = async (id) => {
    try {
      await api.returnLoan(id);
      notify("Buku berhasil dikembalikan", "success");
      load();
    } catch (e) { notify(formatError(e), "error"); }
  };
  const handleCancel = async (id) => {
    try {
      await api.cancelReservation(id);
      notify("Reservasi dibatalkan", "success");
      load();
    } catch (e) { notify(formatError(e), "error"); }
  };

  return (
    <main className="page-main profile-page">
      <div className="page-title">
        <div>
          <span className="section-kicker">RUANG PRIBADI</span>
          <h1>Halo, {user.name.split(" ")[0]}.</h1>
          <p>Kelola aktivitas dan koleksi bacaanmu di sini.</p>
        </div>
      </div>
      <div className="profile-layout">
        <aside className="profile-card">
          <div className="profile-avatar">{initials(user.name)}</div>
          <h3>{user.name}</h3>
          <span>{user.faculty || (user.role === "admin" ? "Administrator" : "Anggota")}</span>
          <div className="profile-divider" />
          <button className={tab === "overview" ? "profile-nav-active" : ""} data-testid="profile-overview-tab" onClick={() => setTab("overview")}>
            <CircleUserRound size={17} /> Ringkasan akun
          </button>
          <button className={tab === "history" ? "profile-nav-active" : ""} data-testid="profile-history-tab" onClick={() => setTab("history")}>
            <Clock3 size={17} /> Riwayat peminjaman
          </button>
          <button data-testid="profile-logout-button" onClick={onLogout}>Keluar akun</button>
        </aside>
        <section className="profile-content">
          <div className="profile-welcome">
            <div>
              <span className="section-kicker">AKTIVITASMU</span>
              <h2>{tab === "overview" ? "Ringkasan akun" : "Riwayat peminjaman"}</h2>
            </div>
            <span className="member-code" data-testid="member-id">ID ANGGOTA · {user.member_id}</span>
          </div>

          {tab === "overview" && <>
            <div className="mini-stats">
              <div><BookOpen size={19} /><strong>{active.length}</strong><span>Buku dipinjam</span></div>
              <div><CalendarDays size={19} /><strong>{reservations.length}</strong><span>Reservasi aktif</span></div>
              <div><FileText size={19} /><strong>{history.length}</strong><span>Riwayat selesai</span></div>
            </div>
            <div className="loan-box">
              <div className="loan-heading">
                <h3>Peminjaman aktif</h3>
                <button className="text-link" data-testid="profile-browse-button" onClick={() => navigate("catalog")}>Cari buku <ChevronRight size={16} /></button>
              </div>
              {active.length === 0 && <div className="empty-state">Belum ada peminjaman aktif.</div>}
              {active.map((loan, i) => (
                <div className="loan-row" data-testid={`active-loan-${i}`} key={loan.id}>
                  <div className="loan-icon"><BookOpen size={19} /></div>
                  <div>
                    <strong>{loan.book?.title || "Buku"}</strong>
                    <span>Dipinjam {fmtDate(loan.borrowed_at)} · Jatuh tempo {fmtDate(loan.due_at)}</span>
                  </div>
                  <span className="loan-status">Aktif</span>
                  <button className="return-button" data-testid={`return-loan-${i}`} onClick={() => handleReturn(loan.id)}>Kembalikan</button>
                </div>
              ))}
              {reservations.length > 0 && (
                <div className="reservation-list" data-testid="reservation-list">
                  <h3 style={{ marginTop: 28 }}>Antrean reservasi (FIFO)</h3>
                  {reservations.map((item, i) => (
                    <div className="loan-row" data-testid={`reservation-item-${i}`} key={item.id}>
                      <span className="queue-number">#{item.position}</span>
                      <div>
                        <strong>{item.book?.title}</strong>
                        <span>Permintaan {fmtDate(item.requested_at)} · {item.status === "ready" ? "Siap diambil" : "Menunggu"}</span>
                      </div>
                      <span className="loan-status">{item.status === "ready" ? "Siap" : "Menunggu"}</span>
                      <button className="return-button" data-testid={`cancel-reservation-${i}`} onClick={() => handleCancel(item.id)}>Batalkan</button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>}

          {tab === "history" && (
            <div className="loan-box" style={{ borderTop: 0, paddingTop: 4 }}>
              {history.length === 0 && <div className="empty-state">Belum ada riwayat.</div>}
              {history.map((loan, i) => (
                <div className="loan-row" data-testid={`history-loan-${i}`} key={loan.id}>
                  <div className="loan-icon"><FileText size={19} /></div>
                  <div>
                    <strong>{loan.book?.title || "Buku"}</strong>
                    <span>Dikembalikan {fmtDate(loan.returned_at)} · Dipinjam {fmtDate(loan.borrowed_at)}</span>
                  </div>
                  <span className="loan-status" style={{ background: "#eff6ff", color: "#1e3a8a" }}>Selesai</span>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

function RequireAuth({ onOpen }) {
  return (
    <main className="page-main">
      <div className="empty-state" style={{ padding: 100 }} data-testid="require-auth-message">
        <ShieldCheck size={40} style={{ color: "#1e3a8a", marginBottom: 12 }} />
        <p style={{ fontSize: 15, marginBottom: 20 }}>Anda perlu masuk untuk melihat profil.</p>
        <button className="primary-button" data-testid="require-auth-login-button" onClick={onOpen}>Masuk</button>
      </div>
    </main>
  );
}

/* ---------------------------- BOOK CARDS ---------------------------- */
function BookCard({ book, onOpen }) {
  return (
    <article className="book-card" data-testid={`book-card-${book.id}`}>
      <button className="book-cover" data-testid={`book-open-${book.id}`} onClick={() => onOpen(book)}>
        <img src={book.cover_url || "https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?auto=format&fit=crop&w=800&q=85"} alt={`Sampul ${book.title}`} onError={(e) => { e.currentTarget.src = "https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?auto=format&fit=crop&w=800&q=85"; }} />
        <span className="book-type">{book.type}</span>
      </button>
      <div className="book-info">
        <span className="book-category">{book.category}</span>
        <h3>{book.title}</h3>
        <p>{book.author}</p>
        <div className="book-meta">
          <span>{book.year}</span>
          <span className={book.stock ? "available" : "unavailable"}>
            {book.stock ? `${book.stock} tersedia` : "Sedang dipinjam"}
          </span>
        </div>
      </div>
    </article>
  );
}

function BookDetail({ book, onClose, onBorrow, loggedIn }) {
  return (
    <div className="modal-backdrop" data-testid="book-detail-modal">
      <div className="detail-modal">
        <button className="modal-close" data-testid="book-detail-close-button" onClick={onClose}><X /></button>
        <img className="detail-cover" src={book.cover_url} alt={`Sampul ${book.title}`} />
        <div className="detail-copy">
          <span className="book-category">{book.category} · {book.type}</span>
          <h2>{book.title}</h2>
          <p className="detail-author">Oleh {book.author}</p>
          <div className="detail-meta">
            <span><CalendarDays size={16} /> Terbit {book.year}</span>
            <span><FileText size={16} /> Bahasa Indonesia</span>
            <span className={book.stock ? "available" : "unavailable"}>
              {book.stock ? `${book.stock} stok tersedia` : "Stok habis"}
            </span>
          </div>
          <p className="abstract">{book.description || "Buku ini menghadirkan pembahasan terstruktur dan kontekstual untuk mendukung proses belajar, penelitian, dan pengembangan wawasan pembaca."}</p>
          <button className="primary-button" data-testid="borrow-book-button" onClick={onBorrow}>
            {book.stock === 0 ? "Masuk antrean reservasi" : loggedIn ? "Pinjam koleksi" : "Masuk untuk meminjam"}
            <ChevronRight size={17} />
          </button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------ AUTH ------------------------------ */
function AuthModal({ mode, setMode, onClose, onSuccess, notify }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [faculty, setFaculty] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const submit = async () => {
    setBusy(true); setErr("");
    try {
      if (mode === "login") await api.login(email, password);
      else await api.register({ name, email, password, faculty });
      await onSuccess();
    } catch (e) {
      setErr(formatError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" data-testid="auth-modal">
      <div className="login-modal">
        <button className="modal-close" data-testid="auth-close-button" onClick={onClose}><X /></button>
        <div className="login-icon"><ShieldCheck size={25} /></div>
        <span className="section-kicker">{mode === "login" ? "AKSES ANGGOTA" : "DAFTAR ANGGOTA"}</span>
        <h2>{mode === "login" ? "Selamat datang kembali" : "Bergabung dengan DigiLib"}</h2>
        <p>{mode === "login" ? "Masuk untuk meminjam koleksi dan mengelola aktivitas bacaan." : "Buat akun untuk mulai meminjam koleksi digital."}</p>

        {mode === "register" && (
          <>
            <label>Nama lengkap
              <input data-testid="register-name-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Nama lengkap" />
            </label>
            <label>Fakultas / Program (opsional)
              <input data-testid="register-faculty-input" value={faculty} onChange={(e) => setFaculty(e.target.value)} placeholder="Fakultas Ilmu Pendidikan" />
            </label>
          </>
        )}
        <label>Email
          <input data-testid={`${mode}-email-input`} type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="nama@digilib.ac.id" />
        </label>
        <label>Kata sandi
          <input data-testid={`${mode}-password-input`} type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Minimal 6 karakter" />
        </label>

        {err && <div data-testid="auth-error" style={{ color: "#c2410c", fontSize: 11, marginTop: 12 }}>{err}</div>}

        <button className="primary-button full" data-testid={`${mode}-submit-button`} disabled={busy} onClick={submit}>
          {busy ? "Memproses..." : mode === "login" ? "Masuk ke DigiLib" : "Buat akun & masuk"}
          <ChevronRight size={17} />
        </button>
        <small>
          {mode === "login" ? (
            <>Belum punya akun? <a href="#" data-testid="switch-to-register" onClick={(e) => { e.preventDefault(); setMode("register"); setErr(""); }}>Daftar</a></>
          ) : (
            <>Sudah punya akun? <a href="#" data-testid="switch-to-login" onClick={(e) => { e.preventDefault(); setMode("login"); setErr(""); }}>Masuk</a></>
          )}
        </small>
        <small style={{ marginTop: 8, opacity: 0.7 }}>Demo: admin@digilib.ac.id / admin123 · andi@digilib.ac.id / member123</small>
      </div>
    </div>
  );
}

/* ------------------------------ ADMIN ------------------------------ */
function AdminPanel({ notify }) {
  const [tab, setTab] = useState("books");
  const [stats, setStats] = useState(null);
  const [books, setBooks] = useState([]);
  const [members, setMembers] = useState([]);
  const [loans, setLoans] = useState([]);
  const [editing, setEditing] = useState(null);

  const load = useCallback(async () => {
    try {
      const [s, b, m, l] = await Promise.all([api.stats(), api.listBooks({ limit: 500 }), api.members(), api.adminLoans()]);
      setStats(s); setBooks(b); setMembers(m); setLoans(l);
    } catch (e) { notify(formatError(e), "error"); }
  }, [notify]);

  useEffect(() => { load(); }, [load]);

  const saveBook = async (data) => {
    try {
      if (data.id) await api.updateBook(data.id, data);
      else await api.createBook(data);
      notify("Buku disimpan", "success");
      setEditing(null);
      load();
    } catch (e) { notify(formatError(e), "error"); }
  };

  const deleteBook = async (id) => {
    if (!window.confirm("Hapus buku ini?")) return;
    try { await api.deleteBook(id); notify("Buku dihapus", "success"); load(); }
    catch (e) { notify(formatError(e), "error"); }
  };

  const deleteMember = async (id) => {
    if (!window.confirm("Hapus anggota ini?")) return;
    try { await api.deleteMember(id); notify("Anggota dihapus", "success"); load(); }
    catch (e) { notify(formatError(e), "error"); }
  };

  const forceReturn = async (loanId) => {
    try { await api.returnLoan(loanId); notify("Peminjaman ditandai selesai", "success"); load(); }
    catch (e) { notify(formatError(e), "error"); }
  };

  return (
    <main className="page-main admin-page">
      <div className="page-title">
        <div>
          <span className="section-kicker">PUSAT KENDALI</span>
          <h1>Panel admin</h1>
          <p>Kelola katalog, anggota, dan aktivitas perpustakaan.</p>
        </div>
        {tab === "books" && (
          <button className="primary-button" data-testid="admin-add-book-button" onClick={() => setEditing({})}>
            <PlusCircle size={17} /> Tambah koleksi
          </button>
        )}
      </div>

      {stats && (
        <div className="admin-stats">
          <div><BookOpen /><strong>{stats.total_books}</strong><span>Total koleksi</span></div>
          <div><Users /><strong>{stats.total_members}</strong><span>Anggota</span></div>
          <div><Clock3 /><strong>{stats.active_loans}</strong><span>Peminjaman aktif</span></div>
          <div><ShieldCheck /><strong>{stats.overdue}</strong><span>Melewati tenggat</span></div>
        </div>
      )}

      <div className="admin-tabs" style={{ display: "flex", gap: 24, borderBottom: "1px solid var(--line)", marginBottom: 26 }}>
        {[
          ["books", "Katalog"], ["members", "Anggota"], ["loans", "Peminjaman"], ["stats", "Statistik"],
        ].map(([k, label]) => (
          <button
            key={k}
            data-testid={`admin-tab-${k}`}
            onClick={() => setTab(k)}
            style={{
              padding: "12px 4px", background: "none", border: 0, cursor: "pointer",
              color: tab === k ? "var(--blue)" : "var(--muted)",
              fontWeight: tab === k ? 700 : 500, fontSize: 12,
              borderBottom: tab === k ? "2px solid var(--orange)" : "2px solid transparent",
            }}
          >{label}</button>
        ))}
      </div>

      {tab === "books" && (
        <section className="admin-table-card">
          <div className="table-heading"><h2>Katalog ({books.length})</h2></div>
          <div className="admin-table">
            {books.map((b) => (
              <div className="table-row" data-testid={`admin-book-row-${b.id}`} key={b.id}>
                <img src={b.cover_url} alt="" />
                <div><strong>{b.title}</strong><span>{b.author}</span></div>
                <span>{b.category}</span>
                <span>{b.stock} tersedia</span>
                <div style={{ display: "flex", gap: 8 }}>
                  <button data-testid={`admin-edit-book-${b.id}`} onClick={() => setEditing(b)}><Pencil size={14} /></button>
                  <button data-testid={`admin-delete-book-${b.id}`} onClick={() => deleteBook(b.id)} style={{ color: "#c2410c" }}><Trash2 size={14} /></button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {tab === "members" && (
        <section className="admin-table-card">
          <div className="table-heading"><h2>Anggota ({members.length})</h2></div>
          <div className="admin-table">
            {members.map((m) => (
              <div className="table-row" data-testid={`admin-member-row-${m.id}`} key={m.id} style={{ gridTemplateColumns: "42px 1fr 140px 110px 45px" }}>
                <div className="loan-icon" style={{ width: 36, height: 36 }}>{initials(m.name)}</div>
                <div><strong>{m.name}</strong><span>{m.email}</span></div>
                <span>{m.faculty || "-"}</span>
                <span style={{ color: m.role === "admin" ? "var(--orange)" : "var(--muted)" }}>{m.role}</span>
                <button data-testid={`admin-delete-member-${m.id}`} onClick={() => deleteMember(m.id)} style={{ color: "#c2410c" }}><Trash2 size={14} /></button>
              </div>
            ))}
          </div>
        </section>
      )}

      {tab === "loans" && (
        <section className="admin-table-card">
          <div className="table-heading"><h2>Peminjaman ({loans.length})</h2></div>
          <div className="admin-table">
            {loans.map((l) => (
              <div className="table-row" data-testid={`admin-loan-row-${l.id}`} key={l.id} style={{ gridTemplateColumns: "1fr 1fr 140px 110px 90px" }}>
                <div><strong>{l.book?.title || "Buku"}</strong><span>{l.book?.author}</span></div>
                <div><strong>{l.user?.name || "-"}</strong><span>{l.user?.email}</span></div>
                <span>Jatuh tempo {fmtDate(l.due_at)}</span>
                <span style={{ color: l.status === "active" ? "var(--green)" : "var(--muted)" }}>{l.status}</span>
                {l.status === "active" ? (
                  <button data-testid={`admin-return-loan-${l.id}`} onClick={() => forceReturn(l.id)}>Kembalikan</button>
                ) : <span style={{ fontSize: 10 }}>{fmtDate(l.returned_at)}</span>}
              </div>
            ))}
          </div>
        </section>
      )}

      {tab === "stats" && stats && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
          <section className="admin-table-card">
            <div className="table-heading"><h2>Buku paling dipinjam</h2></div>
            {stats.top_books.length === 0 && <div className="empty-state">Belum ada data peminjaman.</div>}
            {stats.top_books.map((t, i) => (
              <div className="table-row" key={t.book.id} style={{ gridTemplateColumns: "30px 42px 1fr 60px" }}>
                <strong>{i + 1}</strong>
                <img src={t.book.cover_url} alt="" />
                <div><strong>{t.book.title}</strong><span>{t.book.author}</span></div>
                <span>{t.count}×</span>
              </div>
            ))}
          </section>
          <section className="admin-table-card">
            <div className="table-heading"><h2>Peminjaman per kategori</h2></div>
            {stats.per_category.length === 0 && <div className="empty-state">Belum ada data.</div>}
            {stats.per_category.map((c) => (
              <div key={c.category} style={{ padding: "12px 0", borderTop: "1px solid var(--line)", display: "flex", justifyContent: "space-between", fontSize: 12 }}>
                <strong>{c.category}</strong>
                <span style={{ color: "var(--muted)" }}>{c.count} peminjaman</span>
              </div>
            ))}
          </section>
        </div>
      )}

      {editing && <BookEditor initial={editing} onSave={saveBook} onClose={() => setEditing(null)} />}
    </main>
  );
}

function BookEditor({ initial, onSave, onClose }) {
  const [form, setForm] = useState({
    id: initial.id,
    title: initial.title || "",
    author: initial.author || "",
    type: initial.type || "Buku",
    category: initial.category || "Pendidikan",
    year: initial.year || String(new Date().getFullYear()),
    stock: initial.stock ?? 1,
    cover_url: initial.cover_url || "",
    description: initial.description || "",
    featured: !!initial.featured,
  });
  const [busy, setBusy] = useState(false);

  const change = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async () => {
    setBusy(true);
    await onSave({ ...form, stock: Number(form.stock) });
    setBusy(false);
  };

  return (
    <div className="modal-backdrop" data-testid="book-editor-modal">
      <div className="login-modal" style={{ maxWidth: 500 }}>
        <button className="modal-close" data-testid="book-editor-close" onClick={onClose}><X /></button>
        <div className="login-icon"><PlusCircle size={25} /></div>
        <span className="section-kicker">{form.id ? "EDIT KOLEKSI" : "TAMBAH KOLEKSI"}</span>
        <h2>{form.id ? "Ubah koleksi" : "Koleksi baru"}</h2>
        <label>Judul<input data-testid="book-title-input" value={form.title} onChange={(e) => change("title", e.target.value)} /></label>
        <label>Penulis<input data-testid="book-author-input" value={form.author} onChange={(e) => change("author", e.target.value)} /></label>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <label>Jenis
            <select data-testid="book-type-select" value={form.type} onChange={(e) => change("type", e.target.value)}
              style={{ display: "block", width: "100%", marginTop: 7, border: "1px solid var(--line)", padding: 12, borderRadius: 4, font: "12px inherit" }}>
              {["Buku", "E-Book", "Skripsi", "Jurnal", "Tesis", "Disertasi"].map((t) => <option key={t}>{t}</option>)}
            </select>
          </label>
          <label>Kategori
            <select data-testid="book-category-select" value={form.category} onChange={(e) => change("category", e.target.value)}
              style={{ display: "block", width: "100%", marginTop: 7, border: "1px solid var(--line)", padding: 12, borderRadius: 4, font: "12px inherit" }}>
              {CATEGORY_OPTIONS.filter((c) => c !== "Semua kategori").map((c) => <option key={c}>{c}</option>)}
            </select>
          </label>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <label>Tahun<input data-testid="book-year-input" value={form.year} onChange={(e) => change("year", e.target.value)} /></label>
          <label>Stok<input data-testid="book-stock-input" type="number" min="0" value={form.stock} onChange={(e) => change("stock", e.target.value)} /></label>
        </div>
        <label>URL Sampul<input data-testid="book-cover-input" value={form.cover_url} onChange={(e) => change("cover_url", e.target.value)} placeholder="https://..." /></label>
        <label>Deskripsi
          <textarea
            data-testid="book-description-input"
            value={form.description}
            onChange={(e) => change("description", e.target.value)}
            rows={3}
            style={{ display: "block", width: "100%", marginTop: 7, border: "1px solid var(--line)", padding: 12, borderRadius: 4, font: "12px inherit", resize: "vertical" }}
          />
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 15 }}>
          <input data-testid="book-featured-checkbox" type="checkbox" checked={form.featured} onChange={(e) => change("featured", e.target.checked)} style={{ width: "auto", margin: 0 }} />
          Tandai sebagai koleksi pilihan
        </label>
        <button className="primary-button full" data-testid="book-save-button" disabled={busy} onClick={submit}>
          {busy ? "Menyimpan..." : "Simpan koleksi"} <ChevronRight size={17} />
        </button>
      </div>
    </div>
  );
}

export default App;
