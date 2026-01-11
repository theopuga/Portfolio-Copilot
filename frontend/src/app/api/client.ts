/**
 * API client for backend communication
 */

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export interface Holding {
  ticker: string;
  weight: number;
}

export interface InvestorProfile {
  user_id: string;
  objective: {
    type: 'growth' | 'income' | 'balanced';
    notes: string;
  };
  horizon_months: number;
  risk_score: number;
  constraints: {
    max_holdings: number;
    max_position_pct: number;
    exclusions: string[];
    options_allowed: boolean;
    leverage_allowed: boolean;
  };
  preferences: {
    sectors_like: string[];
    sectors_avoid: string[];
    regions_like: string[];
  };
  rebalance_frequency: 'monthly' | 'quarterly' | 'annual';
  last_updated: string;
}

export interface PortfolioMetrics {
  total_holdings: number;
  top_1_weight: number;
  top_3_weight: number;
  top_5_weight: number;
  herfindahl_index: number;
  constraint_violations: string[];
  drift_summary?: string;
  sector_allocation: Record<string, number>;
  ticker_sectors?: Record<string, string>;
}

export interface RebalanceAction {
  action: 'BUY' | 'SELL';
  ticker: string;
  delta_weight: number;
}

export interface RebalancePlan {
  actions: RebalanceAction[];
  notes: string[];
  warnings: string[];
}

export interface RecommendationResponse {
  profile: InvestorProfile;
  metrics: PortfolioMetrics;
  plan: RebalancePlan;
  explanation: string;
  operation_type: 'construct' | 'rebalance';
}

export interface PortfolioSnapshot {
  snapshot_id: string;
  timestamp: string;
  user_id: string;
  holdings: Holding[];
  cash_weight: number;
  metrics: PortfolioMetrics;
}

export interface PortfolioHistoryResponse {
  user_id: string;
  snapshots: PortfolioSnapshot[];
}

export interface PortfolioComparison {
  current: PortfolioMetrics;
  recommended: PortfolioMetrics;
  differences: {
    holdings_change: number;
    risk_change: number;
    top_1_weight_change: number;
    top_3_weight_change: number;
    top_5_weight_change: number;
    cash_weight_change: number;
    sector_allocation_changes: Record<string, {
      current: number;
      recommended: number;
      change: number;
    }>;
  };
}

class ApiError extends Error {
  constructor(
    public status: number,
    public error: string,
    public errorCode: string,
    public detail?: string
  ) {
    super(error);
    this.name = 'ApiError';
  }
}

async function request<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;
  
  let response: Response;
  try {
    response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
    });
  } catch (err) {
    // Handle network errors (connection refused, CORS, timeout, etc.)
    if (err instanceof TypeError) {
      throw new ApiError(
        0,
        'Network error: Could not connect to the API server',
        'NETWORK_ERROR',
        `Failed to connect to ${url}. Make sure the backend server is running at ${API_BASE_URL}`
      );
    }
    throw new ApiError(
      0,
      'Request failed',
      'REQUEST_ERROR',
      err instanceof Error ? err.message : String(err)
    );
  }

  // Try to parse JSON response
  let data: any;
  try {
    const text = await response.text();
    if (!text) {
      data = {};
    } else {
      data = JSON.parse(text);
    }
  } catch (err) {
    // If response is not JSON, throw an error with the raw text
    throw new ApiError(
      response.status,
      'Invalid response from server',
      'INVALID_RESPONSE',
      `Server returned non-JSON response (status: ${response.status})`
    );
  }

  if (!response.ok) {
    throw new ApiError(
      response.status,
      data.error || 'Request failed',
      data.error_code || 'UNKNOWN_ERROR',
      data.detail
    );
  }

  return data;
}

