import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Trash2, Plus, AlertCircle, Loader2 } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/card';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Badge } from '../ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../ui/table';
import { PieChart, Pie, Cell, ResponsiveContainer } from 'recharts';
import { api, ApiError } from '../../api/client';
import { getUserId } from '../../utils/user';
import { loadPortfolioCache, savePortfolioCache } from '../../utils/portfolioCache';

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

export function PortfolioPage() {
  const [searchParams] = useSearchParams();
  const [holdings, setHoldings] = useState<Array<{ ticker: string; weight: number; sector?: string }>>([
    { ticker: 'AAPL', weight: 18.5 },
    { ticker: 'MSFT', weight: 15.2 },
    { ticker: 'GOOGL', weight: 13.5 },
  ]);

  const [cashAllocation, setCashAllocation] = useState('0');
  const [analyzing, setAnalyzing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [metrics, setMetrics] = useState<any>(null);
  const [tickerSectors, setTickerSectors] = useState<Record<string, string>>({});

  // Load snapshot or last draft/analysis once so navigating away doesn't wipe the UI.
  useEffect(() => {
    const loadData = async () => {
      const snapshotId = searchParams.get('snapshot_id');
      const userId = getUserId();

      // If snapshot_id is provided, load that snapshot
      if (snapshotId && userId) {
        try {
          setLoading(true);
          setError(null);
          const history = await api.getPortfolioHistory(userId);
          const snapshot = history.snapshots.find(s => s.snapshot_id === snapshotId);
          
          if (snapshot) {
            // Load snapshot data
            const loadedHoldings = snapshot.holdings.map(h => ({
              ticker: h.ticker,
              weight: h.weight * 100, // Convert to percentage
            }));
            setHoldings(loadedHoldings);
            setCashAllocation(String(snapshot.cash_weight * 100));
            setMetrics(snapshot.metrics);
            // Sectors are included in metrics.ticker_sectors
          } else {
            setError(`Snapshot not found: ${snapshotId}`);
          }
        } catch (err) {
          setError(err instanceof Error ? err.message : 'Failed to load snapshot');
        } finally {
          setLoading(false);
        }
      } else {
        // Otherwise, load from cache
        const cached = loadPortfolioCache(userId);
        if (cached) {
          if (cached.holdings?.length) {
            const cachedHoldings = cached.holdings.map((h) => ({ ticker: h.ticker, weight: h.weightPct }));
            setHoldings(cachedHoldings);
            // Sectors are included in cached.metrics.ticker_sectors if metrics exist
          }
          if (typeof cached.cashPct === 'number' && Number.isFinite(cached.cashPct)) {
            setCashAllocation(String(cached.cashPct));
          }
          if (cached.metrics) {
            setMetrics(cached.metrics as any);
          }
        }
      }
    };

    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  // Update sectors from metrics when available
  useEffect(() => {
    // Sectors are included in metrics response, so use them directly
    if (metrics?.ticker_sectors && Object.keys(metrics.ticker_sectors).length > 0) {
      setTickerSectors(metrics.ticker_sectors);
    }
  }, [metrics]);

  // Persist draft + latest analysis.
  useEffect(() => {
    const userId = getUserId();
    savePortfolioCache(userId, {
      holdings: holdings.map((h) => ({ ticker: h.ticker, weightPct: h.weight })),
      cashPct: parseFloat(cashAllocation || '0') || 0,
      metrics,
      updatedAt: new Date().toISOString(),
    });
  }, [holdings, cashAllocation, metrics]);

  const totalWeight = holdings.reduce((sum, h) => sum + h.weight, 0) + parseFloat(cashAllocation || '0');
  const isValid = Math.abs(totalWeight - 100) < 0.01;

  // Convert sector allocation to chart data
  const sectorData = metrics?.sector_allocation
    ? [
        ...Object.entries(metrics.sector_allocation).map(([name, value]) => ({
          name,
          value: Math.round((value as number) * 100),
          color: SECTOR_COLORS[name] || SECTOR_COLORS['Other'],
        })),
        ...(parseFloat(cashAllocation || '0') > 0 ? [{
          name: 'Cash',
          value: parseFloat(cashAllocation || '0'),
          color: '#6b7280',
        }] : []),
      ].filter(item => item.value > 0).sort((a, b) => b.value - a.value)
    : [];

  const removeHolding = (index: number) => {
    setHoldings(holdings.filter((_, i) => i !== index));
    setMetrics(null); // Clear metrics when holdings change
  };

  const addHolding = () => {
    setHoldings([...holdings, { ticker: '', weight: 0 }]);
  };

  const handleAnalyze = async () => {
    if (!isValid) {
      setError('Portfolio weights must sum to 100%');
      return;
    }

    try {
      setAnalyzing(true);
      setError(null);
      setSuccess(false);
      const userId = getUserId();
      
      const validHoldings = holdings.filter(h => h.ticker.trim() && h.weight > 0);
      const metricsData = await api.analyzePortfolio(
        userId,
        validHoldings,
        parseFloat(cashAllocation || '0')
      );
      
      setMetrics(metricsData);
      // Update sectors from metrics
      if (metricsData.ticker_sectors) {
        setTickerSectors(metricsData.ticker_sectors);
      }

      // Note: Snapshot saving is handled manually via the "Save Snapshot" button
      // to prevent duplicate saves when analyzing portfolios

      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to analyze portfolio');
    } finally {
      setAnalyzing(false);
    }
  };

  const handleSaveSnapshot = async () => {
    if (!isValid) {
      setError('Portfolio weights must sum to 100%');
      return;
    }

    if (!metrics) {
      setError('Please analyze portfolio first');
      return;
    }

    try {
      setSaving(true);
      setError(null);
      const userId = getUserId();
      
      const validHoldings = holdings.filter(h => h.ticker.trim() && h.weight > 0);
      await api.saveSnapshot(
        userId,
        validHoldings,
        parseFloat(cashAllocation || '0')
      );
      
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save snapshot');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold text-gray-900">Portfolio</h1>
        <p className="text-gray-600 mt-1">
          {searchParams.get('snapshot_id') ? 'Viewing portfolio snapshot' : 'Enter and analyze your current holdings'}
        </p>
      </div>

      {loading && (
        <div className="flex items-center justify-center h-64">
          <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
        </div>
      )}

      {!loading && (
        <>
      {/* Holdings Table */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Holdings</CardTitle>
          <Button onClick={addHolding} size="sm" variant="outline" className="gap-2">
            <Plus className="w-4 h-4" />
            Add Holding
          </Button>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Ticker</TableHead>
                <TableHead>Weight (%)</TableHead>
                <TableHead>Sector</TableHead>
                <TableHead className="w-16"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {holdings.map((holding, index) => (
                <TableRow key={index}>
                  <TableCell>
                    <Input
                      value={holding.ticker}
                      onChange={(e) => {
                        const newHoldings = [...holdings];
                        newHoldings[index].ticker = e.target.value.toUpperCase();
                        setHoldings(newHoldings);
                        setMetrics(null); // Clear metrics when holdings change
                      }}
                      className="h-9 w-24"
                      placeholder="AAPL"
                    />
                  </TableCell>
                  <TableCell>
                    <Input
                      type="number"
                      value={holding.weight}
                      onChange={(e) => {
                        const newHoldings = [...holdings];
                        newHoldings[index].weight = parseFloat(e.target.value) || 0;
                        setHoldings(newHoldings);
                        setMetrics(null); // Clear metrics when holdings change
                      }}
                      className="h-9 w-24"
                      step="0.1"
                    />
                  </TableCell>
                  <TableCell className="text-sm text-gray-600">
                    {holdings[index]?.ticker 
                      ? (tickerSectors[holdings[index].ticker.toUpperCase()] || '-')
                      : '-'}
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => removeHolding(index)}
                      className="text-red-600 hover:text-red-700 hover:bg-red-50"
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          <div className="mt-6 flex items-center gap-4">
            <div className="flex items-center gap-2">
              <label className="text-sm font-medium text-gray-700">Cash Allocation:</label>
              <Input
                type="number"
                value={cashAllocation}
                onChange={(e) => setCashAllocation(e.target.value)}
                className="h-9 w-20"
                step="0.1"
              />
              <span className="text-sm text-gray-600">%</span>
            </div>

            <div className="ml-auto flex items-center gap-4">
              <div className="text-sm">
                <span className="text-gray-600">Total:</span>{' '}
                <span className={`font-medium ${isValid ? 'text-green-600' : 'text-red-600'}`}>
                  {totalWeight.toFixed(1)}%
                </span>
              </div>
              {!isValid && (
                <Badge variant="destructive" className="gap-1">
                  <AlertCircle className="w-3 h-3" />
                  Must equal 100%
                </Badge>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

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

      {success && (
        <Card className="border-green-200 bg-green-50">
          <CardContent className="pt-6">
            <div className="flex items-center gap-2 text-green-800">
              <p>Operation completed successfully!</p>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="flex gap-3">
        <Button 
          className="bg-blue-600 hover:bg-blue-700" 
          disabled={!isValid || analyzing}
          onClick={handleAnalyze}
        >
          {analyzing ? (
            <>
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              Analyzing...
            </>
          ) : (
            'Analyze Portfolio'
          )}
        </Button>
        {metrics && (
          <Button 
            variant="outline"
            disabled={saving}
            onClick={handleSaveSnapshot}
          >
            {saving ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Saving...
              </>
            ) : (
              'Save Snapshot'
            )}
          </Button>
        )}
      </div>

      {/* Analysis Results */}
      {metrics && (
        <>
          <div className="grid grid-cols-2 gap-6">
            {/* Portfolio Metrics */}
            <Card>
              <CardHeader>
                <CardTitle>Portfolio Metrics</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex justify-between items-center">
                  <span className="text-sm text-gray-600">Holdings Count</span>
                  <span className="text-lg font-medium text-gray-900">{metrics.total_holdings}</span>
                </div>
                <div className="h-px bg-gray-200" />
                
                <div className="flex justify-between items-center">
                  <span className="text-sm text-gray-600">Top 1 Concentration</span>
                  <span className="text-sm font-medium text-gray-900">
                    {Math.round(metrics.top_1_weight * 100 * 10) / 10}%
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-gray-600">Top 3 Concentration</span>
                  <span className="text-sm font-medium text-gray-900">
                    {Math.round(metrics.top_3_weight * 100 * 10) / 10}%
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-gray-600">Top 5 Concentration</span>
                  <span className="text-sm font-medium text-gray-900">
                    {Math.round(metrics.top_5_weight * 100 * 10) / 10}%
                  </span>
                </div>
                
                <div className="h-px bg-gray-200" />
                
                <div className="flex justify-between items-center">
                  <span className="text-sm text-gray-600">HHI Score</span>
                  <span className="text-lg font-medium text-gray-900">{metrics.herfindahl_index.toFixed(3)}</span>
                </div>
              </CardContent>
            </Card>

            {/* Sector Allocation */}
            <Card>
              <CardHeader>
                <CardTitle>Sector Allocation</CardTitle>
              </CardHeader>
              <CardContent>
                {sectorData.length > 0 ? (
                  <>
                    <div className="h-48">
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie
                            data={sectorData}
                            cx="50%"
                            cy="50%"
                            innerRadius={50}
                            outerRadius={75}
                            paddingAngle={2}
                            dataKey="value"
                          >
                            {sectorData.map((entry, index) => (
                              <Cell key={`cell-${index}`} fill={entry.color} />
                            ))}
                          </Pie>
                        </PieChart>
                      </ResponsiveContainer>
                    </div>
                    <div className="grid grid-cols-2 gap-2 mt-4">
                      {sectorData.map((sector) => (
                        <div key={sector.name} className="flex items-center gap-2">
                          <div className="w-3 h-3 rounded-sm" style={{ backgroundColor: sector.color }} />
                          <span className="text-xs text-gray-600">{sector.name}</span>
                          <span className="text-xs font-medium text-gray-900 ml-auto">{sector.value}%</span>
                        </div>
                      ))}
                    </div>
                  </>
                ) : (
                  <div className="h-48 flex items-center justify-center text-gray-500">
                    <p>No sector data available</p>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Constraint Violations */}
          {metrics.constraint_violations.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <AlertCircle className="w-5 h-5 text-amber-600" />
                  Constraint Violations
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-2">
                  {metrics.constraint_violations.map((violation, index) => (
                    <li key={index} className="flex items-start gap-2 text-sm">
                      <span className="text-amber-600 mt-0.5">•</span>
                      <span className="text-gray-700">{violation}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </>
      )}
      </>
      )}
    </div>
  );
}
