<template>
  <section class="detail-section">
    <div class="section-header" @click="$emit('toggle')">
      <div class="section-title">
        <i :class="expanded ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
        <h2>Plots</h2>
      </div>
      <span class="section-badge">{{ state.availablePlots.length }} visualizations</span>
    </div>
    <Transition name="collapse">
      <div v-if="expanded" class="section-content plots-content">
        <div v-if="!state.hasOutput" class="empty-plot-message">
          <i class="pi pi-play" />
          <span>Run the node to generate visualizations.</span>
        </div>
        <div v-else-if="state.availablePlots.length === 0" class="empty-plot-message">
          <i class="pi pi-chart-line" />
          <span>No visualizations available for this node type.</span>
        </div>
        <template v-else>
          <!-- PCA Plots -->
          <template v-if="state.isPCAOutput">
            <div class="plot-subsection">
              <div class="plot-subsection-header" @click="$emit('togglePlot', 'pcaScores')">
                <i :class="plotSections.pcaScores ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                <span>Scores Plot</span>
              </div>
              <Transition name="collapse">
                <div v-if="plotSections.pcaScores" class="plot-container">
                  <div class="plot-controls">
                    <div class="control-group">
                      <label>X Axis</label>
                      <Dropdown v-model="pcaXAxis" :options="state.pcaAxisOptions" optionLabel="label" optionValue="value" />
                    </div>
                    <div class="control-group">
                      <label>Y Axis</label>
                      <Dropdown v-model="pcaYAxis" :options="state.pcaAxisOptions" optionLabel="label" optionValue="value" />
                    </div>
                    <div v-if="state.scoreColorOptions.length > 1" class="control-group">
                      <label>Color by</label>
                      <Dropdown v-model="scoreColorMode" :options="state.scoreColorOptions" optionLabel="label" optionValue="value" />
                    </div>
                  </div>
                  <PlotlyChart :data="state.pcaScoresData" :layout="state.pcaScoresLayout" :config="state.pcaScoresConfig" />
                </div>
              </Transition>
            </div>

            <div class="plot-subsection">
              <div class="plot-subsection-header" @click="$emit('togglePlot', 'pcaBiplot')">
                <i :class="plotSections.pcaBiplot ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                <span>Biplot (Scores + Loadings)</span>
              </div>
              <Transition name="collapse">
                <div v-if="plotSections.pcaBiplot" class="plot-container">
                  <div class="plot-controls">
                    <div class="control-group">
                      <label>X Axis</label>
                      <Dropdown v-model="pcaXAxis" :options="state.pcaAxisOptions" optionLabel="label" optionValue="value" />
                    </div>
                    <div class="control-group">
                      <label>Y Axis</label>
                      <Dropdown v-model="pcaYAxis" :options="state.pcaAxisOptions" optionLabel="label" optionValue="value" />
                    </div>
                  </div>
                  <PlotlyChart :data="state.pcaBiplotData" :layout="state.pcaBiplotLayout" :config="state.pcaScoresConfig" />
                </div>
              </Transition>
            </div>

            <div class="plot-subsection">
              <div class="plot-subsection-header" @click="$emit('togglePlot', 'pcaLoadings')">
                <i :class="plotSections.pcaLoadings ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                <span>Loadings Plot</span>
              </div>
              <Transition name="collapse">
                <div v-if="plotSections.pcaLoadings" class="plot-container">
                  <PlotlyChart :data="state.pcaLoadingsData" :layout="state.pcaLoadingsLayout" :config="state.pcaLoadingsConfig" />
                </div>
              </Transition>
            </div>

            <div class="plot-subsection">
              <div class="plot-subsection-header" @click="$emit('togglePlot', 'pcaScree')">
                <i :class="plotSections.pcaScree ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                <span>Scree Plot (Explained Variance)</span>
              </div>
              <Transition name="collapse">
                <div v-if="plotSections.pcaScree" class="plot-container">
                  <PlotlyChart :data="state.pcaScreeData" :layout="state.pcaScreeLayout" />
                </div>
              </Transition>
            </div>

            <div class="plot-subsection">
              <div class="plot-subsection-header" @click="$emit('togglePlot', 'pcaDiagnostics')">
                <i :class="plotSections.pcaDiagnostics ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
                <span>Diagnostics Plot (T² / SPE)</span>
              </div>
              <Transition name="collapse">
                <div v-if="plotSections.pcaDiagnostics" class="plot-container">
                  <PlotlyChart :data="state.pcaDiagnosticsData" :layout="state.pcaDiagnosticsLayout" />
                </div>
              </Transition>
            </div>
          </template>

        <!-- MCR-ALS / SIMPLISMA -->
        <template v-if="state.nodeTypeKey === 'model.mcr_als' || state.nodeTypeKey === 'model.simplisma'">
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'mcrConcentrations')">
              <i :class="plotSections.mcrConcentrations ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>Concentration Profiles (C)</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.mcrConcentrations" class="plot-container">
                <PlotlyChart :data="state.mcrConcentrationData" :layout="state.mcrConcentrationLayout" />
              </div>
            </Transition>
          </div>
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'mcrSpectra')">
              <i :class="plotSections.mcrSpectra ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>Pure Spectra (S<sup>T</sup>)</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.mcrSpectra" class="plot-container">
                <PlotlyChart :data="state.mcrSpectraData" :layout="state.mcrSpectraLayout" />
              </div>
            </Transition>
          </div>
          <div v-if="state.nodeTypeKey === 'model.mcr_als'" class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'mcrGroundTruthValidation')">
              <i :class="plotSections.mcrGroundTruthValidation ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>Ground Truth Validation</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.mcrGroundTruthValidation" class="plot-container">
                <div v-if="mcrCandidateOptions.length > 0" class="mcr-validation-controls">
                  <div class="control-group mcr-candidate-picker">
                    <label>Review Target / Component Pair</label>
                    <Dropdown
                      v-model="selectedMcrCandidate"
                      :options="mcrCandidateOptions"
                      optionLabel="label"
                      optionValue="value"
                    />
                  </div>
                  <div v-if="selectedMcrCandidateRecord" class="mcr-candidate-metrics">
                    <span>R² {{ formatMcrNumber(selectedMcrCandidateRecord.r2) }}</span>
                    <span>RMSE {{ formatMcrNumber(selectedMcrCandidateRecord.rmse) }}</span>
                    <span>r {{ formatMcrNumber(selectedMcrCandidateRecord.correlation) }}</span>
                  </div>
                  <div v-if="selectedMcrCandidateRecord" class="mcr-candidate-hint">
                    Set Validation Target {{ Number(selectedMcrCandidateRecord.target_index ?? 0) + 1 }}
                    and MCR Component {{ Number(selectedMcrCandidateRecord.component_index ?? 0) + 1 }},
                    then rerun to emit this pair as ValidationResult.
                  </div>
                </div>
                <div v-if="mcrSelectedValidationScatterData.length > 0" class="mcr-validation-grid">
                  <PlotlyChart :data="mcrSelectedValidationScatterData" :layout="state.mcrValidationScatterLayout" />
                  <PlotlyChart
                    v-if="mcrSelectedSpectrumData.length > 0 || state.mcrValidationSpectrumData.length > 0"
                    :data="mcrSelectedSpectrumData.length > 0 ? mcrSelectedSpectrumData : state.mcrValidationSpectrumData"
                    :layout="state.mcrValidationSpectrumLayout"
                  />
                </div>
                <div v-else class="no-plot-message">
                  Run MCR-ALS on a synthetic dataset with ground-truth concentrations, then select the validation target and MCR component in the node settings.
                </div>
              </div>
            </Transition>
          </div>
        </template>

        <!-- MCR-ALS only: contour diagnostics -->
        <template v-if="state.nodeTypeKey === 'model.mcr_als'">
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'mcrOriginalContour')">
              <i :class="plotSections.mcrOriginalContour ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>Original Data Contour</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.mcrOriginalContour" class="plot-container">
                <PlotlyChart :data="state.mcrOriginalContourData" :layout="state.mcrOriginalContourLayout" />
              </div>
            </Transition>
          </div>
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'mcrReconstructedContour')">
              <i :class="plotSections.mcrReconstructedContour ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>Reconstructed Contour (D̂ = C·S<sup>T</sup>)</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.mcrReconstructedContour" class="plot-container">
                <PlotlyChart :data="state.mcrReconstructedContourData" :layout="state.mcrReconstructedContourLayout" />
              </div>
            </Transition>
          </div>
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'mcrResidualContour')">
              <i :class="plotSections.mcrResidualContour ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>Residual Contour (D − D̂)</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.mcrResidualContour" class="plot-container">
                <PlotlyChart :data="state.mcrResidualContourData" :layout="state.mcrResidualContourLayout" />
              </div>
            </Transition>
          </div>
        </template>

        <!-- EFA -->
        <template v-if="state.nodeTypeKey === 'model.efa'">
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'efaEigenvalues')">
              <i :class="plotSections.efaEigenvalues ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>Eigenvalue Plot</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.efaEigenvalues" class="plot-container">
                <PlotlyChart :data="state.efaEigenvalueData" :layout="state.efaEigenvalueLayout" />
              </div>
            </Transition>
          </div>
        </template>

        <!-- PLS -->
        <template v-if="state.nodeTypeKey === 'model.pls'">
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'plsScores')">
              <i :class="plotSections.plsScores ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>Scores Plot</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.plsScores" class="plot-container">
                <div class="plot-controls">
                  <div class="control-group">
                    <label>X Axis</label>
                    <Dropdown v-model="pcaXAxis" :options="state.pcaAxisOptions" optionLabel="label" optionValue="value" />
                  </div>
                  <div class="control-group">
                    <label>Y Axis</label>
                    <Dropdown v-model="pcaYAxis" :options="state.pcaAxisOptions" optionLabel="label" optionValue="value" />
                  </div>
                  <div v-if="state.scoreColorOptions.length > 1" class="control-group">
                    <label>Color by</label>
                    <Dropdown v-model="scoreColorMode" :options="state.scoreColorOptions" optionLabel="label" optionValue="value" />
                  </div>
                </div>
                <PlotlyChart :data="state.plsScoresData" :layout="state.plsScoresLayout" :config="state.pcaScoresConfig" />
              </div>
            </Transition>
          </div>
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'plsLoadings')">
              <i :class="plotSections.plsLoadings ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>Loadings Plot</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.plsLoadings" class="plot-container">
                <PlotlyChart :data="state.plsLoadingsData" :layout="state.plsLoadingsLayout" :config="state.pcaLoadingsConfig" />
              </div>
            </Transition>
          </div>
        </template>

        <!-- PLS-DA -->
        <template v-if="state.nodeTypeKey === 'classification.plsda'">
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'classificationScores')">
              <i :class="plotSections.classificationScores ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>Scores Plot</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.classificationScores" class="plot-container">
                <div class="plot-controls">
                  <div class="control-group">
                    <label>X Axis</label>
                    <Dropdown v-model="pcaXAxis" :options="state.pcaAxisOptions" optionLabel="label" optionValue="value" />
                  </div>
                  <div class="control-group">
                    <label>Y Axis</label>
                    <Dropdown v-model="pcaYAxis" :options="state.pcaAxisOptions" optionLabel="label" optionValue="value" />
                  </div>
                  <div v-if="state.scoreColorOptions.length > 1" class="control-group">
                    <label>Color by</label>
                    <Dropdown v-model="scoreColorMode" :options="state.scoreColorOptions" optionLabel="label" optionValue="value" />
                  </div>
                </div>
                <PlotlyChart :data="state.classificationScoresData" :layout="state.classificationScoresLayout" :config="state.pcaScoresConfig" />
              </div>
            </Transition>
          </div>
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'plsdaLoadings')">
              <i :class="plotSections.plsdaLoadings ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>Loadings Plot</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.plsdaLoadings" class="plot-container">
                <div class="plot-controls">
                  <Button
                    :label="'Line Plot'"
                    :class="{ 'p-button-outlined': plsdaLoadingsViewMode !== 'lines' }"
                    @click="plsdaLoadingsViewMode = 'lines'"
                    size="small"
                  />
                  <Button
                    :label="'Biplot'"
                    :class="{ 'p-button-outlined': plsdaLoadingsViewMode !== 'biplot' }"
                    @click="plsdaLoadingsViewMode = 'biplot'"
                    size="small"
                  />
                </div>
                <PlotlyChart :data="state.plsdaLoadingsData" :layout="state.plsdaLoadingsLayout" :config="state.pcaLoadingsConfig" />
              </div>
            </Transition>
          </div>
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'plsdaVip')">
              <i :class="plotSections.plsdaVip ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>VIP Scores (Variable Importance)</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.plsdaVip" class="plot-container">
                <PlotlyChart :data="state.plsdaVipData" :layout="state.plsdaVipLayout" />
              </div>
            </Transition>
          </div>
        </template>

        <!-- SIMCA -->
        <template v-if="state.nodeTypeKey === 'classification.simca'">
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'classificationScores')">
              <i :class="plotSections.classificationScores ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>Scores Plot (Class Model Projections)</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.classificationScores" class="plot-container">
                <div class="plot-controls">
                  <div class="control-group">
                    <label>X Axis</label>
                    <Dropdown v-model="pcaXAxis" :options="state.pcaAxisOptions" optionLabel="label" optionValue="value" />
                  </div>
                  <div class="control-group">
                    <label>Y Axis</label>
                    <Dropdown v-model="pcaYAxis" :options="state.pcaAxisOptions" optionLabel="label" optionValue="value" />
                  </div>
                  <div v-if="state.scoreColorOptions.length > 1" class="control-group">
                    <label>Color by</label>
                    <Dropdown v-model="scoreColorMode" :options="state.scoreColorOptions" optionLabel="label" optionValue="value" />
                  </div>
                </div>
                <PlotlyChart :data="state.classificationScoresData" :layout="state.classificationScoresLayout" :config="state.pcaScoresConfig" />
              </div>
            </Transition>
          </div>
        </template>

        <!-- KNN -->
        <template v-if="state.nodeTypeKey === 'classification.knn'">
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'classificationScores')">
              <i :class="plotSections.classificationScores ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>Feature Space Plot</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.classificationScores" class="plot-container">
                <div class="plot-controls">
                  <div class="control-group">
                    <label>X Axis</label>
                    <Dropdown v-model="pcaXAxis" :options="state.pcaAxisOptions" optionLabel="label" optionValue="value" />
                  </div>
                  <div class="control-group">
                    <label>Y Axis</label>
                    <Dropdown v-model="pcaYAxis" :options="state.pcaAxisOptions" optionLabel="label" optionValue="value" />
                  </div>
                  <div v-if="state.scoreColorOptions.length > 1" class="control-group">
                    <label>Color by</label>
                    <Dropdown v-model="scoreColorMode" :options="state.scoreColorOptions" optionLabel="label" optionValue="value" />
                  </div>
                </div>
                <PlotlyChart :data="state.classificationScoresData" :layout="state.classificationScoresLayout" :config="state.pcaScoresConfig" />
              </div>
            </Transition>
          </div>
        </template>

        <!-- Regression: Predicted vs Actual (PLS/PCR/SVR) -->
        <template v-if="['model.pls', 'model.pcr', 'model.svr'].includes(state.nodeTypeKey) && state.regressionCorrelationData.length > 0">
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'regressionCorrelation')">
              <i :class="plotSections.regressionCorrelation ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>Predicted vs Actual</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.regressionCorrelation" class="plot-container">
                <div v-if="state.regressionTargetOptions.length > 1" class="plot-controls">
                  <div class="control-group">
                    <label>Target</label>
                    <Dropdown v-model="regressionTargetIdx" :options="state.regressionTargetOptions" optionLabel="label" optionValue="value" />
                  </div>
                </div>
                <PlotlyChart :data="state.regressionCorrelationData" :layout="state.regressionCorrelationLayout" />
              </div>
            </Transition>
          </div>
        </template>

        <!-- Classification: Confusion Matrices -->
        <template v-if="['classification.plsda', 'classification.simca', 'classification.knn'].includes(state.nodeTypeKey)">
          <div v-if="state.plsdaConfusionTrainData.length > 0" class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'plsdaConfusionTrain')">
              <i :class="plotSections.plsdaConfusionTrain ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>Confusion Matrix (Training)</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.plsdaConfusionTrain" class="plot-container">
                <PlotlyChart :data="state.plsdaConfusionTrainData" :layout="state.plsdaConfusionTrainLayout" />
              </div>
            </Transition>
          </div>
          <div v-if="state.plsdaConfusionCVData.length > 0" class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'plsdaConfusionCV')">
              <i :class="plotSections.plsdaConfusionCV ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>Confusion Matrix (Cross-Validation)</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.plsdaConfusionCV" class="plot-container">
                <PlotlyChart :data="state.plsdaConfusionCVData" :layout="state.plsdaConfusionCVLayout" />
              </div>
            </Transition>
          </div>
        </template>

        <!-- Classification: Per-Class Accuracy -->
        <template v-if="['classification.plsda', 'classification.simca', 'classification.knn'].includes(state.nodeTypeKey) && state.classificationAccuracyData.length > 0">
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'classificationAccuracy')">
              <i :class="plotSections.classificationAccuracy ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>Per-Class Accuracy</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.classificationAccuracy" class="plot-container">
                <PlotlyChart :data="state.classificationAccuracyData" :layout="state.classificationAccuracyLayout" />
              </div>
            </Transition>
          </div>
        </template>

        <!-- HCA -->
        <template v-if="state.nodeTypeKey === 'model.hca'">
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'hcaDendrogram')">
              <i :class="plotSections.hcaDendrogram ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>Dendrogram</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.hcaDendrogram" class="plot-container">
                <PlotlyChart :data="state.hcaDendrogramData" :layout="state.hcaDendrogramLayout" />
              </div>
            </Transition>
          </div>
        </template>

        <!-- Peak Finding -->
        <template v-if="state.nodeTypeKey === 'analysis.peak_finding'">
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'peakFinding')">
              <i :class="plotSections.peakFinding ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>Spectra with Peaks</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.peakFinding" class="plot-container">
                <PlotlyChart :data="state.peakFindingPlotData" :layout="state.peakFindingPlotLayout" />
              </div>
            </Transition>
          </div>
        </template>

        <!-- Compare vs. Library -->
        <template v-if="state.nodeTypeKey === 'analysis.compare_library'">
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'libraryCompare')">
              <i :class="plotSections.libraryCompare ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>Library Overlay</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.libraryCompare" class="plot-container">
                <div v-if="filteredLibraryCompareCandidates.length > 0" class="library-candidate-controls">
                  <div class="control-group library-sample-picker">
                    <label>Spectrum</label>
                    <Dropdown
                      v-model="selectedLibrarySample"
                      :options="libraryCompareSampleOptions"
                      optionLabel="label"
                      optionValue="value"
                    />
                  </div>
                  <div class="control-group library-candidate-picker">
                    <label>Species rank</label>
                    <div class="species-rank-list" role="listbox" aria-label="Library species to overlay">
                      <button
                        v-for="candidate in filteredLibraryCompareCandidates"
                        :key="libraryCandidateKey(candidate)"
                        type="button"
                        class="species-rank-row"
                        :class="{ selected: isLibraryCandidateChecked(candidate) }"
                        @click="toggleLibraryCandidate(candidate)"
                      >
                        <input
                          type="checkbox"
                          :checked="isLibraryCandidateChecked(candidate)"
                          tabindex="-1"
                          aria-hidden="true"
                          readonly
                        />
                        <span
                          class="species-color-swatch"
                          :style="{ background: libraryTraceColorForCandidate(candidate) }"
                          aria-hidden="true"
                        />
                        <span>
                          #{{ candidate.sample_rank ?? candidate.rank ?? "?" }} {{ candidate.library ?? "Library" }}
                        </span>
                        <strong>HQI {{ formatHqi(candidate.hqi) }}</strong>
                      </button>
                    </div>
                  </div>
                  <span
                    v-if="selectedLibraryCandidateRecords.length === 1"
                    class="candidate-status-badge"
                    :class="`candidate-status-${selectedLibraryCandidateRecords[0].candidate_status || 'review'}`"
                  >
                    {{ formatCandidateStatus(selectedLibraryCandidateRecords[0].candidate_status) }}
                  </span>
                  <span v-else-if="selectedLibraryCandidateRecords.length > 1" class="candidate-hqi">
                    {{ selectedLibraryCandidateRecords.length }} species selected
                  </span>
                  <span
                    v-if="selectedLibraryAlignmentStatus"
                    class="candidate-alignment-badge"
                    :class="{ aligned: selectedLibraryAlignmentStatus.aligned }"
                  >
                    <i :class="selectedLibraryAlignmentStatus.aligned ? 'pi pi-check-circle' : 'pi pi-exclamation-triangle'" />
                    {{ selectedLibraryAlignmentStatus.label }}
                  </span>
                  <span v-if="selectedLibraryCandidateCaveat" class="candidate-caveat">
                    {{ selectedLibraryCandidateCaveat }}
                  </span>
                </div>
                <PlotlyChart :data="libraryCompareInteractiveData" :layout="libraryCompareInteractiveLayout" />
              </div>
            </Transition>
          </div>
        </template>

        <!-- Plot / Contour Visualization -->
        <template v-if="state.nodeTypeKey === 'output.plot' || state.nodeTypeKey === 'output.contour'">
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'plotVisualization')">
              <i :class="plotSections.plotVisualization ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>Visualization</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.plotVisualization" class="plot-container">
                <div v-if="state.plotNodeWarning" class="plot-warning" :title="state.plotNodeWarning">
                  <i class="pi pi-info-circle" />
                  <span>{{ state.plotNodeWarning }}</span>
                </div>
                <PlotlyChart v-if="state.plotNodeData.length > 0" :data="state.plotNodeData" :layout="state.plotNodeLayout" />
                <div v-else class="empty-plot-message">
                  <i class="pi pi-play" />
                  <span>Run the node to generate the visualization.</span>
                </div>
              </div>
            </Transition>
          </div>
        </template>

        <!-- Preprocessing / DATA Spectra + Interactive Contour -->
        <template v-if="(state.isPreprocessingNode || state.isDataNode) && state.isSpectraData">
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'spectraOverview')">
              <i :class="plotSections.spectraOverview ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>Spectra Overview</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.spectraOverview" class="plot-container">
                <div class="plot-controls">
                  <div class="control-group">
                    <label>Display</label>
                    <Dropdown v-model="spectraDisplayMode" :options="state.spectraDisplayOptions" optionLabel="label" optionValue="value" />
                  </div>
                </div>
                <PlotlyChart
                  v-if="spectraDisplayMode === 'overlay'"
                  :data="state.spectraOverlayData"
                  :layout="state.spectraOverlayLayout"
                />
                <div v-else class="interactive-contour-container">
                  <PlotlyChart
                    :data="state.spectraContourData"
                    :layout="state.spectraContourLayout"
                    @click="(e) => $emit('contourClick', e)"
                  />
                  <div v-if="state.contourClickPoint" class="slice-plots">
                    <div class="slice-plot">
                      <h5>Spectrum at Sample {{ state.contourClickPoint.sampleIdx + 1 }}</h5>
                      <PlotlyChart :data="state.horizontalSliceData" :layout="state.horizontalSliceLayout" />
                    </div>
                    <div class="slice-plot">
                      <h5>Time Profile at {{ state.contourClickPoint.wavenumber.toFixed(1) }} {{ state.nodeOutput?.metadata?.x_units || '' }}</h5>
                      <PlotlyChart :data="state.verticalSliceData" :layout="state.verticalSliceLayout" />
                    </div>
                  </div>
                  <div v-else class="slice-hint">
                    <i class="pi pi-info-circle" />
                    <span>Click on the contour plot to view spectral and temporal slices</span>
                  </div>
                </div>
              </div>
            </Transition>
          </div>
        </template>

        <!-- Generic Data Overview (also covers preprocessing nodes with non-spectral output) -->
        <template v-if="state.isGenericDataNode || (state.isPreprocessingNode && !state.isSpectraData)">
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'dataOverview')">
              <i :class="plotSections.dataOverview ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>Data Overview</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.dataOverview" class="plot-container">
                <div class="plot-controls">
                  <div class="control-group">
                    <label>Display</label>
                    <Dropdown v-model="genericDisplayMode" :options="state.genericDisplayOptions" optionLabel="label" optionValue="value" />
                  </div>
                  <template v-if="genericDisplayMode === 'scatter'">
                    <div class="control-group">
                      <label>X Axis</label>
                      <Dropdown v-model="featureXAxis" :options="state.featureOptions" optionLabel="label" optionValue="value" />
                    </div>
                    <div class="control-group">
                      <label>Y Axis</label>
                      <Dropdown v-model="featureYAxis" :options="state.featureOptions" optionLabel="label" optionValue="value" />
                    </div>
                  </template>
                </div>
                <PlotlyChart
                  v-if="genericDisplayMode === 'boxplot'"
                  :data="state.genericBoxPlotData"
                  :layout="state.genericBoxPlotLayout"
                />
                <PlotlyChart
                  v-else
                  :data="state.genericScatterData"
                  :layout="state.genericScatterLayout"
                />
              </div>
            </Transition>
          </div>
        </template>

        <!-- Cluster Scatter (KMeans / DBSCAN) -->
        <template v-if="state.nodeTypeKey === 'model.kmeans' || state.nodeTypeKey === 'model.dbscan'">
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'clusterScatter')">
              <i :class="plotSections.clusterScatter ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>Cluster Scatter</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.clusterScatter" class="plot-container">
                <div v-if="state.clusterScatterData.length > 0">
                  <PlotlyChart :data="state.clusterScatterData" :layout="state.clusterScatterLayout" />
                </div>
                <div v-else class="no-plot-message">
                  Execute the node to see cluster assignments.
                </div>
              </div>
            </Transition>
          </div>
        </template>

        <!-- NMF / ICA -->
        <template v-if="state.nodeTypeKey === 'model.nmf' || state.nodeTypeKey === 'model.ica'">
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'mcrConcentrations')">
              <i :class="plotSections.mcrConcentrations ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>{{ state.nodeTypeKey === 'model.nmf' ? 'Basis Weights (W)' : 'Source Signals (S)' }}</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.mcrConcentrations" class="plot-container">
                <PlotlyChart :data="state.mcrConcentrationData" :layout="state.mcrConcentrationLayout" />
              </div>
            </Transition>
          </div>
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'mcrSpectra')">
              <i :class="plotSections.mcrSpectra ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>{{ state.nodeTypeKey === 'model.nmf' ? 'Basis Spectra (H)' : 'Spectral Components' }}</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.mcrSpectra" class="plot-container">
                <PlotlyChart :data="state.mcrSpectraData" :layout="state.mcrSpectraLayout" />
              </div>
            </Transition>
          </div>
        </template>

        <!-- Outlier Detection -->
        <template v-if="state.nodeTypeKey === 'diagnostics.outliers'">
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'outlierChart')">
              <i :class="plotSections.outlierChart ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>T² vs Q Control Chart</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.outlierChart" class="plot-container">
                <div v-if="state.outlierChartData.length > 0">
                  <PlotlyChart :data="state.outlierChartData" :layout="state.outlierChartLayout" />
                </div>
                <div v-else class="no-plot-message">
                  Execute the node to see outlier diagnostics.
                </div>
              </div>
            </Transition>
          </div>
        </template>

        <!-- Holdout / CV Evaluation -->
        <template v-if="state.nodeTypeKey === 'diagnostics.holdout_evaluation' || state.nodeTypeKey === 'diagnostics.cross_validation'">
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'evaluationResults')">
              <i :class="plotSections.evaluationResults ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>Evaluation Results</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.evaluationResults" class="plot-container">
                <div v-if="state.holdoutVisualization" class="evaluation-viz">
                  <template v-if="state.holdoutVisualization.type === 'confusion_matrix'">
                    <PlotlyChart :data="state.holdoutConfusionData" :layout="state.holdoutConfusionLayout" />
                  </template>
                  <template v-else-if="state.holdoutVisualization.type === 'predicted_vs_actual'">
                    <PlotlyChart :data="state.holdoutRegressionData" :layout="state.holdoutRegressionLayout" />
                  </template>
                </div>
                <div v-else class="no-plot-message">
                  Execute the node to see evaluation results.
                </div>
              </div>
            </Transition>
          </div>
        </template>

        <!-- Stats Summary -->
        <template v-if="state.nodeTypeKey === 'stats.summary'">
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'statsDistribution')">
              <i :class="plotSections.statsDistribution ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>Summary Plot</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.statsDistribution" class="plot-container">
                <PlotlyChart :data="state.statsPlotData" :layout="state.statsPlotLayout" />
              </div>
            </Transition>
          </div>
        </template>
        </template>
      </div>
    </Transition>
  </section>
