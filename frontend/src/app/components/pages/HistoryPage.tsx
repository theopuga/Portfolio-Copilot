import { useState, useEffect } from 'react';
import { Eye, GitCompare, Calendar, Loader2, AlertCircle } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/card';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
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

export function HistoryPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [snapshots, setSnapshots] = useState<any[]>([]);
  const navigate = useNavigate();

  useEffect(() => {
    loadHistory();
  }, []);

  const loadHistory = async () => {
    try {
      setLoading(true);
      setError(null);
      const userId = getUserId();
      const history = await api.getPortfolioHistory(userId);
      setSnapshots(history.snapshots.map((snapshot, index) => ({
        id: index + 1,
        snapshot_id: snapshot.snapshot_id,
        date: new Date(snapshot.timestamp).toLocaleDateString(),
        time: new Date(snapshot.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        holdings: snapshot.holdings.length,
        riskScore: 0, // Would need profile to compute
        hhiScore: snapshot.metrics.herfindahl_index,
        topConcentration: Math.round(snapshot.metrics.top_1_weight * 100 * 10) / 10,
        type: index === 0 ? 'Current' : 'Snapshot',
        snapshot,
      })));
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setSnapshots([]);
      } else {
        setError(err instanceof Error ? err.message : 'Failed to load history');
      }
    } finally {
      setLoading(false);
    }
  };

  const [selectedSnapshots, setSelectedSnapshots] = useState<number[]>([]);

  const toggleSnapshot = (id: number) => {
    if (selectedSnapshots.includes(id)) {
      setSelectedSnapshots(selectedSnapshots.filter(sid => sid !== id));
    } else if (selectedSnapshots.length < 2) {
      setSelectedSnapshots([...selectedSnapshots, id]);
    }
  };

  const handleCompare = () => {
    if (selectedSnapshots.length === 2) {
      const selected = snapshots.filter(s => selectedSnapshots.includes(s.id));
      const snapshotIds = selected.map(s => s.snapshot_id);
      navigate(`/compare?snapshot1=${snapshotIds[0]}&snapshot2=${snapshotIds[1]}`);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold text-gray-900">Portfolio History</h1>
        <p className="text-gray-600 mt-1">Track and compare portfolio snapshots over time</p>
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

      {snapshots.length > 0 ? (
        <>
          {/* Timeline Stats */}
          <div className="grid grid-cols-4 gap-6">
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center">
                    <Calendar className="w-6 h-6 text-blue-600" />
                  </div>
                  <div>
                    <p className="text-sm text-gray-600">Total Snapshots</p>
                    <p className="text-2xl font-semibold text-gray-900">{snapshots.length}</p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="pt-6">
                <div>
                  <p className="text-sm text-gray-600 mb-1">Holdings Trend</p>
                  <p className="text-2xl font-semibold text-green-600">
                    {snapshots.length > 1 
                      ? `${snapshots[0].holdings - snapshots[snapshots.length - 1].holdings >= 0 ? '+' : ''}${snapshots[0].holdings - snapshots[snapshots.length - 1].holdings}`
                      : '0'}
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    {snapshots.length > 1 ? `Since ${snapshots[snapshots.length - 1].date}` : 'No comparison'}
                  </p>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="pt-6">
                <div>
                  <p className="text-sm text-gray-600 mb-1">Diversification</p>
                  <p className="text-2xl font-semibold text-green-600">
                    {snapshots.length > 1 && snapshots[0].hhiScore < snapshots[snapshots.length - 1].hhiScore ? 'Improved' : 'Stable'}
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    {snapshots.length > 1 
                      ? `HHI: ${snapshots[snapshots.length - 1].hhiScore.toFixed(3)} → ${snapshots[0].hhiScore.toFixed(3)}`
                      : `HHI: ${snapshots[0]?.hhiScore.toFixed(3) || 'N/A'}`}
                  </p>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="pt-6">
                <div>
                  <p className="text-sm text-gray-600 mb-1">Top Concentration</p>
                  <p className="text-2xl font-semibold text-gray-900">
                    {snapshots[0]?.topConcentration || 0}%
                  </p>
                  <p className="text-xs text-gray-500 mt-1">Current portfolio</p>
                </div>
              </CardContent>
            </Card>
          </div>
        </>
      ) : (
        <Card>
          <CardContent className="pt-6">
            <div className="text-center py-8">
              <p className="text-gray-600 mb-4">No portfolio snapshots found. Save a snapshot from the Portfolio page.</p>
            </div>
          </CardContent>
        </Card>
      )}

      {snapshots.length > 0 && (
        <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Portfolio Snapshots</CardTitle>
          {selectedSnapshots.length === 2 && (
            <Button 
              size="sm" 
              className="bg-blue-600 hover:bg-blue-700 gap-2"
              onClick={handleCompare}
            >
              <GitCompare className="w-4 h-4" />
              Compare Selected
            </Button>
          )}
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-12"></TableHead>
                <TableHead>Date</TableHead>
                <TableHead>Time</TableHead>
                <TableHead>Type</TableHead>
                <TableHead className="text-right">Holdings</TableHead>
                <TableHead className="text-right">Risk Score</TableHead>
                <TableHead className="text-right">HHI</TableHead>
                <TableHead className="text-right">Top %</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {snapshots.map((snapshot) => (
                <TableRow key={snapshot.id}>
                  <TableCell>
                    <input
                      type="checkbox"
                      className="rounded border-gray-300"
                      checked={selectedSnapshots.includes(snapshot.id)}
                      onChange={() => toggleSnapshot(snapshot.id)}
                      disabled={
                        selectedSnapshots.length >= 2 && !selectedSnapshots.includes(snapshot.id)
                      }
                    />
                  </TableCell>
                  <TableCell className="font-medium">{snapshot.date}</TableCell>
                  <TableCell className="text-sm text-gray-600">{snapshot.time}</TableCell>
                  <TableCell>
                    {snapshot.type === 'Current' && (
                      <Badge className="bg-green-600 text-white">Current</Badge>
                    )}
                    {snapshot.type === 'Initial' && (
                      <Badge variant="outline">Initial</Badge>
                    )}
                    {snapshot.type === 'Snapshot' && (
                      <Badge variant="secondary">Snapshot</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-right">{snapshot.holdings}</TableCell>
                  <TableCell className="text-right">-</TableCell>
                  <TableCell className="text-right">{snapshot.hhiScore.toFixed(3)}</TableCell>
                  <TableCell className="text-right">{snapshot.topConcentration}%</TableCell>
                  <TableCell className="text-right">
                    <Button 
                      variant="ghost" 
                      size="sm" 
                      className="gap-2"
                      onClick={() => navigate(`/portfolio?snapshot_id=${snapshot.snapshot_id}`)}
                    >
                      <Eye className="w-4 h-4" />
                      View
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          {selectedSnapshots.length === 1 && (
            <p className="text-sm text-gray-500 mt-4 text-center">
              Select one more snapshot to compare
            </p>
          )}
        </CardContent>
      </Card>
      )}
    </div>
  );
}
