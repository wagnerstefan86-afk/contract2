<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center;">
      <h1>
        Prüfung — Offene Fundstellen
        <span v-if="gruppiertesErgebnis" style="font-size: 0.85rem; color: #6b7280; font-weight: normal;">
          ({{ gruppiertesErgebnis.debug.nachher }} Gruppen aus {{ gruppiertesErgebnis.debug.vorher }} Einzelfundstellen)
        </span>
      </h1>
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
    <div v-if="ansicht === 'gruppiert' && gruppiertesErgebnis && gruppiertesErgebnis.gruppen.length > 0" style="margin-top: 1rem;">
      <div
        v-for="gruppe in gruppiertesErgebnis.gruppen"
        :key="gruppe.gruppe_id"
        style="background: white; border-radius: 6px; margin-bottom: 0.75rem; border: 1px solid #e5e7eb; overflow: hidden;"
      >
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

        <div v-if="offeneGruppen.has(gruppe.gruppe_id)" style="border-top: 1px solid #e5e7eb;">
          <table style="margin: 0; border-radius: 0;">
            <thead>
              <tr><th>Kurzbeschreibung</th><th>Risiko</th><th>Vertrag</th><th></th></tr>
            </thead>
            <tbody>
              <tr v-for="f in gruppe.fundstellen" :key="f.id">
                <td>{{ f.kurzbeschreibung }}</td>
                <td><StatusBadge :status="f.risikostufe" /></td>
                <td>{{ f.vertrag_id.substring(0, 8) }}...</td>
                <td><router-link :to="`/pruefung/${f.id}`">Prüfen</router-link></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Flat view -->
    <table v-else-if="ansicht === 'flat' && fundstellen.length > 0" style="margin-top: 1rem;">
      <thead>
        <tr><th>Kurzbeschreibung</th><th>Kategorie</th><th>Risiko</th><th>Vertrag</th><th></th></tr>
      </thead>
      <tbody>
        <tr v-for="f in fundstellen" :key="f.id">
          <td>{{ f.kurzbeschreibung }}</td>
          <td>{{ f.kategorie }}</td>
          <td><StatusBadge :status="f.risikostufe" /></td>
          <td>{{ f.vertrag_id.substring(0, 8) }}...</td>
          <td><router-link :to="`/pruefung/${f.id}`">Prüfen</router-link></td>
        </tr>
      </tbody>
    </table>

    <div v-else style="background: white; padding: 2rem; border-radius: 6px; text-align: center; color: #6b7280; margin-top: 1rem;">
      Keine offenen Fundstellen vorhanden.
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import api from "../api/client";
import StatusBadge from "../components/StatusBadge.vue";
import type { Fundstelle, GruppiertesErgebnis } from "../types";

const gruppiertesErgebnis = ref<GruppiertesErgebnis | null>(null);
const ansicht = ref<"gruppiert" | "flat">("gruppiert");
const offeneGruppen = ref<Set<string>>(new Set());

// Derive flat list from grouped data so both tabs use the same final-selected layer
const fundstellen = computed<Fundstelle[]>(() => {
  if (!gruppiertesErgebnis.value) return [];
  const all: Fundstelle[] = [];
  for (const gruppe of gruppiertesErgebnis.value.gruppen) {
    for (const f of gruppe.fundstellen) {
      all.push(f as Fundstelle);
    }
  }
  return all;
});

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

onMounted(async () => {
  try {
    const groupRes = await api.get("/fundstellen/offen/gruppiert");
    gruppiertesErgebnis.value = groupRes.data;
  } catch {
    gruppiertesErgebnis.value = null;
  }
});
</script>
