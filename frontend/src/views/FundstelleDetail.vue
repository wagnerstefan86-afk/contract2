<template>
  <div v-if="f" style="max-width: 820px;">
    <!-- === HEADER — compact: badge + short title + decision === -->
    <div style="margin-bottom: 0.6rem;">
      <router-link :to="`/vertrag/${f.vertrag_id}`" style="color: #9ca3af; font-size: 0.78rem; text-decoration: none;">&larr; Vertrag</router-link>
      <div style="display: flex; align-items: center; gap: 0.4rem; margin-top: 0.35rem; flex-wrap: wrap;">
        <StatusBadge :status="displayRisikostufe" />
        <h1 style="margin: 0; font-size: 1.1rem; font-weight: 700; line-height: 1.25; color: #111827;">{{ displayTitel }}</h1>
        <DecisionBadge v-if="te" :status="currentDecisionStatus" />
      </div>
      <!-- Problem summary as subtitle, not a separate box -->
      <p v-if="displayProblemSummary && displayProblemSummary !== displayTitel" style="margin: 0.25rem 0 0; font-size: 0.85rem; color: #4b5563; line-height: 1.4; max-width: 680px;">{{ displayProblemSummary }}</p>
      <!-- Inline meta chips -->
      <div style="display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; margin-top: 0.3rem;">
        <span style="background: #f3f4f6; color: #6b7280; font-size: 0.65rem; padding: 0.05rem 0.4rem; border-radius: 3px;">{{ displayKategorie }}</span>
        <span v-if="f.evidence_page_from" style="color: #9ca3af; font-size: 0.72rem;">S. {{ f.evidence_page_from }}{{ f.evidence_page_to && f.evidence_page_to !== f.evidence_page_from ? '–' + f.evidence_page_to : '' }}</span>
        <span v-else-if="d && d.seite" style="color: #9ca3af; font-size: 0.72rem;">S. {{ d.seite }}{{ d.seite_unsicher ? ' (ca.)' : '' }}</span>
      </div>
    </div>

    <!-- === IMPACT — lightweight inline list, no heavy box === -->
    <div v-if="displayImpact.length" style="padding: 0.4rem 0.75rem; margin-bottom: 0.5rem; border-left: 3px solid #dc2626; background: #fef2f2; border-radius: 0 4px 4px 0;">
      <ul style="margin: 0; padding-left: 1rem; list-style: disc;">
        <li v-for="(item, i) in displayImpact.slice(0, 3)" :key="i" style="font-size: 0.82rem; color: #991b1b; line-height: 1.35; margin-bottom: 0.1rem;">{{ item }}</li>
      </ul>
    </div>

    <!-- === RECOMMENDATION — primary action block, strongest emphasis === -->
    <div style="background: #f0fdf4; padding: 0.6rem 0.85rem; border-radius: 6px; border-left: 4px solid #16a34a; margin-bottom: 0.5rem;">
      <div style="display: flex; align-items: center; gap: 0.3rem; margin-bottom: 0.25rem;">
        <h3 style="margin: 0; font-size: 0.78rem; font-weight: 700; color: #166534; text-transform: uppercase; letter-spacing: 0.03em;">Empfehlung</h3>
        <span v-if="te?.recommendation_override" style="font-size: 0.6rem; color: #2563eb; background: #dbeafe; padding: 0.05rem 0.3rem; border-radius: 3px;">Manuell</span>
      </div>
      <div v-if="te?.recommendation_override" style="font-size: 0.85rem; color: #15803d; line-height: 1.4; white-space: pre-wrap;">{{ te.recommendation_override }}</div>
      <ul v-else-if="effectiveRecommendation.length" style="margin: 0; padding-left: 1.1rem; list-style: disc;">
        <li v-for="(item, i) in effectiveRecommendation.slice(0, 3)" :key="i" style="margin-bottom: 0.1rem; line-height: 1.35; font-size: 0.85rem; color: #15803d;">{{ item }}</li>
      </ul>
      <p v-else style="margin: 0; color: #6b7280; font-size: 0.85rem;">Klausel im Detail prüfen und ggf. nachverhandeln.</p>
      <div v-if="te?.recommendation_override && effectiveRecommendation.length" style="margin-top: 0.35rem; font-size: 0.72rem; color: #6b7280;">
        KI-Original: {{ effectiveRecommendation.slice(0, 2).join(' · ') }}
      </div>
    </div>

    <!-- === NEGOTIATION — secondary emphasis, slightly lighter === -->
    <div v-if="hasNegotiation" style="padding: 0.5rem 0.85rem; border-radius: 6px; border-left: 4px solid #ea580c; background: #fff7ed; margin-bottom: 0.5rem;">
      <div style="display: flex; align-items: center; gap: 0.3rem; margin-bottom: 0.25rem;">
        <h3 style="margin: 0; font-size: 0.78rem; font-weight: 600; color: #9a3412; text-transform: uppercase; letter-spacing: 0.03em;">Verhandlung</h3>
        <span v-if="te?.negotiation_override" style="font-size: 0.6rem; color: #2563eb; background: #dbeafe; padding: 0.05rem 0.3rem; border-radius: 3px;">Manuell</span>
      </div>
      <div v-if="te?.negotiation_override" style="font-size: 0.85rem; color: #9a3412; line-height: 1.4; white-space: pre-wrap;">{{ te.negotiation_override }}</div>
      <ul v-else-if="effectiveNegotiation.length" style="margin: 0; padding-left: 1.1rem; list-style: disc;">
        <li v-for="(item, i) in effectiveNegotiation.slice(0, 3)" :key="i" style="margin-bottom: 0.1rem; line-height: 1.35; font-size: 0.85rem; color: #9a3412;">{{ item }}</li>
      </ul>
      <div v-if="te?.negotiation_override && effectiveNegotiation.length" style="margin-top: 0.35rem; font-size: 0.72rem; color: #92400e;">
        KI-Original: {{ effectiveNegotiation.slice(0, 2).join(' · ') }}
      </div>
    </div>

    <!-- === ALTERNATIV + BIETERFRAGE — combined collapsible if either exists === -->
    <div v-if="displayAlternativ || displayBieterfrage" style="margin-bottom: 0.5rem;">
      <button
        style="display: flex; align-items: center; gap: 0.3rem; width: 100%; padding: 0.35rem 0.75rem; background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 5px; cursor: pointer; font-size: 0.78rem; color: #6b7280;"
        :style="{ borderRadius: formulierungenOffen ? '5px 5px 0 0' : '5px' }"
        @click="formulierungenOffen = !formulierungenOffen"
      >
        <span>{{ formulierungenOffen ? '&#9660;' : '&#9654;' }}</span>
        <span>Alternativformulierung &amp; Bieterfrage</span>
      </button>
      <div v-if="formulierungenOffen" style="border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 5px 5px; padding: 0.5rem 0.85rem; display: flex; flex-direction: column; gap: 0.5rem;">
        <div v-if="displayAlternativ">
          <div style="font-size: 0.68rem; color: #1e40af; text-transform: uppercase; letter-spacing: 0.03em; font-weight: 600; margin-bottom: 0.15rem;">Alternativformulierung</div>
          <p style="margin: 0; line-height: 1.4; font-size: 0.82rem; font-style: italic; color: #374151;">{{ displayAlternativ }}</p>
        </div>
        <div v-if="displayBieterfrage">
          <div style="font-size: 0.68rem; color: #5b21b6; text-transform: uppercase; letter-spacing: 0.03em; font-weight: 600; margin-bottom: 0.15rem;">Bieterfrage</div>
          <p style="margin: 0; line-height: 1.4; font-size: 0.82rem; color: #374151;">{{ displayBieterfrage }}</p>
        </div>
      </div>
    </div>

    <!-- === UNIFIED WORKFLOW — single decision + review block === -->
    <div style="background: white; border: 1px solid #e5e7eb; border-radius: 6px; padding: 0.6rem 0.85rem; margin-bottom: 0.75rem;">
      <!-- Decision status row -->
      <div style="display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.4rem;">
        <span style="font-size: 0.72rem; color: #6b7280; font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em;">Status</span>
        <div style="display: flex; gap: 0.2rem;">
          <button
            v-for="ds in decisionStates"
            :key="ds.value"
            :style="{
              padding: '0.2rem 0.5rem',
              borderRadius: '4px',
              border: currentDecisionStatus === ds.value ? `1.5px solid ${ds.activeColor}` : '1px solid #e5e7eb',
              background: currentDecisionStatus === ds.value ? ds.activeBg : 'white',
              color: currentDecisionStatus === ds.value ? ds.activeColor : '#9ca3af',
              fontWeight: currentDecisionStatus === ds.value ? '600' : '400',
              cursor: 'pointer',
              fontSize: '0.72rem',
            }"
            @click="setDecisionStatus(ds.value)"
          >{{ ds.label }}</button>
        </div>
        <!-- Prüfstatus inline -->
        <span style="font-size: 0.72rem; color: #6b7280; font-weight: 600; margin-left: auto; text-transform: uppercase; letter-spacing: 0.03em;">Prüfung</span>
        <div style="display: flex; gap: 0.15rem;">
          <button
            v-for="s in statusOptionen"
            :key="s"
            :style="{
              background: f.pruef_status === s ? '#374151' : '#f3f4f6',
              color: f.pruef_status === s ? 'white' : '#9ca3af',
              padding: '0.2rem 0.45rem',
              borderRadius: '4px',
              border: 'none',
              cursor: 'pointer',
              fontSize: '0.68rem',
            }"
            @click="setStatus(s)"
          >{{ s }}</button>
        </div>
      </div>
      <!-- Comment + overrides (compact) -->
      <div style="display: flex; gap: 0.35rem; align-items: center; margin-bottom: 0.3rem;">
        <input
          v-model="decisionComment"
          placeholder="Kommentar..."
          style="flex: 1; padding: 0.25rem 0.4rem; border: 1px solid #e5e7eb; border-radius: 4px; font-size: 0.78rem; font-family: inherit;"
          @keyup.enter="saveDecision"
        >
        <button
          style="background: #2563eb; color: white; padding: 0.25rem 0.65rem; border: none; border-radius: 4px; cursor: pointer; font-size: 0.75rem; white-space: nowrap;"
          @click="saveDecision"
        >Speichern</button>
      </div>
      <!-- Override toggle -->
      <button
        style="background: none; border: none; color: #9ca3af; cursor: pointer; font-size: 0.7rem; padding: 0; text-decoration: underline;"
        @click="overridesOffen = !overridesOffen"
      >{{ overridesOffen ? 'Überschreibungen ausblenden' : 'Empfehlung / Verhandlung überschreiben' }}</button>
      <div v-if="overridesOffen" style="display: flex; flex-direction: column; gap: 0.3rem; margin-top: 0.3rem;">
        <textarea
          v-model="recommendationOverride"
          placeholder="Empfehlung überschreiben (leer = KI)"
          style="width: 100%; padding: 0.3rem 0.4rem; border: 1px solid #e5e7eb; border-radius: 4px; min-height: 36px; font-family: inherit; font-size: 0.78rem; resize: vertical;"
        ></textarea>
        <textarea
          v-model="negotiationOverride"
          placeholder="Verhandlung überschreiben (leer = KI)"
          style="width: 100%; padding: 0.3rem 0.4rem; border: 1px solid #e5e7eb; border-radius: 4px; min-height: 36px; font-family: inherit; font-size: 0.78rem; resize: vertical;"
        ></textarea>
      </div>
    </div>

    <!-- === SECONDARY: Evidence + Analysis (collapsible, muted) === -->
    <div style="margin-bottom: 0.4rem;">
      <button
        style="display: flex; align-items: center; gap: 0.3rem; width: 100%; padding: 0.35rem 0.75rem; background: none; border: 1px solid #e5e7eb; border-radius: 5px; cursor: pointer; color: #9ca3af; font-size: 0.75rem;"
        :style="{ borderRadius: kontextOffen ? '5px 5px 0 0' : '5px' }"
        @click="kontextOffen = !kontextOffen"
      >
        <span>{{ kontextOffen ? '&#9660;' : '&#9654;' }}</span>
        <span>Textstelle &amp; Kontext</span>
      </button>
      <div v-if="kontextOffen" style="border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 5px 5px; padding: 0.6rem 0.85rem; display: flex; flex-direction: column; gap: 0.6rem;">
        <div v-if="f.scope_text" style="border-left: 3px solid #2563eb; padding-left: 0.6rem;">
          <div style="font-size: 0.68rem; color: #9ca3af; margin-bottom: 0.15rem;">
            {{ f.scope_type === 'clause_block' ? 'Klauselblock' : 'Absatz' }}
            <span v-if="f.evidence_heading_path"> — {{ f.evidence_heading_path }}</span>
          </div>
          <div style="white-space: pre-wrap; line-height: 1.5; font-size: 0.82rem;" v-html="highlightedScopeText"></div>
        </div>
        <div v-if="f.trigger_spans && f.trigger_spans.length > 0" style="border-left: 3px solid #f59e0b; padding-left: 0.6rem;">
          <div style="font-size: 0.68rem; color: #92400e; margin-bottom: 0.15rem;">Relevante Passagen</div>
          <ul style="margin: 0; padding-left: 1rem;">
            <li v-for="(span, i) in f.trigger_spans" :key="i" style="margin-bottom: 0.15rem; line-height: 1.35; font-size: 0.82rem;">{{ span }}</li>
          </ul>
        </div>
        <div v-if="!f.scope_text" style="border-left: 3px solid #f59e0b; padding-left: 0.6rem;">
          <div style="font-size: 0.68rem; color: #92400e; margin-bottom: 0.15rem;">Betroffene Textstelle</div>
          <div style="white-space: pre-wrap; line-height: 1.5; font-size: 0.82rem;">{{ f.textstelle }}</div>
        </div>
        <div v-if="d && d.kontext && !f.scope_text" style="padding-left: 0.6rem;">
          <div style="font-size: 0.68rem; color: #9ca3af; margin-bottom: 0.15rem;">Umgebender Kontext</div>
          <div style="white-space: pre-wrap; line-height: 1.4; font-size: 0.82rem; color: #4b5563; max-height: 250px; overflow-y: auto;" v-html="highlightedContext"></div>
        </div>
      </div>
    </div>

    <div v-if="f.erklaerung" style="margin-bottom: 0.4rem;">
      <button
        style="display: flex; align-items: center; gap: 0.3rem; width: 100%; padding: 0.35rem 0.75rem; background: none; border: 1px solid #e5e7eb; border-radius: 5px; cursor: pointer; color: #9ca3af; font-size: 0.75rem;"
        :style="{ borderRadius: begruendungOffen ? '5px 5px 0 0' : '5px' }"
        @click="begruendungOffen = !begruendungOffen"
      >
        <span>{{ begruendungOffen ? '&#9660;' : '&#9654;' }}</span>
        <span>Analysebegründung</span>
      </button>
      <div v-if="begruendungOffen" style="border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 5px 5px; padding: 0.6rem 0.85rem;">
        <div style="white-space: pre-wrap; line-height: 1.45; font-size: 0.82rem; color: #4b5563;">{{ f.erklaerung }}</div>
      </div>
    </div>

    <!-- === METADATA — single muted line === -->
    <div style="padding: 0.35rem 0; font-size: 0.68rem; color: #9ca3af; display: flex; gap: 1rem; flex-wrap: wrap;">
      <span v-if="f.evidence_page_from">S. {{ f.evidence_page_from }}{{ f.evidence_page_to && f.evidence_page_to !== f.evidence_page_from ? '–' + f.evidence_page_to : '' }}</span>
      <span v-else-if="d && d.seite">S. {{ d.seite }}{{ d.seite_unsicher ? ' (ca.)' : '' }}</span>
      <span v-if="f.evidence_heading_path">{{ f.evidence_heading_path }}</span>
      <span v-else-if="d && d.ueberschrift">{{ d.ueberschrift }}</span>
      <span>{{ f.quelle_pass || 'unbekannt' }}</span>
      <span>{{ datum(f.erstellt_am) }}</span>
    </div>

    <!-- === DEBUG — demoted, tiny, collapsed === -->
    <details v-if="debugTrace" style="margin-top: 0.25rem; font-size: 0.62rem; color: #d1d5db;">
      <summary style="cursor: pointer; color: #d1d5db;">Debug</summary>
      <pre style="margin-top: 0.15rem; padding: 0.3rem; background: #fafafa; border: 1px solid #f3f4f6; border-radius: 3px; white-space: pre-wrap; font-family: monospace; color: #9ca3af;">{{ debugTrace }}</pre>
    </details>
  </div>
  <div v-else style="padding: 2rem; text-align: center; color: #9ca3af;">Wird geladen...</div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { useRoute } from "vue-router";
