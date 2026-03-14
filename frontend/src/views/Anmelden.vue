<template>
  <div style="max-width: 400px; margin: 4rem auto; padding: 2rem; background: white; border-radius: 8px;">
    <h1 style="margin-bottom: 1.5rem; text-align: center;">Anmelden</h1>

    <div v-if="fehler" style="background: #fef2f2; color: #991b1b; padding: 0.75rem; border-radius: 4px; margin-bottom: 1rem; font-size: 0.9rem;">
      {{ fehler }}
    </div>

    <form @submit.prevent="anmelden" style="display: flex; flex-direction: column; gap: 1rem;">
      <div>
        <label style="display: block; font-size: 0.85rem; color: #374151; margin-bottom: 0.25rem;">E-Mail</label>
        <input
          v-model="email"
          type="email"
          required
          autocomplete="email"
          style="width: 100%; padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 4px; font-size: 0.9rem;"
        />
      </div>
      <div>
        <label style="display: block; font-size: 0.85rem; color: #374151; margin-bottom: 0.25rem;">Passwort</label>
        <input
          v-model="passwort"
          type="password"
          required
          autocomplete="current-password"
          style="width: 100%; padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 4px; font-size: 0.9rem;"
        />
      </div>
      <button
        type="submit"
        :disabled="loading"
        style="background: #2563eb; color: white; padding: 0.6rem; font-size: 0.95rem; border: none; border-radius: 6px; cursor: pointer;"
      >
        {{ loading ? 'Wird angemeldet...' : 'Anmelden' }}
      </button>
    </form>

    <p style="text-align: center; margin-top: 1.5rem; font-size: 0.85rem; color: #6b7280;">
      Noch kein Konto?
      <router-link to="/registrieren">Registrieren</router-link>
    </p>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";

const router = useRouter();
const auth = useAuthStore();
const email = ref("");
const passwort = ref("");
const loading = ref(false);
const fehler = ref<string | null>(null);

async function anmelden() {
  fehler.value = null;
  loading.value = true;
  try {
    await auth.login(email.value, passwort.value);
    router.push("/");
  } catch (e: any) {
    fehler.value = auth.error;
  } finally {
    loading.value = false;
  }
}
</script>
