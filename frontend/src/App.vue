<template>
  <div id="app">
    <Navigation />
    <main style="max-width: 1200px; margin: 0 auto; padding: 1rem;">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import Navigation from "./components/Navigation.vue";
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: system-ui, -apple-system, sans-serif; background: #f5f5f5; color: #1a1a1a; }
a { color: #2563eb; text-decoration: none; }
a:hover { text-decoration: underline; }
button {
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.9rem;
}
table { width: 100%; border-collapse: collapse; background: white; border-radius: 6px; overflow: hidden; }
th, td { padding: 0.75rem 1rem; text-align: left; border-bottom: 1px solid #e5e7eb; }
th { background: #f9fafb; font-weight: 600; }
</style>
