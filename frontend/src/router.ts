import { createRouter, createWebHistory } from "vue-router";

const routes = [
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
    meta: { title: "Einstellungen" },
  },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
});