import api from "../api/client";
import StatusBadge from "../components/StatusBadge.vue";
import DecisionBadge from "../components/DecisionBadge.vue";
import type { Fundstelle, FundstelleDetail as FundstelleDetailType, ThemaEditorialContext } from "../types";

const route = useRoute();
const f = ref<Fundstelle | null>(null);
const kommentar = ref("");
const statusOptionen = ["Offen", "Bestätigt", "Abgelehnt", "Zurückgestellt"];

// Collapsible sections
const kontextOffen = ref(false);
const begruendungOffen = ref(false);
const overridesOffen = ref(false);
const formulierungenOffen = ref(false);

const d = computed<FundstelleDetailType | null>(() => f.value?.detail ?? null);
const te = computed<ThemaEditorialContext | null>(() => f.value?.thema_editorial ?? null);

// Decision layer state
const decisionComment = ref("");
const recommendationOverride = ref("");
const negotiationOverride = ref("");
const currentDecisionStatus = ref("OPEN");

const decisionStates = [
  { value: "OPEN", label: "Offen", activeColor: "#6b7280", activeBg: "#f3f4f6" },
  { value: "IN_NEGOTIATION", label: "In Verhandlung", activeColor: "#92400e", activeBg: "#fffbeb" },
  { value: "ACCEPTED", label: "Akzeptiert", activeColor: "#1d4ed8", activeBg: "#eff6ff" },
  { value: "REJECTED", label: "Abgelehnt", activeColor: "#dc2626", activeBg: "#fef2f2" },
  { value: "CLOSED", label: "Geschlossen", activeColor: "#16a34a", activeBg: "#f0fdf4" },
];