</template>

<script setup lang="ts">
import { computed, inject, ref, watch } from "vue";
import Button from "primevue/button";
import Dropdown from "primevue/dropdown";
import PlotlyChart from "@/components/PlotlyChart.vue";
import { scaleLibraryTraceToSamplePeaks } from "@/utils/libraryTraceScaling";
import { NODE_DETAIL_STATE_KEY } from "../state/useNodeDetailState";

/* eslint-disable @typescript-eslint/no-explicit-any */

defineProps<{
  expanded: boolean;
}>();

defineEmits<{
  (e: "toggle"): void;
  (e: "togglePlot", key: string): void;
  (e: "contourClick", event: any): void;
}>();

const detailState = inject(NODE_DETAIL_STATE_KEY);
if (!detailState) {
  throw new Error("PlotsPanel must be rendered inside NodeDetailView (missing NODE_DETAIL_STATE_KEY)");
}
const { writable, plotSections: plotSectionsRef, plots } = detailState;

// Re-expose under the names the template uses. Refs auto-unwrap in template.
const plotSections = plotSectionsRef;
const state = plots;
// Writable refs: v-model binds directly — mutating .value propagates to shell.
const pcaXAxis = writable.pcaXAxis;
const pcaYAxis = writable.pcaYAxis;
const scoreColorMode = writable.scoreColorMode;
const plsdaLoadingsViewMode = writable.plsdaLoadingsViewMode;
const regressionTargetIdx = writable.regressionTargetIdx;
const spectraDisplayMode = writable.spectraDisplayMode;
const genericDisplayMode = writable.genericDisplayMode;
const featureXAxis = writable.featureXAxis;
const featureYAxis = writable.featureYAxis;

