import { defineStore } from "pinia";
import { ref, computed } from "vue";

export interface ProjectMetadata {
  name: string;
  description: string;
  author: string;
  created: string;
  modified: string;
  version: string;
  tags: string[];
}

export interface ProjectData {
  experiments: number[];
  workflows: string[];
  calibrations: number[];
  settings: Record<string, any>;
}

export interface Project {
  id: string;
  metadata: ProjectMetadata;
  data: ProjectData;
}

export interface ProjectExport {
  format: "spectrapy-project";
  version: "1.0";
  project: Project;
  exportedAt: string;
}

// Generate unique ID
const generateId = () => {
  return `proj_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
};

// Format date for display
const formatDate = (date: Date): string => {
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const days = Math.floor(diff / (1000 * 60 * 60 * 24));

  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;

  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: date.getFullYear() !== now.getFullYear() ? "numeric" : undefined,
  });
};

export const useProjectStore = defineStore("project", () => {
  // State
  const projects = ref<Project[]>([]);
  const currentProjectId = ref<string | null>(null);
  const isLoading = ref(false);
  const error = ref<string | null>(null);

  // Initialize with SpectrochemPy-based sample projects
  const initializeDefaultProjects = () => {
    const now = new Date();
    const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000);
    const twoDaysAgo = new Date(now.getTime() - 2 * 24 * 60 * 60 * 1000);
    const lastWeek = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
    const twoWeeksAgo = new Date(now.getTime() - 14 * 24 * 60 * 60 * 1000);

    projects.value = [
      // === Active Research Projects ===
      {
        id: generateId(),
        metadata: {
          name: "FTIR Calibration Study",
          description: "Wavenumber-specific absorption calibration for ethanol-water mixtures using PLS regression",
          author: "Lab User",
          created: lastWeek.toISOString(),
          modified: now.toISOString(),
          version: "1.0",
          tags: ["FTIR", "calibration", "PLS", "ethanol"],
        },
        data: {
          experiments: [1, 2],
          workflows: ["project1", "pls_regression"],
          calibrations: [],
          settings: { defaultPreprocessing: "asls", baselineMethod: "asls" },
        },
      },
      {
        id: generateId(),
        metadata: {
          name: "MCR-ALS Kinetics Study",
          description: "Time-resolved MCR-ALS analysis with kinetic constraints for reaction mechanism elucidation",
          author: "Lab User",
          created: twoDaysAgo.toISOString(),
          modified: yesterday.toISOString(),
          version: "1.0",
          tags: ["MCR-ALS", "kinetics", "time-resolved", "reaction"],
        },
        data: {
          experiments: [3, 4],
          workflows: ["project2", "efa_analysis"],
          calibrations: [],
          settings: { mcrComponents: 3, constraints: ["non_neg", "closure"] },
        },
      },

      // === SpectrochemPy Example Projects ===
      {
        id: generateId(),
        metadata: {
          name: "IR OPUS Analysis Demo",
          description: "Demonstration of Bruker OPUS file import and IR spectral analysis workflow",
          author: "Lab User",
          created: lastWeek.toISOString(),
          modified: twoDaysAgo.toISOString(),
          version: "1.0",
          tags: ["IR", "OPUS", "Bruker", "demo"],
        },
        data: {
          experiments: [5],
          workflows: ["ir_opus_analysis", "preprocessing"],
          calibrations: [],
          settings: { wavenumberRange: [4000, 400] },
        },
      },
      {
        id: generateId(),
        metadata: {
          name: "Raman Pharmaceutical Analysis",
          description: "Raman spectroscopy workflow with cosmic ray removal and fluorescence baseline correction",
          author: "Lab User",
          created: yesterday.toISOString(),
          modified: yesterday.toISOString(),
          version: "1.0",
          tags: ["Raman", "pharma", "cosmic ray", "fluorescence"],
        },
        data: {
          experiments: [6],
          workflows: ["raman_processing", "peaks"],
          calibrations: [],
          settings: { cosmicRayThreshold: 5 },
        },
      },
      {
        id: generateId(),
        metadata: {
          name: "NMR Metabolomics Study",
          description: "NMR processing pipeline for metabolomic profiling with phase correction and peak fitting",
          author: "Lab User",
          created: twoWeeksAgo.toISOString(),
          modified: lastWeek.toISOString(),
          version: "1.0",
          tags: ["NMR", "metabolomics", "peak fitting", "1H"],
        },
        data: {
          experiments: [7, 8],
          workflows: ["nmr_processing"],
          calibrations: [],
          settings: { ppmRange: [12, -2], phaseCorrection: "auto" },
        },
      },
      {
        id: generateId(),
        metadata: {
          name: "PCA Exploratory Analysis",
          description: "Principal Component Analysis for spectral data exploration and outlier detection",
          author: "Lab User",
          created: twoWeeksAgo.toISOString(),
          modified: twoWeeksAgo.toISOString(),
          version: "1.0",
          tags: ["PCA", "exploratory", "multivariate", "outliers"],
        },
        data: {
          experiments: [1, 2, 3],
          workflows: ["pca"],
          calibrations: [],
          settings: { pcaComponents: 5 },
        },
      },
      {
        id: generateId(),
        metadata: {
          name: "IRIS Relaxation Analysis",
          description: "Integral Regularized Inversion of Spectra for T2 relaxation distribution analysis",
          author: "Lab User",
          created: lastWeek.toISOString(),
          modified: lastWeek.toISOString(),
          version: "1.0",
          tags: ["IRIS", "relaxation", "T2", "distribution"],
        },
        data: {
          experiments: [9],
          workflows: ["iris_decomposition"],
          calibrations: [],
          settings: { regularization: "tikhonov", alpha: 0.01 },
        },
      },
      {
        id: generateId(),
        metadata: {
          name: "EFA Component Analysis",
          description: "Evolving Factor Analysis to determine component rank in time-resolved spectroscopy",
          author: "Lab User",
          created: twoDaysAgo.toISOString(),
          modified: twoDaysAgo.toISOString(),
          version: "1.0",
          tags: ["EFA", "rank", "evolving", "factor analysis"],
        },
        data: {
          experiments: [10],
          workflows: ["efa_analysis", "simplisma"],
          calibrations: [],
          settings: { efaDirection: "both" },
        },
      },
    ];

    // Set first project as current
    if (projects.value.length > 0 && !currentProjectId.value) {
      currentProjectId.value = projects.value[0].id;
    }
  };

  // Getters
  const currentProject = computed(() => {
    if (!currentProjectId.value) return null;
    return projects.value.find((p) => p.id === currentProjectId.value) || null;
  });

  const projectList = computed(() => {
    return projects.value.map((p) => ({
      id: p.id,
      name: p.metadata.name,
      modified: formatDate(new Date(p.metadata.modified)),
      description: p.metadata.description,
      tags: p.metadata.tags,
    }));
  });

  const recentProjects = computed(() => {
    return [...projects.value]
      .sort(
        (a, b) =>
          new Date(b.metadata.modified).getTime() -
          new Date(a.metadata.modified).getTime()
      )
      .slice(0, 5);
  });

  // Actions
  function createProject(
    name: string,
    description: string = "",
    tags: string[] = []
  ): Project {
    const now = new Date().toISOString();
    const project: Project = {
      id: generateId(),
      metadata: {
        name,
        description,
        author: "Lab User",
        created: now,
        modified: now,
        version: "1.0",
        tags,
      },
      data: {
        experiments: [],
        workflows: [],
        calibrations: [],
        settings: {},
      },
    };

    projects.value.unshift(project);
    currentProjectId.value = project.id;

    return project;
  }

  function updateProject(
    projectId: string,
    updates: Partial<ProjectMetadata>
  ): boolean {
    const project = projects.value.find((p) => p.id === projectId);
    if (!project) return false;

    project.metadata = {
      ...project.metadata,
      ...updates,
      modified: new Date().toISOString(),
    };

    return true;
  }

  function deleteProject(projectId: string): boolean {
    const index = projects.value.findIndex((p) => p.id === projectId);
    if (index === -1) return false;

    projects.value.splice(index, 1);

    // If deleted project was current, select another
    if (currentProjectId.value === projectId) {
      currentProjectId.value =
        projects.value.length > 0 ? projects.value[0].id : null;
    }

    return true;
  }

  function selectProject(projectId: string): boolean {
    const project = projects.value.find((p) => p.id === projectId);
    if (!project) return false;

    currentProjectId.value = projectId;

    // Update modified time
    project.metadata.modified = new Date().toISOString();

    return true;
  }

  function duplicateProject(projectId: string): Project | null {
    const original = projects.value.find((p) => p.id === projectId);
    if (!original) return null;

    const now = new Date().toISOString();
    const duplicate: Project = {
      id: generateId(),
      metadata: {
        ...original.metadata,
        name: `${original.metadata.name} (Copy)`,
        created: now,
        modified: now,
      },
      data: { ...original.data },
    };

    projects.value.unshift(duplicate);
    return duplicate;
  }

  // Export/Import
  function exportProject(projectId: string): ProjectExport | null {
    const project = projects.value.find((p) => p.id === projectId);
    if (!project) return null;

    return {
      format: "spectrapy-project",
      version: "1.0",
      project: JSON.parse(JSON.stringify(project)),
      exportedAt: new Date().toISOString(),
    };
  }

  function importProject(data: ProjectExport): Project | null {
    if (data.format !== "spectrapy-project") {
      error.value = "Invalid project format";
      return null;
    }

    const now = new Date().toISOString();
    const imported: Project = {
      ...data.project,
      id: generateId(),
      metadata: {
        ...data.project.metadata,
        modified: now,
      },
    };

    projects.value.unshift(imported);
    currentProjectId.value = imported.id;

    return imported;
  }

  function exportProjectToFile(projectId: string): void {
    const exportData = exportProject(projectId);
    if (!exportData) return;

    const blob = new Blob([JSON.stringify(exportData, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${exportData.project.metadata.name
      .replace(/[^a-z0-9]/gi, "_")
      .toLowerCase()}.spectrapy`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function importProjectFromFile(file: File): Promise<Project | null> {
    try {
      const text = await file.text();
      const data = JSON.parse(text) as ProjectExport;
      return importProject(data);
    } catch (e) {
      error.value = "Failed to parse project file";
      return null;
    }
  }

  // Project data management
  function addExperimentToProject(experimentId: number): void {
    if (!currentProject.value) return;
    if (!currentProject.value.data.experiments.includes(experimentId)) {
      currentProject.value.data.experiments.push(experimentId);
      currentProject.value.metadata.modified = new Date().toISOString();
    }
  }

  function removeExperimentFromProject(experimentId: number): void {
    if (!currentProject.value) return;
    const idx = currentProject.value.data.experiments.indexOf(experimentId);
    if (idx !== -1) {
      currentProject.value.data.experiments.splice(idx, 1);
      currentProject.value.metadata.modified = new Date().toISOString();
    }
  }

  function addWorkflowToProject(workflowId: string): void {
    if (!currentProject.value) return;
    if (!currentProject.value.data.workflows.includes(workflowId)) {
      currentProject.value.data.workflows.push(workflowId);
      currentProject.value.metadata.modified = new Date().toISOString();
    }
  }

  function updateProjectSettings(settings: Record<string, any>): void {
    if (!currentProject.value) return;
    currentProject.value.data.settings = {
      ...currentProject.value.data.settings,
      ...settings,
    };
    currentProject.value.metadata.modified = new Date().toISOString();
  }

  // Initialize on first use
  if (projects.value.length === 0) {
    initializeDefaultProjects();
  }

  return {
    // State
    projects,
    currentProjectId,
    isLoading,
    error,

    // Getters
    currentProject,
    projectList,
    recentProjects,

    // Actions
    createProject,
    updateProject,
    deleteProject,
    selectProject,
    duplicateProject,

    // Export/Import
    exportProject,
    importProject,
    exportProjectToFile,
    importProjectFromFile,

    // Project data
    addExperimentToProject,
    removeExperimentFromProject,
    addWorkflowToProject,
    updateProjectSettings,

    // Initialize
    initializeDefaultProjects,
  };
});
