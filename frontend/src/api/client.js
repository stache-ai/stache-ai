import axios from 'axios'
import { getAuthHeader, getAuthProvider, login } from './auth.js'
import { getConfig } from '../config.js'

// API URL from runtime config or build-time env var
// Falls back to relative paths for same-origin deployment
const getApiUrl = () => getConfig('API_URL', '')

// An extension deployment serves its own routes from a SEPARATE HTTP API with
// its own base URL -- it is not merely a path on API_URL. Empty on a core-only
// deployment, which is the normal case: callers must treat "" as "no extension"
// rather than falling back to API_URL, or every request 404s against a core API
// that does not serve those routes.
const getExtensionApiUrl = () => getConfig('ENTERPRISE_API_URL', '')

//: True when this deployment has an extension API to talk to at all.
export const hasExtensionApi = () => Boolean(getExtensionApiUrl())

// Raised instead of firing a request we know cannot succeed.
export class ExtensionApiUnavailableError extends Error {
  constructor() {
    super('This deployment has no extension API configured.')
    this.name = 'ExtensionApiUnavailableError'
    this.isExtensionUnavailable = true
  }
}

// Create axios instances lazily to pick up runtime config
let clientInstance = null
let extensionInstance = null

// Only kick off one login redirect even if several requests 401 at once
let redirectingToLogin = false

// Both instances get the SAME auth behaviour: the request interceptor attaches
// the Cognito JWT, and a 401 triggers the one-shot re-login redirect. Factored
// out so the extension client can never drift from the core one.
function attachInterceptors(instance) {
  // Request interceptor to add auth headers
  instance.interceptors.request.use(async (config) => {
    const authHeaders = getAuthHeader()
    Object.assign(config.headers, authHeaders)
    return config
  })

  // Response interceptor for error handling
  instance.interceptors.response.use(
    (response) => response,
    (error) => {
        // Handle 401 Unauthorized - the token expired mid-session; without
        // this redirect every action fails silently until the next navigation
        if (error.response?.status === 401 && getAuthProvider() !== 'none') {
          console.warn('Unauthorized - token expired, redirecting to login')
          if (!redirectingToLogin) {
            redirectingToLogin = true
            login()
          }
        }

        // Enhance error with more context
        const enhancedError = new Error(
          error.response?.data?.detail ||
          error.response?.data?.message ||
          error.message ||
          'An unexpected error occurred'
        )
        enhancedError.status = error.response?.status
        enhancedError.isNetworkError = !error.response
        enhancedError.isTimeout = error.code === 'ECONNABORTED'
        enhancedError.isUnauthorized = error.response?.status === 401
        enhancedError.originalError = error
        return Promise.reject(enhancedError)
      }
  )
  return instance
}

function getClient() {
  if (!clientInstance) {
    clientInstance = attachInterceptors(axios.create({
      baseURL: getApiUrl(),
      headers: {
        'Content-Type': 'application/json',
      },
      timeout: 30000, // 30 second timeout
    }))
  }
  return clientInstance
}

// Client for the extension API. Returns null when this deployment has none --
// callers must check, NOT fall back to the core client.
function getExtensionClient() {
  const baseURL = getExtensionApiUrl()
  if (!baseURL) return null
  if (!extensionInstance) {
    extensionInstance = attachInterceptors(axios.create({
      baseURL,
      headers: {
        'Content-Type': 'application/json',
      },
      timeout: 30000,
    }))
  }
  return extensionInstance
}

// Test seam: config is read once and cached in the instances above.
export const _resetClientsForTest = () => {
  clientInstance = null
  extensionInstance = null
}

// Proxy object that delegates to lazily-created client
const client = new Proxy({}, {
  get(target, prop) {
    const realClient = getClient()
    const value = realClient[prop]
    if (typeof value === 'function') {
      return value.bind(realClient)
    }
    return value
  }
})

export const checkHealth = async () => {
  // Call /api/health if authenticated, /api/ping otherwise
  // This avoids initializing providers on serverless before login
  const endpoint = getAuthProvider() !== 'none' && getAuthHeader().Authorization
    ? '/api/health'
    : '/api/ping'
  const response = await getClient().get(endpoint)
  return response.data
}

