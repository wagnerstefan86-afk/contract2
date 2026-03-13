<template>
  <div style="background: #1e293b; color: #e2e8f0; border-radius: 6px; padding: 1rem; font-family: monospace; font-size: 0.85rem; max-height: 400px; overflow-y: auto;">
    <div v-if="eintraege.length === 0" style="color: #94a3b8;">Keine Protokolleinträge vorhanden.</div>
    <div v-for="e in eintraege" :key="e.id" style="margin-bottom: 0.25rem;">
      <span :style="{ color: ebenenFarbe(e.ebene) }">[{{ e.ebene }}]</span>
      <span style="color: #64748b; margin: 0 0.5rem;">{{ zeitformat(e.erstellt_am) }}</span>
      {{ e.nachricht }}
    </div>
  </div>
</template>

<script setup lang="ts">
import type { ProtokollEintrag } from "../types";

defineProps<{ eintraege: ProtokollEintrag[] }>();

function ebenenFarbe(ebene: string): string {
  if (ebene === "Fehler") return "#f87171";
  if (ebene === "Warnung") return "#fbbf24";
  return "#4ade80";
}

function zeitformat(iso: string): string {
  return new Date(iso).toLocaleTimeString("de-DE");
}
</script>
