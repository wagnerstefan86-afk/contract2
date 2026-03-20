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
      <!-- Metrics + filter bar -->
      <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 0.75rem;">
        <div style="background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 6px; padding: 0.45rem 0.75rem; font-size: 0.78rem; color: #1e40af;">
          <strong>{{ finalEditorial.metriken.anzahl_finale_themen_nachher }}</strong> Kernthemen
          &middot; {{ finalEditorial.metriken.anzahl_ausgewaehlte_evidenzen }} Evidenzen
        </div>
        <div style="display: flex; gap: 0.25rem; flex-wrap: wrap;">
          <button
            v-for="df in decisionFilters"
            :key="df.value"
            :style="{
              padding: '0.25rem 0.55rem',
              fontSize: '0.72rem',
              borderRadius: '999px',
              border: activeDecisionFilter === df.value ? '1px solid #2563eb' : '1px solid #d1d5db',
              background: activeDecisionFilter === df.value ? '#eff6ff' : 'white',
              color: activeDecisionFilter === df.value ? '#1d4ed8' : '#6b7280',
              cursor: 'pointer',
            }"
            @click="activeDecisionFilter = df.value"
          >{{ df.label }} <span v-if="df.count > 0" style="font-weight: 600;">({{ df.count }})</span></button>
        </div>
      </div>

      <!-- Final themes (sorted by risk then evidence count, filtered by decision) -->
      <div
        v-for="thema in filteredSortedThemen"
        :key="thema.id"
        :style="{ background: 'white', borderRadius: '6px', marginBottom: '0.5rem', overflow: 'hidden', border: '1px solid #e5e7eb', borderLeft: `4px solid ${risikoFarbe(thema.risikostufe)}` }"
      >
        <!-- HEADER — compact: badge + title + decision + arrow -->
        <router-link
          :to="`/pruefung/${thema.fundstellen[0]?.id || ''}`"
          style="display: flex; align-items: center; gap: 0.4rem; padding: 0.5rem 0.75rem; text-decoration: none; color: inherit; flex-wrap: wrap;"
        >
          <StatusBadge :status="thema.risikostufe" />
          <strong style="font-size: 0.92rem; color: #111827; flex: 1; min-width: 0;">{{ thema.titel }}</strong>
          <DecisionBadge :status="thema.decision_status || 'OPEN'" />
          <span style="color: #d1d5db; font-size: 0.85rem;">&rarr;</span>
        </router-link>

        <!-- PROBLEM — single muted line under header -->
        <div style="padding: 0 0.75rem 0.35rem; font-size: 0.8rem; color: #6b7280; line-height: 1.35; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;">
          {{ truncate(thema.problem_summary || thema.kurzbeschreibung, 160) }}
          <span style="color: #9ca3af; font-size: 0.7rem; margin-left: 0.35rem;">{{ thema.kategorie }} · {{ thema.fundstellen.length }} Evidenz{{ thema.fundstellen.length !== 1 ? 'en' : '' }}</span>
        </div>

        <!-- RECOMMENDATION — always visible, lightweight green strip -->
        <div style="padding: 0.35rem 0.75rem; background: #f0fdf4; border-top: 1px solid #dcfce7;">
          <div v-if="thema.recommendation_override" style="font-size: 0.78rem; color: #15803d; line-height: 1.3;">
            <span style="font-size: 0.6rem; color: #2563eb; background: #dbeafe; padding: 0 0.25rem; border-radius: 2px; margin-right: 0.25rem;">Manuell</span>
            {{ truncate(thema.recommendation_override, 140) }}
          </div>
          <ul v-else-if="thema.recommendation && thema.recommendation.length" style="margin: 0; padding-left: 1rem; list-style: disc;">
            <li
              v-for="(r, ri) in thema.recommendation.slice(0, 2)"
              :key="ri"
              style="font-size: 0.78rem; color: #15803d; line-height: 1.3; margin-bottom: 0.05rem;"
            >{{ truncate(r, 75) }}</li>
          </ul>
          <div v-else style="font-size: 0.78rem; color: #9ca3af;">Empfehlung wird generiert...</div>
        </div>

        <!-- NEGOTIATION — collapsed toggle, hidden if empty -->
        <div v-if="(thema.negotiation_override) || (thema.negotiation && thema.negotiation.length)" style="border-top: 1px solid #f3f4f6;">
          <button
            style="display: flex; align-items: center; gap: 0.25rem; width: 100%; padding: 0.3rem 0.75rem; background: none; border: none; cursor: pointer; font-size: 0.72rem; color: #9a3412;"
            @click.prevent="toggleVerhandlung(thema.id)"
          >
            <span>{{ offeneVerhandlungen.has(thema.id) ? '&#9660;' : '&#9654;' }}</span>
            <span>Verhandlung</span>
            <span v-if="thema.negotiation_override" style="font-size: 0.6rem; color: #2563eb; background: #dbeafe; padding: 0 0.25rem; border-radius: 2px; margin-left: 0.2rem;">Manuell</span>
          </button>
          <div v-if="offeneVerhandlungen.has(thema.id)" style="padding: 0 0.75rem 0.35rem;">
            <div v-if="thema.negotiation_override" style="font-size: 0.78rem; color: #9a3412; line-height: 1.3;">
              {{ truncate(thema.negotiation_override, 140) }}
            </div>
            <ul v-else style="margin: 0; padding-left: 1rem; list-style: disc;">
              <li
                v-for="(n, ni) in thema.negotiation.slice(0, 2)"
                :key="ni"
                style="font-size: 0.78rem; color: #9a3412; line-height: 1.3; margin-bottom: 0.05rem;"
              >{{ truncate(n, 75) }}</li>
            </ul>
          </div>
        </div>

        <!-- DECISION — ultra-compact inline row -->
        <div style="padding: 0.3rem 0.75rem; border-top: 1px solid #f3f4f6; display: flex; align-items: center; gap: 0.15rem;">
          <button
            v-for="ds in decisionStates"
            :key="ds.value"
            :style="{
              padding: '0.15rem 0.35rem',
              fontSize: '0.62rem',
              borderRadius: '3px',
              border: (thema.decision_status || 'OPEN') === ds.value ? `1px solid ${ds.activeColor}` : '1px solid #f3f4f6',
              background: (thema.decision_status || 'OPEN') === ds.value ? ds.activeBg : 'transparent',
              color: (thema.decision_status || 'OPEN') === ds.value ? ds.activeColor : '#d1d5db',
              cursor: 'pointer',
              fontWeight: (thema.decision_status || 'OPEN') === ds.value ? '600' : '400',
            }"
            @click.prevent="setDecision(thema.id, ds.value)"
          >{{ ds.label }}</button>
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

    <div v-else-if="ansicht === 'flat' || ansicht === 'gruppiert'" style="padding: 1.5rem; text-align: center; color: #9ca3af; font-size: 0.85rem;">
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
import DecisionBadge from "../components/DecisionBadge.vue";
import DokumentVorschau from "../components/DokumentVorschau.vue";
import type { Vertrag, Analyse, Fundstelle, GruppiertesErgebnis, RisikoThema, ClusteringDebug, FinalEditorialResult, DecisionStatus } from "../types";

