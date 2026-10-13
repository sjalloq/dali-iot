import { createApp } from "vue";
import PrimeVue from "primevue/config";
import Aura from "@primevue/themes/aura";
import ToastService from "primevue/toastservice";
import ConfirmationService from "primevue/confirmationservice";
import "primeicons/primeicons.css";
import App from "./App.vue";
import "./style.css";

const app = createApp(App);
app.use(PrimeVue, {
  theme: { preset: Aura, options: { darkModeSelector: ".dark" } },
  ripple: true,
});
app.use(ToastService);
app.use(ConfirmationService);
app.mount("#app");
