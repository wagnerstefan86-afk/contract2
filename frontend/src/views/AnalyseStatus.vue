<template>
  <div v-if="analyse">
    <router-link :to="`/vertrag/${analyse.vertrag_id}`" style="color: #6b7280; font-size: 0.85rem;">Zurück zum Vertrag</router-link>
    <h1>Analysestatus</h1>
    <div style="background: white; padding: 1rem; border-radius: 6px; margin: 1rem 0;">
      <p><strong>Status:</strong> <StatusBadge :status="analyse.status" /></p>
      <p v-if="analyse.aktueller_pass"><strong>Aktueller Pass:</strong> {{ analyse.aktueller_pass }}</p>
      <p><strong>Fortschritt:</strong> {{ analyse.fortschritt }}%</p>
      <div style="background: #e5e7eb; border-radius: 4px; height: 8px; margin-top: 0.5rem;">
        <div :style="{ width: analyse.fortschritt + '%', background: '#2563eb', height: '100%', borderRadius: '4px', transition: 'width 0.3s' }"></div>
      </div>
      <p v-if="analyse.fehler" style="color: #dc2626; margin-top: 0.5rem;">{{ analyse.fehler }}</p>
      <p v-if="analyse.status === 'Abgeschlossen'" style="color: #16a34a; margin-top: 0.5rem;">
        Analyse erfolgreich abgeschlossen.
        <router-link :to="`/vertrag/${analyse.vertrag_id}`">Fundstellen anzeigen</router-link>
      </p>
    </div>

    <h2 style="margin: 1.5rem 0 0.5rem;">Protokoll</h2>
    <ProtokollAnzeige :eintraege="protokoll" />
  </div>
  <div v-else style="padding: 2rem; text-align: center; color: #6b7280;">Wird geladen...</div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";
import { useRoute } from "vue-router";
import api from "../api/client";
import StatusBadge from "../components/StatusBadge.vue";
import ProtokollAnzeige from "../components/ProtokollAnzeige.vue";
import type { Analyse, ProtokollEintrag } from "../types";

const route = useRoute();
const analyse = ref<Analyse | null>(null);
const protokoll = ref<ProtokollEintrag[]>([]);
let pollTimer: ReturnType<typeof setInterval> | null = null;

async function laden() {
  const id = route.params.analyseId;
  const [aRes, pRes] = await Promise.all([
    api.get(`/analysen/${id}`),
    api.get(`/protokoll/analyse/${id}`),
  ]);
  analyse.value = aRes.data;
  protokoll.value = pRes.data;
}

function istAbgeschlossen(): boolean {
  const s = analyse.value?.status;
  return s === "Abgeschlossen" || s === "Fehlgeschlagen";
}

onMounted(async () => {
  await laden();
  if (!istAbgeschlossen()) {
    pollTimer = setInterval(async () => {
      await laden();
      if (istAbgeschlossen() && pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    }, 2000);
  }
});

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer);
});
</script>
