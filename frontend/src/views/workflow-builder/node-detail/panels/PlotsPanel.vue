<template>
  <section class="detail-section" v-if="state.hasOutput && state.availablePlots.length > 0">
    <div class="section-header" @click="$emit('toggle')">
      <div class="section-title">
        <i :class="expanded ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
        <h2>Plots</h2>
      </div>
      <span class="section-badge">{{ state.availablePlots.length }} visualizations</span>
    </div>
    <Transition name="collapse">
      <div v-if="expanded" class="section-content plots-content">
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
          <div class="plot-subsection">
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
          <div class="plot-subsection">
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

        <!-- Plot / Contour Visualization -->
        <template v-if="state.nodeTypeKey === 'output.plot' || state.nodeTypeKey === 'output.contour'">
          <div class="plot-subsection">
            <div class="plot-subsection-header" @click="$emit('togglePlot', 'plotVisualization')">
              <i :class="plotSections.plotVisualization ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
              <span>Visualization</span>
            </div>
            <Transition name="collapse">
              <div v-if="plotSections.plotVisualization" class="plot-container">
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

        <!-- Generic Data Overview -->
        <template v-if="state.isGenericDataNode">
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
      </div>
    </Transition>
  </section>
</template>

<script setup lang="ts">
import { inject } from "vue";
import Button from "primevue/button";
import Dropdown from "primevue/dropdown";
import PlotlyChart from "@/components/PlotlyChart.vue";
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
const plsdaLoadingsViewMode = writable.plsdaLoadingsViewMode;
const regressionTargetIdx = writable.regressionTargetIdx;
const spectraDisplayMode = writable.spectraDisplayMode;
const genericDisplayMode = writable.genericDisplayMode;
const featureXAxis = writable.featureXAxis;
const featureYAxis = writable.featureYAxis;
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
