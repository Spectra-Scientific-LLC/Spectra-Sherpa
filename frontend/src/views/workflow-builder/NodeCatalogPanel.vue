<template>
  <section class="node-catalog" aria-label="Canonical node catalog">
    <div class="catalog-intro">
      <strong>Canonical node catalog</strong>
      <span>{{ filteredNodes.length }} of {{ nodes.length }} operations</span>
    </div>

    <div class="catalog-filters" data-testid="catalog-filters">
      <label class="wide-filter">
        <span>Text</span>
        <input
          v-model="query"
          type="search"
          placeholder="Purpose, operation, parameter, citation…"
          data-testid="catalog-text-filter"
        />
      </label>
      <label>
        <span>Family</span>
        <select v-model="family" data-testid="catalog-family-filter">
          <option value="all">All families</option>
          <option v-for="option in familyOptions" :key="option" :value="option">
            {{ nodeCategoryLabel(option) }}
          </option>
        </select>
      </label>
      <label>
        <span>Lifecycle</span>
        <select v-model="lifecycle" data-testid="catalog-lifecycle-filter">
          <option value="all">All lifecycles</option>
          <option v-for="option in lifecycleOptions" :key="option" :value="option">
            {{ humanize(option) }}
          </option>
        </select>
      </label>
      <label>
        <span>Task</span>
        <select v-model="task" data-testid="catalog-task-filter">
          <option value="all">All tasks</option>
          <option v-for="option in taskOptions" :key="option" :value="option">
            {{ taskLabel(option) }}
          </option>
        </select>
      </label>
      <label>
        <span>Managed</span>
        <select v-model="managed" data-testid="catalog-managed-filter">
          <option value="all">Any eligibility</option>
          <option value="eligible">Managed eligible</option>
          <option value="local_only">Local only</option>
        </select>
      </label>
      <label>
        <span>Application</span>
        <select v-model="application" data-testid="catalog-application-filter">
          <option value="all">All operations</option>
          <option value="artifact">Artifact application</option>
          <option value="not_artifact">Not artifact application</option>
        </select>
      </label>
      <label>
        <span>Runtime</span>
        <select v-model="runtime" data-testid="catalog-runtime-filter">
          <option value="all">Any runtime</option>
          <option value="core">Core install</option>
          <option value="optional">Optional install</option>
        </select>
      </label>
      <button type="button" class="reset-filters" data-testid="catalog-reset" @click="resetFilters">
        Reset
      </button>
    </div>

    <div v-if="filteredNodes.length === 0" class="catalog-empty" data-testid="catalog-empty">
      No canonical operations match these filters.
    </div>

    <div v-else class="catalog-results" data-testid="catalog-results">
      <template v-for="(node, index) in filteredNodes" :key="node.node_type">
        <h3
          v-if="index === 0 || filteredNodes[index - 1].category !== node.category"
          class="catalog-family-heading"
          :data-testid="`catalog-family-${node.category}`"
        >
          <span>{{ nodeCategoryLabel(node.category) }}</span>
          <small>{{ visibleFamilyCount(node.category) }}</small>
        </h3>
        <details class="catalog-card" :data-testid="`catalog-node-${node.node_type}`">
        <summary>
          <span class="catalog-title">
            <strong>{{ node.label }}</strong>
            <code>{{ node.node_type }}</code>
          </span>
          <span class="catalog-badges">
            <span class="badge">{{ nodeCategoryLabel(node.category) }}</span>
            <span v-if="isManaged(node)" class="badge managed">Managed</span>
            <span v-if="isArtifactApplication(node)" class="badge artifact">Artifact apply</span>
            <span v-if="node.requires_scp" class="badge optional">Optional SCP</span>
          </span>
          <button
            v-if="addableNodeTypes.includes(node.node_type)"
            type="button"
            class="catalog-add"
            :aria-label="`Add ${node.label}`"
            :data-testid="`catalog-add-${node.node_type}`"
            @click.stop="emit('add-node', node.node_type)"
          >
            Add
          </button>
          <span v-else class="source-bound">Starter/source bound</span>
        </summary>

        <div class="catalog-detail">
          <section>
            <h4>Scientific purpose</h4>
            <p>{{ node.description }}</p>
          </section>

          <section>
            <h4>Parameters</h4>
            <p v-if="scientistParameters(node).length === 0" class="muted">No scientist-set parameters.</p>
            <dl v-else class="detail-grid parameters">
              <template v-for="parameter in scientistParameters(node)" :key="parameter.name">
                <dt>
                  <code>{{ parameter.name }}</code> · {{ parameter.param_type }}
                </dt>
                <dd>
                  {{ parameter.description || "No additional description." }}
                  <span class="parameter-rule">{{ parameterRule(parameter) }}</span>
                </dd>
              </template>
            </dl>
          </section>

          <section>
            <h4>Typed ports</h4>
            <div class="port-columns">
              <div>
                <strong>Inputs</strong>
                <p v-if="!node.input_ports?.length" class="muted">None (source operation).</p>
                <ul v-else>
                  <li v-for="port in node.input_ports" :key="port.name">
                    <code>{{ port.name }}</code> — {{ port.type_ref }}
                    <span>{{ port.required ? "required" : "optional" }}</span>
                  </li>
                </ul>
              </div>
              <div>
                <strong>Outputs</strong>
                <p v-if="!node.output_ports?.length" class="muted">Default output only.</p>
                <ul v-else>
                  <li v-for="port in node.output_ports" :key="port.name">
                    <code>{{ port.name }}</code> — {{ port.type_ref }}
                  </li>
                </ul>
              </div>
            </div>
          </section>

          <section>
            <h4>Lifecycle, fitting, and preprocessing semantics</h4>
            <dl class="detail-grid">
              <dt>Runtime / lifecycle</dt>
              <dd>
                {{ humanize(contractString(node, "runtime_family")) }} /
                {{ humanize(nodeLifecycle(node)) }}
              </dd>
              <dt>Input rank</dt>
              <dd>{{ humanize(contractString(node, "input_rank_policy")) }}</dd>
              <dt>Task / target / groups</dt>
              <dd>
                {{ taskLabel(nodeTask(node)) }} /
                {{ humanize(contractString(node, "target_access")) }} /
                {{ humanize(contractString(node, "group_access")) }}
              </dd>
              <dt>Samples / features</dt>
              <dd>
                {{ humanize(contractString(node, "sample_effect")) }} /
                {{ humanize(contractString(node, "feature_effect")) }}
              </dd>
              <dt>Axis / units</dt>
              <dd>
                {{ humanize(contractString(node, "axis_effect")) }} /
                {{ humanize(contractString(node, "unit_effect")) }}
              </dd>
              <dt>Fitted-state serializer</dt>
              <dd>{{ contractString(node, "fitted_state_serializer") || "Not fitted" }}</dd>
              <dt>Determinism</dt>
              <dd>{{ deterministicLabel(node) }}</dd>
            </dl>
          </section>

          <section>
            <h4>Validation cautions</h4>
            <ul>
              <li v-for="caution in validationCautions(node)" :key="caution">{{ caution }}</li>
            </ul>
          </section>

          <section>
            <h4>Implementation and contract identity</h4>
            <dl class="detail-grid identities">
              <dt>Implementation</dt>
              <dd>
                {{ contractString(node, "implementation_id") }} @
                {{ contractString(node, "implementation_version") }}
              </dd>
              <dt>Implementation digest</dt>
              <dd>
                <code>{{ contractString(node, "implementation_digest") }}</code>
              </dd>
              <dt>Execution contract</dt>
              <dd>
                <code>{{ node.execution_contract?.digest || "Unavailable" }}</code>
              </dd>
              <dt>Help authority</dt>
              <dd>
                <code>{{ contractString(node, "help_reference") }}</code>
              </dd>
            </dl>
            <a
              v-if="nodeHelpUrl(node)"
              class="node-help-link"
              :href="nodeHelpUrl(node) || undefined"
              target="_blank"
              rel="noopener noreferrer"
              :aria-label="`Learn about ${node.label} (opens in a new tab)`"
              :data-testid="`catalog-help-${node.node_type}`"
            >
              <i class="pi pi-book" aria-hidden="true"></i>
              Learn about this node
              <span class="new-tab-note">Opens in a new tab</span>
            </a>
          </section>

          <section>
            <h4>Managed optimization</h4>
            <p>
              <strong>{{
                isManaged(node) ? "Eligible" : "Local-only for managed optimization"
              }}</strong>
              — {{ humanize(node.managed_optimization_profile?.reason || "unclassified") }}.
            </p>
            <p v-if="node.managed_optimization_profile" class="muted">
              {{ node.managed_optimization_profile.profile_id }} v{{
                node.managed_optimization_profile.profile_version
              }}
              · <code>{{ node.managed_optimization_profile.profile_digest }}</code>
            </p>
          </section>

          <section>
            <h4>Optional runtime</h4>
            <template v-if="node.requires_scp">
              <p>
                This operation requires the optional SpectroChemPy runtime. SpectroChemPy does not
                supply ingestion.
              </p>
              <code class="install-command">pip install 'spectra-sherpa[scp]'</code>
              <p
                v-if="node.dependency_readiness && !node.dependency_readiness.ready"
                class="runtime-refusal"
              >
                Execution is unavailable until the dependency check passes.
              </p>
            </template>
            <p v-else>
              Available from the core installation; no SpectroChemPy runtime is required.
            </p>
          </section>

          <section v-if="isArtifactApplication(node)">
            <h4>Artifact application</h4>
            <p>
              This operation applies admitted fitted state; it does not train or validate a new
              model.
            </p>
          </section>

          <section>
            <h4>Citations</h4>
            <p v-if="contractStrings(node, 'citations').length === 0" class="muted">
              No external scientific citation is declared by the execution contract.
            </p>
            <ul v-else>
              <li v-for="citation in contractStrings(node, 'citations')" :key="citation">
                {{ citation }}
              </li>
            </ul>
          </section>
        </div>
        </details>
      </template>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";

