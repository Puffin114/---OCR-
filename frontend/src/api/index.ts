import axios from 'axios'

export const API_BASE = 'http://localhost:8000'

const http = axios.create({ baseURL: API_BASE, withCredentials: true })

// 401 未登录：广播事件，由 App 切回登录页
http.interceptors.response.use(
  r => r,
  err => {
    if (err?.response?.status === 401) {
      window.dispatchEvent(new CustomEvent('app-unauthorized'))
    }
    return Promise.reject(err)
  },
)

export const api = {
  health: () => http.get('/api/health').then(r => r.data),

  login: (username: string, password: string) =>
    http.post('/api/auth/login', { username, password }).then(r => r.data),
  logout: () => http.post('/api/auth/logout').then(r => r.data),
  me: () => http.get('/api/auth/me').then(r => r.data),

  getCredentials: () => http.get('/api/settings/credentials').then(r => r.data),
  saveCredentials: (payload: any) => http.post('/api/settings/credentials', payload).then(r => r.data),
  listModels: () => http.get('/api/settings/models').then(r => r.data),
  createModel: (payload: any) => http.post('/api/settings/models', payload).then(r => r.data),
  updateModel: (id: number, payload: any) => http.put(`/api/settings/models/${id}`, payload).then(r => r.data),
  deleteModel: (id: number) => http.delete(`/api/settings/models/${id}`).then(r => r.data),

  loadDataset: (name = 'default') =>
    http.post('/api/datasets/load', { name }).then(r => r.data),
  uploadDataset: (file: File, name = 'uploaded') => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('name', name)
    return http.post('/api/datasets/upload', fd,
      { headers: { 'Content-Type': 'multipart/form-data' } }).then(r => r.data)
  },
  uploadChunk: (uploadId: string, index: number, chunk: Blob) => {
    const fd = new FormData()
    fd.append('upload_id', uploadId)
    fd.append('index', String(index))
    fd.append('chunk', chunk)
    return http.post('/api/datasets/upload-chunk', fd,
      { headers: { 'Content-Type': 'multipart/form-data' } }).then(r => r.data)
  },
  uploadFinish: (payload: any) => http.post('/api/datasets/upload-finish', payload).then(r => r.data),
  parseFields: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return http.post('/api/datasets/parse-fields', fd,
      { headers: { 'Content-Type': 'multipart/form-data' } }).then(r => r.data)
  },
  createDataset: (payload: { name: string; description?: string; annotated: boolean; fields: any[]; files: File[] }) => {
    const fd = new FormData()
    fd.append('name', payload.name)
    fd.append('description', payload.description || '')
    fd.append('annotated', String(payload.annotated))
    fd.append('fields', JSON.stringify(payload.fields || []))
    for (const f of payload.files) fd.append('files', f)
    return http.post('/api/datasets/create', fd,
      { headers: { 'Content-Type': 'multipart/form-data' } }).then(r => r.data)
  },
  listDatasets: () => http.get('/api/datasets').then(r => r.data),
  checkDatasetName: (name: string, excludeId?: number) =>
    http.get('/api/datasets/name-available',
      { params: { name, ...(excludeId != null ? { exclude_id: excludeId } : {}) } }).then(r => r.data),
  getDataset: (id: number) => http.get(`/api/datasets/${id}`).then(r => r.data),
  deleteDataset: (id: number) => http.delete(`/api/datasets/${id}`).then(r => r.data),
  renameDataset: (id: number, name: string) =>
    http.post(`/api/datasets/${id}/rename`, { name }).then(r => r.data),
  deleteDocument: (datasetId: number, docKey: string) =>
    http.delete(`/api/datasets/${datasetId}/documents/${encodeURIComponent(docKey)}`).then(r => r.data),

  docMeta: (key: string, datasetId?: number) =>
    http.get(`/api/documents/${encodeURIComponent(key)}/meta`,
      { params: datasetId != null ? { dataset_id: datasetId } : {} }).then(r => r.data),
  pageUrl: (key: string, page: number, zoom = 2, datasetId?: number) =>
    `${API_BASE}/api/documents/${encodeURIComponent(key)}/page/${page}.png?zoom=${zoom}` +
    (datasetId != null ? `&dataset_id=${datasetId}` : ''),
  annotationBoxes: (key: string, datasetId?: number) =>
    http.get(`/api/documents/${encodeURIComponent(key)}/annotation`,
      { params: datasetId != null ? { dataset_id: datasetId } : {} }).then(r => r.data),

  annotationGrouped: (key: string, datasetId?: number) =>
    http.get(`/api/documents/${encodeURIComponent(key)}/annotation-grouped`,
      { params: datasetId != null ? { dataset_id: datasetId } : {} }).then(r => r.data),

  recognize: (doc_key: string, page_num: number, box: number[], datasetId?: number) =>
    http.post('/api/annotations/recognize', { doc_key, page_num, box, dataset_id: datasetId }).then(r => r.data),
  saveAnnotation: (payload: any) =>
    http.post('/api/annotations/save', payload).then(r => r.data),
  deleteGroup: (doc_key: string, parent_field: string, group_index: number, datasetId?: number) =>
    http.post('/api/annotations/delete-group',
      { doc_key, parent_field, group_index, dataset_id: datasetId }).then(r => r.data),

  createEvalTask: (payload: any) =>
    http.post('/api/eval-tasks', payload).then(r => r.data),
  taskCandidates: (datasetId: number) =>
    http.get('/api/eval-tasks/candidates', { params: { dataset_id: datasetId } }).then(r => r.data),
  listEvalTasks: () => http.get('/api/eval-tasks').then(r => r.data),
  checkEvalTaskName: (name: string, excludeId?: number) =>
    http.get('/api/eval-tasks/name-available',
      { params: { name, ...(excludeId != null ? { exclude_id: excludeId } : {}) } }).then(r => r.data),
  getEvalTask: (id: number) => http.get(`/api/eval-tasks/${id}`).then(r => r.data),
  deleteEvalTask: (id: number) => http.delete(`/api/eval-tasks/${id}`).then(r => r.data),
  renameEvalTask: (id: number, name: string) =>
    http.post(`/api/eval-tasks/${id}/rename`, { name }).then(r => r.data),
  taskPredictions: (id: number) => http.get(`/api/eval-tasks/${id}/predictions`).then(r => r.data),
  predictionBoxes: (id: number, docKey: string) =>
    http.get(`/api/eval-tasks/${id}/predictions/${encodeURIComponent(docKey)}/boxes`).then(r => r.data),

  getMetrics: (id: number) => http.get(`/api/metrics/${id}`).then(r => r.data),
  getCompare: (id: number) => http.get(`/api/metrics/${id}/compare`).then(r => r.data),
  getPerformance: (id: number) => http.get(`/api/metrics/${id}/performance`).then(r => r.data),

  getCriteria: (id: number) => http.get(`/api/review/${id}/criteria`).then(r => r.data),
  saveCriteria: (task_id: number, items: any[]) =>
    http.post('/api/review/criteria', { task_id, items }).then(r => r.data),
  setOverride: (payload: any) =>
    http.post('/api/review/override', payload).then(r => r.data),
  clearOverride: (task_id: number, doc_key: string, field: string) =>
    http.delete('/api/review/override', { params: { task_id, doc_key, field } }).then(r => r.data),
  recompute: (task_id: number) =>
    http.post('/api/review/recompute', { task_id }).then(r => r.data),

  backflowScene: () => http.get('/api/backflow/scene').then(r => r.data),
  startBackflow: (payload: any) => http.post('/api/backflow/extract/start', payload).then(r => r.data),
  probeBackflow: (payload: any) => http.post('/api/backflow/extract/probe', payload).then(r => r.data),
  getBackflowJob: (jobId: string) => http.get(`/api/backflow/jobs/${jobId}`).then(r => r.data),
  listBackflowDatasets: () => http.get('/api/backflow/datasets').then(r => r.data),
}
