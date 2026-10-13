<script setup>
import { computed, onMounted, ref } from "vue";
import { useToast } from "primevue/usetoast";
import { useConfirm } from "primevue/useconfirm";
import Button from "primevue/button";
import Checkbox from "primevue/checkbox";
import Tag from "primevue/tag";
import { api, useToastErrors } from "../api.js";

const toast = useToast();
const confirm = useConfirm();
const run = useToastErrors(toast);
const prune = ref(false);
const changes = ref([]);
const loading = ref(false);
const result = ref(null);

const real = computed(() => changes.value.filter((c) => c.applies));
const errors = computed(() => changes.value.filter((c) => c.op === "error"));

const SEVERITY = { create: "success", update: "info", rename: "info", groups: "info", delete: "danger", error: "danger", note: "secondary" };

async function plan() {
  loading.value = true;
  result.value = null;
  const p = await run(() => api.get(`/api/plan?prune=${prune.value}`));
  if (p) changes.value = p.changes;
  loading.value = false;
}

function apply() {
  confirm.require({
    header: "Apply to gateway",
    message: `Apply ${real.value.length} change(s)${prune.value ? ", including deletions" : ""}?`,
    icon: "pi pi-cloud-upload",
    acceptLabel: "Apply",
    rejectLabel: "Cancel",
    accept: async () => {
      loading.value = true;
      const r = await run(() => api.post("/api/apply", { prune: prune.value }), "Applied");
      loading.value = false;
      if (r) {
        result.value = r;
        plan();
      }
    },
  });
}

onMounted(plan);
</script>

<template>
  <div class="row" style="margin: 0.5rem 0 1rem">
    <label class="row"><Checkbox v-model="prune" binary /> Prune (delete what is not in the site file)</label>
    <span class="grow" />
    <Button label="Plan" icon="pi pi-refresh" severity="secondary" :loading="loading" @click="plan" />
    <Button label="Apply" icon="pi pi-cloud-upload" :disabled="!real.length || loading" @click="apply" />
  </div>

  <p v-if="!changes.length && !loading" class="muted">No changes: the gateway matches the site file.</p>

  <div v-for="(c, i) in changes" :key="i" class="card row" style="margin-bottom: 0.4rem; padding: 0.5rem 0.75rem">
    <Tag :value="c.op" :severity="SEVERITY[c.op] || 'secondary'" style="width: 5em; justify-content: center" />
    <div class="grow">
      <div>{{ c.what }}</div>
      <div class="muted">{{ c.detail }}</div>
    </div>
  </div>

  <p v-if="errors.length" class="muted">{{ errors.length }} error(s): those entries are left untouched.</p>

  <div v-if="result" class="card">
    <h3>Applied {{ result.applied.length }} change(s)</h3>
    <pre class="plan">{{ result.applied.map((c) => `${c.op} ${c.what}`).join("\n") || "nothing" }}</pre>
  </div>
</template>