import type { NodeParameterMetadata, NodeTypeMetadata } from "@/types";
import { nodeCategoryLabel, sortNodeCategories } from "@/utils/nodeCatalogTaxonomy";
import { resolveNodeHelpUrl } from "@/utils/nodeHelp";

const props = defineProps<{
  nodes: NodeTypeMetadata[];
  addableNodeTypes: string[];
}>();

const emit = defineEmits<{
  (event: "add-node", nodeType: string): void;
}>();

const query = ref("");
const family = ref("all");
const lifecycle = ref("all");
const task = ref("all");
const managed = ref("all");
const application = ref("all");
const runtime = ref("all");

const contractPayload = (node: NodeTypeMetadata): Record<string, unknown> =>
  node.execution_contract?.payload || {};

const contractString = (node: NodeTypeMetadata, key: string): string => {
  const value = contractPayload(node)[key];
  return typeof value === "string" ? value : "";
};

const contractStrings = (node: NodeTypeMetadata, key: string): string[] => {
  const value = contractPayload(node)[key];
  return Array.isArray(value) && value.every((item) => typeof item === "string") ? value : [];
};

const nodeHelpUrl = (node: NodeTypeMetadata): string | null =>
  resolveNodeHelpUrl(contractPayload(node).help_reference);

const nodeLifecycle = (node: NodeTypeMetadata): string =>
  node.catalog_classification?.lifecycle_kind ||
  contractString(node, "lifecycle_kind") ||
  "unclassified";

