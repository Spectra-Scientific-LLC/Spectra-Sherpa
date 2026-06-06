<template>
  <section class="walkthrough-panel">
    <header class="walkthrough-header">
      <div>
        <p class="eyebrow">ISO 17025</p>
        <h2>Validation Walkthrough</h2>
        <p class="walkthrough-sub">
          A repeatable product walkthrough that exercises the Report tab,
          filtered audit views, chain health, and report-pack generation
          on an FTIR or Raman workflow. This is not a validated method —
          it is the rehearsal a lab reviewer can follow.
        </p>
      </div>
      <div class="walkthrough-actions">
        <button
          v-if="auditConfig?.localQuery || auditConfig?.fullPipeline"
          class="ghost-action"
          type="button"
          data-testid="walkthrough-open-audit"
          :disabled="!workflowId"
          @click="$emit('open-audit')"
        >
          <i class="pi pi-shield" aria-hidden="true"></i>
          <span>Open Audit</span>
        </button>
        <button
          class="ghost-action"
          type="button"
          aria-controls="walkthrough-body"
          :aria-expanded="expanded"
          @click="expanded = !expanded"
        >
          <i :class="['pi', expanded ? 'pi-chevron-up' : 'pi-chevron-down']" aria-hidden="true"></i>
          <span>{{ expanded ? "Hide steps" : "Show steps" }}</span>
        </button>
      </div>
    </header>

    <div v-if="expanded" id="walkthrough-body" class="walkthrough-body">
      <details class="walkthrough-section" open>
        <summary>Assumptions</summary>
        <ul>
          <li>Spectra Sherpa is running with audit enabled (<code>SHERPA_AUDIT_ENABLED=true</code>).</li>
          <li>The current user can access <code>audit.basic</code>, <code>audit.full</code>, <code>audit.export</code>, and <code>audit.report_pack</code>.</li>
          <li>The audit chainer is running and <code>/api/v1/audit/verify</code> returns <code>ok: true</code> before the demo starts.</li>
          <li>An FTIR or Raman example dataset or analysis starter is available; if Raman is unavailable, substitute with FTIR or NIR and record the substitution in the validation pack.</li>
          <li>PLS scaling defaults remain <code>false</code> unless a method-specific reason is documented in the workflow parameters.</li>
        </ul>
      </details>

      <details class="walkthrough-section" open>
        <summary>Steps</summary>
        <ol>
          <li>Open <strong>Projects</strong>.</li>
          <li>Select or create a project named <em>ISO 17025 Example — FTIR Raman</em>.</li>
          <li>Click <strong>Audit</strong> from the project header.</li>
          <li>Confirm <strong>Chain Health</strong> shows <em>Verified</em>.</li>
          <li>Return to <strong>Workflows</strong>.</li>
          <li>Start from the FTIR/Raman analysis starter, or build the target workflow manually.</li>
          <li>Load the example dataset.</li>
          <li>Confirm labels/targets are visible and correct.</li>
          <li>Run the workflow.</li>
          <li>Save the workflow.</li>
          <li>Click <strong>Audit</strong> from the workflow header.</li>
          <li>Confirm the filtered audit timeline contains workflow create/update/run/save events.</li>
          <li>Return to <strong>Report</strong>.</li>
          <li>Select the workflow.</li>
          <li>Click <strong>Generate Report</strong>.</li>
          <li>Confirm the Report preview renders pipeline details and execution results.</li>
          <li>Click <strong>Audit</strong> from the Report header (the button above).</li>
          <li>Confirm the filtered audit view targets the same workflow id.</li>
          <li>Click <strong>Generate Pack</strong> with <em>Include PDF summary</em> checked.</li>
          <li>
            Open the ZIP and confirm these files are present:
            <code>manifest.json</code>, <code>audit_export.jsonl|csv</code>,
            <code>audit_chain.jsonl</code>, <code>chain_verification.json</code>,
            <code>reproducibility_summary.json</code>,
            <code>audit_report_summary.pdf</code>,
            <code>clause_to_evidence_matrix.md</code>,
            <code>validation_pack_template.md</code>,
            <code>limitations.md</code>,
            and <code>verify_manifest.py</code>.
          </li>
        </ol>
      </details>

      <details class="walkthrough-section">
        <summary>Acceptance checks</summary>
        <ul>
          <li>Manifest <code>schema</code> = <code>spectra-sherpa.audit-report-pack.v1</code>.</li>
          <li>Manifest <code>signature.algorithm</code> = <code>HMAC-SHA256</code>.</li>
          <li>Manifest <code>pdf_status</code> = <code>generated_v1</code>.</li>
          <li>Audit evidence row count matches the response header.</li>
          <li><code>chain_verification.ok</code> is true.</li>
          <li><code>audit_chain.jsonl</code> spans the full contiguous verification interval; the manifest records both selected and interval row counts.</li>
          <li><code>reproducibility_summary.json</code> includes at least one workflow-run record with a reproducibility payload.</li>
          <li>The audit timeline contains <code>audit.report_pack.generated</code> after pack generation.</li>
          <li>The PDF identifies pack id, tenant, generation time, row count, chain status, and selected evidence rows.</li>
          <li>
            Run the bundled <code>verify_manifest.py</code> with the operator-provided HMAC key and confirm <code>ok: true</code>.
          </li>
        </ul>
      </details>

      <details class="walkthrough-section">
        <summary>Known non-claims</summary>
        <ul>
          <li>This walkthrough does not validate the chemometric method.</li>
          <li>It does not certify dataset suitability, target-label correctness, or model acceptance criteria.</li>
          <li>It does not replace lab SOPs, training records, instrument qualification, or accreditation-body review.</li>
          <li>It proves the product workflow can produce and retrieve a defensible technical evidence bundle for the selected workflow scope.</li>
        </ul>
      </details>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref } from "vue";

