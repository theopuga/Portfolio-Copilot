/**
 * Persist the user's last portfolio draft/analysis locally so navigation/refresh
 * doesn't wipe the UI state.
 *
 * Note: This is *not* the source of truth (backend snapshots are). It's a UX cache.
 */

export type CachedHolding = { ticker: string; weightPct: number };

export type PortfolioCache = {
  holdings: CachedHolding[];
  cashPct: number;
  /**
   * Backend-shaped PortfolioMetrics object (stored as-is).
   * Kept as unknown to avoid tight coupling; consumers can treat it as `any`.
   */
  metrics?: unknown;
  updatedAt: string;
};

const KEY_PREFIX = 'portfolio_copilot:portfolio:';

function key(userId: string) {
  return `${KEY_PREFIX}${userId}`;
}

function safeParseJson(value: string): unknown {
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

export function loadPortfolioCache(userId: string): PortfolioCache | null {
  try {
    const raw = localStorage.getItem(key(userId));
    if (!raw) return null;
    const parsed = safeParseJson(raw) as any;
    if (!parsed || typeof parsed !== 'object') return null;

    const holdings = Array.isArray(parsed.holdings) ? parsed.holdings : [];
    const normalizedHoldings: CachedHolding[] = holdings
      .filter((h: any) => h && typeof h.ticker === 'string')
      .map((h: any) => ({
        ticker: String(h.ticker).toUpperCase(),
        weightPct: Number(h.weightPct ?? 0),
      }))
      .filter((h) => h.ticker.length > 0 && Number.isFinite(h.weightPct));

    const cashPct = Number(parsed.cashPct ?? 0);
    const updatedAt = typeof parsed.updatedAt === 'string' ? parsed.updatedAt : new Date().toISOString();

    return {
      holdings: normalizedHoldings,
      cashPct: Number.isFinite(cashPct) ? cashPct : 0,
      metrics: parsed.metrics,
      updatedAt,
    };
  } catch {
    return null;
  }
}

export function savePortfolioCache(userId: string, cache: PortfolioCache) {
  try {
    localStorage.setItem(key(userId), JSON.stringify(cache));
  } catch {
    // ignore (private mode / quota / disabled storage)
  }
}

export function clearPortfolioCache(userId: string) {
  try {
    localStorage.removeItem(key(userId));
  } catch {
    // ignore
  }
}

/**
 * Save recommended portfolio separately for comparison
 */
export function saveRecommendedPortfolioCache(userId: string, cache: PortfolioCache) {
  try {
    localStorage.setItem(`${KEY_PREFIX}recommended:${userId}`, JSON.stringify(cache));
  } catch {
    // ignore
  }
}

/**
 * Load recommended portfolio from cache
 */
export function loadRecommendedPortfolioCache(userId: string): PortfolioCache | null {
  try {
    const raw = localStorage.getItem(`${KEY_PREFIX}recommended:${userId}`);
    if (!raw) return null;
    const parsed = safeParseJson(raw) as any;
    if (!parsed || typeof parsed !== 'object') return null;

    const holdings = Array.isArray(parsed.holdings) ? parsed.holdings : [];
    const normalizedHoldings: CachedHolding[] = holdings
      .filter((h: any) => h && typeof h.ticker === 'string')
      .map((h: any) => ({
        ticker: String(h.ticker).toUpperCase(),
        weightPct: Number(h.weightPct ?? 0),
      }))
      .filter((h) => h.ticker.length > 0 && Number.isFinite(h.weightPct));

    const cashPct = Number(parsed.cashPct ?? 0);
    const updatedAt = typeof parsed.updatedAt === 'string' ? parsed.updatedAt : new Date().toISOString();

    return {
      holdings: normalizedHoldings,
      cashPct: Number.isFinite(cashPct) ? cashPct : 0,
      metrics: parsed.metrics,
      updatedAt,
    };
  } catch {
    return null;
  }
}


