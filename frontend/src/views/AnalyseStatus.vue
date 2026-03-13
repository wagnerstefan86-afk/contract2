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

    <!-- Debug / Auswertung section — only shown after completion -->
    <template v-if="auswertung">
      <h2 style="margin: 1.5rem 0 0.5rem;">Auswertung / Debug</h2>

      <!-- Summary stats -->
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.75rem; margin-bottom: 1rem;">
        <div class="stat-card">
          <div class="stat-label">Rohkandidaten gesamt</div>
          <div class="stat-value">{{ pipeline?.konsolidierung?.roh_gesamt ?? '-' }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Nach Konsolidierung</div>
          <div class="stat-value">{{ auswertung.fundstellen_gesamt }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Duplikate entfernt</div>
          <div class="stat-value">{{ pipeline?.konsolidierung?.entfernte_duplikate ?? '-' }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Zusammengeführt</div>
          <div class="stat-value">{{ pipeline?.konsolidierung?.zusammengefuehrt ?? '-' }}</div>
        </div>
      </div>

      <!-- Per-pass breakdown -->
      <h3 style="margin: 1rem 0 0.5rem;">Kandidaten pro Pass</h3>
      <table>
        <thead><tr><th>Pass</th><th>Kandidaten</th><th>Dauer</th></tr></thead>
        <tbody>
          <tr v-for="(info, key) in pipeline?.passes" :key="key">
            <td>{{ passLabel(key as string) }}</td>
            <td>{{ (info as any).kandidaten }}</td>
            <td>{{ (info as any).dauer_sekunden }}s</td>
          </tr>
        </tbody>
      </table>

      <!-- Per-perspective breakdown for Pass 2 -->
      <template v-if="pipeline?.passes?.pass2_perspektive?.pro_perspektive">
        <h3 style="margin: 1rem 0 0.5rem;">Perspektive-Aufschlüsselung (Pass 2)</h3>
        <table>
          <thead><tr><th>Perspektive</th><th>Kandidaten</th></tr></thead>
          <tbody>
            <tr v-for="(count, name) in (pipeline.passes.pass2_perspektive as any).pro_perspektive" :key="name">
              <td>{{ name }}</td>
              <td>{{ count }}</td>
            </tr>
          </tbody>
        </table>
      </template>

      <!-- Category distribution -->
      <h3 style="margin: 1rem 0 0.5rem;">Kategorieverteilung (final)</h3>
      <table>
        <thead><tr><th>Kategorie</th><th>Anzahl</th></tr></thead>
        <tbody>
          <tr v-for="(count, cat) in auswertung.kategorien_final" :key="cat">
            <td>{{ cat }}</td>
            <td>{{ count }}</td>
          </tr>
        </tbody>
      </table>

      <!-- Risk distribution -->
      <h3 style="margin: 1rem 0 0.5rem;">Risikostufenverteilung</h3>
      <div style="display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 1rem;">
        <div v-for="(count, stufe) in auswertung.risikostufen_final" :key="stufe">
          <StatusBadge :status="stufe as string" /> {{ count }}
        </div>
      </div>

      <!-- Source pass distribution -->
      <h3 style="margin: 1rem 0 0.5rem;">Quellenverteilung (finale Fundstellen)</h3>
      <table>
        <thead><tr><th>Quelle</th><th>Anzahl</th></tr></thead>
        <tbody>
          <tr v-for="(count, src) in auswertung.quellen_verteilung_final" :key="src">
            <td style="font-size: 0.85rem;">{{ src }}</td>
            <td>{{ count }}</td>
          </tr>
        </tbody>
      </table>

      <!-- Per-finding merge log -->
      <h3 style="margin: 1rem 0 0.5rem;">Fundstellen-Detail (Zusammenführung)</h3>
      <div style="max-height: 500px; overflow-y: auto;">
        <table style="font-size: 0.85rem;">
          <thead><tr><th>Kurzbeschreibung</th><th>Quelle</th><th>Risiko</th><th>Roh</th><th>Status</th></tr></thead>
          <tbody>
            <tr v-for="f in auswertung.fundstellen_detail" :key="f.id">
              <td>{{ f.kurzbeschreibung }}</td>
              <td style="max-width: 200px; word-break: break-word;">{{ f.quelle_pass }}</td>
              <td><StatusBadge :status="f.risikostufe" /></td>
              <td>{{ f.zusammenfuehrung?.anzahl_roh_kandidaten ?? 1 }}</td>
              <td>{{ f.zusammenfuehrung?.ueberlebt_als ?? '?' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Timing -->
      <h3 style="margin: 1rem 0 0.5rem;">Laufzeiten</h3>
      <table>
        <thead><tr><th>Phase</th><th>Dauer</th></tr></thead>
        <tbody>
          <tr v-for="(secs, phase) in pipeline?.zeiten" :key="phase">
            <td>{{ zeitLabel(phase as string) }}</td>
            <td>{{ secs }}s</td>
          </tr>
        </tbody>
      </table>
    </template>
  </div>
  <div v-else style="padding: 2rem; text-align: center; color: #6b7280;">Wird geladen...</div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";
import { useRoute } from "vue-router";
import api from "../api/client";
import StatusBadge from "../components/StatusBadge.vue";
import ProtokollAnzeige from "../components/ProtokollAnzeige.vue";
import type { Analyse, ProtokollEintrag, AnalyseAuswertung } from "../types";

const route = useRoute();
const analyse = ref<Analyse | null>(null);
const protokoll = ref<ProtokollEintrag[]>([]);
const auswertung = ref<AnalyseAuswertung | null>(null);
let pollTimer: ReturnType<typeof setInterval> | null = null;

const pipeline = computed(() =>
  auswertung.value?.pipeline_auswertung as Record<string, any> | null
);

async function laden() {
  const id = route.params.analyseId;
  const [aRes, pRes] = await Promise.all([
    api.get(`/analysen/${id}`),
    api.get(`/protokoll/analyse/${id}`),
  ]);
  analyse.value = aRes.data;
  protokoll.value = pRes.data;

  // Load auswertung once analysis is done
  if (istAbgeschlossen() && !auswertung.value) {
    try {
      const awRes = await api.get(`/analysen/${id}/auswertung`);
      auswertung.value = awRes.data;
    } catch { /* may not be available yet */ }
  }
}

function istAbgeschlossen(): boolean {
  const s = analyse.value?.status;
  return s === "Abgeschlossen" || s === "Fehlgeschlagen";
}

function passLabel(key: string): string {
  const labels: Record<string, string> = {
    pass1_breit: "Pass 1: Breite Ersterfassung",
    pass2_perspektive: "Pass 2: Perspektivische Vertiefung",
    pass3_implizit: "Pass 3: Implizite Pflichten",
  };
  return labels[key] || key;
}

function zeitLabel(key: string): string {
  const labels: Record<string, string> = {
    pass1_sekunden: "Pass 1: Breite Ersterfassung",
    pass2_sekunden: "Pass 2: Perspektivische Vertiefung",
    pass3_sekunden: "Pass 3: Implizite Pflichten",
    konsolidierung_sekunden: "Konsolidierung",
    gesamt_sekunden: "Gesamt",
  };
  return labels[key] || key;
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

<style scoped>
.stat-card {
  background: white;
  padding: 0.75rem;
  border-radius: 6px;
  text-align: center;
}
.stat-label {
  font-size: 0.8rem;
  color: #6b7280;
  margin-bottom: 0.25rem;
}
.stat-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #1e293b;
}
</style>