const route = useRoute();
const vertrag = ref<Vertrag | null>(null);
const analysen = ref<Analyse[]>([]);
const gruppiertesErgebnis = ref<GruppiertesErgebnis | null>(null);

// Derive flat list from grouped data — same final-selected layer as grouped view
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
    case "Kritisch": return "#991b1b";
    case "Hoch": return "#dc2626";
    case "Mittel": return "#f59e0b";
    case "Niedrig": return "#9ca3af";
    default: return "#6b7280";
  }
}

const RISIKO_SORT_ORDER: Record<string, number> = {
  "Kritisch": 0,
  "Hoch": 1,
  "Mittel": 2,
  "Niedrig": 3,
};

const sortedThemen = computed(() => {
  if (!finalEditorial.value) return [];
  return [...finalEditorial.value.finale_themen].sort((a, b) => {
    const ra = RISIKO_SORT_ORDER[a.risikostufe] ?? 9;
    const rb = RISIKO_SORT_ORDER[b.risikostufe] ?? 9;
    if (ra !== rb) return ra - rb;
    return b.fundstellen.length - a.fundstellen.length;
  });
});

const offeneVerhandlungen = ref<Set<string>>(new Set());

function toggleVerhandlung(id: string) {
  const s = new Set(offeneVerhandlungen.value);
  if (s.has(id)) { s.delete(id); } else { s.add(id); }
  offeneVerhandlungen.value = s;
}

