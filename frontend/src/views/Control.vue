<script setup>
import { onMounted, ref } from "vue";
import { useToast } from "primevue/usetoast";
import { useConfirm } from "primevue/useconfirm";
import Button from "primevue/button";
import Slider from "primevue/slider";
import Tag from "primevue/tag";
import { api, useToastErrors } from "../api.js";

const toast = useToast();
const confirm = useConfirm();
const run = useToastErrors(toast);
const state = ref({ devices: [], zones: [], sequences: [] });
const loading = ref(false);
const levels = ref({});

async function refresh() {
  loading.value = true;
  const s = await run(() => api.get("/api/control"));
  if (s) {
    state.value = s;
    for (const d of s.devices) levels.value[d.ref] = d.level ?? (d.on ? 100 : 0);
  }
  loading.value = false;
}

async function send(body, refreshAfter = true) {
  const ok = await run(() => api.post("/api/control", body));
  if (ok && refreshAfter) setTimeout(refresh, 400);
}

const dev = (ref, body) => send({ kind: "device", target: ref, ...body });
const zone = (name, body) => send({ kind: "zone", target: name, ...body });

function allOff() {
  confirm.require({
    message: "Switch every light off?",
    header: "All off",
    icon: "pi pi-power-off",
    acceptLabel: "All off",
    rejectLabel: "Cancel",
    accept: () => send({ kind: "broadcast", switch: false }),
  });
}

function sequence(name, verb) {
  run(() => api.post(`/api/sequences/${encodeURIComponent(name)}/${verb}`), `${name}: ${verb}`);
}

onMounted(refresh);
</script>

<template>
  <div class="row" style="margin: 0.5rem 0 1rem">
    <Button label="All off" icon="pi pi-power-off" severity="danger" @click="allOff" />
    <span class="grow" />
    <Button icon="pi pi-refresh" text rounded :loading="loading" aria-label="Refresh" @click="refresh" />
  </div>

  <section v-if="state.zones.length">
    <h2 class="muted" style="font-size: 0.9rem; margin: 0 0 0.5rem">Zones</h2>
    <div v-for="z in state.zones" :key="z.name" class="card row nowrap">
      <strong class="grow ellipsis">{{ z.name }}</strong>
      <Button label="On" size="small" @click="zone(z.name, { switch: true })" />
      <Button label="Off" size="small" severity="secondary" @click="zone(z.name, { switch: false })" />
    </div>
  </section>

  <section>
    <h2 class="muted" style="font-size: 0.9rem; margin: 1rem 0 0.5rem">Devices</h2>
    <div v-for="d in state.devices" :key="d.ref" class="card">
      <div class="row nowrap">
        <strong class="grow ellipsis">{{ d.name }}</strong>
        <span class="muted">{{ d.type }}</span>
        <Tag :value="d.on ? 'on' : 'off'" :severity="d.on ? 'success' : 'secondary'" />
      </div>
      <div class="row" style="margin-top: 0.6rem">
        <Button label="On" size="small" @click="dev(d.ref, { switch: true })" />
        <Button label="Off" size="small" severity="secondary" @click="dev(d.ref, { switch: false })" />
        <template v-if="d.type !== 'relay'">
          <Slider
            v-model="levels[d.ref]"
            class="grow"
            style="margin-left: 0.5rem"
            :min="0"
            :max="100"
            @slideend="dev(d.ref, { level: levels[d.ref] })"
          />
          <span class="muted" style="width: 3em; text-align: right">{{ levels[d.ref] }}%</span>
        </template>
      </div>
      <div v-if="d.scenes && d.scenes.length" class="row" style="margin-top: 0.6rem">
        <span class="muted">Scenes</span>
        <Button
          v-for="s in d.scenes"
          :key="s"
          :label="String(s)"
          size="small"
          outlined
          @click="dev(d.ref, { scene: s })"
        />
      </div>
    </div>
  </section>

  <section v-if="state.sequences.length">
    <h2 class="muted" style="font-size: 0.9rem; margin: 1rem 0 0.5rem">Sequences</h2>
    <div v-for="s in state.sequences" :key="s" class="card row">
      <strong class="grow">{{ s }}</strong>
      <Button label="Run" size="small" icon="pi pi-play" @click="sequence(s, 'run')" />
      <Button label="Stop" size="small" icon="pi pi-stop" severity="secondary" @click="sequence(s, 'stop')" />
    </div>
  </section>
</template>
