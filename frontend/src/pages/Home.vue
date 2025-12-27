<template>
  <div class="container">
    <div class="hero">
      <h1>Welcome to Stache 📎</h1>
      <p class="subtitle">Your personal AI-powered knowledge base</p>

      <div class="features">
        <div class="feature-card">
          <div class="icon">📝</div>
          <h3>Capture</h3>
          <p>Save thoughts, notes, or upload documents</p>
          <router-link to="/capture" class="btn btn-primary">Start Capturing</router-link>
        </div>

        <div class="feature-card">
          <div class="icon">🔍</div>
          <h3>Query</h3>
          <p>Ask questions, get AI-powered answers</p>
          <router-link to="/query" class="btn btn-primary">Ask a Question</router-link>
        </div>
      </div>

      <div class="stats">
        <div class="stat">
          <div class="stat-value">{{ stats.provider }}</div>
          <div class="stat-label">LLM Provider</div>
        </div>
        <div class="stat">
          <div class="stat-value">{{ stats.collection }}</div>
          <div class="stat-label">Collection</div>
        </div>
        <div class="stat">
          <div class="stat-value">Ready</div>
          <div class="stat-label">Status</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { checkHealth } from '../api/client.js'

const stats = ref({
  provider: 'Loading...',
  collection: 'Loading...'
})

onMounted(async () => {
  try {
    const health = await checkHealth()
    stats.value = {
      provider: health.providers?.llm_provider || 'Unknown',
      collection: health.vectordb_provider || 'stache'
    }
  } catch (error) {
    console.error('Failed to fetch stats:', error)
  }
})
</script>

<style scoped>
.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 2rem;
}

.hero {
  text-align: center;
  padding: 3rem 0;
}

.hero h1 {
  font-size: 3rem;
  color: #1f2937;
  margin-bottom: 1rem;
}

.subtitle {
  font-size: 1.5rem;
  color: #6b7280;
  margin-bottom: 3rem;
}

.features {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 2rem;
  margin-bottom: 4rem;
}

.feature-card {
  background: white;
  padding: 2rem;
  border-radius: 12px;
  box-shadow: 0 4px 6px rgba(0,0,0,0.1);
  transition: transform 0.2s, box-shadow 0.2s;
}

.feature-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 12px rgba(0,0,0,0.15);
}

.icon {
  font-size: 3rem;
  margin-bottom: 1rem;
}

.feature-card h3 {
  font-size: 1.5rem;
  color: #1f2937;
  margin-bottom: 0.5rem;
}

.feature-card p {
  color: #6b7280;
  margin-bottom: 1.5rem;
}

.btn {
  display: inline-block;
  padding: 0.75rem 1.5rem;
  border-radius: 8px;
  text-decoration: none;
  font-weight: 600;
  transition: all 0.2s;
}

.btn-primary {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.btn-primary:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 8px rgba(102, 126, 234, 0.4);
}

.stats {
  display: flex;
  justify-content: center;
  gap: 3rem;
  padding: 2rem;
  background: white;
  border-radius: 12px;
  box-shadow: 0 4px 6px rgba(0,0,0,0.1);
}

.stat {
  text-align: center;
}

.stat-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #667eea;
  margin-bottom: 0.5rem;
}

.stat-label {
  font-size: 0.9rem;
  color: #6b7280;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

@media (max-width: 768px) {
  .container {
    padding: 0 1rem;
  }

  .hero {
    padding: 2rem 0;
  }

  .hero h1 {
    font-size: 1.75rem;
  }

  .subtitle {
    font-size: 1.1rem;
    margin-bottom: 2rem;
  }

  .features {
    grid-template-columns: 1fr;
    gap: 1.25rem;
    margin-bottom: 2rem;
  }

  .feature-card {
    padding: 1.5rem;
  }

  .icon {
    font-size: 2.5rem;
  }

  .feature-card h3 {
    font-size: 1.25rem;
  }

  .feature-card p {
    font-size: 0.95rem;
    margin-bottom: 1rem;
  }

  .btn {
    padding: 0.875rem 1.5rem;
    min-height: 48px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .stats {
    flex-direction: column;
    gap: 1rem;
    padding: 1.5rem;
  }

  .stat {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.5rem 0;
    border-bottom: 1px solid #f3f4f6;
  }

  .stat:last-child {
    border-bottom: none;
  }

  .stat-value {
    font-size: 1.25rem;
    order: 2;
  }

  .stat-label {
    order: 1;
    text-align: left;
  }
}

/* Small mobile */
@media (max-width: 480px) {
  .hero h1 {
    font-size: 1.5rem;
  }

  .subtitle {
    font-size: 1rem;
  }

  .feature-card {
    padding: 1.25rem;
  }

  .icon {
    font-size: 2rem;
    margin-bottom: 0.75rem;
  }

  .feature-card h3 {
    font-size: 1.1rem;
  }

  .stats {
    padding: 1rem;
  }
}
</style>
