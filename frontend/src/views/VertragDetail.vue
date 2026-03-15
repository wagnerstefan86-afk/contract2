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
        <span v-if="finalEditorial && finalEditorial.metriken.hat_editorial" style="font-size: 0.85rem; color: #1e40af; font-weight: normal;">
          ({{ finalEditorial.metriken.anzahl_finale_themen_nachher }} Kernthemen aus {{ finalEditorial.metriken.anzahl_cluster_themen_vorher }} Clustern)
        </span>
        <span v-else-if="risikothemen.length > 0" style="font-size: 0.85rem; color: #6b7280; font-weight: normal;">
          ({{ risikothemen.length }} Risikothemen, {{ fundstellen.length }} Einzelfundstellen)
        </span>
        <span v-else-if="gruppiertesErgebnis" style="font-size: 0.85rem; color: #6b7280; font-weight: normal;">
          ({{ gruppiertesErgebnis.debug.nachher }} Gruppen aus {{ gruppiertesErgebnis.debug.vorher }} Einzelfundstellen)
        </span>
      </h2>
      <div style="display: flex; gap: 0.5rem;">
        <button
          v-if="finalEditorial && finalEditorial.metriken.hat_editorial"
          :style="{ background: ansicht === 'final' ? '#2563eb' : '#e5e7eb', color: ansicht === 'final' ? 'white' : '#1a1a1a', fontSize: '0.8rem', padding: '0.3rem 0.7rem' }"
          @click="ansicht = 'final'"
        >Kernthemen ({{ finalEditorial.finale_themen.length }})</button>
        <button
          v-if="risikothemen.length > 0"
          :style="{ background: ansicht === 'themen' ? '#2563eb' : '#e5e7eb', color: ansicht === 'themen' ? 'white' : '#1a1a1a', fontSize: '0.8rem', padding: '0.3rem 0.7rem' }"
          @click="ansicht = 'themen'"
        >Risikothemen ({{ risikothemen.length }})</button>
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

    <!-- FINAL EDITORIAL view (reduced core themes — main view for reviewers) -->
    <div v-if="ansicht === 'final' && finalEditorial && finalEditorial.metriken.hat_editorial">
      <!-- Metrics bar -->
      <div style="background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 6px; padding: 0.6rem 1rem; font-size: 0.8rem; color: #1e40af; margin-bottom: 0.75rem;">
        <strong>Final Editorial:</strong>
        {{ finalEditorial.metriken.anzahl_finale_themen_nachher }} Kernthemen
        aus {{ finalEditorial.metriken.anzahl_cluster_themen_vorher }} Cluster-Themen selektiert
        &middot; {{ finalEditorial.metriken.anzahl_verworfene_themen }} verworfen
        &middot; {{ finalEditorial.metriken.anzahl_ausgewaehlte_evidenzen }} Evidenzen
      </div>

      <!-- Final themes -->
      <div
        v-for="thema in finalEditorial.finale_themen"
        :key="thema.id"
        style="background: white; border-radius: 6px; margin-bottom: 0.75rem; border: 1px solid #e5e7eb; overflow: hidden;"
      >
        <!-- Theme header -->
        <div
          style="padding: 0.75rem 1rem; cursor: pointer; display: flex; justify-content: space-between; align-items: center;"
          :style="{ borderLeft: `4px solid ${risikoFarbe(thema.risikostufe)}` }"
          @click="toggleGruppe(thema.id)"
        >
          <div style="flex: 1;">
            <div style="display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;">
              <strong>{{ thema.titel }}</strong>
              <StatusBadge :status="thema.risikostufe" />
              <span style="background: #dbeafe; color: #1e40af; font-size: 0.75rem; padding: 0.15rem 0.5rem; border-radius: 999px;">
                {{ thema.fundstellen.length }} {{ thema.fundstellen.length === 1 ? 'Evidenz' : 'Evidenzen' }}
              </span>
              <span style="color: #6b7280; font-size: 0.8rem;">{{ thema.kategorie }}</span>
            </div>
            <div v-if="!offeneGruppen.has(thema.id)" style="color: #374151; font-size: 0.8rem; margin-top: 0.25rem;">
              {{ thema.kurzbeschreibung.substring(0, 200) }}{{ thema.kurzbeschreibung.length > 200 ? '...' : '' }}
            </div>
          </div>
          <span style="color: #9ca3af; font-size: 1.2rem; margin-left: 0.5rem;">
            {{ offeneGruppen.has(thema.id) ? '▼' : '▶' }}
          </span>
        </div>

        <!-- Expanded content -->
        <div v-if="offeneGruppen.has(thema.id)" style="border-top: 1px solid #e5e7eb;">
          <!-- Risk description -->
          <div style="padding: 0.75rem 1rem; background: #f9fafb; font-size: 0.85rem;">
            <div style="color: #374151; margin-bottom: 0.5rem;">{{ thema.kurzbeschreibung }}</div>
            <div v-if="thema.warum_verhandlungsrelevant" style="color: #1e40af; font-size: 0.8rem;">
              <strong>Verhandlungsrelevanz:</strong> {{ thema.warum_verhandlungsrelevant }}
            </div>
          </div>

          <!-- Evidence table -->
          <table style="margin: 0; border-radius: 0;">
            <thead>
              <tr><th></th><th>Fundstelle</th><th>Risiko</th><th>Status</th></tr>
            </thead>
            <tbody>
              <template v-for="f in thema.fundstellen" :key="f.id">
                <tr :style="{ background: f.ist_primaer ? '#eff6ff' : 'white' }">
                  <td style="width: 30px; text-align: center;">
                    <span v-if="f.ist_primaer" style="color: #2563eb; font-weight: bold; font-size: 0.75rem;" title="Primärevidenz">P</span>
                    <span v-else style="color: #6b7280; font-size: 0.75rem;" title="Sekundärevidenz">S</span>
                  </td>
                  <td>
                    <router-link :to="`/pruefung/${f.id}`">{{ f.kurzbeschreibung }}</router-link>
                    <span v-if="f.evidence_heading_path" style="display: block; font-size: 0.75rem; color: #9ca3af; margin-top: 0.15rem;">{{ f.evidence_heading_path }}</span>
                  </td>
                  <td><StatusBadge :status="f.risikostufe" /></td>
                  <td><StatusBadge :status="f.pruef_status" /></td>
                </tr>
                <!-- Scope text preview row -->
                <tr v-if="f.scope_text && offeneGruppen.has(thema.id)" :style="{ background: f.ist_primaer ? '#f0f7ff' : '#fafafa' }">
                  <td></td>
                  <td colspan="3" style="padding: 0.4rem 0.75rem; font-size: 0.8rem; color: #4b5563; border-top: none;">
                    <div style="white-space: pre-wrap; line-height: 1.4; max-height: 100px; overflow: hidden;">{{ f.scope_text.substring(0, 400) }}{{ f.scope_text.length > 400 ? '...' : '' }}</div>
                    <div v-if="f.trigger_spans && f.trigger_spans.length" style="margin-top: 0.3rem; font-size: 0.75rem; color: #92400e;">
                      Relevante Passagen: {{ f.trigger_spans.join(' | ') }}
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>

          <!-- Recommendation block -->
          <div style="padding: 0.75rem 1rem; border-top: 1px solid #e5e7eb; font-size: 0.8rem;">
            <div v-if="thema.alternativformulierung" style="margin-bottom: 0.5rem;">
              <strong style="color: #374151;">Alternativformulierung:</strong>
              <div style="color: #4b5563; margin-top: 0.25rem; padding: 0.5rem; background: #f0fdf4; border-radius: 4px; border: 1px solid #bbf7d0;">
                {{ thema.alternativformulierung }}
              </div>
            </div>
            <div v-if="thema.bieterfrage" style="margin-bottom: 0.5rem;">
              <strong style="color: #374151;">Bieterfrage:</strong>
              <div style="color: #4b5563; margin-top: 0.25rem; padding: 0.5rem; background: #fef3c7; border-radius: 4px; border: 1px solid #fde68a;">
                {{ thema.bieterfrage }}
              </div>
            </div>
            <div v-if="thema.verhandlungsargumente && thema.verhandlungsargumente.length > 0">
              <strong style="color: #374151;">Verhandlungsargumente:</strong>
              <ul style="margin: 0.25rem 0 0 1rem; color: #4b5563;">
                <li v-for="(arg, ai) in thema.verhandlungsargumente" :key="ai">{{ arg }}</li>
              </ul>
            </div>
          </div>
        </div>
      </div>

      <!-- Rejected themes (collapsible) -->
      <div v-if="finalEditorial.verworfene_themen.length > 0" style="margin-top: 0.5rem;">
        <button
          style="background: none; border: none; color: #6b7280; cursor: pointer; font-size: 0.8rem; padding: 0; text-decoration: underline;"
          @click="verworfeneOffen = !verworfeneOffen"
        >
          {{ verworfeneOffen ? 'Verworfene Themen ausblenden' : `${finalEditorial.verworfene_themen.length} verworfene Themen anzeigen` }}
        </button>
        <div v-if="verworfeneOffen" style="margin-top: 0.5rem; background: #fef2f2; border: 1px solid #fecaca; border-radius: 6px; padding: 0.75rem 1rem; font-size: 0.8rem;">
          <div
            v-for="vt in finalEditorial.verworfene_themen"
            :key="vt.id"
            style="padding: 0.25rem 0; color: #6b7280;"
          >
            <span style="text-decoration: line-through;">{{ vt.titel }}</span>
            <span style="color: #9ca3af;"> — {{ vt.grund }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Risikothemen view (LLM-clustered topics) -->
    <div v-if="ansicht === 'themen' && risikothemen.length > 0">
      <div
        v-for="thema in risikothemen"
        :key="thema.id"
        style="background: white; border-radius: 6px; margin-bottom: 0.75rem; border: 1px solid #e5e7eb; overflow: hidden;"
      >
        <div
          style="padding: 0.75rem 1rem; cursor: pointer; display: flex; justify-content: space-between; align-items: center;"
          :style="{ borderLeft: `4px solid ${risikoFarbe(thema.risikostufe)}` }"
          @click="toggleGruppe(thema.id)"
        >
          <div style="flex: 1;">
            <div style="display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;">
              <strong>{{ thema.titel }}</strong>
              <StatusBadge :status="thema.risikostufe" />
              <span style="background: #e5e7eb; color: #374151; font-size: 0.75rem; padding: 0.15rem 0.5rem; border-radius: 999px;">
                {{ thema.anzahl }} {{ thema.anzahl === 1 ? 'Fundstelle' : 'Fundstellen' }}
              </span>
              <span style="color: #6b7280; font-size: 0.8rem;">{{ thema.kategorie }}</span>
            </div>
            <div v-if="!offeneGruppen.has(thema.id)" style="color: #6b7280; font-size: 0.8rem; margin-top: 0.25rem;">
              {{ thema.beschreibung.substring(0, 150) }}{{ thema.beschreibung.length > 150 ? '...' : '' }}
            </div>
          </div>
          <span style="color: #9ca3af; font-size: 1.2rem; margin-left: 0.5rem;">
            {{ offeneGruppen.has(thema.id) ? '▼' : '▶' }}
          </span>
        </div>
        <div v-if="offeneGruppen.has(thema.id)" style="border-top: 1px solid #e5e7eb;">
          <div style="padding: 0.75rem 1rem; background: #f9fafb; font-size: 0.85rem; color: #374151;">
            {{ thema.beschreibung }}
          </div>
          <table style="margin: 0; border-radius: 0;">
            <thead>
              <tr><th>Kurzbeschreibung</th><th>Risiko</th><th>Kategorie</th><th>Status</th></tr>
            </thead>
            <tbody>
              <tr v-for="f in thema.fundstellen" :key="f.id">
                <td><router-link :to="`/pruefung/${f.id}`">{{ f.kurzbeschreibung }}</router-link></td>
                <td><StatusBadge :status="f.risikostufe" /></td>
                <td style="font-size: 0.8rem; color: #6b7280;">{{ f.kategorie }}</td>
                <td><StatusBadge :status="f.pruef_status" /></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Clustering Debug -->
    <div v-if="ansicht === 'themen' && clusteringDebug" style="margin-bottom: 1rem;">
      <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 6px; padding: 0.6rem 1rem; font-size: 0.8rem; color: #374151;">
        <span style="font-weight: 600;">Clustering-Qualität:</span>
        {{ clusteringDebug.metriken.anzahl_risikothemen }} Risikothemen aus {{ clusteringDebug.metriken.anzahl_einzelfindings }} Einzelfindings
        &middot; Ø {{ clusteringDebug.metriken.durchschnittliche_fundstellen_pro_thema }} Evidence/Thema
        <span v-if="clusteringDebug.warnungen.length > 0" style="color: #b45309;">
          &middot; {{ clusteringDebug.warnungen.length }} Warnung{{ clusteringDebug.warnungen.length !== 1 ? 'en' : '' }}
        </span>
        <button
          style="background: none; border: none; color: #2563eb; cursor: pointer; font-size: 0.8rem; margin-left: 0.5rem; padding: 0; text-decoration: underline;"
          @click="debugOffen = !debugOffen"
        >{{ debugOffen ? 'Debug ausblenden' : 'Debug anzeigen' }}</button>
      </div>

      <div v-if="debugOffen" style="background: white; border: 1px solid #e5e7eb; border-radius: 6px; margin-top: 0.5rem; overflow: hidden;">
        <!-- Warnings -->
        <div v-if="clusteringDebug.warnungen.length > 0" style="padding: 0.75rem 1rem; border-bottom: 1px solid #e5e7eb;">
          <div style="font-weight: 600; font-size: 0.8rem; margin-bottom: 0.4rem; color: #b45309;">Warnungen</div>
          <div
            v-for="(w, i) in clusteringDebug.warnungen"
            :key="i"
            style="font-size: 0.78rem; color: #6b7280; padding: 0.15rem 0;"
            :style="{ color: w.typ === 'aehnliche_titel' ? '#7c3aed' : w.typ === 'mehrfach_zugeordnet' ? '#dc2626' : '#b45309' }"
          >
            <span v-if="w.typ === 'einzelne_fundstelle'">&#9888; {{ w.nachricht }}</span>
            <span v-else-if="w.typ === 'mehrfach_zugeordnet'">&#10060; {{ w.nachricht }}</span>
            <span v-else-if="w.typ === 'aehnliche_titel'">&#128279; {{ w.nachricht }}</span>
            <span v-else>{{ w.nachricht }}</span>
          </div>
        </div>

        <!-- Debug table -->
        <table style="margin: 0; border-radius: 0; font-size: 0.78rem;">
          <thead>
            <tr>
              <th>Thema</th>
              <th>Evidence</th>
              <th>Risiko</th>
              <th>Ähnliche Themen</th>
              <th>Warnungen</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in clusteringDebug.themen" :key="t.id">
              <td style="max-width: 250px;">{{ t.titel }}</td>
              <td style="text-align: center;">{{ t.anzahl_evidence }}</td>
              <td><StatusBadge :status="t.risikostufe" /></td>
              <td style="font-size: 0.75rem; color: #7c3aed;">
                {{ aehnlicheThemenFuer(t.titel).join(', ') || '—' }}
              </td>
              <td style="font-size: 0.75rem; color: #b45309;">
                {{ warnungenFuerThema(t.titel).join('; ') || '—' }}
              </td>
            </tr>
          </tbody>
        </table>
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
import type { Vertrag, Analyse, Fundstelle, GruppiertesErgebnis, RisikoThema, ClusteringDebug, FinalEditorialResult } from "../types";

const route = useRoute();
const vertrag = ref<Vertrag | null>(null);
const analysen = ref<Analyse[]>([]);
const fundstellen = ref<Fundstelle[]>([]);
const gruppiertesErgebnis = ref<GruppiertesErgebnis | null>(null);
const risikothemen = ref<RisikoThema[]>([]);
const clusteringDebug = ref<ClusteringDebug | null>(null);
const finalEditorial = ref<FinalEditorialResult | null>(null);
const debugOffen = ref(false);
const verworfeneOffen = ref(false);
const ansicht = ref<"final" | "themen" | "gruppiert" | "flat">("final");
const offeneGruppen = ref<Set<string>>(new Set());
let pollTimer: ReturnType<typeof setInterval> | null = null;

const laeuft = computed(() =>
  analysen.value.some(a =>
    a.status !== "Abgeschlossen" && a.status !== "Fehlgeschlagen"
  )
);

function risikoFarbe(risiko: string): string {
  switch (risiko) {
    case "Kritisch": return "#7c3aed";
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
  const [vRes, aRes, fRes, gRes, tRes] = await Promise.all([
    api.get(`/vertraege/${id}`),
    api.get(`/analysen/vertrag/${id}`),
    api.get(`/fundstellen/vertrag/${id}`),
    api.get(`/fundstellen/vertrag/${id}/gruppiert`).catch(() => ({ data: null })),
    api.get(`/risikothemen/vertrag/${id}`).catch(() => ({ data: [] })),
  ]);
  vertrag.value = vRes.data;
  analysen.value = aRes.data;
  fundstellen.value = fRes.data;
  if (gRes.data) {
    gruppiertesErgebnis.value = gRes.data;
  }
  risikothemen.value = tRes.data || [];
  // Load final editorial data
  try {
    const feRes = await api.get(`/risikothemen/vertrag/${id}/final`);
    finalEditorial.value = feRes.data;
  } catch {
    finalEditorial.value = null;
  }
  // Default to best available view
  if (finalEditorial.value && finalEditorial.value.metriken.hat_editorial) {
    ansicht.value = "final";
  } else if (risikothemen.value.length > 0) {
    ansicht.value = "themen";
    // Load debug data in background
    api.get(`/risikothemen/vertrag/${id}/debug`).then(r => {
      clusteringDebug.value = r.data;
    }).catch(() => {});
  } else if (gruppiertesErgebnis.value) {
    ansicht.value = "gruppiert";
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

function aehnlicheThemenFuer(titel: string): string[] {
  if (!clusteringDebug.value) return [];
  return clusteringDebug.value.aehnliche_themen
    .filter(p => p.thema_a === titel || p.thema_b === titel)
    .map(p => {
      const other = p.thema_a === titel ? p.thema_b : p.thema_a;
      return `${other} (${Math.round(p.aehnlichkeit * 100)}%)`;
    });
}

function warnungenFuerThema(titel: string): string[] {
  if (!clusteringDebug.value) return [];
  return clusteringDebug.value.warnungen
    .filter(w => w.thema === titel)
    .map(w => w.typ === 'einzelne_fundstelle' ? 'Nur 1 Fundstelle' : w.nachricht);
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
