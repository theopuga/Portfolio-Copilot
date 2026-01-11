import { useState, useEffect } from 'react';
import { ArrowRight, TrendingUp, TrendingDown, Loader2, AlertCircle } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/card';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { PieChart, Pie, Cell, ResponsiveContainer, Legend } from 'recharts';
import { api, ApiError, PortfolioSnapshot } from '../../api/client';
import { getUserId } from '../../utils/user';
import { loadPortfolioCache, loadRecommendedPortfolioCache } from '../../utils/portfolioCache';

const SECTOR_COLORS: Record<string, string> = {
  'Technology': '#3b82f6',
  'Healthcare': '#10b981',
  'Finance': '#f59e0b',
  'Consumer Discretionary': '#8b5cf6',
  'Consumer Staples': '#8b5cf6',
  'Energy': '#ef4444',
  'Utilities': '#06b6d4',
  'Real Estate': '#ec4899',
  'Materials': '#14b8a6',
  'Industrials': '#f97316',
  'Other': '#6b7280',
};

export function ComparePage() {
  const [searchParams] = useSearchParams();
  const [loading, setLoading] = useState(true);
  const [comparing, setComparing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [comparison, setComparison] = useState<any>(null);
  const [snapshot1, setSnapshot1] = useState<PortfolioSnapshot | null>(null);
  const [snapshot2, setSnapshot2] = useState<PortfolioSnapshot | null>(null);
  const [snapshot1Holdings, setSnapshot1Holdings] = useState<Array<{ ticker: string; weight: number }>>([]);
  const [snapshot1Cash, setSnapshot1Cash] = useState(0);
  const [snapshot2Holdings, setSnapshot2Holdings] = useState<Array<{ ticker: string; weight: number }>>([]);
  const [snapshot2Cash, setSnapshot2Cash] = useState(0);

  const handleCompare = async () => {
    if (snapshot1Holdings.length === 0 && snapshot2Holdings.length === 0) {
      setError('Please provide at least one portfolio to compare');
      return;
    }

    if (snapshot1Holdings.length === 0) {
      setError('Please provide a first portfolio to compare');
      return;
    }

    if (snapshot2Holdings.length === 0) {
      setError('Please provide a second portfolio to compare');
      return;
    }

    try {
      setComparing(true);
      setError(null);
      const userId = getUserId();
      
      if (!userId) {
        setError('User ID not found. Please refresh the page.');
        return;
      }

      // Normalize and validate first portfolio
      // Step 1: Filter and clean holdings
      let normalizedSnapshot1 = snapshot1Holdings
        .filter(h => h.ticker && h.ticker.trim() && Number.isFinite(h.weight) && h.weight > 0)
        .map(h => ({ ticker: h.ticker.toUpperCase().trim(), weight: Math.max(0, h.weight) }));
      
      // Step 2: Calculate total equity weight
      const snapshot1EquityTotal = normalizedSnapshot1.reduce((sum, h) => sum + h.weight, 0);
      
      // Step 3: Normalize holdings to sum to (100 - cash) if cash is provided, otherwise scale to 100
      const targetSnapshot1Cash = Math.max(0, Math.min(100, snapshot1Cash || 0));
      const targetSnapshot1Equity = 100 - targetSnapshot1Cash;
      
      if (snapshot1EquityTotal > 0 && targetSnapshot1Equity > 0) {
        // Scale holdings to match target equity
        const scale = targetSnapshot1Equity / snapshot1EquityTotal;
        normalizedSnapshot1 = normalizedSnapshot1.map(h => ({
          ticker: h.ticker,
          weight: h.weight * scale
        }));
      } else if (snapshot1EquityTotal === 0 && targetSnapshot1Equity > 0) {
        // No holdings but we need equity - can't fix this, use cash only
        normalizedSnapshot1 = [];
      }
      
      // Step 4: Ensure final cash makes total = 100
      const finalSnapshot1Equity = normalizedSnapshot1.reduce((sum, h) => sum + h.weight, 0);
      let normalizedSnapshot1Cash = Math.max(0, 100 - finalSnapshot1Equity);

      // Normalize and validate second portfolio
      // Step 1: Filter and clean holdings
      let normalizedSnapshot2 = snapshot2Holdings
        .filter(h => h.ticker && h.ticker.trim() && Number.isFinite(h.weight) && h.weight > 0)
        .map(h => ({ ticker: h.ticker.toUpperCase().trim(), weight: Math.max(0, h.weight) }));
      
      // Step 2: Calculate total equity weight
      const snapshot2EquityTotal = normalizedSnapshot2.reduce((sum, h) => sum + h.weight, 0);
      
      // Step 3: Normalize holdings to sum to (100 - cash) if cash is provided, otherwise scale to 100
      const targetSnapshot2Cash = Math.max(0, Math.min(100, snapshot2Cash || 0));
      const targetSnapshot2Equity = 100 - targetSnapshot2Cash;
      
      if (snapshot2EquityTotal > 0 && targetSnapshot2Equity > 0) {
        // Scale holdings to match target equity
        const scale = targetSnapshot2Equity / snapshot2EquityTotal;
        normalizedSnapshot2 = normalizedSnapshot2.map(h => ({
          ticker: h.ticker,
          weight: h.weight * scale
        }));
      } else if (snapshot2EquityTotal === 0 && targetSnapshot2Equity > 0) {
        // No holdings but we need equity - can't fix this, use cash only
        normalizedSnapshot2 = [];
      }
      
      // Step 4: Ensure final cash makes total = 100
      const finalSnapshot2Equity = normalizedSnapshot2.reduce((sum, h) => sum + h.weight, 0);
      let normalizedSnapshot2Cash = Math.max(0, 100 - finalSnapshot2Equity);

      // Verify totals sum to 100 (with small tolerance for floating point)
      const snapshot1Total = normalizedSnapshot1.reduce((sum, h) => sum + h.weight, 0) + normalizedSnapshot1Cash;
      const snapshot2Total = normalizedSnapshot2.reduce((sum, h) => sum + h.weight, 0) + normalizedSnapshot2Cash;
      
      if (Math.abs(snapshot1Total - 100) > 0.01) {
        console.warn(`First portfolio total is ${snapshot1Total}%, normalizing...`);
        // Final normalization: scale everything to sum to 100
        const snapshot1Scale = 100 / snapshot1Total;
        normalizedSnapshot1 = normalizedSnapshot1.map(h => ({
          ticker: h.ticker,
          weight: h.weight * snapshot1Scale
        }));
        normalizedSnapshot1Cash = normalizedSnapshot1Cash * snapshot1Scale;
      }
      
      if (Math.abs(snapshot2Total - 100) > 0.01) {
        console.warn(`Second portfolio total is ${snapshot2Total}%, normalizing...`);
        // Final normalization: scale everything to sum to 100
        const snapshot2Scale = 100 / snapshot2Total;
        normalizedSnapshot2 = normalizedSnapshot2.map(h => ({
          ticker: h.ticker,
          weight: h.weight * snapshot2Scale
        }));
        normalizedSnapshot2Cash = normalizedSnapshot2Cash * snapshot2Scale;
      }
      
      // Update state if needed
      if (
        Math.abs(snapshot1Total - 100) > 0.05 ||
        Math.abs(snapshot2Total - 100) > 0.05
      ) {
        setSnapshot1Holdings(normalizedSnapshot1);
        setSnapshot1Cash(normalizedSnapshot1Cash);
        setSnapshot2Holdings(normalizedSnapshot2);
        setSnapshot2Cash(normalizedSnapshot2Cash);
      }

      // Final validation before API call
      const finalSnapshot1Total = normalizedSnapshot1.reduce((sum, h) => sum + h.weight, 0) + normalizedSnapshot1Cash;
      const finalSnapshot2Total = normalizedSnapshot2.reduce((sum, h) => sum + h.weight, 0) + normalizedSnapshot2Cash;
      
      if (Math.abs(finalSnapshot1Total - 100) > 0.01 || Math.abs(finalSnapshot2Total - 100) > 0.01) {
        const errorMsg = `Portfolio weights do not sum to 100%: First=${finalSnapshot1Total.toFixed(2)}%, Second=${finalSnapshot2Total.toFixed(2)}%`;
        console.error(errorMsg, {
          snapshot1: { holdings: normalizedSnapshot1, cash: normalizedSnapshot1Cash },
          snapshot2: { holdings: normalizedSnapshot2, cash: normalizedSnapshot2Cash }
        });
        setError(errorMsg);
        return;
      }
      
      // Log what we're sending for debugging
      console.log('Comparing portfolios:', {
        snapshot1: {
          holdings: normalizedSnapshot1.length,
          total: finalSnapshot1Total,
          cash: normalizedSnapshot1Cash
        },
        snapshot2: {
          holdings: normalizedSnapshot2.length,
          total: finalSnapshot2Total,
          cash: normalizedSnapshot2Cash
        }
      });

      const comp = await api.comparePortfolios(
        userId,
        normalizedSnapshot1,
        normalizedSnapshot1Cash,
        normalizedSnapshot2,
        normalizedSnapshot2Cash
      );
      
      setComparison(comp);
    } catch (err) {
      console.error('Compare error:', err);
      setError(err instanceof Error ? err.message : 'Failed to compare portfolios');
    } finally {
      setComparing(false);
    }
  };

  useEffect(() => {
    loadInitialData();
  }, [searchParams]);

  const loadInitialData = async () => {
    try {
      setLoading(true);
      setError(null);
      const userId = getUserId();
      
      if (!userId) {
        setError('User ID not found. Please refresh the page.');
        return;
      }

      // Check if profile exists first - required for comparison
      try {
        await api.getProfile(userId);
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          setError('Profile not found. Please initialize your profile first on the Profile page.');
          setLoading(false);
          return;
        }
      }
      
      // Get snapshot IDs from URL params
      const snapshot1Id = searchParams.get('snapshot1');
      const snapshot2Id = searchParams.get('snapshot2');
      
      if (!snapshot1Id || !snapshot2Id) {
        setError('Please select two snapshots to compare from the History page.');
        setLoading(false);
        return;
      }
      
      // Load portfolio history to find the selected snapshots
      try {
        const history = await api.getPortfolioHistory(userId);
        const foundSnapshot1 = history.snapshots.find(s => s.snapshot_id === snapshot1Id);
        const foundSnapshot2 = history.snapshots.find(s => s.snapshot_id === snapshot2Id);
        
        if (!foundSnapshot1) {
          setError(`Snapshot 1 (${snapshot1Id}) not found. Please select valid snapshots from the History page.`);
          setLoading(false);
          return;
        }
        
        if (!foundSnapshot2) {
          setError(`Snapshot 2 (${snapshot2Id}) not found. Please select valid snapshots from the History page.`);
          setLoading(false);
          return;
        }
        
        // Set snapshots
        setSnapshot1(foundSnapshot1);
        setSnapshot2(foundSnapshot2);
        
        // Load holdings for snapshot 1
        setSnapshot1Holdings(
          foundSnapshot1.holdings.map(h => ({
            ticker: h.ticker,
            weight: h.weight * 100, // Convert to percentage
          }))
        );
        setSnapshot1Cash(foundSnapshot1.cash_weight * 100);
        
        // Load holdings for snapshot 2
        setSnapshot2Holdings(
          foundSnapshot2.holdings.map(h => ({
            ticker: h.ticker,
            weight: h.weight * 100, // Convert to percentage
          }))
        );
        setSnapshot2Cash(foundSnapshot2.cash_weight * 100);
        
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load portfolio snapshots');
      }
      
    } catch (err) {
      // Non-fatal - user can still manually enter data
      console.warn('Failed to load initial data for comparison:', err);
      setError(err instanceof Error ? err.message : 'Failed to load portfolio data');
    } finally {
      setLoading(false);
    }
  };

  // Auto-compare when both portfolios are loaded (with proper error handling)
  useEffect(() => {
    // Only auto-compare if we have both portfolios and no error
    if (!loading && !error && snapshot1Holdings.length > 0 && snapshot2Holdings.length > 0 && !comparison && !comparing) {
      // Auto-trigger comparison after a short delay to ensure state is settled
      const timer = setTimeout(async () => {
        try {
          await handleCompare();
        } catch (err) {
          // Error is already handled in handleCompare, but prevent blank page
          console.error('Auto-compare failed:', err);
        }
      }, 300);
      return () => clearTimeout(timer);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, error, snapshot1Holdings.length, snapshot2Holdings.length, comparison, comparing]);

  // Convert sector allocation to chart data
  const getSectorData = (sectorAllocation: Record<string, number> | undefined | null) => {
    if (!sectorAllocation || typeof sectorAllocation !== 'object') {
      return [];
    }
    try {
      return Object.entries(sectorAllocation)
        .map(([name, value]) => ({
          name,
          value: Math.round((Number(value) || 0) * 100),
          color: SECTOR_COLORS[name] || SECTOR_COLORS['Other'],
        }))
        .filter(item => item.value > 0)
        .sort((a, b) => b.value - a.value);
    } catch (err) {
      console.error('Error processing sector data:', err);
      return [];
    }
  };

  const portfolio1 = comparison && comparison.current ? {
    date: snapshot1 ? new Date(snapshot1.timestamp).toLocaleDateString() : 'Snapshot 1',
    timestamp: snapshot1 ? snapshot1.timestamp : '',
    holdings: comparison.current.total_holdings || 0,
    riskScore: 0, // Would need profile
    hhiScore: comparison.current.herfindahl_index || 0,
    topConcentration: Math.round((comparison.current.top_1_weight || 0) * 100 * 10) / 10,
    top3Concentration: Math.round((comparison.current.top_3_weight || 0) * 100 * 10) / 10,
    sectors: getSectorData(comparison.current.sector_allocation),
  } : null;

  const portfolio2 = comparison && comparison.recommended ? {
    date: snapshot2 ? new Date(snapshot2.timestamp).toLocaleDateString() : 'Snapshot 2',
    timestamp: snapshot2 ? snapshot2.timestamp : '',
    holdings: comparison.recommended.total_holdings || 0,
    riskScore: 0, // Would need profile
    hhiScore: comparison.recommended.herfindahl_index || 0,
    topConcentration: Math.round((comparison.recommended.top_1_weight || 0) * 100 * 10) / 10,
    top3Concentration: Math.round((comparison.recommended.top_3_weight || 0) * 100 * 10) / 10,
    sectors: getSectorData(comparison.recommended.sector_allocation),
  } : null;

  const MetricComparisonRow = ({ 
    label, 
    current, 
    recommended, 
    unit = '',
    improved = false 
  }: { 
    label: string; 
    current: number | string; 
    recommended: number | string; 
    unit?: string;
    improved?: boolean;
  }) => (
    <div className="grid grid-cols-3 gap-4 py-3 border-b border-gray-100 last:border-0">
      <div className="text-sm font-medium text-gray-700">{label}</div>
      <div className="text-sm text-gray-900 text-center">{current}{unit}</div>
      <div className="flex items-center justify-center gap-2">
        <span className="text-sm text-gray-900">{recommended}{unit}</span>
        {improved && (
          <Badge variant="outline" className="text-green-600 border-green-600">
            Improved
          </Badge>
        )}
      </div>
    </div>
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold text-gray-900">Portfolio Comparison</h1>
        <p className="text-gray-600 mt-1">Side-by-side analysis of two selected portfolio snapshots</p>
      </div>

      {error && (
        <Card className="border-red-200 bg-red-50">
          <CardContent className="pt-6">
            <div className="flex items-center gap-2 text-red-800">
              <AlertCircle className="w-5 h-5" />
              <p>{error}</p>
            </div>
          </CardContent>
        </Card>
      )}

      {loading && (
        <div className="flex items-center justify-center h-64">
          <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
        </div>
      )}

      {!loading && !comparison && !error && (
        <Card>
          <CardContent className="pt-6">
            <div className="space-y-4">
              <div>
                <h3 className="text-lg font-medium mb-2">First Portfolio</h3>
                <p className="text-sm text-gray-600 mb-2">
                  {snapshot1Holdings.length > 0 && snapshot1
                    ? `Loaded ${snapshot1Holdings.length} holdings from snapshot dated ${new Date(snapshot1.timestamp).toLocaleDateString()}.`
                    : 'No first portfolio found. Please select snapshots from the History page.'}
                </p>
              </div>
              
              <div>
                <h3 className="text-lg font-medium mb-2">Second Portfolio</h3>
                <p className="text-sm text-gray-600 mb-4">
                  {snapshot2Holdings.length > 0 && snapshot2
                    ? `Loaded ${snapshot2Holdings.length} holdings from snapshot dated ${new Date(snapshot2.timestamp).toLocaleDateString()}.`
                    : 'No second portfolio found. Please select snapshots from the History page.'}
                </p>
              </div>

              {snapshot1Holdings.length > 0 && snapshot2Holdings.length > 0 && (
                <div className="flex justify-center">
                  <Button 
                    onClick={handleCompare} 
                    disabled={comparing}
                    className="bg-blue-600 hover:bg-blue-700"
                  >
                    {comparing ? (
                      <>
                        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                        Comparing...
                      </>
                    ) : (
                      'Compare Portfolios'
                    )}
                  </Button>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {comparison && portfolio1 && portfolio2 && (
        <>
          {/* Comparison Header */}
          <div className="grid grid-cols-2 gap-6">
            <Card className="border-2 border-gray-300">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle>Portfolio 1</CardTitle>
                  <Badge variant="outline">{portfolio1.date}</Badge>
                </div>
              </CardHeader>
            </Card>

            <Card className="border-2 border-blue-500">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle>Portfolio 2</CardTitle>
                  <Badge variant="outline">{portfolio2.date}</Badge>
                </div>
              </CardHeader>
            </Card>
          </div>
        </>
      )}

      {comparison && portfolio1 && portfolio2 && (
        <>
          {/* Key Metrics Comparison */}
          <Card>
            <CardHeader>
              <CardTitle>Key Metrics</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-3 gap-4 mb-4 pb-3 border-b border-gray-200">
                <div className="text-sm font-semibold text-gray-600">Metric</div>
                <div className="text-sm font-semibold text-gray-600 text-center">Portfolio 1</div>
                <div className="text-sm font-semibold text-gray-600 text-center">Portfolio 2</div>
              </div>

              <MetricComparisonRow
                label="Holdings Count"
                current={portfolio1.holdings}
                recommended={portfolio2.holdings}
                improved={comparison.differences.holdings_change > 0}
              />
              <MetricComparisonRow
                label="HHI Score"
                current={portfolio1.hhiScore.toFixed(3)}
                recommended={portfolio2.hhiScore.toFixed(3)}
                improved={comparison.differences.risk_change < 0}
              />
              <MetricComparisonRow
                label="Top Position"
                current={portfolio1.topConcentration}
                recommended={portfolio2.topConcentration}
                unit="%"
                improved={comparison.differences.top_1_weight_change < 0}
              />
              <MetricComparisonRow
                label="Top 3 Concentration"
                current={portfolio1.top3Concentration}
                recommended={portfolio2.top3Concentration}
                unit="%"
                improved={comparison.differences.top_3_weight_change < 0}
              />
            </CardContent>
          </Card>
        </>
      )}

      {comparison && portfolio1 && portfolio2 && (
        <>
          {/* Sector Allocation Comparison */}
          <Card>
            <CardHeader>
              <CardTitle>Sector Allocation Comparison</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-8">
                {/* Portfolio 1 Chart */}
                <div>
                  <h3 className="text-sm font-medium text-gray-700 mb-4 text-center">Portfolio 1 ({portfolio1.date})</h3>
                  {portfolio1.sectors.length > 0 ? (
                    <>
                      <div className="h-64">
                        <ResponsiveContainer width="100%" height="100%">
                          <PieChart>
                            <Pie
                              data={portfolio1.sectors}
                              cx="50%"
                              cy="50%"
                              innerRadius={60}
                              outerRadius={90}
                              paddingAngle={2}
                              dataKey="value"
                              label={({ value }) => `${value}%`}
                            >
                              {portfolio1.sectors.map((entry, index) => (
                                <Cell key={`cell-${index}`} fill={entry.color} />
                              ))}
                            </Pie>
                          </PieChart>
                        </ResponsiveContainer>
                      </div>
                      <div className="grid grid-cols-2 gap-2 mt-4">
                        {portfolio1.sectors.map((sector) => (
                          <div key={sector.name} className="flex items-center gap-2">
                            <div className="w-3 h-3 rounded-sm" style={{ backgroundColor: sector.color }} />
                            <span className="text-xs text-gray-600">{sector.name}</span>
                            <span className="text-xs font-medium text-gray-900 ml-auto">{sector.value}%</span>
                          </div>
                        ))}
                      </div>
                    </>
                  ) : (
                    <div className="h-64 flex items-center justify-center text-gray-500">
                      <p>No sector data</p>
                    </div>
                  )}
                </div>

                {/* Portfolio 2 Chart */}
                <div>
                  <h3 className="text-sm font-medium text-gray-700 mb-4 text-center">Portfolio 2 ({portfolio2.date})</h3>
                  {portfolio2.sectors.length > 0 ? (
                    <>
                      <div className="h-64">
                        <ResponsiveContainer width="100%" height="100%">
                          <PieChart>
                            <Pie
                              data={portfolio2.sectors}
                              cx="50%"
                              cy="50%"
                              innerRadius={60}
                              outerRadius={90}
                              paddingAngle={2}
                              dataKey="value"
                              label={({ value }) => `${value}%`}
                            >
                              {portfolio2.sectors.map((entry, index) => (
                                <Cell key={`cell-${index}`} fill={entry.color} />
                              ))}
                            </Pie>
                          </PieChart>
                        </ResponsiveContainer>
                      </div>
                      <div className="grid grid-cols-2 gap-2 mt-4">
                        {portfolio2.sectors.map((sector) => (
                          <div key={sector.name} className="flex items-center gap-2">
                            <div className="w-3 h-3 rounded-sm" style={{ backgroundColor: sector.color }} />
                            <span className="text-xs text-gray-600">{sector.name}</span>
                            <span className="text-xs font-medium text-gray-900 ml-auto">{sector.value}%</span>
                          </div>
                        ))}
                      </div>
                    </>
                  ) : (
                    <div className="h-64 flex items-center justify-center text-gray-500">
                      <p>No sector data</p>
                    </div>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>
        </>
      )}

      {comparison && comparison.differences && comparison.differences.sector_allocation_changes && Object.keys(comparison.differences.sector_allocation_changes).length > 0 && (
        <Card className="border-blue-200 bg-blue-50">
          <CardHeader>
            <CardTitle className="text-blue-900">Key Differences</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {Object.entries(comparison.differences.sector_allocation_changes).map(([sector, change]: [string, any]) => (
                <div key={sector} className="flex items-start gap-3">
                  {change.change > 0 ? (
                    <TrendingUp className="w-5 h-5 text-blue-600 mt-0.5 flex-shrink-0" />
                  ) : (
                    <TrendingDown className="w-5 h-5 text-blue-600 mt-0.5 flex-shrink-0" />
                  )}
                  <div>
                    <p className="text-sm font-medium text-blue-900">
                      {sector} {change.change > 0 ? 'Increased' : 'Reduced'}
                    </p>
                    <p className="text-sm text-blue-800">
                      {Math.round(change.current * 100)}% → {Math.round(change.recommended * 100)}% 
                      ({change.change > 0 ? '+' : ''}{Math.round(change.change * 100)} percentage points)
                    </p>
                  </div>
                </div>
              ))}
              <div className="flex items-start gap-3">
                <ArrowRight className="w-5 h-5 text-blue-600 mt-0.5 flex-shrink-0" />
                <div>
                  <p className="text-sm font-medium text-blue-900">
                    Portfolio Changes
                  </p>
                  <p className="text-sm text-blue-800">
                    Holdings: {comparison.differences.holdings_change > 0 ? '+' : ''}{comparison.differences.holdings_change}, 
                    HHI change: {comparison.differences.risk_change > 0 ? '+' : ''}{comparison.differences.risk_change.toFixed(3)}
                  </p>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
