<template>
  <div v-if="f" style="max-width: 860px;">
    <!-- Header -->
    <div style="margin-bottom: 1.25rem;">
      <router-link :to="`/vertrag/${f.vertrag_id}`" style="color: #6b7280; font-size: 0.85rem;">Zurück zum Vertrag</router-link>
      <div style="display: flex; align-items: center; gap: 0.5rem; margin-top: 0.5rem;">
        <StatusBadge :status="f.risikostufe" />
        <h1 style="margin: 0; font-size: 1.25rem; line-height: 1.3;">{{ displayTitel }}</h1>
      </div>
      <p style="margin: 0.35rem 0 0; color: #374151; font-size: 0.95rem; line-height: 1.5;">{{ displayProblemSummary }}</p>
      <div style="display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; margin-top: 0.35rem;">
        <span style="color: #6b7280; font-size: 0.8rem;">{{ f.kategorie }}</span>
        <span v-if="d && d.seite" style="color: #9ca3af; font-size: 0.8rem;">
          | Seite {{ d.seite }}{{ d.seite_unsicher ? ' (ca.)' : '' }}
        </span>
        <span v-if="f.evidence_heading_path" style="color: #9ca3af; font-size: 0.8rem;">
          | {{ f.evidence_heading_path.substring(0, 60) }}{{ f.evidence_heading_path.length > 60 ? '...' : '' }}
        </span>
        <span style="color: #9ca3af; font-size: 0.8rem;">| {{ f.pruef_status }}</span>
      </div>
    </div>

    <!-- Impact -->
    <div v-if="displayImpact.length" style="background: #fef2f2; padding: 0.75rem 1rem; border-radius: 6px; border-left: 4px solid #dc2626; margin-bottom: 1rem;">
      <h3 style="margin: 0 0 0.4rem; font-size: 0.85rem; font-weight: 600; color: #991b1b; text-transform: uppercase; letter-spacing: 0.03em;">Auswirkungen</h3>
      <ul style="margin: 0; padding-left: 1.2rem; list-style: disc;">
        <li v-for="(item, i) in displayImpact" :key="i" style="margin-bottom: 0.2rem; line-height: 1.4; font-size: 0.9rem; color: #1f2937;">{{ item }}</li>
      </ul>
    </div>

    <!-- Action Block: Recommendation + Negotiation (always visible) -->
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1.25rem;">
      <!-- Recommendation -->
      <div style="background: #f0fdf4; padding: 0.75rem 1rem; border-radius: 6px; border-left: 4px solid #16a34a;">
        <h3 style="margin: 0 0 0.4rem; font-size: 0.85rem; font-weight: 600; color: #166534; text-transform: uppercase; letter-spacing: 0.03em;">Empfehlung</h3>
        <ul v-if="displayRecommendation.length" style="margin: 0; padding-left: 1.2rem; list-style: disc;">
          <li v-for="(item, i) in displayRecommendation" :key="i" style="margin-bottom: 0.2rem; line-height: 1.4; font-size: 0.9rem; color: #1f2937;">{{ item }}</li>
        </ul>
        <p v-else style="margin: 0; color: #6b7280; font-size: 0.9rem;">Klausel im Detail prüfen und ggf. nachverhandeln.</p>
      </div>
      <!-- Negotiation -->
      <div style="background: #fff7ed; padding: 0.75rem 1rem; border-radius: 6px; border-left: 4px solid #ea580c;">
        <h3 style="margin: 0 0 0.4rem; font-size: 0.85rem; font-weight: 600; color: #9a3412; text-transform: uppercase; letter-spacing: 0.03em;">Verhandlung</h3>
        <ul v-if="displayNegotiation.length" style="margin: 0; padding-left: 1.2rem; list-style: disc;">
          <li v-for="(item, i) in displayNegotiation" :key="i" style="margin-bottom: 0.2rem; line-height: 1.4; font-size: 0.9rem; color: #1f2937;">{{ item }}</li>
        </ul>
        <p v-else style="margin: 0; color: #6b7280; font-size: 0.9rem;">Marktübliche Regelung als Gegenvorschlag einbringen.</p>
      </div>
    </div>

    <!-- Alternativformulierung (if available, shown directly) -->
    <div v-if="displayAlternativ" style="background: #eff6ff; padding: 0.75rem 1rem; border-radius: 6px; border-left: 4px solid #2563eb; margin-bottom: 1rem;">
      <h3 style="margin: 0 0 0.4rem; font-size: 0.85rem; font-weight: 600; color: #1e40af; text-transform: uppercase; letter-spacing: 0.03em;">Alternativformulierung</h3>
      <p style="margin: 0; line-height: 1.5; font-size: 0.9rem; font-style: italic; color: #1f2937;">{{ displayAlternativ }}</p>
    </div>

    <!-- Bieterfrage (if available, shown directly) -->
    <div v-if="displayBieterfrage" style="background: #faf5ff; padding: 0.75rem 1rem; border-radius: 6px; border-left: 4px solid #7c3aed; margin-bottom: 1.25rem;">
      <h3 style="margin: 0 0 0.4rem; font-size: 0.85rem; font-weight: 600; color: #5b21b6; text-transform: uppercase; letter-spacing: 0.03em;">Bieterfrage</h3>
      <p style="margin: 0; line-height: 1.5; font-size: 0.9rem; color: #1f2937;">{{ displayBieterfrage }}</p>
    </div>

    <!-- Tab navigation (secondary content only) -->
    <div style="display: flex; gap: 0; border-bottom: 2px solid #e5e7eb; margin-bottom: 1rem;">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        :style="{
          padding: '0.5rem 1rem',
          border: 'none',
          borderBottom: activeTab === tab.key ? '2px solid #2563eb' : '2px solid transparent',
          marginBottom: '-2px',
          background: 'transparent',
          color: activeTab === tab.key ? '#2563eb' : '#6b7280',
          fontWeight: activeTab === tab.key ? '600' : '400',
          cursor: 'pointer',
          fontSize: '0.9rem',
        }"
        @click="activeTab = tab.key"
      >{{ tab.label }}</button>
    </div>

    <!-- Tab: Textstelle & Kontext -->
    <div v-if="activeTab === 'textstelle'" style="display: flex; flex-direction: column; gap: 1rem;">
      <!-- Paragraph / clause context (primary evidence) -->
      <div v-if="f.scope_text" style="background: white; padding: 1rem; border-radius: 6px; border-left: 4px solid #2563eb;">
        <h3 style="margin: 0 0 0.5rem; font-size: 0.95rem; color: #1e40af;">
          {{ f.scope_type === 'clause_block' ? 'Klauselblock-Kontext' : 'Absatz-Kontext' }}
          <span v-if="f.evidence_heading_path" style="font-weight: normal; color: #6b7280; font-size: 0.8rem; margin-left: 0.5rem;">{{ f.evidence_heading_path }}</span>
        </h3>
        <div style="white-space: pre-wrap; line-height: 1.6; font-size: 0.95rem;" v-html="highlightedScopeText"></div>
      </div>

      <!-- Trigger spans listed separately -->
      <div v-if="f.trigger_spans && f.trigger_spans.length > 0" style="background: #fffbeb; border-left: 4px solid #f59e0b; padding: 1rem; border-radius: 4px;">
        <h3 style="margin: 0 0 0.5rem; font-size: 0.95rem; color: #92400e;">Relevante Passagen</h3>
        <ul style="margin: 0; padding-left: 1.2rem;">
          <li v-for="(span, i) in f.trigger_spans" :key="i" style="margin-bottom: 0.4rem; line-height: 1.5; font-size: 0.9rem;">
            {{ span }}
          </li>
        </ul>
      </div>

      <!-- Fallback: legacy textstelle if no scope_text -->
      <div v-if="!f.scope_text" style="background: #fffbeb; border-left: 4px solid #f59e0b; padding: 1rem; border-radius: 4px;">
        <h3 style="margin: 0 0 0.5rem; font-size: 0.95rem; color: #92400e;">Betroffene Textstelle</h3>
        <div style="white-space: pre-wrap; line-height: 1.6; font-size: 0.95rem;">{{ f.textstelle }}</div>
      </div>

      <!-- Legacy context from detail enrichment -->
      <div v-if="d && d.kontext && !f.scope_text" style="background: white; padding: 1rem; border-radius: 6px;">
        <h3 style="margin: 0 0 0.5rem; font-size: 0.95rem; color: #374151;">Umgebender Kontext</h3>
        <div style="white-space: pre-wrap; line-height: 1.5; font-size: 0.9rem; color: #374151; max-height: 400px; overflow-y: auto;" v-html="highlightedContext"></div>
      </div>

      <div style="background: #f9fafb; padding: 0.75rem 1rem; border-radius: 6px;">
        <h3 style="margin: 0 0 0.5rem; font-size: 0.85rem; color: #6b7280;">Referenzen</h3>
        <div style="display: flex; gap: 1.5rem; flex-wrap: wrap; font-size: 0.85rem;">
          <div v-if="f.evidence_page_from"><strong>Seite:</strong> {{ f.evidence_page_from }}{{ f.evidence_page_to && f.evidence_page_to !== f.evidence_page_from ? '–' + f.evidence_page_to : '' }}</div>
          <div v-else-if="d && d.seite"><strong>Seite:</strong> {{ d.seite }}{{ d.seite_unsicher ? ' (ca.)' : '' }}</div>
          <div v-if="f.evidence_heading_path"><strong>Klausel:</strong> {{ f.evidence_heading_path }}</div>
          <div v-else-if="d && d.ueberschrift"><strong>Klausel:</strong> {{ d.ueberschrift }}</div>
          <div v-if="d && d.absatz_referenzen && d.absatz_referenzen.length"><strong>Absätze:</strong> {{ d.absatz_referenzen.join(', ') }}</div>
          <div v-if="d && d.segment_ids && d.segment_ids.length"><strong>Segmente:</strong> {{ d.segment_ids.join(', ') }}</div>
        </div>
      </div>
    </div>

    <!-- Tab: Bewertung -->
    <div v-if="activeTab === 'bewertung'" style="display: flex; flex-direction: column; gap: 1rem;">
      <div style="background: white; padding: 1rem; border-radius: 6px;">
        <h3 style="margin: 0 0 0.75rem; font-size: 0.95rem; color: #374151;">Prüfstatus</h3>
        <div style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
          <button
            v-for="s in statusOptionen"
            :key="s"
            :style="{
              background: f.pruef_status === s ? '#2563eb' : '#e5e7eb',
              color: f.pruef_status === s ? 'white' : '#1a1a1a',
              padding: '0.5rem 1rem',
              borderRadius: '6px',
              border: 'none',
              cursor: 'pointer',
            }"
            @click="setStatus(s)"
          >{{ s }}</button>
        </div>
      </div>

      <div style="background: white; padding: 1rem; border-radius: 6px;">
        <h3 style="margin: 0 0 0.5rem; font-size: 0.95rem; color: #374151;">Prüfkommentar</h3>
        <textarea
          v-model="kommentar"
          placeholder="Kommentar des Prüfers (optional)"
          style="width: 100%; padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 4px; min-height: 100px; font-family: inherit; font-size: 0.9rem;"
        ></textarea>
        <button
          style="background: #2563eb; color: white; margin-top: 0.5rem; padding: 0.5rem 1rem; border: none; border-radius: 6px; cursor: pointer;"
          @click="speichern"
        >Kommentar speichern</button>
      </div>
    </div>

    <!-- Tab: Nachweise -->
    <div v-if="activeTab === 'nachweise'" style="display: flex; flex-direction: column; gap: 1rem;">
      <div style="background: #f9fafb; padding: 1rem; border-radius: 6px;">
        <h3 style="margin: 0 0 0.5rem; font-size: 0.85rem; color: #6b7280;">Pipeline-Quellen</h3>
        <div style="font-size: 0.85rem; color: #374151;">
          <p><strong>Quelle:</strong> {{ f.quelle_pass || 'unbekannt' }}</p>
          <p><strong>Erstellt:</strong> {{ datum(f.erstellt_am) }}</p>
        </div>
      </div>

      <div v-if="f.zusammenfuehrung" style="background: #f9fafb; padding: 1rem; border-radius: 6px;">
        <h3 style="margin: 0 0 0.5rem; font-size: 0.85rem; color: #6b7280;">Konsolidierung</h3>
        <div style="font-size: 0.85rem;">
          <p><strong>Rohkandidaten:</strong> {{ f.zusammenfuehrung.anzahl_roh_kandidaten || 1 }}</p>
          <p><strong>Status:</strong> {{ f.zusammenfuehrung.ueberlebt_als || 'unbekannt' }}</p>
          <div v-if="f.zusammenfuehrung.zusammengefuehrte_quellen && f.zusammenfuehrung.zusammengefuehrte_quellen.length > 1">
            <p style="margin-bottom: 0.25rem;"><strong>Zusammengeführte Quellen:</strong></p>
            <ul style="margin: 0; padding-left: 1.5rem;">
              <li v-for="(q, i) in f.zusammenfuehrung.zusammengefuehrte_quellen" :key="i" style="margin-bottom: 0.25rem;">
                {{ q.kurzbeschreibung }} ({{ q.quelle_pass }}, {{ q.status }})
              </li>
            </ul>
          </div>
        </div>
      </div>

      <div v-if="d" style="background: #f9fafb; padding: 1rem; border-radius: 6px;">
        <h3 style="margin: 0 0 0.5rem; font-size: 0.85rem; color: #6b7280;">Positionsdetails</h3>
        <div style="font-size: 0.85rem;">
          <p v-if="d.seite"><strong>Seite:</strong> {{ d.seite }}{{ d.seite_unsicher ? ' (geschätzt)' : '' }}</p>
          <p v-if="d.ueberschrift"><strong>Nächste Überschrift:</strong> {{ d.ueberschrift }}</p>
          <p v-if="d.absatz_referenzen && d.absatz_referenzen.length"><strong>Absätze:</strong> {{ d.absatz_referenzen.join(', ') }}</p>
          <p v-if="d.segment_ids && d.segment_ids.length"><strong>Segmente:</strong> {{ d.segment_ids.join(', ') }}</p>
          <p v-if="d.position_im_text >= 0"><strong>Zeichenposition:</strong> {{ d.position_im_text }}</p>
        </div>
      </div>
    </div>
  </div>
  <div v-else style="padding: 2rem; text-align: center; color: #6b7280;">Wird geladen...</div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { useRoute } from "vue-router";