type LibraryCompareCandidate = {
  rank?: number;
  sample_rank?: number;
  global_rank?: number;
  sample_index?: number;
  library_index?: number;
  sample_trace_index?: number;
  library_trace_index?: number;
  sample?: string;
  library?: string;
  hqi?: number;
  hqi_band?: string;
  raw_hqi_band?: string;
  candidate_status?: string;
  overlap_sufficient?: boolean;
  coverage_fraction?: number;
  baseline_suspected?: boolean;
  confidence_caveats?: string;
  sample_spacing?: number | null;
  library_spacing?: number | null;
  alignment_spacing?: number | null;
  grid_aligned?: boolean;
  interpolation?: string;
  x?: Array<number | null>;
  sample_x?: Array<number | null>;
  sample_y?: Array<number | null>;
  library_x?: Array<number | null>;
  library_y?: Array<number | null>;
  comparison_x?: Array<number | null>;
  comparison_sample_y?: Array<number | null>;
  comparison_library_y?: Array<number | null>;
  y_units?: string;
};

type LibraryCompareTrace = {
  sample_index?: number;
  library_index?: number;
  sample?: string;
  library?: string;
  x?: Array<number | null>;
  y?: Array<number | null>;
};

type McrCandidatePair = {
  component_index?: number;
  component_name?: string;
  target_index?: number;
  target_name?: string;
  correlation?: number;
  r2?: number | null;
  rmse?: number | null;
  normalized_rmse?: number | null;
  actual?: unknown;
  predicted?: unknown;
};