function setDecisionStatus(status: string) {
  currentDecisionStatus.value = status;
}

async function saveDecision() {
  // Save decision on theme (if linked)
  if (te.value?.thema_id) {
    try {
      await api.patch(`/risikothemen/${te.value.thema_id}/decision`, {
        decision_status: currentDecisionStatus.value,
        decision_comment: decisionComment.value || null,
        recommendation_override: recommendationOverride.value || null,
        negotiation_override: negotiationOverride.value || null,
      });
    } catch (e) {
      console.error("Decision save failed:", e);
    }
  }
  // Also persist prüf_kommentar on the fundstelle
  if (kommentar.value !== (f.value?.pruef_kommentar || "")) {
    await api.patch(`/fundstellen/${route.params.id}`, { pruef_kommentar: kommentar.value });
  }
  await laden();
}

// --- Helper: truncate to N words ---
function truncateWords(text: string, maxWords: number): string {
  const words = text.split(/\s+/).filter(Boolean);
  if (words.length <= maxWords) return text;
  return words.slice(0, maxWords).join(" ") + "…";
}

// --- Display computeds with strict resolution chains ---

// TITLE resolution: theme editorial title → theme title → truncated problem_summary → truncated kurzbeschreibung
// [DEBUG:title] — source tracked in debugTrace
const displayTitel = computed(() => {
  // 1. Parent theme title from editorial (theme.titel passed through)
  if (te.value?.titel) return truncateWords(te.value.titel, 8);
  // 2. Truncated problem_summary as title fallback
  if (te.value?.problem_summary) return truncateWords(te.value.problem_summary, 8);
  // 3. Theme kurzbeschreibung (editorial summary)
  if (te.value?.kurzbeschreibung) return truncateWords(te.value.kurzbeschreibung, 8);
  // 4. Last resort: finding kurzbeschreibung, hard-truncated
  const kb = f.value?.kurzbeschreibung || "";
  return truncateWords(kb, 8);
});

