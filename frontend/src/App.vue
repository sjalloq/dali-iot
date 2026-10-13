<script setup>
import { onMounted, ref } from "vue";
import Tabs from "primevue/tabs";
import TabList from "primevue/tablist";
import Tab from "primevue/tab";
import TabPanels from "primevue/tabpanels";
import TabPanel from "primevue/tabpanel";
import Toast from "primevue/toast";
import ConfirmDialog from "primevue/confirmdialog";
import Button from "primevue/button";
import Control from "./views/Control.vue";
import Devices from "./views/Devices.vue";
import Schedules from "./views/Schedules.vue";
import Apply from "./views/Apply.vue";
import { api } from "./api.js";

const TABS = ["control", "devices", "schedules", "apply"];
const params = new URLSearchParams(location.search);
const fromUrl = params.get("tab");
const tab = ref(TABS.includes(fromUrl) ? fromUrl : localStorage.getItem("tab") || "control");

// Phones get the Control view only: no tab bar, nothing that edits the site
// file or the gateway. ?full=1 forces the full page on a small screen.
const narrow = window.matchMedia("(max-width: 640px)");
const phone = ref(narrow.matches && params.get("full") !== "1");
narrow.addEventListener("change", (e) => (phone.value = e.matches && params.get("full") !== "1"));
const gateway = ref("");
const dark = ref(
  localStorage.getItem("dark") === "1" ||
    (localStorage.getItem("dark") === null && window.matchMedia("(prefers-color-scheme: dark)").matches),
);

function applyDark() {
  document.documentElement.classList.toggle("dark", dark.value);
  localStorage.setItem("dark", dark.value ? "1" : "0");
}
function toggleDark() {
  dark.value = !dark.value;
  applyDark();
}
function remember(v) {
  tab.value = v;
  localStorage.setItem("tab", v);
}

onMounted(async () => {
  applyDark();
  try {
    const info = await api.get("/api/info");
    gateway.value = info.gateway.replace(/^https?:\/\//, "");
  } catch (e) {
    gateway.value = "gateway unreachable";
  }
});
</script>

<template>
  <Toast position="bottom-center" />
  <ConfirmDialog />
  <header class="row" style="padding: 0.75rem 0 0.25rem">
    <h1 style="margin: 0; font-size: 1.3rem" class="grow">dali-iot</h1>
    <span class="muted">{{ gateway }}</span>
    <Button :icon="dark ? 'pi pi-sun' : 'pi pi-moon'" text rounded aria-label="Theme" @click="toggleDark" />
  </header>
  <Control v-if="phone" />
  <Tabs v-else :value="tab" @update:value="remember" scrollable>
    <TabList>
      <Tab value="control"><i class="pi pi-lightbulb" /> Control</Tab>
      <Tab value="devices"><i class="pi pi-list" /> Devices</Tab>
      <Tab value="schedules"><i class="pi pi-clock" /> Schedules</Tab>
      <Tab value="apply"><i class="pi pi-cloud-upload" /> Apply</Tab>
    </TabList>
    <TabPanels>
      <TabPanel value="control"><Control v-if="tab === 'control'" /></TabPanel>
      <TabPanel value="devices"><Devices v-if="tab === 'devices'" /></TabPanel>
      <TabPanel value="schedules"><Schedules v-if="tab === 'schedules'" /></TabPanel>
      <TabPanel value="apply"><Apply v-if="tab === 'apply'" /></TabPanel>
    </TabPanels>
  </Tabs>
</template>
