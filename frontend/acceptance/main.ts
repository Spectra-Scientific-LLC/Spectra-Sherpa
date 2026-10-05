import { createApp } from "vue";
import PrimeVue from "primevue/config";
import "primevue/resources/themes/lara-light-blue/theme.css";
import "primevue/resources/primevue.min.css";
import "primeicons/primeicons.css";
import Audit from "./Fixes.vue";
createApp(Audit).use(PrimeVue).mount("#audit");
