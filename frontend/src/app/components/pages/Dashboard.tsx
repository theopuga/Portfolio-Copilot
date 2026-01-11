import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { AlertCircle, Loader2 } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/card';
import { Button } from '../ui/button';
import { Progress } from '../ui/progress';
import { Badge } from '../ui/badge';
import { PieChart, Pie, Cell, ResponsiveContainer } from 'recharts';
import { api, ApiError } from '../../api/client';
import { getUserId } from '../../utils/user';
import { loadPortfolioCache } from '../../utils/portfolioCache';

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

export function Dashboard() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [profile, setProfile] = useState<any>(null);
  const [metrics, setMetrics] = useState<any>(null);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);
      const userId = getUserId();
      
      try {
        const profileData = await api.getProfile(userId);
        setProfile(profileData);
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          // Profile doesn't exist yet - that's okay
          setProfile(null);
        } else {
          throw err;
        }
      }

      // Prefer backend snapshot as source of truth for "last analyzed" portfolio.
      try {
        const history = await api.getPortfolioHistory(userId);
        const latest = history.snapshots?.[0];
        if (latest?.metrics) {
          setMetrics(latest.metrics as any);
        } else {
          setMetrics(null);
        }
      } catch (err) {
        // If backend has no snapshots or is unavailable, fall back to local cache.
        const cached = loadPortfolioCache(userId);
        setMetrics((cached?.metrics as any) ?? null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load data');
    } finally {
      setLoading(false);
    }
  };

  // Convert sector allocation to chart data
  const sectorData = metrics?.sector_allocation
    ? Object.entries(metrics.sector_allocation)
        .map(([name, value]) => ({
          name,
          value: Math.round((value as number) * 100),
          color: SECTOR_COLORS[name] || SECTOR_COLORS['Other'],
        }))
        .filter(item => item.value > 0)
        .sort((a, b) => b.value - a.value)
    : [];

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-semibold text-gray-900">Dashboard</h1>
          <p className="text-gray-600 mt-1">Portfolio overview and health metrics</p>
        </div>
        <Card className="border-red-200 bg-red-50">
          <CardContent className="pt-6">
            <div className="flex items-center gap-2 text-red-800">
              <AlertCircle className="w-5 h-5" />
              <p>Error loading data: {error}</p>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!profile) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-semibold text-gray-900">Dashboard</h1>
          <p className="text-gray-600 mt-1">Portfolio overview and health metrics</p>
        </div>
        <Card>
          <CardContent className="pt-6">
            <div className="text-center py-8">
              <p className="text-gray-600 mb-4">No profile found. Please initialize your profile first.</p>
              <Link to="/profile">
                <Button className="bg-blue-600 hover:bg-blue-700">
                  Go to Profile
                </Button>
              </Link>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  const investorProfile = {
    objective: profile.objective.type.charAt(0).toUpperCase() + profile.objective.type.slice(1),
    riskScore: profile.risk_score,
    investmentHorizon: profile.horizon_months,
    rebalanceFrequency: profile.rebalance_frequency.charAt(0).toUpperCase() + profile.rebalance_frequency.slice(1),
  };

  const portfolioMetrics = metrics ? {
    totalHoldings: metrics.total_holdings,
    top1Concentration: Math.round(metrics.top_1_weight * 100 * 10) / 10,
    top3Concentration: Math.round(metrics.top_3_weight * 100 * 10) / 10,
    top5Concentration: Math.round(metrics.top_5_weight * 100 * 10) / 10,
    hhiScore: metrics.herfindahl_index,
    violations: metrics.constraint_violations.length,
  } : null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold text-gray-900">Dashboard</h1>
        <p className="text-gray-600 mt-1">Portfolio overview and health metrics</p>
      </div>

      {/* Investor Profile Summary */}
      <Card>
        <CardHeader>
          <CardTitle>Investor Profile Summary</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-6">
            <div>
              <p className="text-sm text-gray-600 mb-1">Investment Objective</p>
              <p className="text-lg font-medium text-gray-900">{investorProfile.objective}</p>
            </div>
            <div>
              <p className="text-sm text-gray-600 mb-1">Risk Score</p>
              <div className="flex items-center gap-3">
                <Progress value={investorProfile.riskScore} className="flex-1" />
                <span className="text-lg font-medium text-gray-900 w-12">{investorProfile.riskScore}</span>
              </div>
            </div>
            <div>
              <p className="text-sm text-gray-600 mb-1">Investment Horizon</p>
              <p className="text-lg font-medium text-gray-900">{investorProfile.investmentHorizon} months</p>
            </div>
            <div>
              <p className="text-sm text-gray-600 mb-1">Rebalance Frequency</p>
              <p className="text-lg font-medium text-gray-900">{investorProfile.rebalanceFrequency}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {portfolioMetrics ? (
        <div className="grid grid-cols-2 gap-6">
          {/* Portfolio Metrics */}
          <Card>
            <CardHeader>
              <CardTitle>Portfolio Metrics</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex justify-between items-center">
                <span className="text-sm text-gray-600">Total Holdings</span>
                <span className="text-lg font-medium text-gray-900">{portfolioMetrics.totalHoldings}</span>
              </div>
              <div className="h-px bg-gray-200" />
              
              <div className="space-y-2">
                <div className="flex justify-between items-center">
                  <span className="text-sm text-gray-600">Top 1 Concentration</span>
                  <span className="text-sm font-medium text-gray-900">{portfolioMetrics.top1Concentration}%</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-gray-600">Top 3 Concentration</span>
                  <span className="text-sm font-medium text-gray-900">{portfolioMetrics.top3Concentration}%</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-gray-600">Top 5 Concentration</span>
                  <span className="text-sm font-medium text-gray-900">{portfolioMetrics.top5Concentration}%</span>
                </div>
              </div>
              
              <div className="h-px bg-gray-200" />
              
              <div className="flex justify-between items-center">
                <span className="text-sm text-gray-600">HHI Score</span>
                <span className="text-lg font-medium text-gray-900">{portfolioMetrics.hhiScore.toFixed(3)}</span>
              </div>
              
              <div className="flex justify-between items-center">
                <span className="text-sm text-gray-600">Constraint Violations</span>
                {portfolioMetrics.violations > 0 ? (
                  <Badge variant="destructive" className="gap-1">
                    <AlertCircle className="w-3 h-3" />
                    {portfolioMetrics.violations}
                  </Badge>
                ) : (
                  <Badge variant="outline">None</Badge>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Sector Allocation Chart */}
          <Card>
            <CardHeader>
              <CardTitle>Sector Allocation</CardTitle>
            </CardHeader>
            <CardContent>
              {sectorData.length > 0 ? (
                <>
                  <div className="h-64">
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie
                          data={sectorData}
                          cx="50%"
                          cy="50%"
                          innerRadius={60}
                          outerRadius={90}
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
                <div className="h-64 flex items-center justify-center text-gray-500">
                  <p>No portfolio data available. Analyze your portfolio first.</p>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      ) : (
        <Card>
          <CardContent className="pt-6">
            <div className="text-center py-8">
              <p className="text-gray-600 mb-4">No portfolio metrics available. Analyze your portfolio first.</p>
              <Link to="/portfolio">
                <Button className="bg-blue-600 hover:bg-blue-700">
                  Go to Portfolio
                </Button>
              </Link>
            </div>
          </CardContent>
        </Card>
      )}

      {/* CTA */}
      <div className="flex justify-center pt-4">
        <Link to="/recommendations">
          <Button size="lg" className="bg-blue-600 hover:bg-blue-700">
            Get AI Recommendation
          </Button>
        </Link>
      </div>
    </div>
  );
}
