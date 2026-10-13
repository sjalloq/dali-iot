<script setup>
import { computed, onMounted, ref } from "vue";
import { useToast } from "primevue/usetoast";
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import InputText from "primevue/inputtext";
import InputNumber from "primevue/inputnumber";
import Select from "primevue/select";
import MultiSelect from "primevue/multiselect";
import ToggleSwitch from "primevue/toggleswitch";
import SelectButton from "primevue/selectbutton";
import Tag from "primevue/tag";
import { api, useToastErrors } from "../api.js";

const toast = useToast();
const run = useToastErrors(toast);
const data = ref({ schedules: [], zones: [], devices: [] });
const editing = ref(null);
const original = ref(null);

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const ACTIONS = ["on", "off", "level", "scene"];
const groups = Array.from({ length: 16 }, (_, i) => i);
const deviceOptions = computed(() => data.value.devices.map((d) => ({ label: `${d.name} (A${d.ref})`, value: d.ref })));

async function refresh() {
  const d = await run(() => api.get("/api/schedules"));
  if (d) data.value = d;
}

function describeAction(s) {
  if (s.switch !== undefined) return s.switch ? "on" : "off";
  if (s.level !== undefined) return `level ${s.level}%` + (s.fade ? ` over ${s.fade}s` : "");
  if (s.scene !== undefined) return `scene ${s.scene}`;
  return "features";
}
function describeTargets(s) {
  const parts = [];
  for (const r of s.devices || []) {
    const d = data.value.devices.find((x) => String(x.ref) === String(r));
    parts.push(d ? d.name : `A${r}`);
  }
  for (const z of s.zones || []) parts.push(`zone ${z}`);
  for (const g of s.groups || []) parts.push(`group ${g}`);
  for (const l of s.broadcast || []) parts.push(`line ${l}`);
  return parts.join(", ") || "—";
}

function toForm(s) {
  const action = s.switch !== undefined ? (s.switch ? "on" : "off") : s.level !== undefined ? "level" : s.scene !== undefined ? "scene" : "features";
  return {
    name: s.name || "",
    at: s.at || "sunset",
    devices: (s.devices || []).map(String),
    zones: s.zones || [],
    groups: s.groups || [],
    broadcast: s.broadcast || [],
    action,
    level: s.level ?? 100,
    fade: s.fade ?? 0,
    scene: s.scene ?? 0,
    features: s.features,
    everyDay: !s.days,
    days: s.days || [...DAYS],
    enabled: s.enabled !== false,
  };
}

function fromForm(f) {
  const out = { name: f.name, at: f.at, enabled: f.enabled };
  if (f.devices.length) out.devices = f.devices.map((r) => (/^\d+$/.test(r) ? Number(r) : r));
  if (f.zones.length) out.zones = f.zones;
  if (f.groups.length) out.groups = f.groups;
  if (f.broadcast.length) out.broadcast = f.broadcast;
  if (f.action === "on") out.switch = true;
  else if (f.action === "off") out.switch = false;
  else if (f.action === "level") {
    out.level = f.level;
    if (f.fade) out.fade = f.fade;
  } else if (f.action === "scene") out.scene = f.scene;
  else out.features = f.features;
  if (!f.everyDay) out.days = DAYS.filter((d) => f.days.includes(d));
  return out;
}

function add() {
  original.value = null;
  editing.value = toForm({});
}
function edit(s) {
  original.value = s.name;
  editing.value = toForm(s);
}

async function save() {
  const body = fromForm(editing.value);
  const ok = await run(
    () => (original.value ? api.put(`/api/schedules/${encodeURIComponent(original.value)}`, body) : api.post("/api/schedules", body)),
    "Saved to site file",
  );
  if (ok) {
    editing.value = null;
    refresh();
  }
}

async function remove(s) {
  if (!confirm(`Delete schedule "${s.name}" from the site file?`)) return;
  if (await run(() => api.del(`/api/schedules/${encodeURIComponent(s.name)}`), "Deleted")) refresh();
}

onMounted(refresh);
</script>

<template>
  <div class="row" style="margin: 0.5rem 0 1rem">
    <p class="muted grow" style="margin: 0">Schedules live in the site file. <em>Apply</em> pushes them to the gateway.</p>
    <Button label="Add" icon="pi pi-plus" @click="add" />
  </div>

  <div v-for="s in data.schedules" :key="s.name" class="card">
    <div class="row">
      <strong class="grow">{{ s.name }}</strong>
      <Tag v-if="s.enabled === false" value="disabled" severity="secondary" />
      <Button icon="pi pi-pencil" text rounded aria-label="Edit" @click="edit(s)" />
      <Button icon="pi pi-trash" text rounded severity="danger" aria-label="Delete" @click="remove(s)" />
    </div>
    <div class="muted">
      at <strong>{{ s.at }}</strong> → {{ describeAction(s) }} → {{ describeTargets(s) }}
      <span v-if="s.days"> · {{ s.days.join(" ") }}</span>
      <span v-if="s.months"> · {{ s.months.join(" ") }}</span>
    </div>
  </div>
  <p v-if="!data.schedules.length" class="muted">No schedules yet.</p>

  <Dialog :visible="!!editing" modal :header="original ? 'Edit schedule' : 'New schedule'" :style="{ width: 'min(26rem, 95vw)' }" @update:visible="editing = null">
    <template v-if="editing">
      <div class="field"><label>Name</label><InputText v-model="editing.name" /></div>
      <div class="field">
        <label>When — HH:MM, sunrise, sunset, sunset-0:30, sunrise+1:00</label>
        <InputText v-model="editing.at" />
      </div>
      <div class="field"><label>Devices</label><MultiSelect v-model="editing.devices" :options="deviceOptions" optionLabel="label" optionValue="value" placeholder="none" filter /></div>
      <div class="field"><label>Zones</label><MultiSelect v-model="editing.zones" :options="data.zones" placeholder="none" /></div>
      <div class="field"><label>DALI groups</label><MultiSelect v-model="editing.groups" :options="groups" placeholder="none" /></div>
      <div class="field"><label>Action</label><SelectButton v-model="editing.action" :options="ACTIONS" :allowEmpty="false" /></div>
      <div v-if="editing.action === 'level'" class="row" style="margin-bottom: 0.75rem">
        <div class="field grow"><label>Level %</label><InputNumber v-model="editing.level" :min="0" :max="100" /></div>
        <div class="field grow"><label>Fade s</label><InputNumber v-model="editing.fade" :min="0" :maxFractionDigits="1" /></div>
      </div>
      <div v-if="editing.action === 'scene'" class="field"><label>Scene</label><InputNumber v-model="editing.scene" :min="0" :max="15" /></div>
      <div class="field">
        <label class="row"><ToggleSwitch v-model="editing.everyDay" /> Every day</label>
        <SelectButton v-if="!editing.everyDay" v-model="editing.days" :options="DAYS" multiple />
      </div>
      <div class="field"><label class="row"><ToggleSwitch v-model="editing.enabled" /> Enabled</label></div>
      <div class="row" style="justify-content: flex-end">
        <Button label="Cancel" text @click="editing = null" />
        <Button label="Save" @click="save" />
      </div>
    </template>
  </Dialog>
</template>