const nodeTask = (node: NodeTypeMetadata): string =>
  contractString(node, "supervised_task") || "none";

const isManaged = (node: NodeTypeMetadata): boolean =>
  node.managed_optimization_profile?.eligible === true ||
  node.catalog_classification?.managed_optimization_eligible === true;

const isArtifactApplication = (node: NodeTypeMetadata): boolean =>
  nodeLifecycle(node) === "artifact_application";

const scientistParameters = (node: NodeTypeMetadata): NodeParameterMetadata[] =>
  node.parameters.filter((parameter) => parameter.category !== "internal");

const deterministicLabel = (node: NodeTypeMetadata): string => {
  const payload = contractPayload(node);
  if (payload.deterministic === true) return "Deterministic; no seed parameter";
  if (payload.deterministic === false) {
    const seed = typeof payload.seed_parameter === "string" ? payload.seed_parameter : "undeclared";
    return `Seeded through ${seed}`;
  }
  return "Not declared";
};

const uniqueSorted = (values: string[]): string[] =>
  [...new Set(values)].sort((a, b) => a.localeCompare(b));

const familyOptions = computed(() => sortNodeCategories(props.nodes.map((node) => node.category)));
const lifecycleOptions = computed(() => uniqueSorted(props.nodes.map(nodeLifecycle)));
const taskOptions = computed(() => uniqueSorted(props.nodes.map(nodeTask)));

