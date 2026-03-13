<template>
  <div>
    <h1>Prüfung — Offene Fundstellen</h1>

    <table v-if="fundstellen.length > 0" style="margin-top: 1rem;">
      <thead>
        <tr><th>Kurzbeschreibung</th><th>Kategorie</th><th>Risiko</th><th>Vertrag</th><th></th></tr>
      </thead>
      <tbody>
        <tr v-for="f in fundstellen" :key="f.id">
          <td>{{ f.kurzbeschreibung }}</td>
          <td>{{ f.kategorie }}</td>
          <td><StatusBadge :status="f.risikostufe" /></td>
          <td>{{ f.vertrag_id.substring(0, 8) }}...</td>
          <td><router-link :to="`/pruefung/${f.id}`">Prüfen</router-link></td>
        </tr>
      </tbody>
    </table>

    <div v-else style="background: white; padding: 2rem; border-radius: 6px; text-align: center; color: #6b7280; margin-top: 1rem;">
      Keine offenen Fundstellen vorhanden.
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from "vue";
import api from "../api/client";
import StatusBadge from "../components/StatusBadge.vue";
import type { Fundstelle } from "../types";

const fundstellen = ref<Fundstelle[]>([]);

onMounted(async () => {
  const res = await api.get("/fundstellen/offen");
  fundstellen.value = res.data;
});
</script>
