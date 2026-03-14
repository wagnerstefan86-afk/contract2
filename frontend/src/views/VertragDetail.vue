<template>
  <div v-if="vertrag">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
      <div>
        <router-link to="/" style="color: #6b7280; font-size: 0.85rem;">Zurück zur Übersicht</router-link>
        <h1>{{ vertrag.dateiname }}</h1>
        <StatusBadge :status="vertrag.status" />
      </div>
      <button
        style="background: #2563eb; color: white;"
        :disabled="laeuft"
        @click="analyseStarten"
      >
        {{ laeuft ? 'Analyse läuft...' : 'Analyse starten' }}
      </button>
    </div>

    <h2 style="margin: 1.5rem 0 0.5rem;">Analysen</h2>
    <table v-if="analysen.length > 0">
      <thead>
        <tr><th>Gestartet</th><th>Status</th><th>Fortschritt</th><th></th></tr>
      </thead>
      <tbody>
        <tr v-for="a in analysen" :key="a.id">
          <td>{{ datum(a.gestartet_am) }}</td>
          <td><StatusBadge :status="a.status" /></td>
          <td>
            <div style="display: flex; align-items: center; gap: 0.5rem;">
              <div style="background: #e5e7eb; border-radius: 4px; height: 6px; width: 80px;">
                <div :style="{ width: a.fortschritt + '%', background: '#2563eb', height: '100%', borderRadius: '4px' }"></div>
              </div>
              {{ a.fortschritt }}%
            </div>
          </td>
          <td><router-link :to="`/vertrag/${vertrag.id}/analyse/${a.id}`">Details</router-link></td>
        </tr>
      </tbody>
    </table>
    <p v-else style="color: #6b7280;">Noch keine Analysen durchgeführt.</p>

    <!-- Grouped findings view -->
    <div style="display: flex; justify-content: space-between; align-items: center; margin: 1.5rem 0 0.5rem;">
      <h2 style="margin: 0;">
        Fundstellen
        <span v-if="gruppiertesErgebnis" style="font-size: 0.85rem; color: #6b7280; font-weight: normal;">
          ({{ gruppiertesErgebnis.debug.nachher }} Gruppen aus {{ gruppiertesErgebnis.debug.vorher }} Einzelfundstellen)
        </span>
      </h2>
      <div style="display: flex; gap: 0.5rem;">
        <button
          :style="{ background: ansicht === 'gruppiert' ? '#2563eb' : '#e5e7eb', color: ansicht === 'gruppiert' ? 'white' : '#1a1a1a', fontSize: '0.8rem', padding: '0.3rem 0.7rem' }"
          @click="ansicht = 'gruppiert'"
        >Gruppiert</button>
        <button
          :style="{ background: ansicht === 'flat' ? '#2563eb' : '#e5e7eb', color: ansicht === 'flat' ? 'white' : '#1a1a1a', fontSize: '0.8rem', padding: '0.3rem 0.7rem' }"
          @click="ansicht = 'flat'"
        >Alle ({{ fundstellen.length }})</button>
      </div>
    </div>

    <!-- Grouped view -->
    <div v-if="ansicht === 'gruppiert' && gruppiertesErgebnis && gruppiertesErgebnis.gruppen.length > 0">
      <div
        v-for="gruppe in gruppiertesErgebnis.gruppen"
        :key="gruppe.gruppe_id"
        style="background: white; border-radius: 6px; margin-bottom: 0.75rem; border: 1px solid #e5e7eb; overflow: hidden;"
      >
        <!-- Group header (clickable) -->
        <div
          style="padding: 0.75rem 1rem; cursor: pointer; display: flex; justify-content: space-between; align-items: center;"
          :style="{ borderLeft: `4px solid ${risikoFarbe(gruppe.risikostufe)}` }"
          @click="toggleGruppe(gruppe.gruppe_id)"
        >
          <div style="flex: 1;">
            <div style="display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;">
              <strong>{{ gruppe.titel }}</strong>
              <StatusBadge :status="gruppe.risikostufe" />
              <span style="background: #e5e7eb; color: #374151; font-size: 0.75rem; padding: 0.15rem 0.5rem; border-radius: 999px;">
                {{ gruppe.anzahl }} {{ gruppe.anzahl === 1 ? 'Fundstelle' : 'Fundstellen' }}
              </span>
              <span style="color: #6b7280; font-size: 0.8rem;">{{ gruppe.kategorie }}</span>
            </div>
            <div v-if="!offeneGruppen.has(gruppe.gruppe_id)" style="color: #6b7280; font-size: 0.8rem; margin-top: 0.25rem;">
              {{ gruppe.zusammenfassung.substring(0, 150) }}{{ gruppe.zusammenfassung.length > 150 ? '...' : '' }}
            </div>
          </div>
          <span style="color: #9ca3af; font-size: 1.2rem; margin-left: 0.5rem;">
            {{ offeneGruppen.has(gruppe.gruppe_id) ? '▼' : '▶' }}
          </span>
        </div>

        <!-- Expanded: sub-findings -->
        <div v-if="offeneGruppen.has(gruppe.gruppe_id)" style="border-top: 1px solid #e5e7eb;">
          <table style="margin: 0; border-radius: 0;">
            <thead>
              <tr><th>Kurzbeschreibung</th><th>Risiko</th><th>Quelle</th><th>Status</th></tr>
            </thead>
            <tbody>
              <tr v-for="f in gruppe.fundstellen" :key="f.id">
                <td><router-link :to="`/pruefung/${f.id}`">{{ f.kurzbeschreibung }}</router-link></td>
                <td><StatusBadge :status="f.risikostufe" /></td>
                <td style="font-size: 0.8rem; color: #6b7280;">{{ f.quelle_pass }}</td>
                <td><StatusBadge :status="f.pruef_status" /></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Flat view (fallback / toggle) -->
    <div v-else-if="ansicht === 'flat'">
      <table v-if="fundstellen.length > 0">
        <thead>
          <tr><th>Kurzbeschreibung</th><th>Kategorie</th><th>Risiko</th><th>Status</th></tr>
        </thead>
        <tbody>
          <tr v-for="f in fundstellen" :key="f.id">
            <td><router-link :to="`/pruefung/${f.id}`">{{ f.kurzbeschreibung }}</router-link></td>
            <td>{{ f.kategorie }}</td>
            <td><StatusBadge :status="f.risikostufe" /></td>
            <td><StatusBadge :status="f.pruef_status" /></td>
          </tr>
        </tbody>
      </table>
      <p v-else style="color: #6b7280;">Keine Fundstellen vorhanden.</p>
    </div>

    <div v-else style="background: white; padding: 2rem; border-radius: 6px; text-align: center; color: #6b7280;">
      Keine Fundstellen vorhanden.
    </div>

    <h2 style="margin: 1.5rem 0 0.5rem;">Dokumentvorschau</h2>
    <DokumentVorschau :text="vertrag.volltext" />
  </div>
  <div v-else style="padding: 2rem; text-align: center; color: #6b7280;">Wird geladen...</div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";
