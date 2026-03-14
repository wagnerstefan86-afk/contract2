<template>
  <nav style="background: #1e293b; color: white; padding: 0.75rem 1.5rem; display: flex; gap: 2rem; align-items: center;">
    <strong style="font-size: 1.1rem;">Vertragsprüfung</strong>

    <template v-if="auth.isAuthenticated">
      <router-link to="/" style="color: #94a3b8;">Vertragsübersicht</router-link>
      <router-link to="/pruefung" style="color: #94a3b8;">Prüfung</router-link>
      <router-link v-if="auth.isAdmin" to="/einstellungen" style="color: #94a3b8;">Einstellungen</router-link>
      <router-link v-if="auth.isAdmin" to="/benutzerverwaltung" style="color: #94a3b8;">Benutzerverwaltung</router-link>

      <div style="margin-left: auto; display: flex; align-items: center; gap: 1rem;">
        <span style="color: #94a3b8; font-size: 0.85rem;">
          {{ auth.user?.name }}
          <span v-if="auth.isAdmin" style="background: #7c3aed; color: white; font-size: 0.7rem; padding: 0.1rem 0.4rem; border-radius: 999px; margin-left: 0.25rem;">Admin</span>
        </span>
        <button
          @click="abmelden"
          style="background: transparent; color: #94a3b8; border: 1px solid #475569; font-size: 0.8rem; padding: 0.25rem 0.6rem; cursor: pointer; border-radius: 4px;"
        >Abmelden</button>
      </div>
    </template>
  </nav>
</template>

<script setup lang="ts">
import { useRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";

const router = useRouter();
const auth = useAuthStore();

function abmelden() {
  auth.logout();
  router.push("/anmelden");
}
</script>
