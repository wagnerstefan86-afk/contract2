<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
      <h1>Vertragsübersicht</h1>
      <label style="background: #2563eb; color: white; padding: 0.5rem 1rem; border-radius: 4px; cursor: pointer;">
        Hochladen
        <input type="file" accept=".pdf,.docx,.doc,.txt" style="display: none" @change="hochladen" />
      </label>
    </div>

    <div v-if="fehler" style="background: #fef2f2; color: #dc2626; padding: 0.75rem; border-radius: 4px; margin-bottom: 1rem;">
      {{ fehler }}
    </div>

    <table v-if="vertraege.length > 0">
      <thead>
        <tr>
          <th>Dateiname</th>
          <th>Status</th>
          <th>Hochgeladen am</th>
          <th>Aktionen</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="v in vertraege" :key="v.id">
          <td>
            <router-link :to="`/vertrag/${v.id}`">{{ v.dateiname }}</router-link>
          </td>
          <td><StatusBadge :status="v.status" /></td>
          <td>{{ datum(v.erstellt_am) }}</td>
          <td>
            <button style="background: #dc2626; color: white; font-size: 0.8rem;" @click="loeschen(v.id)">
              Löschen
            </button>
          </td>
        </tr>
      </tbody>
    </table>

    <div v-else style="background: white; padding: 2rem; border-radius: 6px; text-align: center; color: #6b7280;">
      Noch keine Verträge hochgeladen.
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from "vue";
import api from "../api/client";
import StatusBadge from "../components/StatusBadge.vue";
import type { Vertrag } from "../types";

const vertraege = ref<Vertrag[]>([]);
const fehler = ref("");

async function laden() {
  try {
    const res = await api.get("/vertraege");
    vertraege.value = res.data;
  } catch {
    fehler.value = "Verträge konnten nicht geladen werden.";
  }
}

async function hochladen(event: Event) {
  const input = event.target as HTMLInputElement;
  const datei = input.files?.[0];
  if (!datei) return;

  const form = new FormData();
  form.append("datei", datei);

  try {
    await api.post("/vertraege", form);
    await laden();
  } catch {
    fehler.value = "Hochladen fehlgeschlagen.";
  }
  input.value = "";
}

async function loeschen(id: string) {
  if (!confirm("Vertrag wirklich löschen?")) return;
  try {
    await api.delete(`/vertraege/${id}`);
    await laden();
  } catch {
    fehler.value = "Löschen fehlgeschlagen.";
  }
}

function datum(iso: string): string {
  return new Date(iso).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

onMounted(laden);
</script>
