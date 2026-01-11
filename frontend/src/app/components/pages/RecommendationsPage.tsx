import { useState, useEffect } from 'react';
import { AlertCircle, TrendingUp, TrendingDown, Loader2 } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/card';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../ui/dialog';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../ui/table';
import { api, ApiError } from '../../api/client';
import { getUserId } from '../../utils/user';
import { loadPortfolioCache, savePortfolioCache, saveRecommendedPortfolioCache } from '../../utils/portfolioCache';

export function RecommendationsPage() {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [recommendation, setRecommendation] = useState<any>(null);
  const [holdings, setHoldings] = useState<Array<{ ticker: string; weight: number }>>([]);
  const [cashWeight, setCashWeight] = useState(0);
  const [showExportDialog, setShowExportDialog] = useState(false);

  useEffect(() => {
    // Load latest portfolio (backend snapshot preferred, local cache fallback)
    (async () => {
      const userId = getUserId();
      try {
        const history = await api.getPortfolioHistory(userId);
        const latest = history.snapshots?.[0];
        if (latest) {
          setHoldings(
            (latest.holdings || []).map((h: any) => ({
              ticker: String(h.ticker || '').toUpperCase(),
              weight: Math.round((Number(h.weight || 0) * 100) * 10) / 10, // decimal -> %
            }))
          );
          setCashWeight(Math.round((Number(latest.cash_weight || 0) * 100) * 10) / 10);
          return;
        }
      } catch {
        // ignore
      }

      const cached = loadPortfolioCache(userId);
      if (cached) {
        setHoldings(cached.holdings.map((h) => ({ ticker: h.ticker, weight: h.weightPct })));
        setCashWeight(cached.cashPct);
      }
    })();
  }, []);

  const handleGetRecommendation = async () => {
    try {
      setLoading(true);
      setError(null);
      setSuccess(false);
      const userId = getUserId();
      
      const validHoldings = holdings.filter(h => h.ticker.trim() && h.weight > 0);
      const rec = await api.getRecommendation(
        userId,
        validHoldings,
        cashWeight
      );
      
      setRecommendation(rec);
      
      // Save recommended portfolio to cache for comparison
      // Calculate recommended portfolio by applying actions to current
      const recommendedHoldingsMap = new Map<string, number>();
      
      // Start with current holdings
      validHoldings.forEach(h => {
        recommendedHoldingsMap.set(h.ticker, h.weight);
      });
      
      // Apply actions
      rec.plan.actions.forEach((action: any) => {
        const currentWeight = recommendedHoldingsMap.get(action.ticker) || 0;
        const newWeight = action.action === 'BUY' 
          ? currentWeight + (action.delta_weight * 100)
          : currentWeight + (action.delta_weight * 100); // delta_weight is negative for SELL
        if (newWeight > 0) {
          recommendedHoldingsMap.set(action.ticker, newWeight);
        } else {
          recommendedHoldingsMap.delete(action.ticker);
        }
      });
      
      // Convert to array format
      const recommendedHoldingsArray = Array.from(recommendedHoldingsMap.entries()).map(([ticker, weight]) => ({
        ticker,
        weightPct: weight,
      }));
      // Compute cash from the remainder to ensure total ~100%
      const totalEquity = recommendedHoldingsArray.reduce((sum, h) => sum + h.weightPct, 0);
      const recommendedCashPct = Math.max(0, Math.round((100 - totalEquity) * 10) / 10);
      
      // Save to cache
      saveRecommendedPortfolioCache(userId, {
        holdings: recommendedHoldingsArray,
        cashPct: recommendedCashPct,
        metrics: rec.metrics,
        updatedAt: new Date().toISOString(),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to get recommendation');
    } finally {
      setLoading(false);
    }
  };

  const handleAdoptChanges = async () => {
    if (!recommendation) return;

    try {
      setSaving(true);
      setError(null);
      const userId = getUserId();
      
      // Calculate the full recommended portfolio by applying all actions to current holdings
      const validHoldings = holdings
        .filter(h => h.ticker && h.ticker.trim() && h.weight > 0)
        .map(h => ({
          ticker: h.ticker.trim().toUpperCase().slice(0, 5), // Normalize ticker
          weight: h.weight,
        }))
        .filter(h => /^[A-Z0-9]+$/.test(h.ticker) && h.ticker.length >= 1 && h.ticker.length <= 5);
      
      const recommendedHoldingsMap = new Map<string, number>();
      
      // Start with current holdings (already normalized)
      validHoldings.forEach(h => {
        recommendedHoldingsMap.set(h.ticker, h.weight);
      });
      
      // Apply all actions (both BUY and SELL)
      recommendation.plan.actions.forEach((action: any) => {
        // Normalize ticker from action
        const normalizedTicker = String(action.ticker || '').trim().toUpperCase().slice(0, 5);
        if (!normalizedTicker || !/^[A-Z0-9]+$/.test(normalizedTicker) || normalizedTicker.length < 1) {
          console.warn('Skipping action with invalid ticker:', action.ticker);
          return;
        }
        
        const currentWeight = recommendedHoldingsMap.get(normalizedTicker) || 0;
        const newWeight = currentWeight + (action.delta_weight * 100); // delta_weight is already in decimal form
        if (newWeight > 0.01) { // Keep holdings with weight > 0.01%
          recommendedHoldingsMap.set(normalizedTicker, Math.round(newWeight * 10) / 10);
        } else {
          recommendedHoldingsMap.delete(normalizedTicker);
        }
      });
      
      // Convert to array format for API - validate and normalize
      let recommendedHoldingsArray = Array.from(recommendedHoldingsMap.entries())
        .map(([ticker, weight]) => ({
          ticker: ticker.trim().toUpperCase().slice(0, 5), // Normalize: uppercase, max 5 chars
          weight: Math.max(0, Math.min(100, weight)), // Clamp to 0-100%
        }))
        .filter(h => {
          // Filter out invalid holdings
          const tickerValid = h.ticker.length >= 1 && h.ticker.length <= 5 && /^[A-Z0-9]+$/.test(h.ticker);
          const weightValid = h.weight > 0.01; // Minimum 0.01% to avoid rounding issues
          return tickerValid && weightValid;
        });
      
      if (recommendedHoldingsArray.length === 0) {
        throw new Error('No valid holdings to save. Please check your recommendations.');
      }
      
      // Calculate total equity after applying actions
      let totalEquity = recommendedHoldingsArray.reduce((sum, h) => sum + h.weight, 0);
      
      // Normalize weights if total exceeds 100% (scale down proportionally)
      // This handles cases where actions would result in > 100% allocation
      if (totalEquity > 100.01) {
        const scaleFactor = 100 / totalEquity;
        console.log(`Normalizing portfolio weights: total was ${totalEquity.toFixed(2)}%, scaling by ${scaleFactor.toFixed(3)}`);
        recommendedHoldingsArray = recommendedHoldingsArray.map(h => ({
          ...h,
          weight: Math.round((h.weight * scaleFactor) * 10) / 10,
        }));
        totalEquity = recommendedHoldingsArray.reduce((sum, h) => sum + h.weight, 0);
      }
      
      // Calculate cash from the remainder to ensure total = 100%
      const recommendedCashPct = Math.max(0, Math.min(100, Math.round((100 - totalEquity) * 10) / 10));
      
      // Final validation: ensure total is reasonable (should be close to 100%)
      const finalTotal = totalEquity + recommendedCashPct;
      if (finalTotal < 95 || finalTotal > 105) {
        throw new Error(`Portfolio weights sum to ${finalTotal.toFixed(1)}%, which is outside the expected range (95-105%). Please review the recommendations.`);
      }
      
      // Debug log (can be removed in production)
      console.log('Adopting portfolio:', {
        holdingsCount: recommendedHoldingsArray.length,
        totalEquity: totalEquity.toFixed(2) + '%',
        cashPct: recommendedCashPct.toFixed(2) + '%',
        finalTotal: finalTotal.toFixed(2) + '%',
        holdings: recommendedHoldingsArray.map(h => `${h.ticker}: ${h.weight.toFixed(2)}%`),
      });
      
      // Save to backend as snapshot
      await api.saveSnapshot(userId, recommendedHoldingsArray, recommendedCashPct);
      
      // Update local cache so PortfolioPage shows the new portfolio
      savePortfolioCache(userId, {
        holdings: recommendedHoldingsArray.map(h => ({ ticker: h.ticker, weightPct: h.weight })),
        cashPct: recommendedCashPct,
        metrics: recommendation.metrics,
        updatedAt: new Date().toISOString(),
      });
      
      // Update page state to reflect the new portfolio
      setHoldings(recommendedHoldingsArray);
      setCashWeight(recommendedCashPct);
      
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (err) {
      let errorMessage = 'Failed to adopt changes';
      if (err instanceof ApiError) {
        // ApiError has detail property
        errorMessage = err.detail || err.error || err.message;
      } else if (err instanceof Error) {
        errorMessage = err.message;
      } else if (err && typeof err === 'object' && 'detail' in err) {
        // Handle API error with detail
        errorMessage = String((err as any).detail || (err as any).error || errorMessage);
      }
      setError(errorMessage);
      console.error('Error adopting changes:', err);
    } finally {
      setSaving(false);
    }
  };

  const recommendations = recommendation?.plan?.actions || [];
  const warnings = recommendation?.plan?.warnings || [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold text-gray-900">AI Recommendations</h1>
        <p className="text-gray-600 mt-1">Portfolio rebalancing plan based on your profile</p>
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

      {success && (
        <Card className="border-green-200 bg-green-50">
          <CardContent className="pt-6">
            <div className="flex items-center gap-2 text-green-800">
              <p>Snapshot saved successfully!</p>
            </div>
          </CardContent>
        </Card>
      )}

      {!recommendation && (
        <Card>
          <CardContent className="pt-6">
            <div className="text-center py-8">
              <p className="text-gray-600 mb-4">
                Get AI-powered portfolio recommendations based on your profile and current holdings.
              </p>
              <Button 
                onClick={handleGetRecommendation} 
                disabled={loading}
                className="bg-blue-600 hover:bg-blue-700"
              >
                {loading ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    Generating Recommendation...
                  </>
                ) : (
                  'Get Recommendation'
                )}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {recommendation && (
        <>
          {/* Recommendation Header */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>
                    {recommendation.operation_type === 'construct' ? 'Portfolio Construction' : 'Rebalance Operation'}
                  </CardTitle>
                  <p className="text-sm text-gray-600 mt-1">
                    Generated on {new Date().toLocaleDateString()}
                  </p>
                </div>
                <Badge className="bg-blue-600 text-white">Recommended</Badge>
              </div>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-3 gap-6">
                <div>
                  <p className="text-sm text-gray-600">Current Portfolio</p>
                  <p className="text-lg font-medium text-gray-900 mt-1">
                    {holdings.length} Holdings
                  </p>
                </div>
                <div>
                  <p className="text-sm text-gray-600">Recommended Portfolio</p>
                  <p className="text-lg font-medium text-gray-900 mt-1">
                    {recommendation.metrics.total_holdings} Holdings
                  </p>
                </div>
                <div>
                  <p className="text-sm text-gray-600">HHI Score</p>
                  <p className="text-lg font-medium text-green-600 mt-1">
                    {recommendation.metrics.herfindahl_index.toFixed(3)}
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

      {/* Action Table */}
      <Card>
        <CardHeader>
          <CardTitle>Recommended Actions</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-24">Action</TableHead>
                <TableHead>Ticker</TableHead>
                <TableHead className="text-right">Weight Change</TableHead>
                <TableHead>Notes</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {recommendations.length > 0 ? (
                recommendations.map((rec: any, index: number) => (
                  <TableRow key={index}>
                    <TableCell>
                      {rec.action === 'BUY' ? (
                        <Badge className="bg-green-600 text-white gap-1">
                          <TrendingUp className="w-3 h-3" />
                          BUY
                        </Badge>
                      ) : (
                        <Badge className="bg-red-600 text-white gap-1">
                          <TrendingDown className="w-3 h-3" />
                          SELL
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="font-mono font-medium">{rec.ticker}</TableCell>
                    <TableCell className="text-right">
                      <span className={rec.action === 'BUY' ? 'text-green-600' : 'text-red-600'}>
                        {rec.action === 'BUY' ? '+' : ''}{Math.round(rec.delta_weight * 100 * 10) / 10}%
                      </span>
                    </TableCell>
                    <TableCell className="text-sm text-gray-600">
                      {rec.notes || recommendation.plan.notes[index] || '-'}
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={4} className="text-center text-gray-500 py-8">
                    No actions recommended
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Warnings */}
      <Card className="border-amber-200 bg-amber-50">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-amber-900">
            <AlertCircle className="w-5 h-5" />
            Important Considerations
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="space-y-2">
            {warnings.map((warning, index) => (
              <li key={index} className="flex items-start gap-2 text-sm text-amber-900">
                <span className="mt-0.5">•</span>
                <span>{warning}</span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

          {/* AI Explanation */}
          <Card>
            <CardHeader>
              <CardTitle>AI Analysis & Rationale</CardTitle>
            </CardHeader>
            <CardContent className="prose prose-sm max-w-none">
              <div className="text-gray-700 leading-relaxed whitespace-pre-wrap">
                {recommendation.explanation || 'No explanation available'}
              </div>
            </CardContent>
          </Card>

          <div className="flex justify-end gap-3">
            <Button 
              variant="outline"
              onClick={() => setShowExportDialog(true)}
            >
              Export Changes
            </Button>
            <Button 
              className="bg-green-600 hover:bg-green-700"
              onClick={handleAdoptChanges}
              disabled={saving}
            >
              {saving ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Adopting Changes...
                </>
              ) : (
                'Adopt Changes'
              )}
            </Button>
          </div>

          {/* Export Changes Dialog */}
          <Dialog open={showExportDialog} onOpenChange={setShowExportDialog}>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Export Changes</DialogTitle>
                <DialogDescription>
                  This is a future feature that would connect to your trading platform and export the new portfolio there for you to update.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <Button 
                  variant="outline" 
                  onClick={() => setShowExportDialog(false)}
                >
                  Close
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </>
      )}
    </div>
  );
}
