import { defineStore } from "pinia";
import { ref, computed } from "vue";
import api from "../api/client";

export interface AuthUser {
  id: string;
  name: string;
  email: string;
  rolle: string;
  status: string;
}

export const useAuthStore = defineStore("auth", () => {
  const token = ref<string | null>(localStorage.getItem("token"));
  const user = ref<AuthUser | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);

  const isAuthenticated = computed(() => !!token.value && !!user.value);
  const isAdmin = computed(() => user.value?.rolle === "Admin");

  function setToken(t: string | null) {
    token.value = t;
    if (t) {
      localStorage.setItem("token", t);
    } else {
      localStorage.removeItem("token");
    }
  }

  async function login(email: string, passwort: string) {
    error.value = null;
    loading.value = true;
    try {
      const res = await api.post("/auth/login", { email, passwort });
      setToken(res.data.access_token);
      await fetchUser();
    } catch (e: any) {
      setToken(null);
      user.value = null;
      const detail = e.response?.data?.detail;
      error.value = detail || "Anmeldung fehlgeschlagen";
      throw e;
    } finally {
      loading.value = false;
    }
  }

  async function register(name: string, email: string, passwort: string) {
    error.value = null;
    loading.value = true;
    try {
      await api.post("/auth/registrieren", { name, email, passwort });
    } catch (e: any) {
      const detail = e.response?.data?.detail;
      error.value = detail || "Registrierung fehlgeschlagen";
      throw e;
    } finally {
      loading.value = false;
    }
  }

  async function fetchUser() {
    if (!token.value) return;
    try {
      const res = await api.get("/auth/me");
      user.value = res.data;
    } catch {
      setToken(null);
      user.value = null;
    }
  }

  function logout() {
    setToken(null);
    user.value = null;
  }

  return {
    token, user, loading, error,
    isAuthenticated, isAdmin,
    login, register, fetchUser, logout,
  };
});