function truncate(text: string, max: number): string {
  if (!text) return "";
  if (text.length <= max) return text;
  return text.substring(0, max).replace(/\s+\S*$/, "") + "...";
}

// --- Decision layer ---

const decisionStates = [
  { value: "OPEN", label: "Offen", activeColor: "#6b7280", activeBg: "#f3f4f6" },
  { value: "IN_NEGOTIATION", label: "In Verhandlung", activeColor: "#92400e", activeBg: "#fffbeb" },
  { value: "ACCEPTED", label: "Akzeptiert", activeColor: "#1d4ed8", activeBg: "#eff6ff" },
  { value: "REJECTED", label: "Abgelehnt", activeColor: "#dc2626", activeBg: "#fef2f2" },
  { value: "CLOSED", label: "Geschlossen", activeColor: "#16a34a", activeBg: "#f0fdf4" },
];

const activeDecisionFilter = ref<string>("ALL");

const decisionFilters = computed(() => {
  const themen = sortedThemen.value;
  const counts: Record<string, number> = { ALL: themen.length };
  for (const t of themen) {
    const s = t.decision_status || "OPEN";
    counts[s] = (counts[s] || 0) + 1;
  }
  return [
    { value: "ALL", label: "Alle", count: counts.ALL },
    { value: "OPEN", label: "Offen", count: counts.OPEN || 0 },
    { value: "IN_NEGOTIATION", label: "In Verhandlung", count: counts.IN_NEGOTIATION || 0 },
    { value: "ACCEPTED", label: "Akzeptiert", count: counts.ACCEPTED || 0 },
    { value: "REJECTED", label: "Abgelehnt", count: counts.REJECTED || 0 },
    { value: "CLOSED", label: "Geschlossen", count: counts.CLOSED || 0 },
  ];
});

const filteredSortedThemen = computed(() => {
  if (activeDecisionFilter.value === "ALL") return sortedThemen.value;
  return sortedThemen.value.filter(t => (t.decision_status || "OPEN") === activeDecisionFilter.value);
});

async function setDecision(themaId: string, status: string) {
  try {
    await api.patch(`/risikothemen/${themaId}/decision`, { decision_status: status });
    // Update local state immediately
    if (finalEditorial.value) {
      const thema = finalEditorial.value.finale_themen.find(t => t.id === themaId);
      if (thema) {
        thema.decision_status = status as DecisionStatus;
      }
    }
  } catch (e) {
    console.error("Decision update failed:", e);
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
  const [vRes, aRes, gRes, tRes] = await Promise.all([
    api.get(`/vertraege/${id}`),
    api.get(`/analysen/vertrag/${id}`),
    api.get(`/fundstellen/vertrag/${id}/gruppiert`).catch(() => ({ data: null })),
    api.get(`/risikothemen/vertrag/${id}`).catch(() => ({ data: [] })),
  ]);
  vertrag.value = vRes.data;
  analysen.value = aRes.data;
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