// Account / usage API
//
// GET /account/usage is served by the EXTENSION API, not the core one -- a
// different host entirely. Routing it through the core client (which this once
// did) makes it 404 for every user on every deployment, which no backend test
// can catch: the route exists and answers correctly, just not at the address the
// browser was asking. Hence the separate client, and hence the regression test.
//
// Same auth as every other call: the shared interceptors attach the Cognito JWT
// and turn a 401 into the usual re-login redirect.
export const getAccountUsage = async () => {
  const extension = getExtensionClient()
  if (!extension) throw new ExtensionApiUnavailableError()
  const response = await extension.get('/account/usage')
  return response.data
}

export const captureThought = async (text, metadata = null, namespace = null) => {
  const response = await getClient().post('/api/capture', {
    text,
    metadata,
    chunking_strategy: 'recursive',
    namespace
  })
  return response.data
}

// Ingestion job API (async tier / presigned upload)
const TERMINAL = ['done', 'skipped', 'failed', 'cancelled']

export const submitIngest = async (payload) => (await client.post('/api/ingest', payload)).data

export const getJob = async (id) => (await client.get(`/api/jobs/${id}`)).data

export const listJobs = async (params = {}) => (await client.get('/api/jobs', { params })).data

// Smart-poll a job until it reaches a terminal status (with exponential backoff).
export async function pollJob(jobId, { interval = 1000, maxInterval = 5000, timeout = 600000, onUpdate } = {}) {
  const start = Date.now()
  let wait = interval
  while (Date.now() - start < timeout) {
    const job = await getJob(jobId)
    if (onUpdate) onUpdate(job)
    if (TERMINAL.includes(job.status)) return job
    await new Promise(r => setTimeout(r, wait))
    wait = Math.min(wait * 1.5, maxInterval)
  }
  throw new Error('Job polling timed out')
}

// Large-file path: ask for a presigned URL, PUT the file straight to S3, then poll.
export const uploadViaPresign = async (file, { namespace = null, metadata = null, onUpdate } = {}) => {
  let ticket
  try {
    ticket = await submitIngest({
      upload: true,
      filename: file.name,
      content_type: file.type || 'application/octet-stream',
      namespace,
      metadata,
    })
  } catch (err) {
    // Only a 400 from the presign REQUEST means the backend has no presigned
    // intake (sync tier) and no job was created — safe for callers to fall back
    // to the legacy upload. Errors after this point (S3 PUT, polling) must NOT
    // be treated as fallback-able: the job already exists, and S3 itself
    // returns 400s (RequestTimeout, EntityTooLarge) that would otherwise
    // trigger a duplicate ingest alongside an orphaned UPLOADING job.
    if (err.status === 400) err.presignUnsupported = true
    throw err
  }
  const { job_id, upload_url, required_headers } = ticket
  // Use the RAW axios (not the `client` instance) so the auth interceptor and
  // baseURL don't apply to the direct S3 PUT.
  await axios.put(upload_url, file, {
    headers: required_headers || { 'Content-Type': file.type },
  })
  return pollJob(job_id, { onUpdate })
}

export const queryKnowledge = async (query, synthesize = true, top_k = 5, namespace = null, rerank = false, model = null) => {
  const response = await getClient().post('/api/query', {
    query,
    synthesize,
    top_k,
    namespace,
    rerank,
    model
  })
  return response.data
}

export const listModels = async () => {
  const response = await getClient().get('/api/models')
  return response.data
}

export const uploadDocument = async (file, chunkingStrategy = 'recursive', metadata = null, namespace = null) => {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('chunking_strategy', chunkingStrategy)
  if (metadata) {
    formData.append('metadata', JSON.stringify(metadata))
  }
  if (namespace) {
    formData.append('namespace', namespace)
  }

  const response = await getClient().post('/api/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
    timeout: 120000, // 2 minute timeout for uploads
  })
  return response.data
}

export const batchUploadDocuments = async (files, options = {}) => {
  const {
    chunkingStrategy = 'recursive',
    namespace = null,
    metadata = null,
    prependMetadata = null,
    skipErrors = true,
    onProgress = null
  } = options

  const formData = new FormData()

  // Append all files
  for (const file of files) {
    formData.append('files', file)
  }

  formData.append('chunking_strategy', chunkingStrategy)
  formData.append('skip_errors', skipErrors.toString())

  if (namespace) {
    formData.append('namespace', namespace)
  }
  // Backend expects metadata as a JSON string applied to all files
  if (metadata && Object.keys(metadata).length > 0) {
    formData.append('metadata', JSON.stringify(metadata))
  }
  if (prependMetadata) {
    formData.append('prepend_metadata', prependMetadata)
  }

  const response = await getClient().post('/api/upload/batch', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
    timeout: 600000, // 10 minute timeout for batch uploads
    onUploadProgress: onProgress ? (progressEvent) => {
      const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total)
      onProgress(percentCompleted, progressEvent)
    } : undefined
  })
  return response.data
}

