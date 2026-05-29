import axios from "axios";

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export const api = axios.create({ baseURL: BASE });

export const campaignsApi = {
  list: () => api.get("/campaigns/").then((r) => r.data),
  get: (id: string) => api.get(`/campaigns/${id}`).then((r) => r.data),
  create: (data: unknown) => api.post("/campaigns/", data).then((r) => r.data),
  update: (id: string, data: unknown) => api.patch(`/campaigns/${id}`, data).then((r) => r.data),
  start: (id: string) => api.post(`/campaigns/${id}/start`).then((r) => r.data),
  pause: (id: string) => api.post(`/campaigns/${id}/pause`).then((r) => r.data),
  uploadContacts: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api.post(`/campaigns/${id}/contacts/upload`, form).then((r) => r.data);
  },
};

export const agentsApi = {
  list: () => api.get("/agents/").then((r) => r.data),
  create: (data: unknown) => api.post("/agents/", data).then((r) => r.data),
  setStatus: (id: string, status: string) => api.patch(`/agents/${id}/status?status=${status}`).then((r) => r.data),
  getTurnCredentials: () => api.get("/agents/turn-credentials").then((r) => r.data),
};
