import { useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/card';
import { Button } from '../ui/button';
import { Label } from '../ui/label';
import { Input } from '../ui/input';
import { Textarea } from '../ui/textarea';
import { Slider } from '../ui/slider';
import { Switch } from '../ui/switch';
import { Loader2, AlertCircle } from 'lucide-react';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../ui/select';
import { api, ApiError } from '../../api/client';
import { getUserId } from '../../utils/user';

export function ProfilePage() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [profile, setProfile] = useState<any>(null);
  const [onboardingText, setOnboardingText] = useState('');
  const [updateText, setUpdateText] = useState('');
  const [riskScore, setRiskScore] = useState([72]);
  const [optionsAllowed, setOptionsAllowed] = useState(false);
  const [leverageAllowed, setLeverageAllowed] = useState(false);

  const sectors = [
    'Technology',
    'Healthcare',
    'Finance',
    'Consumer Discretionary',
    'Consumer Staples',
    'Energy',
    'Utilities',
    'Real Estate',
    'Materials',
    'Industrials',
  ];

  useEffect(() => {
    loadProfile();
  }, []);

  const loadProfile = async () => {
    try {
      setLoading(true);
      setError(null);
      const userId = getUserId();
      const profileData = await api.getProfile(userId);
      setProfile(profileData);
      setRiskScore([profileData.risk_score]);
      setOptionsAllowed(profileData.constraints.options_allowed);
      setLeverageAllowed(profileData.constraints.leverage_allowed);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        // Profile doesn't exist yet - that's okay
        setProfile(null);
      } else {
        setError(err instanceof Error ? err.message : 'Failed to load profile');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleInitProfile = async () => {
    if (!onboardingText.trim() || onboardingText.length < 10) {
      setError('Please provide at least 10 characters of onboarding text');
      return;
    }

    try {
      setSaving(true);
      setError(null);
      setSuccess(false);
      const userId = getUserId();
      const profileData = await api.initProfile(userId, onboardingText);
      setProfile(profileData);
      setRiskScore([profileData.risk_score]);
      setOptionsAllowed(profileData.constraints.options_allowed);
      setLeverageAllowed(profileData.constraints.leverage_allowed);
      setOnboardingText('');
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to initialize profile');
    } finally {
      setSaving(false);
    }
  };

  const handleUpdateProfile = async () => {
    if (!updateText.trim() || updateText.length < 10) {
      setError('Please provide at least 10 characters of update text');
      return;
    }

    if (!profile) {
      setError('Profile not found. Please initialize profile first.');
      return;
    }

    try {
      setSaving(true);
      setError(null);
      setSuccess(false);
      const userId = getUserId();
      const profileData = await api.updateProfile(userId, updateText);
      setProfile(profileData);
      setRiskScore([profileData.risk_score]);
      setOptionsAllowed(profileData.constraints.options_allowed);
      setLeverageAllowed(profileData.constraints.leverage_allowed);
      setUpdateText('');
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update profile');
    } finally {
      setSaving(false);
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
        <h1 className="text-3xl font-semibold text-gray-900">Investor Profile</h1>
        <p className="text-gray-600 mt-1">Manage your investment preferences and constraints</p>
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
              <p>Profile saved successfully!</p>
            </div>
          </CardContent>
        </Card>
      )}

      {!profile ? (
        <Card>
          <CardHeader>
            <CardTitle>Initialize Profile</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="onboarding">Describe your investment profile</Label>
              <Textarea
                id="onboarding"
                placeholder="Example: I'm a 35-year-old investor looking for growth. I have a moderate risk tolerance and want to invest for the next 5 years. I prefer technology and healthcare sectors..."
                rows={6}
                value={onboardingText}
                onChange={(e) => setOnboardingText(e.target.value)}
                className="resize-none"
              />
              <p className="text-xs text-gray-500">
                Describe your investment goals, risk tolerance, time horizon, and preferences in plain English
              </p>
            </div>
            <Button 
              onClick={handleInitProfile} 
              disabled={saving || !onboardingText.trim()}
              className="bg-blue-600 hover:bg-blue-700"
            >
              {saving ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Initializing...
                </>
              ) : (
                'Initialize Profile'
              )}
            </Button>
          </CardContent>
        </Card>
      ) : (
        <>
          {/* Read-only Profile Summary */}
          <Card>
            <CardHeader>
              <CardTitle>Current Profile</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-3 gap-6 py-4">
                <div>
                  <p className="text-sm text-gray-600">Objective</p>
                  <p className="text-base font-medium text-gray-900 mt-1">
                    {profile.objective.type.charAt(0).toUpperCase() + profile.objective.type.slice(1)}
                  </p>
                </div>
                <div>
                  <p className="text-sm text-gray-600">Risk Score</p>
                  <p className="text-base font-medium text-gray-900 mt-1">{profile.risk_score}/100</p>
                </div>
                <div>
                  <p className="text-sm text-gray-600">Investment Horizon</p>
                  <p className="text-base font-medium text-gray-900 mt-1">{profile.horizon_months} months</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </>
      )}

      {profile && (
        <>
          {/* Editable Sections - Display only, changes via natural language */}
          <Card>
            <CardHeader>
              <CardTitle>Investment Objective & Risk</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="space-y-2">
                <Label htmlFor="objective">Investment Objective</Label>
                <Select value={profile.objective.type} disabled>
                  <SelectTrigger id="objective">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="growth">Growth</SelectItem>
                    <SelectItem value="income">Income</SelectItem>
                    <SelectItem value="balanced">Balanced</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="risk-score">Risk Score: {riskScore[0]}</Label>
                <Slider
                  id="risk-score"
                  min={0}
                  max={100}
                  step={1}
                  value={riskScore}
                  onValueChange={setRiskScore}
                  className="w-full"
                  disabled
                />
                <p className="text-xs text-gray-500">Higher scores indicate greater risk tolerance</p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="horizon">Investment Horizon (months)</Label>
                <Input id="horizon" type="number" value={profile.horizon_months} min="1" disabled />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Portfolio Constraints</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="grid grid-cols-2 gap-6">
                <div className="space-y-2">
                  <Label htmlFor="max-holdings">Maximum Holdings</Label>
                  <Input id="max-holdings" type="number" value={profile.constraints.max_holdings} min="1" disabled />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="max-position">Maximum Position (%)</Label>
                  <Input id="max-position" type="number" value={profile.constraints.max_position_pct} min="0" max="100" step="0.1" disabled />
                </div>
              </div>

              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label>Options Trading Allowed</Label>
                  <p className="text-xs text-gray-500">Enable options in portfolio construction</p>
                </div>
                <Switch checked={optionsAllowed} onCheckedChange={setOptionsAllowed} disabled />
              </div>

              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label>Leverage Allowed</Label>
                  <p className="text-xs text-gray-500">Allow leveraged positions</p>
                </div>
                <Switch checked={leverageAllowed} onCheckedChange={setLeverageAllowed} disabled />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Sector Preferences</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="space-y-2">
                <Label>Preferred Sectors</Label>
                <div className="grid grid-cols-2 gap-2 p-4 border border-gray-200 rounded-md">
                  {profile.preferences.sectors_like.length > 0 ? (
                    profile.preferences.sectors_like.map((sector: string) => (
                      <div key={sector} className="flex items-center gap-2 text-sm">
                        <span className="text-gray-700">{sector}</span>
                      </div>
                    ))
                  ) : (
                    <span className="text-sm text-gray-500">None specified</span>
                  )}
                </div>
              </div>

              <div className="space-y-2">
                <Label>Avoided Sectors</Label>
                <div className="grid grid-cols-2 gap-2 p-4 border border-gray-200 rounded-md">
                  {profile.preferences.sectors_avoid.length > 0 ? (
                    profile.preferences.sectors_avoid.map((sector: string) => (
                      <div key={sector} className="flex items-center gap-2 text-sm">
                        <span className="text-gray-700">{sector}</span>
                      </div>
                    ))
                  ) : (
                    <span className="text-sm text-gray-500">None specified</span>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>
        </>
      )}

      {profile && (
        <Card>
          <CardHeader>
            <CardTitle>Natural Language Update</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Textarea
              placeholder="Update your preferences in plain English... 
Example: I want to be more conservative and avoid tech stocks"
              rows={4}
              value={updateText}
              onChange={(e) => setUpdateText(e.target.value)}
              className="resize-none"
            />
            <p className="text-xs text-gray-500">
              Describe changes to your profile and the AI will update your settings accordingly
            </p>
            <Button 
              onClick={handleUpdateProfile} 
              disabled={saving || !updateText.trim()}
              className="bg-blue-600 hover:bg-blue-700"
            >
              {saving ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Updating...
                </>
              ) : (
                'Update Profile'
              )}
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
