import axios from "axios";

const BASE = process.env.REACT_APP_BACKEND_URL;

const client = axios.create({
  baseURL: `${BASE}/api`,
  withCredentials: true,
});

export function formatError(err) {
  const d = err?.response?.data?.detail;
  if (d == null) return err?.message || "Terjadi kesalahan";
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((e) => e?.msg || JSON.stringify(e)).join(", ");
  return typeof d === "object" ? d.msg || JSON.stringify(d) : String(d);
}

export const api = {
  // Auth
  me: () => client.get("/auth/me").then((r) => r.data),
  login: (email, password) => client.post("/auth/login", { email, password }).then((r) => r.data),
  register: (payload) => client.post("/auth/register", payload).then((r) => r.data),
  logout: () => client.post("/auth/logout").then((r) => r.data),

  // Books
  listBooks: (params = {}) => client.get("/books", { params }).then((r) => r.data),
  getBook: (id) => client.get(`/books/${id}`).then((r) => r.data),
  categories: () => client.get("/books/categories").then((r) => r.data),
  createBook: (body) => client.post("/books", body).then((r) => r.data),
  updateBook: (id, body) => client.patch(`/books/${id}`, body).then((r) => r.data),
  deleteBook: (id) => client.delete(`/books/${id}`).then((r) => r.data),

  // Loans & reservations
  borrow: (bookId) => client.post(`/loans/borrow/${bookId}`).then((r) => r.data),
  returnLoan: (loanId) => client.post(`/loans/${loanId}/return`).then((r) => r.data),
  myLoans: () => client.get("/loans/me").then((r) => r.data),
  myReservations: () => client.get("/reservations/me").then((r) => r.data),
  cancelReservation: (id) => client.delete(`/reservations/${id}`).then((r) => r.data),

  // Admin
  members: () => client.get("/admin/members").then((r) => r.data),
  updateMember: (id, body) => client.patch(`/admin/members/${id}`, body).then((r) => r.data),
  deleteMember: (id) => client.delete(`/admin/members/${id}`).then((r) => r.data),
  adminLoans: () => client.get("/admin/loans").then((r) => r.data),
  stats: () => client.get("/admin/stats").then((r) => r.data),
};

export default api;