const selectedMcrCandidate = ref(0);
const selectedLibraryCandidateKeys = ref<string[]>([]);
const selectedLibrarySample = ref<string | number | null>(null);

const mcrGroundTruthComparison = computed<Record<string, any> | null>(() => {
  if (state.value.nodeTypeKey !== "model.mcr_als") return null;
  const port = (state.value.nodeOutput as any)?.ports?.ground_truth_comparison;
  const portPayload = port && typeof port === "object" && "value" in port ? port.value : port;
  if (portPayload && typeof portPayload === "object") return portPayload;
  const embedded = (state.value.nodeOutput as any)?.metadata?.ground_truth_comparison;
  return embedded && typeof embedded === "object" ? embedded : null;
});

const mcrCandidatePairs = computed<McrCandidatePair[]>(() => {
  const raw = mcrGroundTruthComparison.value?.metadata?.candidate_pairs;
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((pair) => pair && typeof pair === "object")
    .slice()
    .sort((a, b) => Math.abs(Number(b.correlation ?? 0)) - Math.abs(Number(a.correlation ?? 0)));
});

const mcrCandidateOptions = computed(() =>
  mcrCandidatePairs.value.map((pair, index) => ({
    value: index,
    label: `${pair.component_name ?? `Component ${Number(pair.component_index ?? index) + 1}`} vs ${pair.target_name ?? `Target ${Number(pair.target_index ?? index) + 1}`} · r ${formatMcrNumber(pair.correlation)}`,
  }))
);