// Pending queue API functions
export const listPending = async () => {
  const response = await getClient().get('/api/pending')
  return response.data
}

export const getPending = async (id) => {
  const response = await getClient().get(`/api/pending/${id}`)
  return response.data
}

export const getPendingThumbnailUrl = (id) => {
  return `/api/pending/${id}/thumbnail`
}

export const getPendingPdfUrl = (id) => {
  return `/api/pending/${id}/pdf`
}

export const approvePending = async (id, { filename, namespace, metadata, chunkingStrategy, prependMetadata }) => {
  const response = await getClient().post(`/api/pending/${id}/approve`, {
    filename,
    namespace,
    metadata,
    chunking_strategy: chunkingStrategy || 'recursive',
    prepend_metadata: prependMetadata
  })
  return response.data
}

export const deletePending = async (id) => {
  const response = await getClient().delete(`/api/pending/${id}`)
  return response.data
}

// Namespace API functions
export const listNamespaces = async (includeStats = true) => {
  const response = await getClient().get('/api/namespaces', {
    params: { include_stats: includeStats, include_children: true }
  })
  return response.data
}

export const getNamespaceTree = async (includeStats = false) => {
  const response = await getClient().get('/api/namespaces/tree', {
    params: { include_stats: includeStats }
  })
  return response.data
}

export const getNamespace = async (id) => {
  const response = await getClient().get(`/api/namespaces/${encodeURIComponent(id)}`)
  return response.data
}

export const createNamespaceApi = async ({ id, name, description, parent_id, metadata, filter_keys }) => {
  const response = await getClient().post('/api/namespaces', {
    id,
    name,
    description,
    parent_id,
    metadata,
    filter_keys
  })
  return response.data
}

export const updateNamespace = async (id, { name, description, parent_id, metadata, filter_keys }) => {
  const response = await getClient().put(`/api/namespaces/${encodeURIComponent(id)}`, {
    name,
    description,
    parent_id,
    metadata,
    filter_keys
  })
  return response.data
}

export const deleteNamespaceApi = async (id, cascade = false, deleteDocuments = false) => {
  const response = await getClient().delete(`/api/namespaces/${encodeURIComponent(id)}`, {
    params: { cascade, delete_documents: deleteDocuments }
  })
  return response.data
}

export const getNamespaceDocuments = async (id, limit = 100, offset = 0) => {
  const response = await getClient().get(`/api/namespaces/${encodeURIComponent(id)}/documents`, {
    params: { limit, offset }
  })
  return response.data
}

// Document management API functions
export const listDocuments = async (params = {}) => {
  const response = await getClient().get('/api/documents', { params })
  return response.data
}

export const getDocumentById = async (docId, namespace = 'default') => {
  const response = await getClient().get(`/api/documents/id/${docId}`, {
    params: { namespace }
  })
  return response.data
}

export const updateDocumentMetadata = async (docId, currentNamespace, updates) => {
  const response = await getClient().patch(`/api/documents/${docId}`, updates, {
    params: { current_namespace: currentNamespace }
  })
  return response.data
}

export const deleteDocumentById = async (docId, namespace = 'default') => {
  const response = await getClient().delete(`/api/documents/id/${docId}`, {
    params: { namespace }
  })
  return response.data
}

// Trash management API functions
export const listTrash = async (params = {}) => {
  const response = await getClient().get('/api/trash/', { params })
  return response.data
}

export const restoreFromTrash = async ({ doc_id, namespace, deleted_at_ms }) => {
  const response = await getClient().post('/api/trash/restore', {
    doc_id,
    namespace,
    deleted_at_ms,
  })
  return response.data
}

export const permanentlyDeleteFromTrash = async ({ doc_id, namespace, deleted_at_ms, filename }) => {
  const response = await getClient().post('/api/trash/permanent', {
    doc_id,
    namespace,
    deleted_at_ms,
    filename,  // Pass trash entry filename to ensure correct trash PK
  })
  return response.data
}

export default client