// Track which source provided the title
const titleSource = computed(() => {
  if (te.value?.titel) return "theme.titel";
  if (te.value?.problem_summary) return "theme.final_editorial.problem_summary (truncated)";
  if (te.value?.kurzbeschreibung) return "theme.final_editorial.kurzbeschreibung (truncated)";
  return "fundstelle.kurzbeschreibung (last resort)";
});

// RISIKOSTUFE: prefer theme-level over finding-level
const displayRisikostufe = computed(() => {
  return te.value?.risikostufe || f.value?.risikostufe || "Mittel";
});

// KATEGORIE: prefer theme-level over finding-level
const displayKategorie = computed(() => {
  return te.value?.kategorie || f.value?.kategorie || "";
});

// PROBLEM SUMMARY resolution: editorial problem_summary → editorial kurzbeschreibung → finding kurzbeschreibung
// [DEBUG:problem_summary]
const displayProblemSummary = computed(() => {
  if (te.value?.problem_summary) return te.value.problem_summary;
  if (te.value?.kurzbeschreibung) return te.value.kurzbeschreibung;
  return f.value?.kurzbeschreibung || "";
});

const problemSummarySource = computed(() => {
  if (te.value?.problem_summary) return "theme.final_editorial.problem_summary";
  if (te.value?.kurzbeschreibung) return "theme.final_editorial.kurzbeschreibung";
  return "fundstelle.kurzbeschreibung (fallback)";
});

