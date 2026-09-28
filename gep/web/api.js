export async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
  const body = await response.json();
  if (!response.ok) { const error = new Error(body.error || "请求失败"); error.status = response.status; error.body = body; throw error; }
  return body;
}

export const taskApi = {
  tasks: () => api("/tasks"), graph: taskId => api(`/tasks/${taskId}/graph`), events: (taskId, after) => api(`/tasks/${taskId}/events?after=${after}`),
  snapshots: taskId => api(`/tasks/${taskId}/snapshots`), readiness: taskId => api(`/tasks/${taskId}/readiness`), appendix: taskId => api(`/tasks/${taskId}/appendix-e`),
  evidence: nodeId => api(`/nodes/${nodeId}/evidence`), dataVersion: version => api(`/data-versions/${encodeURIComponent(version)}`),
  assets: query => api(`/data-assets${query ? `?${new URLSearchParams(query)}` : ""}`),
  asset: assetId => api(`/data-assets/${encodeURIComponent(assetId)}`),
  observations: query => api(`/derived-observations?${new URLSearchParams(query)}`),
  automationSummary: taskId => api(`/tasks/${taskId}/automation-summary`),
  demoReadiness: taskId => api(`/tasks/${taskId}/demo-readiness`),
  calculationChain: nodeId => api(`/nodes/${nodeId}/calculation-chain`),
  demoSnapshot: taskId => api(`/tasks/${taskId}/demo-snapshots`, { method:"POST", body:"{}" }),
  create: payload => api("/tasks", { method:"POST", body:JSON.stringify(payload) }), snapshot: taskId => api(`/tasks/${taskId}/snapshots`, { method:"POST", body:"{}" }),
  supplement: (taskId, payload) => api(`/tasks/${taskId}/supplement`, { method:"POST", body:JSON.stringify(payload) }),
  autoSupplement: taskId => api(`/tasks/${taskId}/supplements:auto`, { method:"POST", body:"{}" }),
  batchPreview: taskId => api(`/tasks/${taskId}/batch-review-preview`),
  batchReview: (taskId, payload) => api(`/tasks/${taskId}/batch-reviews`, { method:"POST", body:JSON.stringify(payload) }),
  run: payload => api("/runs", { method:"POST", body:JSON.stringify(payload) }), runChain: runId => api(`/runs/${runId}/chain`),
  review: (nodeId, payload) => api(`/nodes/${nodeId}/reviews`, { method:"POST", body:JSON.stringify(payload) }),
};