import api from "../api/client";
import StatusBadge from "../components/StatusBadge.vue";
import type { Fundstelle, FundstelleDetail as FundstelleDetailType, ThemaEditorialContext } from "../types";

const route = useRoute();
const f = ref<Fundstelle | null>(null);
const kommentar = ref("");
const statusOptionen = ["Offen", "Bestätigt", "Abgelehnt", "Zurückgestellt"];
const activeTab = ref("textstelle");

const tabs = [
  { key: "textstelle", label: "Textstelle & Kontext" },
  { key: "bewertung", label: "Bewertung" },
  { key: "nachweise", label: "Nachweise" },
];

const d = computed<FundstelleDetailType | null>(() => f.value?.detail ?? null);
const te = computed<ThemaEditorialContext | null>(() => f.value?.thema_editorial ?? null);

// Display title: prefer theme editorial title, fallback to truncated kurzbeschreibung
const displayTitel = computed(() => {
  if (te.value?.titel) return te.value.titel;
  const kb = f.value?.kurzbeschreibung || "";
  // Truncate to ~8 words if too long
  const words = kb.split(/\s+/);
  if (words.length <= 8) return kb;
  return words.slice(0, 8).join(" ") + "…";
});

// Problem summary: prefer theme editorial, fallback to erklaerung first sentence
const displayProblemSummary = computed(() => {
  if (te.value?.problem_summary) return te.value.problem_summary;
  // Fallback: kurzbeschreibung (full, since title is now short)
  return f.value?.kurzbeschreibung || "";
});