const selectedMcrCandidateRecord = computed<McrCandidatePair | null>(() => {
  return mcrCandidatePairs.value[selectedMcrCandidate.value] ?? null;
});

const toFiniteNumberList = (values: unknown): number[] => {
  return Array.isArray(values)
    ? values.map(Number).filter((value) => Number.isFinite(value))
    : [];
};

const maxNormalize = (values: number[]): number[] => {
  const finiteAbs = values.map((value) => Math.abs(value)).filter(Number.isFinite);
  const maxAbs = finiteAbs.length > 0 ? Math.max(...finiteAbs) : 0;
  return maxAbs > 0 ? values.map((value) => value / maxAbs) : values;
};

const mcrSelectedValidationScatterData = computed(() => {
  const candidate = selectedMcrCandidateRecord.value as (McrCandidatePair & { actual?: unknown; predicted?: unknown }) | null;
  const actual = toFiniteNumberList(candidate?.actual);
  const predicted = toFiniteNumberList(candidate?.predicted);
  if (actual.length > 0 && predicted.length > 0) {
    const n = Math.min(actual.length, predicted.length);
    const x = actual.slice(0, n);
    const y = predicted.slice(0, n);
    const lo = Math.min(...x, ...y);
    const hi = Math.max(...x, ...y);
    return [
      {
        type: "scatter",
        mode: "markers",
        x,
        y,
        name: "Samples",
        marker: { color: "#3b82f6", size: 8, opacity: 0.72 },
        hovertemplate: "Target: %{x:.4g}<br>Recovered: %{y:.4g}<extra></extra>",
      },
      {
        type: "scatter",
        mode: "lines",
        x: [lo, hi],
        y: [lo, hi],
        name: "Ideal",
        line: { dash: "dash", color: "#94a3b8" },
      },
    ];
  }
  return state.value.mcrValidationScatterData;
});