// IMPACT: only from editorial
const displayImpact = computed(() => te.value?.impact?.length ? te.value.impact : []);

// RECOMMENDATION resolution (AI content, before override check):
// 1. theme.final_editorial.recommendation (array)
// 2. theme.final_editorial.kurzbeschreibung as single-item (legacy: editorial had no structured recommendation)
// 3. finding.empfehlung (legacy string from detection pass)
// [DEBUG:recommendation]
const effectiveRecommendation = computed<string[]>(() => {
  if (te.value?.recommendation?.length) return te.value.recommendation;
  if (f.value?.empfehlung) return [f.value.empfehlung];
  return [];
});

const recommendationSource = computed(() => {
  if (te.value?.recommendation_override) return "OVERRIDE: theme.recommendation_override";
  if (te.value?.recommendation?.length) return "theme.final_editorial.recommendation";
  if (f.value?.empfehlung) return "fundstelle.empfehlung (legacy)";
  return "FALLBACK: generic message";
});

// NEGOTIATION resolution (AI content, before override check):
// 1. theme.final_editorial.negotiation (array)
// 2. theme.final_editorial.verhandlungsargumente (legacy array)
// 3. finding.detail.verhandlungsargumente (legacy string)
// [DEBUG:negotiation]
const effectiveNegotiation = computed<string[]>(() => {
  if (te.value?.negotiation?.length) return te.value.negotiation;
  if (te.value?.verhandlungsargumente?.length) return te.value.verhandlungsargumente;
  if (d.value?.verhandlungsargumente) return [d.value.verhandlungsargumente];
  return [];
});