// Impact bullets: from theme editorial
const displayImpact = computed(() => te.value?.impact?.length ? te.value.impact : []);

// Recommendation bullets: from theme editorial, fallback to empfehlung as single bullet
const displayRecommendation = computed(() => {
  if (te.value?.recommendation?.length) return te.value.recommendation;
  if (f.value?.empfehlung) return [f.value.empfehlung];
  return [];
});

// Negotiation bullets: from theme editorial, fallback to verhandlungsargumente
const displayNegotiation = computed(() => {
  if (te.value?.negotiation?.length) return te.value.negotiation;
  if (te.value?.verhandlungsargumente?.length) return te.value.verhandlungsargumente;
  if (d.value?.verhandlungsargumente) return [d.value.verhandlungsargumente];
  return [];
});

// Alternativformulierung
const displayAlternativ = computed(() => {
  return te.value?.alternativformulierung || d.value?.alternativformulierung || "";
});

// Bieterfrage
const displayBieterfrage = computed(() => {
  return te.value?.bieterfrage || d.value?.bieterfrage || "";
});

const highlightedScopeText = computed(() => {
  if (!f.value?.scope_text) return "";
  const scopeText = f.value.scope_text;
  const spans = f.value.trigger_spans;
  if (!spans || spans.length === 0) return escapeHtml(scopeText);

  // Highlight each trigger span within scope_text
  let result = scopeText;
  const markers: Array<{ start: number; end: number }> = [];
  for (const span of spans) {
    let searchFrom = 0;
    let idx = result.indexOf(span, searchFrom);
    while (idx >= 0) {
      markers.push({ start: idx, end: idx + span.length });
      searchFrom = idx + span.length;
      idx = result.indexOf(span, searchFrom);
    }
  }
  if (markers.length === 0) return escapeHtml(scopeText);

  // Sort by start position, merge overlapping
  markers.sort((a, b) => a.start - b.start);
  const merged: Array<{ start: number; end: number }> = [markers[0]];
  for (let i = 1; i < markers.length; i++) {
    const last = merged[merged.length - 1];
    if (markers[i].start <= last.end) {
      last.end = Math.max(last.end, markers[i].end);
    } else {
      merged.push(markers[i]);
    }
  }

  // Build HTML with highlights
  let html = "";
  let pos = 0;
  for (const m of merged) {
    html += escapeHtml(result.substring(pos, m.start));
    html += `<mark style="background: #fef08a; padding: 0 2px;">${escapeHtml(result.substring(m.start, m.end))}</mark>`;
    pos = m.end;
  }
  html += escapeHtml(result.substring(pos));
  return html;
});

const highlightedContext = computed(() => {
  if (!d.value?.kontext || !f.value?.textstelle) return d.value?.kontext || "";
  const ctx = d.value.kontext;
  const needle = f.value.textstelle;
  const idx = ctx.indexOf(needle);
  if (idx >= 0) {
    const before = escapeHtml(ctx.substring(0, idx));
    const match = escapeHtml(ctx.substring(idx, idx + needle.length));
    const after = escapeHtml(ctx.substring(idx + needle.length));
    return `${before}<mark style="background: #fef08a; padding: 0 2px;">${match}</mark>${after}`;
  }
  return escapeHtml(ctx);
});

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\n/g, "<br>");
}

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

function datum(iso: string): string {
  return new Date(iso).toLocaleDateString("de-DE", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

onMounted(laden);
</script>
