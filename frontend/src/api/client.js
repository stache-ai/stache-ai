import axios from 'axios'
import { getAuthHeader, getAuthProvider } from './auth.js'
import { getConfig } from '../config.js'

// API URL from runtime config or build-time env var
// Falls back to relative paths for same-origin deployment
const getApiUrl = () => getConfig('API_URL', '')

// Create axios instance lazily to pick up runtime config
let clientInstance = null

function getClient() {
  if (!clientInstance) {
    clientInstance = axios.create({
      baseURL: getApiUrl(),
      headers: {
        'Content-Type': 'application/json',
      },
      timeout: 30000, // 30 second timeout
    })

    // Request interceptor to add auth headers
    clientInstance.interceptors.request.use(async (config) => {
      const authHeaders = getAuthHeader()
      Object.assign(config.headers, authHeaders)
      return config
    })

    // Response interceptor for error handling
    clientInstance.interceptors.response.use(
      (response) => response,
      (error) => {
        // Handle 401 Unauthorized - redirect to login if using auth
        if (error.response?.status === 401 && getAuthProvider() !== 'none') {
          console.warn('Unauthorized - token may be expired')
          // Could trigger re-login here if desired
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
  }
  return clientInstance
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

export const captureThought = async (text, metadata = null, namespace = null) => {
  const response = await getClient().post('/api/capture', {
    text,
    metadata,
    chunking_strategy: 'recursive',
    namespace
  })
  return response.data
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

export default client
