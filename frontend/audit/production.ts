import { createApp } from "vue";
import { createPinia } from "pinia";
import PrimeVue from "primevue/config";
import "primevue/resources/themes/lara-light-blue/theme.css";
import "primevue/resources/primevue.min.css";
import "primeicons/primeicons.css";
import "@/assets/tokens.css";
import ProductionReview from "./ProductionReview.vue";
createApp(ProductionReview).use(createPinia()).use(PrimeVue).mount("#audit");
