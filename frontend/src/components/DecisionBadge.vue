<template>
  <span :style="{ background: bg, color: fg, padding: '2px 8px', borderRadius: '999px', fontSize: '0.7rem', fontWeight: '600', letterSpacing: '0.02em', border: `1px solid ${border}`, whiteSpace: 'nowrap' }">
    {{ label }}
  </span>
</template>

<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ status: string }>();

const LABELS: Record<string, string> = {
  OPEN: "Offen",
  IN_NEGOTIATION: "In Verhandlung",
  ACCEPTED: "Akzeptiert",
  REJECTED: "Abgelehnt",
  CLOSED: "Geschlossen",
};

const COLORS: Record<string, { bg: string; fg: string; border: string }> = {
  OPEN:            { bg: "#f3f4f6", fg: "#6b7280", border: "#d1d5db" },
  IN_NEGOTIATION:  { bg: "#fffbeb", fg: "#92400e", border: "#fcd34d" },
  ACCEPTED:        { bg: "#eff6ff", fg: "#1d4ed8", border: "#93c5fd" },
  REJECTED:        { bg: "#fef2f2", fg: "#dc2626", border: "#fca5a5" },
  CLOSED:          { bg: "#f0fdf4", fg: "#16a34a", border: "#86efac" },
};

const label = computed(() => LABELS[props.status] || props.status);
const colors = computed(() => COLORS[props.status] || COLORS.OPEN);
const bg = computed(() => colors.value.bg);
const fg = computed(() => colors.value.fg);
const border = computed(() => colors.value.border);
</script>
