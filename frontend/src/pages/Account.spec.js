import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import Account from './Account.vue'
import { getAccountUsage } from '../api/client.js'

// Mock the shared API client so no real network/auth is exercised. The page
// only depends on getAccountUsage.
vi.mock('../api/client.js', () => ({
  getAccountUsage: vi.fn(),
}))

const fullResponse = {
  tenant_id: 'acme-corp',
  plan: 'free',
  usage: [
    { metric: 'documents', usage_count: 5, quota_limit: 100, period: null },
    { metric: 'storage_bytes', usage_count: 1048576, quota_limit: 104857600, period: null },
    { metric: 'queries', usage_count: 12, quota_limit: 200, period: '2026-07' },
    { metric: 'bedrock_tokens', usage_count: 3400, quota_limit: 500000, period: '2026-07' },
  ],
}

async function mountLoaded(response) {
  getAccountUsage.mockResolvedValueOnce(response)
  const wrapper = mount(Account)
  await flushPromises()
  return wrapper
}

describe('Account usage page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the plan and a row per metric on a normal response', async () => {
    const wrapper = await mountLoaded(fullResponse)

    // Plan shown prominently, capitalized via CSS (raw text is "free").
    expect(wrapper.find('.plan-name').text()).toBe('free')

    const rows = wrapper.findAll('.usage-item')
    expect(rows).toHaveLength(4)

    const labels = wrapper.findAll('.usage-label').map((n) => n.text())
    expect(labels[0]).toContain('Documents')
    expect(labels[1]).toContain('Storage')
    expect(labels[2]).toContain('Queries this month')
    expect(labels[3]).toContain('AI usage this month')

    // Storage bytes are humanized (1 MB / 100 MB), counts are locale-formatted.
    const values = wrapper.findAll('.usage-values').map((n) => n.text())
    expect(values[0]).toContain('5')
    expect(values[0]).toContain('100')
    expect(values[1]).toContain('1 MB')
    expect(values[1]).toContain('100 MB')
    expect(values[3]).toContain('3,400')
    expect(values[3]).toContain('500,000')

    // Monthly metrics show their period tag.
    expect(labels[2]).toContain('2026-07')

    // Progress fills present for bounded metrics with sane widths.
    const fills = wrapper.findAll('.progress-fill')
    expect(fills.length).toBe(4)
    expect(fills[0].attributes('style')).toContain('width: 5%')
  })

  it('renders an unlimited metric with no progress fill', async () => {
    const wrapper = await mountLoaded({
      tenant_id: 't',
      plan: 'pro',
      usage: [{ metric: 'documents', usage_count: 42, quota_limit: null, period: null }],
    })

    expect(wrapper.find('.usage-values').text()).toContain('Unlimited')
    // No computed percentage / fill for an unlimited metric.
    expect(wrapper.find('.progress-fill').exists()).toBe(false)
    expect(wrapper.find('.progress-track.unlimited').exists()).toBe(true)
  })

  it('omits metrics that are absent from the response', async () => {
    const wrapper = await mountLoaded({
      tenant_id: 't',
      plan: 'free',
      usage: [{ metric: 'documents', usage_count: 1, quota_limit: 100, period: null }],
    })

    const rows = wrapper.findAll('.usage-item')
    expect(rows).toHaveLength(1)
    expect(wrapper.text()).toContain('Documents')
    expect(wrapper.text()).not.toContain('Storage')
  })

  it('shows an empty state when usage is [] but keeps the plan', async () => {
    const wrapper = await mountLoaded({ tenant_id: 't', plan: 'free', usage: [] })

    expect(wrapper.find('.plan-name').text()).toBe('free')
    expect(wrapper.findAll('.usage-item')).toHaveLength(0)
    expect(wrapper.text()).toContain('No usage data yet')
  })

  it('falls back to a neutral placeholder when plan is null', async () => {
    const wrapper = await mountLoaded({ tenant_id: 't', plan: null, usage: [] })
    expect(wrapper.find('.plan-name').text()).toBe('—')
  })

  it('shows a retryable error on a generic failure and does not leak the body', async () => {
    const err = new Error('boom')
    err.status = 500
    getAccountUsage.mockRejectedValueOnce(err)

    const wrapper = mount(Account)
    await flushPromises()

    expect(wrapper.find('.state-message').exists()).toBe(true)
    expect(wrapper.text()).toContain("couldn't load your usage")
    expect(wrapper.text()).not.toContain('boom')

    // Retry succeeds and renders data.
    getAccountUsage.mockResolvedValueOnce(fullResponse)
    await wrapper.find('.btn-retry').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.usage-item')).toHaveLength(4)
  })

  it('shows a distinct access-denied message on 403 without a retry button', async () => {
    const err = new Error('forbidden')
    err.status = 403
    getAccountUsage.mockRejectedValueOnce(err)

    const wrapper = mount(Account)
    await flushPromises()

    expect(wrapper.text()).toContain("don't have access")
    expect(wrapper.find('.btn-retry').exists()).toBe(false)
  })
})
