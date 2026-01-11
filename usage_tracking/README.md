# Usage Tracking (Centralized LLM Accounting)

This module provides a **central, async usage tracking layer** for all LLM requests. It logs raw events and updates user aggregates in Firestore **without impacting response latency**.

## A) Architecture (short, clear)

**Flow (step-by-step)**
1. **BEFORE** request: create a `UsageEvent` payload with request metadata (requestId, userId, endpoint, provider, model, plan snapshot, timestamps, platform/appVersion, ipCountry, etc.).
2. Call the LLM provider.
3. **AFTER** response: enrich the same event with usage metrics (tokens, latency, status, error info, cache flags, cost, fx, throttling decision, costCalculationVersion).
4. Return the LLM response to the user **immediately**.
5. **Async fire-and-forget**: enqueue Firestore writes (`usage_events`, `user_usage`, `user_usage_monthly`, and `request_dedup`).
6. **Idempotency**: for each requestId, a transaction ensures only the first write mutates counters.

**Why monthly shard is mandatory**
- Monthly documents keep aggregates bounded in size and allow **periodic quotas/limits**.
- Reduces contention by splitting writes across months.

**Idempotency strategy**
- `request_dedup/{requestId}` document is created in a transaction **before** counters are incremented.
- If it exists, **no counters** are updated.
- Optionally, the `usage_events` document can also serve as dedup, but explicit dedup is faster and explicit.

**Queue/worker approach**
- Preferred: publish usage payload to a queue (Pub/Sub/SQS/Kafka) and let a worker execute Firestore updates.
- If no queue: write `usage_events` only and run a periodic worker to aggregate into `user_usage` and `user_usage_monthly`.
- This repository provides a **fire-and-forget** thread pool helper that can be swapped for a queue later.

## B) Firestore paths + example docs

**Paths**
- `user_usage/{userId}` → lifetime aggregate
- `user_usage_monthly/{userId_YYYY-MM}` → monthly aggregate
- `usage_events/{YYYY-MM-DD}/events/{requestId}` → raw event log (audit)
- `request_dedup/{requestId}` → idempotency guard

> Note: Firestore requires collection/doc alternation, so raw events are stored under a date doc with subcollection `events`.

**Example: user_usage/{userId}** (schema aligned with your exact field names)
```json
{
  "userId": "347a08a8-1d14-43e2-a6bb-b61697f5d3b6",
  "startedAt": "2026-01-05T08:10:48.513Z",
  "lastRequestAt": "2026-01-11T12:34:10.000Z",
  "subscriptionType": "premium",
  "countryCode": "TR",
  "userCurrency": "TRY",
  "plan": {
    "productId": "avenia_premium:avenia-monthly",
    "period": "monthly",
    "listPrice": { "amount": 304.99, "currency": "TRY" },
    "netRevenueEstimate": { "amount": 213.49, "currency": "TRY" },
    "platformFeeEstimate": { "amount": 91.50, "currency": "TRY" },
    "commissionPercentage": 0.125,
    "taxPercentage": 0.1667,
    "store": "PLAY_STORE",
    "renewalNumber": 1,
    "expiresAt": "2026-01-05T08:15:42.876Z",
    "lastRevenueCatEventAt": "2026-01-05T08:10:48.513Z"
  },
  "usage": {
    "totalRequests": 1234,
    "inputTokens": 500000,
    "outputTokens": 487654,
    "totalTokens": 987654,
    "cachedTokens": 50000,
    "cacheHitCount": 320,
    "endpoints": {
      "createImages": 10,
      "deepsearch": 20,
      "summary_pdf": 20
    },
    "endpointTokens": {
      "createImages": { "input": 12000, "output": 12342, "total": 24342 },
      "deepsearch": { "input": 60000, "output": 30111, "total": 90111 },
      "summary_pdf": { "input": 35000, "output": 15123, "total": 50123 }
    }
  },
  "financials": {
    "cost": { "amount": 183.40, "currency": "TRY" },
    "costUSD": 5.71,
    "endpointCost": {
      "createImages": { "amount": 12.40, "currency": "TRY" },
      "deepsearch": { "amount": 55.10, "currency": "TRY" }
    },
    "fx": {
      "base": "USD",
      "quote": "TRY",
      "rate": 32.10,
      "updatedAt": "2026-01-11T00:00:00Z"
    },
    "costCalculationVersion": "pricing_v1.2"
  },
  "providers": {
    "gemini": {
      "requests": 1100,
      "inputTokens": 450000,
      "outputTokens": 430000,
      "costTRY": 160.20
    },
    "openai": {
      "requests": 120,
      "inputTokens": 50000,
      "outputTokens": 57654,
      "costTRY": 23.20
    }
  },
  "models": {
    "gemini-1.5-pro": {
      "requests": 900,
      "inputTokens": 320000,
      "outputTokens": 310000,
      "costTRY": 120.0
    }
  },
  "credits": {
    "paidTokens": 100000,
    "bonusTokens": 20000,
    "paidRemainingTokens": 12000,
    "bonusRemainingTokens": 5000
  },
  "quotas": {
    "monthlyCostLimitLocal": { "amount": 200.0, "currency": "TRY" },
    "dailyCostLimitLocal": { "amount": 15.0, "currency": "TRY" },
    "softLimitReached": true,
    "isThrottled": false,
    "blockedUntil": null,
    "blockReason": null
  },
  "stats": {
    "errorCount": 12,
    "lastErrorAt": "2026-01-11T11:00:00Z",
    "avgLatencyMs": 1850,
    "p95LatencyMs": 3200
  },
  "metadata": {
    "lastPlatform": "ios",
    "lastAppVersion": "2.1.0",
    "lastIpCountryMismatch": false
  },
  "updatedAt": "2026-01-11T12:34:10.000Z"
}
```