export const api = {
  /**
   * Initialize investor profile from onboarding text
   */
  async initProfile(userId: string, onboardingText: string): Promise<InvestorProfile> {
    return request<InvestorProfile>('/profile/init', {
      method: 'POST',
      body: JSON.stringify({
        user_id: userId,
        onboarding_text: onboardingText,
      }),
    });
  },

  /**
   * Update investor profile from update text
   */
  async updateProfile(userId: string, updateText: string): Promise<InvestorProfile> {
    return request<InvestorProfile>('/profile/update', {
      method: 'POST',
      body: JSON.stringify({
        user_id: userId,
        update_text: updateText,
      }),
    });
  },

  /**
   * Get investor profile
   */
  async getProfile(userId: string): Promise<InvestorProfile> {
    return request<InvestorProfile>(`/profile/${userId}`);
  },

  /**
   * Analyze portfolio
   */
  async analyzePortfolio(
    userId: string,
    holdings: Holding[],
    cashWeight: number
  ): Promise<PortfolioMetrics> {
    return request<PortfolioMetrics>('/portfolio/analyze', {
      method: 'POST',
      body: JSON.stringify({
        user_id: userId,
        holdings: holdings.map(h => ({
          ticker: h.ticker,
          weight: h.weight / 100, // Convert percentage to decimal
        })),
        cash_weight: cashWeight / 100, // Convert percentage to decimal
      }),
    });
  },

  /**
   * Get portfolio recommendation
   */
  async getRecommendation(
    userId: string,
    holdings: Holding[],
    cashWeight: number
  ): Promise<RecommendationResponse> {
    return request<RecommendationResponse>('/recommend', {
      method: 'POST',
      body: JSON.stringify({
        user_id: userId,
        holdings: holdings.length > 0 ? holdings.map(h => ({
          ticker: h.ticker,
          weight: h.weight / 100, // Convert percentage to decimal
        })) : [],
        cash_weight: cashWeight / 100, // Convert percentage to decimal
      }),
    });
  },

  /**
   * Save portfolio snapshot
   */
  async saveSnapshot(
    userId: string,
    holdings: Holding[],
    cashWeight: number
  ): Promise<{ success: boolean; snapshot_id: string; timestamp: string }> {
    return request('/portfolio/snapshot', {
      method: 'POST',
      body: JSON.stringify({
        user_id: userId,
        holdings: holdings.map(h => ({
          ticker: h.ticker,
          weight: h.weight / 100, // Convert percentage to decimal
        })),
        cash_weight: cashWeight / 100, // Convert percentage to decimal
      }),
    });
  },

  /**
   * Get portfolio history
   */
  async getPortfolioHistory(userId: string): Promise<PortfolioHistoryResponse> {
    return request<PortfolioHistoryResponse>(`/portfolio/history/${userId}`);
  },

  /**
   * Compare two portfolios
   */
  async comparePortfolios(
    userId: string,
    currentHoldings: Holding[],
    currentCashWeight: number,
    recommendedHoldings: Holding[],
    recommendedCashWeight: number
  ): Promise<PortfolioComparison> {
    return request<PortfolioComparison>('/portfolio/compare', {
      method: 'POST',
      body: JSON.stringify({
        user_id: userId,
        current_portfolio: {
          holdings: currentHoldings.map(h => ({
            ticker: h.ticker,
            weight: h.weight / 100,
          })),
          cash_weight: currentCashWeight / 100,
        },
        recommended_portfolio: {
          holdings: recommendedHoldings.map(h => ({
            ticker: h.ticker,
            weight: h.weight / 100,
          })),
          cash_weight: recommendedCashWeight / 100,
        },
      }),
    });
  },

  /**
   * Health check
   */
  async healthCheck(): Promise<{ status: string; timestamp: string; backboard_connected: boolean }> {
    return request('/health');
  },

  /**
   * Get sectors for a list of tickers
   */
  async getTickerSectors(tickers: string[]): Promise<Record<string, string>> {
    return request<Record<string, string>>('/ticker/sectors', {
      method: 'POST',
      body: JSON.stringify({ tickers }),
    });
  },
};

export { ApiError };

