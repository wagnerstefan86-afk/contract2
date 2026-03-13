<template>
  <div>
    <h1>Einstellungen</h1>

    <div style="background: white; padding: 1.5rem; border-radius: 6px; margin-top: 1rem; max-width: 600px;">
      <h2 style="margin-bottom: 1rem;">LLM-Konfiguration</h2>

      <div v-for="feld in felder" :key="feld.schluessel" style="margin-bottom: 1rem;">
        <label style="display: block; font-weight: 600; margin-bottom: 0.25rem;">{{ feld.label }}</label>
        <input v-model="werte[feld.schluessel]" :type="feld.geheim ? 'password' : 'text'" :placeholder="feld.platzhalter" style="width: 100%; padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 4px;" />
      </div>

      <div style="display: flex; gap: 0.5rem;">
        <button style="background: #2563eb; color: white;" @click="speichern">Speichern</button>
        <button style="background: #e5e7eb;" @click="verbindungTesten">Verbindung testen</button>
      </div>

      <div v-if="meldung" :style="{ marginTop: '1rem', padding: '0.5rem', borderRadius: '4px', background: istFehler ? '#fef2f2' : '#f0fdf4', color: istFehler ? '#dc2626' : '#16a34a' }">
        {{ meldung }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from "vue";
import api from "../api/client";

const felder = [
  { schluessel: "llm_anbieter", label: "LLM-Anbieter", platzhalter: "openai / azure / anthropic", geheim: false },
  { schluessel: "llm_modell", label: "Modell", platzhalter: "gpt-4o / claude-sonnet-4-20250514", geheim: false },
  { schluessel: "llm_api_schluessel", label: "API-Schlüssel", platzhalter: "sk-...", geheim: true },
  { schluessel: "llm_basis_url", label: "Basis-URL (optional)", platzhalter: "https://api.openai.com/v1", geheim: false },
];

const werte = reactive<Record<string, string>>({});
const meldung = ref("");
const istFehler = ref(false);

async function laden() {
  try {
    const res = await api.get("/einstellungen");
    for (const e of res.data) {
      werte[e.schluessel] = e.wert;
    }
  } catch {
    // Initial load, settings may not exist yet
  }
}

async function speichern() {
  try {
    for (const feld of felder) {
      const w = werte[feld.schluessel];
      if (w !== undefined && w !== "") {
        await api.put(`/einstellungen/${feld.schluessel}`, { wert: w });
      }
    }
    meldung.value = "Einstellungen gespeichert.";
    istFehler.value = false;
  } catch {
    meldung.value = "Fehler beim Speichern.";
    istFehler.value = true;
  }
}

function verbindungTesten() {
  // TODO: implement backend endpoint for connection test
  meldung.value = "Verbindungstest ist noch nicht implementiert.";
  istFehler.value = false;
}

onMounted(laden);
</script>
