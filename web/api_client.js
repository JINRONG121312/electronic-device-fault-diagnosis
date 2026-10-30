const API_ROUTES = Object.freeze({
  dashboard: "/api/dashboard",
  job: "/api/job",
  settings: "/api/settings",
  setupProfile: "/api/setup-profile",
  scanFru: "/api/scan-fru",
  collectRuntime: "/api/collect-runtime",
  diagnose: "/api/diagnose",
  remoteDiagnosis: "/api/remote-diagnosis",
  targetProbe: "/api/target/probe",
  targetCollect: "/api/target/collect",
  updateTest: "/api/update-test",
  backgroundStart: "/api/background/start",
  backgroundStop: "/api/background/stop",
  backgroundStatus: "/api/background/status",
  loghubOsExperiment: "/api/experiments/loghub-os",
});

async function apiRequest(route, options = {}) {
  const response = await fetch(route, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok || data.ok === false) {
    const details = data.error || data.stderr || data.stdout || data.stage || response.statusText;
    throw new Error(details);
  }
  return data;
}

const dashboardApi = Object.freeze({
  getDashboard: () => apiRequest(API_ROUTES.dashboard),
  getJob: (id) => apiRequest(`${API_ROUTES.job}?id=${encodeURIComponent(id)}`),
  getSettings: () => apiRequest(API_ROUTES.settings),
  saveSettings: (body) => apiRequest(API_ROUTES.settings, { method: "POST", body: JSON.stringify(body) }),
  setupProfile: (body) => apiRequest(API_ROUTES.setupProfile, { method: "POST", body: JSON.stringify(body) }),
  scanFru: (body) => apiRequest(API_ROUTES.scanFru, { method: "POST", body: JSON.stringify(body) }),
  collectRuntime: (body) => apiRequest(API_ROUTES.collectRuntime, { method: "POST", body: JSON.stringify(body) }),
  diagnose: (body) => apiRequest(API_ROUTES.diagnose, { method: "POST", body: JSON.stringify(body) }),
  remoteDiagnosis: (body) => apiRequest(API_ROUTES.remoteDiagnosis, { method: "POST", body: JSON.stringify(body) }),
  targetProbe: (body) => apiRequest(API_ROUTES.targetProbe, { method: "POST", body: JSON.stringify(body) }),
  targetCollect: (body) => apiRequest(API_ROUTES.targetCollect, { method: "POST", body: JSON.stringify(body) }),
  updateTest: (body) => apiRequest(API_ROUTES.updateTest, { method: "POST", body: JSON.stringify(body) }),
  stopBackground: () => apiRequest(API_ROUTES.backgroundStop, { method: "POST", body: JSON.stringify({}) }),
  getLoghubOsExperiment: (params = {}) => {
    const query = new URLSearchParams(params);
    return apiRequest(`${API_ROUTES.loghubOsExperiment}?${query.toString()}`);
  },
  importLoghubOsExperiment: (body) => apiRequest(`${API_ROUTES.loghubOsExperiment}/import`, { method: "POST", body: JSON.stringify(body) }),
  importLoghubOsTestCases: (body) => apiRequest(`${API_ROUTES.loghubOsExperiment}/import-test`, { method: "POST", body: JSON.stringify(body) }),
});
