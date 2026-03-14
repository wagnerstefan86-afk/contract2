<template>
  <div style="max-width: 400px; margin: 4rem auto; padding: 2rem; background: white; border-radius: 8px;">
    <h1 style="margin-bottom: 1.5rem; text-align: center;">Registrieren</h1>

    <div v-if="erfolg" style="background: #f0fdf4; color: #166534; padding: 0.75rem; border-radius: 4px; margin-bottom: 1rem; font-size: 0.9rem;">
      Registrierung erfolgreich! Ihre Anmeldung muss erst durch einen Administrator freigegeben werden. Sie werden benachrichtigt, sobald Ihr Konto aktiv ist.
      <p style="margin-top: 0.75rem;"><router-link to="/anmelden">Zur Anmeldung</router-link></p>
    </div>

    <div v-if="fehler" style="background: #fef2f2; color: #991b1b; padding: 0.75rem; border-radius: 4px; margin-bottom: 1rem; font-size: 0.9rem;">
      {{ fehler }}
    </div>

    <form v-if="!erfolg" @submit.prevent="registrieren" style="display: flex; flex-direction: column; gap: 1rem;">
      <div>
        <label style="display: block; font-size: 0.85rem; color: #374151; margin-bottom: 0.25rem;">Name</label>
        <input
          v-model="name"
          type="text"
          required
          autocomplete="name"
          style="width: 100%; padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 4px; font-size: 0.9rem;"
        />
      </div>
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
        <label style="display: block; font-size: 0.85rem; color: #374151; margin-bottom: 0.25rem;">Passwort (mind. 6 Zeichen)</label>
        <input
          v-model="passwort"
          type="password"
          required
          minlength="6"
          autocomplete="new-password"
          style="width: 100%; padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 4px; font-size: 0.9rem;"
        />
      </div>
      <button
        type="submit"
        :disabled="loading"
        style="background: #2563eb; color: white; padding: 0.6rem; font-size: 0.95rem; border: none; border-radius: 6px; cursor: pointer;"
      >
        {{ loading ? 'Wird registriert...' : 'Registrieren' }}
      </button>
    </form>

    <p v-if="!erfolg" style="text-align: center; margin-top: 1.5rem; font-size: 0.85rem; color: #6b7280;">
      Bereits registriert?
      <router-link to="/anmelden">Anmelden</router-link>
    </p>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const name = ref("");
const email = ref("");
const passwort = ref("");
const loading = ref(false);
const fehler = ref<string | null>(null);
const erfolg = ref(false);

async function registrieren() {
  fehler.value = null;
  loading.value = true;
  try {
    await auth.register(name.value, email.value, passwort.value);
    erfolg.value = true;
  } catch (e: any) {
    fehler.value = auth.error;
  } finally {
    loading.value = false;
  }
}
</script>