const mcrSelectedSpectrumData = computed(() => {
  const candidate = selectedMcrCandidateRecord.value;
  const componentIndex = Number(candidate?.component_index);
  const metadata = (state.value.nodeOutput as any)?.metadata || {};
  const St = Array.isArray(metadata.St) ? metadata.St : [];
  const row = Number.isInteger(componentIndex) && componentIndex >= 0 ? St[componentIndex] : null;
  const spectrum = Array.isArray(row) ? row.map(Number) : [];
  if (spectrum.length === 0) return [];
  const normalized = maxNormalize(spectrum);
  const rawX = Array.isArray(metadata.spectral_wavenumbers) ? metadata.spectral_wavenumbers.map(Number) : [];
  const x = rawX.length === normalized.length ? rawX : Array.from({ length: normalized.length }, (_, i) => i);
  const traces: any[] = [
    {
      type: "scatter",
      mode: "lines",
      x,
      y: normalized,
      name: String(candidate?.component_name || `Component ${componentIndex + 1}`),
      line: { width: 2, color: "#14b8a6" },
      hovertemplate: "%{x:.4g}<br>Normalized intensity: %{y:.4g}<extra></extra>",
    },
  ];
  const recovery = mcrGroundTruthComparison.value?.spectra_recovery || mcrGroundTruthComparison.value?.metadata?.spectra_recovery;
  const truthIndex = Number((candidate as any)?.target_index ?? (candidate as any)?.truth_index);
  const truthRows = Array.isArray(recovery?.truth_spectra) ? recovery.truth_spectra : [];
  const truthRow = Number.isInteger(truthIndex) && truthIndex >= 0 ? truthRows[truthIndex] : null;
  const truthSpectrum = Array.isArray(truthRow) ? truthRow.map(Number) : [];
  if (truthSpectrum.length > 0) {
    const truthXRaw = Array.isArray(recovery?.truth_spectra_x) ? recovery.truth_spectra_x.map(Number) : [];
    const truthX = truthXRaw.length === truthSpectrum.length
      ? truthXRaw
      : Array.from({ length: truthSpectrum.length }, (_, i) => i);
    traces.push({
      type: "scatter",
      mode: "lines",
      x: truthX,
      y: maxNormalize(truthSpectrum),
      name: String((candidate as any)?.target_name || `Ground truth ${truthIndex + 1}`),
      line: { width: 2, color: "#f59e0b", dash: "dot" },
      hovertemplate: "%{x:.4g}<br>Ground truth: %{y:.4g}<extra></extra>",
    });
  }
  return traces;
});

watch(
  () => mcrCandidatePairs.value.length,
  (length) => {
    if (length === 0 || selectedMcrCandidate.value >= length) {
      selectedMcrCandidate.value = 0;
    }
  },
  { immediate: true }
);

const libraryCompareTracePayload = computed(() => (state.value.nodeOutput as any)?.plots?.library_compare_candidates || {});

const libraryCompareCandidates = computed<LibraryCompareCandidate[]>(() => {
  const raw = libraryCompareTracePayload.value?.data;
  return Array.isArray(raw) ? raw : [];
});

const libraryCompareSampleTraceMap = computed(() => {
  const traces = libraryCompareTracePayload.value?.samples;
  const map = new Map<number, LibraryCompareTrace>();
  if (!Array.isArray(traces)) return map;
  for (const trace of traces) {
    const index = Number(trace?.sample_index);
    if (Number.isFinite(index)) map.set(index, trace as LibraryCompareTrace);
  }
  return map;
});

const libraryCompareLibraryTraceMap = computed(() => {
  const traces = libraryCompareTracePayload.value?.libraries;
  const map = new Map<number, LibraryCompareTrace>();
  if (!Array.isArray(traces)) return map;
  for (const trace of traces) {
    const index = Number(trace?.library_index);
    if (Number.isFinite(index)) map.set(index, trace as LibraryCompareTrace);
  }
  return map;
});

const libraryCompareSampleOptions = computed(() => {
  const seen = new Set<string>();
  const options: Array<{ value: string; label: string }> = [];
  for (const candidate of libraryCompareCandidates.value) {
    const label = String(candidate.sample ?? `Sample ${Number(candidate.sample_index ?? options.length) + 1}`);
    if (seen.has(label)) continue;
    seen.add(label);
    options.push({ value: label, label });
  }
  return options;
});

const filteredLibraryCompareCandidates = computed(() => {
  const sample = selectedLibrarySample.value;
  if (sample === null || sample === undefined || sample === "") {
    return libraryCompareCandidates.value;
  }
  return libraryCompareCandidates.value.filter((candidate) => String(candidate.sample ?? "") === String(sample));
});