const humanize = (value: string): string =>
  value
    ? value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase())
    : "Not declared";

const taskLabel = (value: string): string =>
  value === "none" ? "Unsupervised / no target" : humanize(value);

const textProjection = (node: NodeTypeMetadata): string => {
  const citations = contractStrings(node, "citations");
  return [
    node.node_type,
    node.label,
    node.description,
    node.category,
    nodeLifecycle(node),
    nodeTask(node),
    contractString(node, "implementation_id"),
    ...scientistParameters(node).flatMap((parameter) => [
      parameter.name,
      parameter.label,
      parameter.description || "",
    ]),
    ...citations,
  ]
    .join(" ")
    .toLocaleLowerCase();
};

const filteredNodes = computed(() => {
  const needle = query.value.trim().toLocaleLowerCase();
  const familyOrder = sortNodeCategories(props.nodes.map((node) => node.category));
  return [...props.nodes]
    .filter((node) => !needle || textProjection(node).includes(needle))
    .filter((node) => family.value === "all" || node.category === family.value)
    .filter((node) => lifecycle.value === "all" || nodeLifecycle(node) === lifecycle.value)
    .filter((node) => task.value === "all" || nodeTask(node) === task.value)
    .filter((node) => managed.value === "all" || (managed.value === "eligible") === isManaged(node))
    .filter(
      (node) =>
        application.value === "all" ||
        (application.value === "artifact") === isArtifactApplication(node),
    )
    .filter(
      (node) =>
        runtime.value === "all" || (runtime.value === "optional") === Boolean(node.requires_scp),
    )
    .sort(
      (left, right) =>
        familyOrder.indexOf(left.category) - familyOrder.indexOf(right.category) ||
        left.label.localeCompare(right.label) ||
        left.node_type.localeCompare(right.node_type),
    );
});

const visibleFamilyCount = (category: string): number =>
  filteredNodes.value.filter((node) => node.category === category).length;

const parameterRule = (parameter: NodeParameterMetadata): string => {
  const pieces = [parameter.required ? "required" : "optional"];
  if (parameter.default !== undefined) pieces.push(`default ${JSON.stringify(parameter.default)}`);
  if (parameter.min_value !== undefined) pieces.push(`min ${parameter.min_value}`);
  if (parameter.max_value !== undefined) pieces.push(`max ${parameter.max_value}`);
  return `(${pieces.join("; ")})`;
};

const validationCautions = (node: NodeTypeMetadata): string[] => {
  const cautions: string[] = [];
  const lifecycleKind = nodeLifecycle(node);
  const supervisedTask = nodeTask(node);
  if (supervisedTask !== "none") {
    cautions.push(
      "Performance claims require an explicit held-out validation plan; fitted outputs alone are not validation evidence.",
    );
  }
  if (lifecycleKind === "fitted_model" || lifecycleKind === "fitted_transform") {
    cautions.push("Fit this operation on training data only when it is used inside validation.");
  }
  if (isArtifactApplication(node)) {
    cautions.push(
      "Application results inherit the admitted fitted artifact and must not be described as a new fit.",
    );
  }
  if (!isManaged(node)) {
    cautions.push(
      `This operation is not admitted to managed optimization: ${humanize(node.managed_optimization_profile?.reason || "unclassified")}.`,
    );
  }
  if (node.dependency_readiness && !node.dependency_readiness.ready) {
    cautions.push(
      `Execution currently refuses: ${node.dependency_readiness.blockers.map(humanize).join(", ")}.`,
    );
  }
  if (cautions.length === 0) {
    cautions.push(
      "Interpret outputs according to the declared lifecycle, typed ports, and scientific effects shown above.",
    );
  }
  return cautions;
};

const resetFilters = (): void => {
  query.value = "";
  family.value = "all";
  lifecycle.value = "all";
  task.value = "all";
  managed.value = "all";
  application.value = "all";
  runtime.value = "all";
};
</script>