const negotiationSource = computed(() => {
  if (te.value?.negotiation_override) return "OVERRIDE: theme.negotiation_override";
  if (te.value?.negotiation?.length) return "theme.final_editorial.negotiation";
  if (te.value?.verhandlungsargumente?.length) return "theme.final_editorial.verhandlungsargumente (legacy)";
  if (d.value?.verhandlungsargumente) return "fundstelle.detail.verhandlungsargumente (legacy)";
  return "HIDDEN: no negotiation data";
});

// Whether negotiation section should be visible
const hasNegotiation = computed(() => {
  return !!(te.value?.negotiation_override) || effectiveNegotiation.value.length > 0;
});

const displayAlternativ = computed(() => {
  return te.value?.alternativformulierung || d.value?.alternativformulierung || "";
});

const displayBieterfrage = computed(() => {
  return te.value?.bieterfrage || d.value?.bieterfrage || "";
});

// DEBUG TRACE: shows which data source populated each key field
const debugTrace = computed(() => {
  if (!f.value) return "";
  return [
    `title: ${titleSource.value}`,
    `  → "${displayTitel.value}"`,
    `problem_summary: ${problemSummarySource.value}`,
    `  → "${displayProblemSummary.value?.substring(0, 80)}${(displayProblemSummary.value?.length || 0) > 80 ? '...' : ''}"`,
    `recommendation: ${recommendationSource.value}`,
    `  → [${effectiveRecommendation.value.length} items]`,
    `negotiation: ${negotiationSource.value}`,
    `  → [${effectiveNegotiation.value.length} items]`,
    `risikostufe: ${te.value?.risikostufe ? 'theme' : 'fundstelle'} → "${displayRisikostufe.value}"`,
    `kategorie: ${te.value?.kategorie ? 'theme' : 'fundstelle'} → "${displayKategorie.value}"`,
    `thema_editorial present: ${!!te.value}`,
    `thema_id: ${te.value?.thema_id || 'none'}`,
  ].join("\n");
});

const highlightedScopeText = computed(() => {
  if (!f.value?.scope_text) return "";
  const scopeText = f.value.scope_text;
  const spans = f.value.trigger_spans;
  if (!spans || spans.length === 0) return escapeHtml(scopeText);

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
  const teData = res.data.thema_editorial;
  if (teData) {
    currentDecisionStatus.value = teData.decision_status || "OPEN";
    decisionComment.value = teData.decision_comment || "";
    recommendationOverride.value = teData.recommendation_override || "";
    negotiationOverride.value = teData.negotiation_override || "";
    // Auto-expand overrides section if overrides exist
    if (teData.recommendation_override || teData.negotiation_override) {
      overridesOffen.value = true;
    }
  }
  // [DEBUG] Log resolved data sources to console
  console.debug("[FundstelleDetail] Data source trace:", {
    title: titleSource.value,
    problem_summary: problemSummarySource.value,
    recommendation: recommendationSource.value,
    negotiation: negotiationSource.value,
    thema_editorial_present: !!teData,
    thema_id: teData?.thema_id,
  });
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