const selectedLibraryCandidateRecords = computed<LibraryCompareCandidate[]>(() =>
  filteredLibraryCompareCandidates.value.filter((candidate) =>
    selectedLibraryCandidateKeys.value.includes(libraryCandidateKey(candidate))
  )
);

const selectedLibraryCandidateCaveat = computed(() => {
  if (selectedLibraryCandidateRecords.value.length !== 1) return "";
  const candidate = selectedLibraryCandidateRecords.value[0];
  if (!candidate?.confidence_caveats) return "";
  const coverage = Number.isFinite(Number(candidate.coverage_fraction))
    ? `coverage ${Number(candidate.coverage_fraction).toFixed(2)}`
    : "";
  return coverage ? `${candidate.confidence_caveats} · ${coverage}` : candidate.confidence_caveats;
});

const selectedLibraryAlignmentStatus = computed(() => {
  const candidate = selectedLibraryCandidateRecords.value[0] ?? filteredLibraryCompareCandidates.value[0];
  if (!candidate) return null;
  const aligned = candidate.grid_aligned !== false;
  const spacing = formatSpacing(candidate.alignment_spacing);
  const sampleSpacing = formatSpacing(candidate.sample_spacing);
  const librarySpacing = formatSpacing(candidate.library_spacing);
  const spacingLabel = spacing
    ? `Δ ${spacing} cm-1`
    : sampleSpacing && librarySpacing
      ? `sample/library Δ ${sampleSpacing}/${librarySpacing} cm-1`
      : "";
  return {
    aligned,
    label: `${aligned ? "Grid aligned" : "Grid alignment warning"}${spacingLabel ? ` · ${spacingLabel}` : ""}`,
  };
});

watch(
  libraryCompareSampleOptions,
  (options) => {
    if (options.length === 0) {
      selectedLibrarySample.value = null;
      selectedLibraryCandidateKeys.value = [];
      return;
    }
    if (!options.some((option) => option.value === selectedLibrarySample.value)) {
      selectedLibrarySample.value = options[0].value;
    }
  },
  { immediate: true }
);

watch(
  () => selectedLibrarySample.value,
  () => {
    selectedLibraryCandidateKeys.value = [];
  }
);

watch(
  () => filteredLibraryCompareCandidates.value.map(libraryCandidateKey).join("|"),
  () => {
    if (filteredLibraryCompareCandidates.value.length === 0) {
      selectedLibraryCandidateKeys.value = [];
      return;
    }
    const validKeys = new Set(filteredLibraryCompareCandidates.value.map(libraryCandidateKey));
    const nextKeys = selectedLibraryCandidateKeys.value.filter((key) => validKeys.has(key));
    if (nextKeys.length === 0) {
      nextKeys.push(libraryCandidateKey(filteredLibraryCompareCandidates.value[0]));
    }
    selectedLibraryCandidateKeys.value = nextKeys;
  },
  { immediate: true }
);

const libraryCompareInteractiveData = computed(() => {
  const candidates = selectedLibraryCandidateRecords.value;
  const firstCandidate = candidates[0] ?? filteredLibraryCompareCandidates.value[0];
  if (!firstCandidate) {
    return state.value.libraryComparePlotData;
  }
  const firstSampleTraceIndex = Number(firstCandidate?.sample_trace_index ?? firstCandidate?.sample_index);
  const firstSampleTrace = Number.isFinite(firstSampleTraceIndex)
    ? libraryCompareSampleTraceMap.value.get(firstSampleTraceIndex)
    : undefined;
  const sampleX = firstCandidate?.sample_x ?? firstCandidate?.x ?? firstSampleTrace?.x;
  const sampleY = firstCandidate?.sample_y ?? firstSampleTrace?.y;
  if (!sampleX || !sampleY) {
    return state.value.libraryComparePlotData;
  }
  const traces: any[] = [
    {
      type: "scatter",
      mode: "lines",
      x: sampleX,
      y: sampleY,
      name: firstCandidate.sample || "Sample",
      line: { color: "#f8fafc", width: 2 },
    }
  ];
  for (const candidate of candidates) {
    const libraryTraceIndex = Number(candidate?.library_trace_index ?? candidate?.library_index);
    const libraryTrace = Number.isFinite(libraryTraceIndex)
      ? libraryCompareLibraryTraceMap.value.get(libraryTraceIndex)
      : undefined;
    const libraryX = candidate?.library_x ?? candidate?.x ?? libraryTrace?.x;
    const libraryY = candidate?.library_y ?? libraryTrace?.y;
    if (!libraryX || !libraryY) continue;
    traces.push({
      type: "scatter",
      mode: "lines",
      x: libraryX,
      y: scaleLibraryTraceToSamplePeaks(libraryX, libraryY, sampleX, sampleY),
      name: `${candidate.library || "Library"} (HQI ${formatHqi(candidate.hqi)})`,
      line: { color: libraryTraceColorForCandidate(candidate), width: 2 },
    });
  }
  return traces;
});

const libraryCompareInteractiveLayout = computed(() => {
  const candidate = selectedLibraryCandidateRecords.value[0] ?? filteredLibraryCompareCandidates.value[0];
  if (!candidate) return state.value.libraryComparePlotLayout;
  const backendLayout = (state.value.nodeOutput as any)?.plots?.library_compare_candidates?.layout || {};
  return {
    ...state.value.libraryComparePlotLayout,
    ...backendLayout,
    title: `${candidate.sample || "Sample"} vs selected library signatures`,
    yaxis: {
      ...(state.value.libraryComparePlotLayout?.yaxis || {}),
      ...(backendLayout.yaxis || {}),
      title: candidate.y_units || "Max-normalized response",
    },
  };
});

function formatHqi(value?: number): string {
  if (!Number.isFinite(Number(value))) return "n/a";
  return Number(value).toFixed(1);
}

function formatSpacing(value?: number | null): string {
  if (!Number.isFinite(Number(value))) return "";
  return Number(value).toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
}

function formatMcrNumber(value?: number | null): string {
  if (!Number.isFinite(Number(value))) return "n/a";
  return Number(value).toFixed(4);
}

function formatCandidateStatus(value?: string): string {
  if (value === "auto_selected") return "Auto-selected";
  if (value === "rejected") return "Rejected";
  return "Review";
}

function libraryCandidateKey(candidate: LibraryCompareCandidate): string {
  return `${Number(candidate.sample_index ?? -1)}:${Number(candidate.library_index ?? -1)}`;
}

function isLibraryCandidateChecked(candidate: LibraryCompareCandidate): boolean {
  return selectedLibraryCandidateKeys.value.includes(libraryCandidateKey(candidate));
}

function toggleLibraryCandidate(candidate: LibraryCompareCandidate): void {
  const key = libraryCandidateKey(candidate);
  selectedLibraryCandidateKeys.value = isLibraryCandidateChecked(candidate)
    ? selectedLibraryCandidateKeys.value.filter((item) => item !== key)
    : [...selectedLibraryCandidateKeys.value, key];
}

