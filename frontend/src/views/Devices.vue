<script setup>
import { onMounted, ref } from "vue";
import { useToast } from "primevue/usetoast";
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import InputText from "primevue/inputtext";
import Select from "primevue/select";
import MultiSelect from "primevue/multiselect";
import Tag from "primevue/tag";
import { api, useToastErrors } from "../api.js";

const toast = useToast();
const run = useToastErrors(toast);
const rows = ref([]);
const types = ref([]);
const loading = ref(false);
const editing = ref(null);
const groups = Array.from({ length: 16 }, (_, i) => i);

async function refresh() {
  loading.value = true;
  const d = await run(() => api.get("/api/devices"));
  if (d) {
    rows.value = d.devices;
    types.value = d.types;
  }
  loading.value = false;
}

function edit(r) {
  editing.value = {
    line: r.line,
    address: r.address,
    name: r.name || "",
    type: r.type ?? r.gateway_type ?? null,
    groups: r.groups ?? r.gateway_groups ?? [],
    manageGroups: r.groups != null,
  };
}

async function save() {
  const e = editing.value;
  const body = { name: e.name, type: e.type };
  if (e.manageGroups) body.groups = e.groups;
  const ok = await run(() => api.put(`/api/devices/${e.line}/${e.address}`, body), "Saved to site file");
  if (ok) {
    editing.value = null;
    refresh();
  }
}

async function remove(r) {
  if (!confirm(`Remove ${r.name} (A${r.address}) from the site file?`)) return;
  if (await run(() => api.del(`/api/devices/${r.line}/${r.address}`), "Removed from site file")) refresh();
}

function blink(r) {
  run(() => api.post(`/api/devices/${r.line}/${r.address}/blink`), `Blinked A${r.address}`);
}

onMounted(refresh);
</script>

<template>
  <div class="row" style="margin: 0.5rem 0 1rem">
    <p class="muted grow" style="margin: 0">
      Names, types and groups are the site file's. Edits are written to the file; <em>Apply</em> pushes them.
    </p>
    <Button icon="pi pi-refresh" text rounded :loading="loading" aria-label="Refresh" @click="refresh" />
  </div>

  <div v-for="r in rows" :key="r.ref" class="card">
    <div class="row nowrap">
      <span class="muted" style="flex: 0 0 2.5em">A{{ r.ref }}</span>
      <strong class="grow ellipsis">{{ r.name }}</strong>
      <Button icon="pi pi-sun" text rounded aria-label="Blink" :disabled="!r.on_gateway" @click="blink(r)" />
      <Button icon="pi pi-pencil" text rounded aria-label="Edit" @click="edit(r)" />
      <Button icon="pi pi-trash" text rounded severity="danger" aria-label="Remove" :disabled="!r.in_site" @click="remove(r)" />
    </div>
    <div class="row muted" style="margin-top: 0.3rem; gap: 0.5rem 1rem">
      <span>{{ r.type ?? r.gateway_type ?? "?" }}</span>
      <span v-if="r.type && r.gateway_type && r.type !== r.gateway_type">gateway says {{ r.gateway_type }}</span>
      <span v-if="r.groups">groups {{ r.groups.join(", ") || "none" }}</span>
      <span v-else>groups {{ (r.gateway_groups || []).join(", ") || "none" }} (unmanaged)</span>
      <span v-if="r.product">{{ r.product }}</span>
      <span v-if="r.serial">#{{ r.serial }}</span>
    </div>
    <div v-if="r.on_gateway && r.in_site && r.gateway_name !== r.name" class="muted" style="margin-top: 0.3rem">
      gateway still has: {{ r.gateway_name }}
    </div>
    <div class="row" style="margin-top: 0.3rem">
      <Tag v-if="!r.in_site" value="not in site file" severity="warn" />
      <Tag v-if="!r.on_gateway" value="not on gateway" severity="danger" />
    </div>
  </div>

  <Dialog :visible="!!editing" modal :header="editing ? `Line ${editing.line} A${editing.address}` : ''" :style="{ width: 'min(22rem, 95vw)' }" @update:visible="editing = null">
    <template v-if="editing">
      <div class="field">
        <label>Name</label>
        <InputText v-model="editing.name" autofocus />
      </div>
      <div class="field">
        <label>Type (checked against the gateway)</label>
        <Select v-model="editing.type" :options="types" showClear placeholder="unchecked" />
      </div>
      <div class="field">
        <label><input type="checkbox" v-model="editing.manageGroups" /> Manage DALI groups</label>
        <MultiSelect v-model="editing.groups" :options="groups" :disabled="!editing.manageGroups" placeholder="none" />
      </div>
      <div class="row" style="justify-content: flex-end">
        <Button label="Cancel" text @click="editing = null" />
        <Button label="Save" @click="save" />
      </div>
    </template>
  </Dialog>
</template>
