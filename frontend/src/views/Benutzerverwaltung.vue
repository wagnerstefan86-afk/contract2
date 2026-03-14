<template>
  <div>
    <h1>Benutzerverwaltung</h1>

    <div v-if="fehler" style="background: #fef2f2; color: #991b1b; padding: 0.75rem; border-radius: 4px; margin-bottom: 1rem; font-size: 0.9rem;">
      {{ fehler }}
    </div>

    <div v-if="ausstehende.length > 0" style="margin-bottom: 2rem;">
      <h2 style="margin: 1rem 0 0.5rem; color: #92400e;">Ausstehende Registrierungen ({{ ausstehende.length }})</h2>
      <table>
        <thead>
          <tr><th>Name</th><th>E-Mail</th><th>Registriert am</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="b in ausstehende" :key="b.id">
            <td>{{ b.name }}</td>
            <td>{{ b.email }}</td>
            <td>{{ datum(b.erstellt_am) }}</td>
            <td style="display: flex; gap: 0.5rem;">
              <button
                style="background: #16a34a; color: white; font-size: 0.8rem; padding: 0.3rem 0.7rem;"
                @click="freigeben(b.id)"
              >Freigeben</button>
              <button
                style="background: #dc2626; color: white; font-size: 0.8rem; padding: 0.3rem 0.7rem;"
                @click="sperren(b.id)"
              >Ablehnen</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <h2 style="margin: 1rem 0 0.5rem;">Alle Benutzer ({{ benutzer.length }})</h2>
    <table v-if="benutzer.length > 0">
      <thead>
        <tr><th>Name</th><th>E-Mail</th><th>Rolle</th><th>Status</th><th>Registriert</th><th></th></tr>
      </thead>
      <tbody>
        <tr v-for="b in benutzer" :key="b.id">
          <td>{{ b.name }}</td>
          <td>{{ b.email }}</td>
          <td>
            <select
              :value="b.rolle"
              @change="rolleAendern(b.id, ($event.target as HTMLSelectElement).value)"
              style="padding: 0.25rem; border: 1px solid #d1d5db; border-radius: 4px; font-size: 0.85rem;"
            >
              <option value="Benutzer">Benutzer</option>
              <option value="Admin">Admin</option>
            </select>
          </td>
          <td>
            <span :style="{ color: statusFarbe(b.status), fontWeight: '500' }">{{ b.status }}</span>
          </td>
          <td>{{ datum(b.erstellt_am) }}</td>
          <td>
            <button
              v-if="b.status === 'Ausstehend'"
              style="background: #16a34a; color: white; font-size: 0.8rem; padding: 0.3rem 0.7rem; margin-right: 0.25rem;"
              @click="freigeben(b.id)"
            >Freigeben</button>
            <button
              v-if="b.status === 'Aktiv'"
              style="background: #dc2626; color: white; font-size: 0.8rem; padding: 0.3rem 0.7rem;"
              @click="sperren(b.id)"
            >Sperren</button>
            <button
              v-if="b.status === 'Gesperrt'"
              style="background: #2563eb; color: white; font-size: 0.8rem; padding: 0.3rem 0.7rem;"
              @click="freigeben(b.id)"
            >Entsperren</button>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-else style="color: #6b7280;">Keine Benutzer vorhanden.</p>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import api from "../api/client";

interface BenutzerInfo {
  id: string;
  name: string;
  email: string;
  rolle: string;
  status: string;
  erstellt_am: string;
}

const benutzer = ref<BenutzerInfo[]>([]);
const fehler = ref<string | null>(null);

const ausstehende = computed(() => benutzer.value.filter((b) => b.status === "Ausstehend"));

function statusFarbe(status: string): string {
  switch (status) {
    case "Aktiv": return "#16a34a";
    case "Ausstehend": return "#d97706";
    case "Gesperrt": return "#dc2626";
    default: return "#6b7280";
  }
}

function datum(iso: string): string {
  return new Date(iso).toLocaleDateString("de-DE", {
    day: "2-digit", month: "2-digit", year: "numeric",
  });
}

async function laden() {
  try {
    const res = await api.get("/benutzer");
    benutzer.value = res.data;
  } catch (e: any) {
    fehler.value = e.response?.data?.detail || "Fehler beim Laden";
  }
}

async function freigeben(id: string) {
  try {
    await api.post(`/benutzer/${id}/freigeben`);
    await laden();
  } catch (e: any) {
    fehler.value = e.response?.data?.detail || "Fehler bei Freigabe";
  }
}

async function sperren(id: string) {
  try {
    await api.post(`/benutzer/${id}/sperren`);
    await laden();
  } catch (e: any) {
    fehler.value = e.response?.data?.detail || "Fehler beim Sperren";
  }
}

async function rolleAendern(id: string, rolle: string) {
  try {
    await api.patch(`/benutzer/${id}`, { rolle });
    await laden();
  } catch (e: any) {
    fehler.value = e.response?.data?.detail || "Fehler bei Rollenänderung";
  }
}

onMounted(laden);
</script>