import type { AuditCapabilities } from "@/views/audit/types";

defineProps<{
  workflowId: number | null;
  auditConfig: AuditCapabilities | undefined;
}>();

defineEmits<{
  (e: "open-audit"): void;
}>();

const expanded = ref(false);
</script>

<style scoped>
.walkthrough-panel {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  margin-top: 16px;
  padding: 16px;
}

.walkthrough-header {
  align-items: flex-start;
  display: flex;
  gap: 16px;
  justify-content: space-between;
}

.walkthrough-header h2 {
  font-size: 1.1rem;
  letter-spacing: 0;
  margin: 2px 0 0;
}

.walkthrough-sub {
  color: #475569;
  margin: 6px 0 0;
  max-width: 60ch;
}

.eyebrow {
  color: #64748b;
  font-size: 0.76rem;
  font-weight: 700;
  letter-spacing: 0;
  margin: 0;
  text-transform: uppercase;
}

.walkthrough-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.ghost-action {
  align-items: center;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  color: #0f172a;
  cursor: pointer;
  display: inline-flex;
  font-weight: 700;
  gap: 8px;
  min-height: 36px;
  padding: 0 12px;
}

.ghost-action:disabled {
  background: #e2e8f0;
  color: #64748b;
  cursor: not-allowed;
}

.walkthrough-body {
  margin-top: 12px;
}

.walkthrough-section {
  border-top: 1px solid #e2e8f0;
  padding: 10px 0;
}

.walkthrough-section summary {
  color: #1d4ed8;
  cursor: pointer;
  font-weight: 700;
}

.walkthrough-section ul,
.walkthrough-section ol {
  margin: 8px 0 0 20px;
}

.walkthrough-section li {
  line-height: 1.5;
  margin-bottom: 4px;
}

.walkthrough-section code {
  background: #f1f5f9;
  border-radius: 4px;
  font-size: 0.86rem;
  padding: 1px 4px;
}

@media (max-width: 720px) {
  .walkthrough-header {
    flex-direction: column;
  }
}
</style>
