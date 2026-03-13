<template>
  <div v-if="f">
    <h1>Fundstellendetail</h1>

    <div style="background: white; padding: 1rem; border-radius: 6px; margin: 1rem 0;">
      <p><strong>Kategorie:</strong> {{ f.kategorie }}</p>
      <p><strong>Risikostufe:</strong> <StatusBadge :status="f.risikostufe" /></p>
      <p><strong>Kurzbeschreibung:</strong> {{ f.kurzbeschreibung }}</p>
    </div>

    <h2 style="margin: 1rem 0 0.5rem;">Betroffene Textstelle</h2>
    <div style="background: #fffbeb; border-left: 4px solid #f59e0b; padding: 1rem; border-radius: 4px; white-space: pre-wrap;">{{ f.textstelle }}</div>

    <div v-if="f.erklaerung" style="margin-top: 1rem;">
      <h2>Erklärung</h2>
      <p style="background: white; padding: 1rem; border-radius: 6px;">{{ f.erklaerung }}</p>
    </div>

    <div v-if="f.empfehlung" style="margin-top: 1rem;">
      <h2>Empfehlung</h2>
      <p style="background: #f0fdf4; padding: 1rem; border-radius: 6px;">{{ f.empfehlung }}</p>
    </div>

    <h2 style="margin: 1.5rem 0 0.5rem;">Bewertung</h2>
    <div style="background: white; padding: 1rem; border-radius: 6px; display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: flex-start;">
      <button v-for="s in statusOptionen" :key="s" :style="{ background: f.pruef_status === s ? '#2563eb' : '#e5e7eb', color: f.pruef_status === s ? 'white' : '#1a1a1a' }" @click="setStatus(s)">
        {{ s }}
      </button>
      <div style="width: 100%; margin-top: 0.5rem;">
        <textarea v-model="kommentar" placeholder="Kommentar (optional)" style="width: 100%; padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 4px; min-height: 60px;"></textarea>
        <button style="background: #2563eb; color: white; margin-top: 0.5rem;" @click="speichern">Speichern</button>
      </div>
    </div>
  </div>
  <div v-else style="padding: 2rem; text-align: center; color: #6b7280;">Wird geladen...</div>
</template>

<script setup lang="ts">
import { ref, onMounted } from "vue";
import { useRoute } from "vue-router";
import api from "../api/client";
import StatusBadge from "../components/StatusBadge.vue";
import type { Fundstelle } from "../types";

const route = useRoute();
const f = ref<Fundstelle | null>(null);
const kommentar = ref("");
const statusOptionen = ["Offen", "Bestätigt", "Abgelehnt", "Zurückgestellt"];

async function laden() {
  const res = await api.get(`/fundstellen/${route.params.id}`);
  f.value = res.data;
  kommentar.value = res.data.pruef_kommentar || "";
}

async function setStatus(status: string) {
  await api.patch(`/fundstellen/${route.params.id}`, { pruef_status: status });
  await laden();
}

async function speichern() {
  await api.patch(`/fundstellen/${route.params.id}`, { pruef_kommentar: kommentar.value });
  await laden();
}

onMounted(laden);
</script>