**Example: user_usage_monthly/{userId_YYYY-MM}**
```json
{
  "userId": "347a08a8-1d14-43e2-a6bb-b61697f5d3b6",
  "month": "2026-01",
  "startedAt": "2026-01-01T00:00:00.000Z",
  "lastRequestAt": "2026-01-11T12:34:10.000Z",
  "usage": {
    "totalRequests": 234,
    "inputTokens": 90000,
    "outputTokens": 84321,
    "totalTokens": 174321,
    "cachedTokens": 12000,
    "cacheHitCount": 75,
    "endpoints": {
      "deepsearch": 10
    },
    "endpointTokens": {
      "deepsearch": { "input": 10000, "output": 5011, "total": 15011 }
    }
  },
  "financials": {
    "cost": { "amount": 43.50, "currency": "TRY" },
    "costUSD": 1.35,
    "endpointCost": {
      "deepsearch": { "amount": 10.00, "currency": "TRY" }
    },
    "fx": {
      "base": "USD",
      "quote": "TRY",
      "rate": 32.10,
      "updatedAt": "2026-01-11T00:00:00Z"
    },
    "costCalculationVersion": "pricing_v1.2"
  },
  "updatedAt": "2026-01-11T12:34:10.000Z"
}
```

**Example: usage_events/{YYYY-MM-DD}/events/{requestId}**
```json
{
  "requestId": "req_abc_123",
  "userId": "347a08a8-1d14-43e2-a6bb-b61697f5d3b6",
  "endpoint": "summary_pdf",
  "provider": "openai",
  "model": "gpt-4o-mini",
  "timestamp": "2026-01-11T12:34:10.000Z",
  "subscriptionType": "premium",
  "countryCode": "TR",
  "userCurrency": "TRY",
  "plan": {
    "productId": "avenia_premium:avenia-monthly",
    "period": "monthly",
    "listPrice": { "amount": 304.99, "currency": "TRY" },
    "netRevenueEstimate": { "amount": 213.49, "currency": "TRY" },
    "platformFeeEstimate": { "amount": 91.50, "currency": "TRY" },
    "commissionPercentage": 0.125,
    "taxPercentage": 0.1667,
    "store": "PLAY_STORE",
    "renewalNumber": 1,
    "expiresAt": "2026-01-05T08:15:42.876Z",
    "lastRevenueCatEventAt": "2026-01-05T08:10:48.513Z"
  },
  "inputTokens": 1234,
  "outputTokens": 2100,
  "totalTokens": 3334,
  "cachedTokens": 0,
  "isCacheHit": false,
  "latencyMs": 1520,
  "status": "success",
  "errorCode": null,
  "cost": { "amount": 2.40, "currency": "TRY" },
  "costUSD": 0.075,
  "fx": {
    "base": "USD",
    "quote": "TRY",
    "rate": 32.10,
    "updatedAt": "2026-01-11T00:00:00Z"
  },
  "endpointCost": { "amount": 2.40, "currency": "TRY" },
  "costCalculationVersion": "pricing_v1.2",
  "throttlingDecision": { "isThrottled": false, "blockReason": null },
  "metadata": {
    "platform": "ios",
    "appVersion": "2.1.0",
    "ipCountry": "TR"
  }
}
```

## D) Test scenarios
- **Idempotency**: same requestId processed twice; counters must not increment on 2nd run.
- **Concurrent requests**: simultaneous usage updates for same user; transaction should keep aggregates consistent.
- **Monthly limit**: estimated cost exceeds monthly limit; expect throttle or HTTP 429 (config-driven).
- **Cache hit**: `isCacheHit=true` should increment `cachedTokens` and `cacheHitCount`.
- **Error log**: LLM failure should still write event with `status=error` and optional cost=0.
- **FX caching**: if FX is stale, fetch once and reuse for 24h.
- **Provider/model breakdown**: requests/tokens/cost correctly roll up under provider/model buckets.