function libraryTraceColorForCandidate(candidate: LibraryCompareCandidate): string {
  const palette = [
    "#38bdf8", "#f59e0b", "#22c55e", "#e879f9", "#fb7185", "#a78bfa",
    "#14b8a6", "#f97316", "#84cc16", "#60a5fa", "#f472b6", "#c084fc",
  ];
  const index = Number(candidate.library_trace_index ?? candidate.library_index ?? candidate.sample_rank ?? 0);
  return palette[Math.abs(Math.trunc(Number.isFinite(index) ? index : 0)) % palette.length];
}

</script>

<style scoped>
.detail-section {
  background: #1e293b;
  border-radius: 12px;
  margin-bottom: 24px;
  overflow: hidden;
  border: 1px solid #334155;
}
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  cursor: pointer;
  transition: background 0.15s;
}
.section-header:hover { background: rgba(51, 65, 85, 0.5); }
.section-title { display: flex; align-items: center; gap: 12px; }
.section-title i { font-size: 0.85rem; color: #64748b; }
.section-title h2 { margin: 0; font-size: 1.1rem; font-weight: 600; }
.section-badge {
  padding: 4px 10px;
  background: #334155;
  border-radius: 12px;
  font-size: 0.75rem;
  color: #94a3b8;
}
.section-content { padding: 20px; border-top: 1px solid #334155; }
.collapse-enter-active,
.collapse-leave-active { transition: all 0.2s ease; overflow: hidden; }
.collapse-enter-from,
.collapse-leave-to { opacity: 0; max-height: 0; padding-top: 0; padding-bottom: 0; }

.plots-content { display: flex; flex-direction: column; gap: 12px; }
.plot-subsection {
  background: #0f172a;
  border-radius: 8px;
  overflow: hidden;
}
.plot-subsection-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  cursor: pointer;
  color: #cbd5e1;
  font-size: 0.9rem;
  font-weight: 500;
}
.plot-subsection-header:hover { background: rgba(51, 65, 85, 0.3); }
.plot-subsection-header i { font-size: 0.75rem; color: #64748b; }
.plot-container { padding: 12px 14px; }
.mcr-validation-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: minmax(0, 1fr);
}
.mcr-validation-controls {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.mcr-candidate-picker { min-width: min(100%, 420px); }
.mcr-candidate-metrics {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 34px;
  color: #e2e8f0;
  font-size: 0.84rem;
}
.mcr-candidate-metrics span {
  padding: 4px 8px;
  border: 1px solid #334155;
  border-radius: 6px;
  background: #1e293b;
}
.mcr-candidate-hint {
  flex: 1 1 260px;
  min-height: 34px;
  display: inline-flex;
  align-items: center;
  color: #94a3b8;
  font-size: 0.8rem;
  line-height: 1.35;
}
.plot-warning {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  padding: 8px 10px;
  border: 1px solid rgba(245, 158, 11, 0.35);
  border-radius: 6px;
  background: rgba(245, 158, 11, 0.08);
  color: #fbbf24;
  font-size: 0.82rem;
}
.plot-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-bottom: 10px;
}
.control-group { display: flex; flex-direction: column; gap: 4px; }
.control-group label {
  font-size: 0.75rem;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.library-candidate-controls {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.library-candidate-picker { min-width: min(100%, 420px); }
.library-candidate-picker.control-group {
  align-items: flex-start;
}
.species-rank-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 4px;
  max-height: 132px;
  min-width: min(720px, 100%);
  overflow: auto;
}
.species-rank-row {
  display: grid;
  grid-template-columns: 16px 10px minmax(0, 1fr) auto;
  align-items: center;
  gap: 6px;
  border: 1px solid #334155;
  border-radius: 6px;
  background: #0f172a;
  color: #cbd5e1;
  cursor: pointer;
  font-size: 0.76rem;
  line-height: 1.15;
  padding: 4px 6px;
  text-align: left;
}
.species-rank-row:hover,
.species-rank-row.selected {
  border-color: #38bdf8;
  background: rgba(14, 165, 233, 0.14);
}
.species-rank-row input {
  pointer-events: none;
}
.species-color-swatch {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  box-shadow: 0 0 0 1px rgba(248, 250, 252, 0.28);
}
.species-rank-row span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.species-rank-row strong {
  color: #e2e8f0;
  font-weight: 600;
  white-space: nowrap;
}
.candidate-status-badge {
  display: inline-flex;
  align-items: center;
  min-height: 34px;
  padding: 0 10px;
  border-radius: 6px;
  border: 1px solid #475569;
  color: #cbd5e1;
  background: #1e293b;
  font-size: 0.8rem;
  font-weight: 600;
}
.candidate-status-auto_selected {
  color: #bbf7d0;
  border-color: #15803d;
  background: rgba(22, 101, 52, 0.28);
}
.candidate-status-rejected {
  color: #fecaca;
  border-color: #b91c1c;
  background: rgba(127, 29, 29, 0.26);
}
.candidate-status-review {
  color: #fde68a;
  border-color: #a16207;
  background: rgba(113, 63, 18, 0.28);
}
.candidate-hqi {
  min-height: 34px;
  display: inline-flex;
  align-items: center;
  color: #e2e8f0;
  font-size: 0.85rem;
}
.candidate-alignment-badge {
  min-height: 34px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #fde68a;
  border: 1px solid #a16207;
  border-radius: 6px;
  background: rgba(113, 63, 18, 0.22);
  padding: 0 10px;
  font-size: 0.8rem;
  font-weight: 600;
}
.candidate-alignment-badge.aligned {
  color: #bbf7d0;
  border-color: #15803d;
  background: rgba(22, 101, 52, 0.24);
}
.candidate-caveat {
  min-height: 34px;
  display: inline-flex;
  align-items: center;
  color: #fbbf24;
  font-size: 0.82rem;
}
.interactive-contour-container { display: flex; flex-direction: column; gap: 14px; }
.slice-plots { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.slice-plot h5 {
  margin: 0 0 6px;
  font-size: 0.8rem;
  font-weight: 600;
  color: #94a3b8;
}
.slice-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: rgba(59, 130, 246, 0.05);
  border: 1px dashed rgba(59, 130, 246, 0.3);
  border-radius: 6px;
  color: #94a3b8;
  font-size: 0.85rem;
}
.slice-hint i { color: #3b82f6; }
.empty-plot-message,
.no-plot-message {
  padding: 20px;
  color: #64748b;
  font-size: 0.9rem;
  text-align: center;
}
.empty-plot-message { display: flex; flex-direction: column; align-items: center; gap: 10px; }
.empty-plot-message i { font-size: 2rem; color: #475569; }
.evaluation-viz { width: 100%; }
</style>