<style scoped>
.node-catalog {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
}

.catalog-intro {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 8px;
  color: #f8fafc;
}

.catalog-intro span {
  color: #94a3b8;
  font-size: 0.72rem;
}

.catalog-filters {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.catalog-filters label {
  display: flex;
  flex-direction: column;
  gap: 3px;
  color: #94a3b8;
  font-size: 0.68rem;
}

.catalog-filters .wide-filter {
  grid-column: 1 / -1;
}

.catalog-filters input,
.catalog-filters select {
  min-width: 0;
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #475569;
  border-radius: 5px;
  padding: 7px;
  background: #0f172a;
  color: #e2e8f0;
  font: inherit;
}

.reset-filters {
  border: 1px solid #475569;
  border-radius: 5px;
  background: transparent;
  color: #cbd5e1;
  cursor: pointer;
}

.catalog-results {
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow-y: auto;
}

.catalog-family-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin: 6px 2px 0;
  color: #cbd5e1;
  font-size: 0.8rem;
}

.catalog-family-heading:first-child {
  margin-top: 0;
}

.catalog-family-heading small {
  color: #64748b;
  font-size: 0.68rem;
  font-weight: 500;
}

.catalog-card {
  border: 1px solid #334155;
  border-radius: 7px;
  background: rgba(15, 23, 42, 0.72);
  color: #e2e8f0;
}

.catalog-card summary {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 7px;
  padding: 10px;
  cursor: pointer;
  list-style-position: outside;
}

.catalog-title {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.catalog-title code,
.identities code {
  overflow-wrap: anywhere;
}

.catalog-title code {
  color: #93c5fd;
  font-size: 0.68rem;
}

.catalog-badges {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.badge,
.source-bound {
  border-radius: 999px;
  padding: 2px 6px;
  background: #334155;
  color: #cbd5e1;
  font-size: 0.62rem;
}

.badge.managed {
  background: #14532d;
  color: #bbf7d0;
}
.badge.artifact {
  background: #4c1d95;
  color: #ddd6fe;
}
.badge.optional {
  background: #78350f;
  color: #fde68a;
}

.catalog-add {
  align-self: start;
  border: 1px solid #60a5fa;
  border-radius: 5px;
  padding: 4px 8px;
  background: #1d4ed8;
  color: white;
  cursor: pointer;
}

.source-bound {
  align-self: start;
  white-space: nowrap;
}

.catalog-detail {
  border-top: 1px solid #334155;
  padding: 0 12px 12px;
  font-size: 0.72rem;
  line-height: 1.45;
}

.catalog-detail section {
  padding-top: 10px;
}

.catalog-detail h4 {
  margin: 0 0 5px;
  color: #f8fafc;
  font-size: 0.76rem;
}

.catalog-detail p,
.catalog-detail ul,
.catalog-detail dl {
  margin: 4px 0;
}

.catalog-detail ul {
  padding-left: 17px;
}

.detail-grid {
  display: grid;
  grid-template-columns: minmax(90px, 0.45fr) minmax(0, 1fr);
  gap: 4px 8px;
}

.detail-grid dt {
  color: #94a3b8;
}
.detail-grid dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.parameters {
  grid-template-columns: minmax(110px, 0.55fr) minmax(0, 1fr);
}
.parameter-rule {
  display: block;
  color: #94a3b8;
}

.port-columns {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
}

.port-columns li {
  overflow-wrap: anywhere;
}
.port-columns li span {
  color: #94a3b8;
}
.muted {
  color: #94a3b8;
}
.install-command {
  display: block;
  padding: 6px;
  background: #020617;
  color: #fde68a;
  overflow-wrap: anywhere;
}
.runtime-refusal {
  color: #fca5a5;
}
.catalog-empty {
  padding: 20px 8px;
  text-align: center;
  color: #94a3b8;
}
.node-help-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-top: 8px;
  color: #93c5fd;
  font-weight: 600;
  text-decoration: none;
}
.node-help-link:hover,
.node-help-link:focus-visible {
  text-decoration: underline;
}
.new-tab-note {
  color: #94a3b8;
  font-size: 0.64rem;
  font-weight: 400;
}
</style>