import { useRoute } from "vue-router";
import api from "../api/client";
import StatusBadge from "../components/StatusBadge.vue";
import DokumentVorschau from "../components/DokumentVorschau.vue";
import type { Vertrag, Analyse, Fundstelle, GruppiertesErgebnis } from "../types";

const route = useRoute();
const vertrag = ref<Vertrag | null>(null);
const analysen = ref<Analyse[]>([]);
const fundstellen = ref<Fundstelle[]>([]);
const gruppiertesErgebnis = ref<GruppiertesErgebnis | null>(null);
const ansicht = ref<"gruppiert" | "flat">("gruppiert");
const offeneGruppen = ref<Set<string>>(new Set());
let pollTimer: ReturnType<typeof setInterval> | null = null;

const laeuft = computed(() =>
  analysen.value.some(a =>
    a.status !== "Abgeschlossen" && a.status !== "Fehlgeschlagen"
  )
);

function risikoFarbe(risiko: string): string {
  switch (risiko) {
    case "Hoch": return "#dc2626";
    case "Mittel": return "#f59e0b";
    case "Niedrig": return "#16a34a";
    default: return "#6366f1";
  }
}

function toggleGruppe(gruppeId: string) {
  const s = new Set(offeneGruppen.value);
  if (s.has(gruppeId)) {
    s.delete(gruppeId);
  } else {
    s.add(gruppeId);
  }
  offeneGruppen.value = s;
}

async function laden() {
  const id = route.params.id;
  const [vRes, aRes, fRes, gRes] = await Promise.all([
    api.get(`/vertraege/${id}`),
    api.get(`/analysen/vertrag/${id}`),
    api.get(`/fundstellen/vertrag/${id}`),
    api.get(`/fundstellen/vertrag/${id}/gruppiert`).catch(() => ({ data: null })),
  ]);
  vertrag.value = vRes.data;
  analysen.value = aRes.data;
  fundstellen.value = fRes.data;
  if (gRes.data) {
    gruppiertesErgebnis.value = gRes.data;
  }
}

async function analyseStarten() {
  await api.post(`/analysen/vertrag/${route.params.id}`);
  await laden();
  startPolling();
}

function startPolling() {
  stopPolling();
  pollTimer = setInterval(async () => {
    await laden();
    if (!laeuft.value) stopPolling();
  }, 3000);
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function datum(iso: string): string {
  return new Date(iso).toLocaleDateString("de-DE", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

onMounted(async () => {
  await laden();
  if (laeuft.value) startPolling();
});

onUnmounted(stopPolling);
</script>
