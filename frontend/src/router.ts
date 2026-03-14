import { createRouter, createWebHistory } from "vue-router";
import { useAuthStore } from "./stores/auth";

const routes = [
  {
    path: "/anmelden",
    name: "anmelden",
    component: () => import("./views/Anmelden.vue"),
    meta: { title: "Anmelden", public: true },
  },
  {
    path: "/registrieren",
    name: "registrieren",
    component: () => import("./views/Registrieren.vue"),
    meta: { title: "Registrieren", public: true },
  },
  {
    path: "/",
    name: "vertragsuebersicht",
    component: () => import("./views/VertragUebersicht.vue"),
    meta: { title: "Vertragsübersicht" },
  },
  {
    path: "/vertrag/:id",
    name: "vertragdetail",
    component: () => import("./views/VertragDetail.vue"),
    meta: { title: "Vertragsdetail" },
  },
  {
    path: "/vertrag/:id/analyse/:analyseId",
    name: "analysestatus",
    component: () => import("./views/AnalyseStatus.vue"),
    meta: { title: "Analysestatus" },
  },
  {
    path: "/pruefung",
    name: "pruefung",
    component: () => import("./views/PruefungAnsicht.vue"),
    meta: { title: "Prüfung" },
  },
  {
    path: "/pruefung/:id",
    name: "fundstelledetail",
    component: () => import("./views/FundstelleDetail.vue"),
    meta: { title: "Fundstellendetail" },
  },
  {
    path: "/einstellungen",
    name: "einstellungen",
    component: () => import("./views/Einstellungen.vue"),
    meta: { title: "Einstellungen", requiresAdmin: true },
  },
  {
    path: "/benutzerverwaltung",
    name: "benutzerverwaltung",
    component: () => import("./views/Benutzerverwaltung.vue"),
    meta: { title: "Benutzerverwaltung", requiresAdmin: true },
  },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach(async (to, _from, next) => {
  const auth = useAuthStore();

  // Public routes don't need auth
  if (to.meta.public) {
    // If already logged in, redirect to home
    if (auth.token && to.name === "anmelden") {
      if (!auth.user) await auth.fetchUser();
      if (auth.isAuthenticated) return next("/");
    }
    return next();
  }

  // Check if token exists
  if (!auth.token) {
    return next("/anmelden");
  }

  // Fetch user if not yet loaded
  if (!auth.user) {
    await auth.fetchUser();
  }

  // If still not authenticated after fetch, redirect
  if (!auth.isAuthenticated) {
    return next("/anmelden");
  }

  // Admin-only routes
  if (to.meta.requiresAdmin && !auth.isAdmin) {
    return next("/");
  }

  next();
});
