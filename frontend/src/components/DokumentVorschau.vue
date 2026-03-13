<template>
  <div style="background: white; border: 1px solid #e5e7eb; border-radius: 6px; padding: 1rem; max-height: 500px; overflow-y: auto; white-space: pre-wrap; font-size: 0.9rem; line-height: 1.6;">
    <template v-if="text">{{ text }}</template>
    <span v-else style="color: #9ca3af;">Kein Text vorhanden.</span>
  </div>
</template>

<script setup lang="ts">
defineProps<{ text: string | null | undefined }>();
</script>
