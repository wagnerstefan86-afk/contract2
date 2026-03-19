<template>
  <span :style="{ background: farbe, color: 'white', padding: '2px 8px', borderRadius: '4px', fontSize: '0.8rem' }">
    {{ status }}
  </span>
</template>

<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ status: string }>();

const farbe = computed(() => {
  const s = props.status;
  if (s === "Kritisch") return "#991b1b";
  if (s === "Hoch" || s === "Fehler" || s === "Fehlgeschlagen") return "#dc2626";
  if (s === "Mittel" || s === "Warnung") return "#f59e0b";
  if (s === "Niedrig" || s === "Bestätigt" || s === "Abgeschlossen" || s === "Analysiert") return "#16a34a";
  if (s === "Offen" || s === "Hochgeladen" || s === "Gestartet") return "#6366f1";
  if (s === "Zurückgestellt" || s === "Archiviert") return "#6b7280";
  if (s.includes("läuft") || s === "Konsolidierung" || s === "In Analyse") return "#2563eb";
  return "#6b7280";
});
</script>
